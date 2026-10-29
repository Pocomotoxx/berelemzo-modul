"""Szintetikus „beérkezett adat” és jó nyilatkozatok a tesztekhez. Soha nem valós adat."""

from __future__ import annotations

import copy
import csv
import datetime as dt
import math
import random
import statistics

from berelemzo_audit.indicators import grade_of, job_score

AUDIT_DATE = dt.date(2026, 10, 29)
WEIGHTS = [0.40, 0.35, 0.15, 0.10]
HEADER = ["job_id", "sex", "fte", "alapber", "rendszeres_potlek", "valtozo_bonusz", "termeszetbeni", "tulora", "teljesitmenysav"]


def iso(d: dt.date) -> str:
    return d.isoformat()


def make_world(seed: int = 7, n_jobs: int = 14, delta: float = 0.0, sd: float = 0.05, per_job=(10, 24)):
    rng = random.Random(seed)
    jobs = {f"MK-{i:03d}": [rng.randint(1, 5) for _ in WEIGHTS] for i in range(n_jobs)}
    cfg = {"scheme": {"name": "teszt", "weights": WEIGHTS, "level_max": 5}, "band_width": 10.0, "min_cell": 5, "jobs": jobs}
    rows = []
    for jid, lv in jobs.items():
        s = job_score(lv, WEIGHTS, [5.0] * 4)
        base = 280000 * math.exp(0.012 * s)
        for _ in range(rng.randint(*per_job)):
            female = rng.random() < 0.5
            fte = 0.5 if rng.random() < 0.12 else 1.0
            total_full = base * math.exp(rng.gauss(0, sd) - (delta if female else 0.0))
            total = total_full * fte
            bonus = round(total * rng.choice([0.0, 0.0, 0.05, 0.08]))
            allowance = round(total * 0.04)
            kind = round(total * 0.02)
            ot = round(total * rng.choice([0.0, 0.0, 0.03]))
            basic = round(total) - bonus - allowance - kind - ot
            perf = rng.choice([2, 3, 3, 4, 4, 5])
            rows.append([jid, "F" if female else "M", fte, basic, allowance, bonus, kind, ot, perf])
    return cfg, rows


def write_csv(path, rows, header=HEADER, delimiter=","):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=delimiter)
        w.writerow(header)
        w.writerows(rows)


def good_declarations(cfg: dict, rows: list, audit_date: dt.date = AUDIT_DATE) -> dict:
    """Olyan nyilatkozatok, amelyek mellett nincs NOT_MET: a bérsávok az adatot lefedik, nincs kezeletlen küszöbérintés."""
    wts = cfg["scheme"]["weights"]
    grade = {j: grade_of(job_score(lv, wts, [5.0] * len(wts)), cfg["band_width"]) for j, lv in cfg["jobs"].items()}
    norms: dict[int, list[float]] = {}
    total = 0.0
    for r in rows:
        tot = sum(float(x) for x in r[3:8])
        total += tot
        norms.setdefault(grade[r[0]], []).append(tot / float(r[2]))
    bands = [{"grade": f"G{g}", "min": math.floor(min(v)) - 1, "max": math.ceil(max(v)) + 1} for g, v in sorted(norms.items())]
    day = lambda n: iso(audit_date - dt.timedelta(days=n))
    return {
        "organisation": {"period": "2026-09", "currency": "HUF", "headcount_declared": len(rows)},
        "governance": {"owner_role": "HR-vezető", "raci_ref": "RACI-2026-1", "approved_on": day(100),
                       "legal_review": {"date": day(60), "ref": "JOGI-2026-3"}, "representative_involved": True, "minutes_ref": "JKV-2026-5"},
        "job_catalogue": {j: {"profile_version": "v1.0", "profile_ref": f"JP-{j}", "active": True, "grade": f"G{g}"} for j, g in grade.items()},
        "job_evaluation": {"feor_reference_only": True, "zero_level_reasons": {}, "dominance_threshold": 0.7},
        "pay_elements": ["alapber", "rendszeres_potlek", "valtozo_bonusz", "termeszetbeni", "tulora"],
        "reconciliation": {"headcount": len(rows), "gross_total": round(total, 2)},
        "normalization": {"documented": True, "ref": "NORM-1", "absence_rule": "a távollét nem csökkenti a díjazást a mutatóban"},
        "pay_bands": bands,
        "pay_policy": {"progression_criteria": {"ref": "FEJL-1", "accessible_since": day(200)}},
        "scoring_log": {"raters": {j: [list(lv), list(lv)] for j, lv in cfg["jobs"].items()}, "rationale_documented": {j: True for j in cfg["jobs"]}},
        "justifications": [],
        "justifications_declared_complete": True,
        "deviation_register": [],
        "info_requests": [],
        "info_requests_declared_complete": True,
        "transparency": {"job_ads": {"total": 4, "with_pay_range": 4}, "pay_history_question_banned": True,
                         "annual_notice_on": day(120), "criteria_accessible": True},
        "reporting": {"calendar_ref": "JEL-NAPTAR-1", "owner_role": "HR-vezető"},
        "joint_assessment": {"procedure_ref": "KBE-ELJ-1", "template_ref": "KBE-SAB-1"},
        "data_protection": {"access_matrix_ref": "HM-1", "purpose_ref": "CEL-1", "retention_days": 90,
                            "small_group_mitigation": "szélesebb pontsávok és összevonás a kis kategóriáknál"},
        "change_management": {"job_changes": [], "monitoring_owner_role": "Jogi referens", "last_update_log_on": day(90)},
    }


def find_world(need_no_trigger: bool = True, need_suppressed: bool = False, seed: int = 7, **kw):
    """Olyan világot keres, ahol nincs 5% feletti kategória (és kell, hogy legyen elnyomott kategória)."""
    from berelemzo_audit.indicators import category_table
    from berelemzo_audit.inputs import Config, load_rows
    import tempfile, os
    for s in range(seed, seed + 300):
        cfg, rows = make_world(seed=s, **kw)
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        try:
            write_csv(path, rows)
            ds = load_rows(path)
        finally:
            os.remove(path)
        c = Config(tuple(cfg["scheme"]["weights"]), (5.0,) * 4, cfg["band_width"], 5, {j: tuple(float(x) for x in v) for j, v in cfg["jobs"].items()})
        cats = category_table(ds.rows, c)
        trig = any((not x["suppressed"]) and x["t_c"] for x in cats)
        sup = any(x["suppressed"] for x in cats)
        if (not need_trigger_ok(trig, need_no_trigger)) or (need_suppressed != sup):
            continue
        return cfg, rows
    raise RuntimeError("nem találtam megfelelő szintetikus világot")


def need_trigger_ok(trig: bool, need_no_trigger: bool) -> bool:
    return (not trig) if need_no_trigger else trig
