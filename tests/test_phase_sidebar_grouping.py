"""사이드바 카테고리화(아코디언) 테스트.

두 층위:
  1) group_phases — 순수 함수(Qt 무관). is_list_phase 상단 고정 + portal 3분류 불변식.
     ★ 핵심 불변식: phase 1 은 portal="wehago" 이지만 is_list_phase 라서 위하고가
       아니라 상단 고정으로 가야 한다(portal 분류보다 먼저 떼어냄).
  2) PhaseSidebar 위젯(offscreen) — 전 버튼 등록 보존, 재진입 무중복, 섹션 토글,
     접힘 중 update_phase_status 안전.

라이브 UI 불필요(위젯 단위, offscreen). isHidden() 으로 가시성 단언(미표시 위젯은
isVisible() 이 항상 False 이므로).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEvent

from src.ui.widgets.phase_sidebar import (
    PhaseSidebar, PhaseButton, CollapsibleSection, group_phases,
)

app = QApplication.instance() or QApplication([])


def _phases():
    """실제 10개 phase 를 모사한 합성 입력(무거운 워크플로우 import 회피)."""
    def p(pid, name, portal, is_list=False):
        return {"phase_id": pid, "display_name": name, "portal": portal,
                "enabled": True, "is_list_phase": is_list}
    return [
        p(1, "수임처 리스트 확보", "wehago", is_list=True),
        p(2, "공단 EDI 병렬 자동화", "parallel"),
        p(3, "국민건강보험 EDI", "nhis_edi"),
        p(4, "국민연금 EDI", "nps_edi"),
        p(5, "고용보험 EDI", "comwel_edi"),
        p(6, "WEHAGO 급여자료입력", "wehago"),
        p(7, "WEHAGO 급여명세 PDF", "wehago"),
        p(8, "WEHAGO 원천이행상황신고서", "wehago"),
        p(9, "WEHAGO 원천전자신고", "wehago"),
        p(10, "홈택스 원천세 신고", "hometax"),
    ]


def _ids(items):
    return [x["phase_id"] for x in items]


def _grouped(phases):
    """(pinned_ids, {카테고리명: [ids...]}, 카테고리 순서) 로 평탄화."""
    pinned, groups = group_phases(phases)
    return _ids(pinned), {name: _ids(items) for name, items in groups}, [n for n, _ in groups]


# ── 1) group_phases 순수 테스트 ──

def test_pinned_is_only_list_phase():
    """상단 고정 = is_list_phase 뿐(phase 1). portal=wehago 여도 위하고로 안 감."""
    pinned_ids, groups, _ = _grouped(_phases())
    assert pinned_ids == [1]
    assert 1 not in groups.get("위하고", [])   # ★ 불변식: 위하고에 흡수되지 않음


def test_category_order_and_membership():
    pinned_ids, groups, order = _grouped(_phases())
    assert order == ["공단 EDI", "위하고", "홈택스"]
    assert groups["공단 EDI"] == [2, 3, 4, 5]
    assert groups["위하고"] == [6, 7, 8, 9]
    assert groups["홈택스"] == [10]


def test_sorted_within_group_regardless_of_input_order():
    """입력이 뒤섞여도 pinned/각 그룹 내부는 phase_id 오름차순."""
    reversed_phases = list(reversed(_phases()))
    pinned_ids, groups, order = _grouped(reversed_phases)
    assert pinned_ids == [1]
    assert order == ["공단 EDI", "위하고", "홈택스"]
    assert groups["공단 EDI"] == [2, 3, 4, 5]
    assert groups["위하고"] == [6, 7, 8, 9]


def test_empty_category_omitted():
    """홈택스 phase 를 빼면 홈택스 그룹은 생성되지 않는다."""
    phases = [p for p in _phases() if p["portal"] != "hometax"]
    _, groups, order = _grouped(phases)
    assert "홈택스" not in groups
    assert order == ["공단 EDI", "위하고"]


def test_unknown_portal_goes_to_trailing_fallback():
    """매핑에 없는 portal 은 버리지 않고 후행 '기타'로 모은다."""
    phases = _phases() + [{"phase_id": 99, "display_name": "미지의 항목",
                           "portal": "mystery", "enabled": True, "is_list_phase": False}]
    _, groups, order = _grouped(phases)
    assert groups["기타"] == [99]
    assert order[-1] == "기타"                 # 알려진 카테고리 뒤
    assert order[:3] == ["공단 EDI", "위하고", "홈택스"]


# ── 2) PhaseSidebar 위젯 테스트(offscreen) ──

def test_all_phases_registered_in_buttons():
    """위치(고정/카테고리)와 무관하게 10개 phase 전부 self._buttons 에 등록."""
    sb = PhaseSidebar()
    sb.set_phases(_phases())
    assert set(sb._buttons.keys()) == set(range(1, 11))


def test_reentrant_set_phases_no_duplicate_widgets():
    """set_phases 재호출 시 버튼/섹션 누적 없음(재진입 안전 teardown)."""
    sb = PhaseSidebar()
    sb.set_phases(_phases())
    sb.set_phases(_phases())
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    assert len(sb.findChildren(PhaseButton)) == 10
    assert len(sb.findChildren(CollapsibleSection)) == 3   # 공단EDI/위하고/홈택스
    assert set(sb._buttons.keys()) == set(range(1, 11))


def test_pinned_button_not_inside_any_section():
    """phase 1 버튼은 어떤 CollapsibleSection 에도 속하지 않는다(상단 고정)."""
    sb = PhaseSidebar()
    sb.set_phases(_phases())
    sections = sb.findChildren(CollapsibleSection)
    btn1 = sb._buttons[1]
    assert not any(sec.isAncestorOf(btn1) for sec in sections)
    # 반대로 카테고리 소속 버튼(예: 6)은 어떤 섹션의 자손이어야 한다
    btn6 = sb._buttons[6]
    assert any(sec.isAncestorOf(btn6) for sec in sections)


def test_section_toggle_hides_only_its_body():
    """헤더 클릭 시 해당 섹션 본문만 접힘(독립 토글). 기본은 펼침."""
    sb = PhaseSidebar()
    sb.set_phases(_phases())
    sections = sb.findChildren(CollapsibleSection)
    first, second = sections[0], sections[1]
    assert first._body.isHidden() is False          # 기본 펼침
    first.header.click()
    app.processEvents()
    assert first._body.isHidden() is True           # 접힘
    assert second._body.isHidden() is False         # 다른 섹션은 그대로(독립)
    first.header.click()
    app.processEvents()
    assert first._body.isHidden() is False           # 다시 펼침


def test_update_status_works_while_collapsed():
    """접힌 섹션의 자식이어도 update_phase_status 는 안전하게 상태 반영."""
    sb = PhaseSidebar()
    sb.set_phases(_phases())
    # 공단 EDI 섹션(3번 포함) 접기
    for sec in sb.findChildren(CollapsibleSection):
        if sec.isAncestorOf(sb._buttons[3]):
            sec.header.click()
            break
    app.processEvents()
    sb.update_phase_status(3, "running", 1, 3)      # 예외 없이 동작
    assert sb._buttons[3].status == "running"


def test_first_enabled_auto_selected_is_phase_one():
    """자동 선택은 평면 리스트 기준 첫 활성 = phase 1(고정 후에도 유지)."""
    sb = PhaseSidebar()
    sb.set_phases(_phases())
    assert sb._selected_phase == 1
    assert sb._buttons[1]._selected is True


def test_header_click_does_not_emit_phase_selected():
    """섹션 헤더 클릭은 phase_selected 를 절대 emit 하지 않는다."""
    sb = PhaseSidebar()
    sb.set_phases(_phases())
    received = []
    sb.phase_selected.connect(lambda pid: received.append(pid))
    sb.findChildren(CollapsibleSection)[0].header.click()
    app.processEvents()
    assert received == []
    # 반면 phase 버튼 클릭은 emit
    sb._buttons[6].btn.click()
    app.processEvents()
    assert received == [6]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"PASS: {fn.__name__}")
    print(f"\n모든 사이드바 카테고리화 테스트 통과 ({len(tests)}건)")
