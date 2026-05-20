import asyncio
import sys
import os
from datetime import datetime
from playwright.async_api import async_playwright

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')

async def direct_print_and_save():
    async with async_playwright() as p:
        try:
            print("기존 브라우저(9222 포트)에 연결 중...")
            browser = await p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0]
            page = context.pages[0]
            
            print("현재 화면의 목록에서 '출력' 버튼을 찾습니다...")
            
            # 버튼 직접 찾기 (출력 텍스트를 가진 첫 번째 버튼)
            print_btn = page.locator("button:has-text('출력')").first
            
            if await print_btn.count() > 0:
                print("출력 버튼 발견! 클릭을 시도합니다.")
                
                # 네이티브 알림창(모달) 자동 승인 설정 (혹시 모를 대비)
                page.on("dialog", lambda d: asyncio.create_task(d.accept()))
                
                # 다운로드 이벤트 감지 설정
                async with page.expect_download(timeout=60000) as download_info:
                    # 버튼이 화면에 보이도록 스크롤 후 클릭
                    await print_btn.scroll_into_view_if_needed()
                    await print_btn.click()
                    print("출력 버튼을 클릭했습니다.")
                    
                    # HTML 커스텀 모달 대기 및 확인 버튼 클릭
                    modal = page.locator('#common-CONFIRM-modal')
                    try:
                        await modal.wait_for(state='visible', timeout=5000)
                        print("안내 모달이 나타났습니다. 확인 버튼을 클릭합니다.")
                        confirm_btn = modal.locator('button:has-text("확인")')
                        await confirm_btn.click()
                    except:
                        print("모달이 나타나지 않았습니다. 바로 다운로드를 대기합니다.")

                    print("다운로드를 대기합니다...")
                
                download = await download_info.value
                
                # 바탕화면에 저장
                desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
                today_str = datetime.now().strftime("%Y%m%d")
                save_path = os.path.join(desktop_path, f"{today_str}_증명서.pdf")
                
                await download.save_as(save_path)
                print(f"성공! 증명서가 바탕화면에 저장되었습니다.\n경로: {save_path}")
                
            else:
                print("화면에서 '출력' 버튼을 찾지 못했습니다. 목록이 제대로 로드되었는지 확인해 주세요.")

        except Exception as e:
            print(f"오류 발생: {e}")

if __name__ == "__main__":
    asyncio.run(direct_print_and_save())
