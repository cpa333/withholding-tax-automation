"""WEHAGO 자동화 공통 함수 모듈

모든 자동화 플로우(SWSA0101, SWTA0101, SWER0101)에서 공유하는 함수들.
각 함수는 최선의 구현 버전에서 추출함.
"""
import asyncio
import re
from datetime import datetime


CDP_URL = "http://localhost:9223"
WEHAGO_URL = "https://www.wehago.com/"


def log(msg):
    print(msg, flush=True)


# ═══════════════════════════════════════════════════════════════════════
# 기간 계산
# ═══════════════════════════════════════════════════════════════════════

def compute_target_period():
    """현재 기준 저번달 (year, month) 반환. 1월이면 전년 12월."""
    now = datetime.now()
    if now.month == 1:
        return now.year - 1, 12
    return now.year, now.month - 1


# ═══════════════════════════════════════════════════════════════════════
# 모달/다이얼로그 처리
# ═══════════════════════════════════════════════════════════════════════

async def dismiss_dialogs(page):
    """표시 중인 팝업/다이얼로그가 있으면 모두 닫기

    대상: _isDialog, LUX_basic_dialog + z-index >= 1000 fixed 오버레이
    닫기 순서: 닫기 → X → 확인(btnbx) → 확인 → 취소
    중첩 시 모두 사라질 때까지 반복.
    """
    for _ in range(20):
        closed = await page.evaluate("""() => {
            const selectors = ['._isDialog', '.LUX_basic_dialog'];
            let target = null;
            for (const sel of selectors) {
                for (const d of document.querySelectorAll(sel)) {
                    const cs = window.getComputedStyle(d);
                    if (cs.display !== 'none' && cs.visibility !== 'hidden'
                        && d.offsetParent !== null && d.offsetWidth > 0) {
                        target = d; break;
                    }
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
            for (const btn of allBtns) {
                if (btn.textContent.trim() === '닫기') { btn.click(); return '닫기'; }
            }
            const luxBtns = target.querySelectorAll('button.WSC_LUXButton');
            for (const btn of luxBtns) {
                if (!btn.textContent.trim()) { btn.click(); return 'X'; }
            }
            const confirmBtn = target.querySelector('.dialog_btnbx button');
            if (confirmBtn) { confirmBtn.click(); return '확인(btnbx)'; }
            for (const btn of allBtns) {
                if (btn.textContent.trim() === '확인' && btn.offsetWidth > 0) {
                    btn.click(); return '확인';
                }
            }
            for (const btn of allBtns) {
                if (btn.textContent.trim() === '취소') { btn.click(); return '취소'; }
            }
            return 'stuck';
        }""")
        if not closed:
            return
        log(f"  팝업 닫음 ({closed})")
        await asyncio.sleep(0.5)


async def close_warning_overlay(page, keyword):
    """특정 키워드가 포함된 z-index 고정 오버레이에서 확인 버튼 클릭"""
    return await page.evaluate("""(kw) => {
        const all = document.querySelectorAll('*');
        for (const el of all) {
            const cs = window.getComputedStyle(el);
            if (cs.position !== 'fixed' || cs.display === 'none'
                || parseInt(cs.zIndex) < 1000) continue;
            if (!el.textContent.includes(kw)) continue;
            const btns = el.querySelectorAll('button');
            for (const btn of btns) {
                if (btn.textContent.trim() === '확인' && btn.offsetWidth > 0) {
                    btn.click(); return true;
                }
            }
        }
        return false;
    }""", keyword)


async def click_codehelp_confirm(page):
    """iframe 포함 코드도움 모달에서 확인(enter) 클릭"""
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


async def click_dialog_button(page, button_text):
    """현재 떠 있는 모달/다이얼로그에서 지정된 텍스트의 버튼 클릭"""
    await page.evaluate("""(btnText) => {
        const selectors = ['._isDialog', '.LUX_basic_dialog'];
        let target = null;
        for (const sel of selectors) {
            for (const d of document.querySelectorAll(sel)) {
                if (d.style.display !== 'none') { target = d; break; }
            }
            if (target) break;
        }
        if (!target) return;
        const btns = target.querySelectorAll('button, a');
        for (const b of btns) {
            if (b.textContent.trim().includes(btnText)) { b.click(); return; }
        }
    }""", button_text)
    await asyncio.sleep(1)
    log(f"  모달 버튼 클릭: {button_text}")


async def _click_modal_text(page, text_fragment, action):
    """특정 텍스트가 포함된 모달에서 action(확인/취소) 버튼 클릭"""
    for _ in range(20):
        result = await page.evaluate("""(args) => {
            const all = document.querySelectorAll('*');
            for (const el of all) {
                if (!el.textContent.includes(args.fragment)) continue;
                const btns = el.querySelectorAll('button');
                for (const btn of btns) {
                    if (btn.textContent.trim() === args.action && btn.offsetWidth > 0) {
                        btn.click();
                        return args.action;
                    }
                }
            }
            return null;
        }""", {"fragment": text_fragment, "action": action})
        if result:
            return True
        await asyncio.sleep(0.5)
    return False


# ═══════════════════════════════════════════════════════════════════════
# 페이지 네비게이션
# ═══════════════════════════════════════════════════════════════════════

async def goto_menu_page(page, menu_id):
    """SmartA 내 다른 메뉴 페이지로 이동 (URL 해시 교체)

    2단계 폴백: /smarta/humanresource/{MENU_ID} 우선, 실패 시 /{MENU_ID}
    """
    current_url = page.url
    new_url = re.sub(
        r'/smarta/humanresource/[A-Z]+\d+(?=[?#]|$)',
        f'/smarta/humanresource/{menu_id}', current_url
    )
    if new_url == current_url:
        new_url = re.sub(r'/[A-Z]+\d+(?=[?#]|$)', f'/{menu_id}', current_url)
    if new_url == current_url:
        log(f"  URL 교체 실패: {menu_id}")
        return False
    log(f"  메뉴 이동: {menu_id}")
    await page.goto(new_url, wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(2)
    log(f"  이동 완료: {await page.title()}")
    return True


async def click_menu(page, menu_id):
    """SmartA 사이드 메뉴 클릭 (SPA 내부 라우팅)"""
    await page.evaluate("""(menuId) => {
        const link = document.querySelector('a#' + menuId + '.text_link');
        if (link) link.click();
    }""", menu_id)
    await asyncio.sleep(3)
    log(f"  메뉴 이동 완료: {await page.title()}")


async def wait_for_login(page):
    """WEHAGO 로그인 완료 대기 (수동 로그인)"""
    await page.goto(WEHAGO_URL + "#/main", wait_until="domcontentloaded")
    await asyncio.sleep(2)

    if await page.locator("#company_").count() > 0 or await page.locator("text=나의 수임처").count() > 0:
        log("이미 로그인되어 있습니다.")
        return True

    log("\n브라우저에서 WEHAGO 로그인을 진행해 주세요.")
    log("로그인 완료 후 자동으로 감지됩니다. (터미널에서 키 입력하지 마세요)")

    for _ in range(120):
        await asyncio.sleep(5)
        try:
            if await page.locator("text=나의 수임처").count() > 0:
                log("로그인 확인됨.")
                return True
            await page.reload(wait_until="domcontentloaded")
            await asyncio.sleep(2)
            if await page.locator("text=나의 수임처").count() > 0:
                log("로그인 확인됨.")
                return True
        except Exception:
            pass

    log("로그인 대기 시간 초과 (10분).")
    return False


async def goto_salary_page(page, company_name):
    """수임처의 SmartA 급여 메인 페이지로 이동

    window.open 인터셉트 → 수임처 카드 '급여' 버튼 클릭 → URL 캡처 → page.goto
    """
    await page.evaluate("""() => {
        window.__capturedUrl = null;
        window.__origOpen = window.open;
        window.open = function(url) {
            window.__capturedUrl = url;
            return null;
        };
    }""")

    clicked = await page.evaluate("""(companyName) => {
        const allDivs = document.querySelectorAll('[id^="company_"]');
        for (const div of allDivs) {
            const nameEl = div.querySelector('a');
            if (nameEl && nameEl.textContent.trim() === companyName) {
                let card = div;
                for (let i = 0; i < 3; i++) card = card.parentElement;
                const buttons = card.querySelectorAll('button.btn_quick');
                for (const btn of buttons) {
                    if (btn.querySelector('span')?.textContent.trim() === '급여') {
                        btn.click(); return true;
                    }
                }
            }
        }
        return false;
    }""", company_name)

    if not clicked:
        log(f"  수임처 '{company_name}'의 급여 버튼을 찾지 못했습니다.")
        return False

    await asyncio.sleep(1)
    url = await page.evaluate("() => window.__capturedUrl")
    await page.evaluate("() => { window.open = window.__origOpen; }")

    if not url:
        log("  SmartA URL 캡처 실패")
        return False

    log(f"  SmartA 급여 URL: {url}")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)

    for i in range(15):
        await asyncio.sleep(2)
        if await page.locator("a.text_link").count() > 0:
            break
    else:
        log("  SmartA 페이지 로드 타임아웃")
        return False

    log(f"  페이지 이동 완료: {await page.title()}")
    return True


# ═══════════════════════════════════════════════════════════════════════
# 드롭다운 / 메뉴
# ═══════════════════════════════════════════════════════════════════════

async def select_dropdown(page, dropdown_index, option_text):
    """커스텀 드롭다운(LS_ngh_select2)에서 옵션 선택"""
    await page.evaluate("""(idx) => {
        const dd = document.querySelectorAll('.LS_ngh_select2')[idx];
        if (dd) dd.querySelector('.LSbutton').click();
    }""", dropdown_index)
    await asyncio.sleep(1)

    await page.evaluate("""(args) => {
        const items = document.querySelectorAll('.LSselectResult li');
        for (const li of items) {
            if (li.textContent.includes(args.text)) {
                li.querySelector('a').click();
                return true;
            }
        }
        return false;
    }""", {"text": option_text})
    await asyncio.sleep(1)

    value = await page.evaluate("""(idx) => {
        const dd = document.querySelectorAll('.LS_ngh_select2')[idx];
        return dd ? dd.querySelector('.fakeinput').textContent.trim() : '';
    }""", dropdown_index)
    log(f"  드롭다운 선택: {value}")


async def open_collect_menu(page):
    """우측 끝 #collect 버튼 클릭하여 드롭다운 메뉴 열기"""
    await page.evaluate("""() => {
        const btn = document.querySelector('#collect');
        if (btn) btn.click();
    }""")
    await asyncio.sleep(1)


async def click_menu_item(page, item_text):
    """sao_head_menu 드롭다운에서 특정 텍스트 항목의 a 태그 클릭"""
    return await page.evaluate("""(text) => {
        const menu = document.querySelector('.sao_head_menu');
        if (!menu) return false;
        const items = menu.querySelectorAll('li');
        for (const li of items) {
            if (li.textContent.includes(text)) {
                const a = li.querySelector('a');
                if (a) { a.click(); return true; }
                li.click();
                return true;
            }
        }
        return false;
    }""", item_text)


# ═══════════════════════════════════════════════════════════════════════
# 기간 설정
# ═══════════════════════════════════════════════════════════════════════

async def get_report_period_type(page):
    """원천징수이행상황신고서의 매월/반기 라디오 상태 반환"""
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
        if (monthly) {
            monthly.radio.click();
            return '매월';
        }
        return null;
    }""")
    return result


async def set_period_fields(page, year, start_month, end_month):
    """지급기간/귀속기간 설정. JS sprite click + 드롭다운 닫기 + 3회 재시도 검증."""
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
                entry.years.push({
                    i, text: d.textContent.trim(),
                    x: r.x, y: r.y, w: r.width, h: r.height
                });
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

    for rect in rects:
        label = rect.get("title", "기간항목")
        log(f"    {label}: {year}년 {start_month:02d}월 ~ {end_month:02d}월")

        for retry in range(3):
            # 시작 연도
            if rect["years"]:
                y = rect["years"][0]
                await page.mouse.click(
                    y["x"] + y["w"] / 2, y["y"] + y["h"] / 2, click_count=3
                )
                await asyncio.sleep(0.3)
                await page.keyboard.type(str(year))
                await page.keyboard.press("Enter")
                await asyncio.sleep(0.5)

            # 시작 월: JS로 스프라이트 버튼 클릭 → 드롭다운에서 항목 선택
            if rect["months"]:
                await page.evaluate("""(args) => {
                    const item = document.querySelectorAll('#SearchMain .item')[args.idx];
                    if (!item) return;
                    const btns = item.querySelectorAll('button .WSC_LUXSpriteIcon');
                    const btn = btns[0]?.closest('button');
                    if (btn) btn.click();
                }""", {"idx": rect["idx"]})
                await asyncio.sleep(1)
                await page.evaluate("""(t) => {
                    const all = document.querySelectorAll('*');
                    for (const el of all) {
                        if (el.textContent.trim() === t && el.offsetWidth > 0 && el.offsetWidth < 200) {
                            const li = el.closest('li');
                            if (li) { li.click(); return; }
                            el.click(); return;
                        }
                    }
                }""", f"{start_month:02d}")
                await asyncio.sleep(0.3)
                # 드롭다운 닫기
                await page.evaluate("""() => {
                    document.querySelectorAll('.LSselectResult, div[style*="position: fixed"]').forEach(el => {
                        if (el.offsetWidth > 0) el.style.display = 'none';
                    });
                }""")
                await asyncio.sleep(0.3)

            # 종료 연도
            if len(rect["years"]) > 2:
                y = rect["years"][2]
                await page.mouse.click(
                    y["x"] + y["w"] / 2, y["y"] + y["h"] / 2, click_count=3
                )
                await asyncio.sleep(0.3)
                await page.keyboard.type(str(year))
                await page.keyboard.press("Enter")
                await asyncio.sleep(0.5)

            # 종료 월
            if len(rect["months"]) > 1:
                await page.evaluate("""(args) => {
                    const item = document.querySelectorAll('#SearchMain .item')[args.idx];
                    if (!item) return;
                    const btns = item.querySelectorAll('button .WSC_LUXSpriteIcon');
                    const btn = btns[1]?.closest('button');
                    if (btn) btn.click();
                }""", {"idx": rect["idx"]})
                await asyncio.sleep(1)
                await page.evaluate("""(t) => {
                    const all = document.querySelectorAll('*');
                    for (const el of all) {
                        if (el.textContent.trim() === t && el.offsetWidth > 0 && el.offsetWidth < 200) {
                            const li = el.closest('li');
                            if (li) { li.click(); return; }
                            el.click(); return;
                        }
                    }
                }""", f"{end_month:02d}")
                await asyncio.sleep(0.3)
                # 드롭다운 닫기
                await page.evaluate("""() => {
                    document.querySelectorAll('.LSselectResult, div[style*="position: fixed"]').forEach(el => {
                        if (el.offsetWidth > 0) el.style.display = 'none';
                    });
                }""")
                await asyncio.sleep(0.3)

            # 전체 값 검증
            verify = await page.evaluate("""(args) => {
                const items = document.querySelectorAll('#SearchMain .item');
                if (!items[args.idx]) return null;
                const divs = items[args.idx].querySelectorAll('div[tabindex="0"]');
                return Array.from(divs).map(d => d.textContent.trim());
            }""", {"idx": rect["idx"]})

            expected = [str(year), f"{start_month:02d}", str(year), f"{end_month:02d}"]
            if verify == expected:
                log(f"      verified: {verify}")
                break
            log(f"      mismatch (retry {retry+1}): got {verify}, expected {expected}")
            await asyncio.sleep(0.5)
        else:
            log(f"      FAILED to set period after 3 retries")
