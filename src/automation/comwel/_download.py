"""근로복지공단(고용보험) EDI 인쇄물 다운로드 모듈 (라이브 검증 2026-07)

엑셀 v3 (E100~E102): 고용 탭 → 고용보험료 지원금 정보(사회보험료지원금 조회) → 인쇄하기.

라이브 검증된 전체 흐름:
  1. 하단 '고용' 탭(btnTabGy) 클릭
  2. 지원금정보 버튼(키워드 매칭 — 라벨/동적 id 가변) 클릭 → WL0502_P02 팝업 오픈
  3. 데이터 건수 확인 — 0건이면 인쇄 생략(정상 처리)
  4. 팝업 내 '인쇄하기' 버튼(텍스트 매칭) 클릭 → WZ0203 모달 + ifr_Report(ClipReport) 오픈
  5. ClipReport 리포트 뷰어에서 PDF + 엑셀 동시 다운로드:
     a. report_menu_pdf_download_button("PDF 저장") → PDF 직접 다운로드
     b. report_menu_excel_download_button("엑셀 저장") → 엑셀 직접 다운로드
     (전용 버튼은 형식 선택 다이얼로그 없이 직접 다운로드 — save_button 흐름보다 간단)

주의:
- 지원금 버튼 라벨이 사업장에 따라 다름 ("사회보험료 지원금정보" / "고용보험료 지원금 정보")
  → BTN_SUPPORT_INFO_KEYWORD("지원금") 키워드 매칭.
- 인쇄/엑셀 버튼 id(wq_uuid_XXXX)는 동적 → 텍스트 매칭.
- ClipReport 는 ifr_Report 프레임(별도 DOM)으로 접근해야 한다.

당월보험료 부과내역조회(WL0502_P04, 라이브 검증 2026-07) 추가:
- 20209 본문의 '당월보험료 부과내역조회(간편조회)' 런처 → WL0502_P04 팝업.
- 인쇄→ClipReport 흐름은 WL0502_P02(지원금)과 완전 동일 → 팝업 id 를 매개변수화한
  공유 헬퍼(_click_print_button/_read_support_count/_close_support_popup)로 재사용.
- 산재/고용 탭별로 파일명을 구분(당월보험료부과내역_{산재|고용}_{YYYYMM}).
"""

import os
import asyncio

from src.utils.log import log
from src.utils.human import human_delay
from src.automation.comwel._constants import (
    TAB_SANJEONG_ID, TAB_EMPLOYMENT_ID,
    BTN_SUPPORT_INFO_KEYWORD,
    POPUP_SUPPORT_ID,
    BTN_PREMIUM_DETAIL_KEYWORD, BTN_PREMIUM_DETAIL_TEXT,
    POPUP_PREMIUM_DETAIL_ID,
    BTN_PRINT_TEXT, BTN_EXCEL_TEXT,
    REPORT_IFRAME_NAME, REPORT_BTN_SAVE_ID,
    REPORT_FORMAT_SELECT_ID, REPORT_FORMAT_PDF_TEXT,
    REPORT_DOWNLOAD_BTN_ID,
    REPORT_BTN_PDF_DOWNLOAD_ID, REPORT_BTN_EXCEL_DOWNLOAD_ID,
    DOWNLOAD_TIMEOUT_S, PRINT_CLICK_RETRIES,
    POPUP_TIMEOUT_S,
)

# 저장 최상위 폴더명(site_name). 병렬(--save-site 공단EDI) 시 "공단EDI"로 오버라이드.
# comwel_auto_cdp.py main() 에서 이 모듈 변수를 설정 (NPS/NHIS 패턴과 동일).
# 단독 실행(phase 5) 기본값: "고용보험" → ~/Desktop/고용보험_{YYYYMM}/{수임처}/
# 병렬 실행(phase 2): "공단EDI", subdir="고용보험" → ~/Desktop/공단EDI_{YYYYMM}/{수임처}/고용보험/
_SAVE_SITE = "고용보험"
_SAVE_SUBDIR = None  # 병렬(--save-site 공단EDI) 시 포털 하위폴더명; 단독 실행 시 None


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
        return "xlsx"   # OOXML (xlsx)
    if head[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "xls"    # OLE2 Compound Document (구 엑셀 .xls) — ClipReport 엑셀 형식
    return None


def _rename_download(downloaded, save_dir, base_name):
    """형식 자동 판별 후 리네임."""
    fmt = _detect_format(downloaded)
    ext = {"pdf": ".pdf", "xlsx": ".xlsx", "xls": ".xls"}.get(fmt, ".bin")
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


async def _click_tab_active_guard(page, tab_id: str, tab_label: str = "") -> bool:
    """하단 탭 active-guard 클릭 (라이브 검증 원형).

    이미 활성(w2tabcontrol_active) 탭이면 클릭하지 않는다 — 중복 클릭 시
    반대 탭으로 토글되어 해당 탭 데이터가 소실되는 문제 방지.
    산재/고용 양 탭 모두 이 패턴을 공유한다.
    """
    already = await page.evaluate(r'''(id) => {
        const el = document.getElementById(id);
        if (!el) return false;
        const li = el.closest("li");
        return !!(li && /w2tabcontrol_active/.test(li.className || ""));
    }''', tab_id)
    label = f"'{tab_label}' " if tab_label else ""
    if already:
        log(f"  {label}탭 이미 활성 — 클릭 생략")
        return True
    clicked = await page.evaluate(r"""(id) => {
        const el = document.getElementById(id);
        if (!el) return false;
        el.click();
        return true;
    }""", tab_id)
    if clicked:
        log(f"  {label}탭 클릭")
        await human_delay(3)
    return clicked


async def click_employment_tab(page) -> bool:
    """하단 '고용' 탭 클릭 (엑셀 E100). active-guard 유지."""
    return await _click_tab_active_guard(page, TAB_EMPLOYMENT_ID, "고용")


async def click_sanjeong_tab(page) -> bool:
    """하단 '산재' 탭 클릭 (라이브 검증 2026-07).

    20209 조회 후 기본 활성 탭은 산재. active-guard 로 이미 활성이면 클릭 생략 —
    중복 클릭 시 고용 탭으로 토글되어 산재 데이터가 소실되는 문제 방지.
    """
    return await _click_tab_active_guard(page, TAB_SANJEONG_ID, "산재")


async def open_support_popup(page) -> bool:
    """지원금정보 버튼 클릭 → WL0502_P02 팝업 오픈 (엑셀 E101).

    버튼 id(wq_uuid_XXXX)가 동적이고 라벨도 사업장에 따라 다름
    ("사회보험료 지원금정보" / "고용보험료 지원금 정보") → "지원금" 키워드 포함 +
    하단 탭 영역(고용 탭 근처, w2trigger)의 input/button 으로 매칭. (라이브 검증)
    """
    clicked_id = await page.evaluate(r"""(keyword) => {
        // 본문(mf_wfm_content) input/button 중 "지원금" 키워드 포함 첫 요소.
        // 사이드 메뉴(mf_gen_firstGenerator_side)는 제외. 스크롤에 무관.
        for (const el of document.querySelectorAll("input, button")) {
            const r = el.getBoundingClientRect();
            if (r.width === 0) continue;
            const id = el.id || "";
            if (!id.startsWith("mf_wfm_content")) continue;
            const t = (el.textContent || el.value || "").trim();
            if (t.includes(keyword)) { el.click(); return el.id; }
        }
        return null;
    }""", BTN_SUPPORT_INFO_KEYWORD)
    if not clicked_id:
        log(f"  ⚠ '지원금' 버튼을 찾지 못함 (키워드 매칭)")
        return False
    log(f"  '지원금' 버튼 클릭 (id={clicked_id}) — 팝업 대기...")
    await asyncio.sleep(3)
    return await _wait_popup_open(page, POPUP_SUPPORT_ID)


async def _click_print_button(page, popup_id: str = POPUP_SUPPORT_ID) -> str:
    """팝업 내 '인쇄하기' 버튼 텍스트 매칭 클릭 (엑셀 E102).

    wq_uuid_XXXX id 가 동적이라 텍스트로 찾는다. 성공 시 클릭한 버튼 id 반환.
    주의: 클릭 시 새 창(리포트 뷰어)이 열려 CDP 세션이 끊길 수 있다.
    popup_id 로 전달된 팝업 컨테이너 범위에서만 버튼을 찾는다(WL0502_P02/P04 공통).
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
        }""", {"popupId": popup_id, "text": BTN_PRINT_TEXT})
        if result.get("ok"):
            log(f"  '{BTN_PRINT_TEXT}' 클릭 (id={result.get('id')})")
            return result.get("id", "")
        await asyncio.sleep(1)
    log(f"  ⚠ '{BTN_PRINT_TEXT}' 버튼을 찾지 못함 (텍스트 매칭, popup={popup_id})")
    return ""


def _popup_close_id(popup_id: str) -> str:
    """팝업 id 로부터 팝업 닫기 id derive. 패턴: {popup_id}_close.

    P02: mf_wfm_content_WL0502_P02 → mf_wfm_content_WL0502_P02_close
    P04: mf_wfm_content_WL0502_P04 → mf_wfm_content_WL0502_P04_close
    WL0502 계열 팝업의 닫기 버튼 id 가 이 패턴을 따름(라이브 검증).
    """
    return f"{popup_id}_close"


def _report_modal_close_id(popup_id: str) -> str:
    """팝업 id 로부터 ClipReport(WZ0203) 모달 닫기 id derive.

    패턴: {popup_id}_wframe_WZ0203_close
    P02: ...WL0502_P02_wframe_WZ0203_close (== REPORT_MODAL_CLOSE_ID)
    P04: ...WL0502_P04_wframe_WZ0203_close (== REPORT_MODAL_P04_CLOSE_ID)
    """
    return f"{popup_id}_wframe_WZ0203_close"


async def _close_support_popup(page, popup_id: str = POPUP_SUPPORT_ID,
                               report_modal_close_id: str = None):
    """팝업(+ ClipReport WZ0203 모달) 닫기 — WL0502_P02/P04 공통.

    다운로드 후 두 모달이 열린 채 남아 다음 단계/수임처 진행을 방해하므로
    확실히 닫는다. 순서: WZ0203(ClipReport 인쇄 모달) 먼저 → 팝업.
    (라이브 검증: WZ0203 닫기 후 팝업 닫기 순으로 동작)

    report_modal_close_id 미제공 시 popup_id 로부터 derive(DRY). 기본값
    POPUP_SUPPORT_ID(P02) → 기존 지원금 흐름의 동작/결과 불변.
    """
    if report_modal_close_id is None:
        report_modal_close_id = _report_modal_close_id(popup_id)
    popup_close = _popup_close_id(popup_id)
    # 1) WZ0203 (ClipReport 인쇄 모달) 닫기
    await page.evaluate(r"""(id) => {
        const el = document.getElementById(id);
        if (el) el.click();
    }""", report_modal_close_id)
    await asyncio.sleep(1)
    # 2) 팝업 닫기
    await page.evaluate(r"""(id) => {
        const el = document.getElementById(id);
        if (el) el.click();
    }""", popup_close)
    await asyncio.sleep(1)


# ─── 메인 다운로드 함수 ─────────────────────────────────────────────────────────

async def _read_support_count(page, popup_id: str = POPUP_SUPPORT_ID) -> int | None:
    """팝업의 '총 조회건 N건' 읽기. 없으면 None. WL0502_P02/P04 공통."""
    return await page.evaluate(r"""(popupId) => {
        const popup = document.getElementById(popupId);
        if (!popup) return null;
        const m = popup.innerText.match(/총\s*조회건\s*(\d+)\s*건/);
        return m ? parseInt(m[1]) : null;
    }""", popup_id)


async def download_support_info_printout(
    page, context, client_name, *, year: int = None, month: int = None,
):
    """고용보험료 지원금 정보 인쇄물 다운로드 (엑셀 E100~E102).

    흐름: 고용 탭 → 지원금정보 팝업 → (0건이면 스킵) → 인쇄하기(새 창 리포트 뷰어).

    라이브 검증: 현재 DB 수임처들은 지원금 데이터가 0건인 경우가 많다.
    0건일 때 인쇄 버튼은 활성(disabled=False)이지만 의미 없는 빈 인쇄물이
    생성되므로, 0건이면 인쇄를 생략하고 정상(빈 결과)으로 처리한다.

    **폴더 생성 지연**: 0건 수임처는 빈 폴더조차 만들지 않도록, save_dir 폴더는
    실제 다운로드가 일어날 때(데이터 1건 이상)만 생성한다.

    Args:
        client_name: 수임처명 (make_save_dir 용). save_dir 경로 대신 전달.

    Returns:
        dict: {"path": 경로|None, "format": "pdf"|"xlsx"|None,
               "print_clicked": bool, "count": int|None,
               "skipped": bool(0건으로 스킵 여부)}
    """
    from src.utils.save_path import make_save_dir

    period = f"{year}{month:02d}" if year and month else ""
    base_name = f"고용보험료지원금정보_{period}" if period else "고용보험료지원금정보"

    # 1) 고용 탭
    await click_employment_tab(page)

    # 2) 지원금정보 팝업 오픈
    #    지원금 버튼 자체가 없는 수임처(지원금 대상 아님)는 스킵(정상 처리).
    if not await open_support_popup(page):
        log("  지원금 버튼 없음 — 지원금 대상 아님, 스킵 (정상)")
        return {"path": None, "format": None, "print_clicked": False,
                "count": None, "skipped": True}

    # 3) 데이터 건수 확인 — 0건이면 인쇄 생략 (라이브 검증)
    #    0건 수임처는 폴더 생성도 하지 않는다 (빈 폴더 방지).
    count = await _read_support_count(page)
    if count is not None and count == 0:
        log(f"  지원금 데이터 0건 — 인쇄 생략 (정상, 폴더 미생성)")
        await _close_support_popup(page)
        return {"path": None, "format": None, "print_clicked": False,
                "count": 0, "skipped": True}
    if count and count > 0:
        log(f"  지원금 데이터 {count}건 — 인쇄 진행")

    # 데이터가 있으므로 여기서 폴더 생성 (0건은 위에서 반환되어 폴더 안 생김)
    # _SAVE_SITE/_SAVE_SUBDIR: 병렬(공단EDI) 시 comwel_auto_cdp main()에서 오버라이드.
    save_dir = make_save_dir(_SAVE_SITE, client_name, year=year, month=month,
                             subdir=_SAVE_SUBDIR)

    # 4) 인쇄하기 버튼 클릭 → WZ0203 모달 + ClipReport(ifr_Report) 오픈
    #    CDP 다운로드 감시를 미리 설정해 두고 클릭.
    before, cdp = await _setup_cdp_download(context, page, save_dir)
    try:
        clicked_id = await _click_print_button(page)
        if not clicked_id:
            return {"path": None, "format": None, "print_clicked": False,
                    "count": count, "skipped": False}

        # 5) ClipReport 리포트 뷰어에서 PDF + 엑셀 다운로드 (전용 버튼, 라이브 검증)
        #    report_menu_pdf_download_button / report_menu_excel_download_button 은
        #    형식 선택 다이얼로그 없이 직접 다운로드 → 간단하고 안정적.
        await asyncio.sleep(3)  # ClipReport 로딩 대기
        files = await _clipreport_download_files(page, save_dir, before, base_name)
        if files:
            paths = [f[0] for f in files]
            for fpath, fmt in files:
                log(f"  인쇄물 저장: {os.path.basename(fpath)} (형식: {fmt})")
            return {"path": paths[0] if paths else None,
                    "paths": paths,
                    "formats": [f[1] for f in files],
                    "format": files[0][1] if files else None,
                    "print_clicked": True, "count": count, "skipped": False}

        log("  ⚠ ClipReport 다운로드 실패")
        return {"path": None, "paths": [], "format": None, "formats": [],
                "print_clicked": True, "count": count, "skipped": False}
    finally:
        # 다운로드 성공/실패 무관 WZ0203 모달 + 지원금 팝업 확실히 닫기
        # (남아있으면 다음 수임처 진행 시 꼬임 — 라이브 검증)
        try:
            await _close_support_popup(page)
        except Exception:
            pass
        try:
            await cdp.detach()
        except Exception:
            pass


async def _find_report_frame(page, max_wait: int = 15):
    """ifr_Report(ClipReport) 프레임을 찾을 때까지 대기 후 반환."""
    for _ in range(max_wait):
        for fr in page.frames:
            if fr.name == REPORT_IFRAME_NAME or "ClipReport" in fr.url:
                return fr
        await asyncio.sleep(1)
    return None


async def _clipreport_download_one(report_frame, btn_id: str, save_dir, before,
                                   base_name: str, ext: str, label: str):
    """ClipReport 전용 다운로드 버튼 클릭 → 단일 파일 다운로드.

    전용 버튼(pdf_download/excel_download)은 형식 다이얼로그 없이 직접 다운로드.
    Returns: (final_path, format) or None
    """
    try:
        clicked = await report_frame.evaluate(r'''(id) => {
            const btn = document.getElementById(id);
            if (!btn) return false;
            btn.click();
            return true;
        }''', btn_id)
        if not clicked:
            log(f"  ⚠ '{label}' 버튼을 찾지 못함 ({btn_id})")
            return None
    except Exception as e:
        log(f"  ⚠ '{label}' 버튼 클릭 실패: {e}")
        return None

    downloaded = await _wait_for_download(save_dir, before, DOWNLOAD_TIMEOUT_S,
                                          label=label)
    if not downloaded:
        log(f"  ⚠ '{label}' 다운로드 감지 안 됨")
        return None
    fmt = _detect_format(downloaded) or ext
    final_path, detected_fmt = _rename_download(downloaded, save_dir, base_name)
    return (final_path, detected_fmt)


async def _clipreport_download_files(page, save_dir, before, base_name):
    """ClipReport 리포트 뷰어에서 PDF + 엑셀 다운로드 (전용 버튼 기반).

    라이브 검증: report_menu_pdf_download_button / report_menu_excel_download_button 은
    형식 선택 다이얼로그 없이 직접 다운로드. 두 파일을 순차적으로 다운로드.

    Returns:
        [(final_path, format), ...] or None (모두 실패 시)
    """
    report_frame = await _find_report_frame(page)
    if not report_frame:
        log("  ⚠ ClipReport 프레임(ifr_Report)을 찾지 못함")
        return None

    results = []
    # 1) PDF 다운로드
    pdf = await _clipreport_download_one(
        report_frame, REPORT_BTN_PDF_DOWNLOAD_ID, save_dir, before,
        base_name, "pdf", "PDF 저장",
    )
    if pdf:
        results.append(pdf)
        before = set(os.listdir(save_dir))  # 다음 다운로드 감지를 위해 갱신
    await asyncio.sleep(1)

    # 2) 엑셀 다운로드
    excel = await _clipreport_download_one(
        report_frame, REPORT_BTN_EXCEL_DOWNLOAD_ID, save_dir, before,
        base_name, "xlsx", "엑셀 저장",
    )
    if excel:
        results.append(excel)

    return results if results else None


# ─── 당월보험료 부과내역조회 (WL0502_P04, 라이브 검증 2026-07) ──────────────────
# 20209 본문의 '당월보험료 부과내역조회(간편조회)' 런처 → WL0502_P04 팝업 → 인쇄.
# 고용/산재 양 탭에서 동일 런처 버튼(활성 탭의 데이터로 동작). 인쇄→ClipReport
# 흐름은 WL0502_P02(지원금)과 완전 동일 → 매개변수화된 공유 헬퍼 재사용.

def _premium_detail_base_name(tab: str, year=None, month=None) -> str:
    """당월보험료 부과내역 파일 base_name 생성(순수 함수, 단위테스트용).

    탭 구분(산재/고용)으로 파일명 충돌 방지. period 미제공 시 접미사 생략.
    예: ("산재", 2026, 6) → "당월보험료부과내역_산재_202606"
    """
    period = f"{year}{month:02d}" if year and month else ""
    tab_tag = tab or "산재"
    return (f"당월보험료부과내역_{tab_tag}_{period}"
            if period else f"당월보험료부과내역_{tab_tag}")


async def _open_premium_detail_popup(page) -> bool:
    """당월보험료 부과내역조회 런처 버튼 클릭 → WL0502_P04 팝업 오픈 (라이브 검증).

    버튼 id(wq_uuid_XXXX, 예: mf_wfm_content_wq_uuid_1759)는 동적 → 텍스트 매칭.
    부분문자열 "당월보험료 부과내역" 로 매칭(전체 라벨은 "당월보험료 부과내역조회(간편조회)").
    본문(mf_wfm_content) input/button 범위에서 찾는다. 고용/산재 양 탭에서 동일 버튼.
    """
    clicked_id = await page.evaluate(r"""(keyword) => {
        // 본문(mf_wfm_content) input/button 중 키워드 포함 첫 가시 요소.
        for (const el of document.querySelectorAll("input, button")) {
            const r = el.getBoundingClientRect();
            if (r.width === 0) continue;
            const id = el.id || "";
            if (!id.startsWith("mf_wfm_content")) continue;
            const t = (el.textContent || el.value || "").trim();
            if (t.includes(keyword)) { el.click(); return el.id; }
        }
        return null;
    }""", BTN_PREMIUM_DETAIL_KEYWORD)
    if not clicked_id:
        log(f"  ⚠ '{BTN_PREMIUM_DETAIL_KEYWORD}' 버튼을 찾지 못함 (텍스트 매칭)")
        return False
    log(f"  '{BTN_PREMIUM_DETAIL_KEYWORD}' 버튼 클릭 (id={clicked_id}) — 팝업 대기...")
    await asyncio.sleep(3)
    return await _wait_popup_open(page, POPUP_PREMIUM_DETAIL_ID)


async def download_premium_detail_printout(
    page, context, client_name, *, tab: str = "산재",
    year: int = None, month: int = None,
):
    """당월보험료 부과내역조회 인쇄물 다운로드 (WL0502_P04, 라이브 검증).

    흐름(활성 탭 기준):
      당월보험료 부과내역조회 버튼(텍스트 매칭) → WL0502_P04 팝업 →
      (0건이면 스킵, 폴더 미생성) → 인쇄하기 → ClipReport → PDF+엑셀.

    tab 인자는 파일명 구분용("산재"/"고용") — 호출측이 미리 active-guard 로
    해당 탭을 활성화해 둔다(산재→고용 전환 시 토글 소실 주의).

    라이브 검증: 산재 건수(리드플렉스 6월)=6건. 0건 수임처 스킵 정상.

    Returns:
        dict: download_support_info_printout 과 동일 구조
              {"path", "paths", "format", "formats", "print_clicked",
               "count", "skipped"}
    """
    from src.utils.save_path import make_save_dir

    base_name = _premium_detail_base_name(tab, year, month)
    tab_tag = tab or "산재"

    # 1) 당월보험료 부과내역조회 팝업 오픈
    if not await _open_premium_detail_popup(page):
        log(f"  당월보험료 부과내역 버튼 없음 — 스킵 (정상, tab={tab_tag})")
        return {"path": None, "format": None, "print_clicked": False,
                "count": None, "skipped": True}

    # 2) 데이터 건수 — 0건이면 인쇄 생략 + 폴더 미생성 (지원금 흐름과 동일)
    count = await _read_support_count(page, POPUP_PREMIUM_DETAIL_ID)
    if count is not None and count == 0:
        log(f"  당월보험료 부과내역 0건 — 인쇄 생략 (정상, 폴더 미생성, tab={tab_tag})")
        await _close_support_popup(page, POPUP_PREMIUM_DETAIL_ID)
        return {"path": None, "format": None, "print_clicked": False,
                "count": 0, "skipped": True}
    if count and count > 0:
        log(f"  당월보험료 부과내역 {count}건 — 인쇄 진행 (tab={tab_tag})")

    # 데이터가 있으므로 여기서 폴더 생성 (0건은 위에서 반환되어 폴더 안 생김).
    # _SAVE_SITE/_SAVE_SUBDIR: 병렬(공단EDI) 시 comwel_auto_cdp main()에서 오버라이드.
    save_dir = make_save_dir(_SAVE_SITE, client_name, year=year, month=month,
                             subdir=_SAVE_SUBDIR)

    # 3) 인쇄하기 버튼 클릭 → WZ0203 모달 + ClipReport(ifr_Report) 오픈
    #    CDP 다운로드 감지를 미리 설정해 두고 클릭.
    before, cdp = await _setup_cdp_download(context, page, save_dir)
    try:
        clicked_id = await _click_print_button(page, POPUP_PREMIUM_DETAIL_ID)
        if not clicked_id:
            return {"path": None, "format": None, "print_clicked": False,
                    "count": count, "skipped": False}

        # 4) ClipReport 리포트 뷰어에서 PDF + 엑셀 다운로드
        #    WL0502_P04 도 동일 ifr_Report 흐름 → 공유 헬퍼 재사용.
        await asyncio.sleep(3)  # ClipReport 로딩 대기
        files = await _clipreport_download_files(page, save_dir, before, base_name)
        if files:
            paths = [f[0] for f in files]
            for fpath, fmt in files:
                log(f"  인쇄물 저장: {os.path.basename(fpath)} (형식: {fmt})")
            return {"path": paths[0] if paths else None,
                    "paths": paths,
                    "formats": [f[1] for f in files],
                    "format": files[0][1] if files else None,
                    "print_clicked": True, "count": count, "skipped": False}

        log("  ⚠ ClipReport 다운로드 실패 (당월보험료 부과내역)")
        return {"path": None, "paths": [], "format": None, "formats": [],
                "print_clicked": True, "count": count, "skipped": False}
    finally:
        # 다운로드 성공/실패 무관 WZ0203 모달 + P04 팝업 확실히 닫기
        # (남아있으면 다음 단계/수임처 진행 시 꼬임 — 라이브 검증).
        try:
            await _close_support_popup(page, POPUP_PREMIUM_DETAIL_ID)
        except Exception:
            pass
        try:
            await cdp.detach()
        except Exception:
            pass
