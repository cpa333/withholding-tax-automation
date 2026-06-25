"""NHIS EDI 문서 다운로드 모듈

인쇄 버튼 3전략 클릭, PDF 다운로드, Crownix 뷰어 제어, 탭 정리.

인쇄 버튼 클릭:
  _click_print_button() — JS MouseEvent → Playwright locator → DOM click 3전략.
  각 전략 후 find_preview_tab()으로 미리보기 탭 오픈 검증, 최대 3회 재시도.
  NPS _download.py의 _click_output_button 패턴과 동일.

Nexacro 그리드 셀 ID:
  패턴 = gridrow_{rowIdx}_cell_{rowIdx}_{colIdx}
  colIdx: 0=순번, 1=받은일자, 2=번호, 3=서식명, 4=구분, 5=최종받은일자
  중간 번호도 행 인덱스이므로 _cell_0_ 하드코딩 금지.
"""

import asyncio
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from src.utils.log import log
from src.utils.save_path import make_save_dir
from src.utils.human import human_delay
from src.automation.nhis._constants import (
    NHIS_EDI_MAIN,
    BTN_PRINT,
    GRID_BODY_ID,
    PRINT_CLICK_RETRIES,
    CROWNIX_LOAD_TIMEOUT_S,
    PDF_DOWNLOAD_TIMEOUT_S,
    PAGE_STABLE_TIMEOUT_S,
)
from src.automation.nhis._nexacro import wait_for_nexacro_ready
from src.automation.nhis._doc_access import (
    open_received_docs,
    select_doc_type,
    find_preview_tab,
)


# ═══════════════════════════════════════════════════════════════════════════════
# 인쇄 버튼 3전략
# ═══════════════════════════════════════════════════════════════════════════════

async def _click_print_button(edi_page, context, pages_before):
    """인쇄 버튼 3전략 클릭. 미리보기 탭 Page 반환 또는 None.

    전략 1: JS MouseEvent 시뮬레이션 (기존 방식)
    전략 2: Playwright locator.click(force=True)
    전략 3: DOM element.focus() + element.click()

    각 전략 후 find_preview_tab으로 미리보기 탭 오픈 확인.
    전체 최대 3회 재시도.
    """
    for attempt in range(PRINT_CLICK_RETRIES):
        # ── 전략 1: JS MouseEvent 시뮬레이션 ──
        log(f"  [1] JS MouseEvent 시뮬레이션... (시도 {attempt + 1}/{PRINT_CLICK_RETRIES})")
        try:
            result = await edi_page.evaluate(f'''() => {{
                var btn = document.getElementById('{BTN_PRINT}');
                if (!btn) return {{ok: false, msg: 'print btn not found'}};
                var rect = btn.getBoundingClientRect();
                var cx = rect.x + rect.width / 2 + (Math.random() * 4 - 2);
                var cy = rect.y + rect.height / 2 + (Math.random() * 4 - 2);
                var base = {{bubbles: true, cancelable: true, view: window, screenX: cx, screenY: cy, clientX: cx, clientY: cy, button: 0, buttons: 1, relatedTarget: null}};
                btn.dispatchEvent(new MouseEvent('mousemove', {{...base, detail: 0, buttons: 0}}));
                var t = performance.now();
                while (performance.now() - t < 30 + Math.random() * 50) {{}}
                btn.dispatchEvent(new MouseEvent('mousedown', {{...base, detail: 1}}));
                btn.dispatchEvent(new MouseEvent('mouseup', {{...base, detail: 1}}));
                btn.dispatchEvent(new MouseEvent('click', {{...base, detail: 1}}));
                return {{ok: true}};
            }}''')
            if result.get("ok"):
                preview = await find_preview_tab(context, pages_before)
                if preview:
                    log("  [1] 성공 — 미리보기 탭 오픈")
                    return preview
                log("  [1] 클릭 ok but 미리보기 탭 미감지")
            else:
                log(f"  [1] 버튼 없음 — {result}")
        except Exception as e:
            log(f"  [1] 예외 — {e}")

        # ── 전략 2: Playwright locator.click(force=True) ──
        log("  [2] Playwright locator.click(force=True)...")
        try:
            btn = edi_page.locator(f'[id="{BTN_PRINT}"]')
            await btn.click(force=True, timeout=5000)
            preview = await find_preview_tab(context, pages_before)
            if preview:
                log("  [2] 성공 — 미리보기 탭 오픈")
                return preview
            log("  [2] 실패 — 미리보기 탭 미감지")
        except Exception as e:
            log(f"  [2] 예외 — {e}")

        # ── 전략 3: DOM element.focus() + element.click() ──
        log("  [3] DOM element.click()...")
        try:
            await edi_page.evaluate(f'''() => {{
                var el = document.getElementById('{BTN_PRINT}');
                if (!el) throw new Error('print btn not found');
                el.focus();
                el.click();
            }}''')
            preview = await find_preview_tab(context, pages_before)
            if preview:
                log("  [3] 성공 — 미리보기 탭 오픈")
                return preview
            log("  [3] 실패 — 미리보기 탭 미감지")
        except Exception as e:
            log(f"  [3] 예외 — {e}")

        if attempt < PRINT_CLICK_RETRIES - 1:
            log("  모든 전략 실패 — 2초 후 재시도...")
            await asyncio.sleep(2)

    return None


# ═══════════════════════════════════════════════════════════════════════════════
# PDF 다운로드
# ═══════════════════════════════════════════════════════════════════════════════

async def _find_target_row(edi_page, target_yyyymm):
    """그리드에서 YYYYMM 매칭 행 찾기 + 서식명 셀(col=3) 더블클릭

    매칭은 행 전체 textContent 에서 숫자만 추출(구분자 - . 년 월 일 제거)한 뒤
    6자리 target_yyyymm(예: 202605) 가 부분문자열로 들어있는지 본다. 포털 날짜가
    2026-05-15 / 2026.05 / 2026년05월 등 어떤 형태여도 YYYYMM 으로 정규화 매칭.
    """
    log(f"  문서 검색 (고지년월: {target_yyyymm})...")
    result = await edi_page.evaluate("""(args) => {
        var body = document.getElementById(args.gridBodyId);
        if (!body) return {ok: false, msg: 'grid body not found'};

        var allRows = body.querySelectorAll('[id*="gridrow_"]');
        var matchedIdx = null;
        for (var i = 0; i < allRows.length; i++) {
            var row = allRows[i];
            if (row.id.includes('gridrow_-1')) continue;
            if (row.id.includes('G')) continue;
            var digits = (row.textContent || '').replace(/\\D+/g, '');
            if (digits.indexOf(args.target) !== -1) {
                var m = row.id.match(/gridrow_(\\d+)$/);
                if (m) { matchedIdx = m[1]; break; }
            }
        }
        if (matchedIdx === null)
            return {ok: false, msg: 'no matching row for ' + args.target
                    + ' (rows seen: ' + allRows.length + ')'};

        var cellId = args.gridBodyId
            + '_gridrow_' + matchedIdx + '_cell_' + matchedIdx + '_3';
        var cell = document.getElementById(cellId);
        if (!cell)
            return {ok: false, msg: 'cell not found: ' + cellId};

        var rect = cell.getBoundingClientRect();
        var cx = rect.x + rect.width / 2 + (Math.random() * 4 - 2);
        var cy = rect.y + rect.height / 2 + (Math.random() * 4 - 2);
        var base = {bubbles: true, cancelable: true, view: window,
            screenX: cx, screenY: cy, clientX: cx, clientY: cy,
            button: 0, buttons: 1, relatedTarget: null};

        cell.dispatchEvent(new MouseEvent('mousemove',
            {...base, detail: 0, buttons: 0}));
        var t = performance.now();
        while (performance.now() - t < 30 + Math.random() * 50) {}
        cell.dispatchEvent(new MouseEvent('mousedown', {...base, detail: 1}));
        cell.dispatchEvent(new MouseEvent('mouseup',   {...base, detail: 1}));
        cell.dispatchEvent(new MouseEvent('click',     {...base, detail: 1}));
        t = performance.now();
        while (performance.now() - t < 30 + Math.random() * 50) {}
        cell.dispatchEvent(new MouseEvent('mousedown',  {...base, detail: 2}));
        cell.dispatchEvent(new MouseEvent('mouseup',    {...base, detail: 2}));
        cell.dispatchEvent(new MouseEvent('click',      {...base, detail: 2}));
        cell.dispatchEvent(new MouseEvent('dblclick',   {...base, detail: 2}));
        return {ok: true, rowIdx: matchedIdx,
                text: cell.textContent.trim().substring(0, 60)};
    }""", {"gridBodyId": GRID_BODY_ID, "target": target_yyyymm})

    if not result.get("ok"):
        log(f"  ERROR: 문서 검색 실패 - {result}")
        return None
    log(f"  문서 발견 (row {result['rowIdx']}): "
        f"{result.get('text', '')[:60]}")
    return result


async def _setup_crownix_download(context, preview, save_dir):
    """reportview iframe → Crownix 뷰어 대기 → CDP 다운로드 세션 설정

    Returns:
        (report_frame, cdp_session) or (None, None)
    """
    # ── reportview iframe 찾기 ──
    report_frame = None
    for attempt in range(10):
        for f in preview.frames:
            if "reportview" in f.url:
                report_frame = f
                break
        if report_frame:
            break
        await asyncio.sleep(1)

    if not report_frame:
        log("  ERROR: 리포트 프레임을 찾지 못했습니다 (10초 대기).")
        try:
            await preview.close()
        except Exception:
            pass
        return None, None

    # ── Crownix 뷰어 로딩 대기 ──
    log("  Crownix 뷰어 로딩 대기...")
    pdf_btn_found = False
    for attempt in range(CROWNIX_LOAD_TIMEOUT_S):
        try:
            pdf_btn_found = await report_frame.evaluate("""() => {
                const btn = document.querySelector('button[title="PDF 저장"]');
                return !!btn;
            }""")
            if pdf_btn_found:
                log(f"  Crownix 뷰어 준비 완료 ({attempt + 1}초)")
                break
        except Exception:
            pass
        await asyncio.sleep(1)

    if not pdf_btn_found:
        log(f"  ERROR: Crownix PDF 버튼을 찾지 못했습니다 ({CROWNIX_LOAD_TIMEOUT_S}초 대기).")
        try:
            await preview.close()
        except Exception:
            pass
        return None, None

    # ── CDP 다운로드 경로 설정 ──
    os.makedirs(save_dir, exist_ok=True)
    cdp_session = await context.new_cdp_session(preview)
    await cdp_session.send("Browser.setDownloadBehavior", {
        "behavior": "allowAndName",
        "downloadPath": save_dir,
        "eventsEnabled": True,
    })

    return report_frame, cdp_session


async def _wait_and_rename_pdf(save_dir, before, year, month):
    """다운로드 완료 대기 + PDF 헤더 검증 + 이름변경

    Returns:
        str: 저장된 PDF 경로, 또는 None
    """
    _y = year
    _m = month

    checked_files = set()
    for i in range(PDF_DOWNLOAD_TIMEOUT_S):
        await asyncio.sleep(1)
        after = set(os.listdir(save_dir))
        new_files = after - before
        downloading = [f for f in new_files if f.endswith(".crdownload")]
        done = [f for f in new_files if not f.endswith(".crdownload")]

        if not downloading and done:
            for fname in sorted(done):
                if fname in checked_files:
                    continue
                checked_files.add(fname)
                filepath = os.path.join(save_dir, fname)
                try:
                    with open(filepath, "rb") as fh:
                        header = fh.read(5)
                except Exception:
                    continue

                if header == b"%PDF-":
                    new_name = f"가입자고지내역서_건강_{_y}{_m:02d}.pdf"
                    new_path = os.path.join(save_dir, new_name)
                    if os.path.exists(new_path):
                        os.remove(new_path)
                    os.rename(filepath, new_path)
                    log(f"  PDF 저장 완료: {new_path}")
                    for f in os.listdir(save_dir):
                        if not f.lower().endswith(".pdf"):
                            try:
                                os.remove(os.path.join(save_dir, f))
                                log(f"  정리: {f} 삭제")
                            except Exception:
                                pass
                    return new_path
                else:
                    log(f"  비-PDF 파일 (무시): {fname} header={header!r}")

        if i % 10 == 9:
            log(f"  PDF 다운로드 대기... ({i + 1}초) downloading={len(downloading)} done={done}")

    log(f"  ERROR: PDF 다운로드 시간 초과 ({PDF_DOWNLOAD_TIMEOUT_S}초)")
    return None


def _resolve_period(year: int | None, month: int | None) -> tuple[int, int, str]:
    """year/month 의 None 폴백(당월) + 정규화. (year, month, target_yyyymm) 반환.

    target_yyyymm 은 6자리(예: 202605). None 이면 datetime.now() 의 년/월 사용.
    받은문서 그리드 행의 숫자정규화 text 와 부분문자열 매칭(_find_target_row)의 기준.
    """
    now = datetime.now()
    _y = year if year is not None else now.year
    _m = month if month is not None else now.month
    return _y, _m, f"{_y}{_m:02d}"


async def download_first_doc_pdf(edi_page, context, save_dir, firm_name,
                                  year: int | None = None, month: int | None = None):
    """웹EDI 받은문서 목록에서 YYYYMM 매칭 행 더블클릭 → 인쇄 → PDF 다운로드

    서식명(가입자 고지(산출) 내역서) 필터링 후, 그리드에서 고지년월이
    year/month와 일치하는 첫 번째 행을 찾아 상세 진입 후 PDF 저장.

    Nexacro 그리드 셀 ID 패턴: gridrow_{idx}_cell_{idx}_{col}
    중간 번호도 행 인덱스이므로 _cell_0_ 고정 금지.
    """
    # YYYYMM 타겟 계산 (None → 당월 폴백)
    _y, _m, target_yyyymm = _resolve_period(year, month)

    # 그리드에서 YYYYMM 매칭 행 찾기 + 더블클릭
    result = await _find_target_row(edi_page, target_yyyymm)
    if not result:
        return None
    await human_delay(3)

    # ── 인쇄 버튼 클릭 (3전략) ──
    pages_before = set(id(pg) for pg in context.pages)
    log("  인쇄 버튼 클릭 (3전략)...")
    preview = await _click_print_button(edi_page, context, pages_before)
    if not preview:
        log("  ERROR: 미리보기 탭을 찾지 못했습니다 (3전략 × 3회 시도).")
        return None
    log("  미리보기 탭 열림")

    # ── Crownix 뷰어 + CDP 세션 ──
    report_frame, cdp_session = await _setup_crownix_download(context, preview, save_dir)
    if not report_frame:
        return None

    try:
        before = set(os.listdir(save_dir))

        # 전략 1: DOM element.click()
        log("  PDF 버튼 클릭 (DOM .click())...")
        clicked = await report_frame.evaluate("""() => {
            const btn = document.querySelector('button[title="PDF 저장"]');
            if (btn) { btn.click(); return true; }
            return false;
        }""")

        download_started = False
        for _ in range(5):
            await asyncio.sleep(1)
            after = set(os.listdir(save_dir))
            new_files = after - before
            if new_files:
                download_started = True
                log(f"  다운로드 시작 감지: {list(new_files)[:3]}")
                break

        # 전략 2: Playwright locator.click(force=True)
        if not download_started:
            log("  PDF 버튼 DOM 클릭으로 다운로드 미시작 — Playwright locator 클릭...")
            try:
                pdf_btn = report_frame.locator('button[title="PDF 저장"]')
                await pdf_btn.click(force=True, timeout=5000)
                for _ in range(5):
                    await asyncio.sleep(1)
                    after = set(os.listdir(save_dir))
                    new_files = after - before
                    if new_files:
                        download_started = True
                        log(f"  다운로드 시작 감지 (전략2): {list(new_files)[:3]}")
                        break
            except Exception as e:
                log(f"  Playwright locator 클릭 예외 — {e}")

        if not download_started:
            log("  WARN: PDF 다운로드가 감지되지 않음 — 추가 대기 진행...")

        # 다운로드 완료 대기 + PDF 검증 + 이름변경
        pdf_path = await _wait_and_rename_pdf(save_dir, before, _y, _m)

        if not pdf_path:
            try:
                await preview.close()
                log("  미리보기 탭 닫기 완료 (타임아웃 정리)")
            except Exception:
                pass

        return pdf_path

    finally:
        if cdp_session:
            try:
                await cdp_session.detach()
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════════════════
# 워크플로우 오케스트레이터
# ═══════════════════════════════════════════════════════════════════════════════

async def reset_main_page(page):
    """retrieveMain 페이지를 재로드해 로그인 사업장(기본 사업장) 상태로 리셋.

    not-found/예외 등으로 run_single_firm_workflow 의 we_btn_relogin 복귀가
    생략된 뒤, 다음 수임처의 select_firm 클릭이 stale 페이지에서 no-op 가 되는
    것(N+1 lag/state-bleed)을 막기 위해 매 run_single 시작에 호출한다.

    page.goto(네비게이션)은 입력이벤트가 아니라 모달/alert/occlusion/선택된
    수임처 상태 무관하게 동작하며 세션(공동인증서 쿠키)이 유지돼 재로그인이
    불필요하다. NPS reset_workplace_page(page.goto(NPS_URL)+wait_for_nexacro_ready)
    와 동일한 패턴.
    """
    try:
        await page.goto(NHIS_EDI_MAIN, wait_until="domcontentloaded", timeout=60000)
        log("  retrieveMain 리셋(재로드) — 로그인 사업장 복귀")
    except Exception as e:
        log(f"  WARN: retrieveMain 리셋(goto) 실패 - {e}")
    await wait_for_nexacro_ready(page)


async def run_single_firm_workflow(page, context, firm_name,
                                    year: int | None = None,
                                    month: int | None = None,
                                    *, close_popups_fn=None):
    """수임처 1개에 대한 전체 워크플로우 수행

    플로우:
    1. 받은문서 → 웹EDI 탭 열기
    2. 전체 라디오 + 서식명 선택
    3. 첫 문서 더블클릭 → 인쇄 → PDF 다운로드
    4. 미리보기 + 웹EDI 탭 닫기
    5. 로그인 사업장 돌아가기
    """
    save_dir = make_save_dir("국민건강보험", firm_name, year=year, month=month)

    log("  메인페이지 안정화 대기...")
    for i in range(PAGE_STABLE_TIMEOUT_S):
        try:
            ready = await page.evaluate("""() => {
                return document.readyState === 'complete'
                    || document.readyState === 'interactive';
            }""")
            if ready:
                break
        except Exception:
            pass
        await asyncio.sleep(1)

    # Step 1: 받은문서 열기
    log("  [1/5] 받은문서 열기...")
    edi_page = await open_received_docs(page, context)
    if not edi_page:
        return False

    # Step 2: 전체 라디오 + 서식명 선택
    log("  [2/5] 전체 라디오 + 서식명 선택...")
    ok = await select_doc_type(edi_page)
    if not ok:
        await _close_edi_tabs(context)
        return False

    # Step 3: PDF 다운로드
    log("  [3/5] PDF 다운로드...")
    pdf_path = await download_first_doc_pdf(edi_page, context, save_dir, firm_name,
                                             year=year, month=month)

    # Step 4: 탭 정리
    log("  [4/5] 탭 정리...")
    await _close_edi_tabs(context)

    # Step 5: 로그인 사업장 돌아가기
    log("  [5/5] 로그인 사업장 복귀...")
    await page.evaluate("""() => {
        var img = document.querySelector('img[src*="we_btn_relogin"]');
        if (img) img.click();
    }""")
    await human_delay(3)

    # 모달 닫기
    if close_popups_fn:
        await close_popups_fn(context)

    if pdf_path:
        log(f"  완료! 저장: {pdf_path}")
        return True
    else:
        log("  PDF 다운로드 실패")
        return False


async def _close_edi_tabs(context):
    """웹EDI, 미리보기 등 메인이 아닌 탭 모두 닫기"""
    main_page = None
    for pg in context.pages:
        if "retrieveMain" in pg.url:
            main_page = pg
            break

    for pg in context.pages[:]:
        if pg != main_page:
            try:
                await pg.close()
            except Exception:
                pass
