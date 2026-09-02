"""
ui/tabs/results_tab.py
"""

from __future__ import annotations

import csv as csv_module
import os
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.processing.oliver_pharr import ResultadoIndentacion
from ui.widgets.matplotlib_canvas import MatplotlibWidget
from utils.logger import get_logger

log = get_logger()


class ResultsTab(QWidget):
    """Pestaña de resultados: tabla tensión-deformación, gráfico con
    curva de ajuste, tabla resumen y exportación a CSV."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._resultado: Optional[ResultadoIndentacion] = None
        self._csv_path_origen: str = ""

        self._build_ui()
        self._wire_signals()

    # ------------------------------------------------------------------
    # Construcción de la UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        upper = QHBoxLayout()
        upper.addWidget(self._build_table_group(), stretch=0)
        upper.addWidget(self._build_graph_group(), stretch=1)
        layout.addLayout(upper, stretch=1)

        self.guardar_btn = QPushButton("Guardar Resultados")
        self.guardar_btn.setEnabled(False)
        layout.addWidget(self.guardar_btn, alignment=Qt.AlignHCenter)

        layout.addWidget(self._build_summary_group())

    def _build_table_group(self) -> QGroupBox:
        box = QGroupBox("Tensión-Deformación plástica")
        vbox = QVBoxLayout(box)

        self.results_table = QTableWidget(0, 2)
        self.results_table.setHorizontalHeaderLabels(["Deformación", "Tensión"])
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.results_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.results_table.setMinimumWidth(260)
        vbox.addWidget(self.results_table)

        return box

    def _build_graph_group(self) -> QGroupBox:
        box = QGroupBox("GRÁFICO DE RESULTADOS")
        vbox = QVBoxLayout(box)

        self.plot_widget = MatplotlibWidget(nrows=1, ncols=1, figsize=(10, 6))
        self._reset_plot()
        vbox.addWidget(self.plot_widget, stretch=1)

        return box

    def _build_summary_group(self) -> QGroupBox:
        box = QGroupBox("DATOS GENERALES")
        vbox = QVBoxLayout(box)

        self.summary_table = QTableWidget(0, 6)
        self.summary_table.setHorizontalHeaderLabels(
            ["Fluencia [MPa]", "Error Fluencia [%]", "n [~]", "Error n [%]", "UTS [MPa]", "Error UTS [%]"]
        )
        self.summary_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.summary_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.summary_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.summary_table.setFixedHeight(90)
        vbox.addWidget(self.summary_table)

        return box

    # ------------------------------------------------------------------
    # Conexión de señales
    # ------------------------------------------------------------------
    def _wire_signals(self) -> None:
        self.guardar_btn.clicked.connect(self._guardar_resultados)

    # ------------------------------------------------------------------
    # Slot público: consumido por AnalysisTab.resultado_calculado
    # ------------------------------------------------------------------
    def mostrar_resultado(self, resultado: ResultadoIndentacion, csv_path: str = "") -> None:
        """Punto de entrada principal de la pestaña. Conectar así desde
        ``MainWindow``::

            self.analysis_tab.resultado_calculado.connect(self.results_tab.mostrar_resultado)
        """
        self._resultado = resultado
        self._csv_path_origen = csv_path

        deformacion = resultado.deformacion
        tension_mpa = resultado.tension / 1e6

        self._populate_results_table(deformacion, tension_mpa)
        self._update_plot(
            deformacion,
            tension_mpa,
            resultado.x_fit,
            resultado.y_fit / 1e6,
            xlabel="Deformación plástica [~]",
            ylabel="Tensión plástica [MPa]",
            titulo="Gráfico de Resultados",
        )
        self._update_summary(resultado)
        self.guardar_btn.setEnabled(True)

    # ------------------------------------------------------------------
    # Tabla tensión-deformación (réplica de update_results_table)
    # ------------------------------------------------------------------
    def _populate_results_table(self, deformacion, tension_mpa) -> None:
        self.results_table.setRowCount(0)
        self.results_table.setRowCount(len(deformacion))
        for row, (d, t) in enumerate(zip(deformacion, tension_mpa)):
            self.results_table.setItem(row, 0, QTableWidgetItem(f"{d:.5f}"))
            self.results_table.setItem(row, 1, QTableWidgetItem(f"{t:.2f}"))

    # ------------------------------------------------------------------
    # Gráfico (réplica de update_results_plot)
    # ------------------------------------------------------------------
    def _reset_plot(self) -> None:
        ax = self.plot_widget.ax()
        ax.clear()
        ax.set_title("Seleccione datos para visualizar el resultado")
        ax.set_xlabel("Eje X")
        ax.set_ylabel("Eje Y")
        ax.grid(True)
        self.plot_widget.redraw()

    def _update_plot(self, x, y, x_fit, y_fit, xlabel="Eje X", ylabel="Eje Y", titulo="Gráfico de Resultados") -> None:
        ax = self.plot_widget.ax()
        ax.clear()
        ax.scatter(x, y, marker="o", color="black")
        ax.plot(x_fit, y_fit, color="blue")
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.set_title(titulo)
        ax.set_ylim(0, 1.1 * max(y))
        ax.set_xlim(0, 1.1 * max(x))
        ax.grid(True)
        self.plot_widget.redraw()

    # ------------------------------------------------------------------
    # Tabla resumen (réplica de update_summary_table)
    # ------------------------------------------------------------------
    def _update_summary(self, resultado: ResultadoIndentacion) -> None:
        self.summary_table.setRowCount(0)
        self.summary_table.setRowCount(1)

        fila = (
            round(float(resultado.sigma_y) / 1e6),
            round(float(resultado.err_sigma_y) / float(resultado.sigma_y) * 100, 2),
            round(float(resultado.n), 3),
            round(float(resultado.err_n) / float(resultado.n) * 100, 2),
            round(float(resultado.UTS1) / 1e6),
            round(float(resultado.err_UTS1) / float(resultado.UTS1) * 100, 2),
        )
        for col, valor in enumerate(fila):
            self.summary_table.setItem(0, col, QTableWidgetItem(str(valor)))

    # ------------------------------------------------------------------
    # Exportación a CSV (réplica de generar_nombre_resultados + guardar_resultados_csv)
    # ------------------------------------------------------------------
    def _generar_nombre_resultados(self, nombre_original: str) -> str:
        base = os.path.basename(nombre_original) if nombre_original else "resultados.csv"
        nombre_base = base[:-4] if base.lower().endswith(".csv") else base
        return f"resultados_{nombre_base}.csv"

    def _guardar_resultados(self) -> None:
        if self._resultado is None:
            QMessageBox.critical(self, "Error", "No hay resultados calculados para guardar.")
            return

        resultado = self._resultado
        nombre_sugerido = self._generar_nombre_resultados(self._csv_path_origen)

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Guardar resultados...", nombre_sugerido, "Archivos CSV (*.csv);;Todos los archivos (*.*)"
        )
        if not file_path:
            return

        try:
            with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv_module.writer(f)
                writer.writerow(["h_max", "L", "S", "Tensión", "Deformación"])
                # deformacion/tension incluyen el punto (0, sigma_y) insertado al
                # principio (ver core/processing/oliver_pharr.py), que no tiene un
                # ciclo h_max/L/S asociado; se omite acá para alinear las columnas
                # correctamente (el original las desalineaba al hacer zip con
                # arrays de distinto largo).
                for i in range(len(resultado.h_max)):
                    writer.writerow(
                        [
                            resultado.h_max[i],
                            resultado.L[i],
                            resultado.S[i],
                            resultado.tension[i + 1],
                            resultado.deformacion[i + 1],
                        ]
                    )
                writer.writerow([])
                writer.writerow(["Parámetro", "Valor", "Error"])
                writer.writerow(["Tensión de fluencia", resultado.sigma_y, resultado.err_sigma_y])
                writer.writerow(["n", resultado.n, resultado.err_n])
                writer.writerow(["UTS", resultado.UTS1, resultado.err_UTS1])
            QMessageBox.information(self, "Guardado", f"Resultados guardados en:\n{file_path}")
        except OSError as exc:
            log.error(f"Error al guardar resultados: {exc}")
            QMessageBox.critical(self, "Error", f"No se pudo guardar el archivo:\n{exc}")