"""근로복지공단(고용보험) EDI 인쇄물 다운로드 모듈 (라이브 검증 2026-07)

엑셀 v3 (E100~E102): 고용 탭 → 고용보험료 지원금 정보(사회보험료지원금 조회) → 인쇄하기.

라이브 확인된 흐름:
  1. 하단 '고용' 탭(btnTabGy) 클릭
  2. '사회보험료 지원금정보'(wq_uuid_1191) 버튼 클릭 → WL0502_P02 팝업 오픈
  3. 팝업 내 '인쇄하기' 버튼(텍스트 매칭 — wq_uuid_XXXX 동적) 클릭
  4. 새 창(리포트 뷰어)이 열림 → CDP 세션 끊김 주의

주의:
- '인쇄하기'/'엑셀저장' 버튼 id는 매 렌더링마다 동적(wq_uuid_XXXX)이므로
  텍스트 매칭 + 팝업(POPUP_SUPPORT_ID) 범위로 클릭해야 한다.
- 인쇄 버튼 클릭 시 CDP 연결이 끊길 수 있어(새 창 window.open) 호출측에서
  재연결 로직이 필요할 수 있다. 현재 구현은 인쇄 버튼 클릭까지 담당하며,
  리포트 뷰어 창에서의 저장/PDF 다운로드는 2차 라이브 튜닝 대상이다.
"""

import os
import asyncio

from src.utils.log import log
from src.utils.human import human_delay
from src.automation.comwel._constants import (
    TAB_EMPLOYMENT_ID, BTN_SUPPORT_INFO_ID,
    POPUP_SUPPORT_ID, POPUP_SUPPORT_CLOSE_ID,
    BTN_PRINT_TEXT, BTN_EXCEL_TEXT,
    DOWNLOAD_TIMEOUT_S, PRINT_CLICK_RETRIES,
    POPUP_TIMEOUT_S,
)


# ─── CDP 다운로드 헬퍼 (NPS 패턴) ────────────────────────────────────────────

async def _setup_cdp_download(context, page, save_dir):
    """CDP 다운로드 동작 설정, (이전 파일 set, cdp 세션) 반환."""
    os.makedirs(save_dir, exist_ok=True)
    cdp = await context.new_cdp_session(page)
    await cdp.send("Browser.setDownloadBehavior", {
        "behavior": "allowAndName",
        "downloadPath": save_dir,
        "eventsEnabled": True,
    })
    return set(os.listdir(save_dir)), cdp


async def _wait_for_download(save_dir, before, timeout, label="file"):
    """다운로드 완료 폴링. 완료 파일 경로 or None."""
    for i in range(timeout):
        await asyncio.sleep(1)
        after = set(os.listdir(save_dir))
        new_files = after - before
        crdownload = [f for f in new_files if f.endswith(".crdownload")]
        done = [f for f in new_files if not f.endswith(".crdownload")]
        if not crdownload and done:
            return os.path.join(save_dir, done[0])
        if i % 10 == 9 and (crdownload or done):
            log(f"  {label} 다운로드 진행 중... ({i+1}s)")
    return None


def _detect_format(path):
    """다운로드 파일 매직으로 PDF/엑셀 형식 판별."""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError:
        return None
    if head[:5] == b"%PDF-":
        return "pdf"
    if head[:4] == b"PK\x03\x04" and os.path.getsize(path) >= 2048:
        return "xlsx"
    return None


def _rename_download(downloaded, save_dir, base_name):
    """형식 자동 판별 후 리네임."""
    fmt = _detect_format(downloaded)
    ext = {"pdf": ".pdf", "xlsx": ".xlsx"}.get(fmt, ".bin")
    final_path = os.path.join(save_dir, f"{base_name}{ext}")
    if downloaded != final_path:
        if os.path.exists(final_path):
            os.remove(final_path)
        os.rename(downloaded, final_path)
    return final_path, fmt


# ─── 팝업/탭 제어 (라이브 검증 id) ─────────────────────────────────────────────

async def _wait_popup_open(page, popup_id: str, timeout: int = POPUP_TIMEOUT_S) -> bool:
    for _ in range(timeout):
        visible = await page.evaluate(r"""(id) => {
            const el = document.getElementById(id);
            return el ? el.getBoundingClientRect().width > 0 : false;
        }""", popup_id)
        if visible:
            return True
        await asyncio.sleep(1)
    return False


async def click_employment_tab(page) -> bool:
    """하단 '고용' 탭 클릭 (엑셀 E100)."""
    clicked = await page.evaluate(r"""(id) => {
        const el = document.getElementById(id);
        if (!el) return false;
        el.click();
        return true;
    }""", TAB_EMPLOYMENT_ID)
    if clicked:
        log("  '고용' 탭 클릭")
        await human_delay(2)
    return clicked


async def open_support_popup(page) -> bool:
    """'사회보험료 지원금정보' 버튼 클릭 → WL0502_P02 팝업 오픈 (엑셀 E101)."""
    clicked = await page.evaluate(r"""(id) => {
        const el = document.getElementById(id);
        if (!el) return false;
        el.click();
        return true;
    }""", BTN_SUPPORT_INFO_ID)
    if not clicked:
        log(f"  ⚠ '사회보험료 지원금정보' 버튼({BTN_SUPPORT_INFO_ID}) 클릭 실패")
        return False
    log("  '사회보험료 지원금정보' 클릭 — 팝업 대기...")
    await asyncio.sleep(3)
    return await _wait_popup_open(page, POPUP_SUPPORT_ID)


async def _click_print_button(page) -> str:
    """팝업 내 '인쇄하기' 버튼 텍스트 매칭 클릭 (엑셀 E102).

    wq_uuid_XXXX id 가 동적이라 텍스트로 찾는다. 성공 시 클릭한 버튼 id 반환.
    주의: 클릭 시 새 창(리포트 뷰어)이 열려 CDP 세션이 끊길 수 있다.
    """
    for attempt in range(PRINT_CLICK_RETRIES):
        result = await page.evaluate(r"""(args) => {
            const popup = document.getElementById(args.popupId);
            if (!popup) return {ok: false, reason: "popup 없음"};
            for (const el of popup.querySelectorAll("input, button, a")) {
                const r = el.getBoundingClientRect();
                if (r.width === 0) continue;
                const t = (el.textContent || el.value || "").trim();
                if (t === args.text) {
                    el.click();
                    return {ok: true, id: el.id};
                }
            }
            return {ok: false, reason: "버튼 못찾음"};
        }""", {"popupId": POPUP_SUPPORT_ID, "text": BTN_PRINT_TEXT})
        if result.get("ok"):
            log(f"  '{BTN_PRINT_TEXT}' 클릭 (id={result.get('id')})")
            return result.get("id", "")
        await asyncio.sleep(1)
    log(f"  ⚠ '{BTN_PRINT_TEXT}' 버튼을 찾지 못함 (텍스트 매칭)")
    return ""


async def _close_support_popup(page):
    """지원금 팝업 닫기."""
    await page.evaluate(r"""(id) => {
        const el = document.getElementById(id);
        if (el) el.click();
    }""", POPUP_SUPPORT_CLOSE_ID)
    await asyncio.sleep(1)


# ─── 메인 다운로드 함수 ─────────────────────────────────────────────────────────

async def download_support_info_printout(
    page, context, save_dir, *, year: int = None, month: int = None,
):
    """고용보험료 지원금 정보 인쇄물 다운로드 (엑셀 E100~E102).

    흐름: 고용 탭 → 지원금정보 팝업 → 인쇄하기(새 창 리포트 뷰어).

    Returns:
        dict: {"path": 경로|None, "format": "pdf"|"xlsx"|None, "print_clicked": bool}
    """
    period = f"{year}{month:02d}" if year and month else ""
    base_name = f"고용보험료지원금정보_{period}" if period else "고용보험료지원금정보"

    # 1) 고용 탭
    await click_employment_tab(page)

    # 2) 지원금정보 팝업 오픈
    if not await open_support_popup(page):
        return {"path": None, "format": None, "print_clicked": False}

    # 3) 인쇄하기 버튼 클릭 — 새 창(리포트 뷰어)이 열림
    #    CDP 다운로드 감시를 미리 설정해 두고 클릭.
    before, cdp = await _setup_cdp_download(context, page, save_dir)
    try:
        clicked_id = await _click_print_button(page)
        if not clicked_id:
            return {"path": None, "format": None, "print_clicked": False}

        # 새 창/다운로드 대기 — 인쇄 버튼은 새 창 리포트 뷰어를 여므로
        # 직접 다운로드가 아닐 수 있다. 다운로드 + 새 페이지 둘 다 감시.
        log("  인쇄물(리포트 뷰어) 대기 중...")
        downloaded = await _wait_for_download(
            save_dir, before, DOWNLOAD_TIMEOUT_S, label="고용보험 인쇄물",
        )
        if downloaded:
            final_path, fmt = _rename_download(downloaded, save_dir, base_name)
            log(f"  인쇄물 저장: {os.path.basename(final_path)} (형식: {fmt})")
            return {"path": final_path, "format": fmt, "print_clicked": True}

        # 직접 다운로드 없음 → 리포트 뷰어 새 창에서 별도 저장 필요 (2차 튜닝)
        log("  ⚠ 직접 다운로드 감지 안 됨 — 리포트 뷰어 새 창에서 저장 필요 (2차 튜닝)")
        return {"path": None, "format": None, "print_clicked": True}
    finally:
        try:
            await cdp.detach()
        except Exception:
            pass
