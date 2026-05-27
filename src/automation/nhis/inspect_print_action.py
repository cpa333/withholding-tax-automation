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
            
            # 새 탭 감지
            async def handle_popup(popup):
                print(f"새 팝업 열림: {popup.url}")
                await popup.wait_for_load_state()
                print(f"팝업 제목: {await popup.title()}")

            page.on("popup", lambda p: asyncio.create_task(handle_popup(p)))
            
            # 다운로드 감지
            async def handle_download(download):
                print(f"다운로드 시작됨: {download.suggested_filename}")

            page.on("download", lambda d: asyncio.create_task(handle_download(d)))

            print_btn = page.locator("button:has-text('출력')").first
            
            if await print_btn.count() > 0:
                print("출력 버튼 클릭!")
                await print_btn.click()
                
                # 모달 확인
                modal = page.locator('#common-CONFIRM-modal')
                try:
                    await modal.wait_for(state='visible', timeout=5000)
                    print("모달 확인 버튼 클릭")
                    await modal.locator('button:has-text("확인")').click()
                except:
                    pass

                print("20초간 대기하며 이벤트 확인...")
                await asyncio.sleep(20)
            else:
                print("출력 버튼을 찾을 수 없음.")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(run())
