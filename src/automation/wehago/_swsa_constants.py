"""SWSA0101 (급여자료입력) 전용 상수

JS 상수 문자열(React LS_calendar) + Windows PrintDialog 상수.
"""

import sys

# ─── Windows PrintDialog 상수 ─────────────────────────────────────────────────
PRINT_DIALOG_TITLE_RE = r"Duzon.*PrintDialog"
PRINT_DIALOG_CLASS_RE = r"WindowsForms10\.Window.*"
SAVE_DIALOG_CLASS = "#32770"
DEFAULT_PRINT_FORMAT = "급여명세(사원당 한장)"

# 급여명세 PDF 페이즈(6번)에서 수임처별로 함께 다운로드할 인쇄형태 목록.
# 같은 수임처 폴더에 각각 저장.
# ★cbContents 드롭다운 "상단→하단" 순서로 기재★ — click_input 선택이 스크롤 위치의
# 영향을 받아, 역순(하단→상단) 선택 시 스크롤 업이 꼬여 잘못된 항목이 선택된다.
# cbContents 순서: 급여명세(구)[0], 급여대장[1], ..., 급여명세(사원당 한장)[5], ...
# 급여대장[1](상단)을 먼저, 급여명세(사원당 한장)[5](하단)을 나중에 받는다.
SALARY_PDF_FORMATS = ["급여대장", DEFAULT_PRINT_FORMAT]


# ═══════════════════════════════════════════════════════════════════════════════
# SWSA0101 귀속연월 설정용 JS 상수 (React LS_calendar)
# ═══════════════════════════════════════════════════════════════════════════════

_READ_SWSA_YM_JS = """() => {
    const items = document.querySelectorAll('#SearchMain .item');
    for (const item of items) {
        const title = item.querySelector('.item_title, strong');
        if (title && title.textContent.trim() === '귀속연월') {
            return item.querySelector('.fakeinput')?.textContent.trim() || '';
        }
    }
    return '';
}"""

_READ_CALENDAR_YEAR_JS = """() => {
    return document.querySelector('.LS_calendar .date_day_title')?.textContent.trim() || '';
}"""

_REACT_SET_CALENDAR_YEAR_JS = """(targetYear) => {
    const all = document.querySelectorAll('*');
    for (const el of all) {
        const keys = Object.keys(el).filter(k => k.startsWith('__reactInternalInstance'));
        for (const key of keys) {
            let node = el[key];
            const queue = [node];
            const visited = new Set();
            for (let depth = 0; depth < 25 && queue.length > 0; depth++) {
                const current = queue.shift();
                if (!current || visited.has(current)) continue;
                visited.add(current);
                const inst = current._instance;
                if (inst && inst.state && inst.state.selectedDate
                    && typeof inst.state.selectedDate.year === 'number') {
                    const oldYear = inst.state.selectedDate.year;
                    const oldMonth = inst.state.selectedDate.month;
                    const newMax = {year: targetYear, month: 12};
                    const newMin = inst.state.minDate
                        ? {year: Math.min(inst.state.minDate.year, targetYear - 1), month: 1}
                        : {year: targetYear - 1, month: 1};
                    inst.setState({
                        selectedDate: {year: targetYear, month: oldMonth},
                        maxDate: newMax,
                        minDate: newMin,
                    });
                    return {success: true, oldYear, oldMonth, newMax, newMin};
                }
                if (current._renderedChildren) {
                    for (const child of Object.values(current._renderedChildren)) {
                        if (child) queue.push(child);
                    }
                }
                if (current._renderedComponent) queue.push(current._renderedComponent);
                if (current.child) queue.push(current.child);
                if (current.sibling) queue.push(current.sibling);
                if (current.return) queue.push(current.return);
            }
        }
    }
    return {success: false};
}"""
