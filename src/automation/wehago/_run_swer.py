"""원천징수 전자신고(SWER0101) 전체 자동화

WEHAGO 로그인 → 수임처 급여 → SWSA0101 → SWER0101 →
지급기간 설정 → 수임처 선택 → 제작(F4) →
비밀번호 입력 → 전자신고 파일 제작 → WehagoNTS 폴더 선택 → 파일 저장.

사전 조건:
- Chrome CDP 모드(port 9223) 실행 (src/utils/chrome_cdp.py 사용)
- WEHAGO 로그인 대기 (수동 로그인 후 자동 감지)

실행: python _run_swer.py
"""
import asyncio
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

import comtypes.client

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from playwright.async_api import async_playwright
from src.utils.chrome_cdp import CDP_URL

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding="utf-8")
WEHAGO_URL = "https://www.wehago.com/"
PASSWORD = "asdfghjk"
COMPANY_NAME = "[테스트] (주)리틀치프코리아"
DESKTOP_PATH = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")
NTS_FOLDER = "원천징수전자신고"


def log(msg):
    print(msg, flush=True)


# ═══════════════════════════════════════════════════════════════════════
# WehagoNTS (Windows Forms) 제어 — COM UIAutomation
# ═══════════════════════════════════════════════════════════════════════

def select_nts_folder(folder_name):
    """WehagoNTS 폴더 선택 다이얼로그에서 바탕화면/지정폴더 선택 후 확인.

    처리 흐름:
    1. WehagoNTS 프로세스 대기 (최대 20초)
    2. "이미 기록된 파일" 질의 → 예(Y) 자동 클릭
    3. FormSelectFolder 창에서 바탕화면 확장 → 폴더 선택
    4. 확인 → 후속 모달(질의/안내) 자동 처리
    5. 바탕화면에 남은 파일 → 폴더로 이동
    """
    comtypes.CoInitialize()
    UIA = comtypes.client.GetModule("UIAutomationCore.dll")
    uia = comtypes.CoCreateInstance(
        UIA.CUIAutomation._reg_clsid_, interface=UIA.IUIAutomation
    )

    pid = _wait_for_nts(uia)
    if not pid:
        return False

    root = uia.GetRootElement()
    cond_pid = uia.CreatePropertyCondition(UIA.UIA_ProcessIdPropertyId, pid)
    nts_root = root.FindFirst(UIA.TreeScope_Children, cond_pid)
    if not nts_root:
        log("  NTS root not found")
        return False

    target_path = os.path.join(DESKTOP_PATH, folder_name)
    if not os.path.exists(target_path):
        os.makedirs(target_path)
        log(f"  폴더 생성: {target_path}")

    form = _wait_for_folder_dialog(UIA, uia, nts_root)
    if not form:
        return False
    log("  폴더 선택 창 감지")

    if not _select_tree_folder(UIA, uia, form, folder_name):
        return False

    # 경로 확인
    cond_lbl = uia.CreatePropertyCondition(
        UIA.UIA_AutomationIdPropertyId, "lblSelectNode"
    )
    lbl = form.FindFirst(UIA.TreeScope_Descendants, cond_lbl)
    if lbl:
        log(f"  경로: {lbl.CurrentName}")

    # 확인 버튼
    if not _invoke_btn(UIA, uia, nts_root, "btnOK"):
        log("  확인 클릭 실패")
        return False
    log("  확인 클릭")

    _handle_nts_modals(UIA, uia, nts_root)
    _move_desktop_files_to_folder(target_path, folder_name)

    if os.path.exists(target_path) and os.listdir(target_path):
        log(f"  완료: {folder_name}/ 에 {len(os.listdir(target_path))}개 파일")
        return True

    log("  파일 저장 확인 실패")
    return False


def _wait_for_nts(uia):
    """WehagoNTS.exe 프로세스 시작 대기 (최대 20초)"""
    for _ in range(20):
        r = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq WehagoNTS.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True,
        )
        try:
            pid = int(r.stdout.split(",")[1].strip('"'))
            log(f"  WehagoNTS PID: {pid}")
            return pid
        except (IndexError, ValueError):
            pass
        time.sleep(1)
    log("  WehagoNTS not running (timeout)")
    return None


def _wait_for_folder_dialog(UIA, uia, nts_root):
    """FormSelectFolder 대기. 중간에 '이미 기록된 파일' 질의 처리."""
    cond_form = uia.CreatePropertyCondition(
        UIA.UIA_AutomationIdPropertyId, "FormSelectFolder"
    )
    cond_win = uia.CreatePropertyCondition(
        UIA.UIA_ControlTypePropertyId, UIA.UIA_WindowControlTypeId
    )

    for _ in range(15):
        # "이미 기록된 파일" 질의 선처리
        try:
            windows = nts_root.FindAll(UIA.TreeScope_Children, cond_win)
            for j in range(windows.Length):
                w = windows.GetElement(j)
                if w.CurrentName == "질의" and _is_overwrite_query(UIA, uia, w):
                    _invoke_btn(UIA, uia, w, "6")
                    log("  '이미 기록된 파일' → 예(Y) 클릭")
                    time.sleep(2)
        except Exception:
            pass

        try:
            form = nts_root.FindFirst(UIA.TreeScope_Descendants, cond_form)
            if form and form.CurrentAutomationId == "FormSelectFolder":
                return form
        except Exception:
            pass
        time.sleep(1)

    log("  FormSelectFolder not found (timeout)")
    return None


def _is_overwrite_query(UIA, uia, window):
    """창이 '이미 기록된 파일' 질의인지 확인"""
    cond_text = uia.CreatePropertyCondition(
        UIA.UIA_ControlTypePropertyId, UIA.UIA_TextControlTypeId
    )
    texts = window.FindAll(UIA.TreeScope_Descendants, cond_text)
    msg = "".join(texts.GetElement(i).CurrentName for i in range(texts.Length))
    return "이미 기록된 파일" in msg


def _select_tree_folder(UIA, uia, form, folder_name):
    """트리에서 바탕화면 확장 후 폴더 선택"""
    cond_tree = uia.CreatePropertyCondition(
        UIA.UIA_AutomationIdPropertyId, "treeDir"
    )
    tree = form.FindFirst(UIA.TreeScope_Descendants, cond_tree)
    if not tree:
        log("  treeDir not found")
        return False

    cond_item = uia.CreatePropertyCondition(
        UIA.UIA_ControlTypePropertyId, UIA.UIA_TreeItemControlTypeId
    )

    # 바탕화면 노드 찾기
    items = tree.FindAll(UIA.TreeScope_Children, cond_item)
    desktop_item = None
    for i in range(items.Length):
        if items.GetElement(i).CurrentName == "바탕화면":
            desktop_item = items.GetElement(i)
            break

    if not desktop_item:
        log("  바탕화면 노드 not found")
        return False

    # 바탕화면 확장
    try:
        exp = desktop_item.GetCurrentPattern(UIA.UIA_ExpandCollapsePatternId)
        exp.QueryInterface(UIA.IUIAutomationExpandCollapsePattern).Expand()
        time.sleep(1.5)
    except Exception:
        pass

    # 폴더 찾기
    sub_items = desktop_item.FindAll(UIA.TreeScope_Descendants, cond_item)
    for i in range(sub_items.Length):
        si = sub_items.GetElement(i)
        if si.CurrentName == folder_name:
            try:
                sel = si.GetCurrentPattern(UIA.UIA_SelectionItemPatternId)
                sel.QueryInterface(UIA.IUIAutomationSelectionItemPattern).Select()
                time.sleep(0.5)
            except Exception:
                pass
            log(f"  폴더 선택: {folder_name}")
            return True

    # 폴더가 트리에 없으면 바탕화면 선택
    try:
        sel = desktop_item.GetCurrentPattern(UIA.UIA_SelectionItemPatternId)
        sel.QueryInterface(UIA.IUIAutomationSelectionItemPattern).Select()
        time.sleep(0.5)
    except Exception:
        pass
    log(f"  '{folder_name}' 트리에 없음 → 바탕화면 선택")
    return True


def _handle_nts_modals(UIA, uia, nts_root):
    """확인 후 후속 모달(질의/안내) 자동 처리"""
    cond_win = uia.CreatePropertyCondition(
        UIA.UIA_ControlTypePropertyId, UIA.UIA_WindowControlTypeId
    )

    for _ in range(10):
        time.sleep(2)
        try:
            windows = nts_root.FindAll(UIA.TreeScope_Children, cond_win)
            if windows.Length == 0:
                break

            w = windows.GetElement(0)
            win_name = w.CurrentName

            if win_name == "질의":
                if _is_overwrite_query(UIA, uia, w):
                    _invoke_btn(UIA, uia, w, "6")
                    log("  '이미 기록된 파일' → 예(Y) 클릭")
                else:
                    _invoke_btn(UIA, uia, w, "6")
                    log("  질의 → 예(Y) 클릭")
                continue

            if win_name == "안내":
                _invoke_btn(UIA, uia, w, "2")
                log("  안내 모달 닫기")
                break
        except Exception:
            pass


def _invoke_btn(UIA, uia, parent, auto_id):
    """auto_id로 버튼 찾아서 Invoke 패턴 실행"""
    cond = uia.CreatePropertyCondition(
        UIA.UIA_AutomationIdPropertyId, auto_id
    )
    btn = parent.FindFirst(UIA.TreeScope_Descendants, cond)
    if not btn:
        return False
    try:
        inv = btn.GetCurrentPattern(UIA.UIA_InvokePatternId)
        inv.QueryInterface(UIA.IUIAutomationInvokePattern).Invoke()
        return True
    except Exception:
        return False


def _move_desktop_files_to_folder(target_path, folder_name):
    """바탕화면에 남은 .01 파일을 폴더로 이동"""
    for f in os.listdir(DESKTOP_PATH):
        if f.endswith(".01") and os.path.isfile(os.path.join(DESKTOP_PATH, f)):
            os.rename(os.path.join(DESKTOP_PATH, f), os.path.join(target_path, f))
            log(f"  파일 이동: {f} → {folder_name}/")


# ═══════════════════════════════════════════════════════════════════════
# 브라우저 모달 처리
# ═══════════════════════════════════════════════════════════════════════

async def dismiss_dialogs(page):
    """_isDialog, LUX_basic_dialog, z-index overlay 모달 닫기"""
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


# ═══════════════════════════════════════════════════════════════════════
# 지급기간 설정
# ═══════════════════════════════════════════════════════════════════════

async def set_period_fields(page, year, start_month, end_month):
    """지급기간/귀속기간 설정. 3회 재시도 + 전체 값 검증."""
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

    for idx, rect in enumerate(rects):
        label = rect.get("title", f"항목{idx}")
        log(f"    {label}: {year}년 {start_month:02d}월 ~ {end_month:02d}월")

        for retry in range(3):
            # 시작 연도: triple-click → 타이핑 → Enter
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
                # 드롭다운 닫기: JS로 열린 드롭다운 패널 직접 숨김
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
                # 드롭다운 닫기: JS로 열린 드롭다운 패널 직접 숨김
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


# ═══════════════════════════════════════════════════════════════════════
# 비밀번호 입력 + 전자신고 파일 제작
# ═══════════════════════════════════════════════════════════════════════

async def set_password_and_submit(page, password):
    """LSinput 컴포넌트 비밀번호 입력 + 전자신고 파일 제작.

    LSinput 특성상 keyboard type만으로는 fakeinput(placeholder)이 갱신 안 됨.
    해결: native setter로 input.value 설정 + fakeinput 직접 조작.
    비밀번호 규칙 경고 시 확인 클릭 → 재입력 → 재제출 (최대 3회).
    """
    for attempt in range(1, 4):
        await close_warning_overlay(page, "최소 8~15자리")
        await asyncio.sleep(0.3)

        # native setter + fakeinput 직접 조작
        set_result = await page.evaluate("""(pwd) => {
            const dialogs = document.querySelectorAll('._isDialog');
            for (const d of dialogs) {
                if (d.offsetWidth < 100 || !d.textContent.includes('변환파일 비밀번호')) continue;
                const inp = d.querySelector('input.LSinput');
                const fake = d.querySelector('.fakeinput');
                if (!inp || !fake) return 'no elements';

                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value'
                ).set;
                setter.call(inp, pwd);
                fake.classList.remove('placeholder');
                fake.textContent = pwd;
                inp.dispatchEvent(new Event('input', { bubbles: true }));
                inp.dispatchEvent(new Event('change', { bubbles: true }));
                return 'ok';
            }
            return 'no dialog';
        }""", password)
        if set_result != "ok":
            log(f"    failed (attempt {attempt}): {set_result}")
            await asyncio.sleep(1)
            continue
        await asyncio.sleep(0.3)

        # 검증
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

        if not val or val.get("fake", "") != password or val.get("val", "") != password:
            log(f"    mismatch (attempt {attempt}): {json.dumps(val, ensure_ascii=False)}")
            continue

        log(f"    password OK (attempt {attempt})")

        # 전자신고 파일 제작(Enter) 클릭
        log("    전자신고 파일 제작(Enter) 클릭...")
        await page.evaluate("""() => {
            const btns = document.querySelectorAll('button');
            for (const btn of btns) {
                if (btn.textContent.trim() === '전자신고 파일 제작(Enter)' && btn.offsetWidth > 0) {
                    btn.click(); return;
                }
            }
        }""")
        await asyncio.sleep(3)

        # 비밀번호 규칙 경고 확인 → 확인 클릭 후 재시도
        pwd_warning = await page.evaluate("""() => {
            const all = document.querySelectorAll('*');
            for (const el of all) {
                try {
                    const cs = window.getComputedStyle(el);
                    if (cs.position !== 'fixed' || cs.display === 'none'
                        || parseInt(cs.zIndex) < 1000 || el.offsetWidth < 50) continue;
                    const txt = el.textContent.trim();
                    if (txt.includes('비밀번호는 최소 8~15자리')) return txt.substring(0, 200);
                } catch(e) {}
            }
            return null;
        }""")
        if pwd_warning:
            log(f"    비밀번호 규칙 경고 감지 → 확인 클릭 후 재시도")
            await close_warning_overlay(page, "최소 8~15자리")
            await asyncio.sleep(0.5)
            continue

        # 기타 에러 확인
        has_error = await page.evaluate("""() => {
            const all = document.querySelectorAll('*');
            for (const el of all) {
                try {
                    const cs = window.getComputedStyle(el);
                    if (cs.position !== 'fixed' || cs.display === 'none'
                        || parseInt(cs.zIndex) < 1000 || el.offsetWidth < 50) continue;
                    const txt = el.textContent.trim();
                    if (txt.includes('전자신고 파일 제작') || txt.includes('홈택스 ID')) continue;
                    if ((txt.includes('오류') || txt.includes('에러')
                        || txt.includes('실패')) && txt.length < 300) return txt.substring(0, 100);
                } catch(e) {}
            }
            return null;
        }""")
        if has_error:
            log(f"    error: {has_error[:60]}")
            continue

        return True

    log("    FAILED after 3 attempts")
    return False


# ═══════════════════════════════════════════════════════════════════════
# 메인 플로우
# ═══════════════════════════════════════════════════════════════════════

async def goto_menu_page(page, menu_id):
    """SmartA 내 메뉴 URL 해시 교체 이동

    URL 패턴: /smarta/humanresource/{MENU_ID}?params
    예: /smarta/humanresource/SWSA0101 → /smarta/humanresource/SWER0101
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


async def main():
    async with async_playwright() as p:
        # ── [1] Chrome CDP 연결 ──────────────────────────────────
        log("[1] Chrome CDP 연결...")
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0]

        from src.utils.stealth import stealth_all_pages, register_auto_stealth
        await stealth_all_pages(context)
        register_auto_stealth(context)

        page = context.pages[0] if context.pages else await context.new_page()

        # ── [2] WEHAGO 로그인 ────────────────────────────────────
        log("[2] WEHAGO 메인 이동...")
        await page.goto(WEHAGO_URL + "#/main", wait_until="domcontentloaded", timeout=15000)
        await asyncio.sleep(3)

        has_login = (
            await page.locator("#company_").count() > 0
            or await page.locator("text=나의 수임처").count() > 0
        )
        if not has_login:
            log("\n브라우저에서 WEHAGO 로그인을 진행해 주세요.")
            log("로그인 완료 후 여기서 감지합니다...\n")
            for i in range(120):
                await asyncio.sleep(5)
                try:
                    if await page.locator("text=나의 수임처").count() > 0:
                        log("로그인 확인됨!")
                        break
                    await page.reload(wait_until="domcontentloaded")
                    await asyncio.sleep(2)
                    if await page.locator("text=나의 수임처").count() > 0:
                        log("로그인 확인됨!")
                        break
                except Exception:
                    pass
                if i % 6 == 5:
                    log(f"  로그인 대기 중... {(i+1)*5}초")
            else:
                log("로그인 대기 시간 초과.")
                return
        else:
            log("  이미 로그인되어 있습니다.")

        # ── [3] 전체 탭 + 팝업 닫기 ──────────────────────────────
        log("[3] 전체 탭 클릭...")
        await page.evaluate("""() => {
            const tabs = document.querySelectorAll('.tab_list button, .tab_list a');
            for (const tab of tabs) {
                if (tab.textContent.trim() === '전체') { tab.click(); return; }
            }
        }""")
        await asyncio.sleep(1)
        await dismiss_dialogs(page)

        # ── [4] 수임처 급여(SmartA) 이동 ─────────────────────────
        log(f"\n[4] '{COMPANY_NAME}' 급여 이동...")
        await page.evaluate("""() => {
            window.__capturedUrl = null;
            window.__origOpen = window.open;
            window.open = function(url) { window.__capturedUrl = url; return null; };
        }""")
        clicked = await page.evaluate("""(cn) => {
            const allDivs = document.querySelectorAll('[id^="company_"]');
            for (const div of allDivs) {
                const nameEl = div.querySelector('a');
                if (nameEl && nameEl.textContent.trim() === cn) {
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
        }""", COMPANY_NAME)
        if not clicked:
            log(f"  '{COMPANY_NAME}' 급여 버튼 못 찾음")
            return
        await asyncio.sleep(1)
        url = await page.evaluate("() => window.__capturedUrl")
        await page.evaluate("() => { window.open = window.__origOpen; }")
        if not url:
            log("  SmartA URL 없음")
            return
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        await dismiss_dialogs(page)

        # ── [5] 급여자료입력(SWSA0101) 진입 ─────────────────────
        log("[5] 급여자료입력(SWSA0101) 메뉴 진입...")
        await page.evaluate("""() => {
            const link = document.querySelector('a#SWSA0101.text_link');
            if (link) link.click();
        }""")
        await asyncio.sleep(3)
        await dismiss_dialogs(page)

        # ── [6] 원천징수 전자신고(SWER0101) 이동 ────────────────
        log("[6] 원천징수 전자신고(SWER0101) 이동...")
        await goto_menu_page(page, "SWER0101")
        await asyncio.sleep(3)
        await dismiss_dialogs(page)

        # ── [7] 지급기간 설정 (저번달) ──────────────────────────
        now = datetime.now()
        target_year = now.year if now.month > 1 else now.year - 1
        target_month = now.month - 1 if now.month > 1 else 12
        log(f"[7] 지급기간: {target_year}년 {target_month:02d}월")
        await set_period_fields(page, target_year, target_month, target_month)

        # ── [8] 수임처 아이콘 → 코드도움 확인 ───────────────────
        log("[8] 수임처 아이콘 클릭...")
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

        # ── [9] 제작(F4) ─────────────────────────────────────────
        log("[9] 제작(F4) 클릭...")
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

        # ── [10] 모달 대기: 참고사항 or 비밀번호 ──────────────────
        log("[10] 모달 대기...")
        modal_found = False
        for i in range(20):
            await asyncio.sleep(1)
            found = await page.evaluate("""() => {
                const dialogs = document.querySelectorAll('._isDialog');
                for (const d of dialogs) {
                    if (d.offsetWidth > 100 && d.textContent.includes('변환파일 비밀번호'))
                        return 'pwd';
                    if (d.offsetWidth > 100 && d.textContent.includes('참고사항'))
                        return 'ref';
                }
                return null;
            }""")
            if found:
                log(f"  [{i+1}s] modal: {found}")
                modal_found = True
                if found == "pwd":
                    break
                elif found == "ref":
                    log("  참고사항 모달 닫기...")
                    await dismiss_dialogs(page)

        if not modal_found:
            log("  ERROR: No modal detected!")
            return

        # 비밀번호 모달 ready 대기
        for i in range(15):
            await asyncio.sleep(1)
            if await page.evaluate("""() => {
                const dialogs = document.querySelectorAll('._isDialog');
                for (const d of dialogs) {
                    if (d.offsetWidth > 100 && d.textContent.includes('변환파일 비밀번호'))
                        return true;
                }
                return false;
            }"""):
                log(f"  [{i+1}s] 비밀번호 modal ready")
                break
        else:
            log("  ERROR: 비밀번호 modal not found!")
            return

        await asyncio.sleep(2)

        # ── [11] 비밀번호 입력 + 전자신고 파일 제작 ──────────────
        log("[11] 비밀번호 입력 + 전자신고 파일 제작...")
        success = await set_password_and_submit(page, PASSWORD)
        if not success:
            log("\nFAILED: 비밀번호 제출 실패")
            return

        # ── [12] WehagoNTS 폴더 선택 + 파일 저장 ─────────────────
        log("\n[12] WehagoNTS 폴더 선택...")
        loop = asyncio.get_event_loop()
        nts_ok = await loop.run_in_executor(None, select_nts_folder, NTS_FOLDER)

        if nts_ok:
            log("\n=== SUCCESS ===")
        else:
            log("\n  WARNING: NTS 폴더 선택 실패")

        await page.screenshot(path="current_screen.png")


if __name__ == "__main__":
    asyncio.run(main())
