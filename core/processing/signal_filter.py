"""
core/processing/signal_filter.py
==================================
Filtrado de la señal cruda de LVDT: elimina outliers (saltos de
velocidad irreales), realinea tramos discontinuos y normaliza el cero.

Traducción 1:1 del método original ``Filtrado_señal`` pero:
- Sin ``self`` ni atributos de instancia: recibe todo por parámetro.
- Sin llamadas a la UI (``self.update_analysis_plot``): el resultado se
  devuelve en un dataclass y quien llama decide qué graficar.
- Sin ``self.cancel_flag``: se reemplaza por un callback opcional
  ``cancel_check()`` que, si devuelve True, aborta el procesamiento.
  Esto permite que el ``QThread`` de análisis lo cancele de forma
  cooperativa sin acoplar este módulo a Qt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
from scipy.ndimage import gaussian_filter1d

from config import (
    FILTER_GAUSSIAN_SIGMA,
    FILTER_JUMP_THRESHOLD,
    FILTER_NORM_SAMPLE_POINTS,
    FILTER_OUTLIER_GRADIENT_MAX,
)


@dataclass
class FilteredSignal:
    """Resultado del filtrado: vectores ya sincronizados y del mismo
    largo (tras aplicar la máscara de outliers).
    """

    tiempo: np.ndarray
    lvdt_ajustado: np.ndarray          # antes "h_ajustado"
    carga: np.ndarray                  # antes "L_f"
    estado: np.ndarray                 # antes "e_f"
    desplazamiento_ref: np.ndarray     # antes "desplz[mask]" (para segmentación por pendiente)
    err_lvdt: np.ndarray
    correcciones_aplicadas: int
    puntos_originales: int
    puntos_validos: int


def filtrar_senal(
    tiempo,
    desplazamiento_lvdt,
    desplazamiento_ref,
    carga,
    estado,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Optional[FilteredSignal]:
    """Filtra la señal de LVDT.

    Parameters
    ----------
    tiempo, desplazamiento_lvdt, carga, estado : array-like
        Columnas crudas leídas del CSV.
    desplazamiento_ref : array-like
        Columna "Desplazamiento" (motor/referencia), usada como
        respaldo para la segmentación por pendiente.
    cancel_check : callable, opcional
        Si se provee y devuelve True durante el bucle de realineación,
        el procesamiento se aborta devolviendo ``None`` (equivalente al
        antiguo ``if self.cancel_flag: return``).

    Returns
    -------
    FilteredSignal | None
        ``None`` si el proceso fue cancelado.
    """
    t = np.asarray(tiempo, dtype=float)
    h = np.asarray(desplazamiento_lvdt, dtype=float)
    c = np.asarray(carga, dtype=float)
    e = np.asarray(estado)
    d_ref = np.asarray(desplazamiento_ref)

    # Paso 1: outliers por gradiente de velocidad irreal sobre la señal suavizada
    deltas = np.gradient(gaussian_filter1d(h, sigma=FILTER_GAUSSIAN_SIGMA), t)
    mask = np.abs(deltas) <= FILTER_OUTLIER_GRADIENT_MAX

    t_f = t[mask]
    h_f = h[mask]
    L_f = c[mask]
    e_f = e[mask]
    d_ref_f = d_ref[mask]

    # Paso 2: tramos continuos (huecos en los índices originales)
    indices_originales = np.where(mask)[0]
    cortes = np.where(np.diff(indices_originales) > 1)[0] + 1
    cortes = np.concatenate(([0], cortes, [len(h_f)]))

    # Paso 3: realineación de tramos (solape preventivo)
    h_ajustado = h_f.copy()
    correcciones = 0
    for i in range(1, len(cortes) - 1):
        if cancel_check is not None and cancel_check():
            return None

        idx_fin_previo = cortes[i] - 1
        idx_inicio_nuevo = cortes[i]
        delta = h_ajustado[idx_fin_previo] - h_ajustado[idx_inicio_nuevo]

        if np.abs(delta) > FILTER_JUMP_THRESHOLD:
            h_ajustado[idx_inicio_nuevo:] += delta
            correcciones += 1

    # Paso 4: normalización del cero (ajuste lineal sobre los primeros puntos)
    try:
        _, b = np.polyfit(
            L_f[:FILTER_NORM_SAMPLE_POINTS], h_ajustado[:FILTER_NORM_SAMPLE_POINTS], 1
        )
        h_ajustado = h_ajustado - b
    except Exception:
        h_ajustado = h_ajustado - np.min(h_ajustado)

    err_h = np.full_like(h_ajustado, 0.001)

    return FilteredSignal(
        tiempo=t_f,
        lvdt_ajustado=h_ajustado,
        carga=L_f,
        estado=e_f,
        desplazamiento_ref=d_ref_f,
        err_lvdt=err_h,
        correcciones_aplicadas=correcciones,
        puntos_originales=len(h),
        puntos_validos=int(np.sum(mask)),
    )