import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp('http://localhost:9222')
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
