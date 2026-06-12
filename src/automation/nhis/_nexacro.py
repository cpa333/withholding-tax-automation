"""NHIS EDI Nexacro 프레임워크 제어 헬퍼

웹EDI(Nexacro) 초기화 대기, 라디오/그리드 이벤트 제어.
공통 nexacro 유틸리티(src.utils.nexacro)를 기반으로
NHIS EDI 특화 로직만 포함.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from src.utils.log import log
from src.utils.human import human_delay
from src.utils.nexacro import (
    nexacro_click,
    nexacro_dblclick,
    nexacro_select_combo,
    nexacro_click_radio,
)

# ─── 상수 (NHIS EDI Nexacro 요소 ID) ─────────────────────────────────────────
from src.automation.nhis._constants import (
    RDO_PROG_STAT, RADIO_ITEMS, GRID_RECEIVED, CBO_DOCID, BTN_PRINT,
)


# ─── Nexacro 초기화/제어 함수 ────────────────────────────────────────────────

async def wait_for_nexacro_ready(page):
    """웹EDI(Nexacro) 프레임워크가 완전히 로딩될 때까지 대기

    DOM 요소뿐 아니라 nexacro.Application.mainframe.childframe.form 까지
    접근 가능해야 Nexacro 내부 API로 제어 가능.
    """
    for i in range(30):
        await asyncio.sleep(1)
        try:
            ready = await page.evaluate("""() => {
                try {
                    var n = window.nexacro;
                    if (!n || !n.Application) return false;
                    var mf = n.Application.mainframe;
                    if (!mf || !mf.childframe) return false;
                    var form = mf.childframe.form;
                    if (!form || !form.components) return false;
                    return !!form.components.div_body;
                } catch(e) {
                    return false;
                }
            }""")
            if ready:
                log(f"  Nexacro 프레임워크 준비 완료 ({i+1}초)")
                return True
        except Exception:
            pass
    log("  ERROR: Nexacro 프레임워크 로딩 시간 초과")
    return False


async def nexacro_set_radio(page, index):
    """Nexacro 라디오 컴포넌트를 DOM 클릭 + Nexacro 이벤트로 선택

    Nexacro 컴포넌트 객체가 준비되어도 DOM 렌더링이 늦을 수 있으므로
    DOM 컨테이너가 나타날 때까지 대기 후 클릭.

    Phase 1: DOM 컨테이너 대기 + 클릭 (단일 evaluate)
    Phase 2: Nexacro API로 onitemchanged 트리거 (최선 처리)

    Args:
        page: 웹EDI 탭
        index: 선택할 항목 인덱스 (0=전체, 1=신규, 2=열람)

    Returns:
        dict: {ok, value, index, text}
    """
    target_text = RADIO_ITEMS.get(index)
    if not target_text:
        return {"ok": False, "error": f"Unknown radio index: {index}"}

    # ── Phase 0: DOM 컨테이너 렌더링 대기 (최대 15초) ─────────────────
    log(f"  라디오 DOM 컨테이너 대기...")
    for i in range(15):
        found = await page.evaluate("""(radioId) => {
            return !!document.getElementById(radioId)
                || document.querySelectorAll('[id*=rdo_prog_stat]').length > 0;
        }""", RDO_PROG_STAT)
        if found:
            log(f"  라디오 DOM 준비 완료 ({i+1}초)")
            break
        await asyncio.sleep(1)
    else:
        log("  ERROR: 라디오 DOM 컨테이너 대기 시간 초과 (15초)")
        return {"ok": False, "error": "radio container not found after 15s wait"}

    # ── Phase 1: DOM 클릭 (단일 evaluate, 안정적) ──────────────────────
    click_result = await page.evaluate("""(args) => {
        var container = document.getElementById(args.radioId);
        if (!container) {
            var candidates = document.querySelectorAll('[id*=rdo_prog_stat]');
            if (candidates.length > 0) container = candidates[0];
        }
        if (!container) return {ok: false, error: 'radio container not found'};

        var items = container.querySelectorAll('div[id$="_item"]');
        for (var item of items) {
            var textEl = item.querySelector('[id*=TextBoxElement]');
            if (textEl && textEl.textContent.trim() === args.targetText) {
                var rect = item.getBoundingClientRect();
                var cx = rect.x + rect.width / 2 + (Math.random() * 4 - 2);
                var cy = rect.y + rect.height / 2 + (Math.random() * 4 - 2);
                var base = {
                    bubbles: true, cancelable: true, view: window,
                    screenX: cx, screenY: cy, clientX: cx, clientY: cy,
                    button: 0, buttons: 1, relatedTarget: null
                };
                item.dispatchEvent(new MouseEvent('mousemove', {...base, detail: 0, buttons: 0}));
                var t = performance.now();
                while (performance.now() - t < 30 + Math.random() * 50) {}
                item.dispatchEvent(new MouseEvent('mousedown', {...base, detail: 1}));
                item.dispatchEvent(new MouseEvent('mouseup', {...base, detail: 1}));
                item.dispatchEvent(new MouseEvent('click', {...base, detail: 1}));
                return {ok: true, clicked: args.targetText};
            }
        }
        return {ok: false, error: 'item not found: ' + args.targetText};
    }""", {"radioId": RDO_PROG_STAT, "targetText": target_text})

    if not click_result.get("ok"):
        log(f"  ERROR: 라디오 DOM 클릭 실패 - {click_result}")
        return click_result

    # ── Phase 2: Nexacro API onitemchanged 트리거 (최대 3회 재시도) ───
    for attempt in range(3):
        await asyncio.sleep(0.5)
        result = await page.evaluate("""(targetIdx) => {
            try {
                var n = window.nexacro;
                if (!n || !n.Application) return null;
                var form = n.Application.mainframe.childframe.form;
                var divBody = form.components.div_body;
                var radio = divBody.components.rdo_prog_stat;
                if (!radio || typeof radio.index !== 'number') return null;

                var oldIndex = radio.index;
                var oldValue = radio.value;

                if (radio.index !== targetIdx) {
                    radio.set_index(targetIdx);
                }

                var newValue = radio.value;
                var newIndex = radio.index;
                var newText = radio.text;

                radio.on_fire_onitemchanged(oldValue, newValue, oldIndex, newIndex);

                return {ok: true, value: newValue, index: newIndex, text: newText};
            } catch(e) {
                return null;
            }
        }""", index)

        if result is not None:
            return result

    log("  WARN: Nexacro onitemchanged 트리거 실패 (DOM 클릭은 성공)")
    return {"ok": True, "value": None, "index": index, "text": target_text}


async def nexacro_dblclick_cell(page, grid_id, row, col):
    """Nexacro 그리드 셀에 더블클릭 이벤트 발생

    NHIS EDI 그리드 ID 형식: {grid_id}_body_gridrow_{row}_cell_{row}_{col}
    """
    cell_id = f"{grid_id}_body_gridrow_{row}_cell_{row}_{col}"
    return await nexacro_dblclick(page, cell_id)
