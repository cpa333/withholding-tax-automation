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

async def click_link_from_article():
    async with async_playwright() as p:
        try:
            print(f"기존 브라우저에 연결 중... ({CDP_URL})")
            browser = await p.chromium.connect_over_cdp(CDP_URL)
            context = browser.contexts[0]
            page = context.pages[0]
            
            print("안내 페이지 하단의 발급/신청 버튼을 클릭합니다.")
            
            # 분석된 버튼 셀렉터: .btn.xlg.nhis-side-primary
            # 이 버튼은 'data-href' 속성을 가지고 있으며, 클릭 시 해당 경로로 이동함
            
            target_selector = ".btn.xlg.nhis-side-primary"
            
            # 버튼이 로드될 때까지 잠시 대기
            await page.wait_for_selector(target_selector, timeout=5000)
            
            # 버튼 클릭
            await page.click(target_selector)
            print("버튼 클릭 완료. 발급 신청 화면으로 이동합니다.")
            
            # 이동 후 잠시 대기하여 결과 확인
            await asyncio.sleep(3)
            print(f"현재 페이지 URL: {page.url}")

        except Exception as e:
            print(f"오류 발생: {e}")

if __name__ == "__main__":
    asyncio.run(click_link_from_article())
