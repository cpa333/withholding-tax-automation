"""인증 전용 백그라운드 워커 (QThread).

update_worker.py와 동일한 패턴: src.utils.auth(stdlib)를 호출하고
결과를 Qt Signal로 방출한다. UI 스레드 블로킹을 방지하기 위해
로그인/검증을 별도 스레드에서 수행한다.
"""

from PySide6.QtCore import QThread, Signal

from src.utils import auth


class AuthWorker(QThread):
    """로그인/검증 두 모드를 갖는 단발성 워커.

    Signals:
        login_done(dict)       - 로그인 성공 시 세션 dict
        login_failed(str)      - 로그인 실패 시 에러 메시지
        validation_done(bool)  - 세션 검증 결과
    """

    login_done = Signal(dict)
    login_failed = Signal(str)
    validation_done = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = "validate"
        self._email = ""
        self._password = ""

    # ── 외부 호출 (메인 스레드) ────────────────────────────────────────

    def start_login(self, email: str, password: str):
        """로그인 시작."""
        self._mode = "login"
        self._email = email
        self._password = password
        self.start()

    def start_validate(self):
        """세션 검증 시작."""
        self._mode = "validate"
        self.start()

    # ── 스레드 본문 ────────────────────────────────────────────────────

    def run(self):
        try:
            if self._mode == "login":
                result = auth.login(self._email, self._password)
                if result and not result.get("_error"):
                    self.login_done.emit(result)
                else:
                    msg = (result or {}).get("message", "로그인에 실패했습니다.")
                    self.login_failed.emit(msg)
            else:
                ok = auth.validate_session()
                self.validation_done.emit(ok)
        except Exception as e:
            if self._mode == "login":
                self.login_failed.emit(str(e))
            else:
                self.validation_done.emit(False)
