"""원천징수 전자신고(SWER0101) 자동화"""
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


async def dismiss_dialogs_all_frames(page):
    """모든 frame(iframe 포함)에서 모달 닫기"""
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
                    // z-index overlay
                    const all = document.querySelectorAll('*');
                    for (const el of all) {
                        const cs = window.getComputedStyle(el);
                        if (cs.position !== 'fixed' || cs.display === 'none'
                            || parseInt(cs.zIndex) < 1000 || el.offsetWidth < 100) continue;
                        if (el.textContent.trim().length === 0) continue;
                        const btns = el.querySelectorAll('button');
                        for (const btn of btns) {
                            if (btn.textContent.trim() === '확인(enter)' && btn.offsetWidth > 0) {
                                btn.click(); return '확인(enter)';
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
                log(f"      start month {target_text} select failed")
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
                log(f"      end month {target_text} select failed")
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

        current_url = page.url
        log(f"Current URL: {current_url}")

        # SmartA SWTA0101에 있어야 함. 아니면 처음부터
        if "smarta" not in current_url:
            log("ERROR: Not on SmartA. Run SWTA0101 automation first.")
            return

        # ===== [SWER-1] SWER0101 이동 =====
        log("\n[SWER-1] Navigating to SWER0101...")
        new_url = re.sub(r'/[A-Z]+\d+(?=[?#]|$)', '/SWER0101', current_url)
        if new_url == current_url:
            log("  URL replace failed!")
            return
        log(f"  target: {new_url[:80]}...")
        await page.goto(new_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        log(f"  URL: {page.url}")
        log(f"  Title: {await page.title()}")

        # 모달 닫기 (제출자등록 안내 등)
        log("[SWER-1a] dismissing modals...")
        await dismiss_dialogs(page)
        await page.screenshot(path="current_screen.png")

        # ===== [SWER-2] 지급기간 설정 =====
        now = datetime.now()
        if now.month == 1:
            target_year = now.year - 1
            target_month = 12
        else:
            target_year = now.year
            target_month = now.month - 1
        log(f"[SWER-2] Setting 지급기간: {target_year}-{target_month:02d}")
        await set_period_fields(page, target_year, target_month, target_month)

        # ===== [SWER-3] 수임처 아이콘 클릭 → 코드도움 확인 =====
        log("[SWER-3] 수임처 icon click...")
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

        # 코드도움 모달에서 확인(enter) 클릭
        log("  코드도움 확인(enter) click...")
        clicked_confirm = False
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
                    clicked_confirm = True
                    break
            except Exception:
                pass

        if not clicked_confirm:
            # 메인 프레임에서도 시도
            await page.evaluate("""() => {
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
                                btn.click(); return;
                            }
                        }
                    } catch(e) {}
                }
            }""")
        await asyncio.sleep(2)
        log(f"  코드도움 confirm: {clicked_confirm}")

        # ===== [SWER-4] 제작(F4) 버튼 클릭 =====
        log("[SWER-4] 제작(F4) click...")
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
        await asyncio.sleep(3)

        # ===== [SWER-5] 제작제외 참고사항 모달 닫기 =====
        log("[SWER-5] handling 제작제외 모달...")
        modal_handled = False
        for frame in page.frames:
            try:
                result = await frame.evaluate("""() => {
                    const dialogs = document.querySelectorAll('._isDialog');
                    for (const d of dialogs) {
                        if (!d.textContent.includes('참고사항')) continue;
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
                if result:
                    log(f"  제작제외 모달 닫음 ({result})")
                    modal_handled = True
                    break
            except Exception:
                pass

        if not modal_handled:
            # 메인 프레임에서도 시도
            await dismiss_dialogs(page)

        await asyncio.sleep(2)

        # ===== [SWER-6] 제작 진행 대기 =====
        log("[SWER-6] waiting for 제작 to process...")
        await asyncio.sleep(5)

        # 추가 모달 처리 (제작 완료 등)
        await dismiss_dialogs_all_frames(page)

        await page.screenshot(path="current_screen.png")
        log("  screenshot saved")

        # 현재 페이지 상태 확인
        state = await page.evaluate("""() => {
            const result = {};
            result.url = location.href;
            result.title = document.title;
            // 에러/성공 메시지
            const sels = ['._isDialog', '.LUX_basic_dialog'];
            for (const s of sels) {
                for (const d of document.querySelectorAll(s)) {
                    if (d.style.display !== 'none' && d.offsetParent !== null) {
                        result.dialogText = d.textContent.trim().substring(0, 200);
                    }
                }
            }
            // 버튼 상태
            const btns = document.querySelectorAll('button.WSC_LUXButton');
            result.visibleButtons = [];
            for (const b of btns) {
                const t = b.textContent.trim();
                const r = b.getBoundingClientRect();
                if (t && r.width > 0 && r.y < 200) result.visibleButtons.push(t);
            }
            return result;
        }""")
        import json
        log(f"\nPage state:\n{json.dumps(state, ensure_ascii=False, indent=2)}")

        log("\n원천징수 전자신고(SWER0101) 자동화 완료!")


if __name__ == "__main__":
    asyncio.run(main())
