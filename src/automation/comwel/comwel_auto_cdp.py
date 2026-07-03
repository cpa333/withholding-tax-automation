"""근로복지공단(고용보험) EDI 자동화 — CDP 기반 메인 진입점

엑셀 v3 (C86~H106) 워크플로우 기반. 단독 CLI 실행 + 향후 병렬 편입용.

Usage:
    python -m src.automation.comwel.comwel_auto_cdp
    python src/automation/comwel/comwel_auto_cdp.py

사용법:
    1. Chrome이 CDP 모드(포트 9223 단독 / 9225 병렬)로 실행 중이어야 함
    2. 공동인증서(사무대행 151-86-01316) 로그인은 사용자가 직접 수행
    3. 로그인 후 사업장별 고용보험료 지원금 정보 인쇄물 다운로드

저장 경로:
    단독: ~/Desktop/고용보험_{YYYYMM}/{수임처}/
    병렬(--save-site 공단EDI): ~/Desktop/공단EDI_{YYYYMM}/{수임처}/고용보험/

주의: 포털 DOM/셀렉터는 라이브 튜닝에서 확정. 아래는 HTML 기반 추정 로직.
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from playwright.async_api import async_playwright
from src.utils.chrome_cdp import launch_chrome, connect_page as cdp_connect

# 저장 최상위 폴더명(site_name). CLI --save-site 로 오버라이드 — 병렬 실행 시
# 공통 폴더("공단EDI")로 묶음. 미지정 시 "고용보험"
# (단독 실행 기본값: ~/Desktop/고용보험_{YYYYMM}/{수임처}/).
_SAVE_SITE = "고용보험"
_SAVE_SUBDIR = None  # 병렬(--save-site 공단EDI) 시 포털 하위폴더명; 단독 실행 시 None

from src.utils.human import human_delay
from datetime import datetime as _dt

from src.automation.comwel._common import (
    log, COMWEL_URL, connect_page, wait_for_login,
    switch_workplace, select_workplace, reset_workplace_page,
    navigate_to_premium_20209, set_period, search_main, dismiss_dialogs,
    PAGE_LOAD_TIMEOUT_MS,
)
from src.automation.comwel._download import download_support_info_printout


_TRACE_PATH = os.path.join("debug", "comwel_parallel_trace.log")


def _trace(msg: str):
    """병렬 comwel 사업장 선택 진단용 파일 로그."""
    try:
        os.makedirs("debug", exist_ok=True)
        with open(_TRACE_PATH, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def _emit_summary(total, completed, skipped):
    """병렬 러너가 파싱할 결과 요약을 stdout 으로 출력 (NPS _emit_summary 대칭)."""
    try:
        from src.automation._parallel_report import emit_summary
        emit_summary(total, completed, skipped)
    except Exception:
        print(f"[요약] 전체 {total} / 완료 {completed} / 스킵 {len(skipped)}")
        for s in skipped:
            print(f"  - {s.get('name','?')}: {s.get('reason','?')}")


def print_header():
    log("=" * 60)
    log("  근로복지공단(고용보험) EDI 자동화 — 고용보험료 지원금 정보 다운로드")
    log("=" * 60)


async def run_single_workplace(page, context, workplace_name, *,
                               is_first=False, year=None, month=None,
                               management_number=""):
    """단일 사업장 인쇄물 다운로드 워크플로우 (라이브 검증 흐름).

    흐름: 20209 진입 → 연월 설정 → 사업장 전환 → 본화면조회 → 고용탭/지원금/인쇄.
    폴더는 download_support_info_printout 내부에서 데이터 있을 때만 생성.
    """
    # 0) 20209 화면 진입 (첫 수임처이거나 페이지가 대시보드일 때)
    await navigate_to_premium_20209(page)

    # 1) 부과기간 설정
    if year is not None and month is not None:
        await set_period(page, year, month)

    # 2) 사업장 전환
    ok = await switch_workplace(page, workplace_name, management_number)
    if not ok:
        log(f"  사업장 전환 실패: '{workplace_name}'")
        return False

    # 3) 본 화면 조회(btnSearch) — 데이터 로드 (라이브 검증)
    await search_main(page)

    # 4) 고용 탭 → 지원금정보 → 인쇄 (폴더는 데이터 있을 때만 생성)
    result = await download_support_info_printout(
        page, context, workplace_name, year=year, month=month,
    )
    await dismiss_dialogs(page)
    if result.get("path"):
        return True
    if result.get("skipped"):
        log(f"  '{workplace_name}' 지원금 0건 — 스킵 (폴더 미생성)")
        return True
    log(f"  '{workplace_name}' 인쇄물 다운로드 없음/실패")
    return False


async def run_auto_batch(page, context, *, firms, year, month, mgmts=None):
    """비대화형 일괄 실행 (--auto 모드). NPS run_auto_batch 대칭."""
    # comwel 단독 CLI는 firms 가 전달된 경우에만 동작 (전체 자동 수집은 미지원 —
    # 사업장 목록이 위하고 DB 기준이므로 GUI/어댑터 경로에서 사용).
    if firms is None:
        log("ERROR: --firms 없이 전체 실행은 지원하지 않습니다. GUI(phase 10)를 사용하세요.")
        return
    targets = list(firms)

    log(f"비대화형 일괄 실행: {len(targets)}개 수임처 (year={year}, month={month})")
    completed = 0
    skipped = []
    for i, wp_name in enumerate(targets, 1):
        mgmt = mgmts[i - 1] if mgmts and (i - 1) < len(mgmts) else ""
        log(f"\n{'='*55}")
        log(f"  [{i}/{len(targets)}] {wp_name}" + (f" (관리번호 {mgmt})" if mgmt else ""))
        try:
            ok = await run_single_workplace(page, context, wp_name,
                                            is_first=(completed == 0),
                                            year=year, month=month,
                                            management_number=mgmt)
            _trace(f"[{i}/{len(targets)}] target='{wp_name}' mgmt='{mgmt}' "
                   f"-> ok={bool(ok)}")
            if ok:
                completed += 1
                log(f"  {wp_name} 처리 완료. ({completed}개 완료)")
            else:
                log(f"  스킵: '{wp_name}' 처리 실패")
                skipped.append({"name": wp_name, "reason": "처리실패", "detail": "인쇄물"})
        except Exception as e:
            log(f"  ERROR: {wp_name} 처리 실패 - {e}")
            import traceback
            traceback.print_exc()
            skipped.append({"name": wp_name, "reason": "오류", "detail": str(e)})
            await reset_workplace_page(page)
            continue
    _emit_summary(len(targets), completed, skipped)


async def main(args=None):
    print_header()

    global _SAVE_SITE, _SAVE_SUBDIR
    _SAVE_SITE = getattr(args, "save_site", None) or "고용보험"
    _SAVE_SUBDIR = "고용보험" if getattr(args, "save_site", None) else None

    # _download 모듈의 저장 경로 변수도 동일하게 오버라이드 (NHIS 패턴:
    # nhis_edi_auto_cdp.py 가 _doc_download._SAVE_SITE 를 설정하는 것과 동일).
    # download_support_info_printout 이 이 값을 참조해 make_save_dir 호출.
    from src.automation.comwel import _download
    _download._SAVE_SITE = _SAVE_SITE
    _download._SAVE_SUBDIR = _SAVE_SUBDIR

    # ═══ Phase 1: Chrome 실행 + 연결 ═══
    log("\n[1/3] Chrome 실행...")
    result = launch_chrome(url=COMWEL_URL)
    if not result["success"]:
        log(f"ERROR: {result['error']}")
        return
    if result.get("reused"):
        log("  기존 Chrome에 연결")

    async with async_playwright() as p:
        log("[2/3] Chrome 연결 + 로그인 대기...")
        try:
            browser, context, page = await cdp_connect(p)
        except Exception as e:
            log(f"ERROR: Chrome 연결 실패 - {e}")
            return

        await page.goto(COMWEL_URL, wait_until="domcontentloaded",
                        timeout=PAGE_LOAD_TIMEOUT_MS)
        await page.bring_to_front()

        if not await wait_for_login(page):
            log("로그인 실패")
            return

        log("로그인 확인됨. 자동화 시작.\n")

        # --auto 비대화형 모드
        if args is not None and getattr(args, "auto", False):
            firms = ([s.strip() for s in args.firms.split(",") if s.strip()]
                     if args.firms else None)
            mgmts = ([s.strip() for s in args.mgmts.split(",")]
                     if getattr(args, "mgmts", None) else None)
            await run_auto_batch(page, context, firms=firms,
                                 year=args.year, month=args.month, mgmts=mgmts)
            return

        # ═══ Phase 2: 날짜 입력 ═══
        _now = _dt.now()
        _yr = input(f"연도 (기본={_now.year}): ").strip()
        _mo = input(f"월 (기본={_now.month}): ").strip()
        year = int(_yr) if _yr else None
        month = int(_mo) if _mo else None

        # ═══ Phase 3: 전체 자동 ═══
        await run_auto_batch(page, context, firms=None,
                             year=year, month=month, mgmts=None)


def _parse_args():
    import argparse
    p = argparse.ArgumentParser(description="근로복지공단(고용보험) EDI 자동화")
    p.add_argument("--auto", action="store_true", help="비대화형 일괄 실행")
    p.add_argument("--year", type=int, default=None)
    p.add_argument("--month", type=int, default=None)
    p.add_argument("--firms", type=str, default=None,
                   help="쉼표로 구분된 수임처명 (비어있으면 전체)")
    p.add_argument("--mgmts", type=str, default=None,
                   help="쉼표로 구분된 사업장관리번호 (--firms 와 같은 순서)")
    p.add_argument("--save-site", type=str, default=None,
                   help="저장 최상위 폴더명 오버라이드 (병렬: 공단EDI)")
    return p.parse_args()


if __name__ == "__main__":
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')
    asyncio.run(main(_parse_args()))
