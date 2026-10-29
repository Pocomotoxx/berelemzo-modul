"""Aggregált mutatók az egyéni szintű adatból. Két, egymástól független számítási úton is elérhetők (STA-01).

Mutatók: átlagos és medián bérkülönbség, a változó díjazás különbsége és aránya, a nők és férfiak aránya a négy
bérkvartilisben, valamint kategóriánkénti átlag- és mediánrés a 5%-os trigger és a Welch-jelzés állapotával.
A kis cellák (nemenként < min_cell) elnyomva szerepelnek, számadat nélkül.

Módszertani feltevések (a tudásbázis a pontos eljárást nem rögzíti, ezért jelöltek):
  * a bérkülönbség (férfi − nő) / férfi, a teljes munkaidőre átszámolt (FTE-normalizált) díjazáson;
  * a kvartilis-határ az `inclusive` módszerű kvantilis (statistics.quantiles), a határ-érték az alsó kvartilishez tartozik;
  * a kategória a Bérelemző szabálya szerint: ceil(pontszám / sávszélesség), a pontszám 100·Σ w·ℓ/ℓ_max.
"""

from __future__ import annotations

import math
import statistics

from berelemzo_verify.tdist import upper_quantile

from .catalogue import TRIGGER_GAP
from .inputs import Config, Dataset, Row

ALPHA = 0.05


def job_score(levels, weights, level_max) -> float:
    return 100.0 * sum(w * l / m for w, l, m in zip(weights, levels, level_max))


def grade_of(score: float, width: float) -> int:
    return int(math.ceil(max(score, 1e-9) / width))


def floor_count(n: int, k: int):
    """Kis nemnulla darabszám nem közölhető pontosan."""
    return n if n == 0 or n >= k else f"<{k}"


def _gap(m: float, f: float):
    """(férfi − nő) / férfi; None, ha a férfi érték 0 (a viszony nem értelmezhető)."""
    return None if m == 0 else (m - f) / m


def _r(x, nd: int = 6):
    return None if x is None else round(x, nd)


# ----------------------------------------------------------------- két független számítási út
def mean_gap_fast(rows: list[Row], attr: str = "norm"):
    f = [getattr(r, attr) for r in rows if r.female]
    m = [getattr(r, attr) for r in rows if not r.female]
    if not f or not m:
        return None
    return _gap(sum(m) / len(m), sum(f) / len(f))


def mean_gap_naive(rows: list[Row], attr: str = "norm"):
    sf = sm = 0.0
    nf = nm = 0
    for r in rows:
        v = getattr(r, attr)
        if r.female:
            sf += v
            nf += 1
        else:
            sm += v
            nm += 1
    if not nf or not nm:
        return None
    return _gap(sm / nm, sf / nf)


def median_gap_fast(rows: list[Row], attr: str = "norm"):
    f = [getattr(r, attr) for r in rows if r.female]
    m = [getattr(r, attr) for r in rows if not r.female]
    if not f or not m:
        return None
    return _gap(statistics.median(m), statistics.median(f))


def _median_sorted(v: list[float]) -> float:
    v = sorted(v)
    n = len(v)
    return v[n // 2] if n % 2 else 0.5 * (v[n // 2 - 1] + v[n // 2])


def median_gap_naive(rows: list[Row], attr: str = "norm"):
    f = [getattr(r, attr) for r in rows if r.female]
    m = [getattr(r, attr) for r in rows if not r.female]
    if not f or not m:
        return None
    return _gap(_median_sorted(m), _median_sorted(f))


def quartile_cuts(values: list[float]) -> list[float]:
    return statistics.quantiles(values, n=4, method="inclusive")


def quartile_of(v: float, cuts: list[float]) -> int:
    return 1 + sum(1 for c in cuts if v > c)


# ----------------------------------------------------------------- mutatók
def overall(rows: list[Row], k: int) -> dict:
    nf = sum(1 for r in rows if r.female)
    nm = len(rows) - nf
    out = {"n_f": floor_count(nf, k), "n_m": floor_count(nm, k)}
    if nf < k or nm < k:
        out["suppressed"] = True
        return out
    out["suppressed"] = False
    out["mean_gap"] = _r(mean_gap_fast(rows))
    out["median_gap"] = _r(median_gap_fast(rows))
    return out


def variable_pay(rows: list[Row], k: int) -> dict | None:
    if not rows or rows[0].var_norm is None:
        return None
    f_all = [r for r in rows if r.female]
    m_all = [r for r in rows if not r.female]
    f_rec = [r for r in f_all if (r.var_norm or 0) > 0]
    m_rec = [r for r in m_all if (r.var_norm or 0) > 0]
    out = {"recipients_f": floor_count(len(f_rec), k), "recipients_m": floor_count(len(m_rec), k)}
    if 0 < len(f_rec) < k or 0 < len(m_rec) < k:
        # az arány és a különbség egy 1–(k−1) fős csoport pontos létszámát vagy összegét fedné fel
        out["suppressed"] = True
        return out
    if len(f_all) >= k and len(m_all) >= k:
        out["share_receiving_f"] = round(len(f_rec) / len(f_all), 6)
        out["share_receiving_m"] = round(len(m_rec) / len(m_all), 6)
        out["mean_gap_all_workers"] = _r(mean_gap_fast(rows, "var_norm"))
        out["median_gap_all_workers"] = _r(median_gap_fast(rows, "var_norm"))
    if len(f_rec) >= k and len(m_rec) >= k:
        out["mean_gap_recipients"] = _r(mean_gap_fast(f_rec + m_rec, "var_norm"))
        out["median_gap_recipients"] = _r(median_gap_fast(f_rec + m_rec, "var_norm"))
    return out


def quartile_distribution(rows: list[Row], k: int) -> list[dict]:
    if len(rows) < 4:
        return []
    cuts = quartile_cuts([r.norm for r in rows])
    out = []
    for q in (1, 2, 3, 4):
        members = [r for r in rows if quartile_of(r.norm, cuts) == q]
        nf = sum(1 for r in members if r.female)
        nm = len(members) - nf
        cell = {"quartile": q, "n_f": floor_count(nf, k), "n_m": floor_count(nm, k)}
        if nf >= k and nm >= k:
            cell["share_f"] = round(nf / (nf + nm), 6)
        else:
            cell["suppressed"] = True
        out.append(cell)
    return out


def _welch(f_vals: list[float], m_vals: list[float]):
    lf, lm = [math.log(x) for x in f_vals], [math.log(x) for x in m_vals]
    mf, mm = statistics.fmean(lf), statistics.fmean(lm)
    vf, vm = statistics.variance(lf), statistics.variance(lm)
    a, b = vm / len(lm), vf / len(lf)
    if a + b <= 0:
        return None
    se = math.sqrt(a + b)
    t = (mm - mf) / se
    df = (a + b) ** 2 / (a ** 2 / (len(lm) - 1) + b ** 2 / (len(lf) - 1))
    return t, df, upper_quantile(ALPHA, df), se


def grade_map(rows: list[Row], cfg: Config) -> dict[str, int]:
    """Munkakör → kategória. Pontozott konfigurációnál a pontsáv, pontozás nélkül minden munkakör külön csoport (azonos munka)."""
    if cfg.scoring:
        return {j: grade_of(job_score(lv, cfg.weights, cfg.level_max), cfg.band_width) for j, lv in cfg.jobs.items()}
    return {j: i + 1 for i, j in enumerate(sorted({r.job for r in rows}))}


def category_table(rows: list[Row], cfg: Config) -> list[dict]:
    """Kategóriánkénti mutatók. A nyers `grade` kulccsal; a kis cellák elnyomva."""
    grade_of_job = grade_map(rows, cfg)
    by: dict[int, list[Row]] = {}
    for r in rows:
        if r.job in grade_of_job:
            by.setdefault(grade_of_job[r.job], []).append(r)
    out = []
    for g in sorted(by):
        members = by[g]
        f = [r.norm for r in members if r.female]
        m = [r.norm for r in members if not r.female]
        rng = [round((g - 1) * cfg.band_width, 6), round(g * cfg.band_width, 6)] if cfg.scoring else None
        if len(f) < cfg.min_cell or len(m) < cfg.min_cell:
            out.append({"grade": g, "score_range": rng, "suppressed": True})
            continue
        gap = _gap(sum(m) / len(m), sum(f) / len(f))
        med = _gap(statistics.median(m), statistics.median(f))
        w = _welch(f, m)
        t_c = gap >= TRIGGER_GAP
        welch_sig = bool(w and w[0] > w[2])
        out.append({"grade": g, "score_range": rng, "suppressed": False, "n_f": len(f), "n_m": len(m),
                    "mean_gap": round(gap, 6), "median_gap": round(med, 6),
                    "t_c": t_c, "welch_significant": welch_sig, "sampling_signal": bool(t_c and welch_sig),
                    "t": None if w is None else round(w[0], 4), "df": None if w is None else round(w[1], 3),
                    "se_log": None if w is None else round(w[3], 6)})
    return out


def job_female_share(rows: list[Row]) -> dict[str, tuple[int, int]]:
    out: dict[str, list[int]] = {}
    for r in rows:
        c = out.setdefault(r.job, [0, 0])
        c[0 if r.female else 1] += 1
    return {j: (c[0], c[1]) for j, c in out.items()}


def all_indicators(ds: Dataset, cfg: Config) -> dict:
    k = cfg.min_cell
    return {"overall": overall(ds.rows, k), "variable_pay": variable_pay(ds.rows, k),
            "quartiles": quartile_distribution(ds.rows, k), "categories": category_table(ds.rows, cfg)}
