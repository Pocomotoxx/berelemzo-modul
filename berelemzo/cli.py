"""Parancssori belépési pont: python -m berelemzo --config C --data D --out R"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .core import analyze
from .intake import IntakeError, load_config, read_pay_file


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="berelemzo", description="Bérelemző: determinisztikus, MI-mentes bérrés-számítás (helyi futtatás).")
    p.add_argument("--config", required=True, help="értékelési séma és munkakör-szintek (JSON)")
    p.add_argument("--data", required=True, help="helyi bérfájl (CSV: job_id, sex, pay)")
    p.add_argument("--out", help="az eredmény (JSON) helye; nélküle a standard kimenetre ír")
    p.add_argument("--delimiter", default=",", help="CSV-elválasztó (alapértelmezés: vessző)")
    p.add_argument("--overwrite", action="store_true", help="meglévő kimeneti fájl felülírása")
    p.add_argument("--version", action="version", version=f"berelemzo {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.out:
            out, data = Path(args.out).resolve(), Path(args.data).resolve()
            if out == data:
                raise IntakeError("A kimenet nem lehet azonos a bérfájllal.")
            if out.exists() and not args.overwrite:
                raise IntakeError("A kimeneti fájl már létezik (--overwrite a felülíráshoz).")
        cfg = load_config(args.config)
        stats, excluded = read_pay_file(args.data, cfg, args.delimiter)
        result = analyze(cfg, stats, excluded)
    except IntakeError as exc:
        print(f"Hiba: {exc}", file=sys.stderr)
        return 2
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        s = result["summary"]
        print(f"Kész: {s['categories_reported']} kategória közölve, {s['categories_suppressed']} elnyomva; "
              f"küszöbérintés: {s['point_threshold_hits']}, mintavételi jelzés: {s['sampling_signals']}. "
              f"Lenyomat: {result['fingerprint']['result'][:16]}…")
    else:
        print(text)
    return 0
