"""
ui/tabs/report_tab.py
"""

from __future__ import annotations

import io
from typing import List, Optional, Tuple

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QLabel,
    QLineEdit,
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

_RESUMEN_COLUMNAS = [
    "Indentación", "σᵧ [MPa]", "Δσᵧ [MPa]", "Promedio\nσᵧ [MPa]", "Desv σᵧ [%]",
    "σᵤ [MPa]", "Δσᵤ [MPa]", "Promedio\nσᵤ [MPa]", "Desv σᵤ [%]",
]
_SAVGOL_POLYORDER = 3
_SAVGOL_MAX_WINDOW = 301
_FIRST_ROW_COLOR = QColor("#0371CC")


class ReportTab(QWidget):
    """Pestaña de preinforme: datos de cliente, curvas de indentación
    superpuestas y tabla resumen con promedios/desviaciones en vivo."""

    #: Emitida al pedir la exportación a Excel. ``MainWindow`` la
    #: conecta, junta los datos de esta pestaña y de ``HardnessTab``, y
    #: llama a ``utils/excel_exporter.py``.
    exportar_solicitado = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._indent_counter = 0
        self._max_x = 0.0
        self._max_y = 0.0

        self._build_ui()
        self._wire_signals()

    # ------------------------------------------------------------------
    # Construcción de la UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        layout.addWidget(self._build_client_group())
        layout.addWidget(self._build_graph_group(), stretch=1)
        layout.addWidget(self._build_summary_group())

        self.export_excel_btn = QPushButton("Exportar Informe a Excel")
        self.limpiar_btn = QPushButton("Limpiar Informe")
        layout.addWidget(self.export_excel_btn, alignment=Qt.AlignHCenter)
        layout.addWidget(self.limpiar_btn, alignment=Qt.AlignHCenter)

    def _build_client_group(self) -> QGroupBox:
        box = QGroupBox("DATOS DEL CLIENTE")
        grid = QGridLayout(box)

        grid.addWidget(QLabel("Fecha:"), 0, 0)
        self.fecha_label = QLabel("")
        grid.addWidget(self.fecha_label, 0, 1)

        grid.addWidget(QLabel("Cliente:"), 0, 2)
        self.cliente_label = QLabel("")
        grid.addWidget(self.cliente_label, 0, 3)

        grid.addWidget(QLabel("Solicitud N°:"), 1, 0)
        self.solicitud_label = QLabel("")
        grid.addWidget(self.solicitud_label, 1, 1)

        grid.addWidget(QLabel("Identificación de Muestra:"), 1, 2)
        self.muestra_label = QLabel("")
        grid.addWidget(self.muestra_label, 1, 3)

        grid.addWidget(QLabel("Lugar:"), 2, 0)
        self.lugar_input = QLineEdit()
        grid.addWidget(self.lugar_input, 2, 1)

        grid.addWidget(QLabel("Comentarios:"), 2, 2)
        self.comentario_input = QLineEdit()
        grid.addWidget(self.comentario_input, 2, 3)

        grid.addWidget(QLabel("Temperatura de muestra:"), 3, 0)
        self.temperatura_input = QLineEdit()
        grid.addWidget(self.temperatura_input, 3, 1)

        grid.addWidget(QLabel("Chequeo vibraciones:"), 3, 2)
        self.vibraciones_input = QLineEdit()
        grid.addWidget(self.vibraciones_input, 3, 3)

        grid.addWidget(QLabel("Inclinación:"), 4, 0)
        self.inclinacion_input = QLineEdit()
        grid.addWidget(self.inclinacion_input, 4, 1)

        grid.addWidget(QLabel("Coordenadas de la medición:"), 4, 2)
        self.coordenadas_input = QLineEdit()
        grid.addWidget(self.coordenadas_input, 4, 3)

        grid.setColumnStretch(3, 1)
        return box

    def _build_graph_group(self) -> QGroupBox:
        box = QGroupBox("GRÁFICOS DE INDENTACIÓN")
        layout = QVBoxLayout(box)

        self.plot_widget = MatplotlibWidget(nrows=1, ncols=1, figsize=(10, 6))
        self._reset_plot()
        layout.addWidget(self.plot_widget, stretch=1)

        return box

    def _build_summary_group(self) -> QGroupBox:
        box = QGroupBox("RESULTADOS FINALES")
        layout = QVBoxLayout(box)

        self.resumen_table = QTableWidget(0, len(_RESUMEN_COLUMNAS))
        self.resumen_table.setHorizontalHeaderLabels(_RESUMEN_COLUMNAS)
        self.resumen_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.resumen_table.setSelectionMode(QAbstractItemView.SingleSelection)
        # Editable con doble clic (comportamiento nativo de QTableWidget),
        # reemplaza al hack de tk.Entry superpuesto de on_double_click.
        layout.addWidget(self.resumen_table)

        return box

    # ------------------------------------------------------------------
    # Conexión de señales
    # ------------------------------------------------------------------
    def _wire_signals(self) -> None:
        self.export_excel_btn.clicked.connect(self.exportar_solicitado.emit)
        self.limpiar_btn.clicked.connect(self._limpiar_informe)

    # ------------------------------------------------------------------
    # Slots públicos (conectados desde MainWindow)
    # ------------------------------------------------------------------
    def set_client_info(self, client_info: dict) -> None:
        """Conectado a ``AcquisitionTab.client_data_changed``."""
        self.fecha_label.setText(client_info.get("fecha", ""))
        self.cliente_label.setText(client_info.get("cliente", ""))
        self.solicitud_label.setText(client_info.get("solicitud", ""))
        self.muestra_label.setText(client_info.get("muestra", ""))

    def agregar_curva(self, lvdt_mm, carga) -> None:
        """Conectado a ``AnalysisTab.curva_informe_lista``. Réplica de
        ``update_informe_plot``: suaviza con Savitzky-Golay y superpone
        una curva más por indentación, con leyenda numerada."""
        try:
            from scipy.signal import savgol_filter

            x = np.asarray(lvdt_mm, dtype=float)
            y = np.asarray(carga, dtype=float)

            window = min(_SAVGOL_MAX_WINDOW, len(x) if len(x) % 2 == 1 else len(x) - 1)
            if window > _SAVGOL_POLYORDER:
                x = savgol_filter(x, window_length=window, polyorder=_SAVGOL_POLYORDER)
        except Exception as exc:  # noqa: BLE001 - si falla el suavizado, graficamos sin él
            log.warning(f"No se pudo suavizar la curva del preinforme: {exc}")
            x = np.asarray(lvdt_mm, dtype=float)
            y = np.asarray(carga, dtype=float)

        ax = self.plot_widget.ax()

        if self._indent_counter == 0:
            ax.cla()
            ax.set_xlabel("Desplazamiento (mm)")
            ax.set_ylabel("Carga (N)")
            ax.set_title("Curva Carga vs. Desplazamiento")
            ax.grid(True)
            self._max_x = 0.0
            self._max_y = 0.0

        self._indent_counter += 1

        ax.plot(x, y, linestyle="-", label=f"N° {self._indent_counter}")
        ax.legend(title="Indentaciones")

        self._max_x = max(self._max_x, float(np.max(x)) * 1.05)
        self._max_y = max(self._max_y, float(np.max(y)) * 1.05)
        ax.set_xlim(0, self._max_x)
        ax.set_ylim(0, self._max_y)

        self.plot_widget.redraw()

    def agregar_resultado(self, resultado: ResultadoIndentacion) -> None:
        """Conectado a ``AnalysisTab.resultado_informe_listo``. Réplica
        de ``update_informe_table``: agrega una fila con sigma_y/UTS y
        recalcula promedios/desviaciones de toda la tabla."""
        self._agregar_fila_resumen(
            resultado.sigma_y, resultado.err_sigma_y, resultado.UTS1, resultado.err_UTS1
        )

    # ------------------------------------------------------------------
    # Tabla resumen (réplica de update_informe_table)
    # ------------------------------------------------------------------
    def _agregar_fila_resumen(self, sigma_y, err_sigma_y, UTS1, err_UTS1) -> None:
        sigma_y_val = float(sigma_y) / 1e6
        err_sigma_y_val = round(float(err_sigma_y) / 1e6, 0) if sigma_y != 0 else 0
        UTS_val = float(UTS1) / 1e6
        err_UTS_val = round(float(err_UTS1) / 1e6, 0) if UTS1 != 0 else 0

        valores_sigma: List[float] = []
        valores_uts: List[float] = []
        for row in range(self.resumen_table.rowCount()):
            item_sigma = self.resumen_table.item(row, 1)
            item_uts = self.resumen_table.item(row, 5)
            try:
                if item_sigma is not None and item_sigma.text() != "":
                    valores_sigma.append(float(item_sigma.text()))
                if item_uts is not None and item_uts.text() != "":
                    valores_uts.append(float(item_uts.text()))
            except ValueError:
                pass

        valores_sigma.append(sigma_y_val)
        valores_uts.append(UTS_val)

        promedio_sigma = sum(valores_sigma) / len(valores_sigma)
        promedio_uts = sum(valores_uts) / len(valores_uts)

        desv_sigma_pct = abs((sigma_y_val - promedio_sigma) / promedio_sigma) * 100 if promedio_sigma != 0 else 0
        desv_uts_pct = abs((UTS_val - promedio_uts) / promedio_uts) * 100 if promedio_uts != 0 else 0

        fila = [
            f"N° {self._indent_counter}",
            str(int(sigma_y_val)),
            str(int(err_sigma_y_val)),
            "",
            str(round(desv_sigma_pct, 2)),
            str(int(UTS_val)),
            str(int(err_UTS_val)),
            "",
            str(round(desv_uts_pct, 2)),
        ]

        row_idx = self.resumen_table.rowCount()
        self.resumen_table.insertRow(row_idx)
        for col, valor in enumerate(fila):
            self.resumen_table.setItem(row_idx, col, QTableWidgetItem(valor))

        self._resaltar_primera_fila()

        item_prom_sigma = QTableWidgetItem(str(round(promedio_sigma, 1)))
        item_prom_uts = QTableWidgetItem(str(round(promedio_uts, 1)))
        self.resumen_table.setItem(0, 3, item_prom_sigma)
        self.resumen_table.setItem(0, 7, item_prom_uts)
        self._resaltar_primera_fila()

        for row in range(self.resumen_table.rowCount()):
            sigma_i = float(self.resumen_table.item(row, 1).text())
            desv_i = ((sigma_i - promedio_sigma) / promedio_sigma) * 100 if promedio_sigma != 0 else 0
            self.resumen_table.setItem(row, 4, QTableWidgetItem(str(round(desv_i, 2))))

            uts_i = float(self.resumen_table.item(row, 5).text())
            desv_uts_i = ((uts_i - promedio_uts) / promedio_uts) * 100 if promedio_uts != 0 else 0
            self.resumen_table.setItem(row, 8, QTableWidgetItem(str(round(desv_uts_i, 2))))

        self._resaltar_primera_fila()

    def _resaltar_primera_fila(self) -> None:
        """Réplica del tag ``first_row`` (fondo azul, texto en negrita)
        que el original aplicaba a la fila de promedios."""
        if self.resumen_table.rowCount() == 0:
            return
        for col in range(self.resumen_table.columnCount()):
            item = self.resumen_table.item(0, col)
            if item is None:
                item = QTableWidgetItem("")
                self.resumen_table.setItem(0, col, item)
            item.setBackground(_FIRST_ROW_COLOR)
            item.setForeground(QColor("white"))
            font = item.font()
            font.setBold(True)
            item.setFont(font)

    # ------------------------------------------------------------------
    # Limpieza / exportación
    # ------------------------------------------------------------------
    def _reset_plot(self) -> None:
        ax = self.plot_widget.ax()
        ax.clear()
        ax.set_xlabel("Desplazamiento (mm)")
        ax.set_ylabel("Carga (N)")
        ax.set_title("Curva Carga vs. Desplazamiento")
        ax.grid(True, linestyle=":")
        self.plot_widget.redraw()

    def _limpiar_informe(self) -> None:
        """Réplica de ``reset_informe``."""
        for label in (self.cliente_label, self.fecha_label, self.muestra_label, self.solicitud_label):
            label.setText("")
        for entry in (
            self.lugar_input, self.comentario_input, self.temperatura_input,
            self.vibraciones_input, self.inclinacion_input, self.coordenadas_input,
        ):
            entry.clear()

        self.resumen_table.setRowCount(0)
        self._reset_plot()

        self._indent_counter = 0
        self._max_x = 0.0
        self._max_y = 0.0

    # ------------------------------------------------------------------
    # Datos para la exportación (consumidos por MainWindow, ver
    # utils/excel_exporter.py — esta pestaña NO arma el archivo, solo
    # expone sus propios datos ya extraídos de los widgets Qt)
    # ------------------------------------------------------------------
    def obtener_datos_generales(self) -> dict:
        return {
            "cliente": self.cliente_label.text(),
            "solicitud": self.solicitud_label.text(),
            "fecha": self.fecha_label.text(),
            "muestra": self.muestra_label.text(),
            "lugar": self.lugar_input.text(),
            "coordenadas": self.coordenadas_input.text(),
            "temperatura": self.temperatura_input.text(),
            "comentario": self.comentario_input.text(),
        }

    def obtener_resultados_para_exportacion(self) -> List[Tuple[float, float, float, float]]:
        """Devuelve (sigma_y_mpa, err_sigma_y_mpa, uts_mpa, err_uts_mpa)
        por fila de ``resumen_table``, en el mismo orden en que se
        agregaron. Relee los valores desde las celdas (mismo criterio
        que ``_agregar_fila_resumen`` usa para recalcular promedios),
        no hace falta guardar una lista aparte."""
        filas: List[Tuple[float, float, float, float]] = []
        for row in range(self.resumen_table.rowCount()):
            try:
                sigma_y = float(self.resumen_table.item(row, 1).text())
                err_sigma_y = float(self.resumen_table.item(row, 2).text())
                uts = float(self.resumen_table.item(row, 5).text())
                err_uts = float(self.resumen_table.item(row, 6).text())
            except (AttributeError, ValueError):
                continue
            filas.append((sigma_y, err_sigma_y, uts, err_uts))
        return filas

    def render_grafico_png(self) -> Optional[bytes]:
        """Renderiza el gráfico superpuesto actual a PNG, para insertar
        en el Excel exportado. ``None`` si todavía no hay curvas."""
        if self._indent_counter == 0:
            return None
        buf = io.BytesIO()
        self.plot_widget.figure.savefig(buf, format="png", dpi=100)
        return buf.getvalue()