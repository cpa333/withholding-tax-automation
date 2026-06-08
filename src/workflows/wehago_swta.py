"""Phase 6: WEHAGO 원천징수이행상황신고서 (SWTA0101) 어댑터"""

from src.workflows.registry import register
from src.workflows.base import BaseWorkflow
from src.batch.state import StateManager


@register(
    phase_id=6,
    portal="wehago",
    display_name="WEHAGO 원천이행상황신고서",
    enabled=False,
)
class WehagoSwtaWorkflow(BaseWorkflow):
    steps = [
        {"name": "goto_salary_page", "index": 0},
        {"name": "dismiss_dialogs", "index": 1},
        {"name": "run_swta0101", "index": 2},
    ]

    async def run_single(
        self, page, context, client_name: str, job_id: int,
        state: StateManager, **kwargs,
    ) -> bool:
        from src.automation.wehago._common import (
            goto_salary_page, dismiss_dialogs,
        )
        from src.automation.wehago.run_swta0101 import run_swta0101

        # 수임처 급여 페이지로 이동
        if not state.should_skip_step(job_id, "goto_salary_page"):
            state.before_step(job_id, "goto_salary_page", 0)
            if not await goto_salary_page(page, client_name):
                state.fail_step(job_id, "goto_salary_page", "급여 페이지 이동 실패")
                return False
            state.after_step(job_id, "goto_salary_page")

        if not state.should_skip_step(job_id, "dismiss_dialogs"):
            state.before_step(job_id, "dismiss_dialogs", 1)
            await dismiss_dialogs(page)
            state.after_step(job_id, "dismiss_dialogs")

        if not state.should_skip_step(job_id, "run_swta0101"):
            state.before_step(job_id, "run_swta0101", 2)
            try:
                await run_swta0101(page)
                state.after_step(job_id, "run_swta0101")
            except Exception as e:
                state.fail_step(job_id, "run_swta0101", str(e))
                return False

        return True
