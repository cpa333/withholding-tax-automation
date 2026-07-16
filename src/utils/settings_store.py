"""사용자 환경설정 영속 저장 (APP_DATA_DIR/app_settings.json).

updater.py 의 _load_prefs/_save_prefs 패턴과 동일 — 업데이트/제거에도 보존되도록
설치 폴더 밖(%LOCALAPPDATA%/원천징수자동화-data)에 저장.
현재 키: slow_network (bool) — WEHAGO 느린 네트워크 모드.
"""
import json
import os

from src.config import APP_DATA_DIR

_SETTINGS_PATH = os.path.join(APP_DATA_DIR, "app_settings.json")


def _load() -> dict:
    try:
        with open(_SETTINGS_PATH, encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(d: dict) -> bool:
    try:
        os.makedirs(APP_DATA_DIR, exist_ok=True)
        with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def get_slow_network() -> bool:
    """저장된 느린 네트워크 모드 설정. 기본 False (빠른 회선 = 기본 속도)."""
    return bool(_load().get("slow_network", False))


def set_slow_network_flag(enabled: bool) -> bool:
    """느린 네트워크 모드 설정을 영속 저장 (즉시 적용은 human.set_slow_network 가 담당)."""
    d = _load()
    d["slow_network"] = bool(enabled)
    return _save(d)
