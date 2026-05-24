"""급여자료입력 → PDF 다운로드 자동화"""
import asyncio
import sys
import os
import re
import time
from playwright.async_api import async_playwright

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')

if sys.platform == "win32":
    from pywinauto import Desktop as WinDesktop
    import pywinauto.actionlogger
    pywinauto.actionlogger.ActionLogger.logger.handlers = []

CDP_URL = "http://localhost:9223"
PRINT_DIALOG_TITLE = "Duzon - PrintDialog"
PRINT_DIALOG_CLASS = "WindowsForms10.Window.8.app.0.141b42a_r8_ad1"
SAVE_DIALOG_CLASS = "#32770"


def log(msg):
    print(msg, flush=True)


async def dismiss_dialogs(page):
    for _ in range(20):
        closed = await page.evaluate("""() => {
            const selectors = ['._isDialog', '.LUX_basic_dialog'];
            let target = null;
            for (const sel of selectors) {
                for (const d of document.querySelectorAll(sel)) {
                    const cs = window.getComputedStyle(d);
                    if (cs.display !== 'none' && cs.visibility !== 'hidden'
                        && d.offsetParent !== null && d.offsetWidth > 0) { target = d; break; }
                }
                if (target) break;
            }
            if (!target) {
                const all = document.querySelectorAll('*');
                for (const el of all) {
                    const cs = window.getComputedStyle(el);
                    if (cs.position !== 'fixed' || cs.display === 'none'
                        || parseInt(cs.zIndex) < 1000 || el.offsetWidth < 100) continue;
                    if (el.classList.contains('WSC_LUXSnackbar')) continue;
                    if (el.textContent.trim().length === 0) continue;
                    target = el; break;
                }
            }
            if (!target) return null;
            const allBtns = target.querySelectorAll('button, a');
            for (const btn of allBtns) { if (btn.textContent.trim() === '닫기') { btn.click(); return '닫기'; } }
            const luxBtns = target.querySelectorAll('button.WSC_LUXButton');
            for (const btn of luxBtns) { if (!btn.textContent.trim()) { btn.click(); return 'X'; } }
            const confirmBtn = target.querySelector('.dialog_btnbx button');
            if (confirmBtn) { confirmBtn.click(); return '확인(btnbx)'; }
            for (const btn of allBtns) { if (btn.textContent.trim() === '확인' && btn.offsetWidth > 0) { btn.click(); return '확인'; } }
            for (const btn of allBtns) { if (btn.textContent.trim() === '취소') { btn.click(); return '취소'; } }
            return 'stuck';
        }""")
        if not closed:
            return
        log(f"  popup closed ({closed})")
        await asyncio.sleep(0.5)


async def click_menu_item(page, item_text):
    return await page.evaluate("""(text) => {
        const menu = document.querySelector('.sao_head_menu');
        if (!menu) return false;
        const items = menu.querySelectorAll('li');
        for (const li of items) {
            if (li.textContent.includes(text)) {
                const a = li.querySelector('a');
                if (a) { a.click(); return true; }
                li.click(); return true;
            }
        }
        return false;
    }""", item_text)


def _find_print_dialog():
    desktop = WinDesktop(backend='uia')
    return desktop.window(title_re=PRINT_DIALOG_TITLE, class_name=PRINT_DIALOG_CLASS)


def _print_dialog_exists():
    try:
        return _find_print_dialog().exists(timeout=1)
    except Exception:
        return False


def _close_existing_print_dialog():
    if not _print_dialog_exists():
        return
    log("  existing PrintDialog found, cleaning up...")
    try:
        dlg = _find_print_dialog()
        for btn in dlg.descendants(control_type='Button'):
            name = btn.element_info.element.CurrentName
            if name and name == '확인':
                btn.click_input()
                time.sleep(1)
                break
    except Exception:
        pass
    try:
        time.sleep(1)
        _find_print_dialog().child_window(auto_id='btnClose', control_type='Button').click_input()
        time.sleep(2)
    except Exception:
        pass


def _select_print_format(target_text):
    dlg = _find_print_dialog()
    dlg.set_focus()
    time.sleep(0.5)
    cb = dlg.child_window(auto_id='cbContents', control_type='ComboBox')
    open_btn = cb.children(control_type='Button')[0]
    open_btn.click_input()
    time.sleep(1.5)
    items = cb.descendants(control_type='ListItem')
    for item in items:
        name = item.element_info.element.CurrentName
        if name and target_text in name:
            item.click_input()
            log(f"  print format: {name}")
            time.sleep(2)
            return True
    log(f"  format not found: {target_text}")
    return False


def _click_save_pdf():
    dlg = _find_print_dialog()
    dlg.child_window(auto_id='btnSavePDF', control_type='Button').click_input()
    log("  PDF save btn clicked")
    time.sleep(3)


def _handle_save_dialog(save_path):
    desktop = WinDesktop(backend='win32')
    dlg = desktop.window(title='다른 이름으로 저장', class_name=SAVE_DIALOG_CLASS)
    edit = dlg.child_window(class_name='Edit')
    edit.set_edit_text(save_path)
    time.sleep(1)
    save_btn = dlg.child_window(title='저장(&S)', class_name='Button')
    save_btn.click_input()
    time.sleep(3)
    if os.path.exists(save_path) and os.path.getsize(save_path) > 0:
        log(f"  PDF saved: {save_path} ({os.path.getsize(save_path):,} bytes)")
        return True
    log("  PDF save failed")
    return False


def _close_print_dialog():
    dlg = _find_print_dialog()
    dlg.child_window(auto_id='btnClose', control_type='Button').click_input()
    log("  PrintDialog closed")


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0]
        page = context.pages[0]

        # ===== [1] 메인 페이지 =====
        log("[1] WEHAGO main page...")
        await page.goto("https://www.wehago.com/#/main", wait_until="domcontentloaded")
        await asyncio.sleep(3)

        # 전체 탭 선택
        await page.evaluate("""() => {
            const tabs = document.querySelector('ul.main_tab_bx');
            if (tabs) tabs.querySelector('li').querySelector('button').click();
        }""")
        await asyncio.sleep(2)
        await dismiss_dialogs(page)
        log("  main page ready")

        # ===== [2] 수임처 SmartA 급여 URL =====
        company_name = "[테스트] (주)리틀치프코리아"
        log(f"[2] company: {company_name}")

        await page.evaluate("""() => {
            window.__capturedUrl = null;
            window.__origOpen = window.open;
            window.open = function(url) { window.__capturedUrl = url; return null; };
        }""")
        clicked = await page.evaluate("""(cn) => {
            const divs = document.querySelectorAll('[id^="company_"]');
            for (const div of divs) {
                const a = div.querySelector('a');
                if (a && a.textContent.trim() === cn) {
                    let card = div;
                    for (let i = 0; i < 3; i++) card = card.parentElement;
                    for (const btn of card.querySelectorAll('button.btn_quick')) {
                        if (btn.querySelector('span')?.textContent.trim() === '급여') { btn.click(); return true; }
                    }
                }
            }
            return false;
        }""", company_name)
        if not clicked:
            log("  company button not found!")
            return

        await asyncio.sleep(1)
        url = await page.evaluate("() => window.__capturedUrl")
        await page.evaluate("() => { window.open = window.__origOpen; }")
        log(f"  SmartA URL captured")

        # ===== [3] SmartA 이동 =====
        log("[3] navigating to SmartA...")
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        for i in range(15):
            await asyncio.sleep(2)
            if await page.locator("a.text_link").count() > 0:
                break
        log(f"  loaded: {await page.title()}")
        await dismiss_dialogs(page)

        # ===== [4] 급여자료입력(SWSA0101) =====
        log("[4] SWSA0101 menu click...")
        await page.evaluate("""() => {
            const link = document.querySelector('a#SWSA0101.text_link');
            if (link) link.click();
        }""")
        await asyncio.sleep(3)
        log(f"  URL: {page.url}")

        # 간이세액 모달 닫기
        await page.evaluate("""() => {
            const all = document.querySelectorAll('*');
            for (const el of all) {
                const cs = window.getComputedStyle(el);
                if (cs.position !== 'fixed' || cs.display === 'none' ||
                    parseInt(cs.zIndex) <= 100 || el.offsetWidth <= 100) continue;
                if (!el.textContent.includes('간이세액')) continue;
                for (const btn of el.querySelectorAll('button.WSC_LUXButton')) {
                    if (!btn.textContent.trim() && btn.offsetWidth > 0) { btn.click(); return; }
                }
            }
        }""")
        await asyncio.sleep(1)
        await dismiss_dialogs(page)

        # ===== [5] 구분 드롭다운: 급여+상여 =====
        log("[5] dropdown -> 급여+상여...")
        await page.evaluate("""() => {
            const dd = document.querySelectorAll('.LS_ngh_select2')[0];
            if (dd) dd.querySelector('.LSbutton').click();
        }""")
        await asyncio.sleep(1)
        await page.evaluate("""() => {
            const items = document.querySelectorAll('.LSselectResult li');
            for (const li of items) {
                if (li.textContent.includes('급여+상여')) { li.querySelector('a').click(); return; }
            }
        }""")
        await asyncio.sleep(1)

        # ===== [6-7] 복사후 재계산 모달 =====
        has_modal = await page.evaluate("""() => {
            const sels = ['._isDialog', '.LUX_basic_dialog'];
            for (const s of sels) for (const d of document.querySelectorAll(s))
                if (d.style.display !== 'none') return true;
            return false;
        }""")
        if has_modal:
            log("[6] 복사후 재계산 click...")
            await page.evaluate("""() => {
                const sels = ['._isDialog', '.LUX_basic_dialog'];
                for (const s of sels) for (const d of document.querySelectorAll(s)) {
                    if (d.style.display === 'none') continue;
                    for (const b of d.querySelectorAll('button'))
                        if (b.textContent.trim() === '복사후 재계산') { b.click(); return; }
                }
            }""")
            await asyncio.sleep(1)
            log("[7] 취소 click...")
            await page.evaluate("""() => {
                const sels = ['._isDialog', '.LUX_basic_dialog'];
                for (const s of sels) for (const d of document.querySelectorAll(s)) {
                    if (d.style.display === 'none') continue;
                    for (const b of d.querySelectorAll('button'))
                        if (b.textContent.trim() === '취소') { b.click(); return; }
                }
            }""")
            await asyncio.sleep(1)
        else:
            log("[6-7] no modal, skip")

        await page.screenshot(path="current_screen.png")
        log("  screenshot saved (급여자료입력)")

        # ===== [8] PDF 다운로드 =====
        log("[8] PDF download...")
        loop = asyncio.get_event_loop()

        # 기존 PrintDialog 정리
        await loop.run_in_executor(None, _close_existing_print_dialog)

        # #print 버튼 클릭
        log("  #print btn click...")
        await page.evaluate("""() => {
            const btn = document.querySelector('#print');
            if (btn) btn.click();
        }""")
        await asyncio.sleep(1)

        # 일괄출력 클릭
        log("  일괄출력 click...")
        await click_menu_item(page, "일괄출력")

        # PrintDialog 대기
        log("  waiting for PrintDialog...")
        found = False
        for i in range(15):
            await asyncio.sleep(2)
            if await loop.run_in_executor(None, _print_dialog_exists):
                log("  PrintDialog opened!")
                found = True
                break
            if i % 3 == 2:
                log(f"  waiting... {(i+1)*2}s")

        if not found:
            log("  PrintDialog timeout!")
            return

        # 인쇄형태 선택
        print_format = "급여명세(사원당 한장)"
        log(f"  selecting format: {print_format}")
        selected = await loop.run_in_executor(None, _select_print_format, print_format)
        if not selected:
            return

        # PDF 저장 버튼
        log("  clicking PDF save...")
        await loop.run_in_executor(None, _click_save_pdf)

        # Windows 저장 대화상자
        save_dir = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "results"))
        os.makedirs(save_dir, exist_ok=True)
        filename = f"{time.strftime('%Y%m%d_%H%M%S')}_{print_format.split('(')[0]}.pdf"
        save_path = os.path.join(save_dir, filename)
        log(f"  save to: {save_path}")

        saved = await loop.run_in_executor(None, _handle_save_dialog, save_path)
        if not saved:
            log("  PDF save failed!")
            return

        # PrintDialog 종료
        await loop.run_in_executor(None, _close_print_dialog)

        log(f"\nPDF download complete: {save_path}")
        await page.screenshot(path="current_screen.png")


if __name__ == "__main__":
    asyncio.run(main())
