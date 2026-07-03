"""Phase 6: WEHAGO 원천징수이행상황신고서 (SWTA0101) 어댑터

플로우:
  0. WEHAGO 메인 복귀
  1. 수임처 급여 페이지 진입 (사업자번호 우선 → 이름 fallback)
  2. SWTA0101 마감/마감해제 처리
     - 사용자가 설정한 귀속연도/월(year, month kwargs)을 기간에 반영
     - 매월: 지정월, 반기: 상반기(01~06) 또는 하반기(07~12)
"""

from datetime import datetime

from src.utils.human import human_delay
from src.workflows.registry import register
from src.workflows.base import BaseWorkflow
from src.batch.state import StateManager


@register(
    phase_id=8,
    portal="wehago",
    display_name="WEHAGO 원천이행상황신고서",
    enabled=True,
)
class WehagoSwtaWorkflow(BaseWorkflow):
    steps = [
        {"name": "navigate_to_wehago_main", "index": 0},
        {"name": "goto_salary_page",        "index": 1},
        {"name": "run_swta0101",            "index": 2},
    ]

    async def run_single(
        self, page, context, client_name: str, job_id: int,
        state: StateManager, management_number: str = "", **kwargs,
    ) -> bool:
        from src.automation.wehago._common import (
            ensure_wehago_main, goto_salary_page_with_fallback, log,
        )
        from src.automation.wehago.run_swta0101 import run_swta0101

        year = kwargs.get("year")
        month = kwargs.get("month")
        business_number = kwargs.get("business_number", "")
        report_cycle = kwargs.get("report_cycle", "")   # DB 신고주기 (매월/반기/빈)
        client_id = kwargs.get("client_id")              # 역충전(backfill)용

        # ── 반기 월 필터링(1·7월만) ───────────────────────────────────
        # DB 에 반기로 확정된 수임처는 비신고월에 WEHAGO 탐색 자체를 스킵(효율).
        # 빈 주기 수임처는 run_swta0101 에서 라디오 확정 후 같은 규칙으로 마감만 스킵
        # (라디오 확정값 역충전은 허용).
        if report_cycle == "반기":
            _target_m = month if month else datetime.now().month
            if _target_m not in (1, 7):
                log(f"  [SWTA] 반기 수임처 비신고월({_target_m}월) — 마감 스킵 (반기는 1·7월만)")
                return True

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

        # ── Step 2: SWTA0101 마감 처리 ────────────────────────────────
        # run_swta0101()이 내부적으로 dismiss_dialogs를 포함한
        # 모든 모달 처리를 수행하므로 별도 단계 불필요
        if not state.should_skip_step(job_id, "run_swta0101"):
            state.before_step(job_id, "run_swta0101", 2)
            try:
                used_cycle = await run_swta0101(
                    page, year=year, month=month,
                    report_cycle=report_cycle, client_id=client_id,
                )
                state.after_step(job_id, "run_swta0101")
                # 역충전: DB report_cycle 이 비어있었고 위하고 라디오(ground truth)에서
                # 주기를 얻었으면 DB 에 기록한다(1번 메뉴 DB 와 동일 clients 테이블).
                if (not report_cycle) and used_cycle in ("매월", "반기") and client_id:
                    self._backfill_report_cycle(client_id, used_cycle)
            except Exception as e:
                state.fail_step(job_id, "run_swta0101", str(e))
                return False

        return True

    @staticmethod
    def _backfill_report_cycle(client_id: int, cycle: str) -> None:
        """DB report_cycle 이 비어있을 때 위하고 라디오(ground truth) 값을 역충전.

        새로가져오기(1번)에서 태그가 없어 report_cycle 이 비어있는 수임처를 6번 메딨
        수행 중 라디오로 확정한 값을 DB 에 채운다. 새로가져오기 시 스크랩값으로 덮어씀.
        """
        from src.config import DB_PATH
        from src.batch.db import BatchDB, ClientRepository
        from src.automation.wehago._common import log
        try:
            with BatchDB(DB_PATH) as db:
                ClientRepository(db).update_report_cycle(client_id, cycle)
            log(f"  [SWTA] 신고주기 역충전 DB 기록: client_id={client_id} → {cycle}")
        except Exception as e:
            log(f"  [SWTA] 신고주기 역충전 실패: {e}")
