"""Phase 2: 국민건강보험 EDI PDF 다운로드 어댑터"""

from src.workflows.registry import register
from src.workflows.base import BaseWorkflow
from src.batch.state import StateManager


@register(
    phase_id=3,
    portal="nhis_edi",
    display_name="국민건강보험 EDI",
)
class NhisEdiWorkflow(BaseWorkflow):
    steps = [
        {"name": "open_firm_selector", "index": 0},
        {"name": "select_firm", "index": 1},
        {"name": "close_firm_popup", "index": 2},
        {"name": "run_workflow", "index": 3},
        {"name": "cleanup_tabs", "index": 4},
    ]

    async def run_single(
        self, page, context, client_name: str, job_id: int,
        state: StateManager, management_number: str = "", **kwargs,
    ) -> bool:
        from src.automation.nhis._common_edi import (
            close_popups, open_firm_selector, select_firm, close_firm_popup,
            run_single_firm_workflow, _close_edi_tabs, reset_main_page,
        )
        import asyncio
        from src.utils.human import human_delay

        year = kwargs.get("year")
        month = kwargs.get("month")

        # 매 실행 전 팝업 닫기 + 메인 페이지 확보
        main_page = await close_popups(context)
        if not main_page:
            main_page = page

        # PAGE RESET — 이전 수임처(성공/not-found/예외 무관)가 남긴 stale 상태를
        # 지우고 로그인 사업장(retrieveMain)에서 시작. we_btn_relogin 복귀가
        # run_single_firm_workflow 안에서만 일어나 not-found 시 생략되므로, 그대로
        # 두면 다음 수임처의 select_firm 클릭이 no-op 가 되어 N+1 lag 가 발생한다.
        # 매 시작에 페이지를 리셋해 이 state-bleed 를 근본 차단.
        await reset_main_page(main_page)
        await human_delay(3)

        # 사업장 선택 팝업 열기
        if not state.should_skip_step(job_id, "open_firm_selector"):
            state.before_step(job_id, "open_firm_selector", 0)
            popup = await open_firm_selector(main_page, context)
            if not popup:
                state.fail_step(job_id, "open_firm_selector", "사업장 선택 팝업 열기 실패")
                return False
            state.after_step(job_id, "open_firm_selector")
        else:
            popup = await open_firm_selector(main_page, context)

        # 사업장 검색/선택
        if not state.should_skip_step(job_id, "select_firm"):
            state.before_step(job_id, "select_firm", 1)
            ok = await select_firm(popup, client_name, management_number)
            if not ok:
                state.fail_step(job_id, "select_firm", f"'{client_name}' 선택 실패")
                await close_firm_popup(context, popup)
                return False
            state.after_step(job_id, "select_firm")

        # 팝업 닫기
        if not state.should_skip_step(job_id, "close_firm_popup"):
            state.before_step(job_id, "close_firm_popup", 2)
            await close_firm_popup(context, popup)
            await human_delay(3)
            state.after_step(job_id, "close_firm_popup")

        # 워크플로우 실행
        workflow_ok = True
        if not state.should_skip_step(job_id, "run_workflow"):
            state.before_step(job_id, "run_workflow", 3)
            try:
                result = await run_single_firm_workflow(main_page, context, client_name,
                                                         year=year, month=month)
                if result:
                    state.after_step(job_id, "run_workflow")
                else:
                    # PDF 다운로드 실패를 성공으로 위장하지 않는다(masking 방지).
                    # not-found 다음 수임처가 잘못된/없는 자료로 끝난 경우도 여기서 걸림.
                    state.fail_step(job_id, "run_workflow", "PDF 다운로드 실패")
                    workflow_ok = False
            except Exception as e:
                state.fail_step(job_id, "run_workflow", str(e))
                workflow_ok = False

        # 탭 정리 — 성공/실패 무관 항상 실행(다음 수임처를 위한 clean state)
        if not state.should_skip_step(job_id, "cleanup_tabs"):
            state.before_step(job_id, "cleanup_tabs", 4)
            await _close_edi_tabs(context)
            state.after_step(job_id, "cleanup_tabs")

        return workflow_ok
