import asyncio
import sys
import os
from datetime import datetime
from playwright.async_api import async_playwright

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')

async def issue_pdf():
    async with async_playwright() as p:
        try:
            print("기존 브라우저(9222 포트)에 연결 중...")
            browser = await p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0]
            page = context.pages[0]
            
            # 1. 조회 버튼 클릭 (페이지 내의 '조회' 버튼 타겟팅)
            print("조회 버튼을 클릭합니다...")
            # '조회' 버튼은 보통 input[type=button] 이나 a 태그임
            search_btn = page.locator("button:has-text('조회'), input[value='조회'], a:has-text('조회')").first
            await search_btn.click()
            
            # 2. 결과 목록이 나올 때까지 대기
            print("조회 결과를 기다리는 중...")
            await asyncio.sleep(3) # 데이터 로딩 대기
            
            # 3. 가장 상단 항목의 '출력' 버튼 클릭
            # 보통 테이블의 첫 번째 행에 있는 버튼
            print("가장 상단 항목의 '출력' 버튼을 찾습니다...")
            print_btn = page.locator("button:has-text('출력'), a:has-text('출력')").first
            
            if await print_btn.count() > 0:
                # 4. 출력 버튼 클릭 및 모달 대응
                # '확인' 버튼이 있는 모달이 뜨는 경우를 대비해 다이얼로그 핸들러 등록
                async def handle_dialog(dialog):
                    print(f"모달 창 발생: {dialog.message}")
                    await dialog.accept()
                    print("모달 확인 버튼을 눌렀습니다.")
                
                page.on("dialog", lambda dialog: asyncio.create_task(handle_dialog(dialog)))
                
                # 다운로드 이벤트 대기 설정
                async with page.expect_download() as download_info:
                    await print_btn.click()
                    print("'출력' 버튼을 클릭했습니다.")
                
                download = await download_info.value
                
                # 5. 바탕화면에 지정된 파일명으로 저장
                desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
                today_str = datetime.now().strftime("%Y%m%d")
                file_name = f"{today_str}_증명서.pdf"
                save_path = os.path.join(desktop_path, file_name)
                
                await download.save_as(save_path)
                print(f"성공! 파일이 저장되었습니다: {save_path}")
                
            else:
                print("조회 결과에서 '출력' 버튼을 찾지 못했습니다. 조회가 성공했는지 확인해 주세요.")

        except Exception as e:
            print(f"오류 발생: {e}")

if __name__ == "__main__":
    asyncio.run(issue_pdf())
