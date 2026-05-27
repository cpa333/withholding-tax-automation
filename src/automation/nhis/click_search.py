import asyncio
import os
import sys
from playwright.async_api import async_playwright

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)
from src.utils.chrome_cdp import CDP_URL

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        page = browser.contexts[0].pages[0]
        
        search_btn = page.locator("a:has-text('검색')").last
        print('검색 버튼 클릭...')
        await search_btn.scroll_into_view_if_needed()
        await search_btn.click()
        await asyncio.sleep(3)
        print('조회 완료')

if __name__ == "__main__":
    asyncio.run(run())
