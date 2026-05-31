"""페이즈 사이드바 — 7개 페이즈 버튼 + 상태 표시"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QLabel,
)
from PySide6.QtCore import Signal, Qt


# 상태별 색상
_STATUS_COLORS = {
    "pending":  ("#9e9e9e", "#f5f5f5"),   # 회색
    "running":  ("#2196f3", "#e3f2fd"),   # 파랑
    "completed":("#4caf50", "#e8f5e9"),   # 초록
    "failed":   ("#f44336", "#ffebee"),   # 빨강
    "paused":   ("#ff9800", "#fff3e0"),   # 주황
}


class PhaseButton(QWidget):
    """단일 페이즈 버튼 + 진행 상태 표시"""

    clicked = Signal(int)  # phase_id

    def __init__(self, phase_id: int, display_name: str, parent=None, *, enabled: bool = True):
        super().__init__(parent)
        self.phase_id = phase_id
        self._status = "pending"
        self._selected = False
        self._progress = (0, 0)
        self._enabled = enabled

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)

        self.btn = QPushButton(f"{phase_id}. {display_name}")
        self.btn.setFlat(True)

        if enabled:
            self.btn.setStyleSheet(
                "QPushButton { text-align: left; padding: 6px; font-size: 13px; "
                "color: #1a1a1a; background-color: transparent; border: none; }"
            )
            self.btn.clicked.connect(lambda: self.clicked.emit(self.phase_id))
        else:
            self.btn.setEnabled(False)
            self.btn.setStyleSheet(
                "QPushButton { text-align: left; padding: 6px; font-size: 13px; "
                "color: #b0b0b0; background-color: #e8e8e8; border: none; border-radius: 3px; } "
                "QPushButton:disabled { color: #b0b0b0; background-color: #e8e8e8; }"
            )

        layout.addWidget(self.btn)

        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("color: #666; font-size: 11px; padding-left: 8px;")
        layout.addWidget(self.progress_label)

        self._update_style()

    def set_selected(self, selected: bool):
        self._selected = selected
        self._update_style()

    def set_status(self, status: str, completed: int = 0, total: int = 0):
        self._status = status
        self._progress = (completed, total)

        if total > 0:
            self.progress_label.setText(f"  ({completed}/{total})")
        else:
            self.progress_label.setText("")

        self._update_style()

    def _update_style(self):
        if not self._enabled:
            self.setStyleSheet(
                "PhaseButton { background-color: #ececec; "
                "border-left: 4px solid #ccc; margin: 1px 4px; border-radius: 3px; }"
            )
            return

        fg, bg = _STATUS_COLORS.get(self._status, _STATUS_COLORS["pending"])
        if self._selected:
            bg = "#bbdefb"
            border_fg = "#0d47a1"
            btn_bg = "#bbdefb"
            btn_font = "font-weight: bold;"
        else:
            border_fg = fg
            btn_bg = "transparent"
            btn_font = ""
        self.setStyleSheet(
            f"PhaseButton {{ background-color: {bg}; "
            f"border-left: 4px solid {border_fg}; margin: 1px 4px; border-radius: 3px; }}"
        )
        self.btn.setStyleSheet(
            f"QPushButton {{ text-align: left; padding: 6px; font-size: 13px; "
            f"color: #1a1a1a; background-color: {btn_bg}; border: none; {btn_font} }}"
        )

    @property
    def status(self):
        return self._status


class PhaseSidebar(QWidget):
    """페이즈 선택 사이드바"""

    phase_selected = Signal(int)  # phase_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._buttons: dict[int, PhaseButton] = {}
        self._selected_phase: int = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(0)

        title = QLabel("  자동화 단계")
        title.setStyleSheet("font-weight: bold; font-size: 14px; padding: 8px;")
        layout.addWidget(title)

        # 구분선
        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet("background-color: #ddd;")
        layout.addWidget(line)

    def set_phases(self, phases: list[dict]):
        """페이즈 목록 설정. phases: [{"phase_id": 1, "display_name": "..."}, ...]"""
        # 기존 버튼 제거
        for btn in self._buttons.values():
            btn.setParent(None)
            btn.deleteLater()
        self._buttons.clear()

        for phase in phases:
            btn = PhaseButton(phase["phase_id"], phase["display_name"],
                              enabled=phase.get("enabled", True))
            btn.clicked.connect(self._on_phase_clicked)
            self.layout().addWidget(btn)
            self._buttons[phase["phase_id"]] = btn

        # 빈 공간
        from PySide6.QtWidgets import QSpacerItem, QSizePolicy
        self.layout().addSpacerItem(
            QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding)
        )

        # 활성화된 첫 번째 페이즈 자동 선택
        first_enabled = next(
            (p["phase_id"] for p in phases if p.get("enabled", True)),
            None,
        )
        if first_enabled is not None:
            self._selected_phase = first_enabled
            self._buttons[first_enabled].set_selected(True)

    def update_phase_status(self, phase_id: int, status: str,
                            completed: int = 0, total: int = 0):
        btn = self._buttons.get(phase_id)
        if btn:
            btn.set_status(status, completed, total)

    def _on_phase_clicked(self, phase_id: int):
        # 이전 선택 해제
        if self._selected_phase in self._buttons:
            self._buttons[self._selected_phase].set_selected(False)
        # 새 선택 표시
        self._selected_phase = phase_id
        if phase_id in self._buttons:
            self._buttons[phase_id].set_selected(True)
        self.phase_selected.emit(phase_id)
