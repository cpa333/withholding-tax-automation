"""Phase 4: WEHAGO 급여자료입력 (SWSA0101) 어댑터

엑셀 다운로드 → raw data 병합 → 엑셀 업로드까지 수행.
PDF 발급은 Phase 5(WEHAGO 급여명세 PDF)에서 별도 실행.

플로우:
  0. WEHAGO 메인 복귀
  1. 수임처 급여 페이지 진입
  2. SWSA0101 메뉴 이동 + 드롭다운 설정
  3. 엑셀 다운로드
  4. 업로드 양식 변환 (raw data 병합 포함)
  5. 엑셀 업로드
"""
import asyncio
import os

from src.config import WEHAGO_URL
from src.utils.save_path import make_save_dir
from src.utils.human import human_delay
from src.workflows.registry import register
from src.workflows.base import BaseWorkflow
from src.batch.state import StateManager


@register(
    phase_id=4,
    portal="wehago",
    display_name="WEHAGO 급여자료입력",
    enabled=True,
)
class WehagoSwsaWorkflow(BaseWorkflow):
    steps = [
        {"name": "navigate_to_wehago_main", "index": 0},
        {"name": "goto_salary_page",        "index": 1},
        {"name": "navigate_to_swsa0101",    "index": 2},
        {"name": "download_excel",          "index": 3},
        {"name": "convert_excel",           "index": 4},
        {"name": "upload_excel",            "index": 5},
    ]

    async def run_single(
        self, page, context, client_name: str, job_id: int,
        state: StateManager, management_number: str = "", **kwargs,
    ) -> bool:
        from src.automation.wehago._common import (
            goto_salary_page, dismiss_dialogs, dismiss_ai_briefing_popup,
            ensure_full_tab, click_menu, goto_menu_page, select_dropdown,
            click_dialog_button, log,
        )
        from src.automation.wehago.run_swsa0101 import (
            download_excel, convert_for_upload, upload_excel, download_pdf,
        )

        year = kwargs.get("year")
        month = kwargs.get("month")
        dry_run = kwargs.get("dry_run", True)

        # ── Step 0: WEHAGO 메인 복귀 ──────────────────────────────────
        if not state.should_skip_step(job_id, "navigate_to_wehago_main"):
            state.before_step(job_id, "navigate_to_wehago_main", 0)
            try:
                is_on_main = await page.evaluate(
                    "() => document.querySelectorAll('[id^=\"company_\"]').length > 0"
                )
            except Exception:
                is_on_main = False
            if not is_on_main:
                await page.goto(
                    WEHAGO_URL + "#/main",
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
                await asyncio.sleep(3)
                await ensure_full_tab(page)
                await dismiss_dialogs(page)
                await dismiss_ai_briefing_popup(page)
            state.after_step(job_id, "navigate_to_wehago_main")

        # ── Step 1: 수임처 급여 페이지 진입 ───────────────────────────
        if not state.should_skip_step(job_id, "goto_salary_page"):
            state.before_step(job_id, "goto_salary_page", 1)

            goto_ok = False

            # --- NEW: 사업자등록번호 검색 시도 ---
            biz_number = (
                management_number[:-1]
                if management_number and management_number.endswith("0")
                else management_number
            )
            if biz_number:
                try:
                    found_name = await self._search_company_by_biz(page, biz_number)
                    if found_name and await goto_salary_page(page, found_name):
                        goto_ok = True
                except Exception as e:
                    log(f"  사업자번호 검색 예외: {e}")

            # --- FALLBACK: 수임처명 직접 진입 (기존 작동 방식) ---
            if not goto_ok:
                try:
                    log(f"  수임처명 '{client_name}'으로 직접 진입...")
                    if await goto_salary_page(page, client_name):
                        goto_ok = True
                except Exception as e:
                    log(f"  수임처명 진입 예외: {e}")

            if not goto_ok:
                state.fail_step(job_id, "goto_salary_page", "급여 페이지 이동 실패")
                return False

            await human_delay(2)
            state.after_step(job_id, "goto_salary_page")

        # 급여 페이지 진입 성공 후에만 폴더 생성 (빈 폴더 방지)
        save_dir = make_save_dir(
            "위하고급여자료입력", client_name, year=year, month=month,
        )

        # ── Step 2: SWSA0101 메뉴 이동 + 설정 ─────────────────────────
        if not state.should_skip_step(job_id, "navigate_to_swsa0101"):
            state.before_step(job_id, "navigate_to_swsa0101", 2)
            ok = await self._navigate_to_swsa0101(page)
            if not ok:
                state.fail_step(job_id, "navigate_to_swsa0101", "SWSA0101 이동 실패")
                return False
            state.after_step(job_id, "navigate_to_swsa0101")

        # ── Step 3: 엑셀 다운로드 ─────────────────────────────────────
        if not state.should_skip_step(job_id, "download_excel"):
            state.before_step(job_id, "download_excel", 3)
            download_path = await download_excel(page, save_dir)
            state.after_step(job_id, "download_excel", {"path": download_path})
        else:
            step_data = state.get_step_data(job_id, "download_excel")
            download_path = step_data.get("path", "")

        if not download_path or not os.path.exists(download_path):
            state.fail_step(job_id, "download_excel", "다운로드 파일 없음")
            return False

        # ── Step 4: 업로드 양식 변환 (raw data 병합 포함) ───────────────
        if not state.should_skip_step(job_id, "convert_excel"):
            state.before_step(job_id, "convert_excel", 4)

            # Phase 2/3 raw data 파일 탐색 및 파싱
            nhis_data = None
            nps_member_data = None
            nps_retro_data = None
            nps_govt_data = None

            try:
                raw = self._locate_raw_data(client_name, year, month)
                if raw:
                    from src.utils.raw_data_reader import (
                        read_nhis_pdf, read_nps_member_excel,
                        read_nps_retro_excel, read_nps_govt_excel,
                    )
                    if raw.get("nhis_pdf"):
                        nhis_data = read_nhis_pdf(raw["nhis_pdf"])
                        log(f"  NHIS 데이터: {len(nhis_data)}명")
                    if raw.get("nps_member"):
                        nps_member_data = read_nps_member_excel(raw["nps_member"])
                        log(f"  NPS 가입자내역: {len(nps_member_data)}명")
                    if raw.get("nps_retro"):
                        nps_retro_data = read_nps_retro_excel(raw["nps_retro"])
                        log(f"  NPS 소급분내역: {len(nps_retro_data)}명")
                    if raw.get("nps_govt"):
                        nps_govt_data = read_nps_govt_excel(raw["nps_govt"])
                        log(f"  NPS 국고지원내역: {len(nps_govt_data)}명")
            except Exception as e:
                log(f"  원천데이터 읽기 스킵: {e}")

            upload_path = convert_for_upload(
                download_path,
                nhis_data=nhis_data,
                nps_member_data=nps_member_data,
                nps_retro_data=nps_retro_data,
                nps_govt_data=nps_govt_data,
            )
            state.after_step(job_id, "convert_excel", {"path": upload_path})
        else:
            step_data = state.get_step_data(job_id, "convert_excel")
            upload_path = step_data.get("path", "")

        if not upload_path or not os.path.exists(upload_path):
            state.fail_step(job_id, "convert_excel", "변환 파일 없음")
            return False

        # ── Step 5: 엑셀 업로드 ───────────────────────────────────────
        if not state.should_skip_step(job_id, "upload_excel"):
            state.before_step(job_id, "upload_excel", 5)
            success = await upload_excel(page, upload_path, dry_run=dry_run)
            if not success:
                state.fail_step(job_id, "upload_excel", "업로드 실패")
                return False
            state.after_step(job_id, "upload_excel")

        return True

    # ── 헬퍼 ───────────────────────────────────────────────────────────

    @staticmethod
    def _locate_raw_data(client_name: str, year, month) -> dict | None:
        """Phase 2/3 raw data 파일 경로 탐색

        Desktop 경로에서 건강보험 PDF, 국민연금 Excel을 찾아 dict로 반환.
        파일이 없으면 해당 키의 값이 None.

        Returns:
            {"nhis_pdf": path|None, "nps_member": path|None,
             "nps_retro": path|None, "nps_govt": path|None}
        """
        import glob
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        folder = client_name.replace(" ", "_")
        period = f"{year}{int(month):02d}" if year and month else None

        if not period:
            return None

        result = {
            "nhis_pdf": None,
            "nps_member": None,
            "nps_retro": None,
            "nps_govt": None,
        }

        # 건강보험 PDF
        nhis_dir = os.path.join(desktop, f"국민건강보험_{period}", folder)
        if os.path.isdir(nhis_dir):
            matches = glob.glob(os.path.join(nhis_dir, "가입자고지내역서_건강_*.pdf"))
            if matches:
                result["nhis_pdf"] = matches[0]

        # 국민연금 Excel
        nps_dir = os.path.join(desktop, f"국민연금_{period}", folder)
        if os.path.isdir(nps_dir):
            for f in os.listdir(nps_dir):
                full = os.path.join(nps_dir, f)
                if "가입자내역_엑셀" in f and f.endswith(".xlsx"):
                    result["nps_member"] = full
                elif "소급분내역_엑셀" in f and f.endswith(".xlsx"):
                    result["nps_retro"] = full
                elif "국고지원내역_엑셀" in f and f.endswith(".xlsx"):
                    result["nps_govt"] = full

        # 하나라도 있으면 dict 반환, 전부 None이면 None 반환
        if any(result.values()):
            return result
        return None

    async def _search_company_by_biz(self, page, biz_number: str) -> str | None:
        """WEHAGO 메인 검색: 사업자등록번호 입력 → 검색 버튼 클릭 → 결과에서 수임처명 반환

        locator.click()이 AI 브리핑 팝업 등 오버레이에 의해 실패할 수 있으므로
        page.evaluate fallback을 함께 제공.
        """
        from src.automation.wehago._common import log, dismiss_ai_briefing_popup

        if not biz_number:
            log("  사업자등록번호가 비어있음")
            return None

        log(f"  사업자등록번호 '{biz_number}' 검색 중...")

        # AI 브리핑 팝업이 검색 버튼을 가릴 수 있으므로 미리 닫기
        await dismiss_ai_briefing_popup(page)

        xpath_input = '//*[@id="wehagoPortalMain"]/div[1]/div[3]/div/div[1]/div/div/div[1]/div[2]/div[1]/div/input'
        xpath_btn = '//*[@id="wehagoPortalMain"]/div[1]/div[3]/div/div[1]/div/div/div[1]/div[2]/div[1]/div/button'

        try:
            # ── 1) input에 사업자등록번호 입력 (force=True: 팝업이 가려도 입력)
            input_loc = page.locator(f'xpath={xpath_input}')
            await input_loc.fill(biz_number, timeout=5000, force=True)
            log("  검색어 입력 완료")
            await asyncio.sleep(0.5)

            # ── 2) 검색 버튼 클릭 (force=True: SVG 아이콘/팝업이 있어도 클릭)
            btn_loc = page.locator(f'xpath={xpath_btn}')
            await btn_loc.click(timeout=5000, force=True)
            log("  검색 버튼 클릭 → 결과 대기...")
            await asyncio.sleep(3)

        except Exception as e:
            log(f"  locator 조작 실패, keyboard.type으로 재시도: {e}")
            # Fallback: 팝업 재확인 후 keyboard.type + force click
            try:
                await dismiss_ai_briefing_popup(page)
                input_loc = page.locator(f'xpath={xpath_input}')
                await input_loc.click(timeout=5000, force=True)
                await input_loc.fill("", force=True)
                await page.keyboard.type(biz_number, delay=50)
                await asyncio.sleep(0.5)
                btn_loc = page.locator(f'xpath={xpath_btn}')
                await btn_loc.click(timeout=5000, force=True)
                log("  keyboard.type + force click으로 검색 완료")
                await asyncio.sleep(3)
            except Exception as e2:
                log(f"  keyboard.type 재시도도 실패: {e2}")
                return None

        # ── 3) 결과 리스트에서 수임처명 찾기 (읽기 전용 evaluate) ────
        try:
            found_name = await asyncio.wait_for(
                page.evaluate("""() => {
                    try {
                        // 검색 결과에서 수임처명 찾기
                        // company_ 카드를 직접 사용 (li a는 내비게이션 메뉴를 먼저 매칭함)
                        const cards = document.querySelectorAll('[id^="company_"]');
                        for (const card of cards) {
                            if (card.offsetWidth < 10) continue;
                            const nameEl = card.querySelector('a');
                            if (nameEl) {
                                const name = nameEl.textContent.trim();
                                if (name) return name;
                            }
                        }
                        return null;
                    } catch(e) {
                        return null;
                    }
                }"""),
                timeout=10,
            )
        except Exception as e:
            log(f"  결과 읽기 실패: {e}")
            return None

        if found_name:
            log(f"  사업자번호 '{biz_number}' → '{found_name}' 검색 완료")
        else:
            log(f"  사업자번호 '{biz_number}' 검색 결과 없음")
        return found_name

    async def _navigate_to_swsa0101(self, page) -> bool:
        """SWSA0101 메뉴 이동 + 간이세액 모달 + 드롭다운 설정

        run_swsa0101() lines 557-609 로직을 추출.
        """
        from src.automation.wehago._common import (
            click_menu, goto_menu_page, dismiss_dialogs,
            select_dropdown, click_dialog_button,
        )

        # SWSA0101 메뉴 이동
        current_url = page.url
        if "SWSA0101" not in current_url:
            await click_menu(page, "SWSA0101")
            await asyncio.sleep(3)
            if "SWSA0101" not in page.url:
                await goto_menu_page(page, "SWSA0101")
                await asyncio.sleep(3)
        await dismiss_dialogs(page)

        # 간이세액 개정 안내 모달 닫기
        await page.evaluate("""() => {
            const all = document.querySelectorAll('*');
            for (const el of all) {
                const cs = window.getComputedStyle(el);
                if (cs.position !== 'fixed' || cs.display === 'none' ||
                    parseInt(cs.zIndex) <= 100 || el.offsetWidth <= 100) continue;
                if (!el.textContent.includes('간이세액')) continue;
                const btns = el.querySelectorAll('button.WSC_LUXButton');
                for (const btn of btns) {
                    if (!btn.textContent.trim() && btn.offsetWidth > 0) {
                        btn.click(); return;
                    }
                }
            }
        }""")
        await asyncio.sleep(1)
        await dismiss_dialogs(page)

        # 구분 드롭다운 → 급여+상여
        await select_dropdown(page, 0, "급여+상여")

        # 복사후 재계산 모달 (조건부)
        await asyncio.sleep(1)
        has_modal = await page.evaluate("""() => {
            const selectors = ['._isDialog', '.LUX_basic_dialog'];
            for (const sel of selectors) {
                for (const d of document.querySelectorAll(sel)) {
                    if (d.style.display !== 'none') return true;
                }
            }
            return false;
        }""")
        if has_modal:
            await click_dialog_button(page, "복사후 재계산")
            await asyncio.sleep(1)
            await click_dialog_button(page, "취소")

        return True
