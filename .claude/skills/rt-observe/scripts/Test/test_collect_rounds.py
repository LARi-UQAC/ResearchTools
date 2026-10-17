"""
test_collect_rounds - the `rounds` snapshot section: every plan stage of a round folder, and the
review loops of every worktree (local coding contract, plan 6, task 3).

Offline. Each case builds a fictitious repository under a temporary directory (plain folders,
no git process: the collector reads the git directory as files, like collect_repo does) with
`now` injected (R19, R21) and fictitious names (R34). The degradation contract is asserted: a
thing that cannot be answered is `unavailable` WITH ITS REASON, never a blank (R8, R11), and a
malformed ledger is named, not fatal.

Run:
    python .claude/skills/rt-observe/scripts/Test/test_collect_rounds.py
"""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import collect_rounds  # noqa: E402
import rt_server  # noqa: E402
import rt_state  # noqa: E402

NOW = datetime(2026, 10, 17, 12, 0, 0, tzinfo=timezone.utc)
SHIPPED_CONFIG = Path(__file__).resolve().parents[2] / "observe-config.json"
STATE_FILE = "rt-review-loop.json"


def entry(value):
    """Wrap a value the way observe-config.json does."""
    return {"value": value, "provenance": "test fixture"}


CONFIG = {"paths": {"round_roots": entry(["docs/superpowers/todo", "docs/superpowers/plans"])},
          "caps": {"rounds_max": entry(10)}}


def header(executor="local-coder", tier="simple"):
    """A valid plan header."""
    return (f"---\nexecutor: {executor}\ntier: {tier}\nbounds:\n  max_rounds: 3\n"
            "  max_tokens: 1500000\n  plateau: 2\n---\n# Plan\n")


class RepoCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / "home"
        self.repo = Path(tmp.name) / "repo"
        self.home.mkdir()
        (self.repo / ".git").mkdir(parents=True)
        self.folder = self.repo / "docs" / "superpowers" / "todo" / "2026-10-17-fictitious"
        self.folder.mkdir(parents=True)

    def plan(self, name, text="# Plan without a header\n"):
        (self.folder / name).write_text(text, encoding="utf-8")

    def ledger(self, text):
        (self.folder / "progress.md").write_text(text, encoding="utf-8")

    def collect(self, config=None):
        return collect_rounds.collect(self.repo, self.home, NOW, config or CONFIG)

    def plans_of(self, state):
        return {p["name"]: p for p in state["rounds"][0]["plans"]}


class TestPlans(RepoCase):
    def test_each_plan_reports_executor_tier_and_task_counts(self):
        self.plan("plan1.md", header("local-coder", "standard"))
        self.plan("plan2.md", header("aider", "simple"))
        self.ledger("# Progress\n\n## plan1.md\n- [x] T1 a\n- [x] T2 b\n- [ ] T3 c\n\n"
                    "## plan2.md\n- [x] T1 a\n")
        state = self.collect()
        self.assertEqual(state["status"], "ok")
        plans = self.plans_of(state)
        one = plans["plan1.md"]
        self.assertEqual((one["executor"], one["tier"]), ("local-coder", "standard"))
        self.assertEqual((one["tasks_total"], one["tasks_done"], one["tasks_blocked"]), (3, 2, 0))
        self.assertEqual(one["state"], "open")
        self.assertEqual(plans["plan2.md"]["state"], "done")
        for key in ("proven_by", "proven_at"):
            self.assertTrue(state[key])

    def test_a_blocked_mark_makes_the_plan_blocked_not_done(self):
        self.plan("plan1.md", header())
        self.ledger("## plan1.md\n- [x] T1 a\n- [!] T2 stuck\n")
        plan = self.plans_of(self.collect())["plan1.md"]
        self.assertEqual((plan["state"], plan["tasks_blocked"]), ("blocked", 1))

    def test_a_plan_without_a_header_has_a_null_executor(self):
        self.plan("plan1.md")
        self.ledger("## plan1.md\n- [ ] T1 a\n")
        plan = self.plans_of(self.collect())["plan1.md"]
        self.assertIsNone(plan["executor"])
        self.assertIsNone(plan["tier"])

    def test_an_invalid_header_gives_a_null_executor_not_a_crash(self):
        self.plan("plan1.md", "---\nexecutor: [broken\n---\nbody")
        self.ledger("## plan1.md\n- [ ] T1 a\n")
        self.assertIsNone(self.plans_of(self.collect())["plan1.md"]["executor"])

    def test_a_malformed_ledger_is_named_not_fatal(self):
        self.plan("plan1.md", header())
        self.ledger("## plan1.md\n- [x] T1 a\n- [?] T2 odd\n")
        state = self.collect()
        self.assertEqual(state["status"], "ok")
        round_ = state["rounds"][0]
        self.assertTrue(any("line 3" in e for e in round_["ledger_errors"]))
        self.assertEqual(self.plans_of(state)["plan1.md"]["tasks_total"], 1)

    def test_a_plan_with_no_ledger_section_has_zero_tasks_and_is_open(self):
        self.plan("plan1.md", header())
        self.ledger("## plan2.md\n- [ ] T1 a\n")
        plan = self.plans_of(self.collect())["plan1.md"]
        self.assertEqual((plan["tasks_total"], plan["state"]), (0, "open"))


class TestReviewLoops(RepoCase):
    def loop(self, git_dir, branches):
        git_dir.mkdir(parents=True, exist_ok=True)
        doc = {"branches": branches}
        (git_dir / STATE_FILE).write_text(json.dumps(doc), encoding="utf-8")

    def state_for(self, rounds_used, max_rounds=3, ticks=()):
        return {"max_rounds": max_rounds, "max_tokens": 1000, "plateau": 2,
                "invocations": {"code-review": rounds_used, "security-review": 1},
                "ticks": [{"findings": n, "at": "x"} for n in ticks]}

    def test_review_loops_of_two_worktrees_are_both_reported(self):
        self.plan("plan1.md", header())
        self.ledger("## plan1.md\n- [ ] T1 a\n")
        self.loop(self.repo / ".git", {"main": self.state_for(1)})
        self.loop(self.repo / ".git" / "worktrees" / "local-coding-contract",
                  {"feat/x": self.state_for(2, ticks=(5, 3))})
        loops = self.collect()["review_loops"]
        by_branch = {item["branch"]: item for item in loops}
        self.assertEqual(sorted(by_branch), ["feat/x", "main"])
        self.assertEqual(by_branch["feat/x"]["rounds_used"], 2)
        self.assertEqual(by_branch["feat/x"]["ticks"], [5, 3])
        self.assertEqual((by_branch["feat/x"]["max_rounds"], by_branch["feat/x"]["plateau"]),
                         (3, 2))
        self.assertEqual(by_branch["feat/x"]["worktree"], "local-coding-contract")

    def test_a_worktree_git_file_resolves_to_the_common_directory(self):
        common = self.repo.parent / "main" / ".git"
        self.loop(common / "worktrees" / "wt1", {"b": self.state_for(1)})
        (common / "worktrees" / "wt1" / "commondir").write_text("../..", encoding="utf-8")
        import shutil
        shutil.rmtree(self.repo / ".git")
        (self.repo / ".git").write_text("gitdir: %s" % (common / "worktrees" / "wt1"),
                                        encoding="utf-8")
        self.plan("plan1.md", header())
        self.assertEqual([i["branch"] for i in self.collect()["review_loops"]], ["b"])

    def test_a_corrupt_state_file_is_skipped_not_fatal(self):
        self.plan("plan1.md", header())
        self.ledger("## plan1.md\n- [ ] T1 a\n")
        (self.repo / ".git" / STATE_FILE).write_text("{broken", encoding="utf-8")
        state = self.collect()
        self.assertEqual(state["status"], "ok")
        self.assertEqual(state["review_loops"], [])


class TestUnavailableAndRedaction(RepoCase):
    def test_no_round_folder_is_unavailable_with_its_reason(self):
        for path in sorted(self.folder.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        self.folder.rmdir()
        state = self.collect()
        self.assertEqual(state["status"], "unavailable")
        self.assertIn("docs/superpowers/todo", state["reason"])

    def test_a_folder_without_progress_md_is_not_a_round(self):
        self.plan("plan1.md", header())
        state = self.collect()
        self.assertEqual(state["status"], "unavailable")

    def test_paths_are_redacted(self):
        self.plan("plan1.md", header())
        self.ledger("## plan1.md\n- [x] T1 a\n")
        text = json.dumps(self.collect())
        self.assertNotIn(str(self.home), text)
        wt = self.home / ".claude"
        (self.repo / ".git" / "worktrees" / str(wt).replace(":", "").replace("\\", "_")
         ).mkdir(parents=True)
        self.assertNotIn(str(self.home), json.dumps(self.collect()))

    def test_a_missing_config_key_is_named_and_never_raises(self):
        state = self.collect({"paths": {}, "caps": {}})
        self.assertEqual(state["status"], "unavailable")
        self.assertIn("round_roots", state["reason"])


class TestRound1Findings(RepoCase):
    """Fixes for the code review of 2026-10-17 (R35 round 1)."""

    def test_the_contract_is_loaded_once_and_sys_path_does_not_grow(self):
        self.plan("plan1.md", header())
        self.ledger("## plan1.md\n- [ ] T1 a\n")
        self.collect()
        before = list(sys.path)
        for _ in range(3):
            self.collect()
        self.assertEqual(sys.path, before)

    def test_review_loops_say_why_when_the_state_name_cannot_be_read(self):
        from unittest import mock
        self.plan("plan1.md", header())
        self.ledger("## plan1.md\n- [ ] T1 a\n")
        (self.repo / ".git" / STATE_FILE).write_text(
            json.dumps({"branches": {"b": {"max_rounds": 3, "invocations": {}}}}),
            encoding="utf-8")
        with mock.patch.object(collect_rounds, "_load_contract", return_value=None):
            state = self.collect()
        self.assertEqual(state["status"], "ok")
        self.assertEqual(state["review_loops"], [])
        self.assertIn("plan_contract", state["review_loops_note"])
        self.assertEqual(len(state["rounds"]), 1)


class TestLedgerBullets(RepoCase):
    def test_a_markdown_link_bullet_is_not_a_ledger_mark(self):
        # R35 round 4: `- [plan1](plan1.md)` matched with mark `p` and raised a false error.
        self.plan("plan1.md", header())
        self.ledger("## plan1.md\n- [x] T1 a\n- [plan1](plan1.md) notes\n- [X] T2\n- [?] T3\n")
        errors = self.collect()["rounds"][0]["ledger_errors"]
        self.assertEqual(len(errors), 2)
        self.assertTrue(all("[p]" not in e for e in errors))


class TestNewestFirst(RepoCase):
    def test_the_cap_drops_the_oldest_folders_and_says_so(self):
        base = self.repo / "docs" / "superpowers" / "todo"
        for n in range(1, 13):
            d = base / ("2026-10-%02d-x" % n)
            d.mkdir(exist_ok=True)
            (d / "progress.md").write_text("## plan1.md\n- [ ] T1\n", encoding="utf-8")
            (d / "plan1.md").write_text(header(), encoding="utf-8")
        state = self.collect(dict(CONFIG, caps={"rounds_max": entry(3)}))
        names = [r["folder"].split("/")[-1] for r in state["rounds"]]
        self.assertEqual(names, ["2026-10-12-x", "2026-10-11-x", "2026-10-10-x"])
        self.assertGreater(state["rounds_dropped"], 0)


class TestRegistration(unittest.TestCase):
    def test_the_section_is_registered_with_its_ttl(self):
        shipped = json.loads(SHIPPED_CONFIG.read_text(encoding="utf-8"))
        builders = rt_state.section_builders(Path("."), Path("."), shipped)
        self.assertIn("rounds", builders)
        self.assertEqual(rt_server.SECTION_TTL_KEY["rounds"], "rounds")
        for group, key in (("ttl_seconds", "rounds"), ("caps", "rounds_max"),
                           ("paths", "round_roots")):
            self.assertTrue(shipped[group][key]["provenance"], f"{group}.{key}")
        self.assertIn("docs/superpowers/todo", shipped["paths"]["round_roots"]["value"])


if __name__ == "__main__":
    unittest.main()
