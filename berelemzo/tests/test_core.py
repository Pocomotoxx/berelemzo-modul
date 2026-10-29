import copy
import json
import math
import unittest

from berelemzo.core import Acc, analyze, grade_of, job_score
from berelemzo.intake import IntakeError, parse_config
from berelemzo.core import JobStats
from berelemzo.stats import t_upper_quantile

from . import synth


def json_copy(obj):
    return json.loads(json.dumps(obj))


def build_stats(cfg, rows):
    stats = {}
    for jid, sx, pay in rows:
        st = stats.setdefault(jid, JobStats())
        (st.f if sx == "F" else st.m).add(float(pay))
    return stats


def reference(cfg, rows, width, k=5):
    """Független, naiv referencia: egyedi sorokból, külön kódúton."""
    by_grade = {}
    for jid, sx, pay in rows:
        g = grade_of(job_score(cfg["jobs"][jid], cfg["scheme"]["weights"]), width)
        by_grade.setdefault(g, {"F": [], "M": []})[sx].append(float(pay))
    out = {}
    for g, d in by_grade.items():
        f, m = d["F"], d["M"]
        if len(f) < k or len(m) < k:
            out[g] = None
            continue
        gap = (sum(m) / len(m) - sum(f) / len(f)) / (sum(m) / len(m))
        lf, lm = [math.log(x) for x in f], [math.log(x) for x in m]
        mf, mm = sum(lf) / len(lf), sum(lm) / len(lm)
        vf = sum((x - mf) ** 2 for x in lf) / (len(lf) - 1)
        vm = sum((x - mm) ** 2 for x in lm) / (len(lm) - 1)
        a, b = vm / len(lm), vf / len(lf)
        t = (mm - mf) / math.sqrt(a + b)
        df = (a + b) ** 2 / (a ** 2 / (len(lm) - 1) + b ** 2 / (len(lf) - 1))
        out[g] = (len(f), len(m), gap, t, df)
    return out


class CoreTests(unittest.TestCase):
    def test_score_and_grade(self):
        # 100 * (0,8*0,4 + 0,6*0,35 + 0,6*0,15 + 0,4*0,1) = 66
        self.assertAlmostEqual(job_score([4, 3, 3, 2], synth.WEIGHTS), 66.0, places=9)
        self.assertEqual(grade_of(66.0, 5.0), 14)
        self.assertEqual(grade_of(65.0, 5.0), 13)   # a sáv felső határa a sávhoz tartozik
        self.assertEqual(grade_of(0.0, 5.0), 1)

    def test_per_subfactor_level_max(self):
        w = [0.5, 0.5]
        # egységes skála és az azonos értékű lista ugyanazt adja
        self.assertAlmostEqual(job_score([4, 2], w, 5), job_score([4, 2], w, [5, 5]), places=12)
        # a szaktudás-jellegű részfaktor 0–8: a 4. szint a skála fele, nem a 4/5
        self.assertAlmostEqual(job_score([4, 5], w, [8, 5]), 100 * (0.5 * 0.5 + 0.5 * 1.0), places=12)
        self.assertAlmostEqual(job_score([8, 5], w, [8, 5]), 100.0, places=12)

    def test_eige14_example_config(self):
        import json
        from pathlib import Path
        p = Path(__file__).resolve().parents[1] / "examples" / "config.eige14.example.json"
        cfg = parse_config(json.loads(p.read_text(encoding="utf-8")))
        self.assertEqual(len(cfg.weights), 14)
        self.assertAlmostEqual(sum(cfg.weights), 1.0, places=12)
        self.assertAlmostEqual(job_score(list(cfg.level_max), cfg.weights, cfg.level_max), 100.0, places=9)
        # az EIGE-táblázat főfaktor-összegei: készségek 40, felelősség 35, erőfeszítés 15, munkakörülmények 10
        sums = [sum(cfg.weights[a:b]) for a, b in ((0, 5), (5, 9), (9, 12), (12, 14))]
        for got, want in zip(sums, (0.40, 0.35, 0.15, 0.10)):
            self.assertAlmostEqual(got, want, places=12)

    def test_level_max_list_validation(self):
        base = {"scheme": {"weights": [0.5, 0.5], "level_max": [8, 5]}, "jobs": {"J": [8, 5]}}
        self.assertEqual(parse_config(base).level_max, (8.0, 5.0))
        bad = json_copy(base)
        bad["scheme"]["level_max"] = [8]
        with self.assertRaises(IntakeError):
            parse_config(bad)
        bad = json_copy(base)
        bad["jobs"]["J"] = [9, 5]     # a 9. szint meghaladja a részfaktor 8-as maximumát
        with self.assertRaises(IntakeError):
            parse_config(bad)
        bad = json_copy(base)
        bad["jobs"]["J"] = [8, 6]     # a 6. szint meghaladja a másik részfaktor 5-ös maximumát
        with self.assertRaises(IntakeError):
            parse_config(bad)

    def test_scalar_and_equal_list_configs_give_equal_categories(self):
        cfg_raw, rows = synth.make(seed=9, n_jobs=10, delta=0.05)
        a = parse_config(cfg_raw)
        raw2 = json_copy(cfg_raw)
        raw2["scheme"]["level_max"] = [5] * len(raw2["scheme"]["weights"])
        b = parse_config(raw2)
        ra, rb = analyze(a, build_stats(cfg_raw, rows)), analyze(b, build_stats(cfg_raw, rows))
        self.assertEqual(ra["categories"], rb["categories"])

    def test_acc_merge_equals_single_pass(self):
        xs = [100.0 + 7 * i for i in range(40)]
        whole, a, b = Acc(), Acc(), Acc()
        for x in xs:
            whole.add(x)
        for x in xs[:13]:
            a.add(x)
        for x in xs[13:]:
            b.add(x)
        a.merge(b)
        self.assertEqual(a.n, whole.n)
        self.assertAlmostEqual(a.mean, whole.mean, places=12)
        self.assertAlmostEqual(a.m2, whole.m2, places=10)
        self.assertAlmostEqual(a.pay_sum, whole.pay_sum, places=8)

    def test_matches_naive_reference(self):
        cfg_raw, rows = synth.make(seed=11, n_jobs=14, delta=0.06)
        cfg = parse_config(cfg_raw)
        res = analyze(cfg, build_stats(cfg_raw, rows))
        ref = reference(cfg_raw, rows, cfg.band_width)
        seen = 0
        for c in res["categories"]:
            r = ref[c["grade"]]
            if r is None:
                self.assertTrue(c["suppressed"])
                continue
            seen += 1
            nf, nm, gap, t, df = r
            self.assertEqual((c["n_f"], c["n_m"]), (nf, nm))
            self.assertAlmostEqual(c["gap"], gap, places=6)
            self.assertAlmostEqual(c["t"], t, places=3)
            self.assertAlmostEqual(c["df"], df, places=2)
            self.assertEqual(c["welch_significant"], t > t_upper_quantile(0.05, df))
            self.assertEqual(c["t_c_point_threshold"], gap >= 0.05)
        self.assertGreater(seen, 0)

    def test_small_cells_are_suppressed_without_numbers(self):
        cfg_raw, rows = synth.make(seed=3, n_jobs=6)
        # egyetlen nőt hagyunk az egyik munkakörben
        target = rows[0][0]
        keep, women = [], 0
        for r in rows:
            if r[0] == target and r[1] == "F":
                women += 1
                if women > 1:
                    continue
            keep.append(r)
        cfg = parse_config(cfg_raw)
        res = analyze(cfg, build_stats(cfg_raw, keep))
        for c in res["categories"]:
            if c["suppressed"]:
                self.assertEqual(set(c), {"grade", "score_range", "suppressed"})
        text = json.dumps(res)
        self.assertNotIn('"pay"', text)

    def test_excluded_small_counts_are_floored(self):
        cfg_raw, rows = synth.make(seed=3, n_jobs=6)
        cfg = parse_config(cfg_raw)
        res = analyze(cfg, build_stats(cfg_raw, rows), {"other_sex": 1, "unknown_job": 0})
        self.assertEqual(res["excluded"], {"other_sex": "<5", "unknown_job": 0})

    def test_deterministic_and_fingerprint_sensitive(self):
        cfg_raw, rows = synth.make(seed=5)
        cfg = parse_config(cfg_raw)
        a = analyze(cfg, build_stats(cfg_raw, rows))
        b = analyze(cfg, build_stats(cfg_raw, rows))
        self.assertEqual(a, b)
        rows2 = copy.deepcopy(rows)
        rows2[0] = (rows2[0][0], rows2[0][1], rows2[0][2] + 1.0)
        c = analyze(cfg, build_stats(cfg_raw, rows2))
        self.assertNotEqual(a["fingerprint"], c["fingerprint"])

    def test_null_world_trigger_rate_is_close_to_model_expectation(self):
        # valós hézag nélkül a küszöbérintések átlagos száma közelítse a modell várható értékét
        hits, exp, runs = 0, 0.0, 120
        for s in range(runs):
            cfg_raw, rows = synth.make(seed=1000 + s, n_jobs=12, delta=0.0, sd_ind=0.15)
            cfg = parse_config(cfg_raw)
            res = analyze(cfg, build_stats(cfg_raw, rows))
            hits += res["summary"]["point_threshold_hits"]
            exp += res["summary"]["expected_point_hits_if_no_gap"]
        self.assertLess(abs(hits - exp) / runs, 0.35)


if __name__ == "__main__":
    unittest.main()
