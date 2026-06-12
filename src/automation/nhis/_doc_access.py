"""NHIS EDI 문서 접근 모듈

받은문서 열기, 대체 진입, 서식 선택, 미리보기 탐지.
문서 다운로드 전 준비 단계(탐색/선택)만 담당.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from src.utils.log import log
from src.utils.human import human_delay
from src.utils.polling import wait_for_new_tab
from src.automation.nhis._constants import (
    DOCS_READY_TIMEOUT_S,
    RDO_PROG_STAT,
    RADIO_ITEMS,
    CBO_DOCID,
    PRINT_PREVIEW_TIMEOUT_S,
)
from src.automation.nhis._nexacro import (
    wait_for_nexacro_ready,
    nexacro_set_radio,
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
    for i in range(DOCS_READY_TIMEOUT_S):
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


async def find_preview_tab(context, pages_before, timeout=PRINT_PREVIEW_TIMEOUT_S):
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
