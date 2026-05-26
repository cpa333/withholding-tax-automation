"""국민연금 EDI 자동화 공통 함수 모듈

Nexacro 기반 edi.nps.or.kr 사이트 제어를 위한 유틸리티.
모든 NPS 자동화 플로우에서 공유.
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from src.utils.chrome_cdp import launch_chrome, CDP_URL

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
GRID_DECISION_DETAIL = (
    "mainframe.VFrameSet.FrameSdi.form.divWork_M08010200"
    ".form.divWork.form.tab00.Tabpage1.form"
)


def log(msg):
    print(msg, flush=True)


async def connect_page(playwright):
    """CDP로 Chrome에 연결하고 NPS EDI 탭 우선 반환"""
    browser = await playwright.chromium.connect_over_cdp(CDP_URL)
    context = browser.contexts[0]

    for pg in context.pages:
        try:
            if "edi.nps.or.kr" in pg.url:
                return browser, context, pg
        except Exception:
            continue

    page = context.pages[0] if context.pages else await context.new_page()
    return browser, context, page


async def wait_for_login(page):
    """NPS EDI 로그인 완료 대기 (수동 로그인)

    공동인증서 로그인은 사용자가 직접 수행.
    Nexacro 메인 페이지로 리디렉트되면 로그인 완료로 판단.
    최대 15분 대기.
    """
    # 이미 Nexacro 페이지면 로그인된 상태
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


async def ensure_login_page(page):
    """NPS EDI 메인 페이지로 이동하여 로그인 대기"""
    await page.goto(NPS_URL, wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(3)
    return await wait_for_login(page)


# ═══════════════════════════════════════════════════════════════════════════════
# Nexacro 그리드 제어
# ═══════════════════════════════════════════════════════════════════════════════

async def nexacro_dblclick_cell(page, grid_id, row, col):
    """Nexacro 그리드 셀에 더블클릭 이벤트 발생

    Nexacro 프레임워크는 일반 DOM click을 무시하므로,
    mousedown/mouseup/click/dblclick 이벤트를 순차적으로 dispatch 해야 함.

    Args:
        page: Playwright page
        grid_id: Nexacro 그리드 ID prefix
        row: 행 인덱스 (0-based)
        col: 열 인덱스 (0-based)
    """
    cell_id = f"{grid_id}.body.gridrow_{row}.cell_{row}_{col}"
    text_id = f"{cell_id}:text"

    return await page.evaluate("""(ids) => {
        const target = document.getElementById(ids.textId) || document.getElementById(ids.cellId);
        if (!target) return {error: 'cell not found'};

        const rect = target.getBoundingClientRect();
        const cx = rect.x + rect.width / 2;
        const cy = rect.y + rect.height / 2;

        const base = {
            bubbles: true, cancelable: true, view: window,
            screenX: cx, screenY: cy, clientX: cx, clientY: cy,
            button: 0, buttons: 1, relatedTarget: null
        };

        target.dispatchEvent(new MouseEvent('mousedown', {...base, detail: 1}));
        target.dispatchEvent(new MouseEvent('mouseup', {...base, detail: 1}));
        target.dispatchEvent(new MouseEvent('click', {...base, detail: 1}));
        target.dispatchEvent(new MouseEvent('mousedown', {...base, detail: 2}));
        target.dispatchEvent(new MouseEvent('mouseup', {...base, detail: 2}));
        target.dispatchEvent(new MouseEvent('click', {...base, detail: 2}));
        target.dispatchEvent(new MouseEvent('dblclick', {...base, detail: 2}));

        return {ok: true, text: target.textContent.trim()};
    }""", {"cellId": cell_id, "textId": text_id})


async def nexacro_find_row(page, grid_id, col, text):
    """Nexacro 그리드에서 특정 텍스트가 포함된 행 인덱스 검색

    Args:
        page: Playwright page
        grid_id: Nexacro 그리드 ID prefix
        col: 검색할 열 인덱스
        text: 검색할 텍스트 (부분 매칭)

    Returns:
        int or None: 매칭된 행 인덱스, 없으면 None
    """
    return await page.evaluate("""(args) => {
        const prefix = args.gridId + '.body.gridrow_';
        const allCells = document.querySelectorAll('[id^=\"' + prefix + '\"]');
        for (const cell of allCells) {
            const id = cell.id;
            if (!id.includes('.cell_')) continue;
            const match = id.match(/gridrow_(\\d+)\\.cell_\\d+_(\\d+)/);
            if (!match) continue;
            const rowIdx = parseInt(match[1]);
            const colIdx = parseInt(match[2]);
            if (colIdx !== args.col) continue;
            if (cell.textContent.trim().includes(args.text)) {
                return rowIdx;
            }
        }
        return null;
    }""", {"gridId": grid_id, "col": col, "text": text})


async def nexacro_get_grid_data(page, grid_id):
    """Nexacro 그리드의 모든 가시 행 데이터 반환

    Returns:
        list[list[str]]: 2차원 배열 (행 × 열)
    """
    return await page.evaluate("""(gridId) => {
        const prefix = gridId + '.body.gridrow_';
        const rows = {};
        const cells = document.querySelectorAll('[id^=\"' + prefix + '\"]');
        for (const cell of cells) {
            const id = cell.id;
            const match = id.match(/gridrow_(\\d+)\\.cell_\\d+_(\\d+)$/);
            if (!match) continue;
            const row = parseInt(match[1]);
            const col = parseInt(match[2]);
            if (!rows[row]) rows[row] = {};
            rows[row][col] = cell.textContent.trim();
        }
        return Object.keys(rows).sort((a,b) => a-b).map(r => {
            const row = rows[r];
            const maxCol = Math.max(...Object.keys(row).map(Number));
            const arr = [];
            for (let c = 0; c <= maxCol; c++) arr.push(row[c] || '');
            return arr;
        });
    }""", grid_id)


# ═══════════════════════════════════════════════════════════════════════════════
# Nexacro 메뉴 네비게이션
# ═══════════════════════════════════════════════════════════════════════════════

async def nexacro_click_button(page, element_id):
    """Nexacro 버튼에 mousedown/mouseup/click 이벤트 발생

    Nexacro 프레임워크의 버튼은 일반 DOM click을 무시하므로,
    이벤트를 직접 dispatch 해야 함.

    Args:
        page: Playwright page
        element_id: Nexacro 버튼 element ID
    """
    return await page.evaluate("""(elId) => {
        const btn = document.getElementById(elId);
        if (!btn) return {error: 'element not found: ' + elId};

        const rect = btn.getBoundingClientRect();
        const cx = rect.x + rect.width / 2;
        const cy = rect.y + rect.height / 2;

        const base = {
            bubbles: true, cancelable: true, view: window,
            screenX: cx, screenY: cy, clientX: cx, clientY: cy,
            button: 0, buttons: 1, relatedTarget: null
        };

        btn.dispatchEvent(new MouseEvent('mousedown', {...base, detail: 1}));
        btn.dispatchEvent(new MouseEvent('mouseup', {...base, detail: 1}));
        btn.dispatchEvent(new MouseEvent('click', {...base, detail: 1}));

        return {ok: true, text: btn.textContent.trim().substring(0, 40)};
    }""", element_id)


async def navigate_to_decision_details(page):
    """결정내역 > 국민연금보험료 결정내역 메뉴로 이동

    상단 네비바에서 '결정내역'(M08000000) 클릭 후
    '국민연금보험료 결정내역'(M08010000) 서브메뉴 클릭.
    """
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
        log(f"  ERROR: {result}")
        return False
    await asyncio.sleep(2)

    log("국민연금보험료 결정내역 서브메뉴 클릭...")
    result = await nexacro_click_button(page, SUB_MENU_ID)
    if not result.get("ok"):
        log(f"  ERROR: {result}")
        return False
    await asyncio.sleep(3)

    log("국민연금보험료 결정내역 페이지 이동 완료.")
    return True


async def open_decision_detail(page, round_filter="2차"):
    """결정내역 목록에서 이번 달 + 지정 차수 행을 더블클릭하여 상세 진입

    결정내역 그리드(GRID_DECISION_LIST)에서:
    - 처리결과 통지일(col=1)이 이번 달인 행
    - 업무명(col=3)에 round_filter(기본 '2차')가 포함된 행
    을 찾아 더블클릭.

    Args:
        page: Playwright page
        round_filter: 차수 필터 (기본 '2차')

    Returns:
        bool: 상세 페이지 진입 성공 여부
    """
    from datetime import datetime
    now = datetime.now()
    month_prefix = f"{now.year}.{now.month:02d}"

    log(f"결정내역에서 이번 달({month_prefix}) {round_filter} 행 검색...")

    # 텍스트 매칭으로 행 찾기: 업무명(col=3)에 연도.월 + 차수 포함
    row_idx = await page.evaluate("""(args) => {
        const prefix = args.gridId + '.body.gridrow_';
        const allCells = document.querySelectorAll('[id^="' + prefix + '"]');
        for (const cell of allCells) {
            const match = cell.id.match(/gridrow_(\\d+)\\.cell_\\d+_(\\d+)$/);
            if (!match) continue;
            const rowIdx = parseInt(match[1]);
            const colIdx = parseInt(match[2]);
            if (colIdx !== args.col) continue;
            const text = cell.textContent.trim();
            if (text.includes(args.monthPrefix) && text.includes(args.roundFilter)) {
                return rowIdx;
            }
        }
        return null;
    }""", {
        "gridId": GRID_DECISION_LIST,
        "col": 3,
        "monthPrefix": month_prefix,
        "roundFilter": round_filter,
    })

    if row_idx is None:
        log(f"  {month_prefix} {round_filter} 행을 찾지 못했습니다.")
        return False

    log(f"  {round_filter} 행 발견 (row={row_idx}). 더블클릭 진입 중...")
    result = await nexacro_dblclick_cell(page, GRID_DECISION_LIST, row=row_idx, col=3)

    if not result.get("ok"):
        log(f"  더블클릭 실패: {result}")
        return False

    await asyncio.sleep(3)
    log("결정내역 상세 페이지 진입 완료.")
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# 사업장 선택
# ═══════════════════════════════════════════════════════════════════════════════

async def open_workplace_selector(page):
    """사업장 선택 모달(업무대행서비스) 열기

    좌측 메뉴에서 '업무대행서비스' → '위탁사업장' 클릭.
    """
    # 메뉴 트리에서 '업무대행서비스' 찾아서 클릭
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
    await asyncio.sleep(2)

    # '위탁사업장' 하위 메뉴 클릭
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
    await asyncio.sleep(2)


async def select_workplace(page, workplace_name):
    """사업장 선택 모달에서 특정 사업장을 더블클릭으로 선택

    Args:
        page: Playwright page
        workplace_name: 선택할 사업장명 (부분 매칭)

    Returns:
        bool: 선택 성공 여부
    """
    log(f"  사업장 검색: '{workplace_name}'")

    # 사업장명 컬럼(col=2)에서 텍스트 매칭하여 행 인덱스 찾기
    row = await nexacro_find_row(page, GRID_WORKPLACE, col=2, text=workplace_name)

    if row is None:
        log(f"  '{workplace_name}' 사업장을 찾지 못했습니다.")
        return False

    log(f"  '{workplace_name}' 발견 (row={row}). 더블클릭 선택 중...")
    result = await nexacro_dblclick_cell(page, GRID_WORKPLACE, row=row, col=2)

    if result.get("ok"):
        log(f"  사업장 선택 완료: {result.get('text', '')}")
        await asyncio.sleep(3)
        return True

    log(f"  사업장 선택 실패: {result}")
    return False


async def select_workplace_by_index(page, index):
    """사업장 선택 모달에서 N번째(0-based) 사업장 선택

    Args:
        page: Playwright page
        index: 행 인덱스 (0-based)

    Returns:
        bool: 선택 성공 여부
    """
    log(f"  사업장 {index + 1}번째 행 선택 중...")
    result = await nexacro_dblclick_cell(page, GRID_WORKPLACE, row=index, col=2)

    if result.get("ok"):
        log(f"  사업장 선택 완료: {result.get('text', '')}")
        await asyncio.sleep(3)
        return True

    log(f"  사업장 선택 실패: {result}")
    return False


async def list_workplaces(page):
    """현재 사업장 목록의 가시 행 데이터 반환

    Returns:
        list[dict]: [{index, number, name}, ...]
    """
    data = await nexacro_get_grid_data(page, GRID_WORKPLACE)
    workplaces = []
    for i, row in enumerate(data):
        workplaces.append({
            "index": i,
            "number": row[1] if len(row) > 1 else "",
            "name": row[2] if len(row) > 2 else "",
        })
    return workplaces
