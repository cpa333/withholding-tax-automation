"""수임처 세부 단계 진행 패널 — 선택된 Job의 체크포인트 스텝 시각화"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QProgressBar,
)
from PySide6.QtCore import Qt


_STEP_STATUS_STYLE = {
    "completed": ("✓", "#4caf50"),
    "running":   ("▶", "#2196f3"),
    "failed":    ("✗", "#f44336"),
    "pending":   ("○", "#9e9e9e"),
}


class StepRow(QWidget):
    """단일 스텝 행: 아이콘 + 이름 + 프로그레스바"""

    def __init__(self, step_name: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(8)

        self.icon = QLabel("○")
        self.icon.setFixedWidth(20)
        self.icon.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.icon)

        self.name_label = QLabel(step_name)
        self.name_label.setFixedWidth(180)
        layout.addWidget(self.name_label)

        self.progress = QProgressBar()
        self.progress.setFixedHeight(16)
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

    def set_status(self, status: str):
        icon_text, color = _STEP_STATUS_STYLE.get(status, ("?", "#000"))
        self.icon.setText(icon_text)
        self.icon.setStyleSheet(f"color: {color}; font-weight: bold;")

        if status == "running":
            self.progress.setValue(50)
            self.progress.setStyleSheet(
                "QProgressBar::chunk { background-color: #2196f3; }"
            )
        elif status == "completed":
            self.progress.setValue(100)
            self.progress.setStyleSheet(
                "QProgressBar::chunk { background-color: #4caf50; }"
            )
        elif status == "failed":
            self.progress.setValue(100)
            self.progress.setStyleSheet(
                "QProgressBar::chunk { background-color: #f44336; }"
            )
        else:
            self.progress.setValue(0)


class StepDetail(QWidget):
    """선택된 수임처의 세부 단계 진행 패널"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[StepRow] = []
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(0)

        self._title = QLabel("수임처를 선택하세요")
        self._title.setStyleSheet("font-weight: bold; padding: 4px;")
        self._layout.addWidget(self._title)

        from PySide6.QtWidgets import QSpacerItem, QSizePolicy
        self._layout.addSpacerItem(
            QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding)
        )

    def set_steps(self, client_name: str, steps: list[dict]):
        """스텝 목록 설정.

        steps: [{"step_name": "...", "status": "pending|running|completed|failed"}, ...]
        """
        # 기존 행 제거
        for row in self._rows:
            self._layout.removeWidget(row)
            row.deleteLater()
        self._rows.clear()

        # 제목 업데이트
        self._title.setText(f"[{client_name}] 세부 단계")

        # spacer 제거 후 재추가
        item = self._layout.itemAt(self._layout.count() - 1)
        if item and item.spacerItem():
            self._layout.removeItem(item)

        # 새 스텝 행 추가
        for step in steps:
            row = StepRow(step.get("step_name", ""))
            row.set_status(step.get("status", "pending"))
            self._layout.addWidget(row)
            self._rows.append(row)

        # spacer 재추가
        from PySide6.QtWidgets import QSpacerItem, QSizePolicy
        self._layout.addSpacerItem(
            QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding)
        )
