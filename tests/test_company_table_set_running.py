"""CompanyTable.set_running 회귀 테스트 — 병렬 실행 중 정지 버튼 클릭 가능 보장.

버그: 병렬 실행 시작 시 set_run_active(True)+set_buttons_enabled(False)+
set_selected_run_mode(False) 연달아 호출이 full_run_btn(=정지 버튼)을 숨기고
비활성화해 실행 중 정지가 불가능했다. set_running 은 정지 버튼을 항상 보이고
활성화하도록 위젯별 직접 제어로 이를 고친다.

주의: 미표시 위젯은 isVisible() 이 항상 False 이므로 isHidden() 으로 가시성 단언.
라이브 UI 불필요(위젯 단위, offscreen).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.ui.widgets.company_table import CompanyTable
from src.ui.styles import BTN_RED, BTN_GREEN

app = QApplication.instance() or QApplication([])


def _table():
    ct = CompanyTable()
    ct.set_selected_run_mode(True)  # Phase 2+ idle 진입(버튼 표시 상태)
    return ct


def test_running_state_keeps_stop_button_visible_and_enabled():
    """set_running(True) → 정지 버튼(full_run_btn) 보이고 활성화, 텍스트 '정지'."""
    ct = _table()
    ct.set_running(True)
    assert ct._is_running is True
    assert ct.full_run_btn.isEnabled() is True          # ★ 핵심: 클릭 가능
    assert ct.full_run_btn.isHidden() is False          # ★ 핵심: 숨겨지지 않음
    assert ct.full_run_btn.text() == "정지"
    assert ct.full_run_btn.styleSheet() == BTN_RED
    # 관리 버튼 잠금, 선택건실행/힌트 숨김
    assert ct.refresh_btn.isEnabled() is False
    assert ct.delete_all_btn.isEnabled() is False
    assert ct.selected_run_btn.isHidden() is True
    assert ct.selection_hint.isHidden() is True


def test_idle_restore_equivalent_to_old_three_calls():
    """set_running(False) → 기존 3-호출 복원과 동등한 idle 상태."""
    ct = _table()
    ct.set_running(True)
    ct.set_running(False)
    assert ct._is_running is False
    assert ct.full_run_btn.text() == "전체실행"
    assert ct.full_run_btn.styleSheet() == BTN_GREEN
    assert ct.full_run_btn.isEnabled() is True
    assert ct.full_run_btn.isHidden() is False
    assert ct.refresh_btn.isEnabled() is True
    assert ct.delete_all_btn.isEnabled() is True
    assert ct.selected_run_btn.isHidden() is False
    assert ct.selected_run_btn.isEnabled() is False     # 선택 전까지 비활성
    assert ct._selected_clients == []
    assert ct.selection_hint.isHidden() is False
    assert "수임처를 선택하세요" in ct.selection_hint.text()


def test_stop_click_emits_stop_requested_while_running():
    """실행 중 정지 버튼 클릭 → stop_requested 시그널 방출(사용자 체감 동작)."""
    ct = _table()
    received = []
    ct.stop_requested.connect(lambda: received.append(True))
    ct.set_running(True)
    ct.full_run_btn.click()
    app.processEvents()
    assert received == [True]


def test_idle_click_does_not_emit_stop():
    """대기 중 클릭은 full_run_requested 경로 — stop_requested 미방출."""
    ct = _table()
    stops = []
    ct.stop_requested.connect(lambda: stops.append(True))
    # _is_running == False 상태에서 클릭 → _on_full_run_clicked 가 full_run_requested emit
    ct.full_run_btn.click()
    app.processEvents()
    assert stops == []


def test_running_forces_visible_regardless_of_incoming_state():
    """Phase 1(버튼 숨김) 상태에서도 set_running(True) 는 정지 버튼을 강제 표시."""
    ct = CompanyTable()
    ct.set_client_mode(True)            # full_run_btn 숨김/비활성 상태
    assert ct.full_run_btn.isHidden() is True
    ct.set_running(True)
    assert ct.full_run_btn.isHidden() is False
    assert ct.full_run_btn.isEnabled() is True


if __name__ == "__main__":
    for fn in (test_running_state_keeps_stop_button_visible_and_enabled,
               test_idle_restore_equivalent_to_old_three_calls,
               test_stop_click_emits_stop_requested_while_running,
               test_idle_click_does_not_emit_stop,
               test_running_forces_visible_regardless_of_incoming_state):
        fn()
        print(f"PASS: {fn.__name__}")
    print("\n모든 set_running 테스트 통과")
