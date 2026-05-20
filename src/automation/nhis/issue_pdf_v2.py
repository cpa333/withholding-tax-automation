import asyncio
import sys
import os
from datetime import datetime
from playwright.async_api import async_playwright

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')

async def issue_pdf_v2():
    async with async_playwright() as p:
        try:
            print("기존 브라우저(9222 포트)에 연결 중...")
            browser = await p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0]
            page = context.pages[0]
            
            print("발급 페이지 내부의 '조회' 버튼을 정밀 탐색합니다.")
            
            # 발급 폼 내부의 조회 버튼은 보통 특정 클래스나 ID를 가집니다.
            # 텍스트가 정확히 '조회'인 요소 중 가장 적합한 것을 찾습니다.
            search_btn = page.locator("button.btn.lg.primary, #searchBtn, .btn_search, button:has-text('조회')").last
            
            await search_btn.scroll_into_view_if_needed()
            await search_btn.click()
            print("조회 버튼 클릭 완료. 결과를 기다립니다...")
            
            # 조회 후 목록이 나타날 때까지 대기
            await asyncio.sleep(3)
            
            # 목록에서 '출력' 버튼 찾기
            # '출력'이라는 텍스트가 포함된 첫 번째 버튼 또는 링크
            print_btn = page.locator("table >> text='출력'").first
            
            if await print_btn.count() > 0:
                print("출력 버튼을 찾았습니다. 클릭을 시도합니다.")
                
                # 모달/팝업 대응 핸들러
                async def handle_dialog(dialog):
                    print(f"알림창 확인: {dialog.message}")
                    await dialog.accept()

                page.on("dialog", lambda d: asyncio.create_task(handle_dialog(d)))
                
                # 다운로드 이벤트 대기
                async with page.expect_download() as download_info:
                    await print_btn.click()
                    print("출력 실행 중...")
                
                download = await download_info.value
                
                desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
                today_str = datetime.now().strftime("%Y%m%d")
                save_path = os.path.join(desktop_path, f"{today_str}_증명서.pdf")
                
                await download.save_as(save_path)
                print(f"성공! PDF가 바탕화면에 저장되었습니다: {save_path}")
            else:
                print("조회 결과 목록에서 '출력' 버튼을 찾지 못했습니다. 데이터가 있는지 확인해 주세요.")

        except Exception as e:
            print(f"오류 발생: {e}")

if __name__ == "__main__":
    asyncio.run(issue_pdf_v2())
