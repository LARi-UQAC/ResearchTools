"""
loop_audit.py - code-quality scorer for the loop-engineer skill.

Aggregates the findings emitted by the installed review tools (code-review,
security-guidance, pr-review-toolkit, systematic-debugging) plus the test result and the
security-hook status into a single 0-100 code-quality score, per-axis sub-scores, and the
booleans of the composite stop gate. This is the deterministic step the loop runs after each
review pass; it is distinct from the referenced loop-audit tool, which scores loop-readiness
(project setup) rather than code quality.

Scoring model
-------------
Each finding carries a severity (CRITICAL / HIGH / MEDIUM / LOW). A finding subtracts a
severity weight from its axis sub-score; the aggregate is the weighted mean of the axes.
Security is a hard floor: any CRITICAL fails the gate regardless of the aggregate.

Composite gate (default): tests_green AND no CRITICAL AND no HIGH AND aggregate >= min_score.

Input JSON schema (one report object)
--------------------------------------
{
  "tests":   {"passed": int, "failed": int, "errored": int},   # optional; absent => unknown
  "hooks":   {"betterleaks_blocked": bool, "pip_audit_criticals": int},  # optional
  "findings": [
    {"source": "code-review", "axis": "correctness", "severity": "HIGH", "summary": "..."},
    ...
  ]
}

CLI
---
    python loop_audit.py <report.json> [--min-score 90] [--json-out <path>]
Exit code 0 when the composite gate passes, 1 otherwise, so the loop can branch on it.
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Severity penalty subtracted from the axis sub-score for one finding of that severity.
SEVERITY_WEIGHT: dict[str, int] = {
    "CRITICAL": 25,
    "HIGH": 10,
    "MEDIUM": 4,
    "LOW": 1,
}

# Axes the score is broken down into, with their weight in the aggregate mean.
AXIS_WEIGHT: dict[str, float] = {
    "correctness": 3.0,
    "security": 3.0,
    "tests": 2.0,
    "tech-debt": 1.0,
    "style": 1.0,
    "ai-first": 1.0,
}

DEFAULT_MIN_SCORE = 90.0
_VALID_SEVERITIES = set(SEVERITY_WEIGHT)


def _normalize_severity(raw: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Map a free-form severity string to one of the four canonical bands.

    Inputs:
        raw (str): severity as reported by a tool (any case; e.g. "high", "warning").

    Outputs:
        result (str): one of CRITICAL / HIGH / MEDIUM / LOW (defaults to MEDIUM
        when the value is unrecognized, so an unknown never silently scores zero).
    --------------------------------------------------------------------------
    """
    key = (raw or "").strip().upper()
    if key in _VALID_SEVERITIES:
        return key
    # A few common synonyms from the different tools.
    synonyms = {
        "BLOCKER": "CRITICAL",
        "ERROR": "HIGH",
        "WARNING": "MEDIUM",
        "WARN": "MEDIUM",
        "INFO": "LOW",
        "NIT": "LOW",
        "NITPICK": "LOW",
    }
    return synonyms.get(key, "MEDIUM")


def _axis_of(finding: dict[str, Any]) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve the scoring axis of a finding, defaulting security-source
        findings to the security axis and everything else to correctness.

    Inputs:
        finding (dict): one finding object from the report.

    Outputs:
        result (str): an axis key present in AXIS_WEIGHT.
    --------------------------------------------------------------------------
    """
    axis = (finding.get("axis") or "").strip().lower()
    if axis in AXIS_WEIGHT:
        return axis
    source = (finding.get("source") or "").strip().lower()
    if "security" in source:
        return "security"
    return "correctness"


def score(
    report: dict[str, Any],
    min_score: float = DEFAULT_MIN_SCORE,
) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Compute per-axis sub-scores, the aggregate 0-100 code-quality score, and
        the composite stop-gate booleans for one review report.

    Inputs:
        report (dict): the report object (see the module docstring schema).
        min_score (float): the aggregate threshold the gate requires (default 90).

    Outputs:
        result (dict): {per_axis, aggregate, counts, tests_green,
        security_floor_ok, gate_pass, reasons}.
    --------------------------------------------------------------------------
    """
    findings = report.get("findings") or []

    # Per-axis penalty accumulation, starting each axis at 100.
    per_axis: dict[str, float] = {axis: 100.0 for axis in AXIS_WEIGHT}
    counts: dict[str, int] = {sev: 0 for sev in SEVERITY_WEIGHT}

    for finding in findings:
        severity = _normalize_severity(finding.get("severity", ""))
        axis = _axis_of(finding)
        counts[severity] += 1
        per_axis[axis] = max(0.0, per_axis[axis] - SEVERITY_WEIGHT[severity])

    # Aggregate: weighted mean of the axes (clamped to [0, 100]).
    total_weight = sum(AXIS_WEIGHT.values())
    aggregate = sum(per_axis[a] * AXIS_WEIGHT[a] for a in AXIS_WEIGHT) / total_weight
    aggregate = round(max(0.0, min(100.0, aggregate)), 2)

    # Tests: green only when the report says so and nothing failed or errored.
    tests = report.get("tests")
    if tests is None:
        tests_green = False
        tests_reason = "no test result reported (treated as not green)"
    else:
        failed = int(tests.get("failed", 0)) + int(tests.get("errored", 0))
        tests_green = failed == 0 and int(tests.get("passed", 0)) >= 0
        tests_reason = "tests green" if tests_green else f"{failed} test failure(s)/error(s)"

    # Security hard floor: any CRITICAL finding, a betterleaks block, or a pip-audit
    # CRITICAL sinks the gate regardless of the aggregate.
    hooks = report.get("hooks") or {}
    betterleaks_blocked = bool(hooks.get("betterleaks_blocked", False))
    pip_audit_criticals = int(hooks.get("pip_audit_criticals", 0))
    security_floor_ok = (
        counts["CRITICAL"] == 0
        and not betterleaks_blocked
        and pip_audit_criticals == 0
    )

    # Composite gate.
    reasons: list[str] = []
    if not tests_green:
        reasons.append(tests_reason)
    if not security_floor_ok:
        if counts["CRITICAL"]:
            reasons.append(f"{counts['CRITICAL']} CRITICAL finding(s)")
        if betterleaks_blocked:
            reasons.append("betterleaks blocked a write (leaked secret)")
        if pip_audit_criticals:
            reasons.append(f"{pip_audit_criticals} CRITICAL CVE(s) from pip-audit")
    if counts["HIGH"]:
        reasons.append(f"{counts['HIGH']} HIGH finding(s)")
    if aggregate < min_score:
        reasons.append(f"aggregate {aggregate} < min_score {min_score}")

    gate_pass = (
        tests_green
        and security_floor_ok
        and counts["HIGH"] == 0
        and aggregate >= min_score
    )
    if gate_pass:
        reasons.append("composite gate passed")

    return {
        "per_axis": {a: round(per_axis[a], 2) for a in per_axis},
        "aggregate": aggregate,
        "counts": counts,
        "tests_green": tests_green,
        "security_floor_ok": security_floor_ok,
        "min_score": min_score,
        "gate_pass": gate_pass,
        "reasons": reasons,
    }


def load_report(path: Path) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read and parse a review report JSON file, failing fast with a clear
        message rather than a bare traceback.

    Inputs:
        path (Path): path to the report JSON file.

    Outputs:
        result (dict): the parsed report object.
    --------------------------------------------------------------------------
    """
    if not path.is_file():
        raise SystemExit(f"[LOOP-AUDIT] report not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"[LOOP-AUDIT] invalid JSON in {path}: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        CLI entry point: score a report file, print the result JSON, and return
        the gate exit code (0 pass, 1 fail) for the loop to branch on.

    Inputs:
        argv (list[str] | None): argument vector (defaults to sys.argv[1:]).

    Outputs:
        result (int): process exit code.
    --------------------------------------------------------------------------
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Score a loop-engineer review report.")
    parser.add_argument("report", type=Path, help="path to the review report JSON")
    parser.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE)
    parser.add_argument("--json-out", type=Path, default=None, help="also write result JSON here")
    args = parser.parse_args(argv)

    report = load_report(args.report)
    result = score(report, min_score=args.min_score)

    text = json.dumps(result, indent=2)
    print(text)
    if args.json_out is not None:
        args.json_out.write_text(text, encoding="utf-8")
        logger.info("[LOOP-AUDIT] wrote %s", args.json_out)

    return 0 if result["gate_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
