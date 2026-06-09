"""Phase 5: WEHAGO 급여명세 PDF 발급 어댑터

Phase 4(급여자료입력)에서 분리된 PDF 전용 페이즈.
사용자가 엑셀 업로드 후 점검을 마친 뒤 실행.

플로우:
  0. WEHAGO 메인 복귀
  1. 수임처 급여 페이지 진입
  2. SWSA0101 메뉴 이동 + 드롭다운 설정
  3. PDF 발급
  4. 모달 정리
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
    phase_id=5,
    portal="wehago",
    display_name="WEHAGO 급여명세 PDF",
    enabled=True,
)
class WehagoSalaryPdfWorkflow(BaseWorkflow):
    steps = [
        {"name": "navigate_to_wehago_main", "index": 0},
        {"name": "goto_salary_page",        "index": 1},
        {"name": "navigate_to_swsa0101",    "index": 2},
        {"name": "download_pdf",            "index": 3},
        {"name": "cleanup_modals",          "index": 4},
    ]

    async def run_single(
        self, page, context, client_name: str, job_id: int,
        state: StateManager, management_number: str = "", **kwargs,
    ) -> bool:
        from src.automation.wehago._common import (
            goto_salary_page, dismiss_dialogs, dismiss_ai_briefing_popup,
            ensure_full_tab, click_menu, goto_menu_page, select_dropdown,
            click_dialog_button,
        )
        from src.automation.wehago.run_swsa0101 import download_pdf

        year = kwargs.get("year")
        month = kwargs.get("month")

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

            # 사업자등록번호 검색 시도
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
                    from src.automation.wehago._common import log
                    log(f"  사업자번호 검색 예외: {e}")

            # 수임처명 직접 진입 (fallback)
            if not goto_ok:
                try:
                    from src.automation.wehago._common import log
                    log(f"  수임처명 '{client_name}'으로 직접 진입...")
                    if await goto_salary_page(page, client_name):
                        goto_ok = True
                except Exception as e:
                    from src.automation.wehago._common import log
                    log(f"  수임처명 진입 예외: {e}")

            if not goto_ok:
                state.fail_step(job_id, "goto_salary_page", "급여 페이지 이동 실패")
                return False

            await human_delay(2)
            state.after_step(job_id, "goto_salary_page")

        save_dir = make_save_dir(
            "위하고급여명세PDF", client_name, year=year, month=month,
        )

        # ── Step 2: SWSA0101 메뉴 이동 + 설정 ─────────────────────────
        if not state.should_skip_step(job_id, "navigate_to_swsa0101"):
            state.before_step(job_id, "navigate_to_swsa0101", 2)
            ok = await self._navigate_to_swsa0101(page)
            if not ok:
                state.fail_step(job_id, "navigate_to_swsa0101", "SWSA0101 이동 실패")
                return False
            state.after_step(job_id, "navigate_to_swsa0101")

        # ── Step 3: PDF 발급 ───────────────────────────────────────────
        if not state.should_skip_step(job_id, "download_pdf"):
            state.before_step(job_id, "download_pdf", 3)
            await download_pdf(page, save_dir)
            state.after_step(job_id, "download_pdf")

        # ── Step 4: 모달 정리 ─────────────────────────────────────────
        if not state.should_skip_step(job_id, "cleanup_modals"):
            state.before_step(job_id, "cleanup_modals", 4)
            await self._cleanup_print_modals(page)
            state.after_step(job_id, "cleanup_modals")

        return True

    # ── 헬퍼 ───────────────────────────────────────────────────────────

    async def _search_company_by_biz(self, page, biz_number: str) -> str | None:
        """WEHAGO 메인 검색: 사업자등록번호로 수임처명 반환"""
        from src.automation.wehago._common import log, dismiss_ai_briefing_popup

        if not biz_number:
            return None

        await dismiss_ai_briefing_popup(page)

        xpath_input = '//*[@id="wehagoPortalMain"]/div[1]/div[3]/div/div[1]/div/div/div[1]/div[2]/div[1]/div/input'
        xpath_btn = '//*[@id="wehagoPortalMain"]/div[1]/div[3]/div/div[1]/div/div/div[1]/div[2]/div[1]/div/button'

        try:
            input_loc = page.locator(f'xpath={xpath_input}')
            await input_loc.fill(biz_number, timeout=5000, force=True)
            await asyncio.sleep(0.5)
            btn_loc = page.locator(f'xpath={xpath_btn}')
            await btn_loc.click(timeout=5000, force=True)
            await asyncio.sleep(3)
        except Exception:
            try:
                await dismiss_ai_briefing_popup(page)
                input_loc = page.locator(f'xpath={xpath_input}')
                await input_loc.click(timeout=5000, force=True)
                await input_loc.fill("", force=True)
                await page.keyboard.type(biz_number, delay=50)
                await asyncio.sleep(0.5)
                btn_loc = page.locator(f'xpath={xpath_btn}')
                await btn_loc.click(timeout=5000, force=True)
                await asyncio.sleep(3)
            except Exception:
                return None

        try:
            found_name = await asyncio.wait_for(
                page.evaluate("""() => {
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
                }"""),
                timeout=10,
            )
        except Exception:
            return None

        return found_name

    async def _navigate_to_swsa0101(self, page) -> bool:
        """SWSA0101 메뉴 이동 + 간이세액 모달 + 드롭다운 설정"""
        from src.automation.wehago._common import (
            click_menu, goto_menu_page, dismiss_dialogs,
            select_dropdown, click_dialog_button,
        )

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

    async def _cleanup_print_modals(self, page):
        """일괄인쇄/일괄PDF 모달 정리"""
        for _ in range(3):
            closed = await page.evaluate("""() => {
                const all = document.querySelectorAll('*');
                for (const el of all) {
                    try {
                        const cs = window.getComputedStyle(el);
                        if ((cs.position !== 'fixed' && cs.position !== 'absolute')
                            || cs.display === 'none' || el.offsetWidth < 50) continue;
                        const z = parseInt(cs.zIndex);
                        if (z < 1000) continue;
                        if (!el.textContent.includes('일괄인쇄')
                            && !el.textContent.includes('일괄PDF')) continue;
                        const btns = el.querySelectorAll('button');
                        for (const btn of btns) {
                            if (btn.textContent.trim().startsWith('닫기')
                                    && btn.offsetWidth > 0) {
                                btn.click(); return 'closed';
                            }
                        }
                    } catch(e) {}
                }
                return null;
            }""")
            if closed:
                await asyncio.sleep(0.5)
            else:
                break
