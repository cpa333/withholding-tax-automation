"""원천징수 전자신고(SWER0101) 전체 자동화 - 예외처리 완비"""
import asyncio
import json
import sys
import re
import subprocess
import time
from datetime import datetime
from playwright.async_api import async_playwright

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')

CDP_URL = "http://localhost:9223"


def log(msg):
    print(msg, flush=True)


async def dismiss_dialogs(page):
    for _ in range(20):
        closed = await page.evaluate("""() => {
            const selectors = ['._isDialog', '.LUX_basic_dialog'];
            let target = null;
            for (const sel of selectors) {
                for (const d of document.querySelectorAll(sel)) {
                    const cs = window.getComputedStyle(d);
                    if (cs.display !== 'none' && cs.visibility !== 'hidden'
                        && d.offsetParent !== null && d.offsetWidth > 0) { target = d; break; }
                }
                if (target) break;
            }
            if (!target) {
                const all = document.querySelectorAll('*');
                for (const el of all) {
                    const cs = window.getComputedStyle(el);
                    if (cs.position !== 'fixed' || cs.display === 'none'
                        || parseInt(cs.zIndex) < 1000 || el.offsetWidth < 100) continue;
                    if (el.classList.contains('WSC_LUXSnackbar')) continue;
                    if (el.textContent.trim().length === 0) continue;
                    target = el; break;
                }
            }
            if (!target) return null;
            const allBtns = target.querySelectorAll('button, a');
            for (const btn of allBtns) { if (btn.textContent.trim() === '닫기') { btn.click(); return '닫기'; } }
            const luxBtns = target.querySelectorAll('button.WSC_LUXButton');
            for (const btn of luxBtns) { if (!btn.textContent.trim()) { btn.click(); return 'X'; } }
            for (const btn of allBtns) { if (btn.textContent.trim() === '확인' && btn.offsetWidth > 0) { btn.click(); return '확인'; } }
            for (const btn of allBtns) { if (btn.textContent.trim() === '취소') { btn.click(); return '취소'; } }
            return 'stuck';
        }""")
        if not closed:
            return
        log(f"    popup closed ({closed})")
        await asyncio.sleep(0.5)


async def close_warning_overlay(page, keyword):
    return await page.evaluate("""(kw) => {
        const all = document.querySelectorAll('*');
        for (const el of all) {
            const cs = window.getComputedStyle(el);
            if (cs.position !== 'fixed' || cs.display === 'none' || parseInt(cs.zIndex) < 1000) continue;
            if (!el.textContent.includes(kw)) continue;
            const btns = el.querySelectorAll('button');
            for (const btn of btns) {
                if (btn.textContent.trim() === '확인' && btn.offsetWidth > 0) { btn.click(); return true; }
            }
        }
        return false;
    }""", keyword)


async def set_period_fields(page, year, start_month, end_month):
    await page.evaluate("""() => {
        document.querySelectorAll('.WSC_LUXAlert').forEach(a => {
            const btn = a.querySelector('button.WSC_LUXButton');
            if (btn) btn.click();
            a.style.display = 'none';
        });
    }""")

    rects = await page.evaluate("""() => {
        const results = [];
        const items = document.querySelectorAll('#SearchMain .item');
        items.forEach((item, idx) => {
            const title = item.querySelector('.item_title, strong');
            const titleText = title ? title.textContent.trim() : '';
            if (!titleText.includes('기간')) return;
            const inputDivs = item.querySelectorAll('div[tabindex="0"]');
            const spriteBtns = item.querySelectorAll('button .WSC_LUXSpriteIcon');
            if (inputDivs.length < 4 || spriteBtns.length < 2) return;
            const entry = {idx, title: titleText, years: [], months: []};
            inputDivs.forEach((d, i) => {
                const r = d.getBoundingClientRect();
                entry.years.push({i, text: d.textContent.trim(), x: r.x, y: r.y, w: r.width, h: r.height});
            });
            spriteBtns.forEach((s, i) => {
                const btn = s.closest('button');
                const r = btn.getBoundingClientRect();
                entry.months.push({i, x: r.x, y: r.y, w: r.width, h: r.height});
            });
            results.push(entry);
        });
        return results;
    }""")

    if not rects:
        log("    WARNING: no period fields found")
        return

    for idx, rect in enumerate(rects):
        label = rect.get('title', f'항목{idx}')
        log(f"    {label}: {year}년 {start_month:02d}월 ~ {end_month:02d}월")

        if len(rect['years']) > 0:
            y = rect['years'][0]
            await page.mouse.click(y['x'] + y['w'] / 2, y['y'] + y['h'] / 2, click_count=3)
            await asyncio.sleep(0.3)
            await page.keyboard.type(str(year))
            await page.keyboard.press('Enter')
            await asyncio.sleep(0.3)

        if len(rect['months']) > 0:
            m = rect['months'][0]
            await page.mouse.click(m['x'] + m['w'] / 2, m['y'] + m['h'] / 2)
            await asyncio.sleep(0.5)
            target_text = f"{start_month:02d}"
            await page.evaluate(f"""() => {{
                const lis = document.querySelectorAll('div[style*="position: fixed"] li div');
                for (const li of lis) {{
                    if (li.textContent.trim() === '{target_text}') {{ li.click(); return; }}
                }}
            }}""")
            await asyncio.sleep(0.3)

        if len(rect['years']) > 2:
            y = rect['years'][2]
            await page.mouse.click(y['x'] + y['w'] / 2, y['y'] + y['h'] / 2, click_count=3)
            await asyncio.sleep(0.3)
            await page.keyboard.type(str(year))
            await page.keyboard.press('Enter')
            await asyncio.sleep(0.3)

        if len(rect['months']) > 1:
            m = rect['months'][1]
            await page.mouse.click(m['x'] + m['w'] / 2, m['y'] + m['h'] / 2)
            await asyncio.sleep(0.5)
            target_text = f"{end_month:02d}"
            await page.evaluate(f"""() => {{
                const lis = document.querySelectorAll('div[style*="position: fixed"] li div');
                for (const li of lis) {{
                    if (li.textContent.trim() === '{target_text}') {{ li.click(); return; }}
                }}
            }}""")
            await asyncio.sleep(0.3)

        verify = await page.evaluate(f"""() => {{
            const items = document.querySelectorAll('#SearchMain .item');
            if (!items[{idx}]) return null;
            const divs = items[{idx}].querySelectorAll('div[tabindex="0"]');
            return Array.from(divs).map(d => d.textContent.trim());
        }}""")
        if verify and verify[0] != str(year):
            log(f"      year retry ({verify[0]} -> {year})...")
            y = rect['years'][0]
            await page.mouse.click(y['x'] + y['w'] / 2, y['y'] + y['h'] / 2, click_count=3)
            await asyncio.sleep(0.3)
            await page.keyboard.type(str(year))
            await page.keyboard.press('Enter')
            await asyncio.sleep(0.3)


async def click_codehelp_confirm(page):
    for frame in page.frames:
        try:
            result = await frame.evaluate("""() => {
                const all = document.querySelectorAll('*');
                for (const el of all) {
                    try {
                        const cs = window.getComputedStyle(el);
                        const z = parseInt(cs.zIndex) || 0;
                        if (z < 1000 || cs.display === 'none' || el.offsetWidth < 100) continue;
                        if (!el.textContent.includes('코드도움')) continue;
                        const btns = el.querySelectorAll('button');
                        for (const btn of btns) {
                            if (btn.textContent.trim() === '확인(enter)' && btn.offsetWidth > 0) {
                                btn.click(); return true;
                            }
                        }
                    } catch(e) {}
                }
                return false;
            }""")
            if result:
                return True
        except Exception:
            pass
    return False


async def set_password_and_submit(page, password):
    """비밀번호 입력 + 전자신고 파일 제작

    LSinput 컴포넌트 특성상 첫 입력 시도는 fakeinput이 갱신되지 않음.
    두 번째 시도에서 정상 동작하므로, 검증 실패 시 자동 재시도.
    """
    for attempt in range(1, 4):
        await close_warning_overlay(page, "최소 8~15자리")
        await asyncio.sleep(0.3)

        rect = await page.evaluate("""() => {
            const dialogs = document.querySelectorAll('._isDialog');
            for (const d of dialogs) {
                if (d.offsetWidth < 100 || !d.textContent.includes('변환파일 비밀번호')) continue;
                const fake = d.querySelector('.fake_inputbox');
                if (!fake) return null;
                const r = fake.getBoundingClientRect();
                return {x: r.x, y: r.y, w: r.width, h: r.height};
            }
            return null;
        }""")
        if not rect:
            log("    fake_inputbox not found!")
            return False

        # click -> type -> native setter
        await page.mouse.click(rect['x'] + rect['w'] / 2, rect['y'] + rect['h'] / 2)
        await asyncio.sleep(0.3)
        await page.keyboard.press('Control+a')
        await page.keyboard.press('Backspace')
        await asyncio.sleep(0.1)
        await page.keyboard.type(password, delay=30)
        await asyncio.sleep(0.3)

        await page.evaluate("""(pwd) => {
            const dialogs = document.querySelectorAll('._isDialog');
            for (const d of dialogs) {
                if (d.offsetWidth < 100 || !d.textContent.includes('변환파일 비밀번호')) continue;
                const inp = d.querySelector('input.LSinput');
                if (!inp) return;
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value'
                ).set;
                setter.call(inp, pwd);
                inp.dispatchEvent(new Event('input', { bubbles: true }));
                inp.dispatchEvent(new Event('change', { bubbles: true }));
            }
        }""", password)
        await asyncio.sleep(0.3)

        # fakeinput 검증
        val = await page.evaluate("""() => {
            const dialogs = document.querySelectorAll('._isDialog');
            for (const d of dialogs) {
                if (d.offsetWidth < 100 || !d.textContent.includes('변환파일 비밀번호')) continue;
                const inp = d.querySelector('input.LSinput');
                const fake = d.querySelector('.fakeinput');
                return {val: inp?.value, fake: fake?.textContent.trim()};
            }
            return null;
        }""")

        if not val or val.get('fake', '') != password:
            continue  # LSinput 컴포넌트 한계: 자동 재시도

        log(f"    password OK (attempt {attempt})")

        # 전자신고 파일 제작(Enter) 클릭
        log("    clicking 전자신고 파일 제작(Enter)...")
        await page.evaluate("""() => {
            const btns = document.querySelectorAll('button');
            for (const btn of btns) {
                if (btn.textContent.trim() === '전자신고 파일 제작(Enter)' && btn.offsetWidth > 0) {
                    btn.click(); return;
                }
            }
        }""")
        await asyncio.sleep(3)

        # 에러 확인
        has_error = await page.evaluate("""() => {
            const all = document.querySelectorAll('*');
            for (const el of all) {
                try {
                    const cs = window.getComputedStyle(el);
                    if (cs.position !== 'fixed' || cs.display === 'none'
                        || parseInt(cs.zIndex) < 1000 || el.offsetWidth < 50) continue;
                    const txt = el.textContent.trim();
                    if ((txt.includes('최소') || txt.includes('오류') || txt.includes('에러')
                        || txt.includes('실패')) && txt.length < 300) return txt.substring(0, 100);
                } catch(e) {}
            }
            return null;
        }""")
        if has_error:
            log(f"    warning: {has_error[:60]}")
            continue

        return True

    log("    FAILED after 3 attempts")
    return False


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0]

        for pg in list(context.pages):
            if 'downloadcenter' in pg.url:
                await pg.close()
                log("  closed downloadcenter tab")

        page = context.pages[0]
        log(f"Start: {await page.title()}")

        # [1] 새로고침
        log("\n[1] Page reload...")
        await page.reload(wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        log(f"  Title: {await page.title()}")
        await dismiss_dialogs(page)

        # [2] 지급기간
        now = datetime.now()
        if now.month == 1:
            target_year, target_month = now.year - 1, 12
        else:
            target_year, target_month = now.year, now.month - 1
        log(f"[2] 지급기간: {target_year}-{target_month:02d}")
        await set_period_fields(page, target_year, target_month, target_month)

        # [3] 수임처
        log("[3] 수임처 icon click...")
        await page.evaluate("""() => {
            const items = document.querySelectorAll('#SearchMain .item');
            for (const item of items) {
                const title = item.querySelector('.item_title, strong');
                if (!title || !title.textContent.includes('수임처')) continue;
                const btns = item.querySelectorAll('button.WSC_LUXButton');
                for (const btn of btns) {
                    const r = btn.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0 && !btn.textContent.trim()) {
                        btn.click(); return;
                    }
                }
            }
        }""")
        await asyncio.sleep(2)
        confirmed = await click_codehelp_confirm(page)
        log(f"  코드도움: {confirmed}")
        await asyncio.sleep(2)

        # [4] 제작(F4)
        log("[4] 제작(F4) click...")
        clicked_f4 = await page.evaluate("""() => {
            const all = document.querySelectorAll('button.WSC_LUXButton');
            for (const btn of all) {
                if (btn.textContent.trim() === '제작(F4)') {
                    const r = btn.getBoundingClientRect();
                    if (r.y < 200 && r.width > 0) { btn.click(); return true; }
                }
            }
            return false;
        }""")
        log(f"  clicked: {clicked_f4}")

        # [5] 모달 대기
        log("[5] Waiting for modals...")
        modal_found = False
        for i in range(20):
            await asyncio.sleep(1)
            found = await page.evaluate("""() => {
                const dialogs = document.querySelectorAll('._isDialog');
                for (const d of dialogs) {
                    if (d.offsetWidth > 100 && d.textContent.includes('변환파일 비밀번호')) return 'pwd';
                    if (d.offsetWidth > 100 && d.textContent.includes('참고사항')) return 'ref';
                }
                return null;
            }""")
            if found:
                log(f"  [{i+1}s] modal: {found}")
                modal_found = True
                if found == 'pwd':
                    break
                elif found == 'ref':
                    log("  closing 참고사항...")
                    await dismiss_dialogs(page)

        if not modal_found:
            log("  ERROR: No modal!")
            return

        # 비밀번호 모달 추가 대기
        pwd_ready = await page.evaluate("""() => {
            const dialogs = document.querySelectorAll('._isDialog');
            for (const d of dialogs) {
                if (d.offsetWidth > 100 && d.textContent.includes('변환파일 비밀번호')) return true;
            }
            return false;
        }""")
        if not pwd_ready:
            for i in range(15):
                await asyncio.sleep(1)
                if await page.evaluate("""() => {
                    const dialogs = document.querySelectorAll('._isDialog');
                    for (const d of dialogs) {
                        if (d.offsetWidth > 100 && d.textContent.includes('변환파일 비밀번호')) return true;
                    }
                    return false;
                }"""):
                    log(f"  [{i+1}s] 비밀번호 modal ready")
                    break
            else:
                log("  ERROR: 비밀번호 modal not found!")
                return

        await asyncio.sleep(2)

        # [6] 비밀번호 + 제출
        log("[6] Password + submit...")
        success = await set_password_and_submit(page, "asdfghjk")

        if not success:
            log("\nFAILED")
            return

        # [7] 결과
        log("[7] Final check...")
        r = subprocess.run(["tasklist"], capture_output=True, text=True)
        nts_found = False
        for line in r.stdout.split("\n"):
            if "WehagoNTS" in line:
                log(f"  WehagoNTS: {line.strip()}")
                nts_found = True

        if nts_found:
            log("\n=== SUCCESS ===")
        else:
            log("\n  WARNING: WehagoNTS not detected")

        await page.screenshot(path="current_screen.png")


if __name__ == "__main__":
    asyncio.run(main())
