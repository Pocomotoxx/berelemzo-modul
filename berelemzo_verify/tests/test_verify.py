import copy
import io
import json
import random
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from berelemzo.core import JobStats, analyze
from berelemzo.intake import parse_config
from berelemzo.stats import t_upper_quantile as core_quantile

from berelemzo_verify import checks
from berelemzo_verify.benchmark import run_benchmark
from berelemzo_verify.cli import main
from berelemzo_verify.mutations import CATALOG, refingerprint
from berelemzo_verify.report import verify
from berelemzo_verify.tdist import upper_quantile

from .support import clean_pair

ROOT = Path(__file__).resolve().parents[2]


def status_map(rec):
    return {c["id"]: c["status"] for c in rec["checks"]}


class TdistTests(unittest.TestCase):
    def test_table_values(self):
        for df, expected in ((1, 6.313752), (5, 2.015048), (10, 1.812461), (30, 1.697261), (100, 1.660234)):
            self.assertAlmostEqual(upper_quantile(0.05, df), expected, places=5, msg=f"df={df}")

    def test_fixed_reference_values(self):
        ref = {2.5: 2.5582186141359355, 7.3: 1.8829300179564308, 19.9: 1.725138790921033,
               48.2: 1.6770872569879265, 233.0: 1.6514196466104323}
        for df, expected in ref.items():
            self.assertAlmostEqual(upper_quantile(0.05, df), expected, places=7)

    def test_agrees_with_core_implementation(self):
        rng = random.Random(5)
        for _ in range(40):
            df = rng.uniform(1.2, 400.0)
            self.assertAlmostEqual(upper_quantile(0.05, df), core_quantile(0.05, df), places=6)


class CleanResultTests(unittest.TestCase):
    def test_clean_results_have_no_flags(self):
        for seed, n_jobs, delta in ((11, 14, 0.07), (31, 12, 0.0), (77, 16, 0.1)):
            res, cfg = clean_pair(seed=seed, n_jobs=n_jobs, delta=delta, need_suppressed=False)
            rec = verify(res, cfg)
            self.assertEqual(rec["summary"]["FAIL"], 0, rec["checks"])
            self.assertEqual(rec["summary"]["WARN"], 0, rec["checks"])
            self.assertEqual(rec["summary"]["SKIPPED"], 0)
            self.assertEqual(rec["verdict"], "NO_FAILURES")

    def test_without_config_only_config_checks_are_skipped(self):
        res, _ = clean_pair()
        st = status_map(verify(res, None))
        self.assertEqual(st["V03"], "SKIPPED")
        self.assertTrue(all(v in ("PASS", "SKIPPED") for v in st.values()))

    def test_eige14_example_config_with_level_max_list(self):
        cfg_raw = json.loads((ROOT / "berelemzo" / "examples" / "config.eige14.example.json").read_text(encoding="utf-8"))
        rng = random.Random(3)
        stats = {}
        cfg = parse_config(cfg_raw)
        for jid in cfg_raw["jobs"]:
            st = stats.setdefault(jid, JobStats())
            for i in range(14):
                (st.f if i % 2 else st.m).add(float(400000 + 90000 * int(jid[-1]) + rng.randint(-20000, 20000)))
        res = json.loads(json.dumps(analyze(cfg, stats, {"other_sex": 0, "unknown_job": 0})))
        rec = verify(res, cfg_raw)
        self.assertEqual(rec["summary"]["FAIL"], 0, rec["checks"])
        self.assertIsInstance(res["parameters"]["level_max"], list)

    def test_fingerprint_matches_core(self):
        res, _ = clean_pair()
        self.assertEqual(status_map(verify(res, None))["V02"], "PASS")

    def test_text_scan_ignores_hex_digests_but_flags_digits(self):
        res, cfg = clean_pair()
        self.assertEqual(status_map(verify(res, cfg))["V18"], "PASS")
        res2 = copy.deepcopy(res)
        res2["notes"].append("azonosító 123456789")
        self.assertEqual(status_map(verify(refingerprint(res2), cfg))["V18"], "FAIL")


class StructuralFailureTests(unittest.TestCase):
    def test_structural_error_skips_dependent_checks(self):
        res, cfg = clean_pair()
        bad = copy.deepcopy(res)
        del bad["summary"]
        st = status_map(verify(refingerprint(bad), cfg))
        self.assertEqual(st["V01"], "FAIL")
        self.assertEqual(st["V11"], "SKIPPED")
        self.assertEqual(st["V18"], "PASS")

    def test_non_object_input_does_not_crash(self):
        for bad in (None, 5, "x", [], [1, 2]):
            rec = verify(bad, None)
            self.assertEqual(rec["verdict"], "FAILURES" if bad != [] else rec["verdict"])
            self.assertIn("V01", status_map(rec))

    def test_findings_carry_resolvable_locators(self):
        res, cfg = clean_pair()
        bad = copy.deepcopy(res)
        c = next(x for x in bad["categories"] if not x["suppressed"])
        c["t_c_point_threshold"] = not c["t_c_point_threshold"]
        rec = verify(refingerprint(bad), cfg)
        f = next(x for chk in rec["checks"] if chk["id"] == "V07" for x in chk["findings"])
        node = bad
        for part in f["locator"].strip("/").split("/"):
            node = node[int(part)] if isinstance(node, list) else node[part]
        self.assertEqual(node, c["t_c_point_threshold"])


class BenchmarkTests(unittest.TestCase):
    def test_every_check_has_a_mutation_that_expects_it(self):
        covered = {cid for m in CATALOG for cid in m.expect}
        self.assertEqual(covered, {f"V{i:02d}" for i in range(1, 19)})

    def test_benchmark_detects_all_applicable_mutations(self):
        for seed in (11, 40, 90):
            res, cfg = clean_pair(seed=seed)
            rep = run_benchmark(res, cfg)
            self.assertFalse(rep["false_positive"], rep["control_flags"])
            missed = [r["id"] for r in rep["mutations"] if r["applicable"] and not r["detected"]]
            self.assertEqual(missed, [], rep)
            self.assertEqual(rep["summary"]["not_applicable"], 0, rep)
            self.assertEqual(rep["summary"]["detection_rate"], 1.0)

    def test_stale_fingerprint_is_the_only_flag_for_m22(self):
        res, cfg = clean_pair()
        m = next(x for x in CATALOG if x.id == "M22")
        mr, mc = m.fn(res, cfg)
        flagged = [c["id"] for c in verify(mr, mc)["checks"] if c["status"] in ("FAIL", "WARN")]
        self.assertEqual(flagged, ["V02"])


class CliTests(unittest.TestCase):
    def test_cli_exit_codes_and_record(self):
        res, cfg = clean_pair()
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "r.json").write_text(json.dumps(res), encoding="utf-8")
            (d / "c.json").write_text(json.dumps(cfg), encoding="utf-8")
            out = d / "l1.json"
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--result", str(d / "r.json"), "--config", str(d / "c.json"), "--out", str(out)]), 0)
            rec = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(rec["verdict"], "NO_FAILURES")
            self.assertIn("nem azonos azzal", rec["coverage_note"])
            bad = copy.deepcopy(res)
            bad["summary"]["sampling_signals"] += 1
            (d / "b.json").write_text(json.dumps(refingerprint(bad)), encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--result", str(d / "b.json"), "--config", str(d / "c.json")]), 1)
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--result", str(d / "r.json"), "--out", str(out)]), 2)  # nem ír felül

    def test_record_is_deterministic(self):
        res, cfg = clean_pair()
        self.assertEqual(verify(res, cfg), verify(copy.deepcopy(res), copy.deepcopy(cfg)))


if __name__ == "__main__":
    unittest.main()
