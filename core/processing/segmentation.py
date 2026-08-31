"""
core/processing/segmentation.py
=================================
Segmentación de la señal ya filtrada en tramos de "carga" / "espera" /
"descarga", detección del patrón válido de ciclo y extracción de
(h_max, L, S) por indentación.

Traducción de los métodos originales:
    segmentar_por_estado      (líneas ~1176-1204)
    segmentar_por_pendiente   (líneas ~1206-1257)
    detectar_patrones         (líneas ~1259-1272)
    obtencion_datos           (líneas ~1274-1381)

Cambios respecto al original:
- Todo son funciones puras: reciben arrays y devuelven dataclasses,
  no hay ``self.Datos`` ni llamadas a ``self.update_analysis_table``.
- ``segmentar_por_pendiente`` ya no depende de un ``self`` intermedio.
- ``obtener_datos_ciclos`` (antes ``obtencion_datos``) recibe R, E_i, E
  y sus errores como parámetros en vez de fijarlos dentro del propio
  método de UI que arma ``self.Datos``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Sequence

import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.optimize import curve_fit

from config import (
    DEFAULT_E,
    DEFAULT_E_I,
    DEFAULT_R,
    PATRON_CON_ESTADO,
    PATRON_SIN_ESTADO,
    SEGMENTATION_DEFAULT_ERR_LVDT,
    SEGMENTATION_SLOPE_SIGMA,
)
from core.processing.signal_filter import FilteredSignal


@dataclass
class Segmento:
    """Un tramo homogéneo de la señal (todo 'carga', todo 'espera' o
    todo 'descarga')."""

    tipo: str
    t: np.ndarray
    L: np.ndarray
    h: np.ndarray
    err_h: np.ndarray


@dataclass
class DatosIndentacion:
    """Resultado agregado de todos los ciclos válidos detectados en el
    ensayo. Reemplaza al antiguo ``self.Datos``."""

    h_max: np.ndarray
    L: np.ndarray
    S: np.ndarray
    err_h: np.ndarray
    err_L: np.ndarray
    err_S: np.ndarray
    R: float = DEFAULT_R
    E_i: float = DEFAULT_E_I
    E: float = DEFAULT_E

    def n_ciclos(self) -> int:
        return len(self.L)


def segmentar_por_estado(
    tiempo, carga, lvdt, estado, err_lvdt=SEGMENTATION_DEFAULT_ERR_LVDT
) -> List[Segmento]:
    """Segmentación basada en la columna EstadoIndentacion (último
    carácter: 'C'/'D'/'E')."""
    tipo_cod = np.array([str(e)[-1] for e in estado])
    etiquetas = np.full_like(tipo_cod, "", dtype=object)

    etiquetas[tipo_cod == "C"] = "carga"
    etiquetas[tipo_cod == "D"] = "descarga"
    etiquetas[tipo_cod == "E"] = "espera"

    if np.isscalar(err_lvdt):
        err_lvdt = np.full(len(etiquetas), err_lvdt)

    segmentos: List[Segmento] = []
    i = 0
    while i < len(etiquetas):
        if etiquetas[i] == "":
            i += 1
            continue
        curr_tipo, j = etiquetas[i], i
        while j < len(etiquetas) and etiquetas[j] == curr_tipo:
            j += 1

        segmentos.append(
            Segmento(
                tipo=curr_tipo,
                t=tiempo[i:j],
                L=carga[i:j],
                h=lvdt[i:j],
                err_h=err_lvdt[i:j],
            )
        )
        i = j
    return segmentos


def segmentar_por_pendiente(
    tiempo,
    carga,
    desplazamiento_ref,
    desplazamiento,
    err_lvdt=SEGMENTATION_DEFAULT_ERR_LVDT,
    sigma_suavizado=SEGMENTATION_SLOPE_SIGMA,
) -> List[Segmento]:
    """Segmentación por derivada numérica (respaldo cuando no hay
    columna de estado confiable)."""
    carga_suave = gaussian_filter1d(carga, sigma=sigma_suavizado)
    desplz_suave = gaussian_filter1d(desplazamiento_ref, sigma=sigma_suavizado)

    ddesplz = np.gradient(desplz_suave, tiempo)

    ddesplzpos = ddesplz[ddesplz > 0]
    ddesplzneg = ddesplz[ddesplz < 0]

    if len(ddesplzpos) == 0 or len(ddesplzneg) == 0:
        return []

    epsilon_cte = 0.2 * min(np.mean(ddesplzpos), abs(np.mean(ddesplzneg)))
    epsilon_pendiente = 0.925 * abs(min(np.mean(ddesplzpos), abs(np.mean(ddesplzneg))))

    etiquetas = np.full_like(ddesplz, "", dtype=object)
    etiquetas[np.abs(ddesplz) < epsilon_cte] = "espera"
    etiquetas[ddesplz >= epsilon_pendiente] = "carga"
    etiquetas[ddesplz <= -epsilon_pendiente] = "descarga"

    if np.isscalar(err_lvdt):
        err_lvdt = np.full(len(etiquetas), err_lvdt)

    segmentos: List[Segmento] = []
    i = 0
    while i < len(etiquetas):
        if etiquetas[i] == "":
            i += 1
            continue
        tipo = etiquetas[i]
        j = i
        while j < len(etiquetas) and etiquetas[j] == tipo:
            j += 1

        segmentos.append(
            Segmento(
                tipo=tipo,
                t=tiempo[i:j],
                L=carga[i:j],
                h=desplazamiento[i:j],
                err_h=err_lvdt[i:j],
            )
        )
        i = j

    # Corrección del primer contacto: se usa el primer tramo de carga
    # para estimar el desplazamiento cero y se resta a TODOS los tramos.
    for seg in segmentos:
        if seg.tipo == "carga" and len(seg.L) > 2:
            coef = np.polyfit(seg.L, seg.h, 1)
            desplazamiento_cero = coef[1]
            for s in segmentos:
                s.h = s.h - desplazamiento_cero
            break

    return segmentos


def detectar_patrones(
    segmentos: Sequence[Segmento], patron: Sequence[str] = PATRON_SIN_ESTADO
) -> List[List[Segmento]]:
    """Devuelve todas las subsecuencias de ``segmentos`` cuyo tipo
    coincide exactamente con ``patron``."""
    n = len(patron)
    secuencias_validas: List[List[Segmento]] = []

    for i in range(len(segmentos) - n + 1):
        tipos_en_ventana = [segmentos[i + j].tipo for j in range(n)]
        if tipos_en_ventana == list(patron):
            secuencias_validas.append([segmentos[i + j] for j in range(n)])

    return secuencias_validas


def _power_law(h, A, hf, m):
    return A * np.maximum((h - hf), 1e-9) ** m


def _lin(x, a, b):
    return a * x + b


def obtener_datos_ciclos(
    patrones_validos: Sequence[Sequence[Segmento]],
    R: float = DEFAULT_R,
    E_i: float = DEFAULT_E_I,
    E: float = DEFAULT_E,
) -> DatosIndentacion:
    """Extrae (h_max, L_max, S) de cada ciclo válido.

    Traducción directa de ``obtencion_datos``: por cada secuencia de
    segmentos que matchea el patrón, toma L_max/h_max de la última
    "espera" y ajusta la ley de potencia de Oliver-Pharr sobre el tramo
    de "descarga" para obtener la rigidez S = dL/dh en h_max (con
    fallback a un ajuste lineal si el ajuste no lineal no converge).
    """
    res = {"h_max": [], "L": [], "S": [], "err_h": [], "err_L": [], "err_S": []}

    for secuencia in patrones_validos:
        esperas = [s for s in secuencia if s.tipo == "espera"]
        if not esperas:
            continue

        ult_espera = esperas[-1]
        idx_Lmin = -1

        L_max_val = ult_espera.L[idx_Lmin]
        h_max_val = ult_espera.h[idx_Lmin]
        err_h_val = ult_espera.err_h[idx_Lmin]

        descarga = next((s for s in secuencia if s.tipo == "descarga"), None)
        if descarga is None:
            continue

        L_s = descarga.L
        h_s = descarga.h

        try:
            p0_op = [L_max_val / (h_max_val * 0.2) ** 1.5, 0.8 * h_max_val, 1.5]
            bnds_op = ([0.001, 0, 1.0], [np.inf, h_max_val * 0.99, 4.0])

            popt_op, cov_op = curve_fit(
                _power_law, h_s, L_s, p0=p0_op, bounds=bnds_op, maxfev=100000
            )
            A_op, hf_op, m_op = popt_op

            S_val = A_op * m_op * (h_max_val - hf_op) ** (m_op - 1)
            grad_S = np.array(
                [
                    m_op * (h_max_val - hf_op) ** (m_op - 1),
                    -A_op * m_op * (m_op - 1) * (h_max_val - hf_op) ** (m_op - 2),
                    A_op
                    * (h_max_val - hf_op) ** (m_op - 1)
                    * (1 + m_op * np.log(h_max_val - hf_op)),
                ]
            )
            err_S_val = np.sqrt(np.dot(grad_S.T, np.dot(cov_op, grad_S)))

        except Exception:
            try:
                popt_lin, pcov_lin = curve_fit(_lin, h_s, L_s)
                S_val = popt_lin[0]
                err_S_val = np.sqrt(pcov_lin[0, 0])
            except Exception:
                S_val, err_S_val = np.nan, np.nan

        res["L"].append(L_max_val)
        res["h_max"].append(h_max_val / 1000)
        res["S"].append(S_val * 1000)  # N/um -> N/mm
        res["err_S"].append(err_S_val * 1000)
        res["err_h"].append(err_h_val / 1000)
        res["err_L"].append(L_max_val * 0.003 + 1)

    return DatosIndentacion(
        h_max=np.array(res["h_max"]),
        L=np.array(res["L"]),
        S=np.array(res["S"]),
        err_h=np.array(res["err_h"]),
        err_L=np.array(res["err_L"]),
        err_S=np.array(res["err_S"]),
        R=R,
        E_i=E_i,
        E=E,
    )


def procesar_senal_filtrada(filtered: FilteredSignal) -> DatosIndentacion:
    """Orquesta segmentación completa a partir de una señal ya filtrada
    (ver ``core.processing.signal_filter.filtrar_senal``).

    Réplica el flujo de decisión del ``Filtrado_señal`` original:
    intenta primero segmentar por Estado; si no hay segmentos, cae a
    segmentación por pendiente como respaldo.
    """
    segmentos = segmentar_por_estado(
        filtered.tiempo, filtered.carga, filtered.lvdt_ajustado, filtered.estado,
        filtered.err_lvdt,
    )

    if segmentos:
        patrones = detectar_patrones(segmentos, PATRON_CON_ESTADO)
    else:
        segmentos = segmentar_por_pendiente(
            filtered.tiempo,
            filtered.carga,
            filtered.desplazamiento_ref,
            filtered.lvdt_ajustado,
            filtered.err_lvdt,
        )
        patrones = detectar_patrones(segmentos, PATRON_SIN_ESTADO)

    return obtener_datos_ciclos(patrones)