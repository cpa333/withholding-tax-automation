"""SWER0101 자동화 재시도 - 제작(F4)부터"""
import asyncio
import json
import sys
import subprocess

from playwright.async_api import async_playwright

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')

CDP_URL = "http://localhost:9223"


def log(msg):
    print(msg, flush=True)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0]
        page = context.pages[0]

        log(f"Page: {await page.title()}")
        log(f"URL: {page.url[:80]}")

        # ===== [1] 제작(F4) 클릭 =====
        log("\n[1] Clicking 제작(F4)...")
        clicked = await page.evaluate("""() => {
            const all = document.querySelectorAll('button.WSC_LUXButton');
            for (const btn of all) {
                if (btn.textContent.trim() === '제작(F4)') {
                    const r = btn.getBoundingClientRect();
                    if (r.y < 200 && r.width > 0) { btn.click(); return true; }
                }
            }
            return false;
        }""")
        log(f"  clicked: {clicked}")

        # ===== [2] 모달 대기 =====
        log("[2] Monitoring modals...")
        for i in range(20):
            await asyncio.sleep(1)
            dialogs = await page.evaluate("""() => {
                const results = [];
                document.querySelectorAll('._isDialog').forEach(d => {
                    if (d.offsetWidth < 50) return;
                    const txt = d.textContent.trim();
                    results.push(txt.substring(0, 80));
                });
                // fixed overlay
                document.querySelectorAll('*').forEach(el => {
                    try {
                        const cs = window.getComputedStyle(el);
                        if (cs.position !== 'fixed' || cs.display === 'none'
                            || parseInt(cs.zIndex) < 1000 || el.offsetWidth < 100) return;
                        const txt = el.textContent.trim();
                        if (txt.length > 20 && txt.length < 300)
                            results.push('ov:' + txt.substring(0, 80));
                    } catch(e) {}
                });
                return results;
            }""")
            if dialogs:
                log(f"  [{i+1}s] found {len(dialogs)} dialog(s):")
                for d in dialogs:
                    log(f"    {d[:80]}")
                break
            if i % 3 == 2:
                log(f"  [{i+1}s] waiting...")

        # ===== [3] 제작제외 참고사항 모달만 닫기 =====
        log("[3] Closing 제작제외 only...")
        await asyncio.sleep(1)
        for frame in page.frames:
            try:
                closed = await frame.evaluate("""() => {
                    const dialogs = document.querySelectorAll('._isDialog');
                    for (const d of dialogs) {
                        if (d.offsetWidth < 50) continue;
                        const txt = d.textContent.trim();
                        if (txt.includes('참고사항') && !txt.includes('비밀번호')) {
                            const btns = d.querySelectorAll('button');
                            for (const btn of btns) {
                                const t = btn.textContent.trim();
                                if ((t === '확인(enter)' || t === '확인') && btn.offsetWidth > 0) {
                                    btn.click(); return t;
                                }
                            }
                        }
                    }
                    return null;
                }""")
                if closed:
                    log(f"  closed iframe modal ({closed})")
            except Exception:
                pass

        # 메인 프레임 오버레이에서 제작제외만 닫기
        closed_main = await page.evaluate("""() => {
            const all = document.querySelectorAll('*');
            for (const el of all) {
                const cs = window.getComputedStyle(el);
                if (cs.position !== 'fixed' || cs.display === 'none'
                    || parseInt(cs.zIndex) < 1000 || el.offsetWidth < 50) continue;
                const txt = el.textContent.trim();
                if (!txt.includes('참고사항') || txt.includes('비밀번호')) continue;
                // X 버튼 (WSC_LUXButton 빈 텍스트)
                for (const btn of el.querySelectorAll('button.WSC_LUXButton')) {
                    if (!btn.textContent.trim() && btn.offsetWidth > 0) { btn.click(); return 'X'; }
                }
                for (const btn of el.querySelectorAll('button')) {
                    const t = btn.textContent.trim();
                    if (t === '확인(enter)' || t === '확인') { btn.click(); return t; }
                }
            }
            return null;
        }""")
        if closed_main:
            log(f"  closed overlay ({closed_main})")

        # ===== [4] 전자신고 파일 제작 모달 대기 =====
        log("[4] Waiting for 비밀번호 modal...")
        modal_found = False
        for i in range(20):
            await asyncio.sleep(1)
            found = await page.evaluate("""() => {
                const dialogs = document.querySelectorAll('._isDialog');
                for (const d of dialogs) {
                    if (d.offsetWidth > 100 && d.textContent.includes('변환파일 비밀번호')) return true;
                }
                const all = document.querySelectorAll('*');
                for (const el of all) {
                    const cs = window.getComputedStyle(el);
                    if (cs.position !== 'fixed' || cs.display === 'none'
                        || parseInt(cs.zIndex) < 1000 || el.offsetWidth < 100) continue;
                    if (el.textContent.includes('변환파일 비밀번호')) return true;
                }
                return false;
            }""")
            if found:
                log(f"  [{i+1}s] Modal found!")
                modal_found = True
                break
            if i % 3 == 2:
                log(f"  [{i+1}s] waiting...")

        if not modal_found:
            log("  ERROR: 비밀번호 modal not found!")
            # 디버그: 현재 보이는 다이얼로그
            debug = await page.evaluate("""() => {
                const r = [];
                document.querySelectorAll('._isDialog').forEach(d => {
                    if (d.offsetWidth > 10) r.push(d.textContent.trim().substring(0, 60));
                });
                return r;
            }""")
            log(f"  visible dialogs: {debug}")
            return

        # ===== [5] 비밀번호 입력 =====
        log("[5] Setting password via React native setter...")
        pwd = await page.evaluate("""() => {
            let targetDlg = null;
            const dialogs = document.querySelectorAll('._isDialog');
            for (const d of dialogs) {
                if (d.offsetWidth > 100 && d.textContent.includes('변환파일 비밀번호')) {
                    targetDlg = d; break;
                }
            }
            if (!targetDlg) return 'no dialog';

            const input = targetDlg.querySelector('input.LSinput');
            if (!input) return 'no input';

            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value'
            ).set;
            setter.call(input, 'asdfghjk');
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));

            const fake = targetDlg.querySelector('.fakeinput');
            return {
                val: input.value,
                fake: fake ? fake.textContent.trim() : 'no fakeinput',
            };
        }""")
        log(f"  password set: {json.dumps(pwd, ensure_ascii=False)}")

        # ===== [6] 전자신고 파일 제작(Enter) =====
        log("[6] Clicking 전자신고 파일 제작(Enter)...")
        await page.evaluate("""() => {
            const btns = document.querySelectorAll('button');
            for (const btn of btns) {
                if (btn.textContent.trim() === '전자신고 파일 제작(Enter)' && btn.offsetWidth > 0) {
                    btn.click(); return;
                }
            }
        }""")
        await asyncio.sleep(4)

        # ===== [7] 결과 확인 =====
        log("[7] Checking result...")
        errors = await page.evaluate("""() => {
            const results = [];
            const all = document.querySelectorAll('*');
            for (const el of all) {
                try {
                    const cs = window.getComputedStyle(el);
                    if (cs.position !== 'fixed' || cs.display === 'none'
                        || parseInt(cs.zIndex) < 1000 || el.offsetWidth < 50) continue;
                    const txt = el.textContent.trim();
                    if ((txt.includes('최소') || txt.includes('오류') || txt.includes('에러')
                        || txt.includes('실패')) && txt.length < 300) {
                        results.push(txt.substring(0, 100));
                    }
                } catch(e) {}
            }
            return results.length > 0 ? results : null;
        }""")
        if errors:
            log(f"  ERRORS: {errors}")
        else:
            log("  No errors - SUCCESS!")

        # WehagoNTS 프로세스 확인
        r = subprocess.run(["tasklist"], capture_output=True, text=True)
        for line in r.stdout.split("\n"):
            if "WehagoNTS" in line:
                log(f"  WehagoNTS: {line.strip()}")

        await page.screenshot(path="current_screen.png")
        log("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
