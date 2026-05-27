"""현재 화면 스크린샷 캡처"""
import asyncio, sys, os

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from playwright.async_api import async_playwright
from src.utils.chrome_cdp import CDP_URL

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0]
        page = context.pages[0]

        screenshot_path = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "..", "debug", "current_screen.png"
        ))
        os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)

        await page.screenshot(path=screenshot_path, full_page=False)
        print(f"스크린샷 저장: {screenshot_path}")

        await browser.close()

asyncio.run(main())
