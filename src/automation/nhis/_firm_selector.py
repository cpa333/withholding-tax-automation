"""NHIS EDI 수임사업장 선택 모듈

사업장 선택 팝업 제어, 검색, 페이징, 선택 관련 함수.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from src.utils.log import log
from src.utils.human import human_delay

# 수임사업장 리스트 URL 경로
from src.automation.nhis._constants import FIRM_LIST_URL


async def wait_firm_selector_ready(page, context, timeout_s=40):
    """로그인 직후 retrieveMain 이 리다이렉트·렌더를 끝내고 수임사업장선택
    버튼이 나타날 때까지 대기.

    로그인 직후 첫 수임처에서 (a) 버튼이 아직 안 떠 '못 찾음' (b) 폴링 중
    네비게이션으로 'context destroyed' 가 났다(첫 1~2건만 실패하고 안정된
    뒤 건은 성공한 원인). 첫 건 처리 전에 페이지를 한 번 안정화시킨다.
    네비게이션 중 evaluate 예외는 무시하고 재시도하며, retrieveMain 탭을
    매번 재해석한다.
    """
    for _ in range(timeout_s * 2):
        target = page
        for pg in context.pages:
            try:
                if "retrieveMain" in pg.url:
                    target = pg
                    break
            except Exception:
                continue
        try:
            found = await target.evaluate("""() => {
                const img = document.querySelector('img[src*="we_btn_suim"]')
                         || document.querySelector('img[alt*="수임사업장선택"]');
                return !!img;
            }""")
            if found:
                return True
        except Exception:
            pass
        await asyncio.sleep(0.5)
    return False


async def open_firm_selector(page, context, *, close_popups_fn=None):
    """수임사업장선택 버튼 클릭 → 팝업 탭 반환

    수임처가 선택된 상태면 먼저 '로그인 사업장 돌아가기'로 복귀 후
    수임사업장선택 버튼 클릭.

    Args:
        page: NHIS EDI 메인 페이지
        context: Browser context
        close_popups_fn: close_popups 함수 (circular import 방지용)

    Returns:
        Page or None: 사업장 선택 팝업 탭
    """
    # 수임사업장선택 버튼은 retrieveMain 메인 페이지에 있음.
    # 전달된 page 가 다른 탭/전환 중 상태로 드리프트했을 수 있어 context 에서
    # retrieveMain 탭을 재해석해 그 페이지에서 조작.
    main = None
    for pg in context.pages:
        try:
            if "retrieveMain" in pg.url:
                main = pg
                break
        except Exception:
            continue
    if main:
        page = main
        try:
            await page.bring_to_front()
        except Exception:
            pass

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
        if close_popups_fn:
            await close_popups_fn(context)

    log("수임사업장선택 버튼 클릭...")
    # 버튼이 렌더링될 때까지 폴링 — retrieveMain 메인프레임 콘텐츠는 로드 후
    # 비동기로 채워지고, 병렬에서 가려진 창은 렌더·타이머가 throttle 되어
    # 단발/단기 querySelector 로는 못 잡는다(라이브 점검 시 버튼은 분명 존재).
    # 최대 ~25초로 늘리고, 주기적으로 탭을 전면화해 렌더를 촉진한다.
    clicked = False
    for i in range(50):
        # evaluate 가 페이지 네비게이션과 겹치면 'Execution context was destroyed'
        # 예외가 난다(로그인 직후 retrieveMain 리다이렉트 중 발생). 폴링 전체가
        # 죽지 않게 예외를 삼키고 다음 반복에서 재시도한다.
        try:
            clicked = await page.evaluate("""() => {
                const img = document.querySelector('img[src*="we_btn_suim"]')
                         || document.querySelector('img[alt*="수임사업장선택"]');
                if (img) { img.click(); return true; }
                return false;
            }""")
        except Exception:
            clicked = False
        if clicked:
            break
        if i % 10 == 9:
            try:
                await page.bring_to_front()
            except Exception:
                pass
        await asyncio.sleep(0.5)
    if not clicked:
        try:
            cur_url = page.url
        except Exception:
            cur_url = "?"
        log(f"  ERROR: 수임사업장선택 버튼을 찾지 못했습니다. (page={cur_url})")
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
    """
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

    # 중복 제거
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
    type_value = "사업장명" if search_type == "name" else "사업장관리번호"

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
        ids = await popup.evaluate("""() => {
            const inputs = document.querySelectorAll('input, select, button');
            return Array.from(inputs).map(el =>
                (el.id || el.name || el.type) + ':' + el.tagName
            ).join(', ');
        }""")
        log(f"  ERROR: 검색 폼 요소를 찾지 못함. DOM: {ids}")
        return []

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
    """
    log(f"  select_firm: name='{firm_name}' mgmt_no='{management_number}'")
    if management_number:
        log(f"  사업장 검색: 관리번호 '{management_number}'")
        results = await search_firm(popup, management_number, search_type="number")
        if not results:
            log(f"  관리번호 '{management_number}' 사업장을 찾지 못했습니다.")
            return False
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

    await popup.evaluate('() => { fn_next("1"); }')
    await human_delay(2)

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

    log(f"  현재 페이지에 없음 — 검색으로 찾는 중...")
    results = await search_firm(popup, firm_name, search_type="name")

    if not results:
        log(f"  '{firm_name}' 사업장을 찾지 못했습니다.")
        return False

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
    """사업장 선택 팝업에서 N번째(0-based) 행의 사업장 선택"""
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
