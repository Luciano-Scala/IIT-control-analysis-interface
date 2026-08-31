"""
main.py
========
Entrypoint de IITCAI. Reemplaza al ``if __name__ == '__main__': root =
tk.Tk(); app = DataLoggerApp(root); root.mainloop()`` del original.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow
from utils.logger import get_logger


def main() -> int:
    logger = get_logger()
    logger.info("=" * 60)
    logger.info("IITCAI iniciado")

    app = QApplication(sys.argv)
    window = MainWindow()
    window.showMaximized()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())