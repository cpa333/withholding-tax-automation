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
from src.utils.save_path import make_save_dir
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
    """사업장 선택 대화형 처리 — 선택된 사업장명 반환"""
    # 사업장 선택 모달 열기
    log("사업장 선택 모달 열기...")
    await open_workplace_selector(page)
    await asyncio.sleep(2)

    # 현재 목록 표시
    workplaces = await list_workplaces(page)
    if not workplaces:
        log("  사업장 목록을 불러오지 못했습니다.")
        return None

    log(f"\n  총 {len(workplaces)}개 사업장:")
    for wp in workplaces[:10]:
        log(f"    {wp['index'] + 1}. [{wp['number']}] {wp['name']}")
    if len(workplaces) > 10:
        log(f"    ... 외 {len(workplaces) - 10}개")

    choice = input("\n  사업장명 또는 번호 입력 (0=취소): ").strip()
    if not choice or choice == "0":
        return None

    # 번호로 선택 시도
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(workplaces):
            await select_workplace_by_index(page, idx)
            return workplaces[idx]["name"]
    except ValueError:
        pass

    # 이름으로 선택
    await select_workplace(page, choice)
    return choice


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

        # ═══ Phase 2: 모드 선택 ═══
        log("실행 모드 선택:")
        log("  1. 전체 자동 (수임처별 전체 워크플로우)")
        log("  2. 대화형 메뉴")
        mode = input("\n선택 > ").strip()

        if mode == "1":
            await run_full_auto(page, context)
        else:
            await run_interactive(page, context)


async def run_full_auto(page, context):
    """전체 자동 모드: 수임처를 하나씩 선택하며 전체 워크플로우 수행"""
    from src.automation.nps._common import select_workplace as _select_wp
    completed = 0

    while True:
        log(f"\n{'='*55}")
        log("  사업장전환 모달 열기...")
        try:
            await switch_workplace_open(page)
            await asyncio.sleep(2)
        except Exception as e:
            log(f"  WARN: 사업장전환 버튼 실패, 재시도... ({e})")
            await asyncio.sleep(3)
            await switch_workplace_open(page)
            await asyncio.sleep(2)

        workplaces = await list_workplaces(page)
        if not workplaces:
            log("  사업장 목록을 불러오지 못했습니다. 재시도...")
            await asyncio.sleep(2)
            continue

        log(f"\n  사업장 목록 ({len(workplaces)}개):")
        for wp in workplaces:
            log(f"    {wp['index'] + 1}. [{wp['number']}] {wp['name']}")

        log(f"\n  완료: {completed}개 | 목록에 없으면 이름 직접 입력 가능")

        # ── 수임처 선택 루프 (잘못 입력 시 여기서 반복) ──
        wp_name = None
        while True:
            choice = input("\n  수임처 번호 또는 이름 (0=종료): ").strip()
            if not choice or choice == "0":
                log(f"\n  총 {completed}개 수임처 자동화 완료. 종료.")
                return

            wp_name = None

            # 번호로 선택 시도
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(workplaces):
                    wp_name = workplaces[idx]["name"]
            except ValueError:
                pass

            # 이름 일부 매칭 (표시된 목록에서)
            if not wp_name:
                matches = [wp for wp in workplaces if choice in wp["name"]]
                if len(matches) == 1:
                    wp_name = matches[0]["name"]
                elif len(matches) > 1:
                    log(f"\n  '{choice}'와(과) 일치하는 사업장 {len(matches)}개:")
                    for j, m in enumerate(matches):
                        log(f"    {j + 1}. [{m['number']}] {m['name']}")
                    sub = input("  선택 (0=취소): ").strip()
                    try:
                        sub_idx = int(sub) - 1
                        if 0 <= sub_idx < len(matches):
                            wp_name = matches[sub_idx]["name"]
                    except ValueError:
                        pass
                    if not wp_name:
                        continue

            # 표시된 목록에 없으면 직접 이름으로 검색 시도
            if not wp_name:
                wp_name = choice
                log(f"  '{choice}' — 표시 목록에 없음, 이름으로 검색합니다.")

            # 사업장 선택 시도 (모달 내 검색 포함)
            ok = await _select_wp(page, wp_name)
            if ok:
                break  # 선택 성공 → 워크플로우 진행

            log(f"  '{wp_name}' 사업장을 찾을 수 없습니다. 다시 입력해주세요.")
            # 모달을 다시 열고 목록 새로고침
            await switch_workplace_open(page)
            await asyncio.sleep(2)
            workplaces = await list_workplaces(page)
            if workplaces:
                log(f"\n  사업장 목록 ({len(workplaces)}개):")
                for wp in workplaces:
                    log(f"    {wp['index'] + 1}. [{wp['number']}] {wp['name']}")
        # ── 수임처 선택 완료 ──

        log(f"\n{'='*55}")
        log(f"  [{completed + 1}] {wp_name}")
        log(f"{'='*55}")

        try:
            await run_single_workplace(page, context, wp_name, is_first=(completed == 0))
            completed += 1
            log(f"\n  {wp_name} 처리 완료. ({completed}개 완료)")
        except Exception as e:
            log(f"  ERROR: {wp_name} 처리 실패 - {e}")
            import traceback
            traceback.print_exc()
            continue


async def switch_workplace_open(page):
    """사업장전환 버튼 클릭하여 모달 열기 (선택은 하지 않음)"""
    from src.automation.nps._common import nexacro_click_button, BTN_CHANGE_WORKPLACE
    await nexacro_click_button(page, BTN_CHANGE_WORKPLACE)


async def run_single_workplace(page, context, workplace_name, is_first=False,
                                year: int | None = None, month: int | None = None):
    """단일 수임처에 대한 전체 워크플로우 수행

    사업장은 이미 선택된 상태여야 함 (run_full_auto에서 사전 선택).

    플로우:
    1. 결정내역 이동
    2. 2차 상세 진입
    3. 가입자내역 → PDF + 엑셀
    4. 소급분내역 → PDF + 엑셀 (빈 경우 스킵)
    5. 국고지원내역 → PDF + 통합저장 (빈 경우 스킵)
    """
    save_dir = make_save_dir("국민연금", workplace_name, year=year, month=month)

    await asyncio.sleep(3)

    # Step 1: 결정내역 이동
    log("  결정내역 메뉴 이동...")
    ok = await navigate_to_decision_details(page)
    if not ok:
        log(f"  ERROR: 결정내역 이동 실패 - {workplace_name} 스킵")
        return

    # Step 3: 2차 상세 진입
    log("  2차 결정내역 진입...")
    ok = await open_decision_detail(page)
    if not ok:
        log(f"  ERROR: 2차 상세 진입 실패 - {workplace_name} 스킵")
        return

    # Step 4~6: 탭별 다운로드
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

    log(f"  저장 경로: {save_dir}")

    # 페이지 상태 정리: 첫 번째 탭으로 복귀
    await click_detail_tab(page, TAB_MEMBER)
    await asyncio.sleep(1)


async def run_interactive(page, context):
    """대화형 메뉴 모드"""
    current_workplace = None  # 선택된 사업장명 추적

    # ═══ Phase 2: 메뉴 루프 ═══
    while True:
            print_menu()
            choice = input("선택 > ").strip()

            if choice == "1":
                try:
                    name = await handle_select_workplace(page)
                    if name:
                        current_workplace = name
                        log(f"  현재 사업장: {current_workplace}")
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
                    wp = current_workplace or input("  수임처명: ").strip()
                    if not wp:
                        log("  수임처명이 필요합니다.")
                        continue
                    save_dir = make_save_dir("국민연금", wp)
                    await download_pdf_from_preview(context, save_dir, filename)
                except Exception as e:
                    log(f"ERROR: {e}")
                    import traceback
                    traceback.print_exc()

            elif choice == "6":
                try:
                    from datetime import datetime
                    now = datetime.now()
                    wp = current_workplace or input("  수임처명: ").strip()
                    if not wp:
                        log("  수임처명이 필요합니다.")
                        continue
                    save_dir = make_save_dir("국민연금", wp)
                    filename = f"국민연금보험료_결정내역_{now.strftime('%Y%m')}_엑셀"
                    await save_excel(page, context, save_dir, filename)
                except Exception as e:
                    log(f"ERROR: {e}")
                    import traceback
                    traceback.print_exc()

            elif choice == "7":
                try:
                    wp = current_workplace or input("  수임처명: ").strip()
                    if not wp:
                        log("  수임처명이 필요합니다.")
                        continue
                    save_dir = make_save_dir("국민연금", wp)
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
                    wp = current_workplace or input("  수임처명: ").strip()
                    if not wp:
                        log("  수임처명이 필요합니다.")
                        continue
                    save_dir = make_save_dir("국민연금", wp)
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
                        current_workplace = name
                        log(f"  현재 사업장: {current_workplace}")
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
