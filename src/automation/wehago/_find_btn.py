"""화면에서 동그라미/원형 버튼 찾아서 클릭"""
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

        # 모든 버튼 찾기 - 뷰포트 내 보이는 것만
        print("[1] 화면상 보이는 버튼 찾기...")
        buttons = await page.evaluate("""() => {
            const btns = document.querySelectorAll('button');
            const results = [];
            for (const btn of btns) {
                const rect = btn.getBoundingClientRect();
                const cs = window.getComputedStyle(btn);
                // 뷰포트 내에 있고 실제 보이는 것
                if (rect.top >= 0 && rect.top < window.innerHeight &&
                    rect.width > 0 && rect.height > 0 &&
                    cs.display !== 'none' && cs.visibility !== 'hidden') {
                    const br = cs.borderRadius;
                    const isRound = (parseFloat(br) >= 50) ||
                                   (rect.width === rect.height) ||
                                   btn.classList.contains('circle') ||
                                   btn.classList.contains('round');
                    results.push({
                        id: btn.id || '',
                        cls: (btn.className || '').substring(0, 80),
                        text: btn.textContent.trim().substring(0, 20),
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y),
                               w: Math.round(rect.width), h: Math.round(rect.height)},
                        borderRadius: br,
                        isRound: isRound,
                        icon: btn.querySelector('i, span, svg, img') ?
                              btn.querySelector('i, span, svg, img').className?.substring(0, 40) || 'has-child' : 'no-child'
                    });
                }
            }
            return results;
        }""")

        for b in buttons:
            marker = "⭕" if b['isRound'] else "  "
            print(f"  {marker} id='{b['id']}' text='{b['text']}' "
                  f"rect=({b['rect']['x']},{b['rect']['y']},{b['rect']['w']},{b['rect']['h']}) "
                  f"radius={b['borderRadius']} icon={b['icon']}")
            print(f"     cls: {b['cls'][:60]}")

        # #collect 버튼 확인
        print("\n[2] #collect 버튼 직접 확인...")
        collect = await page.evaluate("""() => {
            const btn = document.querySelector('#collect');
            if (!btn) return {found: false};
            const rect = btn.getBoundingClientRect();
            const cs = window.getComputedStyle(btn);
            // 스크롤해서 보이게
            btn.scrollIntoView({block: 'center', inline: 'end'});
            return {
                found: true,
                rect: {x: Math.round(rect.x), y: Math.round(rect.y),
                       w: Math.round(rect.width), h: Math.round(rect.height)},
                inViewport: rect.top >= 0 && rect.top < window.innerHeight &&
                           rect.left >= 0 && rect.left < window.innerWidth,
                display: cs.display,
                overflow: cs.overflow
            };
        }""")
        print(f"  {collect}")

        if collect.get('found') and not collect.get('inViewport'):
            print("  → 뷰포트 밖에 있음. scrollIntoView로 가져옴...")
            await asyncio.sleep(1)

        # collect 버튼 다시 확인 후 클릭
        collect2 = await page.evaluate("""() => {
            const btn = document.querySelector('#collect');
            if (!btn) return null;
            const rect = btn.getBoundingClientRect();
            return {x: Math.round(rect.x + rect.width/2),
                    y: Math.round(rect.y + rect.height/2),
                    inViewport: rect.left >= 0 && rect.left < window.innerWidth};
        }""")
        print(f"\n  클릭 전 위치: {collect2}")

        if collect2 and collect2.get('inViewport'):
            # CDP로 물리 픽셀 좌표 계산
            dpr = await page.evaluate("() => window.devicePixelRatio")
            px = round(collect2['x'] * dpr)
            py = round(collect2['y'] * dpr)
            print(f"  DPR={dpr} → 물리 픽셀: ({px}, {py})")

            cdp = await page.context.new_cdp_session(page)
            await cdp.send('Input.dispatchMouseEvent', {
                'type': 'mousePressed', 'x': px, 'y': py,
                'button': 'left', 'clickCount': 1
            })
            await cdp.send('Input.dispatchMouseEvent', {
                'type': 'mouseReleased', 'x': px, 'y': py,
                'button': 'left', 'clickCount': 1
            })
            print("  CDP 클릭 전송!")
            await asyncio.sleep(3)

            # 결과 확인
            items_visible = await page.evaluate("""() => {
                const menu = document.querySelector('.sao_head_menu');
                if (!menu) return 0;
                return Array.from(menu.querySelectorAll('li')).filter(
                    li => li.offsetHeight > 0
                ).length;
            }""")
            print(f"  보이는 메뉴 항목: {items_visible}개")

            # 스크린샷
            import os
            ss_path = os.path.abspath(os.path.join(
                os.path.dirname(__file__), "..", "debug", "after_collect_click.png"
            ))
            await page.screenshot(path=ss_path)
            print(f"  스크린샷: {ss_path}")

        await browser.close()

asyncio.run(main())
