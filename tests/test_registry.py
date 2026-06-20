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
    # 다른 테스트가 임시 phase(901 등)를 등록했을 수 있으므로 1~8 포함 여부만 확인
    assert ids[:8] == [1, 2, 3, 4, 5, 6, 7, 8]
    for pid in range(1, 9):
        assert get_phase_info(pid) is not None
        assert get_workflow(pid) is not None

    # capability 메타데이터 검증 (Wave 2) — 이전 phase_id==1/7/8/>=4 매직넘버와 동등
    assert get_phase_info(1)["is_list_phase"] is True
    assert get_phase_info(2)["is_list_phase"] is False
    for pid in (4, 5, 6, 7, 8):
        assert get_phase_info(pid)["ui_locked"] is True, f"phase {pid} 잠금 기대"
    for pid in (1, 2, 3):
        assert get_phase_info(pid)["ui_locked"] is False, f"phase {pid} 활성 기대"
    assert get_phase_info(7)["needs_password"] is True
    assert get_phase_info(8)["needs_password"] is True
    for pid in (1, 2, 3, 4, 5, 6):
        assert get_phase_info(pid)["needs_password"] is False
