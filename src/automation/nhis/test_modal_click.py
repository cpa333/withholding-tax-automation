import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp('http://localhost:9222')
        page = browser.contexts[0].pages[0]
        
        print_btn = page.locator('button:has-text("출력")').first
        await print_btn.click()
        
        modal = page.locator('#common-CONFIRM-modal')
        await modal.wait_for(state='visible')
        
        buttons = await modal.locator('button').all()
        for b in buttons:
            text = await b.inner_text()
            className = await b.evaluate('el => el.className')
            onclick = await b.evaluate('el => el.getAttribute("onclick")')
            print(f'Button: {text}, Class: {className}, OnClick: {onclick}')
            
        confirm_btn = modal.locator('button', has_text='확인').first
        await confirm_btn.click(force=True)
        print('확인 버튼 클릭함.')
        await asyncio.sleep(5)

asyncio.run(run())
