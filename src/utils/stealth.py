"""Stealth utilities for CDP-connected browser sessions.

Provides page-level anti-detection patches applied after connect_over_cdp().
Only lightweight measures needed -- this project uses a real Chrome profile
with human-in-the-loop login, so fingerprint spoofing is counterproductive.

Key design: real Chrome + real profile already has correct fingerprint values.
Overwriting them (WebGL vendor, hardwareConcurrency) creates inconsistencies
that are themselves a detection signal. We only patch what's genuinely wrong:
navigator.webdriver and automation artifacts.
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

    For real Chrome + real profile environments, only patches automation
    artifacts (navigator.webdriver). Fingerprint values (GPU, cores, etc.)
    are left as-is because overwriting correct values creates inconsistencies.
    """
    try:
        from playwright_stealth import Stealth
        s = Stealth(
            navigator_webdriver=True,
            navigator_plugins=True,
            navigator_permissions=True,
            navigator_vendor=True,
            chrome_app=True,
            chrome_csi=True,
            chrome_load_times=True,
            hairline=True,
            iframe_content_window=True,
            error_prototype=True,
            webgl_vendor=False,                    # 실제 GPU 정보 유지
            navigator_hardware_concurrency=False,   # 실제 코어 수 유지
            navigator_platform=False,               # 실제 platform 유지
            navigator_platform_override=None,
            navigator_languages=False,              # 실제 언어 유지
            navigator_languages_override=None,
            navigator_user_agent=False,             # 실제 UA 유지
            navigator_user_agent_data=False,        # 실제 Client Hints 유지
            sec_ch_ua=False,                        # 실제 Sec-CH-UA 유지
            media_codecs=False,                     # 실제 코덱 유지
            chrome_runtime=False,                   # 확장 충돌 방지
        )
        await s.apply_stealth_async(page)
    except Exception:
        # playwright-stealth 미설치 또는 런타임 오류 시 수동 폴백
        try:
            await page.add_init_script(_WEBDRIVER_OVERRIDE)
        except Exception:
            pass
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
