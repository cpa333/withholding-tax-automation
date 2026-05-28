"""원천징수 자동화 GUI 런처"""

import sys
import os


def resource_path(relative_path):
    """PyInstaller 번들 환경에서 리소스 경로 반환"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


def main():
    # PyInstaller exe에서도 프로젝트 루트를 CWD로 유지
    if hasattr(sys, '_MEIPASS'):
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
