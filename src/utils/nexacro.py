"""Nexacro 프레임워크 DOM 조작 공통 유틸리티

Nexacro 그리드/콤보/라디오 등 컴포넌트 조작을 위한
비동기 JS evaluate 헬퍼. NHIS/NPS EDI 포털에서 공유.

모든 함수는 기존 인라인 page.evaluate() 호출과
동일한 JS 코드를 생성하여 런타임 동작을 보존.
"""

import asyncio
import random


# ──────────────────────────────────────────────────────────────────────────────
# 기본 이벤트 생성 JS 스니펫
# ──────────────────────────────────────────────────────────────────────────────

# mousemove → delay → mousedown → mouseup → click
_JS_CLICK = """
(function() {
    var el = %s;
    if (!el) return null;
    var rect = el.getBoundingClientRect();
    var cx = rect.x + rect.width / 2 + (Math.random() * 4 - 2);
    var cy = rect.y + rect.height / 2 + (Math.random() * 4 - 2);
    var base = {
        bubbles: true, cancelable: true, view: window,
        screenX: cx, screenY: cy, clientX: cx, clientY: cy,
        button: 0, buttons: 1, relatedTarget: null
    };
    el.dispatchEvent(new MouseEvent('mousemove', {...base, detail: 0, buttons: 0}));
    var t = performance.now();
    while (performance.now() - t < 30 + Math.random() * 50) {}
    el.dispatchEvent(new MouseEvent('mousedown', {...base, detail: 1}));
    el.dispatchEvent(new MouseEvent('mouseup', {...base, detail: 1}));
    el.dispatchEvent(new MouseEvent('click', {...base, detail: 1}));
    return {ok: true, cx: cx, cy: cy};
})()
"""

# click + pause + mousedown(detail:2) → mouseup → click → dblclick
_JS_DBLCLICK_SUFFIX = """
    var t = performance.now();
    while (performance.now() - t < 30 + Math.random() * 50) {}
    el.dispatchEvent(new MouseEvent('mousedown', {...base, detail: 2}));
    el.dispatchEvent(new MouseEvent('mouseup', {...base, detail: 2}));
    el.dispatchEvent(new MouseEvent('click', {...base, detail: 2}));
    el.dispatchEvent(new MouseEvent('dblclick', {...base, detail: 2}));
"""


# ──────────────────────────────────────────────────────────────────────────────
# 공통 유틸리티 함수
# ──────────────────────────────────────────────────────────────────────────────

async def nexacro_click(page, element_id):
    """Nexacro 요소에 mousedown/mouseup/click 이벤트 발생

    기존 NHIS _common_edi.py의 nexacro_click과 동일한 동작.
    """
    return await page.evaluate("""(elId) => {
        const el = document.getElementById(elId);
        if (!el) return {error: 'not found: ' + elId};
        const rect = el.getBoundingClientRect();
        const cx = rect.x + rect.width / 2 + (Math.random() * 4 - 2);
        const cy = rect.y + rect.height / 2 + (Math.random() * 4 - 2);
        const base = {
            bubbles: true, cancelable: true, view: window,
            screenX: cx, screenY: cy, clientX: cx, clientY: cy,
            button: 0, buttons: 1, relatedTarget: null
        };
        el.dispatchEvent(new MouseEvent('mousemove', {...base, detail: 0, buttons: 0}));
        const t = performance.now();
        while (performance.now() - t < 30 + Math.random() * 50) {}
        el.dispatchEvent(new MouseEvent('mousedown', {...base, detail: 1}));
        el.dispatchEvent(new MouseEvent('mouseup', {...base, detail: 1}));
        el.dispatchEvent(new MouseEvent('click', {...base, detail: 1}));
        return {ok: true};
    }""", element_id)


async def nexacro_dblclick(page, cell_id):
    """Nexacro 요소에 더블클릭 이벤트 발생 (cell_id 직접 지정)

    기존 NHIS _common_edi.py의 nexacro_dblclick_cell 패턴과 동일.
    NPS 버전은 viewport 판정 + page.mouse.dblclick fallback이 추가되어 있으므로
    NPS에서는 별도 함수(nexacro_dblclick_cell_viewport) 사용.
    """
    return await page.evaluate("""(cellId) => {
        const cell = document.getElementById(cellId);
        if (!cell) return {error: 'cell not found'};
        const rect = cell.getBoundingClientRect();
        const cx = rect.x + rect.width / 2 + (Math.random() * 4 - 2);
        const cy = rect.y + rect.height / 2 + (Math.random() * 4 - 2);
        const base = {
            bubbles: true, cancelable: true, view: window,
            screenX: cx, screenY: cy, clientX: cx, clientY: cy,
            button: 0, buttons: 1, relatedTarget: null
        };
        cell.dispatchEvent(new MouseEvent('mousemove', {...base, detail: 0, buttons: 0}));
        let t = performance.now();
        while (performance.now() - t < 30 + Math.random() * 50) {}
        cell.dispatchEvent(new MouseEvent('mousedown', {...base, detail: 1}));
        cell.dispatchEvent(new MouseEvent('mouseup', {...base, detail: 1}));
        cell.dispatchEvent(new MouseEvent('click', {...base, detail: 1}));
        t = performance.now();
        while (performance.now() - t < 30 + Math.random() * 50) {}
        cell.dispatchEvent(new MouseEvent('mousedown', {...base, detail: 2}));
        cell.dispatchEvent(new MouseEvent('mouseup', {...base, detail: 2}));
        cell.dispatchEvent(new MouseEvent('click', {...base, detail: 2}));
        cell.dispatchEvent(new MouseEvent('dblclick', {...base, detail: 2}));
        return {ok: true, text: cell.textContent.trim()};
    }""", cell_id)


async def nexacro_dblclick_cell_viewport(page, grid_id, row, col):
    """Nexacro 그리드 셀 더블클릭 — viewport 판정 + fallback

    NPS _common.py의 nexacro_dblclick_cell과 동일한 로직.
    viewport 내: page.mouse.dblclick (실제 마우스)
    viewport 밖: 합성 dispatchEvent
    """
    cell_id = f"{grid_id}.body.gridrow_{row}.cell_{row}_{col}"
    text_id = f"{cell_id}:text"

    # 뷰포트 내: 실제 마우스 더블클릭
    try:
        info = await page.evaluate("""(ids) => {
            const target = document.getElementById(ids.textId) || document.getElementById(ids.cellId);
            if (!target) return null;
            const r = target.getBoundingClientRect();
            const inViewport = r.top < window.innerHeight && r.bottom > 0
                            && r.left < window.innerWidth && r.right > 0;
            return {
                x: r.x, y: r.y, w: r.width, h: r.height,
                inViewport: inViewport,
                text: target.textContent.trim()
            };
        }""", {"cellId": cell_id, "textId": text_id})

        if not info:
            return {"error": "cell not found"}

        if info.get('inViewport') and info['w'] > 0 and info['h'] > 0:
            cx = info['x'] + info['w'] / 2 + random.uniform(-2, 2)
            cy = info['y'] + info['h'] / 2 + random.uniform(-2, 2)
            await page.mouse.dblclick(cx, cy)
            return {"ok": True, "text": info.get('text', '')}
    except Exception:
        pass

    # 폴백: 합성 이벤트 dispatch
    return await page.evaluate("""(ids) => {
        const target = document.getElementById(ids.textId) || document.getElementById(ids.cellId);
        if (!target) return {error: 'cell not found'};

        const rect = target.getBoundingClientRect();
        const cx = rect.x + rect.width / 2 + (Math.random() * 4 - 2);
        const cy = rect.y + rect.height / 2 + (Math.random() * 4 - 2);

        const base = {
            bubbles: true, cancelable: true, view: window,
            screenX: cx, screenY: cy, clientX: cx, clientY: cy,
            button: 0, buttons: 1, relatedTarget: null
        };

        target.dispatchEvent(new MouseEvent('mousemove', {...base, detail: 0, buttons: 0}));
        let t = performance.now();
        while (performance.now() - t < 30 + Math.random() * 50) {}

        target.dispatchEvent(new MouseEvent('mousedown', {...base, detail: 1}));
        target.dispatchEvent(new MouseEvent('mouseup', {...base, detail: 1}));
        target.dispatchEvent(new MouseEvent('click', {...base, detail: 1}));

        t = performance.now();
        while (performance.now() - t < 30 + Math.random() * 50) {}

        target.dispatchEvent(new MouseEvent('mousedown', {...base, detail: 2}));
        target.dispatchEvent(new MouseEvent('mouseup', {...base, detail: 2}));
        target.dispatchEvent(new MouseEvent('click', {...base, detail: 2}));
        target.dispatchEvent(new MouseEvent('dblclick', {...base, detail: 2}));

        return {ok: true, text: target.textContent.trim()};
    }""", {"cellId": cell_id, "textId": text_id})


async def nexacro_click_button_viewport(page, element_id):
    """Nexacro 버튼 클릭 — viewport 판정 + fallback

    NPS _common.py의 nexacro_click_button과 동일한 로직.
    """
    # 1) 요소 위치 확인 + 뷰포트 내 판정
    try:
        info = await page.evaluate("""(elId) => {
            const btn = document.getElementById(elId);
            if (!btn) return null;
            const r = btn.getBoundingClientRect();
            const inViewport = r.top < window.innerHeight && r.bottom > 0
                            && r.left < window.innerWidth && r.right > 0;
            return {
                x: r.x, y: r.y, w: r.width, h: r.height,
                inViewport: inViewport,
                text: btn.textContent.trim().substring(0, 40)
            };
        }""", element_id)

        if not info:
            return {"error": f"element not found: {element_id}"}

        if info.get('inViewport') and info['w'] > 0 and info['h'] > 0:
            cx = info['x'] + info['w'] / 2 + random.uniform(-2, 2)
            cy = info['y'] + info['h'] / 2 + random.uniform(-2, 2)
            await page.mouse.click(cx, cy)
            return {"ok": True, "text": info.get('text', '')}
    except Exception:
        pass

    # 2) 폴백: 합성 이벤트 dispatch
    return await page.evaluate("""(elId) => {
        const btn = document.getElementById(elId);
        if (!btn) return {error: 'element not found: ' + elId};

        const rect = btn.getBoundingClientRect();
        const cx = rect.x + rect.width / 2 + (Math.random() * 4 - 2);
        const cy = rect.y + rect.height / 2 + (Math.random() * 4 - 2);

        const base = {
            bubbles: true, cancelable: true, view: window,
            screenX: cx, screenY: cy, clientX: cx, clientY: cy,
            button: 0, buttons: 1, relatedTarget: null
        };

        btn.dispatchEvent(new MouseEvent('mousemove', {...base, detail: 0, buttons: 0}));
        const t = performance.now();
        while (performance.now() - t < 30 + Math.random() * 50) {}

        btn.dispatchEvent(new MouseEvent('mousedown', {...base, detail: 1}));
        btn.dispatchEvent(new MouseEvent('mouseup', {...base, detail: 1}));
        btn.dispatchEvent(new MouseEvent('click', {...base, detail: 1}));

        return {ok: true, text: btn.textContent.trim().substring(0, 40)};
    }""", element_id)


async def nexacro_wait_and_click(page, element_id, max_wait=10):
    """Nexacro 요소가 DOM에 나타날 때까지 대기 후 클릭

    NPS _common.py의 nexacro_wait_and_click과 동일.
    """
    for i in range(max_wait):
        try:
            found = await page.evaluate(
                '(elId) => !!document.getElementById(elId)', element_id
            )
            if found:
                break
        except Exception:
            pass
        await asyncio.sleep(1)
    else:
        return {"error": f"element not found after {max_wait}s: {element_id}"}

    try:
        return await nexacro_click_button_viewport(page, element_id)
    except Exception as e:
        return {"error": f"click failed: {e}"}


async def nexacro_select_combo(page, combo_id, item_text):
    """Nexacro 콤보박스에서 특정 텍스트 항목 선택

    combolist가 이미 열려있어야 함 (dropbutton 클릭 후).
    기존 NHIS _common_edi.py의 nexacro_select_combo와 동일.
    """
    return await page.evaluate("""(args) => {
        var list = document.getElementById(args.comboId + '_combolist');
        if (!list) return {error: 'combolist not found'};
        var items = list.querySelectorAll('div[id$="_item"]');
        for (var item of items) {
            var textEl = item.querySelector('[id*=TextBoxElement]');
            if (textEl && textEl.textContent.trim() === args.itemText) {
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
                return {ok: true, text: args.itemText};
            }
        }
        return {error: 'item not found: ' + args.itemText};
    }""", {"comboId": combo_id, "itemText": item_text})


async def nexacro_click_radio(page, radio_id, item_text):
    """Nexacro 라디오 그룹에서 특정 텍스트 항목 선택

    기존 NHIS _common_edi.py의 nexacro_click_radio와 동일.
    """
    return await page.evaluate("""(args) => {
        var container = document.getElementById(args.radioId);
        if (!container) return {error: 'radio not found'};
        var items = container.querySelectorAll('div[id$="_item"]');
        for (var item of items) {
            var textEl = item.querySelector('[id*=TextBoxElement]');
            if (textEl && textEl.textContent.trim() === args.itemText) {
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
                return {ok: true};
            }
        }
        return {error: 'item not found: ' + args.itemText};
    }""", {"radioId": radio_id, "itemText": item_text})


async def nexacro_find_row(page, grid_id, col, text):
    """Nexacro 그리드에서 특정 텍스트가 포함된 행 인덱스 검색

    NPS _common.py의 nexacro_find_row와 동일.
    NPS 형식: grid_id + '.body.gridrow_{N}.cell_{N}_{col}'

    Args:
        page: Playwright page
        grid_id: Nexacro 그리드 ID prefix
        col: 검색할 열 인덱스
        text: 검색할 텍스트 (부분 매칭)

    Returns:
        int or None: 매칭된 행 인덱스
    """
    return await page.evaluate("""(args) => {
        const prefix = args.gridId + '.body.gridrow_';
        const allCells = document.querySelectorAll('[id^="' + prefix + '"]');
        for (const cell of allCells) {
            const id = cell.id;
            if (!id.includes('.cell_')) continue;
            const match = id.match(/gridrow_(\\d+)\\.cell_\\d+_(\\d+)/);
            if (!match) continue;
            const rowIdx = parseInt(match[1]);
            const colIdx = parseInt(match[2]);
            if (colIdx !== args.col) continue;
            if (cell.textContent.trim().includes(args.text)) {
                return rowIdx;
            }
        }
        return null;
    }""", {"gridId": grid_id, "col": col, "text": text})


async def nexacro_get_grid_data(page, grid_id):
    """Nexacro 그리드의 모든 가시 행 데이터 반환

    NPS _common.py의 nexacro_get_grid_data와 동일.

    Returns:
        list[list[str]]: 2차원 배열 (행 × 열)
    """
    return await page.evaluate("""(gridId) => {
        const prefix = gridId + '.body.gridrow_';
        const rows = {};
        const cells = document.querySelectorAll('[id^="' + prefix + '"]');
        for (const cell of cells) {
            const id = cell.id;
            const match = id.match(/gridrow_(\\d+)\\.cell_\\d+_(\\d+)$/);
            if (!match) continue;
            const row = parseInt(match[1]);
            const col = parseInt(match[2]);
            if (!rows[row]) rows[row] = {};
            rows[row][col] = cell.textContent.trim();
        }
        return Object.keys(rows).sort((a,b) => a-b).map(r => {
            const row = rows[r];
            const maxCol = Math.max(...Object.keys(row).map(Number));
            const arr = [];
            for (let c = 0; c <= maxCol; c++) arr.push(row[c] || '');
            return arr;
        });
    }""", grid_id)
