"""급여자료입력 (SWSA0101) 자동화 — 오케스트레이터 + backward-compat re-export

엑셀 다운로드 → 업로드 양식 변환 → 엑셀 업로드 → PDF 발급.

하위 모듈로 분할 관리:
- _swsa_constants.py: JS 상수 + PrintDialog 상수
- _swsa_excel.py:     엑셀 다운로드/변환/업로드 + 모달 핸들러
- _swsa_calendar.py:  React LS_calendar 귀속연월 설정
- _swsa_pdf.py:       Windows PrintDialog PDF 다운로드

사전 조건:
- page가 이미 SmartA 급여 페이지에 있어야 함
- Chrome CDP 모드(port 9223) 실행 상태
"""
import asyncio
import os
import sys

from src.automation.wehago._common import (
    log, dismiss_dialogs, dismiss_print_modals,
)

# ─── backward-compat re-export ───────────────────────────────────────────────
from src.automation.wehago._swsa_constants import (
    PRINT_DIALOG_TITLE_RE, PRINT_DIALOG_CLASS_RE,
    SAVE_DIALOG_CLASS, DEFAULT_PRINT_FORMAT,
    _READ_SWSA_YM_JS, _READ_CALENDAR_YEAR_JS, _REACT_SET_CALENDAR_YEAR_JS,
)
from src.automation.wehago._swsa_excel import (
    download_excel, convert_for_upload, upload_excel, recalculate_salary,
    _handle_code_link_modal, _handle_jegasan_modal,
)
from src.automation.wehago._swsa_calendar import set_swsa_ym
from src.automation.wehago._swsa_pdf import download_pdf


# ═══════════════════════════════════════════════════════════════════════
# 메인 플로우
# ═══════════════════════════════════════════════════════════════════════

async def run_swsa0101(page, save_dir, *, dry_run=True, year=None, month=None,
                      recalculate=True, recalculate_category="고용보험 재계산"):
    """급여자료입력 전체 자동화

    흐름: 메뉴 이동 → (재계산) → 엑셀 다운로드 → 업로드 양식 변환 → 엑셀 업로드 → PDF.

    Args:
        page: SmartA 급여 페이지에 위치한 Playwright page
        save_dir: 파일 저장 디렉토리
        dry_run: True면 업로드 후 취소(테스트), False면 확인(실운영)
        year: 귀속연도 (None이면 이전 달 자동 계산)
        month: 귀속월 (None이면 이전 달 자동 계산)
        recalculate: True면 엑셀 다운로드 직전 사원 전체 재계산 수행 (라이브 검증)
        recalculate_category: 재계산 항목 (기본 '고용보험 재계산')
    """
    from src.automation.wehago._common import (
        navigate_to_swsa0101, compute_target_period,
    )

    # year/month 기본값: 이전 달
    if year is None or month is None:
        year, month = compute_target_period()

    # [1] SWSA0101 메뉴 이동 + 귀속연월 설정
    log(f"[SWSA0101] 급여자료입력 메뉴 이동 ({year}.{month:02d})...")
    ok = await navigate_to_swsa0101(page, year=year, month=month)
    if not ok:
        log("[SWSA0101] 이동/설정 실패")
        return

    # [2] 사원 전체 재계산 (다운로드 직전) — 해상도 무관, 라이브 검증
    if recalculate:
        log(f"[SWSA0101] 사원 재계산 ({recalculate_category})...")
        ok_recalc = await recalculate_salary(page, category=recalculate_category)
        if not ok_recalc:
            log("  ⚠ 재계산 실패 — 엑셀 다운로드로 계속 진행")

    # [4] 엑셀 다운로드
    log("[SWSA0101] 엑셀 다운로드...")
    download_path = await download_excel(page, save_dir)

    # [5] 업로드 양식 변환
    log("[SWSA0101] 업로드 양식 변환...")
    upload_path = convert_for_upload(download_path)

    # [5.5] 업로드 전 모달 정리
    log("[SWSA0101] 업로드 전 화면 정리...")
    await dismiss_dialogs(page)

    # [6] 엑셀 업로드
    log("[SWSA0101] 엑셀 업로드...")
    success = await upload_excel(page, upload_path, dry_run=dry_run)
    if success:
        log("  업로드 완료!")
    else:
        log("  업로드 중 에러 발생. 화면을 확인하세요.")

    # [7] PDF 다운로드
    log("[SWSA0101] PDF 다운로드...")
    pdf_path = await download_pdf(page, save_dir)
    if pdf_path:
        log(f"  PDF 완료: {pdf_path}")
    else:
        log("  PDF 다운로드 실패")

    # 급여대장 일괄인쇄 모달 닫기
    log("[SWSA0101] 일괄인쇄 모달 정리...")
    await dismiss_print_modals(page)

    log("[SWSA0101] 완료")


# ═══════════════════════════════════════════════════════════════════════
# 독립 실행
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import io
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')

    async def _main():
        from playwright.async_api import async_playwright
        from src.utils.chrome_cdp import launch_chrome, connect_page
        from src.automation.wehago._common import wait_for_login, goto_salary_page

        company = input("수임처 이름: ").strip()
        if not company:
            print("수임처 이름이 필요합니다.")
            return

        year_input = input("연도 (Enter=자동): ").strip()
        month_input = input("월 (Enter=자동): ").strip()
        year = int(year_input) if year_input else None
        month = int(month_input) if month_input else None

        launch_chrome()
        async with async_playwright() as p:
            browser, context, page = await connect_page(p)
            if not await wait_for_login(page):
                return
            await dismiss_dialogs(page)
            if not await goto_salary_page(page, company):
                return
            await dismiss_dialogs(page)

            save_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "results"))
            await run_swsa0101(page, save_dir, dry_run=True, year=year, month=month)

    asyncio.run(_main())
