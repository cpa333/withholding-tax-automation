"""Workflow 어댑터 베이스 클래스

기존 자동화 함수를 BatchEngine의 workflow_func 시그니처에 맞게 래핑.
각 페이즈는 이 클래스를 상속하여 run_single()만 구현.
"""

from abc import ABC, abstractmethod
from typing import Any

from src.batch.models import Job
from src.batch.state import StateManager


class BaseWorkflow(ABC):
    """포털 자동화 워크플로우 어댑터.

    Attributes:
        phase_id: 페이즈 번호 (1-8)
        portal: Portal enum value ("wehago", "nhis_edi", ...)
        display_name: UI 표시명
        steps: 단계 정의 [{"name": "...", "index": 0}, ...]
        needs_password: UI 비밀번호 필드 필요 여부 (Phase 7, 8)
        is_list_phase: 수임처 리스트 모드 Phase (Phase 1)
        ui_locked: UI 버튼 잠금 여부 (현재 Phase 4~8 임시 비활성)
    """

    phase_id: int = 0
    portal: str = ""
    display_name: str = ""
    steps: list[dict] = []
    # UI/동작 메타데이터 — 매직넘버 분기(main_window/runner) 대체용
    needs_password: bool = False
    is_list_phase: bool = False
    ui_locked: bool = False

    @abstractmethod
    async def run_single(
        self, page, context, client_name: str, job_id: int,
        state: StateManager, **kwargs,
    ) -> bool:
        """단일 수임처에 대한 자동화 실행.

        Args:
            page: Playwright page 객체
            context: Playwright browser context
            client_name: 수임처명
            job_id: Job ID (상태 추적용)
            state: StateManager (체크포인트 관리)
            **kwargs: 페이즈별 추가 파라미터

        Returns:
            True면 성공, False면 실패
        """
        ...

    def as_workflow_func(self, **kwargs):
        """BatchEngine.run()에 전달할 callable 반환.

        BatchEngine은 async def workflow(page, context, job, state_manager) -> bool
        시그니처를 기대하므로, 이 메서드가 그 형태로 변환.
        """
        workflow_self = self

        async def _workflow(page, context, job: Job, state_manager: StateManager,
                            **engine_kwargs) -> bool:
            # 워크플로우 단계 정의 (최초 실행 시에만)
            resume_at = state_manager.get_resume_index(job.id)
            if resume_at == 0:
                state_manager.define_workflow(job.id, workflow_self.steps)

            merged = {**kwargs, **engine_kwargs}
            return await workflow_self.run_single(
                page, context, job.client_name, job.id, state_manager, **merged,
            )

        _workflow.__name__ = f"{self.__class__.__name__}.as_workflow_func"
        return _workflow
