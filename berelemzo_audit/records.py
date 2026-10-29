"""Rekordellenőrzők és rekordépítők a bértranszparencia-domain két rekordtípusához (MI-mentes, determinisztikus).

* `validate_job_evaluation`: nemsemleges pont–faktor munkakörértékelés-rekord fegyelme (a munkakört értékeljük, nem a
  személyt): négy főfaktor, 100-ra összegződő súlyok, szintek a skálán belül, a 0 szint indoklása, tartományban lévő
  normalizált pontszám és megnevezett számítási mód, személyes adat tilalma.
* `validate_pay_equity_analysis`: aggregált nemi bérrés-rekord fegyelme: számított érték csak megnevezett módszerrel és
  bizonyítékhivatkozással, cellaminimum, az 5%-os trigger, nincs kiszámított érték UNVERIFIABLE státusszal, nincs
  egyéni szintű bér- vagy azonosító adat, nincs jogi minősítés.

Csak a szerkezetet és a fegyelmet ellenőrzik; a jogi kérdést nem döntik el, és a bérrést nem számolják.
"""

from __future__ import annotations

import math
import re

from .catalogue import MIN_CELL_FLOOR, TRIGGER_GAP

TRIGGER_PERCENT = TRIGGER_GAP * 100.0

# --- munkakörértékelés-rekord
JOB_REQUIRED = {"record_type", "job_id", "job_profile_ref", "evaluates", "factors", "weights", "normalized_score", "score_method", "value_group"}
JOB_EVALUATES = {"JOB"}
JOB_FORBIDDEN = {"employee_name", "employee_id", "person_id", "gender", "sex", "salary", "wage"}
FACTOR_REQUIRED = {"main_factor", "name", "level", "max", "weight"}
MAIN_FACTORS = {"SKILLS", "RESPONSIBILITY", "EFFORT", "WORKING_CONDITIONS"}
WEIGHT_TOTAL = 100.0
TOLERANCE = 1e-6

# --- bérrés-elemzés rekord
PAY_REQUIRED = {"record_type", "comparison_group", "pay_element", "gap_metric", "gap_value", "computation",
                "cohort_counts", "min_cell_size", "adjusted", "threshold_status", "objective_justification_refs",
                "limitations", "countercheck"}
PAY_ELEMENTS = {"BASE", "BONUS", "ALLOWANCE", "IN_KIND", "TOTAL"}
GAP_METRICS = {"MEAN", "MEDIAN", "QUARTILE_DISTRIBUTION", "PROPORTION_ABOVE_MIDPOINT"}
THRESHOLD_STATUS = {"WITHIN_THRESHOLD", "ABOVE_THRESHOLD_REVIEW", "UNVERIFIABLE"}
COMPUTATION_REQUIRED = {"method", "evidence_ref", "input_reality"}
INPUT_REALITIES = {"REAL", "SYNTHETIC", "MIXED"}
COHORT_REQUIRED = {"group", "count"}
PAY_FORBIDDEN = {"employee_name", "employee_id", "person_id", "name", "raw_salary", "individual_salary", "salary",
                 "salaries", "wage", "wages", "pay", "individual_pay", "payroll"}
PAY_FORBIDDEN_TOKENS = {"salary", "salaries", "wage", "wages", "payroll", "fizetes", "fizetés", "ber", "bér", "berek", "bérek"}


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _nonempty(v) -> bool:
    return isinstance(v, str) and bool(v.strip())


def forbidden_key(key) -> bool:
    if not isinstance(key, str):
        return False
    folded = key.casefold()
    return folded in PAY_FORBIDDEN or bool(set(re.split(r"[_\-\s.]+", folded)) & PAY_FORBIDDEN_TOKENS)


def has_forbidden(value) -> bool:
    if isinstance(value, dict):
        return any(forbidden_key(k) or has_forbidden(v) for k, v in value.items())
    if isinstance(value, list):
        return any(has_forbidden(v) for v in value)
    return False


def _job_forbidden(value) -> bool:
    if isinstance(value, dict):
        return any(str(k).casefold() in JOB_FORBIDDEN or _job_forbidden(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_job_forbidden(v) for v in value)
    return False


def validate_job_evaluation(record: dict) -> list[str]:
    if not isinstance(record, dict):
        return ["record must be an object"]
    errors = [f"missing required field: {n}" for n in sorted(JOB_REQUIRED - set(record))]
    if errors:
        return errors
    if record["record_type"] != "job-evaluation":
        errors.append("record_type must be job-evaluation")
    if not isinstance(record["evaluates"], str) or record["evaluates"] not in JOB_EVALUATES:
        errors.append("evaluates must be JOB (the model evaluates the job, not the person)")
    for f in ("job_id", "job_profile_ref", "score_method", "value_group"):
        if not _nonempty(record.get(f)):
            errors.append(f"{f} must be a non-empty string")
    weights = record.get("weights")
    if not isinstance(weights, dict):
        errors.append("weights must be an object mapping each main factor to a percentage")
    else:
        if set(weights) != MAIN_FACTORS:
            errors.append(f"weights must cover exactly {sorted(MAIN_FACTORS)}")
        bad = sorted(str(k) for k, v in weights.items() if not _num(v) or not 0 <= v <= WEIGHT_TOTAL)
        if bad:
            errors.append(f"weights must be finite numbers from 0 to 100: {', '.join(bad)}")
        elif abs(sum(weights.values()) - WEIGHT_TOTAL) > TOLERANCE:
            errors.append("weights must sum to 100")
    factors = record.get("factors")
    seen: set[str] = set()
    if not isinstance(factors, list) or not factors:
        errors.append("factors must be a non-empty list")
    else:
        for i, fct in enumerate(factors):
            if not isinstance(fct, dict):
                errors.append(f"factor[{i}] must be an object")
                continue
            for f in sorted(FACTOR_REQUIRED - set(fct)):
                errors.append(f"factor[{i}] missing {f}")
            if fct.get("main_factor") in MAIN_FACTORS:
                seen.add(fct["main_factor"])
            else:
                errors.append(f"factor[{i}] has an invalid main_factor")
            lvl, mx = fct.get("level"), fct.get("max")
            if not isinstance(mx, int) or isinstance(mx, bool) or mx <= 0:
                errors.append(f"factor[{i}] max must be a positive integer")
            elif not isinstance(lvl, int) or isinstance(lvl, bool) or not 0 <= lvl <= mx:
                errors.append(f"factor[{i}] level must be an integer from 0 to max")
            elif lvl == 0 and not _nonempty(fct.get("reason")):
                errors.append(f"factor[{i}] level 0 requires an explicit reason, not a blank field")
            if not _num(fct.get("weight")) or fct.get("weight", -1) < 0:
                errors.append(f"factor[{i}] weight must be a non-negative number")
        missing = MAIN_FACTORS - seen
        if missing:
            errors.append(f"every main factor must be represented; missing {sorted(missing)}")
    score = record.get("normalized_score")
    if not _num(score) or not 0 <= score <= 100:
        errors.append("normalized_score must be a number in [0, 100]")
    if _job_forbidden(record):
        errors.append("a job evaluation must not contain personal data (name, id, gender, salary)")
    return errors


def validate_pay_equity_analysis(record: dict) -> list[str]:
    if not isinstance(record, dict):
        return ["record must be an object"]
    errors = [f"missing required field: {n}" for n in sorted(PAY_REQUIRED - set(record))]
    if errors:
        return errors
    if record["record_type"] != "pay-equity-analysis":
        errors.append("record_type must be pay-equity-analysis")
    if not isinstance(record["pay_element"], str) or record["pay_element"] not in PAY_ELEMENTS:
        errors.append("invalid pay_element")
    if not isinstance(record["gap_metric"], str) or record["gap_metric"] not in GAP_METRICS:
        errors.append("invalid gap_metric")
    if not isinstance(record["threshold_status"], str) or record["threshold_status"] not in THRESHOLD_STATUS:
        errors.append("invalid threshold_status")
    if not _nonempty(record.get("comparison_group")):
        errors.append("comparison_group must be a non-empty string")
    if not _nonempty(record.get("countercheck")):
        errors.append("countercheck must be a non-empty string")
    if not isinstance(record.get("limitations"), list):
        errors.append("limitations must be a list")
    if not isinstance(record.get("objective_justification_refs"), list):
        errors.append("objective_justification_refs must be a list")
    if not isinstance(record.get("adjusted"), bool):
        errors.append("adjusted must be a boolean")
    min_cell = record.get("min_cell_size")
    if not isinstance(min_cell, int) or isinstance(min_cell, bool) or min_cell < 1:
        errors.append("min_cell_size must be a positive integer")
        min_cell = None
    elif min_cell < MIN_CELL_FLOOR:
        errors.append(f"min_cell_size must be at least the domain floor {MIN_CELL_FLOOR}")
        min_cell = MIN_CELL_FLOOR
    cohorts = record.get("cohort_counts")
    if not isinstance(cohorts, list) or not cohorts:
        errors.append("cohort_counts must be a non-empty list")
    else:
        for i, c in enumerate(cohorts):
            if not isinstance(c, dict):
                errors.append(f"cohort[{i}] must be an object")
                continue
            for f in sorted(COHORT_REQUIRED - set(c)):
                errors.append(f"cohort[{i}] missing {f}")
            n = c.get("count")
            if not isinstance(n, int) or isinstance(n, bool) or n < 0:
                errors.append(f"cohort[{i}] count must be a non-negative integer")
            elif min_cell is not None and 0 < n < min_cell:
                errors.append(f"cohort[{i}] count below min_cell_size must be suppressed, not reported")
    gap = record.get("gap_value")
    comp = record.get("computation")
    cd = comp if isinstance(comp, dict) else {}
    if comp is not None and not isinstance(comp, dict):
        errors.append("computation must be an object")
    if gap is None:
        if record["threshold_status"] != "UNVERIFIABLE":
            errors.append("a null gap_value requires threshold_status UNVERIFIABLE")
    elif not _num(gap):
        errors.append("gap_value must be a number or null")
    else:
        if not _nonempty(cd.get("method")) or not _nonempty(cd.get("evidence_ref")):
            errors.append("a stated gap_value requires computation.method and computation.evidence_ref (it must be actually computed)")
        if cd.get("input_reality") not in INPUT_REALITIES:
            errors.append("computation.input_reality must be REAL, SYNTHETIC, or MIXED")
        if record["threshold_status"] == "UNVERIFIABLE":
            errors.append("a computed gap_value cannot be UNVERIFIABLE; state WITHIN_THRESHOLD or ABOVE_THRESHOLD_REVIEW")
        if record["adjusted"] is True and abs(gap) >= TRIGGER_PERCENT and record["threshold_status"] == "WITHIN_THRESHOLD":
            errors.append(f"an adjusted gap of at least {TRIGGER_PERCENT:g}% cannot be WITHIN_THRESHOLD")
    if record["threshold_status"] == "ABOVE_THRESHOLD_REVIEW" and not record.get("objective_justification_refs"):
        errors.append("ABOVE_THRESHOLD_REVIEW requires objective_justification_refs for the joint assessment")
    if has_forbidden(record):
        errors.append("raw individual pay or identifier data is prohibited; the analysis is aggregate")
    return errors


def build_pay_equity_record(*, group: str, pay_element: str, metric: str, gap_percent, counts: list[dict], min_cell: int,
                            adjusted: bool, justification_refs: list, input_reality: str, method: str, evidence_ref: str,
                            limitations: list, countercheck: str) -> dict:
    """Aggregált bérrés-rekord. A küszöbállapot a számított értékből következik, nem szabadon választott."""
    if gap_percent is None:
        status = "UNVERIFIABLE"
    else:
        status = "ABOVE_THRESHOLD_REVIEW" if abs(gap_percent) >= TRIGGER_PERCENT else "WITHIN_THRESHOLD"
    return {
        "record_type": "pay-equity-analysis", "comparison_group": group, "pay_element": pay_element, "gap_metric": metric,
        "gap_value": gap_percent,
        "computation": {"method": method, "evidence_ref": evidence_ref, "input_reality": input_reality},
        "cohort_counts": counts, "min_cell_size": min_cell, "adjusted": adjusted, "threshold_status": status,
        "objective_justification_refs": justification_refs, "limitations": limitations, "countercheck": countercheck,
    }
