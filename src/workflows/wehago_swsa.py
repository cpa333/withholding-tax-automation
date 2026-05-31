"""Phase 4: WEHAGO 급여자료입력 (SWSA0101) 어댑터

기존 run_swsa0101()을 BatchEngine에 연결.
"""

import os

from src.workflows.registry import register
from src.workflows.base import BaseWorkflow
from src.batch.state import StateManager


@register(
    phase_id=4,
    portal="wehago",
    display_name="WEHAGO 급여자료입력",
    enabled=False,
)
class WehagoSwsaWorkflow(BaseWorkflow):
    steps = [
        {"name": "goto_salary_page", "index": 0},
        {"name": "dismiss_dialogs", "index": 1},
        {"name": "download_excel", "index": 2},
        {"name": "convert_excel", "index": 3},
        {"name": "upload_excel", "index": 4},
        {"name": "download_pdf", "index": 5},
    ]

    async def run_single(
        self, page, context, client_name: str, job_id: int,
        state: StateManager, **kwargs,
    ) -> bool:
        from src.automation.wehago._common import (
            goto_salary_page, dismiss_dialogs,
        )
        from src.automation.wehago.run_swsa0101 import run_swsa0101

        save_dir = kwargs.get("save_dir", os.path.join(os.getcwd(), "results"))
        dry_run = kwargs.get("dry_run", True)

        # 수임처 급여 페이지로 이동
        if not state.should_skip_step(job_id, "goto_salary_page"):
            state.before_step(job_id, "goto_salary_page", 0)
            if not await goto_salary_page(page, client_name):
                state.fail_step(job_id, "goto_salary_page", "급여 페이지 이동 실패")
                return False
            state.after_step(job_id, "goto_salary_page")

        # 다이얼로그 정리
        if not state.should_skip_step(job_id, "dismiss_dialogs"):
            state.before_step(job_id, "dismiss_dialogs", 1)
            await dismiss_dialogs(page)
            state.after_step(job_id, "dismiss_dialogs")

        # 기존 자동화 함수 호출 (내부 단계는 로그로 추적)
        state.before_step(job_id, "run_swsa0101", 2)
        try:
            await run_swsa0101(page, save_dir, dry_run=dry_run)
            state.after_step(job_id, "run_swsa0101")
            return True
        except Exception as e:
            state.fail_step(job_id, "run_swsa0101", str(e))
            return False
