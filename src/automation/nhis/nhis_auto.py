"""건강보험공단 자동화 v3 - Playwright 직접 실행 + 팝업/다운로드 완전 처리"""
import asyncio
import sys
import os
from datetime import datetime
from playwright.async_api import async_playwright

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')

NHIS_URL = "https://www.nhis.or.kr"
MINWON_URL = "https://www.nhis.or.kr/nhis/minwon/minwonServiceBoard.do"
PDF_PASSWORD = "880718"

# 프로젝트 루트 경로
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)
from src.utils.pdf_reader import postprocess_pdf
from src.utils.log import log


async def run():
    async with async_playwright() as p:
        log("Chromium 브라우저 실행...")
        browser = await p.chromium.launch(
            headless=False,
            args=["--start-maximized", "--disable-popup-blocking"]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            accept_downloads=True
        )
        page = await context.new_page()

        log(f"건강보험공단 이동: {NHIS_URL}")
        await page.goto(NHIS_URL, wait_until="domcontentloaded")
        await asyncio.sleep(2)

        # ===== 로그인 대기 =====
        log("\n" + "=" * 50)
        log("브라우저에서 로그인을 진행해 주세요.")
        log("=" * 50 + "\n")

        elapsed = 0
        while elapsed < 300:
            if await page.locator("text=로그아웃").count() > 0:
                log("로그인 감지!\n")
                break
            await asyncio.sleep(2)
            elapsed += 2
            if elapsed % 10 == 0:
                log(f"  로그인 대기... ({300 - elapsed}초)")
        else:
            log("로그인 시간 초과.")
            await browser.close()
            return

        # ===== 민원 서비스 → 발급 페이지 =====
        log("[1/4] 민원 서비스 이동...")
        await page.goto(MINWON_URL, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        log("[2/4] 보험료 납부확인서 '발급하기' 클릭...")
        href = await page.evaluate("""() => {
            const items = document.querySelectorAll('li');
            for (const li of items) {
                if (li.textContent.includes('보험료 납부확인서') && !li.textContent.includes('완납증명서')) {
                    for (const a of li.querySelectorAll('a')) {
                        if (a.textContent.trim().includes('발급하기')) return a.href;
                    }
                }
            }
            return null;
        }""")

        if href:
            log(f"  발급 페이지 이동: {href}")
            await page.goto(href, wait_until="domcontentloaded")
            await asyncio.sleep(3)
        else:
            log("  발급하기를 찾지 못함.")
            return

        # ===== 출력 버튼 → 모달 → 팝업/다운로드 =====
        log("[3/4] '출력' 버튼 클릭 → 모달 처리...")

        # fn_openPrint 직접 호출 (첫 번째 출력 버튼의 파라미터 사용)
        await page.evaluate("""() => {
            const buttons = document.querySelectorAll('button');
            for (const btn of buttons) {
                if ((btn.textContent || '').trim() === '출력' && btn.offsetParent !== null) {
                    const onclick = btn.getAttribute('onclick') || '';
                    if (onclick.includes('fn_openPrint')) {
                        eval(onclick);
                        return;
                    }
                }
            }
        }""")

        # 커스텀 모달 대기
        log("  확인 모달 대기...")
        for _ in range(50):  # 최대 10초
            modal_visible = await page.evaluate("""() => {
                const m = document.querySelector('#common-CONFIRM-modal');
                return m && m.offsetParent !== null;
            }""")
            if modal_visible:
                break
            await asyncio.sleep(0.2)

        # 모달 확인 버튼 클릭
        log("  모달 '확인' 클릭...")
        await page.evaluate("""() => {
            const btn = document.querySelector('#modal-confirm');
            if (btn) btn.click();
        }""")

        # ===== [4/4] 다운로드 대기 (팝업 내 MarkAny 뷰어가 자동 다운로드) =====
        log("[4/4] PDF 다운로드 대기...")

        # download_future 또는 popup_future 둘 다 대기
        # 팝업이 먼저 열리고, 그 안에서 MarkAny가 다운로드를 트리거함
        download_future_final = asyncio.Future()

        def on_dl_final(d):
            if not download_future_final.done():
                log(f"  [다운로드 감지] {d.suggested_filename}")
                download_future_final.set_result(d)

        page.on("download", on_dl_final)
        context.on("page", lambda np: np.on("download", on_dl_final))

        try:
            download = await asyncio.wait_for(download_future_final, timeout=60.0)
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            fname = f"{datetime.now().strftime('%Y%m%d')}_보험료납부확인서.pdf"
            save_path = os.path.join(desktop, fname)
            await download.save_as(save_path)
            log(f"\n  성공! PDF 저장: {save_path}")

            # 후처리: 복호화 + 텍스트 추출
            log("\n[후처리] PDF 복호화 및 텍스트 추출 중...")
            try:
                pdf_path, txt_path = postprocess_pdf(save_path, PDF_PASSWORD)
                log(f"  완료! 복호화 PDF: {pdf_path}")
                log(f"  완료! 텍스트 파일: {txt_path}")
            except Exception as e:
                log(f"  후처리 실패: {e}")

        except asyncio.TimeoutError:
            log("  다운로드 시간 초과. Downloads 폴더를 확인하세요.")

        log("\n자동화 완료. Ctrl+C로 종료하세요.\n")
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass
        finally:
            await browser.close()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log("\n종료되었습니다.")
