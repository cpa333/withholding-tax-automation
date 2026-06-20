"""페이즈 레지스트리 — phase_id → Workflow 클래스 매핑"""

from src.workflows.base import BaseWorkflow


# phase_id → (workflow_class, portal, display_name)
_PHASE_REGISTRY: dict[int, dict] = {}


def register(phase_id: int, portal: str, display_name: str, *, enabled: bool = True,
             needs_password: bool = False, is_list_phase: bool = False,
             ui_locked: bool = False):
    """워크플로우 클래스를 레지스트리에 등록하는 데코레이터.

    capability 메타데이터(needs_password/is_list_phase/ui_locked)는
    UI 분기(main_window/automation_runner)에서 매직넘버(phase_id==1/7/8)를
    대체하는 데 사용. 동작 자체는 변경하지 않는다.
    """
    def decorator(cls):
        cls.phase_id = phase_id
        cls.portal = portal
        cls.display_name = display_name
        cls.needs_password = needs_password
        cls.is_list_phase = is_list_phase
        cls.ui_locked = ui_locked
        _PHASE_REGISTRY[phase_id] = {
            "class": cls,
            "portal": portal,
            "display_name": display_name,
            "enabled": enabled,
            "needs_password": needs_password,
            "is_list_phase": is_list_phase,
            "ui_locked": ui_locked,
        }
        return cls
    return decorator


def get_workflow(phase_id: int) -> BaseWorkflow | None:
    """phase_id에 해당하는 워크플로우 인스턴스 반환."""
    entry = _PHASE_REGISTRY.get(phase_id)
    if not entry:
        return None
    return entry["class"]()


def get_phase_info(phase_id: int) -> dict | None:
    """phase_id에 해당하는 페이즈 정보 반환."""
    return _PHASE_REGISTRY.get(phase_id)


def get_all_phases() -> list[dict]:
    """모든 등록된 페이즈 정보를 phase_id 순으로 반환."""
    return [
        {
            "phase_id": pid,
            "display_name": info["display_name"],
            "portal": info["portal"],
            "enabled": info["enabled"],
            "needs_password": info.get("needs_password", False),
            "is_list_phase": info.get("is_list_phase", False),
            "ui_locked": info.get("ui_locked", False),
        }
        for pid, info in sorted(_PHASE_REGISTRY.items())
    ]
