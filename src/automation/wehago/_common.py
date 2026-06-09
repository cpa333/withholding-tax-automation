"""WEHAGO 자동화 공통 함수 모듈

모든 자동화 플로우(SWSA0101, SWTA0101, SWER0101)에서 공유하는 함수들.
"""
import asyncio
import os
import re
import sys
from datetime import datetime

# PROJECT_ROOT to sys.path for src.* imports
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from src.utils.chrome_cdp import CDP_URL
from src.utils.log import log
from src.config import WEHAGO_URL, WEHAGO_TAXAGENT_URL


async def _safe_evaluate(page, expression, *args, timeout=10):
    """page.evaluate with timeout guard. Returns None on timeout/error."""
    try:
        return await asyncio.wait_for(page.evaluate(expression, *args), timeout=timeout)
    except (asyncio.TimeoutError, Exception) as e:
        msg = str(e).lower()
        # 브라우저 종료 관련 에러는 조용히 무시 (상위 핸들러가 처리)
        _browser_closed = any(kw in msg for kw in (
            "target closed", "browser", "disconnected",
            "connection closed", "context was destroyed",
        ))
        if not _browser_closed:
            log(f"  page.evaluate 오류: {type(e).__name__}")
        return None


# ═══════════════════════════════════════════════════════════════════════
# 기간 계산
# ═══════════════════════════════════════════════════════════════════════

def compute_target_period():
    """현재 기준 저번달 (year, month) 반환. 1월이면 전년 12월."""
    now = datetime.now()
    if now.month == 1:
        return now.year - 1, 12
    return now.year, now.month - 1


# ═══════════════════════════════════════════════════════════════════════
# 모달/다이얼로그 처리
# ═══════════════════════════════════════════════════════════════════════

async def dismiss_dialogs(page):
    """표시 중인 팝업/다이얼로그가 있으면 모두 닫기

    z-index가 가장 높은 모달부터 처리 (비과세 등 상위 모달이 하위 클릭을 가리는 문제 방지).
    비과세 모달은 취소 우선, 나머지는 닫기 → X → 확인 → 취소 순.
    """
    for _ in range(20):
        # AI 브리핑 팝업 우선 처리 (z-index/버튼 기준에 맞지 않을 수 있으므로 별도 처리)
        await dismiss_ai_briefing_popup(page)

        closed = await page.evaluate("""() => {
            // z-index 내림차순으로 정렬하여 가장 위에 있는 모달부터 처리
            const candidates = [];
            const all = document.querySelectorAll('*');
            for (const el of all) {
                try {
                    const cs = window.getComputedStyle(el);
                    if (cs.display === 'none' || cs.visibility === 'hidden'
                        || el.offsetWidth < 50) continue;
                    const z = parseInt(cs.zIndex);
                    if (isNaN(z) || z < 1000) continue;
                    if (cs.position !== 'fixed' && cs.position !== 'absolute') continue;
                    if (el.classList.contains('WSC_LUXSnackbar')) continue;
                    const txt = el.textContent.trim();
                    // Canvas fallback 텍스트만 있는 요소 제외
                    const clean = txt.replace(/Your browser does not support HTML5 Canvas\\./g, '').trim();
                    if (clean.length === 0) continue;
                    // 버튼이 있는지 확인
                    const hasBtn = el.querySelectorAll('button').length > 0;
                    if (!hasBtn) continue;
                    candidates.push({el, z, txt: clean});
                } catch(e) {}
            }
            candidates.sort((a, b) => {
                // 비과세 모달 최우선
                const aNT = a.txt.includes('비과세') ? 1 : 0;
                const bNT = b.txt.includes('비과세') ? 1 : 0;
                if (aNT !== bNT) return bNT - aNT;
                return b.z - a.z;
            });

            const target = candidates.length > 0 ? candidates[0] : null;
            if (!target) return null;

            const btns = target.el.querySelectorAll('button, a');
            const text = target.txt;

            // 비과세 모달: 취소 우선
            if (text.includes('비과세')) {
                for (const btn of btns) {
                    const t = btn.textContent.trim();
                    if ((t === '취소' || t.startsWith('취소')) && btn.offsetWidth > 0) {
                        btn.click(); return '비과세→취소';
                    }
                }
            }

            // 닫기 버튼 (닫기, 닫기(Esc))
            for (const btn of btns) {
                const t = btn.textContent.trim();
                if (t.startsWith('닫기') && btn.offsetWidth > 0) { btn.click(); return '닫기'; }
            }
            // 수당 및 공제등록 모달: display:none으로 강제 숨김
            // (z:1100 오버레이가 X 버튼을 덮어 JS/mouse click 불가)
            if (text.includes('수당 및 공제등록') || text.includes('수당 및 공제 등록')) {
                target.el.style.display = 'none';
                // z:1100 검은 오버레이도 함께 숨김
                const siblings = target.el.parentElement?.children;
                if (siblings) {
                    for (const sib of siblings) {
                        const scs = window.getComputedStyle(sib);
                        if (scs.position === 'fixed' && parseInt(scs.zIndex) === 1100) {
                            sib.style.display = 'none';
                        }
                    }
                }
                return '수당공제→force-hide';
            }
            // 확인 버튼 (간이세액 등)
            for (const btn of btns) {
                if (btn.textContent.trim() === '확인' && btn.offsetWidth > 0) {
                    btn.click(); return '확인';
                }
            }
            // X 버튼 (일반)
            const luxBtns = target.el.querySelectorAll('button.WSC_LUXButton');
            for (const btn of luxBtns) {
                if (!btn.textContent.trim() && btn.offsetWidth > 0) { btn.click(); return 'X'; }
            }
            // 취소 버튼
            for (const btn of btns) {
                if (btn.textContent.trim() === '취소') { btn.click(); return '취소'; }
            }
            return 'stuck';
        }""")
        if not closed:
            return
        log(f"  팝업 닫음 ({closed})")
        await asyncio.sleep(0.5)


async def dismiss_ai_briefing_popup(page):
    """WEHAGO 메인 팝업 닫기 (AI 에디션 프로모션, 2차 인증 등)

    실제 팝업 구조:
      - ._isDialog.WSC_LUXDialog (AI 에디션 프로모션) → button.btn_close
      - .LUX_basic_dialog (2차 인증) → button.btn_close
      - .dimmed 오버레이 (z-index: 1100) 배경
    기존 ai-briefing-popover 셀렉터는 실제 DOM에 존재하지 않아 매칭 실패했음.
    """
    closed = await page.evaluate(r"""() => {
        let dismissed = [];

        // 1) WSC_LUXDialog / LUX_basic_dialog 닫기 버튼 클릭
        const dialogSelectors = [
            '._isDialog button.btn_close',
            '._isDialog.WSC_LUXDialog button.btn_close',
            '.LUX_basic_dialog button.btn_close',
            '.LUX_basic_dialog button.qa_popupClose',
        ];
        for (const sel of dialogSelectors) {
            const btns = document.querySelectorAll(sel);
            for (const btn of btns) {
                if (btn.offsetWidth > 0) {
                    btn.click();
                    dismissed.push('dialog-close:' + sel);
                }
            }
        }

        // 2) aiOpenPop* 래퍼 강제 숨김 (닫기 버튼으로 안 닫히는 경우)
        document.querySelectorAll('[class*="aiOpenPop"]').forEach(el => {
            if (el.offsetWidth > 0) {
                el.style.display = 'none';
                dismissed.push('aiOpenPop-hide');
            }
        });

        // 3) dimmed 오버레이 숨김
        document.querySelectorAll('.dimmed').forEach(el => {
            const cs = window.getComputedStyle(el);
            if (parseInt(cs.zIndex) >= 1000 && el.offsetWidth > 0) {
                el.style.display = 'none';
                dismissed.push('dimmed-hide');
            }
        });

        // 4) 기존 ai-briefing-popover도 유지 (미래 호환성)
        const oldSelectors = [
            '[class*="ai-briefing-popover"] button[class*="close"]',
            '[class*="ai-briefing-popover"] button[aria-label="close"]',
            '[id*="T_MAIN_LAUNCH_PROMO_DIALOG"] button',
        ];
        for (const sel of oldSelectors) {
            const btn = document.querySelector(sel);
            if (btn && btn.offsetWidth > 0) {
                btn.click();
                dismissed.push('legacy-close:' + sel);
            }
        }

        return dismissed.length > 0 ? dismissed.join(', ') : false;
    }""")
    if closed:
        log(f"  WEHAGO 팝업 닫음 ({closed})")
        await asyncio.sleep(0.5)


async def close_warning_overlay(page, keyword):
    """특정 키워드가 포함된 z-index 고정 오버레이에서 확인 버튼 클릭"""
    return await page.evaluate("""(kw) => {
        const all = document.querySelectorAll('*');
        for (const el of all) {
            const cs = window.getComputedStyle(el);
            if (cs.position !== 'fixed' || cs.display === 'none'
                || parseInt(cs.zIndex) < 1000) continue;
            if (!el.textContent.includes(kw)) continue;
            const btns = el.querySelectorAll('button');
            for (const btn of btns) {
                if (btn.textContent.trim() === '확인' && btn.offsetWidth > 0) {
                    btn.click(); return true;
                }
            }
        }
        return false;
    }""", keyword)


async def click_codehelp_confirm(page):
    """iframe 포함 코드도움 모달에서 확인(enter) 클릭"""
    for frame in page.frames:
        try:
            result = await frame.evaluate("""() => {
                const all = document.querySelectorAll('*');
                for (const el of all) {
                    try {
                        const cs = window.getComputedStyle(el);
                        const z = parseInt(cs.zIndex) || 0;
                        if (z < 1000 || cs.display === 'none' || el.offsetWidth < 100) continue;
                        if (!el.textContent.includes('코드도움')) continue;
                        const btns = el.querySelectorAll('button');
                        for (const btn of btns) {
                            if (btn.textContent.trim() === '확인(enter)' && btn.offsetWidth > 0) {
                                btn.click(); return true;
                            }
                        }
                    } catch(e) {}
                }
                return false;
            }""")
            if result:
                return True
        except Exception:
            pass
    return False


async def click_dialog_button(page, button_text):
    """현재 떠 있는 모달/다이얼로그에서 지정된 텍스트의 버튼 클릭"""
    await page.evaluate("""(btnText) => {
        const selectors = ['._isDialog', '.LUX_basic_dialog'];
        let target = null;
        for (const sel of selectors) {
            for (const d of document.querySelectorAll(sel)) {
                if (d.style.display !== 'none') { target = d; break; }
            }
            if (target) break;
        }
        if (!target) return;
        const btns = target.querySelectorAll('button, a');
        for (const b of btns) {
            if (b.textContent.trim().includes(btnText)) { b.click(); return; }
        }
    }""", button_text)
    await asyncio.sleep(1)
    log(f"  모달 버튼 클릭: {button_text}")


async def _click_modal_text(page, text_fragment, action):
    """특정 텍스트가 포함된 모달에서 action(확인/취소) 버튼 클릭"""
    for _ in range(20):
        result = await page.evaluate("""(args) => {
            const all = document.querySelectorAll('*');
            for (const el of all) {
                if (!el.textContent.includes(args.fragment)) continue;
                const btns = el.querySelectorAll('button');
                for (const btn of btns) {
                    if (btn.textContent.trim() === args.action && btn.offsetWidth > 0) {
                        btn.click();
                        return args.action;
                    }
                }
            }
            return null;
        }""", {"fragment": text_fragment, "action": action})
        if result:
            return True
        await asyncio.sleep(0.5)
    return False


# ═══════════════════════════════════════════════════════════════════════
# 페이지 네비게이션
# ═══════════════════════════════════════════════════════════════════════

async def goto_menu_page(page, menu_id):
    """SmartA 내 다른 메뉴 페이지로 이동 (URL 해시 교체)

    2단계 폴백: /smarta/humanresource/{MENU_ID} 우선, 실패 시 /{MENU_ID}
    """
    current_url = page.url
    new_url = re.sub(
        r'/smarta/humanresource/[A-Z]+\d+(?=[?#]|$)',
        f'/smarta/humanresource/{menu_id}', current_url
    )
    if new_url == current_url:
        new_url = re.sub(r'/[A-Z]+\d+(?=[?#]|$)', f'/{menu_id}', current_url)
    if new_url == current_url:
        log(f"  URL 교체 실패: {menu_id}")
        return False
    log(f"  메뉴 이동: {menu_id}")
    await page.goto(new_url, wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(2)
    log(f"  이동 완료: {await page.title()}")
    return True


async def click_menu(page, menu_id):
    """SmartA 사이드 메뉴 클릭 (SPA 내부 라우팅)"""
    await page.evaluate("""(menuId) => {
        const link = document.querySelector('a#' + menuId + '.text_link');
        if (link) link.click();
    }""", menu_id)
    await asyncio.sleep(3)
    log(f"  메뉴 이동 완료: {await page.title()}")


async def wait_for_login(page):
    """WEHAGO 로그인 완료 대기 (수동 로그인)

    초기 30초는 DOM만 확인(새로고침 없이 로그인 진행 방해하지 않음),
    이후 15초 간격으로 DOM 확인 + 45초마다 새로고침.
    총 최대 15분 대기.
    """
    await page.goto(WEHAGO_URL + "#/main", wait_until="domcontentloaded")
    await asyncio.sleep(3)

    if await page.locator("#company_").count() > 0 or await page.locator("text=나의 수임처").count() > 0:
        log("이미 로그인되어 있습니다.")
        return True

    log("\n브라우저에서 WEHAGO 로그인을 진행해 주세요.")
    log("로그인 완료 후 자동으로 감지됩니다. (터미널에서 키 입력하지 마세요)")

    # 초기 30초: 새로고침 없이 DOM만 조용히 확인
    log("  로그인 대기 중...")
    for _ in range(6):
        await asyncio.sleep(5)
        try:
            if await page.locator("text=나의 수임처").count() > 0:
                log("로그인 확인됨.")
                return True
        except Exception:
            pass

    # 이후: 15초 간격 DOM 확인, 45초마다 새로고침
    for i in range(52):
        await asyncio.sleep(15)
        try:
            if await page.locator("text=나의 수임처").count() > 0:
                log("로그인 확인됨.")
                return True
            # 3회마다(=45초마다) 새로고침
            if i % 3 == 2:
                await page.reload(wait_until="domcontentloaded")
                await asyncio.sleep(3)
                if await page.locator("text=나의 수임처").count() > 0:
                    log("로그인 확인됨.")
                    return True
        except Exception:
            pass

    log("로그인 대기 시간 초과 (15분).")
    return False


async def ensure_full_tab(page):
    """WEHAGO 메인 수임처 탭이 '전체'인지 확인 후, 아니면 '전체' 탭 클릭"""
    is_active = await page.evaluate("""() => {
        const tabs = document.querySelectorAll('ul.main_tab_bx > li');
        for (const li of tabs) {
            if (li.textContent.trim() === '전체') {
                return li.classList.contains('active');
            }
        }
        return null;  // 탭 자체를 못 찾음
    }""")

    if is_active is None:
        log("  '전체' 탭을 찾을 수 없습니다 (메인 페이지가 아닐 수 있음)")
        return
    if is_active:
        log("  '전체' 탭 확인됨")
        return

    log("  '전체' 탭으로 전환...")
    await page.evaluate("""() => {
        const tabs = document.querySelectorAll('ul.main_tab_bx > li');
        for (const li of tabs) {
            if (li.textContent.trim() === '전체') {
                const btn = li.querySelector('button');
                if (btn) btn.click();
                return;
            }
        }
    }""")
    await asyncio.sleep(2)
    log("  '전체' 탭 전환 완료")


async def search_companies(page, keyword):
    """키워드로 수임처 검색. 부분 매칭 결과 목록 반환.

    Returns:
        list[str]: 매칭된 수임처 이름 목록 (빈 리스트면 결과 없음)
    """
    results = await page.evaluate("""(kw) => {
        const matches = [];
        const seen = new Set();
        const allDivs = document.querySelectorAll('[id^="company_"]');
        for (const div of allDivs) {
            const nameEl = div.querySelector('a');
            if (!nameEl) continue;
            const name = nameEl.textContent.trim();
            if (!name.includes(kw)) continue;
            if (seen.has(name)) continue;
            seen.add(name);
            matches.push(name);
        }
        return matches;
    }""", keyword)
    return results or []


async def goto_client_management(page):
    """메인 페이지에서 '수임처관리' 버튼 클릭하여 전체 수임처 목록 페이지로 이동.

    '담당 수임처' 텍스트 근처의 '수임처관리' 링크/버튼을 찾아 클릭.
    """
    # 현재 페이지 URL 로깅
    current_url = page.url
    log(f"  현재 URL: {current_url}")

    # 페이지에 있는 텍스트 디버깅
    debug_info = await page.evaluate("""() => {
        const info = {buttons: [], links: [], cardCount: 0, nameTextCount: 0};

        // 모든 버튼/링크에서 '수임처' 포함 텍스트 수집
        document.querySelectorAll('a, button').forEach(el => {
            const t = el.textContent.trim();
            if (t.includes('수임처') || t.includes('관리')) {
                info.buttons.push({tag: el.tagName, text: t.substring(0, 50), href: el.href || ''});
            }
        });

        // 카드/이름 요소 개수
        info.cardCount = document.querySelectorAll('li[id^="card"]').length;
        info.nameTextCount = document.querySelectorAll('span.company_name_text').length;
        info.companyDivCount = document.querySelectorAll('[id^="company_"]').length;

        return info;
    }""")
    log(f"  디버그: 버튼/링크={debug_info.get('buttons', [])}")
    log(f"  디버그: card={debug_info.get('cardCount')}, name_text={debug_info.get('nameTextCount')}, company_div={debug_info.get('companyDivCount')}")

    # 이미 수임처관리 페이지에 있는지 확인
    if debug_info.get('cardCount', 0) > 0:
        log("  이미 수임처관리 페이지에 있습니다.")
        return True

    # "수임처관리" 클릭 시도 — 여러 방식으로
    clicked = await page.evaluate("""() => {
        // 1) 정확히 "수임처관리" 텍스트
        const allElements = document.querySelectorAll('a, button, span');
        for (const el of allElements) {
            const text = el.textContent.trim();
            if (text === '수임처관리' || text === '수임처 관리' || text === '수임처 관리 ') {
                el.click();
                return 'exact: ' + text;
            }
        }

        // 2) "수임처관리"를 포함하는 요소
        for (const el of allElements) {
            const text = el.textContent.trim();
            if (text.includes('수임처관리') && text.length < 20) {
                el.click();
                return 'contains: ' + text;
            }
        }

        // 3) "담당 수임처" 근처에서 찾기
        const headings = document.querySelectorAll('h2, h3, h4, .title, [class*="title"]');
        for (const h of headings) {
            if (h.textContent.includes('담당 수임처') || h.textContent.includes('수임처')) {
                const parent = h.parentElement;
                if (parent) {
                    const link = parent.querySelector('a, button');
                    if (link) {
                        link.click();
                        return 'near_title: ' + link.textContent.trim();
                    }
                }
            }
        }

        return false;
    }""")

    if not clicked:
        log("  '수임처관리' 버튼을 찾지 못했습니다.")
        return False

    log(f"  '수임처관리' 클릭 성공 ({clicked}) → 로딩 대기...")
    await asyncio.sleep(3)

    # 이동 후 확인
    after_info = await page.evaluate("""() => ({
        url: location.href,
        cardCount: document.querySelectorAll('li[id^="card"]').length,
        nameTextCount: document.querySelectorAll('span.company_name_text').length,
    })""")
    log(f"  이동 후: url={after_info['url']}, card={after_info['cardCount']}, name_text={after_info['nameTextCount']}")

    return True


async def get_all_clients_from_management(page):
    """수임처관리 페이지에서 전체 수임처 목록 스크래핑.

    HTML 구조: <ul class="acceptance_list"> 안의 <li>에서 수임처명.
    리스트는 div.cl_lnb_bottom 스크롤 컨테이너 안에 있어서
    컨테이너를 끝까지 스크롤해야 전체 항목이 로드됨.
    """
    # 1) 스크롤 컨테이너를 끝까지 스크롤하여 모든 항목 로드
    for _ in range(10):
        count = await page.evaluate("""() => {
            const container = document.querySelector('div.cl_lnb_bottom');
            if (!container) return 0;
            container.scrollTop = container.scrollHeight;
            const lists = container.querySelectorAll('ul.acceptance_list');
            let total = 0;
            for (const ul of lists) {
                total += ul.querySelectorAll(':scope > li').length;
            }
            return total;
        }""")
        await asyncio.sleep(0.5)

    # 2) 로드된 전체 항목에서 이름 수집
    names = await page.evaluate("""() => {
        const allLists = document.querySelectorAll('ul.acceptance_list');
        for (const list of allLists) {
            const items = list.querySelectorAll(':scope > li');
            if (items.length === 0) continue;
            const results = [];
            for (const item of items) {
                const nameEl = item.querySelector('span.company_name_text');
                if (!nameEl) continue;
                const name = nameEl.textContent.trim();
                if (name) results.push(name);
            }
            return results;
        }
        return [];
    }""")

    log(f"  수임처 스크랩 완료: 총 {len(names or [])}건")
    return names or []


async def search_clients_by_name(page, name: str):
    """수임처관리 페이지에서 담당자 이름으로 검색.

    1) 검색 입력란에 이름 입력
    2) 조회 버튼 클릭
    3) 결과 로딩 대기
    """
    # 검색 입력란 — XPath 우선 (CSS 셀렉터는 hidden input 37개 포함하여 부정확)
    search_input = page.locator(
        'xpath=//*[@id="mainCard"]/div[2]/div/div[1]/div/span/input'
    )
    if await search_input.count() > 0:
        await search_input.first.fill("")
        await search_input.first.fill(name)
        log(f"  검색어 입력: {name}")
    else:
        # CSS fallback: visible text input
        search_input_css = page.locator('#mainCard input[type="text"]:visible')
        if await search_input_css.count() > 0:
            await search_input_css.first.fill("")
            await search_input_css.first.fill(name)
            log(f"  검색어 입력 (CSS): {name}")
        else:
            log("  검색 입력란을 찾을 수 없음 — 전체 조회로 진행")
            return

    # 조회 버튼 — XPath 우선
    search_btn = page.locator(
        'xpath=//*[@id="mainCard"]/div[1]/div[3]/button'
    )
    if await search_btn.count() > 0:
        await search_btn.first.click()
        log("  조회 버튼 클릭")
    else:
        # 텍스트 기반 fallback
        search_btn_txt = page.locator('#mainCard button').filter(has_text="조회")
        if await search_btn_txt.count() > 0:
            await search_btn_txt.first.click()
            log("  조회 버튼 클릭 (텍스트)")
        else:
            log("  조회 버튼을 찾을 수 없음 — 전체 조회로 진행")
            return

    # 결과 로딩 대기
    await asyncio.sleep(1)


async def get_clients_with_biz_from_taxagent(page):
    """taxagent에서 카드를 클릭하며 수임처명 + 사업자등록번호 수집.

    각 카드를 클릭하면 상세 영역에 사업자등록번호가 표시됨.
    전체 카드를 순회하며 이름과 사업자번호를 수집.
    """
    # 스크롤로 전체 카드 로드
    for _ in range(10):
        await _safe_evaluate(page, """() => {
            const container = document.querySelector('div.cl_lnb_bottom');
            if (container) container.scrollTop = container.scrollHeight;
        }""")
        await asyncio.sleep(0.5)

    # 카드 목록 수집
    total_cards = await _safe_evaluate(page, r'''() => {
        const allLists = document.querySelectorAll('ul.acceptance_list');
        for (const list of allLists) {
            const items = list.querySelectorAll(':scope > li');
            if (items.length === 0) continue;
            return items.length;
        }
        return 0;
    }''') or 0

    results = []
    for i in range(total_cards):
        # i번째 카드 클릭
        clicked = await _safe_evaluate(page, r'''(idx) => {
            const allLists = document.querySelectorAll('ul.acceptance_list');
            for (const list of allLists) {
                const cards = list.querySelectorAll('a.acceptance_card');
                if (cards.length === 0) continue;
                if (cards[idx]) {
                    cards[idx].click();
                    return true;
                }
            }
            return false;
        }''', i)
        if not clicked:
            continue

        await asyncio.sleep(0.5)

        # 상세 영역에서 이름과 사업자번호 추출
        info = await _safe_evaluate(page, r'''() => {
            // cl_basicinfo_section에 상세 정보 표시됨
            const infoEl = document.querySelector('.cl_basicinfo_section');
            if (!infoEl) return null;

            const text = infoEl.textContent;

            // 사업자등록번호 패턴 (XXX-XX-XXXXX)
            const bizMatch = text.match(/(\d{3}-\d{2}-\d{5})/);
            const bizNum = bizMatch ? bizMatch[1] : '';

            // 수임처명: 클릭된 li.selected의 company_name_text에서
            const selectedLi = document.querySelector('li.is_linkbtn.selected');
            let name = '';
            if (selectedLi) {
                const nameEl = selectedLi.querySelector('span.company_name_text');
                if (nameEl) name = nameEl.textContent.trim();
            }

            return {name, business_number: bizNum};
        }''')

        if info and info["name"]:
            name = info["name"].replace("[테스트] ", "")
            if name:
                results.append({
                    "name": name,
                    "business_number": info.get("business_number", ""),
                })

    log(f"  taxagent 스크랩: {len(results)}건 (이름+사업자번호)")
    return results


async def goto_salary_page(page, company_name):
    """수임처의 SmartA 급여 메인 페이지로 이동

    window.open 인터셉트 → 수임처 카드 '급여' 버튼 클릭 → URL 캡처 → page.goto
    모든 page.evaluate 호출을 _safe_evaluate로 래핑하여
    페이지 전환 중 예외가 브라우저 종료로 오인되는 것을 방지.
    """
    await _safe_evaluate(page, """() => {
        window.__capturedUrl = null;
        window.__origOpen = window.open;
        window.open = function(url) {
            window.__capturedUrl = url;
            return null;
        };
    }""")

    clicked = await _safe_evaluate(page, """(companyName) => {
        const allDivs = document.querySelectorAll('[id^="company_"]');
        for (const div of allDivs) {
            const nameEl = div.querySelector('a');
            if (nameEl && nameEl.textContent.trim() === companyName) {
                let card = div;
                for (let i = 0; i < 3; i++) card = card.parentElement;
                const buttons = card.querySelectorAll('button.btn_quick');
                for (const btn of buttons) {
                    if (btn.querySelector('span')?.textContent.trim() === '급여') {
                        btn.click(); return true;
                    }
                }
            }
        }
        return false;
    }""", company_name)

    if not clicked:
        log(f"  수임처 '{company_name}'의 급여 버튼을 찾지 못했습니다.")
        return False

    await asyncio.sleep(1)
    url = await _safe_evaluate(page, "() => window.__capturedUrl")
    await _safe_evaluate(page, "() => { window.open = window.__origOpen; }")

    if not url:
        log("  SmartA URL 캡처 실패")
        return False

    log(f"  SmartA 급여 URL: {url}")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)

    for i in range(15):
        await asyncio.sleep(2)
        if await page.locator("a.text_link").count() > 0:
            break
    else:
        log("  SmartA 페이지 로드 타임아웃")
        return False

    log(f"  페이지 이동 완료: {await page.title()}")

    # 수당 및 공제등록 모달 처리 (최대 10초 대기)
    # _safe_evaluate 사용으로 예외가 브라우저 종료로 오인되어
    # 세션이 끊기는 것을 방지
    for _ in range(5):
        try:
            await dismiss_dialogs(page)
        except Exception:
            pass  # dismiss_dialogs 내부 page.evaluate 실패 → 무시
        await asyncio.sleep(1)
        has_modal = await _safe_evaluate(page, """() => {
            const all = document.querySelectorAll('*');
            for (const el of all) {
                const cs = window.getComputedStyle(el);
                if (cs.display === 'none' || el.offsetWidth < 50) continue;
                if (parseInt(cs.zIndex) < 1000) continue;
                if (cs.position !== 'fixed' && cs.position !== 'absolute') continue;
                const txt = el.textContent;
                if (txt.includes('수당') && txt.includes('공제')) return true;
            }
            return false;
        }""", timeout=5)
        if not has_modal:
            break

    return True


# ═══════════════════════════════════════════════════════════════════════
# 드롭다운 / 메뉴
# ═══════════════════════════════════════════════════════════════════════

async def select_dropdown(page, dropdown_index, option_text):
    """커스텀 드롭다운(LS_ngh_select2)에서 옵션 선택"""
    await page.evaluate("""(idx) => {
        const dd = document.querySelectorAll('.LS_ngh_select2')[idx];
        if (dd) dd.querySelector('.LSbutton').click();
    }""", dropdown_index)
    await asyncio.sleep(1)

    await page.evaluate("""(args) => {
        const items = document.querySelectorAll('.LSselectResult li');
        for (const li of items) {
            if (li.textContent.includes(args.text)) {
                li.querySelector('a').click();
                return true;
            }
        }
        return false;
    }""", {"text": option_text})
    await asyncio.sleep(1)

    value = await page.evaluate("""(idx) => {
        const dd = document.querySelectorAll('.LS_ngh_select2')[idx];
        return dd ? dd.querySelector('.fakeinput').textContent.trim() : '';
    }""", dropdown_index)
    log(f"  드롭다운 선택: {value}")


async def open_collect_menu(page):
    """우측 끝 #collect 버튼 클릭하여 드롭다운 메뉴 열기

    항상 close → open 순서로 실행하여 토글 상태와 무관하게 열린 상태 보장.
    Playwright locator.click() 사용 (JS evaluate click은 합성 이벤트로 인식되어
    일부 페이지에서 드롭다운이 열리지 않음).
    """
    # close (토글 상태 모르므로 한 번 클릭)
    try:
        await page.locator('#collect').click(timeout=3000)
    except Exception:
        pass
    await asyncio.sleep(0.5)
    # open
    try:
        await page.locator('#collect').click(timeout=3000)
    except Exception:
        pass
    await asyncio.sleep(1)


async def close_collect_menu(page):
    """드롭다운 메뉴 닫기"""
    try:
        await page.locator('#collect').click(timeout=3000)
    except Exception:
        pass
    await asyncio.sleep(0.5)


async def click_menu_item(page, item_text):
    """sao_head_menu 드롭다운에서 특정 텍스트 항목의 a 태그 클릭"""
    return await page.evaluate("""(text) => {
        const menu = document.querySelector('.sao_head_menu');
        if (!menu) return false;
        const items = menu.querySelectorAll('li');
        for (const li of items) {
            if (li.textContent.includes(text)) {
                const a = li.querySelector('a');
                if (a) { a.click(); return true; }
                li.click();
                return true;
            }
        }
        return false;
    }""", item_text)


# ═══════════════════════════════════════════════════════════════════════
# 기간 설정
# ═══════════════════════════════════════════════════════════════════════

async def get_report_period_type(page):
    """원천징수이행상황신고서의 매월/반기 라디오 상태 반환"""
    result = await page.evaluate("""() => {
        const radios = document.querySelectorAll('input.LSinput[type=radio]');
        const monthlyRadios = [];
        for (const r of radios) {
            const label = r.closest('label')?.querySelector('.label_text')?.textContent?.trim();
            if (label === '매월' || label === '반기') {
                monthlyRadios.push({radio: r, label, checked: r.checked});
            }
        }
        const checked = monthlyRadios.find(r => r.checked);
        if (checked) return checked.label;
        const monthly = monthlyRadios.find(r => r.label === '매월');
        if (monthly) {
            monthly.radio.click();
            return '매월';
        }
        return null;
    }""")
    return result


async def set_period_fields(page, year, start_month, end_month):
    """지급기간/귀속기간 설정. JS sprite click + 드롭다운 닫기 + 3회 재시도 검증."""
    await page.evaluate("""() => {
        document.querySelectorAll('.WSC_LUXAlert').forEach(a => {
            const btn = a.querySelector('button.WSC_LUXButton');
            if (btn) btn.click();
            a.style.display = 'none';
        });
    }""")

    rects = await page.evaluate("""() => {
        const results = [];
        const items = document.querySelectorAll('#SearchMain .item');
        items.forEach((item, idx) => {
            const title = item.querySelector('.item_title, strong');
            const titleText = title ? title.textContent.trim() : '';
            if (!titleText.includes('기간')) return;
            const inputDivs = item.querySelectorAll('div[tabindex="0"]');
            const spriteBtns = item.querySelectorAll('button .WSC_LUXSpriteIcon');
            if (inputDivs.length < 4 || spriteBtns.length < 2) return;
            const entry = {idx, title: titleText, years: [], months: []};
            inputDivs.forEach((d, i) => {
                const r = d.getBoundingClientRect();
                entry.years.push({
                    i, text: d.textContent.trim(),
                    x: r.x, y: r.y, w: r.width, h: r.height
                });
            });
            spriteBtns.forEach((s, i) => {
                const btn = s.closest('button');
                const r = btn.getBoundingClientRect();
                entry.months.push({i, x: r.x, y: r.y, w: r.width, h: r.height});
            });
            results.push(entry);
        });
        return results;
    }""")

    if not rects:
        log("    WARNING: no period fields found")
        return

    for rect in rects:
        label = rect.get("title", "기간항목")
        log(f"    {label}: {year}년 {start_month:02d}월 ~ {end_month:02d}월")

        for retry in range(3):
            # 시작 연도
            if rect["years"]:
                y = rect["years"][0]
                await page.mouse.click(
                    y["x"] + y["w"] / 2, y["y"] + y["h"] / 2, click_count=3
                )
                await asyncio.sleep(0.3)
                await page.keyboard.type(str(year))
                await page.keyboard.press("Enter")
                await asyncio.sleep(0.5)

            # 시작 월: JS로 스프라이트 버튼 클릭 → 드롭다운에서 항목 선택
            if rect["months"]:
                await page.evaluate("""(args) => {
                    const item = document.querySelectorAll('#SearchMain .item')[args.idx];
                    if (!item) return;
                    const btns = item.querySelectorAll('button .WSC_LUXSpriteIcon');
                    const btn = btns[0]?.closest('button');
                    if (btn) btn.click();
                }""", {"idx": rect["idx"]})
                await asyncio.sleep(1)
                await page.evaluate("""(t) => {
                    const all = document.querySelectorAll('*');
                    for (const el of all) {
                        if (el.textContent.trim() === t && el.offsetWidth > 0 && el.offsetWidth < 200) {
                            const li = el.closest('li');
                            if (li) { li.click(); return; }
                            el.click(); return;
                        }
                    }
                }""", f"{start_month:02d}")
                await asyncio.sleep(0.3)
                # 드롭다운 닫기
                await page.evaluate("""() => {
                    document.querySelectorAll('.LSselectResult, div[style*="position: fixed"]').forEach(el => {
                        if (el.offsetWidth > 0) el.style.display = 'none';
                    });
                }""")
                await asyncio.sleep(0.3)

            # 종료 연도
            if len(rect["years"]) > 2:
                y = rect["years"][2]
                await page.mouse.click(
                    y["x"] + y["w"] / 2, y["y"] + y["h"] / 2, click_count=3
                )
                await asyncio.sleep(0.3)
                await page.keyboard.type(str(year))
                await page.keyboard.press("Enter")
                await asyncio.sleep(0.5)

            # 종료 월
            if len(rect["months"]) > 1:
                await page.evaluate("""(args) => {
                    const item = document.querySelectorAll('#SearchMain .item')[args.idx];
                    if (!item) return;
                    const btns = item.querySelectorAll('button .WSC_LUXSpriteIcon');
                    const btn = btns[1]?.closest('button');
                    if (btn) btn.click();
                }""", {"idx": rect["idx"]})
                await asyncio.sleep(1)
                await page.evaluate("""(t) => {
                    const all = document.querySelectorAll('*');
                    for (const el of all) {
                        if (el.textContent.trim() === t && el.offsetWidth > 0 && el.offsetWidth < 200) {
                            const li = el.closest('li');
                            if (li) { li.click(); return; }
                            el.click(); return;
                        }
                    }
                }""", f"{end_month:02d}")
                await asyncio.sleep(0.3)
                # 드롭다운 닫기
                await page.evaluate("""() => {
                    document.querySelectorAll('.LSselectResult, div[style*="position: fixed"]').forEach(el => {
                        if (el.offsetWidth > 0) el.style.display = 'none';
                    });
                }""")
                await asyncio.sleep(0.3)

            # 전체 값 검증
            verify = await page.evaluate("""(args) => {
                const items = document.querySelectorAll('#SearchMain .item');
                if (!items[args.idx]) return null;
                const divs = items[args.idx].querySelectorAll('div[tabindex="0"]');
                return Array.from(divs).map(d => d.textContent.trim());
            }""", {"idx": rect["idx"]})

            expected = [str(year), f"{start_month:02d}", str(year), f"{end_month:02d}"]
            if verify == expected:
                log(f"      verified: {verify}")
                break
            log(f"      mismatch (retry {retry+1}): got {verify}, expected {expected}")
            await asyncio.sleep(0.5)
        else:
            log(f"      FAILED to set period after 3 retries")


# ═══════════════════════════════════════════════════════════════════════
# 급여 워크플로우 공유 헬퍼 (Phase 4/5)
# ═══════════════════════════════════════════════════════════════════════

# WEHAGO 메인 검색 XPath (사업자등록번호)
_SEARCH_XPATH_INPUT = (
    '//*[@id="wehagoPortalMain"]/div[1]/div[3]/div/div[1]/div/div/div[1]'
    '/div[2]/div[1]/div/input'
)
_SEARCH_XPATH_BTN = (
    '//*[@id="wehagoPortalMain"]/div[1]/div[3]/div/div[1]/div/div/div[1]'
    '/div[2]/div[1]/div/button'
)


async def ensure_wehago_main(page):
    """WEHAGO 메인 페이지 확인 → 아니면 이동 + 모달 정리"""
    is_on_main = await _safe_evaluate(
        page,
        "() => document.querySelectorAll('[id^=\"company_\"]').length > 0",
    )
    if not is_on_main:
        await page.goto(
            WEHAGO_URL + "#/main",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        await asyncio.sleep(3)
        await ensure_full_tab(page)
        await dismiss_dialogs(page)
        await dismiss_ai_briefing_popup(page)


async def search_company_by_biz(page, biz_number: str) -> str | None:
    """WEHAGO 메인 검색: 사업자등록번호 → 수임처명 반환

    locator.fill 시도 → 실패 시 keyboard.type fallback.
    """
    if not biz_number:
        log("  사업자등록번호가 비어있음")
        return None

    log(f"  사업자등록번호 '{biz_number}' 검색 중...")
    await dismiss_ai_briefing_popup(page)

    try:
        input_loc = page.locator(f"xpath={_SEARCH_XPATH_INPUT}")
        await input_loc.fill(biz_number, timeout=5000, force=True)
        log("  검색어 입력 완료")
        await asyncio.sleep(0.5)

        btn_loc = page.locator(f"xpath={_SEARCH_XPATH_BTN}")
        await btn_loc.click(timeout=5000, force=True)
        log("  검색 버튼 클릭 → 결과 대기...")
        await asyncio.sleep(3)

    except Exception as e:
        log(f"  locator 조작 실패, keyboard.type으로 재시도: {e}")
        try:
            await dismiss_ai_briefing_popup(page)
            input_loc = page.locator(f"xpath={_SEARCH_XPATH_INPUT}")
            await input_loc.click(timeout=5000, force=True)
            await input_loc.fill("", force=True)
            await page.keyboard.type(biz_number, delay=50)
            await asyncio.sleep(0.5)
            btn_loc = page.locator(f"xpath={_SEARCH_XPATH_BTN}")
            await btn_loc.click(timeout=5000, force=True)
            log("  keyboard.type + force click으로 검색 완료")
            await asyncio.sleep(3)
        except Exception as e2:
            log(f"  keyboard.type 재시도도 실패: {e2}")
            return None

    # 결과 리스트에서 수임처명 찾기
    found_name = await _safe_evaluate(page, """() => {
        try {
            const cards = document.querySelectorAll('[id^="company_"]');
            for (const card of cards) {
                if (card.offsetWidth < 10) continue;
                const nameEl = card.querySelector('a');
                if (nameEl) {
                    const name = nameEl.textContent.trim();
                    if (name) return name;
                }
            }
            return null;
        } catch(e) { return null; }
    }""")

    if found_name:
        log(f"  사업자번호 '{biz_number}' → '{found_name}' 검색 완료")
    else:
        log(f"  사업자번호 '{biz_number}' 검색 결과 없음")
    return found_name


async def goto_salary_page_with_fallback(
    page, client_name: str, management_number: str = "",
) -> bool:
    """사업자번호 검색 → 수임처명 fallback → 급여 페이지 진입"""
    goto_ok = False

    biz_number = (
        management_number[:-1]
        if management_number and management_number.endswith("0")
        else management_number
    )
    if biz_number:
        try:
            found_name = await search_company_by_biz(page, biz_number)
            if found_name and await goto_salary_page(page, found_name):
                goto_ok = True
        except Exception as e:
            log(f"  사업자번호 검색 예외: {e}")

    if not goto_ok:
        try:
            log(f"  수임처명 '{client_name}'으로 직접 진입...")
            if await goto_salary_page(page, client_name):
                goto_ok = True
        except Exception as e:
            log(f"  수임처명 진입 예외: {e}")

    return goto_ok


async def navigate_to_swsa0101(page) -> bool:
    """SWSA0101 메뉴 이동 + 간이세액 모달 + 드롭다운 설정"""
    current_url = page.url
    if "SWSA0101" not in current_url:
        await click_menu(page, "SWSA0101")
        await asyncio.sleep(3)
        if "SWSA0101" not in page.url:
            await goto_menu_page(page, "SWSA0101")
            await asyncio.sleep(3)
    await dismiss_dialogs(page)

    # 간이세액 개정 안내 모달 닫기
    await _safe_evaluate(page, """() => {
        const all = document.querySelectorAll('*');
        for (const el of all) {
            const cs = window.getComputedStyle(el);
            if (cs.position !== 'fixed' || cs.display === 'none' ||
                parseInt(cs.zIndex) <= 100 || el.offsetWidth <= 100) continue;
            if (!el.textContent.includes('간이세액')) continue;
            const btns = el.querySelectorAll('button.WSC_LUXButton');
            for (const btn of btns) {
                if (!btn.textContent.trim() && btn.offsetWidth > 0) {
                    btn.click(); return;
                }
            }
        }
    }""")
    await asyncio.sleep(1)
    await dismiss_dialogs(page)

    # 구분 드롭다운 → 급여+상여
    await select_dropdown(page, 0, "급여+상여")

    # 복사후 재계산 모달 (조건부)
    await asyncio.sleep(1)
    has_modal = await _safe_evaluate(page, """() => {
        const selectors = ['._isDialog', '.LUX_basic_dialog'];
        for (const sel of selectors) {
            for (const d of document.querySelectorAll(sel)) {
                if (d.style.display !== 'none') return true;
            }
        }
        return false;
    }""")
    if has_modal:
        await click_dialog_button(page, "복사후 재계산")
        await asyncio.sleep(1)
        await click_dialog_button(page, "취소")

    return True
