"""Tesztsegéd: ismert jó eredményt állít elő a Bérelemzővel (csak a tesztekben importáljuk, az ellenőrző nem)."""

from __future__ import annotations

import json

from berelemzo.core import JobStats, analyze
from berelemzo.intake import parse_config
from berelemzo.tests import synth


def clean_pair(seed: int = 11, n_jobs: int = 14, delta: float = 0.07, need_suppressed: bool = True):
    """(eredmény, konfiguráció) pár, JSON-on átvezetve. Olyan magot keres, amelyben van elnyomott és olyan közölt
    kategória is, ahol a mutációk alkalmazhatók."""
    for s in range(seed, seed + 400):
        cfg_raw, rows = synth.make(seed=s, n_jobs=n_jobs, delta=delta)
        cfg = parse_config(cfg_raw)
        stats = {}
        for jid, sx, pay in rows:
            st = stats.setdefault(jid, JobStats())
            (st.f if sx == "F" else st.m).add(float(pay))
        res = analyze(cfg, stats, {"other_sex": 0, "unknown_job": 0})
        cats = res["categories"]
        rep = [c for c in cats if not c["suppressed"]]
        ok = (len(rep) >= 3 and any(c["gap"] > 0.03 and c["t"] is not None for c in rep)
              and (not need_suppressed or any(c["suppressed"] for c in cats)))
        if ok:
            return json.loads(json.dumps(res)), json.loads(json.dumps(cfg_raw))
    raise RuntimeError("nem találtam megfelelő tiszta mintát")
