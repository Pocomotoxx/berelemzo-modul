"""A bérelemző számítási magja: tiszta függvények, fájl- és hálózatkezelés nélkül.

Bemenet: munkakörönkénti összegző statisztikák (nem egyedi sorok) és az emberi
döntésből származó értékelési séma. Kimenet: kategóriánkénti bérrés-jelentés.

Módszer (S1–S5):
  S1  munkakör-pontszám  S_j = 100 · Σ_k w_k · ℓ_jk / ℓ_max,k  (a skálamaximum részfaktoronként eltérhet)
  S2  kategória          g_j = ceil(S_j / szélesség)
  S3  nemenkénti összevonás kategóriánként (Chan-féle párhuzamos összegzés)
  S4  hézag              G_c = (átlag_férfi − átlag_nő) / átlag_férfi (számtani bérátlag)
  S5  jelzések           T_c = [G_c ≥ 0,05]; mintavételi jelzés = T_c ∧ Welch-féle egyoldali t-próba

Nem jogi minősítés: a T_c küszöbérintés, nem a közös bérértékelési kötelezettség.
Az indoklás (J_c) és az orvoslás (R_c) emberi döntés, ezt a modul nem hozza meg.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field

from . import METHOD_ID, __version__
from .stats import norm_cdf, t_upper_quantile

TRIGGER_GAP = 0.05
ALPHA = 0.05
# A kategóriánkénti nemenkénti minimum létszám alsó korlátja (kis cellák elnyomása).
MIN_CELL_FLOOR = 5


@dataclass
class Acc:
    """Egy nem bérlogaritmusának futó statisztikája (Welford/Chan) és a bérek összege."""

    n: int = 0
    mean: float = 0.0
    m2: float = 0.0
    pay_sum: float = 0.0

    def add(self, pay: float) -> None:
        lp = math.log(pay)
        self.n += 1
        d = lp - self.mean
        self.mean += d / self.n
        self.m2 += d * (lp - self.mean)
        self.pay_sum += pay

    def merge(self, other: "Acc") -> None:
        if other.n == 0:
            return
        if self.n == 0:
            self.n, self.mean, self.m2, self.pay_sum = other.n, other.mean, other.m2, other.pay_sum
            return
        n = self.n + other.n
        d = other.mean - self.mean
        self.m2 += other.m2 + d * d * self.n * other.n / n
        self.mean += d * other.n / n
        self.n = n
        self.pay_sum += other.pay_sum

    @property
    def var(self) -> float:
        return self.m2 / (self.n - 1)


@dataclass
class JobStats:
    f: Acc = field(default_factory=Acc)
    m: Acc = field(default_factory=Acc)


@dataclass(frozen=True)
class Config:
    weights: tuple[float, ...]
    level_max: "float | tuple[float, ...]"  # egységes skálamaximum vagy részfaktoronkénti lista
    band_width: float
    min_cell: int
    jobs: dict[str, tuple[float, ...]]
    scheme_name: str = ""

    def level_max_out(self):
        return list(self.level_max) if isinstance(self.level_max, tuple) else self.level_max

    def canonical(self) -> dict:
        return {"scheme_name": self.scheme_name, "weights": list(self.weights), "level_max": self.level_max_out(),
                "band_width": self.band_width, "min_cell": self.min_cell,
                "jobs": {k: list(v) for k, v in sorted(self.jobs.items())}}

    def sha256(self) -> str:
        return _digest(self.canonical())


def job_score(levels, weights, level_max=5.0) -> float:
    """level_max: egységes szám, vagy részfaktoronkénti lista (pl. az EIGE szaktudás részfaktora 0–8, a többi 0–5)."""
    maxes = level_max if isinstance(level_max, (tuple, list)) else (level_max,) * len(weights)
    return 100.0 * sum(w * l / m for w, l, m in zip(weights, levels, maxes))


def grade_of(score: float, width: float) -> int:
    return int(math.ceil(max(score, 1e-9) / width))


def _digest(obj) -> str:
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _r(x: float, nd: int = 6) -> float:
    return round(x, nd)


def floor_count(n: int, k: int):
    """Kis nemnulla darabszám nem közölhető pontosan (egyént azonosíthat)."""
    return n if n == 0 or n >= k else f"<{k}"


def analyze(cfg: Config, stats: dict[str, JobStats], excluded: dict[str, int] | None = None) -> dict:
    by_grade: dict[int, list[str]] = {}
    for jid, lv in cfg.jobs.items():
        if jid in stats:
            by_grade.setdefault(grade_of(job_score(lv, cfg.weights, cfg.level_max), cfg.band_width), []).append(jid)

    t_trigger = -math.log(1.0 - TRIGGER_GAP)  # a 0,05-ös számtani hézag log-megfelelője
    cats, p0s = [], []
    for g in sorted(by_grade):
        f, m = Acc(), Acc()
        for jid in by_grade[g]:
            f.merge(stats[jid].f)
            m.merge(stats[jid].m)
        rng = [_r((g - 1) * cfg.band_width, 6), _r(g * cfg.band_width, 6)]
        if f.n < cfg.min_cell or m.n < cfg.min_cell:
            cats.append({"grade": g, "score_range": rng, "suppressed": True})
            continue
        gap = (m.pay_sum / m.n - f.pay_sum / f.n) / (m.pay_sum / m.n)
        va, vb = m.var / m.n, f.var / f.n
        se = math.sqrt(va + vb)
        if se > 0.0:
            t = (m.mean - f.mean) / se
            df = (va + vb) ** 2 / (va ** 2 / (m.n - 1) + vb ** 2 / (f.n - 1))
            t_crit = t_upper_quantile(ALPHA, df)
            welch = t > t_crit
            p0 = 1.0 - norm_cdf(t_trigger / se)
        else:  # nincs szórás: a becslés elfajult, jelzést nem adunk
            t = df = t_crit = None
            welch, p0 = False, 0.0
        point = gap >= TRIGGER_GAP
        p0s.append(p0)
        cats.append({
            "grade": g, "score_range": rng, "suppressed": False,
            "n_f": f.n, "n_m": m.n,
            "gap": _r(gap), "se_log": _r(se, 6),
            "t": None if t is None else _r(t, 4), "df": None if df is None else _r(df, 3),
            "t_crit": None if t_crit is None else _r(t_crit, 4),
            "t_c_point_threshold": bool(point),
            "welch_significant": bool(welch),
            "sampling_signal": bool(point and welch),
            "p_point_trigger_if_no_gap": _r(p0, 6),
        })

    rep = [c for c in cats if not c["suppressed"]]
    p_any = 1.0 - math.prod(1.0 - p for p in p0s) if p0s else 0.0
    ex = excluded or {}
    result = {
        "method_id": METHOD_ID,
        "core_version": __version__,
        "evidence_level": "COMPUTED_MEASURED",
        "legal_status": "REVIEW_REQUIRED",
        "parameters": {
            "weights": list(cfg.weights), "level_max": cfg.level_max_out(), "band_width": cfg.band_width,
            "min_cell": cfg.min_cell, "trigger_gap": TRIGGER_GAP, "alpha": ALPHA,
            "config_sha256": cfg.sha256(),
        },
        "categories": cats,
        "summary": {
            "categories_total": len(cats),
            "categories_reported": len(rep),
            "categories_suppressed": len(cats) - len(rep),
            "point_threshold_hits": sum(c["t_c_point_threshold"] for c in rep),
            "sampling_signals": sum(c["sampling_signal"] for c in rep),
            "expected_point_hits_if_no_gap": _r(sum(p0s), 4),
            "p_any_point_hit_if_no_gap": _r(p_any, 4),
        },
        "excluded": {k: floor_count(v, cfg.min_cell) for k, v in sorted(ex.items())},
        "notes": [
            "A T_c küszöbérintés nem a közös bérértékelési kötelezettség; az indoklás és az orvoslás emberi döntés.",
            "A mintavételi jelzés statisztikai segédinformáció, nem jogi minősítés és nem szabálysértés megállapítása.",
            "A p_point_trigger_if_no_gap azt mutatja, mekkora eséllyel érné el az 5%-ot a pontbecslés valós hézag nélkül; "
            "a szervezetszintű érték a többszörös összehasonlítás (family-wise) hatását mutatja.",
        ],
    }
    result["fingerprint"] = {"algorithm": "sha256", "result": _digest(result)}
    return result
