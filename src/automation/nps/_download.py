"""NPS EDI PDF/Excel download module

Tab switching, output button (3-strategy click), PDF/Excel/Integrated save,
Crownix viewer control.
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
from src.automation.nps._constants import (
    TAB_BTN_PREFIX, GRID_DECISION_DETAIL,
    BTN_OUTPUT, BTN_EXCEL_SAVE, BTN_INTEGRATED_SAVE,
    BTN_MODAL_CONFIRM, BTN_MODAL_CANCEL,
    MODAL_PREFIX, RADIO_FULL_SSN,
    EXCEL_MODAL_PREFIX, EXCEL_RADIO_FULL_SSN, EXCEL_BTN_CONFIRM, EXCEL_BTN_CANCEL,
    INTEGRATED_MODAL_PREFIX, INTEGRATED_RADIO_FULL_SSN, INTEGRATED_BTN_CONFIRM,
    INTEGRATED_BTN_CANCEL,
    DOWNLOAD_TIMEOUT_S, EXCEL_DOWNLOAD_TIMEOUT_S,
    CROWNIX_LOAD_TIMEOUT_S, PREVIEW_TAB_TIMEOUT_S,
    MODAL_WAIT_TIMEOUT_S, OUTPUT_CLICK_RETRIES, OUTPUT_STRATEGIES,
)

# Local alias
nexacro_click_button = nexacro_click_button_viewport


# --- Tab switching -----------------------------------------------------------

async def click_detail_tab(page, tab_index):
    """Switch tab on decision detail page."""
    tab_id = f"{TAB_BTN_PREFIX}{tab_index}"
    result = await nexacro_click_button(page, tab_id)
    if result.get("ok"):
        log(f"  tab {tab_index} switched")
    else:
        log(f"  tab switch failed: {result}")
    await human_delay(1)
    return result.get("ok", False)


# --- Modal helpers -----------------------------------------------------------

async def _wait_for_modal(page, modal_id, timeout=MODAL_WAIT_TIMEOUT_S):
    """Poll until modal element appears in DOM."""
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
    """Scroll element to viewport center."""
    try:
        await page.evaluate("""(elId) => {
            const el = document.getElementById(elId);
            if (el) el.scrollIntoView({block: 'center', behavior: 'instant'});
        }""", element_id)
        await asyncio.sleep(0.3)
    except Exception:
        pass


# --- Output button (3-strategy click) ----------------------------------------

async def _click_output_button(page):
    """Click output button using 3 sequential strategies. Returns strategy number or 0."""
    # Strategy 1: nexacro_click_button + scrollIntoView
    log("  [1] nexacro_click_button + scrollIntoView...")
    try:
        await _scroll_into_view(page, BTN_OUTPUT)
        result = await nexacro_click_button(page, BTN_OUTPUT)
        if result.get("ok") and await _wait_for_modal(page, BTN_MODAL_CONFIRM):
            log("  [1] success - modal appeared")
            return 1
        log(f"  [1] failed - result={result}")
    except Exception as e:
        log(f"  [1] exception - {e}")

    # Strategy 2: Playwright locator.click(force=True)
    log("  [2] Playwright locator.click(force=True)...")
    try:
        btn = page.locator(f'[id="{BTN_OUTPUT}"]')
        await btn.click(force=True, timeout=5000)
        if await _wait_for_modal(page, BTN_MODAL_CONFIRM):
            log("  [2] success - modal appeared")
            return 2
        log("  [2] failed - no modal")
    except Exception as e:
        log(f"  [2] exception - {e}")

    # Strategy 3: DOM element.click()
    log("  [3] DOM element.click()...")
    try:
        await page.evaluate("""(elId) => {
            const el = document.getElementById(elId);
            if (!el) throw new Error('element not found: ' + elId);
            el.focus();
            el.click();
        }""", BTN_OUTPUT)
        if await _wait_for_modal(page, BTN_MODAL_CONFIRM):
            log("  [3] success - modal appeared")
            return 3
        log("  [3] failed - no modal")
    except Exception as e:
        log(f"  [3] exception - {e}")

    return 0


async def output_with_full_ssn(page):
    """Click output button, select full SSN radio, confirm."""
    for attempt in range(1, OUTPUT_CLICK_RETRIES + 1):
        try:
            existing_modal = await page.evaluate(
                '(elId) => !!document.getElementById(elId)', BTN_MODAL_CONFIRM
            )
            if existing_modal:
                log("  existing output modal detected - closing...")
                await nexacro_click_button(page, BTN_MODAL_CANCEL)
                await human_delay(1)
        except Exception:
            pass

        log(f"output button click... (attempt {attempt}/{OUTPUT_CLICK_RETRIES})")
        strategy = await _click_output_button(page)

        if strategy > 0:
            log(f"  output button clicked (strategy {strategy})")
            break

        if attempt < OUTPUT_CLICK_RETRIES:
            log(f"  all strategies failed - retry in 3s...")
            await human_delay(3)
    else:
        log(f"  ERROR: output button click failed ({OUTPUT_CLICK_RETRIES}x{OUTPUT_STRATEGIES} attempts)")
        return False
    await human_delay(2)

    log("select full SSN display...")
    await nexacro_wait_and_click(page, RADIO_FULL_SSN)
    await human_delay(1)

    log("click confirm...")
    result = await nexacro_wait_and_click(page, BTN_MODAL_CONFIRM)
    if not result.get("ok"):
        log(f"  ERROR: confirm click failed - {result}")
        return False
    await human_delay(2)

    log("output options applied.")
    return True


# --- Download helpers --------------------------------------------------------

async def _find_preview_tab(context, timeout=PREVIEW_TAB_TIMEOUT_S):
    """Find and return rdPreview tab, or None."""
    rd_page = None
    for _ in range(timeout):
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
    return rd_page


async def _wait_for_crownix(page, timeout=CROWNIX_LOAD_TIMEOUT_S):
    """Wait for Crownix viewer to load and show PDF button."""
    for _ in range(timeout):
        try:
            found = await page.evaluate("""() => {
                const btns = document.querySelectorAll('button.crownix-toolbar-button');
                for (const btn of btns) {
                    if ((btn.textContent || '').trim() === 'PDF') return true;
                }
                return false;
            }""")
            if found:
                return True
        except Exception:
            pass
        await asyncio.sleep(1)
    return False


async def _setup_cdp_download(context, page, save_dir):
    """Configure CDP download behavior, return files_before set."""
    os.makedirs(save_dir, exist_ok=True)
    cdp = await context.new_cdp_session(page)
    await cdp.send("Browser.setDownloadBehavior", {
        "behavior": "allowAndName",
        "downloadPath": save_dir,
        "eventsEnabled": True,
    })
    return set(os.listdir(save_dir))


async def _wait_for_download(save_dir, before, timeout, label="file"):
    """Poll for download completion. Return downloaded path or None."""
    for i in range(timeout):
        await asyncio.sleep(1)
        after = set(os.listdir(save_dir))
        new_files = after - before
        crdownload = [f for f in new_files if f.endswith(".crdownload")]
        done = [f for f in new_files if not f.endswith(".crdownload")]
        if not crdownload and done:
            return os.path.join(save_dir, done[0])
        if i % 10 == 9 and (crdownload or done):
            log(f"  {label} download in progress... ({i+1}s)")
    return None


def _rename_download(downloaded, save_dir, filename, ext=None):
    """Rename downloaded file to desired name."""
    if ext is None:
        ext = os.path.splitext(downloaded)[1] or ".xlsx"
    final_path = os.path.join(save_dir, f"{filename}{ext}")
    if downloaded != final_path:
        if os.path.exists(final_path):
            os.remove(final_path)
        os.rename(downloaded, final_path)
    return final_path


# --- PDF download ------------------------------------------------------------

async def download_pdf_from_preview(context, save_dir, filename):
    """Download PDF from rdPreview tab (Crownix viewer), then close tab."""
    rd_page = await _find_preview_tab(context)
    if not rd_page:
        log(f"  ERROR: rdPreview tab not found ({PREVIEW_TAB_TIMEOUT_S}s waited)")
        return None

    log("  waiting for Crownix viewer...")
    if not await _wait_for_crownix(rd_page):
        log(f"  ERROR: Crownix PDF button not found ({CROWNIX_LOAD_TIMEOUT_S}s waited)")
        try:
            await rd_page.close()
        except Exception:
            pass
        return None

    before = await _setup_cdp_download(context, rd_page, save_dir)

    # Click PDF button (DOM .click())
    log("  PDF button click (DOM .click())...")
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
        log("  PDF DOM click did not start download - Playwright locator click...")
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
            log(f"  Playwright locator click exception - {e}")

    if not download_started:
        log("  WARN: PDF download not detected - proceeding with wait...")

    downloaded = await _wait_for_download(
        save_dir, before, DOWNLOAD_TIMEOUT_S, label="PDF"
    )
    if downloaded:
        final_path = _rename_download(downloaded, save_dir, filename, ext=".pdf")
        await rd_page.close()
        log(f"  PDF saved: {final_path}")
        return final_path

    log(f"  ERROR: PDF download timeout ({DOWNLOAD_TIMEOUT_S}s)")
    try:
        await rd_page.close()
        log("  rdPreview tab closed (timeout cleanup)")
    except Exception:
        pass
    return None


# --- Excel/Integrated save (unified) -----------------------------------------

async def _save_with_modal(page, context, save_dir, filename, *,
                           btn_id, modal_confirm_id, modal_cancel_id,
                           radio_full_ssn_id, label):
    """Generic: click button, select full SSN, confirm, wait for download, rename."""
    log(f"{label} button click...")

    # Dismiss existing modal
    existing_modal = await page.evaluate(
        '(elId) => !!document.getElementById(elId)', modal_confirm_id
    )
    if existing_modal:
        log(f"  existing {label} modal detected - closing...")
        await nexacro_click_button(page, modal_cancel_id)
        await human_delay(1)

    before = await _setup_cdp_download(context, page, save_dir)

    result = await nexacro_click_button(page, btn_id)
    if not result.get("ok"):
        log(f"  ERROR: {label} button click failed - {result}")
        return None
    await human_delay(2)

    log(f"select full SSN ({label} modal)...")
    await nexacro_wait_and_click(page, radio_full_ssn_id)
    await human_delay(1)

    log("click confirm...")
    result = await nexacro_wait_and_click(page, modal_confirm_id)
    if not result.get("ok"):
        log(f"  ERROR: confirm click failed - {result}")
        return None

    downloaded = await _wait_for_download(
        save_dir, before, EXCEL_DOWNLOAD_TIMEOUT_S, label=label
    )
    if downloaded:
        final_path = _rename_download(downloaded, save_dir, filename)
        log(f"  {label} complete: {final_path}")
        return final_path

    log(f"  ERROR: {label} download timeout ({EXCEL_DOWNLOAD_TIMEOUT_S}s)")
    return None


async def save_excel(page, context, save_dir, filename):
    """Excel save: click button, full SSN, confirm, download."""
    return await _save_with_modal(
        page, context, save_dir, filename,
        btn_id=BTN_EXCEL_SAVE,
        modal_confirm_id=EXCEL_BTN_CONFIRM,
        modal_cancel_id=EXCEL_BTN_CANCEL,
        radio_full_ssn_id=EXCEL_RADIO_FULL_SSN,
        label="excel save",
    )


async def save_integrated(page, context, save_dir, filename):
    """Integrated save: click button, full SSN, confirm, download."""
    return await _save_with_modal(
        page, context, save_dir, filename,
        btn_id=BTN_INTEGRATED_SAVE,
        modal_confirm_id=INTEGRATED_BTN_CONFIRM,
        modal_cancel_id=INTEGRATED_BTN_CANCEL,
        radio_full_ssn_id=INTEGRATED_RADIO_FULL_SSN,
        label="integrated save",
    )


# --- Tab download pipeline ---------------------------------------------------

async def process_tab_download(page, context, save_dir, tab_index, tab_label,
                                grid_suffix, *,
                                year: int | None = None,
                                month: int | None = None):
    """Download PDF + Excel from a decision detail tab."""
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

    # PDF download
    pdf_path = None
    if await output_with_full_ssn(page):
        pdf_path = await download_pdf_from_preview(context, save_dir, base)

    # Cleanup stale modal/tabs
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

    # Excel/Integrated download
    if tab_index == 4:  # TAB_GOVT
        excel_path = await save_integrated(page, context, save_dir, f"{base}_엑셀")
    else:
        excel_path = await save_excel(page, context, save_dir, f"{base}_엑셀")

    return {"pdf": pdf_path, "excel": excel_path, "skipped": False}
