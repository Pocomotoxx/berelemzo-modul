"""Parancssori belépési pont: python -m berelemzo_verify --result EREDMENY.json [--config KONFIG.json] [--out L1.json]"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .report import verify


def _load(path: str, what: str):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Hiba: a(z) {what} nem olvasható vagy nem érvényes JSON ({type(exc).__name__}).") from None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="berelemzo_verify", description="A Bérelemző eredményének determinisztikus (L1) ellenőrzése.")
    p.add_argument("--result", required=True, help="a Bérelemző eredményfájlja (JSON)")
    p.add_argument("--config", help="a futtatáshoz használt konfiguráció (JSON), a V03 és a V14 teljes futtatásához")
    p.add_argument("--out", help="az L1 rekord helye (JSON); nélküle a standard kimenetre ír")
    p.add_argument("--overwrite", action="store_true", help="meglévő kimeneti fájl felülírása")
    p.add_argument("--version", action="version", version=f"berelemzo_verify {__version__}")
    a = p.parse_args(argv)
    if a.out and Path(a.out).exists() and not a.overwrite:
        print("Hiba: a kimeneti fájl már létezik (--overwrite a felülíráshoz).", file=sys.stderr)
        return 2
    record = verify(_load(a.result, "eredményfájl"), _load(a.config, "konfiguráció") if a.config else None)
    text = json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
        s = record["summary"]
        print(f"L1: PASS {s['PASS']}, FAIL {s['FAIL']}, WARN {s['WARN']}, SKIPPED {s['SKIPPED']} ({record['verdict']})")
    else:
        print(text)
    return 1 if record["summary"]["FAIL"] else 0
