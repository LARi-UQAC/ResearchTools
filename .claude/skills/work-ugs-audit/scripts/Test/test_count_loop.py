"""
Purpose: Offline tests of the count loop (plan 12 Task 2, spec E6). Extraction is a stub: no PDF, no OCR (R21).
Pipeline stage: work-ugs-audit, figure preparation (issue 126).
Expected runtime: under one second.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import count_loop  # noqa: E402

STEPS = [{"group_max_gap_pt": 48}, {"group_max_gap_pt": 96}, {"group_max_gap_pt": 192}]


def _records(count):
    """
    Purpose: Build fictitious element records holding count figures.
    Inputs:
        count: int - number of figure records.
    Outputs:
        List[dict] - records with element_type figure.
    Raises:
        None.
    """
    return [{"element_type": "figure", "element_id": f"F{i + 1:02d}"} for i in range(count)]


class _Stub:
    """Extraction stub returning a count chosen per overrides, recording every call."""

    def __init__(self, counts_by_gap):
        self.counts_by_gap = counts_by_gap
        self.calls = []

    def __call__(self, overrides):
        """
        Purpose: Return the records of one attempt.
        Inputs:
            overrides: dict - the setting overrides of the attempt.
        Outputs:
            List[dict] - figure records for the count chosen for the gap.
        Raises:
            None.
        """
        self.calls.append(dict(overrides))
        gap = overrides.get("group_max_gap_pt")
        return _records(self.counts_by_gap.get(gap, self.counts_by_gap["default"]))


class TestCountLoop(unittest.TestCase):
    """Behaviour of run_count_loop on stub extractions."""

    def test_one_too_many_is_merged_on_second_attempt(self):
        stub = _Stub({"default": 28, 48: 27})
        result = count_loop.run_count_loop(stub, 27, STEPS, 3)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["attempts"]), 2)
        self.assertEqual(result["attempts"][-1]["extracted"], 27)
        self.assertEqual(len(result["records"]), 27)

    def test_one_too_few_is_retried_then_mismatch(self):
        stub = _Stub({"default": 26})
        result = count_loop.run_count_loop(stub, 27, STEPS, 2)
        self.assertEqual(result["status"], "mismatch")
        self.assertEqual(len(result["attempts"]), 3)  # first attempt plus max_iterations re-runs
        self.assertEqual(len(stub.calls), 3)

    def test_not_found_runs_once(self):
        stub = _Stub({"default": 5})
        result = count_loop.run_count_loop(stub, None, STEPS, 3)
        self.assertEqual(result["status"], "not_found")
        self.assertEqual(len(stub.calls), 1)
        self.assertIsNone(result["declared"])

    def test_bound_is_respected(self):
        stub = _Stub({"default": 1})
        result = count_loop.run_count_loop(stub, 27, STEPS, 1)
        self.assertEqual(len(result["attempts"]), 2)
        self.assertEqual(len(stub.calls), 2)

    def test_best_attempt_is_kept_on_mismatch(self):
        stub = _Stub({"default": 30, 48: 25, 96: 26})
        result = count_loop.run_count_loop(stub, 27, STEPS, 3)
        self.assertEqual(result["status"], "mismatch")
        self.assertEqual(result["attempts"][1]["extracted"], 25)
        self.assertEqual(result["attempts"][2]["extracted"], 26)
        self.assertEqual(len(result["records"]), 26)

    def test_first_attempt_uses_no_override(self):
        stub = _Stub({"default": 27})
        count_loop.run_count_loop(stub, 27, STEPS, 3)
        self.assertEqual(stub.calls[0], {})

    def test_zero_iterations_means_one_attempt(self):
        stub = _Stub({"default": 1})
        result = count_loop.run_count_loop(stub, 27, STEPS, 0)
        self.assertEqual(len(result["attempts"]), 1)
        self.assertEqual(result["status"], "mismatch")

    def test_read_settings_names_a_missing_key(self):
        with self.assertRaises(count_loop.CountLoopError) as ctx:
            count_loop.read_loop_settings({"count_max_iterations": {"value": 3, "provenance": "x"}})
        self.assertIn("count_gap_steps_pt", str(ctx.exception))

    def test_read_settings_builds_overrides_from_steps(self):
        block = {
            "count_max_iterations": {"value": 3, "provenance": "proposal"},
            "count_gap_steps_pt": {"value": [48, 96], "provenance": "proposal"},
        }
        max_iterations, steps = count_loop.read_loop_settings(block)
        self.assertEqual(max_iterations, 3)
        self.assertEqual(steps, [{"group_max_gap_pt": 48}, {"group_max_gap_pt": 96}])


if __name__ == "__main__":
    unittest.main()
