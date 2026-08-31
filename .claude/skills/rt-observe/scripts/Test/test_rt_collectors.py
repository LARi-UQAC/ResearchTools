"""
test_rt_collectors - the core collectors: registry, repo, progress, graph, services.

Offline. Every case builds its tree under tempfile; `shutil.which` and
`subprocess.run` are patched, so no binary is executed, no network is touched and
no port is bound (R21).

The recurring assertion, in every collector, is the one the degradation contract
turns on: a thing that cannot be answered is reported UNAVAILABLE WITH ITS
REASON, never as a zero, an empty list or a blank panel. An empty MCP roster
reads as "no servers configured"; a missing green stamp reads as "green"; a
leftover lock reads as "running". Each of those is a wrong answer that looks like
a right one, so each has its own test here.
"""
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import collect_graph  # noqa: E402
import collect_progress  # noqa: E402
import collect_registry  # noqa: E402
import collect_repo  # noqa: E402
import collect_services  # noqa: E402

NOW = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path


def no_binaries():
    """Patch every binary away.

    Without this, a services test invokes the REAL `claude mcp list`, which
    reaches the network for every configured server. Measured while writing this
    suite: three cases did exactly that and the run took 55 seconds instead of
    0.4. An offline suite that quietly goes online is not offline, and it then
    fails on a machine with no network for reasons that have nothing to do with
    the code it is meant to be testing.
    """
    return mock.patch.object(collect_services.shutil, "which", return_value=None)


class TempTree(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name) / "repo"
        self.home = Path(self._tmp.name) / "home"
        self.home.mkdir(parents=True, exist_ok=True)


class RegistryTest(TempTree):

    def _agent(self, name, text):
        write(self.repo / ".claude" / "agents" / (name + ".md"), text)

    def test_a_well_formed_set_is_clean(self):
        self._agent("alpha", "---\nname: alpha\ndescription: \"does a thing\"\n---\n\nbody\n")
        write(self.repo / ".claude" / "skills" / "s1" / "SKILL.md",
              "---\nname: s1\ndescription: \"a skill\"\n---\n\nbody\n")
        state = collect_registry.collect(self.repo, now=NOW)
        self.assertEqual(state["status"], "ok")
        self.assertTrue(state["clean"])
        self.assertEqual(state["counts"]["skills"], 1)

    def test_frontmatter_name_disagreeing_with_the_filename_is_a_problem(self):
        """A harness that indexes by one and loads by the other silently misses
        the definition, and every mirror of it looks perfectly healthy."""
        self._agent("alpha", "---\nname: beta\ndescription: \"x\"\n---\n\nbody\n")
        state = collect_registry.collect(self.repo, now=NOW)
        self.assertFalse(state["clean"])
        self.assertIn("but the file is named", state["findings"][0]["problems"][0])

    def test_a_missing_description_is_a_problem(self):
        self._agent("alpha", "---\nname: alpha\n---\n\nbody\n")
        state = collect_registry.collect(self.repo, now=NOW)
        self.assertFalse(state["clean"])

    def test_a_skill_directory_without_a_skill_md_is_reported(self):
        write(self.repo / ".claude" / "agents" / "alpha.md",
              "---\nname: alpha\ndescription: \"x\"\n---\n\nbody\n")
        (self.repo / ".claude" / "skills" / "empty").mkdir(parents=True)
        state = collect_registry.collect(self.repo, now=NOW)
        self.assertFalse(state["clean"])
        self.assertTrue(any(f["name"] == "empty" for f in state["findings"]))

    def test_a_command_without_frontmatter_is_not_a_problem(self):
        """install.ps1 promotes a frontmatter-less command's H1 to a description,
        so flagging it would be noise on a form the generator supports."""
        write(self.repo / ".claude" / "commands" / "doc.md", "# doc\n\nbody\n")
        state = collect_registry.collect(self.repo, now=NOW)
        self.assertTrue(state["clean"])

    def test_mixed_language_is_an_advisory_and_never_a_problem(self):
        """R22 is real, but this check cannot tell a rule written in French from
        an English rule quoting a French deliverable string, which is allowed. It
        reports; it never fails a run."""
        self._agent("alpha",
                    "---\nname: alpha\ndescription: \"x\"\n---\n\n"
                    "Cette règle est écrite dans la langue des livrables.\n")
        state = collect_registry.collect(self.repo, now=NOW)
        self.assertTrue(state["clean"])
        self.assertEqual(state["advisory_count"], 1)

    def test_no_claude_directory_is_unavailable_not_empty(self):
        state = collect_registry.collect(self.repo, now=NOW)
        self.assertEqual(state["status"], "unavailable")


class RepoStateTest(TempTree):

    def test_a_bom_stamp_is_read_rather_than_raising(self):
        """PowerShell writes .rt-green.json with a UTF-8 BOM and plain utf-8
        RAISES on it. Measured 2026-08-30."""
        blob = json.dumps({"generated": "2026-08-30T21:43:59", "suites": {},
                           "outcomes": [1, 2], "code_hashes": {"a": "b"},
                           "elapsed_s": 12})
        (self.repo).mkdir(parents=True, exist_ok=True)
        with io.open(self.repo / ".rt-green.json", "w",
                     encoding="utf-8-sig", newline="\n") as handle:
            handle.write(blob)
        state = collect_repo.collect(self.repo, NOW, 604800)
        self.assertEqual(state["green"]["status"], "ok")
        self.assertEqual(state["green"]["value"], "green")
        self.assertEqual(state["green"]["code_files_hashed"], 1)

    def test_an_absent_stamp_is_not_proven_never_green(self):
        """The runner DELETES the stamp on any failure, so absence is the failure
        signal. Reading it as 'nothing to report' inverts the meaning exactly."""
        self.repo.mkdir(parents=True, exist_ok=True)
        state = collect_repo.collect(self.repo, NOW, 604800)
        self.assertEqual(state["green"]["status"], "unavailable")
        self.assertEqual(state["green"]["value"], "not proven")
        self.assertIn("DELETES", state["green"]["reason"])

    def test_an_old_stamp_is_green_but_flagged_aged(self):
        blob = json.dumps({"generated": "2026-08-01T00:00:00", "suites": {},
                           "outcomes": [], "code_hashes": {}})
        write(self.repo / ".rt-green.json", blob)
        import os
        old = (NOW - timedelta(days=30)).timestamp()
        os.utime(self.repo / ".rt-green.json", (old, old))
        state = collect_repo.collect(self.repo, NOW, 604800)
        self.assertTrue(state["green"]["aged"])
        self.assertIn("passed then", state["green"]["reason"])

    def test_the_branch_is_read_from_head_as_a_file(self):
        """Never a git command: this toolkit's sessions may not invoke git at
        all, and .git/HEAD is ordinary text."""
        write(self.repo / ".git" / "HEAD", "ref: refs/heads/feat/rt-dashboard\n")
        state = collect_repo.collect(self.repo, NOW, 604800)
        self.assertEqual(state["branch"]["value"], "feat/rt-dashboard")

    def test_a_detached_head_is_said_rather_than_guessed(self):
        write(self.repo / ".git" / "HEAD", "9f1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c\n")
        state = collect_repo.collect(self.repo, NOW, 604800)
        self.assertEqual(state["branch"]["value"], "detached")

    def test_a_profile_selector_naming_a_missing_file_is_reported(self):
        write(self.repo / ".claude" / "CLAUDE.md",
              "```yaml\nactive_profile: ghost\n```\n")
        state = collect_repo.collect(self.repo, NOW, 604800)
        self.assertEqual(state["profile"]["value"], "ghost")
        self.assertFalse(state["profile"]["profile_file_exists"])
        self.assertIn("does not exist", state["profile"]["reason"])


class ProgressTest(TempTree):

    def _progress(self, body):
        write(self.repo / "PROGRESS.md", body)

    def _plan(self, rel, phases):
        text = "# plan\n\n" + "\n".join(
            "### Phase %d - %s\n\nbody\n" % (n, label) for n, label in phases)
        write(self.repo / rel, text)

    def test_a_done_phase_without_evidence_is_unproven_not_green(self):
        """Nothing in a Markdown file proves work happened, so a bare tick is
        rendered unproven. This is the whole reason the panel is trustworthy."""
        self._progress("- [x] Phase 1 - policy extraction\n")
        state = collect_progress.collect(self.repo, now=NOW)
        self.assertEqual(state["phases"][0]["state"], "unproven")
        self.assertIn("no `| evidence:`", state["phases"][0]["reason"])

    def test_a_done_phase_with_evidence_is_done(self):
        self._progress("- [x] Phase 1 - policy | evidence: 62 suites green\n")
        state = collect_progress.collect(self.repo, now=NOW)
        self.assertEqual(state["phases"][0]["state"], "done")
        self.assertEqual(state["phases"][0]["evidence"], "62 suites green")

    def test_a_phase_in_the_plan_and_absent_from_progress_is_unreported(self):
        """The failure mode of every hand-maintained progress file: it stops
        being updated while still looking complete."""
        self._plan("plan.md", [(1, "one"), (2, "two"), (3, "three")])
        self._progress("plan: plan.md\n\n- [x] Phase 1 - one | evidence: x\n")
        state = collect_progress.collect(self.repo, now=NOW)
        states = {p["number"]: p["state"] for p in state["phases"]}
        self.assertEqual(states[1], "done")
        self.assertEqual(states[2], "unreported")
        self.assertEqual(states[3], "unreported")
        self.assertEqual(state["crosscheck"]["unreported"], [2, 3])
        self.assertFalse(state["crosscheck"]["agrees"])

    def test_a_progress_phase_unknown_to_the_plan_is_reported(self):
        """The other direction: a phase nobody planned is as suspect as a phase
        nobody reported."""
        self._plan("plan.md", [(1, "one")])
        self._progress("plan: plan.md\n\n- [x] Phase 1 - one | evidence: x\n"
                       "- [ ] Phase 9 - invented\n")
        state = collect_progress.collect(self.repo, now=NOW)
        self.assertEqual(state["crosscheck"]["unknown_to_the_plan"], [9])

    def test_agreement_is_reported_when_the_two_match(self):
        self._plan("plan.md", [(1, "one"), (2, "two")])
        self._progress("plan: plan.md\n\n- [x] Phase 1 - one | evidence: x\n"
                       "- [~] Phase 2 - two\n")
        state = collect_progress.collect(self.repo, now=NOW)
        self.assertTrue(state["crosscheck"]["agrees"])

    def test_a_missing_plan_line_disables_only_the_crosscheck(self):
        self._progress("- [x] Phase 1 - one | evidence: x\n")
        state = collect_progress.collect(self.repo, now=NOW)
        self.assertEqual(state["status"], "ok")
        self.assertEqual(state["crosscheck"]["status"], "unavailable")

    def test_the_next_action_line_is_extracted_and_its_absence_stated(self):
        self._progress("- [x] Phase 1 | evidence: x\n\n**NEXT ACTION**: run Phase 2\n")
        state = collect_progress.collect(self.repo, now=NOW)
        self.assertEqual(state["next_action"], "run Phase 2")
        self._progress("- [x] Phase 1 | evidence: x\n")
        state = collect_progress.collect(self.repo, now=NOW)
        self.assertIsNone(state["next_action"])
        self.assertIn("cold session", state["next_action_missing_reason"])

    def test_no_progress_file_infers_nothing_from_the_plan(self):
        self._plan("plan.md", [(1, "one")])
        state = collect_progress.collect(self.repo, now=NOW)
        self.assertEqual(state["status"], "unavailable")
        self.assertIn("nothing is inferred", state["reason"])

    def test_every_marker_maps_to_a_state(self):
        self._progress("- [x] Phase 1 | evidence: e\n- [ ] Phase 2\n"
                       "- [~] Phase 3\n- [!] Phase 4\n- [R] Phase 5\n- [-] Phase 6\n")
        state = collect_progress.collect(self.repo, now=NOW)
        got = {p["number"]: p["state"] for p in state["phases"]}
        self.assertEqual(got, {1: "done", 2: "todo", 3: "in-progress",
                               4: "blocked", 5: "review", 6: "deferred"})


class GraphPanelTest(TempTree):

    def test_an_absent_snapshot_names_the_dispatch_rather_than_blanking(self):
        state = collect_graph.collect("~/rt-graph-snapshot.json", self.home,
                                      NOW, 86400)
        self.assertEqual(state["status"], "unavailable")
        self.assertIn("never reads the graph itself", state["reason"])
        self.assertIn("local-writer", state["refresh"])

    def test_a_snapshot_is_rendered_with_its_age(self):
        write(self.home / "rt-graph-snapshot.json", json.dumps({
            "generated": "2026-08-30T11:00:00", "nodes": 5683, "links": 7869,
            "origins": {"ast": 5683}, "file_types": {".py": 100}}))
        state = collect_graph.collect("~/rt-graph-snapshot.json", self.home,
                                      NOW, 86400)
        self.assertEqual(state["status"], "ok")
        self.assertEqual(state["nodes"], 5683)
        self.assertFalse(state["stale"])
        self.assertTrue(state["ast_only"])
        self.assertIn("why-question belongs to the vault", state["ast_only_reason"])

    def test_an_old_snapshot_is_stale_rather_than_current(self):
        path = write(self.home / "rt-graph-snapshot.json",
                     json.dumps({"generated": "x", "nodes": 1, "links": 1,
                                 "origins": {"ast": 1}, "file_types": {}}))
        import os
        old = (NOW - timedelta(days=5)).timestamp()
        os.utime(path, (old, old))
        state = collect_graph.collect("~/rt-graph-snapshot.json", self.home,
                                      NOW, 86400)
        self.assertTrue(state["stale"])
        self.assertIn("as it was, not as it is", state["reason"])

    def test_missing_fields_are_named_rather_than_rendered_as_zero(self):
        write(self.home / "rt-graph-snapshot.json", json.dumps({"nodes": 3}))
        state = collect_graph.collect("~/rt-graph-snapshot.json", self.home,
                                      NOW, 86400)
        self.assertIn("links", state["missing_fields"])
        self.assertIn("because the data is absent", state["missing_fields_reason"])

    def test_an_unparsable_snapshot_degrades_with_its_reason(self):
        write(self.home / "rt-graph-snapshot.json", "{ broken ")
        state = collect_graph.collect("~/rt-graph-snapshot.json", self.home,
                                      NOW, 86400)
        self.assertEqual(state["status"], "unavailable")
        self.assertIn("does not parse", state["reason"])


class ServicesTest(TempTree):

    def _values(self):
        return {"mcp_timeout_s": 5, "subprocess_timeout_s": 5,
                "outbox_root": str(self.home / "outbox"),
                "daemon_lock_path": str(self.home / "vault-daemon.lock"),
                "lock_stale_after_s": 900}

    def test_without_claude_the_roster_falls_to_tier_two_and_says_so(self):
        write(self.repo / ".mcp.json",
              json.dumps({"mcpServers": {"alpha": {}, "beta": {}}}))
        with mock.patch.object(collect_services.shutil, "which",
                               return_value=None):
            state = collect_services.collect(self.repo, self.home,
                                             self._values(), now=NOW)
        mcp = state["mcp"]
        self.assertEqual(mcp["tier"], 2)
        self.assertEqual(mcp["liveness"], "unavailable")
        self.assertEqual(mcp["counts"]["configured"], 2)

    def test_a_timing_out_claude_is_unavailable_never_an_empty_roster(self):
        """An empty roster reads as 'no servers configured', which is a wrong
        answer that looks like a right one (R8)."""
        import subprocess as sp
        write(self.repo / ".mcp.json", json.dumps({"mcpServers": {"alpha": {}}}))
        with mock.patch.object(collect_services.shutil, "which",
                               side_effect=lambda n: "C:/fake/%s.CMD" % n), \
             mock.patch.object(collect_services.subprocess, "run",
                               side_effect=sp.TimeoutExpired("claude", 5)):
            state = collect_services.collect(self.repo, self.home,
                                             self._values(), now=NOW)
        mcp = state["mcp"]
        self.assertEqual(mcp["tier"], 2)
        self.assertIn("did not answer within", mcp["tier1_reason"])
        self.assertEqual(mcp["counts"]["configured"], 1)

    def test_the_binary_is_invoked_by_resolved_path_not_by_bare_name(self):
        """On Windows the launcher is claude.CMD and a bare name fails with
        [WinError 2], which silently demoted a machine that HAS claude to the
        tier-2 roster. Measured 2026-08-30."""
        seen = {}

        def fake_run(argv, **kwargs):
            seen["argv"] = argv
            return mock.Mock(returncode=0,
                             stdout="alpha: ok - ✔ Connected\n", stderr="")

        with mock.patch.object(collect_services.shutil, "which",
                               side_effect=lambda n: "C:/fake/%s.CMD" % n), \
             mock.patch.object(collect_services.subprocess, "run", fake_run):
            collect_services.collect(self.repo, self.home, self._values(), now=NOW)
        self.assertTrue(seen["argv"][0].endswith(".CMD"), seen["argv"])

    def test_the_three_live_states_are_parsed(self):
        out = ("alpha: cmd - ✔ Connected\n"
               "beta: cmd - ! Needs authentication\n"
               "gamma: cmd - ✘ Failed to connect\n")

        def fake_run(argv, **kwargs):
            if "mcp" in argv:
                return mock.Mock(returncode=0, stdout=out, stderr="")
            return mock.Mock(returncode=0, stdout="NAME\n", stderr="")

        with mock.patch.object(collect_services.shutil, "which",
                               side_effect=lambda n: "C:/fake/%s.CMD" % n), \
             mock.patch.object(collect_services.subprocess, "run", fake_run):
            state = collect_services.collect(self.repo, self.home,
                                             self._values(), now=NOW)
        self.assertEqual(state["mcp"]["counts"],
                         {"connected": 1, "needs-auth": 1, "failed": 1})

    def test_a_leftover_lock_with_a_dead_holder_reports_not_running(self):
        """Reading a leftover lock as 'running' reports exactly backwards: a
        daemon killed mid-run leaves its singleton lock behind."""
        lock_module = mock.Mock()
        lock_module.held_by_live_holder.return_value = False
        write(self.repo / ".claude" / "skills" / "obsidian-cli" / "scripts"
              / "vault_lock.py", "def held_by_live_holder(p, s):\n    return False\n")
        (self.home / "outbox" / "raw").mkdir(parents=True)
        write(self.home / "outbox" / "raw" / "drop.md", "x")
        with no_binaries():
            state = collect_services.collect(self.repo, self.home,
                                             self._values(), now=NOW)
        daemon = state["vault_daemon"]
        self.assertFalse(daemon["running"])
        self.assertIn("nothing will consume them", daemon["alert"])

    def test_a_live_holder_reports_running_and_raises_no_alert(self):
        write(self.repo / ".claude" / "skills" / "obsidian-cli" / "scripts"
              / "vault_lock.py", "def held_by_live_holder(p, s):\n    return True\n")
        (self.home / "outbox" / "raw").mkdir(parents=True)
        write(self.home / "outbox" / "raw" / "drop.md", "x")
        with no_binaries():
            state = collect_services.collect(self.repo, self.home,
                                             self._values(), now=NOW)
        self.assertTrue(state["vault_daemon"]["running"])
        self.assertIsNone(state["vault_daemon"]["alert"])

    def test_an_absent_vault_lock_module_says_so_rather_than_guessing(self):
        with no_binaries():
            state = collect_services.collect(self.repo, self.home,
                                             self._values(), now=NOW)
        daemon = state["vault_daemon"]
        self.assertIsNone(daemon["running"])
        self.assertIn("does NOT mean a daemon is running", daemon["reason"])

    def test_ollama_absent_is_stated_rather_than_reported_as_zero_models(self):
        with mock.patch.object(collect_services.shutil, "which",
                               return_value=None):
            state = collect_services.collect(self.repo, self.home,
                                             self._values(), now=NOW)
        self.assertEqual(state["local_models"]["status"], "unavailable")
        self.assertIn("not on PATH", state["local_models"]["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
