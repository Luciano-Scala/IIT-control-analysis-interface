"""
ui/dialogs/hardness_dialog.py
"""

from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)


class HardnessDialog(QDialog):
    """Pide los diámetros D1, D2, D3 (mm) de la impronta."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ingresar datos de impronta (mm)")
        self.setModal(True)

        layout = QVBoxLayout(self)
        grid = QGridLayout()

        grid.addWidget(QLabel("Diámetro 1:"), 0, 0)
        self.d1_edit = QLineEdit()
        grid.addWidget(self.d1_edit, 0, 1)

        grid.addWidget(QLabel("Diámetro 2:"), 1, 0)
        self.d2_edit = QLineEdit()
        grid.addWidget(self.d2_edit, 1, 1)

        grid.addWidget(QLabel("Diámetro 3:"), 2, 0)
        self.d3_edit = QLineEdit()
        grid.addWidget(self.d3_edit, 2, 1)

        layout.addLayout(grid)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._diametros: Optional[Tuple[float, float, float]] = None

    def _on_accept(self) -> None:
        try:
            if not self.d1_edit.text() or not self.d2_edit.text() or not self.d3_edit.text():
                raise ValueError("Todos los campos deben estar completos")

            d1 = float(self.d1_edit.text())
            d2 = float(self.d2_edit.text())
            d3 = float(self.d3_edit.text())

            if d1 <= 0 or d2 <= 0 or d3 <= 0:
                raise ValueError("Los valores deben ser positivos")

        except ValueError as exc:
            QMessageBox.critical(self, "Error de validación", str(exc))
            return

        self._diametros = (d1, d2, d3)
        self.accept()

    def get_diametros(self) -> Optional[Tuple[float, float, float]]:
        """Devuelve (d1, d2, d3) si el diálogo se aceptó, ``None`` si
        se canceló. Llamar después de ``exec()``."""
        return self._diametros