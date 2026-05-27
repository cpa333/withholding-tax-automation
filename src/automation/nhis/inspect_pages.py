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
            context = browser.contexts[0]
            page = context.pages[0]
            
            print(f"초기 열려있는 페이지 수: {len(context.pages)}")
            
            print_btn = page.locator("button:has-text('출력')").first
            if await print_btn.count() > 0:
                print("출력 버튼 클릭!")
                await print_btn.click()
                
                modal = page.locator('#common-CONFIRM-modal')
                try:
                    await modal.wait_for(state='visible', timeout=5000)
                    print("모달 확인 버튼 클릭")
                    await modal.locator('button:has-text("확인")').click()
                except:
                    pass

                print("10초 대기...")
                await asyncio.sleep(10)
                
                print(f"현재 열려있는 페이지 수: {len(context.pages)}")
                for i, p in enumerate(context.pages):
                    print(f"페이지 {i}: {p.url}")
                    
                # 혹시 다운로드가 발생했는지 확인
                print("브라우저 콘솔에서 에러가 있었는지 확인...")
            else:
                print("출력 버튼을 찾을 수 없음.")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(run())
