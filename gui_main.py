"""원천징수 자동화 GUI 런처"""

import sys
import os


class _NullWriter:
    """windowed 모드에서 sys.stdout/stderr가 None일 때 대체"""
    def write(self, *args, **kwargs): pass
    def flush(self): pass
    def fileno(self): return -1
    def detach(self):
        import io
        return io.BufferedWriter(io.BytesIO())
    encoding = 'utf-8'


# 모듈 로드 시점에 즉시 교체 — 다른 어떤 import보다 먼저 실행
if sys.stdout is None:
    sys.stdout = _NullWriter()
if sys.stderr is None:
    sys.stderr = _NullWriter()


def resource_path(relative_path):
    """PyInstaller 번들 환경에서 리소스 경로 반환"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


_MUTEX_HANDLE = None


def _create_single_instance_mutex():
    """installer.iss 의 AppMutex 와 일치하는 명명 뮤텍스 생성.

    Inno Setup이 업그레이드/제거 시 실행 중인 인스턴스를 감지해
    파일 잠금 충돌(반쪽 덮어쓰기)을 막을 수 있게 한다.
    핸들은 프로세스 종료 시 자동 해제되도록 일부러 닫지 않는다.
    """
    global _MUTEX_HANDLE
    if sys.platform != "win32":
        return
    try:
        import ctypes
        _MUTEX_HANDLE = ctypes.windll.kernel32.CreateMutexW(
            None, False, "WithholdingTaxAutomation_SingleInstance"
        )
    except Exception:
        pass


def main():
    # PyInstaller onefile/onedir 모두: exe 위치를 CWD로
    if getattr(sys, 'frozen', False):
        os.chdir(os.path.dirname(sys.executable))

    sys.path.insert(0, resource_path("."))

    _create_single_instance_mutex()

    from PySide6.QtWidgets import QApplication
    from src.ui.main_window import MainWindow
    from src.version import __version__
    from src.config import migrate_legacy_data

    # 구버전 데이터(설치 폴더 내) → %LOCALAPPDATA% 1회 이전 (DB 접근 전에)
    migrate_legacy_data()

    app = QApplication(sys.argv)
    app.setApplicationName("원천징수 자동화")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")

    # 스타일시트 로드
    qss_path = resource_path(os.path.join("src", "ui", "resources", "style.qss"))
    if os.path.exists(qss_path):
        with open(qss_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())

    # ── 인증 게이트 ────────────────────────────────────────────────────
    from PySide6.QtWidgets import QMessageBox, QDialog

    from src.utils.auth import is_beta_expired, validate_session, is_within_grace_period
    from src.ui.resources.auth_config import BETA_EXPIRES

    # 1) 베타 만료 확인
    if is_beta_expired():
        QMessageBox.critical(
            None, "사용 기간 만료",
            f"베타 사용 기간이 만료되었습니다.\n({BETA_EXPIRES})\n\n"
            "새 버전을 설치해 주세요.",
        )
        sys.exit(1)

    # 2) 세션 검증 → 유효하면 바로 MainWindow 진입
    session_ok = validate_session()

    if not session_ok and not is_within_grace_period():
        # 3) 유예 기간도 초과 → 로그인 다이얼로그
        from src.ui.widgets.login_dialog import LoginDialog
        login_dlg = LoginDialog()
        if login_dlg.exec() != QDialog.Accepted:
            sys.exit(0)

    # ── 메인 윈도우 ────────────────────────────────────────────────────
    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
