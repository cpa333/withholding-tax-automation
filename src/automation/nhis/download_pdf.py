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

async def download_pdf():
    async with async_playwright() as p:
        try:
            print(f"기존 브라우저에 연결 중... ({CDP_URL})")
            browser = await p.chromium.connect_over_cdp(CDP_URL)
            context = browser.contexts[0]
            page = context.pages[0]
            
            print("현재 페이지:", page.url)
            
            print_btn = page.locator("button:has-text('출력'), a:has-text('출력')")
            
            # Find the first visible button
            target_btn = None
            for idx in range(await print_btn.count()):
                btn = print_btn.nth(idx)
                if await btn.is_visible():
                    target_btn = btn
                    break
                    
            if target_btn is not None:
                print("'출력' 버튼을 찾았습니다. 클릭을 시도합니다.")
                await target_btn.scroll_into_view_if_needed()
                await target_btn.evaluate("node => node.click()")
                
                print("모달 대기 중...")
                modal = page.locator('#common-CONFIRM-modal')
                await modal.wait_for(state='visible', timeout=10000)
                
                confirm_btn = modal.locator('button', has_text='확인').first
                
                # 확인 버튼의 onclick 속성 가져오기
                onclick = await confirm_btn.evaluate('el => el.getAttribute("onclick")')
                print(f"확인 버튼의 onclick 이벤트: {onclick}")
                
                # 다운로드와 팝업 이벤트를 모두 대기할 준비
                download_future = asyncio.Future()
                popup_future = asyncio.Future()
                
                def on_download(download):
                    if not download_future.done():
                        print("다운로드 이벤트 감지됨!")
                        download_future.set_result(download)
                        
                def on_popup(popup):
                    if not popup_future.done():
                        print("새 팝업 감지됨!")
                        popup_future.set_result(popup)

                page.on("download", on_download)
                page.on("popup", on_popup)
                
                # 프리징(사이트 멈춤) 방지를 위해 클릭을 백그라운드로 실행하거나, onclick 스크립트를 직접 실행
                print("모달 '확인' 버튼 클릭 실행...")
                # Playwright의 click()은 이벤트를 기다리며 행을 유발할 수 있으므로 자바스크립트의 비동기 클릭(setTimeout)을 사용
                await confirm_btn.evaluate("node => setTimeout(() => node.click(), 10)")
                
                print("이벤트(팝업/다운로드) 발생을 기다립니다...")
                
                # 최대 30초 대기
                done, pending = await asyncio.wait(
                    [download_future, popup_future],
                    return_when=asyncio.FIRST_COMPLETED,
                    timeout=30.0
                )
                
                if download_future in done:
                    download = download_future.result()
                    desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
                    today_str = datetime.now().strftime("%Y%m%d")
                    save_path = os.path.join(desktop_path, f"{today_str}_확인서.pdf")
                    await download.save_as(save_path)
                    print(f"다운로드 성공! 경로: {save_path}")
                elif popup_future in done:
                    popup = popup_future.result()
                    print(f"팝업이 열렸습니다. URL: {popup.url}")
                    # 여기서 팝업 내의 PDF 저장 로직을 추가해야 할 수도 있음 (예: Crownix 뷰어)
                    # 팝업이 로드될 때까지 대기
                    await popup.wait_for_load_state()
                    print("팝업 페이지 타이틀:", await popup.title())
                    
                    # 팝업에서 다운로드가 발생하는지 확인
                    try:
                        async with popup.expect_download(timeout=15000) as popup_dl_info:
                            print("팝업에서 자동 다운로드가 있는지 확인 중...")
                        
                        popup_download = await popup_dl_info.value
                        desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
                        today_str = datetime.now().strftime("%Y%m%d")
                        save_path = os.path.join(desktop_path, f"{today_str}_확인서.pdf")
                        await popup_download.save_as(save_path)
                        print(f"팝업에서 다운로드 성공! 경로: {save_path}")
                    except asyncio.TimeoutError:
                        print("팝업 내에서 자동 다운로드가 발생하지 않았습니다. 리포트 뷰어일 수 있습니다.")
                else:
                    print("다운로드나 팝업 이벤트가 30초 내에 발생하지 않았습니다.")
                    
            else:
                print("화면에서 '출력' 버튼을 찾지 못했습니다. 목록이 조회되었는지 확인해 주세요.")

        except Exception as e:
            print(f"오류 발생: {e}")

if __name__ == "__main__":
    asyncio.run(download_pdf())