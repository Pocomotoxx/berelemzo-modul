"""Az L1 ellenőrző saját ellenőrzése: észlelési arány a hibabeoltott katalóguson és téves riasztás a tiszta kontrollon.

Használat: python -m berelemzo_verify.benchmark --result TISZTA_EREDMENY.json [--config KONFIG.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .mutations import CATALOG, refingerprint
from .report import verify

_RANK = {"PASS": 0, "SKIPPED": 0, "WARN": 1, "FAIL": 2}


def run_benchmark(clean: dict, config: dict | None = None) -> dict:
    control = verify(clean, config)
    control_flags = [c["id"] for c in control["checks"] if c["status"] in ("FAIL", "WARN")]
    rows = []
    for m in CATALOG:
        out = m.fn(clean, config)
        if out is None:
            rows.append({"id": m.id, "name": m.name, "applicable": False, "detected": None})
            continue
        mr, mc = out
        if m.refp:
            refingerprint(mr)
        rec = verify(mr, mc)
        status = {c["id"]: c["status"] for c in rec["checks"]}
        detected = all(_RANK.get(status.get(cid), 0) >= _RANK[need] for cid, need in m.expect.items())
        rows.append({"id": m.id, "name": m.name, "applicable": True, "expect": m.expect, "detected": detected,
                     "flagged": sorted(cid for cid, s in status.items() if s in ("FAIL", "WARN"))})
    applicable = [r for r in rows if r["applicable"]]
    hit = sum(1 for r in applicable if r["detected"])
    return {
        "control_flags": control_flags,
        "false_positive": bool(control_flags),
        "mutations": rows,
        "summary": {"applicable": len(applicable), "detected": hit,
                    "detection_rate": round(hit / len(applicable), 4) if applicable else None,
                    "not_applicable": len(rows) - len(applicable)},
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="berelemzo_verify.benchmark", description="Hibabeoltott benchmark az L1 ellenőrzőhöz.")
    p.add_argument("--result", required=True, help="ismert tiszta eredményfájl")
    p.add_argument("--config", help="a hozzá tartozó konfiguráció")
    a = p.parse_args(argv)
    try:
        clean = json.loads(Path(a.result).read_text(encoding="utf-8"))
        cfg = json.loads(Path(a.config).read_text(encoding="utf-8")) if a.config else None
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Hiba: a bemenet nem olvasható ({type(exc).__name__}).", file=sys.stderr)
        return 2
    rep = run_benchmark(clean, cfg)
    print(json.dumps(rep, ensure_ascii=False, indent=2, sort_keys=True))
    s = rep["summary"]
    return 0 if (not rep["false_positive"] and s["detected"] == s["applicable"]) else 1


if __name__ == "__main__":
    sys.exit(main())
