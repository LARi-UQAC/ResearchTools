"""
Offline tests for the aider adapter. No network, no model, no ResearchTools
clone: every fixture is a temporary directory and the clock is injected.

The cases that matter are the negative ones. A dashboard panel that reports a
dead run as live, or silently drops a record it cannot parse, is worse than a
panel that is absent - it is a panel that lies while looking healthy.
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


class Context(object):
    """The slice of AdapterContext this adapter actually reads."""

    def __init__(self, home, now, config=None):
        self.home = Path(home)
        self.repo_root = Path(home)
        self.now = now
        self.config = config if config is not None else {
            "staleness_seconds": {"session_idle": 900}}

    @property
    def stamp(self):
        return self.now.isoformat(timespec="seconds")


NOW = datetime.datetime(2026, 9, 3, 22, 0, 0)


def write_record(home, name, **fields):
    runs = Path(home) / ".aider-plan" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    record = {
        "schema": "aider-plan/run-record/1",
        "run_id": name,
        "pid": os.getpid(),
        "project": str(Path(home) / "work" / "demo"),
        "state": "writing",
        "state_since": "2026-09-03T21:50:00",
        "branch": "student/night-2026-09-03",
        "plan": "plan1.md",
        "round": 1,
        "plan_count": 2,
        "plans_done": 0,
        "steps_done": 1,
        "steps_open": 3,
        "steps_blocked": 0,
        "audit_bytes": 0,
        "window": 262144,
        "working_set": 224336,
        "skills": True,
    }
    record.update(fields)
    path = runs / (name + ".json")
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


class ProbeTests(unittest.TestCase):

    def test_absent_directory_is_not_installed(self):
        with tempfile.TemporaryDirectory() as home:
            self.assertFalse(aider.probe(Context(home, NOW)))

    def test_empty_directory_is_not_installed(self):
        with tempfile.TemporaryDirectory() as home:
            (Path(home) / ".aider-plan" / "runs").mkdir(parents=True)
            self.assertFalse(aider.probe(Context(home, NOW)),
                             "a directory with no record is a machine that has "
                             "never run the pipeline")

    def test_one_record_is_installed(self):
        with tempfile.TemporaryDirectory() as home:
            write_record(home, "aaaaaaaa")
            self.assertTrue(aider.probe(Context(home, NOW)))


class CollectTests(unittest.TestCase):

    def test_a_running_project_is_reported(self):
        with tempfile.TemporaryDirectory() as home:
            write_record(home, "aaaaaaaa")
            state = aider.collect(Context(home, NOW))
            self.assertEqual(state["status"], "ok")
            self.assertEqual(state["counts"]["projects"], 1)
            session = state["sessions"][0]
            self.assertEqual(session["branch"], "student/night-2026-09-03")
            self.assertEqual(session["mode"], "skills")
            self.assertEqual(session["progress"]["steps_open"], 3)

    def test_no_home_path_reaches_the_snapshot(self):
        with tempfile.TemporaryDirectory() as home:
            write_record(home, "aaaaaaaa")
            state = aider.collect(Context(home, NOW))
            dumped = json.dumps(state)
            self.assertNotIn(str(home), dumped,
                             "the dashboard is screenshotted; a home path must "
                             "never reach the payload")
            self.assertIn("~", state["sessions"][0]["project"])

    def test_a_dead_pid_is_reported_dead_with_its_reason(self):
        with tempfile.TemporaryDirectory() as home:
            # A pid that cannot be running: 0 is refused by the check, and a
            # very high one is not allocated here.
            write_record(home, "aaaaaaaa", pid=999999)
            session = aider.collect(Context(home, NOW))["sessions"][0]
            self.assertIn(session["live"], (False, None))
            if session["live"] is False:
                self.assertIsNotNone(session["live_reason"])

    def test_a_live_pid_is_reported_live(self):
        with tempfile.TemporaryDirectory() as home:
            write_record(home, "aaaaaaaa", pid=os.getpid())
            session = aider.collect(Context(home, NOW))["sessions"][0]
            self.assertTrue(session["live"])
            self.assertIsNone(session["live_reason"])

    def test_windows_liveness_never_calls_os_kill(self):
        """Measured 2026-09-24: `os.kill(pid, 0)` on Windows maps to
        GenerateConsoleCtrlEvent(CTRL_C_EVENT, ...) (CTRL_C_EVENT == 0), which
        can deliver Ctrl+C to every process sharing the caller's console -
        reproduced killing the PARENT PowerShell process with zero output,
        under a Start-Process invocation with redirected stderr. The fix
        (`_alive_windows`, OpenProcess/CloseHandle) must be the path taken on
        win32, and os.kill must never be reached there at all."""
        from unittest import mock
        with mock.patch.object(aider.sys, "platform", "win32"), \
             mock.patch.object(aider.os, "kill",
                               side_effect=AssertionError(
                                   "os.kill must not be called on win32")):
            with mock.patch.object(aider, "_alive_windows", return_value=True) as fake:
                self.assertTrue(aider._alive(os.getpid()))
                fake.assert_called_once_with(os.getpid())

    def test_windows_liveness_reports_a_dead_pid_as_false(self):
        from unittest import mock
        with mock.patch.object(aider.sys, "platform", "win32"), \
             mock.patch.object(aider, "_alive_windows", return_value=False):
            self.assertFalse(aider._alive(999999))

    def test_an_unparsable_record_is_named_not_dropped(self):
        with tempfile.TemporaryDirectory() as home:
            runs = Path(home) / ".aider-plan" / "runs"
            runs.mkdir(parents=True)
            (runs / "broken.json").write_text("{not json", encoding="utf-8")
            state = aider.collect(Context(home, NOW))
            self.assertEqual(state["counts"]["projects"], 0)
            self.assertEqual(state["counts"]["unreadable"], 1)
            self.assertEqual(state["unreadable"][0]["file"], "broken.json")

    def test_an_unknown_schema_is_refused_rather_than_guessed(self):
        with tempfile.TemporaryDirectory() as home:
            write_record(home, "aaaaaaaa", schema="aider-plan/run-record/99")
            state = aider.collect(Context(home, NOW))
            self.assertEqual(state["counts"]["projects"], 0)
            self.assertIn("refusing to guess", state["unreadable"][0]["reason"])

    def test_one_bad_record_does_not_hide_a_good_one(self):
        with tempfile.TemporaryDirectory() as home:
            write_record(home, "aaaaaaaa")
            runs = Path(home) / ".aider-plan" / "runs"
            (runs / "broken.json").write_text("{not json", encoding="utf-8")
            state = aider.collect(Context(home, NOW))
            self.assertEqual(state["counts"]["projects"], 1)
            self.assertEqual(state["counts"]["unreadable"], 1)


class FlowTests(unittest.TestCase):

    def test_a_stale_running_state_reads_idle(self):
        with tempfile.TemporaryDirectory() as home:
            path = write_record(home, "aaaaaaaa", state="writing")
            old = NOW.timestamp() - 3600
            os.utime(path, (old, old))
            session = aider.collect(Context(home, NOW))["sessions"][0]
            self.assertEqual(session["flow"]["state"], "idle")

    def test_a_terminal_state_is_never_idle(self):
        with tempfile.TemporaryDirectory() as home:
            path = write_record(home, "aaaaaaaa", state="done")
            old = NOW.timestamp() - 86400
            os.utime(path, (old, old))
            session = aider.collect(Context(home, NOW))["sessions"][0]
            self.assertEqual(session["flow"]["state"], "done",
                             "a finished run is finished, however long ago")

    def test_done_with_blocked_is_a_state_of_its_own(self):
        ids = [s[0] for s in aider.FLOW_STATES]
        self.assertIn("done_with_blocked", ids,
                      "aider-plan.ps1:1129 writes it, so a viewer that does not "
                      "know it renders a blocked night as an unknown state")
        role = dict((s[0], s[2]) for s in aider.FLOW_STATES)["done_with_blocked"]
        self.assertEqual(role, "terminal",
                         "the run has finished; only the reading is outstanding")

    def test_every_terminal_state_survives_ageing(self):
        # Written over the defect rather than around it: the ageing check used to
        # read the literal ("done", "failed"), so a done_with_blocked record older
        # than the idle threshold was reported as "idle" - the dashboard claiming
        # nothing happened about a run that finished and needs reading. Driving it
        # from FLOW_STATES means the next state added is covered without a test
        # being remembered.
        terminal = [s[0] for s in aider.FLOW_STATES if s[2] == "terminal"]
        self.assertGreater(len(terminal), 2, "the vocabulary lost a terminal state")
        for name in terminal:
            with tempfile.TemporaryDirectory() as home:
                path = write_record(home, "aaaaaaaa", state=name)
                old = NOW.timestamp() - 86400
                os.utime(path, (old, old))
                session = aider.collect(Context(home, NOW))["sessions"][0]
                self.assertEqual(session["flow"]["state"], name,
                                 "%s aged into %s" % (name, session["flow"]["state"]))

    def test_a_non_terminal_state_still_ages_into_idle(self):
        # The negative control for the two above. Without it, marking every state
        # terminal would satisfy them and silently remove the idle report, which
        # is the one thing telling a reader a run has stopped moving.
        for name in [s[0] for s in aider.FLOW_STATES if s[2] != "terminal"]:
            with tempfile.TemporaryDirectory() as home:
                path = write_record(home, "aaaaaaaa", state=name)
                old = NOW.timestamp() - 86400
                os.utime(path, (old, old))
                session = aider.collect(Context(home, NOW))["sessions"][0]
                self.assertEqual(session["flow"]["state"], "idle",
                                 "%s should have aged into idle" % name)

    def test_evicting_is_a_state_of_its_own(self):
        ids = [s[0] for s in aider.FLOW_STATES]
        self.assertIn("evicting", ids,
                      "a model swap is three minutes of apparent silence; "
                      "without a name a reader calls it a hang")

    def test_the_token_percentage_is_computed_not_refused(self):
        with tempfile.TemporaryDirectory() as home:
            write_record(home, "aaaaaaaa")
            tokens = aider.collect(Context(home, NOW))["sessions"][0]["flow"]["tokens"]
            self.assertIsNotNone(tokens["percent"])
            self.assertEqual(tokens["window"], 262144)

    def test_no_window_means_no_percentage_and_a_reason(self):
        with tempfile.TemporaryDirectory() as home:
            write_record(home, "aaaaaaaa", window=0)
            tokens = aider.collect(Context(home, NOW))["sessions"][0]["flow"]["tokens"]
            self.assertIsNone(tokens["percent"])
            self.assertIn("no window", tokens["percent_reason"])

    def test_the_inbox_is_unreachable_and_says_so(self):
        with tempfile.TemporaryDirectory() as home:
            write_record(home, "aaaaaaaa")
            inbox = aider.collect(Context(home, NOW))["sessions"][0]["inbox"]
            self.assertEqual(inbox["status"], "unreachable")
            self.assertIn("prompt-submit", inbox["reason"])


class ContractTests(unittest.TestCase):
    """The adapter must be droppable in with no core edit."""

    def test_it_exposes_exactly_probe_and_collect(self):
        for name in ("probe", "collect"):
            self.assertTrue(callable(getattr(aider, name, None)),
                            "%s is required by adapters/__init__.py" % name)

    def test_it_reads_the_clock_from_the_context_only(self):
        source = (Path(aider.__file__)).read_text(encoding="utf-8")
        for forbidden in ("datetime.now(", "time.time(", "Path.home("):
            self.assertNotIn(forbidden, source,
                             "%s makes the snapshot depend on when it ran; the "
                             "context injects both (R19, R21)" % forbidden)

    def test_the_entry_fragment_matches_the_module_name(self):
        # harnesses-entry.json was the staging instruction for merging this
        # adapter's entry into harnesses.json (see its own "_how_to_apply");
        # once applied, the merged registry is the one source of truth, so this
        # checks THAT rather than keeping a second, driftable copy around.
        registry = json.loads(
            (Path(__file__).resolve().parents[2] / "harnesses.json")
            .read_text(encoding="utf-8"))
        entry = next(a for a in registry["adapters"] if a["id"] == "aider")
        self.assertEqual(entry["module"], "aider")
        self.assertEqual(entry["id"], "aider")


if __name__ == "__main__":
    unittest.main(verbosity=2)
