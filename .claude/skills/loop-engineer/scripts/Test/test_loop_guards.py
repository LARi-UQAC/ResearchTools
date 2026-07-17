"""
test_loop_guards.py - offline unit tests for the loop-engineer control logic.

Exercises evaluate_stop / no_progress / regressed and the --dry-run driver over fixture
report files. No SDK, no models, no network: loop_engineer imports claude_agent_sdk lazily,
so importing the module here is safe offline.

Run:
    python .claude/skills/loop-engineer/scripts/Test/test_loop_guards.py
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent
sys.path.insert(0, str(_SCRIPTS))

import loop_audit  # noqa: E402
import loop_engineer as le  # noqa: E402


def _iter(index, aggregate, gate_pass=False, security=100.0, security_ok=True,
          tests_green=True, cost=0.01):
    """Build an Iteration with a synthetic score result."""
    result = {
        "aggregate": aggregate,
        "gate_pass": gate_pass,
        "tests_green": tests_green,
        "security_floor_ok": security_ok,
        "per_axis": {"security": security},
    }
    return le.Iteration(index=index, result=result, cost_usd=cost)


class TestGuards(unittest.TestCase):
    def test_gate_pass_stops_ready(self):
        state = le.LoopState(history=[_iter(1, 95.0, gate_pass=True)])
        cfg = le.LoopConfig(budget_usd=1.0)
        stop, reason = le.evaluate_stop(state, cfg)
        self.assertTrue(stop)
        self.assertTrue(reason.startswith("READY:"))

    def test_budget_cap_stops(self):
        # Two iterations at 0.6 each exceed a 1.0 cap; not a gate pass.
        state = le.LoopState(history=[_iter(1, 50.0, cost=0.6), _iter(2, 60.0, cost=0.6)])
        cfg = le.LoopConfig(budget_usd=1.0)
        stop, reason = le.evaluate_stop(state, cfg)
        self.assertTrue(stop)
        self.assertIn("budget cap", reason)

    def test_max_iters_stops(self):
        hist = [_iter(i, 40.0 + i, cost=0.0) for i in range(1, 4)]
        state = le.LoopState(history=hist)
        cfg = le.LoopConfig(budget_usd=100.0, max_iters=3)
        stop, reason = le.evaluate_stop(state, cfg)
        self.assertTrue(stop)
        self.assertIn("max iterations", reason)

    def test_no_progress_stops(self):
        # Flat aggregate over the patience window (patience=2 -> needs 3 points).
        hist = [_iter(1, 80.0, cost=0.0), _iter(2, 80.1, cost=0.0), _iter(3, 80.2, cost=0.0)]
        state = le.LoopState(history=hist)
        cfg = le.LoopConfig(budget_usd=100.0, max_iters=10, no_progress_patience=2)
        stop, reason = le.evaluate_stop(state, cfg)
        self.assertTrue(stop)
        self.assertIn("no progress", reason)

    def test_real_progress_does_not_stop(self):
        hist = [_iter(1, 70.0, cost=0.0), _iter(2, 80.0, cost=0.0), _iter(3, 88.0, cost=0.0)]
        state = le.LoopState(history=hist)
        cfg = le.LoopConfig(budget_usd=100.0, max_iters=10, no_progress_patience=2)
        stop, reason = le.evaluate_stop(state, cfg)
        self.assertFalse(stop)
        self.assertEqual(reason, "")

    def test_security_regression_stops(self):
        hist = [_iter(1, 90.0, security=100.0, security_ok=True, cost=0.0),
                _iter(2, 92.0, security=60.0, security_ok=False, cost=0.0)]
        state = le.LoopState(history=hist)
        cfg = le.LoopConfig(budget_usd=100.0, max_iters=10)
        stop, reason = le.evaluate_stop(state, cfg)
        self.assertTrue(stop)
        self.assertIn("regression", reason)

    def test_dry_run_reaches_ready_and_writes_ledger(self):
        # Two reports: first has a HIGH (fails gate), second is clean (passes gate).
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            r1 = d / "r1.json"
            r2 = d / "r2.json"
            r1.write_text(json.dumps({
                "tests": {"passed": 5, "failed": 0},
                "hooks": {},
                "findings": [{"source": "code-review", "axis": "correctness", "severity": "HIGH"}],
            }), encoding="utf-8")
            r2.write_text(json.dumps({
                "tests": {"passed": 6, "failed": 0},
                "hooks": {},
                "findings": [],
            }), encoding="utf-8")
            cfg = le.LoopConfig(budget_usd=1.0, min_score=90, max_iters=10)
            run_dir = d / "run"
            rc = le._run_dry(cfg, [r1, r2], run_dir, per_iter_cost=0.01)
            self.assertEqual(rc, 0)  # ended READY
            self.assertTrue((run_dir / "PROCESS.md").is_file())
            self.assertTrue((run_dir / "loop-run-log.md").is_file())
            self.assertTrue((run_dir / "loop-budget.md").is_file())

    def test_dry_run_budget_stop_returns_1(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            r = d / "r.json"
            r.write_text(json.dumps({
                "tests": {"passed": 1, "failed": 3},  # red -> never passes gate
                "hooks": {},
                "findings": [{"source": "code-review", "axis": "correctness", "severity": "HIGH"}],
            }), encoding="utf-8")
            cfg = le.LoopConfig(budget_usd=0.005, min_score=90)  # cap below one iter cost
            rc = le._run_dry(cfg, [r], d / "run", per_iter_cost=0.01)
            self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
