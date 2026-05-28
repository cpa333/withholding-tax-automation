"""페이즈 간 검증 다이얼로그 — 전 단계 완료 여부 확인"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QCheckBox,
)


class VerificationDialog(QDialog):
    """페이즈 전환 시 검증 다이얼로그"""

    def __init__(
        self, phase_id: int, phase_name: str,
        failed_count: int = 0, total_count: int = 0,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("단계 전환 확인")
        self.setMinimumWidth(400)
        self._skip_failed = False

        layout = QVBoxLayout(self)

        # 안내 메시지
        if failed_count > 0:
            msg = (
                f"Phase {phase_id - 1} 완료 중 {failed_count}건 실패가 있습니다.\n"
                f"Phase {phase_id} ({phase_name})를 시작하시겠습니까?"
            )
        else:
            msg = (
                f"Phase {phase_id - 1}이 완료되었습니다.\n"
                f"Phase {phase_id} ({phase_name})를 시작하시겠습니까?"
            )

        layout.addWidget(QLabel(msg))

        # 실패 건 건너뛰기 옵션
        if failed_count > 0:
            self.skip_check = QCheckBox(
                f"실패한 {failed_count}건을 건너뛰고 계속"
            )
            layout.addWidget(self.skip_check)

        # 버튼
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("취소")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        ok_btn = QPushButton("시작")
        ok_btn.setStyleSheet(
            "QPushButton { background-color: #4caf50; color: white; "
            "padding: 5px 20px; border-radius: 3px; }"
        )
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)

        layout.addLayout(btn_layout)

    @property
    def skip_failed(self) -> bool:
        return hasattr(self, "skip_check") and self.skip_check.isChecked()
