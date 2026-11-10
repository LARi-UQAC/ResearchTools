"""
Offline tests for the live context of the aider adapter (2026-11-09).

The ring and the meters of an aider run used to show a fixed number: the window
minus the budget the driver leaves for the task, 27K for the whole run. The real
context is the prompt of the last request, which aider prints in its log as
"Tokens: 21k sent, 479 received.". The adapter now reads that line from the
newest logs of a run that is still going. Every fixture is a temporary folder
with invented names, the clock is injected (R19, R21, R34).
"""
import datetime
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "adapters"))
import aider  # noqa: E402

NOW = datetime.datetime(2026, 11, 9, 22, 0, 0)
CAPS = {"aider_log_tail_bytes": 4096, "aider_log_files": 3}


class Context(object):
    def __init__(self, home, caps=CAPS):
        self.home = Path(home)
        self.repo_root = Path(home)
        self.now = NOW
        self.config = {"staleness_seconds": {"session_idle": 900}}
        if caps is not None:
            self.config["caps"] = caps

    @property
    def stamp(self):
        return self.now.isoformat(timespec="seconds")


def make_project(home):
    project = Path(home) / "work" / "demo"
    logs = project / "docs" / "superpowers" / "plans" / ".logs"
    logs.mkdir(parents=True, exist_ok=True)
    return project, logs


def write_record(home, project, **fields):
    runs = Path(home) / ".aider-plan" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    record = {
        "schema": "aider-plan/run-record/1", "run_id": "run1", "pid": os.getpid(),
        "project": str(project), "state": "writing", "plan": "plan2.md",
        "round": 3, "plan_index": 2, "plan_count": 6, "plans_done": 1,
        "steps_done": 4, "steps_open": 5, "steps_blocked": 0, "audit_bytes": 0,
        "window": 65536, "working_set": 38063, "skills": True,
    }
    record.update(fields)
    (runs / "run1.json").write_text(json.dumps(record), encoding="utf-8")


def write_log(logs, name, text, age, encoding="utf-8"):
    path = logs / name
    path.write_bytes(text.encode(encoding))
    stamp = NOW.timestamp() - age
    os.utime(path, (stamp, stamp))
    return path


def tokens_of(home, caps=CAPS):
    result = aider.collect(Context(home, caps))
    return result["sessions"][0]["flow"]["tokens"], result["sessions"][0]


class SentTokens(unittest.TestCase):

    def test_the_decimal_k_and_a_plain_number_are_parsed(self):
        self.assertEqual(4100, aider._sent_tokens("Tokens: 4.1k sent, 1.2k received."))
        self.assertEqual(21000, aider._sent_tokens("Tokens: 21k sent, 479 received."))
        self.assertEqual(479, aider._sent_tokens("Tokens: 479 sent, 12 received."))

    def test_the_last_request_wins_and_no_line_gives_none(self):
        text = "Tokens: 3k sent, 1 received.\nsomething\nTokens: 9k sent, 2 received.\n"
        self.assertEqual(9000, aider._sent_tokens(text))
        self.assertIsNone(aider._sent_tokens("no request here"))


class LiveContext(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name
        self.project, self.logs = make_project(self.home)

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_live_context_is_the_last_request_of_the_newest_log(self):
        write_record(self.home, self.project)
        write_log(self.logs, "a-plan1.log", "Tokens: 5k sent, 1 received.\n", age=600)
        write_log(self.logs, "b-plan1.log",
                  "Tokens: 12k sent, 1 received.\nTokens: 14k sent, 2 received.\n", age=10)
        tokens, _ = tokens_of(self.home)
        self.assertEqual(14000, tokens["live_context"])
        self.assertEqual(14000, tokens["held"])
        self.assertEqual(round(100.0 * 14000 / 65536, 1), tokens["percent"])
        self.assertEqual(65536 - 38063, tokens["fixed_cost"])
        self.assertNotIn("live_reason", tokens)

    def test_a_utf16_log_is_read_like_powershell_writes_it(self):
        write_record(self.home, self.project)
        text = "x" * 3000 + "\nTokens: 28k sent, 775 received.\n"
        write_log(self.logs, "w-plan1.log", text, age=5, encoding="utf-16")
        tokens, _ = tokens_of(self.home, caps={"aider_log_tail_bytes": 1001,
                                               "aider_log_files": 3})
        self.assertEqual(28000, tokens["live_context"])

    def test_a_newest_log_with_no_request_falls_back_to_an_older_one(self):
        write_record(self.home, self.project)
        write_log(self.logs, "w-plan1.log", "Tokens: 11k sent, 1 received.\n", age=300)
        write_log(self.logs, "w-plan1-tests.log", "Ran 4 tests\nOK\n", age=2)
        tokens, _ = tokens_of(self.home)
        self.assertEqual(11000, tokens["live_context"])

    def test_no_logs_keeps_the_fixed_cost_and_says_why(self):
        write_record(self.home, self.project)
        tokens, _ = tokens_of(self.home)
        self.assertNotIn("live_context", tokens)
        self.assertEqual(65536 - 38063, tokens["held"])
        self.assertEqual("no request has been logged yet", tokens["live_reason"])

    def test_a_project_with_no_log_folder_is_not_an_error(self):
        write_record(self.home, Path(self.home) / "work" / "missing")
        tokens, _ = tokens_of(self.home)
        self.assertEqual(65536 - 38063, tokens["held"])
        self.assertIn("live_reason", tokens)

    def test_a_finished_run_is_not_read(self):
        write_record(self.home, self.project, state="done")
        write_log(self.logs, "w-plan1.log", "Tokens: 12k sent, 1 received.\n", age=5)
        tokens, _ = tokens_of(self.home)
        self.assertNotIn("live_context", tokens)
        self.assertNotIn("live_reason", tokens)

    def test_wrapped_caps_are_read_as_observe_config_writes_them(self):
        write_record(self.home, self.project)
        write_log(self.logs, "w-plan1.log", "Tokens: 7k sent, 1 received.\n", age=5)
        wrapped = {"aider_log_tail_bytes": {"value": 4096, "unit": "bytes", "provenance": "t"},
                   "aider_log_files": {"value": 3, "unit": "files", "provenance": "t"}}
        tokens, _ = tokens_of(self.home, caps=wrapped)
        self.assertEqual(7000, tokens["live_context"])

    def test_missing_caps_are_named_and_the_fixed_cost_stays(self):
        write_record(self.home, self.project)
        write_log(self.logs, "w-plan1.log", "Tokens: 7k sent, 1 received.\n", age=5)
        tokens, _ = tokens_of(self.home, caps=None)
        self.assertNotIn("live_context", tokens)
        self.assertIn("aider_log_tail_bytes", tokens["live_reason"])

    def test_the_reason_never_carries_a_path(self):
        write_record(self.home, self.project)
        tokens, _ = tokens_of(self.home)
        self.assertNotIn(self.home, json.dumps(tokens))

    def test_plan_index_and_round_reach_the_page(self):
        write_record(self.home, self.project)
        _, session = tokens_of(self.home)
        self.assertEqual(2, session["progress"]["plan_index"])
        self.assertEqual(3, session["progress"]["round"])


if __name__ == "__main__":
    unittest.main()
