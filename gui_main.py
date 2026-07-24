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


def _apply_light_palette(app):
    """Windows 다크 모드에서 Fusion 기본 팔레트가 다크가 되어 QMessageBox/
    QDialog/QComboBox 팝업/QToolTip 등이 '검정 바탕 + 검정 글자'로 안 보이는
    것을 방지. 명시적 라이트 팔레트를 강제 적용한다 (style.qss 라이트 테마와 일치).
    메뉴바처럼 위젯별로 고치는 게 아니라 근본(palette)에서 해결."""
    from PySide6.QtGui import QPalette, QColor
    LIGHT_BG = QColor("#ffffff")
    LIGHT_BTN = QColor("#f5f5f5")
    DARK_TEXT = QColor("#1a1a1a")
    GRAY_TEXT = QColor("#999999")
    p = QPalette()
    p.setColor(QPalette.Window, LIGHT_BG)
    p.setColor(QPalette.WindowText, DARK_TEXT)
    p.setColor(QPalette.Base, LIGHT_BG)
    p.setColor(QPalette.AlternateBase, QColor("#fafafa"))
    p.setColor(QPalette.Text, DARK_TEXT)
    p.setColor(QPalette.Button, LIGHT_BTN)
    p.setColor(QPalette.ButtonText, DARK_TEXT)
    p.setColor(QPalette.ToolTipBase, QColor("#1e1e1e"))
    p.setColor(QPalette.ToolTipText, QColor("#ffffff"))
    p.setColor(QPalette.Highlight, QColor("#d0e4f7"))
    p.setColor(QPalette.HighlightedText, DARK_TEXT)
    p.setColor(QPalette.PlaceholderText, GRAY_TEXT)
    # 비활성(disabled) 텍스트도 다크 잔재가 없도록 회색 통일
    p.setColor(QPalette.Disabled, QPalette.WindowText, GRAY_TEXT)
    p.setColor(QPalette.Disabled, QPalette.Text, GRAY_TEXT)
    p.setColor(QPalette.Disabled, QPalette.ButtonText, GRAY_TEXT)
    app.setPalette(p)


def _dispatch_cli_subprocess() -> bool:
    """병렬 자동화 subprocess 디스패치 (--wtax-cli).

    빌드된 exe(frozen)에서는 `python -m <module>` 모듈 실행이 불가하므로,
    GUI 진입점이 `--wtax-cli <module>` 인자를 받아 해당 CLI 모듈을 대신 실행한다.
    일반 GUI 실행에는 영향 없음(플래그가 없으면 False 반환).
    각 subprocess 는 WTAX_CDP_PORT env 로 포트가 격리된다(parallel_cli_worker 설정).
    """
    argv = sys.argv[1:]
    if "--wtax-cli" not in argv:
        return False

    idx = argv.index("--wtax-cli")
    module = argv[idx + 1] if idx + 1 < len(argv) else ""
    rest = argv[:idx] + argv[idx + 2:]

    # GUI main() 과 동일 환경 보장 (CWD, sys.path) — CLI 가 config/DB/import 를 정상 해석.
    if getattr(sys, "frozen", False):
        os.chdir(os.path.dirname(sys.executable))
    sys.path.insert(0, resource_path("."))

    # ── stdout/stderr 을 utf-8 로 강제 (frozen 병렬 다운로드 교착 근본 차단) ──
    # frozen exe 는 PYTHONUTF8 을 무시해 파이프 stdout 이 한글 Windows 기본값(cp949)
    # 으로 열린다. dev 의 `python -m` 은 모듈을 __main__ 로 실행해 각 CLI 파일 하단의
    # utf-8 재설정 블록이 돌지만, 이 --wtax-cli 는 importlib 로 import 진입이라(__main__
    # 아님) 그 블록을 건너뛴다. 그러면 부모(parallel_cli_worker)의 utf-8 파이프 reader
    # 가 첫 한글 줄에서 UnicodeDecodeError 로 죽고 → 파이프 미배수 → 자식이 버퍼가 찬
    # 시점에 print 에서 블록 → 다운로드가 중간에 교착된다. 자식 진입점인 여기서 강제.
    import io
    for _stream_name in ("stdout", "stderr"):
        _stream = getattr(sys, _stream_name, None)
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, io.UnsupportedOperation):
            pass

    if not module:
        return False

    import argparse
    import asyncio
    import importlib

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--month", type=int, default=None)
    parser.add_argument("--firms", type=str, default=None)
    parser.add_argument("--mgmts", type=str, default=None,
                        help="콤마로 구분된 사업장관리번호 (--firms 와 같은 순서)")
    parser.add_argument("--save-site", type=str, default=None,
                        help="저장 최상위 폴더명 오버라이드 (병렬: NHIS/NPS 공통 폴더)")
    args = parser.parse_args(rest)

    try:
        mod = importlib.import_module(module)
        asyncio.run(mod.main(args))
    except Exception as e:
        print(f"[wtax-cli] FATAL: {e}", file=sys.stderr)
    return True


def main():
    # 병렬 자동화 subprocess 디스패치 (frozen exe --wtax-cli) — GUI 없이 CLI 실행 후 종료.
    # 빌드된 exe 에서는 python -m 이 불가해 parallel_cli_worker 가 이 진입점을 경유해 CLI 모듈을 실행.
    if _dispatch_cli_subprocess():
        return

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
    _apply_light_palette(app)  # 다크 모드 대비 — 라이트 팔레트 강제

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
