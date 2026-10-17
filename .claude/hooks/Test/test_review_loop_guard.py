"""
test_review_loop_guard - the PreToolUse gate on the Skill tool that stops a review loop at the
bounds the owner declared (R35 as amended, local coding contract plan 2).

Offline. No network, no model. Every behavioural case runs the REAL hook as a subprocess
against a COPY of it in a temporary directory with a fixture config (the only way to stage the
R11 cases, since the hook reads its settings from a file beside itself) and a REAL temporary git
repository with fictitious identities (R34). Nothing is read from the machine (R21).

R20: both directions are asserted - the refusals, and the passes without which a hook that
refuses everything would look right (an unguarded skill, a call within bounds, a repository
outside git, a missing module, a missing or broken config, a malformed payload).

NOT VERIFIED here (R15): that Claude Code fires a PreToolUse matcher on the Skill tool at all
and the exact payload keys. Plan 2 task 1 checks the documentation and plan 11 asks for one live
firing. This suite proves what the hook does GIVEN the payload it expects.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
HOOK = REPO / ".claude" / "hooks" / "review-loop-guard.py"
SHIPPED_CONFIG = REPO / ".claude" / "hooks" / "review-loop-guard.json"
TEMPLATE = REPO / ".claude" / "settings.template.json"
LOOP_BOUNDS = REPO / ".claude" / "skills" / "loop-engineer" / "scripts" / "loop_bounds.py"
CONFIG_NAME = "review-loop-guard.json"
NOW = "2026-10-17T12:00:00+00:00"
GIT_ID = ["-c", "user.name=Wick, J.", "-c", "user.email=student@example.org"]

sys.path.insert(0, str(LOOP_BOUNDS.parent))
import loop_bounds as lb  # noqa: E402


def entry(value):
    """Wrap a value the way the shipped config does."""
    return {"value": value, "provenance": "test fixture"}


def fixture_config(**over):
    """A fixture config pointing at the real loop_bounds.py by absolute path."""
    config = {"enabled": entry(True),
              "guarded_skills": entry(["code-review", "security-review"]),
              "loop_bounds_candidates": entry([str(LOOP_BOUNDS)])}
    config.update(over)
    return config


def git(cwd, *args):
    """Run a real git command in a temporary repository."""
    return subprocess.run(["git", *GIT_ID, *args], cwd=cwd, capture_output=True, text=True,
                          timeout=30, check=True).stdout.strip()


def usage_line(inp, out):
    """One transcript record carrying a usage block."""
    return json.dumps({"message": {"usage": {"input_tokens": inp, "output_tokens": out}}})


class HookCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        (self.repo / "a.txt").write_text("a", encoding="utf-8")
        git(self.repo, "add", "a.txt")
        git(self.repo, "commit", "-m", "first")
        self.hook_dir = self.tmp / "hooks"
        self.hook_dir.mkdir()
        shutil.copy(HOOK, self.hook_dir / HOOK.name)
        self.write_config(fixture_config())
        self.config = lb.load_config()
        self.path = lb.state_path(self.repo, config=self.config)

    def write_config(self, config):
        """Write the fixture config beside the hook copy."""
        (self.hook_dir / CONFIG_NAME).write_text(json.dumps(config), encoding="utf-8")

    def declare(self, branch="main", transcript=None, **bounds):
        """Declare bounds for a branch through the real engine and return the state."""
        args = dict(max_rounds=3, max_tokens=1000, plateau=2)
        args.update(bounds)
        state = lb.init_state(branch, transcript=transcript, now_iso=NOW, **args)
        lb.save_state(self.path, branch, state)
        return state

    def stored(self, branch="main"):
        """Read the branch state back from disk."""
        return lb.load_state(self.path, branch)

    def run_hook(self, skill="code-review", cwd=None, payload=None, tool="Skill", **extra):
        """Run the copied hook with a PreToolUse payload and return (code, stdout, stderr)."""
        if payload is None:
            payload = {"tool_name": tool, "tool_input": {"skill": skill},
                       "cwd": str(cwd or self.repo), **extra}
        text = payload if isinstance(payload, str) else json.dumps(payload)
        done = subprocess.run([sys.executable, str(self.hook_dir / HOOK.name)], input=text,
                              capture_output=True, text=True, timeout=60)
        return done.returncode, done.stdout, done.stderr


class TestRefusals(HookCase):
    def test_no_bounds_declared_is_refused_and_names_the_init_command(self):
        code, _, err = self.run_hook()
        self.assertEqual(code, 2)
        self.assertIn('loop_bounds.py" init', err)

    def test_refused_when_invocations_reach_max_rounds(self):
        state = self.declare(max_rounds=2)
        lb.record_invocation(state, "code-review")
        lb.record_invocation(state, "code-review")
        lb.save_state(self.path, "main", state)
        code, _, err = self.run_hook()
        self.assertEqual(code, 2)
        self.assertIn("max_rounds", err)

    def test_refused_when_tokens_since_init_exceed_the_budget(self):
        transcript = self.tmp / "t.jsonl"
        transcript.write_text("", encoding="utf-8")
        self.declare(transcript=transcript, max_tokens=100)
        transcript.write_text(usage_line(90, 20) + "\n", encoding="utf-8")
        code, _, err = self.run_hook()
        self.assertEqual(code, 2)
        self.assertIn("max_tokens", err)

    def test_the_plugin_spelling_of_a_skill_shares_the_round_counter(self):
        # Code review 2026-10-17: each spelling had its own counter, so alternating them
        # allowed max_rounds times the number of spellings.
        self.write_config(fixture_config(
            guarded_skills=entry(["code-review", "code-review:code-review"])))
        self.declare(max_rounds=2)
        self.assertEqual(self.run_hook(skill="code-review")[0], 0)
        self.assertEqual(self.run_hook(skill="code-review:code-review")[0], 0)
        code, _, err = self.run_hook(skill="code-review")
        self.assertEqual(code, 2)
        self.assertIn("max_rounds", err)
        self.assertEqual(self.stored()["invocations"], {"code-review": 2})

    def test_a_namespaced_spelling_of_a_guarded_skill_is_guarded_too(self):
        # R35 round 2: `engineering:code-review` was not in guarded_skills and skipped the check.
        self.assertEqual(self.run_hook(skill="engineering:code-review")[0], 2)
        self.assertEqual(self.run_hook(skill="some-plugin:security-review")[0], 2)
        self.assertEqual(self.run_hook(skill="engineering:debug")[0], 0)

    def test_refused_on_plateau(self):
        state = self.declare(plateau=2)
        for count in (4, 4, 4):
            lb.tick(state, count, NOW)
        lb.save_state(self.path, "main", state)
        code, _, err = self.run_hook()
        self.assertEqual(code, 2)
        self.assertIn("plateau", err)

    def test_bounds_of_another_branch_are_not_used(self):
        self.declare()
        git(self.repo, "checkout", "-b", "other")
        code, _, err = self.run_hook()
        self.assertEqual(code, 2)
        self.assertIn('loop_bounds.py" init', err)


class TestPasses(HookCase):
    def test_unguarded_skill_passes(self):
        self.assertEqual(self.run_hook(skill="brainstorming")[0], 0)

    def test_another_tool_passes(self):
        self.assertEqual(self.run_hook(tool="Bash")[0], 0)

    def test_a_leading_slash_on_the_skill_name_is_still_guarded(self):
        self.assertEqual(self.run_hook(skill="/code-review")[0], 2)

    def test_guarded_skill_within_bounds_passes_and_counts_one_invocation(self):
        self.declare()
        code, out, err = self.run_hook()
        self.assertEqual((code, out, err), (0, "", ""))
        self.assertEqual(self.stored()["invocations"], {"code-review": 1})

    def test_a_refused_call_does_not_consume_a_round(self):
        state = self.declare(max_rounds=1)
        lb.record_invocation(state, "code-review")
        lb.save_state(self.path, "main", state)
        self.assertEqual(self.run_hook()[0], 2)
        self.assertEqual(self.stored()["invocations"], {"code-review": 1})

    def test_the_first_allowed_call_adopts_the_payload_transcript_as_the_baseline(self):
        self.declare()
        transcript = self.tmp / "t.jsonl"
        transcript.write_text(usage_line(5000, 0) + "\n", encoding="utf-8")
        self.assertEqual(self.run_hook(transcript_path=str(transcript))[0], 0)
        state = self.stored()
        self.assertEqual(state["transcript"], str(transcript))
        self.assertEqual(state["transcript_offset"], transcript.stat().st_size)

    def test_outside_a_git_repository_passes_in_silence(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        self.assertEqual(self.run_hook(cwd=plain), (0, "", ""))

    def test_missing_loop_bounds_module_passes_in_silence(self):
        self.write_config(fixture_config(loop_bounds_candidates=entry([str(self.tmp / "no.py")])))
        self.assertEqual(self.run_hook(), (0, "", ""))

    def test_unreadable_transcript_passes(self):
        self.declare(transcript=self.tmp / "gone.jsonl", max_tokens=1)
        self.assertEqual(self.run_hook()[0], 0)

    def test_malformed_payload_passes(self):
        for bad in ("not json", "[]", "{}", json.dumps({"tool_name": "Skill"}),
                    json.dumps({"tool_name": "Skill", "tool_input": "x"})):
            with self.subTest(bad=bad):
                self.assertEqual(self.run_hook(payload=bad), (0, "", ""))

    def test_disabled_config_passes(self):
        self.write_config(fixture_config(enabled=entry(False)))
        self.assertEqual(self.run_hook(), (0, "", ""))

    def test_missing_or_unparsable_config_passes_in_silence(self):
        (self.hook_dir / CONFIG_NAME).write_text("{broken", encoding="utf-8")
        self.assertEqual(self.run_hook(), (0, "", ""))
        (self.hook_dir / CONFIG_NAME).unlink()
        self.assertEqual(self.run_hook(), (0, "", ""))
        self.write_config({"enabled": entry(True)})
        self.assertEqual(self.run_hook(), (0, "", ""))


class TestShippedFiles(unittest.TestCase):
    def test_the_shipped_config_parses_and_carries_provenance_on_every_key(self):
        config = json.loads(SHIPPED_CONFIG.read_text(encoding="utf-8"))
        for key in ("enabled", "guarded_skills", "loop_bounds_candidates"):
            self.assertTrue(config[key]["provenance"], key)
        self.assertIn("code-review", config["guarded_skills"]["value"])
        self.assertIn("security-review", config["guarded_skills"]["value"])

    def test_template_declares_the_hook_on_the_skill_matcher_only(self):
        template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
        found = [group for group in template["hooks"]["PreToolUse"]
                 if any("review-loop-guard.py" in h["command"] for h in group["hooks"])]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["matcher"], "Skill")


if __name__ == "__main__":
    unittest.main()
