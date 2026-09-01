"""
Offline tests for model_resolver's read-only scoring path (--score, --record).

Two defects motivated this command, both found on 2026-08-28.

Reading a candidate's score used to require --qualify, whose purpose is to CHANGE the
adopted tag, so measuring a field of candidates meant either adopting one or reading the
number out of a refusal message. An evaluation that cannot be run without side effects gets
run rarely, and a rarely-run evaluation goes stale.

And an incumbent's recorded score is frozen at whatever task set existed when it was
adopted. When the frozen set grew from three tasks per role to ten, every incumbent still
carried a number from the old set, so the next challenger would have been compared against
a score from a different measurement. --record refreshes that number in place; it can never
change which tag is current.

run_qualification_tasks is patched, so no bridge, no daemon, no model.
"""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SCRIPTS))

import model_resolver as mr  # noqa: E402


def _result(tag, role, passed, total):
    return {
        "tag": tag, "passed": passed, "total": total,
        "ratio": passed / total if total else 0.0,
        "by_kind": {role: {"passed": passed, "total": total}},
        "results": [{"id": f"{role}-{i}", "kind": role, "passed": i < passed, "detail": ""}
                    for i in range(total)],
    }


def _state(role, tag, passed, total):
    return {
        "current": tag,
        "current_by_role": {role: {"tag": tag, "passed": passed, "total": total,
                                   "adopted": "2026-08-14"}},
        "score": {"passed": passed, "total": total, "ratio": passed / total,
                  "by_kind": {role: {"passed": passed, "total": total}}},
        "qualified_at": "2026-08-14T00:00:00+00:00",
        "history": [],
    }


class TestScoreWritesNothing(unittest.TestCase):
    def test_a_plain_score_leaves_the_state_document_byte_identical(self):
        with tempfile.TemporaryDirectory() as d:
            state_path = Path(d) / "state.json"
            state_path.write_text(json.dumps(_state("coder", "vendor-a:9b", 2, 3)),
                                  encoding="utf-8")
            before = state_path.read_bytes()

            out = io.StringIO()
            with mock.patch.object(mr, "STATE_PATH", state_path), \
                 mock.patch.object(mr, "_load_tasks",
                                   return_value=[{"id": "t", "kind": "coder"}]), \
                 mock.patch.object(mr, "run_qualification_tasks",
                                   return_value=_result("vendor-b:9b", "coder", 8, 10)), \
                 redirect_stdout(out):
                rc = mr.cmd_score("vendor-b:9b", "coder")

            self.assertEqual(rc, 0)
            self.assertEqual(state_path.read_bytes(), before)
            self.assertIn("nothing written", out.getvalue())

    def test_the_report_names_each_task_not_only_the_total(self):
        # A ten-task set exists so two candidates on the same total can still be told apart
        # by WHICH tasks each failed. A bare total throws that away.
        out = io.StringIO()
        with mock.patch.object(mr, "_load_tasks", return_value=[{"id": "t", "kind": "coder"}]), \
             mock.patch.object(mr, "run_qualification_tasks",
                               return_value=_result("vendor-b:9b", "coder", 1, 3)), \
             redirect_stdout(out):
            mr.cmd_score("vendor-b:9b", "coder")
        text = out.getvalue()

        self.assertIn("PASS", text)
        self.assertIn("FAIL", text)

    def test_a_role_naming_no_task_is_refused(self):
        err = io.StringIO()
        with mock.patch.object(mr, "_load_tasks", return_value=[{"id": "t", "kind": "coder"}]), \
             redirect_stderr(err):
            rc = mr.cmd_score("vendor-b:9b", "writer")

        self.assertEqual(rc, 1)
        self.assertIn("no task of kind", err.getvalue())


class TestRecordRefreshesOnlyAnIncumbent(unittest.TestCase):
    def test_the_incumbents_number_is_refreshed_and_its_tag_kept(self):
        with tempfile.TemporaryDirectory() as d:
            state_path = Path(d) / "state.json"
            state_path.write_text(json.dumps(_state("coder", "vendor-a:9b", 2, 3)),
                                  encoding="utf-8")

            with mock.patch.object(mr, "STATE_PATH", state_path), \
                 mock.patch.object(mr, "_load_tasks",
                                   return_value=[{"id": "t", "kind": "coder"}]), \
                 mock.patch.object(mr, "run_qualification_tasks",
                                   return_value=_result("vendor-a:9b", "coder", 9, 10)), \
                 redirect_stdout(io.StringIO()):
                rc = mr.cmd_score("vendor-a:9b", "coder", record=True)

            entry = json.loads(state_path.read_text(encoding="utf-8"))["current_by_role"]["coder"]

        self.assertEqual(rc, 0)
        self.assertEqual(entry["tag"], "vendor-a:9b")
        self.assertEqual((entry["passed"], entry["total"]), (9, 10))

    def test_recording_a_tag_that_is_not_current_is_refused(self):
        # The whole safety property: --record must never be a back door to adoption.
        with tempfile.TemporaryDirectory() as d:
            state_path = Path(d) / "state.json"
            state_path.write_text(json.dumps(_state("coder", "vendor-a:9b", 2, 3)),
                                  encoding="utf-8")
            before = state_path.read_bytes()

            err = io.StringIO()
            with mock.patch.object(mr, "STATE_PATH", state_path), \
                 mock.patch.object(mr, "_load_tasks",
                                   return_value=[{"id": "t", "kind": "coder"}]), \
                 mock.patch.object(mr, "run_qualification_tasks",
                                   return_value=_result("vendor-b:9b", "coder", 10, 10)), \
                 redirect_stdout(io.StringIO()), redirect_stderr(err):
                rc = mr.cmd_score("vendor-b:9b", "coder", record=True)

            self.assertEqual(rc, 1)
            self.assertEqual(state_path.read_bytes(), before)
            self.assertIn("not the current tag", err.getvalue())

    def test_recording_without_a_role_is_refused(self):
        err = io.StringIO()
        with mock.patch.object(mr, "_load_tasks", return_value=[{"id": "t", "kind": "coder"}]), \
             mock.patch.object(mr, "run_qualification_tasks",
                               return_value=_result("vendor-a:9b", "coder", 9, 10)), \
             redirect_stdout(io.StringIO()), redirect_stderr(err):
            rc = mr.cmd_score("vendor-a:9b", None, record=True)

        self.assertEqual(rc, 1)
        self.assertIn("--record needs --role", err.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
