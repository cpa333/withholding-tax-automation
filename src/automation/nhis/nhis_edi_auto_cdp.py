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
    select_firm_by_index, close_firm_popup,
    run_single_firm_workflow,
)


def print_header():
    print("\n" + "=" * 55)
    print("  국민건강보험 EDI 자동화")
    print("=" * 55)


def print_menu():
    print("\n" + "-" * 55)
    print("  1. 수임사업장 선택 (목록에서 선택)")
    print("  2. 전체 수임사업장 목록 조회")
    print("  3. 수임처 PDF 다운로드 (받은문서 → 가입자고지내역서)")
    print("  4. 전체 자동 (수임처별 워크플로우 반복)")
    print("  0. 종료")
    print("-" * 55)


async def handle_select_workplace(page, context):
    """수임사업장 선택 대화형 처리"""
    popup = await open_firm_selector(page, context)
    if not popup:
        return

    await asyncio.sleep(2)
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

    log(f"\n  현재 페이지 {len(result)}개:")
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


async def handle_download_pdf(page, context):
    """현재 선택된 수임처의 PDF 다운로드"""
    # 현재 수임처명 확인
    firm_name = await page.evaluate("""() => {
        var text = document.body.innerText;
        var m = text.match(/수임 사업자명\\s*:\\s*(.+)/);
        return m ? m[1].trim() : null;
    }""")
    if not firm_name:
        log("  ERROR: 수임처가 선택되지 않았습니다. 먼저 메뉴 1로 선택하세요.")
        return

    log(f"  수임처: {firm_name}")
    await run_single_firm_workflow(page, context, firm_name)


async def run_full_auto(page, context):
    """전체 자동 모드: 수임처를 하나씩 선택하며 워크플로우 수행"""
    completed = 0

    while True:
        log(f"\n{'='*55}")
        log("  수임사업장선택 모달 열기...")
        popup = await open_firm_selector(page, context)
        if not popup:
            log("  ERROR: 사업장 선택 팝업을 열지 못했습니다.")
            return

        await asyncio.sleep(2)

        # 첫 페이지 목록 표시
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

        log(f"\n  사업장 목록 ({len(result)}개):")
        for f in result[:10]:
            log(f"    {f['no']}. [{f['mgmtNo']}] {f['name']}")
        if len(result) > 10:
            log(f"    ... 외 {len(result) - 10}개")

        log(f"\n  완료: {completed}개 | 목록에 없으면 이름 직접 입력 가능")

        # 수임처 선택 루프
        firm_name = None
        while True:
            choice = input("\n  수임처 번호 또는 이름 (0=종료): ").strip()
            if not choice or choice == "0":
                await close_firm_popup(context, popup)
                log(f"\n  총 {completed}개 수임처 자동화 완료. 종료.")
                return

            # 번호로 선택 시도
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(result):
                    firm_name = result[idx]["name"]
                    break
            except ValueError:
                pass

            # 이름 일부 매칭
            matches = [f for f in result if choice in f["name"]]
            if len(matches) == 1:
                firm_name = matches[0]["name"]
                break
            elif len(matches) > 1:
                log(f"\n  '{choice}'와(과) 일치하는 사업장 {len(matches)}개:")
                for j, m in enumerate(matches):
                    log(f"    {j + 1}. [{m['mgmtNo']}] {m['name']}")
                sub = input("  선택 (0=취소): ").strip()
                try:
                    sub_idx = int(sub) - 1
                    if 0 <= sub_idx < len(matches):
                        firm_name = matches[sub_idx]["name"]
                        break
                except ValueError:
                    pass
                continue

            # 직접 이름으로 검색 시도
            firm_name = choice
            log(f"  '{choice}' — 표시 목록에 없음, 이름으로 검색합니다.")
            break

        # 사업장 선택
        ok = await select_firm(popup, firm_name)
        if not ok:
            log(f"  '{firm_name}' 사업장을 찾지 수 없습니다. 다시 입력해주세요.")
            await close_firm_popup(context, popup)
            continue

        await asyncio.sleep(3)
        await close_firm_popup(context, popup)

        log(f"\n{'='*55}")
        log(f"  [{completed + 1}] {firm_name}")
        log(f"{'='*55}")

        try:
            ok = await run_single_firm_workflow(page, context, firm_name)
            if ok:
                completed += 1
                log(f"\n  {firm_name} 처리 완료. ({completed}개 완료)")
            else:
                log(f"\n  {firm_name} 처리 실패.")
        except Exception as e:
            log(f"  ERROR: {firm_name} 처리 실패 - {e}")
            import traceback
            traceback.print_exc()


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
            browser, context, page = await connect_page(p)
        except Exception as e:
            log(f"ERROR: Chrome 연결 실패 - {e}")
            return

        # 이미 NHIS EDI 페이지면 재로딩하지 않음 (팝업 재생성 방지)
        if "edi.nhis.or.kr" not in page.url:
            await page.goto(NHIS_EDI_URL, wait_until="domcontentloaded", timeout=30000)

        # 팝업 먼저 닫기 — popup 탭이 pages[0]일 수 있어 로그인 인식 방해
        page = await close_popups(context)
        await page.bring_to_front()

        if not await wait_for_login(page):
            log("로그인 실패")
            return

        log("로그인 확인됨. 자동화 시작.\n")

        # Phase 2: 모드 선택
        log("실행 모드 선택:")
        log("  1. 전체 자동 (수임처별 전체 워크플로우)")
        log("  2. 대화형 메뉴")
        mode = input("\n선택 > ").strip()

        if mode == "1":
            await run_full_auto(page, context)
        else:
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

        elif choice == "3":
            try:
                await handle_download_pdf(page, context)
            except Exception as e:
                log(f"ERROR: {e}")
                import traceback
                traceback.print_exc()

        elif choice == "4":
            try:
                await run_full_auto(page, context)
            except Exception as e:
                log(f"ERROR: {e}")
                import traceback
                traceback.print_exc()

        elif choice == "0":
            log("종료합니다.")
            break

        else:
            log("잘못된 선택입니다. 0~4 중 하나를 입력하세요.")


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
