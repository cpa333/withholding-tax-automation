"""홈택스 파일 업로드 모듈

Raon K Uploader 파일 선택 + 파일검증 처리.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from src.utils.log import log
from src.automation.hometax._constants import SELECTOR_BTN_CEN_STS
from src.automation.hometax._session import dismiss_modals


async def select_file(ht, file_path):
    """파일변환신고 화면에서 파일 선택 (Raon K Uploader iframe 내 hidden file input)

    Raon K Uploader가 raonkuploader_frame_fileList iframe에
    <input type="file">을 동적으로 생성함.
    파일 설정 후 change 이벤트를 발생시켜 컴포넌트가 파일을 인식하도록 함.
    """
    log(f"[3] 파일 선택: {os.path.basename(file_path)}")
    for _ in range(15):
        # list(ht.frames) 스냅샷 + per-frame try/except: 재실행 시 페이지 리로드로
        # 프레임이 순회 중 분리(detach)되면 'Frame was detached'가 나므로 건너뛴다.
        for frame in list(ht.frames):
            try:
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
            except Exception:
                # detached/navigating frame → 다음 프레임/다음 폴링에서 재시도
                continue
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


# 비밀번호 팝업 안의 password input을 가진, 표시 중인 WebSquare 팝업을 찾는 헬퍼 JS.
# id에 동적 부분(예: UTERNAAZ65)이 있어 고정 id 대신 "보이는 팝업 + password input"으로 식별.
_JS_FIND_PW_POPUP = """() => {
    const modals = document.querySelectorAll('.w2popup_window');
    for (const m of modals) {
        if (m.offsetParent === null) continue;          // 숨김 팝업 제외
        if (m.querySelector('input[type=password]')) return true;
    }
    return false;
}"""


async def enter_password(ht, password):
    """파일검증 직후 뜨는 '비밀번호입력' 팝업에 전자파일 비밀번호 입력 + 확인.

    파일검증하기 → '이미 검증...' 확인 직후 나타나는 WebSquare 팝업
    (`.w2popup_window` 안의 `input[type=password]`, w2input)에 값을 주입하고
    text가 '확인'인 버튼을 클릭한다. id의 동적 부분에 의존하지 않도록
    "표시 중 팝업 + password input" 기준으로 요소를 찾는다.
    """
    log("[5] 전자파일 비밀번호 입력...")
    if not password:
        log("  비밀번호가 비어 있음 — 입력 건너뜀")
        return False

    # 비밀번호 팝업 대기 (최대 15초)
    for _ in range(15):
        if await ht.evaluate(_JS_FIND_PW_POPUP):
            break
        await asyncio.sleep(1)
    else:
        log("  비밀번호 팝업을 찾지 못함 (15초 초과)")
        return False

    # 값 주입: native setter + input/change/keyup 이벤트 (WebSquare 데이터모델 반영)
    set_len = await ht.evaluate("""(pwd) => {
        const modals = document.querySelectorAll('.w2popup_window');
        for (const m of modals) {
            if (m.offsetParent === null) continue;
            const inp = m.querySelector('input[type=password]');
            if (!inp) continue;
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value').set;
            setter.call(inp, pwd);
            inp.dispatchEvent(new Event('input', { bubbles: true }));
            inp.dispatchEvent(new Event('change', { bubbles: true }));
            inp.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
            return (inp.value || '').length;
        }
        return -1;
    }""", password)
    if set_len != len(password):
        log(f"  비밀번호 주입 실패 (기대 {len(password)}, 실제 {set_len})")
        return False
    await asyncio.sleep(0.5)

    # '확인' 버튼 클릭 (같은 팝업 내, text 매칭)
    clicked = await ht.evaluate("""() => {
        const modals = document.querySelectorAll('.w2popup_window');
        for (const m of modals) {
            if (m.offsetParent === null) continue;
            if (!m.querySelector('input[type=password]')) continue;
            const btns = m.querySelectorAll('input[type=button], button, a[role=button]');
            for (const b of btns) {
                const t = (b.value || b.textContent || '').trim();
                if (t === '확인') { b.click(); return true; }
            }
        }
        return false;
    }""")
    if not clicked:
        log("  '확인' 버튼을 찾지 못함")
        return False

    # 확인 후 검증: 비밀번호 팝업이 사라졌는지 확인 (틀린 비번이면 팝업 유지/에러).
    # 최대 6초 대기하며 팝업이 닫히면 성공, 계속 떠 있으면 실패로 판정.
    await asyncio.sleep(1)
    for _ in range(6):
        if not await ht.evaluate(_JS_FIND_PW_POPUP):
            log("  비밀번호 입력 완료 (팝업 닫힘)")
            return True
        await asyncio.sleep(1)

    log("  비밀번호 확인 후에도 팝업이 남아 있음 — 비밀번호 오류 가능")
    return False


# 제출 화면의 최종 제출 버튼을 text로 식별 (id의 btn_confirm은 모달 확인과 겹칠 수 있어 text 우선).
_JS_FIND_SUBMIT_BTN = """() => {
    for (const b of document.querySelectorAll('input[type=button], button, a[role=button]')) {
        const t = (b.value || b.textContent || '').trim();
        if (t === '전자파일 제출하기') {
            const r = b.getBoundingClientRect();
            const cs = getComputedStyle(b);
            if (cs.display !== 'none' && cs.visibility !== 'hidden' && r.width > 0)
                return true;
        }
    }
    return false;
}"""


async def _wait_and_click_popup(ht, text_regex, btn_text, timeout=15):
    """text_regex(정규식)를 포함한 '표시 중' WebSquare 팝업에서 btn_text 버튼을 클릭.

    성공 시 True. WebSquare 확인/안내 모달을 text 기준으로 안전하게 처리하기 위한 헬퍼
    (dismiss_modals 는 btn_confirm id 를 무차별 클릭해 잘못된 모달을 닫을 수 있어 사용 안 함).
    """
    for _ in range(timeout):
        clicked = await ht.evaluate("""([pat, bt]) => {
            const re = new RegExp(pat);
            for (const m of document.querySelectorAll('.w2popup_window')) {
                if (m.offsetParent === null) continue;
                if (!re.test(m.textContent || '')) continue;
                for (const b of m.querySelectorAll('input[type=button], button, a[role=button]')) {
                    if ((b.value || b.textContent || '').trim() === bt) { b.click(); return true; }
                }
            }
            return false;
        }""", [text_regex, btn_text])
        if clicked:
            return True
        await asyncio.sleep(1)
    return False


async def submit_report(ht, dry_run=True):
    """제출하러 가기 → 전자파일 제출하기 → 확인 2회 → 접수증 (최종 제출).

    관찰된 실제 흐름:
      1) '제출하러 가기'(btn_rigSts) → 제출 화면
      2) '전자파일 제출하기'(text) 클릭
      3) 안내 모달 "정상 변환된 신고서를 제출합니다" → 확인
      4) 확인 모달 "신고서를 제출하시겠습니까?" → 확인
      5) 접수증 팝업 "원천세 신고서 접수증" → 성공 판정 + 닫기

    **되돌릴 수 없는 실제 세금 신고**이므로 dry_run 기본 True로 보호한다.
    dry_run=True: 제출 화면 진입까지만(전자파일 제출하기 직전).
    dry_run=False: 실제 제출 + 접수증 확인.
    """
    log("[6] 제출하러 가기...")
    # 비밀번호 검증 직후 페이지가 안정화되기 전에 클릭하면 화면 전환이 누락되는
    # 레이스가 있어, (재)클릭 재시도 + 대기로 '전자파일 제출하기' 등장을 보장한다.
    await asyncio.sleep(2)
    submit_ready = False
    for attempt in range(5):
        if await ht.evaluate(_JS_FIND_SUBMIT_BTN):
            submit_ready = True
            break
        # '제출하러 가기' 버튼이 (아직) 보이면 클릭. JS click은 모달 오버레이가 있어도 동작.
        re_clicked = await ht.evaluate("""() => {
            const b = document.querySelector('[id*="btn_rigSts"]');
            if (b && b.offsetParent !== null) { b.click(); return true; }
            return false;
        }""")
        if not re_clicked:
            # 진입을 막는 모달이 있으면 text를 남겨 원인 추적(예상 못한 안내/경고 대비).
            mt = await ht.evaluate("""() => {
                for (const m of document.querySelectorAll('.w2popup_window')) {
                    if (m.offsetParent === null) continue;
                    const t = (m.textContent || '').replace(/\\s+/g, ' ').trim();
                    if (t) return t.slice(0, 120);
                }
                return null;
            }""")
            if mt:
                log(f"  [진단] 제출 진입 대기 중 모달: {mt}")
        for _ in range(6):
            if await ht.evaluate(_JS_FIND_SUBMIT_BTN):
                submit_ready = True
                break
            await asyncio.sleep(1)
        if submit_ready:
            break
    if not submit_ready:
        log("  '전자파일 제출하기' 버튼을 찾지 못함 (제출 화면 진입 실패)")
        return False

    if dry_run:
        log("  [dry_run] 제출 화면 진입 완료 — '전자파일 제출하기'는 누르지 않음")
        return True

    # ── 실제 제출 (dry_run=False) ──────────────────────────────────────────
    log("[7] 전자파일 제출하기 클릭 (실제 제출)...")
    await ht.evaluate("""() => {
        for (const b of document.querySelectorAll('input[type=button], button, a[role=button]')) {
            const t = (b.value || b.textContent || '').trim();
            if (t === '전자파일 제출하기') { b.click(); return; }
        }
    }""")

    # 안내 모달 "정상 변환된 신고서를 제출합니다" → 확인
    if not await _wait_and_click_popup(ht, "신고서를 제출합니다", "확인"):
        log("  제출 안내 모달('...제출합니다')을 찾지 못함")
        return False

    # 확인 모달 "신고서를 제출하시겠습니까?" → 확인
    if not await _wait_and_click_popup(ht, "제출하시겠습니까", "확인"):
        log("  제출 확인 모달('제출하시겠습니까')을 찾지 못함")
        return False

    # 접수증 팝업 대기 → 성공 판정
    for _ in range(20):
        receipt = await ht.evaluate("""() => {
            for (const m of document.querySelectorAll('.w2popup_window')) {
                if (m.offsetParent === null) continue;
                const t = m.textContent || '';
                if (/접수증/.test(t)) return t.replace(/\\s+/g, ' ').trim();
            }
            return null;
        }""")
        if receipt:
            # 접수 건수 요약 로그 (총/정상/오류)
            import re
            total = re.search(r"총 신고건수\s*(\d+)", receipt)
            normal = re.search(r"정상건수\s*(\d+)", receipt)
            err = re.search(r"오류건수\s*(\d+)", receipt)
            log(f"  접수증 확인 — 총 {total.group(1) if total else '?'}건 / "
                f"정상 {normal.group(1) if normal else '?'}건 / "
                f"오류 {err.group(1) if err else '?'}건")
            # 접수증 닫기 (닫기 우선, 없으면 확인)
            if not await _wait_and_click_popup(ht, "접수증", "닫기", timeout=2):
                await _wait_and_click_popup(ht, "접수증", "확인", timeout=2)
            log("  제출 완료 (정상 접수)")
            return True
        await asyncio.sleep(1)

    log("  접수증을 확인하지 못함 — 제출 결과 불명(홈택스 신고내역에서 확인 필요)")
    return False
