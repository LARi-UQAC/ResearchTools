"""
Offline tests for rt_actions - the dashboard's write half.

Nothing here spawns a process, opens a socket or touches the real home: the
PATH lookup, the subprocess, the clock, the id and the section collector are all
injected, and every path is a tempfile tree (R19, R21).

The refusals are the product. An action that cannot run here is reported
unavailable with its reason rather than offered as a button that fails on click;
an id that is not on the whitelist cannot run at all; a destructive id without an
explicit confirm is refused; and - the case R9 exists for - an action that exits
0 while the effect it claims did not happen is reported FAILED, because
restart-ollama.ps1 is the documented script that exits 0 while an orphaned child
keeps its VRAM.
"""
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import rt_actions  # noqa: E402

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
SKILL_ROOT = SCRIPTS.parent


def fake_catalog():
    """A catalogue with one of each shape, so a case never depends on which
    actions the shipped file happens to declare."""
    return {
        "version": 1,
        "argv_tokens": {"binaries": {"powershell": ["pwsh", "powershell"],
                                     "claude": ["claude"]}},
        "actions": [
            {"id": "safe.read", "label": "Read something",
             "what": "read-only", "argv": ["{powershell}", "-File",
                                           "{repo_root}/tool.ps1"],
             "destructive": False, "confirm": None, "verify": None},
            {"id": "danger.write", "label": "Write something",
             "what": "destructive", "argv": ["{powershell}", "-File",
                                             "{repo_root}/tool.ps1", "-Go"],
             "destructive": True, "confirm": "This rewrites things. Run it?",
             "verify": "mirrors_no_lost"},
            {"id": "profiled", "label": "Uses the profile", "what": "profile",
             "argv": ["{powershell}", "-File", "{repo_root}/tool.ps1",
                      "-Profile", "{profile}"],
             "destructive": False, "confirm": None, "verify": None},
            {"id": "bad.token", "label": "Unknown token", "what": "bad",
             "argv": ["{powershell}", "-File", "{repo_root}/tool.ps1",
                      "{whatever}"],
             "destructive": False, "confirm": None, "verify": None},
            {"id": "bad.binary.position", "label": "Binary not first",
             "what": "bad", "argv": ["{powershell}", "{claude}"],
             "destructive": False, "confirm": None, "verify": None},
            {"id": "inbox.send", "label": "Send", "what": "inbox",
             "kind": "inbox", "destructive": False, "confirm": None,
             "verify": None},
        ],
    }


class Base(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.repo = root / "repo"
        self.home = root / "home"
        (self.repo).mkdir(parents=True)
        (self.home / ".claude").mkdir(parents=True)
        with io.open(self.repo / "tool.ps1", "w") as handle:
            handle.write("# a script that exists\n")
        self.spawned = []
        self.addCleanup(self.tmp.cleanup)

    def values(self):
        return {"timeout_s": 30, "action_log": "~/.claude/rt-actions.jsonl",
                "inbox_root": "~/.claude/rt-inbox", "message_chars": 100,
                "output_tail_chars": 40}

    def runner(self, exit_code=0, stdout="done", stderr="", section=None,
               which=None, raises=None, catalog=None):
        def fake_run(argv, **kwargs):
            self.spawned.append((argv, kwargs))
            if raises is not None:
                raise raises
            return mock.Mock(returncode=exit_code, stdout=stdout, stderr=stderr)

        def fake_which(name):
            if which is None:
                return "C:/fake/%s.CMD" % name
            return which(name)

        return rt_actions.Runner(
            self.repo, self.home, self.values(),
            catalog=catalog or fake_catalog(),
            section_fn=(lambda name: section) if section is not None else None,
            which=fake_which, run=fake_run, clock=lambda: NOW,
            ident=lambda: "abc123", profile_fn=lambda: "engineering")

    def log_lines(self):
        path = self.home / ".claude" / "rt-actions.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in
                io.open(path, encoding="utf-8").read().splitlines() if line]


class Whitelist(Base):

    def test_an_id_that_is_not_on_the_whitelist_cannot_run(self):
        result = self.runner().run({"id": "rm -rf /", "confirm": True})
        self.assertEqual("refused", result["status"])
        self.assertEqual(404, result["http_status"])
        self.assertEqual([], self.spawned)

    def test_no_field_of_the_request_can_reach_argv(self):
        """The whole reason the catalogue holds a FIXED argv. Every extra key
        here is a field an attacker would try; none of them may appear in what
        is spawned."""
        runner = self.runner()
        runner.run({"id": "safe.read", "confirm": True,
                    "argv": ["calc.exe"], "args": "; shutdown /s",
                    "cmd": "whoami", "target": "../../etc",
                    "text": "$(whoami)", "profile": "evil"})
        argv, kwargs = self.spawned[0]
        flat = " ".join(argv)
        for poison in ("calc.exe", "shutdown", "whoami", "evil", "etc"):
            self.assertNotIn(poison, flat, argv)
        self.assertEqual(str(self.repo), kwargs["cwd"])
        self.assertFalse(kwargs.get("shell", False))

    def test_a_destructive_action_without_confirm_is_refused(self):
        result = self.runner().run({"id": "danger.write"})
        self.assertEqual("refused", result["status"])
        self.assertEqual(409, result["http_status"])
        self.assertIn("rewrites things", result["reason"])
        self.assertTrue(result["needs_confirm"])
        self.assertEqual([], self.spawned)

    def test_a_confirm_that_is_merely_truthy_is_not_a_confirm(self):
        """`confirm: "no"` and `confirm: 1` are both truthy in JavaScript and
        in Python, and neither is a person pressing a second button."""
        for value in ("no", 1, "false", [], {}):
            with self.subTest(confirm=value):
                result = self.runner().run({"id": "danger.write",
                                            "confirm": value})
                self.assertEqual("refused", result["status"])
        self.assertEqual([], self.spawned)

    def test_dry_run_resolves_the_argv_and_spawns_nothing(self):
        result = self.runner().run({"id": "danger.write", "dry_run": True})
        self.assertEqual("ok", result["status"])
        self.assertTrue(result["dry_run"])
        self.assertIn("-Go", result["argv"])
        self.assertEqual([], self.spawned)

    def test_a_dry_run_of_a_destructive_action_needs_no_confirm(self):
        """Printing what WOULD happen is how a person decides whether to
        confirm, so requiring the confirm first would invert the order (R16)."""
        result = self.runner().run({"id": "danger.write", "dry_run": True})
        self.assertEqual("ok", result["status"])
        self.assertEqual([], self.spawned)


class Availability(Base):

    def test_with_no_powershell_every_ps1_action_is_unavailable_with_a_reason(self):
        runner = self.runner(which=lambda name: None)
        entries = {e["id"]: e for e in runner.catalogue()}
        for action_id in ("safe.read", "danger.write", "profiled"):
            with self.subTest(action=action_id):
                self.assertFalse(entries[action_id]["available"])
                self.assertIn("on PATH", entries[action_id]["reason"])
        result = runner.run({"id": "safe.read"})
        self.assertEqual("unavailable", result["status"])
        self.assertEqual(503, result["http_status"])
        self.assertEqual([], self.spawned)

    def test_the_inbox_action_stays_available_with_no_interpreter_at_all(self):
        """It spawns nothing, so a machine with no PowerShell can still send."""
        entries = {e["id"]: e for e in
                   self.runner(which=lambda name: None).catalogue()}
        self.assertTrue(entries["inbox.send"]["available"])

    def test_a_declared_script_that_is_absent_is_unavailable_not_offered(self):
        os.remove(str(self.repo / "tool.ps1"))
        entry = {e["id"]: e for e in self.runner().catalogue()}["safe.read"]
        self.assertFalse(entry["available"])
        self.assertIn("does not exist", entry["reason"])

    def test_an_unknown_token_is_a_refusal_never_a_passthrough(self):
        result = self.runner().run({"id": "bad.token"})
        self.assertEqual("unavailable", result["status"])
        self.assertIn("{whatever}", result["reason"])
        self.assertEqual([], self.spawned)

    def test_a_binary_token_outside_argv_zero_is_refused(self):
        result = self.runner().run({"id": "bad.binary.position"})
        self.assertEqual("unavailable", result["status"])
        self.assertIn("argv[0]", result["reason"])
        self.assertEqual([], self.spawned)

    def test_an_unreadable_profile_stops_the_action_rather_than_guessing(self):
        """install.ps1 with no -Profile PROMPTS, and a Read-Host in a headless
        run hangs until the timeout. Substituting a plausible profile name
        instead would be the silent-fallback failure (R8)."""
        runner = self.runner()
        runner._profile_fn = lambda: None
        result = runner.run({"id": "profiled"})
        self.assertEqual("unavailable", result["status"])
        self.assertIn("active profile", result["reason"])
        self.assertEqual([], self.spawned)

    def test_the_resolved_binary_is_a_path_not_a_bare_name(self):
        self.runner().run({"id": "safe.read"})
        self.assertTrue(self.spawned[0][0][0].endswith(".CMD"),
                        self.spawned[0][0])


class JudgedByEffect(Base):
    """R9. restart-ollama.ps1 exits 0 while an orphaned llama-server keeps its
    VRAM, so an exit code is evidence and never the verdict."""

    def test_exit_zero_with_the_effect_missing_is_reported_failed(self):
        runner = self.runner(exit_code=0,
                             section={"status": "ok",
                                      "totals": {"lost": 3, "stale": 0}})
        result = runner.run({"id": "danger.write", "confirm": True})
        self.assertEqual("failed", result["status"])
        self.assertIs(False, result["verified"])
        self.assertEqual(0, result["exit_code"])
        self.assertIn("lost=3", result["verify_detail"])

    def test_exit_zero_with_the_effect_present_is_ok(self):
        runner = self.runner(exit_code=0,
                             section={"status": "ok",
                                      "totals": {"lost": 0, "stale": 0}})
        result = runner.run({"id": "danger.write", "confirm": True})
        self.assertEqual("ok", result["status"])
        self.assertIs(True, result["verified"])

    def test_a_non_zero_exit_is_failed_whatever_the_effect_says(self):
        runner = self.runner(exit_code=1,
                             section={"status": "ok",
                                      "totals": {"lost": 0, "stale": 0}})
        result = runner.run({"id": "danger.write", "confirm": True})
        self.assertEqual("failed", result["status"])

    def test_an_action_with_no_verifier_says_so_rather_than_claiming_success(self):
        result = self.runner(exit_code=0).run({"id": "safe.read"})
        self.assertEqual("ok", result["status"])
        self.assertIsNone(result["verified"])
        self.assertIn("no verifiable effect", result["verify_detail"])

    def test_with_no_collector_wired_in_the_effect_is_unchecked_and_said(self):
        """Not silently true. A runner built without a collector - the CLI
        before it loads the config, a test harness - must not report an
        unverified action as verified."""
        runner = self.runner(exit_code=0)
        result = runner.run({"id": "danger.write", "confirm": True})
        self.assertIsNone(result["verified"])
        self.assertIn("no collector", result["verify_detail"])

    def test_an_unavailable_section_is_not_read_as_a_failed_effect(self):
        runner = self.runner(exit_code=0,
                             section={"status": "unavailable",
                                      "reason": "no policy"})
        result = runner.run({"id": "danger.write", "confirm": True})
        self.assertIsNone(result["verified"])
        self.assertEqual("ok", result["status"])
        self.assertIn("no policy", result["verify_detail"])

    def test_a_timeout_is_failed_and_claims_no_effect(self):
        import subprocess
        runner = self.runner(raises=subprocess.TimeoutExpired("x", 30))
        result = runner.run({"id": "safe.read"})
        self.assertEqual("failed", result["status"])
        self.assertIs(False, result["verified"])
        self.assertIn("30s", result["reason"])

    def test_every_verifier_the_catalogue_names_exists(self):
        catalog = rt_actions.load_actions(SKILL_ROOT)
        for action in catalog["actions"]:
            name = action.get("verify")
            if name:
                with self.subTest(action=action["id"]):
                    self.assertIn(name, rt_actions.VERIFIERS)

    def test_a_verifier_that_does_not_exist_is_reported_not_ignored(self):
        """The negative control for the case above: without it, a typo in
        actions.json would silently mean 'no effect claimed'."""
        catalog = fake_catalog()
        catalog["actions"][0]["verify"] = "no_such_verifier"
        runner = self.runner(catalog=catalog, section={"status": "ok"})
        result = runner.run({"id": "safe.read"})
        self.assertIsNone(result["verified"])
        self.assertIn("does not exist", result["verify_detail"])


class TheLog(Base):

    def test_every_attempt_is_appended_including_a_refusal(self):
        runner = self.runner()
        runner.run({"id": "safe.read"})
        runner.run({"id": "danger.write"})
        runner.run({"id": "nope"})
        records = self.log_lines()
        self.assertEqual(["safe.read", "danger.write", "nope"],
                         [r["id"] for r in records])
        self.assertEqual(["ok", "refused", "refused"],
                         [r["status"] for r in records])
        for record in records:
            self.assertEqual(NOW.isoformat(timespec="seconds"), record["at"])

    def test_an_unwritable_log_says_so_and_does_not_claim_the_action_failed(self):
        runner = self.runner()
        runner.values["action_log"] = "~/.claude/nope/../../\x00bad"
        result = runner.run({"id": "safe.read"})
        self.assertEqual("ok", result["status"])
        self.assertIn("log", result["log_error"].lower())

    def test_the_output_tail_keeps_the_end_not_the_head(self):
        """A Python traceback names its exception on the LAST line."""
        runner = self.runner(stdout="x" * 200 + "NameError: collections",
                             stderr="")
        result = runner.run({"id": "safe.read"})
        self.assertIn("NameError: collections", result["stdout_tail"])
        self.assertTrue(result["stdout_tail"].startswith("..."))

    def test_no_home_path_reaches_the_response(self):
        """The page is rendered in a browser and screenshotted, so an account
        name in a tail is published exactly like one in a panel."""
        runner = self.runner(stdout="wrote %s\\thing" % self.home)
        result = runner.run({"id": "safe.read"})
        self.assertNotIn(str(self.home), json.dumps(result))
        self.assertIn("~", result["stdout_tail"])


class Inbox(Base):

    def send(self, **body):
        payload = {"id": "inbox.send", "target": "sess-1", "text": "hello"}
        payload.update(body)
        return self.runner().run(payload)

    def test_a_message_is_written_atomically_and_parses(self):
        result = self.send()
        self.assertEqual("ok", result["status"])
        folder = self.home / ".claude" / "rt-inbox" / "sess-1"
        files = sorted(p.name for p in folder.iterdir())
        self.assertEqual(["abc123.json"], files, files)
        record = json.loads(io.open(folder / "abc123.json",
                                    encoding="utf-8").read())
        self.assertEqual("hello", record["text"])
        self.assertEqual("rt-dashboard", record["from"])

    def test_with_no_delivery_hook_it_is_unreachable_never_delivered(self):
        """A message written into a directory nobody drains is the vault drop
        that sat in working/ for an hour, rebuilt."""
        result = self.send()
        self.assertEqual("unreachable", result["delivery"])
        self.assertIn("would sit unread", result["verify_detail"])

    def test_with_the_hook_declared_it_is_queued(self):
        with io.open(self.home / ".claude" / "settings.json", "w") as handle:
            handle.write(json.dumps({"hooks": {"UserPromptSubmit": [
                {"hooks": [{"command": "python rt-inbox-deliver.py"}]}]}}))
        result = self.send()
        self.assertEqual("queued", result["delivery"])

    def test_a_target_carrying_a_path_is_refused_before_a_path_is_built(self):
        for target in ("../evil", "a/b", "..", "C:/win", "", "x" * 80,
                       ".hidden", None, 7):
            with self.subTest(target=target):
                result = self.send(target=target)
                self.assertEqual("refused", result["status"])
                self.assertEqual(400, result["http_status"])
        self.assertFalse((self.home / ".claude" / "rt-inbox").exists())

    def test_an_oversized_message_is_refused_rather_than_truncated(self):
        result = self.send(text="x" * 101)
        self.assertEqual("refused", result["status"])
        self.assertIn("refused rather than truncated", result["reason"])

    def test_an_empty_message_is_not_sent(self):
        for text in ("", "   ", None, 5):
            with self.subTest(text=text):
                self.assertEqual("refused", self.send(text=text)["status"])

    def test_a_dry_run_writes_no_message(self):
        result = self.send(dry_run=True)
        self.assertEqual("ok", result["status"])
        self.assertFalse((self.home / ".claude" / "rt-inbox").exists())


class ShippedCatalogue(unittest.TestCase):
    """The file itself, checked against the clone it points at."""

    def setUp(self):
        self.catalog = rt_actions.load_actions(SKILL_ROOT)
        self.repo = SKILL_ROOT.parent.parent.parent

    def test_every_action_declares_what_the_page_must_render(self):
        seen = set()
        for action in self.catalog["actions"]:
            with self.subTest(action=action.get("id")):
                for key in ("id", "label", "what", "destructive"):
                    self.assertIn(key, action)
                self.assertNotIn(action["id"], seen)
                seen.add(action["id"])
                if action.get("kind") != "inbox":
                    self.assertTrue(action.get("argv"))

    def test_every_destructive_action_carries_its_own_confirm_sentence(self):
        """A generic 'are you sure' teaches nothing. The one action that spends
        money must say so in its own words."""
        for action in self.catalog["actions"]:
            if action.get("destructive"):
                with self.subTest(action=action["id"]):
                    self.assertTrue((action.get("confirm") or "").strip())
                    self.assertGreater(len(action["confirm"]), 30)
        spawn = [a for a in self.catalog["actions"] if a["id"] == "session.spawn"]
        self.assertTrue(spawn)
        self.assertIn("SPENDS MONEY", spawn[0]["confirm"])

    def test_every_script_the_catalogue_points_at_exists_in_this_clone(self):
        """R14: no invented path. An action naming a script that is not here
        would be offered and fail on click."""
        checked = 0
        for action in self.catalog["actions"]:
            argv = action.get("argv") or []
            for index, item in enumerate(argv):
                if item == "-File" and index + 1 < len(argv):
                    relative = argv[index + 1].replace("{repo_root}/", "")
                    with self.subTest(script=relative):
                        self.assertTrue((self.repo / relative).exists(),
                                        relative)
                    checked += 1
        self.assertGreater(checked, 4, "the path finder matched nothing")

    def test_the_path_finder_can_actually_fail(self):
        """The negative control for the case above."""
        self.assertFalse((self.repo / "no-such-script.ps1").exists())

    def test_no_action_ever_names_a_model_tag_or_a_shell(self):
        text = io.open(SKILL_ROOT / "actions.json", encoding="utf-8").read()
        for forbidden in ("cmd.exe", "/c ", "-Command", "shell=True", ":latest"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
