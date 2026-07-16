"""human.py 느린네트워크 토글(WTAX_SLOW_NETWORK) 회귀 테스트.

검증:
1. WTAX_SLOW_NETWORK 미설정 → NET_DELAY_MULT=1.0, net_mult(base)==base, SLOW_NETWORK=False.
2. WTAX_SLOW_NETWORK 설정 → NET_DELAY_MULT=2.5, net_mult(base)==base*2.5, SLOW_NETWORK=True.
3. truthy/falsy 값 파라미터화.
4. toggle/reload 안정성 + WTAX_NO_DELAY 토글과의 독립성.
5. ms 타임아웃용 int(net_mult(15000)) 정수 변환.

test_human_no_delay.py 와 동일한 reload 패턴. 순수 단위테스트(Playwright/PySide6 미의존).
"""
import importlib

import pytest


def _reload_human(monkeypatch, slow_value, no_delay_value=None):
    """env var 설정 후 src.utils.human 을 reload 하여 _SLOW_NETWORK 재평가.

    slow_value=None → WTAX_SLOW_NETWORK 미설정(기본 동작).
    no_delay_value=None → WTAX_NO_DELAY 미설정.
    """
    if slow_value is None:
        monkeypatch.delenv("WTAX_SLOW_NETWORK", raising=False)
    else:
        monkeypatch.setenv("WTAX_SLOW_NETWORK", slow_value)
    if no_delay_value is None:
        monkeypatch.delenv("WTAX_NO_DELAY", raising=False)
    else:
        monkeypatch.setenv("WTAX_NO_DELAY", no_delay_value)
    import src.utils.human as human_mod
    importlib.reload(human_mod)
    return human_mod


@pytest.fixture(autouse=True)
def _reset_human_default(monkeypatch):
    """각 테스트 후 모듈을 기본 상태(SLOW_NETWORK=False, _NO_DELAY=False)로 복원.

    reload 로 bake 된 상태가 다른 테스트 모듈에 누수되지 않도록 teardown 에서
    env 클리어 + reload.
    """
    yield
    monkeypatch.delenv("WTAX_SLOW_NETWORK", raising=False)
    monkeypatch.delenv("WTAX_NO_DELAY", raising=False)
    import src.utils.human as human_mod
    importlib.reload(human_mod)


@pytest.fixture
def slow_off(monkeypatch):
    return _reload_human(monkeypatch, None)


@pytest.fixture
def slow_on(monkeypatch):
    return _reload_human(monkeypatch, "1")


# ── 비활성(기본): multiplier 1.0 ───────────────────────────────────

def test_default_multiplier_is_one(slow_off):
    assert slow_off.NET_DELAY_MULT == 1.0
    assert slow_off.SLOW_NETWORK is False
    assert slow_off.net_mult(3.0) == pytest.approx(3.0)
    assert slow_off.net_mult(0.5) == pytest.approx(0.5)


def test_default_int_mult_preserves_value(slow_off):
    """비활성 시 int(net_mult(15000))==15000 (타임아웃 값 그대로)."""
    assert int(slow_off.net_mult(15000)) == 15000


# ── 활성: multiplier 2.5 ───────────────────────────────────────────

def test_enabled_multiplier_is_2_5(slow_on):
    assert slow_on.NET_DELAY_MULT == 2.5
    assert slow_on.SLOW_NETWORK is True
    assert slow_on.net_mult(3.0) == pytest.approx(7.5)
    assert slow_on.net_mult(15000) == pytest.approx(37500.0)


def test_enabled_int_mult_for_timeout(slow_on):
    """활성 시 int(net_mult(15000))==37500 (타임아웃 15s→37.5s)."""
    assert int(slow_on.net_mult(15000)) == 37500


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "On"])
def test_slow_truthy_values(monkeypatch, val):
    mod = _reload_human(monkeypatch, val)
    assert mod.SLOW_NETWORK is True
    assert mod.NET_DELAY_MULT == 2.5


@pytest.mark.parametrize("val", ["", "0", "false", "no", "off", "  ", "maybe"])
def test_slow_falsy_values(monkeypatch, val):
    mod = _reload_human(monkeypatch, val)
    assert mod.SLOW_NETWORK is False
    assert mod.NET_DELAY_MULT == 1.0


# ── 되돌림 + 독립성 ───────────────────────────────────────────────

def test_toggle_off_after_on(monkeypatch):
    on = _reload_human(monkeypatch, "1")
    assert on.SLOW_NETWORK is True and on.NET_DELAY_MULT == 2.5
    off = _reload_human(monkeypatch, None)
    assert off.SLOW_NETWORK is False and off.NET_DELAY_MULT == 1.0


def test_independent_of_no_delay(monkeypatch):
    """WTAX_SLOW_NETWORK=1 이 WTAX_NO_DELAY 에 영향 주지 않음(역도 동일)."""
    mod = _reload_human(monkeypatch, "1", no_delay_value=None)
    assert mod.SLOW_NETWORK is True
    assert mod._NO_DELAY is False

    mod2 = _reload_human(monkeypatch, None, no_delay_value="1")
    assert mod2.SLOW_NETWORK is False
    assert mod2._NO_DELAY is True


# ── 런타임 세터: 즉시 적용 (재시작/reload 불필요) ─────────────────

def test_set_slow_network_runtime_on(monkeypatch):
    """set_slow_network(True) 가 net_mult() 에 즉시 반영 (reload 없이)."""
    mod = _reload_human(monkeypatch, None)  # 기본 off
    assert mod.NET_DELAY_MULT == 1.0
    mod.set_slow_network(True)
    assert mod.NET_DELAY_MULT == 2.5
    assert mod.SLOW_NETWORK is True
    assert mod.net_mult(3.0) == pytest.approx(7.5)
    assert int(mod.net_mult(15000)) == 37500


def test_set_slow_network_runtime_off(monkeypatch):
    """set_slow_network(False) 가 켜진 상태에서 즉시 기본값 복귀."""
    mod = _reload_human(monkeypatch, "1")  # env=on 으로 시작
    assert mod.NET_DELAY_MULT == 2.5
    mod.set_slow_network(False)
    assert mod.NET_DELAY_MULT == 1.0
    assert mod.SLOW_NETWORK is False
    assert mod.net_mult(3.0) == pytest.approx(3.0)


def test_set_slow_network_overrides_env(monkeypatch):
    """GUI setter가 env 초기값을 override (in-program 설정이 우선)."""
    mod = _reload_human(monkeypatch, "1")  # env=on → 2.5
    assert mod.NET_DELAY_MULT == 2.5
    mod.set_slow_network(False)  # 사용자가 GUI에서 끔
    assert mod.NET_DELAY_MULT == 1.0  # setter 승리
    mod.set_slow_network(True)
    assert mod.NET_DELAY_MULT == 2.5
