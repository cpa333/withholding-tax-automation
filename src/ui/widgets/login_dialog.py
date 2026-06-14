"""로그인 다이얼로그 — 이메일/비밀번호 인증.

settings_dialog.py (VerificationDialog) 패턴을 따르며,
AuthWorker로 백그라운드 로그인을 수행하여 UI 블로킹을 방지한다.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QMessageBox,
)
from PySide6.QtCore import Qt

from src.ui.styles import BTN_GREEN
from src.ui.workers.auth_worker import AuthWorker


class LoginDialog(QDialog):
    """Supabase 이메일/비밀번호 로그인 다이얼로그.

    성공(accepted) 시 auth_session.json이 이미 저장되어 있다.
    실패 또는 종료 시 rejected → 호출자에서 sys.exit() 처리.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("원천징수 자동화 로그인")
        self.setMinimumWidth(420)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self._worker = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(32, 28, 32, 24)

        # 앱 이름
        title = QLabel("원천징수 자동화")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #1a1a1a;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("로그인이 필요합니다.")
        subtitle.setStyleSheet("font-size: 13px; color: #666;")
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle)

        # 계정 안내 — 계정이 없는 비전공자가 막히지 않도록 안내
        help_label = QLabel(
            "계정이 없으신가요? 계정 발급은 담당자에게 문의해 주세요."
        )
        help_label.setStyleSheet("font-size: 11px; color: #999;")
        help_label.setAlignment(Qt.AlignCenter)
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        layout.addSpacing(16)

        # 이메일
        email_label = QLabel("이메일")
        email_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(email_label)

        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("이메일을 입력하세요")
        self.email_input.setMinimumHeight(32)
        layout.addWidget(self.email_input)

        # 비밀번호
        pw_label = QLabel("비밀번호")
        pw_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(pw_label)

        self.pw_input = QLineEdit()
        self.pw_input.setPlaceholderText("비밀번호를 입력하세요")
        self.pw_input.setEchoMode(QLineEdit.Password)
        self.pw_input.setMinimumHeight(32)
        self.pw_input.returnPressed.connect(self._on_login)
        layout.addWidget(self.pw_input)

        layout.addSpacing(4)

        # 에러 메시지 (초기 숨김)
        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #f44336; font-size: 12px;")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)

        layout.addSpacing(8)

        # 버튼
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.quit_btn = QPushButton("종료")
        self.quit_btn.setMinimumWidth(80)
        self.quit_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.quit_btn)

        self.login_btn = QPushButton("로그인")
        self.login_btn.setMinimumWidth(120)
        self.login_btn.setMinimumHeight(36)
        self.login_btn.setStyleSheet(BTN_GREEN)
        self.login_btn.clicked.connect(self._on_login)
        btn_layout.addWidget(self.login_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # 이메일 입력에 포커스
        self.email_input.setFocus()

    def _on_login(self):
        """로그인 버튼 클릭 → AuthWorker로 백그라운드 로그인."""
        email = self.email_input.text().strip()
        password = self.pw_input.text()

        # 입력 검증
        if not email:
            self._show_error("이메일을 입력하세요.")
            self.email_input.setFocus()
            return
        if not password:
            self._show_error("비밀번호를 입력하세요.")
            self.pw_input.setFocus()
            return

        # UI 상태: 로딩
        self._set_loading(True)

        # 워커 시작
        self._worker = AuthWorker(self)
        self._worker.login_done.connect(self._on_login_done)
        self._worker.login_failed.connect(self._on_login_failed)
        self._worker.start_login(email, password)

    def _on_login_done(self, session: dict):
        """로그인 성공 → 다이얼로그 수락."""
        self._cleanup_worker()
        self.accept()

    def _on_login_failed(self, message: str):
        """로그인 실패 → 에러 표시."""
        self._cleanup_worker()
        self._set_loading(False)
        self._show_error(message)
        self.pw_input.selectAll()
        self.pw_input.setFocus()

    def _show_error(self, message: str):
        self.error_label.setText(message)
        self.error_label.show()

    def _set_loading(self, loading: bool):
        """로딩 상태 토글."""
        self.login_btn.setEnabled(not loading)
        self.email_input.setEnabled(not loading)
        self.pw_input.setEnabled(not loading)
        self.quit_btn.setEnabled(not loading)
        if loading:
            self.login_btn.setText("로그인 중...")
            self.error_label.hide()
        else:
            self.login_btn.setText("로그인")

    def _cleanup_worker(self):
        if self._worker:
            try:
                self._worker.login_done.disconnect(self._on_login_done)
            except (RuntimeError, TypeError):
                pass
            try:
                self._worker.login_failed.disconnect(self._on_login_failed)
            except (RuntimeError, TypeError):
                pass
            if self._worker.isRunning():
                self._worker.quit()
                self._worker.wait(2000)
            self._worker.deleteLater()
            self._worker = None

    def reject(self):
        """종료 버튼 또는 X 버튼 → 워커 정리 후 거부."""
        self._cleanup_worker()
        super().reject()
