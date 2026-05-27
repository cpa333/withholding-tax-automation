"""Stealth utilities for CDP-connected browser sessions.

Provides page-level anti-detection patches applied after connect_over_cdp().
Only lightweight measures needed -- this project uses a real Chrome profile
with human-in-the-loop login, so fingerprint spoofing is counterproductive.
"""
import asyncio

from playwright.async_api import Page

_WEBDRIVER_OVERRIDE = """
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
    });
"""


async def apply_stealth(page: Page) -> None:
    """Apply stealth patches to a single page.

    Uses playwright-stealth for navigator.webdriver removal and
    other lightweight JS-level patches. Falls back to manual override
    if playwright-stealth is not installed or fails at runtime.
    """
    try:
        from playwright_stealth import stealth_async
        await stealth_async(page)
    except Exception:
        # playwright-stealth 미설치 또는 런타임 오류 시 수동 폴백
        try:
            await page.add_init_script(_WEBDRIVER_OVERRIDE)
        except Exception:
            pass
        # 현재 페이지에도 즉시 적용
        try:
            await page.evaluate(_WEBDRIVER_OVERRIDE)
        except Exception:
            pass


async def _stealth_new_page(page: Page) -> None:
    """Callback: apply stealth to pages opened by the site."""
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=10000)
    except Exception:
        pass
    await apply_stealth(page)


def register_auto_stealth(context) -> None:
    """Register callback to auto-apply stealth to new tabs opened by the site."""
    context.on("page", lambda pg: asyncio.create_task(_stealth_new_page(pg)))


async def stealth_all_pages(context) -> None:
    """Apply stealth to all existing pages in a context."""
    for pg in context.pages:
        try:
            await apply_stealth(pg)
        except Exception:
            pass
