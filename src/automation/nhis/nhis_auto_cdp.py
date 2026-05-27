"""CDP로 기존 Chrome에 연결하여 보험료 납부확인서 발급 자동화"""
import asyncio
import sys
import os
import shutil
import glob
import subprocess
import time
from datetime import datetime
from playwright.async_api import async_playwright

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')

# 프로젝트 루트 경로
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from src.utils.chrome_cdp import CDP_URL, CDP_PORT
from src.utils.pdf_reader import postprocess_pdf

MINWON_URL = "https://www.nhis.or.kr/nhis/minwon/minwonServiceBoard.do"
PDF_PASSWORD = "880718"


def log(msg):
    print(msg, flush=True)


def is_valid_pdf(path):
    """파일이 유효한 PDF인지 확인 (헤더가 %PDF로 시작)"""
    try:
        with open(path, "rb") as f:
            header = f.read(5)
            return header == b"%PDF-"
    except Exception:
        return False


def find_chrome():
    """Chrome 실행 파일 경로 찾기"""
    paths = [
        os.path.join(os.environ.get("PROGRAMFILES", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
    ]
    for p in paths:
        if os.path.exists(p):
            return p
    return None


async def check_cdp_available():
    """CDP 포트가 활성인지 확인"""
    try:
        import urllib.request
        with urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def kill_chrome():
    """기존 Chrome 프로세스 종료"""
    subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)


_session_extend_cancel = None


async def auto_session_extend(page):
    """세션 연장 팝업을 주기적으로 감지하여 자동 클릭

    공단 포털은 약 25분 비활동 후 '로그인 상태 연장' 팝업을 표시함.
    팝업 내 연장 버튼 또는 .modal-dialog 내 확인 버튼을 자동 클릭.
    또한 세션 타이머 만료 시 doLoginSessionExtend() 로 세션 연장.
    """
    while True:
        try:
            clicked = await page.evaluate("""() => {
                // 1) '연장' 텍스트 버튼 클릭 (세션 연장 팝업)
                const selectors = ['button', 'a', 'input[type=button]'];
                for (const sel of selectors) {
                    const els = document.querySelectorAll(sel);
                    for (const el of els) {
                        if (el.offsetParent === null) continue;
                        const t = (el.textContent || el.value || '').trim();
                        if (t === '연장' || t === '시간연장' || t === '연장하기') {
                            el.click();
                            return t;
                        }
                    }
                }
                // 2) .modal-dialog 내 '확인' 버튼 (연장 완료 안내 모달)
                const dialogs = document.querySelectorAll('.modal-dialog');
                for (const d of dialogs) {
                    if (d.offsetParent === null) continue;
                    const text = d.textContent || '';
                    if (!text.includes('연장') && !text.includes('로그인')) continue;
                    const btns = d.querySelectorAll('button, a');
                    for (const btn of btns) {
                        const t = (btn.textContent || '').trim();
                        if (t === '확인') {
                            btn.click();
                            return 'modal 확인 (' + text.trim().substring(0, 30) + ')';
                        }
                    }
                }
                return null;
            }""")
            if clicked:
                log(f"  [세션 연장] '{clicked}' 클릭")
        except Exception:
            pass
        await asyncio.sleep(30)


async def trigger_session_popup_soon(page, seconds=10):
    """개발용: 세션 만료 팝업을 지정된 초 후에 강제 트리거

    공단 포털(nhis.or.kr)의 세션 타이머를 단축하여 연장 팝업을 빠르게 유발.
    실제 발견된 글로벌 함수: doLoginSessionExtend, initLoginExtend, doExtendLogin
    테스트 시에만 사용. 프로덕션에서는 호출하지 않음.

    Usage:
        await trigger_session_popup_soon(page, seconds=5)  # 5초 후 팝업 등장
    """
    log(f"[DEV] {seconds}초 후 세션 연장 팝업 강제 트리거...")
    result = await page.evaluate("""(sec) => {
        // extendTimerPrd 를 짧게 설정하여 initLoginExtend 가 빠르게 트리거되도록 함
        window.extendTimerPrd = sec * 1000;
        clearTimeout(window.extendTimer);
        if (typeof initLoginExtend === 'function') {
            initLoginExtend();
            return 'initLoginExtend called with period=' + (sec * 1000) + 'ms';
        }
        // fallback: doLoginSessionExtend 직접 호출
        if (typeof doLoginSessionExtend === 'function') {
            setTimeout(() => doLoginSessionExtend(), sec * 1000);
            return 'doLoginSessionExtend scheduled';
        }
        return 'no_handler_found';
    }""", seconds)
    log(f"[DEV] {result}")


async def run():
    async with async_playwright() as p:
        # ===== Chrome 연결 =====
        log("Chrome 브라우저 연결 확인 중...")

        if not await check_cdp_available():
            chrome_path = find_chrome()
            if not chrome_path:
                log("Chrome 브라우저를 찾을 수 없습니다. Chrome을 설치해 주세요.")
                return

            log("기존 Chrome을 종료하고 디버깅 모드로 재실행합니다...")
            kill_chrome()

            subprocess.Popen([
                chrome_path,
                f"--remote-debugging-port={CDP_PORT}",
                "--user-data-dir=" + os.path.join(os.environ.get("TEMP", "/tmp"), "chrome-nhis"),
                "--start-maximized",
                "https://www.nhis.or.kr"
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            log("Chrome 실행 대기...")
            for _ in range(30):
                await asyncio.sleep(1)
                if await check_cdp_available():
                    log("Chrome 연결 성공!")
                    break
            else:
                log("Chrome 실행 실패. 수동으로 실행해 주세요.")
                return

        # ===== CDP 연결 =====
        try:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
        except Exception as e:
            log(f"연결 실패: {e}")
            return

        context = browser.contexts[0]

        from src.utils.stealth import stealth_all_pages, register_auto_stealth
        await stealth_all_pages(context)
        register_auto_stealth(context)

        page = context.pages[0]

        # 이전 팝업 탭 정리
        for pg in context.pages[1:]:
            try:
                await pg.close()
            except Exception:
                pass

        # ===== 로그인 확인 =====
        await page.goto("https://www.nhis.or.kr/nhis/index.do", wait_until="domcontentloaded")
        await asyncio.sleep(2)

        if await page.locator("text=로그아웃").count() == 0:
            log("\n브라우저에서 로그인을 진행해 주세요.")
            log("로그인 완료 후 Enter를 누르세요.")
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, input)

            if await page.locator("text=로그아웃").count() == 0:
                log("로그인되지 않았습니다. 종료합니다.")
                return

        log("로그인 확인됨. 자동화 시작.\n")

        # 세션 연장 자동 처리 (백그라운드)
        global _session_extend_cancel
        session_task = asyncio.create_task(auto_session_extend(page))
        _session_extend_cancel = session_task

        # ===== [1/3] 민원 서비스 → 발급 페이지 =====
        log("[1/3] 민원 서비스 → 보험료 납부확인서 발급 페이지 이동...")
        await page.goto(MINWON_URL, wait_until="domcontentloaded")
        await asyncio.sleep(3)

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

        if not href:
            log("  발급하기 버튼을 찾지 못했습니다.")
            return

        log(f"  발급 페이지 이동: {href}")
        await page.goto(href, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        # ===== [2/3] 출력 버튼 → 모달 확인 =====
        log("[2/3] 출력 버튼 클릭 → 확인 모달 처리...")

        download_future = asyncio.Future()

        def on_dl(d):
            if not download_future.done():
                log(f"  [다운로드 감지] {d.suggested_filename}")
                download_future.set_result(d)

        page.on("download", on_dl)
        context.on("page", lambda np: np.on("download", on_dl))

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

        for _ in range(50):
            if await page.evaluate("""() => {
                const m = document.querySelector('#common-CONFIRM-modal');
                return m && m.offsetParent !== null;
            }"""):
                break
            await asyncio.sleep(0.2)

        await page.evaluate("""() => {
            const btn = document.querySelector('#modal-confirm');
            if (btn) btn.click();
        }""")
        log("  모달 확인 클릭 완료.")

        # ===== [3/3] PDF 다운로드 대기 =====
        log("[3/3] PDF 다운로드 대기...")

        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        downloads = os.path.join(os.path.expanduser("~"), "Downloads")
        fname = f"{datetime.now().strftime('%Y%m%d')}_보험료납부확인서.pdf"
        save_path = os.path.join(desktop, fname)

        try:
            download = await asyncio.wait_for(download_future, timeout=60.0)
            log(f"  파일명: {download.suggested_filename}")

            try:
                await download.save_as(save_path)
                if os.path.exists(save_path) and is_valid_pdf(save_path):
                    log(f"\n  성공! PDF 저장: {save_path}")
                else:
                    raise Exception("invalid pdf")
            except Exception:
                log("  Downloads 폴더에서 실제 PDF 파일을 찾습니다...")
                time.sleep(3)

                pdf_files = sorted(
                    glob.glob(os.path.join(downloads, "nhis-*.pdf")),
                    key=os.path.getmtime,
                    reverse=True
                )

                if pdf_files and is_valid_pdf(pdf_files[0]):
                    shutil.copy2(pdf_files[0], save_path)
                    log(f"\n  성공! PDF 저장: {save_path}")
                else:
                    log("  PDF 파일을 찾지 못했습니다.")

            # ===== 후처리: 복호화 + 텍스트 추출 =====
            if os.path.exists(save_path):
                log("\n[후처리] PDF 복호화 및 텍스트 추출 중...")
                try:
                    pdf_path, txt_path = postprocess_pdf(save_path, PDF_PASSWORD)
                    log(f"  완료! 복호화 PDF: {pdf_path}")
                    log(f"  완료! 텍스트 파일: {txt_path}")
                except Exception as e:
                    log(f"  후처리 실패: {e}")

        except asyncio.TimeoutError:
            log("  다운로드 시간 초과. Downloads 폴더를 확인하세요.")

        # ===== 정리 =====
        session_task.cancel()
        await asyncio.sleep(2)
        for pg in context.pages:
            if pg != page:
                try:
                    await pg.close()
                    log("  팝업 탭 닫음.")
                except Exception:
                    pass

        await page.goto("https://www.nhis.or.kr/nhis/index.do", wait_until="domcontentloaded")
        log("  메인 페이지로 복귀.")

        log("\n완료.")


if __name__ == "__main__":
    asyncio.run(run())
