"""홈택스 네비게이션 모듈

메뉴 이동, 파일변환신고 페이지 진입, 요소 대기.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from src.utils.log import log
from src.automation.hometax._constants import (
    SELECTOR_MENU_WITHHOLDING,
    SELECTOR_BTN_CBC_MEDI_RTN,
    SELECTOR_BTN_CEN_STS,
    DEFAULT_TIMEOUT_MS,
)
from src.automation.hometax._session import dismiss_modals


async def wait_element(ht, selector, timeout=DEFAULT_TIMEOUT_MS, label=""):
    """요소가 DOM에 나타날 때까지 대기"""
    try:
        await ht.wait_for_selector(selector, timeout=timeout, state="attached")
        return True
    except Exception:
        log(f"  대기 실패: {label or selector}")
        return False


async def goto_withholding_tax(ht):
    """원천세 신고 > 일반신고 메뉴로 이동"""
    log("[1] 원천세 신고 > 일반신고 이동...")
    await ht.evaluate("""() => {
        const a = document.querySelector('#menuAtag_4106010000');
        if (a) a.click();
    }""")
    if not await wait_element(ht, SELECTOR_BTN_CBC_MEDI_RTN, timeout=DEFAULT_TIMEOUT_MS, label="btn_cbcMediRtn"):
        return False
    log(f"  이동 완료: {await ht.title()}")
    return True


async def goto_file_convert(ht):
    """파일변환신고 버튼 클릭하여 이동"""
    log("[2] 파일변환신고 이동...")
    await ht.evaluate("""() => {
        const a = document.querySelector('[id*="btn_cbcMediRtn"]');
        if (a) { a.scrollIntoView({block: 'center'}); }
    }""")
    await asyncio.sleep(1)
    await ht.evaluate("""() => {
        const a = document.querySelector('[id*="btn_cbcMediRtn"]');
        if (a) a.click();
    }""")
    await dismiss_modals(ht)
    if not await wait_element(ht, SELECTOR_BTN_CEN_STS, timeout=DEFAULT_TIMEOUT_MS, label="btn_cenSts"):
        return False
    log("  파일변환신고 페이지 로드")
    return True
