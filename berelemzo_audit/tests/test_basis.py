import json
import os
import tempfile
import unittest

from berelemzo_audit.engine import run_audit
from berelemzo_audit.inputs import IntakeError, load_config, load_rows

from .fixtures import AUDIT_DATE, make_world, write_csv
from .support import status

HEADER_T = ["job_id", "sex", "fte", "alapber", "rendszeres_potlek", "valtozo_bonusz", "termeszetbeni", "tulora", "kifizetett_osszes_kezi"]


def run(rows, header, basis="components", cfg=None):
    d = tempfile.mkdtemp()
    write_csv(os.path.join(d, "a.csv"), rows, header=header)
    with open(os.path.join(d, "c.json"), "w", encoding="utf-8") as fh:
        json.dump(cfg or {"grouping": "job", "min_cell": 5}, fh)
    ds = load_rows(os.path.join(d, "a.csv"), pay_basis=basis)
    return ds, run_audit(ds, load_config(os.path.join(d, "c.json")), {}, AUDIT_DATE)


def fte_scaled_rows(n=12):
    """Részmunkaidősök: a komponensek teljes munkaidős összegek, az összes díjazás a ténylegesen kifizetett (komponens × fte)."""
    rows = []
    for i in range(n):
        for sx, base in (("M", 600000), ("F", 600000)):
            fte = 0.5 if (sx == "F" and i < 6) else 1.0
            comp = [base + i * 1000, 0, 0, 0, 0]
            rows.append(["A", sx, fte] + comp + [(base + i * 1000) * fte])
    return rows


class PayBasisTests(unittest.TestCase):
    def test_default_components_basis_double_normalizes_and_is_flagged(self):
        ds, rec = run(fte_scaled_rows(), HEADER_T, "components")
        self.assertEqual(ds.total_mismatch_rows, 6)
        self.assertEqual(ds.total_equals_components_times_fte, 6)
        pay02 = status(rec, "PAY-02")
        self.assertEqual(pay02["status"], "NOT_MET")
        self.assertIn("kétszeres", pay02["findings"][0]["detail"])
        pay01 = status(rec, "PAY-01")
        self.assertEqual(pay01["status"], "NOT_MET")
        self.assertIn("× fte", pay01["findings"][0]["detail"])
        # a kétszeres normalizálás a részmunkaidős nők bérét felfelé torzítja: negatív (nők javára) rés
        self.assertLess(rec["indicators"]["categories"][0]["mean_gap"], -0.2)

    def test_total_basis_normalizes_once_and_removes_the_distortion(self):
        ds, rec = run(fte_scaled_rows(), HEADER_T, "total")
        self.assertEqual(rec["scope"]["pay_basis"], "total")
        self.assertAlmostEqual(rec["indicators"]["categories"][0]["mean_gap"], 0.0, places=6)
        self.assertEqual(status(rec, "PAY-02")["status"], "NOT_ASSESSABLE")     # nincs FTE-hiba, a dokumentáció hiányzik

    def test_total_basis_requires_the_total_column(self):
        rows = [r[:-1] for r in fte_scaled_rows()]
        d = tempfile.mkdtemp()
        write_csv(os.path.join(d, "a.csv"), rows, header=HEADER_T[:-1])
        with self.assertRaises(IntakeError):
            load_rows(os.path.join(d, "a.csv"), pay_basis="total")
        with self.assertRaises(IntakeError):
            load_rows(os.path.join(d, "a.csv"), pay_basis="nonsense")


class VacuousAndPrivacyTests(unittest.TestCase):
    def test_sta_02_is_not_met_vacuously_when_every_category_is_suppressed(self):
        _, rows = make_world(seed=3, n_jobs=8, per_job=(2, 7))
        d = tempfile.mkdtemp()
        write_csv(os.path.join(d, "a.csv"), rows)
        with open(os.path.join(d, "c.json"), "w", encoding="utf-8") as fh:
            json.dump({"grouping": "job", "min_cell": 5}, fh)
        rec = run_audit(load_rows(os.path.join(d, "a.csv")), load_config(os.path.join(d, "c.json")), {}, AUDIT_DATE)
        sta = status(rec, "STA-02")
        self.assertEqual(sta["status"], "NOT_ASSESSABLE")
        self.assertTrue(sta["needs"])

    def test_variable_pay_of_a_small_recipient_group_is_not_published(self):
        rows = []
        for i in range(12):
            rows.append(["A", "M", 1.0, 500000, 0, 40000 if i < 2 else 0, 0, 0, 3])
            rows.append(["A", "F", 1.0, 480000, 0, 0, 0, 0, 3])
        d = tempfile.mkdtemp()
        write_csv(os.path.join(d, "a.csv"), rows, header=["job_id", "sex", "fte", "alapber", "rendszeres_potlek", "valtozo_bonusz", "termeszetbeni", "tulora", "teljesitmenysav"])
        with open(os.path.join(d, "c.json"), "w", encoding="utf-8") as fh:
            json.dump({"grouping": "job", "min_cell": 5}, fh)
        rec = run_audit(load_rows(os.path.join(d, "a.csv")), load_config(os.path.join(d, "c.json")), {}, AUDIT_DATE)
        vp = rec["indicators"]["variable_pay"]
        self.assertTrue(vp["suppressed"])
        self.assertEqual(vp["recipients_m"], "<5")
        text = json.dumps(vp)
        for leaked in ("share_receiving", "mean_gap", "median_gap"):
            self.assertNotIn(leaked, text)
        self.assertNotIn("0.166667", json.dumps(rec))        # 2/12: a pontos létszámot felfedő arány


if __name__ == "__main__":
    unittest.main()
