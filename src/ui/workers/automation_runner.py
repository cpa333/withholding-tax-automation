"""Automation Runner — 페이즈 실행 오케스트레이터

AsyncWorker를 상속하여 BatchEngine + Workflow 어댑터를 연결.
QThread 내부에서 Playwright + BatchEngine을 실행하고
Qt Signal로 UI에 진행 상황을 방출.
"""

import asyncio
import os
import random
import traceback

from src.config import DB_PATH, PORTAL_URLS
from src.ui.workers.async_bridge import AsyncWorker

# 브라우저가 확실히 종료된 패턴 (즉시 disconnect 처리)
_BROWSER_DISCONNECT_PATTERNS = (
    "Target page, context or browser has been closed",
    "Target closed",
    "Browser closed",
    "Connection closed",
    "Browser has been disconnected",
    "net::ERR_CONNECTION_REFUSED",
    "No target found",
)

# 페이지 전환 중 발생할 수 있는 일시적 에러 패턴
# (실제 브라우저 종료가 아닐 수 있으므로 _is_page_alive로 확인 후 판단)
_BROWSER_TRANSIENT_PATTERNS = (
    "Execution context was destroyed",
    "Frame was detached",
    "Page navigated",
    "Session expired",
)


def _is_browser_disconnected(error: Exception) -> bool:
    """예외가 브라우저 연결 끊김인지 판별

    하드 disconnect 패턴만 True 반환.
    일시적 에러 패턴은 _is_page_alive()로 별도 확인 필요.
    """
    if isinstance(error, _BrowserClosedError):
        return True
    msg = str(error).lower()
    return any(p.lower() in msg for p in _BROWSER_DISCONNECT_PATTERNS)


def _is_transient_error(error: Exception) -> bool:
    """예외가 페이지 전환 중 일시적 에러인지 판별"""
    msg = str(error).lower()
    return any(p.lower() in msg for p in _BROWSER_TRANSIENT_PATTERNS)


class _BrowserClosedError(Exception):
    """브라우저가 사용자에 의해 종료되었을 때 발생하는 내부 예외"""
    pass


class AutomationRunner(AsyncWorker):
    """BatchEngine 기반 페이즈 실행기"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._db_path = DB_PATH
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._current_portal = None
        self._last_phase_id = 1  # 가장 최근 실행 페이즈 추적

    async def _async_main(self):
        """비동기 메인 — Playwright 초기화 후 명령 대기"""
        from playwright.async_api import async_playwright

        self.log_message.emit("자동화 러너 초기화 중...")

        async with async_playwright() as p:
            self._playwright = p
            self.log_message.emit("Playwright 준비 완료. 명령 대기 중...")

            while not self._stop_event.is_set():
                # 일시정지 확인
                if not self._pause_event.is_set():
                    await asyncio.sleep(0.5)
                    continue

                # 명령 큐 확인
                try:
                    cmd = self._command_queue.get_nowait()
                except Exception:
                    await asyncio.sleep(0.1)
                    continue

                if cmd.get("type") == "stop":
                    break

                try:
                    if cmd.get("type") == "run_phase":
                        await self._handle_run_phase(cmd)
                    elif cmd.get("type") == "refresh_clients":
                        await self._handle_refresh_clients(cmd)
                    elif cmd.get("type") == "run_selected_clients":
                        await self._handle_run_selected_clients(cmd)
                except Exception as e:
                    # 하드 disconnect → 즉시 복구/종료 처리
                    if _is_browser_disconnected(e):
                        await self._handle_browser_disconnect(cmd, e)
                    # 일시적 에러 → _is_page_alive로 실제 상태 확인
                    elif _is_transient_error(e):
                        if not await self._is_page_alive():
                            await self._handle_browser_disconnect(cmd, e)
                        else:
                            self.log_message.emit(f"일시적 오류 (복구됨): {e}")
                    # 기타 에러 → 브라우저 상태 확인 후 처리
                    elif not await self._is_page_alive():
                        await self._handle_browser_disconnect(cmd, e)
                    else:
                        tb = traceback.format_exc()
                        self.log_message.emit(f"실행 오류: {e}\n{tb}")
                        self.error_occurred.emit(str(e))
                        await self._reset_after_error(cmd)

        self.log_message.emit("자동화 러너 종료됨")

    async def _handle_run_phase(self, cmd: dict):
        """run_phase 명령 처리"""
        phase_id = cmd.get("phase_id", 0)
        self._last_phase_id = phase_id
        kwargs = {k: v for k, v in cmd.items() if k not in ("type", "phase_id")}

        from src.workflows.registry import get_phase_info, get_workflow

        info = get_phase_info(phase_id)
        if not info:
            self.log_message.emit(f"알 수 없는 페이즈: {phase_id}")
            return

        portal = info["portal"]
        display_name = info["display_name"]
        self.log_message.emit(f"[{display_name}] 실행 시작")
        self.phase_changed.emit(phase_id, "running")

        if self._stop_event.is_set():
            self.phase_changed.emit(phase_id, "failed")
            return

        # Chrome 실행 + 로그인 (기존 세션 재사용 우선)
        reused = await self._try_reuse_browser(portal)

        if not reused:
            if not await self._ensure_browser(portal):
                self.phase_changed.emit(phase_id, "failed")
                self.error_occurred.emit("Chrome 연결 실패")
                return

            if self._stop_event.is_set():
                self.phase_changed.emit(phase_id, "failed")
                return

        # 포털별 로그인 대기 (세션 재사용 시에도 로그아웃 상태일 수 있으므로 항상 확인)
        if not await self._wait_for_login(portal):
            if self._stop_event.is_set():
                self.log_message.emit("[사용자 중단] 로그인 대기 중단")
            else:
                self.phase_changed.emit(phase_id, "failed")
                self.error_occurred.emit("로그인 실패 또는 시간 초과")
            return

        # 로그인 후 페이지 재연결 (인증 과정에서 탭이 바뀔 수 있음)
        await self._reconnect_page(portal)

        # Phase 1은 "새로 가져오기" 버튼으로만 실행
        if phase_id == 1:
            self.log_message.emit("수임처 리스트는 '새로 가져오기' 버튼을 사용하세요")
            self.phase_changed.emit(1, "completed")
            return

        # Phase 2+: BatchEngine으로 배치 실행
        from src.batch.engine import BatchEngine
        from src.batch.models import Client, BatchStatus, biz_to_mgmt_no

        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)

        # 이전 배치 정리
        self._reset_batch(self._db_path, portal, phase_id)

        engine = BatchEngine(self._db_path, portal)
        engine.initialize()

        try:
            # WEHAGO 수임처를 현재 포털에 자동 복사
            wehago_clients = engine.client_repo.list_active("wehago")
            if wehago_clients:
                existing = engine.client_repo.list_active(portal)
                existing_names = {c.name for c in existing}
                for c in wehago_clients:
                    if c.name not in existing_names:
                        engine.client_repo.upsert(Client(
                            name=c.name,
                            portal=portal,
                            business_number=c.business_number,
                            enabled=True,
                        ))
                self.log_message.emit(f"  WEHAGO → {portal}: {len(wehago_clients)}개 수임처 동기화")

            batch = engine.prepare_batch(
                year=kwargs.get("year"),
                month=kwargs.get("month"),
            )

            # 워크플로우 실행
            workflow = get_workflow(phase_id)
            if not workflow:
                self.log_message.emit(f"워크플로우를 찾을 수 없음: phase {phase_id}")
                return

            workflow_func = workflow.as_workflow_func(**kwargs)

            # 배치를 running으로
            engine.batch_repo.update_status(batch.id, BatchStatus.RUNNING)

            try:
                # 수임처별 루프 — 일시정지/정지/브라우저 종료 체크
                from src.utils.human import human_break
                clients_done = 0
                last_break_at = 0
                break_gap = random.randint(5, 8)

                while not self._stop_event.is_set():
                    # 일시정지 대기
                    while not self._pause_event.is_set() and not self._stop_event.is_set():
                        await asyncio.sleep(0.5)

                    if self._stop_event.is_set():
                        engine.batch_repo.update_status(batch.id, BatchStatus.PAUSED)
                        self.log_message.emit("[사용자 중단] 배치 일시정지됨")
                        break

                    # 브라우저 종료 확인
                    if not await self._is_page_alive():
                        self.log_message.emit("브라우저가 닫혀서 세션이 중단되었습니다.")
                        self.log_message.emit("다시 시작하려면 '시작' 버튼을 눌러주세요.")
                        engine.batch_repo.update_status(batch.id, BatchStatus.PAUSED)
                        break

                    job = engine.job_repo.get_next_pending(batch.id)
                    if not job:
                        break

                    # 직접 잡 실행 — 브라우저 종료 에러는 _run_job이 잡아주지만,
                    # 에러 메시지가 무서운 traceback으로 표시되지 않도록 여기서 선제 감지
                    engine.job_repo.mark_running(job.id)

                    mgmt_no = ""
                    if job.client_id:
                        client = engine.client_repo.get(job.client_id)
                        if client and client.business_number:
                            mgmt_no = biz_to_mgmt_no(client.business_number)

                    try:
                        success = await workflow_func(
                            self._page, self._context, job, engine.state,
                            management_number=mgmt_no,
                        )
                        if success:
                            engine.job_repo.mark_completed(job.id)
                        else:
                            engine.job_repo.mark_failed(job.id, "워크플로우 False 반환")
                    except Exception as e:
                        # 브라우저 종료 → 즉시 루프 중단
                        if not await self._is_page_alive():
                            engine.job_repo.mark_failed(job.id, "브라우저 종료")
                            self.log_message.emit("브라우저가 닫혀서 세션이 중단되었습니다.")
                            self.log_message.emit("다시 시작하려면 '시작' 버튼을 눌러주세요.")
                            engine.batch_repo.update_status(batch.id, BatchStatus.PAUSED)
                            break
                        engine.job_repo.mark_failed(job.id, f"{type(e).__name__}: {e}")

                    self._emit_progress(engine, batch.id, phase_id)

                    # 수임처 간 무작위 휴식 (탐지 패턴 방지)
                    clients_done += 1
                    if (clients_done - last_break_at) >= break_gap:
                        next_peek = engine.job_repo.get_next_pending(batch.id)
                        if next_peek is not None:
                            took = await human_break(
                                check_stop=lambda: self._stop_event.is_set(),
                                log_fn=lambda m: self.log_message.emit(m),
                            )
                            if not took:
                                engine.batch_repo.update_status(batch.id, BatchStatus.PAUSED)
                                break
                            last_break_at = clients_done
                            break_gap = random.randint(5, 8)
            except asyncio.CancelledError:
                engine.batch_repo.update_status(batch.id, BatchStatus.PAUSED)
                self.log_message.emit("[작업 취소됨]")

            # 완료 확인
            if not self._stop_event.is_set():
                counts = engine.job_repo.count_by_status(batch.id)
                all_done = counts.get("pending", 0) == 0 and counts.get("running", 0) == 0
                if all_done:
                    engine.batch_repo.update_status(batch.id, BatchStatus.COMPLETED)

            # 최종 상태
            batch = engine.batch_repo.get(batch.id)
            from src.batch.models import BatchStatus as BS
            if batch.status == BS.COMPLETED:
                self.phase_changed.emit(phase_id, "completed")
            elif batch.status == BS.PAUSED:
                self.phase_changed.emit(phase_id, "paused")
            else:
                self.phase_changed.emit(phase_id, "failed")

            self._emit_progress(engine, batch.id, phase_id)

        finally:
            engine.close()

    async def _handle_refresh_clients(self, cmd: dict = None):
        """새로 가져오기: taxagent에서 수임처명 + 사업자등록번호 수집 후 DB 업데이트"""
        if cmd is None:
            cmd = {}
        self._last_phase_id = 1
        from src.automation.wehago._common import (
            WEHAGO_TAXAGENT_URL, dismiss_dialogs,
            get_clients_with_biz_from_taxagent, search_clients_by_name,
        )
        from src.batch.db import BatchDB, ClientRepository
        from src.batch.models import Client

        name_filter = cmd.get("name", "")
        if name_filter:
            self.log_message.emit(f"[수임처 새로 가져오기] 시작... (담당자: {name_filter})")
        else:
            self.log_message.emit("[수임처 새로 가져오기] 시작...")

        if self._stop_event.is_set():
            return

        # 브라우저 세션 재사용 시도 (기존 WEHAGO 세션이 살아있으면 재사용)
        reused = await self._try_reuse_browser("wehago")

        if not reused:
            if not await self._ensure_browser("wehago"):
                self.phase_changed.emit(1, "failed")
                self.error_occurred.emit("Chrome 연결 실패")
                return

            if self._stop_event.is_set():
                return

            # 로그인 대기
            if not await self._wait_for_login("wehago"):
                if not self._stop_event.is_set():
                    self.error_occurred.emit("WEHAGO 로그인 실패 또는 시간 초과")
                return

            # 로그인 후 페이지 재연결
            await self._reconnect_page("wehago")

        page = self._page
        try:
            # 수임처관리 페이지로 이동
            self.log_message.emit("수임처관리 페이지로 이동...")
            await page.goto(WEHAGO_TAXAGENT_URL, wait_until="domcontentloaded", timeout=30000)
            await dismiss_dialogs(page)

            # 페이지 건강성 확인 (크래시/세션 만료 감지)
            if not await self._is_page_alive():
                raise _BrowserClosedError()

            # 담당자 이름 필터링 (이름이 있으면 검색 입력 → 조회 버튼 클릭)
            if name_filter:
                self.log_message.emit(f"담당자 '{name_filter}'으로 필터링 조회...")
                await search_clients_by_name(page, name_filter)
                await asyncio.sleep(1)

            try:
                await page.wait_for_selector(
                    'ul.acceptance_list li span.company_name_text',
                    timeout=15000,
                )
            except Exception:
                self.log_message.emit("리스트 로딩 재시도...")
                await dismiss_dialogs(page)
                await page.wait_for_selector(
                    'ul.acceptance_list li span.company_name_text',
                    timeout=20000,
                )

            # 카드 클릭하며 이름+사업자번호 수집
            clients_data = await get_clients_with_biz_from_taxagent(page)
            clients_data = [c for c in clients_data if c["name"]]

            self.log_message.emit(f"수임처 {len(clients_data)}건 조회 완료")

            # DB 교체
            os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
            with BatchDB(self._db_path) as db:
                conn = db.conn
                conn.execute("DELETE FROM steps")
                conn.execute("DELETE FROM jobs")
                conn.execute("DELETE FROM batches")
                conn.execute("DELETE FROM clients")

                client_repo = ClientRepository(db)
                for c in clients_data:
                    client_repo.upsert(Client(
                        name=c["name"],
                        portal="wehago",
                        business_number=c["business_number"],
                        enabled=True,
                    ))

            self.log_message.emit(f"수임처 새로 가져오기 완료: {len(clients_data)}건")
            self.phase_changed.emit(1, "completed")

        except _BrowserClosedError:
            raise
        except Exception as e:
            # Playwright 에러도 브라우저 종료일 수 있으므로 확인
            if _is_browser_disconnected(e) or not await self._is_page_alive():
                raise
            self.log_message.emit(f"수임처 조회 실패: {e}")
            self.error_occurred.emit(f"수임처 조회 실패: {e}")

    async def _handle_browser_disconnect(self, cmd: dict, error: Exception):
        """브라우저 연결 끊김 처리 — CDP 재연결 시도 후 실패 시 세션 초기화

        1) CDP 포트가 살아있으면 Playwright 재연결 시도 (Chrome kill 없이 복구)
        2) 재연결 실패 또는 CDP 포트 불응답 → Chrome 종료 + 세션 초기화
        """
        from src.utils.chrome_cdp import check_cdp_available, CDP_URL

        phase_id = cmd.get("phase_id", self._last_phase_id)

        # 복구 시도: CDP 포트가 살아있으면 Playwright 재연결
        recovered = False
        if await asyncio.to_thread(check_cdp_available):
            try:
                browser = await self._playwright.chromium.connect_over_cdp(CDP_URL)
                context = browser.contexts[0]
                page = context.pages[0] if context.pages else await context.new_page()
                # 재연결된 페이지가 실제로 응답하는지 확인
                await asyncio.wait_for(page.evaluate("1"), timeout=5)
                self._browser = browser
                self._context = context
                self._page = page
                self.log_message.emit("브라우저 재연결 성공 (복구)")
                recovered = True
            except Exception:
                pass

        if not recovered:
            self.log_message.emit("브라우저가 닫혀서 세션이 중단되었습니다.")
            self.log_message.emit("다시 시작하려면 '시작' 버튼을 눌러주세요.")
            await self._disconnect_browser()
            self.phase_changed.emit(phase_id, "failed")
            self.error_occurred.emit("브라우저가 닫혀서 세션이 중단되었습니다. 다시 시작하려면 시작 버튼을 눌러주세요.")

    async def _reset_after_error(self, cmd: dict):
        """일반 오류 후 상태 초기화"""
        await self._disconnect_browser()

        phase_id = cmd.get("phase_id", self._last_phase_id)
        self.phase_changed.emit(phase_id, "failed")

    async def _disconnect_browser(self):
        """Playwright 브라우저 연결 정상 종료 + Chrome 프로세스 종료

        누적 좀비 연결 방지를 위해 반드시 호출 필요.
        """
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
        from src.utils.chrome_cdp import kill_chrome
        kill_chrome()
        self._browser = None
        self._context = None
        self._page = None
        self._current_portal = None

    def cleanup_session(self):
        """정지 버튼 클릭 시 호출 — Chrome 종료 + 세션 초기화"""
        from src.utils.chrome_cdp import kill_chrome
        kill_chrome()
        self._browser = None
        self._context = None
        self._page = None
        self._current_portal = None
        self.log_message.emit("[세션 종료] Chrome 프로세스 종료 + 세션 초기화됨")

    def start_selected_clients(self, phase_id: int,
                               client_infos: list[dict],
                               year: int | None = None,
                               month: int | None = None,
                               **kwargs):
        """선택건 실행: 여러 수임처에 대해 순차 자동화 실행"""
        self._ensure_running()
        cmd = {
            "type": "run_selected_clients",
            "phase_id": phase_id,
            "client_infos": client_infos,
            "year": year,
            "month": month,
            **kwargs,
        }
        self._command_queue.put_nowait(cmd)

    async def _handle_run_selected_clients(self, cmd: dict):
        """선택건 실행 — 여러 수임처를 순차 실행 (BatchEngine 없이)"""
        phase_id = cmd.get("phase_id", 0)
        self._last_phase_id = phase_id
        client_infos = cmd.get("client_infos", [])
        year = cmd.get("year")
        month = cmd.get("month")
        extra_kwargs = {k: v for k, v in cmd.items()
                        if k not in ("type", "phase_id", "client_infos", "year", "month")}
        total = len(client_infos)

        from src.workflows.registry import get_phase_info, get_workflow

        info = get_phase_info(phase_id)
        if not info:
            self.log_message.emit(f"알 수 없는 페이즈: {phase_id}")
            return

        portal = info["portal"]
        display_name = info["display_name"]
        self.log_message.emit(f"[{display_name}] 선택건 실행: {total}건")
        self.phase_changed.emit(phase_id, "running")

        if self._stop_event.is_set():
            self.phase_changed.emit(phase_id, "failed")
            return

        # 브라우저 세션 재사용 시도
        reused = await self._try_reuse_browser(portal)

        if not reused:
            if not await self._ensure_browser(portal):
                self.phase_changed.emit(phase_id, "failed")
                self.error_occurred.emit("Chrome 연결 실패")
                return

            if self._stop_event.is_set():
                self.phase_changed.emit(phase_id, "failed")
                return

            if not await self._wait_for_login(portal):
                if self._stop_event.is_set():
                    self.log_message.emit("[사용자 중단] 로그인 대기 중단")
                else:
                    self.phase_changed.emit(phase_id, "failed")
                    self.error_occurred.emit("로그인 실패 또는 시간 초과")
                return

        await self._reconnect_page(portal)

        workflow = get_workflow(phase_id)
        if not workflow:
            self.log_message.emit(f"워크플로우를 찾을 수 없음: phase {phase_id}")
            return

        results = []
        from src.utils.human import human_break
        sel_break_gap = random.randint(5, 8)
        sel_last_break = 0

        for i, client_info in enumerate(client_infos):
            client_name = client_info["name"]
            management_number = client_info.get("management_number", "")

            if self._stop_event.is_set():
                self.log_message.emit(f"[{display_name}] 사용자 중단 ({i}/{total} 완료)")
                break

            if not await self._is_page_alive():
                self.log_message.emit("브라우저가 종료되어 실행을 중단합니다.")
                results.append({"name": client_name, "success": False, "error": "브라우저 종료"})
                break

            self.log_message.emit(f"[{display_name}] ({i+1}/{total}) {client_name} 처리 중...")

            from src.batch.state import NoopStateManager
            state = NoopStateManager()

            try:
                success = await workflow.run_single(
                    self._page, self._context,
                    client_name, job_id=0,
                    state=state,
                    management_number=management_number,
                    year=year,
                    month=month,
                    **extra_kwargs,
                )
                if success:
                    self.log_message.emit(f"[{display_name}] ({i+1}/{total}) {client_name} 완료")
                    results.append({"name": client_name, "success": True})
                else:
                    self.log_message.emit(f"[{display_name}] ({i+1}/{total}) {client_name} 실패")
                    results.append({"name": client_name, "success": False, "error": "실패"})

                    if not await self._is_page_alive():
                        self.log_message.emit("브라우저가 종료되어 실행을 중단합니다.")
                        break
            except Exception as e:
                self.log_message.emit(f"[{display_name}] ({i+1}/{total}) {client_name} 오류: {e}")
                results.append({"name": client_name, "success": False, "error": str(e)})

                if not await self._is_page_alive():
                    self.log_message.emit("브라우저가 종료되어 실행을 중단합니다.")
                    break

            # 수임처 간 무작위 휴식 (탐지 패턴 방지)
            if (i + 1 < total and (i + 1 - sel_last_break) >= sel_break_gap):
                took = await human_break(
                    check_stop=lambda: self._stop_event.is_set(),
                    log_fn=lambda m: self.log_message.emit(m),
                )
                if not took:
                    break
                sel_last_break = i + 1
                sel_break_gap = random.randint(5, 8)

        # 완료 요약
        succeeded = sum(1 for r in results if r["success"])
        failed_list = [r for r in results if not r["success"]]
        self.log_message.emit(
            f"[{display_name}] 선택건 실행 완료: 성공 {succeeded}건"
            + (f", 실패 {len(failed_list)}건" if failed_list else "")
        )
        if failed_list:
            names = [r["name"] for r in failed_list]
            self.log_message.emit(f"  실패: {', '.join(names)}")

        # 진행 상황 emit (사이드바 업데이트)
        self.batch_progress.emit({
            "phase_id": phase_id,
            "jobs": [
                {
                    "name": r["name"],
                    "status": "completed" if r["success"] else "failed",
                    "current_step": "",
                    "duration": None,
                    "error": r.get("error", ""),
                }
                for r in results
            ],
            "failed": failed_list,
        })

        if succeeded == total:
            self.phase_changed.emit(phase_id, "completed")
        elif succeeded > 0:
            self.phase_changed.emit(phase_id, "completed")
        else:
            self.phase_changed.emit(phase_id, "failed")

    def _reset_batch(self, db_path: str, portal: str, phase_id: int):
        """이전 배치/잡/단계를 모두 삭제하여 깨끗한 상태로 초기화"""
        if not os.path.exists(db_path):
            return

        from src.batch.db import BatchDB

        with BatchDB(db_path) as db:
            conn = db.conn
            if phase_id == 1:
                conn.execute("DELETE FROM steps")
                conn.execute("DELETE FROM jobs")
                conn.execute("DELETE FROM batches")
                conn.execute("DELETE FROM clients")
            else:
                conn.execute(
                    "DELETE FROM steps WHERE job_id IN "
                    "(SELECT j.id FROM jobs j JOIN batches b ON j.batch_id = b.id WHERE b.portal = ?)",
                    (portal,),
                )
                conn.execute(
                    "DELETE FROM jobs WHERE batch_id IN "
                    "(SELECT id FROM batches WHERE portal = ?)",
                    (portal,),
                )
                conn.execute(
                    "DELETE FROM batches WHERE portal = ?",
                    (portal,),
                )

    async def _ensure_browser(self, portal: str) -> bool:
        """포털에 맞는 Chrome 인스턴스 실행"""
        from src.utils.chrome_cdp import launch_chrome, kill_chrome, CDP_URL

        if self._stop_event.is_set():
            return False

        # 기존 Playwright 연결 정리 (좀비 연결 방지)
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
            self._context = None
            self._page = None

        # 포털별 URL
        url = PORTAL_URLS.get(portal, PORTAL_URLS["wehago"])

        # 포털이 변경되면 Chrome 재시작
        if portal != getattr(self, '_current_portal', None):
            if self._current_portal is not None:
                self.log_message.emit(f"포털 전환: {self._current_portal} → {portal}")
                kill_chrome()
                await asyncio.sleep(2)
            self._current_portal = portal

        # Chrome 실행 (force=True로 항상 새로 실행)
        result = launch_chrome(url, force=True)
        if not result["success"]:
            self.log_message.emit(f"Chrome 실행 실패: {result.get('error', '알 수 없음')}")
            return False

        await asyncio.sleep(2)

        # Playwright 연결
        try:
            browser = await self._playwright.chromium.connect_over_cdp(CDP_URL)
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else await context.new_page()
            self._browser = browser
            self._context = context
            self._page = page
            self.log_message.emit("Chrome 연결 완료")
            return True
        except Exception as e:
            self.log_message.emit(f"Playwright 연결 실패: {e}")
            return False

    async def _try_reuse_browser(self, portal: str) -> bool:
        """기존 브라우저 세션 재사용 가능 여부 확인 (단건실행 전용)

        조건: browser 객체 존재 + 같은 포털 + 페이지 응답 정상
        """
        if self._browser is None:
            return False
        if self._current_portal != portal:
            self.log_message.emit(f"포털 변경 ({self._current_portal} → {portal}), 브라우저 재시작")
            return False
        if not await self._is_page_alive():
            self.log_message.emit("기존 브라우저 세션이 종료됨, 재연결 필요")
            return False
        self.log_message.emit("기존 브라우저 세션 재사용")
        return True

    async def _reconnect_page(self, portal: str):
        """로그인 등으로 페이지가 바뀐 후 Playwright 연결 재확립"""
        from src.utils.chrome_cdp import CDP_URL

        portal_host = {
            "nhis_edi": "edi.nhis",
            "nps_edi": "edi.nps",
            "hometax": "hometax.go.kr",
            "wehago": "wehago.com",
        }.get(portal, "")

        try:
            # 기존 페이지가 유효한지 확인
            url = self._page.url
            if url:
                return  # 아직 유효함
        except Exception:
            pass

        self.log_message.emit("페이지 재연결 중...")

        try:
            browser = await self._playwright.chromium.connect_over_cdp(CDP_URL)
            context = browser.contexts[0]

            # 포털에 맞는 탭 찾기
            target_page = None
            for pg in context.pages:
                try:
                    if portal_host in pg.url:
                        target_page = pg
                        break
                except Exception:
                    continue

            if not target_page:
                target_page = context.pages[0] if context.pages else await context.new_page()

            self._browser = browser
            self._context = context
            self._page = target_page
            self.log_message.emit(f"페이지 재연결 완료: {target_page.url[:60]}")
        except Exception as e:
            self.log_message.emit(f"페이지 재연결 실패: {e}")

    async def _is_page_alive(self) -> bool:
        """현재 페이지가 유효한지 (브라우저가 살아있는지) 확인

        page.evaluate()로 실제 브라우저 통신을 시도하되
        5초 타임아웃 + 1회 재시도로 페이지 전환 중 false negative 방지.
        """
        for attempt in range(2):
            try:
                if self._page is None:
                    return False
                await asyncio.wait_for(self._page.evaluate("1"), timeout=5)
                return True
            except Exception:
                if attempt == 0:
                    await asyncio.sleep(1)  # 페이지 전환 대기
                continue
        return False

    async def _check_browser_alive(self):
        """브라우저가 닫혀있으면 예외 발생"""
        if not await self._is_page_alive():
            raise _BrowserClosedError()

    async def _check_browser_alive_soft(self):
        """로그인 대기 중 브라우저 체크 — 페이지 전환/로딩 오류는 무시

        _check_browser_alive와 달리, 현재 페이지가 응답하지 않아도
        다른 탭 중 하나라도 살아있으면 브라우저가 살아있는 것으로 간주.
        """
        if await self._is_page_alive():
            return
        for pg in self._context.pages:
            try:
                await asyncio.wait_for(pg.evaluate("1"), timeout=3)
                return
            except Exception:
                continue
        raise _BrowserClosedError()

    async def _wait_for_login(self, portal: str) -> bool:
        """포털별 로그인 완료 대기. 브라우저 종료 / 정지 시 즉시 예외 발생."""
        handler = {
            "nhis_edi": self._wait_for_login_nhis,
            "nps_edi": self._wait_for_login_nps,
            "hometax": self._wait_for_login_hometax,
            "wehago": self._wait_for_login_wehago,
        }.get(portal)
        return await handler() if handler else True

    async def _wait_for_login_nhis(self) -> bool:
        """국민건강보험 EDI 로그인 대기"""
        import asyncio
        from src.utils.chrome_cdp import check_cdp_available

        self.log_message.emit("[국민건강보험 EDI] 로그인 대기 중... 공동인증서로 로그인해 주세요.")

        for i in range(180):
            if self._stop_event.is_set():
                return False
            await asyncio.sleep(5)

            cdp_ok = await asyncio.to_thread(check_cdp_available)
            if not cdp_ok:
                raise _BrowserClosedError()

            try:
                for pg in list(self._context.pages):
                    try:
                        if "retrieveMain" in pg.url:
                            has_info = await pg.evaluate("""() => {
                                const text = document.body.innerText;
                                return text.includes('사업장 관리번호') || text.includes('신규문서');
                            }""")
                            if has_info:
                                self._page = pg
                                self.log_message.emit("국민건강보험 EDI 로그인 확인됨.")
                                break
                    except Exception:
                        continue
                else:
                    if i % 6 == 5:
                        self.log_message.emit(f"  로그인 대기 중... ({(i + 1) * 5}초)")
                    continue
                break  # found
            except _BrowserClosedError:
                raise
            except Exception:
                pass
        else:
            self.log_message.emit("국민건강보험 EDI 로그인 대기 시간 초과")
            return False

        await self._reconnect_page("nhis_edi")
        self.log_message.emit("팝업 정리 및 페이지 안정화 대기...")
        await asyncio.sleep(3)
        return True

    async def _wait_for_login_nps(self) -> bool:
        """국민연금 EDI 로그인 대기"""
        from src.automation.nps._common import wait_for_nexacro_ready

        self.log_message.emit("[국민연금 EDI] 로그인 대기 중... 공동인증서로 로그인해 주세요.")

        for i in range(180):
            if self._stop_event.is_set():
                return False
            await asyncio.sleep(5)
            await self._check_browser_alive_soft()
            try:
                for pg in self._context.pages:
                    try:
                        if "nexacro" in pg.url:
                            self._page = pg
                            self.log_message.emit("국민연금 EDI 로그인 확인됨.")
                            break
                    except Exception:
                        continue
                else:
                    if i % 6 == 5:
                        self.log_message.emit(f"  로그인 대기 중... ({(i + 1) * 5}초)")
                    continue
                break
            except _BrowserClosedError:
                raise
            except Exception:
                pass
        else:
            self.log_message.emit("국민연금 EDI 로그인 대기 시간 초과")
            return False

        await self._reconnect_page("nps_edi")
        self.log_message.emit("Nexacro 로딩 대기...")
        if not await wait_for_nexacro_ready(self._page):
            self.error_occurred.emit("Nexacro 프레임워크 로딩 실패")
            return False
        return True

    async def _wait_for_login_hometax(self) -> bool:
        """홈택스 로그인 대기"""
        self.log_message.emit("[홈택스] 로그인 대기 중... 인증서로 로그인해 주세요.")
        for i in range(180):
            if self._stop_event.is_set():
                return False
            await asyncio.sleep(5)
            await self._check_browser_alive()
            try:
                url = self._page.url
                if "hometax.go.kr" in url and "login" not in url.lower():
                    self.log_message.emit("홈택스 로그인 확인됨")
                    return True
            except _BrowserClosedError:
                raise
            except Exception:
                pass
            if i % 12 == 11:
                self.log_message.emit(f"  로그인 대기 중... ({(i+1)*5}초)")
        return False

    async def _wait_for_login_wehago(self) -> bool:
        """WEHAGO 로그인 대기"""
        self.log_message.emit("[WEHAGO] 로그인 상태 확인 중...")

        await self._check_browser_alive()
        try:
            await self._page.goto(
                "https://www.wehago.com/#/main",
                wait_until="domcontentloaded",
                timeout=15000,
            )
        except _BrowserClosedError:
            raise
        except Exception:
            await self._check_browser_alive()

        await asyncio.sleep(3)
        try:
            if (await self._page.locator("#company_").count() > 0
                    or await self._page.locator("text=나의 수임처").count() > 0):
                self.log_message.emit("WEHAGO 이미 로그인되어 있습니다.")
                return True
        except _BrowserClosedError:
            raise
        except Exception:
            pass

        self.log_message.emit("브라우저에서 WEHAGO 로그인을 진행해 주세요.")

        for _ in range(6):
            if self._stop_event.is_set():
                return False
            await asyncio.sleep(5)
            await self._check_browser_alive()
            try:
                if await self._page.locator("text=나의 수임처").count() > 0:
                    self.log_message.emit("WEHAGO 로그인 확인됨.")
                    return True
            except _BrowserClosedError:
                raise
            except Exception:
                pass

        for i in range(52):
            if self._stop_event.is_set():
                return False
            await asyncio.sleep(15)
            await self._check_browser_alive()
            try:
                if await self._page.locator("text=나의 수임처").count() > 0:
                    self.log_message.emit("WEHAGO 로그인 확인됨.")
                    return True
                if i % 3 == 2:
                    await self._page.reload(wait_until="domcontentloaded")
                    await asyncio.sleep(3)
                    if await self._page.locator("text=나의 수임처").count() > 0:
                        self.log_message.emit("WEHAGO 로그인 확인됨.")
                        return True
            except _BrowserClosedError:
                raise
            except Exception:
                pass

        self.log_message.emit("WEHAGO 로그인 대기 시간 초과")
        return False

    def _emit_progress(self, engine, batch_id: int, phase_id: int):
        """현재 진행 상황을 Signal로 방출"""
        progress = engine.get_progress(batch_id)
        if progress:
            self.batch_progress.emit({
                "phase_id": phase_id,
                **progress,
            })

        # Job 목록
        jobs = engine.job_repo.list_by_batch(batch_id)
        job_list = []
        failed_list = []
        for j in jobs:
            job_dict = {
                "job_id": j.id,
                "name": j.client_name,
                "status": j.status,
                "current_step": j.current_step,
                "duration": j.duration_secs,
                "error": j.error_message,
            }
            job_list.append(job_dict)
            if j.status == "failed":
                failed_list.append(job_dict)
            self.job_changed.emit(
                j.id, j.client_name, j.status,
                j.current_step, j.error_message,
            )

        self.batch_progress.emit({
            "phase_id": phase_id,
            "jobs": job_list,
            "failed": failed_list,
        })
