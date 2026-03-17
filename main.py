import sys
import os

from PyQt6.QtWidgets import QApplication

from gui.main_window import MainWindow
from gui.theme import global_stylesheet
from core.config import Config


def main():
    os.makedirs(Config.root_dir(), exist_ok=True)
    app = QApplication(sys.argv)
    app.setApplicationName("DevMaker")
    app.setStyle("Fusion")
    app.setStyleSheet(global_stylesheet())
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
