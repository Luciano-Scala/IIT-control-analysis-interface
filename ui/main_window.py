"""
ui/main_window.py
===================
Ventana principal. Traducción del ``ttk.Notebook`` con sus 5 pestañas
(líneas ~44-99 del original) a un ``QTabWidget`` dentro de un
``QMainWindow``.

Por ahora solo la pestaña de Adquisición está implementada
(``AcquisitionTab``); el resto queda como placeholders para las
próximas entregas (Análisis CSV, Resultados Finales, Pre-Informe de
Indentación, Pre-Informe de Dureza), tal como se acordó en el plan de
entrega progresiva.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QMainWindow, QTabWidget, QVBoxLayout, QWidget

import config
from ui.tabs.acquisition_tab import AcquisitionTab
from ui.tabs.analysis_tab import AnalysisTab


def _placeholder_tab(mensaje: str) -> QWidget:
    """Pestaña provisoria para las secciones aún no migradas."""
    widget = QWidget()
    layout = QVBoxLayout(widget)
    label = QLabel(mensaje)
    label.setStyleSheet("color: gray; font-size: 14px;")
    layout.addWidget(label)
    layout.addStretch(1)
    return widget


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(config.APP_TITLE)
        self.resize(1280, 900)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.acquisition_tab = AcquisitionTab()
        self.tabs.addTab(self.acquisition_tab, "Adquisición de Datos")

        self.analysis_tab = AnalysisTab()
        self.tabs.addTab(self.analysis_tab, "Análisis CSV")
        # ``results_tab`` (próxima entrega) se conectará acá:
        #   self.analysis_tab.resultado_calculado.connect(self.results_tab.mostrar_resultado)

        self.tabs.addTab(
            _placeholder_tab("Resultados Finales — próxima entrega (ui/tabs/results_tab.py)"),
            "Resultados Finales",
        )
        self.tabs.addTab(
            _placeholder_tab("Pre-Informe (Indentación) — próxima entrega (ui/tabs/report_tab.py)"),
            "Pre - Informe (Indentación)",
        )
        self.tabs.addTab(
            _placeholder_tab("Pre-Informe (Dureza) — próxima entrega (ui/tabs/hardness_tab.py)"),
            "Pre - Informe (Dureza)",
        )

    def closeEvent(self, event) -> None:
        """Asegura que el QThread de lectura serie se detenga antes de
        cerrar la aplicación (evita el warning/crash de Qt por hilos
        vivos al destruir la ventana)."""
        self.acquisition_tab.shutdown()
        self.analysis_tab.shutdown()
        super().closeEvent(event)