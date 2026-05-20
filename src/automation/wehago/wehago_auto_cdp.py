"""CDP로 기존 Chrome에 연결하여 WEHAGO 급여 자동화"""
import asyncio
import sys
import os
import subprocess
import time
from playwright.async_api import async_playwright
import openpyxl

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')

CDP_URL = "http://localhost:9222"
WEHAGO_URL = "https://www.wehago.com/"
SMARTA_BASE = "https://smarta.wehago.com"


def log(msg):
    print(msg, flush=True)


def find_chrome():
    """Chrome 실행 파일 경로 찾기"""
    paths = [
        os.path.join(os.environ.get("PROGRAMFILES", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
    ]
    for p in paths:
        if os.path.exists(p):
            return p
    return None


async def check_cdp_available():
    """CDP 포트 9222가 활성인지 확인"""
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:9222/json/version", timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def kill_chrome():
    """기존 Chrome 프로세스 종료"""
    subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)


async def launch_chrome():
    """Chrome을 디버깅 모드로 실행"""
    if await check_cdp_available():
        log("CDP 포트 이미 활성. 기존 Chrome에 연결합니다.")
        return True

    chrome_path = find_chrome()
    if not chrome_path:
        log("Chrome 브라우저를 찾을 수 없습니다.")
        return False

    log("기존 Chrome을 종료하고 디버깅 모드로 재실행합니다...")
    kill_chrome()

    subprocess.Popen([
        chrome_path,
        "--remote-debugging-port=9222",
        "--user-data-dir=" + os.path.join(os.environ.get("TEMP", "/tmp"), "chrome-wehago"),
        "--start-maximized",
        WEHAGO_URL,
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    log("Chrome 실행 대기...")
    for i in range(30):
        await asyncio.sleep(1)
        if await check_cdp_available():
            log("Chrome 연결 성공!")
            return True

    log("Chrome 실행 실패.")
    return False


async def connect_browser(playwright):
    """CDP로 Chrome에 연결하고 첫 페이지 반환"""
    browser = await playwright.chromium.connect_over_cdp(CDP_URL)
    context = browser.contexts[0]
    page = context.pages[0] if context.pages else await context.new_page()
    return browser, context, page


async def wait_for_login(page):
    """WEHAGO 로그인 완료 대기 (수동 로그인)"""
    await page.goto(WEHAGO_URL + "#/main", wait_until="domcontentloaded")
    await asyncio.sleep(2)

    # 로그인 상태 확인: 메인 페이지에 수임처 리스트가 보이면 로그인됨
    if await page.locator("#company_").count() > 0 or await page.locator("text=나의 수임처").count() > 0:
        log("이미 로그인되어 있습니다.")
        return True

    log("\n브라우저에서 WEHAGO 로그인을 진행해 주세요.")
    log("로그인 완료 후 Enter를 누르세요.")
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, input)

    # 로그인 재확인
    await page.reload(wait_until="domcontentloaded")
    await asyncio.sleep(2)
    if await page.locator("text=나의 수임처").count() > 0:
        log("로그인 확인됨.")
        return True

    log("로그인되지 않았습니다.")
    return False


async def get_client_salary_url(page, company_name):
    """수임처의 급여(SmartA) URL 획득

    WEHAGO 메인의 수임처 카드에서 window.open을 가로채어
    급여 버튼 클릭 시 열리는 SmartA URL을 캡처합니다.
    """
    # window.open 가로채기
    await page.evaluate("""() => {
        window.__capturedUrl = null;
        window.__origOpen = window.open;
        window.open = function(url) {
            window.__capturedUrl = url;
            return null;
        };
    }""")

    # 수임처 카드에서 급여 버튼 클릭
    clicked = await page.evaluate("""(companyName) => {
        const allDivs = document.querySelectorAll('[id^="company_"]');
        for (const div of allDivs) {
            const nameEl = div.querySelector('a');
            if (nameEl && nameEl.textContent.trim() === companyName) {
                let card = div;
                for (let i = 0; i < 3; i++) card = card.parentElement;
                const buttons = card.querySelectorAll('button.btn_quick');
                for (const btn of buttons) {
                    if (btn.querySelector('span')?.textContent.trim() === '급여') {
                        btn.click();
                        return true;
                    }
                }
            }
        }
        return false;
    }""", company_name)

    if not clicked:
        log(f"수임처 '{company_name}'의 급여 버튼을 찾지 못했습니다.")
        return None

    # 캡처된 URL 확인
    await asyncio.sleep(1)
    url = await page.evaluate("() => window.__capturedUrl")

    # window.open 복원
    await page.evaluate("() => { window.open = window.__origOpen; }")

    return url


async def goto_salary_page(page, company_name):
    """수임처의 SmartA 급여 메인 페이지로 이동"""
    url = await get_client_salary_url(page, company_name)
    if not url:
        return False

    log(f"SmartA 급여 URL: {url}")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(3)
    log(f"페이지 이동 완료: {await page.title()}")
    return True


async def click_menu(page, menu_id):
    """SmartA 메인의 사이드 메뉴 클릭 (SPA 내부 라우팅)

    menu_id 예시: 'SWSA0101' (급여자료입력), 'SWSA0104' (은행별이체명세) 등
    """
    await page.evaluate("""(menuId) => {
        const link = document.querySelector('a#' + menuId + '.text_link');
        if (link) link.click();
    }""", menu_id)
    await asyncio.sleep(3)
    log(f"메뉴 이동 완료: {await page.title()}")


async def select_dropdown(page, dropdown_index, option_text):
    """커스텀 드롭다운(LS_ngh_select2)에서 옵션 선택

    Args:
        dropdown_index: LS_ngh_select2 요소 중 몇 번째인지 (0-based)
        option_text: 선택할 옵션 텍스트 (부분 매치)
    """
    # 드롭다운 열기
    await page.evaluate("""(idx) => {
        const dd = document.querySelectorAll('.LS_ngh_select2')[idx];
        if (dd) dd.querySelector('.LSbutton').click();
    }""", dropdown_index)
    await asyncio.sleep(1)

    # 옵션 선택
    await page.evaluate("""(args) => {
        const items = document.querySelectorAll('.LSselectResult li');
        for (const li of items) {
            if (li.textContent.includes(args.text)) {
                li.querySelector('a').click();
                return true;
            }
        }
        return false;
    }""", {"text": option_text})
    await asyncio.sleep(1)

    # 선택값 확인
    value = await page.evaluate("""(idx) => {
        const dd = document.querySelectorAll('.LS_ngh_select2')[idx];
        return dd ? dd.querySelector('.fakeinput').textContent.trim() : '';
    }""", dropdown_index)
    log(f"드롭다운 선택: {value}")


async def click_dialog_button(page, button_text):
    """현재 떠 있는 모달/다이얼로그에서 지정된 텍스트의 버튼 클릭"""
    await page.evaluate("""(btnText) => {
        const selectors = ['._isDialog', '.LUX_basic_dialog'];
        let target = null;
        for (const sel of selectors) {
            for (const d of document.querySelectorAll(sel)) {
                if (d.style.display !== 'none') { target = d; break; }
            }
            if (target) break;
        }
        if (!target) return;
        const btns = target.querySelectorAll('button, a');
        for (const b of btns) {
            if (b.textContent.trim().includes(btnText)) { b.click(); return; }
        }
    }""", button_text)
    await asyncio.sleep(1)
    log(f"  모달 버튼 클릭: {button_text}")


async def dismiss_dialogs(page):
    """표시 중인 팝업/다이얼로그가 있으면 모두 닫기

    WEHAGO/SmartA의 다이얼로그를 탐지하여 닫습니다.
    대상: _isDialog, LUX_basic_dialog
    1) '닫기' 텍스트 버튼 → 2) X 버튼 → 3) '확인' 버튼 → 4) '취소' 버튼 순으로 닫습니다.
    팝업이 없으면 아무것도 하지 않으며, 중첩 시 모두 사라질 때까지 반복합니다.
    """
    for _ in range(20):
        closed = await page.evaluate("""() => {
            const selectors = ['._isDialog', '.LUX_basic_dialog'];
            let target = null;
            for (const sel of selectors) {
                for (const d of document.querySelectorAll(sel)) {
                    if (d.style.display !== 'none') { target = d; break; }
                }
                if (target) break;
            }
            if (!target) return null;

            const allBtns = target.querySelectorAll('button, a');

            // 1) 닫기
            for (const btn of allBtns) {
                if (btn.textContent.trim() === '닫기') { btn.click(); return '닫기'; }
            }
            // 2) X (빈 텍스트 WSC_LUXButton)
            const luxBtns = target.querySelectorAll('button.WSC_LUXButton');
            for (const btn of luxBtns) {
                if (!btn.textContent.trim()) { btn.click(); return 'X'; }
            }
            // 3) 확인 in dialog_btnbx
            const confirmBtn = target.querySelector('.dialog_btnbx button');
            if (confirmBtn) { confirmBtn.click(); return '확인(btnbx)'; }
            // 4) 확인
            for (const btn of allBtns) {
                if (btn.textContent.trim() === '확인') { btn.click(); return '확인'; }
            }
            // 5) 취소
            for (const btn of allBtns) {
                if (btn.textContent.trim() === '취소') { btn.click(); return '취소'; }
            }
            return 'stuck';
        }""")
        if not closed:
            return
        log(f"  팝업 닫음 ({closed})")
        await asyncio.sleep(0.5)


async def open_collect_menu(page):
    """우측 끝 #collect 버튼 클릭하여 드롭다운 메뉴 열기"""
    await page.evaluate("""() => {
        const btn = document.querySelector('#collect');
        if (btn) btn.click();
    }""")
    await asyncio.sleep(1)


async def click_menu_item(page, item_text):
    """sao_head_menu 드롭다운에서 특정 텍스트 항목의 a 태그 클릭"""
    return await page.evaluate("""(text) => {
        const menu = document.querySelector('.sao_head_menu');
        if (!menu) return false;
        const items = menu.querySelectorAll('li');
        for (const li of items) {
            if (li.textContent.includes(text)) {
                const a = li.querySelector('a');
                if (a) { a.click(); return true; }
                li.click();
                return true;
            }
        }
        return false;
    }""", item_text)


async def download_excel(page, save_dir="."):
    """급여자료입력 화면에서 엑셀 다운로드

    #collect 드롭다운 → 엑셀 내려받기 클릭 후 파일 저장.
    저장된 파일의 절대경로를 반환.
    """
    log("[엑셀 다운로드] 드롭다운 열기...")
    await open_collect_menu(page)

    download_future = asyncio.Future()

    def on_download(d):
        if not download_future.done():
            log(f"  다운로드 감지: {d.suggested_filename}")
            download_future.set_result(d)

    page.on("download", on_download)

    log("[엑셀 다운로드] 엑셀 내려받기 클릭...")
    await click_menu_item(page, "엑셀 내려받기")

    download = await asyncio.wait_for(download_future, timeout=15)
    fname = download.suggested_filename
    save_path = os.path.join(save_dir, fname)
    await download.save_as(save_path)
    log(f"  저장 완료: {save_path}")
    return os.path.abspath(save_path)


def convert_for_upload(download_path):
    """다운로드 엑셀을 WEHAGO 업로드 양식으로 변환

    다운로드 파일의 2행 헤더(행1 대분류 + 행2 세부항목)를
    단일 헤더 행으로 평탄화하여 모든 열을 보존.
    사원코드는 4자리 0-pad 문자열로 변환 (예: "0005").
    """
    wb_src = openpyxl.load_workbook(download_path)
    ws_src = wb_src["Sheet1"]

    # 헤더 평탄화: 행2(세부항목) 값 우선, 없으면 행1(대분류) 값 사용
    headers = []
    for c in range(1, ws_src.max_column + 1):
        h2 = ws_src.cell(2, c).value
        h1 = ws_src.cell(1, c).value
        if h2 and str(h2).strip():
            headers.append(str(h2).strip())
        elif h1 and str(h1).strip():
            headers.append(str(h1).strip())
        else:
            headers.append(None)

    TEXT_COLS = {"사원코드", "사원명", "부서", "직급", "직종"}

    wb_new = openpyxl.Workbook()
    ws_new = wb_new.active
    ws_new.title = "Sheet1"

    # 헤더 행
    for i, header in enumerate(headers, 1):
        ws_new.cell(1, i).value = header

    # 데이터 행 (행3 ~ 마지막, 합계 제외)
    new_row = 2
    for r in range(3, ws_src.max_row + 1):
        first_val = ws_src.cell(r, 1).value
        if not first_val or first_val == "합계":
            continue

        for c in range(1, ws_src.max_column + 1):
            val = ws_src.cell(r, c).value
            header = headers[c - 1]

            if header == "사원코드" and isinstance(val, str):
                try:
                    val = str(int(val)).zfill(4)
                except (ValueError, TypeError):
                    pass

            if val is None:
                val = "" if header in TEXT_COLS else 0

            ws_new.cell(new_row, c).value = val
        new_row += 1

    base, ext = os.path.splitext(download_path)
    upload_path = f"{base}_업로드{ext}"
    wb_new.save(upload_path)
    log(f"  변환 완료: {upload_path}")
    return os.path.abspath(upload_path)


async def upload_excel(page, file_path, dry_run=True):
    """변환된 엑셀 파일을 WEHAGO에 업로드

    #collect 드롭다운 → 엑셀 불러오기 → file chooser →
    ① 헤더 행 선택 → ② 엑셀제목설정 확인 → 확인 →
    후속 모달에서 dry_run=True면 취소, False면 확인.
    """
    log("[엑셀 업로드] 드롭다운 열기...")
    await open_collect_menu(page)

    log("[엑셀 업로드] 엑셀 불러오기 클릭...")
    async with page.expect_file_chooser(timeout=10000) as fc_info:
        await click_menu_item(page, "엑셀 불러오기")

    file_chooser = await fc_info.value
    log(f"  파일 선택: {file_path}")
    await file_chooser.set_files(file_path)
    await asyncio.sleep(3)

    # ① 엑셀내역 테이블에서 헤더 행(행1) 선택
    log("[엑셀 업로드] ① 헤더 행 선택...")
    cdp = await page.context.new_cdp_session(page)
    pos = await page.evaluate("""() => {
        const tables = document.querySelectorAll('table');
        for (const table of tables) {
            const trs = table.querySelectorAll('tr');
            if (trs.length > 2) {
                const th = trs[1].querySelector('th');
                if (th && th.textContent.trim() === '1') {
                    const rect = th.getBoundingClientRect();
                    return {x: Math.round(rect.x + rect.width / 2), y: Math.round(rect.y + rect.height / 2)};
                }
            }
        }
        return null;
    }""")
    if pos:
        await cdp.send('Input.dispatchMouseEvent', {
            'type': 'mousePressed', 'x': pos['x'], 'y': pos['y'],
            'button': 'left', 'clickCount': 1
        })
        await cdp.send('Input.dispatchMouseEvent', {
            'type': 'mouseReleased', 'x': pos['x'], 'y': pos['y'],
            'button': 'left', 'clickCount': 1
        })
        log("  행1 클릭 완료")
    await asyncio.sleep(1)

    # ② 엑셀제목설정 버튼 클릭
    log("[엑셀 업로드] ② 엑셀제목설정 열기...")
    await page.evaluate("""() => {
        const btns = document.querySelectorAll('button.WSC_LUXButton');
        for (const btn of btns) {
            if (btn.textContent.trim() === '② 엑셀제목설정') {
                btn.click();
                return;
            }
        }
    }""")
    await asyncio.sleep(2)
    log("  제목설정 확인 완료")

    # 확인 버튼 클릭 (모달 하단)
    log("[엑셀 업로드] 확인 버튼 클릭...")
    await page.evaluate("""() => {
        const btns = document.querySelectorAll('button.WSC_LUXButton');
        for (const btn of btns) {
            if (btn.textContent.trim() === '확인') {
                const rect = btn.getBoundingClientRect();
                if (rect.top > 700) { btn.click(); return; }
            }
        }
    }""")
    await asyncio.sleep(5)

    # 후속 모달 1: 데이터 저장 확인 (항상 확인, #confirm 셀렉터 사용)
    log("[엑셀 업로드] 후속 모달 1/3 → #confirm 확인 클릭...")
    await page.evaluate("""() => {
        const btn = document.querySelector('#confirm');
        if (btn) btn.click();
    }""")
    await asyncio.sleep(3)

    # 후속 모달 2: 재계산 여부 (dry_run=True → 취소, False → 확인)
    action = "취소" if dry_run else "확인"
    log(f"[엑셀 업로드] 후속 모달 2/3 → {action} 클릭...")
    await click_dialog_button(page, action)
    await asyncio.sleep(3)

    # 후속 모달 3: 완료 확인 (항상 확인)
    log("[엑셀 업로드] 후속 모달 3/3 → 확인 클릭...")
    await click_dialog_button(page, "확인")
    await asyncio.sleep(2)

    # 업로드 후 에러 감지
    has_error = await page.evaluate("""() => {
        const selectors = ['._isDialog', '.LUX_basic_dialog'];
        for (const sel of selectors) {
            for (const d of document.querySelectorAll(sel)) {
                if (d.style.display !== 'none' && d.offsetParent !== null) {
                    const text = d.textContent.trim();
                    if (text.includes('오류') || text.includes('실패') || text.includes('에러')) {
                        return text.substring(0, 300);
                    }
                }
            }
        }
        return null;
    }""")

    if has_error:
        log(f"  업로드 에러 감지: {has_error}")
        return False

    log("  업로드 완료")
    return True


async def run(dry_run=True):
    """전체 자동화 실행

    Args:
        dry_run: True면 업로드 후 취소(개발용), False면 확인(실제 운영용)
    """
    async with async_playwright() as p:
        # ===== [1] Chrome 실행 =====
        log("[1/10] Chrome 실행...")
        if not await launch_chrome():
            return

        # ===== [2] 연결, 로그인, 팝업 닫기 =====
        log("[2/10] Chrome 연결 및 로그인 확인...")
        browser, context, page = await connect_browser(p)
        if not await wait_for_login(page):
            return
        await dismiss_dialogs(page)

        # ===== [3] 수임처 급여 페이지 이동 =====
        log("[3/10] 수임처 급여 페이지 이동...")
        company_name = "근린커피 상암"
        if not await goto_salary_page(page, company_name):
            return
        await dismiss_dialogs(page)

        # ===== [4] 급여자료입력 메뉴 이동 =====
        log("[4/10] 급여자료입력 메뉴 이동...")
        await click_menu(page, "SWSA0101")
        await dismiss_dialogs(page)

        # ===== [5] 구분 드롭다운: 급여+상여 선택 =====
        log("[5/10] 구분 드롭다운 → 급여+상여 선택...")
        await select_dropdown(page, 0, "급여+상여")

        # ===== [6-7] 복사후 재계산 모달 (조건부) =====
        # 구분 변경 시 모달이 뜨는 경우만 처리, 없으면 스킵
        await asyncio.sleep(1)
        has_modal = await page.evaluate("""() => {
            const selectors = ['._isDialog', '.LUX_basic_dialog'];
            for (const sel of selectors) {
                for (const d of document.querySelectorAll(sel)) {
                    if (d.style.display !== 'none') return true;
                }
            }
            return false;
        }""")
        if has_modal:
            log("[6/10] 복사후 재계산 버튼 클릭...")
            await click_dialog_button(page, "복사후 재계산")
            await asyncio.sleep(1)

            log("[7/10] 확인 모달 → 취소 클릭...")
            await click_dialog_button(page, "취소")
        else:
            log("[6-7/10] 모달 없음 - 스킵")

        # ===== [8] 엑셀 다운로드 =====
        log("[8/10] 엑셀 다운로드...")
        save_dir = os.path.dirname(os.path.abspath(__file__))
        # 프로젝트 루트의 results 디렉토리 사용
        save_dir = os.path.abspath(os.path.join(save_dir, "..", "..", "results"))
        os.makedirs(save_dir, exist_ok=True)
        download_path = await download_excel(page, save_dir)

        # ===== [9] 업로드 양식 변환 =====
        log("[9/10] 업로드 양식 변환...")
        upload_path = convert_for_upload(download_path)

        # ===== [10] 엑셀 업로드 =====
        log("[10/10] 엑셀 업로드...")
        success = await upload_excel(page, upload_path, dry_run=dry_run)

        if success:
            log(f"\n'{company_name}' 급여자료 엑셀 업로드 완료!")
        else:
            log(f"\n'{company_name}' 업로드 중 에러 발생. 화면을 확인하세요.")
        log(f"URL: {page.url}")


if __name__ == "__main__":
    asyncio.run(run())
