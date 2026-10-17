"""
test_loop_bounds.py - offline tests for loop_bounds.py, the engine that stores and decides the
bounds of a review loop (R35 as amended by the local coding contract, plan 1).

Every case runs in temporary directories and, where git matters, in REAL temporary git
repositories with fictitious identities (R34). The configuration is injected, never read from
a machine-local file (R21). Failure paths are asserted next to the happy paths (R20).

Run:
    python .claude/skills/loop-engineer/scripts/Test/test_loop_bounds.py
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import loop_bounds as lb  # noqa: E402

CONFIG = {
    "state_file_name": {"value": "rt-review-loop.json", "provenance": "test fixture"},
    "git_timeout_s": {"value": 10, "provenance": "test fixture"},
    "transcript_scan_max_bytes": {"value": 1000000, "provenance": "test fixture"},
}
NOW = "2026-10-17T12:00:00+00:00"
GIT_ID = ["-c", "user.name=Wick, J.", "-c", "user.email=student@example.org"]


def git(cwd: Path, *args: str) -> str:
    """Run a real git command in a temporary repository and return its stdout."""
    out = subprocess.run(["git", *GIT_ID, *args], cwd=cwd, capture_output=True, text=True,
                         timeout=30, check=True)
    return out.stdout.strip()


def make_repo(root: Path) -> Path:
    """Create a repository with one commit on branch main and return its path."""
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    (repo / "a.txt").write_text("a", encoding="utf-8")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-m", "first")
    return repo


def usage_line(inp: int, cache_create: int, cache_read: int, out: int) -> str:
    """One transcript record carrying a usage block."""
    return json.dumps({"message": {"usage": {
        "input_tokens": inp, "cache_creation_input_tokens": cache_create,
        "cache_read_input_tokens": cache_read, "output_tokens": out}}})


def fresh_state(**over) -> dict:
    """A valid state built through the real init function."""
    args = dict(branch="main", max_rounds=3, max_tokens=1000, plateau=2, transcript=None,
                now_iso=NOW)
    args.update(over)
    return lb.init_state(**args)


class TestInit(unittest.TestCase):
    def test_init_requires_all_three_bounds_as_positive_integers(self):
        for key in ("max_rounds", "max_tokens", "plateau"):
            for bad in (None, 0, -1, "3", True, 2.5):
                with self.subTest(key=key, bad=bad):
                    with self.assertRaises(lb.BoundsError) as ctx:
                        fresh_state(**{key: bad})
                    self.assertIn(key, str(ctx.exception))

    def test_init_records_the_transcript_size_as_offset(self):
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "t.jsonl"
            transcript.write_bytes(b"x" * 40)
            self.assertEqual(fresh_state(transcript=transcript)["transcript_offset"], 40)
            self.assertIsNone(fresh_state(transcript=Path(tmp) / "absent")["transcript_offset"])


class TestStatePlacement(unittest.TestCase):
    def test_state_lives_in_the_git_dir_of_each_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            wt = Path(tmp) / "wt"
            git(repo, "worktree", "add", "-b", "other", str(wt))
            first = lb.state_path(repo, config=CONFIG)
            second = lb.state_path(wt, config=CONFIG)
            self.assertIsNotNone(first)
            self.assertIsNotNone(second)
            self.assertNotEqual(first, second)
            self.assertEqual(first.name, "rt-review-loop.json")

    def test_state_path_is_none_outside_a_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(lb.state_path(Path(tmp), config=CONFIG))

    def test_state_path_is_none_for_a_missing_directory(self):
        self.assertIsNone(lb.state_path(Path("Z:/no/such/dir/for/the/test"), config=CONFIG))

    def test_state_is_keyed_by_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            lb.save_state(path, "feat/a", fresh_state(branch="feat/a"))
            self.assertIsNotNone(lb.load_state(path, "feat/a"))
            self.assertIsNone(lb.load_state(path, "feat/b"))

    def test_load_state_tolerates_a_missing_or_corrupt_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            self.assertIsNone(lb.load_state(path, "main"))
            path.write_text("{not json", encoding="utf-8")
            self.assertIsNone(lb.load_state(path, "main"))

    def test_save_is_atomic_and_leaves_no_tmp_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            lb.save_state(path, "main", fresh_state())
            lb.save_state(path, "other", fresh_state(branch="other"))
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["state.json"])
            doc = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(sorted(doc["branches"]), ["main", "other"])


class TestDecide(unittest.TestCase):
    def test_no_bounds_declared_is_refused_and_names_the_init_command(self):
        allowed, reason = lb.decide(None, "code-review", None)
        self.assertFalse(allowed)
        self.assertIn('loop_bounds.py" init', reason)

    def test_decide_refuses_at_max_rounds_and_allows_one_before(self):
        state = fresh_state(max_rounds=3)
        for _ in range(2):
            lb.record_invocation(state, "code-review")
        self.assertTrue(lb.decide(state, "code-review", 0)[0])
        lb.record_invocation(state, "code-review")
        allowed, reason = lb.decide(state, "code-review", 0)
        self.assertFalse(allowed)
        self.assertIn("max_rounds", reason)

    def test_each_guarded_skill_is_counted_separately(self):
        state = fresh_state(max_rounds=1)
        lb.record_invocation(state, "code-review")
        self.assertFalse(lb.decide(state, "code-review", 0)[0])
        self.assertTrue(lb.decide(state, "security-review", 0)[0])

    def test_decide_refuses_over_the_token_budget_and_allows_when_tokens_unknown(self):
        state = fresh_state(max_tokens=1000)
        self.assertTrue(lb.decide(state, "code-review", 1000)[0])
        allowed, reason = lb.decide(state, "code-review", 1001)
        self.assertFalse(allowed)
        self.assertIn("max_tokens", reason)
        self.assertTrue(lb.decide(state, "code-review", None)[0])

    def test_plateau_refuses_when_the_last_k_ticks_do_not_fall(self):
        def with_ticks(counts):
            state = fresh_state(plateau=2)
            for count in counts:
                lb.tick(state, count, NOW)
            return state

        self.assertTrue(lb.decide(with_ticks([5, 3, 1]), "code-review", 0)[0])
        self.assertTrue(lb.decide(with_ticks([5, 5]), "code-review", 0)[0])
        self.assertTrue(lb.decide(with_ticks([5, 3, 3]), "code-review", 0)[0])
        for flat in ([4, 4, 4], [2, 3, 4], [9, 4, 4, 4]):
            allowed, reason = lb.decide(with_ticks(flat), "code-review", 0)
            self.assertFalse(allowed, flat)
            self.assertIn("plateau", reason)

    def test_tick_rejects_a_negative_or_non_integer_count(self):
        for bad in (-1, "2", True, None):
            with self.assertRaises(lb.BoundsError):
                lb.tick(fresh_state(), bad, NOW)


class TestTokensSince(unittest.TestCase):
    def test_tokens_since_counts_input_cache_creation_and_output_and_skips_cache_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "t.jsonl"
            transcript.write_text("\n".join([
                usage_line(1, 10, 99999, 100),
                "this line is not json",
                usage_line(2, 20, 99999, 200),
            ]) + "\n", encoding="utf-8")
            self.assertEqual(lb.tokens_since(transcript, 0, 1000000), 333)

    def test_bytes_before_the_offset_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "t.jsonl"
            first = usage_line(1000, 0, 0, 0) + "\n"
            transcript.write_text(first + usage_line(1, 1, 0, 1) + "\n", encoding="utf-8")
            self.assertEqual(lb.tokens_since(transcript, len(first.encode()), 1000000), 3)

    def test_a_missing_or_oversized_transcript_is_unknown_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(lb.tokens_since(Path(tmp) / "absent.jsonl", 0, 1000))
            big = Path(tmp) / "big.jsonl"
            big.write_text(usage_line(1, 1, 1, 1) + "\n", encoding="utf-8")
            self.assertIsNone(lb.tokens_since(big, 0, 5))

    def test_an_offset_past_the_end_is_unknown(self):
        # R35 round 2: a transcript rewritten smaller than the saved offset counted 0 and the
        # budget silently stopped binding.
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "t.jsonl"
            transcript.write_text(usage_line(1, 1, 1, 1) + "\n", encoding="utf-8")
            self.assertIsNone(lb.tokens_since(transcript, 10 ** 6, 1000000))

    def test_a_message_written_as_several_records_is_counted_once(self):
        def rec(mid, inp, out):
            return json.dumps({"message": {"id": mid, "usage": {
                "input_tokens": inp, "output_tokens": out}}})
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp) / "t.jsonl"
            t.write_text("\n".join([rec("m1", 10, 5), rec("m1", 10, 5), rec("m1", 10, 7),
                                    rec("m2", 1, 1)]) + "\n", encoding="utf-8")
            self.assertEqual(lb.tokens_since(t, 0, 10 ** 6), 17 + 2)

    def test_status_survives_a_state_missing_keys(self):
        # R35 round 4: a hand-edited or older state raised KeyError instead of a report.
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            path = lb.state_path(repo)
            lb.save_state(path, "main", {"max_rounds": 3})
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = lb.main(["--cwd", str(repo), "--json", "status"])
            report = json.loads(buf.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(report["max_rounds"], 3)
        self.assertIsNone(report["plateau"])

    def test_from_plan_resolves_a_relative_path_against_cwd(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            (repo / "plans").mkdir()
            (repo / "plans" / "plan1.md").write_text(
                "---\nexecutor: cloud\ntier: simple\nbounds:\n  max_rounds: 2\n"
                "  max_tokens: 9\n  plateau: 1\n---\n- Create: `a.py`\n", encoding="utf-8")
            elsewhere = Path(tmp) / "elsewhere"
            elsewhere.mkdir()
            buf = io.StringIO()
            old = Path.cwd()
            os.chdir(elsewhere)
            try:
                with redirect_stdout(buf):
                    code = lb.main(["--cwd", str(repo), "--json", "init", "--from-plan",
                                    "plans/plan1.md"])
            finally:
                os.chdir(old)
            self.assertEqual(code, 0, buf.getvalue())


class TestCli(unittest.TestCase):
    def run_cli(self, *argv: str) -> tuple[int, dict]:
        """Run main() with --json and return the exit code and the parsed report."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = lb.main(list(argv))
        text = buf.getvalue().strip()
        return code, (json.loads(text) if text else {})

    def test_cli_dry_run_writes_nothing_and_a_real_init_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            base = ["--cwd", str(repo), "--json"]
            init = ["init", "--max-rounds", "3", "--max-tokens", "1500000", "--plateau", "2"]
            code, report = self.run_cli(*base, *init, "--dry-run")
            self.assertEqual(code, 0)
            self.assertTrue(report["dry_run"])
            self.assertFalse(lb.state_path(repo).exists())
            code, report = self.run_cli(*base, *init)
            self.assertEqual(code, 0)
            self.assertTrue(lb.state_path(repo).exists())
            code, report = self.run_cli(*base, *init)
            self.assertEqual(code, 2, "re-init over existing state needs --yes")
            code, report = self.run_cli(*base, *init, "--yes")
            self.assertEqual(code, 0)

    def test_json_report_has_the_keys_a_caller_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            base = ["--cwd", str(repo), "--json"]
            code, report = self.run_cli(*base, "status")
            self.assertEqual((code, report["initialised"]), (0, False))
            self.run_cli(*base, "init", "--max-rounds", "2", "--max-tokens", "9", "--plateau", "1")
            code, report = self.run_cli(*base, "status")
            for key in ("initialised", "branch", "max_rounds", "max_tokens", "plateau",
                        "invocations", "ticks", "tokens_used"):
                self.assertIn(key, report)
            code, report = self.run_cli(*base, "tick", "--findings", "4")
            self.assertEqual((code, report["findings"]), (0, 4))
            code, report = self.run_cli(*base, "check", "--skill", "code-review", "--record")
            self.assertEqual((code, report["allowed"]), (0, True))
            self.run_cli(*base, "check", "--skill", "code-review", "--record")
            code, report = self.run_cli(*base, "check", "--skill", "code-review")
            self.assertEqual((code, report["allowed"]), (2, False))
            self.assertIn("max_rounds", report["reason"])

    def test_cli_refuses_a_bad_bound_with_exit_2_and_outside_git_with_exit_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            code, _ = self.run_cli("--cwd", str(repo), "--json", "init", "--max-rounds", "0",
                                   "--max-tokens", "9", "--plateau", "1")
            self.assertEqual(code, 2)
            plain = Path(tmp) / "plain"
            plain.mkdir()
            code, _ = self.run_cli("--cwd", str(plain), "--json", "init", "--max-rounds", "1",
                                   "--max-tokens", "9", "--plateau", "1")
            self.assertEqual(code, 1)


class TestFromPlan(unittest.TestCase):
    run_cli = TestCli.run_cli

    HEADER = ("---\nexecutor: cloud\ntier: simple\nbounds:\n  max_rounds: {r}\n"
              "  max_tokens: 900000\n  plateau: 1\n---\n# Plan\n- Create: `a.py`\n")

    def test_init_from_plan_stores_the_plans_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            plan = repo / "plan1.md"
            plan.write_text(self.HEADER.format(r=4), encoding="utf-8")
            base = ["--cwd", str(repo), "--json"]
            code, report = self.run_cli(*base, "init", "--from-plan", str(plan))
            self.assertEqual(code, 0, report)
            state = lb.load_state(lb.state_path(repo), "main")
            self.assertEqual((state["max_rounds"], state["max_tokens"], state["plateau"]),
                             (4, 900000, 1))

    def test_init_from_plan_refuses_a_wrong_header_flags_with_it_and_nothing_at_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            plan = repo / "plan1.md"
            plan.write_text(self.HEADER.format(r='"4"'), encoding="utf-8")
            base = ["--cwd", str(repo), "--json"]
            code, report = self.run_cli(*base, "init", "--from-plan", str(plan))
            self.assertEqual(code, 2)
            self.assertIn("max_rounds", report["error"])
            plan.write_text(self.HEADER.format(r=4), encoding="utf-8")
            code, _ = self.run_cli(*base, "init", "--from-plan", str(plan), "--max-rounds", "2")
            self.assertEqual(code, 2)
            code, report = self.run_cli(*base, "init")
            self.assertEqual(code, 2)
            self.assertIn("--from-plan", report["error"])
            self.assertFalse(lb.state_path(repo).exists())


class TestRound1Findings(unittest.TestCase):
    """Fixes for the code review of 2026-10-17 (R35 round 1), each watched failing first."""

    def test_the_remedy_command_names_the_script_by_absolute_path(self):
        # The hook is installed globally, so a repo-relative remedy fails in every other
        # project: the command must point at the script that issued it.
        script = str(Path(lb.__file__).resolve())
        self.assertIn(script, lb.INIT_COMMAND)
        self.assertNotIn(" .claude/skills/", lb.INIT_COMMAND)
        allowed, reason = lb.decide(None, "code-review", None)
        self.assertIn(script, reason)

    def test_two_spellings_of_one_review_skill_share_one_counter(self):
        state = fresh_state(max_rounds=3)
        for name in ("code-review", "code-review:code-review", "/code-review"):
            lb.record_invocation(state, name)
        self.assertEqual(state["invocations"], {"code-review": 3})
        allowed, reason = lb.decide(state, "code-review:code-review", 0)
        self.assertFalse(allowed)
        self.assertIn("max_rounds", reason)
        self.assertTrue(lb.decide(state, "security-review", 0)[0])


class TestRound5Lock(unittest.TestCase):
    """R35 round 5: /code-review and /security-review hooks run in parallel, and an unlocked
    load-modify-save lost a count. The read-modify-write now runs under a lock file."""

    LOCK_CONFIG = dict(CONFIG,
                       lock_timeout_s={"value": 5, "provenance": "test fixture"},
                       lock_stale_s={"value": 30, "provenance": "test fixture"},
                       lock_poll_s={"value": 0.005, "provenance": "test fixture"})

    def test_parallel_read_modify_write_loses_no_count(self):
        import threading
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            lb.save_state(path, "main", fresh_state(max_rounds=999))

            def work():
                for _ in range(5):
                    with lb.state_lock(path, self.LOCK_CONFIG):
                        state = lb.load_state(path, "main")
                        lb.record_invocation(state, "code-review")
                        lb.save_state(path, "main", state)

            threads = [threading.Thread(target=work) for _ in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(lb.load_state(path, "main")["invocations"]["code-review"], 40)

    def test_a_stale_lock_is_reclaimed_and_a_live_one_times_out_unheld(self):
        import os
        import time
        config = dict(self.LOCK_CONFIG,
                      lock_timeout_s={"value": 0.05, "provenance": "test fixture"},
                      lock_stale_s={"value": 1, "provenance": "test fixture"})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            lock = path.with_name(path.name + ".lock")
            lock.write_text("x", encoding="utf-8")
            with lb.state_lock(path, config) as held:  # fresh lock: not ours, gives up
                self.assertFalse(held)
            self.assertTrue(lock.exists())
            old = time.time() - 60
            os.utime(lock, (old, old))
            with lb.state_lock(path, config) as held:  # stale lock: reclaimed
                self.assertTrue(held)
            self.assertFalse(lock.exists())

    def test_the_temporary_file_name_is_unique_per_process(self):
        import os
        seen = []
        real = os.replace
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            lb.os.replace = lambda src, dst: (seen.append(Path(src).name), real(src, dst))[1]
            try:
                lb.save_state(path, "main", fresh_state())
            finally:
                lb.os.replace = real
        self.assertEqual(len(seen), 1)
        self.assertIn(str(os.getpid()), seen[0])

    def test_the_shipped_config_declares_the_lock_keys(self):
        config = lb.load_config()
        for key in ("lock_timeout_s", "lock_stale_s", "lock_poll_s"):
            self.assertTrue(config[key]["provenance"], key)
            lb.config_value(config, key)


class TestConfig(unittest.TestCase):
    def test_a_missing_key_is_a_named_error(self):
        with self.assertRaises(KeyError) as ctx:
            lb.config_value({"git_timeout_s": {"value": 1}}, "state_file_name")
        self.assertIn("state_file_name", str(ctx.exception))

    def test_the_shipped_config_carries_every_key_with_provenance(self):
        config = lb.load_config()
        for key in ("state_file_name", "git_timeout_s", "transcript_scan_max_bytes"):
            self.assertTrue(config[key]["provenance"], key)
            lb.config_value(config, key)


if __name__ == "__main__":
    unittest.main()
