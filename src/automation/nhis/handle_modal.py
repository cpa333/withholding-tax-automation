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
            
            modal = page.locator('#common-CONFIRM-modal')
            if await modal.is_visible():
                text = await modal.inner_text()
                print('모달 내용:', text.strip().replace('\n', ' '))
                
                btn = modal.locator('button:has-text("확인")')
                if await btn.count() > 0:
                    print('확인 버튼 클릭')
                    await btn.click()
                else:
                    print('확인 버튼을 찾을 수 없음. 가능한 버튼들:')
                    btns = await modal.locator('button').all_inner_texts()
                    print(btns)
            else:
                print('열려있는 모달이 없음')
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(run())
