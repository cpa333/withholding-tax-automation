"""NPS EDI 결정내역 출력/다운로드 모듈

탭 전환, 출력 버튼, PDF/Excel 다운로드, Crownix 뷰어 제어.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from src.utils.log import log
from src.utils.human import human_delay
from src.utils.nexacro import (
    nexacro_click_button_viewport,
    nexacro_wait_and_click,
    nexacro_get_grid_data,
)

# ─── 상수 ────────────────────────────────────────────────────────────────────

# 결정내역 상세 탭 인덱스
TAB_FINAL = 0      # 최종결정내역
TAB_RECEIPT = 1    # 수납내역
TAB_MEMBER = 2     # 가입자내역
TAB_RETRO = 3      # 소급분내역
TAB_GOVT = 4       # 국고지원내역

TAB_BTN_PREFIX = (
    "mainframe.VFrameSet.FrameSdi.form.divWork_M08010200"
    ".form.divWork.form.tab00.tabbutton_"
)
GRID_DECISION_DETAIL = (
    "mainframe.VFrameSet.FrameSdi.form.divWork_M08010200"
    ".form.divWork.form.tab00.Tabpage1.form"
)

# 출력 버튼 / 엑셀저장 버튼 / 통합저장 버튼
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

# Local alias for backward compatibility
nexacro_click_button = nexacro_click_button_viewport


# ─── 함수 구현 ───────────────────────────────────────────────────────────────

async def click_detail_tab(page, tab_index):
    """결정내역 상세 페이지의 탭 전환"""
    tab_id = f"{TAB_BTN_PREFIX}{tab_index}"
    result = await nexacro_click_button(page, tab_id)
    if result.get("ok"):
        log(f"  탭 {tab_index} 전환 완료")
    else:
        log(f"  탭 전환 실패: {result}")
    await human_delay(1)
    return result.get("ok", False)


async def _wait_for_modal(page, modal_id, timeout=5):
    """모달 요소가 DOM에 나타날 때까지 폴링"""
    for _ in range(timeout):
        try:
            found = await page.evaluate(
                '(elId) => !!document.getElementById(elId)', modal_id
            )
            if found:
                return True
        except Exception:
            pass
        await asyncio.sleep(1)
    return False


async def _scroll_into_view(page, element_id):
    """요소를 뷰포트 중앙으로 스크롤"""
    try:
        await page.evaluate("""(elId) => {
            const el = document.getElementById(elId);
            if (el) el.scrollIntoView({block: 'center', behavior: 'instant'});
        }""", element_id)
        await asyncio.sleep(0.3)
    except Exception:
        pass


async def _click_output_button(page):
    """출력 버튼을 3가지 전략으로 순차 클릭"""
    # 전략 1
    log("  [전략 1] nexacro_click_button + scrollIntoView...")
    try:
        await _scroll_into_view(page, BTN_OUTPUT)
        result = await nexacro_click_button(page, BTN_OUTPUT)
        if result.get("ok") and await _wait_for_modal(page, BTN_MODAL_CONFIRM, timeout=5):
            log("  [전략 1] 성공 — 모달 출현 확인")
            return 1
        modal_exists = await page.evaluate('(elId) => !!document.getElementById(elId)', BTN_MODAL_CONFIRM)
        log(f"  [전략 1] 실패 — result={result}, modal={not modal_exists}")
    except Exception as e:
        log(f"  [전략 1] 예외 — {e}")

    # 전략 2
    log("  [전략 2] Playwright locator.click(force=True)...")
    try:
        btn = page.locator(f'[id="{BTN_OUTPUT}"]')
        await btn.click(force=True, timeout=5000)
        if await _wait_for_modal(page, BTN_MODAL_CONFIRM, timeout=5):
            log("  [전략 2] 성공 — 모달 출현 확인")
            return 2
        log("  [전략 2] 실패 — 모달 미출현")
    except Exception as e:
        log(f"  [전략 2] 예외 — {e}")

    # 전략 3
    log("  [전략 3] DOM element.click()...")
    try:
        await page.evaluate("""(elId) => {
            const el = document.getElementById(elId);
            if (!el) throw new Error('element not found: ' + elId);
            el.focus();
            el.click();
        }""", BTN_OUTPUT)
        if await _wait_for_modal(page, BTN_MODAL_CONFIRM, timeout=5):
            log("  [전략 3] 성공 — 모달 출현 확인")
            return 3
        log("  [전략 3] 실패 — 모달 미출현")
    except Exception as e:
        log(f"  [전략 3] 예외 — {e}")

    return 0


async def output_with_full_ssn(page):
    """출력 버튼 클릭 → 주민번호 전체표출 → 확인"""
    for attempt in range(1, 4):
        try:
            existing_modal = await page.evaluate(
                '(elId) => !!document.getElementById(elId)', BTN_MODAL_CONFIRM
            )
            if existing_modal:
                log("  기존 출력 모달 감지 — 취소로 닫기...")
                await nexacro_click_button(page, BTN_MODAL_CANCEL)
                await human_delay(1)
        except Exception:
            pass

        log(f"출력 버튼 클릭... (시도 {attempt}/3)")
        strategy = await _click_output_button(page)

        if strategy > 0:
            log(f"  출력 버튼 클릭 성공 (전략 {strategy})")
            break

        if attempt < 3:
            log(f"  모든 전략 실패 — 3초 후 재시도...")
            await human_delay(3)
    else:
        log("  ERROR: 출력 버튼 클릭 실패 (3회 × 3전략 시도)")
        return False
    await human_delay(2)

    log("주민번호 전체표출 선택...")
    await nexacro_wait_and_click(page, RADIO_FULL_SSN)
    await human_delay(1)

    log("확인 클릭...")
    result = await nexacro_wait_and_click(page, BTN_MODAL_CONFIRM)
    if not result.get("ok"):
        log(f"  ERROR: 확인 클릭 실패 - {result}")
        return False
    await human_delay(2)

    log("출력 옵션 적용 완료.")
    return True


async def download_pdf_from_preview(context, save_dir, filename):
    """rdPreview 탭에서 PDF 다운로드 후 탭 닫기"""
    rd_page = None
    for _ in range(10):
        for pg in context.pages:
            try:
                if "rdPreview" in pg.url:
                    rd_page = pg
                    break
            except Exception:
                continue
        if rd_page:
            break
        await asyncio.sleep(1)

    if not rd_page:
        log("  ERROR: rdPreview 탭을 찾지 못했습니다 (10초 대기).")
        return None

    log("  Crownix 뷰어 로딩 대기...")
    pdf_btn_found = False
    for _ in range(15):
        try:
            pdf_btn_found = await rd_page.evaluate("""() => {
                const btns = document.querySelectorAll('button.crownix-toolbar-button');
                for (const btn of btns) {
                    if ((btn.textContent || '').trim() === 'PDF') return true;
                }
                return false;
            }""")
            if pdf_btn_found:
                break
        except Exception:
            pass
        await asyncio.sleep(1)

    if not pdf_btn_found:
        log("  ERROR: Crownix PDF 버튼을 찾지 못했습니다 (15초 대기).")
        try:
            await rd_page.close()
        except Exception:
            pass
        return None

    os.makedirs(save_dir, exist_ok=True)
    cdp = await context.new_cdp_session(rd_page)
    await cdp.send("Browser.setDownloadBehavior", {
        "behavior": "allowAndName",
        "downloadPath": save_dir,
        "eventsEnabled": True,
    })

    before = set(os.listdir(save_dir))

    log("  PDF 버튼 클릭 (DOM .click())...")
    clicked = await rd_page.evaluate("""() => {
        const btns = document.querySelectorAll('button.crownix-toolbar-button');
        for (const btn of btns) {
            if ((btn.textContent || '').trim() === 'PDF') {
                btn.click();
                return true;
            }
        }
        return false;
    }""")

    download_started = False
    for _ in range(5):
        await asyncio.sleep(1)
        after = set(os.listdir(save_dir))
        new_files = after - before
        if any(f.endswith(".crdownload") or f.endswith(".pdf") for f in new_files):
            download_started = True
            break

    if not download_started:
        log("  PDF 버튼 DOM 클릭으로 다운로드 미시작 — Playwright locator 클릭...")
        try:
            pdf_btn = rd_page.locator('button.crownix-toolbar-button:has-text("PDF")')
            await pdf_btn.click(force=True, timeout=5000)
            for _ in range(5):
                await asyncio.sleep(1)
                after = set(os.listdir(save_dir))
                new_files = after - before
                if any(f.endswith(".crdownload") or f.endswith(".pdf") for f in new_files):
                    download_started = True
                    break
        except Exception as e:
            log(f"  Playwright locator 클릭 예외 — {e}")

    if not download_started:
        log("  WARN: PDF 다운로드가 감지되지 않음 — 추가 대기 진행...")

    for i in range(60):
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
            await rd_page.close()
            log(f"  PDF 저장 완료: {final_path}")
            return final_path
        if i % 10 == 9 and (crdownload or done):
            log(f"  PDF 다운로드 진행 중... ({i+1}초)")

    log("  ERROR: PDF 다운로드 시간 초과 (60초)")
    try:
        await rd_page.close()
        log("  rdPreview 탭 닫기 완료 (타임아웃 정리)")
    except Exception:
        pass
    return None


async def save_excel(page, context, save_dir, filename):
    """엑셀저장 버튼 클릭 → 주민번호 전체표출 → 확인 → Excel 다운로드"""
    log("엑셀저장 버튼 클릭...")

    existing_modal = await page.evaluate(
        '(elId) => !!document.getElementById(elId)', EXCEL_BTN_CONFIRM
    )
    if existing_modal:
        log("  기존 엑셀 모달 감지 — 닫기...")
        cancel_id = f"{EXCEL_MODAL_PREFIX}.div00_00.form.btn00"
        await nexacro_click_button(page, cancel_id)
        await human_delay(1)

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
    await nexacro_wait_and_click(page, EXCEL_RADIO_FULL_SSN)
    await human_delay(1)

    log("확인 클릭...")
    result = await nexacro_wait_and_click(page, EXCEL_BTN_CONFIRM)
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
            log(f"  Excel 저장 완료: {final_path}")
            return final_path

    log("  ERROR: Excel 다운로드 시간 초과")
    return None


async def save_integrated(page, context, save_dir, filename):
    """통합저장 버튼 클릭 → 주민번호 전체표출 → 확인 → 파일 다운로드"""
    log("통합저장 버튼 클릭...")

    existing_modal = await page.evaluate(
        '(elId) => !!document.getElementById(elId)', INTEGRATED_BTN_CONFIRM
    )
    if existing_modal:
        log("  기존 통합 모달 감지 — 닫기...")
        cancel_id = f"{INTEGRATED_MODAL_PREFIX}.div00_00.form.btn00"
        await nexacro_click_button(page, cancel_id)
        await human_delay(1)

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
    await nexacro_wait_and_click(page, INTEGRATED_RADIO_FULL_SSN)
    await human_delay(1)

    log("확인 클릭...")
    result = await nexacro_wait_and_click(page, INTEGRATED_BTN_CONFIRM)
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
    """결정내역 상세 탭에서 PDF + Excel 순차 다운로드"""
    from datetime import datetime
    now = datetime.now()
    _y = year if year is not None else now.year
    _m = month if month is not None else now.month
    base = f"국민연금보험료_결정내역_{_y}{_m:02d}_{tab_label}"

    log(f"{tab_label} 탭 이동...")
    ok = await click_detail_tab(page, tab_index)
    if not ok:
        log(f"  {tab_label} 탭 전환 실패, 스킵")
        return {"pdf": None, "excel": None, "skipped": True}

    grid_id = f"{GRID_DECISION_DETAIL}.{grid_suffix}"
    data = await nexacro_get_grid_data(page, grid_id)
    if not data:
        log(f"  {tab_label} 데이터 없음, 다운로드 스킵")
        return {"pdf": None, "excel": None, "skipped": True}

    log(f"  {tab_label} 데이터 {len(data)}행 감지, 다운로드 시작")

    pdf_path = None
    if await output_with_full_ssn(page):
        pdf_path = await download_pdf_from_preview(context, save_dir, base)

    try:
        stale = await page.evaluate(
            '(elId) => !!document.getElementById(elId)', BTN_MODAL_CONFIRM
        )
        if stale:
            log("  잔여 출력 모달 정리...")
            await nexacro_click_button(page, BTN_MODAL_CANCEL)
            await human_delay(1)
    except Exception:
        pass

    for pg in context.pages:
        try:
            if "rdPreview" in pg.url:
                await pg.close()
                log("  잔여 rdPreview 탭 닫기 완료")
        except Exception:
            continue

    if tab_index == TAB_GOVT:
        excel_path = await save_integrated(page, context, save_dir, f"{base}_엑셀")
    else:
        excel_path = await save_excel(page, context, save_dir, f"{base}_엑셀")

    return {"pdf": pdf_path, "excel": excel_path, "skipped": False}
