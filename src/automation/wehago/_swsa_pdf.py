"""SWSA0101 PDF 다운로드 모듈 (OS-level PrintDialog 제어)

Windows pywinauto로 Duzon PrintDialog를 제어하여 PDF 저장.
Windows 전용 — 비 Windows 환경에서는 동작하지 않음.
"""

import asyncio
import os
import sys
import time

from src.automation.wehago._common import (
    log, click_menu_item,
)
from src.automation.wehago._swsa_constants import (
    PRINT_DIALOG_TITLE_RE,
    PRINT_DIALOG_CLASS_RE,
    SAVE_DIALOG_CLASS,
    DEFAULT_PRINT_FORMAT,
)

if sys.platform == "win32":
    from pywinauto import Desktop as WinDesktop
    import pywinauto.actionlogger
    pywinauto.actionlogger.ActionLogger.logger.handlers = []


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
