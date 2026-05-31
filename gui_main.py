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


def main():
    # PyInstaller onefile/onedir 모두: exe 위치를 CWD로
    if getattr(sys, 'frozen', False):
        os.chdir(os.path.dirname(sys.executable))

    sys.path.insert(0, resource_path("."))

    from PySide6.QtWidgets import QApplication
    from src.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("원천징수 자동화")
    app.setStyle("Fusion")

    # 스타일시트 로드
    qss_path = resource_path(os.path.join("src", "ui", "resources", "style.qss"))
    if os.path.exists(qss_path):
        with open(qss_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
