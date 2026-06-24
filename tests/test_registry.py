"""phase 레지스트리 회귀 테스트 — Wave 2(phase_id 메타데이터화) 기준선."""
import pytest

from src.workflows import registry
from src.workflows.base import BaseWorkflow
from src.workflows.registry import get_all_phases, get_phase_info, get_workflow


def test_register_get_info_get_workflow_mechanics():
    """레지스트리 기본 메커니즘(가벼운 더미 클래스로 검증, 무거운 의존성 없음)."""
    @registry.register(901, "test_portal", "테스트 페이즈", enabled=True)
    class _DummyWorkflow(BaseWorkflow):
        steps = []

        async def run_single(self, page, context, client_name, job_id,
                             state, **kwargs):
            return True

    try:
        info = get_phase_info(901)
        assert info is not None
        assert info["portal"] == "test_portal"
        assert info["display_name"] == "테스트 페이즈"
        assert info["enabled"] is True

        wf = get_workflow(901)
        assert isinstance(wf, _DummyWorkflow)
        assert wf.phase_id == 901

        phases = get_all_phases()
        assert any(p["phase_id"] == 901 for p in phases)
    finally:
        registry._PHASE_REGISTRY.pop(901, None)


def test_real_eight_phases_registered_in_order():
    """실제 8개 워크플로우가 phase_id 1~8 순으로 등록되는지(무거운 import 실패 시 skip)."""
    try:
        import src.workflows.wehago_list_clients  # noqa: F401
        import src.workflows.nhis_edi             # noqa: F401
        import src.workflows.nps_edi              # noqa: F401
        import src.workflows.wehago_swsa          # noqa: F401
        import src.workflows.wehago_salary_pdf    # noqa: F401
        import src.workflows.wehago_swta          # noqa: F401
        import src.workflows.wehago_swer          # noqa: F401
        import src.workflows.hometax              # noqa: F401
    except Exception as e:  # Playwright/pywinauto 등 의존성 미충족 시
        pytest.skip(f"워크플로우 모듈 import 불가(의존성): {e}")

    ids = [p["phase_id"] for p in get_all_phases()]
    # 병렬 phase(2)는 테스트에서 등록 안 함(main_window 에서만). 8개 워크플로우 = phase_id 1,3..9.
    assert ids[:8] == [1, 3, 4, 5, 6, 7, 8, 9]
    for pid in (1, 3, 4, 5, 6, 7, 8, 9):
        assert get_phase_info(pid) is not None
        assert get_workflow(pid) is not None

    # capability 메타데이터 검증 — phase 2(병렬)은 테스트 미등록
    assert get_phase_info(1)["is_list_phase"] is True
    assert get_phase_info(3)["is_list_phase"] is False
    # 병렬 EDI 안정화 후 모든 phase 재활성화 — ui_locked=False
    for pid in (1, 3, 4, 5, 6, 7, 8, 9):
        assert get_phase_info(pid)["ui_locked"] is False, f"phase {pid} 활성 기대"
    assert get_phase_info(8)["needs_password"] is True
    assert get_phase_info(9)["needs_password"] is True
    for pid in (1, 3, 4, 5, 6, 7):
        assert get_phase_info(pid)["needs_password"] is False
