"""Phase 7: WEHAGO 원천징수전자신고 (SWER0101) 어댑터

플로우:
  0. WEHAGO 메인 복귀
  1. 수임처 급여 페이지 진입 (사업자번호 우선 → 이름 fallback)
  2. SWER0101 전자신고 파일 제작
     - 사용자가 설정한 귀속연도/월(year, month kwargs)을 지급기간에 반영
     - None이면 compute_target_period()로 직전월 자동 산출
"""

from src.utils.human import human_delay
from src.utils.save_path import make_save_dir
from src.workflows.registry import register
from src.workflows.base import BaseWorkflow
from src.batch.state import StateManager


@register(
    phase_id=7,
    portal="wehago",
    display_name="WEHAGO 원천전자신고",
    enabled=True,
)
class WehagoSwerWorkflow(BaseWorkflow):
    steps = [
        {"name": "navigate_to_wehago_main", "index": 0},
        {"name": "goto_salary_page",        "index": 1},
        {"name": "run_swer0101",            "index": 2},
    ]

    async def run_single(
        self, page, context, client_name: str, job_id: int,
        state: StateManager, management_number: str = "", **kwargs,
    ) -> bool:
        from src.automation.wehago._common import (
            ensure_wehago_main, goto_salary_page_with_fallback, log,
        )
        from src.automation.wehago.run_swer0101 import run_swer0101

        password = kwargs.get("password", "")
        nts_folder = kwargs.get("nts_folder", "원천징수전자신고")
        year = kwargs.get("year")
        month = kwargs.get("month")
        save_dir = make_save_dir("원천전자신고", client_name, year=year, month=month)

        if not password:
            log("  전자신고 비밀번호가 없습니다")
            return False

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

        # ── Step 2: SWER0101 전자신고 파일 제작 ───────────────────────
        # run_swer0101()이 내부적으로 dismiss_dialogs, 모달 처리,
        # 비밀번호 입력, NTS 폴더 선택까지 모두 수행
        if not state.should_skip_step(job_id, "run_swer0101"):
            state.before_step(job_id, "run_swer0101", 2)
            try:
                await run_swer0101(page, password, nts_folder, year=year, month=month, save_dir=save_dir)
                state.after_step(job_id, "run_swer0101")
            except Exception as e:
                state.fail_step(job_id, "run_swer0101", str(e))
                return False

        return True
