import copy
import json
import os
import tempfile
import unittest

from berelemzo_audit.engine import run_audit
from berelemzo_audit.inputs import IntakeError, load_config, load_rows

from .fixtures import AUDIT_DATE, HEADER, make_world, write_csv
from .support import status


def run(rows, header=HEADER, cfg=None, decl=None):
    d = tempfile.mkdtemp()
    write_csv(os.path.join(d, "a.csv"), rows, header=header)
    with open(os.path.join(d, "c.json"), "w", encoding="utf-8") as fh:
        json.dump(cfg or {"grouping": "job", "min_cell": 5}, fh)
    ds, c = load_rows(os.path.join(d, "a.csv")), load_config(os.path.join(d, "c.json"))
    return run_audit(ds, c, decl or {}, AUDIT_DATE)


class GroupingTests(unittest.TestCase):
    def test_job_level_grouping_reports_categories_without_scoring(self):
        _, rows = make_world(seed=3, n_jobs=5, per_job=(20, 30))
        rec = run(rows)
        cats = rec["indicators"]["categories"]
        self.assertEqual(len(cats), 5)
        self.assertTrue(all(c["score_range"] is None for c in cats if not c["suppressed"]))
        self.assertTrue(any(not c["suppressed"] for c in cats))
        for cid in ("JOB-01", "JOB-02", "JOB-03"):
            self.assertEqual(status(rec, cid)["status"], "NOT_ASSESSABLE", cid)
            self.assertTrue(status(rec, cid)["needs"])
        self.assertEqual(status(rec, "STA-01")["status"], "MET")
        self.assertEqual(rec["egress"]["status"], "PASSED")
        self.assertTrue(any("azonos munka" in r["comparison_group"] for r in rec["pay_equity_records"] + rec["pay_equity_records_not_valid"]))

    def test_small_jobs_are_fully_suppressed(self):
        _, rows = make_world(seed=3, n_jobs=8, per_job=(2, 7))
        rec = run(rows)
        reported = [c for c in rec["indicators"]["categories"] if not c["suppressed"]]
        self.assertEqual(reported, [])
        sta = status(rec, "STA-02")
        self.assertEqual(sta["metrics"]["categories_reported"], 0)
        self.assertGreater(status(rec, "DPR-02")["metrics"]["share_in_suppressed_categories"], 0.9)
        self.assertEqual(status(rec, "DPR-02")["status"], "NOT_MET")

    def test_known_gap_within_a_job_is_found(self):
        rows = []
        for i in range(10):
            rows.append(["A", "M", 1.0, 600000 + i * 500, 0, 0, 0, 0, 3])
            rows.append(["A", "F", 1.0, round((600000 + i * 500) * 0.88), 0, 0, 0, 0, 3])
        rec = run(rows)
        c = rec["indicators"]["categories"][0]
        self.assertAlmostEqual(c["mean_gap"], 0.12, places=3)
        self.assertTrue(c["sampling_signal"])
        self.assertEqual(status(rec, "STA-02")["status"], "NOT_MET")

    def test_grouping_cannot_be_combined_with_scheme(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "c.json")
        for bad in ({"grouping": "job", "scheme": {"weights": [1.0]}}, {"grouping": "other"}, {"grouping": "job", "min_cell": 3}):
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(bad, fh)
            with self.assertRaises(IntakeError):
                load_config(p)


class TotalIntegrationTests(unittest.TestCase):
    def _rows(self, wrong):
        _, rows = make_world(seed=5, n_jobs=3, per_job=(12, 16))
        out = []
        for i, r in enumerate(rows):
            comp_sum = sum(float(x) for x in r[3:8])
            out.append(r[:-1] + [comp_sum + (5000 if i < wrong else 0)] + [r[-1]])
        return out

    def test_total_that_differs_from_the_components_is_flagged(self):
        header = HEADER[:-1] + ["kifizetett_osszes_kezi", "teljesitmenysav"]
        rec = run(self._rows(wrong=7), header=header)
        c = status(rec, "PAY-01")
        self.assertEqual(c["status"], "NOT_MET")
        self.assertEqual(c["metrics"]["rows_total_differs_from_component_sum"], 7)
        rec = run(self._rows(wrong=3), header=header)
        c = status(rec, "PAY-01")
        self.assertEqual(c["status"], "NOT_MET")
        self.assertEqual(c["metrics"]["rows_total_differs_from_component_sum"], "<5")
        clean = status(run(self._rows(wrong=0), header=header), "PAY-01")
        self.assertEqual(clean["status"], "NOT_ASSESSABLE")        # az összeg rendben, a deklarációk hiányoznak
        self.assertEqual(clean["metrics"]["rows_total_differs_from_component_sum"], 0)


if __name__ == "__main__":
    unittest.main()
