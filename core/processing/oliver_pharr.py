"""
core/processing/oliver_pharr.py
=================================
Modelo de indentación esférica (Oliver-Pharr / Haggag) y ajuste de la
curva de endurecimiento por deformación (Ludwig/Hollomon), con
propagación de errores.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import numpy as np
from scipy.optimize import curve_fit

from config import DEFAULT_ALPHA_M, MATERIAL_BETA_M


# ──────────────────────────────────────────────────────────────────────
# Compliance del instrumento
# ──────────────────────────────────────────────────────────────────────
def calculo_compliance(h, L, err_h, err_L, CF: float, err_CF: float) -> Tuple[np.ndarray, np.ndarray]:
    """Corrige el desplazamiento medido por la flexibilidad (compliance)
    propia de la máquina."""
    h_com = h - CF * L
    err_h_com = np.sqrt(err_h ** 2 + (L * err_CF) ** 2 + (CF * err_L) ** 2)
    return h_com, err_h_com


# ──────────────────────────────────────────────────────────────────────
# Método híbrido Newton-Raphson / bisección
# ──────────────────────────────────────────────────────────────────────
def newton_raphson_hibrido(F, dF, x_min, x_max, tol=1e-6, max_iter=1000, *args, **kwargs):
    """Encuentra raíces de F(x) combinando Newton-Raphson con control
    de bisección (evita divergencia fuera del intervalo [x_min, x_max]).
    Vectorizado: x_min/x_max pueden ser arrays (uno por punto de dato).
    """
    x = (x_min + x_max) / 2
    for _ in range(max_iter):
        x_newton = x - (F(x, *args, **kwargs) / dF(x, *args, **kwargs))

        x_newton = np.where((x_newton > x_min) & (x_newton < x_max), x_newton, (x_min + x_max) / 2)

        if np.all(np.abs(F(x, *args, **kwargs)) < tol):
            return x

        x_min = np.where(F(x, *args, **kwargs) > 0, x_min, x)
        x_max = np.where(F(x, *args, **kwargs) > 0, x, x_max)

        x = x_newton
    return x


def estimar_error_total_nr(F, dF, x, err=0, *args, **kwargs):
    """Propaga errores de los argumentos de F/dF hasta el resultado x
    del método híbrido, sumando en cuadratura el error de propagación
    con el error residual del método numérico.
    """
    all_params = list(args) + list(kwargs.values())
    try:
        err = np.asarray(err, dtype=float)
        if err.shape == () or err.ndim == 0:
            err = np.zeros(len(all_params))
    except Exception:
        err = np.zeros(len(all_params))

    eps = 1e-8

    def partial_deriv(f, params, idx, h=eps):
        p_plus = params.copy()
        p_plus[idx] += h
        f_plus = f(x, *p_plus)
        p_minus = params.copy()
        p_minus[idx] -= h
        f_minus = f(x, *p_minus)
        return (f_plus - f_minus) / (2 * h)

    dF_ddp = dF(x, *all_params)

    err_input = 0
    for i, _ in enumerate(all_params):
        err_input += (partial_deriv(F, all_params, i) * err[i] / dF_ddp) ** 2
    err_input = np.sqrt(err_input)

    error_metodo = np.abs(F(x, *args, **kwargs) / dF_ddp)

    return np.sqrt(err_input ** 2 + error_metodo ** 2)


# ──────────────────────────────────────────────────────────────────────
# Modelo Haggag (dp, epsilon_p, sigma_p)
# ──────────────────────────────────────────────────────────────────────
def calculo_parametros(parametros: dict, alpha_m: float = DEFAULT_ALPHA_M, tol: float = 1e-6, max_iter: int = 1000):
    """Calcula dp (diámetro de huella plástica), epsilon_p (deformación
    representativa) y sigma_p (tensión representativa) por punto de
    dato, junto con sus errores propagados.

    ``parametros`` debe contener las claves:
        h_max, err_h_max, L, err_L, S, err_S, R, err_R, E_i, err_E_i, E, err_E
    (arrays de igual longitud para las que varían por ciclo; escalares
    para R, E_i, E y sus errores).

    Returns
    -------
    dp, epsilon_p, sigma_p, err_dp, err_eps, err_sigma
    """
    h_max = parametros["h_max"]
    err_h_max = parametros["err_h_max"]
    L = parametros["L"]
    err_L = parametros["err_L"]
    S = parametros["S"]
    R = parametros["R"]
    err_R = parametros["err_R"]
    E_i = parametros["E_i"]
    err_E_i = parametros["err_E_i"]
    E = parametros["E"]
    err_E = parametros["err_E"]

    h_p = h_max - L / S
    err_hp = np.sqrt(
        (err_h_max) ** 2 + (err_L / S) ** 2 + (L / (S ** 2) * parametros["err_S"]) ** 2
    )

    def F_dp1(dp, h_p, L, R, E_i, E):
        C = 5.47 * L * (1 / E_i + 1 / E)
        A = C * R * (h_p ** 2 + (dp / 2) ** 2)
        B = h_p ** 2 + (dp / 2) ** 2 - 2 * h_p * R
        return (dp ** 3) * B - A

    def dF_dp1(dp, h_p, L, R, E_i, E):
        C = 5.47 * L * (1 / E_i + 1 / E)
        return -3 * (dp ** 2) * (2 * h_p * R - h_p ** 2) + (dp ** 4) * (5 / 4) - C * R * dp / 2

    def F_sigma1(sigma, dp, e_p, L, E, delta_min, delta_max):
        tau = (delta_max - delta_min) / np.log(27)
        return ((4 * L) / (np.pi * dp ** 2 * (delta_min + tau * np.log(e_p * E / (0.43 * sigma))))) - sigma

    def dF_sigma1(sigma, dp, e_p, L, E, delta_min, delta_max):
        tau = (delta_max - delta_min) / np.log(27)
        denominador = (delta_min + tau * np.log(e_p * E / (0.43 * sigma))) ** 2
        return (tau * 4 * L) / (np.pi * sigma * dp ** 2 * denominador) - 1

    dp_min = 2 * np.sqrt(2 * R * h_p - h_p ** 2)
    dp_max = 5 * np.sqrt(2 * R * h_p - h_p ** 2)

    dp = newton_raphson_hibrido(F_dp1, dF_dp1, dp_min, dp_max, R * 1e-30, max_iter, h_p, L, R, E_i, E)

    N = len(L)
    err_dp = estimar_error_total_nr(
        F_dp1, dF_dp1, dp,
        np.array(
            [
                err_hp,
                err_L,
                np.full(N, err_R),
                np.full(N, err_E_i),
                np.full(N, err_E),
            ]
        ),
        h_p, L, R, E_i, E,
    )

    # Relación de indentación plástica (Haggag)
    epsilon_p = 0.2 * dp / (2 * R)
    err_eps = epsilon_p * np.sqrt((err_dp / dp) ** 2 + (err_R / R) ** 2)

    delta_max = 2.87 * alpha_m
    delta_min = 1.12
    tau = (delta_max - delta_min) / np.log(27)

    s_dmin = 4 * L / (np.pi * delta_min * dp ** 2)
    s_dmax = 4 * L / (np.pi * delta_max * dp ** 2)
    s_min = epsilon_p * E / (0.43 * 27)
    sigma_p = 4 * L / (np.pi * 2 * dp ** 2)
    sigma_ans = sigma_p

    for _ in range(100):
        sigma_p = np.where(
            sigma_p > epsilon_p * E / 0.43,
            s_dmin,
            np.where(
                sigma_p < epsilon_p * E / (0.43 * 27),
                s_dmax,
                newton_raphson_hibrido(
                    F_sigma1, dF_sigma1, s_min, s_dmax, 1e-20, max_iter,
                    dp, epsilon_p, L, E, delta_min, delta_max,
                ),
            ),
        )
        if np.all(abs(sigma_ans - sigma_p) < sigma_p * tol):
            break
        sigma_ans = sigma_p

    err_sigma = np.empty_like(sigma_p)
    for i in range(len(sigma_p)):
        if sigma_p[i] > epsilon_p[i] * E / 0.43:
            err_sigma[i] = s_dmin[i] * np.sqrt((err_L[i] / L[i]) ** 2 + (2 * err_dp[i] / dp[i]) ** 2)
        elif sigma_p[i] < epsilon_p[i] * E / (0.43 * 27):
            err_sigma[i] = s_dmax[i] * np.sqrt((err_L[i] / L[i]) ** 2 + (2 * err_dp[i] / dp[i]) ** 2)
        else:
            err_s_i = np.array(
                [err_dp[i], err_eps[i], err_L[i], err_E, 0, 0]
            )
            err_sigma[i] = estimar_error_total_nr(
                F_sigma1, dF_sigma1, sigma_p[i], err_s_i,
                dp[i], epsilon_p[i], L[i], E, delta_min, delta_max,
            )

    return dp, epsilon_p, sigma_p, err_dp, err_eps, err_sigma


# ──────────────────────────────────────────────────────────────────────
# Tensión de fluencia (sigma_y) vía ajuste potencial
# ──────────────────────────────────────────────────────────────────────
def calc_sigma_y(h_max, R, L, err_h_max, err_R, err_L, beta_m: float) -> Tuple[float, float]:
    """Calcula la tensión de fluencia sigma_y ajustando y = a * x**b
    sobre los datos de la zona elástica, y la escala por el coeficiente
    Beta_m del material (antes tomado de ``self.acero_var.get()``, ver
    ``config.MATERIAL_BETA_M``)."""

    def dt(h_max, R):
        return 2 * np.sqrt(h_max * 2 * R - h_max ** 2)

    def errores(f, params, ERR):
        def partial_deriv(f, params, idx, h=1e-8):
            p_plus = params.copy()
            p_plus[idx] += h
            f_plus = f(*p_plus)
            p_minus = params.copy()
            p_minus[idx] -= h
            f_minus = f(*p_minus)
            return (f_plus - f_minus) / (2 * h)

        err = 0
        for i, _ in enumerate(params):
            err += (partial_deriv(f, params, i) * ERR[i]) ** 2
        return np.sqrt(err)

    def x_sigma(dt, R):
        return dt / (2 * R)

    def y_sigma(L, dt):
        return L / dt ** 2

    def pot(x, a, b):
        return a * (x ** b)

    d_t = dt(h_max, R)
    err_d_t = [errores(dt, [h_max[i], R], [err_h_max[i], err_R]) for i in range(len(L))]
    x = x_sigma(d_t, R)
    y = y_sigma(L, d_t)
    err_y = [errores(y_sigma, [L[i], d_t[i]], [err_L[i], err_d_t[i]]) for i in range(len(L))]

    err_y, absolute_sigma = (None, False) if np.any(np.isclose(err_y, 0.0)) else (err_y, False)
    params, cov = curve_fit(
        pot, x, y, p0=[1e7, 0.05], bounds=([0, 0], [1e10, 0.5]),
        sigma=err_y, absolute_sigma=absolute_sigma, maxfev=1000000,
    )

    sigma_y = params[0] * beta_m
    sigma = np.diag(cov) ** 0.5
    err_sigma_y = sigma_y * np.sqrt((sigma[0] / params[0]) ** 2 + (0.005) ** 2)

    return sigma_y, err_sigma_y


def beta_m_de_material(material: str, tabla: dict = MATERIAL_BETA_M) -> float:
    """Resuelve el coeficiente Beta_m a partir del nombre de material.
    Lanza ``KeyError`` si el material no está en la tabla, en vez de
    fallar silenciosamente como el ``if/elif`` original (que dejaba
    ``B_m`` sin definir para cualquier material no contemplado)."""
    try:
        return tabla[material]
    except KeyError as exc:
        raise KeyError(
            f"Material '{material}' sin Beta_m definido. "
            f"Materiales disponibles: {list(tabla)}"
        ) from exc


# ──────────────────────────────────────────────────────────────────────
# Exponente de endurecimiento n (Ludwig/Hollomon)
# ──────────────────────────────────────────────────────────────────────
def calcular_n(sigma_ri, epsilon_ri, sigma_y, E, err_sig):
    """Ajusta sigma = sigma_y * (1 + (E/sigma_y) * eps)^n y devuelve
    (n, err_n). Devuelve (None, None) si el ajuste no converge."""

    def model(x, n):
        return sigma_y * (1 + (E / sigma_y) * x) ** n

    n, err_n = None, None
    try:
        popt, cov = curve_fit(
            model, epsilon_ri, sigma_ri,
            p0=[0.1], bounds=([0.01], [0.9]),
            sigma=err_sig, maxfev=int(1e6),
        )
        n = popt[0]
        err_n = np.sqrt(cov[0, 0])
    except RuntimeError:
        pass
    except Exception:
        pass

    return n, err_n


# ──────────────────────────────────────────────────────────────────────
# Orquestación: resultado completo de una indentación
# ──────────────────────────────────────────────────────────────────────
@dataclass
class ResultadoIndentacion:
    """Equivalente puro de lo que el método ``Calculos`` original dejaba
    repartido en atributos de instancia (``self.sigma_y``, ``self.n``,
    ``self.UTS1``, ...), listo para que la capa de UI lo grafique/tabule
    y decida si lo agrega al preinforme."""

    sigma_y: float
    err_sigma_y: float
    n: float
    err_n: float
    UTS1: float
    err_UTS1: float
    deformacion: np.ndarray   # incluye el punto (0, sigma_y) al inicio
    tension: np.ndarray       # Pa
    x_fit: np.ndarray         # deformación para la curva de ajuste continua
    y_fit: np.ndarray         # tensión (Pa) de la curva de ajuste continua
    h_max: np.ndarray         # por ciclo, corregido por compliance (m)
    L: np.ndarray             # por ciclo (N)
    S: np.ndarray             # por ciclo (N/m)


def calcular_resultados_indentacion(parametros: dict, material: str) -> ResultadoIndentacion:
    """Traducción pura de ``Calculos``: corrige compliance, resuelve el
    modelo Haggag, ajusta sigma_y y n, y devuelve todo empaquetado.

    A diferencia del original, NO pregunta "¿agregar al preinforme?"
    (``messagebox.askyesno``) ni actualiza gráficos/tablas: eso queda
    para el controlador de la pestaña de resultados en ``ui/``.

    ``parametros`` acepta las mismas claves que :func:`calculo_parametros`
    más ``CF``/``err_CF`` opcionales (compliance del instrumento); si no
    se incluyen se usan los valores de ``config.COMPLIANCE_CF``.
    """
    from config import COMPLIANCE_CF, COMPLIANCE_ERR_CF  # import local: evita ciclo si config crece

    h_max = parametros["h_max"]
    err_h_max = parametros["err_h_max"]
    L = parametros["L"]
    err_L = parametros["err_L"]
    R = parametros["R"]
    err_R = parametros["err_R"]
    E = parametros["E"]
    alpha_m = parametros.get("alpha_m", DEFAULT_ALPHA_M)
    CF = parametros.get("CF", COMPLIANCE_CF)
    err_CF = parametros.get("err_CF", COMPLIANCE_ERR_CF)

    h_corr, err_h_corr = calculo_compliance(h_max, L, err_h_max, err_L, CF, err_CF)

    parametros_mod = dict(parametros)
    parametros_mod["h_max"] = h_corr
    parametros_mod["err_h_max"] = err_h_corr

    _, deformacion, tension, err_b, err_c = calculo_parametros(parametros_mod, alpha_m)[:5]

    beta_m = beta_m_de_material(material)
    sigma_y, err_sigma_y = calc_sigma_y(h_corr, R, L, err_h_corr, err_R, err_L, beta_m)

    deformacion = np.insert(deformacion, 0, 0)
    tension = np.insert(tension, 0, sigma_y)
    err_c = np.insert(err_c, 0, err_sigma_y)

    n, err_n = calcular_n(tension / 1e6, deformacion, sigma_y / 1e6, E / 1e6, err_c / 1e6)

    UTS1 = sigma_y * (E * n / (np.e * sigma_y)) ** n
    err_UTS1 = np.sqrt(
        (UTS1 / sigma_y * (1 - n) * err_sigma_y) ** 2
        + (UTS1 * (np.log(E / sigma_y) + np.log(n / np.e) + 1) * err_n) ** 2
    )

    def model(x, n, s):
        return s * (1 + E / s * x) ** n

    x_fit = np.linspace(min(deformacion), max(deformacion))
    y_fit = model(x_fit, n, sigma_y)

    return ResultadoIndentacion(
        sigma_y=sigma_y,
        err_sigma_y=err_sigma_y,
        n=n,
        err_n=err_n,
        UTS1=UTS1,
        err_UTS1=err_UTS1,
        deformacion=deformacion,
        tension=tension,
        x_fit=x_fit,
        y_fit=y_fit,
        h_max=h_corr,
        L=L,
        S=parametros["S"],
    )