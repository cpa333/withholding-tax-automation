"""원천징수전자신고 (SWER0101) 자동화

SWER0101 이동 → 지급기간 설정 → 수임처 선택 → 제작(F4) →
비밀번호 입력 → 전자신고 파일 제작 → WehagoNTS 폴더 선택 → 파일 저장.

지급기간 설정:
  - year/month가 전달되면 해당 연월을 지급기간에 반영
  - None이면 compute_target_period()로 직전월 산출
  - set_period_fields()에서 3회 재시도 검증으로 페이지 기본 연도 불일치 자동 복구

사전 조건:
- page가 이미 SmartA 급여 페이지에 있어야 함
- Chrome CDP 모드(port 9223) 실행 상태
"""
import asyncio
import json
import sys

from src.automation.wehago._common import (
    log, dismiss_dialogs, goto_menu_page, set_period_fields,
    click_codehelp_confirm, close_warning_overlay, compute_target_period,
    click_menu,
)
from src.automation.wehago._nts import select_nts_folder
from src.utils.human import net_mult


async def set_password_and_submit(page, password):
    """LSinput 컴포넌트 비밀번호 입력 + 전자신고 파일 제작

    native setter로 input.value 설정 + fakeinput 직접 조작.
    비밀번호 규칙 경고 시 확인 클릭 → 재입력 → 재제출 (최대 3회).
    """
    for attempt in range(1, 4):
        await close_warning_overlay(page, "최소 8~15자리")
        await asyncio.sleep(0.3)

        # native setter + fakeinput 조작
        set_result = await page.evaluate("""(pwd) => {
            const dialogs = document.querySelectorAll('._isDialog');
            for (const d of dialogs) {
                if (d.offsetWidth < 100 || !d.textContent.includes('변환파일 비밀번호')) continue;
                const inp = d.querySelector('input.LSinput');
                const fake = d.querySelector('.fakeinput');
                if (!inp || !fake) return 'no elements';

                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value'
                ).set;
                setter.call(inp, pwd);
                fake.classList.remove('placeholder');
                fake.textContent = pwd;
                inp.dispatchEvent(new Event('input', { bubbles: true }));
                inp.dispatchEvent(new Event('change', { bubbles: true }));
                return 'ok';
            }
            return 'no dialog';
        }""", password)
        if set_result != "ok":
            log(f"    failed (attempt {attempt}): {set_result}")
            await asyncio.sleep(1)
            continue
        await asyncio.sleep(0.3)

        # 검증
        val = await page.evaluate("""() => {
            const dialogs = document.querySelectorAll('._isDialog');
            for (const d of dialogs) {
                if (d.offsetWidth < 100 || !d.textContent.includes('변환파일 비밀번호')) continue;
                const inp = d.querySelector('input.LSinput');
                const fake = d.querySelector('.fakeinput');
                return {val: inp?.value, fake: fake?.textContent.trim()};
            }
            return null;
        }""")

        if not val or val.get("fake", "") != password or val.get("val", "") != password:
            log(f"    mismatch (attempt {attempt}): {json.dumps(val, ensure_ascii=False)}")
            continue

        log(f"    password OK (attempt {attempt})")

        # 전자신고 파일 제작(Enter) 클릭
        log("    전자신고 파일 제작(Enter) 클릭...")
        await page.evaluate("""() => {
            const btns = document.querySelectorAll('button');
            for (const btn of btns) {
                if (btn.textContent.trim() === '전자신고 파일 제작(Enter)' && btn.offsetWidth > 0) {
                    btn.click(); return;
                }
            }
        }""")
        await asyncio.sleep(net_mult(3.0))

        # 비밀번호 규칙 경고
        pwd_warning = await page.evaluate("""() => {
            const all = document.querySelectorAll('*');
            for (const el of all) {
                try {
                    const cs = window.getComputedStyle(el);
                    if (cs.position !== 'fixed' || cs.display === 'none'
                        || parseInt(cs.zIndex) < 1000 || el.offsetWidth < 50) continue;
                    const txt = el.textContent.trim();
                    if (txt.includes('비밀번호는 최소 8~15자리')) return txt.substring(0, 200);
                } catch(e) {}
            }
            return null;
        }""")
        if pwd_warning:
            log(f"    비밀번호 규칙 경고 감지 → 확인 클릭 후 재시도")
            await close_warning_overlay(page, "최소 8~15자리")
            await asyncio.sleep(0.5)
            continue

        # 기타 에러 확인
        has_error = await page.evaluate("""() => {
            const all = document.querySelectorAll('*');
            for (const el of all) {
                try {
                    const cs = window.getComputedStyle(el);
                    if (cs.position !== 'fixed' || cs.display === 'none'
                        || parseInt(cs.zIndex) < 1000 || el.offsetWidth < 50) continue;
                    const txt = el.textContent.trim();
                    if (txt.includes('전자신고 파일 제작') || txt.includes('홈택스 ID')) continue;
                    if ((txt.includes('오류') || txt.includes('에러')
                        || txt.includes('실패')) && txt.length < 300) return txt.substring(0, 100);
                } catch(e) {}
            }
            return null;
        }""")
        if has_error:
            log(f"    error: {has_error[:60]}")
            continue

        return True

    log("    FAILED after 3 attempts")
    return False


async def run_swer0101(page, password, nts_folder="원천징수전자신고",
                       year: int = None, month: int = None,
                       save_dir: str = None):
    """원천징수전자신고 전체 자동화

    Args:
        page: SmartA 페이지에 위치한 Playwright page
        password: 전자신고 파일 비밀번호
        nts_folder: WehagoNTS 저장 폴더명 (save_dir=None일 때 사용)
        year: 귀속 연도 (None이면 compute_target_period로 산출)
        month: 귀속 월 (None이면 compute_target_period로 산출)
        save_dir: 파일 저장 절대경로 (None이면 nts_folder 기반 바탕화면에 저장)
    """
    # [0] SPA 라우팅 초기화: SWSA0101 사이드바 클릭
    log("[SWER0101] 급여자료입력(SWSA0101) 사이드바 클릭 (SPA 라우팅 초기화)...")
    await click_menu(page, "SWSA0101")
    await asyncio.sleep(net_mult(3.0))
    await dismiss_dialogs(page)

    # [1] SWER0101 이동 (URL 해시 교체)
    log("[SWER0101] 원천징수전자신고 이동...")
    await goto_menu_page(page, "SWER0101")
    await asyncio.sleep(net_mult(3.0))

    # 모달 닫기 (제출자등록 안내 등)
    log("[SWER0101] 모달 확인...")
    await dismiss_dialogs(page)
    # z-index overlay 추가 정리
    for _ in range(5):
        closed = await page.evaluate("""() => {
            const all = document.querySelectorAll('*');
            for (const el of all) {
                try {
                    const cs = window.getComputedStyle(el);
                    if (cs.position !== 'fixed' || cs.display === 'none'
                        || parseInt(cs.zIndex) < 1000 || el.offsetWidth < 100) continue;
                    const txt = el.textContent.trim();
                    if (txt.length === 0) continue;
                    const btns = el.querySelectorAll('button');
                    for (const btn of btns) {
                        const t = btn.textContent.trim();
                        if ((t === '확인' || t === '닫기' || t === 'X') && btn.offsetWidth > 0) {
                            btn.click(); return t;
                        }
                    }
                } catch(e) {}
            }
            return null;
        }""")
        if not closed:
            break
        log(f"    overlay closed ({closed})")
        await asyncio.sleep(0.5)

    # [2] 지급기간 설정
    if year is None or month is None:
        year, month = compute_target_period()
    log(f"[SWER0101] 지급기간: {year}년 {month:02d}월")
    await set_period_fields(page, year, month, month)

    # [3] 수임처 아이콘 → 코드도움 확인
    log("[SWER0101] 수임처 아이콘 클릭...")
    await page.evaluate("""() => {
        const items = document.querySelectorAll('#SearchMain .item');
        for (const item of items) {
            const title = item.querySelector('.item_title, strong');
            if (!title || !title.textContent.includes('수임처')) continue;
            const btns = item.querySelectorAll('button.WSC_LUXButton');
            for (const btn of btns) {
                const r = btn.getBoundingClientRect();
                if (r.width > 0 && r.height > 0 && !btn.textContent.trim()) {
                    btn.click(); return;
                }
            }
        }
    }""")
    await asyncio.sleep(net_mult(2.0))
    confirmed = await click_codehelp_confirm(page)
    log(f"  코드도움: {confirmed}")
    await asyncio.sleep(net_mult(2.0))

    # [4] 제작(F4) 버튼 클릭 — Playwright real click (JS click skips disabled buttons)
    log("[SWER0101] 제작(F4) 클릭...")
    try:
        f4_btn = page.locator('button.WSC_LUXButton:has-text("제작(F4)")')
        if await f4_btn.count() > 0:
            await f4_btn.first.click(timeout=5000)
            log("  clicked (Playwright)")
        else:
            log("  F4 button not found, trying JS fallback...")
            clicked_f4 = await page.evaluate("""() => {
                const all = document.querySelectorAll('button.WSC_LUXButton');
                for (const btn of all) {
                    if (btn.textContent.trim() === '제작(F4)') {
                        const r = btn.getBoundingClientRect();
                        if (r.y < 200 && r.width > 0) { btn.click(); return true; }
                    }
                }
                return false;
            }""")
            log(f"  clicked (JS): {clicked_f4}")
    except Exception as e:
        log(f"  Playwright click error: {e}")

    # [5] 모달 대기: 참고사항 vs 비밀번호
    log("[SWER0101] 모달 대기...")
    modal_found = False
    _f4_polls = 20
    for i in range(_f4_polls):
        await asyncio.sleep(net_mult(1.0))
        found = await page.evaluate("""() => {
            const dialogs = document.querySelectorAll('._isDialog');
            for (const d of dialogs) {
                if (d.offsetWidth > 100 && d.textContent.includes('변환파일 비밀번호'))
                    return 'pwd';
                if (d.offsetWidth > 100 && d.textContent.includes('참고사항'))
                    return 'ref';
            }
            return null;
        }""")
        if found:
            log(f"  [{i+1}s] modal: {found}")
            modal_found = True
            if found == "pwd":
                break
            elif found == "ref":
                log("  참고사항 모달 닫기...")
                await dismiss_dialogs(page)

    if not modal_found:
        # 느린 네트워크에서 F4 후 모달이 늦게 떠 폴링 예산을 초과한 경우,
        # 조용히 return 하면 어댑터가 성공으로 오인(잘못된 전자신고 파일 누락)하므로
        # loud 실패로 처리한다(wehago_swer.py try/except → fail_step).
        raise RuntimeError(
            "[SWER0101] 제작(F4) 후 변환파일 비밀번호/참고사항 모달이 "
            f"{_f4_polls}회 폴링 내 미출현 — 네트워크 지연 또는 F4 처리 실패 의심. "
            "잡을 실패로 처리합니다."
        )

    # 비밀번호 모달 ready 대기
    _pwd_polls = 15
    for i in range(_pwd_polls):
        await asyncio.sleep(net_mult(1.0))
        if await page.evaluate("""() => {
            const dialogs = document.querySelectorAll('._isDialog');
            for (const d of dialogs) {
                if (d.offsetWidth > 100 && d.textContent.includes('변환파일 비밀번호'))
                    return true;
            }
            return false;
        }"""):
            log(f"  [{i+1}s] 비밀번호 modal ready")
            break
    else:
        # 모달 ready 미달 시 loud 실패(조용한 성공 처리 방지).
        raise RuntimeError(
            "[SWER0101] 변환파일 비밀번호 모달이 ready 상태에 도달하지 않음 "
            f"({_pwd_polls}회 폴링 초과) — 네트워크 지연 의심. 잡을 실패로 처리합니다."
        )

    await asyncio.sleep(net_mult(2.0))

    # [6] 비밀번호 입력 + 전자신고 파일 제작
    log("[SWER0101] 비밀번호 입력 + 전자신고 파일 제작...")
    success = await set_password_and_submit(page, password)
    if not success:
        # 비밀번호 제출 실패(규칙 미충족/처리 실패)도 loud 실패로 처리 —
        # 조용히 return 시 어댑터가 성공으로 오인(전자신고 파일 미산출 누락).
        raise RuntimeError(
            "[SWER0101] 변환파일 비밀번호 제출 실패(3회 재시도 후 실패) — "
            "비밀번호 규칙 미충족 또는 처리 실패. 잡을 실패로 처리합니다."
        )

    # [7] WehagoNTS 폴더 선택 + 파일 저장
    log("[SWER0101] WehagoNTS 폴더 선택...")
    loop = asyncio.get_event_loop()
    if save_dir:
        nts_ok = await loop.run_in_executor(None, select_nts_folder, None, save_dir)
    else:
        nts_ok = await loop.run_in_executor(None, select_nts_folder, nts_folder)

    if nts_ok:
        log("[SWER0101] 완료 - 전자신고 파일 저장 성공")
    else:
        log("[SWER0101] WARNING: NTS 폴더 선택 실패")


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
        password = input("전자신고 비밀번호: ").strip()
        nts_folder = input("NTS 폴더명 (기본=원천징수전자신고): ").strip() or "원천징수전자신고"

        if not company or not password:
            print("수임처 이름과 비밀번호가 필요합니다.")
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

            await run_swer0101(page, password, nts_folder)

    asyncio.run(_main())
