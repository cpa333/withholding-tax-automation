"""원천징수이행상황신고서 (SWTA0101) 자동화

SWTA0101 이동 → 매월/반기 확인 → 기간 설정 → 조회 → 마감/마감해제.

사전 조건:
- page가 이미 SmartA 급여 페이지에 있어야 함
- Chrome CDP 모드(port 9223) 실행 상태
"""
import asyncio
import sys
from datetime import datetime

from src.automation.wehago._common import (
    log, dismiss_dialogs, goto_menu_page, get_report_period_type,
    set_period_fields, compute_target_period, click_menu,
)


async def run_swta0101(page):
    """원천징수이행상황신고서 자동화

    Args:
        page: SmartA 페이지에 위치한 Playwright page
    """
    # [0] SPA 라우팅 초기화: SWSA0101 사이드바 클릭
    log("[SWTA0101] 급여자료입력(SWSA0101) 사이드바 클릭 (SPA 라우팅 초기화)...")
    await click_menu(page, "SWSA0101")
    await asyncio.sleep(3)
    await dismiss_dialogs(page)

    # [1] SWTA0101 이동
    log("[SWTA0101] 원천징수이행상황신고서 이동...")
    await goto_menu_page(page, "SWTA0101")
    await asyncio.sleep(3)
    await dismiss_dialogs(page)

    # [2] 매월/반기 확인
    log("[SWTA0101] 신고유형 확인...")
    period_type = await get_report_period_type(page)
    log(f"  신고유형: {period_type}")

    # [3] 기간 설정
    year, month = compute_target_period()
    if period_type == "매월":
        log(f"[SWTA0101] 매월 → {year}년 {month:02d}월")
        await set_period_fields(page, year, month, month)
    elif period_type == "반기":
        current_month = datetime.now().month
        if current_month >= 7:
            log(f"[SWTA0101] 반기 → {year}년 07월 ~ 12월")
            await set_period_fields(page, year, 7, 12)
        else:
            log(f"[SWTA0101] 반기 → {year}년 01월 ~ 06월")
            await set_period_fields(page, year, 1, 6)
    else:
        log(f"  알 수 없는 신고유형: {period_type}")
        return

    # [4] 조회 버튼 클릭
    log("[SWTA0101] 조회 버튼 클릭...")
    await page.evaluate("""() => {
        const btns = document.querySelectorAll('#Search button');
        for (const btn of btns) {
            if (btn.textContent.trim() === '조회' && btn.getBoundingClientRect().width > 0) {
                btn.click();
                return true;
            }
        }
        return false;
    }""")
    await asyncio.sleep(3)

    # [5] 마감/마감해제 버튼 처리
    log("[SWTA0101] 마감 상태 확인...")
    btn_text = await page.evaluate("""() => {
        const btns = document.querySelectorAll('.WSC_LUXTooltip button.WSC_LUXButton');
        for (const btn of btns) {
            const text = btn.textContent.trim();
            if (text === '마감' || text === '마감해제') return text;
        }
        return null;
    }""")

    if btn_text == "마감":
        log("  마감 버튼 클릭 (마감해제)...")
        await page.evaluate("""() => {
            const btns = document.querySelectorAll('.WSC_LUXTooltip button.WSC_LUXButton');
            for (const btn of btns) {
                if (btn.textContent.trim() === '마감') { btn.click(); return; }
            }
        }""")
        await asyncio.sleep(1)
    elif btn_text == "마감해제":
        log("  이미 마감해제 상태 - 스킵")
    else:
        log(f"  마감 버튼 상태: {btn_text}")

    await dismiss_dialogs(page)
    log("[SWTA0101] 완료")


# ═══════════════════════════════════════════════════════════════════════
# 독립 실행
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import io
    import os

    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')

    async def _main():
        from playwright.async_api import async_playwright
        from src.utils.chrome_cdp import launch_chrome, connect_page
        from src.automation.wehago._common import (
            wait_for_login, goto_salary_page, click_menu,
        )

        company = input("수임처 이름: ").strip()
        if not company:
            print("수임처 이름이 필요합니다.")
            return

        launch_chrome()
        async with async_playwright() as p:
            browser, context, page = await connect_page(p)
            if not await wait_for_login(page):
                return
            await dismiss_dialogs(page)
            if not await goto_salary_page(page, company):
                return
            await dismiss_dialogs(page)

            await run_swta0101(page)

    asyncio.run(_main())
