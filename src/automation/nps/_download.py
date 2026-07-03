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
    nexacro_click,
    nexacro_wait_and_click,
    nexacro_get_grid_data,
)
from src.automation.nps._constants import (
    TAB_BTN_PREFIX, GRID_DECISION_DETAIL, TAB_FINAL,
    BTN_OUTPUT, BTN_OUTPUT_GOVT, BTN_EXCEL_SAVE, BTN_INTEGRATED_SAVE,
    BTN_MODAL_CONFIRM, BTN_MODAL_CANCEL,
    MODAL_PREFIX, RADIO_FULL_SSN,
    EXCEL_MODAL_PREFIX, EXCEL_RADIO_FULL_SSN, EXCEL_BTN_CONFIRM, EXCEL_BTN_CANCEL,
    INTEGRATED_MODAL_PREFIX, INTEGRATED_RADIO_FULL_SSN, INTEGRATED_BTN_CONFIRM,
    INTEGRATED_BTN_CANCEL,
    DOWNLOAD_TIMEOUT_S, EXCEL_DOWNLOAD_TIMEOUT_S,
    CROWNIX_LOAD_TIMEOUT_S, PREVIEW_TAB_TIMEOUT_S,
    MODAL_WAIT_TIMEOUT_S, OUTPUT_CLICK_RETRIES, OUTPUT_STRATEGIES,
    EXCEL_CLICK_RETRIES,
)

# Local alias
nexacro_click_button = nexacro_click_button_viewport


# --- Tab switching -----------------------------------------------------------

async def _is_tab_active(page, tab_index):
    """해당 탭이 활성 상태인지 (aria-selected == 'true')."""
    return await page.evaluate(
        '(id) => { const e = document.getElementById(id); '
        'return !!(e && e.getAttribute("aria-selected") === "true"); }',
        f"{TAB_BTN_PREFIX}{tab_index}",
    )


async def _wait_tab_present(page, tab_id, timeout_s=12):
    """탭 버튼 DOM이 나타날 때까지 폴링. 보이는 크기(w>0)까지 확인.

    2차 상세 진입 직후 Nexacro 탭바 렌더가 끝나기 전(특히 병렬·빈 프로필·
    백그라운드 창에서 느림)에 클릭하면 getElementById 가 null 이라 모든
    클릭 전략이 무동작 → 'aria-selected 미전환' 으로 실패한다. 클릭 전에
    탭 요소가 실제로 렌더될 때까지 기다려 타이밍 의존을 제거한다.
    """
    for _ in range(timeout_s * 2):
        try:
            ready = await page.evaluate(
                '(id) => { const e = document.getElementById(id); '
                'if (!e) return false; '
                'const r = e.getBoundingClientRect(); return r.width > 0; }',
                tab_id,
            )
            if ready:
                return True
        except Exception:
            pass
        await asyncio.sleep(0.5)
    return False


async def click_detail_tab(page, tab_index):
    """결정내역 상세의 탭 전환 — 합성 이벤트 + aria-selected 검증.

    Nexacro 탭 버튼은 page.mouse.click(좌표 기반)이 {ok:True}를 반환해도
    실제 전환이 일어나지 않는다(CSS transform 탓에 좌표가 어긋나 탭을
    누르지 못함 — 줄곧 최종결정내역 탭에 머무는 원인). 합성 dispatchEvent
    로 클릭하고 aria-selected 로 실제 전환을 반드시 검증한다. 실패 시
    mouse.click / DOM .click() 을 순차 폴백.

    클릭 전 탭바 렌더 완료를 기다리고(병렬 throttling 대응), 3전략을 여러
    라운드 재시도해 타이밍 흔들림에 둔감하게 만든다.
    """
    tab_id = f"{TAB_BTN_PREFIX}{tab_index}"

    # 탭바 렌더 대기 — 없으면 모든 전략이 무동작이라 의미 없음.
    if not await _wait_tab_present(page, tab_id, timeout_s=12):
        log(f"  tab {tab_index} 버튼 미렌더 (2차 상세 로딩 지연) — 전환 실패")
        return False

    # 이미 활성이면 바로 성공 (기본 활성 탭일 수 있음).
    if await _is_tab_active(page, tab_index):
        log(f"  tab {tab_index} already active")
        await human_delay(1)
        return True

    # 3전략 × 다중 라운드 — 렌더가 막 끝나 핸들러 바인딩이 늦는 경우 대비.
    for attempt in range(3):
        # 전략 1: 합성 dispatchEvent (Nexacro 탭 전환에 유효)
        try:
            await nexacro_click(page, tab_id)
        except Exception:
            pass
        await asyncio.sleep(1.0)
        if await _is_tab_active(page, tab_index):
            log(f"  tab {tab_index} switched (synthetic)")
            await human_delay(1)
            return True

        # 전략 2: page.mouse.click (좌표 기반 폴백)
        try:
            rect = await page.evaluate(
                '(id) => { const e = document.getElementById(id); if (!e) return null; '
                'const r = e.getBoundingClientRect(); '
                'return {x: r.x, y: r.y, w: r.width, h: r.height}; }',
                tab_id,
            )
            if rect and rect.get("w", 0) > 0:
                await page.mouse.click(rect["x"] + rect["w"] / 2, rect["y"] + rect["h"] / 2)
                await asyncio.sleep(1.0)
                if await _is_tab_active(page, tab_index):
                    log(f"  tab {tab_index} switched (mouse.click)")
                    await human_delay(1)
                    return True
        except Exception:
            pass

        # 전략 3: DOM element.click()
        try:
            await page.evaluate(
                '(id) => { const e = document.getElementById(id); if (e) e.click(); }',
                tab_id,
            )
            await asyncio.sleep(1.0)
            if await _is_tab_active(page, tab_index):
                log(f"  tab {tab_index} switched (dom click)")
                await human_delay(1)
                return True
        except Exception:
            pass

        if attempt < 2:
            log(f"  tab {tab_index} 전환 재시도... ({attempt + 1}/3)")
            await human_delay(1)

    log(f"  tab {tab_index} switch FAILED (aria-selected 미전환)")
    return False


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

async def _click_output_button(page, button_id=BTN_OUTPUT):
    """출력 버튼 클릭 — 순차 전략. 모달 출현으로 검증. 성공 시 >0 반환.

    GOVT(국고지원내역) 탭은 공용 BTN_OUTPUT(상단 div00.btn02) 대신 탭 고유의
    하단 출력 버튼(BTN_OUTPUT_GOVT)을 써야 모달이 열리므로 호출부가 button_id
    를 지정한다. 합성 dispatchEvent 를 최우선으로 쓴다 — Nexacro 버튼은 좌표
    기반 page.mouse.click 이 {ok:True}를 반환해도 실제 동작하지 않는 경우가
    있기 때문(GOVT 하단 출력 버튼 등).
    """
    # 전략 0: 합성 dispatchEvent (Nexacro 에 가장 신뢰)
    log("  [0] synthetic dispatch...")
    try:
        await nexacro_click(page, button_id)
        if await _wait_for_modal(page, BTN_MODAL_CONFIRM):
            log("  [0] success - modal appeared")
            return 1
        log("  [0] failed - no modal")
    except Exception as e:
        log(f"  [0] exception - {e}")

    # 전략 1: nexacro_click_button(mouse.click) + scrollIntoView
    log("  [1] nexacro_click_button + scrollIntoView...")
    try:
        await _scroll_into_view(page, button_id)
        result = await nexacro_click_button(page, button_id)
        if result.get("ok") and await _wait_for_modal(page, BTN_MODAL_CONFIRM):
            log("  [1] success - modal appeared")
            return 2
        log(f"  [1] failed - result={result}")
    except Exception as e:
        log(f"  [1] exception - {e}")

    # 전략 2: Playwright locator.click(force=True)
    log("  [2] Playwright locator.click(force=True)...")
    try:
        btn = page.locator(f'[id="{button_id}"]')
        await btn.click(force=True, timeout=5000)
        if await _wait_for_modal(page, BTN_MODAL_CONFIRM):
            log("  [2] success - modal appeared")
            return 3
        log("  [2] failed - no modal")
    except Exception as e:
        log(f"  [2] exception - {e}")

    # 전략 3: DOM element.click()
    log("  [3] DOM element.click()...")
    try:
        await page.evaluate("""(elId) => {
            const el = document.getElementById(elId);
            if (!el) throw new Error('element not found: ' + elId);
            el.focus();
            el.click();
        }""", button_id)
        if await _wait_for_modal(page, BTN_MODAL_CONFIRM):
            log("  [3] success - modal appeared")
            return 4
        log("  [3] failed - no modal")
    except Exception as e:
        log(f"  [3] exception - {e}")

    return 0


async def output_with_full_ssn(page, button_id=BTN_OUTPUT):
    """Click output button, select full SSN radio, confirm.

    button_id: GOVT 탭처럼 공용 출력 버튼이 아닌 탭 고유 버튼을 썸 때 지정.
    """
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
        strategy = await _click_output_button(page, button_id)

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
    """Wait for Crownix viewer to load and show PDF save button.

    신형 툴바는 'PDF 파일로 저장' 버튼이 '저장' 드롭다운 하위에 숨어있고,
    보이는 PDF 아이콘은 'PDF 파일로 변환하여 인쇄'(인쇄)이므로 title로 식별한다.
    구형(단일 PDF 버튼)은 textContent 'PDF' 로 폴백.
    """
    for _ in range(timeout):
        try:
            found = await page.evaluate(r"""() => {
                const btns = document.querySelectorAll('button.crownix-toolbar-button');
                for (const b of btns) {
                    if ((b.getAttribute('title')||'') === 'PDF 파일로 저장') return true;
                }
                let n = 0;
                for (const b of btns) if ((b.textContent||'').trim() === 'PDF') n++;
                return n === 1;
            }""")
            if found:
                return True
        except Exception:
            pass
        await asyncio.sleep(1)
    return False


async def _click_crownix_pdf_save(rd_page):
    """Crownix 'PDF 파일로 저장' 다운로드 버튼 클릭.

    보이는 PDF 아이콘은 'PDF 파일로 변환하여 인쇄'(인쇄)이고, 실제 다운로드
    ('PDF 파일로 저장') 버튼은 '저장' 드롭다운 하위에 숨어있을 수 있다
    (국고지원내역 GOVT 탭 등). 숨겨져 있으면 '저장' 드롭다운을 먼저 열어
    클릭이 동작하게 만든 뒤 title 으로 식별해 클릭.

    Returns: 'title' | 'text' | False
    """
    # 'PDF 파일로 저장' 이 숨겨져 있으면 '저장' 드롭다운을 먼저 연다
    hidden_save = await rd_page.evaluate(r"""() => {
        const btns = document.querySelectorAll('button.crownix-toolbar-button');
        for (const b of btns) {
            if ((b.getAttribute('title')||'') === 'PDF 파일로 저장' && b.offsetParent === null)
                return true;
        }
        return false;
    }""")
    if hidden_save:
        await rd_page.evaluate(r"""() => {
            const btns = document.querySelectorAll('button.crownix-toolbar-button');
            for (const b of btns) {
                if ((b.getAttribute('title')||'') === '저장' && b.offsetParent !== null) {
                    b.click(); return true;
                }
            }
            return false;
        }""")
        await asyncio.sleep(1.2)

    method = await rd_page.evaluate(r"""() => {
        const btns = document.querySelectorAll('button.crownix-toolbar-button');
        for (const b of btns) {
            if ((b.getAttribute('title')||'') === 'PDF 파일로 저장') { b.click(); return 'title'; }
        }
        for (const b of btns) {
            if ((b.textContent||'').trim() === 'PDF') { b.click(); return 'text'; }
        }
        return false;
    }""")
    return method


async def _setup_cdp_download(context, page, save_dir):
    """Configure CDP download behavior, return (files_before set, cdp session).

    cdp 세션을 함께 반환해 호출처가 사용 후 detach 하도록 한다(NHIS _doc_download 패턴).
    이전엔 세션을 반환하지 않아 호출처가 detach 못 해 매 다운로드마다 세션이 누수됐다.
    """
    os.makedirs(save_dir, exist_ok=True)
    cdp = await context.new_cdp_session(page)
    await cdp.send("Browser.setDownloadBehavior", {
        "behavior": "allowAndName",
        "downloadPath": save_dir,
        "eventsEnabled": True,
    })
    return set(os.listdir(save_dir)), cdp


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


def _is_valid_xlsx(path):
    """엑셀(zip) 매직(PK\\x03\\x04) + 최소 크기 검증.

    PDF %PDF- 매직 게이트(download_pdf_from_preview)와 동일 구조. 공유 폴더에서
    다른 파일(PDF/사이드카)을 grab 했거나 에러 페이지가 떨어진 경우를 가짜 엑셀로
    리네임·보고하는 것을 방지(BUG2). xlsx 는 zip 컨테이너이므로 PK 매직으로 검증.
    """
    try:
        with open(path, "rb") as f:
            head = f.read(8)
        size = os.path.getsize(path)
    except OSError:
        return False
    return head[:4] == b"PK\x03\x04" and size >= 2048


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

    before, cdp = await _setup_cdp_download(context, rd_page, save_dir)
    try:
        # PDF 저장 버튼 클릭 — '저장' 드롭다운 하위의 'PDF 파일로 저장'(다운로드).
        # 보이는 PDF 아이콘은 'PDF 파일로 변환하여 인쇄'(인쇄)이므로 title 로 식별한다.
        log("  PDF 저장 버튼 클릭...")
        method = await _click_crownix_pdf_save(rd_page)
        if method:
            log(f"  PDF 버튼 클릭 ({method})")
        else:
            log("  WARN: 'PDF 파일로 저장' 버튼을 찾지 못함")

        download_started = False
        for _ in range(10):
            await asyncio.sleep(1)
            new_files = set(os.listdir(save_dir)) - before
            # Crownix 는 UUID 이름(확장자 없음)으로 다운로드하기도 하므로,
            # .crdownload 가 없고 새 파일이 있으면 다운로드 시작으로 본다.
            if new_files and not any(f.endswith(".crdownload") for f in new_files):
                download_started = True
                break

        if not download_started:
            log("  PDF 클릭으로 다운로드 미시작 - Playwright locator 재시도...")
            try:
                pdf_btn = rd_page.locator(
                    'button.crownix-toolbar-button[title="PDF 파일로 저장"]'
                ).first
                if await pdf_btn.count() == 0:
                    pdf_btn = rd_page.locator(
                        'button.crownix-toolbar-button', has_text="PDF"
                    ).first
                await pdf_btn.click(force=True, timeout=5000)
                for _ in range(10):
                    await asyncio.sleep(1)
                    new_files = set(os.listdir(save_dir)) - before
                    if new_files and not any(f.endswith(".crdownload") for f in new_files):
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
            # PDF 무결성 검증 — Crownix 가 에러/사이드카 파일을 떨구는 경우
            # 이를 PDF로 오인·리네임해 가짜 성공을 보고하는 것을 방지.
            try:
                with open(final_path, "rb") as f:
                    head = f.read(8)
                size = os.path.getsize(final_path)
                if head[:5] != b"%PDF-" or size < 2048:
                    log(f"  ERROR: 다운로드 파일이 PDF가 아님 (size={size} magic={head!r})")
                    os.remove(final_path)
                    return None
            except Exception as e:
                log(f"  WARN: PDF 검증 중 예외: {e}")
            log(f"  PDF saved: {final_path}")
            return final_path

        log(f"  ERROR: PDF download timeout ({DOWNLOAD_TIMEOUT_S}s)")
        try:
            await rd_page.close()
            log("  rdPreview tab closed (timeout cleanup)")
        except Exception:
            pass
        return None
    finally:
        try:
            await cdp.detach()
        except Exception:
            pass


# --- Excel/Integrated save (unified) -----------------------------------------

async def _save_with_modal(page, context, save_dir, filename, *,
                           btn_id, modal_confirm_id, modal_cancel_id,
                           radio_full_ssn_id, label):
    """Generic: click button, select full SSN, confirm, wait for download, rename.

    PDF 경로(output_with_full_ssn/_click_output_button)의 robustness 를 엑셀에 이식:
      - 저장버튼 클릭을 모달 출현으로 검증하며 재시도 — nexacro_click_button 은
        page.mouse.click 후 {ok:True} 를 반환하지만 백그라운드/occluded 창에선
        no-op 일 수 있어 모달이 떴는지로 확정(BUG2 원인인 거짓양성 차단).
      - 리네임 후 zip 매직(PK) 검증 — 공유 폴더/사이드카 파일을 엑셀로 오인·리네임
        해 가짜 성공을 보고하는 것 방지(PDF %PDF- 게이트와 동일 구조).
    CDP 세션은 사용 후 finally 에서 detach(NHIS _doc_download 패턴).
    """
    log(f"{label} button click...")

    # Dismiss existing modal
    existing_modal = await page.evaluate(
        '(elId) => !!document.getElementById(elId)', modal_confirm_id
    )
    if existing_modal:
        log(f"  existing {label} modal detected - closing...")
        await nexacro_click_button(page, modal_cancel_id)
        await human_delay(1)

    before, cdp = await _setup_cdp_download(context, page, save_dir)
    try:
        # 저장 버튼 클릭 — 모달 출현으로 검증하며 재시도.
        modal_opened = False
        for attempt in range(1, EXCEL_CLICK_RETRIES + 1):
            result = await nexacro_click_button(page, btn_id)
            if result.get("ok") and await _wait_for_modal(page, modal_confirm_id):
                log(f"  {label} modal opened (attempt {attempt}/{EXCEL_CLICK_RETRIES})")
                modal_opened = True
                break
            log(f"  {label} 버튼/모달 실패 (attempt {attempt}/{EXCEL_CLICK_RETRIES}) result={result}")
            if attempt < EXCEL_CLICK_RETRIES:
                await human_delay(2)
        if not modal_opened:
            log(f"  ERROR: {label} 모달 오픈 실패 ({EXCEL_CLICK_RETRIES}회) - 다운로드 미진행")
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
        if not downloaded:
            log(f"  ERROR: {label} download timeout ({EXCEL_DOWNLOAD_TIMEOUT_S}s)")
            return None

        final_path = _rename_download(downloaded, save_dir, filename)
        # 엑셀 무결성 검증 — PDF %PDF- 매직 게이트와 동일 구조. 공유 폴더에서 다른
        # 파일을 grab 했거나 사이드카/에러 페이지가 떨어진 경우를 가짜 엑셀로
        # 리네임·보고하는 것을 방지(BUG2). 실패 시 파일 제거 + None 반환(상층이
        # 다운로드실패로 보고).
        if not _is_valid_xlsx(final_path):
            try:
                with open(final_path, "rb") as f:
                    head = f.read(8)
                log(f"  ERROR: 다운로드 파일이 엑셀(zip)이 아님 "
                    f"(size={os.path.getsize(final_path)} magic={head!r})")
                os.remove(final_path)
            except OSError:
                log(f"  ERROR: 엑셀 검증/제거 실패 - {final_path}")
            return None
        log(f"  {label} complete: {final_path}")
        return final_path
    finally:
        try:
            await cdp.detach()
        except Exception:
            pass


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


async def download_final_integrated(page, context, save_dir, *,
                                    year: int | None = None,
                                    month: int | None = None):
    """최종결정내역 탭(tab 0) 통합엑셀 + 출력 PDF 다운로드.

    3개 탭(가입자/소급/국고) 개별 다운로드를 대체하는 단일 소스.
    최종결정내역 탭에서 전체표출(주민번호 full)로 받아야 "2차결정내역통보서"
    전체 데이터(가입자+소급+국고, 성명 단위)가 한 장에 담긴다.

    1) 통합엑셀(BTN_INTEGRATED_SAVE → 전체표출 → 확인) — WEHAGO 자동입력 데이터 소스
    2) PDF(BTN_OUTPUT → 전체표출 → 확인 → Crownix rdPreview) — 사용자 열람용(베타 요구)

    Returns:
        {"excel": 경로|None, "pdf": 경로|None}
    """
    from datetime import datetime
    now = datetime.now()
    _y = year if year is not None else now.year
    _m = month if month is not None else now.month
    base = f"결정내역통보서_{_y}{_m:02d}"

    log("최종결정내역(tab 0) 이동...")
    ok = await click_detail_tab(page, TAB_FINAL)
    if not ok:
        log("  ERROR: 최종결정내역 탭 전환 실패")
        return {"excel": None, "pdf": None}
    await human_delay(2)

    # 1) 통합엑셀 (WEHAGO 자동입력 데이터 소스)
    log("통합저장(전체표출) 실행 — 엑셀...")
    excel_path = await save_integrated(page, context, save_dir, base)

    # 엑셀 모달(UHJE0002P2) 잔여 정리 — output_with_full_ssn은 출력 모달(UHJE0002P1)만
    # 정리하므로, 통합 모달이 남아있으면 BTN_OUTPUT 클릭 전 명시적으로 닫는다.
    try:
        stale_integrated = await page.evaluate(
            '(elId) => !!document.getElementById(elId)', INTEGRATED_BTN_CONFIRM
        )
        if stale_integrated:
            log("  잔여 통합 모달 정리...")
            await nexacro_click_button(page, INTEGRATED_BTN_CANCEL)
            await human_delay(1)
    except Exception:
        pass

    # 2) PDF — 상단 출력 버튼(BTN_OUTPUT, div00.btn02) → 전체표출 → Crownix.
    # 구 3탭 파이프라인(process_tab_download)에서 검증된 output_with_full_ssn +
    # download_pdf_from_preview 체인을 tab 0에 동일하게 적용.
    log("출력(PDF) 실행 — 상단 출력 버튼(BTN_OUTPUT)...")
    pdf_path = None
    if await output_with_full_ssn(page, button_id=BTN_OUTPUT):
        pdf_path = await download_pdf_from_preview(context, save_dir, f"{base}_출력")

    # 잔여 출력 모달(UHJE0002P1) + rdPreview 탭 정리 (process_tab_download 패턴)
    try:
        stale_output = await page.evaluate(
            '(elId) => !!document.getElementById(elId)', BTN_MODAL_CONFIRM
        )
        if stale_output:
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

    return {"excel": excel_path, "pdf": pdf_path}


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

    # PDF download — GOVT(국고지원내역) 탭은 공용 출력 버튼(BTN_OUTPUT)이
    # 동작하지 않으므로 탭 고유의 하단 출력 버튼(BTN_OUTPUT_GOVT)을 사용.
    pdf_path = None
    output_btn = BTN_OUTPUT_GOVT if tab_index == 4 else BTN_OUTPUT
    if await output_with_full_ssn(page, button_id=output_btn):
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
