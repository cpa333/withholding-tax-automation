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
            
            elements = await page.query_selector_all(':text-is("출력")')
            for i, el in enumerate(elements):
                tag = await el.evaluate('el => el.tagName')
                text = await el.inner_text()
                className = await el.evaluate('el => el.className')
                print(f'[{i}] Tag: {tag}, Class: {className}, Text: {text.strip()}')
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(run())
