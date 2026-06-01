"""국민연금 EDI 자동화 공통 함수 모듈

Nexacro 기반 edi.nps.or.kr 사이트 제어를 위한 유틸리티.
모든 NPS 자동화 플로우에서 공유.
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from src.utils.chrome_cdp import launch_chrome, CDP_URL
from src.utils.log import log
from src.utils.human import human_delay

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

# 결정내역 상세 탭 인덱스
TAB_FINAL = 0      # 최종결정내역
TAB_RECEIPT = 1    # 수납내역
TAB_MEMBER = 2     # 가입자내역
TAB_RETRO = 3      # 소급분내역
TAB_GOVT = 4       # 국고지원내역

# 결정내역 상세 탭 버튼 ID prefix
TAB_BTN_PREFIX = (
    "mainframe.VFrameSet.FrameSdi.form.divWork_M08010200"
    ".form.divWork.form.tab00.tabbutton_"
)

# 출력 버튼 / 엑셀저장 버튼 / 통합저장 버튼
# 모달 ID: 출력=UHJE0002P1, 통합저장=UHJE0002P2, 엑셀저장=UHJE0002P3
BTN_OUTPUT = (
    "mainframe.VFrameSet.FrameSdi.form.divWork_M08010200"
    ".form.divWork.form.div00.form.btn02"
)
BTN_EXCEL_SAVE = (
    "mainframe.VFrameSet.FrameSdi.form.divWork_M08010200"
    ".form.divWork.form.div01.form.btn01"
)
BTN_INTEGRATED_SAVE = (
    "mainframe.VFrameSet.FrameSdi.form.divWork_M08010200"
    ".form.divWork.form.div01.form.btn02"
)
MODAL_PREFIX = "mainframe.VFrameSet.FrameSdi.UHJE0002P1.form.divPopBg.form.divPopWork.form"
RADIO_FULL_SSN = f"{MODAL_PREFIX}.div00_01.form.div01.form.rdo06.radioitem1"
BTN_MODAL_CONFIRM = f"{MODAL_PREFIX}.div00_00.form.btn01"
BTN_MODAL_CANCEL = f"{MODAL_PREFIX}.div00_00.form.btn00"
EXCEL_MODAL_PREFIX = "mainframe.VFrameSet.FrameSdi.UHJE0002P3.form.divPopBg.form.divPopWork.form"
EXCEL_RADIO_FULL_SSN = f"{EXCEL_MODAL_PREFIX}.div00_01.form.div01.form.rdo06.radioitem1"
EXCEL_BTN_CONFIRM = f"{EXCEL_MODAL_PREFIX}.div00_00.form.btn01"
INTEGRATED_MODAL_PREFIX = "mainframe.VFrameSet.FrameSdi.UHJE0002P2.form.divPopBg.form.divPopWork.form"
INTEGRATED_RADIO_FULL_SSN = f"{INTEGRATED_MODAL_PREFIX}.div00_01.form.div01.form.rdo06.radioitem1"
INTEGRATED_BTN_CONFIRM = f"{INTEGRATED_MODAL_PREFIX}.div00_00.form.btn01"

# 사업장전환 버튼 (페이지 상단 헤더)
BTN_CHANGE_WORKPLACE = (
    "mainframe.VFrameSet.FrameSdi.form.divHeader.form.divHeader.form.btnChangeBusi"
)
# 사업장전환 모달 그리드 — 기존 GRID_WORKPLACE와 동일 (ChangeBusi.grdList)


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


async def wait_for_nexacro_ready(page, max_wait=30):
    """Nexacro 프레임워크가 완전히 로딩될 때까지 대기

    로그인 후 Nexacro 애플리케이션이 초기화되어
    mainframe.VFrameSet.FrameSdi 등의 컴포넌트에 접근 가능해질 때까지 폴링.
    """
    for i in range(max_wait):
        await asyncio.sleep(1)
        try:
            ready = await page.evaluate("""() => {
                try {
                    var btn = document.getElementById(
                        'mainframe.VFrameSet.FrameSdi.form.divHeader.form.divHeader.form.btnChangeBusi'
                    );
                    return !!btn;
                } catch(e) {
                    return false;
                }
            }""")
            if ready:
                log(f"  Nexacro 프레임워크 준비 완료 ({i+1}초)")
                return True
        except Exception:
            pass
    log("  ERROR: Nexacro 프레임워크 로딩 시간 초과")
    return False


async def ensure_login_page(page):
    """NPS EDI 메인 페이지로 이동하여 로그인 대기"""
    await page.goto(NPS_URL, wait_until="domcontentloaded", timeout=30000)
    await human_delay(3)
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
        const cx = rect.x + rect.width / 2 + (Math.random() * 4 - 2);
        const cy = rect.y + rect.height / 2 + (Math.random() * 4 - 2);

        const base = {
            bubbles: true, cancelable: true, view: window,
            screenX: cx, screenY: cy, clientX: cx, clientY: cy,
            button: 0, buttons: 1, relatedTarget: null
        };

        target.dispatchEvent(new MouseEvent('mousemove', {...base, detail: 0, buttons: 0}));
        let t = performance.now();
        while (performance.now() - t < 30 + Math.random() * 50) {}

        target.dispatchEvent(new MouseEvent('mousedown', {...base, detail: 1}));
        target.dispatchEvent(new MouseEvent('mouseup', {...base, detail: 1}));
        target.dispatchEvent(new MouseEvent('click', {...base, detail: 1}));

        t = performance.now();
        while (performance.now() - t < 30 + Math.random() * 50) {}

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
        const cx = rect.x + rect.width / 2 + (Math.random() * 4 - 2);
        const cy = rect.y + rect.height / 2 + (Math.random() * 4 - 2);

        const base = {
            bubbles: true, cancelable: true, view: window,
            screenX: cx, screenY: cy, clientX: cx, clientY: cy,
            button: 0, buttons: 1, relatedTarget: null
        };

        btn.dispatchEvent(new MouseEvent('mousemove', {...base, detail: 0, buttons: 0}));
        const t = performance.now();
        while (performance.now() - t < 30 + Math.random() * 50) {}

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
    await human_delay(2)

    log("국민연금보험료 결정내역 서브메뉴 클릭...")
    result = await nexacro_click_button(page, SUB_MENU_ID)
    if not result.get("ok"):
        log(f"  ERROR: {result}")
        return False
    await human_delay(3)

    log("국민연금보험료 결정내역 페이지 이동 완료.")
    return True


async def open_decision_detail(page, round_filter="2차",
                                year: int | None = None,
                                month: int | None = None):
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
    _y = year if year is not None else now.year
    _m = month if month is not None else now.month
    month_prefix = f"{_y}.{_m:02d}"

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

    await human_delay(3)
    log("결정내역 상세 페이지 진입 완료.")
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# 결정내역 상세 탭 / 출력 / PDF
# ═══════════════════════════════════════════════════════════════════════════════

async def click_detail_tab(page, tab_index):
    """결정내역 상세 페이지의 탭 전환

    Args:
        page: Playwright page
        tab_index: 탭 인덱스 (TAB_FINAL=0, TAB_RECEIPT=1, TAB_MEMBER=2, TAB_RETRO=3, TAB_GOVT=4)
    """
    tab_id = f"{TAB_BTN_PREFIX}{tab_index}"
    result = await nexacro_click_button(page, tab_id)
    if result.get("ok"):
        log(f"  탭 {tab_index} 전환 완료")
    else:
        log(f"  탭 전환 실패: {result}")
    await human_delay(1)
    return result.get("ok", False)


async def output_with_full_ssn(page):
    """출력 버튼 클릭 → 주민번호 전체표출 → 확인

    출력 옵션 모달에서 주민번호를 전체표출로 선택 후 확인.
    Crownix rdPreview 새 탭이 열림.
    """
    log("출력 버튼 클릭...")
    result = await nexacro_click_button(page, BTN_OUTPUT)
    if not result.get("ok"):
        log(f"  ERROR: 출력 버튼 클릭 실패 - {result}")
        return False
    await human_delay(2)

    log("주민번호 전체표출 선택...")
    await nexacro_click_button(page, RADIO_FULL_SSN)
    await human_delay(1)

    log("확인 클릭...")
    result = await nexacro_click_button(page, BTN_MODAL_CONFIRM)
    if not result.get("ok"):
        log(f"  ERROR: 확인 클릭 실패 - {result}")
        return False
    await human_delay(2)

    log("출력 옵션 적용 완료.")
    return True


async def download_pdf_from_preview(context, save_dir, filename):
    """rdPreview 탭에서 PDF 다운로드 후 탭 닫기

    Crownix 뷰어(rdPreview.do) 새 탭에서 PDF 버튼 클릭으로 다운로드.

    Args:
        context: Playwright browser context
        save_dir: 저장할 디렉토리 경로
        filename: 저장할 파일명 (확장자 제외)

    Returns:
        str or None: 저장된 파일 경로, 실패 시 None
    """
    # rdPreview 탭 찾기
    rd_page = None
    for pg in context.pages:
        try:
            if "rdPreview" in pg.url:
                rd_page = pg
                break
        except Exception:
            continue

    if not rd_page:
        log("  ERROR: rdPreview 탭을 찾지 못했습니다.")
        return None

    # 다운로드 경로 설정
    os.makedirs(save_dir, exist_ok=True)
    cdp = await context.new_cdp_session(rd_page)
    await cdp.send("Browser.setDownloadBehavior", {
        "behavior": "allowAndName",
        "downloadPath": save_dir,
        "eventsEnabled": True,
    })

    # PDF 버튼 클릭
    before = set(os.listdir(save_dir))
    await rd_page.evaluate("""() => {
        const btns = document.querySelectorAll('button.crownix-toolbar-button');
        for (const btn of btns) {
            if ((btn.textContent || '').trim() === 'PDF') {
                btn.click();
                return true;
            }
        }
        return false;
    }""")

    # 다운로드 완료 대기
    for _ in range(30):
        await asyncio.sleep(1)
        after = set(os.listdir(save_dir))
        new_files = after - before
        crdownload = [f for f in new_files if f.endswith(".crdownload")]
        done = [f for f in new_files if not f.endswith(".crdownload")]
        if not crdownload and done:
            downloaded = os.path.join(save_dir, done[0])
            final_path = os.path.join(save_dir, f"{filename}.pdf")
            if os.path.exists(final_path):
                os.remove(final_path)
            if downloaded != final_path:
                os.rename(downloaded, final_path)
            # rdPreview 탭 닫기
            await rd_page.close()
            log(f"  PDF 저장 완료: {final_path}")
            return final_path

    log("  ERROR: PDF 다운로드 시간 초과")
    return None


async def save_excel(page, context, save_dir, filename):
    """엑셀저장 버튼 클릭 → 주민번호 전체표출 → 확인 → Excel 다운로드

    결정내역 상세 페이지의 '엑셀저장' 버튼(btn01 in div01) 클릭 후
    UHJE0002P3 모달에서 전체표출 선택 → 확인.

    Args:
        page: Playwright page (NPS EDI main page)
        context: Playwright browser context
        save_dir: 저장할 디렉토리 경로
        filename: 저장할 파일명 (확장자 제외)

    Returns:
        str or None: 저장된 파일 경로, 실패 시 None
    """
    log("엑셀저장 버튼 클릭...")

    os.makedirs(save_dir, exist_ok=True)
    cdp = await context.new_cdp_session(page)
    await cdp.send("Browser.setDownloadBehavior", {
        "behavior": "allowAndName",
        "downloadPath": save_dir,
        "eventsEnabled": True,
    })

    before = set(os.listdir(save_dir))

    result = await nexacro_click_button(page, BTN_EXCEL_SAVE)
    if not result.get("ok"):
        log(f"  ERROR: 엑셀저장 버튼 클릭 실패 - {result}")
        return None
    await human_delay(2)

    log("주민번호 전체표출 선택 (엑셀 모달)...")
    await nexacro_click_button(page, EXCEL_RADIO_FULL_SSN)
    await human_delay(1)

    log("확인 클릭...")
    result = await nexacro_click_button(page, EXCEL_BTN_CONFIRM)
    if not result.get("ok"):
        log(f"  ERROR: 확인 클릭 실패 - {result}")
        return None

    # 다운로드 완료 대기
    for _ in range(30):
        await asyncio.sleep(1)
        after = set(os.listdir(save_dir))
        new_files = after - before
        crdownload = [f for f in new_files if f.endswith(".crdownload")]
        done = [f for f in new_files if not f.endswith(".crdownload") and not f.endswith(".pdf")]
        if not crdownload and done:
            downloaded = os.path.join(save_dir, done[0])
            ext = os.path.splitext(done[0])[1] or ".xlsx"
            final_path = os.path.join(save_dir, f"{filename}{ext}")
            if downloaded != final_path:
                if os.path.exists(final_path):
                    os.remove(final_path)
                os.rename(downloaded, final_path)
            log(f"  Excel 저장 완료: {final_path}")
            return final_path

    log("  ERROR: Excel 다운로드 시간 초과")
    return None


async def save_integrated(page, context, save_dir, filename):
    """통합저장 버튼 클릭 → 주민번호 전체표출 → 확인 → 파일 다운로드

    통합저장은 엑셀저장과 동일한 플로우지만 UHJE0002P2 모달 사용.
    국고지원내역 탭에서 사용.

    Args:
        page: Playwright page (NPS EDI main page)
        context: Playwright browser context
        save_dir: 저장할 디렉토리 경로
        filename: 저장할 파일명 (확장자 제외)

    Returns:
        str or None: 저장된 파일 경로, 실패 시 None
    """
    log("통합저장 버튼 클릭...")

    os.makedirs(save_dir, exist_ok=True)
    cdp = await context.new_cdp_session(page)
    await cdp.send("Browser.setDownloadBehavior", {
        "behavior": "allowAndName",
        "downloadPath": save_dir,
        "eventsEnabled": True,
    })

    before = set(os.listdir(save_dir))

    result = await nexacro_click_button(page, BTN_INTEGRATED_SAVE)
    if not result.get("ok"):
        log(f"  ERROR: 통합저장 버튼 클릭 실패 - {result}")
        return None
    await human_delay(2)

    log("주민번호 전체표출 선택 (통합 모달)...")
    await nexacro_click_button(page, INTEGRATED_RADIO_FULL_SSN)
    await human_delay(1)

    log("확인 클릭...")
    result = await nexacro_click_button(page, INTEGRATED_BTN_CONFIRM)
    if not result.get("ok"):
        log(f"  ERROR: 확인 클릭 실패 - {result}")
        return None

    for _ in range(30):
        await asyncio.sleep(1)
        after = set(os.listdir(save_dir))
        new_files = after - before
        crdownload = [f for f in new_files if f.endswith(".crdownload")]
        done = [f for f in new_files if not f.endswith(".crdownload") and not f.endswith(".pdf")]
        if not crdownload and done:
            downloaded = os.path.join(save_dir, done[0])
            ext = os.path.splitext(done[0])[1] or ".xlsx"
            final_path = os.path.join(save_dir, f"{filename}{ext}")
            if downloaded != final_path:
                if os.path.exists(final_path):
                    os.remove(final_path)
                os.rename(downloaded, final_path)
            log(f"  통합저장 완료: {final_path}")
            return final_path

    log("  ERROR: 통합저장 다운로드 시간 초과")
    return None


async def process_tab_download(page, context, save_dir, tab_index, tab_label, grid_suffix,
                                year: int | None = None,
                                month: int | None = None):
    """결정내역 상세 탭에서 PDF + Excel 순차 다운로드

    그리드가 비어있으면 스킵.

    Args:
        page: Playwright page
        context: Playwright browser context
        save_dir: 저장 디렉토리
        tab_index: 탭 인덱스 (TAB_MEMBER=2, TAB_RETRO=3, TAB_GOVT=4)
        tab_label: 파일명 구분용 라벨 (예: '가입자내역', '소급분내역')
        grid_suffix: 그리드 ID 접미사 (예: 'grdList2', 'grdList3')

    Returns:
        dict: {pdf: path|None, excel: path|None, skipped: bool}
    """
    from datetime import datetime
    now = datetime.now()
    _y = year if year is not None else now.year
    _m = month if month is not None else now.month
    base = f"국민연금보험료_결정내역_{_y}{_m:02d}_{tab_label}"

    # 탭 전환
    log(f"{tab_label} 탭 이동...")
    ok = await click_detail_tab(page, tab_index)
    if not ok:
        log(f"  {tab_label} 탭 전환 실패, 스킵")
        return {"pdf": None, "excel": None, "skipped": True}

    # 그리드 데이터 확인
    grid_id = f"{GRID_DECISION_DETAIL}.{grid_suffix}"
    data = await nexacro_get_grid_data(page, grid_id)
    if not data:
        log(f"  {tab_label} 데이터 없음, 다운로드 스킵")
        return {"pdf": None, "excel": None, "skipped": True}

    log(f"  {tab_label} 데이터 {len(data)}행 감지, 다운로드 시작")

    # PDF
    pdf_path = None
    if await output_with_full_ssn(page):
        pdf_path = await download_pdf_from_preview(context, save_dir, base)

    # 통합저장/엑셀저장 (국고지원내역은 통합저장 사용)
    if tab_index == TAB_GOVT:
        excel_path = await save_integrated(page, context, save_dir, f"{base}_엑셀")
    else:
        excel_path = await save_excel(page, context, save_dir, f"{base}_엑셀")

    return {"pdf": pdf_path, "excel": excel_path, "skipped": False}


# ═══════════════════════════════════════════════════════════════════════════════
# 사업장 선택 / 전환
# ═══════════════════════════════════════════════════════════════════════════════

async def switch_workplace(page, workplace_name, management_number=""):
    """사업장전환 버튼으로 사업장 전환

    페이지 상단 '사업장전환' 버튼 클릭 → 모달에서 사업장 더블클릭 선택.

    Args:
        page: Playwright page
        workplace_name: 선택할 사업장명 (부분 매칭)
        management_number: 사업장관리번호 (숫자만, 우선 사용)

    Returns:
        bool: 전환 성공 여부
    """
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
    """사업장전환 모달의 검색 입력란에 텍스트 입력 후 검색 실행

    Args:
        page: Playwright page
        search_text: 검색할 텍스트
        search_by_mgmt_no: True면 사업장관리번호(item_1), False면 사업장명(item_0)
    """
    MODAL_SEARCH = (
        "mainframe.VFrameSet.FrameSdi.ChangeBusi"
        ".form.divPopBg.form.divPopWork.form.div01.form"
    )
    # 검색 필드 콤보 드롭다운 열기 → 항목 선택
    await nexacro_click_button(page, f"{MODAL_SEARCH}.cbo00.dropbutton")
    await human_delay(0.5)
    item = "item_1" if search_by_mgmt_no else "item_0"
    await nexacro_click_button(page, f"{MODAL_SEARCH}.cbo00.combolist.{item}")
    await human_delay(0.5)

    # 검색 입력란(edt08)에 텍스트 입력
    await page.evaluate("""(args) => {
        const input = document.getElementById(args.inputId + ":input");
        if (input) {
            input.value = args.text;
            input.dispatchEvent(new Event("input", {bubbles: true}));
            input.dispatchEvent(new Event("change", {bubbles: true}));
            return true;
        }
        return false;
    }""", {"inputId": f"{MODAL_SEARCH}.edt08", "text": search_text})
    await human_delay(0.5)

    # 검색 버튼(btn00) 클릭
    await nexacro_click_button(page, f"{MODAL_SEARCH}.btn00")


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
    await human_delay(2)

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
    await human_delay(2)


async def select_workplace(page, workplace_name, management_number=""):
    """사업장 선택 모달에서 특정 사업장을 더블클릭으로 선택

    management_number가 제공되면 사업장관리번호(col=1)로 검색.
    그렇지 않으면 사업장명(col=2)으로 검색.

    Args:
        page: Playwright page
        workplace_name: 선택할 사업장명 (부분 매칭)
        management_number: 사업장관리번호 (숫자만, 우선 사용)

    Returns:
        bool: 선택 성공 여부
    """
    if management_number:
        log(f"  사업장 검색: 관리번호 '{management_number}'")
        # 그리드는 하이픈 포함 형식이므로 모달 검색으로 바로 진행
        await _search_workplace_in_modal(page, management_number, search_by_mgmt_no=True)
        await human_delay(2)
        # 검색 후 첫 번째 행 선택 (관리번호 검색은 결과가 1건)
        result = await nexacro_dblclick_cell(page, GRID_WORKPLACE, row=0, col=2)
        if result.get("ok"):
            log(f"  사업장 선택 완료: {result.get('text', '')}")
            await human_delay(3)
            return True
        log(f"  사업장 선택 실패: {result}")
        return False

    log(f"  사업장 검색: '{workplace_name}'")

    # 사업장명 컬럼(col=2)에서 텍스트 매칭하여 행 인덱스 찾기
    row = await nexacro_find_row(page, GRID_WORKPLACE, col=2, text=workplace_name)

    # 그리드에 없으면 모달 검색으로 찾기 시도
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
        await human_delay(3)
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
