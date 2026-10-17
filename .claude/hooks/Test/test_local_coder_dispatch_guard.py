"""
test_local_coder_dispatch_guard - the PreToolUse gate on the Agent tool that refuses a
`local-coder` dispatch with no valid plan (local coding contract, plan 3 task 2).

Offline. Every behavioural case runs the REAL hook as a subprocess against a COPY of it in a
temporary directory with a fixture config, a fixture tier table, a fixture budget and a fixture
resolver module, inside a real temporary git repository with fictitious identities (R34). Nothing
is read from the machine and no model is asked (R21).

R20: both directions are asserted - the refusals, and the passes without which a hook that
refuses everything would look right.

NOT VERIFIED here (R15): that Claude Code fires a PreToolUse matcher on the Agent tool (the docs
name the matcher `Agent` and the keys `subagent_type` and `prompt`), which plan 11 checks live.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
HOOK = REPO / ".claude" / "hooks" / "local-coder-dispatch-guard.py"
SHIPPED_CONFIG = REPO / ".claude" / "hooks" / "local-coder-dispatch-guard.json"
TEMPLATE = REPO / ".claude" / "settings.template.json"
SKILL = REPO / ".claude" / "skills" / "loop-engineer"
PLAN_CONTRACT = SKILL / "scripts" / "plan_contract.py"
SHIPPED_TIERS = SKILL / "plan-tiers.json"
CONFIG_NAME = "local-coder-dispatch-guard.json"
GIT_ID = ["-c", "user.name=Wick, J.", "-c", "user.email=student@example.org"]

RESOLVER_SOURCE = '''
def resolve(role, require_role=False):
    if role == "coder":
        return "vendor-a:9b"
    raise RuntimeError("no qualified model for role " + role)
'''


def entry(value):
    """Wrap a value the way the shipped config does."""
    return {"value": value, "provenance": "test fixture"}


def plan_text(executor="local-coder", tier="simple", rounds="3"):
    """A fictitious plan with a valid header unless a value is overridden."""
    return (f"---\nexecutor: {executor}\ntier: {tier}\nbounds:\n  max_rounds: {rounds}\n"
            "  max_tokens: 1500000\n  plateau: 2\n---\n# Plan 1 - fictitious\n"
            "- Create: `src/mod.py`\n")


class DispatchCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = self.tmp / "repo"
        (self.repo / "plans").mkdir(parents=True)
        for cmd in (["init", "-b", "main"],):
            subprocess.run(["git", *GIT_ID, *cmd], cwd=self.repo, check=True,
                           capture_output=True, timeout=30)
        self.hook_dir = self.tmp / "hooks"
        self.hook_dir.mkdir()
        shutil.copy(HOOK, self.hook_dir / HOOK.name)
        (self.tmp / "resolver.py").write_text(RESOLVER_SOURCE, encoding="utf-8")
        self.budget = self.tmp / "budget.json"
        self.set_ceilings({"spec.md": 4000, "plan.md": 4000, "progress.md": 2048,
                           "audit.md": 4096, "code_file": 16000})
        tiers = json.loads(SHIPPED_TIERS.read_text(encoding="utf-8"))
        tiers["budget_candidates"] = {"value": [str(self.budget)], "provenance": "fixture"}
        self.tiers = self.tmp / "tiers.json"
        self.tiers.write_text(json.dumps(tiers), encoding="utf-8")
        self.write_config()

    def set_ceilings(self, ceilings):
        """Write the fixture budget file."""
        self.budget.write_text(json.dumps({"ceilings": ceilings}), encoding="utf-8")

    def write_config(self, **over):
        """Write the fixture config beside the hook copy."""
        config = {"enabled": entry(True), "guarded_agents": entry(["local-coder"]),
                  "plan_line_prefix": entry("PLAN:"),
                  "plan_contract_candidates": entry([str(PLAN_CONTRACT)]),
                  "tiers_candidates": entry([str(self.tiers)]),
                  "resolver_module": entry(str(self.tmp / "resolver.py"))}
        config.update(over)
        (self.hook_dir / CONFIG_NAME).write_text(json.dumps(config), encoding="utf-8")

    def plan(self, text=None, name="plan1.md") -> Path:
        """Write a plan inside the repository and return its path."""
        path = self.repo / "plans" / name
        path.write_text(plan_text() if text is None else text, encoding="utf-8")
        return path

    def run_hook(self, prompt=None, agent="local-coder", payload=None, tool="Agent"):
        """Run the copied hook and return (code, stdout, stderr)."""
        if payload is None:
            payload = {"tool_name": tool, "cwd": str(self.repo),
                       "tool_input": {"subagent_type": agent, "prompt": prompt or "do it"}}
        text = payload if isinstance(payload, str) else json.dumps(payload)
        done = subprocess.run([sys.executable, str(self.hook_dir / HOOK.name)], input=text,
                              capture_output=True, text=True, timeout=60)
        return done.returncode, done.stdout, done.stderr

    def dispatch(self, path):
        """Dispatch local-coder with a prompt naming the plan file."""
        return self.run_hook(prompt=f"Implement the plan.\nPLAN: {path}\nThanks.")


class TestRefusals(DispatchCase):
    def test_no_plan_line_is_refused_and_names_the_line_to_add(self):
        code, _, err = self.run_hook(prompt="please write a function")
        self.assertEqual(code, 2)
        self.assertIn("PLAN:", err)

    def test_a_plan_path_outside_the_repository_is_refused(self):
        with tempfile.TemporaryDirectory() as other:
            outside = Path(other) / "plan1.md"
            outside.write_text(plan_text(), encoding="utf-8")
            code, _, err = self.dispatch(outside)
        self.assertEqual(code, 2)
        self.assertIn("outside", err)

    def test_a_missing_plan_file_is_refused(self):
        code, _, err = self.dispatch(self.repo / "plans" / "absent.md")
        self.assertEqual(code, 2)
        self.assertIn("not found", err)

    def test_an_invalid_header_is_refused_with_the_contract_message(self):
        code, _, err = self.dispatch(self.plan(plan_text(rounds='"3"')))
        self.assertEqual(code, 2)
        self.assertIn("max_rounds", err)

    def test_a_plan_over_its_size_ceiling_is_refused(self):
        self.set_ceilings({"spec.md": 4000, "plan.md": 5, "progress.md": 2048,
                           "audit.md": 4096, "code_file": 16000})
        code, _, err = self.dispatch(self.plan())
        self.assertEqual(code, 2)
        self.assertIn("ceiling", err)

    def test_a_plan_whose_executor_is_not_local_coder_is_refused(self):
        code, _, err = self.dispatch(self.plan(plan_text(executor="aider")))
        self.assertEqual(code, 2)
        self.assertIn("aider", err)

    def test_a_plan_that_resolves_to_the_cloud_is_refused_with_the_reason(self):
        code, _, err = self.dispatch(self.plan(plan_text(tier="large")))
        self.assertEqual(code, 2)
        self.assertIn("no qualified model for role session", err)


class TestPasses(DispatchCase):
    def test_a_valid_plan_passes(self):
        self.assertEqual(self.dispatch(self.plan()), (0, "", ""))

    def test_a_relative_plan_path_is_resolved_against_the_payload_cwd(self):
        self.plan()
        self.assertEqual(self.run_hook(prompt="PLAN: plans/plan1.md"), (0, "", ""))

    def test_another_agent_type_passes(self):
        for agent in ("local-writer", "Explore", "general-purpose"):
            with self.subTest(agent=agent):
                self.assertEqual(self.run_hook(agent=agent), (0, "", ""))

    def test_another_tool_passes(self):
        self.assertEqual(self.run_hook(tool="Bash"), (0, "", ""))

    def test_missing_plan_contract_module_passes_in_silence(self):
        self.write_config(plan_contract_candidates=entry([str(self.tmp / "no.py")]))
        self.assertEqual(self.run_hook(prompt="no plan line"), (0, "", ""))

    def test_missing_tier_file_passes_in_silence(self):
        self.write_config(tiers_candidates=entry([str(self.tmp / "no.json")]))
        self.assertEqual(self.run_hook(prompt="no plan line"), (0, "", ""))

    def test_a_missing_budget_skips_the_ceilings_but_still_judges_the_header(self):
        self.budget.unlink()
        self.assertEqual(self.dispatch(self.plan()), (0, "", ""))
        self.assertEqual(self.dispatch(self.plan(plan_text(tier="huge"), "plan2.md"))[0], 2)

    def test_disabled_or_missing_or_broken_config_passes_in_silence(self):
        self.write_config(enabled=entry(False))
        self.assertEqual(self.run_hook(prompt="no plan line"), (0, "", ""))
        (self.hook_dir / CONFIG_NAME).write_text("{broken", encoding="utf-8")
        self.assertEqual(self.run_hook(prompt="no plan line"), (0, "", ""))
        (self.hook_dir / CONFIG_NAME).unlink()
        self.assertEqual(self.run_hook(prompt="no plan line"), (0, "", ""))

    def test_malformed_payload_passes(self):
        for bad in ("not json", "[]", "{}", json.dumps({"tool_name": "Agent"}),
                    json.dumps({"tool_name": "Agent", "tool_input": "x"})):
            with self.subTest(bad=bad):
                self.assertEqual(self.run_hook(payload=bad), (0, "", ""))

    def test_a_guarded_dispatch_with_no_prompt_at_all_is_still_refused(self):
        payload = {"tool_name": "Agent", "cwd": str(self.repo),
                   "tool_input": {"subagent_type": "local-coder"}}
        self.assertEqual(self.run_hook(payload=payload)[0], 2)


class TestShippedFiles(unittest.TestCase):
    def test_the_shipped_config_carries_provenance_on_every_key(self):
        config = json.loads(SHIPPED_CONFIG.read_text(encoding="utf-8"))
        for key in ("enabled", "guarded_agents", "plan_line_prefix", "plan_contract_candidates",
                    "tiers_candidates", "resolver_module"):
            self.assertTrue(config[key]["provenance"], key)
        self.assertIsNone(config["resolver_module"]["value"])
        self.assertEqual(config["guarded_agents"]["value"], ["local-coder"])

    def test_template_declares_the_hook_on_the_verified_matcher(self):
        template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
        found = [group for group in template["hooks"]["PreToolUse"]
                 if any("local-coder-dispatch-guard.py" in h["command"] for h in group["hooks"])]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["matcher"], "Agent")


if __name__ == "__main__":
    unittest.main()
