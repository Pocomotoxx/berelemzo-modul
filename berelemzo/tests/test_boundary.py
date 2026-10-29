"""A határ ellenőrzése: nincs hálózat, nincs naplózás, és csak szabványos könyvtár használható (így MI-/LLM-/ML-csomag sem)."""

import ast
import sys
import unittest
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
FORBIDDEN = {
    "socket", "ssl", "http", "urllib", "urllib3", "requests", "httpx", "aiohttp", "ftplib", "smtplib",
    "telnetlib", "xmlrpc", "subprocess", "logging", "webbrowser",
}


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
        return [p for p in PKG.glob("*.py")]

    def test_no_network_or_logging_imports(self):
        for p in self.sources():
            for name in imports(p):
                root = name.split(".")[0]
                self.assertNotIn(root, FORBIDDEN, f"{p.name}: tiltott import: {name}")

    def test_only_stdlib_or_own_package(self):
        std = set(sys.stdlib_module_names)
        for p in self.sources():
            for name in imports(p):
                self.assertTrue(name.split(".")[0] in std, f"{p.name}: nem szabványos könyvtár: {name}")

    def test_core_and_stats_do_no_io(self):
        for name in ("core.py", "stats.py"):
            src = (PKG / name).read_text(encoding="utf-8")
            for token in ("open(", "print(", "Path(", "input("):
                self.assertNotIn(token, src, f"{name}: I/O nem megengedett a magban: {token}")


if __name__ == "__main__":
    unittest.main()
