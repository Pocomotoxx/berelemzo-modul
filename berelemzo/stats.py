"""Függőségmentes eloszlásfüggvények (csak a szabványos könyvtár).

A Welch-féle egyoldali t-próbához kell a Student-féle t eloszlás felső farka és
kvantilise. A megvalósítás a regularizált nem teljes béta-függvényen
(Lentz-féle lánctört) alapul; a kvantilis felezéses keresés, ezért determinisztikus.
"""

from __future__ import annotations

import math


def norm_cdf(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def _betacf(a: float, b: float, x: float) -> float:
    eps, fpmin = 3e-16, 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    d = fpmin if abs(d) < fpmin else d
    d = 1.0 / d
    h = d
    for m in range(1, 1000):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = fpmin if abs(d) < fpmin else d
        c = 1.0 + aa / c
        c = fpmin if abs(c) < fpmin else c
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = fpmin if abs(d) < fpmin else d
        c = 1.0 + aa / c
        c = fpmin if abs(c) < fpmin else c
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def betainc_reg(x: float, a: float, b: float) -> float:
    """Regularizált nem teljes béta-függvény I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                  + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def t_sf(t: float, df: float) -> float:
    """P(T > t) a Student-féle t eloszlásra."""
    if t < 0:
        return 1.0 - t_sf(-t, df)
    return 0.5 * betainc_reg(df / (df + t * t), df / 2.0, 0.5)


def t_upper_quantile(alpha: float, df: float) -> float:
    """Az a t, amelyre P(T > t) = alpha (0 < alpha < 0,5)."""
    if not 0.0 < alpha < 0.5:
        raise ValueError("alpha 0 és 0,5 között legyen")
    lo, hi = 0.0, 1.0
    while t_sf(hi, df) > alpha:
        hi *= 2.0
        if hi > 1e12:
            raise ValueError("a kvantilis nem keresztezhető")
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if t_sf(mid, df) > alpha:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)
