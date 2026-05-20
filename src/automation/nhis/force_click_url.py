import asyncio
import sys
from playwright.async_api import async_playwright

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')

async def force_click_by_url():
    async with async_playwright() as p:
        try:
            print("기존 브라우저(9222 포트)에 연결 중...")
            browser = await p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0]
            page = context.pages[0]
            
            print("페이지를 아래로 스크롤하고 발급 링크를 강제 클릭합니다.")
            
            # 1. 페이지 하단으로 스크롤 (버튼 활성화를 위함)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1)
            
            # 2. 'jpAea00101.do' 주소를 포함하는 모든 요소를 찾아 클릭
            # 이 주소는 '보험료 납부확인서 발급'의 실제 시스템 경로임
            script = """
            () => {
                // a 태그뿐만 아니라 data-href 속성을 가진 요소까지 모두 검색
                const targetPath = 'jpAea00101.do';
                const allElements = document.querySelectorAll('a, button, [data-href]');
                
                for (let el of allElements) {
                    const href = el.getAttribute('href') || '';
                    const dataHref = el.getAttribute('data-href') || '';
                    const onclick = el.getAttribute('onclick') || '';
                    
                    if (href.includes(targetPath) || dataHref.includes(targetPath) || onclick.includes(targetPath)) {
                        el.scrollIntoView();
                        el.click();
                        return "발급 링크 발견 및 클릭 성공: " + targetPath;
                    }
                }
                return "발급 링크를 찾지 못함";
            }
            """
            
            result = await page.evaluate(script)
            print(f"결과: {result}")
            
            if "성공" in result:
                await asyncio.sleep(3)
                print(f"이동 후 URL: {page.url}")
            else:
                # 텍스트로 다시 시도
                print("'발급하기' 텍스트로 다시 시도합니다.")
                await page.evaluate("() => { const a = [...document.querySelectorAll('a')].find(el => el.textContent.includes('발급하기')); if(a) a.click(); }")

        except Exception as e:
            print(f"오류 발생: {e}")

if __name__ == "__main__":
    asyncio.run(force_click_by_url())
