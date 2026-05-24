"""SWER0101 전체 자동화 - 페이지 새로고침부터 끝까지"""
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
        log(f"  popup closed ({closed})")
        await asyncio.sleep(0.5)


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

        # 연도 검증
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


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0]
        page = context.pages[0]

        log(f"Start: {await page.title()}")
        log(f"URL: {page.url[:80]}")

        # ===== [1] 페이지 새로고침 =====
        log("\n[1] Page reload...")
        await page.reload(wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        log(f"  Title: {await page.title()}")

        # 모달 닫기
        await dismiss_dialogs(page)

        # ===== [2] 지급기간 설정 =====
        now = datetime.now()
        if now.month == 1:
            target_year = now.year - 1
            target_month = 12
        else:
            target_year = now.year
            target_month = now.month - 1
        log(f"[2] Setting 지급기간: {target_year}-{target_month:02d}")
        await set_period_fields(page, target_year, target_month, target_month)

        # ===== [3] 수임처 아이콘 → 코드도움 확인 =====
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

        # 코드도움 확인(enter)
        log("  코드도움 확인(enter)...")
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
                    break
            except Exception:
                pass
        await asyncio.sleep(2)

        # ===== [4] 제작(F4) 클릭 =====
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

        # ===== [5] 모달 모니터링 =====
        log("[5] Waiting for modals...")
        for i in range(20):
            await asyncio.sleep(1)
            all_txt = await page.evaluate("""() => {
                const r = [];
                document.querySelectorAll('._isDialog').forEach(d => {
                    if (d.offsetWidth > 50) r.push('dlg:' + d.textContent.trim().substring(0, 60));
                });
                document.querySelectorAll('*').forEach(el => {
                    try {
                        const cs = window.getComputedStyle(el);
                        if (cs.position !== 'fixed' || cs.display === 'none'
                            || parseInt(cs.zIndex) < 1000 || el.offsetWidth < 100) return;
                        const txt = el.textContent.trim();
                        if (txt.length > 20 && txt.length < 200) r.push('ov:' + txt.substring(0, 60));
                    } catch(e) {}
                });
                return r;
            }""")
            if all_txt:
                log(f"  [{i+1}s] found {len(all_txt)} overlay(s)")
                for t in all_txt[:5]:
                    log(f"    {t}")
                break
            if i % 4 == 3:
                log(f"  [{i+1}s] waiting...")

        # ===== [6] 제작제외 참고사항만 닫기 (비밀번호 모달 유지) =====
        log("[6] Close 제작제외 only...")
        # iframe에서 제작제외 모달 닫기
        for frame in page.frames:
            try:
                await frame.evaluate("""() => {
                    const dialogs = document.querySelectorAll('._isDialog');
                    for (const d of dialogs) {
                        if (d.offsetWidth < 50) continue;
                        const txt = d.textContent;
                        if (!txt.includes('참고사항') || txt.includes('비밀번호')) continue;
                        const btns = d.querySelectorAll('button');
                        for (const btn of btns) {
                            const t = btn.textContent.trim();
                            if ((t === '확인(enter)' || t === '확인') && btn.offsetWidth > 0) { btn.click(); return; }
                        }
                    }
                }""")
            except Exception:
                pass
        await asyncio.sleep(2)

        # ===== [7] 전자신고 파일 제작 모달 대기 =====
        log("[7] Waiting for 비밀번호 modal...")
        modal_found = False
        for i in range(15):
            await asyncio.sleep(1)
            found = await page.evaluate("""() => {
                const dialogs = document.querySelectorAll('._isDialog');
                for (const d of dialogs) {
                    if (d.offsetWidth > 100 && d.textContent.includes('변환파일 비밀번호')) return true;
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
            log("  ERROR: Modal not found!")
            return

        # ===== [8] 비밀번호 입력 =====
        log("[8] Setting password...")
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
            return {val: input.value, fake: fake ? fake.textContent.trim() : 'none'};
        }""")
        log(f"  result: {json.dumps(pwd, ensure_ascii=False)}")

        # ===== [9] 전자신고 파일 제작(Enter) =====
        log("[9] 전자신고 파일 제작(Enter) click...")
        await page.evaluate("""() => {
            const btns = document.querySelectorAll('button');
            for (const btn of btns) {
                if (btn.textContent.trim() === '전자신고 파일 제작(Enter)' && btn.offsetWidth > 0) {
                    btn.click(); return;
                }
            }
        }""")
        await asyncio.sleep(4)

        # ===== [10] 결과 확인 =====
        log("[10] Checking result...")
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
            log("  SUCCESS - no errors!")

        # WehagoNTS 확인
        r = subprocess.run(["tasklist"], capture_output=True, text=True)
        for line in r.stdout.split("\n"):
            if "WehagoNTS" in line:
                log(f"  Process: {line.strip()}")

        await page.screenshot(path="current_screen.png")
        log("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
