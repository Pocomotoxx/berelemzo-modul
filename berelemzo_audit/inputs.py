"""Bemenetek beolvasása: egyéni szintű sorok (fehérlistás oszlopok), konfiguráció, nyilatkozatok.

Az egyéni szintű adat csak a memóriában él, a kimenetbe nem kerül. A fehérlistán kívüli oszlopok értékét a
beolvasó NEM olvassa ki, csak a nevüket jelzi (adattakarékosság). A hibaüzenet sosem tartalmaz cellaértéket.
"""

from __future__ import annotations

import calendar
import csv
import datetime as dt
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from .catalogue import MIN_CELL_FLOOR

ALLOWED_COLUMNS = ("job_id", "sex", "fte", "alapber", "rendszeres_potlek", "valtozo_bonusz", "termeszetbeni",
                   "tulora", "kifizetett_osszes_kezi", "szerzodes_tipus", "belepes_eve", "munkahely", "muszakrend",
                   "iskolai_vegzettseg", "teljesitmenysav", "eletkor_sav")
DERIVED_COLUMNS = ("pay_normalizalt", "szolgalati_ido_sav", "azonos_sor_db (ellenőrző)", "azonos_sor_db")
COMPONENTS = ("alapber", "rendszeres_potlek", "valtozo_bonusz", "termeszetbeni", "tulora")
_F = {"f", "female", "woman", "nő", "no"}
_M = {"m", "male", "man", "férfi", "ferfi"}
IDENTIFIER_TOKENS = {"name", "nev", "név", "neve", "taj", "adoszam", "adószám", "bankszamla", "bankszámla", "email",
                     "e-mail", "telefon", "phone", "cim", "cím", "lakcim", "lakcím", "szuletesi", "születési",
                     "torzsszam", "törzsszám", "employee_id", "person_id"}

CONFIG_KEYS = {"scheme", "band_width", "min_cell", "jobs"}
DECLARATION_KEYS = {"organisation", "governance", "job_catalogue", "job_evaluation", "pay_elements", "reconciliation",
                    "normalization", "pay_bands", "pay_policy", "scoring_log", "justifications",
                    "justifications_declared_complete", "deviation_register", "info_requests",
                    "info_requests_declared_complete", "transparency", "reporting", "joint_assessment",
                    "data_protection", "change_management"}


class IntakeError(ValueError):
    """Bemeneti hiba; az üzenet nem tartalmazhat adatértéket."""


@dataclass
class Row:
    idx: int            # az adatsor sorszáma a fájlban (a fejléc után, üres sorok nélkül, 1-től)
    job: str
    female: bool
    fte: float
    total: float        # tényleges, nem normalizált havi bruttó
    norm: float         # a teljes munkaidőre átszámolt összes díjazás (pontosan egyszer osztva az FTE-vel)
    base_norm: float | None
    var_norm: float | None
    perf: int | None
    declared_norm: float | None = None


@dataclass
class Dataset:
    rows: list[Row] = field(default_factory=list)
    columns: set[str] = field(default_factory=set)
    rejected_columns: list[str] = field(default_factory=list)
    excluded_other_sex: int = 0
    invalid_fte_rows: int = 0
    headcount_all: int = 0          # minden adatsor, a kizártakkal együtt
    sum_total_all: float = 0.0      # a tényleges havi bruttó összeg minden soron, a kizártakkal együtt


@dataclass(frozen=True)
class Config:
    weights: tuple[float, ...]
    level_max: tuple[float, ...]
    band_width: float
    min_cell: int
    jobs: dict[str, tuple[float, ...]]
    scheme_name: str = ""


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def parse_date(value, what: str) -> dt.date:
    if isinstance(value, dt.date):
        return value
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise IntakeError(f"A(z) {what} dátuma ÉÉÉÉ-HH-NN alakú legyen.")
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise IntakeError(f"A(z) {what} dátuma érvénytelen.") from None


def add_months(d: dt.date, months: int) -> dt.date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return dt.date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def load_config(path: str | Path) -> Config:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntakeError(f"A konfiguráció nem olvasható vagy nem érvényes JSON: {type(exc).__name__}") from None
    if not isinstance(raw, dict) or set(raw) - CONFIG_KEYS:
        raise IntakeError("A konfiguráció kulcsai: scheme, band_width, min_cell, jobs.")
    scheme = raw.get("scheme")
    if not isinstance(scheme, dict) or "weights" not in scheme:
        raise IntakeError("A 'scheme.weights' kötelező.")
    w = scheme["weights"]
    if not (isinstance(w, list) and w and all(_num(x) and x >= 0 for x in w)) or abs(sum(w) - 1.0) > 1e-9:
        raise IntakeError("A súlyok nemnegatívak, összegük 1 legyen.")
    lm = scheme.get("level_max", 5)
    if isinstance(lm, list):
        if len(lm) != len(w) or not all(_num(x) and x > 0 for x in lm):
            raise IntakeError("A level_max lista hossza egyezzen a súlyokéval, elemei pozitívak legyenek.")
        maxes = tuple(float(x) for x in lm)
    elif _num(lm) and lm > 0:
        maxes = (float(lm),) * len(w)
    else:
        raise IntakeError("A level_max pozitív szám vagy lista legyen.")
    band = raw.get("band_width", 5.0)
    if not _num(band) or band <= 0:
        raise IntakeError("A band_width pozitív szám legyen.")
    mc = raw.get("min_cell", MIN_CELL_FLOOR)
    if not isinstance(mc, int) or isinstance(mc, bool) or mc < MIN_CELL_FLOOR:
        raise IntakeError(f"A min_cell egész szám legyen, legalább {MIN_CELL_FLOOR}.")
    jobs_raw = raw.get("jobs")
    if not isinstance(jobs_raw, dict) or not jobs_raw:
        raise IntakeError("A 'jobs' nem üres objektum legyen.")
    jobs = {}
    for jid, lv in jobs_raw.items():
        if not (isinstance(lv, list) and len(lv) == len(w) and all(_num(x) and 0 <= x <= m for x, m in zip(lv, maxes))):
            raise IntakeError(f"A '{jid}' munkakör szintlistája hibás.")
        jobs[str(jid)] = tuple(float(x) for x in lv)
    return Config(tuple(float(x) for x in w), maxes, float(band), mc, jobs, str(scheme.get("name", "")))


def load_declarations(path: str | Path | None) -> dict:
    if path is None:
        return {}
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntakeError(f"A nyilatkozatfájl nem olvasható vagy nem érvényes JSON: {type(exc).__name__}") from None
    if not isinstance(raw, dict):
        raise IntakeError("A nyilatkozatfájl gyökere objektum legyen.")
    extra = set(raw) - DECLARATION_KEYS
    if extra:
        raise IntakeError(f"Ismeretlen nyilatkozati kulcs: {', '.join(sorted(extra))}")
    return raw


def _float(cell: str):
    s = cell.strip()
    if s == "":
        return None
    try:
        v = float(s)
    except ValueError:
        raise ValueError from None
    if not math.isfinite(v):
        raise ValueError
    return v


def load_rows(path: str | Path, delimiter: str = ",") -> Dataset:
    if "://" in str(path):
        raise IntakeError("Csak helyi fájl olvasható be.")
    ds = Dataset()
    try:
        fh = open(path, encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise IntakeError(f"Az adatfájl nem nyitható meg: {type(exc).__name__}") from None
    with fh:
        reader = csv.reader(fh, delimiter=delimiter)
        header = next(reader, None)
        if header is None:
            raise IntakeError("Az adatfájl üres.")
        names = [h.strip() for h in header]
        folded = [h.casefold() for h in names]
        col = {}
        for i, h in enumerate(folded):
            if h in ALLOWED_COLUMNS:
                col[h] = i
            elif h == "pay_normalizalt":
                col[h] = i
            elif h in (d.casefold() for d in DERIVED_COLUMNS):
                continue
            else:
                ds.rejected_columns.append(names[i])
        for need in ("job_id", "sex", "fte"):
            if need not in col:
                raise IntakeError(f"Hiányzó kötelező oszlop: {need}")
        if "kifizetett_osszes_kezi" not in col and not any(c in col for c in COMPONENTS):
            raise IntakeError("Kell díjazási komponens oszlop vagy kifizetett_osszes_kezi.")
        ds.columns = set(col)
        seq = 0
        for lineno, row in enumerate(reader, start=2):
            if not row or all(not c.strip() for c in row):
                continue
            seq += 1
            if len(row) != len(header):
                raise IntakeError(f"A(z) {lineno}. sor oszlopszáma hibás.")
            try:
                fte = _float(row[col["fte"]])
                comps = {c: _float(row[col[c]]) for c in COMPONENTS if c in col}
                total_cell = _float(row[col["kifizetett_osszes_kezi"]]) if "kifizetett_osszes_kezi" in col else None
                perf_cell = _float(row[col["teljesitmenysav"]]) if "teljesitmenysav" in col else None
                declared_norm = _float(row[col["pay_normalizalt"]]) if "pay_normalizalt" in col else None
            except ValueError:
                raise IntakeError(f"A(z) {lineno}. sor valamelyik számmezője nem szám.") from None
            present = [v for v in comps.values() if v is not None]
            total = sum(present) if present else total_cell
            if total is None or total <= 0 or any(v < 0 for v in present):
                raise IntakeError(f"A(z) {lineno}. sor díjazása hiányzik, nem pozitív vagy negatív komponenst tartalmaz.")
            ds.headcount_all += 1
            ds.sum_total_all += total
            sx = row[col["sex"]].strip().casefold()
            if sx in _F:
                female = True
            elif sx in _M:
                female = False
            else:
                ds.excluded_other_sex += 1
                continue
            if fte is None or not (0.0 < fte <= 1.0):
                ds.invalid_fte_rows += 1
                continue
            norm = total / fte
            ds.rows.append(Row(
                idx=seq, job=row[col["job_id"]].strip(), female=female, fte=fte, total=total, norm=norm,
                base_norm=(comps["alapber"] / fte if comps.get("alapber") is not None else None),
                var_norm=((comps.get("valtozo_bonusz") or 0.0) / fte if "valtozo_bonusz" in col else None),
                perf=(int(perf_cell) if perf_cell is not None and float(perf_cell).is_integer() else None),
                declared_norm=declared_norm))
    return ds
