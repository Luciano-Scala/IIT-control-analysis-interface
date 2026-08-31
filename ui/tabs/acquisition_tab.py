"""
ui/tabs/acquisition_tab.py
============================
Pestaña "Adquisición de Datos". Traducción del ``setup_ui`` original
(líneas ~292-637) más la lógica de conexión serie, grabación a CSV,
indentación automática y control de motor que en el monolito estaba
repartida entre ``toggle_serial_connection``, ``start_recording``,
``stop_recording``, ``process_serial_data``, ``update_ui``,
``start_auto_indentation``, ``stop_auto_indentation``, ``aprox_material``,
``subir_motor``, ``bajar_motor``, ``parar_motor`` y ``update_Jestado``.

Diferencias clave respecto al original:
- La lectura serie ya no pasa por ``self.data_queue`` +
  ``root.after(200, self.update_ui)``: usa ``SerialWorker`` (QThread)
  y sus señales (ver ``core/hardware/serial_worker.py``). Los puntos
  llegan uno por uno vía ``data_point_received`` (Qt los encola
  automáticamente al hilo principal); esta pestaña los junta en un
  buffer y un ``QTimer`` los vuelca en lote cada
  ``config.ACQUISITION_UI_REFRESH_MS`` — mismo criterio de "actualizar
  en lote" que el original, pero sin acoplarse a ``queue.Queue``.
- Sin SQLite: el número de indentación para el nombre de archivo es un
  contador en memoria (``self._contador_indentacion``), no una
  consulta a ``Logger.db``. Si más adelante se agrega persistencia,
  va en una capa aparte (``core/`` con QtSql), sin tocar esta pestaña.
- Sin ``messagebox`` de Tkinter: se usa ``QMessageBox``.
- Fuera de alcance por ahora (se agregan en una entrega posterior):
  exportación a PDF (``utils/pdf_exporter.py``), vista de cámara,
  panel de temperatura/GPS/burbuja y las alertas sonoras (``winsound``
  es específico de Windows y no es parte de la lógica de adquisición).
"""

from __future__ import annotations

import csv
import os
from datetime import datetime
from typing import List, Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import config
from core.hardware.serial_worker import IndentationDataPoint, SerialWorker, list_serial_ports
from ui.widgets.matplotlib_canvas import MatplotlibWidget
from utils.logger import get_logger

log = get_logger()


class LedIndicator(QLabel):
    """LED circular simple (reemplazo liviano del ``tk.Canvas`` con un
    óvalo que usaba ``create_led`` en el original). Se moverá a
    ``ui/widgets/status_panel.py`` cuando esa pestaña compartida se
    construya; por ahora vive acá porque es la única que lo usa.
    """

    def __init__(self, diameter: int = 18, color: str = "red", parent=None):
        super().__init__(parent)
        self._diameter = diameter
        self.setFixedSize(diameter, diameter)
        self.set_color(color)

    def set_color(self, color: str) -> None:
        self.setStyleSheet(
            f"background-color: {color}; border-radius: {self._diameter // 2}px; "
            f"border: 1px solid #333;"
        )


class AcquisitionTab(QWidget):
    """Pestaña de adquisición: conexión serie, grabación a CSV, gráfico
    en vivo Carga vs LVDT, e indentación automática."""

    def __init__(self, parent=None):
        super().__init__(parent)

        # ---- Estado interno (antes atributos sueltos de DataLoggerApp) ----
        self._worker: Optional[SerialWorker] = None
        self._connected = False
        self._recording = False
        self._csv_header_written = False
        self._file_path = ""
        self._file_name = config.DEFAULT_CSV_FILENAME
        self._contador_indentacion = 1  # reemplaza al MAX(ind_local) de SQLite

        self._pending_points: List[IndentationDataPoint] = []
        self._time_data: List[int] = []
        self._load_data: List[float] = []
        self._lvdt_data: List[float] = []
        self._motor_pos_data: List[int] = []

        self._use_autoscale = True
        self._auto_indent_active = False

        self._build_ui()
        self._wire_signals()

        self._refresh_ports()

        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(config.ACQUISITION_UI_REFRESH_MS)
        self._flush_timer.timeout.connect(self._flush_pending_points)
        self._flush_timer.start()

    # ------------------------------------------------------------------
    # Construcción de la UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root_layout = QHBoxLayout(self)

        left_col = QVBoxLayout()
        right_col = QVBoxLayout()
        root_layout.addLayout(left_col, stretch=3)
        root_layout.addLayout(right_col, stretch=1)

        left_col.addWidget(self._build_client_group())
        left_col.addWidget(self._build_config_group())
        left_col.addWidget(self._build_control_group())
        left_col.addWidget(self._build_plot_group(), stretch=1)
        left_col.addLayout(self._build_status_row())
        left_col.addWidget(self._build_auto_indent_group())

        right_col.addWidget(self._build_state_group())
        right_col.addStretch(1)

    def _build_client_group(self) -> QGroupBox:
        box = QGroupBox("DATOS DEL CLIENTE")
        grid = QGridLayout(box)

        grid.addWidget(QLabel("Fecha:"), 0, 0)
        self.fecha_edit = QLineEdit(datetime.now().strftime("%d/%m/%Y"))
        self.fecha_edit.setReadOnly(True)
        self.fecha_edit.setFixedWidth(100)
        grid.addWidget(self.fecha_edit, 0, 1)

        grid.addWidget(QLabel("Cliente:"), 0, 2)
        self.cliente_edit = QLineEdit()
        grid.addWidget(self.cliente_edit, 0, 3)

        grid.addWidget(QLabel("Solicitud N°:"), 1, 0)
        self.solicitud_edit = QLineEdit()
        self.solicitud_edit.setFixedWidth(100)
        grid.addWidget(self.solicitud_edit, 1, 1)

        grid.addWidget(QLabel("Identificación de Muestra:"), 1, 2)
        self.muestra_edit = QLineEdit()
        grid.addWidget(self.muestra_edit, 1, 3)

        grid.setColumnStretch(3, 1)
        return box

    def _build_config_group(self) -> QGroupBox:
        box = QGroupBox("CONFIGURACIÓN")
        grid = QGridLayout(box)

        grid.addWidget(QLabel("Puerto COM:"), 0, 0)
        self.port_combo = QComboBox()
        self.port_combo.setEditable(False)
        grid.addWidget(self.port_combo, 0, 1)

        self.refresh_ports_btn = QPushButton("Actualizar puertos")
        grid.addWidget(self.refresh_ports_btn, 0, 2)

        self.connect_btn = QPushButton("Conectar")
        grid.addWidget(self.connect_btn, 0, 3)

        grid.addWidget(QLabel("Nombre archivo:"), 1, 0)
        self.filename_edit = QLineEdit(self._file_name)
        self.filename_edit.setReadOnly(True)
        grid.addWidget(self.filename_edit, 1, 1)

        self.browse_btn = QPushButton("Seleccionar ubicación")
        grid.addWidget(self.browse_btn, 1, 2)

        self.refresh_name_btn = QPushButton("↻ Actualizar Nro")
        grid.addWidget(self.refresh_name_btn, 1, 3)

        grid.addWidget(QLabel("Intervalo (ms):"), 2, 0)
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 60000)
        self.interval_spin.setValue(config.DEFAULT_RECORD_INTERVAL_MS)
        grid.addWidget(self.interval_spin, 2, 1)

        return box

    def _build_control_group(self) -> QGroupBox:
        box = QGroupBox("CONTROL DE DATOS")
        outer = QVBoxLayout(box)

        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("Iniciar Registro")
        self.start_btn.setEnabled(False)
        self.stop_btn = QPushButton("Detener Registro")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setObjectName("dangerButton")
        self.clear_btn = QPushButton("Limpiar Gráfico")
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addWidget(self.clear_btn)
        btn_row.addStretch(1)
        outer.addLayout(btn_row)

        proc_box = QGroupBox("Elija el procedimiento")
        proc_row = QHBoxLayout(proc_box)
        self.rb_dureza = QRadioButton("DUREZA")
        self.rb_indentacion = QRadioButton("INDENTACIÓN COMPLETA")
        self.procedimiento_group = QButtonGroup(self)
        self.procedimiento_group.addButton(self.rb_dureza)
        self.procedimiento_group.addButton(self.rb_indentacion)
        proc_row.addWidget(self.rb_dureza)
        proc_row.addWidget(self.rb_indentacion)
        proc_row.addStretch(1)
        outer.addWidget(proc_box)

        return box

    def _build_plot_group(self) -> QGroupBox:
        box = QGroupBox("GRÁFICO CARGA vs LVDT — TIEMPO REAL")
        layout = QVBoxLayout(box)

        self.plot_widget = MatplotlibWidget(nrows=1, ncols=1, figsize=(8, 5))
        ax = self.plot_widget.ax()
        ax.set_title("Curva Carga vs Desplazamiento LVDT")
        ax.set_xlabel("Desplazamiento LVDT (mm)")
        ax.set_ylabel("Carga (N)")
        ax.grid(True)
        (self._plot_line,) = ax.plot([], [], "r-", linewidth=2)
        layout.addWidget(self.plot_widget, stretch=1)

        controls_row = QHBoxLayout()
        self.autoscale_btn = QPushButton("Autoescala")
        self.fixed_scale_btn = QPushButton("Escala Fija")
        controls_row.addWidget(self.autoscale_btn)
        controls_row.addWidget(self.fixed_scale_btn)
        controls_row.addStretch(1)
        layout.addLayout(controls_row)

        return box

    def _build_status_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.status_label = QLabel("Desconectado")
        self.status_label.setStyleSheet("color: red;")
        self.recording_label = QLabel("No grabando")
        self.recording_label.setStyleSheet("color: gray;")
        row.addWidget(self.status_label)
        row.addStretch(1)
        row.addWidget(self.recording_label)
        return row

    def _build_auto_indent_group(self) -> QGroupBox:
        box = QGroupBox("INDENTACIÓN AUTOMÁTICA POR INTERVALOS")
        outer = QVBoxLayout(box)

        # Parámetros según procedimiento (equivalente a iso_config_frame /
        # brinell_config_frame, alternados con grid()/grid_remove() en el original)
        self.param_stack = QStackedWidget()

        iso_page = QGroupBox("Parámetros ISO 14577")
        QVBoxLayout(iso_page).addWidget(QLabel("(sin parámetros configurables por ahora)"))

        brinell_page = QGroupBox("Parámetros Brinell")
        brinell_layout = QHBoxLayout(brinell_page)
        brinell_layout.addWidget(QLabel("Carga objetivo (N):"))
        self.brinell_carga_combo = QComboBox()
        self.brinell_carga_combo.addItems(["741"])
        brinell_layout.addWidget(self.brinell_carga_combo)
        brinell_layout.addWidget(QLabel("Tiempo mantenimiento (s):"))
        self.brinell_tiempo_combo = QComboBox()
        self.brinell_tiempo_combo.addItems(["10"])
        brinell_layout.addWidget(self.brinell_tiempo_combo)
        brinell_layout.addStretch(1)

        self.param_stack.addWidget(QWidget())  # índice 0: nada seleccionado
        self.param_stack.addWidget(iso_page)      # índice 1
        self.param_stack.addWidget(brinell_page)  # índice 2
        outer.addWidget(self.param_stack)

        btn_row = QHBoxLayout()
        self.start_indent_btn = QPushButton("Iniciar Indentación")
        self.stop_indent_btn = QPushButton("Detener Indentación")
        self.stop_indent_btn.setEnabled(False)
        self.stop_indent_btn.setObjectName("dangerButton")
        self.aprox_mat_btn = QPushButton("Aproximar Material")
        self.subir_motor_btn = QPushButton("SUBIR")
        self.bajar_motor_btn = QPushButton("BAJAR")
        self.parar_motor_btn = QPushButton("PARAR")
        self.parar_motor_btn.setObjectName("dangerButton")
        self.ver_camara_btn = QPushButton("VER CÁMARA 📷")
        self.ver_camara_btn.setEnabled(False)
        self.ver_camara_btn.setToolTip("No implementado en esta entrega")

        for b in (
            self.start_indent_btn,
            self.stop_indent_btn,
            self.aprox_mat_btn,
            self.subir_motor_btn,
            self.bajar_motor_btn,
            self.parar_motor_btn,
            self.ver_camara_btn,
        ):
            btn_row.addWidget(b)
        outer.addLayout(btn_row)

        self.indent_status_label = QLabel("Listo")
        self.indent_status_label.setAlignment(Qt.AlignCenter)
        self.indent_status_label.setStyleSheet("color: blue; font-weight: bold;")
        outer.addWidget(self.indent_status_label)

        return box

    def _build_state_group(self) -> QGroupBox:
        box = QGroupBox("ESTADO")
        grid = QGridLayout(box)

        grid.addWidget(QLabel("Conexión:"), 0, 0)
        self.led_conexion = LedIndicator(color="red")
        grid.addWidget(self.led_conexion, 0, 1)

        grid.addWidget(QLabel("Endstop inicial:"), 1, 0)
        self.led_endstop_ini = LedIndicator(color="red")
        grid.addWidget(self.led_endstop_ini, 1, 1)

        grid.addWidget(QLabel("Endstop final:"), 2, 0)
        self.led_endstop_fin = LedIndicator(color="red")
        grid.addWidget(self.led_endstop_fin, 2, 1)

        grid.addWidget(QLabel("J Actual:"), 3, 0)
        self.j_actual_label = QLabel("No iniciado")
        grid.addWidget(self.j_actual_label, 3, 1)

        grid.addWidget(QLabel("Carga (N):"), 4, 0)
        self.load_label = QLabel("0.00")
        grid.addWidget(self.load_label, 4, 1)

        grid.addWidget(QLabel("Desplazamiento (mm):"), 5, 0)
        self.disp_label = QLabel("0.00")
        grid.addWidget(self.disp_label, 5, 1)

        grid.addWidget(QLabel("Posición motor:"), 6, 0)
        self.motor_pos_label = QLabel("0")
        grid.addWidget(self.motor_pos_label, 6, 1)

        return box

    # ------------------------------------------------------------------
    # Conexión de señales
    # ------------------------------------------------------------------
    def _wire_signals(self) -> None:
        self.refresh_ports_btn.clicked.connect(self._refresh_ports)
        self.connect_btn.clicked.connect(self._toggle_connection)
        self.browse_btn.clicked.connect(self._select_file_location)
        self.refresh_name_btn.clicked.connect(self._actualizar_nombre_archivo)

        self.start_btn.clicked.connect(self._start_recording)
        self.stop_btn.clicked.connect(self._stop_recording)
        self.clear_btn.clicked.connect(self._clear_plot)

        self.rb_dureza.toggled.connect(self._on_procedimiento_changed)
        self.rb_indentacion.toggled.connect(self._on_procedimiento_changed)

        self.autoscale_btn.clicked.connect(self._apply_autoscale)
        self.fixed_scale_btn.clicked.connect(self._apply_fixed_scale)

        self.start_indent_btn.clicked.connect(self._start_auto_indentation)
        self.stop_indent_btn.clicked.connect(self._stop_auto_indentation)
        self.aprox_mat_btn.clicked.connect(self._aprox_material)
        self.subir_motor_btn.clicked.connect(self._subir_motor)
        self.bajar_motor_btn.clicked.connect(self._bajar_motor)
        self.parar_motor_btn.clicked.connect(self._parar_motor)

    # ------------------------------------------------------------------
    # Puerto serie: listado / conexión
    # ------------------------------------------------------------------
    def _refresh_ports(self) -> None:
        ports = list_serial_ports()
        self.port_combo.clear()
        self.port_combo.addItems(ports)
        if ports:
            self.port_combo.setCurrentIndex(0)

    def _toggle_connection(self) -> None:
        if self._connected:
            self._disconnect_serial()
        else:
            self._connect_serial()

    def _connect_serial(self) -> None:
        port = self.port_combo.currentText()
        if not port:
            QMessageBox.critical(self, "Error", "Seleccione un puerto COM")
            return

        self._worker = SerialWorker(port, baudrate=config.SERIAL_BAUDRATE)
        self._worker.data_point_received.connect(self._on_data_point)
        self._worker.raw_line_received.connect(lambda line: log.debug(f"Serial msg: {line}"))
        self._worker.parse_error.connect(lambda msg: log.error(msg))
        self._worker.connection_error.connect(self._on_connection_error)
        self._worker.connection_state_changed.connect(self._on_connection_state_changed)
        self._worker.start()

    def _disconnect_serial(self) -> None:
        if self._worker is not None:
            self._worker.stop()
            self._worker = None
        self._connected = False
        self.status_label.setText("Desconectado")
        self.status_label.setStyleSheet("color: red;")
        self.led_conexion.set_color("red")
        self.connect_btn.setText("Conectar")
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self._recording = False
        self.recording_label.setText("No grabando")
        self.recording_label.setStyleSheet("color: gray;")

    def _on_connection_state_changed(self, connected: bool) -> None:
        self._connected = connected
        if connected:
            self.status_label.setText("Conectado")
            self.status_label.setStyleSheet("color: green;")
            self.led_conexion.set_color("green")
            self.connect_btn.setText("Desconectar")
            self.start_btn.setEnabled(True)
            log.info(f"Conexión serial establecida: {self.port_combo.currentText()}")
        else:
            self.status_label.setText("Desconectado")
            self.status_label.setStyleSheet("color: red;")
            self.led_conexion.set_color("red")
            self.connect_btn.setText("Conectar")
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)

    def _on_connection_error(self, message: str) -> None:
        log.error(message)
        QMessageBox.critical(self, "Error de conexión", message)
        self._disconnect_serial()

    # ------------------------------------------------------------------
    # Archivo de salida
    # ------------------------------------------------------------------
    def _select_file_location(self) -> None:
        sugerido = self.filename_edit.text() or config.DEFAULT_CSV_FILENAME
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Guardar archivo CSV como", sugerido, "CSV Files (*.csv);;All Files (*.*)"
        )
        if not file_path:
            return

        if not file_path.lower().endswith(".csv"):
            file_path += ".csv"

        self._file_path = file_path
        self._file_name = os.path.basename(file_path)
        self.filename_edit.setText(self._file_name)

        try:
            open(self._file_path, "w", newline="").close()  # reserva el nombre
        except OSError as exc:
            QMessageBox.critical(self, "Error al crear archivo", f"No se pudo crear el archivo:\n{exc}")
            return

        QMessageBox.information(self, "Ubicación seleccionada", f"Archivo configurado:\n{self._file_path}")

    def _generar_nombre_archivo(self) -> str:
        """Genera un nombre de archivo a partir de los datos de cliente.

        Reemplaza la consulta ``SELECT MAX(ind_local) ...`` a SQLite del
        original por un contador en memoria (ver docstring del módulo).
        """
        fecha = self.fecha_edit.text().upper()
        cliente = self.cliente_edit.text().strip().upper()
        solicitud = self.solicitud_edit.text().strip().upper()
        muestra = self.muestra_edit.text().strip().upper()

        cliente_limpio = "".join(c for c in cliente if c.isalnum() or c in (" ", "-", "_")).rstrip()
        fecha_limpia = fecha.replace("/", "")

        partes = [f"IND{self._contador_indentacion}"]
        if cliente_limpio:
            partes.append(cliente_limpio)
        if solicitud:
            partes.append(f"SOL-{solicitud}")
        if muestra:
            partes.append(f"IDM-{muestra}")
        if fecha_limpia:
            partes.append(fecha_limpia)

        return "_".join(partes) + ".csv"

    def _actualizar_nombre_archivo(self) -> None:
        nuevo_nombre = self._generar_nombre_archivo()
        self.filename_edit.setText(nuevo_nombre)
        if self._file_path:
            carpeta = os.path.dirname(self._file_path)
            self._file_path = os.path.join(carpeta, nuevo_nombre)
        self._file_name = nuevo_nombre

    # ------------------------------------------------------------------
    # Grabación
    # ------------------------------------------------------------------
    def _start_recording(self) -> None:
        if not self._connected:
            QMessageBox.critical(self, "Error", "No hay conexión serial")
            return
        if not self._file_name:
            QMessageBox.critical(self, "Error", "Seleccione un nombre de archivo")
            return

        if os.path.dirname(self._file_path):
            self._file_path = os.path.join(os.path.dirname(self._file_path), self._file_name)
        else:
            self._file_path = self._file_name

        if os.path.exists(self._file_path) and os.path.getsize(self._file_path) > 200:
            resp = QMessageBox.question(
                self,
                "Atención",
                f"El archivo ya contiene datos:\n{self._file_name}\n\n"
                "¿Sobreescribir? (se perderá todo el contenido anterior)",
            )
            if resp != QMessageBox.Yes:
                return

        client_data = {
            "fecha": self.fecha_edit.text(),
            "cliente": self.cliente_edit.text(),
            "solicitud": self.solicitud_edit.text(),
            "muestra": self.muestra_edit.text(),
        }
        try:
            with open(self._file_path, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Datos de Cliente"])
                writer.writerow(["Fecha:", client_data["fecha"]])
                writer.writerow(["Cliente:", client_data["cliente"]])
                writer.writerow(["Solicitud Nro.:", client_data["solicitud"]])
                writer.writerow(["Identificacion de Muestra:", client_data["muestra"]])
                writer.writerow([])
                writer.writerow(
                    ["Tiempo(ms)", "MotorPosicion", "CargaF(N)", "Desplazamiento(mm)",
                     "EstadoIndentacion", "Desplazamiento LVDT"]
                )
            self._csv_header_written = True
            log.info(f"Archivo CSV creado con encabezado: {self._file_path}")
        except OSError as exc:
            QMessageBox.critical(self, "Error", f"No se pudo crear el archivo:\n{exc}")
            return

        self._recording = True
        self._set_recording_ui_lock(True)
        self.recording_label.setText("Grabando")
        self.recording_label.setStyleSheet("color: green;")
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        if self._worker is not None:
            self._worker.send_command(config.CMD_START_RECORDING)
            log.debug("Comando G enviado al serial")

    def _stop_recording(self) -> None:
        self._recording = False
        self._csv_header_written = False
        self._set_recording_ui_lock(False)
        self.recording_label.setText("No grabando")
        self.recording_label.setStyleSheet("color: gray;")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

        if self._worker is not None:
            self._worker.send_command(config.CMD_STOP_RECORDING)

    def _set_recording_ui_lock(self, locking: bool) -> None:
        """Bloquea/desbloquea controles que no deben tocarse mientras
        se está grabando (equivalente a ``_set_recording_ui_lock``)."""
        self.cliente_edit.setReadOnly(locking)
        self.solicitud_edit.setReadOnly(locking)
        self.muestra_edit.setReadOnly(locking)

        self.port_combo.setEnabled(not locking)
        self.connect_btn.setEnabled(not locking)
        self.refresh_ports_btn.setEnabled(not locking)
        self.browse_btn.setEnabled(not locking)
        self.refresh_name_btn.setEnabled(not locking)

    # ------------------------------------------------------------------
    # Gráfico
    # ------------------------------------------------------------------
    def _clear_plot(self) -> None:
        self._time_data.clear()
        self._load_data.clear()
        self._lvdt_data.clear()
        self._motor_pos_data.clear()
        self._update_plot()

    def _update_plot(self) -> None:
        if self._lvdt_data and self._load_data:
            self._plot_line.set_data(self._lvdt_data, self._load_data)
            ax = self.plot_widget.ax()
            if self._use_autoscale:
                ax.relim()
                ax.autoscale_view()
            self.plot_widget.redraw()

    def _apply_autoscale(self) -> None:
        self._use_autoscale = True
        ax = self.plot_widget.ax()
        ax.relim()
        ax.autoscale_view()
        self.plot_widget.redraw()

    def _apply_fixed_scale(self) -> None:
        self._use_autoscale = False
        ax = self.plot_widget.ax()
        ax.set_xlim(0, 0.75)
        ax.set_ylim(0, 2500)
        self.plot_widget.redraw()

    # ------------------------------------------------------------------
    # Recepción de datos (SerialWorker -> buffer -> flush en lote)
    # ------------------------------------------------------------------
    def _on_data_point(self, point: IndentationDataPoint) -> None:
        self._pending_points.append(point)

    def _flush_pending_points(self) -> None:
        if not self._pending_points:
            return

        pending, self._pending_points = self._pending_points, []
        csv_rows = []

        for point in pending:
            self._time_data.append(point.time_ms)
            self._load_data.append(point.load)
            self._lvdt_data.append(point.lvdt)
            self._motor_pos_data.append(point.motor_pos)

            if self._recording and self._csv_header_written:
                csv_rows.append(point.raw_fields)

        last = pending[-1]
        self.j_actual_label.setText(self._estado_texto(last.estado))
        self.load_label.setText(f"{last.load:.2f}")
        self.disp_label.setText(f"{last.displacement:.2f}")
        self.motor_pos_label.setText(str(last.motor_pos))

        if csv_rows and self._recording and self._csv_header_written:
            try:
                with open(self._file_path, mode="a", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerows(csv_rows)
            except OSError as exc:
                log.error(f"Error al escribir en CSV: {exc}")

        self._update_plot()

    def _estado_texto(self, codigo: str) -> str:
        """Traduce el código de estado (p.ej. 'J1C', 'NI') a un texto
        legible para ``j_actual_label``. Réplica de ``update_Jestado``."""
        if not codigo or not isinstance(codigo, str):
            return self.j_actual_label.text()

        codigo = codigo.strip().upper()

        if codigo and codigo[0] == "J":
            if codigo[-1] == "C":
                return f"Ciclo {codigo[:-1]}: Carga"
            elif codigo[-1] == "E":
                return f"Ciclo {codigo[:-1]}: Espera"
            else:
                return f"Ciclo {codigo[:-1]}: Descarga"

        if self.j_actual_label.text() == "No iniciado":
            return "Iniciando"

        if self._motor_pos_data and abs(self._motor_pos_data[-1]) >= 0:
            return "Finalizando"

        return "Indentación Finalizada"

    # ------------------------------------------------------------------
    # Procedimiento (Dureza / Indentación completa)
    # ------------------------------------------------------------------
    def _on_procedimiento_changed(self) -> None:
        if self.rb_dureza.isChecked():
            self.aprox_mat_btn.setEnabled(False)
            self.param_stack.setCurrentIndex(2)
            self.start_indent_btn.setText("Iniciar Dureza (Brinell)")
        elif self.rb_indentacion.isChecked():
            self.aprox_mat_btn.setEnabled(True)
            self.param_stack.setCurrentIndex(1)
            self.start_indent_btn.setText("Iniciar Indentación")
        else:
            self.aprox_mat_btn.setEnabled(True)
            self.param_stack.setCurrentIndex(0)

    def _procedimiento_actual(self) -> str:
        if self.rb_dureza.isChecked():
            return "DUREZA"
        if self.rb_indentacion.isChecked():
            return "INDENTACIÓN COMPLETA"
        return ""

    # ------------------------------------------------------------------
    # Indentación automática / control de motor
    # ------------------------------------------------------------------
    def _start_auto_indentation(self) -> None:
        modo = self._procedimiento_actual()

        if modo == "":
            QMessageBox.warning(self, "Atención", "Seleccioná un procedimiento: DUREZA o INDENTACIÓN COMPLETA.")
            return
        if not self._connected or self._worker is None:
            QMessageBox.critical(self, "Error", "No hay conexión serial activa.")
            return

        if modo == "INDENTACIÓN COMPLETA":
            if self._worker.send_command(config.CMD_START_AUTO_INDENT):
                self.start_indent_btn.setEnabled(False)
                self.stop_indent_btn.setEnabled(True)
                self.indent_status_label.setText("Indentando.................................")
                self.indent_status_label.setStyleSheet("color: orange; font-weight: bold;")
                log.info("Indentación ISO iniciada")
            else:
                QMessageBox.critical(self, "Error", "No se pudo enviar el comando de inicio de indentación")

        elif modo == "DUREZA":
            try:
                carga = float(self.brinell_carga_combo.currentText())
                tiempo = float(self.brinell_tiempo_combo.currentText())
            except ValueError:
                QMessageBox.critical(self, "Error", "Ingresá valores numéricos válidos para Brinell.")
                return

            comando = f"K;{int(carga)};{int(tiempo)}\n".encode("utf-8")
            if self._worker.send_command(comando):
                self.start_indent_btn.setEnabled(False)
                self.stop_indent_btn.setEnabled(True)
                self.indent_status_label.setText("Realizando prueba de dureza...")
                self.indent_status_label.setStyleSheet("color: orange; font-weight: bold;")
                log.info(f"Prueba de dureza iniciada con carga {carga}N y tiempo de espera {tiempo}s")
            else:
                QMessageBox.critical(self, "Error", "No se pudo enviar el comando de prueba de dureza")

    def _stop_auto_indentation(self) -> None:
        modo = self._procedimiento_actual()

        if self._worker is not None:
            if modo == "INDENTACIÓN COMPLETA":
                if not self._worker.send_command(config.CMD_MOTOR_STOP):
                    QMessageBox.critical(self, "Error", "No se pudo enviar el comando de parada de indentación")
            elif modo == "DUREZA":
                if not self._worker.send_command(config.CMD_MOTOR_STOP_ALT):
                    QMessageBox.critical(self, "Error", "No se pudo enviar el comando de parada de prueba de dureza")

        self._auto_indent_active = False
        self.stop_indent_btn.setEnabled(False)
        self.start_indent_btn.setEnabled(True)
        self.indent_status_label.setText("PROCEDIMIENTO DETENIDO")
        self.indent_status_label.setStyleSheet("color: red; font-weight: bold;")

    def _aprox_material(self) -> None:
        if self._worker is not None and not self._worker.send_command(config.CMD_APROX_MATERIAL):
            QMessageBox.critical(self, "Error", "No se pudo enviar el comando de Aproximar Material")

        self._auto_indent_active = False
        self.stop_indent_btn.setEnabled(False)
        self.start_indent_btn.setEnabled(True)
        self.indent_status_label.setText("MATERIAL APROXIMANDO")
        self.indent_status_label.setStyleSheet("color: red; font-weight: bold;")

    def _subir_motor(self) -> None:
        if self._worker is not None and not self._worker.send_command(config.CMD_MOTOR_SUBIR):
            QMessageBox.critical(self, "Error", "No se pudo enviar el comando de subir cabezal")

        self._auto_indent_active = False
        self.stop_indent_btn.setEnabled(False)
        self.start_indent_btn.setEnabled(False)
        self.indent_status_label.setText("CABEZAL SUBIENDO A 200 PPS")
        self.indent_status_label.setStyleSheet("color: blue; font-weight: bold;")

    def _bajar_motor(self) -> None:
        if self._worker is not None and not self._worker.send_command(config.CMD_MOTOR_BAJAR):
            QMessageBox.critical(self, "Error", "No se pudo enviar el comando de bajar cabezal")

        self._auto_indent_active = False
        self.stop_indent_btn.setEnabled(False)
        self.start_indent_btn.setEnabled(False)
        self.indent_status_label.setText("CABEZAL BAJANDO A 200 PPS")
        self.indent_status_label.setStyleSheet("color: blue; font-weight: bold;")

    def _parar_motor(self) -> None:
        if self._worker is not None and not self._worker.send_command(config.CMD_MOTOR_PARAR):
            QMessageBox.critical(self, "Error", "No se pudo enviar el comando de parar cabezal")

        self._auto_indent_active = False
        self.stop_indent_btn.setEnabled(False)
        self.start_indent_btn.setEnabled(False)
        self.indent_status_label.setText("CABEZAL PARADO")
        self.indent_status_label.setStyleSheet("color: blue; font-weight: bold;")

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------
    def shutdown(self) -> None:
        """Detiene el hilo de lectura serie de forma prolija. Debe
        llamarse desde ``MainWindow.closeEvent``."""
        self._flush_timer.stop()
        self._flush_pending_points()
        if self._worker is not None:
            self._worker.stop()
            self._worker = None