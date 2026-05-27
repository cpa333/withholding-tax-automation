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

async def click_issue():
    async with async_playwright() as p:
        try:
            print(f"기존 브라우저에 연결 중... ({CDP_URL})")
            browser = await p.chromium.connect_over_cdp(CDP_URL)
            context = browser.contexts[0]
            page = context.pages[0]
            
            # 1. 서비스 목록 페이지인지 확인 및 이동
            target_url = "https://www.nhis.or.kr/nhis/minwon/minwonServiceBoard.do"
            if target_url not in page.url:
                print(f"목록 페이지로 이동합니다: {target_url}")
                await page.goto(target_url)
                await page.wait_for_load_state("networkidle")

            print("'보험료 납부확인서' 구역의 '발급하기' 버튼을 정밀 탐색합니다.")
            
            # 2. 정확한 구역을 찾기 위한 시도
            # NHIS 사이트 구조: <dl> <dt>제목</dt> <dd>설명</dd> <dd><a class="btn">발급하기</a></dd> </dl>
            # '보험료 납부확인서' 텍스트를 가진 dt를 찾고, 그 부모 dl 내의 '발급하기' 링크를 찾습니다.
            
            sections = await page.query_selector_all("dl")
            target_button = None
            
            for section in sections:
                header = await section.query_selector("dt")
                if header:
                    header_text = await header.inner_text()
                    if "보험료 납부확인서" in header_text:
                        print(f"대상 구역 발견: {header_text.strip()}")
                        # 해당 dl 내의 '발급하기' 버튼 검색
                        target_button = await section.query_selector("a:has-text('발급하기')")
                        if target_button:
                            break
            
            if target_button:
                print("발급하기 버튼을 클릭합니다.")
                await target_button.click()
                print("클릭 완료. 페이지 전환을 확인해 주세요.")
            else:
                print("특정 구역에서 버튼을 찾지 못해 전체 페이지 검색을 시도합니다.")
                # Fallback: 전체 페이지에서 가장 정확해 보이는 링크 클릭
                await page.click("//dl[dt[contains(.,'보험료 납부확인서')]]//a[contains(.,'발급하기')]")
                print("Xpath를 통한 클릭을 시도했습니다.")

        except Exception as e:
            print(f"오류 발생: {e}")

if __name__ == "__main__":
    asyncio.run(click_issue())
