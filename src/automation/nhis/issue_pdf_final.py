import asyncio
import os
import sys
from datetime import datetime
from playwright.async_api import async_playwright

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)
from src.utils.chrome_cdp import CDP_URL

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')

async def issue_pdf():
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
            context = browser.contexts[0]
            page = context.pages[0]
            
            print("최상단 항목의 '출력' 버튼을 찾습니다...")
            
            print_btn = page.locator("button:has-text('출력')").first
            
            if await print_btn.count() > 0:
                print("출력 버튼 클릭 시도 (자바스크립트 클릭 사용)...")
                await print_btn.scroll_into_view_if_needed()
                
                # Playwright의 click() 대신 자바스크립트로 클릭 이벤트를 트리거하여 프리징 방지
                await print_btn.evaluate("node => node.click()")
                
                modal = page.locator('#common-CONFIRM-modal')
                await modal.wait_for(state='visible', timeout=10000)
                print("안내 모달 확인. '확인' 버튼을 클릭합니다.")
                
                confirm_btn = modal.locator('button', has_text='확인').first
                
                # Context 레벨에서 다운로드 감지
                download_future = asyncio.Future()
                
                async def handle_download(download):
                    if not download_future.done():
                        download_future.set_result(download)
                
                for p in context.pages:
                    p.on("download", handle_download)
                    
                async def handle_page(new_page):
                    new_page.on("download", handle_download)
                
                context.on("page", handle_page)
                
                # 모달 확인 버튼도 자바스크립트 클릭 사용
                await confirm_btn.evaluate("node => node.click()")
                print("확인 버튼 클릭 완료. 팝업 및 다운로드 진행 중...")
                    
                try:
                    download = await asyncio.wait_for(download_future, timeout=60.0)
                    
                    desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
                    today_str = datetime.now().strftime("%Y%m%d")
                    save_path = os.path.join(desktop_path, f"{today_str}_보험료납부확인서.pdf")
                    
                    await download.save_as(save_path)
                    print(f"성공! PDF 증명서가 바탕화면에 저장되었습니다.\n저장 경로: {save_path}")
                except asyncio.TimeoutError:
                    print("다운로드 시간 초과. 브라우저가 직접 다운로드 폴더에 저장했을 수 있습니다.")
                    print("C:\\Users\\cobaetoo\\Downloads 폴더를 확인해 보세요.")
                
            else:
                print("화면에서 '출력' 버튼을 찾지 못했습니다.")

        except Exception as e:
            print(f"오류 발생: {e}")

if __name__ == "__main__":
    asyncio.run(issue_pdf())
