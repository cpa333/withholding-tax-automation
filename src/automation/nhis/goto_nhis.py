import asyncio
import os
import sys
from playwright.async_api import async_playwright

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)
from src.utils.chrome_cdp import CDP_URL

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')

async def navigate():
    async with async_playwright() as p:
        try:
            print(f"기존 브라우저에 연결 중... ({CDP_URL})")
            browser = await p.chromium.connect_over_cdp(CDP_URL)
            context = browser.contexts[0]
            page = context.pages[0]
            
            target_url = "https://www.nhis.or.kr/nhis/index.do"
            print(f"{target_url}로 이동합니다...")
            await page.goto(target_url)
            print("이동 완료. 이제 브라우저에서 로그인을 진행해 주세요.")
            
        except Exception as e:
            print(f"오류 발생: {e}")

if __name__ == "__main__":
    asyncio.run(navigate())
