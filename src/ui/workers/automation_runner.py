"""Automation Runner — 페이즈 실행 오케스트레이터

AsyncWorker를 상속하여 BatchEngine + Workflow 어댑터를 연결.
QThread 내부에서 Playwright + BatchEngine을 실행하고
Qt Signal로 UI에 진행 상황을 방출.
"""

import asyncio
import os

from src.ui.workers.async_bridge import AsyncWorker


class AutomationRunner(AsyncWorker):
    """BatchEngine 기반 페이즈 실행기"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._db_path = os.path.join(os.getcwd(), "data", "withholding_tax.db")
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._current_portal = None

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
                elif cmd.get("type") == "run_phase":
                    await self._handle_run_phase(cmd)

        self.log_message.emit("자동화 러너 종료됨")

    async def _handle_run_phase(self, cmd: dict):
        """run_phase 명령 처리"""
        phase_id = cmd.get("phase_id", 0)
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

        # Chrome 실행 + 로그인
        if not await self._ensure_browser(portal):
            self.phase_changed.emit(phase_id, "failed")
            self.error_occurred.emit("Chrome 연결 실패")
            return

        # 포털별 로그인 대기
        if not await self._wait_for_login(portal):
            self.phase_changed.emit(phase_id, "failed")
            self.error_occurred.emit("로그인 실패 또는 시간 초과")
            return

        # Phase 1: BatchEngine 없이 직접 스크래핑
        if phase_id == 1:
            await self._run_phase1_directly()
            return

        # Phase 2+: BatchEngine으로 배치 실행
        from src.batch.engine import BatchEngine
        from src.batch.models import Client, BatchStatus

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
                            enabled=True,
                        ))
                self.log_message.emit(f"  WEHAGO → {portal}: {len(wehago_clients)}개 수임처 동기화")

            batch = engine.prepare_batch()

            # 워크플로우 실행
            workflow = get_workflow(phase_id)
            if not workflow:
                self.log_message.emit(f"워크플로우를 찾을 수 없음: phase {phase_id}")
                return

            workflow_func = workflow.as_workflow_func(**kwargs)

            # 배치를 running으로
            engine.batch_repo.update_status(batch.id, BatchStatus.RUNNING)

            try:
                # 수임처별 루프 — 일시정지/정지 체크
                while not self._stop_event.is_set():
                    # 일시정지 대기
                    while not self._pause_event.is_set() and not self._stop_event.is_set():
                        await asyncio.sleep(0.5)

                    if self._stop_event.is_set():
                        engine.batch_repo.update_status(batch.id, BatchStatus.PAUSED)
                        self.log_message.emit("[사용자 중단] 배치 일시정지됨")
                        break

                    job = engine.job_repo.get_next_pending(batch.id)
                    if not job:
                        break

                    await engine._run_job(
                        job, workflow_func,
                        page=self._page,
                        context=self._context,
                    )

                    self._emit_progress(engine, batch.id, phase_id)
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

    async def _run_phase1_directly(self):
        """Phase 1: 수임처 리스트 직접 스크래핑 (BatchEngine 미사용)"""
        from src.automation.wehago._common import (
            WEHAGO_TAXAGENT_URL, dismiss_dialogs,
            get_all_clients_from_management,
        )
        from src.batch.db import BatchDB, ClientRepository
        from src.batch.models import Client

        page = self._page
        try:
            # 수임처관리 페이지 이동
            self.log_message.emit("수임처관리 페이지로 이동 중...")
            await page.goto(WEHAGO_TAXAGENT_URL, wait_until="domcontentloaded", timeout=30000)
            await dismiss_dialogs(page)

            # SPA 렌더링 대기: 수임처 리스트가 나타날 때까지
            try:
                await page.wait_for_selector(
                    'ul.acceptance_list li span.company_name_text',
                    timeout=10000,
                )
            except Exception:
                self.log_message.emit("리스트 로딩 재시도...")
                await dismiss_dialogs(page)
                await page.wait_for_selector(
                    'ul.acceptance_list li span.company_name_text',
                    timeout=8000,
                )

            # 전체 수임처 스크래핑
            self.log_message.emit("수임처 목록 조회 중...")
            companies = await get_all_clients_from_management(page)
            companies = [n.replace("[테스트] ", "") for n in companies]
            companies = [n for n in companies if n]

            self.log_message.emit(f"수임처 {len(companies)}건 조회 완료")

            # DB에 저장 (wehago 단일 소스)
            os.makedirs(os.path.dirname(self._db_path), exist_ok=True)

            # 기존 clients 전체 삭제 후 재등록
            import sqlite3
            conn = sqlite3.connect(self._db_path)
            try:
                # FK 해제 안전을 위해 관련 데이터도 정리
                conn.execute("DELETE FROM steps")
                conn.execute("DELETE FROM jobs")
                conn.execute("DELETE FROM batches")
                conn.execute("DELETE FROM clients")
                conn.commit()
            finally:
                conn.close()

            db = BatchDB(self._db_path)
            db.connect()
            try:
                client_repo = ClientRepository(db)
                for name in companies:
                    client_repo.upsert(Client(
                        name=name,
                        portal="wehago",
                        enabled=True,
                    ))
            finally:
                db.close()

            self.phase_changed.emit(1, "completed")
            self.log_message.emit(f"수임처 리스트 확보 완료: {len(companies)}건")

        except Exception as e:
            self.log_message.emit(f"수임처 조회 실패: {e}")
            self.phase_changed.emit(1, "failed")
            self.error_occurred.emit(f"수임처 조회 실패: {e}")

    def _reset_batch(self, db_path: str, portal: str, phase_id: int):
        """이전 배치/잡/단계를 모두 삭제하여 깨끗한 상태로 초기화"""
        import sqlite3
        if not os.path.exists(db_path):
            return

        conn = sqlite3.connect(db_path)
        try:
            if phase_id == 1:
                # Phase 1: 모든 포털 배치+수임처 초기화 (wehago가 소스이므로 전체 리셋)
                conn.execute("DELETE FROM steps")
                conn.execute("DELETE FROM jobs")
                conn.execute("DELETE FROM batches")
                conn.execute("DELETE FROM clients")
            else:
                # 다른 페이즈: 해당 포털 배치만 삭제 (수임처는 유지)
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
            conn.commit()
        finally:
            conn.close()

    async def _ensure_browser(self, portal: str) -> bool:
        """포털에 맞는 Chrome 인스턴스 실행"""
        from src.utils.chrome_cdp import launch_chrome, kill_chrome, CDP_URL

        # 포털별 URL
        portal_urls = {
            "wehago": "https://www.wehago.com/",
            "nhis_edi": "https://edi.nhis.or.kr/",
            "nps_edi": "https://edi.nps.or.kr/",
            "hometax": "https://www.hometax.go.kr/",
        }
        url = portal_urls.get(portal, "https://www.wehago.com/")

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

    async def _wait_for_login(self, portal: str) -> bool:
        """포털별 로그인 완료 대기. 수동 로그인 필요 시 안내 메시지 출력."""
        import asyncio

        if portal == "nhis_edi":
            self.log_message.emit("[국민건강보험 EDI] 로그인 대기 중... 공동인증서로 로그인해 주세요.")
            # 페이지가 NHIS EDI 탭인지 확인, 아니면 올바른 탭 찾기
            page = self._page
            if "edi.nhis" not in page.url:
                for pg in self._context.pages:
                    if "edi.nhis" in pg.url:
                        page = pg
                        self._page = page
                        break

            for i in range(180):
                await asyncio.sleep(5)
                try:
                    url = page.url
                    self.log_message.emit(f"  로그인 확인 중... URL: {url[:80]}")
                    if "retrieveMain" in url:
                        self.log_message.emit("국민건강보험 EDI 로그인 확인됨 (retrieveMain)")
                        return True
                    # URL이 로그인 페이지가 아니면 로그인 완료로 간주
                    if "edi.nhis.or.kr" in url and "login" not in url.lower() and "index" not in url.lower():
                        body = await page.evaluate("() => document.body.innerText.substring(0, 100)")
                        if body and len(body) > 30:
                            self.log_message.emit(f"국민건강보험 EDI 로그인 확인됨")
                            return True
                except Exception as e:
                    self.log_message.emit(f"  로그인 확인 오류: {e}")
                if i % 6 == 5:
                    self.log_message.emit(f"  로그인 대기 중... ({(i+1)*5}초)")
            return False

        elif portal == "nps_edi":
            self.log_message.emit("[국민연금 EDI] 로그인 대기 중... 공동인증서로 로그인해 주세요.")
            # 올바른 탭 찾기
            page = self._page
            if "edi.nps" not in page.url:
                for pg in self._context.pages:
                    if "edi.nps" in pg.url:
                        page = pg
                        self._page = page
                        break

            for i in range(180):
                await asyncio.sleep(5)
                try:
                    url = page.url
                    if i < 3 or i % 6 == 5:
                        self.log_message.emit(f"  로그인 확인 중... URL: {url[:80]}")

                    if "edi.nps.or.kr" in url and "login" not in url.lower() and "index" not in url.lower():
                        self.log_message.emit("국민연금 EDI 로그인 확인됨")
                        return True

                    # URL이 login/index가 아니면 body 확인
                    if "edi.nps.or.kr" in url:
                        body = await page.evaluate("() => document.body.innerText.substring(0, 200)")
                        if body and len(body) > 30:
                            self.log_message.emit("국민연금 EDI 로그인 확인됨 (body)")
                            return True
                except Exception as e:
                    self.log_message.emit(f"  로그인 확인 오류: {e}")
                if i % 6 == 5:
                    self.log_message.emit(f"  로그인 대기 중... ({(i+1)*5}초)")
            return False

        elif portal == "hometax":
            self.log_message.emit("[홈택스] 로그인 대기 중... 인증서로 로그인해 주세요.")
            for i in range(180):
                await asyncio.sleep(5)
                try:
                    url = self._page.url
                    if "hometax.go.kr" in url and "login" not in url.lower():
                        self.log_message.emit("홈택스 로그인 확인됨")
                        return True
                except Exception:
                    pass
                if i % 12 == 11:
                    self.log_message.emit(f"  로그인 대기 중... ({(i+1)*5}초)")
            return False

        else:
            # wehago 등은 이미 로그인된 상태로 진행
            return True

    async def _poll_progress(self, engine, batch_id: int, phase_id: int):
        """진행 상황 주기적 폴링 → Signal 방출"""
        try:
            while True:
                await asyncio.sleep(2)
                self._emit_progress(engine, batch_id, phase_id)
        except asyncio.CancelledError:
            pass

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
