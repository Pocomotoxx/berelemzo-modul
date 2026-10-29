"""Az audit-motor határa: MI-mentes, csak szabványos könyvtár (és a független ellenőrző), nincs hálózat és naplózás,
a számító modulok nem végeznek I/O-t, és nem importálják a számító `berelemzo` csomagot."""

import ast
import re
import sys
import unittest
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
FORBIDDEN = {"socket", "ssl", "http", "urllib", "urllib3", "requests", "httpx", "aiohttp", "ftplib", "smtplib",
             "telnetlib", "xmlrpc", "subprocess", "logging", "webbrowser"}
ALLOWED_OWN = {"berelemzo_audit", "berelemzo_verify"}
PURE = ("catalogue.py", "controls.py", "indicators.py", "engine.py", "egress.py", "records.py")


def imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module


class BoundaryTests(unittest.TestCase):
    def sources(self):
        return list(PKG.glob("*.py"))

    def test_stdlib_or_independent_verifier_only(self):
        std = set(sys.stdlib_module_names)
        for p in self.sources():
            for name in imports(p):
                root = name.split(".")[0]
                self.assertTrue(root in std or root in ALLOWED_OWN, f"{p.name}: nem megengedett import: {name}")

    def test_does_not_import_the_calculation_package(self):
        for p in self.sources():
            for name in imports(p):
                self.assertNotEqual(name.split(".")[0], "berelemzo", f"{p.name}: a számító csomag importálása tilos")

    def test_no_network_or_logging(self):
        for p in self.sources():
            for name in imports(p):
                self.assertNotIn(name.split(".")[0], FORBIDDEN, f"{p.name}: tiltott import: {name}")

    def test_pure_modules_do_no_io(self):
        for name in PURE:
            src = (PKG / name).read_text(encoding="utf-8")
            for call in ("open", "print", "Path", "input"):
                self.assertIsNone(re.search(r"(?<![A-Za-z0-9_])" + call + r"[(]", src), f"{name}: I/O nem megengedett: {call}(")


if __name__ == "__main__":
    unittest.main()
