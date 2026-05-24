"""급여 등록 자동화 (SWSA0101) — CDP 연결 후 3~14단계 실행

이미 Chrome CDP 모드로 실행 + WEHAGO 로그인 완료 상태에서 실행.
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from playwright.async_api import async_playwright

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')

CDP_URL = "http://localhost:9223"
COMPANY_NAME = "[테스트] (주)리틀치프코리아"
SAVE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "results"))


def log(msg):
    print(msg, flush=True)


async def main():
    from automation.wehago.wehago_auto_cdp import (
        goto_salary_page,
        click_menu,
        select_dropdown,
        click_dialog_button,
        dismiss_dialogs,
        download_excel,
        convert_for_upload,
        upload_excel,
        download_pdf,
    )

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0]
        page = context.pages[0]

        log(f"연결됨: {await page.title()}")
        log(f"URL: {page.url[:80]}")

        os.makedirs(SAVE_DIR, exist_ok=True)

        # ===== [3] 수임처 급여(SmartA) 페이지 이동 =====
        log("\n[3/14] 수임처 급여 페이지 이동...")
        if not await goto_salary_page(page, COMPANY_NAME):
            log("ERROR: 급여 페이지 이동 실패")
            return
        await dismiss_dialogs(page)

        # ===== [4] 급여자료입력 메뉴 이동 =====
        log("[4/14] 급여자료입력(SWSA0101) 메뉴 이동...")
        await click_menu(page, "SWSA0101")
        await asyncio.sleep(3)

        # 간이세액 개정 안내 모달 닫기
        await page.evaluate("""() => {
            const all = document.querySelectorAll('*');
            for (const el of all) {
                const cs = window.getComputedStyle(el);
                if (cs.position !== 'fixed' || cs.display === 'none' ||
                    parseInt(cs.zIndex) <= 100 || el.offsetWidth <= 100) continue;
                if (!el.textContent.includes('간이세액')) continue;
                const btns = el.querySelectorAll('button.WSC_LUXButton');
                for (const btn of btns) {
                    if (!btn.textContent.trim() && btn.offsetWidth > 0) { btn.click(); return; }
                }
            }
        }""")
        await asyncio.sleep(1)
        await dismiss_dialogs(page)

        # ===== [5] 구분 드롭다운 → 급여+상여 =====
        log("[5/14] 구분 드롭다운 → 급여+상여 선택...")
        await select_dropdown(page, 0, "급여+상여")

        # ===== [6-7] 복사후 재계산 모달 (조건부) =====
        await asyncio.sleep(1)
        has_modal = await page.evaluate("""() => {
            const selectors = ['._isDialog', '.LUX_basic_dialog'];
            for (const sel of selectors) {
                for (const d of document.querySelectorAll(sel)) {
                    if (d.style.display !== 'none') return true;
                }
            }
            return false;
        }""")
        if has_modal:
            log("[6/14] 복사후 재계산 버튼 클릭...")
            await click_dialog_button(page, "복사후 재계산")
            await asyncio.sleep(1)
            log("[7/14] 확인 모달 → 취소 클릭...")
            await click_dialog_button(page, "취소")
        else:
            log("[6-7/14] 모달 없음 - 스킵")

        # ===== [8] 엑셀 다운로드 =====
        log("[8/14] 엑셀 다운로드...")
        download_path = await download_excel(page, SAVE_DIR)
        if not download_path:
            log("ERROR: 엑셀 다운로드 실패")
            return
        log(f"  다운로드: {download_path}")

        # ===== [9] 업로드 양식 변환 =====
        log("[9/14] 업로드 양식 변환...")
        upload_path = convert_for_upload(download_path)
        if not upload_path:
            log("ERROR: 변환 실패")
            return
        log(f"  변환 완료: {upload_path}")

        # ===== [10] 엑셀 업로드 =====
        log("[10/14] 엑셀 업로드 (dry_run=True)...")
        success = await upload_excel(page, upload_path, dry_run=True)
        if success:
            log(f"  업로드 완료!")
        else:
            log(f"  업로드 중 에러 발생. 화면을 확인하세요.")

        # ===== [11-14] PDF 다운로드 =====
        log("[11-14/14] PDF 다운로드...")
        pdf_path = await download_pdf(page, SAVE_DIR)
        if pdf_path:
            log(f"  PDF 완료: {pdf_path}")
        else:
            log("  PDF 다운로드 실패")

        log(f"\n=== '{COMPANY_NAME}' 급여 등록 자동화 완료 ===")


if __name__ == "__main__":
    asyncio.run(main())
