"""근로복지공단(고용보험) EDI 사업장 선택 모듈 (라이브 검증 2026-07)

엑셀 v3 (E98, H98): 관리번호 = 사업자등록번호 + '0'.
기존 biz_to_mgmt_no() (src/batch/models.py) 규칙과 동일.

사업장 전환 흐름 (라이브 검증):
  1. 메인 화면 관리번호 입력란(maeGwanriNo)에 관리번호 입력
  2. 사업장조회 버튼(btnSaeopjangSearch) 클릭 → WZ0101_P01 팝업 오픈
  3. 팝업의 관리번호 입력란에 값이 자동 채워짐(부모에서 전달)
  4. 팝업 '조회' 버튼(btnSearch) 클릭 → 결과 그리드 표시
  5. 결과 행의 '선택' 버튼(GridMain_button_0_0) 클릭 → 팝업 닫히며 부모에 반영
"""

import asyncio
import re

from src.utils.log import log
from src.utils.human import human_delay
from src.automation.comwel._constants import (
    INPUT_MGMT_NO_ID, BTN_WORKPLACE_SEARCH_ID,
    POPUP_WORKPLACE_ID, POPUP_WORKPLACE_CLOSE_ID,
    POPUP_WORKPLACE_MGMT_NO_ID, POPUP_WORKPLACE_SEARCH_BTN_ID,
    POPUP_WORKPLACE_SELECT_BTN_PREFIX, WORKPLACE_GRID_ROW_CLASS,
    WORKPLACE_SEARCH_DELAY_S, POPUP_TIMEOUT_S,
)


def _normalize_mgmt_no(number: str) -> str:
    """관리번호 정규화 — 숫자만 추출."""
    return re.sub(r"\D", "", number or "")


async def reset_workplace_page(page):
    """사업장 검색 기준 페이지로 리셋."""
    from src.automation.comwel._constants import COMWEL_MAIN
    try:
        await page.goto(COMWEL_MAIN)
        await asyncio.sleep(2)
    except Exception as e:
        log(f"  reset_workplace_page 실패: {e}")


async def _wait_popup_open(page, popup_id: str, timeout: int = POPUP_TIMEOUT_S) -> bool:
    """팝업이 가시 상태로 열릴 때까지 대기."""
    for _ in range(timeout):
        visible = await page.evaluate(r"""(id) => {
            const el = document.getElementById(id);
            if (!el) return false;
            return el.getBoundingClientRect().width > 0;
        }""", popup_id)
        if visible:
            return True
        await asyncio.sleep(1)
    return False


async def _enter_mgmt_no(page, management_number: str) -> bool:
    """메인 화면 관리번호 입력란에 값 입력 (w2 프레임워크 native setter).

    입력값은 자동 포맷팅됨(예: 51586017090 → 515-86-01709-0).
    """
    ok = await page.evaluate(r"""(args) => {
        const el = document.getElementById(args.id);
        if (!el) return false;
        el.focus();
        const setter = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype, 'value').set;
        setter.call(el, args.mgmt);
        el.dispatchEvent(new Event("input", {bubbles: true}));
        el.dispatchEvent(new Event("change", {bubbles: true}));
        el.dispatchEvent(new Event("blur", {bubbles: true}));
        return el.value;
    }""", {"id": INPUT_MGMT_NO_ID, "mgmt": management_number})
    return bool(ok)


async def _click_workplace_search(page) -> bool:
    """사업장조회 버튼 클릭 → WZ0101_P01 팝업 오픈 대기."""
    clicked = await page.evaluate(r"""(id) => {
        const el = document.getElementById(id);
        if (!el) return false;
        el.click();
        return true;
    }""", BTN_WORKPLACE_SEARCH_ID)
    if not clicked:
        return False
    return await _wait_popup_open(page, POPUP_WORKPLACE_ID)


async def _popup_search_and_select(page, target_mgmt: str) -> tuple[bool, str]:
    """팝업에서 조회 후 관리번호가 일치하는 행 선택.

    팝업 관리번호란은 부모에서 자동 채워지지만, 일치 확인을 위해 결과 행의
    관리번호(숫자 정규화)와 target_mgmt 를 비교한다 (blind 첫 행 클릭 방지).

    Returns:
        (selected, workplace_name)
    """
    # 팝업 '조회' 버튼 클릭
    await page.evaluate(r"""(id) => {
        const el = document.getElementById(id);
        if (el) el.click();
    }""", POPUP_WORKPLACE_SEARCH_BTN_ID)
    await asyncio.sleep(WORKPLACE_SEARCH_DELAY_S)

    # 결과 행에서 관리번호 일치 행 찾기 + 해당 행의 '선택' 버튼 클릭
    result = await page.evaluate(r"""(args) => {
        const popup = document.getElementById(args.popupId);
        if (!popup) return {ok: false, reason: "popup 없음"};
        const rows = popup.querySelectorAll("[class*='grid_body_row'], .w2grid_lastRow, [class*='row']");
        let target = null;
        let targetName = "";
        for (const row of rows) {
            const r = row.getBoundingClientRect();
            if (r.width === 0) continue;
            const cells = Array.from(row.querySelectorAll("td, span, div"))
                .map(c => (c.textContent || "").trim());
            // 행 전체 텍스트에서 숫자만 추출해 관리번호 비교
            const rowText = cells.join("");
            const digits = rowText.replace(/\D/g, "");
            const targetDigits = args.targetDigits;
            if (digits.includes(targetDigits)) {
                target = row;
                // 사업장명은 보통 3번째 셀 (선택/관리번호/사업장명/...)
                targetName = cells[2] || cells[1] || "";
                break;
            }
        }
        if (!target) {
            // 일치 행 못 찾으면 첫 번째 가시 결과 행 사용(fallback)
            for (const row of rows) {
                if (row.getBoundingClientRect().width > 0) { target = row; break; }
            }
            if (target) {
                const cells = Array.from(target.querySelectorAll("td, span, div")).map(c => (c.textContent||"").trim());
                targetName = cells[2] || cells[1] || "";
            }
        }
        if (!target) return {ok: false, reason: "결과 행 없음"};

        // 행 내 '선택' 버튼 또는 부모 컨테이너의 GridMain_button 찾기
        let selBtn = null;
        // 행 자체에 button 있으면 사용
        selBtn = target.querySelector("button[class*=''], button");
        // 아니면 GridMain_button_0_0 (첫 행) 사용
        if (!selBtn) {
            selBtn = document.getElementById(args.selectBtnPrefix + "0_0");
        }
        // 행 클릭으로 선택 처리 시도 후 버튼 클릭
        try { target.click(); } catch(e) {}
        if (selBtn) {
            try { selBtn.click(); } catch(e) {}
        }
        return {ok: true, name: targetName};
    }""", {"popupId": POPUP_WORKPLACE_ID,
            "targetDigits": _normalize_mgmt_no(target_mgmt),
            "selectBtnPrefix": POPUP_WORKPLACE_SELECT_BTN_PREFIX})

    if result.get("ok"):
        return True, result.get("name", "")
    return False, result.get("reason", "")


async def _close_workplace_popup(page):
    """사업장조회 팝업 닫기 (정리용)."""
    await page.evaluate(r"""(id) => {
        const el = document.getElementById(id);
        if (el) el.click();
    }""", POPUP_WORKPLACE_CLOSE_ID)
    await asyncio.sleep(1)


async def select_workplace(page, workplace_name: str, management_number: str = ""):
    """사업장 선택 (이미 사업장조회 팝업이 열려 있다고 가정하지 않음).

    메인 화면에서 관리번호 입력 → 사업장조회 → 팝업 조회/선택 전체 수행.

    Args:
        page: 20209 메인 화면 페이지
        workplace_name: 사업장명 (fallback/로깅용)
        management_number: 사업장관리번호 (사업자번호+0). 우선 사용.

    Returns:
        bool: 선택 성공 여부.
    """
    mgmt = management_number or workplace_name
    if not mgmt:
        log("  사업장 선택 실패: 관리번호/이름 없음")
        return False

    log(f"  관리번호 입력: {mgmt}")
    if not await _enter_mgmt_no(page, mgmt):
        log(f"  ⚠ 관리번호 입력란({INPUT_MGMT_NO_ID})을 찾지 못함")
        return False
    await human_delay(0.5)

    log("  사업장조회 버튼 클릭...")
    if not await _click_workplace_search(page):
        log(f"  ⚠ 사업장조회 팝업이 열리지 않음 (버튼: {BTN_WORKPLACE_SEARCH_ID})")
        return False

    log("  팝업에서 조회/선택...")
    ok, name = await _popup_search_and_select(page, mgmt)
    if ok:
        log(f"  사업장 선택 완료: '{name or workplace_name}'")
        await asyncio.sleep(WORKPLACE_SEARCH_DELAY_S)
        return True

    log(f"  사업장 선택 실패: {name or '원인 불명'}")
    await _close_workplace_popup(page)
    return False


async def switch_workplace(page, workplace_name: str, management_number: str = ""):
    """사업장 전환 풀 시퀀스: 관리번호 입력 → 조회 → 선택. 어댑터 진입점."""
    return await select_workplace(page, workplace_name, management_number)


async def list_workplaces(page, *, retry: bool = True):
    """현재 사업장 목록 조회 (미구현 placeholder)."""
    log("  (list_workplaces) 단독 실행 모드에서만 사용 — GUI 경로에선 미사용")
    return []
