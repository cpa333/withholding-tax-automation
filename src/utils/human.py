"""Human-like delay utilities for browser automation anti-detection.

Provides randomized sleep to make automated browser sessions appear
more natural to server-side behavioral analysis.
"""
import asyncio
import random


async def human_delay(base: float, jitter: float = 0.3) -> None:
    """Sleep for a randomized duration centered on base.

    Args:
        base: Target wait time in seconds.
        jitter: Fractional variation range. 0.3 = ±30%.
                Automatically clamped to 0.15 for sub-1s delays
                to keep short waits functional.

    Formula: uniform(base * (1 - jitter), base * (1 + jitter))
    Example: human_delay(3.0) → 2.1s ~ 3.9s
    """
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
    """
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
