"""Phase 6: WEHAGO 원천징수이행상황신고서 (SWTA0101) 어댑터

플로우:
  0. WEHAGO 메인 복귀
  1. 수임처 급여 페이지 진입 (사업자번호 우선 → 이름 fallback)
  2. SWTA0101 마감/마감해제 처리
"""

from src.utils.human import human_delay
from src.workflows.registry import register
from src.workflows.base import BaseWorkflow
from src.batch.state import StateManager


@register(
    phase_id=6,
    portal="wehago",
    display_name="WEHAGO 원천이행상황신고서",
    enabled=True,
)
class WehagoSwtaWorkflow(BaseWorkflow):
    steps = [
        {"name": "navigate_to_wehago_main", "index": 0},
        {"name": "goto_salary_page",        "index": 1},
        {"name": "run_swta0101",            "index": 2},
    ]

    async def run_single(
        self, page, context, client_name: str, job_id: int,
        state: StateManager, management_number: str = "", **kwargs,
    ) -> bool:
        from src.automation.wehago._common import (
            ensure_wehago_main, goto_salary_page_with_fallback, log,
        )
        from src.automation.wehago.run_swta0101 import run_swta0101

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

        # ── Step 2: SWTA0101 마감 처리 ────────────────────────────────
        # run_swta0101()이 내부적으로 dismiss_dialogs를 포함한
        # 모든 모달 처리를 수행하므로 별도 단계 불필요
        if not state.should_skip_step(job_id, "run_swta0101"):
            state.before_step(job_id, "run_swta0101", 2)
            try:
                await run_swta0101(page)
                state.after_step(job_id, "run_swta0101")
            except Exception as e:
                state.fail_step(job_id, "run_swta0101", str(e))
                return False

        return True
