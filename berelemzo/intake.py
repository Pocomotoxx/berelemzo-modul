"""Helyi adatbevitel: a konfiguráció és a bérfájl szigorú, sémaalapú beolvasása.

Adatvédelmi szabályok (kódban érvényesítve, nem csak leírva):
  * Fehérlista: a bérfájl pontosan a `job_id`, `sex`, `pay` oszlopot tartalmazhatja.
    Minden más oszlop (név, adószám, bankszámlaszám, e-mail stb.) elutasítandó.
  * Nincs egyéni azonosító: a sorokból csak munkakörönkénti összegzés készül.
  * A hibaüzenet sosem tartalmaz cellaértéket, csak a sor számát és a mező nevét.
  * A modul nem naplóz és nem ír ki sort; a nyers sorok nem hagyják el a memóriát.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

from .core import MIN_CELL_FLOOR, Config, JobStats

ALLOWED_COLUMNS = ("job_id", "sex", "pay")
_F = {"f", "female", "woman", "nő", "no"}
_M = {"m", "male", "man", "férfi", "ferfi"}
CONFIG_KEYS = {"scheme", "band_width", "min_cell", "jobs"}
SCHEME_KEYS = {"name", "weights", "level_max"}


class IntakeError(ValueError):
    """Bemeneti hiba; az üzenet nem tartalmazhat adatértéket."""


def load_config(path: str | Path) -> Config:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntakeError(f"A konfiguráció nem olvasható vagy nem érvényes JSON: {type(exc).__name__}") from None
    return parse_config(raw)


def parse_config(raw: object) -> Config:
    if not isinstance(raw, dict):
        raise IntakeError("A konfiguráció gyökere objektum legyen.")
    extra = set(raw) - CONFIG_KEYS
    if extra:
        raise IntakeError(f"Ismeretlen konfigurációs kulcs: {', '.join(sorted(extra))}")
    scheme = raw.get("scheme")
    if not isinstance(scheme, dict) or set(scheme) - SCHEME_KEYS or "weights" not in scheme:
        raise IntakeError("A 'scheme' objektum kötelező, kulcsai: name, weights, level_max.")
    weights = scheme["weights"]
    if (not isinstance(weights, list) or not weights
            or not all(_num(w) and w >= 0 for w in weights) or abs(sum(weights) - 1.0) > 1e-9):
        raise IntakeError("A súlyok nemnegatív számok listája legyenek, összegük 1.")
    level_max = scheme.get("level_max", 5)
    if isinstance(level_max, list):
        if len(level_max) != len(weights) or not all(_num(m) and m > 0 for m in level_max):
            raise IntakeError("A level_max lista hossza egyezzen a súlyok számával, elemei pozitív számok legyenek.")
        maxes = tuple(float(m) for m in level_max)
    elif _num(level_max) and level_max > 0:
        maxes = (float(level_max),) * len(weights)
        level_max = float(level_max)
    else:
        raise IntakeError("A level_max pozitív szám vagy részfaktoronkénti pozitív számok listája legyen.")
    band = raw.get("band_width", 5.0)
    if not _num(band) or band <= 0:
        raise IntakeError("A band_width pozitív szám legyen.")
    min_cell = raw.get("min_cell", MIN_CELL_FLOOR)
    if not isinstance(min_cell, int) or isinstance(min_cell, bool) or min_cell < MIN_CELL_FLOOR:
        raise IntakeError(f"A min_cell egész szám legyen, legalább {MIN_CELL_FLOOR} (a küszöb nem csökkenthető).")
    jobs_raw = raw.get("jobs")
    if not isinstance(jobs_raw, dict) or not jobs_raw:
        raise IntakeError("A 'jobs' nem üres objektum legyen: munkakör → szintek listája.")
    jobs = {}
    for jid, lv in jobs_raw.items():
        if (not isinstance(lv, list) or len(lv) != len(weights)
                or not all(_num(x) and 0 <= x <= m for x, m in zip(lv, maxes))):
            raise IntakeError(f"A '{jid}' munkakör szintlistája hibás (hossz = súlyok száma, értékek 0..a részfaktor skálamaximuma).")
        jobs[str(jid)] = tuple(float(x) for x in lv)
    return Config(weights=tuple(float(w) for w in weights),
                  level_max=tuple(maxes) if isinstance(level_max, list) else level_max, band_width=float(band),
                  min_cell=min_cell, jobs=jobs, scheme_name=str(scheme.get("name", "")))


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def read_pay_file(path: str | Path, cfg: Config, delimiter: str = ",") -> tuple[dict[str, JobStats], dict[str, int]]:
    """A bérfájlból munkakörönkénti összegzést készít; a sorok nem maradnak meg."""
    if "://" in str(path):
        raise IntakeError("Csak helyi fájl olvasható be.")
    stats: dict[str, JobStats] = {}
    excluded = {"other_sex": 0, "unknown_job": 0}
    try:
        fh = open(path, encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise IntakeError(f"A bérfájl nem nyitható meg: {type(exc).__name__}") from None
    with fh:
        reader = csv.reader(fh, delimiter=delimiter)
        header = next(reader, None)
        if header is None:
            raise IntakeError("A bérfájl üres.")
        cols = [h.strip().casefold() for h in header]
        extra = [h for h in cols if h not in ALLOWED_COLUMNS]
        if extra or sorted(cols) != sorted(ALLOWED_COLUMNS):
            raise IntakeError(
                "A bérfájl oszlopai pontosan ezek legyenek: job_id, sex, pay. "
                + (f"Nem engedélyezett oszlop: {', '.join(extra)}." if extra else "Hiányzó oszlop."))
        ij, isx, ip = cols.index("job_id"), cols.index("sex"), cols.index("pay")
        for lineno, row in enumerate(reader, start=2):
            if not row or all(not c.strip() for c in row):
                continue
            if len(row) != len(cols):
                raise IntakeError(f"A(z) {lineno}. sor oszlopszáma hibás.")
            jid, sx = row[ij].strip(), row[isx].strip().casefold()
            try:
                pay = float(row[ip].strip())
            except ValueError:
                raise IntakeError(f"A(z) {lineno}. sor 'pay' mezője nem szám.") from None
            if not math.isfinite(pay) or pay <= 0:
                raise IntakeError(f"A(z) {lineno}. sor 'pay' mezője nem pozitív véges szám.")
            if sx in _F:
                female = True
            elif sx in _M:
                female = False
            else:
                excluded["other_sex"] += 1
                continue
            if jid not in cfg.jobs:
                excluded["unknown_job"] += 1
                continue
            st = stats.setdefault(jid, JobStats())
            (st.f if female else st.m).add(pay)
    return stats, excluded
