"""
ui/tabs/analysis_tab.py
=========================
Pestaña "Análisis CSV". Traducción de ``setup_ui_analysis`` (líneas
~735-849) más los métodos backend asociados: ``load_csv_file``,
``process_csv_data``, ``borrar_csv``, ``update_analysis_plot``,
``update_analysis_table``, ``toggle_checkbox`` y ``recalcular``.

Flujo (idéntico al original en espíritu, distinto en mecánica):

    1. El usuario elige un CSV grabado por AcquisitionTab.
    2. Se parsea el encabezado de cliente + filas de datos (se
       descartan filas con EstadoIndentacion == "NI").
    3. ``core.processing.signal_filter.filtrar_senal`` limpia outliers
       y realinea tramos.
    4. ``core.processing.segmentation.procesar_senal_filtrada``
       segmenta por estado/pendiente y extrae (h_max, L, S) por ciclo.
    5. La curva intermedia (LVDT filtrado vs Carga) y la tabla de
       ciclos se muestran; cada fila tiene un checkbox ("Incluir") que
       decide si ese ciclo entra en el cálculo final.
    6. Al presionar "Calcular parámetros de indentación" se arma el
       diccionario de parámetros filtrado por los checkboxes y se llama
       a ``core.processing.oliver_pharr.calcular_resultados_indentacion``.

Diferencias respecto al original:
- Los pasos 2-4 corren en un ``QThread`` dedicado (``_AnalysisWorker``)
  en vez de un ``threading.Thread`` crudo con ``self.data_queue``
  implícito vía atributos de instancia; el progreso llega por señales
  Qt (``progress``, ``plot_ready``, ``datos_ready``, ``error``).
- ``self.cancel_flag`` se reemplaza por ``worker.cancel()``, que fija
  un flag leído por el ``cancel_check`` que recibe ``filtrar_senal``.
- Sin ``messagebox.askyesno`` de "¿agregar al preinforme?": el
  resultado del cálculo se emite por la señal ``resultado_calculado``
  para que ``ui/tabs/results_tab.py`` (próxima entrega) decida qué
  hacer con él. Mientras tanto, se muestra un resumen en un
  ``QMessageBox`` para que el cálculo ya sea útil hoy.
- "Calcular Dureza" queda como stub: el original leía
  ``self.Datos["L_max"]``, una clave que ``obtencion_datos`` nunca
  llega a definir (solo define ``"L"``, el array de cargas máximas por
  ciclo) — es decir, esa función ya estaba rota en el monolito. Se
  documenta acá en vez de reproducir el bug; se implementa como
  corresponde en ``ui/tabs/hardness_tab.py``.
"""

from __future__ import annotations

import csv as csv_module
from typing import Dict, List, Optional

import numpy as np
from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import config
from core.processing.oliver_pharr import ResultadoIndentacion, calcular_resultados_indentacion
from core.processing.segmentation import DatosIndentacion, procesar_senal_filtrada
from core.processing.signal_filter import filtrar_senal
from ui.widgets.matplotlib_canvas import MatplotlibWidget
from utils.logger import get_logger

log = get_logger()


class _AnalysisWorker(QThread):
    """Corre en un hilo aparte: parseo de CSV + filtrado + segmentación.
    Evita congelar la UI con archivos grandes, igual que el
    ``threading.Thread(target=tarea, daemon=True)`` original."""

    progress = Signal(str, float)          # (mensaje, porcentaje 0-100)
    client_info_ready = Signal(dict)       # {"fecha":..., "cliente":..., "solicitud":..., "muestra":...}
    plot_ready = Signal(object, object)    # (lvdt_um: np.ndarray, carga: np.ndarray)
    datos_ready = Signal(object)           # DatosIndentacion
    error = Signal(str)
    cancelled = Signal()

    def __init__(self, csv_path: str, parent=None):
        super().__init__(parent)
        self.csv_path = csv_path
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            self.progress.emit("Cargando...", 0.0)
            column_dict, client_info = self._parse_csv()
            self.client_info_ready.emit(client_info)

            if self._cancel:
                self.cancelled.emit()
                return

            self.progress.emit("Filtrando señal...", 50.0)
            filtered = filtrar_senal(
                column_dict["Tiempo(ms)"],
                column_dict["Desplazamiento LVDT"],
                column_dict["Desplazamiento(mm)"],
                column_dict["CargaF(N)"],
                column_dict["EstadoIndentacion"],
                cancel_check=lambda: self._cancel,
            )
            if filtered is None:
                self.cancelled.emit()
                return

            self.plot_ready.emit(filtered.lvdt_ajustado * 1000, filtered.carga)

            self.progress.emit("Segmentando y detectando patrones...", 70.0)
            datos = procesar_senal_filtrada(filtered)

            self.progress.emit("Cálculo terminado", 100.0)
            self.datos_ready.emit(datos)

        except Exception as exc:  # noqa: BLE001 - reportamos cualquier error al hilo de UI
            log.exception("Error procesando CSV de análisis")
            self.error.emit(str(exc))

    def _parse_csv(self):
        """Réplica de la lectura manual del original: 1 línea título +
        4 líneas de cliente + 1 línea de encabezado de columnas, luego
        filas de datos vía ``csv.DictReader``, descartando las que
        tengan ``EstadoIndentacion == config.ESTADO_NO_INICIADO``."""
        column_dict: Dict[str, List] = {
            "Tiempo(ms)": [],
            "MotorPosicion": [],
            "CargaF(N)": [],
            "Desplazamiento(mm)": [],
            "EstadoIndentacion": [],
            "Desplazamiento LVDT": [],
        }

        with open(self.csv_path, newline="", encoding="utf-8") as f:
            next(f)  # "Datos de Cliente"
            cliente_raw = [next(f).strip().split(",") for _ in range(config.CSV_CLIENT_INFO_LINES)]
            next(f)  # línea en blanco
            # next(f)  # encabezado de columnas de datos

            client_info = {
                "fecha": cliente_raw[0][1] if len(cliente_raw[0]) > 1 else "",
                "cliente": cliente_raw[1][1] if len(cliente_raw[1]) > 1 else "",
                "solicitud": cliente_raw[2][1] if len(cliente_raw[2]) > 1 else "",
                "muestra": cliente_raw[3][1] if len(cliente_raw[3]) > 1 else "",
            }

            reader = csv_module.DictReader(f, delimiter=",")
            for fila in reader:
                if self._cancel:
                    break
                if fila.get("EstadoIndentacion") == config.ESTADO_NO_INICIADO:
                    continue
                try:
                    column_dict["Tiempo(ms)"].append(float(fila["Tiempo(ms)"]))
                    column_dict["MotorPosicion"].append(float(fila["MotorPosicion"]))
                    column_dict["CargaF(N)"].append(float(fila["CargaF(N)"]))
                    column_dict["Desplazamiento(mm)"].append(float(fila["Desplazamiento(mm)"]))
                    column_dict["EstadoIndentacion"].append(fila["EstadoIndentacion"])
                    column_dict["Desplazamiento LVDT"].append(float(fila["Desplazamiento LVDT"]))
                except (ValueError, KeyError) as exc:
                    log.debug(f"Fila inválida o incompleta: {fila} — Error: {exc}")

        return column_dict, client_info


class AnalysisTab(QWidget):
    """Pestaña de análisis: carga de CSV, filtrado/segmentación y
    disparo del cálculo de parámetros de indentación."""

    #: Emitida al terminar un cálculo exitoso; ``results_tab`` (próxima
    #: entrega) se conectará acá para graficar/tabular el resultado.
    resultado_calculado = Signal(object)  # ResultadoIndentacion

    def __init__(self, parent=None):
        super().__init__(parent)

        self._csv_path = ""
        self._worker: Optional[_AnalysisWorker] = None
        self._datos: Optional[DatosIndentacion] = None

        self._build_ui()
        self._wire_signals()
        self._actualizar_calcular_ind()

    # ------------------------------------------------------------------
    # Construcción de la UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        layout.addWidget(self._build_file_group())
        layout.addWidget(self._build_graph_group(), stretch=1)
        layout.addWidget(self._build_table_group(), stretch=1)
        layout.addLayout(self._build_action_buttons())

    def _build_file_group(self) -> QGroupBox:
        box = QGroupBox("CARGA DE ARCHIVO CSV")
        grid = QGridLayout(box)

        grid.addWidget(QLabel("Archivo CSV:"), 0, 0)
        self.csv_path_edit = QLineEdit()
        self.csv_path_edit.setReadOnly(True)
        grid.addWidget(self.csv_path_edit, 0, 1)

        self.load_csv_btn = QPushButton("Cargar CSV")
        grid.addWidget(self.load_csv_btn, 0, 2)

        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.setVisible(False)
        grid.addWidget(self.cancel_btn, 0, 3)

        self.borrar_csv_btn = QPushButton("Borrar")
        grid.addWidget(self.borrar_csv_btn, 0, 4)

        self.status_label = QLabel("")
        grid.addWidget(self.status_label, 0, 5)

        self.progress_label = QLabel("")
        grid.addWidget(self.progress_label, 0, 6)

        grid.addWidget(QLabel("Tipo de Acero:"), 1, 0)
        self.acero_combo = QComboBox()
        self.acero_combo.addItem("")  # arranca vacío, como el original
        self.acero_combo.addItems(list(config.MATERIAL_BETA_M.keys()))
        grid.addWidget(self.acero_combo, 1, 1)

        proc_box = QGroupBox("Elija el procedimiento utilizado")
        proc_row = QHBoxLayout(proc_box)
        self.rb_dureza_calc = QRadioButton("DUREZA")
        self.rb_indentacion_calc = QRadioButton("INDENTACIÓN")
        proc_row.addWidget(self.rb_dureza_calc)
        proc_row.addWidget(self.rb_indentacion_calc)
        grid.addWidget(proc_box, 1, 2, 1, 2)

        grid.setColumnStretch(1, 1)
        return box

    def _build_graph_group(self) -> QGroupBox:
        box = QGroupBox("GRÁFICO DE ANÁLISIS")
        layout = QVBoxLayout(box)

        self.clear_plot_btn = QPushButton("Limpiar gráfico")
        layout.addWidget(self.clear_plot_btn, alignment=Qt.AlignLeft)

        self.plot_widget = MatplotlibWidget(nrows=1, ncols=1, figsize=(10, 6))
        self._reset_plot()
        layout.addWidget(self.plot_widget, stretch=1)

        return box

    def _build_table_group(self) -> QGroupBox:
        box = QGroupBox("TABLA DE RESULTADOS")
        layout = QVBoxLayout(box)

        self.results_table = QTableWidget(0, 4)
        self.results_table.setHorizontalHeaderLabels(
            ["Desplazamiento máximo (µm)", "Carga máxima (N)", "Pendiente de descarga (N/µm)", "Incluir"]
        )
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.results_table.setSelectionMode(QAbstractItemView.NoSelection)
        layout.addWidget(self.results_table)

        return box

    def _build_action_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.calcular_ind_btn = QPushButton("Calcular parámetros de indentación")
        self.calcular_dur_btn = QPushButton("Calcular Dureza")
        row.addStretch(1)
        row.addWidget(self.calcular_ind_btn)
        row.addWidget(self.calcular_dur_btn)
        row.addStretch(1)
        return row

    # ------------------------------------------------------------------
    # Conexión de señales
    # ------------------------------------------------------------------
    def _wire_signals(self) -> None:
        self.load_csv_btn.clicked.connect(self._load_csv_file)
        self.cancel_btn.clicked.connect(self._cancel_processing)
        self.borrar_csv_btn.clicked.connect(self._borrar_csv)
        self.clear_plot_btn.clicked.connect(self._reset_plot)

        self.acero_combo.currentIndexChanged.connect(self._actualizar_calcular_ind)
        self.rb_dureza_calc.toggled.connect(self._actualizar_calcular_ind)
        self.rb_indentacion_calc.toggled.connect(self._actualizar_calcular_ind)

        self.calcular_ind_btn.clicked.connect(self._calcular_indentacion)
        self.calcular_dur_btn.clicked.connect(self._calcular_dureza)

    # ------------------------------------------------------------------
    # Carga y procesamiento de CSV
    # ------------------------------------------------------------------
    def _load_csv_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar archivo CSV", "", "Archivos CSV (*.csv)"
        )
        if not file_path:
            return

        self._csv_path = file_path
        self.csv_path_edit.setText(file_path)
        self._process_csv_data(file_path)

    def _process_csv_data(self, csv_path: str) -> None:
        self._set_ui_busy(True)
        self.status_label.setText("Cargando...")
        self.progress_label.setText("0.0%")

        self._worker = _AnalysisWorker(csv_path)
        self._worker.progress.connect(self._on_progress)
        self._worker.client_info_ready.connect(self._on_client_info)
        self._worker.plot_ready.connect(self._on_plot_ready)
        self._worker.datos_ready.connect(self._on_datos_ready)
        self._worker.error.connect(self._on_error)
        self._worker.cancelled.connect(self._on_cancelled)
        self._worker.finished.connect(lambda: self._set_ui_busy(False))
        self._worker.start()

    def _cancel_processing(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.status_label.setText("Cancelando...")

    def _set_ui_busy(self, busy: bool) -> None:
        self.load_csv_btn.setEnabled(not busy)
        self.borrar_csv_btn.setEnabled(not busy)
        self.cancel_btn.setVisible(busy)

    def _on_progress(self, message: str, percent: float) -> None:
        self.status_label.setText(message)
        self.progress_label.setText(f"{percent:.1f}%")

    def _on_client_info(self, client_info: dict) -> None:
        # ``results_tab``/``report_tab`` (próxima entrega) mostrarán estos
        # datos en sus propios encabezados; por ahora solo quedan en el log.
        log.info(f"Datos de cliente leídos del CSV: {client_info}")

    def _on_plot_ready(self, lvdt_um, carga) -> None:
        ax = self.plot_widget.ax()
        ax.clear()
        ax.plot(lvdt_um, carga, linestyle="-")
        ax.set_xlabel(r"Desplazamiento ($\mu$m)")
        ax.set_ylabel("Carga (N)")
        ax.set_title("Curva Carga vs. Desplazamiento")
        ax.grid(True)
        self.plot_widget.redraw()

    def _on_datos_ready(self, datos: DatosIndentacion) -> None:
        self._datos = datos
        self._populate_results_table(datos)
        self.status_label.setText("Cálculo terminado")
        self.progress_label.setText("100.0%")

    def _on_cancelled(self) -> None:
        self.status_label.setText("Cancelado por usuario")
        self.progress_label.setText("0.0%")

    def _on_error(self, message: str) -> None:
        self.status_label.setText("Error de Lectura/Procesamiento")
        self.status_label.setStyleSheet("color: red;")
        self.progress_label.setText("0.0%")
        QMessageBox.critical(self, "Error", "No se pudo cargar o procesar el archivo CSV")
        log.error(f"Error procesando CSV: {message}")

    # ------------------------------------------------------------------
    # Tabla de ciclos detectados
    # ------------------------------------------------------------------
    def _populate_results_table(self, datos: DatosIndentacion) -> None:
        self.results_table.setRowCount(0)
        h_max_um = datos.h_max * 1e6
        carga = datos.L
        S_n_um = datos.S / 1e6

        self.results_table.setRowCount(datos.n_ciclos())
        for row, (h, l, s) in enumerate(zip(h_max_um, carga, S_n_um)):
            self.results_table.setItem(row, 0, QTableWidgetItem(f"{h:.1f}"))
            self.results_table.setItem(row, 1, QTableWidgetItem(f"{l:.1f}"))
            self.results_table.setItem(row, 2, QTableWidgetItem(f"{s:.1f}"))

            incluir_item = QTableWidgetItem()
            incluir_item.setCheckState(Qt.Checked)
            incluir_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            self.results_table.setItem(row, 3, incluir_item)

    def _mascara_incluidos(self) -> np.ndarray:
        n = self.results_table.rowCount()
        mask = np.zeros(n, dtype=bool)
        for row in range(n):
            item = self.results_table.item(row, 3)
            mask[row] = item is not None and item.checkState() == Qt.Checked
        return mask

    # ------------------------------------------------------------------
    # Limpieza
    # ------------------------------------------------------------------
    def _reset_plot(self) -> None:
        ax = self.plot_widget.ax()
        ax.clear()
        ax.set_title("Gráfico de análisis (Seleccione y procese archivo)")
        ax.set_xlabel("Eje X")
        ax.set_ylabel("Eje Y")
        ax.grid(True)
        self.plot_widget.redraw()

    def _borrar_csv(self) -> None:
        self._csv_path = ""
        self.csv_path_edit.setText("")
        self._reset_plot()
        self.results_table.setRowCount(0)
        self.acero_combo.setCurrentIndex(0)
        self.rb_dureza_calc.setAutoExclusive(False)
        self.rb_indentacion_calc.setAutoExclusive(False)
        self.rb_dureza_calc.setChecked(False)
        self.rb_indentacion_calc.setChecked(False)
        self.rb_dureza_calc.setAutoExclusive(True)
        self.rb_indentacion_calc.setAutoExclusive(True)
        self._datos = None
        self._actualizar_calcular_ind()
        self.status_label.setText("Archivo eliminado")
        self.status_label.setStyleSheet("color: orange;")

    # ------------------------------------------------------------------
    # Habilitación del botón de cálculo (réplica de actualizar_calcular_ind)
    # ------------------------------------------------------------------
    def _actualizar_calcular_ind(self) -> None:
        if self.rb_dureza_calc.isChecked() or not (
            self.rb_dureza_calc.isChecked() or self.rb_indentacion_calc.isChecked()
        ):
            self.calcular_ind_btn.setEnabled(False)
        elif self.acero_combo.currentText() == "":
            self.calcular_ind_btn.setEnabled(False)
        else:
            self.calcular_ind_btn.setEnabled(True)

    # ------------------------------------------------------------------
    # Cálculo de parámetros de indentación (réplica de "recalcular")
    # ------------------------------------------------------------------
    def _calcular_indentacion(self) -> None:
        if self._datos is None:
            QMessageBox.critical(self, "Error", "No se cargó un archivo de datos.")
            return

        mask = self._mascara_incluidos()
        if not np.any(mask):
            QMessageBox.warning(self, "Atención", "No hay ciclos incluidos (todos los checkboxes están destildados).")
            return

        material = self.acero_combo.currentText()
        datos = self._datos

        parametros = {
            "h_max": datos.h_max[mask],
            "err_h_max": datos.err_h[mask],
            "L": datos.L[mask],
            "err_L": datos.err_L[mask],
            "S": datos.S[mask],
            "err_S": datos.err_S[mask],
            "R": datos.R,
            "err_R": config.DEFAULT_ERR_R,
            "E_i": datos.E_i,
            "err_E_i": config.DEFAULT_ERR_E_I,
            "E": datos.E,
            "err_E": config.DEFAULT_ERR_E,
        }

        try:
            resultado: ResultadoIndentacion = calcular_resultados_indentacion(parametros, material)
        except KeyError as exc:
            QMessageBox.critical(self, "Error", str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("Error calculando parámetros de indentación")
            QMessageBox.critical(self, "Error", f"No se pudo completar el cálculo:\n{exc}")
            return

        self.resultado_calculado.emit(resultado)

        QMessageBox.information(
            self,
            "Cálculo terminado",
            (
                f"σy = {resultado.sigma_y / 1e6:.1f} ± {resultado.err_sigma_y / 1e6:.1f} MPa\n"
                f"n = {resultado.n:.3f} ± {resultado.err_n:.3f}\n"
                f"UTS = {resultado.UTS1 / 1e6:.1f} ± {resultado.err_UTS1 / 1e6:.1f} MPa\n\n"
                "El detalle completo (curva y tabla) se mostrará en la pestaña "
                "'Resultados Finales' en la próxima entrega."
            ),
        )

    def _calcular_dureza(self) -> None:
        """Placeholder: ver docstring del módulo (bug de ``self.Datos['L_max']``
        en el original). Se implementa correctamente en ``hardness_tab.py``."""
        QMessageBox.information(
            self,
            "Próximamente",
            "El cálculo de Dureza (Brinell) se implementa en la pestaña "
            "'Pre - Informe (Dureza)' en una próxima entrega.",
        )

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------
    def shutdown(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(2000)