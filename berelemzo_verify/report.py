"""Az L1 rekord összeállítása: ellenőrzések, összegzés, végállapot és lefedettségi nyilatkozat."""

from __future__ import annotations

from . import VERIFIER_ID, __version__
from .canon import sha256
from .checks import run_all

COVERAGE_NOTE = (
    "Az L1 csak az eredményfájl és a konfiguráció belső épségét és konzisztenciáját vizsgálja. "
    "Nem vizsgálja a nyers adatot (V20–V22 helyi ellenőrzések), a módszertan helyességét, a pontozás megalapozottságát "
    "és a jogi megfelelést. A „nincs eltérés” nem azonos azzal, hogy „helyes”."
)


def verify(result, config=None) -> dict:
    checks = run_all(result, config)
    counts = {s: sum(1 for c in checks if c["status"] == s) for s in ("PASS", "FAIL", "WARN", "SKIPPED")}
    target = {"result_sha256": sha256(result) if isinstance(result, (dict, list)) else None}
    if isinstance(result, dict):
        target["method_id"] = result.get("method_id") if isinstance(result.get("method_id"), str) else None
        target["core_version"] = result.get("core_version") if isinstance(result.get("core_version"), str) else None
    return {
        "verifier": VERIFIER_ID,
        "verifier_version": __version__,
        "target": target,
        "config_supplied": config is not None,
        "checks": checks,
        "summary": counts,
        "verdict": "FAILURES" if counts["FAIL"] else "NO_FAILURES",
        "coverage_note": COVERAGE_NOTE,
    }
