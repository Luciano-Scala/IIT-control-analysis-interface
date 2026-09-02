"""
core/processing/brinell.py
============================
Cálculo de dureza Brinell a partir de los diámetros de la impronta.
Traducción pura de la fórmula usada en ``calcular_dureza``, separada de cualquier diálogo/UI.

    HB = 2F / (πD(D − √(D² − d²)))

con F en kgf y D, d en mm.
"""

from __future__ import annotations

import numpy as np


def calcular_dureza_brinell(diametros_mm, carga_N: float, radio_indentador_m: float) -> np.ndarray:
    """Calcula la dureza Brinell para uno o más diámetros de impronta.

    Parameters
    ----------
    diametros_mm : array-like
        Diámetro(s) de la impronta, en mm (típicamente 3 mediciones).
    carga_N : float
        Carga máxima aplicada durante el ensayo, en Newtons.
    radio_indentador_m : float
        Radio del indentador esférico, en metros (ver ``config.DEFAULT_R``).

    Returns
    -------
    np.ndarray
        Dureza Brinell calculada para cada diámetro provisto.
    """
    d = np.asarray(diametros_mm, dtype=float)
    F = carga_N * 0.102          # N -> kgf
    D = radio_indentador_m * 2000  # radio (m) -> diámetro del indentador (mm)

    return 2 * F / (np.pi * D * (D - np.sqrt(D**2 - d**2)))