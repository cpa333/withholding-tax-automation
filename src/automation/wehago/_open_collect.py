"""page.mouse.click으로 #collect 클릭 → 드롭다운 열기 시도"""
import asyncio, sys, os

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from playwright.async_api import async_playwright
from src.utils.chrome_cdp import CDP_URL

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0]
        page = context.pages[0]

        print(f"현재: {await page.title()}\n")

        # #collect 버튼 위치 (CSS 픽셀)
        pos = await page.evaluate("""() => {
            const btn = document.querySelector('#collect');
            if (!btn) return null;
            const rect = btn.getBoundingClientRect();
            return {x: rect.x + rect.width/2, y: rect.y + rect.height/2};
        }""")
        print(f"#collect 중심(CSS): {pos}")

        # Playwright mouse.click (CSS 좌표, DPR 자동 처리)
        print("\npage.mouse.click() 전송...")
        await page.mouse.click(pos['x'], pos['y'])
        await asyncio.sleep(3)

        # 드롭다운 열렸는지 확인
        items_visible = await page.evaluate("""() => {
            const menu = document.querySelector('.sao_head_menu');
            if (!menu) return {found: false};
            const items = Array.from(menu.querySelectorAll('li')).filter(li => li.offsetHeight > 0);
            return {
                found: true,
                visibleCount: items.length,
                items: items.map(li => li.textContent.trim().substring(0, 25))
            };
        }""")
        print(f"결과: {items_visible}")

        if items_visible.get('visibleCount', 0) > 0:
            print("\n✅ 드롭다운 열림!")
        else:
            print("\n드롭다운 안 열림. 한 번 더 클릭 (토글)...")
            await page.mouse.click(pos['x'], pos['y'])
            await asyncio.sleep(2)
            items2 = await page.evaluate("""() => {
                const items = Array.from(document.querySelectorAll('.sao_head_menu li')).filter(li => li.offsetHeight > 0);
                return items.map(li => li.textContent.trim().substring(0, 25));
            }""")
            print(f"재시도 결과: {items2}")

        await browser.close()

asyncio.run(main())
