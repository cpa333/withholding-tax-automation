"""원천징수이행상황신고서 (SWTA0101) 자동화

SWTA0101 이동 → 매월/반기 확인 → 사용자 지정 연도/월로 기간 설정 → 조회 → 마감/마감해제.

기간 설정:
  - 신고주기: DB report_cycle("매월"/"반기") 우선. 비어있으면 위하고 라디오
    (ground truth, 읽기 전용)에서 읽어 결정 → 어댑터가 DB 에 역충전.
  - 매월: 선택 연/월({year}/{month:02d}). None 이면 compute_target_period() 직전월
  - 반기: 실행일 기준 — 7~12월 실행→당해 1~6월 / 1~6월 실행→전년 7~12월.
    compute_half_period() 사용. (GUI 연/월 무시)
  - 귀속기간과 지급기간은 set_period_fields()에서 모두 설정
    (반기 모드에서는 두 기간이 완전 연동되지 않으므로 개별 설정 필요)

사전 조건:
- page가 이미 SmartA 급여 페이지에 있어야 함
- Chrome CDP 모드(port 9223) 실행 상태
"""
import asyncio
import sys
from datetime import datetime

from src.automation.wehago._common import (
    log, dismiss_dialogs, goto_menu_page, get_report_period_type,
    set_period_fields, compute_target_period, click_menu,
)


def compute_half_period(now: datetime) -> tuple[int, int, int]:
    """반기 신고의 (연도, 시작월, 종료월)을 실행일 기준으로 반환.

    반기 신고는 연 2회:
      - 7월에 상반기(1~6월) 신고 → 실행월이 7~12월이면 당해 1~6월
      - 1월에 하반기(전년 7~12월) 신고 → 실행월이 1~6월이면 전년 7~12월
    """
    if now.month >= 7:
        return now.year, 1, 6
    return now.year - 1, 7, 12


async def run_swta0101(page, year: int = None, month: int = None,
                       report_cycle: str = "", client_id: int = None) -> str:
    """원천징수이행상황신고서 자동화

    Args:
        page: SmartA 페이지에 위치한 Playwright page
        year: 귀속 연도 (매월 모드에서만 사용. None이면 compute_target_period)
        month: 귀속 월 (매월 모드에서만 사용. None이면 compute_target_period)
        report_cycle: DB 에 저장된 신고주기("매월"/"반기"/""). 비어있거나 알 수 없으면
            위하고 라디오(ground truth)를 읽어 결정.
        client_id: 역충전(backfill) 식별용 (이 함수 자체는 사용 않함, 어댑터가 사용).

    Returns:
        이번 실행에 사용된 신고주기("매월"/"반기"/""). DB 가 비어있었고 라디오에서
        값을 얻은 경우 어댑터가 이 값을 DB 에 역충전한다.
    """
    # [0] SPA 라우팅 초기화: SWSA0101 사이드바 클릭
    log("[SWTA0101] 급여자료입력(SWSA0101) 사이드바 클릭 (SPA 라우팅 초기화)...")
    await click_menu(page, "SWSA0101")
    await asyncio.sleep(3)
    await dismiss_dialogs(page)

    # [1] SWTA0101 이동
    log("[SWTA0101] 원천징수이행상황신고서 이동...")
    await goto_menu_page(page, "SWTA0101")
    await asyncio.sleep(3)
    await dismiss_dialogs(page)

    # [2] 신고주기 결정: DB report_cycle 우선. 비어있으면 위하고 라디오(ground truth).
    #     라디오는 시스템 고정(클릭 불가)이므로 읽기만 한다.
    cycle = (report_cycle or "").strip()
    if cycle not in ("매월", "반기"):
        radio_cycle = await get_report_period_type(page)
        log(f"[SWTA0101] 신고주기: DB='{cycle or '비어있음'}' → 라디오 ground truth='{radio_cycle}'")
        cycle = radio_cycle or ""
    else:
        log(f"[SWTA0101] 신고주기: DB report_cycle='{cycle}'")

    # [3] 기간 설정
    if cycle == "매월":
        # 매월: 사용자 선택 연/월 (None 이면 직전월)
        if year is None or month is None:
            year, month = compute_target_period()
        log(f"[SWTA0101] 매월 → {year}년 {month:02d}월")
        await set_period_fields(page, year, month, month)
    elif cycle == "반기":
        # 반기 신고는 연 2회(7월: 상반기 1~6월 / 1월: 하반기 전년 7~12월).
        # 실행일 기준으로 반기를 결정한다.
        y, sm, em = compute_half_period(datetime.now())
        half = "상반기(01~06)" if sm == 1 else "하반기(07~12)"
        log(f"[SWTA0101] 반기 → {y}년 {sm:02d}월 ~ {em:02d}월 ({half}, 실행일 기준)")
        await set_period_fields(page, y, sm, em)
    else:
        # 신고주기를 알 수 없음 → 안전하게 매월(선택월)로 폴백. 역충전 않함(cycle="").
        log(f"[SWTA0101] 신고주기 알 수 없음 — 매월(선택월)로 폴백")
        if year is None or month is None:
            year, month = compute_target_period()
        await set_period_fields(page, year, month, month)

    # [4] 조회 버튼 클릭
    log("[SWTA0101] 조회 버튼 클릭...")
    await page.evaluate("""() => {
        const btns = document.querySelectorAll('#Search button');
        for (const btn of btns) {
            if (btn.textContent.trim() === '조회' && btn.getBoundingClientRect().width > 0) {
                btn.click();
                return true;
            }
        }
        return false;
    }""")
    await asyncio.sleep(5)

    # [4-1] "저장된 내용이 있습니다" 모달 → 확인 (저장된 데이터 불러오기)
    for _ in range(3):
        loaded = await page.evaluate("""() => {
            const sels = ['._isDialog', '.LUX_basic_dialog'];
            for (const sel of sels) {
                for (const el of document.querySelectorAll(sel)) {
                    const cs = window.getComputedStyle(el);
                    if (cs.display === 'none' || el.offsetWidth < 50) continue;
                    if (!el.textContent.includes('저장된 내용')) continue;
                    const btns = el.querySelectorAll('button');
                    for (const btn of btns) {
                        if (btn.textContent.trim() === '확인' && btn.offsetWidth > 0) {
                            btn.click(); return true;
                        }
                    }
                }
            }
            return false;
        }""")
        if loaded:
            log("  저장된 데이터 불러오기 → 확인")
            await asyncio.sleep(2)
        else:
            break

    # [5] 마감/마감해제 버튼 처리
    log("[SWTA0101] 마감 상태 확인...")
    btn_text = await page.evaluate("""() => {
        const selectors = [
            '.WSC_LUXTooltip button.WSC_LUXButton',
            'button.WSC_LUXButton'
        ];
        for (const sel of selectors) {
            for (const btn of document.querySelectorAll(sel)) {
                const text = btn.textContent.trim();
                if ((text === '마감' || text === '마감해제') && btn.offsetWidth > 0) return text;
            }
        }
        return null;
    }""")

    if btn_text == "마감":
        log("  마감 버튼 클릭 (마감 적용)...")
        await page.evaluate("""() => {
            const btns = document.querySelectorAll('button.WSC_LUXButton');
            for (const btn of btns) {
                if (btn.textContent.trim() === '마감' && btn.offsetWidth > 0) { btn.click(); return; }
            }
        }""")

        # 1) 유의사항 안내 모달 → 확인(enter)
        for i in range(15):
            await asyncio.sleep(0.5)
            clicked = await page.evaluate("""() => {
                const dialogs = document.querySelectorAll('._isDialog, .LUX_basic_dialog');
                for (const d of dialogs) {
                    const cs = window.getComputedStyle(d);
                    if (cs.display === 'none' || d.offsetWidth < 30) continue;
                    const btns = d.querySelectorAll('button');
                    for (const btn of btns) {
                        const t = btn.textContent.trim();
                        if ((t === '확인(enter)' || t === '확인') && btn.offsetWidth > 0) {
                            btn.click(); return t;
                        }
                    }
                }
                return null;
            }""")
            if clicked:
                log(f"  모달 버튼 클릭: {clicked}")
                break

        # 2) "마감 완료!" 후속 모달 → 확인
        await asyncio.sleep(2)
        for i in range(5):
            clicked = await page.evaluate("""() => {
                const dialogs = document.querySelectorAll('._isDialog, .LUX_basic_dialog');
                for (const d of dialogs) {
                    const cs = window.getComputedStyle(d);
                    if (cs.display === 'none' || d.offsetWidth < 30) continue;
                    const btns = d.querySelectorAll('button');
                    for (const btn of btns) {
                        const t = btn.textContent.trim();
                        if ((t === '확인(enter)' || t === '확인') && btn.offsetWidth > 0) {
                            btn.click(); return t;
                        }
                    }
                }
                return null;
            }""")
            if clicked:
                log(f"  후속 모달 버튼 클릭: {clicked}")
                await asyncio.sleep(1)
            else:
                break

        # 마감 후 상태 확인
        await asyncio.sleep(1)
        new_btn = await page.evaluate("""() => {
            const selectors = [
                '.WSC_LUXTooltip button.WSC_LUXButton',
                'button.WSC_LUXButton'
            ];
            for (const sel of selectors) {
                for (const btn of document.querySelectorAll(sel)) {
                    const text = btn.textContent.trim();
                    if ((text === '마감' || text === '마감해제') && btn.offsetWidth > 0) return text;
                }
            }
            return null;
        }""")
        log(f"  마감 후 버튼 상태: {new_btn}")
    elif btn_text == "마감해제":
        log("  이미 마감 상태 - 스킵")
    else:
        log(f"  마감 버튼 상태: {btn_text}")

    await dismiss_dialogs(page)
    log("[SWTA0101] 완료")
    return cycle


# ═══════════════════════════════════════════════════════════════════════
# 독립 실행
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import io
    import os

    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')

    async def _main():
        from playwright.async_api import async_playwright
        from src.utils.chrome_cdp import launch_chrome, connect_page
        from src.automation.wehago._common import (
            wait_for_login, goto_salary_page, click_menu,
        )

        company = input("수임처 이름: ").strip()
        if not company:
            print("수임처 이름이 필요합니다.")
            return

        launch_chrome()
        async with async_playwright() as p:
            browser, context, page = await connect_page(p)
            if not await wait_for_login(page):
                return
            await dismiss_dialogs(page)
            if not await goto_salary_page(page, company):
                return
            await dismiss_dialogs(page)

            await run_swta0101(page)

    asyncio.run(_main())
