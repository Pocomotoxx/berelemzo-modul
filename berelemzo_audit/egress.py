"""Kimeneti kapu: az audit-rekord csak aggregátumot tartalmazhat.

Ellenőrzések: nincs tiltott kulcs (egyéni bér- vagy azonosító jellegű kulcsnév), nincs 1–(k−1) közötti pontos darabszám
a `count`, `n_f`, `n_m`, `recipients_*` jellegű mezőkben, nincs azonosító-, URL- vagy utasításszerű szöveg.
A kapu heurisztika: nem jogi anonimizálás és nem megfelelőségi garancia.
"""

from __future__ import annotations

import re

from berelemzo_verify.checks import _EMAIL, _INSTRUCTION, _LONG_DIGITS, _URL

from .records import forbidden_key

COUNT_KEYS = re.compile(r"(^count$|^n_[a-z]+$|^recipients_[a-z]+$|_count$|^rows_)")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def scan(obj, k: int, path: str = "") -> list[dict]:
    """A rekord szabálysértései: [{locator, issue}]. Üres lista = a kapu átengedi."""
    out: list[dict] = []
    if isinstance(obj, dict):
        for key, val in obj.items():
            here = f"{path}/{key}"
            if forbidden_key(key):
                out.append({"locator": here, "issue": "tiltott kulcsnév (egyéni bér- vagy azonosító jelleg)"})
            if isinstance(key, str) and COUNT_KEYS.search(key) and isinstance(val, int) and not isinstance(val, bool) and 0 < val < k:
                out.append({"locator": here, "issue": f"kis darabszám pontosan közölve (< {k})"})
            out.extend(scan(val, k, here))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(scan(v, k, f"{path}/{i}"))
    elif isinstance(obj, str) and not _HEX64.match(obj):
        if _EMAIL.search(obj):
            out.append({"locator": path, "issue": "e-mail-cím jellegű szöveg"})
        if _URL.search(obj):
            out.append({"locator": path, "issue": "URL jellegű szöveg"})
        if _LONG_DIGITS.search(obj):
            out.append({"locator": path, "issue": "hosszú számsor (azonosító-gyanú)"})
        if _INSTRUCTION.search(obj):
            out.append({"locator": path, "issue": "utasításszerű szöveg"})
    return out
