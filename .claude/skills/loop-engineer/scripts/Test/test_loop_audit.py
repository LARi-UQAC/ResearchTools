"""
test_loop_audit.py - offline unit tests for the loop-engineer code-quality scorer.

No network, no API key, no model load: the scorer works on plain report dicts, so the
suite runs fully offline with the project Python.

Run:
    python .claude/skills/loop-engineer/scripts/Test/test_loop_audit.py
"""

import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent
sys.path.insert(0, str(_SCRIPTS))

import loop_audit  # noqa: E402


def _report(findings=None, passed=10, failed=0, errored=0, hooks=None):
    """Build a minimal report dict with green tests and no hook issues by default."""
    return {
        "tests": {"passed": passed, "failed": failed, "errored": errored},
        "hooks": hooks or {"betterleaks_blocked": False, "pip_audit_criticals": 0},
        "findings": findings or [],
    }


class TestLoopAudit(unittest.TestCase):
    def test_clean_report_scores_100_and_passes(self):
        result = loop_audit.score(_report(), min_score=90)
        self.assertEqual(result["aggregate"], 100.0)
        self.assertTrue(result["tests_green"])
        self.assertTrue(result["security_floor_ok"])
        self.assertTrue(result["gate_pass"])

    def test_critical_security_fails_gate_even_with_high_aggregate(self):
        # One CRITICAL on the security axis. Aggregate stays high (only one axis dented),
        # but the security hard floor must sink the gate.
        findings = [{"source": "security-guidance", "axis": "security", "severity": "CRITICAL"}]
        result = loop_audit.score(_report(findings=findings), min_score=90)
        self.assertFalse(result["security_floor_ok"])
        self.assertFalse(result["gate_pass"])
        self.assertGreaterEqual(result["counts"]["CRITICAL"], 1)

    def test_failing_tests_fail_gate(self):
        result = loop_audit.score(_report(passed=8, failed=2), min_score=90)
        self.assertFalse(result["tests_green"])
        self.assertFalse(result["gate_pass"])

    def test_single_high_finding_fails_gate(self):
        # No CRITICAL/HIGH rule: even one HIGH blocks the gate, and dents the aggregate.
        findings = [{"source": "code-review", "axis": "correctness", "severity": "HIGH"}]
        result = loop_audit.score(_report(findings=findings), min_score=90)
        self.assertEqual(result["counts"]["HIGH"], 1)
        self.assertLess(result["aggregate"], 100.0)
        self.assertFalse(result["gate_pass"])

    def test_low_medium_only_green_tests_passes(self):
        # A few low/medium findings that keep the aggregate at or above 90 with green
        # tests and no CRITICAL/HIGH must pass the composite gate.
        findings = [
            {"source": "pr-review-toolkit", "axis": "style", "severity": "LOW"},
            {"source": "code-review", "axis": "tech-debt", "severity": "MEDIUM"},
        ]
        result = loop_audit.score(_report(findings=findings), min_score=90)
        self.assertEqual(result["counts"]["CRITICAL"], 0)
        self.assertEqual(result["counts"]["HIGH"], 0)
        self.assertGreaterEqual(result["aggregate"], 90.0)
        self.assertTrue(result["gate_pass"])

    def test_betterleaks_block_sinks_security_floor(self):
        hooks = {"betterleaks_blocked": True, "pip_audit_criticals": 0}
        result = loop_audit.score(_report(hooks=hooks), min_score=90)
        self.assertFalse(result["security_floor_ok"])
        self.assertFalse(result["gate_pass"])

    def test_missing_test_result_is_not_green(self):
        report = {"findings": [], "hooks": {}}  # no "tests" key
        result = loop_audit.score(report, min_score=90)
        self.assertFalse(result["tests_green"])
        self.assertFalse(result["gate_pass"])

    def test_unknown_severity_defaults_to_medium(self):
        findings = [{"source": "x", "axis": "correctness", "severity": "bogus"}]
        result = loop_audit.score(_report(findings=findings), min_score=90)
        self.assertEqual(result["counts"]["MEDIUM"], 1)

    def test_min_score_threshold_is_respected(self):
        # Enough MEDIUMs on correctness to drop aggregate below a strict 99 threshold.
        findings = [
            {"source": "code-review", "axis": "correctness", "severity": "MEDIUM"}
            for _ in range(3)
        ]
        result = loop_audit.score(_report(findings=findings), min_score=99)
        self.assertLess(result["aggregate"], 99.0)
        self.assertFalse(result["gate_pass"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
