"""홈택스 자동화 공통 모듈 — 재export 허브

모든 홈택스 자동화 플로우에서 공유.
이 모듈은 하위 모듈을 재export하여
기존 import를 변경 없이 유지.

하위 모듈:
- _constants.py: 상수 (URL, 선택자, 타임아웃)
- _session.py:   세션 연장 + 모달 자동 처리
- _navigation.py: 메뉴 이동 + 파일변환신고 진입
- _upload.py:    파일 선택 + 파일검증
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

# ─── 상수 재export ───────────────────────────────────────────────────────────
from src.automation.hometax._constants import (
    HOMETAX_URL,
    SELECTOR_MENU_WITHHOLDING,
    SELECTOR_BTN_CBC_MEDI_RTN,
    SELECTOR_BTN_CEN_STS,
    DEFAULT_TIMEOUT_MS,
    SESSION_EXTEND_INTERVAL_S,
)

# ─── 세션 관리 재export ──────────────────────────────────────────────────────
from src.automation.hometax._session import (
    auto_session_extend,
    trigger_session_popup_soon,
    dismiss_modals,
)

# ─── 네비게이션 재export ─────────────────────────────────────────────────────
from src.automation.hometax._navigation import (
    wait_element,
    goto_withholding_tax,
    goto_file_convert,
)

# ─── 업로드 재export ─────────────────────────────────────────────────────────
from src.automation.hometax._upload import (
    select_file,
    verify_file,
)


# ─── 연결 ────────────────────────────────────────────────────────────────────

async def connect_browser(playwright):
    """CDP로 Chrome에 연결하고 홈택스 탭 반환"""
    from src.utils.stealth import stealth_all_pages, register_auto_stealth
    from src.utils.chrome_cdp import CDP_URL

    browser = await playwright.chromium.connect_over_cdp(CDP_URL)
    context = browser.contexts[0]

    await stealth_all_pages(context)
    register_auto_stealth(context)

    for pg in context.pages:
        if "홈택스" in await pg.title():
            return browser, context, pg

    page = await context.new_page()
    await page.goto(HOMETAX_URL, timeout=DEFAULT_TIMEOUT_MS, wait_until="load")
    return browser, context, page
