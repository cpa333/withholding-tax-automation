"""CDP로 기존 Chrome에 연결하여 홈택스 원천세 파일변환신고 자동화"""
import asyncio
import sys
import os

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')

from playwright.async_api import async_playwright

CDP_URL = "http://localhost:9222"
HOMETAX_URL = "https://www.hometax.go.kr"


def log(msg):
    print(msg, flush=True)


async def connect_browser(playwright):
    """CDP로 Chrome에 연결하고 홈택스 탭 반환"""
    browser = await playwright.chromium.connect_over_cdp(CDP_URL)
    context = browser.contexts[0]

    for pg in context.pages:
        if "홈택스" in await pg.title():
            return browser, context, pg

    page = await context.new_page()
    await page.goto(HOMETAX_URL, timeout=30000, wait_until="load")
    return browser, context, page


async def dismiss_modals(ht):
    """홈택스 팝업 모달 자동 처리 (w2popup_window 내 btn_confirm 클릭)

    WebSquare w2popup_window 기반 알림/확인 모달을 모두 닫음.
    - 알림 모달 (페이지 진입 시)
    - 확인 모달 (파일검증 후 "이미 검증된 자료가 존재합니다" 등)
    """
    for _ in range(10):
        closed = await ht.evaluate("""() => {
            const modals = document.querySelectorAll('.w2popup_window');
            for (const modal of modals) {
                if (modal.style.display === 'none' || modal.offsetParent === null) continue;
                const btns = modal.querySelectorAll('input[type=button]');
                for (const b of btns) {
                    if (b.id && b.id.includes('btn_confirm')) {
                        b.click();
                        return b.id;
                    }
                }
            }
            return null;
        }""")
        if closed:
            log(f"  모달 닫음: {closed}")
            await asyncio.sleep(1)
        else:
            break


async def wait_element(ht, selector, timeout=30000, label=""):
    """요소가 DOM에 나타날 때까지 대기"""
    try:
        await ht.wait_for_selector(selector, timeout=timeout, state="attached")
        return True
    except Exception:
        log(f"  대기 실패: {label or selector}")
        return False


async def goto_withholding_tax(ht):
    """원천세 신고 > 일반신고 메뉴로 이동"""
    log("[1] 원천세 신고 > 일반신고 이동...")
    await ht.evaluate("""() => {
        const a = document.querySelector('#menuAtag_4106010000');
        if (a) a.click();
    }""")
    if not await wait_element(ht, '[id*="btn_cbcMediRtn"]', timeout=30000, label="btn_cbcMediRtn"):
        return False
    log(f"  이동 완료: {await ht.title()}")
    return True


async def goto_file_convert(ht):
    """파일변환신고 버튼 클릭하여 이동"""
    log("[2] 파일변환신고 이동...")
    await ht.evaluate("""() => {
        const a = document.querySelector('[id*="btn_cbcMediRtn"]');
        if (a) { a.scrollIntoView({block: 'center'}); }
    }""")
    await asyncio.sleep(1)
    await ht.evaluate("""() => {
        const a = document.querySelector('[id*="btn_cbcMediRtn"]');
        if (a) a.click();
    }""")
    await dismiss_modals(ht)
    if not await wait_element(ht, '[id*="btn_cenSts"]', timeout=30000, label="btn_cenSts"):
        return False
    log("  파일변환신고 페이지 로드")
    return True


async def select_file(ht, file_path):
    """파일변환신고 화면에서 파일 선택 (Raon K Uploader iframe 내 hidden file input)

    Raon K Uploader가 raonkuploader_frame_fileList iframe에
    <input type="file">을 동적으로 생성함.
    파일 설정 후 change 이벤트를 발생시켜 컴포넌트가 파일을 인식하도록 함.
    """
    log(f"[3] 파일 선택: {os.path.basename(file_path)}")
    for _ in range(15):
        for frame in ht.frames:
            file_input = frame.locator('input[type="file"]')
            if await file_input.count() > 0:
                await file_input.set_input_files(file_path)
                try:
                    await frame.evaluate("""() => {
                        const fi = document.querySelector('input[type="file"]');
                        if (fi) fi.dispatchEvent(new Event('change', {bubbles: true}));
                    }""")
                except Exception:
                    pass
                log("  파일 설정 완료")
                await asyncio.sleep(2)
                return True
        await asyncio.sleep(2)
    log("  파일 input을 찾지 못함 (30초 대기 초과)")
    return False


async def verify_file(ht):
    """파일검증하기 버튼 클릭 후 후속 모달 자동 처리"""
    log("[4] 파일검증하기 클릭...")
    clicked = await ht.evaluate("""() => {
        const btn = document.querySelector('[id*="btn_cenSts"]');
        if (btn) { btn.click(); return true; }
        return false;
    }""")
    if not clicked:
        log("  파일검증 버튼을 찾지 못함")
        return False

    await asyncio.sleep(3)
    await dismiss_modals(ht)
    await asyncio.sleep(5)
    log("  파일검증 완료")
    return True


async def run(file_path, dry_run=True):
    """홈택스 원천세 파일변환신고 자동화 실행

    Args:
        file_path: 업로드할 엑셀 파일 경로
        dry_run: True면 검증까지만, False면 제출까지 진행
    """
    async with async_playwright() as p:
        log("Chrome 연결...")
        browser, context, ht = await connect_browser(p)
        log(f"현재: {await ht.title()}\n")

        # Raon K Uploader 파일 설정 시 JS dialog 자동 처리
        def _dismiss_dialog(dialog):
            try:
                asyncio.get_event_loop().create_task(dialog.dismiss())
            except Exception:
                pass
        ht.on("dialog", _dismiss_dialog)

        if not await goto_withholding_tax(ht):
            return
        if not await goto_file_convert(ht):
            return
        if not await select_file(ht, file_path):
            return
        if not await verify_file(ht):
            return

        if dry_run:
            log("\n[dry_run] 검증까지만 완료. 제출은 건너뜀.")
        else:
            log("\n[실운영] 제출 진행...")
            # TODO: 비밀번호 입력 → 제출 단계 구현

        log("\n완료.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python hometax_auto_cdp.py <업로드엑셀경로> [--dry-run|--submit]")
        sys.exit(1)

    excel_path = sys.argv[1]
    dry = "--submit" not in sys.argv
    asyncio.run(run(excel_path, dry_run=dry))
