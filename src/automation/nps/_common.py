"""국민연금 EDI 자동화 공통 함수 모듈

Nexacro 기반 edi.nps.or.kr 사이트 제어를 위한 유틸리티.
모든 NPS 자동화 플로우에서 공유.

하위 모듈에서 분할 관리:
- _output.py:  결정내역 출력/PDF/Excel 다운로드, 탭 제어

이 모듈은 모든 하위 모듈을 재export하여
기존 `from src.automation.nps._common import X` import를
변경 없이 유지.
"""

import asyncio
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from src.utils.chrome_cdp import launch_chrome, CDP_URL
from src.utils.log import log
from src.utils.human import human_delay
from src.utils.nexacro import (
    nexacro_dblclick_cell_viewport,
    nexacro_click_button_viewport,
    nexacro_wait_and_click,
    nexacro_find_row,
    nexacro_get_grid_data,
)
from src.utils.polling import wait_for_element

# ─── 상수 ────────────────────────────────────────────────────────────────────

NPS_URL = "https://edi.nps.or.kr"
NPS_NEXACRO_URL = "https://edi.nps.or.kr/nexacro/index.html"

# Nexacro 그리드 ID prefix
GRID_WORKPLACE = (
    "mainframe.VFrameSet.FrameSdi.ChangeBusi"
    ".form.divPopBg.form.divPopWork.form.grdList"
)
GRID_DECISION_LIST = (
    "mainframe.VFrameSet.FrameSdi.form.divWork_M08010000"
    ".form.divWork.form.grdList"
)

# 사업장전환 버튼
BTN_CHANGE_WORKPLACE = (
    "mainframe.VFrameSet.FrameSdi.form.divHeader.form.divHeader.form.btnChangeBusi"
)

# Nexacro 헬퍼 로컬 별칭
nexacro_dblclick_cell = nexacro_dblclick_cell_viewport
nexacro_click_button = nexacro_click_button_viewport

# ─── 출력 모듈 재export ──────────────────────────────────────────────────────
from src.automation.nps._output import (
    TAB_FINAL,
    TAB_RECEIPT,
    TAB_MEMBER,
    TAB_RETRO,
    TAB_GOVT,
    TAB_BTN_PREFIX,
    GRID_DECISION_DETAIL,
    BTN_OUTPUT,
    BTN_EXCEL_SAVE,
    BTN_INTEGRATED_SAVE,
    MODAL_PREFIX,
    RADIO_FULL_SSN,
    BTN_MODAL_CONFIRM,
    BTN_MODAL_CANCEL,
    EXCEL_MODAL_PREFIX,
    EXCEL_RADIO_FULL_SSN,
    EXCEL_BTN_CONFIRM,
    INTEGRATED_MODAL_PREFIX,
    INTEGRATED_RADIO_FULL_SSN,
    INTEGRATED_BTN_CONFIRM,
    click_detail_tab,
    output_with_full_ssn,
    download_pdf_from_preview,
    save_excel,
    save_integrated,
    process_tab_download,
)


# ─── 연결/로그인 ────────────────────────────────────────────────────────────

async def connect_page(playwright):
    """CDP로 Chrome에 연결하고 NPS EDI 탭 우선 반환"""
    from src.utils.stealth import stealth_all_pages, register_auto_stealth

    browser = await playwright.chromium.connect_over_cdp(CDP_URL)
    context = browser.contexts[0]

    await stealth_all_pages(context)
    register_auto_stealth(context)

    for pg in context.pages:
        try:
            if "edi.nps.or.kr" in pg.url:
                return browser, context, pg
        except Exception:
            continue

    page = context.pages[0] if context.pages else await context.new_page()
    return browser, context, page


async def wait_for_login(page):
    """NPS EDI 로그인 완료 대기 (수동 로그인)"""
    if "nexacro" in page.url:
        log("이미 로그인되어 있습니다.")
        return True

    log("\n브라우저에서 국민연금 EDI 로그인을 진행해 주세요.")
    log("공동인증서로 로그인 후 자동으로 감지됩니다.")

    for i in range(180):
        await asyncio.sleep(5)
        try:
            if "nexacro" in page.url:
                log("로그인 확인됨.")
                return True
        except Exception:
            pass
        if i % 6 == 5:
            log(f"  로그인 대기 중... ({(i + 1) * 5}초)")

    log("로그인 대기 시간 초과 (15분).")
    return False


async def wait_for_nexacro_ready(page, max_wait=30):
    """Nexacro 프레임워크가 완전히 로딩될 때까지 대기"""
    NPS_READY_ELEMENT = (
        "mainframe.VFrameSet.FrameSdi.form.divHeader.form.divHeader.form.btnChangeBusi"
    )
    for i in range(max_wait):
        if await wait_for_element(page, NPS_READY_ELEMENT, timeout=1):
            log(f"  Nexacro 프레임워크 준비 완료 ({i+1}초)")
            return True
    log("  ERROR: Nexacro 프레임워크 로딩 시간 초과")
    return False


async def ensure_login_page(page):
    """NPS EDI 메인 페이지로 이동하여 로그인 대기"""
    await page.goto(NPS_URL, wait_until="domcontentloaded", timeout=30000)
    await human_delay(3)
    return await wait_for_login(page)


# ─── 네비게이션 ──────────────────────────────────────────────────────────────

async def navigate_to_decision_details(page):
    """결정내역 > 국민연금보험료 결정내역 메뉴로 이동"""
    TOP_MENU_ID = (
        "mainframe.VFrameSet.FrameSdi.form.divTop.form.divTopMenu"
        ".form.btnTop_M08000000"
    )
    SUB_MENU_ID = (
        "mainframe.VFrameSet.FrameSdi.form.divTop.form.divTopMenu"
        ".form.divSub_M08000000.form.btn2D_M08010000"
    )

    log("결정내역 메뉴 클릭...")
    result = await nexacro_click_button(page, TOP_MENU_ID)
    if not result.get("ok"):
        log(f"  ERROR: 결정내역 메뉴 클릭 실패 - {result}")
        return False
    await human_delay(2)

    log("국민연금보험료 결정내역 서브메뉴 클릭...")
    result = await nexacro_click_button(page, SUB_MENU_ID)
    if not result.get("ok"):
        log(f"  ERROR: 서브메뉴 클릭 실패 - {result}")
        return False
    await human_delay(3)
    return True


async def open_decision_detail(page, year=None, month=None):
    """결정내역 그리드에서 사용자 지정 월의 행을 찾아 더블클릭

    내용 컬럼(col=3)에서 해당 월의 2차를 우선 찾고,
    2차가 없으면 해당 월의 첫 번째 아이템을 선택.
    해당 월 자체가 없으면 첫 행으로 폴백.
    """
    now = datetime.now()
    _y = year if year is not None else now.year
    _m = month if month is not None else now.month
    month_prefix = f"{_y}.{_m:02d}"

    log(f"  결정내역 검색: 월={month_prefix}...")

    # 조회 버튼 클릭
    SEARCH_BTN = (
        "mainframe.VFrameSet.FrameSdi.form.divWork_M08010000"
        ".form.divWork.form.div00.form.btn00"
    )
    await nexacro_click_button(page, SEARCH_BTN)
    await human_delay(3)

    # 1순위: 해당 월의 2차 찾기 (col=3)
    row = await _find_row_with_round(page, GRID_DECISION_LIST,
                                     month_prefix, "2차")

    # 2순위: 해당 월의 첫 번째 아이템
    if row is None:
        row = await nexacro_find_row(page, GRID_DECISION_LIST,
                                     col=3, text=month_prefix)

    if row is None:
        log(f"  WARN: {month_prefix} 해당 결정내역 없음 — 첫 행으로 진행")
        row = 0
    else:
        log(f"  {month_prefix} 결정내역 발견 (row {row})")

    log(f"  결정내역 row {row} 더블클릭...")
    result = await nexacro_dblclick_cell(page, GRID_DECISION_LIST, row=row, col=1)
    await human_delay(3)
    return result



async def _find_row_with_round(page, grid_id, month_prefix, round_text):
    """내용 컬럼(col=3)에서 월+차수 동시 매칭 행 검색"""
    return await page.evaluate(r"""(args) => {
        const prefix = args.gridId + '.body.gridrow_';
        const allCells = document.querySelectorAll('[id^="' + prefix + '"]');
        for (const cell of allCells) {
            const id = cell.id;
            if (!id.includes('.cell_')) continue;
            const match = id.match(/gridrow_(\d+)\.cell_\d+_(\d+)/);
            if (!match) continue;
            if (parseInt(match[2]) !== 3) continue;
            const text = cell.textContent.trim();
            if (text.includes(args.month) && text.includes(args.round)) {
                return parseInt(match[1]);
            }
        }
        return null;
    }""", {"gridId": grid_id, "month": month_prefix, "round": round_text})


# ─── 사업장 선택/전환 ────────────────────────────────────────────────────────

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
