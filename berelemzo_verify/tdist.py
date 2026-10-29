"""Student-féle t eloszlás felső kvantilise, a Bérelemzőtől eltérő módszerrel.

A Bérelemző a regularizált nem teljes béta-függvényt (lánctört) használja. Itt a sűrűségfüggvény numerikus
integrálása (összetett Simpson-szabály) és Newton–bisection gyökkeresés szolgál ugyanarra, hogy a két megvalósítás
hibái ne essenek egybe.
"""

from __future__ import annotations

import math


def _pdf(x: float, df: float) -> float:
    c = math.exp(math.lgamma((df + 1.0) / 2.0) - math.lgamma(df / 2.0)) / math.sqrt(df * math.pi)
    return c * (1.0 + x * x / df) ** (-(df + 1.0) / 2.0)


def _integral_0_to(t: float, df: float, n: int = 4000) -> float:
    """A sűrűségfüggvény integrálja 0-tól t-ig (t >= 0), összetett Simpson-szabállyal."""
    if t <= 0.0:
        return 0.0
    h = t / n
    s = _pdf(0.0, df) + _pdf(t, df)
    for i in range(1, n):
        s += (4.0 if i % 2 else 2.0) * _pdf(i * h, df)
    return s * h / 3.0


def upper_quantile(alpha: float, df: float) -> float:
    """Az a t, amelyre P(T > t) = alpha (0 < alpha < 0,5)."""
    if not 0.0 < alpha < 0.5:
        raise ValueError("alpha 0 és 0,5 között legyen")
    if not df > 0.0:
        raise ValueError("a szabadságfok pozitív legyen")
    target = 0.5 - alpha
    lo, hi = 0.0, 1.0
    while _integral_0_to(hi, df) < target:
        hi *= 2.0
        if hi > 1e4:
            raise ValueError("a kvantilis nem keresztezhető")
    t = min(max(1.7, lo), hi)
    for _ in range(60):
        f = _integral_0_to(t, df) - target
        if abs(f) < 1e-13:
            return t
        if f > 0:
            hi = t
        else:
            lo = t
        step = f / _pdf(t, df)
        nt = t - step
        t = nt if lo < nt < hi else 0.5 * (lo + hi)
    return t
