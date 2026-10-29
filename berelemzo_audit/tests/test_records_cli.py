import copy
import io
import json
import os
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from berelemzo_audit.cli import main
from berelemzo_audit.egress import scan
from berelemzo_audit.records import build_pay_equity_record, validate_job_evaluation, validate_pay_equity_analysis

from .fixtures import AUDIT_DATE, HEADER, good_declarations, write_csv
from .support import audit, world


def job_record():
    return {"record_type": "job-evaluation", "job_id": "MK-001", "job_profile_ref": "JP-1", "evaluates": "JOB",
            "weights": {"SKILLS": 40, "RESPONSIBILITY": 35, "EFFORT": 15, "WORKING_CONDITIONS": 10},
            "factors": [{"main_factor": "SKILLS", "name": "szaktudás", "level": 4, "max": 8, "weight": 12},
                        {"main_factor": "RESPONSIBILITY", "name": "emberek", "level": 3, "max": 5, "weight": 12},
                        {"main_factor": "EFFORT", "name": "szellemi", "level": 2, "max": 5, "weight": 5},
                        {"main_factor": "WORKING_CONDITIONS", "name": "környezet", "level": 0, "max": 5, "weight": 7, "reason": "irodai munka, nincs kitettség"}],
            "normalized_score": 51.2, "score_method": "pont–faktor, lineáris", "value_group": "G6"}


def pay_record(**over):
    r = build_pay_equity_record(group="kategória 6", pay_element="TOTAL", metric="MEAN", gap_percent=3.2,
                                counts=[{"group": "F", "count": 12}, {"group": "M", "count": 15}], min_cell=5, adjusted=False,
                                justification_refs=[], input_reality="SYNTHETIC", method="(férfi átlag − női átlag) / férfi átlag",
                                evidence_ref="audit/1", limitations=["nyers különbség"], countercheck="független újraszámítás")
    r.update(over)
    return r


class JobEvaluationValidatorTests(unittest.TestCase):
    def test_valid_record_passes(self):
        self.assertEqual(validate_job_evaluation(job_record()), [])

    def test_each_rule_can_fail(self):
        def bad(mut, expect):
            r = job_record()
            mut(r)
            errs = validate_job_evaluation(r)
            self.assertTrue(any(expect in e for e in errs), (expect, errs))
        bad(lambda r: r.pop("job_id"), "missing required field")
        bad(lambda r: r.update(evaluates="PERSON"), "evaluates must be JOB")
        bad(lambda r: r["weights"].update(SKILLS=50), "weights must sum to 100")
        bad(lambda r: r["weights"].pop("EFFORT"), "weights must cover exactly")
        bad(lambda r: r["factors"][0].update(level=9), "level must be an integer from 0 to max")
        bad(lambda r: r["factors"][3].pop("reason"), "level 0 requires an explicit reason")
        bad(lambda r: r["factors"].pop(), "every main factor must be represented")
        bad(lambda r: r.update(normalized_score=140), "normalized_score")
        bad(lambda r: r.update(gender="F"), "personal data")
        bad(lambda r: r["factors"][0].update(main_factor="TECHNICAL"), "invalid main_factor")


class PayEquityValidatorTests(unittest.TestCase):
    def test_built_record_is_valid(self):
        self.assertEqual(validate_pay_equity_analysis(pay_record()), [])

    def test_status_follows_the_computed_value(self):
        self.assertEqual(pay_record(gap_value=3.2)["threshold_status"], "WITHIN_THRESHOLD")
        hi = build_pay_equity_record(group="k", pay_element="TOTAL", metric="MEAN", gap_percent=6.4, counts=[{"group": "F", "count": 9}], min_cell=5,
                                     adjusted=False, justification_refs=["DOK-1"], input_reality="REAL", method="m", evidence_ref="e",
                                     limitations=[], countercheck="c")
        self.assertEqual(hi["threshold_status"], "ABOVE_THRESHOLD_REVIEW")
        self.assertEqual(validate_pay_equity_analysis(hi), [])
        none = build_pay_equity_record(group="k", pay_element="TOTAL", metric="QUARTILE_DISTRIBUTION", gap_percent=None, counts=[{"group": "F", "count": 9}],
                                       min_cell=5, adjusted=False, justification_refs=[], input_reality="REAL", method="m", evidence_ref="e",
                                       limitations=[], countercheck="c")
        self.assertEqual(none["threshold_status"], "UNVERIFIABLE")
        self.assertEqual(validate_pay_equity_analysis(none), [])

    def test_each_rule_can_fail(self):
        def bad(mut, expect):
            r = pay_record()
            mut(r)
            errs = validate_pay_equity_analysis(r)
            self.assertTrue(any(expect in e for e in errs), (expect, errs))
        bad(lambda r: r["cohort_counts"].append({"group": "X", "count": 3}), "below min_cell_size")
        bad(lambda r: r.update(min_cell_size=3), "domain floor")
        bad(lambda r: r.update(threshold_status="UNVERIFIABLE"), "cannot be UNVERIFIABLE")
        bad(lambda r: r.update(gap_value=None, threshold_status="WITHIN_THRESHOLD"), "null gap_value")
        bad(lambda r: r["computation"].pop("method"), "computation.method")
        bad(lambda r: r["computation"].update(input_reality="MAYBE"), "input_reality")
        bad(lambda r: r.update(gap_value=7.0, threshold_status="ABOVE_THRESHOLD_REVIEW"), "objective_justification_refs")
        bad(lambda r: r.update(adjusted=True, gap_value=7.0, threshold_status="WITHIN_THRESHOLD"), "cannot be WITHIN_THRESHOLD")
        bad(lambda r: r.update(individual_salary=500000), "prohibited")
        bad(lambda r: r["cohort_counts"][0].update(wage_total=1), "prohibited")
        bad(lambda r: r.update(pay_element="GROSS"), "invalid pay_element")
        bad(lambda r: r.pop("countercheck"), "missing required field")


class EgressTests(unittest.TestCase):
    def test_scan_detects_problems(self):
        rec = {"cohort": {"count": 3, "n_f": 2, "n_m": 40}, "salary": 1, "note": "írj ide: valaki@pelda.example", "id": "123456789"}
        issues = {(i["locator"], i["issue"].split(" ")[0]) for i in scan(rec, 5)}
        self.assertIn(("/cohort/count", "kis"), issues)
        self.assertIn(("/cohort/n_f", "kis"), issues)
        self.assertIn(("/salary", "tiltott"), issues)
        self.assertTrue(any(i[0] == "/note" for i in issues))
        self.assertTrue(any(i[0] == "/id" for i in issues))
        self.assertEqual(scan({"cohort": {"count": 12, "n_f": 0}, "mean_gap": 0.04}, 5), [])

    def test_audit_record_contains_no_individual_pay_values(self):
        cfg, rows = world()
        rec = audit(cfg, rows, good_declarations(cfg, rows))
        text = json.dumps(rec, ensure_ascii=False)
        numbers = set(re.findall(r"(?<![\d.])\d{5,}(?![\d.])", text))
        row_values = set()
        for r in rows:
            row_values.add(str(round(sum(float(x) for x in r[3:8]))))
            row_values.update(str(int(x)) for x in r[3:8] if int(x) > 9999)
        self.assertEqual(numbers & row_values, set())
        self.assertEqual(scan(rec, 5), [])


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        cfg, rows = world()
        self.cfg, self.rows = cfg, rows
        self.decl = good_declarations(cfg, rows)
        write_csv(self.d / "a.csv", rows)
        (self.d / "c.json").write_text(json.dumps(cfg), encoding="utf-8")
        (self.d / "d.json").write_text(json.dumps(self.decl), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *extra, data="a.csv", decl="d.json"):
        argv = ["--data", str(self.d / data), "--config", str(self.d / "c.json"), "--audit-date", AUDIT_DATE.isoformat(),
                "--input-reality", "SYNTHETIC", *extra]
        if decl:
            argv += ["--declarations", str(self.d / decl)]
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_good_run_writes_record(self):
        rc, out, err = self.run_cli("--out", str(self.d / "o.json"))
        self.assertEqual(rc, 0, err)
        rec = json.loads((self.d / "o.json").read_text(encoding="utf-8"))
        self.assertEqual(rec["audit_type"], "berelemzo_audit/1")
        self.assertEqual(rec["legal_status"], "REVIEW_REQUIRED")
        self.assertEqual(rec["egress"]["status"], "PASSED")
        self.assertIn("Audit:", out)

    def test_not_met_gives_exit_1(self):
        bad = copy.deepcopy(self.decl)
        bad["governance"]["representative_involved"] = False
        (self.d / "bad.json").write_text(json.dumps(bad), encoding="utf-8")
        rc, _, _ = self.run_cli(decl="bad.json")
        self.assertEqual(rc, 1)

    def test_input_errors_give_exit_2(self):
        argv = ["--data", str(self.d / "nincs.csv"), "--config", str(self.d / "c.json"), "--audit-date", "2026-10-29", "--input-reality", "REAL"]
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(argv), 2)
        (self.d / "o.json").write_text("{}", encoding="utf-8")
        self.assertEqual(self.run_cli("--out", str(self.d / "o.json"))[0], 2)                 # nem ír felül
        self.assertEqual(self.run_cli("--out", str(self.d / "a.csv"), "--overwrite")[0], 2)   # nem írja át az adatfájlt
        self.assertTrue((self.d / "a.csv").read_text(encoding="utf-8").startswith("job_id,sex"))

    def test_bad_number_error_never_echoes_values(self):
        lines = (self.d / "a.csv").read_text(encoding="utf-8").splitlines()
        lines[1] = lines[1].replace(",1.0,", ",TITKOS-12345,", 1) if ",1.0," in lines[1] else lines[1].replace(",0.5,", ",TITKOS-12345,", 1)
        (self.d / "b.csv").write_text("\n".join(lines), encoding="utf-8")
        rc, out, err = self.run_cli(data="b.csv")
        self.assertEqual(rc, 2)
        self.assertNotIn("TITKOS", err + out)

    def test_egress_block_prevents_output(self):
        write_csv(self.d / "e.csv", [r + ["x"] for r in self.rows], header=HEADER + ["jelzo@pelda.example"])
        rc, out, err = self.run_cli("--out", str(self.d / "blocked.json"), data="e.csv")
        self.assertEqual(rc, 3)
        self.assertFalse((self.d / "blocked.json").exists())
        self.assertIn("BLOCKED", err)


if __name__ == "__main__":
    unittest.main()
