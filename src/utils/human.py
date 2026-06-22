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
