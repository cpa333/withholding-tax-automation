"""원천징수 자동화 GUI 런처"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from src.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("원천징수 자동화")
    app.setStyle("Fusion")

    # 스타일시트 로드
    qss_path = os.path.join(
        os.path.dirname(__file__), "src", "ui", "resources", "style.qss"
    )
    if os.path.exists(qss_path):
        with open(qss_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
