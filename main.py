"""Start refboard. Run with:  .venv/bin/python main.py"""

import sys

from PySide6.QtWidgets import QApplication, QMainWindow

from canvas import Canvas


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("refboard")

    window = QMainWindow()
    window.setWindowTitle("refboard")
    window.setCentralWidget(Canvas())
    window.resize(1618, 1000)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
