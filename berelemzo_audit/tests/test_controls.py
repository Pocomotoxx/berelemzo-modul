import copy
import datetime as dt
import json
import unittest

from berelemzo.core import JobStats, analyze
from berelemzo.intake import parse_config

from berelemzo_audit import catalogue
from berelemzo_audit import controls as controls_mod
from berelemzo_audit.engine import CeilingError, run_audit
from berelemzo_audit.indicators import category_table
from berelemzo_audit.inputs import Config

from .fixtures import AUDIT_DATE, HEADER, good_declarations, iso
from .support import audit, status, world

BASELINE = {
    "GOV-01": "DECLARED_ONLY", "GOV-02": "DECLARED_ONLY", "JOB-01": "MET", "JOB-02": "MET", "JOB-03": "DECLARED_ONLY",
    "JOB-04": "DECLARED_ONLY", "PAY-01": "MET", "PAY-02": "MET", "PAY-03": "DECLARED_ONLY", "OBJ-01": "MET",
    "OBJ-02": "DECLARED_ONLY", "OBJ-03": "MANUAL_REVIEW", "STA-01": "MET", "STA-02": "MET", "STA-03": "MET",
    "TRN-01": "DECLARED_ONLY", "TRN-02": "DECLARED_ONLY", "TRN-03": "DECLARED_ONLY", "REP-01": "DECLARED_ONLY",
    "REP-02": "DECLARED_ONLY", "DPR-01": "DECLARED_ONLY", "DPR-02": "MET", "CHG-01": "DECLARED_ONLY", "CHG-02": "DECLARED_ONLY",
}


def berelemzo_result(cfg, rows):
    """A Bérelemző eredménye ugyanazokon az adatokon (a FTE-normalizált díjazásból)."""
    bc = parse_config(cfg)
    stats = {}
    for r in rows:
        total = sum(float(x) for x in r[3:8])
        st = stats.setdefault(r[0], JobStats())
        (st.f if r[1] == "F" else st.m).add(total / float(r[2]))
    return json.loads(json.dumps(analyze(bc, stats, {"other_sex": 0, "unknown_job": 0})))


class CatalogueTests(unittest.TestCase):
    def test_catalogue_is_complete(self):
        ids = [c[0] for c in catalogue.CONTROLS]
        self.assertEqual(len(ids), 24)
        self.assertEqual(len(set(ids)), 24)
        self.assertEqual(set(ids), set(controls_mod.FUNCS))
        for c in catalogue.CONTROLS:
            self.assertTrue(c[2] and c[3] and c[4] in ("COMPUTED", "MIXED", "DECLARED"))


class BaselineTests(unittest.TestCase):
    def test_good_world_statuses(self):
        cfg, rows = world()
        rec = audit(cfg, rows, good_declarations(cfg, rows), result=berelemzo_result(cfg, rows))
        got = {c["id"]: c["status"] for c in rec["controls"]}
        self.assertEqual(got, BASELINE)
        self.assertEqual(rec["egress"]["status"], "PASSED")
        self.assertEqual(rec["result_l1"]["verdict"], "NO_FAILURES")

    def test_no_declarations_means_not_assessable_not_failure(self):
        cfg, rows = world()
        rec = audit(cfg, rows, {})
        for c in rec["controls"]:
            self.assertNotEqual(c["status"], "NOT_MET", c["id"])
        self.assertGreaterEqual(rec["summary"]["by_status"]["NOT_ASSESSABLE"], 10)
        for c in rec["controls"]:
            if c["status"] == "NOT_ASSESSABLE":
                self.assertTrue(c["needs"] or c["basis"], c["id"])

    def test_deterministic_and_fingerprint(self):
        cfg, rows = world()
        decl = good_declarations(cfg, rows)
        a, b = audit(cfg, rows, decl), audit(cfg, rows, copy.deepcopy(decl))
        self.assertEqual(a, b)
        from berelemzo_verify.canon import sha256
        body = {k: v for k, v in a.items() if k != "fingerprint"}
        self.assertEqual(a["fingerprint"]["result"], sha256(body))

    def test_evidence_ceiling_is_enforced(self):
        cfg, rows = world()
        original = controls_mod.FUNCS["GOV-01"]
        try:
            controls_mod.FUNCS["GOV-01"] = lambda ctx: controls_mod.Outcome(controls_mod.MET, "DECLARED", "hibás")
            with self.assertRaises(CeilingError):
                audit(cfg, rows, good_declarations(cfg, rows))
        finally:
            controls_mod.FUNCS["GOV-01"] = original


def flip(cid, expected, mutate, kind="good", **kw):
    """Egy kontroll státuszának átfordítása egy mutációval; a többi kontroll alapállapotát is megőrzi, ahol releváns."""
    cfg, rows = world(kind)
    decl = good_declarations(cfg, rows)
    out = mutate(cfg, rows, decl)
    if isinstance(out, tuple) and len(out) == 3:
        cfg, rows, decl = out
    rec = audit(cfg, rows, decl, **kw)
    return status(rec, cid), rec


class ControlMutationTests(unittest.TestCase):
    def assertStatus(self, cid, expected, mutate, kind="good", **kw):
        c, rec = flip(cid, expected, mutate, kind, **kw)
        self.assertEqual(c["status"], expected, (cid, c["basis"], c["findings"][:1]))
        return c

    # ---- GOV
    def test_gov(self):
        self.assertStatus("GOV-01", "NOT_MET", lambda c, r, d: d["governance"].update(approved_on=iso(AUDIT_DATE - dt.timedelta(days=400))))
        self.assertStatus("GOV-01", "NOT_MET", lambda c, r, d: d["governance"].update(approved_on=iso(AUDIT_DATE + dt.timedelta(days=5))))
        self.assertStatus("GOV-01", "NOT_ASSESSABLE", lambda c, r, d: d.pop("governance"))
        self.assertStatus("GOV-02", "NOT_MET", lambda c, r, d: d["governance"].update(representative_involved=False))
        self.assertStatus("GOV-02", "NOT_ASSESSABLE", lambda c, r, d: d["governance"].pop("minutes_ref"))

    # ---- JOB
    def test_job_01(self):
        def no_profile(c, r, d):
            next(iter(d["job_catalogue"].values())).pop("profile_version")
        self.assertStatus("JOB-01", "NOT_MET", no_profile)
        def inactive(c, r, d):
            next(iter(d["job_catalogue"].values()))["active"] = False
        self.assertStatus("JOB-01", "NOT_MET", inactive)
        def unscored(c, r, d):
            r.append(["MK-999", "F", 1.0, 400000, 0, 0, 0, 0, 3])
        c = self.assertStatus("JOB-01", "NOT_MET", unscored)
        self.assertEqual(c["metrics"]["jobs_without_scoring_levels"], 1)

    def test_job_02(self):
        def zero_skill(c, r, d):
            c["scheme"]["weights"] = [0.0, 0.5, 0.3, 0.2]
        self.assertStatus("JOB-02", "NOT_MET", zero_skill)
        def zero_level(c, r, d):
            c["jobs"]["MK-000"][0] = 0
        self.assertStatus("JOB-02", "NOT_MET", zero_level)          # a 0 szint indoklás nélkül
        def zero_level_with_reason(c, r, d):
            c["jobs"]["MK-000"][0] = 0
            d["job_evaluation"]["zero_level_reasons"] = {"MK-000": {"0": "a munkakör nem igényel szakmai tudást"}}
        self.assertStatus("JOB-02", "MET", zero_level_with_reason)
        def odd_weights(c, r, d):
            c["scheme"]["weights"] = [0.2, 0.2, 0.2, 0.2, 0.2]
            for j in c["jobs"]:
                c["jobs"][j] = c["jobs"][j] + [3]
            d["job_evaluation"].pop("factor_map", None)
        self.assertStatus("JOB-02", "NOT_ASSESSABLE", odd_weights)

    def test_job_03(self):
        def single(c, r, d):
            j = next(iter(c["jobs"]))
            d["scoring_log"]["raters"][j] = [d["scoring_log"]["raters"][j][0]]
        self.assertStatus("JOB-03", "NOT_MET", single)
        def outside(c, r, d):
            j = next(iter(c["jobs"]))
            d["scoring_log"]["raters"][j] = [[1, 1, 1, 1], [1, 1, 1, 1]] if c["jobs"][j] != [1, 1, 1, 1] else [[2, 2, 2, 2], [2, 2, 2, 2]]
        self.assertStatus("JOB-03", "NOT_MET", outside)
        def no_reason(c, r, d):
            d["scoring_log"]["rationale_documented"][next(iter(c["jobs"]))] = False
        self.assertStatus("JOB-03", "NOT_MET", no_reason)
        c = self.assertStatus("JOB-03", "NOT_ASSESSABLE", lambda c, r, d: d.pop("scoring_log"))
        c, rec = flip("JOB-03", "DECLARED_ONLY", lambda c, r, d: None)
        self.assertEqual(c["metrics"]["rescoring_sample_size"], max(1, -(-len(world()[0]["jobs"]) // 10)))

    def test_job_04(self):
        self.assertStatus("JOB-04", "NOT_MET", lambda c, r, d: d["job_evaluation"].update(feor_reference_only=False))
        self.assertStatus("JOB-04", "NOT_ASSESSABLE", lambda c, r, d: d["job_evaluation"].pop("feor_reference_only"))

    # ---- PAY
    def test_pay_01(self):
        self.assertStatus("PAY-01", "NOT_MET", lambda c, r, d: d["reconciliation"].update(gross_total=d["reconciliation"]["gross_total"] + 5000))
        self.assertStatus("PAY-01", "NOT_MET", lambda c, r, d: d["reconciliation"].update(headcount=d["reconciliation"]["headcount"] + 1))
        self.assertStatus("PAY-01", "NOT_MET", lambda c, r, d: d["pay_elements"].append("cafeteria"))
        self.assertStatus("PAY-01", "NOT_ASSESSABLE", lambda c, r, d: (d.pop("pay_elements"), d.pop("reconciliation")))

    def test_pay_02(self):
        def bad_fte(c, r, d):
            r.append([r[0][0], "F", 1.7, 400000, 0, 0, 0, 0, 3])
            d["reconciliation"]["headcount"] += 1
            d["reconciliation"]["gross_total"] += 400000
        self.assertStatus("PAY-02", "NOT_MET", bad_fte)
        self.assertStatus("PAY-02", "NOT_ASSESSABLE", lambda c, r, d: d.pop("normalization"))

    def test_pay_02_double_normalization_detected(self):
        cfg, rows = world()
        decl = good_declarations(cfg, rows)
        header = HEADER + ["pay_normalizalt"]
        out = []
        for r in rows:
            total = sum(float(x) for x in r[3:8])
            fte = float(r[2])
            out.append(r + [total / fte / fte])           # kétszer osztott
        c = status(audit(cfg, out, decl, header=header), "PAY-02")
        self.assertEqual(c["status"], "NOT_MET")
        self.assertIn("kétszeres normalizálás", c["findings"][0]["detail"])
        ok = [r + [sum(float(x) for x in r[3:8]) / float(r[2])] for r in rows]
        self.assertEqual(status(audit(cfg, ok, decl, header=header), "PAY-02")["status"], "MET")

    def test_pay_03(self):
        def inverted(c, r, d):
            d["pay_bands"][0].update(min=d["pay_bands"][0]["max"] + 10)
        self.assertStatus("PAY-03", "NOT_MET", inverted)
        self.assertStatus("PAY-03", "NOT_MET", lambda c, r, d: d["pay_bands"].append(dict(d["pay_bands"][0])))
        self.assertStatus("PAY-03", "NOT_ASSESSABLE", lambda c, r, d: d["pay_policy"].pop("progression_criteria"))

    # ---- OBJ
    def test_obj_01(self):
        cfg, rows = world()
        decl = good_declarations(cfg, rows)
        for b in decl["pay_bands"]:
            b["max"] = b["min"] + (b["max"] - b["min"]) * 0.6          # szűk sáv: sok sávon kívüli bér
        rec = audit(cfg, rows, decl)
        self.assertEqual(status(rec, "OBJ-01")["status"], "NOT_MET")
        # minden eltéréshez teljes indokrekord -> MET
        from berelemzo_audit.inputs import load_rows
        import tempfile, os
        from .fixtures import write_csv
        d = tempfile.mkdtemp()
        write_csv(os.path.join(d, "a.csv"), rows)
        ds = load_rows(os.path.join(d, "a.csv"))
        band = {b["grade"]: b for b in decl["pay_bands"]}
        recs = [{"row": r.idx, "type": "tapasztalat", "source": "BER-1", "decision_year": 2024, "rule_ref": "SZAB-1"}
                for r in ds.rows if not (band[decl["job_catalogue"][r.job]["grade"]]["min"] <= r.norm <= band[decl["job_catalogue"][r.job]["grade"]]["max"])]
        self.assertGreater(len(recs), 5)
        decl["justifications"] = recs
        self.assertEqual(status(audit(cfg, rows, decl), "OBJ-01")["status"], "MET")
        decl["justifications"] = [dict(x, source="") for x in recs]    # hiányos rekordok
        self.assertEqual(status(audit(cfg, rows, decl), "OBJ-01")["status"], "NOT_MET")
        self.assertEqual(status(audit(cfg, rows, {k: v for k, v in decl.items() if k != "pay_bands"}), "OBJ-01")["status"], "NOT_ASSESSABLE")

    def test_obj_01_small_counts_are_floored(self):
        cfg, rows = world()
        decl = good_declarations(cfg, rows)
        b = decl["pay_bands"][0]
        top = max(sum(float(x) for x in r[3:8]) / float(r[2]) for r in rows if decl["job_catalogue"][r[0]]["grade"] == b["grade"])
        b["max"] = top - 1                                   # pontosan egy ember esik sávon kívülre
        rec = audit(cfg, rows, decl)
        self.assertEqual(status(rec, "OBJ-01")["metrics"]["workers_off_band"], "<5")

    def test_obj_02(self):
        lack = {"row": 1, "type": "teljesítmény", "source": "X", "decision_year": 2025, "rule_ref": "Y"}
        self.assertStatus("OBJ-02", "NOT_MET", lambda c, r, d: d.update(justifications=[lack]))
        self.assertStatus("OBJ-02", "NOT_MET", lambda c, r, d: d.update(justifications=[dict(lack, expires_on=iso(AUDIT_DATE - dt.timedelta(days=1)))]))
        self.assertStatus("OBJ-02", "DECLARED_ONLY", lambda c, r, d: d.update(justifications=[dict(lack, expires_on=iso(AUDIT_DATE + dt.timedelta(days=90)))]))
        self.assertStatus("OBJ-02", "DECLARED_ONLY", lambda c, r, d: d.update(justifications=[dict(lack, type="tapasztalat")]))
        self.assertStatus("OBJ-02", "NOT_ASSESSABLE", lambda c, r, d: (d.pop("justifications"), d.pop("justifications_declared_complete")))

    def test_obj_03(self):
        cfg, rows = world()
        decl = good_declarations(cfg, rows)
        header = HEADER[:-1]
        self.assertEqual(status(audit(cfg, [r[:-1] for r in rows], decl, header=header), "OBJ-03")["status"], "NOT_ASSESSABLE")
        biased = [r[:-1] + [2 if r[1] == "F" else 5] for r in rows]
        c = status(audit(cfg, biased, decl), "OBJ-03")
        self.assertEqual(c["status"], "MANUAL_REVIEW")
        self.assertTrue(c["metrics"]["screening_flag"])
        self.assertTrue(c["findings"])
        flat = [r[:-1] + [3] for r in rows]
        c = status(audit(cfg, flat, decl), "OBJ-03")
        self.assertEqual(c["status"], "MANUAL_REVIEW")
        self.assertFalse(c["metrics"].get("screening_flag", False))

    # ---- STA
    def test_sta_01_cross_check_with_result(self):
        cfg, rows = world()
        decl = good_declarations(cfg, rows)
        res = berelemzo_result(cfg, rows)
        self.assertEqual(status(audit(cfg, rows, decl, result=res), "STA-01")["status"], "MET")
        bad = copy.deepcopy(res)
        c = next(x for x in bad["categories"] if not x["suppressed"])
        c["gap"] = round(c["gap"] + 0.01, 6)
        rec = audit(cfg, rows, decl, result=bad)
        self.assertEqual(status(rec, "STA-01")["status"], "NOT_MET")
        self.assertEqual(status(rec, "STA-03")["status"], "NOT_MET" if rec["result_l1"]["verdict"] != "NO_FAILURES" else "MET")
        self.assertEqual(status(audit(cfg, rows, decl), "STA-01")["status"], "MET")

    def test_sta_03_fails_on_a_result_that_fails_l1(self):
        cfg, rows = world()
        res = berelemzo_result(cfg, rows)
        res["parameters"]["min_cell"] = 3                    # lenyomat és V06 hiba
        rec = audit(cfg, rows, good_declarations(cfg, rows), result=res)
        self.assertEqual(status(rec, "STA-03")["status"], "NOT_MET")
        self.assertEqual(rec["result_l1"]["verdict"], "FAILURES")

    def test_sta_02_trigger_handling(self):
        cfg, rows = world("trigger")
        decl = good_declarations(cfg, rows)
        rec = audit(cfg, rows, decl)
        sta = status(rec, "STA-02")
        self.assertEqual(sta["status"], "NOT_MET")
        self.assertGreater(sta["metrics"]["joint_assessment_indicated"], 0)
        grades = [s["grade"] for s in rec["trigger_states"] if s["state"] == "JOINT_ASSESSMENT_INDICATED"]
        rep = iso(AUDIT_DATE - dt.timedelta(days=30))
        just = {"objective": True, "evidence_refs": ["DOK-1"], "assessment_ref": "ERT-1"}
        d1 = copy.deepcopy(decl)
        d1["deviation_register"] = [{"grade": g, "justification": just, "reported_on": rep} for g in grades]
        self.assertEqual(status(audit(cfg, rows, d1), "STA-02")["status"], "DECLARED_ONLY")
        d2 = copy.deepcopy(decl)
        d2["deviation_register"] = [{"grade": g, "remediation": {"plan_ref": "KT-1", "planned_by": iso(AUDIT_DATE + dt.timedelta(days=90))}, "reported_on": rep} for g in grades]
        self.assertEqual(status(audit(cfg, rows, d2), "STA-02")["status"], "DECLARED_ONLY")
        d3 = copy.deepcopy(decl)      # a terv határideje hat hónapon túl van
        d3["deviation_register"] = [{"grade": g, "remediation": {"plan_ref": "KT-1", "planned_by": iso(AUDIT_DATE + dt.timedelta(days=300))}, "reported_on": rep} for g in grades]
        self.assertEqual(status(audit(cfg, rows, d3), "STA-02")["status"], "NOT_MET")
        d4 = copy.deepcopy(decl)      # lejárt, teljesítetlen terv
        d4["deviation_register"] = [{"grade": g, "remediation": {"plan_ref": "KT-1", "planned_by": iso(AUDIT_DATE - dt.timedelta(days=5))}, "reported_on": iso(AUDIT_DATE - dt.timedelta(days=100))} for g in grades]
        self.assertEqual(status(audit(cfg, rows, d4), "STA-02")["status"], "NOT_MET")
        d5 = copy.deepcopy(d4)
        for e in d5["deviation_register"]:
            e["remediation"]["completed_on"] = iso(AUDIT_DATE - dt.timedelta(days=10))
        self.assertEqual(status(audit(cfg, rows, d5), "STA-02")["status"], "DECLARED_ONLY")

    def test_sta_02_met_when_nothing_triggered(self):
        c, rec = flip("STA-02", "MET", lambda c, r, d: None)
        self.assertEqual(c["status"], "MET")
        self.assertEqual(c["metrics"]["categories_at_or_above_5_percent"], 0)

    # ---- TRN
    def test_trn(self):
        self.assertStatus("TRN-01", "NOT_MET", lambda c, r, d: d["transparency"]["job_ads"].update(with_pay_range=3))
        self.assertStatus("TRN-01", "NOT_MET", lambda c, r, d: d["transparency"].update(pay_history_question_banned=False))
        self.assertStatus("TRN-01", "NOT_ASSESSABLE", lambda c, r, d: d["transparency"].pop("job_ads"))
        rq = {"received": iso(AUDIT_DATE - dt.timedelta(days=100)), "answered": iso(AUDIT_DATE - dt.timedelta(days=60))}
        self.assertStatus("TRN-02", "DECLARED_ONLY", lambda c, r, d: d.update(info_requests=[rq]))
        self.assertStatus("TRN-02", "NOT_MET", lambda c, r, d: d.update(info_requests=[dict(rq, answered=iso(AUDIT_DATE - dt.timedelta(days=10)))]))
        self.assertStatus("TRN-02", "NOT_MET", lambda c, r, d: d.update(info_requests=[{"received": rq["received"], "answered": None}]))
        self.assertStatus("TRN-02", "DECLARED_ONLY", lambda c, r, d: d.update(info_requests=[{"received": iso(AUDIT_DATE - dt.timedelta(days=20)), "answered": None}]))
        self.assertStatus("TRN-02", "NOT_ASSESSABLE", lambda c, r, d: (d.pop("info_requests"), d.pop("info_requests_declared_complete")))
        self.assertStatus("TRN-03", "NOT_MET", lambda c, r, d: d["transparency"].update(annual_notice_on=iso(AUDIT_DATE - dt.timedelta(days=500))))
        self.assertStatus("TRN-03", "NOT_MET", lambda c, r, d: d["transparency"].update(criteria_accessible=False))

    # ---- REP
    def test_rep(self):
        c, _ = flip("REP-01", "DECLARED_ONLY", lambda c, r, d: None)
        self.assertEqual(c["metrics"]["first_report"], "2027-06-07")
        self.assertEqual(c["metrics"]["then"], "háromévente")
        self.assertIn("REVIEW_REQUIRED", " ".join(c["limitations"]))
        self.assertStatus("REP-01", "NOT_ASSESSABLE", lambda c, r, d: d.pop("reporting"))
        def small(c, r, d):
            return c, r[:60], d
        self.assertStatus("REP-01", "NOT_ASSESSABLE", small)
        self.assertStatus("REP-02", "NOT_ASSESSABLE", lambda c, r, d: d.pop("joint_assessment"))
        cfg, rows = world("trigger")
        decl = good_declarations(cfg, rows)
        decl.pop("joint_assessment")
        self.assertEqual(status(audit(cfg, rows, decl), "REP-02")["status"], "NOT_MET")

    # ---- DPR
    def test_dpr_01_non_whitelisted_columns_are_reported_but_not_read(self):
        cfg, rows = world()
        decl = good_declarations(cfg, rows)
        header = HEADER + ["nev", "adoszam"]
        with_names = [r + [f"Teszt Személy {i}", f"8{i:09d}"] for i, r in enumerate(rows)]
        rec = audit(cfg, with_names, decl, header=header)
        c = status(rec, "DPR-01")
        self.assertEqual(c["status"], "NOT_MET")
        self.assertIn("nev", c["findings"][0]["detail"])
        text = json.dumps(rec, ensure_ascii=False)
        self.assertNotIn("Teszt Személy", text)
        self.assertNotIn("8000000", text)
        self.assertEqual(rec["egress"]["status"], "PASSED")

    def test_dpr_01_needs_declarations(self):
        self.assertStatus("DPR-01", "NOT_ASSESSABLE", lambda c, r, d: d.pop("data_protection"))

    def test_dpr_02_suppressed_categories(self):
        cfg, rows = world("suppressed")
        decl = good_declarations(cfg, rows)
        self.assertEqual(status(audit(cfg, rows, decl), "DPR-02")["status"], "DECLARED_ONLY")
        decl["data_protection"].pop("small_group_mitigation")
        c = status(audit(cfg, rows, decl), "DPR-02")
        self.assertEqual(c["status"], "NOT_MET")
        self.assertGreater(c["metrics"]["share_in_suppressed_categories"], 0)

    # ---- CHG
    def test_chg(self):
        ch = {"job_id": "MK-001", "changed_on": iso(AUDIT_DATE - dt.timedelta(days=40)), "reevaluated_on": iso(AUDIT_DATE - dt.timedelta(days=20))}
        self.assertStatus("CHG-01", "DECLARED_ONLY", lambda c, r, d: d["change_management"].update(job_changes=[ch]))
        self.assertStatus("CHG-01", "NOT_MET", lambda c, r, d: d["change_management"].update(job_changes=[dict(ch, reevaluated_on=None)]))
        self.assertStatus("CHG-01", "NOT_MET", lambda c, r, d: d["change_management"].update(job_changes=[dict(ch, reevaluated_on=iso(AUDIT_DATE - dt.timedelta(days=90)))]))
        self.assertStatus("CHG-01", "NOT_ASSESSABLE", lambda c, r, d: d.pop("change_management"))
        self.assertStatus("CHG-02", "NOT_MET", lambda c, r, d: d["change_management"].update(last_update_log_on=iso(AUDIT_DATE - dt.timedelta(days=500))))
        self.assertStatus("CHG-02", "NOT_ASSESSABLE", lambda c, r, d: d["change_management"].pop("monitoring_owner_role"))


class IndicatorTests(unittest.TestCase):
    def test_indicators_are_aggregate_and_consistent(self):
        cfg, rows = world()
        rec = audit(cfg, rows, good_declarations(cfg, rows))
        ind = rec["indicators"]
        self.assertFalse(ind["overall"]["suppressed"])
        self.assertIsNotNone(ind["overall"]["mean_gap"])
        self.assertEqual(len(ind["quartiles"]), 4)
        self.assertEqual(sum(q["n_f"] + q["n_m"] for q in ind["quartiles"]), len(rows))
        self.assertIn("share_receiving_f", ind["variable_pay"])

    def test_known_gap_is_recovered(self):
        # azonos munkakör, a nők pontosan 10%-kal kevesebbet kapnak: a kategória-rés pontosan 10%
        cfg = {"scheme": {"name": "t", "weights": [1.0], "level_max": 5}, "band_width": 20.0, "min_cell": 5, "jobs": {"A": [3]}}
        rows = []
        for i in range(8):
            rows.append(["A", "M", 1.0, 500000 + i * 1000, 0, 0, 0, 0, 3])
            rows.append(["A", "F", 1.0, round((500000 + i * 1000) * 0.9), 0, 0, 0, 0, 3])
        rec = audit(cfg, rows, {})
        cat = rec["indicators"]["categories"][0]
        self.assertAlmostEqual(cat["mean_gap"], 0.1, places=3)
        self.assertTrue(cat["t_c"])
        self.assertTrue(cat["sampling_signal"])


if __name__ == "__main__":
    unittest.main()
