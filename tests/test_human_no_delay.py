"""human.py zero-delay 토글(WTAX_NO_DELAY) 회귀 테스트.

검증:
1. WTAX_NO_DELAY 설정 → human_delay/human_break 즉시 반환(시간 측정).
2. 미설정 → 기존처럼 sleep(asyncio.sleep mock 으로 지연 호출 확인).
3. truthy/falsy 값 파라미터화.
4. toggle/reload 안정성 + 테스트 간 모듈 상태 누수 방지.

pytest.ini 의 pythonpath=. 와 conftest.py 의 sys.path 주입을 그대로 사용.
Playwright/PySide6 미의존 순수 단위테스트.
"""
import asyncio
import importlib
import time

import pytest


def _reload_human(monkeypatch, no_delay_value):
    """env var 설정 후 src.utils.human 을 reload 하여 _NO_DELAY 재평가.

    no_delay_value=None → WTAX_NO_DELAY 미설정(기본 동작).
    """
    if no_delay_value is None:
        monkeypatch.delenv("WTAX_NO_DELAY", raising=False)
    else:
        monkeypatch.setenv("WTAX_NO_DELAY", no_delay_value)
    import src.utils.human as human_mod
    importlib.reload(human_mod)
    return human_mod


@pytest.fixture(autouse=True)
def _reset_human_default(monkeypatch):
    """각 테스트 후 모듈을 기본(_NO_DELAY=False) 상태로 복원.

    reload 로 bake 된 _NO_DELAY 가 monkeypatch env 복원과 무관하게 잔류하지
    않도록, teardown 에서 명시적으로 env 클리어 + reload 한다.
    다른 테스트 모듈(test_nps_* 등)에 _NO_DELAY=True 상태가 누수되는 것 방지.
    """
    yield
    monkeypatch.delenv("WTAX_NO_DELAY", raising=False)
    import src.utils.human as human_mod
    importlib.reload(human_mod)


@pytest.fixture
def human_off(monkeypatch):
    """WTAX_NO_DELAY 미설정(기존 동작)."""
    return _reload_human(monkeypatch, None)


@pytest.fixture
def human_on(monkeypatch):
    """WTAX_NO_DELAY=1 활성."""
    return _reload_human(monkeypatch, "1")


# ── 활성 케이스: 실제 시간 측정 ────────────────────────────────────

def test_human_delay_zero_when_enabled(human_on):
    """활성 시 human_delay(10) 도 수십 ms 이내 반환."""
    t0 = time.perf_counter()
    asyncio.run(human_on.human_delay(10, jitter=0.3))
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.2, f"zero-delay 미동작: {elapsed:.3f}s 소요"


def test_human_break_true_and_fast_when_enabled(human_on):
    """활성 시 human_break 는 즉시 True 반환, check_stop 미호출."""
    called = {"n": 0}

    def stop_fn():
        called["n"] += 1
        return False

    t0 = time.perf_counter()
    result = asyncio.run(human_on.human_break(
        min_s=20, max_s=30, check_stop=stop_fn, check_interval=5,
    ))
    elapsed = time.perf_counter() - t0
    assert result is True
    assert elapsed < 0.2
    assert called["n"] == 0, "zero-delay 시 check_stop 폴링이 호출되면 안 됨"


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "On"])
def test_no_delay_truthy_values(monkeypatch, val):
    mod = _reload_human(monkeypatch, val)
    assert mod._NO_DELAY is True


@pytest.mark.parametrize("val", ["", "0", "false", "no", "off", "  ", "maybe"])
def test_no_delay_falsy_values(monkeypatch, val):
    mod = _reload_human(monkeypatch, val)
    assert mod._NO_DELAY is False


def test_no_delay_unset_default(human_off):
    assert human_off._NO_DELAY is False


# ── 비활성 케이스: asyncio.sleep 이 실제로 호출되는지(mock) ────────

def test_human_delay_sleeps_when_disabled(human_off, monkeypatch):
    """미설정 시 asyncio.sleep 이 양수 인자로 호출된다."""
    sleeps = []
    real_sleep = asyncio.sleep

    async def fake_sleep(t):
        sleeps.append(t)
        await real_sleep(0)  # 실제 대기 없이 양보만(테스트 속도)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    asyncio.run(human_off.human_delay(2.0, jitter=0.0))
    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(2.0, abs=0.01)


def test_human_break_sleeps_and_polls_when_disabled(human_off, monkeypatch):
    """미설정 시 chunk sleep + check_stop 폴링 발생."""
    real_sleep = asyncio.sleep
    sleeps = []
    stops = {"n": 0}

    async def fake_sleep(t):
        sleeps.append(t)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    def stop_fn():
        stops["n"] += 1
        return False

    # min=max=고정 → duration=5, check_interval=5 → chunk 1회
    result = asyncio.run(human_off.human_break(
        min_s=5, max_s=5, check_stop=stop_fn, check_interval=5,
    ))
    assert result is True
    assert len(sleeps) == 1 and sleeps[0] == pytest.approx(5.0, abs=0.01)
    assert stops["n"] == 1


def test_human_break_interrupted_when_disabled(human_off, monkeypatch):
    """미설정 + check_stop True → False 반환."""
    real_sleep = asyncio.sleep

    async def fake_sleep(t):
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    result = asyncio.run(human_off.human_break(
        min_s=5, max_s=5, check_stop=lambda: True, check_interval=5,
    ))
    assert result is False


# ── 되돌림: on/off reload 간 정확 추적 ─────────────────────────────

def test_toggle_off_after_on(monkeypatch):
    """on 리로드 후 off 리로드해도 _NO_DELAY 가 정확히 따라간다."""
    on = _reload_human(monkeypatch, "1")
    assert on._NO_DELAY is True
    off = _reload_human(monkeypatch, None)
    assert off._NO_DELAY is False
