"""
core/hardware/serial_worker.py
===============================
Reemplazo del par ``threading.Thread`` + ``queue.Queue`` del código original
(:func:`process_serial_data` + ``self.data_queue`` + ``root.after(200, ...)``)
por un ``QThread`` que emite ``Signal`` de Qt.

Ventajas frente al original:
- No hace falta un polling periódico (``root.after``) del lado de la UI:
  Qt encola automáticamente las señales cuando el receptor vive en otro
  hilo (conexión ``QueuedConnection`` implícita), por lo que cada slot
  conectado a ``data_point_received`` se ejecuta en el hilo principal
  de forma segura y ordenada.
- El acceso concurrente al objeto ``serial.Serial`` (lecturas continuas
  desde este hilo + escrituras de comandos desde la UI) se protege con
  un ``QMutex`` en vez de confiar en el GIL implícitamente.

Este módulo NO importa nada de ``ui/`` ni de Tkinter/PySide widgets:
solo expone señales con datos (dataclasses / tipos simples) y depende
únicamente de ``pyserial`` y Qt Core.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import serial
import serial.tools.list_ports
from PySide6.QtCore import QThread, QMutex, QMutexLocker, Signal

from config import (
    CSV_DATA_PREFIX,
    CSV_HEADER_PREFIX,
    CSV_MIN_FIELDS,
    SERIAL_BAUDRATE,
    SERIAL_POLL_INTERVAL_S,
    SERIAL_TIMEOUT_S,
)


@dataclass
class IndentationDataPoint:
    """Una fila de datos ya parseada, equivalente a lo que el original
    desempaquetaba manualmente dentro de ``update_ui`` a partir de
    ``line[9:].split(',')``.
    """

    time_ms: int
    motor_pos: int
    load: float                 # CargaF (N)
    displacement: float         # Desplazamiento (mm)
    estado: str                 # EstadoIndentacion, p.ej. "J1C", "NI"
    lvdt: float                 # Desplazamiento LVDT
    raw_fields: List[str]       # fila cruda (para volcar a CSV tal cual el original)


class SerialWorker(QThread):
    """Hilo dedicado a la lectura continua del puerto serie.

    Señales
    -------
    data_point_received(IndentationDataPoint)
        Emitida por cada línea "CSV_DATA:" válida y parseada.
    raw_line_received(str)
        Emitida para cualquier otra línea (equivalente al
        ``self.log.debug(f"Serial msg: {line}")`` del original).
    parse_error(str)
        Emitida cuando una línea CSV_DATA no pudo convertirse a números.
    connection_error(str)
        Emitida si falla la apertura del puerto o se pierde la conexión.
    connection_state_changed(bool)
        True al abrir el puerto correctamente, False al cerrarlo/perderlo.
    """

    data_point_received = Signal(object)      # IndentationDataPoint
    raw_line_received = Signal(str)
    parse_error = Signal(str)
    connection_error = Signal(str)
    connection_state_changed = Signal(bool)

    def __init__(
        self,
        port: str,
        baudrate: int = SERIAL_BAUDRATE,
        timeout: float = SERIAL_TIMEOUT_S,
        parent=None,
    ):
        super().__init__(parent)
        self._port_name = port
        self._baudrate = baudrate
        self._timeout = timeout

        self._serial: Optional[serial.Serial] = None
        self._running = False
        self._mutex = QMutex()  # protege el acceso a self._serial (lectura/escritura)

    # ------------------------------------------------------------------
    # Ciclo de vida del hilo
    # ------------------------------------------------------------------
    def run(self) -> None:
        """Cuerpo del hilo: abre el puerto y lee líneas hasta que se
        llame a :meth:`stop`. Sustituye al bucle ``while True`` con
        ``time.sleep(0.01)`` del ``process_serial_data`` original.
        """
        try:
            with QMutexLocker(self._mutex):
                self._serial = serial.Serial(
                    self._port_name, self._baudrate, timeout=self._timeout
                )
            self._running = True
            self.connection_state_changed.emit(True)
        except Exception as exc:  # noqa: BLE001 - queremos capturar cualquier error de apertura
            self.connection_error.emit(f"No se pudo conectar: {exc}")
            return

        while self._running:
            line = self._read_line_safe()
            if line:
                self._handle_line(line)
            else:
                self.msleep(int(SERIAL_POLL_INTERVAL_S * 1000))

        self._close_port()
        self.connection_state_changed.emit(False)

    def stop(self) -> None:
        """Solicita la detención del hilo y espera a que termine.
        Reemplaza a ``self.serial_connected = False`` + cierre manual.
        """
        self._running = False
        self.wait(2000)

    # ------------------------------------------------------------------
    # Lectura / parseo
    # ------------------------------------------------------------------
    def _read_line_safe(self) -> str:
        with QMutexLocker(self._mutex):
            ser = self._serial
        if ser is None:
            return ""
        try:
            raw = ser.readline().decode("utf-8", errors="replace").strip()
        except Exception:
            return ""
        return raw

    def _handle_line(self, line: str) -> None:
        if line.startswith(CSV_HEADER_PREFIX):
            return  # el firmware solo lo informa, no se procesa (igual que el original)

        if line.startswith(CSV_DATA_PREFIX):
            point = self._parse_csv_data_line(line)
            if point is not None:
                self.data_point_received.emit(point)
            return

        self.raw_line_received.emit(line)

    def _parse_csv_data_line(self, line: str) -> Optional[IndentationDataPoint]:
        """Parsea una línea ``CSV_DATA:...``.

        Réplica de la lógica original en ``update_ui``:
            data = line[9:].split(',')
            time_ms, motor_pos, load, displacement, estado, lvdt = data[0..5]

        Nota: el código original validaba ``len(data) >= 4`` pero luego
        accedía a ``data[5]``; aquí se corrige exigiendo el mínimo real
        de columnas (``CSV_MIN_FIELDS = 6``) para evitar IndexError.
        """
        fields = line[len(CSV_DATA_PREFIX):].split(",")
        if len(fields) < CSV_MIN_FIELDS:
            self.parse_error.emit(f"Fila con columnas insuficientes: {line!r}")
            return None
        try:
            return IndentationDataPoint(
                time_ms=int(fields[0]),
                motor_pos=int(fields[1]),
                load=float(fields[2]),
                displacement=float(fields[3]),
                estado=fields[4],
                lvdt=float(fields[5]),
                raw_fields=fields,
            )
        except ValueError as exc:
            self.parse_error.emit(f"Error procesando datos: {exc}")
            return None

    def _close_port(self) -> None:
        with QMutexLocker(self._mutex):
            if self._serial is not None:
                try:
                    self._serial.close()
                except Exception:
                    pass
                self._serial = None

    # ------------------------------------------------------------------
    # Escritura de comandos (llamable de forma segura desde el hilo de UI)
    # ------------------------------------------------------------------
    def send_command(self, data: bytes) -> bool:
        """Envía un comando al controlador. Protegido por mutex porque
        se invoca desde el hilo principal mientras ``run()`` lee en
        paralelo desde este hilo.
        """
        with QMutexLocker(self._mutex):
            if self._serial is None:
                return False
            try:
                self._serial.write(data)
                return True
            except Exception as exc:  # noqa: BLE001
                self.connection_error.emit(f"Error al enviar comando: {exc}")
                return False


def list_serial_ports() -> List[str]:
    """Equivalente puro de ``get_serial_ports``: no toca la UI."""
    return [p.device for p in serial.tools.list_ports.comports()]