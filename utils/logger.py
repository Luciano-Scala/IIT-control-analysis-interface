"""
utils/logger.py
=================
Configuración de logging, traducida de ``DataLoggerApp._setup_logger``
del monolito original (líneas ~207-230).

Diferencias respecto al original:
- No vive como método de la ventana principal: es una función de
  módulo (``get_logger``) que cualquier capa (``core/``, ``ui/``,
  ``main.py``) puede importar sin acoplarse a Tkinter/Qt.
- Idempotente: puede llamarse varias veces (p.ej. desde distintos
  módulos) sin duplicar handlers, gracias al chequeo de
  ``logger.handlers`` y a que ``logging.getLogger(name)`` siempre
  devuelve la misma instancia para un mismo nombre.
"""

from __future__ import annotations

import logging
import logging.handlers
import os

from config import (
    APP_NAME,
    LOG_BACKUP_COUNT,
    LOG_CONSOLE_LEVEL,
    LOG_FILE_LEVEL,
    LOG_FILE_NAME,
    LOG_MAX_BYTES,
)

# Raíz del proyecto (un nivel arriba de utils/)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_logger(name: str = APP_NAME) -> logging.Logger:
    """Devuelve el logger de la aplicación, configurándolo la primera
    vez que se solicita.

    - Archivo rotativo (``iitcai.log``, hasta ``LOG_MAX_BYTES`` con
      ``LOG_BACKUP_COUNT`` backups): nivel ``DEBUG`` — registra todo.
    - Consola: nivel ``WARNING`` — silencia el ruido de debug, igual
      que el original.
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger  # ya configurado (evita duplicar handlers)

    logger.setLevel(logging.DEBUG)

    log_path = os.path.join(_PROJECT_ROOT, LOG_FILE_NAME)
    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setLevel(getattr(logging, LOG_FILE_LEVEL))
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, LOG_CONSOLE_LEVEL))
    console_handler.setFormatter(logging.Formatter("%(levelname)s  %(message)s"))

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger