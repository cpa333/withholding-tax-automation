"""국민연금 EDI 자동화 — CDP 기반 메인 진입점

Usage:
    python -m src.automation.nps.nps_auto_cdp
    python src/automation/nps/nps_auto_cdp.py

사용법:
    1. Chrome이 CDP 모드(포트 9223)로 실행 중이어야 함
    2. 공동인증서 로그인은 사용자가 직접 수행 (Human-in-the-loop)
    3. 로그인 후 사업장 선택 → 자동화 진행
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
from src.automation.nps._common import (
    log, NPS_URL, connect_page, wait_for_login, ensure_login_page,
    open_workplace_selector, select_workplace, select_workplace_by_index,
    list_workplaces, navigate_to_decision_details, open_decision_detail,
    click_detail_tab, output_with_full_ssn, download_pdf_from_preview,
    save_excel, save_integrated, process_tab_download, switch_workplace,
    TAB_MEMBER, TAB_RETRO, TAB_GOVT,
)


def print_header():
    print("\n" + "=" * 55)
    print("  국민연금 EDI 자동화")
    print("=" * 55)


def print_menu():
    print("\n" + "-" * 55)
    print("  1. 사업장 선택 (목록에서 선택)")
    print("  2. 사업장 전체 목록 조회")
    print("  3. 국민연금보험료 결정내역 이동")
    print("  4. 결정내역 2차 상세 진입 (이번 달)")
    print("  5. 가입자내역 탭 + PDF 다운로드")
    print("  6. 엑셀저장")
    print("  7. 소급분내역 PDF+엑셀")
    print("  8. 전체 탭 자동 처리 (가입자/소급분/국고지원)")
    print("  9. 사업장전환")
    print("  0. 종료")
    print("-" * 55)


async def handle_select_workplace(page):
    """사업장 선택 대화형 처리"""
    # 사업장 선택 모달 열기
    log("사업장 선택 모달 열기...")
    await open_workplace_selector(page)
    await asyncio.sleep(2)

    # 현재 목록 표시
    workplaces = await list_workplaces(page)
    if not workplaces:
        log("  사업장 목록을 불러오지 못했습니다.")
        return

    log(f"\n  총 {len(workplaces)}개 사업장:")
    for wp in workplaces[:10]:
        log(f"    {wp['index'] + 1}. [{wp['number']}] {wp['name']}")
    if len(workplaces) > 10:
        log(f"    ... 외 {len(workplaces) - 10}개")

    choice = input("\n  사업장명 또는 번호 입력 (0=취소): ").strip()
    if not choice or choice == "0":
        return

    # 번호로 선택 시도
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(workplaces):
            await select_workplace_by_index(page, idx)
            return
    except ValueError:
        pass

    # 이름으로 선택
    await select_workplace(page, choice)


async def main():
    print_header()

    # ═══ Phase 1: Chrome 실행 + 연결 ═══
    log("\n[1/3] Chrome 실행...")
    result = launch_chrome(url=NPS_URL)
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

        # NPS EDI 페이지로 이동
        await page.goto(NPS_URL, wait_until="domcontentloaded", timeout=30000)
        await page.bring_to_front()

        if not await wait_for_login(page):
            log("로그인 실패")
            return

        log("로그인 확인됨. 자동화 시작.\n")

        # ═══ Phase 2: 메뉴 루프 ═══
        while True:
            print_menu()
            choice = input("선택 > ").strip()

            if choice == "1":
                try:
                    await handle_select_workplace(page)
                except Exception as e:
                    log(f"ERROR: {e}")
                    import traceback
                    traceback.print_exc()

            elif choice == "2":
                try:
                    await open_workplace_selector(page)
                    workplaces = await list_workplaces(page)
                    if workplaces:
                        log(f"\n  총 {len(workplaces)}개 사업장:")
                        for wp in workplaces:
                            log(f"    {wp['index'] + 1}. [{wp['number']}] {wp['name']}")
                    else:
                        log("  사업장 목록을 불러오지 못했습니다.")
                except Exception as e:
                    log(f"ERROR: {e}")

            elif choice == "3":
                try:
                    await navigate_to_decision_details(page)
                except Exception as e:
                    log(f"ERROR: {e}")
                    import traceback
                    traceback.print_exc()

            elif choice == "4":
                try:
                    await open_decision_detail(page)
                except Exception as e:
                    log(f"ERROR: {e}")
                    import traceback
                    traceback.print_exc()

            elif choice == "5":
                try:
                    log("가입자내역 탭 이동...")
                    await click_detail_tab(page, TAB_MEMBER)
                    await output_with_full_ssn(page)

                    from datetime import datetime
                    now = datetime.now()
                    filename = f"국민연금보험료_결정내역_{now.strftime('%Y%m')}"
                    save_dir = os.path.join(
                        os.path.expanduser("~"), "Desktop",
                        f"주식회사_제이에스_국민연금",
                    )
                    await download_pdf_from_preview(context, save_dir, filename)
                except Exception as e:
                    log(f"ERROR: {e}")
                    import traceback
                    traceback.print_exc()

            elif choice == "6":
                try:
                    from datetime import datetime
                    now = datetime.now()
                    save_dir = os.path.join(
                        os.path.expanduser("~"), "Desktop",
                        f"주식회사_제이에스_국민연금",
                    )
                    filename = f"국민연금보험료_결정내역_{now.strftime('%Y%m')}_엑셀"
                    await save_excel(page, context, save_dir, filename)
                except Exception as e:
                    log(f"ERROR: {e}")
                    import traceback
                    traceback.print_exc()

            elif choice == "7":
                try:
                    save_dir = os.path.join(
                        os.path.expanduser("~"), "Desktop",
                        f"주식회사_제이에스_국민연금",
                    )
                    result = await process_tab_download(
                        page, context, save_dir,
                        tab_index=TAB_RETRO,
                        tab_label="소급분내역",
                        grid_suffix="grdList3",
                    )
                    if result["skipped"]:
                        log("소급분내역 데이터 없음, 스킵")
                except Exception as e:
                    log(f"ERROR: {e}")
                    import traceback
                    traceback.print_exc()

            elif choice == "8":
                try:
                    save_dir = os.path.join(
                        os.path.expanduser("~"), "Desktop",
                        f"주식회사_제이에스_국민연금",
                    )
                    tabs = [
                        (TAB_MEMBER, "가입자내역", "grdList2"),
                        (TAB_RETRO, "소급분내역", "grdList3"),
                        (TAB_GOVT, "국고지원내역", "grdList4"),
                    ]
                    for tab_idx, label, grid_sfx in tabs:
                        result = await process_tab_download(
                            page, context, save_dir, tab_idx, label, grid_sfx,
                        )
                        if result["skipped"]:
                            log(f"  {label} 스킵 (데이터 없음)")
                        await asyncio.sleep(1)
                    log("전체 탭 처리 완료")
                except Exception as e:
                    log(f"ERROR: {e}")
                    import traceback
                    traceback.print_exc()

            elif choice == "9":
                try:
                    name = input("  전환할 사업장명 (0=취소): ").strip()
                    if not name or name == "0":
                        pass
                    else:
                        await switch_workplace(page, name)
                except Exception as e:
                    log(f"ERROR: {e}")
                    import traceback
                    traceback.print_exc()

            elif choice == "0":
                log("종료합니다.")
                break

            else:
                log("잘못된 선택입니다. 1~9, 0 중 하나를 입력하세요.")


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
