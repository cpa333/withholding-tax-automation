"""Phase 8: 홈택스 원천세 신고 어댑터"""

import os
import glob

from src.utils.save_path import make_save_dir
from src.workflows.registry import register
from src.workflows.base import BaseWorkflow
from src.batch.state import StateManager


@register(
    phase_id=9,
    portal="hometax",
    display_name="홈택스 원천세 신고",
    enabled=True,
    ui_locked=True,
    needs_password=True,
)
class HometaxWorkflow(BaseWorkflow):
    steps = [
        {"name": "find_swer_file", "index": 0},
        {"name": "connect_hometax", "index": 1},
        {"name": "goto_filing", "index": 2},
        {"name": "upload_file", "index": 3},
        {"name": "verify", "index": 4},
    ]

    async def run_single(
        self, page, context, client_name: str, job_id: int,
        state: StateManager, **kwargs,
    ) -> bool:
        """홈택스 원천세 파일변환신고.

        WEHAGO SWER0101에서 생성된 .01 파일을 홈택스에 업로드.
        """
        year = kwargs.get("year")
        month = kwargs.get("month")
        dry_run = kwargs.get("dry_run", True)
        save_dir = make_save_dir("원천전자신고", client_name, year=year, month=month)

        # 신고파일 찾기
        if not state.should_skip_step(job_id, "find_swer_file"):
            state.before_step(job_id, "find_swer_file", 0)

            search_pattern = os.path.join(save_dir, "*.01")
            matches = glob.glob(search_pattern)
            if not matches:
                state.fail_step(
                    job_id, "find_swer_file",
                    f"신고파일을 찾을 수 없음: {search_pattern}",
                )
                return False

            file_path = max(matches, key=os.path.getmtime)
            state.after_step(job_id, "find_swer_file", {"file": file_path})
        else:
            step_data = state.get_step_data(job_id, "find_swer_file")
            file_path = step_data.get("file", "")
            if not file_path or not os.path.exists(file_path):
                return False

        # 홈택스 연결 및 파일변환신고
        if not state.should_skip_step(job_id, "connect_hometax"):
            state.before_step(job_id, "connect_hometax", 1)
            # AutomationRunner가 Chrome을 홈택스로 이미 전환했다고 가정
            state.after_step(job_id, "connect_hometax")

        if not state.should_skip_step(job_id, "goto_filing"):
            state.before_step(job_id, "goto_filing", 2)
            from src.automation.hometax.hometax_auto_cdp import (
                goto_withholding_tax, goto_file_convert,
            )
            ht = page  # hometax_auto_cdp는 page를 직접 사용
            if not await goto_withholding_tax(ht):
                state.fail_step(job_id, "goto_filing", "원천세 일반신고 메뉴 이동 실패")
                return False
            if not await goto_file_convert(ht):
                state.fail_step(job_id, "goto_filing", "파일변환신고 페이지 진입 실패")
                return False
            state.after_step(job_id, "goto_filing")

        if not state.should_skip_step(job_id, "upload_file"):
            state.before_step(job_id, "upload_file", 3)
            from src.automation.hometax.hometax_auto_cdp import select_file
            ht = page
            if not await select_file(ht, file_path):
                state.fail_step(job_id, "upload_file", "파일 선택 실패")
                return False
            state.after_step(job_id, "upload_file")

        if not state.should_skip_step(job_id, "verify"):
            state.before_step(job_id, "verify", 4)
            from src.automation.hometax.hometax_auto_cdp import verify_file
            ht = page
            if not await verify_file(ht):
                state.fail_step(job_id, "verify", "파일검증 실패")
                return False
            state.after_step(job_id, "verify")

        return True
