"""Parancssor: python -m berelemzo_audit --data ADAT.csv --config KONFIG.json --audit-date ÉÉÉÉ-HH-NN [--declarations NYILATKOZAT.json]
[--result EREDMENY.json] --input-reality REAL|SYNTHETIC|MIXED [--out AUDIT.json]

Az egyéni szintű adatfájlt helyben kell futtatni; a kimenet csak aggregátum. Ha a kimeneti kapu BLOCKED, a kimenet nem íródik ki.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .engine import run_audit
from .inputs import IntakeError, load_config, load_declarations, load_rows, parse_date


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="berelemzo_audit", description="Bértranszparencia megfelelőségi audit (determinisztikus, MI-mentes).")
    p.add_argument("--data", required=True, help="egyéni szintű adatfájl (CSV, fehérlistás oszlopok), helyi fájl")
    p.add_argument("--config", required=True, help="pontozási konfiguráció (JSON)")
    p.add_argument("--audit-date", required=True, help="az audit napja (ÉÉÉÉ-HH-NN), a lejáratok számításához")
    p.add_argument("--declarations", help="a szervezet nyilatkozatai (JSON)")
    p.add_argument("--result", help="a Bérelemző eredményfájlja a kereszt-ellenőrzéshez (JSON)")
    p.add_argument("--input-reality", required=True, choices=("REAL", "SYNTHETIC", "MIXED"), help="a bemenet jellege")
    p.add_argument("--delimiter", default=",")
    p.add_argument("--pay-basis", choices=("components", "total"), default="components",
                   help="components: a komponensek a kifizetett összegek (alapértelmezés); total: az összes díjazás a kifizetett, a komponensek teljes munkaidősek")
    p.add_argument("--out", help="az audit-rekord helye (JSON); nélküle a standard kimenetre ír")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--version", action="version", version=f"berelemzo_audit {__version__}")
    a = p.parse_args(argv)
    try:
        if a.out and Path(a.out).exists() and not a.overwrite:
            raise IntakeError("A kimeneti fájl már létezik (--overwrite a felülíráshoz).")
        if a.out and Path(a.out).resolve() == Path(a.data).resolve():
            raise IntakeError("A kimenet nem lehet azonos az adatfájllal.")
        audit_date = parse_date(a.audit_date, "audit")
        cfg = load_config(a.config)
        config_raw = json.loads(Path(a.config).read_text(encoding="utf-8"))
        decl = load_declarations(a.declarations)
        ds = load_rows(a.data, a.delimiter, a.pay_basis)
        result = None
        if a.result:
            try:
                result = json.loads(Path(a.result).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise IntakeError(f"Az eredményfájl nem olvasható: {type(exc).__name__}") from None
        record = run_audit(ds, cfg, decl, audit_date, result=result, config_raw=config_raw, input_reality=a.input_reality)
    except IntakeError as exc:
        print(f"Hiba: {exc}", file=sys.stderr)
        return 2
    if record["egress"]["status"] == "BLOCKED":
        print("A kimeneti kapu BLOCKED: az audit-rekord nem íródik ki.", file=sys.stderr)
        for i in record["egress"]["issues"][:10]:
            print(f"  {i['locator']}: {i['issue']}", file=sys.stderr)
        return 3
    text = json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
        s = record["summary"]["by_status"]
        print("Audit: " + ", ".join(f"{k} {v}" for k, v in s.items() if v) + f". Lenyomat: {record['fingerprint']['result'][:16]}…")
    else:
        print(text)
    return 1 if record["summary"]["by_status"]["NOT_MET"] else 0
