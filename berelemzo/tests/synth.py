"""Szintetikus szervezet a tesztekhez és a kézi kipróbáláshoz (soha nem valós adat)."""

from __future__ import annotations

import random

WEIGHTS = [0.40, 0.35, 0.15, 0.10]


def make(seed: int = 7, n_jobs: int = 12, delta: float = 0.0, sd_ind: float = 0.10):
    rng = random.Random(seed)
    jobs = {f"J{i:02d}": [rng.randint(1, 5) for _ in WEIGHTS] for i in range(n_jobs)}
    rows = []
    for jid, lv in jobs.items():
        base = 10.4 + 0.012 * sum(w * l for w, l in zip(WEIGHTS, lv)) * 20
        for _ in range(rng.randint(8, 25)):
            female = rng.random() < 0.5
            lp = base + rng.gauss(0, sd_ind) - (delta if female else 0.0)
            rows.append((jid, "F" if female else "M", round(2.718281828459045 ** lp, 2)))
    cfg = {"scheme": {"name": "teszt", "weights": WEIGHTS}, "band_width": 10.0, "min_cell": 5, "jobs": jobs}
    return cfg, rows


def write_csv(path, rows, header=("job_id", "sex", "pay"), delimiter=","):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(delimiter.join(header) + "\n")
        for r in rows:
            fh.write(delimiter.join(str(x) for x in r) + "\n")
