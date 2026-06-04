"""Programa main del SCADA GIIROB PR2-A1.

Uso:
    python main.py

Requiere PyQt5 y paho-mqtt (ver requirements.txt).
"""

from __future__ import annotations

import sys

from PyQt5.QtWidgets import QApplication

from main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("SCADA GIIROB")
    window = MainWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
