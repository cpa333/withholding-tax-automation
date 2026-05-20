import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp('http://localhost:9222')
            page = browser.contexts[0].pages[0]
            
            # window.open 오버라이드
            await page.evaluate('''
                window.originalOpen = window.open;
                window.interceptedUrls = [];
                window.open = function(url, name, specs) {
                    window.interceptedUrls.push(url);
                    return window.originalOpen(url, name, specs);
                };
            ''')
            
            print_btn = page.locator('button:has-text("출력")').first
            await print_btn.click()
            
            modal = page.locator('#common-CONFIRM-modal')
            try:
                await modal.wait_for(state='visible', timeout=5000)
                await modal.locator('button:has-text("확인")').click()
            except:
                pass
                
            await asyncio.sleep(2)
            urls = await page.evaluate('window.interceptedUrls')
            print('가로챈 팝업 URL들:', urls)
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(run())
