"""Phase 4 SWSA0101 dry_run 테스트 스크립트

CDP로 Chrome에 연결하여 dry_run=True로 엑셀 업로드까지 테스트.
단계별로 실행하며 진행 상황을 출력.
"""
import asyncio
import io
import os
import sys

# Windows UTF-8 stdout
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')

# 프로젝트 루트를 sys.path에 추가
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.chdir(ROOT)


async def main():
    from playwright.async_api import async_playwright
    from src.utils.chrome_cdp import connect_page
    from src.automation.wehago._common import (
        log, wait_for_login, goto_salary_page, dismiss_dialogs,
        navigate_to_swsa0101, compute_target_period,
    )
    from src.automation.wehago._swsa_excel import (
        download_excel, convert_for_upload, upload_excel,
    )

    # 테스트 파라미터
    CLIENT_NAME = "[테스트] 주식회사 쓰리이소프트"
    DRY_RUN = False  # True: 업로드 후 취소, False: 실제 업로드

    # year/month: 이전 달 자동 계산
    year, month = compute_target_period()
    print(f"\n{'='*60}")
    print(f"Phase 4 SWSA0101 dry_run 테스트")
    print(f"  수임처: {CLIENT_NAME}")
    print(f"  귀속연월: {year}.{month:02d}")
    print(f"  dry_run: {DRY_RUN}")
    print(f"{'='*60}\n")

    # CDP 연결
    print("[0] CDP 연결...")
    async with async_playwright() as p:
        browser, context, page = await connect_page(p)
        print(f"  연결 성공: {page.url}")

        # 로그인 확인
        print("\n[1] WEHAGO 로그인 확인...")
        logged_in = await wait_for_login(page)
        if not logged_in:
            print("  로그인 실패. 종료.")
            return
        print("  로그인 확인됨.")

        # 모달 정리
        print("\n[2] 초기 모달 정리...")
        await dismiss_dialogs(page)
        print("  완료.")

        # 급여 페이지 이동
        print(f"\n[3] '{CLIENT_NAME}' 급여 페이지 이동...")
        goto_ok = await goto_salary_page(page, CLIENT_NAME)
        if not goto_ok:
            print("  급여 페이지 이동 실패. 종료.")
            return
        print("  이동 성공.")

        # 모달 정리
        await dismiss_dialogs(page)

        # SWSA0101 메뉴 이동 + 귀속연월 설정
        print(f"\n[4] SWSA0101 메뉴 이동 ({year}.{month:02d})...")
        ok = await navigate_to_swsa0101(page, year=year, month=month)
        if not ok:
            print("  이동/설정 실패. 종료.")
            return
        print("  이동 성공.")

        # 엑셀 다운로드
        save_dir = os.path.join(ROOT, "results", f"test_phase4_{year}{month:02d}")
        os.makedirs(save_dir, exist_ok=True)

        print(f"\n[5] 엑셀 다운로드 → {save_dir}")
        download_path = await download_excel(page, save_dir)
        print(f"  다운로드 완료: {download_path}")

        # 업로드 양식 변환
        print("\n[6] 업로드 양식 변환...")
        upload_path = convert_for_upload(download_path)
        print(f"  변환 완료: {upload_path}")

        # 업로드 전 모달 정리
        print("\n[7] 업로드 전 모달 정리...")
        await dismiss_dialogs(page)

        # 엑셀 업로드 (dry_run)
        print(f"\n[8] 엑셀 업로드 (dry_run={DRY_RUN})...")
        success = await upload_excel(page, upload_path, dry_run=DRY_RUN)

        if success:
            print(f"\n{'='*60}")
            print(f"  ✅ 업로드 {'테스트(dry_run)' if DRY_RUN else '실운영'} 완료!")
            print(f"{'='*60}")
        else:
            print(f"\n{'='*60}")
            print(f"  ❌ 업로드 실패. 화면을 확인하세요.")
            print(f"{'='*60}")

        # 브라우저 연결 유지 (종료하지 않음)
        print("\n브라우저 연결 유지 중. Ctrl+C로 종료.")


if __name__ == "__main__":
    asyncio.run(main())
