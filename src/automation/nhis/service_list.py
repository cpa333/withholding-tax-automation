import asyncio
import sys
import os
from playwright.async_api import async_playwright

# Windows 터미널 한글 깨짐 방지
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        print("건강보험 사이트 민원 서비스 목록 페이지로 이동 중...")
        target_url = "https://www.nhis.or.kr/nhis/minwon/minwonServiceBoard.do"
        await page.goto(target_url)

        print("페이지 로딩 대기 중...")
        try:
            await page.wait_for_selector(".minwon-service-list, .board-list, .service-box, .service-item", timeout=15000)
        except:
            print("목록 대기 중 타임아웃 발생. 현재 페이지에서 직접 추출을 시도합니다.")

        all_links = await page.query_selector_all("a")
        all_dts = await page.query_selector_all("dt")
        all_strongs = await page.query_selector_all("strong")
        
        found_services = []
        for el in all_links + all_dts + all_strongs:
            text = await el.inner_text()
            clean_text = text.replace("\n", " ").strip()
            if len(clean_text) > 2 and clean_text not in found_services:
                if any(k in clean_text for k in ["신고", "조회", "신청", "발급", "보험료"]):
                    found_services.append(f"[검색어 매칭] {clean_text}")
                elif len(found_services) < 30:
                    found_services.append(clean_text)
            if len(found_services) >= 100: break

        # 결과 출력 및 저장
        print("\n--- 추출된 서비스 목록 ---")
        os.makedirs("results", exist_ok=True)
        with open("results/nhis_services.txt", "w", encoding="utf-8") as f:
            for service in found_services:
                print(f"- {service}")
                f.write(f"{service}\n")
        
        print(f"\n총 {len(found_services)}개의 항목을 'results/nhis_services.txt'에 저장했습니다.")
        print("\n브라우저를 유지합니다. 작업을 마치려면 터미널에서 Ctrl+C를 누르세요.")
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n사용자에 의해 종료되었습니다.")

if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n사용자에 의해 종료되었습니다.")
