"""원천징수 전자신고(SWER0101) 전체 자동화 - 처음부터 끝까지"""
import asyncio
import sys
import os
import re
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
            const confirmBtn = target.querySelector('.dialog_btnbx button');
            if (confirmBtn) { confirmBtn.click(); return '확인(btnbx)'; }
            for (const btn of allBtns) { if (btn.textContent.trim() === '확인' && btn.offsetWidth > 0) { btn.click(); return '확인'; } }
            for (const btn of allBtns) { if (btn.textContent.trim() === '취소') { btn.click(); return '취소'; } }
            return 'stuck';
        }""")
        if not closed:
            return
        log(f"  popup closed ({closed})")
        await asyncio.sleep(0.5)


async def dismiss_all_frames(page):
    await dismiss_dialogs(page)
    for frame in page.frames:
        try:
            for _ in range(5):
                closed = await frame.evaluate("""() => {
                    const dialogs = document.querySelectorAll('._isDialog, .LUX_basic_dialog');
                    for (const d of dialogs) {
                        if (d.style.display === 'none' || d.offsetParent === null) continue;
                        const btns = d.querySelectorAll('button');
                        for (const btn of btns) {
                            const txt = btn.textContent.trim();
                            if ((txt === '확인(enter)' || txt === '확인') && btn.offsetWidth > 0) {
                                btn.click(); return txt;
                            }
                        }
                    }
                    return null;
                }""")
                if not closed:
                    break
                log(f"  iframe popup closed ({closed})")
                await asyncio.sleep(0.5)
        except Exception:
            pass


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
            clicked = await page.evaluate(f"""() => {{
                const lis = document.querySelectorAll('div[style*="position: fixed"] li div');
                for (const li of lis) {{
                    if (li.textContent.trim() === '{target_text}') {{ li.click(); return true; }}
                }}
                return false;
            }}""")
            if not clicked:
                log(f"      start month {target_text} failed")
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
            clicked = await page.evaluate(f"""() => {{
                const lis = document.querySelectorAll('div[style*="position: fixed"] li div');
                for (const li of lis) {{
                    if (li.textContent.trim() === '{target_text}') {{ li.click(); return true; }}
                }}
                return false;
            }}""")
            if not clicked:
                log(f"      end month {target_text} failed")
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


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0]

        # downloadcenter 탭이 있으면 닫기
        pages_to_close = []
        swer_page = None
        smarta_page = None
        for pg in context.pages:
            if 'downloadcenter' in pg.url:
                pages_to_close.append(pg)
            elif 'SWER0101' in pg.url:
                swer_page = pg
            elif 'smarta' in pg.url:
                smarta_page = pg
        for pg in pages_to_close:
            await pg.close()
            log(f"  closed tab: {pg.url[:60]}")

        # SWER0101 페이지 새로고침 (깨끗한 상태)
        if swer_page:
            page = swer_page
        elif smarta_page:
            page = smarta_page
        else:
            log("ERROR: No SmartA page found")
            return

        # ===== [1] SWER0101 페이지 새로고침 =====
        log("[1] Refreshing SWER0101 page...")
        current_url = page.url
        if 'SWER0101' not in current_url:
            # SWTA0101이나 SWSA0101에서 SWER0101로 이동
            if re.search(r'/[A-Z]+\d+(?=[?#]|$)', current_url):
                new_url = re.sub(r'/[A-Z]+\d+(?=[?#]|$)', '/SWER0101', current_url)
            else:
                new_url = current_url.rstrip('/') + '/SWER0101'
            await page.goto(new_url, wait_until="domcontentloaded", timeout=30000)
        else:
            await page.reload(wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        log(f"  URL: {page.url[:80]}")
        log(f"  Title: {await page.title()}")

        # 모달 닫기 (제출자등록 안내 등)
        log("[1a] Dismissing modals...")
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

        # ===== [3] 수임처 아이콘 클릭 → 코드도움 확인 =====
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

        # 코드도움 모달 확인(enter) 클릭
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

        # ===== [4] 제작(F4) 버튼 클릭 =====
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
        log(f"  제작(F4) clicked: {clicked_f4}")
        await asyncio.sleep(2)

        # 제작제외 참고사항 모달 닫기
        log("  handling 제작제외 모달...")
        await dismiss_all_frames(page)
        await asyncio.sleep(2)

        # ===== [5] 전자신고 파일 제작 모달 - 비밀번호 입력 =====
        log("[5] Waiting for 전자신고 파일 제작 modal...")

        # 모달이 나타날 때까지 대기
        modal_found = False
        for _ in range(10):
            check = await page.evaluate("""() => {
                const dialogs = document.querySelectorAll('._isDialog');
                for (const d of dialogs) {
                    if (d.offsetWidth > 100 && d.textContent.includes('변환파일 비밀번호')) return true;
                }
                return false;
            }""")
            if check:
                modal_found = True
                break
            await asyncio.sleep(1)

        if not modal_found:
            log("  ERROR: Modal not found!")
            return
        log("  Modal found!")

        # 비밀번호 입력 - React native setter 방식
        log("  Setting password via React native setter...")
        pwd_result = await page.evaluate("""() => {
            const dialogs = document.querySelectorAll('._isDialog');
            let targetDlg = null;
            for (const d of dialogs) {
                if (d.offsetWidth > 100 && d.textContent.includes('변환파일 비밀번호')) {
                    targetDlg = d; break;
                }
            }
            if (!targetDlg) return 'dialog not found';

            const input = targetDlg.querySelector('input.LSinput');
            if (!input) return 'input not found';

            // React native value setter
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value'
            ).set;

            nativeInputValueSetter.call(input, 'asdfghjk');
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));

            // fakeinput 확인
            const fake = targetDlg.querySelector('.fakeinput');
            return {
                inputValue: input.value,
                fakeText: fake ? fake.textContent.trim() : 'no fakeinput',
            };
        }""")
        log(f"  Password set: {pwd_result}")

        # ===== [6] 전자신고 파일 제작(Enter) 버튼 클릭 =====
        log("[6] 전자신고 파일 제작(Enter) click...")
        await page.evaluate("""() => {
            const btns = document.querySelectorAll('button');
            for (const btn of btns) {
                if (btn.textContent.trim() === '전자신고 파일 제작(Enter)' && btn.offsetWidth > 0) {
                    btn.click(); return;
                }
            }
        }""")
        await asyncio.sleep(3)

        # ===== [7] 결과 확인 =====
        log("[7] Checking result...")
        has_error = await page.evaluate("""() => {
            const results = [];
            const all = document.querySelectorAll('*');
            for (const el of all) {
                try {
                    const cs = window.getComputedStyle(el);
                    if (cs.position !== 'fixed' || cs.display === 'none' || parseInt(cs.zIndex) < 1000) continue;
                    if (el.offsetWidth < 50) continue;
                    const txt = el.textContent.trim();
                    if (txt.includes('최소') || txt.includes('오류') || txt.includes('에러') || txt.includes('실패')) {
                        results.push(txt.substring(0, 100));
                    }
                } catch(e) {}
            }
            return results.length > 0 ? results : null;
        }""")

        if has_error:
            log(f"  WARNING: {has_error}")
        else:
            log("  No error modals - SUCCESS!")

        # WehagoNTS 프로세스 확인
        import subprocess
        result = subprocess.run(['tasklist'], capture_output=True, text=True)
        nts_found = False
        for line in result.stdout.split('\n'):
            if 'WehagoNTS' in line:
                log(f"  WehagoNTS process: {line.strip()}")
                nts_found = True
        if not nts_found:
            log("  WehagoNTS process NOT found")

        await page.screenshot(path="current_screen.png")
        log("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
