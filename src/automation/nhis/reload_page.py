import asyncio
import os
import sys
from playwright.async_api import async_playwright

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)
from src.utils.chrome_cdp import CDP_URL

async def run():
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
            page = browser.contexts[0].pages[0]
            print("페이지 새로고침 중...")
            await page.reload()
            print("페이지 새로고침 완료.")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(run())
