"""국민연금 EDI 사업장 선택/검색 모듈

사업장전환 모달, 검색, 더블클릭 선택, 목록 조회.
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from src.utils.log import log
from src.utils.human import human_delay
from src.utils.nexacro import (
    nexacro_dblclick_cell_viewport,
    nexacro_click_button_viewport,
    nexacro_wait_and_click,
    nexacro_find_row,
    nexacro_get_grid_data,
)
from src.automation.nps._constants import GRID_WORKPLACE, BTN_CHANGE_WORKPLACE

# 로컬 별칭
nexacro_dblclick_cell = nexacro_dblclick_cell_viewport
nexacro_click_button = nexacro_click_button_viewport


# ─── 사업장 전환 ───────────────────────────────────────────────────────────────

async def switch_workplace(page, workplace_name, management_number=""):
    """사업장전환 버튼으로 사업장 전환"""
    log("사업장전환 버튼 클릭...")
    result = await nexacro_click_button(page, BTN_CHANGE_WORKPLACE)
    if not result.get("ok"):
        log(f"  ERROR: 사업장전환 버튼 실패 - {result}")
        return False
    await human_delay(2)

    ok = await select_workplace(page, workplace_name, management_number)
    if ok:
        log(f"  사업장 전환 완료: {workplace_name}")
    return ok


async def _search_workplace_in_modal(page, search_text, search_by_mgmt_no=False):
    """사업장전환 모달의 검색 입력란에 텍스트 입력 후 검색 실행"""
    MODAL_SEARCH = (
        "mainframe.VFrameSet.FrameSdi.ChangeBusi"
        ".form.divPopBg.form.divPopWork.form.div01.form"
    )
    await nexacro_click_button(page, f"{MODAL_SEARCH}.cbo00.dropbutton")
    await human_delay(1)

    item = "item_1" if search_by_mgmt_no else "item_0"
    result = await nexacro_wait_and_click(
        page, f"{MODAL_SEARCH}.cbo00.combolist.{item}", max_wait=5
    )
    if not result.get("ok"):
        log(f"  WARN: 드롭다운 항목 선택 실패 - {result}")
    await human_delay(1)

    await page.evaluate("""(args) => {
        const input = document.getElementById(args.inputId + ":input");
        if (input) {
            input.value = '';
            input.dispatchEvent(new Event("input", {bubbles: true}));
            input.value = args.text;
            input.dispatchEvent(new Event("input", {bubbles: true}));
            input.dispatchEvent(new Event("change", {bubbles: true}));
            return true;
        }
        return false;
    }""", {"inputId": f"{MODAL_SEARCH}.edt08", "text": search_text})
    await human_delay(0.5)

    await nexacro_click_button(page, f"{MODAL_SEARCH}.btn00")


async def open_workplace_selector(page):
    """사업장 선택 모달(업무대행서비스) 열기"""
    clicked = await page.evaluate("""() => {
        const all = document.querySelectorAll('*');
        for (const el of all) {
            if (el.offsetParent === null) continue;
            const text = (el.textContent || '').trim();
            if (text !== '업무대행서비스') continue;
            if (el.tagName === 'A' || el.tagName === 'SPAN' || el.tagName === 'DIV') {
                el.click();
                return 'clicked: ' + el.tagName;
            }
        }
        return null;
    }""")
    if clicked:
        log(f"  업무대행서비스 메뉴 클릭: {clicked}")
    await human_delay(2)

    clicked2 = await page.evaluate("""() => {
        const all = document.querySelectorAll('*');
        for (const el of all) {
            if (el.offsetParent === null) continue;
            const text = (el.textContent || '').trim();
            if (text !== '위탁사업장') continue;
            if (el.tagName === 'A' || el.tagName === 'SPAN' || el.tagName === 'DIV') {
                el.click();
                return 'clicked: ' + el.tagName;
            }
        }
        return null;
    }""")
    if clicked2:
        log(f"  위탁사업장 메뉴 클릭: {clicked2}")
    await human_delay(2)


async def select_workplace(page, workplace_name, management_number=""):
    """사업장 선택 모달에서 특정 사업장을 더블클릭으로 선택"""
    if management_number:
        log(f"  사업장 검색: 관리번호 '{management_number}'")
        await _search_workplace_in_modal(page, management_number, search_by_mgmt_no=True)
        await human_delay(2)
        result = await nexacro_dblclick_cell(page, GRID_WORKPLACE, row=0, col=2)
        if result.get("ok"):
            log(f"  사업장 선택 완료: {result.get('text', '')}")
            await human_delay(3)
            return True
        log(f"  사업장 선택 실패: {result}")
        return False

    log(f"  사업장 검색: '{workplace_name}'")

    row = await nexacro_find_row(page, GRID_WORKPLACE, col=2, text=workplace_name)

    if row is None:
        log(f"  표시 목록에 없음 — 모달 검색으로 찾는 중...")
        await _search_workplace_in_modal(page, workplace_name)
        await human_delay(2)
        row = await nexacro_find_row(page, GRID_WORKPLACE, col=2, text=workplace_name)

    if row is None:
        log(f"  '{workplace_name}' 사업장을 찾지 못했습니다.")
        return False

    log(f"  '{workplace_name}' 발견 (row={row}). 더블클릭 선택 중...")
    result = await nexacro_dblclick_cell(page, GRID_WORKPLACE, row=row, col=2)

    if result.get("ok"):
        log(f"  사업장 선택 완료: {result.get('text', '')}")
        await human_delay(3)
        return True

    log(f"  사업장 선택 실패: {result}")
    return False


async def select_workplace_by_index(page, index):
    """사업장 선택 모달에서 N번째(0-based) 사업장 선택"""
    log(f"  사업장 {index + 1}번째 행 선택 중...")
    result = await nexacro_dblclick_cell(page, GRID_WORKPLACE, row=index, col=2)

    if result.get("ok"):
        log(f"  사업장 선택 완료: {result.get('text', '')}")
        await human_delay(3)
        return True

    log(f"  사업장 선택 실패: {result}")
    return False


async def list_workplaces(page):
    """현재 사업장 목록의 가시 행 데이터 반환"""
    data = await nexacro_get_grid_data(page, GRID_WORKPLACE)
    workplaces = []
    for i, row in enumerate(data):
        workplaces.append({
            "index": i,
            "number": row[1] if len(row) > 1 else "",
            "name": row[2] if len(row) > 2 else "",
        })
    return workplaces
