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
        
        page.on('console', lambda msg: print(f'Console: {msg.text}'))
        
        print_btn = page.locator('button:has-text("출력")').first
        await print_btn.click()
        
        modal = page.locator('#common-CONFIRM-modal')
        await modal.wait_for(state='visible')
        
        confirm_btn = modal.locator('button:has-text("확인")').first
        await confirm_btn.click(force=True)
        await asyncio.sleep(5)

asyncio.run(run())
