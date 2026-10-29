"""A 24 kontroll értékelése. Minden függvény egy `Outcome`-ot ad; a motor ellenőrzi a bizonyítékszint-plafont.

Státuszok:
  MET             – az adatból vagy az eredményből számolva teljesül (bizonyíték: COMPUTED_MEASURED)
  NOT_MET         – számolva vagy a nyilatkozat tartalma szerint nem teljesül (NONCOMPLIANCE a katalógushoz képest)
  DECLARED_ONLY   – formailag teljesül, de csak a szervezet nyilatkozata alapján; a motor nem tudja igazolni (DECLARED)
  NOT_ASSESSABLE  – a szükséges bemenet hiányzik (UNVERIFIABLE); a `needs` felsorolja, mi kell
  MANUAL_REVIEW   – emberi mérlegelés kell; a számolt szűrés csatolva, de a semlegességet nem igazolja

A „teljesül” nem jogi minősítés: a katalógus kontrollcéljához képesti állapotot jelenti.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math
import statistics
from dataclasses import dataclass, field

from .catalogue import (ANNUAL_DAYS, BY_ID, CORRECTION_MONTHS, EXPIRY_REQUIRED_TYPES, INFO_REQUEST_MONTHS,
                        REPORTING_SCHEDULE, REPORTING_SOURCE, TRIGGER_GAP)
from .indicators import (floor_count, grade_map, job_female_share, mean_gap_fast, mean_gap_naive,
                         median_gap_fast, median_gap_naive)
from .inputs import Config, Dataset, add_months, parse_date, IntakeError

MET, NOT_MET, DECLARED_ONLY, NOT_ASSESSABLE, MANUAL = "MET", "NOT_MET", "DECLARED_ONLY", "NOT_ASSESSABLE", "MANUAL_REVIEW"
LEVEL_FOR = {MET: "COMPUTED_MEASURED", NOT_MET: None, DECLARED_ONLY: "DECLARED", NOT_ASSESSABLE: "UNVERIFIABLE", MANUAL: None}
EIGE_MAIN = ["SKILLS"] * 5 + ["RESPONSIBILITY"] * 4 + ["EFFORT"] * 3 + ["WORKING_CONDITIONS"] * 2
FOUR_MAIN = ["SKILLS", "RESPONSIBILITY", "EFFORT", "WORKING_CONDITIONS"]


@dataclass
class Ctx:
    ds: Dataset
    cfg: Config
    decl: dict
    audit_date: dt.date
    indicators: dict
    result: dict | None = None
    input_reality: str = "SYNTHETIC"
    cache: dict = field(default_factory=dict)

    @property
    def k(self) -> int:
        return self.cfg.min_cell

    def d(self, *path, default=None):
        node = self.decl
        for p in path:
            if not isinstance(node, dict) or p not in node:
                return default
            node = node[p]
        return node


@dataclass
class Outcome:
    status: str
    evidence_level: str | None = None
    basis: str = ""
    metrics: dict = field(default_factory=dict)
    findings: list = field(default_factory=list)
    needs: list = field(default_factory=list)
    limitations: list = field(default_factory=list)


def _finding(cid: str, target: str, detail: str, countercheck: str, cls: str = "NONCOMPLIANCE") -> dict:
    return {"classification": cls, "target": target, "requirement": BY_ID[cid][2], "detail": detail, "countercheck": countercheck}


def _need(cid: str, needs: list, basis: str = "A szükséges bemenet nem áll rendelkezésre.") -> Outcome:
    return Outcome(NOT_ASSESSABLE, "UNVERIFIABLE", basis, needs=needs)


def _date(ctx: Ctx, value, what: str):
    try:
        return parse_date(value, what)
    except IntakeError:
        return None


# ================================================================ GOV
def gov_01(ctx: Ctx) -> Outcome:
    g = ctx.d("governance", default={}) or {}
    missing = [k for k in ("owner_role", "raci_ref", "approved_on") if not g.get(k)]
    if missing:
        return _need("GOV-01", [f"governance.{k}" for k in missing])
    d = _date(ctx, g["approved_on"], "governance.approved_on")
    if d is None or d > ctx.audit_date:
        return Outcome(NOT_MET, None, "A jóváhagyás dátuma érvénytelen vagy jövőbeli.",
                       findings=[_finding("GOV-01", "governance.approved_on", "érvénytelen vagy jövőbeli dátum", "Érvényes, múltbeli jóváhagyási dátum igazolása.")])
    age = (ctx.audit_date - d).days
    if age > ANNUAL_DAYS:
        return Outcome(NOT_MET, None, "Az éves vezetői jóváhagyás lejárt.", {"days_since_approval": age},
                       [_finding("GOV-01", "governance.approved_on", f"a jóváhagyás {age} napos, az éves kontroll lejárt", "Friss vezetői jóváhagyás igazolása.")])
    return Outcome(DECLARED_ONLY, "DECLARED", "A felelős, a RACI és az éves jóváhagyás nyilatkozat szerint megvan.",
                   {"days_since_approval": age}, limitations=["A jóváhagyás tényét a motor nem tudja igazolni."])


def gov_02(ctx: Ctx) -> Outcome:
    lr = ctx.d("governance", "legal_review", default={}) or {}
    rep = ctx.d("governance", "representative_involved")
    mins = ctx.d("governance", "minutes_ref")
    missing = []
    if not lr.get("date") or not lr.get("ref"):
        missing.append("governance.legal_review.{date,ref}")
    if rep is None:
        missing.append("governance.representative_involved")
    if not mins:
        missing.append("governance.minutes_ref")
    if missing:
        return _need("GOV-02", missing)
    if rep is False:
        return Outcome(NOT_MET, None, "A munkavállalói képviselet bevonása nem történt meg.",
                       findings=[_finding("GOV-02", "governance.representative_involved", "false", "A képviselet bevonásának jegyzőkönyve.")])
    return Outcome(DECLARED_ONLY, "DECLARED", "A jogi felülvizsgálat és a képviselet bevonása nyilatkozat szerint megtörtént.",
                   limitations=["A jegyzőkönyv tartalmát a motor nem vizsgálja."])


# ================================================================ JOB
NO_SCORING = ["pontozási konfiguráció (scheme és jobs): a futás pontozás nélküli, munkakörönkénti csoportosítással történt"]


def job_01(ctx: Ctx) -> Outcome:
    data_jobs = {r.job for r in ctx.ds.rows}
    no_score = {j for j in data_jobs if j not in ctx.cfg.jobs} if ctx.cfg.scoring else set()
    affected = sum(1 for r in ctx.ds.rows if r.job in no_score)
    cat = ctx.d("job_catalogue")
    metrics = {"jobs_in_data": len(data_jobs), "jobs_without_scoring_levels": len(no_score),
               "workers_in_jobs_without_scoring": floor_count(affected, ctx.k)}
    findings = []
    if no_score:
        findings.append(_finding("JOB-01", "adatfájl munkakör-azonosítói", f"{len(no_score)} munkakörnek nincs szintlistája a konfigurációban",
                                 "A hiányzó munkakörök pontozási szintjei a konfigurációban."))
    if not isinstance(cat, dict):
        if findings:
            return Outcome(NOT_MET, None, "Az adatban szereplő munkakörök egy része nincs pontozva.", metrics, findings)
        return Outcome(NOT_ASSESSABLE, "UNVERIFIABLE", "A munkakörprofil-nyilvántartás (job_catalogue) nincs megadva.", metrics,
                       needs=["job_catalogue"] + ([] if ctx.cfg.scoring else NO_SCORING),
                       limitations=["A profilok verziózottsága nem ellenőrizhető."] + ([] if ctx.cfg.scoring else ["A pontozottság nem vizsgálható."]))
    bad_profile = {j for j in data_jobs if not isinstance(cat.get(j), dict) or not cat[j].get("profile_version") or not cat[j].get("profile_ref")}
    inactive = {j for j in data_jobs if isinstance(cat.get(j), dict) and cat[j].get("active") is False}
    metrics.update({"jobs_without_versioned_profile": len(bad_profile), "inactive_jobs_with_workers": len(inactive)})
    if bad_profile:
        findings.append(_finding("JOB-01", "job_catalogue", f"{len(bad_profile)} munkakörnek nincs verziózott profilja", "A munkakörprofilok verziószámmal és hivatkozással."))
    if inactive:
        findings.append(_finding("JOB-01", "job_catalogue.active", f"{len(inactive)} inaktívként jelölt munkakörben vannak munkavállalók", "A munkakör státuszának tisztázása."))
    if findings:
        return Outcome(NOT_MET, None, "A katalógus-egyezés nem teljes.", metrics, findings)
    return Outcome(MET, "COMPUTED_MEASURED", "Minden adatbeli munkakör pontozott, verziózott profillal rendelkező, aktív munkakör.", metrics,
                   limitations=["A profilok tartalmi megfelelését a motor nem vizsgálja."])


def _main_map(ctx: Ctx):
    n = len(ctx.cfg.weights)
    fm = ctx.d("job_evaluation", "factor_map")
    if isinstance(fm, list) and len(fm) == n and all(x in FOUR_MAIN for x in fm):
        return fm
    if n == 14:
        return EIGE_MAIN
    if n == 4:
        return FOUR_MAIN
    return None


def job_02(ctx: Ctx) -> Outcome:
    if not ctx.cfg.scoring:
        return _need("JOB-02", NO_SCORING)
    fmap = _main_map(ctx)
    if fmap is None:
        return _need("JOB-02", ["job_evaluation.factor_map (a súlyok főfaktor-hozzárendelése)"],
                     "A súlyok száma nem 4 vagy 14, a főfaktor-hozzárendelés kell.")
    per = {f: sum(w for w, g in zip(ctx.cfg.weights, fmap) if g == f) for f in FOUR_MAIN}
    metrics = {"main_factor_weights": {f: round(v, 6) for f, v in per.items()}}
    findings = []
    for f, v in per.items():
        if v <= 0:
            findings.append(_finding("JOB-02", f"scheme.weights ({f})", "a főfaktor súlya nulla", "Nem nulla súly a főfaktorra, vagy a kihagyás dokumentált indoklása."))
    zero_cells = [(j, i) for j, lv in ctx.cfg.jobs.items() for i, x in enumerate(lv) if x == 0]
    reasons = ctx.d("job_evaluation", "zero_level_reasons")
    metrics["zero_level_cells"] = len(zero_cells)
    if zero_cells:
        if not isinstance(reasons, dict):
            if not findings:
                return Outcome(NOT_ASSESSABLE, "UNVERIFIABLE", "A 0 szintekhez indoklás kell (zero_level_reasons).", metrics,
                               needs=["job_evaluation.zero_level_reasons"])
        else:
            lack = [1 for j, i in zero_cells if not (isinstance(reasons.get(j), dict) and str(reasons[j].get(str(i), "")).strip())]
            metrics["zero_level_cells_without_reason"] = len(lack)
            if lack:
                findings.append(_finding("JOB-02", "job_evaluation.zero_level_reasons", f"{len(lack)} 0 szintnek nincs indoklása",
                                         "Minden 0 szinthez kimondott indok (nem üres mező)."))
    thr = ctx.d("job_evaluation", "dominance_threshold", default=0.7)
    shares = job_female_share(ctx.ds.rows)
    groups = {"female_dominated": [], "male_dominated": [], "mixed": []}
    for j, (nf, nm) in shares.items():
        if j not in ctx.cfg.jobs:
            continue
        s = nf / (nf + nm)
        groups["female_dominated" if s >= thr else "male_dominated" if s <= 1 - thr else "mixed"].append(j)
    tbl = {}
    for gname, jobs in groups.items():
        if not jobs:
            tbl[gname] = None
            continue
        tbl[gname] = {"jobs": len(jobs)}
        for f in FOUR_MAIN:
            idx = [i for i, g in enumerate(fmap) if g == f]
            vals = [sum(ctx.cfg.jobs[j][i] / ctx.cfg.level_max[i] for i in idx) / len(idx) for j in jobs]
            tbl[gname][f] = round(statistics.fmean(vals), 4)
    metrics["dominance_threshold"] = thr
    metrics["mean_level_share_by_dominance"] = tbl
    lim = ["A nődomináns/férfidomináns küszöb a nyilatkozatból vagy az alapértelmezett 0,7 (feltevés).",
           "A szintek tartalmi helyességét a motor nem vizsgálja."]
    if findings:
        return Outcome(NOT_MET, None, "A főfaktor-lefedettség vagy a 0 szintek indoklása hiányos.", metrics, findings, limitations=lim)
    return Outcome(MET, "COMPUTED_MEASURED", "Mind a négy főfaktor súlyozott, a 0 szintek indokoltak.", metrics, limitations=lim)


def job_03(ctx: Ctx) -> Outcome:
    if not ctx.cfg.scoring:
        return _need("JOB-03", NO_SCORING)
    log = ctx.d("scoring_log")
    if not isinstance(log, dict) or not isinstance(log.get("raters"), dict):
        return _need("JOB-03", ["scoring_log.raters (munkakörönként az értékelők szintlistái)"])
    jobs = list(ctx.cfg.jobs)
    raters = log["raters"]
    rationale = log.get("rationale_documented", {}) if isinstance(log.get("rationale_documented"), dict) else {}
    dual = [j for j in jobs if isinstance(raters.get(j), list) and len(raters[j]) >= 2]
    agree_cells = within1 = cells = outside = 0
    for j in dual:
        for i in range(len(ctx.cfg.weights)):
            vals = [r[i] for r in raters[j] if isinstance(r, list) and len(r) == len(ctx.cfg.weights)]
            if len(vals) < 2:
                continue
            cells += 1
            agree_cells += len(set(vals)) == 1
            within1 += (max(vals) - min(vals)) <= 1
            if not (min(vals) <= ctx.cfg.jobs[j][i] <= max(vals)):
                outside += 1
    documented = sum(1 for j in jobs if rationale.get(j) is True)
    n = len(jobs)
    sample_size = max(1, math.ceil(0.10 * n))
    order = sorted(jobs, key=lambda j: hashlib.sha256(("újrapontozás|" + j).encode("utf-8")).hexdigest())
    metrics = {"jobs": n, "dual_scored_share": round(len(dual) / n, 4), "exact_agreement_share": None if not cells else round(agree_cells / cells, 4),
               "within_one_level_share": None if not cells else round(within1 / cells, 4), "consensus_outside_rater_range_cells": outside,
               "rationale_documented_share": round(documented / n, 4), "rescoring_sample_size": sample_size, "rescoring_sample_jobs": order[:sample_size]}
    findings = []
    if len(dual) < n:
        findings.append(_finding("JOB-03", "scoring_log.raters", f"{n - len(dual)} munkakör nincs legalább két értékelővel pontozva", "Kettős vagy kalibrált pontozás igazolása."))
    if outside:
        findings.append(_finding("JOB-03", "scoring_log.raters", f"{outside} konszenzus-szint kívül esik az értékelők tartományán", "A konszenzus indoklása."))
    if documented < n:
        findings.append(_finding("JOB-03", "scoring_log.rationale_documented", f"{n - documented} munkakörnél nincs dokumentált indoklás", "Az indoklások rögzítése."))
    lim = ["Az újrapontozási minta (a munkakörök 10%-a, determinisztikusan kijelölve) elvégzése emberi feladat."]
    if findings:
        return Outcome(NOT_MET, None, "A pontozási napló nem teljes vagy ellentmondásos.", metrics, findings, limitations=lim)
    return Outcome(DECLARED_ONLY, "DECLARED", "A pontozási napló belsőleg konzisztens: kettős pontozás, indoklás, a konszenzus az értékelői tartományon belül.",
                   metrics, limitations=lim + ["A napló valódiságát a motor nem tudja igazolni."])


def job_04(ctx: Ctx) -> Outcome:
    v = ctx.d("job_evaluation", "feor_reference_only")
    if v is None:
        return _need("JOB-04", ["job_evaluation.feor_reference_only"])
    if v is False:
        return Outcome(NOT_MET, None, "A FEOR/ESCO automatikus értékként szerepel.",
                       findings=[_finding("JOB-04", "job_evaluation.feor_reference_only", "false", "A rendszerszabály módosítása: csak referencia.")])
    return Outcome(DECLARED_ONLY, "DECLARED", "A FEOR/ESCO nyilatkozat szerint csak referencia.", limitations=["A rendszerszabályt a motor nem ellenőrzi."])


# ================================================================ PAY
def pay_01(ctx: Ctx) -> Outcome:
    ds = ctx.ds
    declared_elems = ctx.d("pay_elements")
    rec = ctx.d("reconciliation")
    findings, metrics = [], {}
    if ds.total_compared_rows:
        metrics["rows_total_vs_components_compared"] = ds.total_compared_rows
        metrics["rows_total_differs_from_component_sum"] = floor_count(ds.total_mismatch_rows, ctx.k)
        if ds.total_mismatch_rows:
            findings.append(_finding("PAY-01", "adatfájl, összes díjazás oszlop × komponensek",
                                     f"{floor_count(ds.total_mismatch_rows, ctx.k)} sorban az összes díjazás nem egyezik a komponensek összegével"
                                     + (" (mindegyikben: összes = komponensösszeg × fte, vagyis valamelyik oszlop már FTE-skálázott)"
                                        if ds.total_equals_components_times_fte == ds.total_mismatch_rows else ""),
                                     "Az összes díjazás és a komponensek egyeztetése (minden elem integrálása az összegbe)."))
    if declared_elems is None and not isinstance(rec, dict):
        if findings:
            return Outcome(NOT_MET, None, "A díjazás elemei nincsenek az összes díjazásba integrálva.", metrics, findings)
        return Outcome(NOT_ASSESSABLE, "UNVERIFIABLE", "A deklarációk (pay_elements, reconciliation) hiányoznak; a fájlon belüli összeg–komponens egyezés"
                       + (" rendben van." if metrics else " nem vizsgálható."), metrics, needs=["pay_elements", "reconciliation.{headcount,gross_total}"])
    if isinstance(declared_elems, list):
        missing = [e for e in declared_elems if e not in ds.columns]
        metrics["declared_elements"] = len(declared_elems)
        metrics["declared_elements_not_in_data"] = len(missing)
        if missing:
            findings.append(_finding("PAY-01", "pay_elements", f"{len(missing)} deklarált díjazási elem nincs az adatban", "Minden díjazási elem integrálása az adatba."))
    if isinstance(rec, dict) and rec.get("headcount") is not None and rec.get("gross_total") is not None:
        tol = 0.5 * ds.headcount_all
        diff = ds.sum_total_all - float(rec["gross_total"])
        metrics.update({"headcount_file": ds.headcount_all, "headcount_declared": rec["headcount"], "gross_difference_abs": round(diff, 2),
                        "rounding_tolerance_abs": tol})
        if ds.headcount_all != rec["headcount"]:
            findings.append(_finding("PAY-01", "reconciliation.headcount", "a fájl létszáma eltér a bérszámfejtési létszámtól", "A létszámeltérés magyarázata."))
        if abs(diff) > tol:
            findings.append(_finding("PAY-01", "reconciliation.gross_total", "a bruttó összeg eltér a főkönyvi összegtől a kerekítési tűrésen túl", "Az eltérés tételes magyarázata."))
    elif isinstance(rec, dict):
        return _need("PAY-01", ["reconciliation.headcount", "reconciliation.gross_total"])
    if findings:
        return Outcome(NOT_MET, None, "A díjazás integráltsága vagy a bérszámfejtési egyeztetés hibás.", metrics, findings)
    if not metrics:
        return _need("PAY-01", ["pay_elements", "reconciliation"])
    return Outcome(MET, "COMPUTED_MEASURED", "A deklarált elemek az adatban vannak, és az összeg egyezik a deklarált bérszámfejtési összeggel.", metrics,
                   limitations=["A bérszámfejtési és főkönyvi összeg a szervezet állítása, azt a motor nem ellenőrzi."])


def pay_02(ctx: Ctx) -> Outcome:
    ds = ctx.ds
    findings = []
    mism = double = 0
    compared = 0
    for r in ds.rows:
        if r.declared_norm is not None:
            compared += 1
            if abs(r.declared_norm - r.norm) > max(1.0, 1e-6 * r.norm):
                mism += 1
                if abs(r.declared_norm - r.total / (r.fte ** 2)) <= max(1.0, 1e-6 * r.norm) and r.fte != 1.0:
                    double += 1
    part_time = sum(1 for r in ds.rows if r.fte < 1.0)
    metrics = {"rows_with_invalid_fte": floor_count(ds.invalid_fte_rows, ctx.k), "part_time_workers": floor_count(part_time, ctx.k),
               "declared_normalized_compared": compared, "declared_normalized_mismatch": floor_count(mism, ctx.k),
               "double_normalization_pattern": floor_count(double, ctx.k)}
    metrics["pay_basis"] = ds.pay_basis
    metrics["rows_total_equals_components_times_fte"] = floor_count(ds.total_equals_components_times_fte, ctx.k)
    if ds.pay_basis == "components" and ds.total_equals_components_times_fte:
        findings.append(_finding("PAY-02", "adatfájl, összes díjazás × komponensek × fte",
                                 "az összes díjazás és a komponensek összege között FTE-szorzós összefüggés van: a komponensek vagy az összeg már FTE-skálázott, így a normalizálás kétszeres lehet",
                                 "A díjazási alap tisztázása (a komponensek teljes munkaidős vagy tényleges összegek-e), majd az újraszámítás."))
    if ds.invalid_fte_rows:
        findings.append(_finding("PAY-02", "adatfájl, fte oszlop", "a munkaidő-szorzó 0 vagy 1 feletti / érvénytelen sorok vannak", "Érvényes munkaidő-szorzók (0 < fte ≤ 1)."))
    if mism:
        findings.append(_finding("PAY-02", "adatfájl, pay_normalizalt oszlop", "a normalizált összeg nem egyezik az újraszámolt (összeg / fte) értékkel"
                                 + (" (kétszeres normalizálás mintázata)" if double else ""), "A normalizálás pontosan egyszeri végrehajtása."))
    if findings:
        return Outcome(NOT_MET, None, "A normalizálás újraszámítása hibát talált.", metrics, findings)
    doc = ctx.d("normalization", default={}) or {}
    org = ctx.d("organisation", default={}) or {}
    needs = []
    if doc.get("documented") is not True or not doc.get("ref"):
        needs.append("normalization.{documented,ref}")
    for k in ("absence_rule",):
        if not doc.get(k):
            needs.append(f"normalization.{k}")
    for k in ("period", "currency"):
        if not org.get(k):
            needs.append(f"organisation.{k}")
    if needs:
        return Outcome(NOT_ASSESSABLE, "UNVERIFIABLE", "Az újraszámítás rendben van, a normalizálás dokumentációja nincs megadva.", metrics, needs=needs)
    return Outcome(MET, "COMPUTED_MEASURED", "Az FTE érvényes, a normalizálás újraszámítva egyezik, a dokumentáció megadva.", metrics,
                   limitations=["A dokumentáció tartalmát a motor nem vizsgálja."])


def pay_03(ctx: Ctx) -> Outcome:
    bands = ctx.d("pay_bands")
    crit = ctx.d("pay_policy", "progression_criteria", default={}) or {}
    if not isinstance(bands, list) or not bands:
        return _need("PAY-03", ["pay_bands"])
    findings = []
    grades = [b.get("grade") for b in bands if isinstance(b, dict)]
    bad = [b for b in bands if not (isinstance(b, dict) and isinstance(b.get("min"), (int, float)) and isinstance(b.get("max"), (int, float))
                                    and 0 < b["min"] <= b["max"])]
    metrics = {"bands": len(bands), "bands_invalid": len(bad), "duplicate_grades": len(grades) - len(set(grades))}
    if bad:
        findings.append(_finding("PAY-03", "pay_bands", f"{len(bad)} bérsáv min > max vagy nem pozitív", "Érvényes bérsávtábla."))
    if len(grades) != len(set(grades)):
        findings.append(_finding("PAY-03", "pay_bands.grade", "ismétlődő besorolási szint", "Egyedi szintek."))
    if findings:
        return Outcome(NOT_MET, None, "A bérsávtábla belsőleg hibás.", metrics, findings)
    if not crit.get("ref") or not crit.get("accessible_since"):
        return Outcome(NOT_ASSESSABLE, "UNVERIFIABLE", "A bérsávtábla rendben van, a fejlődési kritérium hozzáférhetősége nincs megadva.", metrics,
                       needs=["pay_policy.progression_criteria.{ref,accessible_since}"])
    return Outcome(DECLARED_ONLY, "DECLARED", "A bérsáv és a fejlődési kritérium nyilatkozat szerint hozzáférhető.", metrics,
                   limitations=["A munkavállalói próbakérelmet (hozzáférhetőség) emberi feladat elvégezni."])


# ================================================================ OBJ
def _justification_rows(ctx: Ctx) -> dict[int, dict]:
    out = {}
    for j in ctx.d("justifications", default=[]) or []:
        if isinstance(j, dict) and isinstance(j.get("row"), int):
            out[j["row"]] = j
    return out


def _complete(j: dict) -> bool:
    return all(j.get(k) not in (None, "") for k in ("type", "source", "decision_year", "rule_ref"))


def obj_01(ctx: Ctx) -> Outcome:
    bands, cat = ctx.d("pay_bands"), ctx.d("job_catalogue")
    if not isinstance(bands, list) or not isinstance(cat, dict):
        return _need("OBJ-01", ["pay_bands", "job_catalogue.<munkakör>.grade"])
    band_of = {b.get("grade"): b for b in bands if isinstance(b, dict)}
    jr = _justification_rows(ctx)
    off = peer = uncovered = 0
    unmapped = 0
    peer_pct = ctx.d("pay_policy", "peer_deviation_pct")
    medians = {}
    if isinstance(peer_pct, (int, float)):
        by = {}
        for r in ctx.ds.rows:
            by.setdefault(r.job, []).append(r.norm)
        medians = {j: statistics.median(v) for j, v in by.items() if len(v) >= ctx.k}
    for r in ctx.ds.rows:
        g = cat.get(r.job, {}).get("grade") if isinstance(cat.get(r.job), dict) else None
        b = band_of.get(g)
        flagged = False
        if b is None:
            unmapped += 1
        elif r.norm < b["min"] or r.norm > b["max"]:
            off += 1
            flagged = True
        if isinstance(peer_pct, (int, float)) and r.job in medians and abs(r.norm - medians[r.job]) / medians[r.job] > peer_pct / 100.0:
            peer += 1
            flagged = True
        if flagged and not (r.idx in jr and _complete(jr[r.idx])):
            uncovered += 1
    metrics = {"workers_off_band": floor_count(off, ctx.k), "workers_unmapped_to_band": floor_count(unmapped, ctx.k),
               "workers_with_peer_deviation": floor_count(peer, ctx.k) if isinstance(peer_pct, (int, float)) else None,
               "flagged_without_complete_justification_record": floor_count(uncovered, ctx.k), "justification_records": len(jr)}
    lim = ["A munkavállalói szintű eltérés-jelzés a bérsáv (teljes munkaidős havi bruttó) és a FTE-normalizált bér összevetése.",
           "A rekordok tartalmi megfelelését célzott mintavétel dönti el (emberi feladat)."]
    if not isinstance(peer_pct, (int, float)):
        lim.append("A peer-eltérés küszöbe (pay_policy.peer_deviation_pct) nincs megadva, ezért nem vizsgált.")
    if unmapped:
        return Outcome(NOT_ASSESSABLE, "UNVERIFIABLE", "Egyes munkavállalók munkaköréhez nincs bérsáv rendelve.", metrics,
                       needs=["job_catalogue.<munkakör>.grade és a hozzá tartozó pay_bands"], limitations=lim)
    if uncovered:
        return Outcome(NOT_MET, None, "Sávon kívüli vagy peer-eltérő díjazás indokrekord nélkül.", metrics,
                       [_finding("OBJ-01", "adatfájl × pay_bands", "vannak indokrekord nélküli eltérő díjazások", "Az eltérésekhez teljes indokrekord (típus, forrás, év, szabály).")], limitations=lim)
    return Outcome(MET, "COMPUTED_MEASURED", "Minden sávon kívüli (és, ha vizsgált, peer-eltérő) díjazáshoz teljes indokrekord tartozik, vagy nincs ilyen.", metrics, limitations=lim)


def obj_02(ctx: Ctx) -> Outcome:
    recs = ctx.d("justifications")
    if recs is None and not ctx.d("justifications_declared_complete"):
        return _need("OBJ-02", ["justifications (vagy justifications_declared_complete)"])
    recs = recs or []
    need_exp = [j for j in recs if isinstance(j, dict) and str(j.get("type", "")).casefold() in EXPIRY_REQUIRED_TYPES]
    no_exp = expired = 0
    for j in need_exp:
        e = _date(ctx, j.get("expires_on"), "justifications.expires_on") if j.get("expires_on") else None
        if e is None:
            no_exp += 1
        elif e < ctx.audit_date:
            expired += 1
    metrics = {"records": len(recs), "records_requiring_expiry": len(need_exp), "without_expiry": floor_count(no_exp, ctx.k), "expired": floor_count(expired, ctx.k)}
    if no_exp or expired:
        f = []
        if no_exp:
            f.append(_finding("OBJ-02", "justifications.expires_on", "vannak lejárat nélküli piaci/megtartási/teljesítményindokok", "Lejárati dátum minden ilyen indokra."))
        if expired:
            f.append(_finding("OBJ-02", "justifications.expires_on", "vannak lejárt indokok", "Az indok megújítása vagy a bér felülvizsgálata."))
        return Outcome(NOT_MET, None, "Lejárat nélküli vagy lejárt indokok.", metrics, f)
    return Outcome(DECLARED_ONLY, "DECLARED", "A deklarált indokrekordok lejárata rendben van.", metrics,
                   limitations=["A rekordok teljességét (hogy minden indok szerepel-e) a motor nem tudja igazolni."])


def _mwu(a: list[float], b: list[float]):
    n1, n2 = len(a), len(b)
    allv = sorted([(v, 0) for v in a] + [(v, 1) for v in b])
    ranks, i = {}, 0
    ties = []
    while i < len(allv):
        j = i
        while j + 1 < len(allv) and allv[j + 1][0] == allv[i][0]:
            j += 1
        avg = (i + j) / 2 + 1
        for t in range(i, j + 1):
            ranks[t] = avg
        ties.append(j - i + 1)
        i = j + 1
    r1 = sum(ranks[t] for t in range(len(allv)) if allv[t][1] == 0)
    u = r1 - n1 * (n1 + 1) / 2
    n = n1 + n2
    var = n1 * n2 / 12.0 * ((n + 1) - sum(t ** 3 - t for t in ties) / (n * (n - 1)))
    if var <= 0:
        return None
    z = (abs(u - n1 * n2 / 2) - 0.5) / math.sqrt(var)
    return z, math.erfc(z / math.sqrt(2))


def obj_03(ctx: Ctx) -> Outcome:
    rows = [r for r in ctx.ds.rows if r.perf is not None]
    if "teljesitmenysav" not in ctx.ds.columns or not rows:
        return _need("OBJ-03", ["adatfájl: teljesitmenysav oszlop"])
    f = [float(r.perf) for r in rows if r.female]
    m = [float(r.perf) for r in rows if not r.female]
    metrics = {"workers_with_rating": floor_count(len(rows), ctx.k)}
    flagged = False
    if len(f) >= ctx.k and len(m) >= ctx.k:
        res = _mwu(f, m)
        metrics.update({"mean_rating_f": round(statistics.fmean(f), 4), "mean_rating_m": round(statistics.fmean(m), 4)})
        if res:
            metrics.update({"mann_whitney_z": round(res[0], 4), "mann_whitney_p_two_sided": round(res[1], 6)})
            flagged = res[1] < 0.05
        metrics["screening_flag"] = flagged
    else:
        metrics["note"] = "kis cella: nemenkénti létszám a cellaminimum alatt, a szűrés nem végezhető"
    lim = ["A statisztikai szűrés nem igazolja a semlegességet, és a kalibrációt sem; a vezetői varianciához nincs adat.",
           "A teljesítményértékelés semlegességét emberi felülvizsgálat dönti el."]
    f_out = [_finding("OBJ-03", "teljesitmenysav eloszlás nemek szerint", "a nemek közötti értékelés-különbség a szűrés szerint szignifikáns", "A különbség magyarázata, a vezetői variancia vizsgálata.", "QUALITY_GAP")] if flagged else []
    return Outcome(MANUAL, None, "Emberi mérlegelés kell; a számolt szűrés csatolva.", metrics, f_out, limitations=lim)


# ================================================================ STA
def sta_01(ctx: Ctx) -> Outcome:
    rows, findings = ctx.ds.rows, []
    pairs = [("mean", mean_gap_fast(rows), mean_gap_naive(rows)), ("median", median_gap_fast(rows), median_gap_naive(rows))]
    if rows and rows[0].var_norm is not None:
        pairs += [("variable_mean", mean_gap_fast(rows, "var_norm"), mean_gap_naive(rows, "var_norm")),
                  ("variable_median", median_gap_fast(rows, "var_norm"), median_gap_naive(rows, "var_norm"))]
    dual_bad = [n for n, a, b in pairs if (a is None) != (b is None) or (a is not None and abs(a - b) > 1e-12)]
    metrics = {"dual_path_indicators_compared": len(pairs), "dual_path_mismatch": len(dual_bad)}
    if dual_bad:
        findings.append(_finding("STA-01", "indikátorok", f"a két független számítási út eltér: {', '.join(dual_bad)}", "A számítás hibájának feltárása.", "TECHNICAL_ERROR"))
    cross = 0
    if ctx.result is not None:
        ours = {c["grade"]: c for c in ctx.indicators["categories"]}
        theirs = {c.get("grade"): c for c in ctx.result.get("categories", []) if isinstance(c, dict)}
        cmp_n = 0
        if set(ours) != set(theirs):
            cross += 1
        for g in set(ours) & set(theirs):
            a, b = ours[g], theirs[g]
            cmp_n += 1
            if a["suppressed"] != b.get("suppressed"):
                cross += 1
            elif not a["suppressed"]:
                if (a["n_f"], a["n_m"]) != (b["n_f"], b["n_m"]) or abs(a["mean_gap"] - b["gap"]) > 2e-6 or abs((a["t"] or 0) - (b["t"] or 0)) > 2e-4:
                    cross += 1
        metrics.update({"result_categories_compared": cmp_n, "result_cross_check_mismatch": cross})
        l1 = ctx.cache.get("l1")
        if l1 is not None:
            metrics["result_l1_verdict"] = l1["verdict"]
        if cross:
            findings.append(_finding("STA-01", "a Bérelemző eredménye × független újraszámítás", f"{cross} eltérés a kategóriánkénti bérrés, létszám vagy t érték között",
                                     "Az eltérés forrásának feltárása (adat, konfiguráció vagy verzió).", "TECHNICAL_ERROR"))
    lim = [] if ctx.result is not None else ["Nincs eredményfájl: a Bérelemző eredményével való kereszt-ellenőrzés nem történt meg."]
    if findings:
        return Outcome(NOT_MET, None, "A számítás nem reprodukálható egyező eredménnyel.", metrics, findings, limitations=lim)
    return Outcome(MET, "COMPUTED_MEASURED", "Az átlag-, medián-, változóbér- és kvartilis-számítás két független úton egyezik"
                   + (", és egyezik a Bérelemző eredményével." if ctx.result is not None else "."), metrics, limitations=lim)


def trigger_states(ctx: Ctx) -> list[dict]:
    """Kategóriánként: T_c, J_c, R_c, O_c, esedékesség. A közös bérértékelési kötelezettség jogi minősítését nem végzi."""
    reg = ctx.d("deviation_register", default=[]) or []
    by_grade: dict[int, list] = {}
    for e in reg:
        if isinstance(e, dict) and isinstance(e.get("grade"), int):
            by_grade.setdefault(e["grade"], []).append(e)
    out = []
    for c in ctx.indicators["categories"]:
        if c["suppressed"]:
            out.append({"grade": c["grade"], "state": "SUPPRESSED"})
            continue
        if not c["t_c"]:
            out.append({"grade": c["grade"], "state": "NOT_TRIGGERED"})
            continue
        j = r = overdue = False
        refs = []
        for e in by_grade.get(c["grade"], []):
            jj = e.get("justification") or {}
            if jj.get("objective") is True and jj.get("evidence_refs") and jj.get("assessment_ref"):
                j = True
                refs += [str(x) for x in jj["evidence_refs"]]
            rm = e.get("remediation") or {}
            rep = _date(ctx, e.get("reported_on"), "deviation_register.reported_on") if e.get("reported_on") else None
            pb = _date(ctx, rm.get("planned_by"), "remediation.planned_by") if rm.get("planned_by") else None
            if rm.get("plan_ref") and pb is not None and rep is not None and pb <= add_months(rep, CORRECTION_MONTHS):
                r = True
                if not rm.get("completed_on") and pb < ctx.audit_date:
                    overdue = True
        state = "TRIGGER_ADDRESSED" if (j or r) else "JOINT_ASSESSMENT_INDICATED"
        out.append({"grade": c["grade"], "state": state, "justified": j, "remediation_planned": r, "remediation_overdue": overdue, "justification_refs": refs})
    return out


def sta_02(ctx: Ctx) -> Outcome:
    states = trigger_states(ctx)
    trig = [s for s in states if s["state"] in ("TRIGGER_ADDRESSED", "JOINT_ASSESSMENT_INDICATED")]
    unaddressed = [s for s in trig if s["state"] == "JOINT_ASSESSMENT_INDICATED"]
    overdue = [s for s in trig if s.get("remediation_overdue")]
    metrics = {"categories_reported": sum(1 for s in states if s["state"] != "SUPPRESSED"), "categories_suppressed": sum(1 for s in states if s["state"] == "SUPPRESSED"),
               "categories_at_or_above_5_percent": len(trig), "addressed_by_justification_or_remediation": len(trig) - len(unaddressed),
               "joint_assessment_indicated": len(unaddressed), "remediation_overdue": len(overdue)}
    if metrics["categories_reported"] == 0:
        return Outcome(NOT_ASSESSABLE, "UNVERIFIABLE", "Egyetlen kategória sem érte el a cellaminimumot, a kategórián belüli rés nem vizsgálható.", metrics,
                       needs=["nagyobb létszám vagy összevonható, pontozott kategóriák (a pontozási konfiguráció)"],
                       limitations=["Az elnyomás védi az egyéneket, de a kategórián belüli 5%-os küszöb ebből az adatból nem értékelhető."])
    if not trig:
        return Outcome(MET, "COMPUTED_MEASURED", "Egyik közölt kategóriában sincs 5% vagy annál nagyobb átlagos bérkülönbség.", metrics,
                       limitations=["Az elnyomott kategóriák állapota nem ismert.", "A küszöbérintés nem jogi minősítés."])
    f = []
    if unaddressed:
        f.append(_finding("STA-02", "kategóriánkénti átlagos bérrés × deviation_register", f"{len(unaddressed)} kategória éri el az 5%-ot, és nincs hozzá kezelt indok vagy hat hónapon belüli korrekciós terv",
                          "Dokumentált objektív indok bizonyítékhivatkozással, vagy hat hónapon belüli korrekciós terv; közös bérértékelés."))
    if overdue:
        f.append(_finding("STA-02", "deviation_register.remediation", f"{len(overdue)} korrekciós terv határideje lejárt teljesítés nélkül", "A korrekció teljesítésének igazolása."))
    if f:
        return Outcome(NOT_MET, None, "Van kezeletlen vagy lejárt 5%-os küszöbérintés.", metrics, f)
    return Outcome(DECLARED_ONLY, "DECLARED", "Minden 5%-ot elérő kategóriához nyilatkozat szerinti indok vagy korrekciós terv tartozik.", metrics,
                   limitations=["Az indok megfelelősége (objektív, nemsemleges) emberi mérlegelést igényel.", "A küszöbérintés nem jogi minősítés."])


def sta_03(ctx: Ctx) -> Outcome:
    cats = ctx.indicators["categories"]
    rep = [c for c in cats if not c["suppressed"]]
    no_unc = [c for c in rep if c["se_log"] is None]
    metrics = {"categories": len(cats), "suppressed": len(cats) - len(rep), "reported_without_uncertainty_measure": len(no_unc), "min_cell": ctx.k}
    if ctx.result is not None and ctx.cache.get("l1"):
        metrics["result_l1_verdict"] = ctx.cache["l1"]["verdict"]
        if ctx.cache["l1"]["verdict"] != "NO_FAILURES":
            return Outcome(NOT_MET, None, "A Bérelemző eredménye az L1 ellenőrzésen nem ment át.", metrics,
                           [_finding("STA-03", "a Bérelemző eredménye", "az L1 ellenőrzés hibát jelzett", "Az L1 megállapítások kezelése.", "TECHNICAL_ERROR")])
    if no_unc:
        return Outcome(NOT_MET, None, "Közölt kategóriában hiányzik a bizonytalansági mutató.", metrics,
                       [_finding("STA-03", "kategóriamutatók", "hiányzó standard hiba", "Bizonytalansági mutató minden közölt kategóriához.")])
    return Outcome(MET, "COMPUTED_MEASURED", "A kis cellák elnyomottak, a közölt kategóriák bizonytalansági mutatóval szerepelnek.", metrics)


# ================================================================ TRN
def trn_01(ctx: Ctx) -> Outcome:
    t = ctx.d("transparency", default={}) or {}
    ads = t.get("job_ads")
    ban = t.get("pay_history_question_banned")
    needs = []
    if not isinstance(ads, dict) or "total" not in ads or "with_pay_range" not in ads:
        needs.append("transparency.job_ads.{total,with_pay_range}")
    if ban is None:
        needs.append("transparency.pay_history_question_banned")
    if needs:
        return _need("TRN-01", needs)
    f = []
    share = (ads["with_pay_range"] / ads["total"]) if ads["total"] else 1.0
    metrics = {"job_ads_total": ads["total"], "job_ads_with_pay_range_share": round(share, 4)}
    if share < 1.0:
        f.append(_finding("TRN-01", "transparency.job_ads", "nem minden hirdetés közli a bérsávot", "Minden hirdetés bérsávval."))
    if ban is False:
        f.append(_finding("TRN-01", "transparency.pay_history_question_banned", "false", "A bértörténeti kérdés tilalmának bevezetése."))
    if f:
        return Outcome(NOT_MET, None, "A felvételi közlés vagy a bértörténeti kérdés tilalma hiányos.", metrics, f)
    return Outcome(DECLARED_ONLY, "DECLARED", "A hirdetések bérsávval jelennek meg, a bértörténeti kérdés tilos, nyilatkozat szerint.", metrics,
                   limitations=["A hirdetés- és interjúmintát emberi feladat vizsgálni."])


def trn_02(ctx: Ctx) -> Outcome:
    reqs = ctx.d("info_requests")
    if reqs is None and not ctx.d("info_requests_declared_complete"):
        return _need("TRN-02", ["info_requests (vagy info_requests_declared_complete)"])
    reqs = reqs or []
    late = overdue = 0
    days = []
    for r in reqs:
        if not isinstance(r, dict):
            continue
        rec = _date(ctx, r.get("received"), "info_requests.received")
        ans = _date(ctx, r.get("answered"), "info_requests.answered") if r.get("answered") else None
        if rec is None:
            continue
        due = add_months(rec, INFO_REQUEST_MONTHS)
        if ans is not None:
            days.append((ans - rec).days)
            late += ans > due
        elif due < ctx.audit_date:
            overdue += 1
    metrics = {"requests": len(reqs), "answered_late": late, "unanswered_past_deadline": overdue,
               "median_days_to_answer": None if not days else statistics.median(days)}
    if late or overdue:
        return Outcome(NOT_MET, None, "Van két hónapon túli vagy megválaszolatlan információkérés.", metrics,
                       [_finding("TRN-02", "info_requests", f"{late} késve megválaszolt és {overdue} lejárt, megválaszolatlan kérés", "A határidők betartásának folyamata.")])
    return Outcome(DECLARED_ONLY, "DECLARED", "A deklarált információkérések mind két hónapon belül megválaszoltak.", metrics,
                   limitations=["A napló teljességét a motor nem tudja igazolni."])


def trn_03(ctx: Ctx) -> Outcome:
    t = ctx.d("transparency", default={}) or {}
    if not t.get("annual_notice_on") or t.get("criteria_accessible") is None:
        return _need("TRN-03", ["transparency.annual_notice_on", "transparency.criteria_accessible"])
    d = _date(ctx, t["annual_notice_on"], "transparency.annual_notice_on")
    if d is None or d > ctx.audit_date or (ctx.audit_date - d).days > ANNUAL_DAYS or t["criteria_accessible"] is False:
        return Outcome(NOT_MET, None, "Az éves tájékoztatás lejárt, érvénytelen, vagy a bérkritérium nem hozzáférhető.", {"criteria_accessible": t["criteria_accessible"]},
                       [_finding("TRN-03", "transparency", "elavult tájékoztatás vagy nem hozzáférhető kritérium", "Friss közlési bizonyíték.")])
    return Outcome(DECLARED_ONLY, "DECLARED", "Az éves tájékoztatás friss, a bérkritérium hozzáférhető, nyilatkozat szerint.", {"days_since_notice": (ctx.audit_date - d).days},
                   limitations=["A közlési bizonyítékot a motor nem látja."])


# ================================================================ REP
def rep_01(ctx: Ctx) -> Outcome:
    org = ctx.d("organisation", default={}) or {}
    hc = ctx.ds.headcount_all
    band = next((s for s in REPORTING_SCHEDULE if hc >= s["min_headcount"] and (s["max_headcount"] is None or hc <= s["max_headcount"])), None)
    metrics = {"headcount_file": hc, "headcount_declared": org.get("headcount_declared"), "schedule_source": REPORTING_SOURCE}
    if band is None:
        return Outcome(NOT_ASSESSABLE, "UNVERIFIABLE", "A létszám a jelentési táblázat küszöbei alatt van.", metrics,
                       needs=["a jelentési kötelezettség jogi megállapítása"], limitations=["A magyar átültetés állapota nem ellenőrzött; a tagállami küszöbök eltérhetnek."])
    first = parse_date(band["first_report"], "first_report")
    metrics.update({"schedule_band": f"{band['min_headcount']}+" if band["max_headcount"] is None else f"{band['min_headcount']}–{band['max_headcount']}",
                    "first_report": band["first_report"], "then": band["then"], "days_until_first_report": (first - ctx.audit_date).days})
    rep = ctx.d("reporting", default={}) or {}
    lim = ["A jelentési ütemezés a tudásbázisból származik, REVIEW_REQUIRED; a magyar átültetés állapota nem ellenőrzött.",
           "Önkéntes pilotnál a határidők tájékoztató jellegűek."]
    if not rep.get("calendar_ref") or not rep.get("owner_role"):
        return Outcome(NOT_ASSESSABLE, "UNVERIFIABLE", "A jelentési naptár és a felelős nincs megadva.", metrics, needs=["reporting.{calendar_ref,owner_role}"], limitations=lim)
    return Outcome(DECLARED_ONLY, "DECLARED", "A jelentési naptár és a felelős nyilatkozat szerint megvan.", metrics, limitations=lim)


def rep_02(ctx: Ctx) -> Outcome:
    ja = ctx.d("joint_assessment", default={}) or {}
    indicated = sum(1 for s in trigger_states(ctx) if s["state"] == "JOINT_ASSESSMENT_INDICATED")
    metrics = {"joint_assessment_indicated_categories": indicated}
    if ja.get("procedure_ref") and ja.get("template_ref"):
        return Outcome(DECLARED_ONLY, "DECLARED", "A közös bérértékelés eljárása és a korrekciós terv sablonja nyilatkozat szerint megvan.", metrics,
                       limitations=["Az eljárás gyakorlatát (triggergyakorlat) emberi feladat kipróbálni."])
    if indicated:
        return Outcome(NOT_MET, None, "Van közös bérértékelést indokló kategória, de nincs eljárás vagy sablon.", metrics,
                       [_finding("REP-02", "joint_assessment", "hiányzó eljárás vagy sablon", "A közös bérértékelés eljárása és a korrekciós terv sablonja.")])
    return _need("REP-02", ["joint_assessment.{procedure_ref,template_ref}"])


# ================================================================ DPR
def dpr_01(ctx: Ctx) -> Outcome:
    rej = ctx.ds.rejected_columns
    extra = sorted(c for c in ctx.ds.columns if c not in ("job_id", "sex", "fte", "alapber", "rendszeres_potlek", "valtozo_bonusz", "termeszetbeni", "tulora", "kifizetett_osszes_kezi", "pay_normalizalt"))
    metrics = {"non_whitelisted_columns": len(rej), "optional_personal_columns_present": extra}
    if rej:
        return Outcome(NOT_MET, None, "Az adatfájl nem engedélyezett oszlopokat tartalmazott; az értékeiket a motor nem olvasta ki.", metrics,
                       [_finding("DPR-01", "adatfájl fejléce", f"nem engedélyezett oszlopnevek: {', '.join(rej)}", "Az adatfájl újragenerálása a fehérlistás oszlopokkal.")])
    dp = ctx.d("data_protection", default={}) or {}
    needs = [f"data_protection.{k}" for k in ("access_matrix_ref", "purpose_ref") if not dp.get(k)]
    if not isinstance(dp.get("retention_days"), int) or dp.get("retention_days", 0) <= 0:
        needs.append("data_protection.retention_days")
    if needs:
        return Outcome(NOT_ASSESSABLE, "UNVERIFIABLE", "Az adatfájl fehérlistás, a hozzáférési mátrix, a cél és a megőrzés nincs megadva.", metrics, needs=needs)
    return Outcome(DECLARED_ONLY, "DECLARED", "Az adatfájl fehérlistás; a hozzáférési mátrix, a cél és a megőrzés nyilatkozat szerint megvan.", metrics,
                   limitations=["A jogosultságmintát emberi feladat vizsgálni."])


def dpr_02(ctx: Ctx) -> Outcome:
    cats = ctx.indicators["categories"]
    grade_of_job = grade_map(ctx.ds.rows, ctx.cfg)
    sup_grades = {c["grade"] for c in cats if c["suppressed"]}
    in_scope = [r for r in ctx.ds.rows if r.job in grade_of_job]
    in_sup = sum(1 for r in in_scope if grade_of_job[r.job] in sup_grades)
    share = (in_sup / len(in_scope)) if in_scope else 0.0
    metrics = {"workers_in_suppressed_categories": floor_count(in_sup, ctx.k), "share_in_suppressed_categories": round(share, 4)}
    if in_sup == 0:
        return Outcome(MET, "COMPUTED_MEASURED", "Nincs olyan munkavállaló, akinek a kategóriája elnyomott.", metrics)
    mit = ctx.d("data_protection", "small_group_mitigation")
    if not mit:
        return Outcome(NOT_MET, None, "Az elnyomás miatt egyes munkavállalók kategóriája nem közölhető, és nincs dokumentált kiegészítő megoldás.", metrics,
                       [_finding("DPR-02", "kategóriák elnyomása", f"a munkavállalók {share:.0%}-a elnyomott kategóriában van", "Dokumentált megoldás (pl. szélesebb sávok, összevonás), hogy az információs jog ne ürüljön ki.")])
    return Outcome(DECLARED_ONLY, "DECLARED", "Az elnyomott kategóriákhoz dokumentált kiegészítő megoldás tartozik, nyilatkozat szerint.", metrics,
                   limitations=["A megoldás megfelelőségét adatvédelmi és jogi ellenőrzés dönti el."])


# ================================================================ CHG
def chg_01(ctx: Ctx) -> Outcome:
    ch = ctx.d("change_management", "job_changes")
    if not isinstance(ch, list):
        return _need("CHG-01", ["change_management.job_changes"])
    miss = 0
    for c in ch:
        if not isinstance(c, dict):
            continue
        a = _date(ctx, c.get("changed_on"), "job_changes.changed_on")
        b = _date(ctx, c.get("reevaluated_on"), "job_changes.reevaluated_on") if c.get("reevaluated_on") else None
        if a is None or b is None or b < a:
            miss += 1
    metrics = {"job_changes": len(ch), "without_reevaluation": miss}
    if miss:
        return Outcome(NOT_MET, None, "Van munkakör-változás újraértékelés nélkül.", metrics,
                       [_finding("CHG-01", "change_management.job_changes", f"{miss} változáshoz nincs (érvényes) újraértékelés", "Az újraértékelés elvégzése és rögzítése.")])
    return Outcome(DECLARED_ONLY, "DECLARED", "Minden deklarált munkakör-változást újraértékelés követett.", metrics, limitations=["A változások teljességét a motor nem tudja igazolni."])


def chg_02(ctx: Ctx) -> Outcome:
    cm = ctx.d("change_management", default={}) or {}
    if not cm.get("monitoring_owner_role") or not cm.get("last_update_log_on"):
        return _need("CHG-02", ["change_management.monitoring_owner_role", "change_management.last_update_log_on"])
    d = _date(ctx, cm["last_update_log_on"], "last_update_log_on")
    if d is None or d > ctx.audit_date or (ctx.audit_date - d).days > ANNUAL_DAYS:
        return Outcome(NOT_MET, None, "A jogszabály- és módszertanfigyelés frissítési naplója elavult vagy érvénytelen.", {},
                       [_finding("CHG-02", "change_management.last_update_log_on", "elavult vagy érvénytelen dátum", "Friss frissítési napló.")])
    return Outcome(DECLARED_ONLY, "DECLARED", "A figyelés tulajdonosa és friss frissítési naplója nyilatkozat szerint megvan.", {"days_since_update_log": (ctx.audit_date - d).days},
                   limitations=["A napló tartalmát a motor nem vizsgálja."])


FUNCS = {"GOV-01": gov_01, "GOV-02": gov_02, "JOB-01": job_01, "JOB-02": job_02, "JOB-03": job_03, "JOB-04": job_04,
         "PAY-01": pay_01, "PAY-02": pay_02, "PAY-03": pay_03, "OBJ-01": obj_01, "OBJ-02": obj_02, "OBJ-03": obj_03,
         "STA-01": sta_01, "STA-02": sta_02, "STA-03": sta_03, "TRN-01": trn_01, "TRN-02": trn_02, "TRN-03": trn_03,
         "REP-01": rep_01, "REP-02": rep_02, "DPR-01": dpr_01, "DPR-02": dpr_02, "CHG-01": chg_01, "CHG-02": chg_02}
