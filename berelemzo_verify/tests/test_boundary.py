"""Az ellenőrző határa: független a Bérelemzőtől, csak szabványos könyvtár, nincs hálózat és naplózás, és a számító
modulok nem végeznek I/O-t."""

import ast
import re
import sys
import unittest
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
FORBIDDEN = {"socket", "ssl", "http", "urllib", "urllib3", "requests", "httpx", "aiohttp", "ftplib", "smtplib",
             "telnetlib", "xmlrpc", "subprocess", "logging", "webbrowser"}
PURE = ("checks.py", "canon.py", "tdist.py", "mutations.py", "report.py")


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

    def test_independent_of_the_calculation_package(self):
        for p in self.sources():
            for name in imports(p):
                self.assertNotEqual(name.split(".")[0], "berelemzo", f"{p.name}: a Bérelemző importálása tilos")

    def test_stdlib_only(self):
        std = set(sys.stdlib_module_names)
        for p in self.sources():
            for name in imports(p):
                self.assertIn(name.split(".")[0], std, f"{p.name}: nem szabványos könyvtár: {name}")

    def test_no_network_or_logging(self):
        for p in self.sources():
            for name in imports(p):
                self.assertNotIn(name.split(".")[0], FORBIDDEN, f"{p.name}: tiltott import: {name}")

    def test_pure_modules_do_no_io(self):
        for name in PURE:
            src = (PKG / name).read_text(encoding="utf-8")
            for name_call in ("open", "print", "Path", "input"):
                pattern = r"(?<![A-Za-z0-9_])" + name_call + r"[(]"
                self.assertIsNone(re.search(pattern, src), f"{name}: I/O nem megengedett: {name_call}(")


if __name__ == "__main__":
    unittest.main()
