import asyncio
import sys
from playwright.async_api import async_playwright

# Windows 터미널 한글 깨짐 방지
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')

async def run():
    async with async_playwright() as p:
        # 이미 9222 포트로 열려 있는 브라우저에 연결 시도
        # 만약 열려있지 않다면 새로 실행하도록 설정 (선택 가능)
        try:
            print("기존 브라우저(9222 포트)에 연결을 시도합니다...")
            browser = await p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0]
            page = context.pages[0]
        except Exception as e:
            print(f"연결 실패: {e}")
            print("새 브라우저를 실행합니다. (로그인을 수동으로 진행해 주세요)")
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context()
            page = await context.new_page()

        # 1. 민원 서비스 목록 페이지로 이동
        target_url = "https://www.nhis.or.kr/nhis/minwon/minwonServiceBoard.do"
        if page.url != target_url:
            print(f"페이지 이동 중: {target_url}")
            await page.goto(target_url)
        
        print("'보험료 납부확인서' 메뉴를 찾는 중...")

        # 2. '보험료 납부확인서' 텍스트가 포함된 영역을 찾아서 그 근처의 '발급하기' 버튼 클릭
        # 사이트 구조상 '보험료 납부확인서' 제목 아래에 '발급하기' 버튼이 위치함
        try:
            # 텍스트로 해당 구역 식별
            # locator('text=...')는 해당 텍스트를 포함하는 요소를 찾음
            certificate_section = page.locator("dt", has_text="보험료 납부확인서")
            
            # 해당 섹션과 가장 가까운(아래에 있는) '발급하기' 버튼 클릭
            # nth(0)은 첫 번째 매칭되는 버튼
            issue_button = page.locator("a:has-text('발급하기')").filter(has=page.locator("xpath=ancestor::dl[dt[contains(text(), '보험료 납부확인서')]]"))
            
            if await issue_button.count() > 0:
                print("버튼을 찾았습니다. 클릭합니다.")
                await issue_button.first.click()
            else:
                # 좀 더 단순한 시도로 전체 페이지에서 '보험료 납부확인서' 텍스트를 가진 요소 클릭 시도
                print("상세 구조 매칭 실패. 단순 텍스트 검색으로 시도합니다.")
                await page.click("text='보험료 납부확인서'")
                
        except Exception as e:
            print(f"메뉴 진입 중 오류 발생: {e}")

        print("\n브라우저 상태를 유지합니다. 터미널에서 Ctrl+C를 누르면 종료됩니다.")
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n사용자에 의해 종료되었습니다.")
