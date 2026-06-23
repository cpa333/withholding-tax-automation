"""Phase 3: 국민연금 EDI PDF+Excel 다운로드 어댑터"""

import os

from src.workflows.registry import register
from src.workflows.base import BaseWorkflow
from src.batch.state import StateManager
from src.utils.save_path import make_save_dir


@register(
    phase_id=4,
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
            download_final_integrated,
        )
        # [롤백 참고] 3탭(가입자/소급/국고) 개별 PDF+엑셀 다운로드로 되돌리려면
        # process_tab_download, click_detail_tab, TAB_MEMBER/RETRO/GOVT 를
        # 다시 import 하여 아래 process_tabs 단계의 주석 처리된 루프를 활성화.
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
            ok = await open_decision_detail(page, year=year, month=month)
            if not ok or not ok.get("ok"):
                state.fail_step(job_id, "open_detail", "2차 결정내역 상세 진입 실패")
                return False
            await human_delay(2)
            state.after_step(job_id, "open_detail")

        # 최종결정내역 통합엑셀 다운로드 — 3탭(가입자/소급/국고) 개별 수신을
        # 최종결정내역 탭의 통합저장(전체표출) 1장으로 대체.
        # raw_data_reader.read_nps_integrated_excel 이 col10/16/24 로 동일한
        # 3개 dict(member/retro/govt)을 생성하므로 하위 data_merger 로직은 불변.
        if not state.should_skip_step(job_id, "process_tabs"):
            state.before_step(job_id, "process_tabs", 3)
            try:
                await download_final_integrated(
                    page, context, firm_dir, year=year, month=month,
                )
            except Exception as e:
                pass  # 데이터 없음/사업장 미대상 등
            state.after_step(job_id, "process_tabs")

            # [롤백용] 구 3탭 개별 다운로드(PDF+엑셀) — process_tab_download,
            # click_detail_tab, TAB_MEMBER/RETRO/GOVT import 후 아래 루프 활성화.
            # tabs = [
            #     (TAB_MEMBER, "가입자내역", "grdList2"),
            #     (TAB_RETRO, "소급분내역", "grdList3"),
            #     (TAB_GOVT, "국고지원내역", "grdList4"),
            # ]
            # for tab_idx, tab_label, grid_suffix in tabs:
            #     try:
            #         await process_tab_download(
            #             page, context, firm_dir,
            #             tab_idx, tab_label, grid_suffix,
            #             year=year, month=month,
            #         )
            #     except Exception as e:
            #         pass  # 빈 탭은 무시

        return True
