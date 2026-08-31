"""
config.py
=========
Centraliza valores que en el monolito original estaban dispersos como
"números mágicos" dentro de los métodos (umbrales de filtrado, parámetros
de calibración, baudrate serie, etc.). Cualquier ajuste de calibración o
comportamiento debería hacerse aquí, no dentro de core/ o ui/.
"""

from __future__ import annotations

# ──────────────────────────────────────────────────────────────────────
# Metadatos de la aplicación
# ──────────────────────────────────────────────────────────────────────
APP_NAME = "IITCAI"
APP_TITLE = "Sistema de Adquisición de Datos IITCAI - Indentador Portátil - V 1.0"
APP_ORG = "SCALA LUCIANO"

# ──────────────────────────────────────────────────────────────────────
# Comunicación serie
# ──────────────────────────────────────────────────────────────────────
SERIAL_BAUDRATE = 115200
SERIAL_TIMEOUT_S = 1.0          # timeout de lectura de pyserial
SERIAL_POLL_INTERVAL_S = 0.01   # tiempo de espera entre lecturas cuando no hay datos

# Comandos enviados al Arduino/controlador (idénticos al firmware original)
CMD_START_RECORDING = b"G\n"
CMD_STOP_RECORDING = b"F\n"
CMD_START_AUTO_INDENT = b"I\n"
CMD_MOTOR_STOP = b"N\n"
CMD_MOTOR_STOP_ALT = b"X\n"
CMD_APROX_MATERIAL = b"W\n"
CMD_MOTOR_SUBIR = b"U200\n"
CMD_MOTOR_BAJAR = b"B200\n"
CMD_MOTOR_PARAR = b"H\n"

# Columnas esperadas en una línea "CSV_DATA:" recibida por el puerto serie
# Tiempo(ms), MotorPosicion, CargaF(N), Desplazamiento(mm), EstadoIndentacion, Desplazamiento LVDT
CSV_DATA_PREFIX = "CSV_DATA:"
CSV_HEADER_PREFIX = "CSV_HEADER:"
CSV_MIN_FIELDS = 6

# ──────────────────────────────────────────────────────────────────────
# Filtrado de señal (core/processing/signal_filter.py)
# ──────────────────────────────────────────────────────────────────────
FILTER_GAUSSIAN_SIGMA = 10          # suavizado previo a detectar outliers por gradiente
FILTER_OUTLIER_GRADIENT_MAX = 5e-6  # |dh/dt| máximo aceptado como válido
FILTER_JUMP_THRESHOLD = 1e-6        # salto mínimo (mm) para considerar corrección de tramo
FILTER_NORM_SAMPLE_POINTS = 500     # cantidad de puntos usados para el ajuste lineal de normalización

# ──────────────────────────────────────────────────────────────────────
# Lectura de CSV grabado (ui/tabs/analysis_tab.py)
# ──────────────────────────────────────────────────────────────────────
# Estructura fija del encabezado escrito por AcquisitionTab._start_recording:
#   línea 1: "Datos de Cliente"
#   líneas 2-5: Fecha / Cliente / Solicitud / Muestra
#   línea 6: encabezado de columnas
#   línea 7+: datos
CSV_CLIENT_INFO_LINES = 4
ESTADO_NO_INICIADO = "NI"  # filas con este estado se descartan del análisis

# ──────────────────────────────────────────────────────────────────────
# Segmentación (core/processing/segmentation.py)
# ──────────────────────────────────────────────────────────────────────
SEGMENTATION_DEFAULT_ERR_LVDT = 0.001
SEGMENTATION_SLOPE_SIGMA = 25       # sigma del suavizado gaussiano para el método por pendiente
PATRON_CON_ESTADO = ["carga", "espera", "descarga"]
PATRON_SIN_ESTADO = ["espera", "carga", "espera", "descarga"]

# ──────────────────────────────────────────────────────────────────────
# Compliance del instrumento (calibración de máquina)
# ──────────────────────────────────────────────────────────────────────
COMPLIANCE_CF = 0 #0.014824e-3 / 2      # um/N
COMPLIANCE_ERR_CF = 0.005817e-3 / 2  # um/N

# ──────────────────────────────────────────────────────────────────────
# Parámetros por defecto del ensayo de indentación (Oliver-Pharr / Haggag)
# ──────────────────────────────────────────────────────────────────────
DEFAULT_R = 0.0015875 / 2   # radio del indentador (m)
DEFAULT_E_I = 550e9         # módulo elástico del indentador (Pa)
DEFAULT_E = 200e9           # módulo elástico del material (Pa)
DEFAULT_ERR_R = 4e-7
# NOTA: el original (método ``recalcular``) usaba el literal 20 (en Pa)
# como error de E_i y E en vez de una incertidumbre relativa real. Se
# preserva tal cual para no alterar los resultados numéricos existentes.
DEFAULT_ERR_E_I = 20.0
DEFAULT_ERR_E = 20.0
DEFAULT_ALPHA_M = 1

# Coeficiente Beta_m según norma Haggag, por tipo de material.
# Reemplaza al antiguo self.acero_var.get() acoplado a la UI de Tkinter.
MATERIAL_BETA_M = {
    "Al carbono (Predet.)": 0.2285,
    "Inoxidable": 0.236,
}
DEFAULT_MATERIAL = "Al carbono (Predet.)"

# ──────────────────────────────────────────────────────────────────────
# UI de adquisición (ui/tabs/acquisition_tab.py)
# ──────────────────────────────────────────────────────────────────────
# Cadencia de refresco de gráfico/labels/CSV. El SerialWorker emite una
# señal por CADA dato leído (a diferencia del original, que encolaba en
# self.data_queue); para no saturar el loop de eventos de Qt con un
# redibujado de Matplotlib por cada punto, un QTimer con este intervalo
# vacía el buffer acumulado en un solo lote (mismo criterio de fondo que
# el antiguo root.after(200, self.update_ui)).
ACQUISITION_UI_REFRESH_MS = 150
DEFAULT_RECORD_INTERVAL_MS = 100
DEFAULT_CSV_FILENAME = "datos.csv"

# ──────────────────────────────────────────────────────────────────────
# Logging (utils/logger.py)
# ──────────────────────────────────────────────────────────────────────
LOG_FILE_NAME = "iitcai.log"
LOG_MAX_BYTES = 2 * 1024 * 1024
LOG_BACKUP_COUNT = 3
LOG_FILE_LEVEL = "DEBUG"
LOG_CONSOLE_LEVEL = "WARNING"