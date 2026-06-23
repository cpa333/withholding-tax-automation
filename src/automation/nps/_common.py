"""국민연금 EDI 자동화 공통 함수 모듈

Nexacro 기반 edi.nps.or.kr 사이트 제어를 위한 유틸리티.
모든 NPS 자동화 플로우에서 공유.

하위 모듈에서 분할 관리:
- _constants.py:  상수 (URL, 엘리먼트 ID, 타임아웃)
- _workplace.py:  사업장 선택/검색
- _download.py:   결정내역 출력/PDF/Excel 다운로드, 탭 제어

이 모듈은 모든 하위 모듈을 재export하여
기존 `from src.automation.nps._common import X` import를
변경 없이 유지.
"""

import asyncio
import sys
import os
import time
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

# ─── 상수 재export ───────────────────────────────────────────────────────────
from src.automation.nps._constants import (
    NPS_URL, NPS_NEXACRO_URL,
    GRID_WORKPLACE, GRID_DECISION_LIST, GRID_DECISION_DETAIL,
    BTN_CHANGE_WORKPLACE, BTN_OUTPUT,
    BTN_EXCEL_SAVE, BTN_INTEGRATED_SAVE,
    TAB_FINAL, TAB_RECEIPT, TAB_MEMBER, TAB_RETRO, TAB_GOVT,
    TAB_BTN_PREFIX,
    MODAL_PREFIX, RADIO_FULL_SSN,
    BTN_MODAL_CONFIRM, BTN_MODAL_CANCEL,
    EXCEL_MODAL_PREFIX, EXCEL_RADIO_FULL_SSN, EXCEL_BTN_CONFIRM,
    INTEGRATED_MODAL_PREFIX, INTEGRATED_RADIO_FULL_SSN, INTEGRATED_BTN_CONFIRM,
    LOGIN_TIMEOUT_S, NEXACRO_READY_TIMEOUT_S,
    PAGE_LOAD_TIMEOUT_MS, DOWNLOAD_TIMEOUT_S,
)

# ─── 사업장 선택 재export ────────────────────────────────────────────────────
from src.automation.nps._workplace import (
    switch_workplace,
    switch_workplace_open,
    open_workplace_selector,
    select_workplace,
    select_workplace_by_index,
    list_workplaces,
)

# ─── 다운로드 재export ────────────────────────────────────────────────────────
from src.automation.nps._download import (
    click_detail_tab,
    output_with_full_ssn,
    download_pdf_from_preview,
    save_excel,
    save_integrated,
    download_final_integrated,
    process_tab_download,
)

# Nexacro 헬퍼 로컬 별칭 (하위 호환)
nexacro_dblclick_cell = nexacro_dblclick_cell_viewport
nexacro_click_button = nexacro_click_button_viewport


# ─── 연결/로그인 ────────────────────────────────────────────────────────────

async def connect_page(playwright, *, url: str = CDP_URL):
    """CDP로 Chrome에 연결하고 NPS EDI 탭 우선 반환 (url 미지정 시 기본 포트)"""
    from src.utils.stealth import stealth_all_pages, register_auto_stealth

    browser = await playwright.chromium.connect_over_cdp(url)
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

    for i in range(LOGIN_TIMEOUT_S // 5):
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


async def wait_for_nexacro_ready(page, max_wait=NEXACRO_READY_TIMEOUT_S):
    """Nexacro 프레임워크가 완전히 로딩될 때까지 대기"""
    NPS_READY_ELEMENT = BTN_CHANGE_WORKPLACE
    for i in range(max_wait):
        if await wait_for_element(page, NPS_READY_ELEMENT, timeout=1):
            log(f"  Nexacro 프레임워크 준비 완료 ({i+1}초)")
            return True
    log("  ERROR: Nexacro 프레임워크 로딩 시간 초과")
    return False


async def ensure_login_page(page):
    """NPS EDI 메인 페이지로 이동하여 로그인 대기"""
    await page.goto(NPS_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT_MS)
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


async def _wait_decision_grid(page, timeout=6, interval=0.5):
    """GRID_DECISION_LIST 행(gridrow_N)이 출현할 때까지 폴링.

    사업장 전환 직후 결정내역 그리드가 늦게 로드되면 행 매칭이 빈 결과로
    스킵되는 레이스 컨디션을 방지한다.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            count = await page.evaluate(
                '(gid) => document.querySelectorAll(\'[id^="\' + gid + \'.body.gridrow_"]\').length',
                GRID_DECISION_LIST,
            )
            if count and count > 0:
                return True
        except Exception:
            pass
        await asyncio.sleep(interval)
    return False


async def open_decision_detail(page, year=None, month=None):
    """결정내역 그리드에서 사용자 지정 월의 행을 찾아 더블클릭

    내용 컬럼(col=3)에서 해당 월의 2차를 우선 찾고,
    2차가 없으면 해당 월의 첫 번째 아이템을 선택.
    해당 월이 없으면 None 반환 (호출부에서 스킵 처리).
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

    # 결정내역 그리드 로드 대기 + 행 매칭 (사업장 전환 직후 그리드 지연 대응).
    # 그리드 자체가 안 로드(0행)면 재시도, 로드됐으면 매칭 결과(있/없) 확정.
    row = None
    for attempt in range(3):
        if not await _wait_decision_grid(page, timeout=6):
            log(f"  결정내역 그리드 로드 대기 중... ({attempt + 1}/3)")
            if attempt < 2:
                await human_delay(2)
            continue
        # 1순위: 해당 월의 2차 찾기 (col=3)
        row = await _find_row_with_round(page, GRID_DECISION_LIST,
                                         month_prefix, "2차")
        # 2순위: 해당 월의 첫 번째 아이템
        if row is None:
            row = await nexacro_find_row(page, GRID_DECISION_LIST,
                                         col=3, text=month_prefix)
        break  # 그리드 로드됨 — 매칭 결과 확정

    if row is None:
        log(f"  {month_prefix} 해당 결정내역 없음 — 스킵")
        return None
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
