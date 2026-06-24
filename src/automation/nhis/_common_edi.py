"""국민건강보험 EDI 자동화 공통 함수 모듈

edi.nhis.or.kr 법인 계정(업무대행) 사이트 제어를 위한 유틸리티.
모든 NHIS EDI 자동화 플로우에서 공유.

하위 모듈에서 분할 관리:
- _constants.py:    상수 (URL, 요소 ID, 타임아웃)
- _nexacro.py:      Nexacro 프레임워크 초기화/제어
- _firm_selector.py: 수임사업장 선택/검색/페이징
- _doc_access.py:    받은문서 열기, 서식 선택, 미리보기 탐지
- _doc_download.py:  인쇄, PDF 다운로드, 워크플로우 오케스트레이터

이 모듈은 모든 하위 모듈을 재export하여
기존 `from src.automation.nhis._common_edi import X` import를
변경 없이 유지.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from src.utils.chrome_cdp import launch_chrome, CDP_URL
from src.utils.log import log
from src.utils.human import human_delay

# ─── 상수 재export ───────────────────────────────────────────────────────────
from src.automation.nhis._constants import (
    NHIS_EDI_URL, NHIS_EDI_MAIN,
    RDO_PROG_STAT, RADIO_ITEMS, GRID_RECEIVED, CBO_DOCID, BTN_PRINT,
    FIRM_LIST_URL,
    LOGIN_TIMEOUT_S, DOCS_READY_TIMEOUT_S, PRINT_PREVIEW_TIMEOUT_S,
    PRINT_CLICK_RETRIES, CROWNIX_LOAD_TIMEOUT_S, PDF_DOWNLOAD_TIMEOUT_S,
    PAGE_STABLE_TIMEOUT_S,
)

# ─── Nexacro 재export ────────────────────────────────────────────────────────
from src.automation.nhis._nexacro import (
    wait_for_nexacro_ready,
    nexacro_set_radio,
    nexacro_dblclick_cell,
)

# ─── Nexacro 공통 유틸리티 재export ──────────────────────────────────────────
from src.utils.nexacro import (
    nexacro_click,
    nexacro_dblclick,
    nexacro_select_combo,
    nexacro_click_radio,
)

# ─── 폴링 유틸리티 재export ─────────────────────────────────────────────────
from src.utils.polling import wait_for_element, wait_for_new_tab

# ─── 수임사업장 선택 재export ────────────────────────────────────────────────
from src.automation.nhis._firm_selector import (
    open_firm_selector,
    wait_firm_selector_ready,
    _parse_current_page_firms,
    list_all_firms,
    search_firm,
    select_firm,
    select_firm_by_index,
    close_firm_popup,
)

# ─── 문서 접근 재export ──────────────────────────────────────────────────────
from src.automation.nhis._doc_access import (
    open_received_docs,
    _open_received_docs_fallback,
    select_doc_type,
    find_preview_tab,
)

# ─── 문서 다운로드 재export ──────────────────────────────────────────────────
from src.automation.nhis._doc_download import (
    download_first_doc_pdf,
    run_single_firm_workflow,
    _close_edi_tabs,
)


# ─── 연결/로그인 ────────────────────────────────────────────────────────────

async def connect_page(playwright, *, url: str = CDP_URL):
    """CDP로 Chrome에 연결하고 NHIS EDI 탭 우선 반환 (url 미지정 시 기본 포트)"""
    from src.utils.stealth import stealth_all_pages, register_auto_stealth

    browser = await playwright.chromium.connect_over_cdp(url)
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


def _logged_in_page(context):
    """context 의 어느 탭이든 메인(retrieveMain/homeapp)에 도달했으면 그 page 반환.

    NHIS EDI 는 인증서 로그인 후 메인을 새 탭/창으로 띄우거나 보안 안내
    페이지를 거치는 경우가 있어, 처음 잡아둔 단일 탭의 url 만 보면 영원히
    감지 못 해 '로그인 상태로 멈춤' 이 된다. 전체 탭을 훑어 감지한다.
    """
    for pg in context.pages:
        try:
            if "retrieveMain" in pg.url or "homeapp" in pg.url:
                return pg
        except Exception:
            continue
    return None


async def wait_for_login(page):
    """NHIS EDI 로그인 완료 대기 (수동 로그인)

    공동인증서 로그인은 사용자가 직접 수행.
    메인 페이지로 리디렉트되면 로그인 완료로 판단(전체 탭 스캔).
    """
    context = page.context

    # 이미 메인 페이지면 로그인된 상태 (어느 탭이든)
    if _logged_in_page(context):
        log("이미 로그인되어 있습니다.")
        return True

    log("\n브라우저에서 국민건강보험 EDI 로그인을 진행해 주세요.")
    log("공동인증서로 로그인 후 자동으로 감지됩니다.")

    for i in range(LOGIN_TIMEOUT_S // 5):
        await asyncio.sleep(5)
        try:
            if _logged_in_page(context):
                log("로그인 확인됨.")
                return True
        except Exception:
            pass
        if i % 6 == 5:
            log(f"  로그인 대기 중... ({(i + 1) * 5}초)")

    log(f"로그인 대기 시간 초과 ({LOGIN_TIMEOUT_S // 60}분).")
    return False


async def close_popups(context):
    """팝업/공지 탭 모두 닫고 메인만 남기기"""
    main_page = None
    for pg in context.pages:
        try:
            if "retrieveMain" in pg.url:
                main_page = pg
                break
        except Exception:
            continue

    if not main_page:
        # 메인(retrieveMain) 탭이 없으면(로그인 전 등) 첫 페이지 반환 — 팝업 닫기 스킵.
        return context.pages[0] if context.pages else None

    for pg in context.pages[:]:
        if pg != main_page:
            try:
                await pg.close()
            except Exception:
                pass
    return main_page
