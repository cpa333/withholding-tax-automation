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
            ensure_wehago_main, goto_salary_page_with_fallback,
            navigate_to_swsa0101, log,
        )
        from src.automation.wehago.run_swsa0101 import download_pdf

        year = kwargs.get("year")
        month = kwargs.get("month")

        # ── Step 0: WEHAGO 메인 복귀 ──────────────────────────────────
        if not state.should_skip_step(job_id, "navigate_to_wehago_main"):
            state.before_step(job_id, "navigate_to_wehago_main", 0)
            await ensure_wehago_main(page)
            state.after_step(job_id, "navigate_to_wehago_main")

        # ── Step 1: 수임처 급여 페이지 진입 ───────────────────────────
        if not state.should_skip_step(job_id, "goto_salary_page"):
            state.before_step(job_id, "goto_salary_page", 1)
            goto_ok = await goto_salary_page_with_fallback(
                page, client_name, management_number,
            )
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
            ok = await navigate_to_swsa0101(page)
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

    # ── 헬퍼 (Phase 5 전용) ────────────────────────────────────────────

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
