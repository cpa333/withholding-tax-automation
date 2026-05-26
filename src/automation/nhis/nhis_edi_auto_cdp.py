"""국민건강보험 EDI 자동화 — CDP 기반 메인 진입점

Usage:
    python -m src.automation.nhis.nhis_edi_auto_cdp
    python src/automation/nhis/nhis_edi_auto_cdp.py

사용법:
    1. Chrome이 CDP 모드(포트 9223)로 실행 중이어야 함
    2. 공동인증서 로그인은 사용자가 직접 수행 (Human-in-the-loop)
    3. 로그인 후 수임사업장 선택 → 자동화 진행
"""
import asyncio
import sys
import os

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from playwright.async_api import async_playwright
from src.utils.chrome_cdp import launch_chrome, connect_page as cdp_connect
from src.automation.nhis._common_edi import (
    log, NHIS_EDI_URL, NHIS_EDI_MAIN,
    connect_page, wait_for_login, close_popups,
    open_firm_selector, list_all_firms, select_firm,
    select_firm_by_index, search_firm, close_firm_popup,
)


def print_header():
    print("\n" + "=" * 55)
    print("  국민건강보험 EDI 자동화")
    print("=" * 55)


def print_menu():
    print("\n" + "-" * 55)
    print("  1. 수임사업장 선택 (목록에서 선택)")
    print("  2. 전체 수임사업장 목록 조회")
    print("  0. 종료")
    print("-" * 55)


async def handle_select_workplace(page, context):
    """수임사업장 선택 대화형 처리"""
    popup = await open_firm_selector(page, context)
    if not popup:
        return

    # 첫 페이지 목록 표시
    await asyncio.sleep(2)
    first_page = await list_all_firms.__wrapped__(popup) if hasattr(list_all_firms, '__wrapped__') else []
    result = await popup.evaluate("""() => {
        const rows = document.querySelectorAll('table.list tbody tr');
        const firms = [];
        rows.forEach(tr => {
            const tds = tr.querySelectorAll('td');
            if (tds.length >= 5 && /^\\d+$/.test(tds[1].textContent.trim())) {
                firms.push({
                    no: tds[1].textContent.trim(),
                    name: tds[2].textContent.trim(),
                    mgmtNo: tds[3].textContent.trim(),
                });
            }
        });
        return firms;
    }""")

    log(f"\n  총 {(await popup.evaluate('() => { const m = document.body.innerText.match(/총 (\\d+) 건/); return m ? m[1] : "0"; }'))}개 사업장")
    log(f"  현재 페이지 {len(result)}개:")
    for f in result[:10]:
        log(f"    {f['no']}. [{f['mgmtNo']}] {f['name']}")
    if len(result) > 10:
        log(f"    ... 외 {len(result) - 10}개")

    choice = input("\n  사업장명 또는 번호 입력 (0=취소): ").strip()
    if not choice or choice == "0":
        await close_firm_popup(context, popup)
        return

    # 번호로 선택 시도
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(result):
            ok = await select_firm_by_index(popup, idx)
            if ok:
                await asyncio.sleep(3)
                await close_firm_popup(context, popup)
                return
    except ValueError:
        pass

    # 이름으로 선택
    ok = await select_firm(popup, choice)
    if ok:
        await asyncio.sleep(3)
    await close_firm_popup(context, popup)


async def handle_list_all_workplaces(page, context):
    """전체 수임사업장 목록 조회"""
    popup = await open_firm_selector(page, context)
    if not popup:
        return

    firms = await list_all_firms(popup)
    log(f"\n  총 {len(firms)}개 수임사업장:")
    for f in firms:
        log(f"    {f['no']}. [{f['mgmtNo']}] {f['name']}")

    input("\n  Enter를 눌러 팝업을 닫습니다...")
    await close_firm_popup(context, popup)


async def main():
    print_header()

    # Phase 1: Chrome 실행 + 연결
    log("\n[1/3] Chrome 실행...")
    result = launch_chrome(url=NHIS_EDI_URL)
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

        # NHIS EDI 페이지로 이동
        await page.goto(NHIS_EDI_URL, wait_until="domcontentloaded", timeout=30000)
        await page.bring_to_front()

        if not await wait_for_login(page):
            log("로그인 실패")
            return

        log("로그인 확인됨. 자동화 시작.\n")

        # 팝업 닫기
        page = await close_popups(context)

        # Phase 2: 대화형 메뉴
        await run_interactive(page, context)


async def run_interactive(page, context):
    """대화형 메뉴 모드"""
    while True:
        print_menu()
        choice = input("선택 > ").strip()

        if choice == "1":
            try:
                await handle_select_workplace(page, context)
            except Exception as e:
                log(f"ERROR: {e}")
                import traceback
                traceback.print_exc()

        elif choice == "2":
            try:
                await handle_list_all_workplaces(page, context)
            except Exception as e:
                log(f"ERROR: {e}")
                import traceback
                traceback.print_exc()

        elif choice == "0":
            log("종료합니다.")
            break

        else:
            log("잘못된 선택입니다. 1, 2, 0 중 하나를 입력하세요.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n프로그램을 종료하려면 Enter를 누르세요...")
        input()
