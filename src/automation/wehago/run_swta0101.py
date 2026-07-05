"""원천징수이행상황신고서 (SWTA0101) 자동화

SWTA0101 이동 → 매월/반기 확인 → 사용자 지정 연도/월로 기간 설정 → 조회 → 마감/마감해제.

마감/마감해제 처리 (메뉴 8번 — 사이드바 phase 8):
  - 미마감(버튼 "마감") → 마감 적용 (클릭 → 2단계 모달 → 검증 로그).
  - 이미 마감(버튼 "마감해제") → 마감해제(마감 취소) 후 같은 월로 재조회하여
    새 내용을 다시 불러온 뒤, 재마감을 적용한다. 마감해제 직후 버튼이 "마감"
    으로 전환되는지 검증하며, 재조회 후에도 마감 버튼이 정상 나타나야 재마감을
    진행한다. 어느 단계에서든 상태가 예상과 다르면 RuntimeError 를 발생시켜
    어댑터(wehago_swta.py)가 해당 잡을 실패 처리하도록 한다.

기간 설정:
  - 신고주기: DB report_cycle("매월"/"반기") 우선. 비어있으면 위하고 라디오
    (ground truth, 읽기 전용)에서 읽어 결정 → 어댑터가 DB 에 역충전.
  - 매월: 선택 연/월({year}/{month:02d}). None 이면 compute_target_period() 직전월
  - 반기: 대상 월(GUI year/month 우선, 없으면 현재) 기준 — 6월→당해 상반기(1~6월),
    12월→당해 하반기(7~12월). compute_half_period() 사용.
    ★반기는 6·12월만 실행(그 외 월은 마감 스킵 — 단 라디오 확정값은 역충전).
  - 주기 미확정(DB 공란 + 라디오 판별 불가) → 매월 폴백 금지, RuntimeError(반기
    수임처의 단월 잘못 마감 방지).
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
    """반기 신고의 (연도, 시작월, 종료월)을 유저 입력월 기준으로 반환.

    반기 신고는 연 2회 (유저 입력 월 기준):
      - 6월 입력 → 당해년도 1~6월 (상반기)
      - 12월 입력 → 당해년도 7~12월 (하반기)
    """
    if now.month == 12:
        return now.year, 7, 12
    return now.year, 1, 6


def half_period_target(year, month):
    """반기 마감 대상 시점(datetime)과 비신고월 스킵 여부를 반환.

    GUI year/month 가 주어지면 그 시점, 아니면 현재 시점을 사용한다.
    반기 신고는 6·12월만 해당 → 그 외 월은 skip=True (마감하지 않음).
    Returns: (target: datetime, skip: bool)
    """
    if year is not None and month is not None:
        target = datetime(year, month, 1)
    else:
        target = datetime.now()
    return target, target.month not in (6, 12)


async def _read_close_button(page) -> str | None:
    """마감/마감해제 가시 버튼의 텍스트("마감" / "마감해제")를 읽어 반환.

    WSC_LUXTooltip 래퍼가 있으면 그 안의 버튼을 우선 탐색. 보이지 않는
    (offsetWidth==0) 버튼은 무시한다. 버튼을 찾지 못하면 None.
    """
    return await page.evaluate(r"""() => {
        const selectors = [
            '.WSC_LUXTooltip button.WSC_LUXButton',
            'button.WSC_LUXButton'
        ];
        for (const sel of selectors) {
            for (const btn of document.querySelectorAll(sel)) {
                const text = btn.textContent.trim();
                const norm = text.replace(/\s+/g, '');
                if ((norm === '마감' || norm === '마감해제') && btn.offsetWidth > 0) return norm;
            }
        }
        return null;
    }""")


async def _click_dialog_confirm(page, max_polls: int = 5, interval: float = 0.5) -> str | None:
    """열린 모달(._isDialog / .LUX_basic_dialog)에서 확인 버튼을 폴링 클릭.

    클릭 대상 버튼 텍스트: "확인(enter)" 또는 "확인". 보이지 않는 모달/버튼은 무시.
    클릭에 성공하면 해당 버튼 텍스트를, 아무것도 클릭하지 못하면 None 을 반환.
    """
    for _ in range(max_polls):
        await asyncio.sleep(interval)
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
            return clicked
    return None


async def _click_search_and_dismiss(page) -> None:
    """조회 버튼 클릭 → 대기 → 정보성 모달 정리.

    #Search 영역의 가시 "조회" 버튼을 클릭하고, 로딩 대기(sleep 5) 후
    dismiss_dialogs 와 정보성 게이트 모달(저장된 내용/이전 신고서 등)을
    닫는다. 최초 조회와 마감해제 후 재조회 양쪽에서 공통으로 사용.
    """
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
    # 조회 직후 정보성 모달(저장된 내용 / 이전에 신고한 신고서 등) 공통 1차 닫기.
    await dismiss_dialogs(page)

    # 정보성 게이트 모달 → 확인 (텍스트 단일 매치 → 다중 단어 확장)
    for _ in range(3):
        loaded = await page.evaluate("""() => {
            const FRAGMENTS = ['저장된 내용', '이전에 신고', '신고서가 있', '이미 신고'];
            const sels = ['._isDialog', '.LUX_basic_dialog'];
            for (const sel of sels) {
                for (const el of document.querySelectorAll(sel)) {
                    const cs = window.getComputedStyle(el);
                    if (cs.display === 'none' || el.offsetWidth < 50) continue;
                    if (!FRAGMENTS.some(f => el.textContent.includes(f))) continue;
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
            log("  정보성 모달(저장된 내용/이전 신고서 등) → 확인")
            await asyncio.sleep(2)
        else:
            break

    # 잔여 모달 재처리(마감 버튼이 모달에 가려 렌더 안 되는 것 방지).
    await dismiss_dialogs(page)


async def _apply_close(page) -> str | None:
    """마감 버튼 클릭 → 2단계 모달 처리 → 마감 후 상태 로그.

    미마감 상태(버튼 "마감")에서 마감을 적용한다. 유의사항 안내 모달(1단계)
    과 "마감 완료!" 후속 모달(2단계)을 순차적으로 확인 처리한 뒤, 마감 적용
    후의 버튼 상태를 로그로 남긴다. 미마감 경로와 마감해제 후 재마감 경로
    양쪽에서 재사용.

    Returns: 마감 적용 후 읽은 버튼 텍스트("마감해제" 예상) 또는 None.
    """
    log("  마감 버튼 클릭 (마감 적용)...")
    await page.evaluate("""() => {
        const btns = document.querySelectorAll('button.WSC_LUXButton');
        for (const btn of btns) {
            if (btn.textContent.trim() === '마감' && btn.offsetWidth > 0) { btn.click(); return; }
        }
    }""")

    # 1) 유의사항 안내 모달 → 확인(enter)
    clicked = await _click_dialog_confirm(page, max_polls=15, interval=0.5)
    if clicked:
        log(f"  모달 버튼 클릭: {clicked}")

    # 2) "마감 완료!" 후속 모달 → 확인
    await asyncio.sleep(2)
    clicked = await _click_dialog_confirm(page, max_polls=5)
    if clicked:
        log(f"  후속 모달 버튼 클릭: {clicked}")
        await asyncio.sleep(1)

    # 마감 후 상태 확인 (현재 정책: 검증 없이 로그만)
    await asyncio.sleep(1)
    new_btn = await _read_close_button(page)
    log(f"  마감 후 버튼 상태: {new_btn}")
    return new_btn


async def _wait_close_button(page, rounds: int = 8, interval: float = 0.5) -> str | None:
    """마감/마감해제 가시 버튼이 렌더될 때까지 폴링 대기 후 텍스트 반환.

    모달이 남아 버튼이 가려진 경우 dismiss_dialogs 로 정리하며 재시도한다.
    rounds 회 시도해도 버튼을 읽지 못하면 None 을 반환한다(호출부에서 처리).
    """
    for _ in range(rounds):
        btn_text = await _read_close_button(page)
        if btn_text:
            return btn_text
        await dismiss_dialogs(page)
        await asyncio.sleep(interval)
    return None


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
        # 반기 신고는 연 2회: 6월→상반기(당해 1~6월) / 12월→하반기(당해 7~12월).
        # 대상 시점: GUI year/month 우선, 없으면 현재. ★6·12월만 실행, 나머지 스킵.
        target, skip = half_period_target(year, month)
        if skip:
            log(f"[SWTA0101] 반기 → 비신고월({target.month}월) 마감 스킵 (반기는 6·12월만)")
            # 라디오로 확정한 주기값은 역충전 허용(어댑터가 used_cycle 로 처리),
            # 마감(기간설정·조회·마감)은 하지 않고 종료.
            return "반기"
        y, sm, em = compute_half_period(target)
        half = "상반기(01~06)" if sm == 1 else "하반기(07~12)"
        log(f"[SWTA0101] 반기 → {y}년 {sm:02d}월 ~ {em:02d}월 ({half})")
        await set_period_fields(page, y, sm, em)
    else:
        # 신고주기 미확정(DB 공란 + 라디오 판별 불가) → 매월 폴밭 금지.
        # 반기 수임처의 단월 잘못 마감을 막기 위해 예외 발생(잡 실패 처리).
        raise RuntimeError(
            "[SWTA0101] 신고주기 확정 불가(DB 공란 + 라디오 판별 실패). "
            "마감 중단 — 수임처 주기(매월/반기) 확인 후 재실행하세요."
        )

    # [4] 조회 버튼 클릭 → 정보성 모달 정리 (_click_search_and_dismiss 헬퍼)
    await _click_search_and_dismiss(page)

    # [5] 마감/마감해제 버튼 처리 — 모달이 닫힌 후 버튼 렌더를 폴링 대기.
    log("[SWTA0101] 마감 상태 확인...")
    btn_text = await _wait_close_button(page)

    if btn_text == "마감":
        # 미마감 → 마감 적용
        await _apply_close(page)
    elif btn_text == "마감해제":
        # 이미 마감 → 마감해제 → (같은 월) 재조회 → 재마감.
        # 마감해제만 적용하고 끝내지 않고, 새 내용을 다시 불러와 마감을 다시 건다.
        log("  마감해제 버튼 클릭 (마감 해제 적용)...")
        await page.evaluate("""() => {
            const btns = document.querySelectorAll('button.WSC_LUXButton');
            for (const btn of btns) {
                if (btn.textContent.trim() === '마감해제' && btn.offsetWidth > 0) { btn.click(); return; }
            }
        }""")

        # 마감 적용과 동일한 2단계 모달 패턴으로 확인 처리
        # 1) 확인 모달 → 확인(enter) / 확인
        clicked = await _click_dialog_confirm(page, max_polls=15, interval=0.5)
        if clicked:
            log(f"  모달 버튼 클릭: {clicked}")

        # 2) 후속 모달 → 확인
        await asyncio.sleep(2)
        clicked = await _click_dialog_confirm(page, max_polls=5)
        if clicked:
            log(f"  후속 모달 버튼 클릭: {clicked}")
            await asyncio.sleep(1)

        # 마감해제 검증: 버튼이 "마감해제" → "마감" 으로 전환되어야 함.
        # 전환되지 않으면 모달이 정상 처리되지 않은 것이므로 잡 실패로 처리한다.
        await asyncio.sleep(1)
        new_btn = await _read_close_button(page)
        if new_btn != "마감":
            raise RuntimeError(
                f"마감해제 확인 실패: 버튼이 '{new_btn}' (예상 '마감'). "
                f"모달이 정상 처리되지 않았을 수 있음."
            )
        log(f"  마감해제 완료 후 버튼 상태: {new_btn}")

        # [5-A] 같은 월로 재조회 — 마감 해제된 새 내용을 불러온다.
        log("  마감해제 완료 — 해당 월로 재조회 후 재마감 진행...")
        await _click_search_and_dismiss(page)

        # [5-B] 재조회 후 마감 버튼이 다시 렌더될 때까지 폴링 대기
        new_btn = await _wait_close_button(page)
        if new_btn != "마감":
            # 재조회 후에도 마감 버튼이 나타나지 않거나 상태가 예상과 다르면
            # 마감을 진행할 수 없으므로 잡 실패로 처리한다.
            raise RuntimeError(
                f"재조회 후 마감 버튼 상태가 '{new_btn}' (예상 '마감'). "
                f"재마감 불가 — 마감해제가 정상 반영되지 않았을 수 있음."
            )

        # [5-C] 재마감 적용 (미마감 경로와 동일 로직)
        log("  재마감 진행 (재조회된 내용으로 마감 적용)...")
        await _apply_close(page)
    else:
        # 마감/마감해제 버튼이 예상과 다르게 감지됨(잘못된 기간/모달 잔여 등).
        # 가시 버튼 영역을 덤프해 원인 파악(라이브 튜닝).
        log(f"  마감 버튼 상태: {btn_text} (예상 밖 — 버튼 영역 진단 덤프)")
        try:
            import os
            import json as _json
            from src.config import APP_DATA_DIR
            btns = await page.evaluate("""() => {
                const out = [];
                document.querySelectorAll('button.WSC_LUXButton, .WSC_LUXTooltip button, button').forEach(b => {
                    const t = b.textContent.trim();
                    if (t && b.offsetWidth > 0) out.push({text: t.slice(0, 40), class: b.className});
                });
                return out.slice(0, 40);
            }""")
            os.makedirs(APP_DATA_DIR, exist_ok=True)
            _dbg = os.path.join(APP_DATA_DIR, "swta_closebtn_debug.txt")
            with open(_dbg, "w", encoding="utf-8") as _f:
                _f.write(f"_read_close_button returned: {btn_text!r}\n\n")
                _f.write(_json.dumps(btns, ensure_ascii=False, indent=2))
            log(f"    [진단] 마감 버튼 영역 덤프 → {_dbg}")
        except Exception as _e:
            log(f"    [진단] 마감 버튼 덤프 실패: {_e}")
        # 마감/마감해제 버튼 미발견 → 조용히 성공(false-success) 처리 금지.
        # 잘못된 기간(매월/반기 불일치)·잔여 모달·미렌더링 등이 원인. loud 실패로
        # 어댑터가 잡을 수 있게 하고, 잘못된 주기의 DB 역충전도 차단한다.
        raise RuntimeError(
            f"[SWTA0101] 마감/마감해제 버튼을 찾지 못했습니다 (current={btn_text!r}). "
            f"잘못된 기간(매월/반기 불일치), 잔여 모달, 또는 미렌더링 상태 — "
            f"모달 확인 후 재조회 필요."
        )

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
