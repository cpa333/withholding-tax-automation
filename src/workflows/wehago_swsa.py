"""Phase 4: WEHAGO 급여자료입력 (SWSA0101) 어댑터

엑셀 다운로드 → raw data 병합 → 엑셀 업로드까지 수행.
PDF 발급은 Phase 5(WEHAGO 급여명세 PDF)에서 별도 실행.

플로우:
  0. WEHAGO 메인 복귀
  1. 수임처 급여 페이지 진입
  2. SWSA0101 메뉴 이동 + 드롭다운 설정
  3. 사원 전체 재계산 (고용보험 재계산) — 엑셀 다운로드 직전
  4. 엑셀 다운로드
  5. 업로드 양식 변환 (raw data 병합 포함)
  6. 엑셀 업로드
"""
import asyncio
import os

from src.utils.save_path import make_save_dir, get_desktop_path, PARALLEL_SAVE_SITE
from src.utils.human import human_delay
from src.workflows.registry import register
from src.workflows.base import BaseWorkflow
from src.batch.state import StateManager


@register(
    phase_id=6,
    portal="wehago",
    display_name="WEHAGO 급여자료입력",
    enabled=True,
)
class WehagoSwsaWorkflow(BaseWorkflow):
    steps = [
        {"name": "navigate_to_wehago_main", "index": 0},
        {"name": "goto_salary_page",        "index": 1},
        {"name": "navigate_to_swsa0101",    "index": 2},
        {"name": "recalculate",             "index": 3},
        {"name": "download_excel",          "index": 4},
        {"name": "convert_excel",           "index": 5},
        {"name": "upload_excel",            "index": 6},
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
            download_excel, convert_for_upload, upload_excel, recalculate_salary,
        )

        year = kwargs.get("year")
        month = kwargs.get("month")
        dry_run = kwargs.get("dry_run", True)
        business_number = kwargs.get("business_number", "")

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
                business_number=business_number,
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

        # ── Step 3: 사원 재계산 (다운로드 직전) — 해상도 무관, 라이브 검증
        recalc_category = kwargs.get("recalculate_category", "고용보험 재계산")
        if kwargs.get("recalculate", True) and not state.should_skip_step(job_id, "recalculate"):
            state.before_step(job_id, "recalculate", 3)
            ok_recalc = await recalculate_salary(page, category=recalc_category)
            if not ok_recalc:
                log(f"  ⚠ 재계산 실패 — 엑셀 다운로드로 계속 진행")
            state.after_step(job_id, "recalculate")

        # ── Step 4: 엑셀 다운로드 ─────────────────────────────────────
        if not state.should_skip_step(job_id, "download_excel"):
            state.before_step(job_id, "download_excel", 4)
            download_path = await download_excel(page, save_dir)
            state.after_step(job_id, "download_excel", {"path": download_path})
        else:
            step_data = state.get_step_data(job_id, "download_excel")
            download_path = step_data.get("path", "")

        if not download_path or not os.path.exists(download_path):
            state.fail_step(job_id, "download_excel", "다운로드 파일 없음")
            return False

        # ── Step 5: 업로드 양식 변환 (raw data 병합 포함) ───────────────
        if not state.should_skip_step(job_id, "convert_excel"):
            state.before_step(job_id, "convert_excel", 5)

            # Phase 2/3/5 raw data 파일 탐색 및 파싱
            nhis_data = None
            nps_member_data = None
            nps_retro_data = None
            nps_govt_data = None
            ei_support_data = None
            ei_collect_data = None

            try:
                raw = self._locate_raw_data(client_name, year, month)
                if raw:
                    from src.utils.raw_data_reader import (
                        read_nhis_pdf, read_nps_integrated_excel,
                        read_nps_member_excel, read_nps_retro_excel,
                        read_nps_govt_excel, read_employment_xls,
                    )
                    if raw.get("nhis_pdf"):
                        nhis_data = read_nhis_pdf(raw["nhis_pdf"])
                        log(f"  NHIS 데이터: {len(nhis_data)}명")
                    # NPS: 통합엑셀 우선 — 1장에서 member/retro/govt 3 dict 추출.
                    # 통합엑셀이 없으면 구 3파일 폴백(레거시/롤백 경로).
                    if raw.get("nps_integrated"):
                        nps_member_data, nps_retro_data, nps_govt_data = (
                            read_nps_integrated_excel(raw["nps_integrated"])
                        )
                        log(f"  NPS 통합엑셀: member {len(nps_member_data)}, "
                            f"retro {len(nps_retro_data)}, govt {len(nps_govt_data)}명")
                    else:
                        if raw.get("nps_member"):
                            nps_member_data = read_nps_member_excel(raw["nps_member"])
                            log(f"  NPS 가입자내역: {len(nps_member_data)}명")
                        if raw.get("nps_retro"):
                            nps_retro_data = read_nps_retro_excel(raw["nps_retro"])
                            log(f"  NPS 소급분내역: {len(nps_retro_data)}명")
                        if raw.get("nps_govt"):
                            nps_govt_data = read_nps_govt_excel(raw["nps_govt"])
                            log(f"  NPS 국고지원내역: {len(nps_govt_data)}명")
                    # 고용보험(근로복지공단) xls — 실업급여 지원금/환수금(근로자)
                    # 다른 보험 파싱 실패에 휘말리지 않도록 독립 except 로 분리.
                    if raw.get("ei_xls"):
                        try:
                            ei_support_data, ei_collect_data = read_employment_xls(raw["ei_xls"])
                            log(f"  고용보험: 지원금 {len(ei_support_data)}명, "
                                f"환수금 {len(ei_collect_data)}명")
                            if not ei_support_data and not ei_collect_data:
                                log(f"  WARN: 고용보험 파일은 있으나 추출 0명 — 미반영 "
                                    f"({os.path.basename(raw['ei_xls'])}). "
                                    f"공단 양식 변경 또는 xlrd 미설치 가능성.")
                        except Exception as e:
                            ei_support_data = ei_collect_data = None
                            log(f"  WARN: 고용보험 파싱 실패 — 미반영: {type(e).__name__}: {e}")
            except Exception as e:
                import traceback
                log(f"  WARN: 원천데이터 읽기 실패 (무시하고 진행): {e}")
                log(f"        client={client_name} year={year} month={month}")
                log(f"        {traceback.format_exc().splitlines()[-1]}")

            upload_path = convert_for_upload(
                download_path,
                nhis_data=nhis_data,
                nps_member_data=nps_member_data,
                nps_retro_data=nps_retro_data,
                nps_govt_data=nps_govt_data,
                ei_support_data=ei_support_data,
                ei_collect_data=ei_collect_data,
            )
            state.after_step(job_id, "convert_excel", {"path": upload_path})
        else:
            step_data = state.get_step_data(job_id, "convert_excel")
            upload_path = step_data.get("path", "")

        if not upload_path or not os.path.exists(upload_path):
            state.fail_step(job_id, "convert_excel", "변환 파일 없음")
            return False

        # ── Step 6: 엑셀 업로드 ───────────────────────────────────────
        if not state.should_skip_step(job_id, "upload_excel"):
            state.before_step(job_id, "upload_excel", 6)
            success = await upload_excel(page, upload_path, dry_run=dry_run)
            if not success:
                state.fail_step(job_id, "upload_excel", "업로드 실패")
                return False
            state.after_step(job_id, "upload_excel")

        return True

    # ── 헬퍼 ───────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_insurance_dir(desktop, period, folder,
                               standalone_site, portal_subdir):
        """보험 원천데이터 디렉토리 경로 리졸브 (단독 우선 → 병렬 폴백).

        1) 단독 실행: ~/Desktop/{standalone_site}_{period}/{folder}/
        2) 병렬 실행: ~/Desktop/{PARALLEL_SAVE_SITE}_{period}/{folder}/{portal_subdir}/
           (PARALLEL_SAVE_SITE="공단EDI")

        단독 경로를 먼저 보고, 없으면 병렬(공단EDI) 경로로 폴백.
        각 보험이 독립적으로 호출하므로 단독·병렬 혼용(NHIS는 단독, NPS는 공단EDI 등)도 커버.
        둘 다 없으면 None 반환.
        """
        standalone = os.path.join(desktop, f"{standalone_site}_{period}", folder)
        if os.path.isdir(standalone):
            return standalone
        if portal_subdir:
            parallel = os.path.join(
                desktop, f"{PARALLEL_SAVE_SITE}_{period}", folder, portal_subdir)
            if os.path.isdir(parallel):
                return parallel
        return None

    @staticmethod
    def _locate_raw_data(client_name: str, year, month) -> dict | None:
        """Phase 2/3/고용보험 raw data 파일 경로 탐색 (단독·병렬 양경로 지원).

        바탕화면에서 건강보험 PDF, 국민연금 Excel, 고용보험 xls를 찾아 dict로 반환.
        단독 실행 경로({보험}_{period}/{folder}/)를 먼저 보고,
        없으면 병렬 실행 경로(공단EDI_{period}/{folder}/{포털}/)로 폴백.
        파일이 없으면 해당 키의 값이 None.

        Returns:
            {"nhis_pdf", "nps_integrated", "nps_member", "nps_retro",
             "nps_govt", "ei_xls"} 중 찾은 것만 값 채움. 전부 None이면 None.
        """
        import glob
        from src.automation.wehago._common import log

        desktop = get_desktop_path()
        folder = client_name.replace(" ", "_")
        period = f"{year}{int(month):02d}" if year and month else None

        if not period:
            log(f"  [원천데이터 탐색] period 미확정(year={year} month={month}) → 스킵")
            return None

        log(f"  [원천데이터 탐색] period={period} folder={folder}")
        log(f"    desktop={desktop}")

        result = {
            "nhis_pdf": None,
            "nps_integrated": None,
            "nps_member": None,
            "nps_retro": None,
            "nps_govt": None,
            "ei_xls": None,
        }

        # 건강보험 PDF
        nhis_dir = WehagoSwsaWorkflow._resolve_insurance_dir(
            desktop, period, folder,
            standalone_site="국민건강보험", portal_subdir="국민건강보험")
        if nhis_dir:
            matches = glob.glob(os.path.join(nhis_dir, "가입자고지내역서_건강_*.pdf"))
            if matches:
                result["nhis_pdf"] = matches[0]
        log(f"    NHIS 디렉토리: {nhis_dir or '미발견'}"
            + (f" → {os.path.basename(result['nhis_pdf'])}" if result["nhis_pdf"] else ""))

        # 국민연금 — 통합엑셀(최종결정내역 통합저장) 우선, 없으면 구 3파일 폴백.
        nps_dir = WehagoSwsaWorkflow._resolve_insurance_dir(
            desktop, period, folder,
            standalone_site="국민연금", portal_subdir="국민연금")
        if nps_dir:
            for f in os.listdir(nps_dir):
                if "결정내역통보서" in f and f.endswith(".xlsx"):
                    result["nps_integrated"] = os.path.join(nps_dir, f)
            # 통합엑셀이 없으면 구 3파일(레거시/롤백 경로)
            if not result["nps_integrated"]:
                for f in os.listdir(nps_dir):
                    full = os.path.join(nps_dir, f)
                    if "가입자내역_엑셀" in f and f.endswith(".xlsx"):
                        result["nps_member"] = full
                    elif "소급분내역_엑셀" in f and f.endswith(".xlsx"):
                        result["nps_retro"] = full
                    elif "국고지원내역_엑셀" in f and f.endswith(".xlsx"):
                        result["nps_govt"] = full
        nps_kind = ("통합엑셀" if result["nps_integrated"]
                    else "구3파일" if (result["nps_member"] or result["nps_retro"]
                                       or result["nps_govt"])
                    else "")
        log(f"    NPS 디렉토리: {nps_dir or '미발견'}"
            + (f" → {nps_kind}" if nps_kind else ""))

        # 고용보험(근로복지공단) xls — 고용보험료지원금정보_{period}.xls
        ei_dir = WehagoSwsaWorkflow._resolve_insurance_dir(
            desktop, period, folder,
            standalone_site="고용보험", portal_subdir="고용보험")
        if ei_dir:
            for f in os.listdir(ei_dir):
                if "고용보험료지원금정보" in f and f.endswith(".xls"):
                    result["ei_xls"] = os.path.join(ei_dir, f)
                    break
        log(f"    EI 디렉토리: {ei_dir or '미발견'}"
            + (f" → {os.path.basename(result['ei_xls'])}" if result["ei_xls"] else ""))

        # 하나라도 있으면 dict 반환, 전부 None이면 None 반환
        found = [k for k, v in result.items() if v]
        log(f"  [원천데이터 탐색] 발견 {len(found)}건: {found or '없음'}")
        if found:
            return result
        return None
