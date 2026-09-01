"""
test_askuserquestion_clarity - the PreToolUse gate on AskUserQuestion (R25).

Offline. No network, no API key, no model load. Every case runs the REAL hook as a
subprocess, against a COPY of it in a temporary directory, so the exit code and the stderr a
blocked call would actually produce are what is asserted rather than the return value of an
imported function. The copy is what makes the R11 cases possible at all: the hook reads its
thresholds from a file beside itself, so "the config is missing" can only be staged by moving
the script somewhere the config is not.

R21: no threshold is read from the machine. Every behavioural case injects its own fixture
config. The one case that reads the SHIPPED askuserquestion-clarity.json asserts only that it
parses and that it declares the keys the hook consults - a key renamed on one side and not the
other would silently switch a check off, and that is the defect this repo has hit before with
settings entries whose script had moved.

R20: the failure paths are the point. A gate that cannot refuse is not a gate, and a gate that
refuses when its own config is absent is the 2026-08-27 vault-access-guard failure again - a
declared hook whose dependency was missing refused every tool in its matcher for four turns.
Both directions are asserted here.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
HOOK = REPO / ".claude" / "hooks" / "askuserquestion-clarity.py"
SHIPPED_CONFIG = REPO / ".claude" / "hooks" / "askuserquestion-clarity.json"

CONFIG_NAME = "askuserquestion-clarity.json"
MARKER = "(Recommended)"

# The fixture thresholds. Deliberately NOT read from the shipped file: a suite that read it
# would change verdict whenever the professor retuned the gate, which is exactly what R21
# forbids for machine-local numbers and is bad practice for shipped ones too.
FIXTURE_CONFIG = {
    "enabled": True,
    "min_question_chars": 60,
    "min_description_chars": 40,
    "min_description_gain_chars": 25,
    "require_question_mark": True,
    "require_recommended_marker": True,
    "require_recommended_first": True,
    "recommended_marker": MARKER,
}

# A question that satisfies every check, used as the baseline the negative cases mutate.
GOOD_QUESTION = {
    "question": ("rt-sync.ps1:288 propagates hooks with -Filter *.py, so a JSON config beside "
                 "a hook never reaches ~/.claude/hooks. Where should the thresholds live?"),
    "header": "Thresholds",
    "multiSelect": False,
    "options": [
        {"label": "Config file plus a widened filter " + MARKER,
         "description": ("Ship the numbers in a JSON beside the hook and widen the sync filter "
                         "to carry *.json. Costs an edit to the propagation engine, so it needs "
                         "a new case in verify-sync-writes.ps1.")},
        {"label": "Constants in the .py",
         "description": ("Module-level constants carrying provenance comments. No installer "
                         "change, but it grants an explicit R0 exception and a student must "
                         "edit Python to retune the gate.")},
    ],
}


def run_hook(payload, config=FIXTURE_CONFIG, write_config=True, raw_config=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Run the real hook against a copy of itself in a temporary directory,
        with the config staged beside it (or deliberately absent).

    Inputs:
        payload (dict): the PreToolUse stdin payload
        config (dict): thresholds written next to the copied hook
        write_config (bool): False stages NO config file, for the R11 case
        raw_config (str): raw text to write instead of JSON, for the
                          unparsable-config case

    Outputs:
        result (tuple): (returncode int, stderr str)
    --------------------------------------------------------------------------
    """
    with tempfile.TemporaryDirectory() as tmp:
        copied = Path(tmp) / HOOK.name
        shutil.copy2(HOOK, copied)
        if raw_config is not None:
            (Path(tmp) / CONFIG_NAME).write_text(raw_config, encoding="utf-8")
        elif write_config:
            (Path(tmp) / CONFIG_NAME).write_text(json.dumps(config), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(copied)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=30,          # generous: this only starts an interpreter
        )
        return completed.returncode, completed.stderr


def ask(questions):
    """Wrap question objects in the payload shape measured from the live hook."""
    return {"hook_event_name": "PreToolUse",
            "tool_name": "AskUserQuestion",
            "tool_input": {"questions": questions}}


def mutate(**changes):
    """A copy of GOOD_QUESTION with the named keys replaced."""
    question = json.loads(json.dumps(GOOD_QUESTION))
    question.update(changes)
    return question


class TestCleanQuestionPasses(unittest.TestCase):
    def test_a_well_formed_question_is_not_blocked(self):
        code, err = run_hook(ask([GOOD_QUESTION]))
        self.assertEqual(code, 0, "a compliant question was refused; stderr:\n" + err)
        self.assertEqual(err.strip(), "", "a passing call must say nothing at all")

    def test_two_clean_questions_in_one_call_pass(self):
        code, _ = run_hook(ask([GOOD_QUESTION, GOOD_QUESTION]))
        self.assertEqual(code, 0)


class TestOptionDescriptions(unittest.TestCase):
    def test_missing_description_is_refused(self):
        broken = mutate(options=[
            {"label": "Config file " + MARKER, "description": ""},
            {"label": "Constants in the .py", "description": "x" * 60},
        ])
        code, err = run_hook(ask([broken]))
        self.assertEqual(code, 2)
        self.assertIn("carries no description", err)
        self.assertIn("Config file", err, "the failing option must be named")

    def test_absent_description_key_is_refused(self):
        broken = mutate(options=[
            {"label": "Config file " + MARKER},
            {"label": "Constants in the .py", "description": "x" * 60},
        ])
        code, err = run_hook(ask([broken]))
        self.assertEqual(code, 2)
        self.assertIn("carries no description", err)

    def test_short_description_is_refused(self):
        broken = mutate(options=[
            {"label": "Config file " + MARKER, "description": "Use a config file."},
            {"label": "Constants in the .py", "description": "y" * 60},
        ])
        code, err = run_hook(ask([broken]))
        self.assertEqual(code, 2)
        self.assertIn("under the 40", err)

    def test_description_restating_its_label_is_refused(self):
        # Long enough to clear min_description_chars, and still says nothing: this is the
        # case a pure length floor would wave through. The recommended option carries it on
        # purpose - the marker used to be part of the normalized label, which made this
        # check unable to fire on exactly this option.
        broken = mutate(options=[
            {"label": "Strict mode " + MARKER,
             "description": "Strict mode. Runs in strict mode, the strict one."},
            {"label": "Lenient mode", "description": "z" * 60},
        ])
        code, err = run_hook(ask([broken]))
        self.assertEqual(code, 2)
        self.assertIn("restates its label", err)

    def test_a_description_that_merely_contains_the_label_still_passes(self):
        # Negative control for the restatement check: naming the label and then explaining
        # it is normal and must NOT be refused, or the check is just banning a word.
        ok = mutate(options=[
            {"label": "Config file " + MARKER,
             "description": ("Config file beside the hook, widening the sync filter to carry "
                             "*.json. Costs a change to the propagation engine.")},
            {"label": "Constants in the .py", "description": "z" * 60},
        ])
        code, err = run_hook(ask([ok]))
        self.assertEqual(code, 0, "a label named then explained was wrongly refused:\n" + err)


class TestQuestionText(unittest.TestCase):
    def test_short_question_is_refused(self):
        code, err = run_hook(ask([mutate(question="Which one?")]))
        self.assertEqual(code, 2)
        self.assertIn("origin of the choice", err)

    def test_missing_question_mark_is_refused(self):
        text = ("rt-sync.ps1:288 filters hooks with -Filter *.py, so decide where the "
                "thresholds should live before the gate ships.")
        code, err = run_hook(ask([mutate(question=text)]))
        self.assertEqual(code, 2)
        self.assertIn("does not end in '?'", err)


class TestRecommendation(unittest.TestCase):
    def test_no_recommended_option_is_refused(self):
        broken = mutate(options=[
            {"label": "Config file", "description": "a" * 60},
            {"label": "Constants in the .py", "description": "b" * 60},
        ])
        code, err = run_hook(ask([broken]))
        self.assertEqual(code, 2)
        self.assertIn("No option is marked", err)

    def test_two_recommended_options_are_refused(self):
        broken = mutate(options=[
            {"label": "Config file " + MARKER, "description": "a" * 60},
            {"label": "Constants " + MARKER, "description": "b" * 60},
        ])
        code, err = run_hook(ask([broken]))
        self.assertEqual(code, 2)
        self.assertIn("2 options are marked", err)

    def test_recommended_option_not_first_is_refused(self):
        broken = mutate(options=[
            {"label": "Constants in the .py", "description": "a" * 60},
            {"label": "Config file " + MARKER, "description": "b" * 60},
        ])
        code, err = run_hook(ask([broken]))
        self.assertEqual(code, 2)
        self.assertIn("not first", err)


class TestEveryProblemIsReportedAtOnce(unittest.TestCase):
    def test_a_question_failing_three_ways_names_all_three(self):
        # A rewrite loop that fixed one fault per round would cost the user three
        # round-trips for one bad question.
        broken = {
            "question": "Which?",
            "header": "Vague",
            "options": [
                {"label": "A", "description": ""},
                {"label": "B", "description": ""},
            ],
        }
        code, err = run_hook(ask([broken]))
        self.assertEqual(code, 2)
        self.assertIn("origin of the choice", err)
        self.assertIn("carries no description", err)
        self.assertIn("No option is marked", err)
        self.assertEqual(err.count("carries no description"), 2,
                         "both undescribed options must be named, not just the first")

    def test_the_second_question_of_a_call_is_judged_too(self):
        code, err = run_hook(ask([GOOD_QUESTION, mutate(question="Which one?")]))
        self.assertEqual(code, 2)
        self.assertIn("origin of the choice", err)


class TestTheGateNeverGetsInTheWay(unittest.TestCase):
    """R11 and R12: everything this hook cannot judge, it lets through in silence."""

    def test_another_tool_is_untouched(self):
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                   "tool_input": {"command": "echo hi"}}
        code, err = run_hook(payload)
        self.assertEqual(code, 0)
        self.assertEqual(err.strip(), "")

    def test_unparsable_stdin_never_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            copied = Path(tmp) / HOOK.name
            shutil.copy2(HOOK, copied)
            (Path(tmp) / CONFIG_NAME).write_text(json.dumps(FIXTURE_CONFIG), encoding="utf-8")
            done = subprocess.run([sys.executable, str(copied)], input="not json at all",
                                  capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0)

    def test_empty_stdin_never_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            copied = Path(tmp) / HOOK.name
            shutil.copy2(HOOK, copied)
            done = subprocess.run([sys.executable, str(copied)], input="",
                                  capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0)

    def test_missing_questions_key_never_blocks(self):
        payload = {"hook_event_name": "PreToolUse", "tool_name": "AskUserQuestion",
                   "tool_input": {}}
        code, _ = run_hook(payload)
        self.assertEqual(code, 0)

    def test_a_missing_config_disables_the_gate_in_silence(self):
        # THE R11 CASE. Measured 2026-08-27: vault-access-guard.py was declared in
        # settings.json and absent from disk, the interpreter returned non-zero, and Read,
        # Grep and Bash were refused for four turns. A gate that refuses when its own
        # dependency is gone is worse than no gate.
        code, err = run_hook(ask([mutate(question="Which one?")]), write_config=False)
        self.assertEqual(code, 0, "a missing config must disable the gate, not refuse")
        self.assertEqual(err.strip(), "", "and it must say nothing while doing so")

    def test_an_unparsable_config_disables_the_gate_in_silence(self):
        code, err = run_hook(ask([mutate(question="Which one?")]), raw_config="{ broken json")
        self.assertEqual(code, 0)
        self.assertEqual(err.strip(), "")

    def test_enabled_false_disables_the_gate(self):
        off = dict(FIXTURE_CONFIG, enabled=False)
        code, err = run_hook(ask([mutate(question="Which one?")]), config=off)
        self.assertEqual(code, 0)
        self.assertEqual(err.strip(), "")

    def test_the_only_non_zero_code_this_hook_emits_is_two(self):
        # R12: 0 is clean, 2 is refusal by design, and nothing else is allowed to escape,
        # because a caller branches on exactly those two.
        for payload in (ask([GOOD_QUESTION]),
                        ask([mutate(question="Which one?")]),
                        {"tool_name": "Bash", "tool_input": {"command": "ls"}},
                        {"tool_name": "AskUserQuestion", "tool_input": {"questions": "nope"}}):
            code, _ = run_hook(payload)
            self.assertIn(code, (0, 2), "unexpected exit code {c}".format(c=code))


class TestTheShippedConfig(unittest.TestCase):
    """The repository's own config file, not a machine's. Its keys are the hook's contract."""

    def test_the_shipped_config_parses(self):
        self.assertTrue(SHIPPED_CONFIG.is_file(),
                        "the gate ships disabled if its config is not in the repository")
        json.loads(SHIPPED_CONFIG.read_text(encoding="utf-8-sig"))

    def test_the_shipped_config_declares_every_key_the_hook_reads(self):
        # A key renamed on one side only would switch a check off with nothing failing.
        config = json.loads(SHIPPED_CONFIG.read_text(encoding="utf-8-sig"))
        for key in ("enabled", "min_question_chars", "min_description_chars",
                    "min_description_gain_chars", "require_question_mark",
                    "require_recommended_marker", "require_recommended_first",
                    "recommended_marker"):
            with self.subTest(key=key):
                self.assertIn(key, config)

    def test_the_shipped_config_actually_gates(self):
        # The negative control for the whole file: a config whose thresholds were all zero
        # would parse, declare every key, and refuse nothing.
        config = json.loads(SHIPPED_CONFIG.read_text(encoding="utf-8-sig"))
        code, _ = run_hook(ask([{"question": "Which?", "header": "H",
                                 "options": [{"label": "A", "description": ""},
                                             {"label": "B", "description": ""}]}]),
                           config=config)
        self.assertEqual(code, 2, "the shipped thresholds refuse nothing")

    def test_the_hook_is_where_the_settings_template_says_it_is(self):
        # R14: the template names a path; if the two drift, the hook is declared and absent,
        # which is the failure mode this whole suite exists to prevent.
        self.assertTrue(HOOK.is_file())
        template = json.loads(
            (REPO / ".claude" / "settings.template.json").read_text(encoding="utf-8-sig"))
        commands = [hook.get("command", "")
                    for entries in template.get("hooks", {}).values()
                    for entry in entries
                    for hook in entry.get("hooks", [])]
        self.assertTrue(any(HOOK.name in command for command in commands),
                        HOOK.name + " is not declared in settings.template.json")


if __name__ == "__main__":
    unittest.main(verbosity=2)
