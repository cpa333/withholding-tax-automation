"""근로복지공단(고용보험) EDI 자동화 공통 함수 모듈

total.comwel.or.kr (w2 프레임워크 SPA) 제어용. 라이브 검증(2026-07) 기반.

하위 모듈 분할:
- _constants.py:  상수 (URL, 엘리먼트 id, 타임아웃)
- _workplace.py:  사업장(관리번호) 검색/선택
- _download.py:   고용보험료 지원금 정보 인쇄물 다운로드

핵심 특성 (라이브 확인):
- 로그인 전후로 URL 고정(https://total.comwel.or.kr/) → 로그인 감지는
  btnLogin/guestView 가시 요소 사라짐으로 판별.
- 실무 메뉴는 상단 GNB(정보조회→보험료정보조회→20209). 진입 후 메뉴를 다시
  클릭해 접어야 화면 가시성 확보(사용자 UX 가이드).
- 사업장 선택은 '사업장조회' 버튼 → WZ0101_P01 팝업 → 관리번호 자동채움 →
  조회 → 결과 행 '선택' 버튼 클릭.
- '인쇄하기' 버튼 id(wq_uuid_XXXX)는 동적 → 텍스트 매칭 + 팝업 범위로 클릭.
- '인쇄하기' 클릭 시 새 창(리포트 뷰어)이 열림 → CDP 세션 끊김 주의.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from src.utils.chrome_cdp import launch_chrome, CDP_URL
from src.utils.log import log
from src.utils.human import human_delay

# ─── 상수 재export ───────────────────────────────────────────────────────────
from src.automation.comwel._constants import (
    COMWEL_URL, COMWEL_MAIN,
    MENU_INFO_INQUIRY_ID, MENU_PREMIUM_INQUIRY_ID, MENU_PREMIUM_20209_ID,
    QUICKMENU_20209_ID,
    INPUT_MGMT_NO_ID, BTN_WORKPLACE_SEARCH_ID,
    SELECT_YEAR_ID, SELECT_MONTH_ID,
    POPUP_WORKPLACE_ID, POPUP_WORKPLACE_CLOSE_ID,
    POPUP_WORKPLACE_MGMT_NO_ID, POPUP_WORKPLACE_SEARCH_BTN_ID,
    POPUP_WORKPLACE_SELECT_BTN_PREFIX, WORKPLACE_GRID_ROW_CLASS,
    TAB_SANJEONG_ID, TAB_EMPLOYMENT_ID, BTN_SUPPORT_INFO_ID,
    POPUP_SUPPORT_ID, POPUP_SUPPORT_CLOSE_ID,
    BTN_PRINT_TEXT, BTN_EXCEL_TEXT,
    PRELOGIN_BTN_LOGIN_ID, PRELOGIN_GUEST_VIEW_ID,
    SAMU_POPUP_CLOSE_ID,
    BTN_INQUIRY,
    LOGIN_TIMEOUT_S, PAGE_LOAD_TIMEOUT_MS, DOWNLOAD_TIMEOUT_S,
    MENU_NAV_DELAY_S, POPUP_TIMEOUT_S, WORKPLACE_SEARCH_DELAY_S,
    PRINT_CLICK_RETRIES,
)

# ─── 사업장 선택 재export ────────────────────────────────────────────────────
from src.automation.comwel._workplace import (
    switch_workplace,
    select_workplace,
    reset_workplace_page,
)

# ─── 다운로드 재export ────────────────────────────────────────────────────────
from src.automation.comwel._download import (
    download_support_info_printout,
)


# ─── 연결/로그인 ────────────────────────────────────────────────────────────

async def connect_page(playwright, *, url: str = CDP_URL):
    """CDP로 Chrome에 연결하고 근로복지공단 EDI 탭 우선 반환."""
    from src.utils.stealth import stealth_all_pages, register_auto_stealth

    browser = await playwright.chromium.connect_over_cdp(url)
    context = browser.contexts[0]

    await stealth_all_pages(context)
    register_auto_stealth(context)

    for pg in context.pages:
        try:
            if "total.comwel.or.kr" in pg.url:
                return browser, context, pg
        except Exception:
            continue

    page = context.pages[0] if context.pages else await context.new_page()
    return browser, context, page


async def wait_for_login(page):
    """근로복지공단 EDI 로그인 완료 대기 (수동 공동인증서 로그인).

    URL 이 고정되므로 로그인 전용 가시 요소(btnLogin/guestView)가 DOM 에서
    사라지면 로그인 완료로 판정. (라이브 검증)
    """
    async def _pre_login_visible(p) -> bool:
        try:
            return await p.evaluate(r"""(ids) => {
                for (const id of ids) {
                    const el = document.getElementById(id);
                    if (el) {
                        const r = el.getBoundingClientRect();
                        if (r.width > 0 && r.height > 0) return true;
                    }
                }
                return false;
            }""", [PRELOGIN_BTN_LOGIN_ID, PRELOGIN_GUEST_VIEW_ID])
        except Exception:
            return True  # evaluate 실패 시 안전하게 대기 유지

    if not await _pre_login_visible(page):
        log("이미 로그인되어 있습니다.")
        return True

    log("\n브라우저에서 근로복지공단(고용보험) EDI 로그인을 진행해 주세요.")
    log("사무대행(151-86-01316) 공동인증서로 로그인 후 자동으로 감지됩니다.")

    for i in range(LOGIN_TIMEOUT_S // 5):
        await asyncio.sleep(5)
        try:
            if not await _pre_login_visible(page):
                log("로그인 확인됨.")
                return True
        except Exception:
            pass
        if i % 6 == 5:
            log(f"  로그인 대기 중... ({(i + 1) * 5}초)")

    log("로그인 대기 시간 초과 (15분).")
    return False


async def close_samu_popup(page):
    """로그인 후 '사무대행기관 정보 확인' 팝업 닫기 (라이브 검증).

    로그인 직후 samuInfoPopup 이 화면을 가리므로 자동화 전 닫아야 함.
    이미 닫혀 있으면 no-op.
    """
    closed = await page.evaluate(r"""(id) => {
        const el = document.getElementById(id);
        if (!el) return false;
        const r = el.getBoundingClientRect();
        if (r.width === 0) return false;
        el.click();
        return true;
    }""", SAMU_POPUP_CLOSE_ID)
    if closed:
        log("  사무대행 안내 팝업 닫기")
        await asyncio.sleep(1)
    return closed


async def wait_for_workplace_ready(page, max_wait: int = POPUP_TIMEOUT_S):
    """페이지 로딩 완료 대기 (간단 버전)."""
    for _ in range(max_wait):
        try:
            ready = await page.evaluate("""() => document.readyState === 'complete'""")
            if ready:
                return True
        except Exception:
            pass
        await asyncio.sleep(1)
    return False


async def dismiss_dialogs(page):
    """열린 모달/팝업 닫기 (보조). 사무대행 팝업도 함께 처리."""
    await close_samu_popup(page)
    await asyncio.sleep(0.3)


# ─── 메뉴 이동 헬퍼 (라이브 검증 id 기반) ─────────────────────────────────────

async def _click_by_id(page, element_id: str) -> bool:
    """id로 가시 요소 클릭."""
    return await page.evaluate(r"""(id) => {
        const el = document.getElementById(id);
        if (!el) return false;
        const r = el.getBoundingClientRect();
        if (r.width === 0 && r.height === 0) return false;
        el.click();
        return true;
    }""", element_id)


async def navigate_to_premium_20209(page):
    """부과고지 보험료 조회(20209) 화면으로 진입 (엑셀 E95~E97).

    메인 대시보드에서 퀵메뉴로 20209 진입이 가장 빠르고 안정적(라이브 검증).
    흐름: 메인 대시보드 → '조회/부과고지 보험료 조회' 퀵메뉴 클릭.

    Returns:
        bool: 20209 화면 진입 성공 여부.
    """
    log("[COMWEL] 부과고지 보험료 조회(20209) 진입...")
    # 퀵메뉴(본문)로 진입 시도 — 메인 대시보드에 있을 때 동작
    ok = await _click_by_id(page, QUICKMENU_20209_ID)
    if ok:
        log("  20209 퀵메뉴 클릭")
        await asyncio.sleep(MENU_NAV_DELAY_S + 1)
        await dismiss_dialogs(page)
        return True

    # 퀵메뉴 없으면(이미 다른 화면) GNB 메뉴 경로로 진입
    log("  퀵메뉴 없음 — GNB 메뉴 경로 시도")
    # 1단계: 정보조회 (펼침)
    await _click_by_id(page, MENU_INFO_INQUIRY_ID)
    await asyncio.sleep(MENU_NAV_DELAY_S)
    # 2단계: 보험료정보 조회
    await _click_by_id(page, MENU_PREMIUM_INQUIRY_ID)
    await asyncio.sleep(MENU_NAV_DELAY_S)
    # 3단계: 부과고지 보험료 조회(20209)
    ok = await _click_by_id(page, MENU_PREMIUM_20209_ID)
    await asyncio.sleep(MENU_NAV_DELAY_S + 1)
    await dismiss_dialogs(page)
    return ok


async def collapse_gnb_menu(page):
    """GNB '정보조회' 메뉴 접기 (사용자 UX 가이드 — 진입 후 메뉴 접음).

    정보조회 1단계 메뉴를 다시 클릭하면 토글로 서브메뉴가 접힘(arrow-up→down).
    화면 가시성 확보 목적. 실패해도 치명적이지 않음.
    """
    collapsed = await page.evaluate(r"""(id) => {
        const el = document.getElementById(id);
        if (!el) return false;
        // 펼쳐진 상태(arrow-up)일 때만 클릭해서 접기
        if (!/arrow-up/.test(el.className || '')) return false;
        el.click();
        return true;
    }""", MENU_INFO_INQUIRY_ID)
    if collapsed:
        log("  GNB 정보조회 메뉴 접기")
        await asyncio.sleep(MENU_NAV_DELAY_S)
    return collapsed


# 레거시 호환용 별칭 (기존 navigate_to_support_info 호출 호환)
async def navigate_to_support_info(page):
    """navigate_to_premium_20209 의 별칭 (레거시 호환)."""
    ok = await navigate_to_premium_20209(page)
    await collapse_gnb_menu(page)
    return ok


# ─── 연월 설정 헬퍼 ──────────────────────────────────────────────────────────

async def set_period(page, year: int, month: int) -> bool:
    """부과년도/부과월 select 설정 (라이브 검증).

    selectbox 의 value 형식: 연도="2026 년", 월="06 월" (공백+한자/월 포함).
    w2 프레임워크 select 는 native select.value 변경 + change 이벤트로 동작.
    """
    year_val = f"{year} 년"
    month_val = f"{month:02d} 월"
    log(f"[COMWEL] 부과기간 설정: {year}년 {month:02d}월")

    result = await page.evaluate(r"""(args) => {
        const out = {};
        // 연도
        const ySel = document.getElementById(args.yearId);
        if (ySel) {
            const yOpt = Array.from(ySel.options).find(o => o.text.trim() === args.yearVal || o.value.trim() === args.yearVal);
            if (yOpt) { ySel.value = yOpt.value; ySel.dispatchEvent(new Event("change", {bubbles:true})); out.year = yOpt.value; }
            else { out.year = null; }
        }
        // 월
        const mSel = document.getElementById(args.monthId);
        if (mSel) {
            const mOpt = Array.from(mSel.options).find(o => o.text.trim() === args.monthVal || o.value.trim() === args.monthVal);
            if (mOpt) { mSel.value = mOpt.value; mSel.dispatchEvent(new Event("change", {bubbles:true})); out.month = mOpt.value; }
            else { out.month = null; }
        }
        return out;
    }""", {"yearId": SELECT_YEAR_ID, "monthId": SELECT_MONTH_ID,
            "yearVal": year_val, "monthVal": month_val})

    if result.get("year") is None or result.get("month") is None:
        log(f"  ⚠ 연월 설정 실패: year={result.get('year')!r} month={result.get('month')!r}")
        return False
    return True
