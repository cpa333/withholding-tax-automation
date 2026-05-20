import asyncio
import sys
import os
from playwright.async_api import async_playwright

async def debug_screenshot():
    async with async_playwright() as p:
        try:
            print("기존 브라우저(9222 포트)에 연결 중...")
            browser = await p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0]
            page = context.pages[0]
            
            print(f"현재 URL: {page.url}")
            
            os.makedirs("debug", exist_ok=True)
            screenshot_path = "debug/current_page.png"
            await page.screenshot(path=screenshot_path)
            print(f"스크린샷 저장 완료: {screenshot_path}")
            
            # 페이지의 모든 텍스트 요소를 덤프해서 텍스트 매칭 문제인지 확인
            text_content = await page.evaluate("() => document.body.innerText")
            with open("debug/page_text.txt", "w", encoding="utf-8") as f:
                f.write(text_content)
            print("페이지 전체 텍스트를 debug/page_text.txt에 저장했습니다.")
            
        except Exception as e:
            print(f"오류 발생: {e}")

if __name__ == "__main__":
    asyncio.run(debug_screenshot())
