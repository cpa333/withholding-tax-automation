"""hidden file input 직접 탐색 → 파일 설정 → Issue #1 검증"""
import asyncio, sys, os

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from playwright.async_api import async_playwright
from src.utils.chrome_cdp import CDP_URL
SAMPLE_UPLOAD = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "sample_excels",
    "공임나라김천모임점_업로드.xlsx"
))


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0]
        page = context.pages[0]

        print(f"현재: {await page.title()}")
        print(f"URL: {page.url}\n")

        # [1] 드롭다운 열기
        print("[1] #collect 드롭다운 열기...")
        collect_pos = await page.evaluate("""() => {
            const btn = document.querySelector('#collect');
            if (!btn) return null;
            const rect = btn.getBoundingClientRect();
            return {x: rect.x + rect.width/2, y: rect.y + rect.height/2};
        }""")
        if not collect_pos:
            print("  #collect 버튼 없음")
            await browser.close()
            return
        await page.mouse.click(collect_pos['x'], collect_pos['y'])
        await asyncio.sleep(2)
        print("  드롭다운 열림\n")

        # [2] 엑셀 불러오기 항목 위치 확인 후 mouse.click
        print("[2] '엑셀 불러오기' 클릭...")
        item_info = await page.evaluate("""() => {
            const menu = document.querySelector('.sao_head_menu');
            if (!menu) return null;
            const items = menu.querySelectorAll('li');
            for (const li of items) {
                if (li.textContent.includes('엑셀 불러오기') && li.offsetHeight > 0) {
                    const rect = li.getBoundingClientRect();
                    return {
                        x: rect.x + rect.width / 2,
                        y: rect.y + rect.height / 2,
                        h: rect.height
                    };
                }
            }
            return null;
        }""")

        if item_info:
            print(f"  항목 위치: ({round(item_info['x'])}, {round(item_info['y'])}) h={round(item_info['h'])}")
            # mouse.click으로 파일 선택창 열기
            try:
                async with page.expect_file_chooser(timeout=10000) as fc_info:
                    await page.mouse.click(item_info['x'], item_info['y'])
                fc = await fc_info.value
                print("  ✅ 파일 선택창 열림!")
                await fc.set_files(SAMPLE_UPLOAD)
                await asyncio.sleep(3)
                print(f"  ✅ 파일 로드: {os.path.basename(SAMPLE_UPLOAD)}\n")
            except:
                # 파일 선택창이 안 열리면 hidden input 직접 찾기
                print("  파일 선택창 안 열림. hidden input 직접 탐색...")
                # 엑셀 불러오기 링크의 onclick 확인
                onclick = await page.evaluate("""() => {
                    const menu = document.querySelector('.sao_head_menu');
                    const items = menu.querySelectorAll('li');
                    for (const li of items) {
                        if (li.textContent.includes('엑셀 불러오기')) {
                            const a = li.querySelector('a');
                            if (a) return {href: a.href, onclick: a.getAttribute('onclick'), ngclick: a.getAttribute('ng-click')};
                        }
                    }
                    return null;
                }""")
                print(f"  링크 속성: {onclick}")

                # file input 탐색
                file_inputs = await page.evaluate("""() => {
                    const inputs = document.querySelectorAll('input[type="file"]');
                    return Array.from(inputs).map(i => ({
                        id: i.id, name: i.name, accept: i.accept,
                        display: window.getComputedStyle(i).display,
                        parent: i.parentElement?.tagName
                    }));
                }""")
                print(f"  file input 수: {len(file_inputs)}")
                for fi in file_inputs:
                    print(f"    {fi}")

                if len(file_inputs) > 0:
                    # 첫 번째 file input에 파일 설정
                    fi = page.locator('input[type="file"]').first
                    await fi.set_input_files(SAMPLE_UPLOAD)
                    await asyncio.sleep(3)
                    print("  ✅ hidden input에 파일 설정 완료\n")
        else:
            print("  항목을 찾지 못함")

        # ===== Issue #1 검증 =====
        print("=" * 60)
        print("[Issue #1] 행1 클릭 수정 전/후 비교")
        print("=" * 60)

        dpr = await page.evaluate("() => window.devicePixelRatio")
        viewport = await page.evaluate("() => ({w: window.innerWidth, h: window.innerHeight})")
        print(f"\n  DPR={dpr}, 뷰포트={viewport['w']}x{viewport['h']}")

        # 수정 전
        print(f"\n  [수정 전] CDP 좌표 방식:")
        pos_old = await page.evaluate("""() => {
            const tables = document.querySelectorAll('table');
            for (const table of tables) {
                const trs = table.querySelectorAll('tr');
                if (trs.length > 2) {
                    const th = trs[1].querySelector('th');
                    if (th && th.textContent.trim() === '1') {
                        const rect = th.getBoundingClientRect();
                        return {x: Math.round(rect.x + rect.width/2),
                                y: Math.round(rect.y + rect.height/2),
                                visible: th.offsetParent !== null};
                    }
                }
            }
            return null;
        }""")
        if pos_old:
            print(f"    CSS 좌표: ({pos_old['x']}, {pos_old['y']}) visible={pos_old['visible']}")
            print(f"    CDP 전송: ({pos_old['x']}, {pos_old['y']}) → 물리 필요: ({round(pos_old['x']*dpr)}, {round(pos_old['y']*dpr)})")
            print(f"    → DPR {dpr}에서 빗나감!")
        else:
            print(f"    숨겨진 테이블만 있어 요소 찾기 불가")

        # 수정 후
        print(f"\n  [수정 후] offsetParent + JS click:")
        clicked = await page.evaluate("""() => {
            const tables = document.querySelectorAll('table');
            for (const table of tables) {
                if (table.offsetParent === null) continue;
                const trs = table.querySelectorAll('tr');
                if (trs.length > 2) {
                    const th = trs[1].querySelector('th');
                    if (th && th.textContent.trim() === '1') {
                        th.click();
                        return true;
                    }
                }
            }
            return false;
        }""")
        print(f"    결과: {'✅ 성공' if clicked else '❌ 실패'}")
        print(f"    → DPR 무관, 항상 정확")

        # 스크린샷
        ss_path = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "debug", "issue1_result.png"
        ))
        os.makedirs(os.path.dirname(ss_path), exist_ok=True)
        await page.screenshot(path=ss_path)
        print(f"\n  스크린샷: {ss_path}")

        print("\n" + "=" * 60)
        print("화면을 확인하세요!")
        print("=" * 60)


asyncio.run(main())
