"""SWSA0101 귀속연월 설정 모듈 (React LS_calendar)

SWSA0101은 SWTA/SWER와 다른 React 기반 달력(LS_calendar)을 사용.
Playwright locator.click으로 캘린더 열고, React setState로 연도 변경 후 월 선택.
"""

import asyncio
import sys

from src.automation.wehago._common import log, _safe_evaluate
from src.automation.wehago._swsa_constants import (
    _READ_SWSA_YM_JS,
    _READ_CALENDAR_YEAR_JS,
    _REACT_SET_CALENDAR_YEAR_JS,
)


async def set_swsa_ym(page, year: int, month: int) -> bool:
    """SWSA0101 귀속연월 설정 (React LS_calendar component)

    SWSA0101은 SWTA/SWER와 다른 React 기반 달력(LS_calendar)을 사용.
    Playwright locator.click으로 캘린더 열고, React setState로 연도 변경 후 월 선택.

    Args:
        page: SWSA0101 페이지에 위치한 Playwright page
        year: 목표 연도 (예: 2026)
        month: 목표 월 (1-12)

    Returns:
        True if 귀속연월 설정 성공, False otherwise
    """
    target_ym = f"{year}.{month:02d}"

    for attempt in range(3):
        log(f"    [귀속연월] 시도 {attempt+1}/3: {target_ym}")

        # ── 현재 값 읽기 ──────────────────────────────────────
        cur_ym = await _safe_evaluate(page, _READ_SWSA_YM_JS)
        if cur_ym == target_ym:
            log(f"    [귀속연월] 이미 {target_ym} — 스킵")
            return True

        log(f"    [귀속연월] 현재: {cur_ym} → 목표: {target_ym}")

        # ── 캘린더 열기 (반드시 Playwright click — JS evaluate는 합성 이벤트) ──
        try:
            await page.locator(
                "#SearchMain .item:first-child .fakebutton"
            ).click(timeout=5000)
            await asyncio.sleep(1)
        except Exception as e:
            log(f"    [귀속연월] 캘린더 열기 실패: {e}")
            await asyncio.sleep(1)
            continue

        # ── 연도 확인 및 React setState ──────────────────────
        cal_yr_text = await _safe_evaluate(page, _READ_CALENDAR_YEAR_JS)
        if not cal_yr_text:
            log("    [귀속연월] 캘린더 연도 읽기 실패")
            await asyncio.sleep(1)
            continue

        try:
            cal_yr = int(cal_yr_text)
        except (ValueError, TypeError):
            cal_yr = None

        if cal_yr is not None and cal_yr != year:
            log(f"    [귀속연월] React setState: {cal_yr} → {year}")
            result = await _safe_evaluate(
                page, _REACT_SET_CALENDAR_YEAR_JS, year,
            )
            if not result or not result.get("success"):
                log(f"    [귀속연월] React setState 실패: {result}")
                await asyncio.sleep(1)
                continue
            await asyncio.sleep(1)

            # 연도 변경 확인
            new_cal_yr = await _safe_evaluate(page, _READ_CALENDAR_YEAR_JS)
            if new_cal_yr != str(year):
                log(f"    [귀속연월] 연도 변경 확인 실패: {new_cal_yr}")
                await asyncio.sleep(1)
                continue

        # ── 월 클릭 ──────────────────────────────────────────
        try:
            month_btn = page.locator(
                f'.LS_calendar td.date_day button:has-text("{month}월")'
            )
            await month_btn.first.click(timeout=3000)
            await asyncio.sleep(1)
        except Exception as e:
            log(f"    [귀속연월] {month}월 클릭 실패: {e}")
            await asyncio.sleep(1)
            continue

        # ── 최종 검증 ────────────────────────────────────────
        final_ym = await _safe_evaluate(page, _READ_SWSA_YM_JS)
        if final_ym == target_ym:
            log(f"    [귀속연월] 설정 완료: {target_ym}")
            return True

        log(f"    [귀속연월] 검증 실패: {final_ym} (예상: {target_ym})")
        await asyncio.sleep(1)

    log(f"    [귀속연월] 3회 재시도 후 실패")
    return False
