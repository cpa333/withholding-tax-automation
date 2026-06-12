"""NHIS EDI 문서 다운로드 모듈

받은문서 열기, 서식 선택, 인쇄(3전략), PDF 다운로드, 탭 정리.

인쇄 버튼 클릭:
  _click_print_button() — JS MouseEvent → Playwright locator → DOM click 3전략.
  각 전략 후 _find_preview_tab()으로 미리보기 탭 오픈 검증, 최대 3회 재시도.
  NPS _download.py의 _click_output_button 패턴과 동일.
"""

import asyncio
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from src.utils.log import log
from src.utils.save_path import make_save_dir
from src.utils.human import human_delay
from src.utils.polling import wait_for_new_tab
from src.automation.nhis._nexacro import (
    wait_for_nexacro_ready,
    nexacro_set_radio,
    CBO_DOCID,
    BTN_PRINT,
)


async def open_received_docs(page, context):
    """받은문서 메뉴 클릭 → 웹EDI 새 탭 반환

    메인 페이지의 '받은문서' 링크(pageLinkPopup1('201')) 클릭.
    새 탭으로 웹EDI(Nexacro) 페이지가 열림.

    사업장 전환 직후 호출되므로:
    1) 메인페이지가 완전히 로드될 때까지 대기
    2) pageLinkPopup1 함수 존재 확인
    3) 실패 시 재시도 + 대체 방식(링크 직접 클릭)

    Returns:
        Page or None: 웹EDI 탭
    """
    # ── 1. 메인페이지 로딩 안정 대기 ──
    log("받은문서 메뉴 클릭 — 페이지 안정화 대기...")
    for i in range(20):
        try:
            ready = await page.evaluate("""() => {
                if (document.readyState !== 'complete'
                    && document.readyState !== 'interactive') return false;
                return typeof pageLinkPopup1 === 'function';
            }""")
            if ready:
                break
        except Exception:
            pass
        await asyncio.sleep(1)
    else:
        log("  pageLinkPopup1 함수를 찾지 못함 — 대체 방식 시도")
        return await _open_received_docs_fallback(page, context)

    # ── 2. 새 탭 열기 전 기존 탭 수 기록 ──
    pages_before = set(id(pg) for pg in context.pages)

    # ── 3. pageLinkPopup1 호출 (최대 3회 재시도) ──
    for attempt in range(1, 4):
        log(f"받은문서 메뉴 클릭... (시도 {attempt}/3)")
        try:
            await page.evaluate("() => { pageLinkPopup1('201'); }")
        except Exception as e:
            log(f"  pageLinkPopup1 호출 오류: {e}")
            await asyncio.sleep(2)
            continue

        # 새 탭 대기
        new_tab, _ = await wait_for_new_tab(context, "webedi", timeout=10)
        if new_tab:
            log("  웹EDI 탭 열림")
            return new_tab

        log(f"  시도 {attempt} 실패 — 새 탭 미감지")
        await asyncio.sleep(2)

    # ── 4. 모든 시도 실패 — 대체 방식 ──
    log("  pageLinkPopup1 방식 실패 — 대체 방식 시도")
    return await _open_received_docs_fallback(page, context)


async def _open_received_docs_fallback(page, context):
    """받은문서 대체 진입: pageLinkPopup1 실패 시 링크/버튼 직접 클릭"""
    pages_before = set(id(pg) for pg in context.pages)

    clicked = await page.evaluate("""() => {
        const selectors = [
            'img[alt*="받은문서"]',
            'a:has(img[alt*="받은문서"])',
            'a[onclick*="201"]',
            'area[onclick*="201"]',
        ];
        for (const sel of selectors) {
            try {
                const el = document.querySelector(sel);
                if (el) { el.click(); return 'selector: ' + sel; }
            } catch(e) {}
        }
        const all = document.querySelectorAll('a, area, img, [onclick]');
        for (const el of all) {
            const text = (el.textContent || el.alt || el.title || '').trim();
            const onclick = el.getAttribute('onclick') || '';
            if (text.includes('받은문서') || onclick.includes("201")) {
                el.click();
                return 'text: ' + text.substring(0, 30);
            }
        }
        const areas = document.querySelectorAll('area');
        for (const area of areas) {
            const href = area.getAttribute('href') || '';
            const onclick = area.getAttribute('onclick') || '';
            const alt = area.getAttribute('alt') || '';
            if (href.includes('201') || onclick.includes('201') || alt.includes('받은문서')) {
                area.click();
                return 'area: ' + alt;
            }
        }
        return null;
    }""")

    if clicked:
        log(f"  대체 클릭 성공: {clicked}")
    else:
        elements_info = await page.evaluate("""() => {
            const results = [];
            document.querySelectorAll('a, area, img, [onclick]').forEach(el => {
                const text = (el.textContent || '').trim().substring(0, 40);
                const alt = (el.alt || '').trim();
                const onclick = (el.getAttribute('onclick') || '').substring(0, 60);
                if (text || alt || onclick) {
                    results.push({tag: el.tagName, text, alt, onclick});
                }
            });
            return results;
        }""")
        log(f"  ERROR: 받은문서 요소를 찾지 못함. 페이지 요소 목록:")
        for el in elements_info[:30]:
            log(f"    {el['tag']} text=\"{el['text']}\" alt=\"{el['alt']}\" onclick=\"{el['onclick']}\"")
        return None

    new_tab, _ = await wait_for_new_tab(context, "webedi", timeout=15)
    if new_tab:
        log("  웹EDI 탭 열림 (대체 방식)")
        return new_tab

    log("  ERROR: 대체 방식으로도 웹EDI 탭이 열리지 않았습니다.")
    return None


async def select_doc_type(edi_page, doc_name="가입자 고지(산출) 내역서"):
    """웹EDI에서 '전체' 라디오 선택 + 서식명 콤보박스 선택

    순서: Nexacro 준비 대기 → 라디오(Nexacro API) → dropbutton → combolist → 항목 선택
    """
    if not await wait_for_nexacro_ready(edi_page):
        return False

    log("  '전체' 라디오 선택...")
    result = await nexacro_set_radio(edi_page, 0)
    if not result.get("ok"):
        log(f"  ERROR: 라디오 선택 실패 - {result}")
        return False
    log(f"  라디오: value=\"{result.get('value')}\" index={result.get('index')} text=\"{result.get('text')}\"")
    await human_delay(2)

    log(f"  서식명 선택: {doc_name}")
    for _ in range(10):
        has_combo = await edi_page.evaluate(f'() => !!document.getElementById("{CBO_DOCID}")')
        if has_combo:
            break
        await asyncio.sleep(1)

    # dropbutton 클릭 → combolist 동적 생성
    result = await edi_page.evaluate(f'''() => {{
        var btn = document.getElementById('{CBO_DOCID}_dropbutton');
        if (!btn) return {{ok: false, msg: 'dropbutton not found'}};
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
    if not result.get("ok"):
        log(f"  ERROR: dropbutton 클릭 실패 - {result}")
        return False

    # combolist DOM 생성 대기
    for _ in range(10):
        has_list = await edi_page.evaluate(f'() => !!document.getElementById("{CBO_DOCID}_combolist")')
        if has_list:
            break
        await asyncio.sleep(0.5)
    else:
        log("  ERROR: combolist가 생성되지 않았습니다.")
        return False

    # combolist에서 항목 선택
    result = await edi_page.evaluate("""(args) => {
        var list = document.getElementById(args.comboId + '_combolist');
        if (!list) return {ok: false, msg: 'combolist not found'};
        var items = list.querySelectorAll('div[id$="_item"]');
        for (var item of items) {
            var textEl = item.querySelector('[id*=TextBoxElement]');
            if (textEl && textEl.textContent.trim() === args.docName) {
                var rect = item.getBoundingClientRect();
                var cx = rect.x + rect.width / 2 + (Math.random() * 4 - 2);
                var cy = rect.y + rect.height / 2 + (Math.random() * 4 - 2);
                var base = {bubbles: true, cancelable: true, view: window, screenX: cx, screenY: cy, clientX: cx, clientY: cy, button: 0, buttons: 1, relatedTarget: null};
                item.dispatchEvent(new MouseEvent('mousemove', {...base, detail: 0, buttons: 0}));
                var t = performance.now();
                while (performance.now() - t < 30 + Math.random() * 50) {}
                item.dispatchEvent(new MouseEvent('mousedown', {...base, detail: 1}));
                item.dispatchEvent(new MouseEvent('mouseup', {...base, detail: 1}));
                item.dispatchEvent(new MouseEvent('click', {...base, detail: 1}));
                return {ok: true};
            }
        }
        return {ok: false, msg: 'item not found: ' + args.docName};
    }""", {"comboId": CBO_DOCID, "docName": doc_name})
    if not result.get("ok"):
        log(f"  ERROR: 서식명 선택 실패 - {result}")
        return False

    await human_delay(1)

    # 확인
    value = await edi_page.evaluate(f"""() => {{
        var input = document.getElementById('{CBO_DOCID}_comboedit_input');
        return input ? input.value : '';
    }}""")
    if value != doc_name:
        log(f"  WARN: 선택값 불일치 '{value}'")

    return True


async def _find_preview_tab(context, pages_before, timeout=5):
    """popup.html + WETZ 미리보기 탭 감지

    새 탭(pages_before 이후) 우선, fallback으로 기존 탭에서 검색.
    """
    preview = None
    for _ in range(timeout):
        for pg in context.pages:
            try:
                if "popup.html" in pg.url and "WETZ" in pg.url:
                    if id(pg) not in pages_before:
                        preview = pg
                        break
            except Exception:
                continue
        if preview:
            break
        await asyncio.sleep(1)

    # fallback: 기존 탭에서도 검색
    if not preview:
        for pg in context.pages:
            try:
                if "popup.html" in pg.url and "WETZ" in pg.url:
                    preview = pg
                    break
            except Exception:
                continue

    return preview


async def _click_print_button(edi_page, context, pages_before):
    """인쇄 버튼 3전략 클릭. 미리보기 탭 Page 반환 또는 None.

    전략 1: JS MouseEvent 시뮬레이션 (기존 방식)
    전략 2: Playwright locator.click(force=True)
    전략 3: DOM element.focus() + element.click()

    각 전략 후 _find_preview_tab으로 미리보기 탭 오픈 확인.
    전체 최대 3회 재시도.
    """
    for attempt in range(3):
        # ── 전략 1: JS MouseEvent 시뮬레이션 ──
        log(f"  [1] JS MouseEvent 시뮬레이션... (시도 {attempt + 1}/3)")
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
                preview = await _find_preview_tab(context, pages_before, timeout=5)
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
            preview = await _find_preview_tab(context, pages_before, timeout=5)
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
            preview = await _find_preview_tab(context, pages_before, timeout=5)
            if preview:
                log("  [3] 성공 — 미리보기 탭 오픈")
                return preview
            log("  [3] 실패 — 미리보기 탭 미감지")
        except Exception as e:
            log(f"  [3] 예외 — {e}")

        if attempt < 2:
            log("  모든 전략 실패 — 2초 후 재시도...")
            await asyncio.sleep(2)

    return None


async def download_first_doc_pdf(edi_page, context, save_dir, firm_name,
                                  year: int | None = None, month: int | None = None):
    """웹EDI 받은문서 목록에서 YYYYMM 매칭 행 더블클릭 → 인쇄 → PDF 다운로드

    서식명(가입자 고지(산출) 내역서) 필터링 후, 그리드에서 고지년월이
    year/month와 일치하는 첫 번째 행을 찾아 상세 진입 후 PDF 저장.
    """
    # YYYYMM 타겟 계산
    now = datetime.now()
    _y = year if year is not None else now.year
    _m = month if month is not None else now.month
    target_yyyymm = f"{_y}{_m:02d}"

    # 그리드에서 YYYYMM 매칭 행 찾기 + 서식명 셀(col=3) 더블클릭
    log(f"  문서 검색 (고지년월: {target_yyyymm})...")
    result = await edi_page.evaluate("""(target) => {
        var body = document.getElementById(
            'mainframe_childframe_form_div_body_grid_list_body'
        );
        if (!body) return {ok: false, msg: 'grid body not found'};

        var allRows = body.querySelectorAll('[id*="gridrow_"]');
        var matchedIdx = null;
        for (var i = 0; i < allRows.length; i++) {
            var row = allRows[i];
            if (row.id.includes('gridrow_-1')) continue;
            if (row.id.includes('G')) continue;
            if (row.textContent.includes(target)) {
                var m = row.id.match(/gridrow_(\\d+)$/);
                if (m) { matchedIdx = m[1]; break; }
            }
        }
        if (matchedIdx === null)
            return {ok: false, msg: 'no matching row for ' + target};

        var cellId = 'mainframe_childframe_form_div_body_grid_list_body'
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
    }""", target_yyyymm)

    if not result.get("ok"):
        log(f"  ERROR: 문서 검색 실패 - {result}")
        return None
    log(f"  문서 발견 (row {result['rowIdx']}): "
        f"{result.get('text', '')[:60]}")
    await human_delay(3)

    # ── 인쇄 버튼 클릭 (3전략) ──
    pages_before = set(id(pg) for pg in context.pages)
    log("  인쇄 버튼 클릭 (3전략)...")
    preview = await _click_print_button(edi_page, context, pages_before)
    if not preview:
        log("  ERROR: 미리보기 탭을 찾지 못했습니다 (3전략 × 3회 시도).")
        return None
    log("  미리보기 탭 열림")

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
        return None

    # ── Crownix 뷰어 로딩 대기 ──
    log("  Crownix 뷰어 로딩 대기...")
    pdf_btn_found = False
    for attempt in range(15):
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
        log("  ERROR: Crownix PDF 버튼을 찾지 못했습니다 (15초 대기).")
        try:
            await preview.close()
        except Exception:
            pass
        return None

    # ── CDP 다운로드 경로 설정 + PDF 다운로드 ──
    os.makedirs(save_dir, exist_ok=True)
    cdp_session = None
    try:
        cdp_session = await context.new_cdp_session(preview)
        await cdp_session.send("Browser.setDownloadBehavior", {
            "behavior": "allowAndName",
            "downloadPath": save_dir,
            "eventsEnabled": True,
        })

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

        # 다운로드 완료 대기 (최대 60초)
        checked_files = set()
        for i in range(60):
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

        log("  ERROR: PDF 다운로드 시간 초과 (60초)")
        try:
            await preview.close()
            log("  미리보기 탭 닫기 완료 (타임아웃 정리)")
        except Exception:
            pass
        return None

    finally:
        if cdp_session:
            try:
                await cdp_session.detach()
            except Exception:
                pass


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
    for i in range(15):
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
