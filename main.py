"""WEHAGO 원천징수 자동화 통합 런처

3개의 자동화 플로우를 메뉴에서 선택하여 실행:
  1. 급여자료입력 (SWSA0101)
  2. 원천징수이행상황신고서 (SWTA0101)
  3. 원천징수전자신고 (SWER0101)

사용법: python main.py
"""
import asyncio
import os
import sys
import traceback

# Windows UTF-8 콘솔 설정
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.async_api import async_playwright

from src.utils.chrome_cdp import launch_chrome, connect_page
from src.automation.wehago._common import (
    log, wait_for_login, goto_salary_page, dismiss_dialogs, WEHAGO_URL,
    search_companies,
)
from src.automation.wehago.run_swsa0101 import run_swsa0101
from src.automation.wehago.run_swta0101 import run_swta0101
from src.automation.wehago.run_swer0101 import run_swer0101


SAVE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "results"))


def print_header():
    print("\n" + "=" * 55)
    print("  WEHAGO 원천징수 자동화")
    print("=" * 55)


def print_menu():
    print("\n" + "-" * 55)
    print("  1. 급여자료입력 (SWSA0101)")
    print("     - 엑셀 다운로드/변환/업로드, PDF 발급")
    print()
    print("  2. 원천징수이행상황신고서 (SWTA0101)")
    print("     - 조회, 마감/마감해제")
    print()
    print("  3. 원천징수전자신고 (SWER0101)")
    print("     - 전자신고 파일 제작, NTS 저장")
    print()
    print("  0. 종료")
    print("-" * 55)


async def main():
    print_header()

    # ═══ Phase 1: Chrome 실행 + 로그인 ═══
    log("\n[1/3] Chrome 실행...")
    result = launch_chrome()
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
            log("Chrome이 CDP 모드(포트 9223)로 실행 중인지 확인하세요.")
            return

        # WEHAGO 메인 페이지로 이동 (항상 이동하여 로그인 상태 확인)
        log("  WEHAGO 메인 페이지로 이동...")
        await page.goto(WEHAGO_URL + "#/main", wait_until="domcontentloaded", timeout=30000)

        if not await wait_for_login(page):
            log("로그인 실패")
            return
        await dismiss_dialogs(page)

        # ═══ Phase 2: 수임처 선택 ═══
        selected_company = None
        while not selected_company:
            log("\n========================================")
            log("  수임처 이름(또는 일부)을 입력하세요")
            log("========================================")
            keyword = input("  검색: ").strip()
            if not keyword:
                continue

            matches = await search_companies(page, keyword)
            if not matches:
                log(f"  '{keyword}'와 일치하는 수임처가 없습니다. 다시 입력해주세요.")
                continue

            if len(matches) == 1:
                log(f"  1개 수임처 발견: {matches[0]}")
                confirm = input(f"  '{matches[0]}'로 진행할까요? (Y/n): ").strip().lower()
                if confirm in ("", "y", "yes"):
                    selected_company = matches[0]
                else:
                    continue
            else:
                log(f"  {len(matches)}개 수임처 발견:")
                for i, name in enumerate(matches, 1):
                    log(f"    {i}. {name}")
                choice = input("  번호 선택 (0=재검색): ").strip()
                try:
                    idx = int(choice)
                    if 1 <= idx <= len(matches):
                        selected_company = matches[idx - 1]
                    elif idx == 0:
                        continue
                    else:
                        log("  잘못된 번호입니다.")
                except ValueError:
                    log("  번호를 입력해주세요.")

        log(f"  '{selected_company}' 급여 페이지로 이동 중...")
        try:
            if not await goto_salary_page(page, selected_company):
                log("수임처 급여 페이지 이동 실패")
                return
        except Exception as e:
            log(f"ERROR: 수임처 이동 중 오류 - {e}")
            return
        await dismiss_dialogs(page)
        log("  이동 완료!\n")

        os.makedirs(SAVE_DIR, exist_ok=True)

        # ═══ Phase 3: 메뉴 루프 ═══
        while True:
            print_menu()
            choice = input("선택 > ").strip()

            if choice == "1":
                dry_input = input("  dry_run? (y/n, 기본=y): ").strip().lower()
                dry_run = dry_input != "n"
                log(f"\n{'='*55}")
                log("  급여자료입력 (SWSA0101) 시작")
                log(f"{'='*55}")
                try:
                    await run_swsa0101(page, SAVE_DIR, dry_run=dry_run)
                except Exception as e:
                    log(f"ERROR: {e}")
                    traceback.print_exc()
                log("\n완료. 다른 작업을 선택하거나 0으로 종료하세요.")

            elif choice == "2":
                log(f"\n{'='*55}")
                log("  원천징수이행상황신고서 (SWTA0101) 시작")
                log(f"{'='*55}")
                try:
                    await run_swta0101(page)
                except Exception as e:
                    log(f"ERROR: {e}")
                    traceback.print_exc()
                log("\n완료. 다른 작업을 선택하거나 0으로 종료하세요.")

            elif choice == "3":
                password = input("  전자신고 비밀번호: ").strip()
                nts_input = input("  NTS 폴더명 (기본=원천징수전자신고): ").strip()
                nts_folder = nts_input or "원천징수전자신고"
                if not password:
                    log("비밀번호가 필요합니다.")
                    continue
                log(f"\n{'='*55}")
                log("  원천징수전자신고 (SWER0101) 시작")
                log(f"{'='*55}")
                try:
                    await run_swer0101(page, password, nts_folder)
                except Exception as e:
                    log(f"ERROR: {e}")
                    traceback.print_exc()
                log("\n완료. 다른 작업을 선택하거나 0으로 종료하세요.")

            elif choice == "0":
                log("종료합니다.")
                break

            else:
                log("잘못된 선택입니다. 1, 2, 3, 0 중 하나를 입력하세요.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        traceback.print_exc()
    finally:
        print("\n프로그램을 종료하려면 Enter를 누르세요...")
        input()
