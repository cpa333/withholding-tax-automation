"""settings_store.py 영속 저장 회귀테스트 (APP_DATA_DIR/app_settings.json).

실제 APP_DATA_DIR 대신 tmp_path 로 격리 — 느린 네트워크 설정의 저장/로드/영속성 검증.
"""
import importlib

import pytest


@pytest.fixture
def store(tmp_path, monkeypatch):
    """격리된 임시 경로로 settings_store 재설정."""
    import src.utils.settings_store as store_mod
    monkeypatch.setattr(store_mod, "_SETTINGS_PATH",
                        str(tmp_path / "app_settings.json"))
    return store_mod


def test_slow_network_default_false(store):
    """설정 파일이 없으면 기본 False (빠른 회선 = 기본 속도)."""
    assert store.get_slow_network() is False


def test_slow_network_roundtrip(store):
    """True 저장 → 읽기 True, False 저장 → 읽기 False."""
    assert store.set_slow_network_flag(True) is True
    assert store.get_slow_network() is True
    assert store.set_slow_network_flag(False) is True
    assert store.get_slow_network() is False


def test_slow_network_persists_to_disk(store, tmp_path):
    """get_slow_network()가 매번 디스크에서 읽음(캐시 아님) → 파일 영속성 보장."""
    store.set_slow_network_flag(True)
    # 파일이 실제로 생성되었는지 확인
    assert (tmp_path / "app_settings.json").exists()
    # 새로운 "프로세스" 모방: 모듈 reload 후 같은 경로에서 읽기
    importlib.reload(store)
    store._SETTINGS_PATH = str(tmp_path / "app_settings.json")
    assert store.get_slow_network() is True
