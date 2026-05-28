"""페이즈 레지스트리 — phase_id → Workflow 클래스 매핑"""

from src.workflows.base import BaseWorkflow


# phase_id → (workflow_class, portal, display_name)
_PHASE_REGISTRY: dict[int, dict] = {}


def register(phase_id: int, portal: str, display_name: str):
    """워크플로우 클래스를 레지스트리에 등록하는 데코레이터."""
    def decorator(cls):
        cls.phase_id = phase_id
        cls.portal = portal
        cls.display_name = display_name
        _PHASE_REGISTRY[phase_id] = {
            "class": cls,
            "portal": portal,
            "display_name": display_name,
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
        }
        for pid, info in sorted(_PHASE_REGISTRY.items())
    ]
