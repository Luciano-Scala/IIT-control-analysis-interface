"""
ui/tabs/hardness_tab.py
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from utils.logger import get_logger

log = get_logger()

_RESUMEN_COLUMNAS_DUR = [
    "Nro de impronta", "Carga aplicada [N]", "Diámetro [mm]", "Dureza", "Promedio", "Desv [%]",
]
_IMAGE_FILTER = "Archivos de imagen (*.png *.jpg *.jpeg *.bmp *.gif *.tiff);;Todos los archivos (*.*)"


class HardnessTab(QWidget):
    """Pestaña de preinforme de dureza: datos de cliente, foto de la
    impronta y tabla resumen de mediciones Brinell."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._contador_improntas = 0
        self._ruta_imagen_actual = ""

        self._build_ui()
        self._wire_signals()

    # ------------------------------------------------------------------
    # Construcción de la UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        layout.addWidget(self._build_client_group())
        layout.addWidget(self._build_image_group(), stretch=1)
        layout.addWidget(self._build_summary_group())

        self.info_export_label = QLabel(
            "Los resultados de dureza se incluyen automáticamente al exportar el "
            "Pre-Informe de Indentación a Excel (columna \"Dureza Portátil\")."
        )
        self.info_export_label.setStyleSheet("color: gray; font-style: italic;")
        self.info_export_label.setAlignment(Qt.AlignHCenter)
        self.info_export_label.setWordWrap(True)
        layout.addWidget(self.info_export_label)

        self.limpiar_btn = QPushButton("Limpiar Informe")
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

    def _build_image_group(self) -> QGroupBox:
        box = QGroupBox("IMPRONTAS")
        layout = QVBoxLayout(box)

        controles = QHBoxLayout()
        self.seleccionar_imagen_btn = QPushButton("Seleccionar imagen")
        self.limpiar_imagen_btn = QPushButton("Limpiar")
        controles.addWidget(self.seleccionar_imagen_btn)
        controles.addWidget(self.limpiar_imagen_btn)
        controles.addStretch(1)
        layout.addLayout(controles)

        self.imagen_label = QLabel("SIN IMAGEN")
        self.imagen_label.setAlignment(Qt.AlignCenter)
        self.imagen_label.setStyleSheet("color: gray; border: 1px solid #999;")
        self.imagen_label.setMinimumHeight(300)
        self.imagen_label.setScaledContents(False)
        layout.addWidget(self.imagen_label, stretch=1)

        return box

    def _build_summary_group(self) -> QGroupBox:
        box = QGroupBox("RESULTADOS FINALES")
        layout = QVBoxLayout(box)

        self.resumen_table = QTableWidget(0, len(_RESUMEN_COLUMNAS_DUR))
        self.resumen_table.setHorizontalHeaderLabels(_RESUMEN_COLUMNAS_DUR)
        self.resumen_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.resumen_table.setSelectionMode(QAbstractItemView.SingleSelection)
        layout.addWidget(self.resumen_table)

        return box

    # ------------------------------------------------------------------
    # Conexión de señales
    # ------------------------------------------------------------------
    def _wire_signals(self) -> None:
        self.seleccionar_imagen_btn.clicked.connect(self._seleccionar_imagen)
        self.limpiar_imagen_btn.clicked.connect(self._limpiar_imagen)
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

    def agregar_impronta(self, d1: float, d2: float, d3: float, carga_N: float, resultados) -> None:
        """Conectado a ``AnalysisTab.resultado_dureza_listo``. Réplica
        de ``agregar_a_informe_dureza``: agrega los tres diámetros como
        filas separadas y recalcula estadísticas globales."""
        self._contador_improntas += 1
        numero_impronta = self._contador_improntas

        diametros = [d1, d2, d3]
        durezas = np.asarray(resultados, dtype=float)
        promedio_local = float(np.mean(durezas))

        for i in range(3):
            desviacion_local = abs((durezas[i] - promedio_local) / promedio_local) * 100 if promedio_local != 0 else 0
            fila = [
                f"Impronta {numero_impronta}-{i + 1}",
                f"{carga_N:.1f} N",
                f"{diametros[i]:.3f} mm",
                f"{durezas[i]:.2f}",
                f"{promedio_local:.2f}",
                f"{desviacion_local:.2f}%",
            ]
            row_idx = self.resumen_table.rowCount()
            self.resumen_table.insertRow(row_idx)
            for col, valor in enumerate(fila):
                self.resumen_table.setItem(row_idx, col, QTableWidgetItem(valor))

        # El promedio/desviación locales de arriba quedan pisados enseguida
        # por las estadísticas globales (réplica exacta del original, que
        # hacía el mismo doble cálculo).
        self._actualizar_estadisticas_dureza()

    # ------------------------------------------------------------------
    # Estadísticas (réplica de actualizar_estadisticas_dureza)
    # ------------------------------------------------------------------
    def _actualizar_estadisticas_dureza(self) -> None:
        n_filas = self.resumen_table.rowCount()
        if n_filas == 0:
            return

        todas_durezas: List[float] = []
        for row in range(n_filas):
            item = self.resumen_table.item(row, 3)
            try:
                if item is not None:
                    todas_durezas.append(float(item.text()))
            except ValueError:
                continue

        if not todas_durezas:
            return

        promedio_general = float(np.mean(todas_durezas))

        for row in range(n_filas):
            item = self.resumen_table.item(row, 3)
            try:
                dureza_actual = float(item.text()) if item is not None else None
            except ValueError:
                dureza_actual = None
            if dureza_actual is None:
                continue

            desviacion = abs((dureza_actual - promedio_general) / promedio_general) * 100 if promedio_general != 0 else 0
            self.resumen_table.setItem(row, 4, QTableWidgetItem(f"{promedio_general:.2f}"))
            self.resumen_table.setItem(row, 5, QTableWidgetItem(f"{desviacion:.2f}%"))

    # ------------------------------------------------------------------
    # Imagen de la impronta
    # ------------------------------------------------------------------
    def _seleccionar_imagen(self) -> None:
        archivo, _ = QFileDialog.getOpenFileName(self, "Seleccionar imagen", "", _IMAGE_FILTER)
        if not archivo:
            return

        pixmap = QPixmap(archivo)
        if pixmap.isNull():
            QMessageBox.critical(self, "Error", "No se pudo cargar la imagen:\nFormato no soportado o archivo dañado.")
            return

        escalado = pixmap.scaled(
            self.imagen_label.width() or 600,
            self.imagen_label.height() or 400,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.imagen_label.setPixmap(escalado)
        self.imagen_label.setText("")
        self._ruta_imagen_actual = archivo

    def _limpiar_imagen(self) -> None:
        self.imagen_label.clear()
        self.imagen_label.setText("SIN IMAGEN")
        self._ruta_imagen_actual = ""

    # ------------------------------------------------------------------
    # Limpieza / exportación
    # ------------------------------------------------------------------
    def _limpiar_informe(self) -> None:
        """Réplica de ``reset_informe_dur`` (con el bug de
        ``limpiar_imagen_dur`` corregido, ver docstring del módulo)."""
        for label in (self.fecha_label, self.cliente_label, self.solicitud_label, self.muestra_label):
            label.setText("")
        for entry in (
            self.lugar_input, self.comentario_input, self.temperatura_input,
            self.vibraciones_input, self.inclinacion_input, self.coordenadas_input,
        ):
            entry.clear()

        self._limpiar_imagen()
        self.resumen_table.setRowCount(0)
        self._contador_improntas = 0

    # ------------------------------------------------------------------
    # Datos para la exportación (consumidos por MainWindow, ver
    # utils/excel_exporter.py — igual que en report_tab.py, esta
    # pestaña solo expone sus propios datos, no arma el archivo)
    # ------------------------------------------------------------------
    def obtener_improntas_para_exportacion(self) -> List[Tuple[float, float]]:
        """Devuelve (carga_N, dureza_promedio) por impronta — agrupa de
        a 3 filas consecutivas (cada impronta agrega exactamente 3,
        una por diámetro medido) y promedia su columna "Dureza"."""
        improntas: List[Tuple[float, float]] = []
        n_filas = self.resumen_table.rowCount()

        for inicio in range(0, n_filas, 3):
            durezas: List[float] = []
            carga_N: Optional[float] = None
            for row in range(inicio, min(inicio + 3, n_filas)):
                item_dureza = self.resumen_table.item(row, 3)
                item_carga = self.resumen_table.item(row, 1)
                try:
                    if item_dureza is not None:
                        durezas.append(float(item_dureza.text()))
                    if carga_N is None and item_carga is not None:
                        carga_N = float(item_carga.text().replace(" N", ""))
                except ValueError:
                    continue

            if durezas and carga_N is not None:
                improntas.append((carga_N, sum(durezas) / len(durezas)))

        return improntas