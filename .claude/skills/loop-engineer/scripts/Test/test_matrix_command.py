"""
Offline tests for model_resolver's --matrix comparison.

The matrix and the comparative table used to be assembled by hand, in throwaway one-liners,
every time a comparison was wanted. Two consequences, both seen on 2026-08-28. A hand-built
comparison scored each candidate only on the role it was declared for, which is how a tag
passing 18 of 20 held the coder role while a tag passing 20 of 20 had never been run on a
coder task. And a tag the bridge REFUSES to run, for want of a measured context window,
printed as 0/20 and read as a very weak model rather than as a harness refusal.

Both are pinned here. run_qualification_tasks is patched, so no bridge, no daemon, no model.
"""

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SCRIPTS))

import model_resolver as mr  # noqa: E402

_TASKS = [
    {"id": "coder-a", "kind": "coder"},
    {"id": "coder-b", "kind": "coder"},
    {"id": "writer-a", "kind": "writer"},
]


def _run(tag, tasks):
    passing = {"vendor-strong:9b": {"coder-a", "coder-b", "writer-a"},
               "vendor-mid:9b": {"coder-a", "writer-a"}}[tag]
    results = [{"id": t["id"], "kind": t["kind"], "passed": t["id"] in passing, "detail": ""}
               for t in tasks]
    by_kind = {}
    for r in results:
        entry = by_kind.setdefault(r["kind"], {"passed": 0, "total": 0})
        entry["total"] += 1
        entry["passed"] += 1 if r["passed"] else 0
    passed = sum(1 for r in results if r["passed"])
    return {"tag": tag, "passed": passed, "total": len(results),
            "ratio": passed / len(results), "by_kind": by_kind, "results": results}


_BUDGETS = {"vendor-strong:9b": {"num_ctx": 16384, "decode_tps": 26.64},
            "vendor-mid:9b": {"num_ctx": 65536, "decode_tps": 38.99},
            "vendor-unmeasured:9b": None}


class TestEveryCandidateIsScoredOnEveryTask(unittest.TestCase):
    def test_a_candidate_is_scored_on_roles_it_is_not_declared_for(self):
        # The defect this command exists to prevent: a coder-declared tag must still be
        # graded on writer tasks, or the comparison measures the declaration.
        with mock.patch.object(mr, "run_qualification_tasks", side_effect=_run), \
             mock.patch.object(mr, "measured_budget", side_effect=lambda t, *a: _BUDGETS[t]):
            matrix = mr.build_matrix(["vendor-strong:9b", "vendor-mid:9b"], _TASKS)

        for tag in ("vendor-strong:9b", "vendor-mid:9b"):
            with self.subTest(tag=tag):
                self.assertEqual(set(matrix["rows"][tag]["per_task"]),
                                 {"coder-a", "coder-b", "writer-a"})
                self.assertIn("coder", matrix["rows"][tag]["by_kind"])
                self.assertIn("writer", matrix["rows"][tag]["by_kind"])

    def test_the_grid_lists_every_task_once_in_order(self):
        with mock.patch.object(mr, "run_qualification_tasks", side_effect=_run), \
             mock.patch.object(mr, "measured_budget", side_effect=lambda t, *a: _BUDGETS[t]):
            matrix = mr.build_matrix(["vendor-strong:9b"], _TASKS)

        self.assertEqual(matrix["task_ids"], ["coder-a", "coder-b", "writer-a"])


class TestAnUnrunnableTagIsNeverScoredZero(unittest.TestCase):
    def test_a_tag_without_a_measured_window_is_reported_not_runnable(self):
        with mock.patch.object(mr, "run_qualification_tasks", side_effect=_run), \
             mock.patch.object(mr, "measured_budget", side_effect=lambda t, *a: _BUDGETS[t]):
            matrix = mr.build_matrix(["vendor-unmeasured:9b"], _TASKS)
        row = matrix["rows"]["vendor-unmeasured:9b"]

        self.assertFalse(row["runnable"])
        self.assertIn("no measured context window", row["why"])

    def test_an_unrunnable_tag_is_never_asked_to_run_a_task(self):
        # Counting a refusal as failures is what made a harness defect look like a weak
        # model. The run must not even be attempted.
        with mock.patch.object(mr, "run_qualification_tasks", side_effect=_run) as run, \
             mock.patch.object(mr, "measured_budget", side_effect=lambda t, *a: _BUDGETS[t]):
            mr.build_matrix(["vendor-unmeasured:9b"], _TASKS)

        run.assert_not_called()

    def test_the_rendered_table_says_not_runnable_rather_than_a_number(self):
        with mock.patch.object(mr, "run_qualification_tasks", side_effect=_run), \
             mock.patch.object(mr, "measured_budget", side_effect=lambda t, *a: _BUDGETS[t]):
            matrix = mr.build_matrix(["vendor-strong:9b", "vendor-unmeasured:9b"], _TASKS)
        text = mr._render_matrix(matrix, ["coder", "writer"])

        self.assertIn("NOT RUNNABLE", text)
        self.assertIn("n-r", text)
        self.assertNotIn("vendor-unmeasured:9b       0/", text)


class TestTheComparativeTableIsComputed(unittest.TestCase):
    def test_the_summary_ranks_by_total_and_carries_the_measurement(self):
        with mock.patch.object(mr, "run_qualification_tasks", side_effect=_run), \
             mock.patch.object(mr, "measured_budget", side_effect=lambda t, *a: _BUDGETS[t]):
            matrix = mr.build_matrix(["vendor-mid:9b", "vendor-strong:9b"], _TASKS)
        text = mr._render_matrix(matrix, ["coder", "writer"])
        summary = text.split("Comparative summary")[1]

        self.assertLess(summary.index("vendor-strong:9b"), summary.index("vendor-mid:9b"))
        self.assertIn("16384", summary)
        self.assertIn("26.64", summary)

    def test_json_output_is_the_whole_structure(self):
        out = io.StringIO()
        with mock.patch.object(mr, "_load_tasks", return_value=_TASKS), \
             mock.patch.object(mr, "_load_local_models",
                               return_value={"vendor-strong:9b": {"tag": "vendor-strong:9b"}}), \
             mock.patch.object(mr, "list_installed_models", return_value=["vendor-strong:9b"]), \
             mock.patch.object(mr, "run_qualification_tasks", side_effect=_run), \
             mock.patch.object(mr, "measured_budget", side_effect=lambda t, *a: _BUDGETS[t]), \
             redirect_stdout(out):
            rc = mr.cmd_matrix(as_json=True)
        parsed = json.loads(out.getvalue())

        self.assertEqual(rc, 0)
        self.assertEqual(parsed["rows"]["vendor-strong:9b"]["passed"], 3)

    def test_no_installed_candidate_is_an_explicit_refusal(self):
        with mock.patch.object(mr, "_load_tasks", return_value=_TASKS), \
             mock.patch.object(mr, "_load_local_models",
                               return_value={"vendor-strong:9b": {"tag": "vendor-strong:9b"}}), \
             mock.patch.object(mr, "list_installed_models", return_value=[]):
            rc = mr.cmd_matrix()

        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
