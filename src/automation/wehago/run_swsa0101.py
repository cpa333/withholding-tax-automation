"""급여자료입력 (SWSA0101) 자동화

엑셀 다운로드 → 업로드 양식 변환 → 엑셀 업로드 → PDF 발급.

사전 조건:
- page가 이미 SmartA 급여 페이지에 있어야 함
- Chrome CDP 모드(port 9223) 실행 상태
"""
import asyncio
import os
import sys
import time

from src.automation.wehago._common import (
    log, dismiss_dialogs, click_menu, click_dialog_button,
    open_collect_menu, click_menu_item, _click_modal_text,
    select_dropdown, goto_menu_page,
)

if sys.platform == "win32":
    import openpyxl
    from pywinauto import Desktop as WinDesktop
    import pywinauto.actionlogger
    pywinauto.actionlogger.ActionLogger.logger.handlers = []

PRINT_DIALOG_TITLE_RE = "Duzon.*PrintDialog"
PRINT_DIALOG_CLASS_RE = "WindowsForms10\.Window.*"
SAVE_DIALOG_CLASS = "#32770"
DEFAULT_PRINT_FORMAT = "급여명세(사원당 한장)"


# ═══════════════════════════════════════════════════════════════════════
# 엑셀 다운로드 / 변환 / 업로드
# ═══════════════════════════════════════════════════════════════════════

async def download_excel(page, save_dir="."):
    """급여자료입력 화면에서 엑셀 다운로드"""
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

    2행 헤더 평탄화, 합계 행 제거, 사원코드 4자리 0-pad.
    """
    wb_src = openpyxl.load_workbook(download_path)
    ws_src = wb_src["Sheet1"]

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

    for i, header in enumerate(headers, 1):
        ws_new.cell(1, i).value = header

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


async def _handle_code_link_modal(page):
    """사원코드연결 모달 처리: 변환 → '제외하고 변환됩니다' 확인

    엑셀 파일의 사원과 급여관리 사원이 다를 때 등장.
    파일 선택 직후 또는 후속 모달 처리 중간에 나타날 수 있음.
    """
    for _ in range(3):
        found = await page.evaluate("""() => {
            const all = document.querySelectorAll('*');
            for (const el of all) {
                try {
                    const cs = window.getComputedStyle(el);
                    if ((cs.position !== 'fixed' && cs.position !== 'absolute')
                        || cs.display === 'none' || el.offsetWidth < 50) continue;
                    const z = parseInt(cs.zIndex);
                    if (z < 1000) continue;
                    const txt = el.textContent;
                    if (!txt.includes('사원코드') || !txt.includes('연결')) continue;
                    if (txt.includes('급여대장')) continue;
                    const btns = el.querySelectorAll('button');
                    for (const btn of btns) {
                        if (btn.textContent.trim() === '변환' && btn.offsetWidth > 0) {
                            btn.click(); return 'clicked';
                        }
                    }
                } catch(e) {}
            }
            return null;
        }""")
        if found:
            log("  사원코드연결 → 변환 클릭")
            await asyncio.sleep(2)
            # "연결되지 않은 사원 및 연말 입력된 사원은 제외하고 변환됩니다" → 확인
            await _click_modal_text(page, "제외하고 변환", "확인")
            await asyncio.sleep(1)
        else:
            break


async def upload_excel(page, file_path, dry_run=True):
    """변환된 엑셀 파일을 WEHAGO에 업로드"""
    log("[엑셀 업로드] 화면 정리...")
    await dismiss_dialogs(page)

    # 드롭다운 열기 (토글 상태 검증 + 재시도)
    log("[엑셀 업로드] 드롭다운 열기...")
    for attempt in range(3):
        await open_collect_menu(page)
        visible_count = await page.evaluate("""() => {
            const menu = document.querySelector('.sao_head_menu');
            if (!menu) return 0;
            return Array.from(menu.querySelectorAll('li'))
                .filter(li => li.offsetHeight > 0).length;
        }""")
        if visible_count > 0:
            log(f"  드롭다운 열림 (항목 {visible_count}개)")
            break
        log(f"  드롭다운 안 열림, 재시도 {attempt + 1}/3...")
        await asyncio.sleep(1)
    else:
        log("  WARNING: 드롭다운을 열지 못함. 계속 진행합니다.")

    # --- 엑셀 불러오기: 3단계 fallback ---
    log("[엑셀 업로드] 엑셀 불러오기 클릭...")
    file_set = False

    # 1순위: page.mouse.click — 실제 CDP 마우스 이벤트 (신뢰된 사용자 제스처)
    item_rect = await page.evaluate("""() => {
        const menu = document.querySelector('.sao_head_menu');
        if (!menu) return null;
        const items = menu.querySelectorAll('li');
        for (const li of items) {
            if (li.textContent.includes('엑셀 불러오기') && li.offsetHeight > 0) {
                const rect = li.getBoundingClientRect();
                return {
                    x: rect.x + rect.width / 2,
                    y: rect.y + rect.height / 2
                };
            }
        }
        return null;
    }""")

    if item_rect:
        log(f"  항목 위치: ({round(item_rect['x'])}, {round(item_rect['y'])})")
        try:
            async with page.expect_file_chooser(timeout=15000) as fc_info:
                await page.mouse.click(item_rect['x'], item_rect['y'])
            file_chooser = await fc_info.value
            log(f"  파일 선택: {file_path}")
            await file_chooser.set_files(file_path)
            file_set = True
        except Exception as e:
            log(f"  mouse.click 파일 선택창 실패: {e}")

    # 2순위: JS evaluate click (기존 방식)
    if not file_set:
        log("[엑셀 업로드] JS evaluate 클릭으로 재시도...")
        try:
            async with page.expect_file_chooser(timeout=15000) as fc_info:
                await click_menu_item(page, "엑셀 불러오기")
            file_chooser = await fc_info.value
            log(f"  파일 선택: {file_path}")
            await file_chooser.set_files(file_path)
            file_set = True
        except Exception as e:
            log(f"  JS evaluate 파일 선택창 실패: {e}")

    # 3순위: hidden file input 직접 설정
    if not file_set:
        log("[엑셀 업로드] hidden file input 직접 설정...")
        await click_menu_item(page, "엑셀 불러오기")
        await asyncio.sleep(2)
        fi_count = await page.evaluate(
            "() => document.querySelectorAll('input[type=\"file\"]').length"
        )
        log(f"  file input 수: {fi_count}")
        if fi_count > 0:
            fi = page.locator('input[type="file"]').first
            await fi.set_input_files(file_path)
            log(f"  파일 설정 완료: {file_path}")
            file_set = True
        else:
            log("  ERROR: file input을 찾지 못해 업로드 불가")
            return False

    await asyncio.sleep(3)

    # 사원코드연결 모달 (파일 선택 직후 등장 가능)
    await _handle_code_link_modal(page)

    # ① 헤더 행(행1) 선택
    log("[엑셀 업로드] ① 헤더 행 선택...")
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
    if clicked:
        log("  행1 클릭 완료")
    else:
        log("  행1 요소를 찾지 못함")
    await asyncio.sleep(1)

    # ② 엑셀제목설정
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

    log("[엑셀 업로드] ② 제목설정 확인...")
    await _click_modal_text(page, "엑셀제목", "확인")
    await asyncio.sleep(2)

    # 확인 버튼
    log("[엑셀 업로드] 확인 버튼 클릭...")
    await page.evaluate("""() => {
        const selectors = ['._isDialog', '.LUX_basic_dialog'];
        for (const sel of selectors) {
            for (const dialog of document.querySelectorAll(sel)) {
                if (dialog.style.display === 'none' || dialog.offsetParent === null) continue;
                const btns = dialog.querySelectorAll('button.WSC_LUXButton');
                for (const btn of btns) {
                    if (btn.textContent.trim() === '확인') {
                        btn.click();
                        return;
                    }
                }
            }
        }
    }""")
    await asyncio.sleep(5)

    # 후속 모달 1: 데이터 저장
    log("[엑셀 업로드] 후속 1/5 → #confirm 확인...")
    await page.evaluate("""() => {
        const btn = document.querySelector('#confirm');
        if (btn) btn.click();
    }""")
    await asyncio.sleep(3)

    # 후속 모달 2: 연결되지 않은 사원
    log("[엑셀 업로드] 후속 2/5 → '연결되지 않은 사원' 확인...")
    await _click_modal_text(page, "연결되지 않은 사원", "확인")
    await asyncio.sleep(3)

    # 사원코드연결 모달 (후속 모달 처리 중간에 등장 가능)
    await _handle_code_link_modal(page)

    # 후속 모달 3: 삭제후 업로드
    action = "취소" if dry_run else "확인"
    log(f"[엑셀 업로드] 후속 3/5 → '삭제후 업로드' {action}...")
    await _click_modal_text(page, "삭제후 업로드", action)
    await asyncio.sleep(3)

    # 후속 모달 4: 변환 취소/완료
    if dry_run:
        log("[엑셀 업로드] 후속 4/5 → '변환이 취소' 확인...")
        await _click_modal_text(page, "변환이 취소", "확인")
    else:
        log("[엑셀 업로드] 후속 4/5 → 완료 확인...")
        await click_dialog_button(page, "확인")
    await asyncio.sleep(2)

    # 에러 감지
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


# ═══════════════════════════════════════════════════════════════════════
# PDF 다운로드 (OS-level PrintDialog 제어)
# ═══════════════════════════════════════════════════════════════════════

async def open_print_dialog(page):
    """브라우저에서 #print 버튼 → 일괄출력 메뉴 클릭하여 PrintDialog 실행"""
    log("[PDF] #print 버튼 클릭...")
    await page.evaluate("""() => {
        const btn = document.querySelector('#print');
        if (btn) btn.click();
    }""")
    await asyncio.sleep(1)

    log("[PDF] 일괄출력 메뉴 클릭...")
    await click_menu_item(page, "일괄출력")

    if sys.platform != "win32":
        log("  Windows 전용 기능입니다.")
        return False

    log("[PDF] PrintDialog 대기...")
    for i in range(15):
        await asyncio.sleep(2)
        if _print_dialog_exists():
            log("  PrintDialog 열림 확인")
            return True
        if i % 3 == 2:
            log(f"  대기 중... {(i+1)*2}초")

    log("  PrintDialog 열림 타임아웃")
    return False


def _find_print_dialog():
    desktop = WinDesktop(backend='uia')
    return desktop.window(title_re=PRINT_DIALOG_TITLE_RE, class_name_re=PRINT_DIALOG_CLASS_RE)


def _print_dialog_exists():
    try:
        dlg = _find_print_dialog()
        return dlg.exists(timeout=1)
    except Exception:
        return False


def _close_existing_print_dialog():
    """기존 PrintDialog가 떠 있으면 종료 + 경고 모달 처리"""
    if not _print_dialog_exists():
        return

    log("  기존 PrintDialog 감지. 정리 중...")

    try:
        dlg = _find_print_dialog()
        for btn in dlg.descendants(control_type='Button'):
            name = btn.element_info.element.CurrentName
            if name and name == '확인':
                btn.click_input()
                log("  경고 모달 '확인' 클릭")
                time.sleep(1)
                break
    except Exception:
        pass

    try:
        time.sleep(1)
        dlg = _find_print_dialog()
        dlg.child_window(auto_id='btnClose', control_type='Button').click_input()
        log("  기존 PrintDialog 종료")
        time.sleep(2)
    except Exception:
        pass


def _select_print_format(target_text):
    """PrintDialog 인쇄형태 드롭다운에서 항목 선택"""
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
            log(f"  인쇄형태 선택: {name}")
            time.sleep(2)
            return True

    log(f"  인쇄형태 '{target_text}' 항목을 찾지 못함")
    return False


def _click_save_pdf():
    """PrintDialog에서 PDF 저장 버튼 클릭"""
    dlg = _find_print_dialog()
    btn = dlg.child_window(auto_id='btnSavePDF', control_type='Button')
    btn.click_input()
    log("  PDF 저장 버튼 클릭")
    time.sleep(3)


def _handle_save_dialog(save_path):
    """Windows '다른 이름으로 저장' 대화상자에서 경로 입력 후 저장"""
    desktop = WinDesktop(backend='win32')
    dlg = desktop.window(title='다른 이름으로 저장', class_name=SAVE_DIALOG_CLASS)

    edit = dlg.child_window(class_name='Edit')
    edit.set_edit_text(save_path)
    time.sleep(1)

    save_btn = dlg.child_window(title='저장(&S)', class_name='Button')
    save_btn.click_input()
    time.sleep(3)

    if os.path.exists(save_path) and os.path.getsize(save_path) > 0:
        log(f"  PDF 저장 완료: {save_path} ({os.path.getsize(save_path):,} bytes)")
        return True

    log("  PDF 파일 저장 실패")
    return False


def _close_print_dialog():
    """PrintDialog 종료"""
    dlg = _find_print_dialog()
    dlg.child_window(auto_id='btnClose', control_type='Button').click_input()
    log("  PrintDialog 종료")


async def download_pdf(page, save_dir, print_format=DEFAULT_PRINT_FORMAT):
    """PrintDialog를 통해 PDF 다운로드"""
    if sys.platform != "win32":
        log("  PDF 다운로드는 Windows 전용 기능입니다.")
        return None

    loop = asyncio.get_event_loop()

    # 기존 PrintDialog 정리
    await loop.run_in_executor(None, _close_existing_print_dialog)

    # PrintDialog 실행
    if not await open_print_dialog(page):
        return None

    # 인쇄형태 선택
    selected = await loop.run_in_executor(None, _select_print_format, print_format)
    if not selected:
        return None

    # PDF 버튼
    await loop.run_in_executor(None, _click_save_pdf)

    # Windows 저장 대화상자
    os.makedirs(save_dir, exist_ok=True)
    filename = f"{time.strftime('%Y%m%d_%H%M%S')}_{print_format.split('(')[0]}.pdf"
    save_path = os.path.join(save_dir, filename)

    saved = await loop.run_in_executor(None, _handle_save_dialog, save_path)
    if not saved:
        return None

    # PrintDialog 종료
    await loop.run_in_executor(None, _close_print_dialog)

    return os.path.abspath(save_path)


# ═══════════════════════════════════════════════════════════════════════
# 메인 플로우
# ═══════════════════════════════════════════════════════════════════════

async def run_swsa0101(page, save_dir, *, dry_run=True):
    """급여자료입력 전체 자동화

    Args:
        page: SmartA 급여 페이지에 위치한 Playwright page
        save_dir: 파일 저장 디렉토리
        dry_run: True면 업로드 후 취소(테스트), False면 확인(실운영)
    """
    # [1] SWSA0101 메뉴 이동
    # 다른 메뉴(SWTA/SWER) 실행 후 URL이 바뀐 상태일 수 있으므로
    # 사이드바 클릭 → URL 해시 교체 순으로 시도
    log("[SWSA0101] 급여자료입력 메뉴 이동...")
    current_url = page.url
    if "SWSA0101" not in current_url:
        await click_menu(page, "SWSA0101")
        await asyncio.sleep(3)
        if "SWSA0101" not in page.url:
            await goto_menu_page(page, "SWSA0101")
            await asyncio.sleep(3)
    await dismiss_dialogs(page)

    # 간이세액 개정 안내 모달 닫기
    log("[SWSA0101] 간이세액 안내 모달 닫기...")
    await page.evaluate("""() => {
        const all = document.querySelectorAll('*');
        for (const el of all) {
            const cs = window.getComputedStyle(el);
            if (cs.position !== 'fixed' || cs.display === 'none' ||
                parseInt(cs.zIndex) <= 100 || el.offsetWidth <= 100) continue;
            if (!el.textContent.includes('간이세액')) continue;
            const btns = el.querySelectorAll('button.WSC_LUXButton');
            for (const btn of btns) {
                if (!btn.textContent.trim() && btn.offsetWidth > 0) { btn.click(); return; }
            }
        }
    }""")
    await asyncio.sleep(1)
    await dismiss_dialogs(page)

    # [2] 구분 드롭다운 → 급여+상여
    log("[SWSA0101] 구분 → 급여+상여 선택...")
    await select_dropdown(page, 0, "급여+상여")

    # [3] 복사후 재계산 모달 (조건부)
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
        log("[SWSA0101] 복사후 재계산 → 취소...")
        await click_dialog_button(page, "복사후 재계산")
        await asyncio.sleep(1)
        await click_dialog_button(page, "취소")
    else:
        log("[SWSA0101] 모달 없음 - 스킵")

    # [4] 엑셀 다운로드
    log("[SWSA0101] 엑셀 다운로드...")
    download_path = await download_excel(page, save_dir)

    # [5] 업로드 양식 변환
    log("[SWSA0101] 업로드 양식 변환...")
    upload_path = convert_for_upload(download_path)

    # [5.5] 업로드 전 모달 정리
    log("[SWSA0101] 업로드 전 화면 정리...")
    await dismiss_dialogs(page)

    # [6] 엑셀 업로드
    log("[SWSA0101] 엑셀 업로드...")
    success = await upload_excel(page, upload_path, dry_run=dry_run)
    if success:
        log("  업로드 완료!")
    else:
        log("  업로드 중 에러 발생. 화면을 확인하세요.")

    # [7] PDF 다운로드
    log("[SWSA0101] PDF 다운로드...")
    pdf_path = await download_pdf(page, save_dir)
    if pdf_path:
        log(f"  PDF 완료: {pdf_path}")
    else:
        log("  PDF 다운로드 실패")

    # 급여대장 일괄인쇄 모달 닫기
    log("[SWSA0101] 일괄인쇄 모달 정리...")
    for _ in range(3):
        closed = await page.evaluate("""() => {
            const all = document.querySelectorAll('*');
            for (const el of all) {
                try {
                    const cs = window.getComputedStyle(el);
                    if ((cs.position !== 'fixed' && cs.position !== 'absolute')
                        || cs.display === 'none' || el.offsetWidth < 50) continue;
                    const z = parseInt(cs.zIndex);
                    if (z < 1000) continue;
                    if (!el.textContent.includes('일괄인쇄') && !el.textContent.includes('일괄PDF')) continue;
                    const btns = el.querySelectorAll('button');
                    for (const btn of btns) {
                        if (btn.textContent.trim().startsWith('닫기') && btn.offsetWidth > 0) {
                            btn.click(); return 'closed';
                        }
                    }
                } catch(e) {}
            }
            return null;
        }""")
        if closed:
            log("  일괄인쇄 모달 닫음")
            await asyncio.sleep(0.5)
        else:
            break

    log("[SWSA0101] 완료")


# ═══════════════════════════════════════════════════════════════════════
# 독립 실행
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import io
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')

    async def _main():
        from playwright.async_api import async_playwright
        from src.utils.chrome_cdp import launch_chrome, connect_page
        from src.automation.wehago._common import wait_for_login, goto_salary_page

        company = input("수임처 이름: ").strip()
        if not company:
            print("수임처 이름이 필요합니다.")
            return

        launch_chrome()
        async with async_playwright() as p:
            browser, context, page = await connect_page(p)
            if not await wait_for_login(page):
                return
            await dismiss_dialogs(page)
            if not await goto_salary_page(page, company):
                return
            await dismiss_dialogs(page)

            save_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "results"))
            await run_swsa0101(page, save_dir, dry_run=True)

    asyncio.run(_main())
