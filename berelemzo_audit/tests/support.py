"""Tesztsegédek: világ építése, audit futtatása ideiglenes fájlokon."""

from __future__ import annotations

import copy
import functools
import json
import os
import tempfile

from berelemzo_audit.engine import run_audit
from berelemzo_audit.inputs import load_config, load_declarations, load_rows

from .fixtures import AUDIT_DATE, HEADER, find_world, good_declarations, write_csv


@functools.lru_cache(maxsize=None)
def _world(kind: str):
    if kind == "good":
        return find_world(need_no_trigger=True, need_suppressed=False, seed=7)
    if kind == "suppressed":
        return find_world(need_no_trigger=True, need_suppressed=True, seed=7, per_job=(3, 14))
    if kind == "trigger":
        cfg, rows = find_world(need_no_trigger=False, need_suppressed=False, seed=7, delta=0.12)
        return cfg, rows
    raise KeyError(kind)


def world(kind: str = "good"):
    cfg, rows = _world(kind)
    return copy.deepcopy(cfg), copy.deepcopy(rows)


def audit(cfg, rows, decl, *, header=HEADER, result=None, audit_date=AUDIT_DATE, reality="SYNTHETIC", extra_rows_cols=None):
    d = tempfile.mkdtemp()
    data = os.path.join(d, "adat.csv")
    write_csv(data, rows, header=header)
    cpath = os.path.join(d, "cfg.json")
    with open(cpath, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)
    dpath = os.path.join(d, "decl.json")
    with open(dpath, "w", encoding="utf-8") as fh:
        json.dump(decl, fh)
    rec = run_audit(load_rows(data), load_config(cpath), load_declarations(dpath), audit_date, result=result, config_raw=cfg, input_reality=reality)
    return rec


def status(rec, cid):
    return next(c for c in rec["controls"] if c["id"] == cid)
