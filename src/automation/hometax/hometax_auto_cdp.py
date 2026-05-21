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


_session_extend_task = None


async def auto_session_extend(page):
    """홈택스 세션을 주기적으로 연장

    홈택스는 24분 비활동 후 세션 연장 팝업(UTXPPABB27)을 표시하고,
    30분 후 강제 로그아웃 처리함.
    팝업이 뜨기 전 20분 주기로 sessionXtn() + sessionTimer()를 직접 호출하여
    세션을 미리 연장함.

    핵심 JS 함수:
      - $c.pp.sessionXtn($p): 다중 서버(TXPP, TECR 등) 세션 연장 JSONP 요청
      - sessionTimer("Y"): 24분 팝업 + 30분 로그아웃 타이머 재시작
    """
    while True:
        try:
            result = await page.evaluate("""() => {
                if (typeof $c === 'undefined' || typeof $p === 'undefined') return 'no_framework';
                try {
                    $c.pp.sessionXtn($p);
                    sessionTimer('Y');
                    return 'extended';
                } catch(e) { return 'error:' + e.message; }
            }""")
            if result == 'extended':
                log("  [세션 연장] sessionXtn + sessionTimer 호출 완료")
            else:
                log(f"  [세션 연장] 결과: {result}")
        except Exception:
            pass
        await asyncio.sleep(20 * 60)  # 20분


async def trigger_session_popup_soon(page, seconds=10):
    """개발용: 세션 만료 팝업을 지정된 초 후에 강제 트리거

    홈택스(hometax.go.kr)의 세션 타이머를 단축하여 연장 팝업을 빠르게 유발.
    실제 발견된 글로벌 변수/함수:
      - sessiontimerDoServiceFnc: 24분 간격 팝업 타이머 ID
      - sessiontimerEndFnc: 30분 간격 로그아웃 타이머 ID
      - sessionTimer(popupOpenYn): 타이머 설정 함수
    테스트 시에만 사용. 프로덕션에서는 호출하지 않음.

    Usage:
        await trigger_session_popup_soon(page, seconds=5)  # 5초 후 팝업 등장
    """
    log(f"[DEV] {seconds}초 후 세션 연장 팝업 강제 트리거...")
    result = await page.evaluate("""(sec) => {
        clearInterval(window.sessiontimerDoServiceFnc);
        clearInterval(window.sessiontimerEndFnc);

        // sec초 후 UTXPPABB27 팝업 열기 (기존 24분 타이머를 단축)
        window.sessiontimerDoServiceFnc = setInterval(function() {
            var errLayer = document.createElement("div");
            errLayer.className = "w2modal";
            errLayer.id = "errLayer1";
            document.body.appendChild(errLayer);
            errLayer = document.createElement("div");
            errLayer.className = "w2modal";
            errLayer.id = "errLayer2";
            document.body.appendChild(errLayer);

            var sessionoptions = {
                id: 'UTXPPABB27',
                popupName: 'sessionOut',
                width: 610,
                height: 420,
                modal: false,
                scrollbars: false
            };
            $c.util.nts_openPopup($p, "/ui/pp/a/b/UTXPPABB27.xml", sessionoptions);
            $c.pp.sessionStop($p);
        }, sec * 1000);

        // sec*2초 후 로그아웃 타이머
        window.sessiontimerEndFnc = setInterval(function() {
            if ($c.com.nts_sendLogout != undefined) {
                $c.com.nts_sendLogout($p, null, null, $c.pp.sessionDdtTimerCallback);
                $p.$(".w2modal").remove();
            }
            $c.pp.endSessionStop($p);
        }, sec * 2000);

        return 'timers set: popup=' + sec + 's, logout=' + (sec*2) + 's';
    }""", seconds)
    log(f"[DEV] {result}")


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

        # 세션 연장 백그라운드 태스크 시작
        global _session_extend_task
        _session_extend_task = asyncio.create_task(auto_session_extend(ht))

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

        # 세션 연장 태스크 정리
        if _session_extend_task:
            _session_extend_task.cancel()

        log("\n완료.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python hometax_auto_cdp.py <업로드엑셀경로> [--dry-run|--submit]")
        sys.exit(1)

    excel_path = sys.argv[1]
    dry = "--submit" not in sys.argv
    asyncio.run(run(excel_path, dry_run=dry))
