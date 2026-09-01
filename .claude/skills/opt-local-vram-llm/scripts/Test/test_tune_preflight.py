"""
Offline tests for tune_preflight.py, the decision half of tune-new-model.ps1.

The harness itself spawns processes and cannot be exercised offline, so everything that
REFUSES or COMPARES was put in this module and is tested here: the installed listing is
patched, the measured window comes from a temp config, and the matrix is a literal fixture.
No Ollama, no GPU, no model call, and no tag written into an assertion by hand - the tuned
name comes from vram_optimizer, which owns it.

The last class checks the PowerShell file as text. Those are the guards that stop the harness
from quietly growing the one behaviour it exists to withhold: adoption.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SCRIPTS))

import tune_preflight as tp  # noqa: E402
import vram_optimizer as vo  # noqa: E402

_BASE = "family:size"
_TUNED = vo.tuned_tag_for(_BASE)
_OTHER = "other-family:size"


def _matrix(rows):
    return {"task_ids": ["t1", "t2"], "rows": rows}


def _row(role, passed, total, all_passed, all_total, runnable=True, why="",
         num_ctx=16384, tps=12.5):
    return {"runnable": runnable, "why": why,
            "by_kind": {role: {"passed": passed, "total": total}},
            "passed": all_passed, "total": all_total,
            "budget": {"num_ctx": num_ctx, "decode_tps": tps},
            "per_task": {}}


class TestTunePhaseRefusals(unittest.TestCase):
    def test_a_tag_that_is_not_installed_is_refused_by_name(self):
        refusals = tp.check_tune(_BASE, [_OTHER], None)
        self.assertEqual(len(refusals), 1)
        self.assertIn(_BASE, refusals[0])
        self.assertIn("not installed", refusals[0])

    def test_no_tag_is_refused_without_consulting_ollama(self):
        # The tag is an argument, never a default. The listing is not even reached,
        # which is why the error string passed here would be a false positive if it were.
        refusals = tp.check_tune("   ", [_BASE], "unreachable")
        self.assertEqual(len(refusals), 1)
        self.assertIn("no tag given", refusals[0])
        self.assertNotIn("unreachable", refusals[0])

    def test_an_already_tuned_tag_is_refused(self):
        # Tuning a tuned tag measures a model two removes from what was downloaded.
        refusals = tp.check_tune(_TUNED, [_TUNED], None)
        self.assertTrue(any(vo.TUNED_TAG_SUFFIX in r for r in refusals))

    def test_an_unreachable_daemon_is_the_only_message(self):
        refusals = tp.check_tune(_BASE, [], "[RESOLVER] cannot run 'ollama list': boom")
        self.assertEqual(refusals, ["[RESOLVER] cannot run 'ollama list': boom"])

    def test_no_installed_model_at_all_is_refused(self):
        refusals = tp.check_tune(_BASE, [], None)
        self.assertEqual(len(refusals), 1)
        self.assertIn("nothing to tune", refusals[0])

    def test_an_installed_base_tag_proceeds(self):
        self.assertEqual(tp.check_tune(_BASE, [_BASE, _OTHER], None), [])


class TestScorePhaseRefusals(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.config = self.tmp / "local-model-config.json"

    def _write_config(self, models):
        self.config.write_text(json.dumps({"models": models}), encoding="utf-8")

    def test_a_sweep_that_left_no_tag_is_refused(self):
        self._write_config({_TUNED: {"retained_num_ctx": 16384}})
        refusals = tp.check_score(_TUNED, [_BASE], None, self.config)
        self.assertTrue(any("did not leave" in r for r in refusals))

    def test_an_unmeasured_tag_is_refused_rather_than_scored(self):
        # This is the case model_resolver reports as NOT RUNNABLE. Scoring it anyway
        # prints zeros that read as failures of the model rather than of the sweep.
        self._write_config({_OTHER: {"retained_num_ctx": 16384}})
        refusals = tp.check_score(_TUNED, [_TUNED], None, self.config)
        self.assertEqual(len(refusals), 1)
        self.assertIn("no measured context window", refusals[0])
        self.assertIn(_TUNED, refusals[0])

    def test_a_missing_config_file_is_refused_not_defaulted(self):
        refusals = tp.check_score(_TUNED, [_TUNED], None, self.tmp / "absent.json")
        self.assertEqual(len(refusals), 1)
        self.assertIn("no measured context window", refusals[0])

    def test_a_measured_installed_tag_proceeds(self):
        self._write_config({_TUNED: {"retained_num_ctx": 16384}})
        self.assertEqual(tp.check_score(_TUNED, [_TUNED], None, self.config), [])

    def test_an_unreachable_daemon_short_circuits_the_window_check(self):
        refusals = tp.check_score(_TUNED, [], "cannot reach ollama", self.config)
        self.assertEqual(refusals, ["cannot reach ollama"])


class TestInstalledTags(unittest.TestCase):
    def test_a_resolver_error_becomes_a_message_not_an_exception(self):
        with mock.patch.object(tp.model_resolver, "list_installed_models",
                               side_effect=tp.model_resolver.ResolverError("[RESOLVER] nope")):
            tags, error = tp.installed_tags()
        self.assertEqual(tags, [])
        self.assertIn("nope", error)

    def test_a_successful_listing_carries_no_error(self):
        with mock.patch.object(tp.model_resolver, "list_installed_models",
                               return_value=[_BASE]):
            tags, error = tp.installed_tags()
        self.assertEqual((tags, error), ([_BASE], None))


class TestTunedTagNaming(unittest.TestCase):
    def test_the_suffix_is_applied_once(self):
        # Both this module and the sweep name the same tag. Suffixing twice would produce
        # a tag Ollama does not have, and the failure would surface three steps later.
        self.assertEqual(vo.tuned_tag_for(_TUNED), _TUNED)
        self.assertEqual(vo.tuned_tag_for(_BASE), _BASE + vo.TUNED_TAG_SUFFIX)


class TestRankingAndSummary(unittest.TestCase):
    def test_the_role_score_outranks_the_overall_score(self):
        matrix = _matrix({
            _OTHER: _row("writer", 8, 10, 20, 20),
            _TUNED: _row("writer", 10, 10, 15, 20),
        })
        order = [r["tag"] for r in tp.rank_rows(matrix, "writer")]
        self.assertEqual(order[0], _TUNED)

    def test_a_not_runnable_row_sorts_last_and_keeps_its_reason(self):
        matrix = _matrix({
            _OTHER: _row("writer", 0, 0, 0, 0, runnable=False, why="no measured window"),
            _TUNED: _row("writer", 5, 10, 5, 20),
        })
        rows = tp.rank_rows(matrix, "writer")
        self.assertEqual(rows[-1]["tag"], _OTHER)
        self.assertEqual(rows[-1]["why"], "no measured window")

    def test_a_candidate_behind_the_incumbent_is_said_to_be_behind(self):
        matrix = _matrix({
            _OTHER: _row("coder", 9, 10, 18, 20),
            _TUNED: _row("coder", 6, 10, 12, 20),
        })
        text = tp.summarize(matrix, _TUNED, "coder", _OTHER)
        self.assertIn("behind", text)
        self.assertIn(_OTHER, text)

    def test_an_unadopted_role_says_so_instead_of_inventing_an_incumbent(self):
        matrix = _matrix({_TUNED: _row("writer", 10, 10, 20, 20)})
        text = tp.summarize(matrix, _TUNED, "writer", None)
        self.assertIn("No tag is currently adopted", text)

    def test_a_candidate_absent_from_the_matrix_is_reported_not_hidden(self):
        matrix = _matrix({_OTHER: _row("writer", 10, 10, 20, 20)})
        text = tp.summarize(matrix, _TUNED, "writer", None)
        self.assertIn("not in the matrix", text)

    def test_the_summary_hands_over_the_adoption_command_and_runs_nothing(self):
        matrix = _matrix({_TUNED: _row("writer", 10, 10, 20, 20)})
        text = tp.summarize(matrix, _TUNED, "writer", None)
        self.assertIn("--qualify", text)
        self.assertIn("decision is yours", text)


class TestCli(unittest.TestCase):
    def test_a_refusal_exits_two_by_design(self):
        with mock.patch.object(tp, "installed_tags", return_value=([_OTHER], None)):
            code = tp.main(["--phase", "tune", "--tag", _BASE])
        self.assertEqual(code, tp.EXIT_REFUSED)

    def test_a_clean_preflight_exits_zero(self):
        with mock.patch.object(tp, "installed_tags", return_value=([_BASE], None)):
            code = tp.main(["--phase", "tune", "--tag", _BASE])
        self.assertEqual(code, tp.EXIT_OK)

    def test_json_output_carries_the_refusals(self):
        import io
        import contextlib
        buffer = io.StringIO()
        with mock.patch.object(tp, "installed_tags", return_value=([_OTHER], None)):
            with contextlib.redirect_stdout(buffer):
                code = tp.main(["--phase", "tune", "--tag", _BASE, "--json"])
        payload = json.loads(buffer.getvalue())
        self.assertEqual(code, tp.EXIT_REFUSED)
        self.assertEqual(payload["tag"], _BASE)
        self.assertTrue(payload["refusals"])

    def test_tuned_tag_is_printed_for_the_harness(self):
        import io
        import contextlib
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = tp.main(["--tuned-tag", "--tag", _BASE])
        self.assertEqual(code, tp.EXIT_OK)
        self.assertEqual(buffer.getvalue().strip(), _TUNED)

    def test_no_verb_at_all_is_a_failure_not_a_silent_success(self):
        self.assertEqual(tp.main([]), tp.EXIT_FAILURE)


class TestHarnessKeepsItsHandsOff(unittest.TestCase):
    """The .ps1 read as text. It exists to stop BEFORE adoption, so the checks are on
    what it must never do, not on what it prints."""

    @classmethod
    def setUpClass(cls):
        cls.text = (_SCRIPTS / "tune-new-model.ps1").read_text(encoding="utf-8")

    def test_it_never_invokes_the_adoption_command(self):
        # --qualify may appear in prose it PRINTS; it must never be handed to the resolver.
        for line in self.text.splitlines():
            if "--qualify" in line and "$Resolver" in line:
                self.fail(f"the harness invokes adoption: {line.strip()}")

    def test_it_never_shells_out_to_ollama_run(self):
        self.assertNotIn("ollama run", self.text)

    def test_it_offers_a_dry_run(self):
        self.assertIn("[switch]$DryRun", self.text)

    # A tag is an argument. Anything looking like a model tag written into the file would
    # be a second truth about which model this machine runs.
    TAG_SHAPE = r"\b[a-z0-9][a-z0-9._-]*:[0-9][a-z0-9._-]*\b"

    def test_it_names_no_model_tag(self):
        import re
        self.assertEqual(re.findall(self.TAG_SHAPE, self.text), [])

    def test_the_tag_check_can_actually_fail(self):
        # Negative control. Without it the check above passes on any file, including one
        # where the pattern was quietly broken, and a hardcoded tag would sail through.
        import re
        planted = self.text + "\n$Tag = 'somefamily:8b'\n"
        self.assertEqual(re.findall(self.TAG_SHAPE, planted), ["somefamily:8b"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
