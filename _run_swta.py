"""원천징수이행상황신고서(SWTA0101) 자동화"""
import asyncio
import sys
import os
import re
import time
from datetime import datetime
from playwright.async_api import async_playwright

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')

from src.utils.chrome_cdp import CDP_URL


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


async def goto_menu_page(page, menu_id):
    current_url = page.url
    new_url = re.sub(r'/[A-Z]+\d+(?=[?#]|$)', '/' + menu_id, current_url)
    if new_url == current_url:
        log(f"  URL replace failed for {menu_id}")
        return False
    log(f"  navigating to {menu_id}...")
    await page.goto(new_url, wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(3)
    return True


async def get_report_period_type(page):
    result = await page.evaluate("""() => {
        const radios = document.querySelectorAll('input.LSinput[type=radio]');
        const monthlyRadios = [];
        for (const r of radios) {
            const label = r.closest('label')?.querySelector('.label_text')?.textContent?.trim();
            if (label === '매월' || label === '반기') {
                monthlyRadios.push({radio: r, label, checked: r.checked});
            }
        }
        const checked = monthlyRadios.find(r => r.checked);
        if (checked) return checked.label;
        const monthly = monthlyRadios.find(r => r.label === '매월');
        if (monthly) { monthly.radio.click(); return '매월'; }
        return null;
    }""")
    return result


async def set_period_fields(page, year, start_month, end_month):
    # WSC_LUXAlert 오버레이 닫기
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
        log(f"  {label}: {year}년 {start_month:02d}월 ~ {year}년 {end_month:02d}월")

        # 시작 연도
        if len(rect['years']) > 0:
            y = rect['years'][0]
            await page.mouse.click(y['x'] + y['w'] / 2, y['y'] + y['h'] / 2, click_count=3)
            await asyncio.sleep(0.3)
            await page.keyboard.type(str(year))
            await page.keyboard.press('Enter')
            await asyncio.sleep(0.3)

        # 시작 월
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
                log(f"    start month {target_text} select failed")
            await asyncio.sleep(0.3)

        # 종료 연도
        if len(rect['years']) > 2:
            y = rect['years'][2]
            await page.mouse.click(y['x'] + y['w'] / 2, y['y'] + y['h'] / 2, click_count=3)
            await asyncio.sleep(0.3)
            await page.keyboard.type(str(year))
            await page.keyboard.press('Enter')
            await asyncio.sleep(0.3)

        # 종료 월
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
                log(f"    end month {target_text} select failed")
            await asyncio.sleep(0.3)

        # 연도 검증 및 재시도
        verify = await page.evaluate(f"""() => {{
            const items = document.querySelectorAll('#SearchMain .item');
            if (!items[{idx}]) return null;
            const divs = items[{idx}].querySelectorAll('div[tabindex="0"]');
            return Array.from(divs).map(d => d.textContent.trim());
        }}""")
        if verify and verify[0] != str(year):
            log(f"    year retry ({verify[0]} -> {year})...")
            y = rect['years'][0]
            await page.mouse.click(y['x'] + y['w'] / 2, y['y'] + y['h'] / 2, click_count=3)
            await asyncio.sleep(0.3)
            await page.keyboard.type(str(year))
            await page.keyboard.press('Enter')
            await asyncio.sleep(0.3)

    return True


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0]
        page = context.pages[0]

        # 현재 SmartA 급여자료입력 페이지 확인
        current_url = page.url
        log(f"Current URL: {current_url}")

        # SmartA 페이지가 아니면 처음부터 진행
        if "smarta" not in current_url or "SWSA0101" not in current_url:
            log("Not on SWSA0101. Navigating from main...")
            await page.goto("https://www.wehago.com/#/main", wait_until="domcontentloaded")
            await asyncio.sleep(3)

            # 전체 탭
            await page.evaluate("""() => {
                const tabs = document.querySelector('ul.main_tab_bx');
                if (tabs) tabs.querySelector('li').querySelector('button').click();
            }""")
            await asyncio.sleep(2)
            await dismiss_dialogs(page)

            # 수임처 SmartA 이동
            company_name = "[테스트] (주)리틀치프코리아"
            await page.evaluate("""() => {
                window.__capturedUrl = null;
                window.__origOpen = window.open;
                window.open = function(url) { window.__capturedUrl = url; return null; };
            }""")
            await page.evaluate("""(cn) => {
                const divs = document.querySelectorAll('[id^="company_"]');
                for (const div of divs) {
                    const a = div.querySelector('a');
                    if (a && a.textContent.trim() === cn) {
                        let card = div;
                        for (let i = 0; i < 3; i++) card = card.parentElement;
                        for (const btn of card.querySelectorAll('button.btn_quick')) {
                            if (btn.querySelector('span')?.textContent.trim() === '급여') { btn.click(); return true; }
                        }
                    }
                }
                return false;
            }""", company_name)
            await asyncio.sleep(1)
            url = await page.evaluate("() => window.__capturedUrl")
            await page.evaluate("() => { window.open = window.__origOpen; }")
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            for i in range(15):
                await asyncio.sleep(2)
                if await page.locator("a.text_link").count() > 0:
                    break
            await dismiss_dialogs(page)

            # SWSA0101 메뉴
            await page.evaluate("""() => {
                const link = document.querySelector('a#SWSA0101.text_link');
                if (link) link.click();
            }""")
            await asyncio.sleep(3)
            await dismiss_dialogs(page)

        # ===== [SWTA-1] 원천징수이행상황신고서 이동 =====
        log("\n[SWTA-1] Navigating to SWTA0101...")
        if not await goto_menu_page(page, "SWTA0101"):
            log("  navigation failed!")
            return
        log(f"  URL: {page.url}")

        # 모달 닫기
        await dismiss_dialogs(page)
        await page.screenshot(path="current_screen.png")
        log("  screenshot saved (SWTA0101)")

        # ===== [SWTA-2] 매월/반기 확인 =====
        log("[SWTA-2] Checking period type...")
        period_type = await get_report_period_type(page)
        log(f"  period type: {period_type}")

        # ===== [SWTA-3] 귀속기간/지급기간 설정 =====
        now = datetime.now()
        if period_type == "매월":
            if now.month == 1:
                target_year = now.year - 1
                target_month = 12
            else:
                target_year = now.year
                target_month = now.month - 1
            log(f"[SWTA-3] Setting period: {target_year}-{target_month:02d} (monthly)")
            await set_period_fields(page, target_year, target_month, target_month)
        elif period_type == "반기":
            target_year = now.year
            log(f"[SWTA-3] Setting period: {target_year}-01~06 (semi-annual)")
            await set_period_fields(page, target_year, 1, 6)
        else:
            log(f"  unknown period type: {period_type}")
            return

        # ===== [SWTA-4] 조회 버튼 =====
        log("[SWTA-4] Clicking 조회...")
        clicked_search = await page.evaluate("""() => {
            const btns = document.querySelectorAll('#Search button');
            for (const btn of btns) {
                if (btn.textContent.trim() === '조회' && btn.getBoundingClientRect().width > 0) {
                    btn.click();
                    return true;
                }
            }
            return false;
        }""")
        if not clicked_search:
            log("  조회 button not found!")
            # 대체: #SearchMain 내 버튼 탐색
            clicked_search = await page.evaluate("""() => {
                const all = document.querySelectorAll('button');
                for (const btn of all) {
                    if (btn.textContent.trim() === '조회' && btn.offsetWidth > 0 && btn.offsetHeight > 0) {
                        btn.click(); return true;
                    }
                }
                return false;
            }""")
        log(f"  조회 clicked: {clicked_search}")
        await asyncio.sleep(5)

        await page.screenshot(path="current_screen.png")
        log("  screenshot saved (after 조회)")

        # ===== [SWTA-5] 마감/마감해제 처리 =====
        log("[SWTA-5] Checking 마감/마감해제 button...")
        btn_text = await page.evaluate("""() => {
            const btns = document.querySelectorAll('.WSC_LUXTooltip button.WSC_LUXButton');
            for (const btn of btns) {
                const text = btn.textContent.trim();
                if (text === '마감' || text === '마감해제') return text;
            }
            return null;
        }""")

        if btn_text == "마감":
            log("  마감 상태 -> 마감해제 클릭...")
            await page.evaluate("""() => {
                const btns = document.querySelectorAll('.WSC_LUXTooltip button.WSC_LUXButton');
                for (const btn of btns) {
                    if (btn.textContent.trim() === '마감') { btn.click(); return; }
                }
            }""")
            await asyncio.sleep(2)
            # 마감해제 확인 모달
            await page.evaluate("""() => {
                const sels = ['._isDialog', '.LUX_basic_dialog'];
                for (const s of sels) for (const d of document.querySelectorAll(s)) {
                    if (d.style.display === 'none' || d.offsetParent === null) continue;
                    for (const b of d.querySelectorAll('button')) {
                        if (b.textContent.trim() === '확인' && b.offsetWidth > 0) { b.click(); return; }
                    }
                }
            }""")
            await asyncio.sleep(2)
            log("  마감해제 완료")
        elif btn_text == "마감해제":
            log("  이미 마감해제 상태 - skip")
        else:
            log(f"  마감 button 상태: {btn_text}")

        await dismiss_dialogs(page)
        await page.screenshot(path="current_screen.png")
        log("  screenshot saved (최종)")

        log("\n원천징수이행상황신고서(SWTA0101) 자동화 완료!")


if __name__ == "__main__":
    asyncio.run(main())
