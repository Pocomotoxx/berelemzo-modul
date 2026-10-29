import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from berelemzo.cli import main
from berelemzo.intake import IntakeError, parse_config, read_pay_file

from . import synth


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cfg_raw, self.rows = synth.make(seed=2, n_jobs=8)
        self.cfg = parse_config(self.cfg_raw)

    def tearDown(self):
        self.tmp.cleanup()

    def test_extra_personal_columns_are_rejected(self):
        for extra in ("name", "adoszam", "bankszamlaszam", "email"):
            p = self.dir / f"{extra}.csv"
            synth.write_csv(p, [(r[0], r[1], r[2], "x") for r in self.rows[:5]], header=("job_id", "sex", "pay", extra))
            with self.assertRaises(IntakeError) as cm:
                read_pay_file(p, self.cfg)
            self.assertIn(extra, str(cm.exception))

    def test_error_messages_never_echo_values(self):
        p = self.dir / "bad.csv"
        synth.write_csv(p, [("J00", "F", "titkos-bér-123456")])
        with self.assertRaises(IntakeError) as cm:
            read_pay_file(p, self.cfg)
        self.assertNotIn("titkos", str(cm.exception))
        self.assertNotIn("123456", str(cm.exception))

    def test_nonpositive_and_nonfinite_pay_rejected(self):
        for bad in ("0", "-5", "nan", "inf"):
            p = self.dir / "b.csv"
            synth.write_csv(p, [("J00", "F", bad)])
            with self.assertRaises(IntakeError):
                read_pay_file(p, self.cfg)

    def test_other_sex_and_unknown_job_are_counted_not_used(self):
        p = self.dir / "x.csv"
        synth.write_csv(p, [("J00", "X", 400000), ("ZZZ", "F", 400000), ("J00", "F", 400000)])
        stats, ex = read_pay_file(p, self.cfg)
        self.assertEqual(ex, {"other_sex": 1, "unknown_job": 1})
        self.assertEqual(stats["J00"].f.n, 1)
        self.assertEqual(stats["J00"].m.n, 0)

    def test_url_paths_refused(self):
        with self.assertRaises(IntakeError):
            read_pay_file("https://example.org/pay.csv", self.cfg)

    def test_config_rules(self):
        base = json.loads(json.dumps(self.cfg_raw))
        for mutate in (
            lambda c: c.update(min_cell=4),                       # a küszöb nem csökkenthető
            lambda c: c["scheme"].update(weights=[0.5, 0.5, 0.5]),
            lambda c: c.update(extra=1),
            lambda c: c["jobs"].update(J99=[1, 2]),
            lambda c: c["jobs"].update(J98=[1, 2, 3, 9]),
        ):
            c = json.loads(json.dumps(base))
            mutate(c)
            with self.assertRaises(IntakeError):
                parse_config(c)

    def test_cli_end_to_end_and_guards(self):
        cfg_p, csv_p, out_p = self.dir / "c.json", self.dir / "d.csv", self.dir / "r.json"
        cfg_p.write_text(json.dumps(self.cfg_raw), encoding="utf-8")
        synth.write_csv(csv_p, self.rows)
        buf, err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf), redirect_stderr(err):
            rc = main(["--config", str(cfg_p), "--data", str(csv_p), "--out", str(out_p)])
        self.assertEqual(rc, 0, err.getvalue())
        res = json.loads(out_p.read_text(encoding="utf-8"))
        self.assertEqual(res["method_id"], "berelemzo/1")
        self.assertIn("fingerprint", res)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--config", str(cfg_p), "--data", str(csv_p), "--out", str(out_p)]), 2)  # nem ír felül
            self.assertEqual(main(["--config", str(cfg_p), "--data", str(csv_p), "--out", str(csv_p), "--overwrite"]), 2)
        self.assertEqual(csv_p.read_text(encoding="utf-8").splitlines()[0], "job_id,sex,pay")  # a bemenet sértetlen

    def test_cli_semicolon_delimiter(self):
        cfg_p, csv_p = self.dir / "c.json", self.dir / "d.csv"
        cfg_p.write_text(json.dumps(self.cfg_raw), encoding="utf-8")
        synth.write_csv(csv_p, self.rows, delimiter=";")
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(main(["--config", str(cfg_p), "--data", str(csv_p), "--delimiter", ";"]), 0)
        self.assertIn('"categories"', buf.getvalue())


if __name__ == "__main__":
    unittest.main()
