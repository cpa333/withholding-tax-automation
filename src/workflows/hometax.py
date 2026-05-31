"""Phase 7: 홈택스 원천세 신고 어댑터"""

import os

from src.workflows.registry import register
from src.workflows.base import BaseWorkflow
from src.batch.state import StateManager


@register(
    phase_id=7,
    portal="hometax",
    display_name="홈택스 원천세 신고",
    enabled=False,
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

        WEHAGO SWER0101에서 생성된 .zip 파일을 홈택스에 업로드.
        """
        import glob

        save_dir = kwargs.get("save_dir", os.path.join(os.getcwd(), "results"))
        dry_run = kwargs.get("dry_run", True)

        # 신고파일 찾기
        if not state.should_skip_step(job_id, "find_swer_file"):
            state.before_step(job_id, "find_swer_file", 0)

            # results/{client_name}/원천징수전자신고/*.zip 패턴 검색
            search_patterns = [
                os.path.join(save_dir, client_name, "원천징수전자신고", "*.zip"),
                os.path.join(save_dir, client_name, "*.zip"),
                os.path.join(save_dir, "*.zip"),
            ]

            file_path = None
            for pattern in search_patterns:
                matches = glob.glob(pattern)
                if matches:
                    file_path = max(matches, key=os.path.getmtime)
                    break

            if not file_path:
                state.fail_step(job_id, "find_swer_file", "신고파일을 찾을 수 없음")
                return False

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
            await goto_withholding_tax(ht)
            await goto_file_convert(ht)
            state.after_step(job_id, "goto_filing")

        if not state.should_skip_step(job_id, "upload_file"):
            state.before_step(job_id, "upload_file", 3)
            from src.automation.hometax.hometax_auto_cdp import select_file
            ht = page
            await select_file(ht, file_path)
            state.after_step(job_id, "upload_file")

        if not state.should_skip_step(job_id, "verify"):
            state.before_step(job_id, "verify", 4)
            from src.automation.hometax.hometax_auto_cdp import verify_file
            ht = page
            await verify_file(ht)
            state.after_step(job_id, "verify")

        return True
