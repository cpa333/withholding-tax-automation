"""Phase 3: 국민연금 EDI PDF+Excel 다운로드 어댑터"""

import os

from src.workflows.registry import register
from src.workflows.base import BaseWorkflow
from src.batch.state import StateManager
from src.utils.save_path import make_save_dir


@register(
    phase_id=3,
    portal="nps_edi",
    display_name="국민연금 EDI",
)
class NpsEdiWorkflow(BaseWorkflow):
    steps = [
        {"name": "switch_workplace", "index": 0},
        {"name": "navigate_to_decision", "index": 1},
        {"name": "open_detail", "index": 2},
        {"name": "process_tabs", "index": 3},
        {"name": "save_files", "index": 4},
    ]

    async def run_single(
        self, page, context, client_name: str, job_id: int,
        state: StateManager, management_number: str = "", **kwargs,
    ) -> bool:
        from src.automation.nps._common import (
            navigate_to_decision_details, open_decision_detail,
            switch_workplace, list_workplaces,
            process_tab_download, click_detail_tab,
            TAB_MEMBER, TAB_RETRO, TAB_GOVT,
        )
        import asyncio
        from src.utils.human import human_delay

        year = kwargs.get("year")
        month = kwargs.get("month")

        # 사업장 전환
        if not state.should_skip_step(job_id, "switch_workplace"):
            state.before_step(job_id, "switch_workplace", 0)
            ok = await switch_workplace(page, client_name, management_number)
            if not ok:
                state.fail_step(job_id, "switch_workplace", f"'{client_name}' 전환 실패")
                return False
            await human_delay(3)
            state.after_step(job_id, "switch_workplace")

        # 사업장 전환 성공 후에만 폴더 생성 (검색 실패 시 빈 폴더 방지)
        firm_dir = make_save_dir("국민연금", client_name, year=year, month=month)

        # 결정내역 이동
        if not state.should_skip_step(job_id, "navigate_to_decision"):
            state.before_step(job_id, "navigate_to_decision", 1)
            ok = await navigate_to_decision_details(page)
            if not ok:
                state.fail_step(job_id, "navigate_to_decision", "결정내역 페이지 이동 실패")
                return False
            await human_delay(2)
            state.after_step(job_id, "navigate_to_decision")

        # 2차 상세 열기
        if not state.should_skip_step(job_id, "open_detail"):
            state.before_step(job_id, "open_detail", 2)
            ok = await open_decision_detail(page, round_filter="2차",
                                            year=year, month=month)
            if not ok:
                state.fail_step(job_id, "open_detail", "2차 결정내역 상세 진입 실패")
                return False
            await human_delay(2)
            state.after_step(job_id, "open_detail")

        # 각 탭 처리
        if not state.should_skip_step(job_id, "process_tabs"):
            state.before_step(job_id, "process_tabs", 3)

            tabs = [
                (TAB_MEMBER, "가입자내역", "grdList2"),
                (TAB_RETRO, "소급분내역", "grdList3"),
                (TAB_GOVT, "국고지원내역", "grdList4"),
            ]

            for tab_idx, tab_label, grid_suffix in tabs:
                try:
                    await process_tab_download(
                        page, context, firm_dir,
                        tab_idx, tab_label, grid_suffix,
                        year=year, month=month,
                    )
                except Exception as e:
                    pass  # 빈 탭은 무시

            state.after_step(job_id, "process_tabs")

        return True
