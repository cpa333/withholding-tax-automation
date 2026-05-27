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

async def click_final_attempt():
    async with async_playwright() as p:
        try:
            print(f"기존 브라우저에 연결 중... ({CDP_URL})")
            browser = await p.chromium.connect_over_cdp(CDP_URL)
            context = browser.contexts[0]
            page = context.pages[0]
            
            print("'보험료 납부확인서' 문구를 포함하는 요소를 찾아 클릭을 시도합니다.")
            
            # 모든 <a> 태그 중에서 텍스트가 일치하거나 부모가 일치하는 것을 탐색
            # '발급하기' 버튼이 '보험료 납부확인서' 텍스트를 포함하거나 그 바로 옆에 있을 것임
            
            script = """
            () => {
                // 1. 우선 '보험료 납부확인서' 라는 텍스트를 가진 모든 요소를 찾음
                const elements = Array.from(document.querySelectorAll('dt, strong, span, a, div'));
                const targetText = '보험료 납부확인서';
                const found = elements.find(el => el.textContent.trim().includes(targetText));
                
                if (found) {
                    // 2. 해당 요소 주변(부모 dl 등)에서 '발급하기' 또는 클릭 가능한 요소를 찾음
                    const container = found.closest('dl') || found.parentElement;
                    const btn = container.querySelector('a, button');
                    if (btn) {
                        btn.scrollIntoView();
                        btn.click();
                        return "텍스트 매칭 및 버튼 클릭 성공: " + found.textContent.trim();
                    }
                    // 3. 버튼을 못 찾았다면 텍스트 그 자체라도 클릭
                    found.click();
                    return "버튼 미발견으로 텍스트 요소 직접 클릭";
                }
                return "해당 텍스트를 가진 요소를 찾지 못함";
            }
            """
            
            result = await page.evaluate(script)
            print(f"결과: {result}")
            
            if "성공" in result or "클릭" in result:
                await asyncio.sleep(2) # 페이지 전환 대기
                print(f"현재 페이지 URL: {page.url}")

        except Exception as e:
            print(f"오류 발생: {e}")

if __name__ == "__main__":
    asyncio.run(click_final_attempt())
