"""Kanonikus JSON és SHA-256: az eredmény- és konfiguráció-lenyomat specifikációja.

A kanonikus alak: kulcsok szerint rendezett, szóköz nélküli JSON, nem-ASCII karakterek változatlanul, UTF-8 bájtok.
"""

from __future__ import annotations

import hashlib
import json


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256(obj) -> str:
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


def canonical_config(cfg: dict) -> dict:
    """A konfigurációs fájl kanonikus alakja (a Bérelemző konfiguráció-lenyomatának specifikációja)."""
    scheme = cfg["scheme"]
    weights = [float(w) for w in scheme["weights"]]
    lm = scheme.get("level_max", 5)
    level_max = [float(m) for m in lm] if isinstance(lm, list) else float(lm)
    jobs = {str(k): [float(x) for x in v] for k, v in cfg["jobs"].items()}
    return {
        "scheme_name": str(scheme.get("name", "")),
        "weights": weights,
        "level_max": level_max,
        "band_width": float(cfg.get("band_width", 5.0)),
        "min_cell": cfg.get("min_cell", 5),
        "jobs": jobs,
    }
