"""국민건강보험 EDI 자동화 공통 함수 모듈

edi.nhis.or.kr 법인 계정(업무대행) 사이트 제어를 위한 유틸리티.
모든 NHIS EDI 자동화 플로우에서 공유.
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from src.utils.chrome_cdp import launch_chrome, CDP_URL

NHIS_EDI_URL = "https://edi.nhis.or.kr/"
NHIS_EDI_MAIN = "https://edi.nhis.or.kr/homeapp/wep/m/retrieveMain.xx"
FIRM_LIST_URL = "retrieveFirmList.do"


def log(msg):
    print(msg, flush=True)


async def connect_page(playwright):
    """CDP로 Chrome에 연결하고 NHIS EDI 탭 우선 반환"""
    browser = await playwright.chromium.connect_over_cdp(CDP_URL)
    context = browser.contexts[0]

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
    """메인 페이지 제외 모든 팝업/공지사항 탭 닫기"""
    main_page = None
    for pg in context.pages:
        if "retrieveMain" in pg.url:
            main_page = pg
            break
    if not main_page:
        main_page = context.pages[0]

    closed = 0
    for pg in context.pages[:]:
        if pg != main_page:
            try:
                await pg.close()
                closed += 1
            except Exception:
                pass
    if closed:
        log(f"  팝업 {closed}개 닫음")
    return main_page


# ═══════════════════════════════════════════════════════════════════════════════
# 수임사업장 선택
# ═══════════════════════════════════════════════════════════════════════════════

async def open_firm_selector(page, context):
    """수임사업장선택 버튼 클릭 → 팝업 탭 반환

    메인 페이지의 수임사업장선택 이미지 버튼(img[src*=we_btn_suim]) 클릭.
    새 탭으로 사업장 목록 팝업이 열림.

    Returns:
        Page or None: 사업장 선택 팝업 탭
    """
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
    await asyncio.sleep(2)

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

    # 검색 유형 선택
    await popup.evaluate("""(args) => {
        const sel = document.getElementById('srchType');
        if (sel) {
            for (const opt of sel.options) {
                if (opt.text.trim() === args.typeValue) {
                    sel.value = opt.value;
                    break;
                }
            }
        }
    }""", {"typeValue": type_value})

    # 검색어 입력
    await popup.evaluate("""(args) => {
        const input = document.getElementById('srchText');
        if (input) {
            input.value = args.keyword;
            input.dispatchEvent(new Event('input', {bubbles: true}));
            input.dispatchEvent(new Event('change', {bubbles: true}));
        }
    }""", {"keyword": keyword})

    # 폼 제출
    await popup.evaluate("""() => {
        document.getElementById('cPage').value = '1';
        document.getElementById('btnSubmit').click();
    }""")
    await asyncio.sleep(3)

    return (await _parse_current_page_firms(popup))["firms"]


async def select_firm(popup, firm_name):
    """사업장 선택 팝업에서 특정 사업장 선택

    현재 목록에서 먼저 찾고, 없으면 검색으로 찾기.

    Args:
        popup: 사업장 선택 팝업 탭
        firm_name: 선택할 사업장명 (부분 매칭)

    Returns:
        bool: 선택 성공 여부
    """
    log(f"  사업장 검색: '{firm_name}'")

    # 1페이지로 리셋 후 전체 목록에서 찾기
    await popup.evaluate('() => { fn_next("1"); }')
    await asyncio.sleep(2)

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
