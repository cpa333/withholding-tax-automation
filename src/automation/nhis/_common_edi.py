"""국민건강보험 EDI 자동화 공통 함수 모듈

edi.nhis.or.kr 법인 계정(업무대행) 사이트 제어를 위한 유틸리티.
모든 NHIS EDI 자동화 플로우에서 공유.
"""
import asyncio
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from src.utils.chrome_cdp import launch_chrome, CDP_URL
from src.utils.log import log
from src.utils.save_path import make_save_dir
from src.utils.human import human_delay

NHIS_EDI_URL = "https://edi.nhis.or.kr/"
NHIS_EDI_MAIN = "https://edi.nhis.or.kr/homeapp/wep/m/retrieveMain.xx"
FIRM_LIST_URL = "retrieveFirmList.do"

# Nexacro 그리드 ID prefix
GRID_RECEIVED = "mainframe_childframe_form_div_body_grid_list"

# 콤보박스 ID
CBO_DOCID = "mainframe_childframe_form_div_body_cbo_docid"

# 라디오 버튼 ID
RDO_PROG_STAT = "mainframe_childframe_form_div_body_rdo_prog_stat"
RADIO_ITEMS = {0: "전체", 1: "신규", 2: "열람"}

# 인쇄 버튼 ID
BTN_PRINT = "mainframe_childframe_form_div_top_img_print"


async def connect_page(playwright):
    """CDP로 Chrome에 연결하고 NHIS EDI 탭 우선 반환"""
    from src.utils.stealth import stealth_all_pages, register_auto_stealth

    browser = await playwright.chromium.connect_over_cdp(CDP_URL)
    context = browser.contexts[0]

    await stealth_all_pages(context)
    register_auto_stealth(context)

    for pg in context.pages:
        try:
            if "edi.nhis.or.kr" in pg.url:
                return browser, context, pg
        except Exception:
            continue

    page = context.pages[0] if context.pages else await context.new_page()
    return browser, context, page


async def wait_for_login(page):
    """NHIS EDI 로그인 완료 대기 (수동 공동인증서 로그인)

    retrieveMain.xx 페이지에 로그인 정보(사업장명)가 표시되면 로그인 완료로 판단.
    최대 15분 대기.
    """
    # 이미 메인 페이지에 사업장 정보가 있으면 로그인된 상태
    has_info = await page.evaluate("""() => {
        const text = document.body.innerText;
        return text.includes('사업장 관리번호') || text.includes('신규문서');
    }""")
    if has_info:
        log("이미 로그인되어 있습니다.")
        return True

    log("\n브라우저에서 국민건강보험 EDI 로그인을 진행해 주세요.")
    log("공동인증서로 로그인 후 자동으로 감지됩니다.")

    for i in range(180):
        await asyncio.sleep(5)
        try:
            if "retrieveMain" in page.url:
                has_info = await page.evaluate("""() => {
                    const text = document.body.innerText;
                    return text.includes('사업장 관리번호') || text.includes('신규문서');
                }""")
                if has_info:
                    log("로그인 확인됨.")
                    return True
        except Exception:
            pass
        if i % 6 == 5:
            log(f"  로그인 대기 중... ({(i + 1) * 5}초)")

    log("로그인 대기 시간 초과 (15분).")
    return False


async def close_popups(context):
    """메인 페이지 제외 모든 팝업/공지사항 탭 닫기

    retrievePopupData.do 팝업은 '하루동안 열지않기' 체크 후 closeWin()으로 닫아
    다음 접속 시 재등장하지 않도록 처리.
    """
    main_page = None
    for pg in context.pages:
        if "retrieveMain" in pg.url:
            main_page = pg
            break
    if not main_page:
        main_page = context.pages[0]

    closed = 0
    for pg in context.pages[:]:
        if pg == main_page:
            continue
        try:
            # 공지 팝업이면 '하루동안 열지않기' 체크 후 정상 닫기
            if "retrievePopupData" in pg.url:
                checked = await pg.evaluate("""() => {
                    var cb = document.getElementById('chk_close');
                    if (cb && !cb.checked) { cb.click(); return true; }
                    return false;
                }""")
                if checked:
                    log("  '하루동안 열지않기' 체크")
                await pg.evaluate("() => { if (typeof closeWin === 'function') closeWin(); }")
                await human_delay(0.5)
            await pg.close()
            closed += 1
        except Exception:
            # closeWin()이 탭을 이미 닫은 경우
            pass
    if closed:
        log(f"  팝업 {closed}개 닫음")
    return main_page


# ═══════════════════════════════════════════════════════════════════════════════
# 수임사업장 선택
# ═══════════════════════════════════════════════════════════════════════════════

async def open_firm_selector(page, context):
    """수임사업장선택 버튼 클릭 → 팝업 탭 반환

    수임처가 선택된 상태면 먼저 '로그인 사업장 돌아가기'로 복귀 후
    수임사업장선택 버튼 클릭.

    Returns:
        Page or None: 사업장 선택 팝업 탭
    """
    # 수임처 선택 상태면 먼저 로그인 사업장으로 복귀
    has_firm = await page.evaluate("""() => {
        var text = document.body.innerText;
        return text.includes('수임 사업자명');
    }""")
    if has_firm:
        log("  로그인 사업장으로 복귀...")
        await page.evaluate("""() => {
            var img = document.querySelector('img[src*="we_btn_relogin"]');
            if (img) img.click();
        }""")
        await human_delay(3)
        await close_popups(context)

    log("수임사업장선택 버튼 클릭...")
    clicked = await page.evaluate("""() => {
        const img = document.querySelector('img[src*="we_btn_suim"]');
        if (img) { img.click(); return true; }
        return false;
    }""")
    if not clicked:
        log("  ERROR: 수임사업장선택 버튼을 찾지 못했습니다.")
        return None

    # 팝업 탭 대기
    for _ in range(15):
        await asyncio.sleep(1)
        for pg in context.pages:
            if FIRM_LIST_URL in pg.url:
                log("  사업장 선택 팝업 열림")
                return pg

    log("  ERROR: 사업장 선택 팝업이 열리지 않았습니다.")
    return None


async def _parse_current_page_firms(popup):
    """현재 팝업 페이지의 사업장 목록 파싱

    Returns:
        dict: {firms: [{no, name, mgmtNo, unitCode, onclick}, ...],
               total, curPage, totalPages}
    """
    return await popup.evaluate("""() => {
        const firms = [];
        const rows = document.querySelectorAll('table.list tbody tr');
        rows.forEach(tr => {
            const tds = tr.querySelectorAll('td');
            if (tds.length >= 5) {
                const no = tds[1].textContent.trim();
                const name = tds[2].textContent.trim();
                const mgmtNo = tds[3].textContent.trim();
                const unitCode = tds[4].textContent.trim();
                const link = tds[2].querySelector('a');
                const onclick = link ? (link.getAttribute('onclick') || '') : '';
                if (no && /^\\d+$/.test(no)) {
                    firms.push({ no, name, mgmtNo, unitCode, onclick });
                }
            }
        });
        const txt = document.body.innerText;
        const m = txt.match(/총 (\\d+) 건/);
        const p = txt.match(/페이지 (\\d+)\\/(\\d+)/);
        return {
            firms,
            total: m ? m[1] : '',
            curPage: p ? p[1] : '',
            totalPages: p ? p[2] : ''
        };
    }""")


async def list_all_firms(popup):
    """페이징을 순회하여 전체 사업장 목록 수집

    fn_next('pageNo') JavaScript 함수로 페이지 전환.

    Args:
        popup: 사업장 선택 팝업 탭

    Returns:
        list[dict]: [{no, name, mgmtNo, unitCode, onclick}, ...]
    """
    # 1페이지로 리셋
    await popup.evaluate('() => { fn_next("1"); }')
    await human_delay(2)

    all_firms = []

    while True:
        await asyncio.sleep(2)
        result = await _parse_current_page_firms(popup)

        cur_page = int(result["curPage"]) if result["curPage"] else 1
        total_pages = int(result["totalPages"]) if result["totalPages"] else 1

        log(f"  [페이지 {cur_page}/{total_pages}] {len(result['firms'])}건 수집")
        all_firms.extend(result["firms"])

        if cur_page >= total_pages:
            break

        await popup.evaluate(f'() => {{ fn_next("{cur_page + 1}"); }}')

    # 중복 제거 (관리번호+단위기호 기준)
    seen = set()
    unique = []
    for f in all_firms:
        key = f["mgmtNo"] + f["unitCode"]
        if key not in seen:
            seen.add(key)
            unique.append(f)

    return unique


async def search_firm(popup, keyword, search_type="name"):
    """사업장 검색

    Args:
        popup: 사업장 선택 팝업 탭
        keyword: 검색어
        search_type: "name"(사업장명) 또는 "number"(사업장관리번호)

    Returns:
        list[dict]: 검색 결과 목록
    """
    type_map = {"name": "사업장명", "number": "사업장관리번호"}
    type_value = "사업장명" if search_type == "name" else "사업장관리번호"

    # 폼 요소 로드 대기
    for i in range(10):
        ready = await popup.evaluate("""() => {
            return !!document.getElementById('srchType')
                && !!document.getElementById('srchText')
                && !!document.getElementById('btnSubmit');
        }""")
        if ready:
            break
        await asyncio.sleep(0.5)
    else:
        # 폼 요소가 없으면 현재 DOM 상태 로깅
        ids = await popup.evaluate("""() => {
            const inputs = document.querySelectorAll('input, select, button');
            return Array.from(inputs).map(el =>
                (el.id || el.name || el.type) + ':' + el.tagName
            ).join(', ');
        }""")
        log(f"  ERROR: 검색 폼 요소를 찾지 못함. DOM: {ids}")
        return []

    # 검색 유형 선택
    await popup.evaluate("""(args) => {
        const sel = document.getElementById('srchType');
        if (sel) {
            for (const opt of sel.options) {
                if (opt.text.trim() === args.typeValue) {
                    sel.value = opt.value;
                    sel.dispatchEvent(new Event('change', {bubbles: true}));
                    break;
                }
            }
        }
    }""", {"typeValue": type_value})

    # 검색어 입력
    await popup.evaluate("""(args) => {
        const input = document.getElementById('srchText');
        if (input) {
            const nativeSetter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value'
            ).set;
            nativeSetter.call(input, args.keyword);
            input.dispatchEvent(new Event('input', {bubbles: true}));
            input.dispatchEvent(new Event('change', {bubbles: true}));
        }
    }""", {"keyword": keyword})

    # 폼 제출
    await popup.evaluate("""() => {
        const cPage = document.getElementById('cPage');
        if (cPage) cPage.value = '1';
        document.getElementById('btnSubmit').click();
    }""")
    await human_delay(3)

    return (await _parse_current_page_firms(popup))["firms"]


async def select_firm(popup, firm_name, management_number=""):
    """사업장 선택 팝업에서 특정 사업장 선택

    management_number가 제공되면 사업장관리번호로 검색.
    그렇지 않으면 사업장명으로 기존 목록에서 찾은 후 검색.

    Args:
        popup: 사업장 선택 팝업 탭
        firm_name: 선택할 사업장명 (부분 매칭)
        management_number: 사업장관리번호 (숫자만, 우선 사용)

    Returns:
        bool: 선택 성공 여부
    """
    if management_number:
        log(f"  사업장 검색: 관리번호 '{management_number}'")
        results = await search_firm(popup, management_number, search_type="number")
        if not results:
            log(f"  관리번호 '{management_number}' 사업장을 찾지 못했습니다.")
            return False
        # fn_firmChang onclick이 있는 실제 수임처 링크 클릭 (헤더 정렬 링크 제외)
        found = await popup.evaluate("""() => {
            const links = document.querySelectorAll('table.list a');
            for (const a of links) {
                const onclick = a.getAttribute('onclick') || '';
                if (onclick.includes('fn_firmChang')) {
                    a.click();
                    return a.textContent.trim();
                }
            }
            return null;
        }""")
        if found:
            log(f"  '{found}' 선택 완료")
            return True
        log(f"  검색 결과에서 사업장을 찾지 못했습니다.")
        return False

    log(f"  사업장 검색: '{firm_name}'")

    # 1페이지로 리셋 후 전체 목록에서 찾기
    await popup.evaluate('() => { fn_next("1"); }')
    await human_delay(2)

    # 현재 페이지에서 찾기
    found = await popup.evaluate("""(name) => {
        const links = document.querySelectorAll('table.list a');
        for (const a of links) {
            if (a.textContent.trim().includes(name)) {
                a.click();
                return a.textContent.trim();
            }
        }
        return null;
    }""", firm_name)

    if found:
        log(f"  '{found}' 선택 완료")
        return True

    # 검색으로 찾기
    log(f"  현재 페이지에 없음 — 검색으로 찾는 중...")
    results = await search_firm(popup, firm_name, search_type="name")

    if not results:
        log(f"  '{firm_name}' 사업장을 찾지 못했습니다.")
        return False

    # 검색 결과에서 클릭
    found = await popup.evaluate("""(name) => {
        const links = document.querySelectorAll('table.list a');
        for (const a of links) {
            if (a.textContent.trim().includes(name)) {
                a.click();
                return a.textContent.trim();
            }
        }
        return null;
    }""", firm_name)

    if found:
        log(f"  '{found}' 선택 완료")
        return True

    log(f"  '{firm_name}' 사업장을 찾지 못했습니다.")
    return False


async def select_firm_by_index(popup, index):
    """사업장 선택 팝업에서 N번째(0-based) 행의 사업장 선택

    Args:
        popup: 사업장 선택 팝업 탭
        index: 행 인덱스 (0-based)

    Returns:
        bool: 선택 성공 여부
    """
    result = await popup.evaluate("""(idx) => {
        const rows = document.querySelectorAll('table.list tbody tr');
        let count = 0;
        for (const tr of rows) {
            const tds = tr.querySelectorAll('td');
            if (tds.length >= 5 && /^\\d+$/.test(tds[1].textContent.trim())) {
                if (count === idx) {
                    const link = tds[2].querySelector('a');
                    if (link) {
                        link.click();
                        return { ok: true, name: link.textContent.trim() };
                    }
                }
                count++;
            }
        }
        return { ok: false };
    }""", index)

    if result.get("ok"):
        log(f"  '{result['name']}' 선택 완료")
        return True

    log(f"  {index + 1}번째 사업장을 찾지 못했습니다.")
    return False


async def close_firm_popup(context, popup):
    """사업장 선택 팝업 닫기"""
    try:
        await popup.close()
        log("  사업장 선택 팝업 닫음")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# Nexacro 초기화 대기
# ═══════════════════════════════════════════════════════════════════════════════

async def wait_for_nexacro_ready(page):
    """웹EDI(Nexacro) 프레임워크가 완전히 로딩될 때까지 대기

    DOM 요소뿐 아니라 nexacro.Application.mainframe.childframe.form 까지
    접근 가능해야 Nexacro 내부 API로 제어 가능.
    """
    for i in range(30):
        await asyncio.sleep(1)
        try:
            ready = await page.evaluate("""() => {
                try {
                    var n = window.nexacro;
                    if (!n || !n.Application) return false;
                    var mf = n.Application.mainframe;
                    if (!mf || !mf.childframe) return false;
                    var form = mf.childframe.form;
                    if (!form || !form.components) return false;
                    return !!form.components.div_body;
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


async def nexacro_set_radio(page, index):
    """Nexacro 라디오 컴포넌트를 DOM 클릭 + Nexacro 이벤트로 선택

    Nexacro 컴포넌트 객체가 준비되어도 DOM 렌더링이 늦을 수 있으므로
    DOM 컨테이너가 나타날 때까지 대기 후 클릭.

    Phase 1: DOM 컨테이너 대기 + 클릭 (단일 evaluate)
    Phase 2: Nexacro API로 onitemchanged 트리거 (최선 처리)

    Args:
        page: 웹EDI 탭
        index: 선택할 항목 인덱스 (0=전체, 1=신규, 2=열람)

    Returns:
        dict: {ok, value, index, text}
    """
    target_text = RADIO_ITEMS.get(index)
    if not target_text:
        return {"ok": False, "error": f"Unknown radio index: {index}"}

    # ── Phase 0: DOM 컨테이너 렌더링 대기 (최대 15초) ─────────────────
    # Nexacro 컴포넌트 객체는 존재해도 DOM 렌더링이 비동기로 늦어질 수 있음
    log(f"  라디오 DOM 컨테이너 대기...")
    for i in range(15):
        found = await page.evaluate("""(radioId) => {
            return !!document.getElementById(radioId)
                || document.querySelectorAll('[id*=rdo_prog_stat]').length > 0;
        }""", RDO_PROG_STAT)
        if found:
            log(f"  라디오 DOM 준비 완료 ({i+1}초)")
            break
        await asyncio.sleep(1)
    else:
        # DOM도 없고 Nexacro API도 안 되면 진짜 실패
        log("  ERROR: 라디오 DOM 컨테이너 대기 시간 초과 (15초)")
        return {"ok": False, "error": "radio container not found after 15s wait"}

    # ── Phase 1: DOM 클릭 (단일 evaluate, 안정적) ──────────────────────
    click_result = await page.evaluate("""(args) => {
        var container = document.getElementById(args.radioId);
        if (!container) {
            var candidates = document.querySelectorAll('[id*=rdo_prog_stat]');
            if (candidates.length > 0) container = candidates[0];
        }
        if (!container) return {ok: false, error: 'radio container not found'};

        var items = container.querySelectorAll('div[id$="_item"]');
        for (var item of items) {
            var textEl = item.querySelector('[id*=TextBoxElement]');
            if (textEl && textEl.textContent.trim() === args.targetText) {
                var rect = item.getBoundingClientRect();
                var cx = rect.x + rect.width / 2 + (Math.random() * 4 - 2);
                var cy = rect.y + rect.height / 2 + (Math.random() * 4 - 2);
                var base = {
                    bubbles: true, cancelable: true, view: window,
                    screenX: cx, screenY: cy, clientX: cx, clientY: cy,
                    button: 0, buttons: 1, relatedTarget: null
                };
                item.dispatchEvent(new MouseEvent('mousemove', {...base, detail: 0, buttons: 0}));
                var t = performance.now();
                while (performance.now() - t < 30 + Math.random() * 50) {}
                item.dispatchEvent(new MouseEvent('mousedown', {...base, detail: 1}));
                item.dispatchEvent(new MouseEvent('mouseup', {...base, detail: 1}));
                item.dispatchEvent(new MouseEvent('click', {...base, detail: 1}));
                return {ok: true, clicked: args.targetText};
            }
        }
        return {ok: false, error: 'item not found: ' + args.targetText};
    }""", {"radioId": RDO_PROG_STAT, "targetText": target_text})

    if not click_result.get("ok"):
        log(f"  ERROR: 라디오 DOM 클릭 실패 - {click_result}")
        return click_result

    # ── Phase 2: Nexacro API onitemchanged 트리거 (최대 3회 재시도) ───
    for attempt in range(3):
        await asyncio.sleep(0.5)
        result = await page.evaluate("""(targetIdx) => {
            try {
                var n = window.nexacro;
                if (!n || !n.Application) return null;
                var form = n.Application.mainframe.childframe.form;
                var divBody = form.components.div_body;
                var radio = divBody.components.rdo_prog_stat;
                if (!radio || typeof radio.index !== 'number') return null;

                var oldIndex = radio.index;
                var oldValue = radio.value;

                // DOM 클릭으로 이미 변경되었을 수 있으니, 다르면 보정
                if (radio.index !== targetIdx) {
                    radio.set_index(targetIdx);
                }

                var newValue = radio.value;
                var newIndex = radio.index;
                var newText = radio.text;

                radio.on_fire_onitemchanged(oldValue, newValue, oldIndex, newIndex);

                return {ok: true, value: newValue, index: newIndex, text: newText};
            } catch(e) {
                return null;  // null = 재시도
            }
        }""", index)

        if result is not None:
            return result

    # Phase 2 실패해도 Phase 1 DOM 클릭은 성공
    log("  WARN: Nexacro onitemchanged 트리거 실패 (DOM 클릭은 성공)")
    return {"ok": True, "value": None, "index": index, "text": target_text}


# ═══════════════════════════════════════════════════════════════════════════════
# Nexacro 이벤트 헬퍼
# ═══════════════════════════════════════════════════════════════════════════════

async def nexacro_click(page, element_id):
    """Nexacro 요소에 mousedown/mouseup/click 이벤트 발생"""
    return await page.evaluate("""(elId) => {
        const el = document.getElementById(elId);
        if (!el) return {error: 'not found: ' + elId};
        const rect = el.getBoundingClientRect();
        const cx = rect.x + rect.width / 2 + (Math.random() * 4 - 2);
        const cy = rect.y + rect.height / 2 + (Math.random() * 4 - 2);
        const base = {
            bubbles: true, cancelable: true, view: window,
            screenX: cx, screenY: cy, clientX: cx, clientY: cy,
            button: 0, buttons: 1, relatedTarget: null
        };
        el.dispatchEvent(new MouseEvent('mousemove', {...base, detail: 0, buttons: 0}));
        const t = performance.now();
        while (performance.now() - t < 30 + Math.random() * 50) {}
        el.dispatchEvent(new MouseEvent('mousedown', {...base, detail: 1}));
        el.dispatchEvent(new MouseEvent('mouseup', {...base, detail: 1}));
        el.dispatchEvent(new MouseEvent('click', {...base, detail: 1}));
        return {ok: true};
    }""", element_id)


async def nexacro_dblclick_cell(page, grid_id, row, col):
    """Nexacro 그리드 셀에 더블클릭 이벤트 발생"""
    cell_id = f"{grid_id}_body_gridrow_{row}_cell_{row}_{col}"
    return await page.evaluate("""(cellId) => {
        const cell = document.getElementById(cellId);
        if (!cell) return {error: 'cell not found'};
        const rect = cell.getBoundingClientRect();
        const cx = rect.x + rect.width / 2 + (Math.random() * 4 - 2);
        const cy = rect.y + rect.height / 2 + (Math.random() * 4 - 2);
        const base = {
            bubbles: true, cancelable: true, view: window,
            screenX: cx, screenY: cy, clientX: cx, clientY: cy,
            button: 0, buttons: 1, relatedTarget: null
        };
        cell.dispatchEvent(new MouseEvent('mousemove', {...base, detail: 0, buttons: 0}));
        let t = performance.now();
        while (performance.now() - t < 30 + Math.random() * 50) {}
        cell.dispatchEvent(new MouseEvent('mousedown', {...base, detail: 1}));
        cell.dispatchEvent(new MouseEvent('mouseup', {...base, detail: 1}));
        cell.dispatchEvent(new MouseEvent('click', {...base, detail: 1}));
        t = performance.now();
        while (performance.now() - t < 30 + Math.random() * 50) {}
        cell.dispatchEvent(new MouseEvent('mousedown', {...base, detail: 2}));
        cell.dispatchEvent(new MouseEvent('mouseup', {...base, detail: 2}));
        cell.dispatchEvent(new MouseEvent('click', {...base, detail: 2}));
        cell.dispatchEvent(new MouseEvent('dblclick', {...base, detail: 2}));
        return {ok: true, text: cell.textContent.trim()};
    }""", cell_id)


async def nexacro_select_combo(page, combo_id, item_text):
    """Nexacro 콤보박스에서 특정 텍스트 항목 선택

    combolist가 이미 열려있어야 함 (dropbutton 클릭 후).
    """
    return await page.evaluate("""(args) => {
        var list = document.getElementById(args.comboId + '_combolist');
        if (!list) return {error: 'combolist not found'};
        var items = list.querySelectorAll('div[id$=\"_item\"]');
        for (var item of items) {
            var textEl = item.querySelector('[id*=TextBoxElement]');
            if (textEl && textEl.textContent.trim() === args.itemText) {
                var rect = item.getBoundingClientRect();
                var cx = rect.x + rect.width / 2 + (Math.random() * 4 - 2);
                var cy = rect.y + rect.height / 2 + (Math.random() * 4 - 2);
                var base = {
                    bubbles: true, cancelable: true, view: window,
                    screenX: cx, screenY: cy, clientX: cx, clientY: cy,
                    button: 0, buttons: 1, relatedTarget: null
                };
                item.dispatchEvent(new MouseEvent('mousemove', {...base, detail: 0, buttons: 0}));
                var t = performance.now();
                while (performance.now() - t < 30 + Math.random() * 50) {}
                item.dispatchEvent(new MouseEvent('mousedown', {...base, detail: 1}));
                item.dispatchEvent(new MouseEvent('mouseup', {...base, detail: 1}));
                item.dispatchEvent(new MouseEvent('click', {...base, detail: 1}));
                return {ok: true, text: args.itemText};
            }
        }
        return {error: 'item not found: ' + args.itemText};
    }""", {"comboId": combo_id, "itemText": item_text})


async def nexacro_click_radio(page, radio_id, item_text):
    """Nexacro 라디오 그룹에서 특정 텍스트 항목 선택"""
    return await page.evaluate("""(args) => {
        var container = document.getElementById(args.radioId);
        if (!container) return {error: 'radio not found'};
        var items = container.querySelectorAll('div[id$=\"_item\"]');
        for (var item of items) {
            var textEl = item.querySelector('[id*=TextBoxElement]');
            if (textEl && textEl.textContent.trim() === args.itemText) {
                var rect = item.getBoundingClientRect();
                var cx = rect.x + rect.width / 2 + (Math.random() * 4 - 2);
                var cy = rect.y + rect.height / 2 + (Math.random() * 4 - 2);
                var base = {
                    bubbles: true, cancelable: true, view: window,
                    screenX: cx, screenY: cy, clientX: cx, clientY: cy,
                    button: 0, buttons: 1, relatedTarget: null
                };
                item.dispatchEvent(new MouseEvent('mousemove', {...base, detail: 0, buttons: 0}));
                var t = performance.now();
                while (performance.now() - t < 30 + Math.random() * 50) {}
                item.dispatchEvent(new MouseEvent('mousedown', {...base, detail: 1}));
                item.dispatchEvent(new MouseEvent('mouseup', {...base, detail: 1}));
                item.dispatchEvent(new MouseEvent('click', {...base, detail: 1}));
                return {ok: true};
            }
        }
        return {error: 'item not found: ' + args.itemText};
    }""", {"radioId": radio_id, "itemText": item_text})


# ═══════════════════════════════════════════════════════════════════════════════
# 수임처 1사이클 워크플로우
# ═══════════════════════════════════════════════════════════════════════════════

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
        # pageLinkPopup1이 없으면 대체 방식 시도
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
        for i in range(10):
            await asyncio.sleep(1)
            for pg in context.pages:
                if id(pg) not in pages_before and "webedi" in pg.url:
                    log("  웹EDI 탭 열림")
                    return pg

        log(f"  시도 {attempt} 실패 — 새 탭 미감지")
        await asyncio.sleep(2)

    # ── 4. 모든 시도 실패 — 대체 방식 ──
    log("  pageLinkPopup1 방식 실패 — 대체 방식 시도")
    return await _open_received_docs_fallback(page, context)


async def _open_received_docs_fallback(page, context):
    """받은문서 대체 진입: pageLinkPopup1 실패 시 링크/버튼 직접 클릭

    '받은문서' 텍스트가 포함된 a 태그 또는 onclick 핸들러가 있는 요소를 찾아 클릭.
    """
    pages_before = set(id(pg) for pg in context.pages)

    # 방법 1: '받은문서' 텍스트가 있는 클릭 가능한 요소 찾기
    clicked = await page.evaluate("""() => {
        // img alt 텍스트 또는 a 태그 텍스트에서 '받은문서' 찾기
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
        // 텍스트 기반 탐색
        const all = document.querySelectorAll('a, area, img, [onclick]');
        for (const el of all) {
            const text = (el.textContent || el.alt || el.title || '').trim();
            const onclick = el.getAttribute('onclick') || '';
            if (text.includes('받은문서') || onclick.includes("201")) {
                el.click();
                return 'text: ' + text.substring(0, 30);
            }
        }
        // 이미지 맵 area 탐색
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
        # 디버깅: 현재 페이지에서 클릭 가능한 요소 덤프
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

    # 새 탭 대기
    for i in range(15):
        await asyncio.sleep(1)
        for pg in context.pages:
            if id(pg) not in pages_before and "webedi" in pg.url:
                log("  웹EDI 탭 열림 (대체 방식)")
                return pg

    log("  ERROR: 대체 방식으로도 웹EDI 탭이 열리지 않았습니다.")
    return None


async def select_doc_type(edi_page, doc_name="가입자 고지(산출) 내역서"):
    """웹EDI에서 '전체' 라디오 선택 + 서식명 콤보박스 선택

    순서: Nexacro 준비 대기 → 라디오(Nexacro API) → dropbutton → combolist → 항목 선택

    Args:
        edi_page: 웹EDI 탭 (Nexacro)
        doc_name: 선택할 서식명

    Returns:
        bool: 선택 성공 여부
    """
    # Nexacro 프레임워크 준비 대기
    if not await wait_for_nexacro_ready(edi_page):
        return False

    # '전체' 라디오 선택 — Nexacro 내부 API 사용
    log("  '전체' 라디오 선택...")
    result = await nexacro_set_radio(edi_page, 0)
    if not result.get("ok"):
        log(f"  ERROR: 라디오 선택 실패 - {result}")
        return False
    log(f"  라디오: value=\"{result.get('value')}\" index={result.get('index')} text=\"{result.get('text')}\"")
    await human_delay(2)

    # 서식명 콤보 — combo 요소 대기
    log(f"  서식명 선택: {doc_name}")
    for _ in range(10):
        has_combo = await edi_page.evaluate('() => !!document.getElementById("mainframe_childframe_form_div_body_cbo_docid")')
        if has_combo:
            break
        await asyncio.sleep(1)

    # dropbutton 클릭 → combolist 동적 생성
    result = await edi_page.evaluate('''() => {
        var btn = document.getElementById('mainframe_childframe_form_div_body_cbo_docid_dropbutton');
        if (!btn) return {ok: false, msg: 'dropbutton not found'};
        var rect = btn.getBoundingClientRect();
        var cx = rect.x + rect.width / 2 + (Math.random() * 4 - 2);
        var cy = rect.y + rect.height / 2 + (Math.random() * 4 - 2);
        var base = {bubbles: true, cancelable: true, view: window, screenX: cx, screenY: cy, clientX: cx, clientY: cy, button: 0, buttons: 1, relatedTarget: null};
        btn.dispatchEvent(new MouseEvent('mousemove', {...base, detail: 0, buttons: 0}));
        var t = performance.now();
        while (performance.now() - t < 30 + Math.random() * 50) {}
        btn.dispatchEvent(new MouseEvent('mousedown', {...base, detail: 1}));
        btn.dispatchEvent(new MouseEvent('mouseup', {...base, detail: 1}));
        btn.dispatchEvent(new MouseEvent('click', {...base, detail: 1}));
        return {ok: true};
    }''')
    if not result.get("ok"):
        log(f"  ERROR: dropbutton 클릭 실패 - {result}")
        return False

    # combolist DOM 생성 대기
    for _ in range(10):
        has_list = await edi_page.evaluate('() => !!document.getElementById("mainframe_childframe_form_div_body_cbo_docid_combolist")')
        if has_list:
            break
        await asyncio.sleep(0.5)
    else:
        log("  ERROR: combolist가 생성되지 않았습니다.")
        return False

    # combolist에서 항목 선택
    result = await edi_page.evaluate("""(docName) => {
        var list = document.getElementById('mainframe_childframe_form_div_body_cbo_docid_combolist');
        if (!list) return {ok: false, msg: 'combolist not found'};
        var items = list.querySelectorAll('div[id$="_item"]');
        for (var item of items) {
            var textEl = item.querySelector('[id*=TextBoxElement]');
            if (textEl && textEl.textContent.trim() === docName) {
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
        return {ok: false, msg: 'item not found: ' + docName};
    }""", doc_name)
    if not result.get("ok"):
        log(f"  ERROR: 서식명 선택 실패 - {result}")
        return False

    await human_delay(1)

    # 확인
    value = await edi_page.evaluate("""() => {
        var input = document.getElementById('mainframe_childframe_form_div_body_cbo_docid_comboedit_input');
        return input ? input.value : '';
    }""")
    if value != doc_name:
        log(f"  WARN: 선택값 불일치 '{value}'")

    return True


async def download_first_doc_pdf(edi_page, context, save_dir, firm_name,
                                  year: int | None = None, month: int | None = None):
    """웹EDI 받은문서 목록에서 첫 행 더블클릭 → 인쇄 → PDF 다운로드

    Args:
        edi_page: 웹EDI 탭
        context: Browser context
        save_dir: 저장 디렉토리
        firm_name: 수임처명 (파일명용)

    Returns:
        str or None: 저장된 PDF 경로
    """
    # 첫 행 더블클릭
    log("  첫 번째 문서 더블클릭...")
    result = await edi_page.evaluate('''() => {
        var cell = document.getElementById('mainframe_childframe_form_div_body_grid_list_body_gridrow_0_cell_0_3');
        if (!cell) return {ok: false, msg: 'cell not found'};
        var rect = cell.getBoundingClientRect();
        var cx = rect.x + rect.width / 2 + (Math.random() * 4 - 2);
        var cy = rect.y + rect.height / 2 + (Math.random() * 4 - 2);
        var base = {bubbles: true, cancelable: true, view: window, screenX: cx, screenY: cy, clientX: cx, clientY: cy, button: 0, buttons: 1, relatedTarget: null};
        cell.dispatchEvent(new MouseEvent('mousemove', {...base, detail: 0, buttons: 0}));
        var t = performance.now();
        while (performance.now() - t < 30 + Math.random() * 50) {}
        cell.dispatchEvent(new MouseEvent('mousedown', {...base, detail: 1}));
        cell.dispatchEvent(new MouseEvent('mouseup', {...base, detail: 1}));
        cell.dispatchEvent(new MouseEvent('click', {...base, detail: 1}));
        t = performance.now();
        while (performance.now() - t < 30 + Math.random() * 50) {}
        cell.dispatchEvent(new MouseEvent('mousedown', {...base, detail: 2}));
        cell.dispatchEvent(new MouseEvent('mouseup', {...base, detail: 2}));
        cell.dispatchEvent(new MouseEvent('click', {...base, detail: 2}));
        cell.dispatchEvent(new MouseEvent('dblclick', {...base, detail: 2}));
        return {ok: true, text: cell.textContent.trim().substring(0, 60)};
    }''')
    if not result.get("ok"):
        log(f"  ERROR: 행 더블클릭 실패 - {result}")
        return None
    log(f"  문서: {result.get('text', '')[:60]}")
    await human_delay(3)

    # 인쇄 버튼 클릭
    log("  인쇄 버튼 클릭...")
    result = await edi_page.evaluate('''() => {
        var btn = document.getElementById('mainframe_childframe_form_div_top_img_print');
        if (!btn) return {ok: false, msg: 'print btn not found'};
        var rect = btn.getBoundingClientRect();
        var cx = rect.x + rect.width / 2 + (Math.random() * 4 - 2);
        var cy = rect.y + rect.height / 2 + (Math.random() * 4 - 2);
        var base = {bubbles: true, cancelable: true, view: window, screenX: cx, screenY: cy, clientX: cx, clientY: cy, button: 0, buttons: 1, relatedTarget: null};
        btn.dispatchEvent(new MouseEvent('mousemove', {...base, detail: 0, buttons: 0}));
        var t = performance.now();
        while (performance.now() - t < 30 + Math.random() * 50) {}
        btn.dispatchEvent(new MouseEvent('mousedown', {...base, detail: 1}));
        btn.dispatchEvent(new MouseEvent('mouseup', {...base, detail: 1}));
        btn.dispatchEvent(new MouseEvent('click', {...base, detail: 1}));
        return {ok: true};
    }''')
    if not result.get("ok"):
        log(f"  ERROR: 인쇄 버튼 클릭 실패 - {result}")
        return None
    await human_delay(3)

    # 미리보기 탭 찾기
    preview = None
    for pg in context.pages:
        if "popup.html" in pg.url and "WETZ" in pg.url:
            preview = pg
            break
    if not preview:
        log("  ERROR: 미리보기 탭을 찾지 못했습니다.")
        return None
    log("  미리보기 탭 열림")

    # reportview iframe 찾기
    report_frame = None
    for f in preview.frames:
        if "reportview" in f.url:
            report_frame = f
            break
    if not report_frame:
        log("  ERROR: 리포트 프레임을 찾지 못했습니다.")
        return None

    # CDP 다운로드 경로 설정
    os.makedirs(save_dir, exist_ok=True)
    cdp = await context.new_cdp_session(preview)
    await cdp.send("Browser.setDownloadBehavior", {
        "behavior": "allowAndName",
        "downloadPath": save_dir,
        "eventsEnabled": True,
    })

    before = set(os.listdir(save_dir))

    # PDF 버튼 클릭
    pdf_btn = report_frame.locator('button[title="PDF 저장"]')
    await pdf_btn.click()
    log("  PDF 버튼 클릭")

    # 다운로드 완료 대기
    for i in range(60):
        await asyncio.sleep(1)
        after = set(os.listdir(save_dir))
        new_files = after - before
        crdownload = [f for f in new_files if f.endswith(".crdownload")]
        done = [f for f in new_files if not f.endswith(".crdownload")]
        if not crdownload and done:
            downloaded = os.path.join(save_dir, sorted(done)[-1])
            with open(downloaded, "rb") as fh:
                header = fh.read(5)
            if header == b"%PDF-":
                now = datetime.now()
                _y = year if year is not None else now.year
                _m = month if month is not None else now.month
                new_name = f"가입자고지내역서_건강_{_y}{_m:02d}.pdf"
                new_path = os.path.join(save_dir, new_name)
                if os.path.exists(new_path):
                    os.remove(new_path)
                os.rename(downloaded, new_path)
                log(f"  PDF 저장 완료: {new_path}")
                return new_path
            else:
                log(f"  다운로드됨 (PDF 아님): {downloaded}")
                return downloaded
        if i % 10 == 9:
            log(f"  다운로드 대기 중... ({i + 1}초)")

    log("  ERROR: PDF 다운로드 시간 초과")
    return None


async def run_single_firm_workflow(page, context, firm_name,
                                    year: int | None = None,
                                    month: int | None = None):
    """수임처 1개에 대한 전체 워크플로우 수행

    플로우:
    1. 받은문서 → 웹EDI 탭 열기
    2. 전체 라디오 + 서식명 선택
    3. 첫 문서 더블클릭 → 인쇄 → PDF 다운로드
    4. 미리보기 + 웹EDI 탭 닫기
    5. 로그인 사업장 돌아가기

    Args:
        page: 메인 NHIS EDI 페이지
        context: Browser context
        firm_name: 수임처명

    Returns:
        bool: 성공 여부
    """
    save_dir = make_save_dir("국민건강보험", firm_name, year=year, month=month)

    # 사업장 전환 직후 메인페이지 안정화 대기
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
    await close_popups(context)

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
