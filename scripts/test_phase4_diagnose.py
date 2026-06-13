"""Phase 4 모달 진단 — 업로드 후속 모달 텍스트 캡처

업로드 과정에서 0.5초 간격으로 visible modal/overlay의 텍스트를 캡처.
"""
import asyncio
import io
import os
import sys

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)


CAPTURE_JS = """() => {
    const results = [];
    // 1) _isDialog / LUX_basic_dialog
    for (const sel of ['._isDialog', '.LUX_basic_dialog']) {
        for (const d of document.querySelectorAll(sel)) {
            if (d.style.display === 'none' || d.offsetParent === null) continue;
            const btns = [...d.querySelectorAll('button')].map(b => b.textContent.trim()).filter(t => t);
            results.push({
                type: sel,
                text: d.textContent.trim().substring(0, 300),
                buttons: btns,
                visible: d.offsetWidth > 0
            });
        }
    }
    // 2) high z-index overlays
    for (const el of document.querySelectorAll('*')) {
        try {
            const cs = window.getComputedStyle(el);
            if (cs.display === 'none' || el.offsetWidth < 30) continue;
            const z = parseInt(cs.zIndex);
            if (z < 1000) continue;
            if (cs.position !== 'fixed' && cs.position !== 'absolute') continue;
            const btns = [...el.querySelectorAll('button')].map(b => b.textContent.trim()).filter(t => t);
            if (btns.length === 0) continue;
            const txt = el.textContent.trim().substring(0, 300);
            if (results.some(r => r.text === txt)) continue;
            results.push({
                type: `overlay z=${z}`,
                text: txt,
                buttons: btns,
                tag: el.tagName,
                cls: el.className?.substring(0, 80)
            });
        } catch(e) {}
    }
    return results;
}"""


async def capture_modals(page, duration_sec=30, interval=0.5):
    """지정 시간 동안 모달 변화를 캡처"""
    seen = set()
    for i in range(int(duration_sec / interval)):
        await asyncio.sleep(interval)
        try:
            modals = await page.evaluate(CAPTURE_JS)
        except Exception as e:
            print(f"  [{i*interval:.1f}s] evaluate 에러: {e}")
            continue

        for m in modals:
            key = m['text'][:100]
            if key not in seen:
                seen.add(key)
                elapsed = (i + 1) * interval
                print(f"\n  [{elapsed:.1f}s] NEW MODAL ({m['type']})")
                print(f"    텍스트: {m['text'][:200]}")
                print(f"    버튼: {m.get('buttons', [])}")


async def main():
    from playwright.async_api import async_playwright
    from src.utils.chrome_cdp import connect_page
    from src.automation.wehago._common import (
        log, wait_for_login, goto_salary_page, dismiss_dialogs,
        navigate_to_swsa0101, compute_target_period,
        _click_modal_text,
    )
    from src.automation.wehago._swsa_excel import (
        download_excel, convert_for_upload,
    )

    CLIENT_NAME = "[테스트] 주식회사 쓰리이소프트"
    year, month = compute_target_period()
    save_dir = os.path.join(ROOT, "results", f"test_phase4_{year}{month:02d}")

    # 이전에 다운로드한 업로드 파일 확인
    import glob
    upload_files = glob.glob(os.path.join(save_dir, "*_업로드.xlsx"))
    if not upload_files:
        print("업로드 파일이 없음. 먼저 다운로드/변환 필요.")
        return
    upload_path = upload_files[-1]
    print(f"사용할 파일: {upload_path}")

    print(f"\n{'='*60}")
    print(f"Phase 4 모달 진단 (dry_run=False)")
    print(f"  수임처: {CLIENT_NAME}")
    print(f"  귀속연월: {year}.{month:02d}")
    print(f"{'='*60}\n")

    async with async_playwright() as p:
        browser, context, page = await connect_page(p)
        print(f"CDP 연결: {page.url}")

        # SmartA 페이지에 있으면 바로 진행, 아니면 이동
        if 'SWSA0101' not in page.url:
            logged_in = await wait_for_login(page)
            if not logged_in:
                return
            await dismiss_dialogs(page)
            await goto_salary_page(page, CLIENT_NAME)
            await dismiss_dialogs(page)
            await navigate_to_swsa0101(page, year=year, month=month)
        else:
            print("이미 SWSA0101 페이지에 있음.")
            await dismiss_dialogs(page)

        # 엑셀 업로드 전 모달 정리
        await dismiss_dialogs(page)

        # 업로드 수동 진행 + 모달 캡처
        from src.automation.wehago._common import (
            close_collect_menu, open_collect_menu, click_menu_item,
        )

        print("\n--- 엑셀 불러오기 ---")
        await close_collect_menu(page)
        await open_collect_menu(page)

        file_set = False
        item_rect = await page.evaluate("""() => {
            const menu = document.querySelector('.sao_head_menu');
            if (!menu) return null;
            const items = menu.querySelectorAll('li');
            for (const li of items) {
                if (li.textContent.includes('엑셀 불러오기') && li.offsetHeight > 0) {
                    const rect = li.getBoundingClientRect();
                    return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
                }
            }
            return null;
        }""")
        if item_rect:
            try:
                async with page.expect_file_chooser(timeout=15000) as fc_info:
                    await page.mouse.click(item_rect['x'], item_rect['y'])
                fc = await fc_info.value
                await fc.set_files(upload_path)
                file_set = True
                print("  파일 선택 완료")
            except Exception as e:
                print(f"  파일 선택 실패: {e}")
                return

        print("\n--- 모달 캡처 시작 (60초) ---")
        print("  (모달이 나타날 때마다 기록)")

        # 파일 선택 후 ~후속 모달까지 전체 캡처
        await capture_modals(page, duration_sec=60, interval=0.5)

        print("\n--- 캡처 종료 ---")


if __name__ == "__main__":
    asyncio.run(main())
