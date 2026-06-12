"""Phase 4: WEHAGO 급여자료입력 (SWSA0101) 어댑터

엑셀 다운로드 → raw data 병합 → 엑셀 업로드까지 수행.
PDF 발급은 Phase 5(WEHAGO 급여명세 PDF)에서 별도 실행.

플로우:
  0. WEHAGO 메인 복귀
  1. 수임처 급여 페이지 진입
  2. SWSA0101 메뉴 이동 + 드롭다운 설정
  3. 엑셀 다운로드
  4. 업로드 양식 변환 (raw data 병합 포함)
  5. 엑셀 업로드
"""
import asyncio
import os

from src.utils.save_path import make_save_dir
from src.utils.human import human_delay
from src.workflows.registry import register
from src.workflows.base import BaseWorkflow
from src.batch.state import StateManager


@register(
    phase_id=4,
    portal="wehago",
    display_name="WEHAGO 급여자료입력",
    enabled=True,
)
class WehagoSwsaWorkflow(BaseWorkflow):
    steps = [
        {"name": "navigate_to_wehago_main", "index": 0},
        {"name": "goto_salary_page",        "index": 1},
        {"name": "navigate_to_swsa0101",    "index": 2},
        {"name": "download_excel",          "index": 3},
        {"name": "convert_excel",           "index": 4},
        {"name": "upload_excel",            "index": 5},
    ]

    async def run_single(
        self, page, context, client_name: str, job_id: int,
        state: StateManager, management_number: str = "", **kwargs,
    ) -> bool:
        from src.automation.wehago._common import (
            ensure_wehago_main, goto_salary_page_with_fallback,
            navigate_to_swsa0101, log,
        )
        from src.automation.wehago.run_swsa0101 import (
            download_excel, convert_for_upload, upload_excel,
        )

        year = kwargs.get("year")
        month = kwargs.get("month")
        dry_run = kwargs.get("dry_run", True)

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

        # 급여 페이지 진입 성공 후에만 폴더 생성 (빈 폴더 방지)
        save_dir = make_save_dir(
            "위하고급여자료입력", client_name, year=year, month=month,
        )

        # ── Step 2: SWSA0101 메뉴 이동 + 설정 ─────────────────────────
        if not state.should_skip_step(job_id, "navigate_to_swsa0101"):
            state.before_step(job_id, "navigate_to_swsa0101", 2)
            ok = await navigate_to_swsa0101(page, year=year, month=month)
            if not ok:
                state.fail_step(job_id, "navigate_to_swsa0101", "SWSA0101 이동 실패")
                return False
            state.after_step(job_id, "navigate_to_swsa0101")

        # ── Step 3: 엑셀 다운로드 ─────────────────────────────────────
        if not state.should_skip_step(job_id, "download_excel"):
            state.before_step(job_id, "download_excel", 3)
            download_path = await download_excel(page, save_dir)
            state.after_step(job_id, "download_excel", {"path": download_path})
        else:
            step_data = state.get_step_data(job_id, "download_excel")
            download_path = step_data.get("path", "")

        if not download_path or not os.path.exists(download_path):
            state.fail_step(job_id, "download_excel", "다운로드 파일 없음")
            return False

        # ── Step 4: 업로드 양식 변환 (raw data 병합 포함) ───────────────
        if not state.should_skip_step(job_id, "convert_excel"):
            state.before_step(job_id, "convert_excel", 4)

            # Phase 2/3 raw data 파일 탐색 및 파싱
            nhis_data = None
            nps_member_data = None
            nps_retro_data = None
            nps_govt_data = None

            try:
                raw = self._locate_raw_data(client_name, year, month)
                if raw:
                    from src.utils.raw_data_reader import (
                        read_nhis_pdf, read_nps_member_excel,
                        read_nps_retro_excel, read_nps_govt_excel,
                    )
                    if raw.get("nhis_pdf"):
                        nhis_data = read_nhis_pdf(raw["nhis_pdf"])
                        log(f"  NHIS 데이터: {len(nhis_data)}명")
                    if raw.get("nps_member"):
                        nps_member_data = read_nps_member_excel(raw["nps_member"])
                        log(f"  NPS 가입자내역: {len(nps_member_data)}명")
                    if raw.get("nps_retro"):
                        nps_retro_data = read_nps_retro_excel(raw["nps_retro"])
                        log(f"  NPS 소급분내역: {len(nps_retro_data)}명")
                    if raw.get("nps_govt"):
                        nps_govt_data = read_nps_govt_excel(raw["nps_govt"])
                        log(f"  NPS 국고지원내역: {len(nps_govt_data)}명")
            except Exception as e:
                log(f"  원천데이터 읽기 스킵: {e}")

            upload_path = convert_for_upload(
                download_path,
                nhis_data=nhis_data,
                nps_member_data=nps_member_data,
                nps_retro_data=nps_retro_data,
                nps_govt_data=nps_govt_data,
            )
            state.after_step(job_id, "convert_excel", {"path": upload_path})
        else:
            step_data = state.get_step_data(job_id, "convert_excel")
            upload_path = step_data.get("path", "")

        if not upload_path or not os.path.exists(upload_path):
            state.fail_step(job_id, "convert_excel", "변환 파일 없음")
            return False

        # ── Step 5: 엑셀 업로드 ───────────────────────────────────────
        if not state.should_skip_step(job_id, "upload_excel"):
            state.before_step(job_id, "upload_excel", 5)
            success = await upload_excel(page, upload_path, dry_run=dry_run)
            if not success:
                state.fail_step(job_id, "upload_excel", "업로드 실패")
                return False
            state.after_step(job_id, "upload_excel")

        return True

    # ── 헬퍼 ───────────────────────────────────────────────────────────

    @staticmethod
    def _locate_raw_data(client_name: str, year, month) -> dict | None:
        """Phase 2/3 raw data 파일 경로 탐색

        Desktop 경로에서 건강보험 PDF, 국민연금 Excel을 찾아 dict로 반환.
        파일이 없으면 해당 키의 값이 None.

        Returns:
            {"nhis_pdf": path|None, "nps_member": path|None,
             "nps_retro": path|None, "nps_govt": path|None}
        """
        import glob
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        folder = client_name.replace(" ", "_")
        period = f"{year}{int(month):02d}" if year and month else None

        if not period:
            return None

        result = {
            "nhis_pdf": None,
            "nps_member": None,
            "nps_retro": None,
            "nps_govt": None,
        }

        # 건강보험 PDF
        nhis_dir = os.path.join(desktop, f"국민건강보험_{period}", folder)
        if os.path.isdir(nhis_dir):
            matches = glob.glob(os.path.join(nhis_dir, "가입자고지내역서_건강_*.pdf"))
            if matches:
                result["nhis_pdf"] = matches[0]

        # 국민연금 Excel
        nps_dir = os.path.join(desktop, f"국민연금_{period}", folder)
        if os.path.isdir(nps_dir):
            for f in os.listdir(nps_dir):
                full = os.path.join(nps_dir, f)
                if "가입자내역_엑셀" in f and f.endswith(".xlsx"):
                    result["nps_member"] = full
                elif "소급분내역_엑셀" in f and f.endswith(".xlsx"):
                    result["nps_retro"] = full
                elif "국고지원내역_엑셀" in f and f.endswith(".xlsx"):
                    result["nps_govt"] = full

        # 하나라도 있으면 dict 반환, 전부 None이면 None 반환
        if any(result.values()):
            return result
        return None
