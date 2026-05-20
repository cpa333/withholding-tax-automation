import asyncio
import sys
from playwright.async_api import async_playwright

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')

async def navigate():
    async with async_playwright() as p:
        try:
            print("기존 브라우저(9222 포트)에 연결 중...")
            browser = await p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0]
            page = context.pages[0]
            
            target_url = "https://www.nhis.or.kr/nhis/minwon/minwonServiceBoard.do"
            print(f"{target_url}로 이동합니다...")
            await page.goto(target_url)
            print("이동 완료.")
            
        except Exception as e:
            print(f"오류 발생: {e}")

if __name__ == "__main__":
    asyncio.run(navigate())
