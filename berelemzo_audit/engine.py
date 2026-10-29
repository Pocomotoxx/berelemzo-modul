"""Az audit-motor: kontrollok futtatása, a bizonyítékszint-plafon érvényesítése, aggregált rekordok és kimeneti kapu."""

from __future__ import annotations

import datetime as dt

from berelemzo_verify.canon import sha256
from berelemzo_verify.report import verify as l1_verify

from . import AUDIT_ID, __version__
from .catalogue import BY_ID, CONTROLS
from .controls import (DECLARED_ONLY, FUNCS, MANUAL, MET, NOT_ASSESSABLE, NOT_MET, Ctx, trigger_states)
from .egress import scan
from .indicators import all_indicators
from .inputs import Config, Dataset
from .records import build_pay_equity_record, validate_pay_equity_analysis

COMPUTED_NOT_MET = {"JOB-01", "JOB-02", "PAY-01", "PAY-02", "OBJ-01", "STA-01", "STA-02", "STA-03", "DPR-01", "DPR-02"}
REQUIRED_EVIDENCE = {MET: "COMPUTED_MEASURED", DECLARED_ONLY: "DECLARED", NOT_ASSESSABLE: "UNVERIFIABLE"}


class CeilingError(AssertionError):
    """Egy kontroll a bizonyítékszintjénél erősebb státuszt kapott: motorhiba, nem adathiba."""


def _pay_equity_records(ctx: Ctx, ind: dict) -> tuple[list[dict], list[dict]]:
    k, reality = ctx.k, ctx.input_reality
    ev = f"{AUDIT_ID}/{__version__}"
    valid, invalid = [], []

    def add(rec, label):
        errs = validate_pay_equity_analysis(rec)
        (invalid if errs else valid).append({"comparison_group": label, "errors": errs} if errs else rec)

    o = ind["overall"]
    n_f = sum(1 for r in ctx.ds.rows if r.female)
    n_m = len(ctx.ds.rows) - n_f
    cohorts = [{"group": "F", "count": n_f}, {"group": "M", "count": n_m}]
    if not o["suppressed"]:
        for metric, key, method in (("MEAN", "mean_gap", "(férfi átlag − női átlag) / férfi átlag, FTE-normalizált díjazás"),
                                    ("MEDIAN", "median_gap", "(férfi medián − női medián) / férfi medián, FTE-normalizált díjazás")):
            add(build_pay_equity_record(group="szervezet egésze", pay_element="TOTAL", metric=metric, gap_percent=round(o[key] * 100, 4), counts=cohorts,
                                        min_cell=k, adjusted=False, justification_refs=[], input_reality=reality, method=method, evidence_ref=ev,
                                        limitations=["Nyers, kiigazítatlan különbség; nem bizonyítja a diszkrimináció okát vagy hiányát.", "Egyetlen időszak."],
                                        countercheck="Független újraszámítás (STA-01), kategóriánkénti bontás."), "szervezet egésze / " + metric)
    vp = ind["variable_pay"]
    if vp and vp.get("mean_gap_all_workers") is not None:
        add(build_pay_equity_record(group="szervezet egésze, változó díjazás", pay_element="BONUS", metric="MEAN", gap_percent=round(vp["mean_gap_all_workers"] * 100, 4),
                                    counts=cohorts, min_cell=k, adjusted=False, justification_refs=[], input_reality=reality,
                                    method="(férfi átlag − női átlag) / férfi átlag, a változó díjazás FTE-normalizált havi összege, minden munkavállalóra",
                                    evidence_ref=ev, limitations=["A jogosultsági és célkitűzési szabály semlegességét nem bizonyítja."],
                                    countercheck="A jogosultsági szabályok felülvizsgálata."), "változó díjazás / MEAN")
    q_counts = []
    for q in ind["quartiles"]:
        for sex, key in (("F", "n_f"), ("M", "n_m")):
            if isinstance(q[key], int) and q[key] >= k:
                q_counts.append({"group": f"Q{q['quartile']}-{sex}", "count": q[key]})
    if q_counts:
        add(build_pay_equity_record(group="szervezet egésze, bérkvartilisek", pay_element="TOTAL", metric="QUARTILE_DISTRIBUTION", gap_percent=None, counts=q_counts,
                                    min_cell=k, adjusted=False, justification_refs=[], input_reality=reality,
                                    method="nők és férfiak száma a négy bérkvartilisben (inclusive kvantilis-határ)", evidence_ref=ev,
                                    limitations=["Az eloszlás nem bizonyít egyenlő bért azonos értékű munkán belül.", "Az elnyomott cellák nem szerepelnek."],
                                    countercheck="Kategóriánkénti bontás."), "bérkvartilisek")
    states = {s["grade"]: s for s in trigger_states(ctx)}
    for c in ind["categories"]:
        if c["suppressed"]:
            continue
        st = states.get(c["grade"], {})
        add(build_pay_equity_record(group=(f"kategória {c['grade']} (pontsáv {c['score_range'][0]}–{c['score_range'][1]})" if c["score_range"] else f"munkakör-csoport {c['grade']} (azonos munka)"), pay_element="TOTAL", metric="MEAN",
                                    gap_percent=round(c["mean_gap"] * 100, 4), counts=[{"group": "F", "count": c["n_f"]}, {"group": "M", "count": c["n_m"]}],
                                    min_cell=k, adjusted=False, justification_refs=st.get("justification_refs", []), input_reality=reality,
                                    method="(férfi átlag − női átlag) / férfi átlag a kategórián belül, FTE-normalizált díjazás", evidence_ref=ev,
                                    limitations=["A küszöbérintés nem jogi minősítés.", "A kiigazítás hiánya: az objektív indokokat külön kell vizsgálni."],
                                    countercheck="Objektív indok és közös bérértékelés (STA-02, REP-02)."), f"kategória {c['grade']}")
    return valid, invalid


def run_audit(ds: Dataset, cfg: Config, decl: dict, audit_date: dt.date, *, result: dict | None = None,
              config_raw: dict | None = None, input_reality: str = "SYNTHETIC") -> dict:
    ind = all_indicators(ds, cfg)
    ctx = Ctx(ds=ds, cfg=cfg, decl=decl, audit_date=audit_date, indicators=ind, result=result, input_reality=input_reality)
    l1 = None
    if result is not None:
        l1 = l1_verify(result, config_raw)
        ctx.cache["l1"] = l1
    controls = []
    for cid, group, objective, test, mode in CONTROLS:
        out = FUNCS[cid](ctx)
        want = REQUIRED_EVIDENCE.get(out.status)
        level = out.evidence_level
        if out.status in (NOT_MET, MANUAL):
            level = "COMPUTED_MEASURED" if (cid in COMPUTED_NOT_MET or out.status == MANUAL) else "DECLARED"
        if want and level != want:
            raise CeilingError(f"{cid}: a(z) {out.status} státuszhoz {want} bizonyítékszint tartozik, kapott: {level}")
        controls.append({"id": cid, "group": group, "objective": objective, "audit_test": test, "mode": mode, "status": out.status,
                         "evidence_level": level, "basis": out.basis, "metrics": out.metrics, "findings": out.findings,
                         "needs": out.needs, "limitations": out.limitations})
    counts = {s: sum(1 for c in controls if c["status"] == s) for s in (MET, NOT_MET, DECLARED_ONLY, NOT_ASSESSABLE, MANUAL)}
    valid, invalid = _pay_equity_records(ctx, ind)
    record = {
        "audit_type": AUDIT_ID, "audit_version": __version__, "audit_date": audit_date.isoformat(), "input_reality": input_reality,
        "legal_status": "REVIEW_REQUIRED",
        "scope": {"catalogue": "bértranszparencia-auditkézikönyv kontrollkatalógusa (24 kontroll)", "workers_in_file": ds.headcount_all,
                  "workers_analysed": len(ds.rows), "min_cell": cfg.min_cell, "pay_basis": ds.pay_basis, "grouping": "pontsáv" if cfg.scoring else "munkakör (azonos munka)"},
        "summary": {"controls": len(controls), "by_status": counts,
                    "assessed_from_data": sum(1 for c in controls if c["status"] in (MET, NOT_MET) and c["evidence_level"] == "COMPUTED_MEASURED"),
                    "declared_only_or_declared_failures": sum(1 for c in controls if c["evidence_level"] == "DECLARED"),
                    "not_assessable": counts[NOT_ASSESSABLE]},
        "controls": controls,
        "indicators": ind,
        "trigger_states": trigger_states(ctx),
        "pay_equity_records": valid,
        "pay_equity_records_not_valid": invalid,
        "result_l1": None if l1 is None else {"verdict": l1["verdict"], "summary": l1["summary"]},
        "notes": [
            "A státuszok a kontrollkatalógus kontrollcéljához képesti állapotot mutatják, nem jogi minősítést, és nem a megfelelőség tanúsítását.",
            "A MET csak az adatból vagy az eredményből számolt teljesülés. A DECLARED_ONLY a szervezet nyilatkozatán alapul, amelyet a motor nem tud igazolni.",
            "A küszöbérintés (5%) nem azonos a közös bérértékelési kötelezettséggel; az indoklás és az orvoslás emberi, jogi döntés.",
            "A „nincs megállapítás” nem azonos azzal, hogy „helyes”. Minden kimenet REVIEW_REQUIRED.",
        ],
    }
    issues = scan(record, cfg.min_cell)
    record["egress"] = {"status": "BLOCKED" if issues else "PASSED", "issues": issues, "note": "Heurisztikus kapu: nem anonimizálási garancia."}
    record["fingerprint"] = {"algorithm": "sha256", "result": sha256({k: v for k, v in record.items() if k != "fingerprint"})}
    return record
