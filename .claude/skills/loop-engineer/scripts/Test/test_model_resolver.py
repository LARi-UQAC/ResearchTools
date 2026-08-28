"""
test_model_resolver.py - offline unit tests for the local-model resolver (P4 Task 3, plus
fix round 1: the phantom-tag guard, the wired policy, the per-role win rule, and the
tightened language gate).

Every test patches model_resolver._ollama_list_raw (the sole process boundary to the
'ollama list' inventory) and, where a qualification run is exercised, model_resolver.
run_qualification_tasks (the sole boundary to the deterministic bridge / real generation).
No test calls the real 'ollama' binary, opens a socket, or reaches the Ollama daemon: the
patched callables are plain Python objects substituted in place of the module's own names
via unittest.mock.patch.object / unittest.mock.patch.dict, matching the pattern already used
in test_ollama_bridge.py. All paths (LOCAL_MODELS_PATH, TASKS_PATH, STATE_PATH) are
redirected to a per-test tempfile.TemporaryDirectory, so no test ever touches the real
.claude/local-models.json, qualification/tasks.json, or local-model-state.json.

Original six cases (brief numbering; case 6 split into two independent test methods):

  1. test_list_marks_undeclared_model_ineligible_with_reason
  2. test_resolve_prints_exactly_one_tag_with_no_decoration
  3. test_qualify_losing_candidate_exits_nonzero_and_leaves_current_unchanged
  4. test_qualify_winner_updates_current_and_appends_dated_history
  5. test_env_override_wins_over_state_and_does_not_modify_it
  6. test_missing_state_file_is_explicit_error / test_empty_state_file_is_explicit_error

Fix round 1 cases:

  F1. test_resolve_refuses_when_current_tag_not_installed
      test_override_refuses_when_tag_not_installed
  F2. test_require_declared_policy_toggle_changes_outcome
      test_unsupported_win_rule_value_refuses
  F3. test_qualify_winner_gains_one_role_no_regression
      test_qualify_loser_regresses_in_one_role
      test_qualify_challenger_regressing_one_role_rejected_despite_net_gain (worked example)
  F4. test_language_gate_fails_on_english_with_stray_french_tokens
      test_language_gate_passes_on_genuine_french_with_accents (positive control)
  F5. test_write_state_leaves_no_leftover_tmp_file

Run:
    python .claude/skills/loop-engineer/scripts/Test/test_model_resolver.py
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent
sys.path.insert(0, str(_SCRIPTS))

import model_resolver as mr  # noqa: E402

# Mirrors the column layout of a real 'ollama list' (NAME, ID, SIZE, MODIFIED), header
# included, exactly as _ollama_list_raw would return it from subprocess stdout.
FAKE_OLLAMA_LIST = (
    "NAME                  ID              SIZE      MODIFIED    \n"
    "vendor-a:9b         b283934ba10f    5.6 GB    10 days ago    \n"
    "vendor:7b        d5ae64a751a0    6.6 GB    10 days ago    \n"
    "random-model:latest   deadbeefcafe    1.0 GB    2 days ago    \n"
)


def _full_policy(**overrides) -> dict:
    """Fix round 1 (F2): the complete, real policy schema, so a fixture test document
    exercises the SAME keys production code reads. Overrides let a single test flip one key
    to prove it changes the outcome."""
    policy = {
        "qualification_mode": "beat_incumbent",
        "require_declared": True,
        "require_installed": True,
        "win_rule": "no_regression_strict_gain_by_role",
        "bootstrap_rule": True,
    }
    policy.update(overrides)
    return policy


_DECLARED_CANDIDATES = {
    "_header": {"purpose": "test fixture, not the real local-models.json"},
    "policy": _full_policy(),
    "candidates": [
        {"tag": "vendor-a:9b", "role": "writer", "declared": "2026-08-14", "notes": "fixture"},
        {"tag": "vendor:7b", "role": "coder", "declared": "2026-08-14", "notes": "fixture"},
        {"tag": "challenger:tag", "role": "writer", "declared": "2026-08-14", "notes": "fixture"},
    ],
}

_FROZEN_TASKS = {
    "_header": {"purpose": "test fixture, not the real qualification/tasks.json"},
    "tasks": [{"id": "fixture-task-1", "kind": "coder", "prompt": "unused", "entrypoint": "f", "cases": []}],
}


def _by_kind(coder_passed: int, coder_total: int, writer_passed: int, writer_total: int) -> dict:
    """Build a by_kind breakdown succinctly for a test fixture or a mocked result."""
    return {
        "coder": {"passed": coder_passed, "total": coder_total},
        "writer": {"passed": writer_passed, "total": writer_total},
    }


def _score_from_by_kind(by_kind: dict) -> dict:
    passed = sum(v["passed"] for v in by_kind.values())
    total = sum(v["total"] for v in by_kind.values())
    return {"passed": passed, "total": total, "ratio": (passed / total) if total else 0.0, "by_kind": by_kind}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _pop_override():
    """Remove LARI_LOCAL_MODEL from the environment for the duration of a test, restoring
    whatever was there afterward, so an override left by an earlier test (or the real shell)
    never leaks into a case that assumes no override is set."""
    return mock.patch.dict(os.environ, {}, clear=False)


class TestListMarksUndeclaredModelIneligible(unittest.TestCase):
    def test_list_marks_undeclared_model_ineligible_with_reason(self):
        with tempfile.TemporaryDirectory() as d, _pop_override():
            os.environ.pop(mr.ENV_OVERRIDE_VAR, None)
            d = Path(d)
            local_models = d / "local-models.json"
            _write_json(local_models, _DECLARED_CANDIDATES)

            out = io.StringIO()
            with mock.patch.object(mr, "LOCAL_MODELS_PATH", local_models), \
                 mock.patch.object(mr, "_ollama_list_raw", return_value=FAKE_OLLAMA_LIST), \
                 redirect_stdout(out):
                rc = mr.main(["--list"])

        self.assertEqual(rc, 0)
        lines = out.getvalue().splitlines()

        undeclared_lines = [ln for ln in lines if "random-model:latest" in ln]
        self.assertEqual(len(undeclared_lines), 1, out.getvalue())
        self.assertIn("ineligible", undeclared_lines[0])
        self.assertIn("not declared", undeclared_lines[0])

        declared_lines = [ln for ln in lines if "vendor-a:9b" in ln]
        self.assertEqual(len(declared_lines), 1, out.getvalue())
        self.assertIn("eligible", declared_lines[0])
        self.assertNotIn("ineligible", declared_lines[0])


class TestResolvePrintsExactlyOneTag(unittest.TestCase):
    def test_resolve_prints_exactly_one_tag_with_no_decoration(self):
        with tempfile.TemporaryDirectory() as d, _pop_override():
            os.environ.pop(mr.ENV_OVERRIDE_VAR, None)
            d = Path(d)
            state_path = d / "local-model-state.json"
            _write_json(state_path, {
                "current": "vendor-a:9b",
                "score": {"passed": 6, "total": 6, "ratio": 1.0, "by_kind": _by_kind(3, 3, 3, 3)},
                "qualified_at": "2026-08-14T00:00:00+00:00",
                "history": [],
            })

            out = io.StringIO()
            # F1: resolve() now verifies the resolved tag against the installed inventory,
            # so this test (which is about output formatting, not F1) must report the tag
            # as installed for the original assertions to still exercise the success path.
            with mock.patch.object(mr, "STATE_PATH", state_path), \
                 mock.patch.object(mr, "_ollama_list_raw", return_value=FAKE_OLLAMA_LIST), \
                 redirect_stdout(out):
                rc = mr.main(["--resolve"])

        self.assertEqual(rc, 0)
        raw = out.getvalue()
        # Exactly one tag: the whole capture is the tag plus a single trailing newline, no
        # other line, no leading/trailing whitespace decoration - safe for $(...) shell
        # substitution, which strips one trailing newline and nothing else.
        self.assertEqual(raw, "vendor-a:9b\n")
        self.assertEqual(raw.strip(), "vendor-a:9b")
        self.assertNotIn("\n", raw.strip())


class TestResolveRefusesPhantomTag(unittest.TestCase):
    """Fix round 1, F1 (CRITICAL): resolve() must check BOTH paths (state "current" and the
    LARI_LOCAL_MODEL override) against the installed inventory, refusing explicitly when the
    resolved tag is not installed rather than handing a phantom tag to the bridge."""

    def test_resolve_refuses_when_current_tag_not_installed(self):
        with tempfile.TemporaryDirectory() as d, _pop_override():
            os.environ.pop(mr.ENV_OVERRIDE_VAR, None)
            d = Path(d)
            state_path = d / "local-model-state.json"
            _write_json(state_path, {
                "current": "phantom:not-installed",
                "score": {"passed": 6, "total": 6, "ratio": 1.0, "by_kind": _by_kind(3, 3, 3, 3)},
                "qualified_at": "2026-08-14T00:00:00+00:00",
                "history": [],
            })

            err = io.StringIO()
            with mock.patch.object(mr, "STATE_PATH", state_path), \
                 mock.patch.object(mr, "_ollama_list_raw", return_value=FAKE_OLLAMA_LIST), \
                 redirect_stderr(err):
                rc = mr.main(["--resolve"])

            with mock.patch.object(mr, "STATE_PATH", state_path), \
                 mock.patch.object(mr, "_ollama_list_raw", return_value=FAKE_OLLAMA_LIST):
                with self.assertRaises(mr.ResolverError):
                    mr.resolve()

        self.assertNotEqual(rc, 0)
        self.assertIn("phantom:not-installed", err.getvalue())
        self.assertIn("not installed", err.getvalue())

    def test_override_refuses_when_tag_not_installed(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            # No state file at all: proves the override path's installed-check runs BEFORE
            # (and independently of) any state-file access - resolve() must not even need a
            # state file to correctly refuse an uninstalled override.
            err = io.StringIO()
            with mock.patch.object(mr, "STATE_PATH", d / "does-not-exist.json"), \
                 mock.patch.object(mr, "_ollama_list_raw", return_value=FAKE_OLLAMA_LIST), \
                 mock.patch.dict(os.environ, {mr.ENV_OVERRIDE_VAR: "phantom:override"}), \
                 redirect_stderr(err):
                rc = mr.main(["--resolve"])

        self.assertNotEqual(rc, 0)
        self.assertIn("phantom:override", err.getvalue())
        self.assertIn("not installed", err.getvalue())


class TestQualifyLosingCandidate(unittest.TestCase):
    def test_qualify_loser_regresses_in_one_role(self):
        with tempfile.TemporaryDirectory() as d, _pop_override():
            os.environ.pop(mr.ENV_OVERRIDE_VAR, None)
            d = Path(d)
            local_models = d / "local-models.json"
            tasks_path = d / "tasks.json"
            state_path = d / "local-model-state.json"
            _write_json(local_models, _DECLARED_CANDIDATES)
            _write_json(tasks_path, _FROZEN_TASKS)
            incumbent_by_kind = _by_kind(coder_passed=2, coder_total=3, writer_passed=3, writer_total=3)
            incumbent_state = {
                "current": "vendor-a:9b",
                "score": _score_from_by_kind(incumbent_by_kind),
                "qualified_at": "2026-08-14T00:00:00+00:00",
                "history": [{"date": "2026-08-14", "tag": "vendor-a:9b", "action": "seed",
                              "score": _score_from_by_kind(incumbent_by_kind), "previous": None}],
            }
            _write_json(state_path, incumbent_state)
            before_bytes = state_path.read_bytes()

            # Regresses in coder (2 -> 1), ties in writer (3 -> 3): must be rejected even
            # though it is not a net loss in every role.
            challenger_by_kind = _by_kind(coder_passed=1, coder_total=3, writer_passed=3, writer_total=3)

            def losing_result(tag, tasks):
                self.assertEqual(tag, "challenger:tag")
                return {"tag": tag, **_score_from_by_kind(challenger_by_kind), "results": []}

            err = io.StringIO()
            with mock.patch.object(mr, "LOCAL_MODELS_PATH", local_models), \
                 mock.patch.object(mr, "TASKS_PATH", tasks_path), \
                 mock.patch.object(mr, "STATE_PATH", state_path), \
                 mock.patch.object(mr, "_ollama_list_raw",
                                    return_value=(FAKE_OLLAMA_LIST + "challenger:tag  aaa  1 GB  1 day ago\n")), \
                 mock.patch.object(mr, "run_qualification_tasks", side_effect=losing_result), \
                 redirect_stderr(err):
                rc = mr.main(["--qualify", "challenger:tag"])

            after_bytes = state_path.read_bytes()

        self.assertNotEqual(rc, 0)
        self.assertEqual(before_bytes, after_bytes)
        self.assertIn("regressed", err.getvalue().lower())
        self.assertIn("coder", err.getvalue())

    def test_qualify_challenger_regressing_one_role_rejected_despite_net_gain(self):
        """Fix round 1, F3 worked example: challenger gains in coder (+2) and regresses in
        writer (-1). Net sum (3) is HIGHER than the incumbent's (2), so the old summed rule
        would have accepted this candidate; the new per-role rule must reject it."""
        with tempfile.TemporaryDirectory() as d, _pop_override():
            os.environ.pop(mr.ENV_OVERRIDE_VAR, None)
            d = Path(d)
            local_models = d / "local-models.json"
            tasks_path = d / "tasks.json"
            state_path = d / "local-model-state.json"
            _write_json(local_models, _DECLARED_CANDIDATES)
            _write_json(tasks_path, _FROZEN_TASKS)
            incumbent_by_kind = _by_kind(coder_passed=1, coder_total=3, writer_passed=1, writer_total=3)
            incumbent_state = {
                "current": "vendor-a:9b",
                "score": _score_from_by_kind(incumbent_by_kind),
                "qualified_at": "2026-08-14T00:00:00+00:00",
                "history": [{"date": "2026-08-14", "tag": "vendor-a:9b", "action": "seed",
                              "score": _score_from_by_kind(incumbent_by_kind), "previous": None}],
            }
            _write_json(state_path, incumbent_state)
            before_bytes = state_path.read_bytes()

            challenger_by_kind = _by_kind(coder_passed=3, coder_total=3, writer_passed=0, writer_total=3)
            self.assertGreater(
                sum(v["passed"] for v in challenger_by_kind.values()),
                sum(v["passed"] for v in incumbent_by_kind.values()),
                "fixture must reproduce the old rule's net-gain trap (3 > 2) to be a real regression test",
            )

            def net_gain_but_regressed_result(tag, tasks):
                return {"tag": tag, **_score_from_by_kind(challenger_by_kind), "results": []}

            err = io.StringIO()
            with mock.patch.object(mr, "LOCAL_MODELS_PATH", local_models), \
                 mock.patch.object(mr, "TASKS_PATH", tasks_path), \
                 mock.patch.object(mr, "STATE_PATH", state_path), \
                 mock.patch.object(mr, "_ollama_list_raw",
                                    return_value=(FAKE_OLLAMA_LIST + "challenger:tag  aaa  1 GB  1 day ago\n")), \
                 mock.patch.object(mr, "run_qualification_tasks", side_effect=net_gain_but_regressed_result), \
                 redirect_stderr(err):
                rc = mr.main(["--qualify", "challenger:tag"])

            after_bytes = state_path.read_bytes()

        self.assertNotEqual(rc, 0, "a net gain that hides a per-role regression must NOT win")
        self.assertEqual(before_bytes, after_bytes)
        self.assertIn("writer", err.getvalue())


class TestQualifyWinnerUpdatesState(unittest.TestCase):
    def test_qualify_winner_gains_one_role_no_regression(self):
        with tempfile.TemporaryDirectory() as d, _pop_override():
            os.environ.pop(mr.ENV_OVERRIDE_VAR, None)
            d = Path(d)
            local_models = d / "local-models.json"
            tasks_path = d / "tasks.json"
            state_path = d / "local-model-state.json"
            _write_json(local_models, _DECLARED_CANDIDATES)
            _write_json(tasks_path, _FROZEN_TASKS)
            incumbent_by_kind = _by_kind(coder_passed=1, coder_total=3, writer_passed=3, writer_total=3)
            incumbent_state = {
                "current": "vendor-a:9b",
                "score": _score_from_by_kind(incumbent_by_kind),
                "qualified_at": "2026-08-14T00:00:00+00:00",
                "history": [{"date": "2026-08-14", "tag": "vendor-a:9b", "action": "seed",
                              "score": _score_from_by_kind(incumbent_by_kind), "previous": None}],
            }
            _write_json(state_path, incumbent_state)

            # Gains in coder (1 -> 3), ties in writer (3 -> 3): no regression anywhere, a
            # strict gain in one role - a clean win under the new rule.
            challenger_by_kind = _by_kind(coder_passed=3, coder_total=3, writer_passed=3, writer_total=3)

            def winning_result(tag, tasks):
                return {"tag": tag, **_score_from_by_kind(challenger_by_kind), "results": []}

            with mock.patch.object(mr, "LOCAL_MODELS_PATH", local_models), \
                 mock.patch.object(mr, "TASKS_PATH", tasks_path), \
                 mock.patch.object(mr, "STATE_PATH", state_path), \
                 mock.patch.object(mr, "_ollama_list_raw",
                                    return_value=(FAKE_OLLAMA_LIST + "challenger:tag  aaa  1 GB  1 day ago\n")), \
                 mock.patch.object(mr, "run_qualification_tasks", side_effect=winning_result):
                rc = mr.main(["--qualify", "challenger:tag"])

            new_state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(rc, 0)
        self.assertEqual(new_state["current"], "challenger:tag")
        self.assertEqual(new_state["score"]["passed"], 6)
        self.assertEqual(new_state["score"]["by_kind"]["coder"]["passed"], 3)
        self.assertEqual(len(new_state["history"]), 2)  # seed entry preserved, new one appended
        self.assertEqual(new_state["history"][0]["tag"], "vendor-a:9b")
        new_entry = new_state["history"][-1]
        self.assertEqual(new_entry["tag"], "challenger:tag")
        self.assertRegex(new_entry["date"], r"^\d{4}-\d{2}-\d{2}$")


class TestEnvOverrideWinsOverState(unittest.TestCase):
    def test_env_override_wins_over_state_and_does_not_modify_it(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            state_path = d / "local-model-state.json"
            _write_json(state_path, {
                "current": "state-tag:latest",
                "score": {"passed": 6, "total": 6, "ratio": 1.0, "by_kind": _by_kind(3, 3, 3, 3)},
                "qualified_at": "2026-08-14T00:00:00+00:00",
                "history": [],
            })
            before_bytes = state_path.read_bytes()

            out = io.StringIO()
            fake_list_with_override = FAKE_OLLAMA_LIST + "override-tag:latest  aaa  1 GB  1 day ago\n"
            with mock.patch.object(mr, "STATE_PATH", state_path), \
                 mock.patch.object(mr, "_ollama_list_raw", return_value=fake_list_with_override), \
                 mock.patch.dict(os.environ, {mr.ENV_OVERRIDE_VAR: "override-tag:latest"}), \
                 redirect_stdout(out):
                rc = mr.main(["--resolve"])

            after_bytes = state_path.read_bytes()

        self.assertEqual(rc, 0)
        self.assertEqual(out.getvalue().strip(), "override-tag:latest")
        self.assertEqual(before_bytes, after_bytes)


class TestMissingOrEmptyStateIsExplicitError(unittest.TestCase):
    def test_missing_state_file_is_explicit_error(self):
        with tempfile.TemporaryDirectory() as d, _pop_override():
            os.environ.pop(mr.ENV_OVERRIDE_VAR, None)
            d = Path(d)
            state_path = d / "does-not-exist.json"  # never created

            err = io.StringIO()
            with mock.patch.object(mr, "STATE_PATH", state_path), redirect_stderr(err):
                rc = mr.main(["--resolve"])

            with mock.patch.object(mr, "STATE_PATH", state_path):
                with self.assertRaises(mr.ResolverError):
                    mr.resolve()

        self.assertNotEqual(rc, 0)
        self.assertIn(str(state_path), err.getvalue())

    def test_empty_state_file_is_explicit_error(self):
        with tempfile.TemporaryDirectory() as d, _pop_override():
            os.environ.pop(mr.ENV_OVERRIDE_VAR, None)
            d = Path(d)
            state_path = d / "local-model-state.json"
            state_path.write_text("", encoding="utf-8")  # present but empty

            err = io.StringIO()
            with mock.patch.object(mr, "STATE_PATH", state_path), redirect_stderr(err):
                rc = mr.main(["--resolve"])

            with mock.patch.object(mr, "STATE_PATH", state_path):
                with self.assertRaises(mr.ResolverError):
                    mr.resolve()

        self.assertNotEqual(rc, 0)
        self.assertIn(str(state_path), err.getvalue())


class TestPolicyIsWired(unittest.TestCase):
    """Fix round 1, F2: local-models.json's policy fields must genuinely drive cmd_qualify's
    decision. Each test flips exactly one field and shows the outcome flips with it."""

    def _setup(self, d: Path, policy: dict, tag: str = "random-model:latest") -> tuple[Path, Path, Path]:
        local_models = d / "local-models.json"
        tasks_path = d / "tasks.json"
        state_path = d / "local-model-state.json"
        candidates_doc = {
            "_header": {"purpose": "fixture"},
            "policy": policy,
            "candidates": [{"tag": "vendor-a:9b", "role": "writer", "declared": "2026-08-14", "notes": "fixture"}],
        }
        _write_json(local_models, candidates_doc)
        _write_json(tasks_path, _FROZEN_TASKS)
        return local_models, tasks_path, state_path

    def test_require_declared_policy_toggle_changes_outcome(self):
        # tag "random-model:latest" is installed (FAKE_OLLAMA_LIST) but NEVER declared as a
        # candidate in either fixture below.
        def bootstrap_result(tag, tasks):
            return {"tag": tag, **_score_from_by_kind(_by_kind(1, 1, 0, 0)), "results": []}

        with tempfile.TemporaryDirectory() as d, _pop_override():
            os.environ.pop(mr.ENV_OVERRIDE_VAR, None)
            d = Path(d)

            # require_declared = True (default): must refuse.
            local_models, tasks_path, state_path = self._setup(d, _full_policy(require_declared=True))
            err = io.StringIO()
            with mock.patch.object(mr, "LOCAL_MODELS_PATH", local_models), \
                 mock.patch.object(mr, "TASKS_PATH", tasks_path), \
                 mock.patch.object(mr, "STATE_PATH", state_path), \
                 mock.patch.object(mr, "_ollama_list_raw", return_value=FAKE_OLLAMA_LIST), \
                 mock.patch.object(mr, "run_qualification_tasks", side_effect=bootstrap_result), \
                 redirect_stderr(err):
                rc_declared_true = mr.main(["--qualify", "random-model:latest"])
            state_exists_after_true = state_path.exists()

            # require_declared = False: the SAME undeclared tag must now be allowed through
            # (it is still installed, and there is no incumbent yet, so it seeds).
            local_models2, tasks_path2, state_path2 = self._setup(
                d / "flip", _full_policy(require_declared=False)
            )
            with mock.patch.object(mr, "LOCAL_MODELS_PATH", local_models2), \
                 mock.patch.object(mr, "TASKS_PATH", tasks_path2), \
                 mock.patch.object(mr, "STATE_PATH", state_path2), \
                 mock.patch.object(mr, "_ollama_list_raw", return_value=FAKE_OLLAMA_LIST), \
                 mock.patch.object(mr, "run_qualification_tasks", side_effect=bootstrap_result):
                rc_declared_false = mr.main(["--qualify", "random-model:latest"])
            state_exists_after_false = state_path2.exists()

        self.assertNotEqual(rc_declared_true, 0)
        self.assertFalse(state_exists_after_true)
        self.assertIn("not declared", err.getvalue())

        self.assertEqual(rc_declared_false, 0)
        self.assertTrue(state_exists_after_false)

    def test_unsupported_win_rule_value_refuses(self):
        with tempfile.TemporaryDirectory() as d, _pop_override():
            os.environ.pop(mr.ENV_OVERRIDE_VAR, None)
            d = Path(d)
            local_models, tasks_path, state_path = self._setup(
                d, _full_policy(win_rule="totally_unknown_rule"), tag="vendor-a:9b"
            )
            err = io.StringIO()
            with mock.patch.object(mr, "LOCAL_MODELS_PATH", local_models), \
                 mock.patch.object(mr, "TASKS_PATH", tasks_path), \
                 mock.patch.object(mr, "STATE_PATH", state_path), \
                 mock.patch.object(mr, "_ollama_list_raw", return_value=FAKE_OLLAMA_LIST), \
                 redirect_stderr(err):
                rc = mr.main(["--qualify", "vendor-a:9b"])

        self.assertNotEqual(rc, 0)
        self.assertIn("win_rule", err.getvalue())
        self.assertIn("totally_unknown_rule", err.getvalue())


class TestLanguageGateTightened(unittest.TestCase):
    """Fix round 1, F4: the language gate must FAIL English prose salted with a couple of
    French tokens (false-PASS is the dangerous direction - a wrongly-passed qualification
    adopts a worse model), while still PASSING genuine French with accents (positive control,
    so the tightened gate has not become unusable)."""

    @staticmethod
    def _run_writer_gate(text: str, task: dict) -> subprocess.CompletedProcess:
        command = mr._build_writer_verify_command(task)
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "candidate.md"
            target.write_text(text, encoding="utf-8")
            resolved = [str(part).replace("{target}", str(target)) for part in command]
            return subprocess.run(resolved, capture_output=True, text=True, timeout=30)

    def test_language_gate_fails_on_english_with_stray_french_tokens(self):
        task = {"required_sections": [], "language": "fr", "min_length_chars": 0,
                 "max_length_chars": 10**6, "frontmatter_keys": []}
        # Plain English, no accented characters anywhere, salted with exactly two French
        # function words ("la", "de") that could appear as loanwords or coincidental tokens.
        english_with_french_tokens = (
            "This report explains the outcome of the la review meeting held last week. "
            "The team discussed several options and picked the plan de action that made the "
            "most sense given the current schedule and the available budget for the quarter. "
            "Everyone agreed the timeline was reasonable and the next steps were assigned to "
            "the appropriate owners before the meeting was closed for the day."
        )
        result = self._run_writer_gate(english_with_french_tokens, task)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("language gate", result.stderr)

    def test_language_gate_passes_on_genuine_french_with_accents(self):
        task = {"required_sections": [], "language": "fr", "min_length_chars": 0,
                 "max_length_chars": 10**6, "frontmatter_keys": []}
        # Genuine French prose, with the accented characters real French text naturally
        # carries (\xe9, \xe8, \xe0, ...), unlike the English-with-stray-tokens case above.
        genuine_french = (
            "Le module est responsable de la validation des données reçues. Le "
            "problème était que la fonction ne vérifiait pas correctement les "
            "valeurs vides, ce qui causait des erreurs silencieuses dans le pipeline. La "
            "correction ajoute une vérification explicite avant tout traitement, et le "
            "comportement est désormais prévisible pour les cas limites déjà "
            "rencontrés par le passé."
        )
        result = self._run_writer_gate(genuine_french, task)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class TestLanguageGateFunctionWordDiscriminator(unittest.TestCase):
    """Fix round 2, item 1: the three fix-round-1 thresholds alone still false-PASS English
    idiom-stacking (a string built entirely of French noun phrases borrowed whole into
    English, which is exactly why a marker-word COUNT is gameable). The new fourth
    requirement - a minimum number of DISTINCT hits from a small function_words list
    targeting clause-level grammar - is additive, not a replacement of the other three."""

    @staticmethod
    def _run_writer_gate(text: str, task: dict) -> subprocess.CompletedProcess:
        command = mr._build_writer_verify_command(task)
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "candidate.md"
            target.write_text(text, encoding="utf-8")
            resolved = [str(part).replace("{target}", str(target)) for part in command]
            return subprocess.run(resolved, capture_output=True, text=True, timeout=30)

    def test_idiom_stacking_string_fails_verbatim_reviewer_case(self):
        # Verbatim string from the fix round 2 review: English idiom-stacking built entirely
        # of borrowed French noun phrases (no French VERB or CLAUSE-level preposition
        # anywhere - "est"/"sont"/"dans"/"avec"/"pour"/"sur"/"qui"/"cette"/"les"/"des"/
        # "nous"/"plus" all absent), which is exactly the shape the new discriminator exists
        # to catch. Kept byte-for-byte as given, not paraphrased.
        idiom_stacking = (
            "Creme de la creme, au contraire, du coup, coup de grace, de facto. "
            "Her fiancee's resume: cafe."
        )
        task = {"required_sections": [], "language": "fr", "min_length_chars": 0,
                 "max_length_chars": 10**6, "frontmatter_keys": []}
        result = self._run_writer_gate(idiom_stacking, task)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("language gate", result.stderr)
        # The new leg specifically, independent of whichever of the other three legs also
        # fail in this environment: zero of the twelve function words appear anywhere in an
        # idiom-stacked string, because none of them are full clauses.
        self.assertIn("0 distinct French function word(s) hit", result.stderr)

    def test_genuine_french_paragraph_from_vault_note_passes(self):
        # A real, substantial French paragraph read READ-ONLY from an existing vault note
        # (C:\Martin Otis\Vault\30_Ressources\Obsidian\obsidian-cli-ecriture-fichiers.md,
        # the "Contexte" and "Probleme" sections verbatim, accents included) - not written
        # back anywhere. Confirms the tightened gate still accepts real French prose.
        vault_note = Path(r"C:\Martin Otis\Vault\30_Ressources\Obsidian\obsidian-cli-ecriture-fichiers.md")
        if not vault_note.exists():
            self.skipTest(f"vault note not present on this machine: {vault_note}")
        full_text = vault_note.read_text(encoding="utf-8")
        start = full_text.index("L'interface")
        end = full_text.index("## Cause racine")
        excerpt = full_text[start:end].strip()
        self.assertGreater(len(excerpt), 500, "the excerpt should be a real paragraph, not a fragment")

        task = {"required_sections": [], "language": "fr", "min_length_chars": 0,
                 "max_length_chars": 10**6, "frontmatter_keys": []}
        result = self._run_writer_gate(excerpt, task)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_short_genuine_french_sentence_still_passes_not_a_length_gate(self):
        # A single short sentence (84 characters), to prove the new discriminator is a
        # grammar check, not disguised minimum-length requirement: it clears all four legs
        # (marker 6, accent 4, density ~0.048, 5 distinct function words: cette/est/dans/
        # pour/les) despite being far shorter than the vault excerpt above.
        short_sentence = "Cette erreur est survenue dans le système pour tous les utilisateurs déjà connectés."
        self.assertLess(len(short_sentence), 100)

        task = {"required_sections": [], "language": "fr", "min_length_chars": 0,
                 "max_length_chars": 10**6, "frontmatter_keys": []}
        result = self._run_writer_gate(short_sentence, task)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class TestAtomicWrite(unittest.TestCase):
    def test_write_state_leaves_no_leftover_tmp_file(self):
        with tempfile.TemporaryDirectory() as d, _pop_override():
            os.environ.pop(mr.ENV_OVERRIDE_VAR, None)
            d = Path(d)
            local_models = d / "local-models.json"
            tasks_path = d / "tasks.json"
            state_path = d / "local-model-state.json"
            _write_json(local_models, _DECLARED_CANDIDATES)
            _write_json(tasks_path, _FROZEN_TASKS)

            def bootstrap_result(tag, tasks):
                return {"tag": tag, **_score_from_by_kind(_by_kind(3, 3, 3, 3)), "results": []}

            with mock.patch.object(mr, "LOCAL_MODELS_PATH", local_models), \
                 mock.patch.object(mr, "TASKS_PATH", tasks_path), \
                 mock.patch.object(mr, "STATE_PATH", state_path), \
                 mock.patch.object(mr, "_ollama_list_raw", return_value=FAKE_OLLAMA_LIST), \
                 mock.patch.object(mr, "run_qualification_tasks", side_effect=bootstrap_result):
                rc = mr.main(["--qualify", "vendor-a:9b"])

            tmp_sibling = state_path.with_name(state_path.name + ".tmp")

            self.assertEqual(rc, 0)
            self.assertTrue(state_path.exists())
            self.assertFalse(tmp_sibling.exists())


class TestCoderTargetMustLookLikePython(unittest.TestCase):
    """Measured 2026-08-14, and it invalidates every coder score recorded before it: the
    candidate module was written to "<task_id>.out", and spec_from_file_location infers its
    loader from the EXTENSION, returning loader=None for ".out". The verify died on
    "AttributeError: 'NoneType' object has no attribute 'loader'" before running a single
    case, so EVERY coder task failed for EVERY model. The generated module itself was
    correct: byte for byte, it passes all five cases from a ".py" file."""

    TASK = {
        "id": "fixture-norm", "kind": "coder", "entrypoint": "f",
        "cases": [{"args": [1], "expect": 2}],
    }
    MODULE = "def f(x):\n    return x + 1\n"

    def _run(self, filename: str) -> subprocess.CompletedProcess:
        command = mr._build_coder_verify_command(self.TASK)
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / filename
            target.write_text(self.MODULE, encoding="utf-8")
            resolved = [str(p).replace("{target}", str(target)) for p in command]
            return subprocess.run(resolved, capture_output=True, text=True, timeout=30)

    def test_the_same_module_passes_from_a_py_file(self):
        self.assertEqual(self._run("candidate.py").returncode, 0)

    def test_a_non_python_extension_fails_with_a_named_reason(self):
        result = self._run("candidate.out")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no loader for that file extension", result.stderr)
        self.assertNotIn("AttributeError", result.stderr)

    def test_a_coder_task_is_handed_a_py_target(self):
        seen = {}

        class FakeBridge:
            DEFAULT_SEED = 42

            @staticmethod
            def run_bridge(prompt_path, verify_command, target_path, seed, log_path):
                seen["target"] = Path(target_path)
                return 0

        with tempfile.TemporaryDirectory() as d:
            mr._run_one_task(FakeBridge, dict(self.TASK, prompt="p"), Path(d))
        self.assertEqual(seen["target"].suffix, ".py")

    def test_a_writer_task_keeps_its_out_target(self):
        seen = {}

        class FakeBridge:
            DEFAULT_SEED = 42

            @staticmethod
            def run_bridge(prompt_path, verify_command, target_path, seed, log_path):
                seen["target"] = Path(target_path)
                return 0

        task = {"id": "fixture-note", "kind": "writer", "prompt": "p",
                 "required_sections": [], "language": "", "frontmatter_keys": []}
        with tempfile.TemporaryDirectory() as d:
            mr._run_one_task(FakeBridge, task, Path(d))
        self.assertEqual(seen["target"].suffix, ".out")


class TestLanguageGateThresholdsAreOnePlace(unittest.TestCase):
    """P7 (open-items pass): the four thresholds were literals buried in the generated
    check, so nothing named them as the judgment calls they are and a sweep meant editing
    code. They now come from model_resolver.LANGUAGE_GATE_THRESHOLDS and a task may
    override any of them. These two cases prove the injection is real: changing the value
    changes the verdict on the SAME text.
    """

    @staticmethod
    def _run_writer_gate(text: str, task: dict) -> subprocess.CompletedProcess:
        command = mr._build_writer_verify_command(task)
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "candidate.md"
            target.write_text(text, encoding="utf-8")
            resolved = [str(part).replace("{target}", str(target)) for part in command]
            return subprocess.run(resolved, capture_output=True, text=True, timeout=30)

    # Genuine French, accents included, written as codepoint escapes so this test file's own
    # bytes stay plain ASCII (the same discipline the checked script itself follows).
    FRENCH = (
        "Cette note décrit la procédure qui est appliquée dans le dépôt pour "
        "les modèles locaux, avec les seuils qui sont mesurés sur la carte."
    )

    def test_a_task_can_raise_a_threshold_and_change_the_verdict(self):
        base = {"required_sections": [], "language": "fr", "min_length_chars": 0,
                 "max_length_chars": 10**6, "frontmatter_keys": []}
        self.assertEqual(self._run_writer_gate(self.FRENCH, base).returncode, 0,
                         "positive control: genuine French passes at the shipped thresholds")

        strict = dict(base, language_thresholds={"min_marker_hits": 10_000})
        result = self._run_writer_gate(self.FRENCH, strict)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("need >= 10000", result.stderr)

    def test_the_shipped_values_are_the_ones_that_reach_the_check(self):
        base = {"required_sections": [], "language": "fr", "min_length_chars": 0,
                 "max_length_chars": 10**6, "frontmatter_keys": []}
        command = mr._build_writer_verify_command(base)
        # The params travel as a JSON string embedded in a Python source string, so the
        # quotes are escaped once; unescape them to read the payload as plain JSON.
        payload = command[2].replace('\\"', '"')
        for key, value in mr.LANGUAGE_GATE_THRESHOLDS.items():
            self.assertIn(f'"{key}": {value}', payload,
                           f"{key} must reach the generated check from the module constant")


_BOTH_KIND_TASKS = {
    "_header": {"purpose": "test fixture: one task of each kind, so a --role run has something to filter"},
    "tasks": [
        {"id": "fixture-coder-1", "kind": "coder", "prompt": "unused", "entrypoint": "f", "cases": []},
        {"id": "fixture-coder-2", "kind": "coder", "prompt": "unused", "entrypoint": "f", "cases": []},
        {"id": "fixture-writer-1", "kind": "writer", "prompt": "unused", "required_sections": []},
    ],
}


def _role_fixture(d: Path, state: dict | None) -> tuple[Path, Path, Path]:
    """Lay down the three data files a --role case needs; state=None writes no state file."""
    local_models = d / "local-models.json"
    tasks_path = d / "tasks.json"
    state_path = d / "local-model-state.json"
    _write_json(local_models, _DECLARED_CANDIDATES)
    _write_json(tasks_path, _BOTH_KIND_TASKS)
    if state is not None:
        _write_json(state_path, state)
    return local_models, tasks_path, state_path


def _state_with_role_map(**by_role) -> dict:
    """An incumbent state document: vendor-a:9b overall, writer-strong and coder-weak,
    which is this machine's real measured shape (writer 3/3, coder 0/3)."""
    by_kind = _by_kind(coder_passed=0, coder_total=3, writer_passed=3, writer_total=3)
    state = {
        "current": "vendor-a:9b",
        "score": _score_from_by_kind(by_kind),
        "qualified_at": "2026-08-14T00:00:00+00:00",
        "history": [{"date": "2026-08-14", "tag": "vendor-a:9b", "action": "seed",
                      "score": _score_from_by_kind(by_kind), "previous": None}],
    }
    if by_role:
        state["current_by_role"] = dict(by_role)
    return state


class TestPerRoleCurrentTag(unittest.TestCase):
    """P4 (open-items pass): `current` no longer decides which model EVERY role gets.

    The defect these cases pin down was measurable on the real state file: the incumbent
    passes 3/3 writer tasks and 0/3 coder tasks, and local-coder was handed that same tag
    because neither resolve() nor the bridge could express "the coder one".
    """

    def test_resolve_role_returns_the_tag_adopted_for_that_role(self):
        with tempfile.TemporaryDirectory() as d, _pop_override():
            os.environ.pop(mr.ENV_OVERRIDE_VAR, None)
            d = Path(d)
            _, _, state_path = _role_fixture(d, _state_with_role_map(
                coder={"tag": "vendor:7b", "passed": 2, "total": 2, "adopted": "2026-08-14"}))
            out = io.StringIO()
            with mock.patch.object(mr, "STATE_PATH", state_path), \
                 mock.patch.object(mr, "_ollama_list_raw", return_value=FAKE_OLLAMA_LIST), \
                 redirect_stdout(out):
                rc = mr.main(["--resolve", "--role", "coder"])
        self.assertEqual(rc, 0)
        self.assertEqual(out.getvalue().strip(), "vendor:7b")

    def test_resolve_role_without_an_entry_falls_back_to_current(self):
        """The fallback is not a D7 downgrade: it returns the very tag the bridge would
        have received before --role existed."""
        with tempfile.TemporaryDirectory() as d, _pop_override():
            os.environ.pop(mr.ENV_OVERRIDE_VAR, None)
            d = Path(d)
            _, _, state_path = _role_fixture(d, _state_with_role_map(
                coder={"tag": "vendor:7b", "passed": 2, "total": 2, "adopted": "2026-08-14"}))
            out = io.StringIO()
            with mock.patch.object(mr, "STATE_PATH", state_path), \
                 mock.patch.object(mr, "_ollama_list_raw", return_value=FAKE_OLLAMA_LIST), \
                 redirect_stdout(out):
                rc = mr.main(["--resolve", "--role", "writer"])
        self.assertEqual(rc, 0)
        self.assertEqual(out.getvalue().strip(), "vendor-a:9b")

    def test_qualify_role_adopts_that_role_only_and_leaves_current_alone(self):
        with tempfile.TemporaryDirectory() as d, _pop_override():
            os.environ.pop(mr.ENV_OVERRIDE_VAR, None)
            d = Path(d)
            local_models, tasks_path, state_path = _role_fixture(d, _state_with_role_map())

            seen_tasks = []

            def coder_result(tag, tasks):
                seen_tasks.extend(tasks)
                return {"tag": tag, "passed": 2, "total": 2, "ratio": 1.0,
                         "by_kind": {"coder": {"passed": 2, "total": 2}}, "results": []}

            with mock.patch.object(mr, "LOCAL_MODELS_PATH", local_models), \
                 mock.patch.object(mr, "TASKS_PATH", tasks_path), \
                 mock.patch.object(mr, "STATE_PATH", state_path), \
                 mock.patch.object(mr, "_ollama_list_raw", return_value=FAKE_OLLAMA_LIST), \
                 mock.patch.object(mr, "run_qualification_tasks", side_effect=coder_result):
                rc = mr.main(["--qualify", "vendor:7b", "--role", "coder"])
            new_state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(rc, 0)
        # Only that role's slice of the frozen set was executed.
        self.assertEqual([t["kind"] for t in seen_tasks], ["coder", "coder"])
        self.assertEqual(new_state["current_by_role"]["coder"]["tag"], "vendor:7b")
        # The overall tag and the full-run score are untouched: a partial task set cannot
        # speak for the whole frozen set.
        self.assertEqual(new_state["current"], "vendor-a:9b")
        self.assertEqual(new_state["score"]["by_kind"]["writer"]["passed"], 3)
        self.assertEqual(new_state["qualified_at"], "2026-08-14T00:00:00+00:00")
        self.assertEqual(new_state["history"][-1]["action"], "promote-role:coder")

    def test_qualify_role_tie_is_not_a_win(self):
        with tempfile.TemporaryDirectory() as d, _pop_override():
            os.environ.pop(mr.ENV_OVERRIDE_VAR, None)
            d = Path(d)
            local_models, tasks_path, state_path = _role_fixture(d, _state_with_role_map(
                coder={"tag": "vendor:7b", "passed": 1, "total": 2, "adopted": "2026-08-14"}))
            before_bytes = state_path.read_bytes()

            def tying_result(tag, tasks):
                return {"tag": tag, "passed": 1, "total": 2, "ratio": 0.5,
                         "by_kind": {"coder": {"passed": 1, "total": 2}}, "results": []}

            err = io.StringIO()
            with mock.patch.object(mr, "LOCAL_MODELS_PATH", local_models), \
                 mock.patch.object(mr, "TASKS_PATH", tasks_path), \
                 mock.patch.object(mr, "STATE_PATH", state_path), \
                 mock.patch.object(mr, "_ollama_list_raw",
                                    return_value=(FAKE_OLLAMA_LIST + "challenger:tag  aaa  1 GB  1 day ago\n")), \
                 mock.patch.object(mr, "run_qualification_tasks", side_effect=tying_result), \
                 redirect_stderr(err):
                rc = mr.main(["--qualify", "challenger:tag", "--role", "coder"])
            after_bytes = state_path.read_bytes()

        self.assertEqual(rc, 1)
        self.assertEqual(before_bytes, after_bytes)
        self.assertIn("not a strict gain", err.getvalue())

    def test_qualify_role_refuses_a_kind_no_task_declares(self):
        with tempfile.TemporaryDirectory() as d, _pop_override():
            os.environ.pop(mr.ENV_OVERRIDE_VAR, None)
            d = Path(d)
            local_models, tasks_path, state_path = _role_fixture(d, _state_with_role_map())
            ran = []
            err = io.StringIO()
            with mock.patch.object(mr, "LOCAL_MODELS_PATH", local_models), \
                 mock.patch.object(mr, "TASKS_PATH", tasks_path), \
                 mock.patch.object(mr, "STATE_PATH", state_path), \
                 mock.patch.object(mr, "_ollama_list_raw",
                                    return_value=(FAKE_OLLAMA_LIST + "challenger:tag  aaa  1 GB  1 day ago\n")), \
                 mock.patch.object(mr, "run_qualification_tasks",
                                    side_effect=lambda tag, tasks: ran.append(tag)), \
                 redirect_stderr(err):
                rc = mr.main(["--qualify", "challenger:tag", "--role", "translator"])

        self.assertEqual(rc, 1)
        self.assertEqual(ran, [])  # refused BEFORE spending a generation
        self.assertIn("translator", err.getvalue())

    def test_qualify_role_refuses_to_seed_an_absent_state_file(self):
        """A role run executes a fraction of the frozen set; letting it seed `current`
        would let a partial measurement decide the global tag."""
        with tempfile.TemporaryDirectory() as d, _pop_override():
            os.environ.pop(mr.ENV_OVERRIDE_VAR, None)
            d = Path(d)
            local_models, tasks_path, state_path = _role_fixture(d, None)

            def coder_result(tag, tasks):
                return {"tag": tag, "passed": 2, "total": 2, "ratio": 1.0,
                         "by_kind": {"coder": {"passed": 2, "total": 2}}, "results": []}

            err = io.StringIO()
            with mock.patch.object(mr, "LOCAL_MODELS_PATH", local_models), \
                 mock.patch.object(mr, "TASKS_PATH", tasks_path), \
                 mock.patch.object(mr, "STATE_PATH", state_path), \
                 mock.patch.object(mr, "_ollama_list_raw", return_value=FAKE_OLLAMA_LIST), \
                 mock.patch.object(mr, "run_qualification_tasks", side_effect=coder_result), \
                 redirect_stderr(err):
                rc = mr.main(["--qualify", "vendor:7b", "--role", "coder"])
            state_written = state_path.exists()

        self.assertEqual(rc, 1)
        self.assertFalse(state_written)
        self.assertIn("no incumbent", err.getvalue())

    def test_full_qualify_keeps_a_role_its_own_tag_wins(self):
        """An overall winner does not quietly take a role it merely TIED: the role keeps
        the tag that holds it. This is the whole point of the map."""
        with tempfile.TemporaryDirectory() as d, _pop_override():
            os.environ.pop(mr.ENV_OVERRIDE_VAR, None)
            d = Path(d)
            local_models, tasks_path, state_path = _role_fixture(d, _state_with_role_map(
                writer={"tag": "vendor-a:9b", "passed": 3, "total": 3, "adopted": "2026-08-14"},
                coder={"tag": "vendor:7b", "passed": 1, "total": 3, "adopted": "2026-08-14"}))

            # Gains in coder (0 -> 3 against the incumbent's own by_kind), ties in writer.
            challenger_by_kind = _by_kind(coder_passed=3, coder_total=3, writer_passed=3, writer_total=3)

            def winning_result(tag, tasks):
                return {"tag": tag, **_score_from_by_kind(challenger_by_kind), "results": []}

            with mock.patch.object(mr, "LOCAL_MODELS_PATH", local_models), \
                 mock.patch.object(mr, "TASKS_PATH", tasks_path), \
                 mock.patch.object(mr, "STATE_PATH", state_path), \
                 mock.patch.object(mr, "_ollama_list_raw",
                                    return_value=(FAKE_OLLAMA_LIST + "challenger:tag  aaa  1 GB  1 day ago\n")), \
                 mock.patch.object(mr, "run_qualification_tasks", side_effect=winning_result):
                rc = mr.main(["--qualify", "challenger:tag"])
            new_state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(rc, 0)
        self.assertEqual(new_state["current"], "challenger:tag")
        # 3/3 beats 1/3 -> the coder role changes hands.
        self.assertEqual(new_state["current_by_role"]["coder"]["tag"], "challenger:tag")
        # 3/3 ties 3/3 -> the writer role does NOT.
        self.assertEqual(new_state["current_by_role"]["writer"]["tag"], "vendor-a:9b")

    def test_role_flag_is_refused_with_list(self):
        err = io.StringIO()
        with redirect_stderr(err):
            rc = mr.main(["--list", "--role", "coder"])
        self.assertEqual(rc, 1)
        self.assertIn("--role", err.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
