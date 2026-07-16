"""Human-like delay utilities for browser automation anti-detection.

Provides randomized sleep to make automated browser sessions appear
more natural to server-side behavioral analysis.
"""
import asyncio
import os
import random
import sys


# ── Zero-delay 토글 (되돌림 가능) ──────────────────────────────────
# WTAX_NO_DELAY=1/true/yes/on 으로 설정 시 human_delay/human_break 의
# 인위 지연만 즉시 0초가 됨. 폴링 interval/timeout/고정 안정화 asyncio.sleep 은
# 이 플래그와 무관 → 데이터 정합성 보존. anti-detect 를 끄는 것이므로 라이브
# 배치 금지(디버그/단건 검증 전용). 런타임 토글 불가 — 프로세스 재시작 필요.
_NO_DELAY = os.environ.get("WTAX_NO_DELAY", "").strip().lower() in (
    "1", "true", "yes", "on")

if _NO_DELAY:
    _msg = ("[WTAX_NO_DELAY] 인위 지연 0화 모드 활성 — "
            "디버그 전용, 라이브 배치 사용 금지")
    try:
        from src.utils.log import log as _wtax_log
        _wtax_log(_msg)
    except Exception:
        pass
    try:
        print(_msg, file=sys.stderr, flush=True)
    except Exception:
        pass


# ── 느린 네트워크 모드 (설치별 토글) ──────────────────────────────────
# WTAX_SLOW_NETWORK=1/true/yes/on 시 WEHAGO 자동화의 네트워크 민감
# 대기/타임아웃을 NET_DELAY_MULT 배로 연장. 빠른 회선 법인은 기본 1.0.
# human_delay/human_break(anti-detect) 및 폴링 interval/데이터 정합성과 무관 —
# 오직 src/automation/wehago/* 의 네트워크 대기/타임아웃에만 적용.
# 런타임 토글 불가 — 프로세스 재시작 필요.
_SLOW_NETWORK = os.environ.get("WTAX_SLOW_NETWORK", "").strip().lower() in (
    "1", "true", "yes", "on")
NET_DELAY_MULT = 2.5 if _SLOW_NETWORK else 1.0
SLOW_NETWORK = _SLOW_NETWORK  # public bool (점검/표시용)


def net_mult(base: float) -> float:
    """네트워크 대기 배수 적용. slow 모드면 base*NET_DELAY_MULT(2.5), 아니면 base 그대로.

    WEHAGO 자동화의 네트워크 민감 고정 대기/타임아웃(ms) 값에만 사용.
    ms 타임아웃 적용 시 int(net_mult(15000)) 처럼 정수 변환.
    NET_DELAY_MULT 를 호출 시점에 live 조회하므로 set_slow_network() 로 런타임 변경 즉시 반영.
    """
    return base * NET_DELAY_MULT


def set_slow_network(enabled: bool) -> None:
    """런타임에 느린 네트워크 모드 켜기/끄기 (즉시 적용, 프로세스 재시작 불필요).

    net_mult()가 NET_DELAY_MULT를 호출 시점에 live 조회하므로, 이 세터 호출 후 이어지는
    모든 net_mult() 호출에 즉시 반영된다. GUI '설정' 메뉴 체크박스에서 사용.
    초기값은 WTAX_SLOW_NETWORK env(import 시점 1회)이며, 앱 시작 시 GUI 저장값으로 override.
    """
    global NET_DELAY_MULT, SLOW_NETWORK
    enabled = bool(enabled)
    SLOW_NETWORK = enabled
    NET_DELAY_MULT = 2.5 if enabled else 1.0
    try:
        from src.utils.log import log as _wtax_log3
        _wtax_log3(f"[WTAX_SLOW_NETWORK] 느린 네트워크 모드 "
                   f"{'활성' if enabled else '비활성'} — WEHAGO 대기/타임아웃 ×{NET_DELAY_MULT}")
    except Exception:
        pass


if _SLOW_NETWORK:
    _smsg = ("[WTAX_SLOW_NETWORK] 느린 네트워크 모드 활성 — "
             "WEHAGO 대기/타임아웃 ×%.1f" % NET_DELAY_MULT)
    try:
        from src.utils.log import log as _wtax_log2
        _wtax_log2(_smsg)
    except Exception:
        pass
    try:
        print(_smsg, file=sys.stderr, flush=True)
    except Exception:
        pass


async def human_delay(base: float, jitter: float = 0.3) -> None:
    """Sleep for a randomized duration centered on base.

    Args:
        base: Target wait time in seconds.
        jitter: Fractional variation range. 0.3 = ±30%.
                Automatically clamped to 0.15 for sub-1s delays
                to keep short waits functional.

    Formula: uniform(base * (1 - jitter), base * (1 + jitter))
    Example: human_delay(3.0) → 2.1s ~ 3.9s

    WTAX_NO_DELAY 환경변수가 설정된 경우 즉시 반환(지연 없음).
    """
    if _NO_DELAY:
        return
    j = min(jitter, 0.15) if base < 1.0 else jitter
    await asyncio.sleep(random.uniform(base * (1 - j), base * (1 + j)))


async def human_break(
    min_s: float = 5,
    max_s: float = 15,
    check_stop=None,
    check_interval: float = 5,
    log_fn=None,
) -> bool:
    """Pause for a random duration between batches of clients.

    Periodically polls check_stop so the user can interrupt the break.

    Args:
        min_s: Minimum pause duration (seconds).
        max_s: Maximum pause duration (seconds).
        check_stop: Optional callable returning True to abort.
        check_interval: How often to poll check_stop (seconds).
        log_fn: Optional callable for status messages.

    Returns:
        True if break completed naturally, False if interrupted.

    WTAX_NO_DELAY 환경변수가 설정된 경우 휴식 없이 즉시 True 반환.
    """
    if _NO_DELAY:
        if log_fn:
            log_fn("  [휴식] zero-delay 모드: 휴식 생략")
        return True   # 자연 완료 — 배치 루프 카운터/상태 무너짐 없음
    duration = random.uniform(min_s, max_s)
    elapsed = 0.0
    if log_fn:
        log_fn(f"  [휴식] {duration:.0f}초 휴식 중...")
    while elapsed < duration:
        chunk = min(check_interval, duration - elapsed)
        await asyncio.sleep(chunk)
        elapsed += chunk
        if check_stop and check_stop():
            if log_fn:
                log_fn("  [휴식] 사용자 중단으로 휴식 종료")
            return False
    return True
