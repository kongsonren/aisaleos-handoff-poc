"""Regression guard: hitting the beat cap must not silently succeed.

Run: python -m unittest discover -s .wb1/nezha/tests -p 'test_self_schedule_cap_contract.py'
Static test only; no token, network, dispatch, or production side effects.
"""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class CapContract(unittest.TestCase):
    def test_nezha_cap_is_nonzero(self):
        src = (ROOT / "loop.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "wait_and_schedule")
        branches = [n for n in ast.walk(fn) if isinstance(n, ast.If) and "MAX_BEATS" in ast.unparse(n.test) and "seq" in ast.unparse(n.test)]
        self.assertEqual(len(branches), 1, "expected one explicit beat cap guard")
        returns = [n for n in branches[0].body if isinstance(n, ast.Return)]
        self.assertEqual(len(returns), 1)
        self.assertIsInstance(returns[0].value, ast.Constant)
        self.assertNotEqual(returns[0].value.value, 0, "cap exhaustion must be visible as failure")

    def test_mozi_cap_is_nonzero(self):
        src = (ROOT / "mozi_watch.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "wait_and_schedule")
        branches = [n for n in ast.walk(fn) if isinstance(n, ast.If) and "maxb" in ast.unparse(n.test) and "seq" in ast.unparse(n.test)]
        self.assertEqual(len(branches), 1)
        returns = [n for n in branches[0].body if isinstance(n, ast.Return)]
        self.assertEqual(len(returns), 1)
        self.assertIsInstance(returns[0].value, ast.Constant)
        self.assertNotEqual(returns[0].value.value, 0)

if __name__ == "__main__":
    unittest.main()
