"""Phase 10: 근로복지공단(고용보험) EDI 인쇄물 다운로드 어댑터

엑셀 v3 (C86~H106) 워크플로우 + 라이브 검증(2026-07) 기반.
위하고 급여자료입력 병합(실업급여지원금/환수금 반영)은 다음 작업으로 분리 —
본 어댑터는 raw data(고용보험료 지원금 정보 인쇄물) 다운로드까지만 담당.

수임처별 흐름 (라이브 검증):
  0. 부과고지 보험료 조회(20209) 화면 진입 (메인 대시보드 퀵메뉴)
  1. 부과년도/부과월 설정 (GUI 연도/월 반영)
  2. 사업장 전환 (관리번호=사업자번호+0 입력 → 사업장조회 → 팝업 선택)
  3. 고용 탭 → 사회보험료 지원금정보 팝업 → 인쇄하기 (새 창 리포트 뷰어)

저장: ~/Desktop/고용보험_{YYYYMM}/{수임처}/
"""

from src.workflows.registry import register
from src.workflows.base import BaseWorkflow
from src.batch.state import StateManager


@register(
    phase_id=5,
    portal="comwel_edi",
    display_name="고용보험 EDI",
)
class ComwelEdiWorkflow(BaseWorkflow):
    steps = [
        {"name": "navigate_to_20209", "index": 0},
        {"name": "set_period",        "index": 1},
        {"name": "switch_workplace",  "index": 2},
        {"name": "search_main",       "index": 3},
        {"name": "print_download",    "index": 4},
        {"name": "cleanup",           "index": 5},
    ]

    async def run_single(
        self, page, context, client_name: str, job_id: int,
        state: StateManager, management_number: str = "", **kwargs,
    ) -> bool:
        from src.automation.comwel._common import (
            navigate_to_premium_20209, set_period,
            switch_workplace, search_main, dismiss_dialogs,
        )
        from src.automation.comwel._download import download_support_info_printout
        from src.utils.human import human_delay

        year = kwargs.get("year")
        month = kwargs.get("month")

        # 0) 부과고지 보험료 조회(20209) 화면 진입
        if not state.should_skip_step(job_id, "navigate_to_20209"):
            state.before_step(job_id, "navigate_to_20209", 0)
            ok = await navigate_to_premium_20209(page)
            if not ok:
                state.fail_step(job_id, "navigate_to_20209", "20209 화면 진입 실패")
                return False
            await human_delay(2)
            state.after_step(job_id, "navigate_to_20209")

        # 1) 부과년도/부과월 설정
        if not state.should_skip_step(job_id, "set_period"):
            state.before_step(job_id, "set_period", 1)
            if year is not None and month is not None:
                ok = await set_period(page, year, month)
                if not ok:
                    state.fail_step(job_id, "set_period", "부과기간 설정 실패")
                    return False
            state.after_step(job_id, "set_period")

        # 2) 사업장 전환
        if not state.should_skip_step(job_id, "switch_workplace"):
            state.before_step(job_id, "switch_workplace", 2)
            ok = await switch_workplace(page, client_name, management_number)
            if not ok:
                state.fail_step(job_id, "switch_workplace",
                                f"'{client_name}' 전환 실패")
                return False
            await human_delay(2)
            state.after_step(job_id, "switch_workplace")

        # 3) 본 화면 조회(btnSearch) — 사업장 선택 후 데이터 로드 (라이브 검증)
        if not state.should_skip_step(job_id, "search_main"):
            state.before_step(job_id, "search_main", 3)
            ok = await search_main(page)
            if not ok:
                state.fail_step(job_id, "search_main", "본 화면 조회 실패")
                return False
            state.after_step(job_id, "search_main")

        # 4) 고용 탭 → 지원금정보 팝업 → 인쇄하기
        # 폴더는 download_support_info_printout 내부에서 데이터 있을 때만 생성
        # (0건 수임처는 빈 폴더도 만들지 않음).
        download_ok = True
        if not state.should_skip_step(job_id, "print_download"):
            state.before_step(job_id, "print_download", 4)
            try:
                result = await download_support_info_printout(
                    page, context, client_name, year=year, month=month,
                )
                if result.get("path"):
                    # 파일 다운로드 성공
                    state.after_step(job_id, "print_download")
                elif result.get("skipped"):
                    # 지원금 데이터 0건 — 인쇄 생략(정상). 라이브 검증.
                    state.after_step(job_id, "print_download")
                elif result.get("print_clicked"):
                    # 인쇄 버튼은 눌렀으나 파일 저장 미확인(리포트 뷰어 새 창)
                    state.after_step(job_id, "print_download")
                else:
                    state.fail_step(job_id, "print_download",
                                    "지원금정보 팝업/인쇄 버튼 진입 실패")
                    download_ok = False
            except Exception as e:
                state.fail_step(job_id, "print_download", str(e))
                download_ok = False

        # 5) 정리 — 성공/실패 무관 항상 실행
        if not state.should_skip_step(job_id, "cleanup"):
            state.before_step(job_id, "cleanup", 5)
            await dismiss_dialogs(page)
            state.after_step(job_id, "cleanup")

        return download_ok
