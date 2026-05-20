import asyncio
import sys
from playwright.async_api import async_playwright

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')

async def click_issue_robust():
    async with async_playwright() as p:
        try:
            print("기존 브라우저(9222 포트)에 연결 중...")
            browser = await p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0]
            page = context.pages[0]
            
            print("브라우저 내 스크립트 실행으로 버튼을 클릭합니다.")
            
            # 브라우저 내부에서 실행될 자바스크립트
            # '보험료 납부확인서' 텍스트를 포함하는 dt를 찾고, 그 부모(dl) 내의 '발급하기' 버튼을 찾아 클릭
            script = """
            () => {
                const dts = Array.from(document.querySelectorAll('dt'));
                const targetDt = dts.find(dt => dt.textContent.includes('보험료 납부확인서'));
                if (targetDt) {
                    const dl = targetDt.closest('dl');
                    const btn = dl.querySelector('a');
                    if (btn) {
                        btn.click();
                        return "버튼 클릭 성공";
                    }
                    return "dl 내에서 버튼을 찾지 못함";
                }
                return "제목(dt)을 찾지 못함";
            }
            """
            
            result = await page.evaluate(script)
            print(f"결과: {result}")
            
            if "성공" in result:
                print("페이지 전환을 기다립니다...")
                await page.wait_for_load_state("networkidle")
            
        except Exception as e:
            print(f"오류 발생: {e}")

if __name__ == "__main__":
    asyncio.run(click_issue_robust())
