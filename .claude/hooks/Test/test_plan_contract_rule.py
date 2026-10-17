"""
test_plan_contract_rule - rule R38 (a coding request beyond a single step gets plan files with a
header before any code) and the new `local-coder` procedure are WRITTEN where every project
reads them (local coding contract, plan 5, task 1, R15).

Offline, reads documentation only. The contract binds every project once ResearchTools is
installed, so it must live in `.claude/rules/workflows.md`, inside the RT-EXPORT region of
`.claude/CLAUDE.md` (exported to other projects), in the agent definition, and in the rule
index. This suite fails when R38 disappears from one of them, when the stale R26 size table
returns, when the routing row goes back to "do not dispatch at all", or when a model tag
appears in a definition file (R2).

Scope, stated rather than hidden: it proves the contract is WRITTEN. It cannot prove a model
obeyed it, which is the job of the two hooks. Every finder has its negative control (R20).
"""
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO / ".claude" / "rules" / "workflows.md"
CODE_STYLE = REPO / ".claude" / "rules" / "code-style.md"
CLAUDE_MD = REPO / ".claude" / "CLAUDE.md"
AGENT = REPO / ".claude" / "agents" / "local-coder.md"
LOOPDEV = REPO / ".claude" / "commands" / "loopdev.md"
SKILLS = ("superpowers:brainstorming", "superpowers:writing-plans",
          "superpowers:executing-plans")

MODEL_TAG = re.compile(r"\b[a-z][a-z0-9._-]*:[0-9]+(?:\.[0-9]+)?b\b")


def flat(text: str) -> str:
    """Collapse whitespace so a phrase wrapped across lines is still found."""
    return re.sub(r"\s+", " ", text)


def block(text: str, start: str, end: str) -> str:
    """The text from a start marker to the next end marker (or the end of the text)."""
    begin = text.index(start)
    stop = text.find(end, begin + len(start))
    return text[begin:stop if stop != -1 else len(text)]


def r38(text: str) -> str:
    """The R38 block of workflows.md, up to the next level-2 heading."""
    return block(text, "**R38", "\n## ")


def r26(text: str) -> str:
    """The R26 block of workflows.md, up to the next rule."""
    return block(text, "**R26", "\n**R29")


def export_region(text: str) -> str:
    """The text between the RT-EXPORT markers of .claude/CLAUDE.md."""
    return block(text, "<!-- RT-EXPORT:BEGIN -->", "<!-- RT-EXPORT:END -->")


class TestRuleIsWritten(unittest.TestCase):
    def setUp(self):
        self.workflows = WORKFLOWS.read_text(encoding="utf-8")
        self.claude = CLAUDE_MD.read_text(encoding="utf-8")
        self.agent = AGENT.read_text(encoding="utf-8")

    def test_r38_is_named_in_the_three_places_every_project_reads(self):
        self.assertIn("**R38", self.workflows)
        self.assertIn("R38", export_region(self.claude))
        self.assertIn("R38", self.agent)

    def test_r38_states_the_plan_before_code_requirement_and_the_five_rows(self):
        body = flat(r38(self.workflows))
        for phrase in ("before any code", "executing-plans", "simple or standard", "large",
                       "aider", "manual", "header"):
            self.assertIn(phrase, body)

    def test_r38_binds_every_project_and_names_both_hooks(self):
        body = flat(r38(self.workflows))
        self.assertIn("every project", body)
        self.assertIn("review-loop-guard.py", body)
        self.assertIn("local-coder-dispatch-guard.py", body)
        self.assertIn("docs/superpowers/todo/", body)
        self.assertIn("docs/superpowers/done/", body)

    def test_the_agent_is_a_plan_procedure_with_no_audit_inside(self):
        body = flat(self.agent)
        for phrase in ("plan_contract.py resolve", "PLAN:", "progress.md", "- [ ]", "- [x]",
                       "- [!]", "no audit"):
            self.assertIn(phrase, body)

    def test_the_agent_passes_the_plan_to_the_bridge_so_the_log_names_it(self):
        # Code review 2026-10-17: the bridge gained --plan for the dashboard, but the
        # agent's own bridge command never passed it, so every record said plan null.
        command = [line for line in self.agent.splitlines() if "ollama_bridge.py" in line
                   and "--prompt-file" in line]
        self.assertEqual(len(command), 1)
        self.assertIn("--plan", command[0])

    def test_the_code_style_index_lists_r38(self):
        index = flat(CODE_STYLE.read_text(encoding="utf-8"))
        self.assertRegex(index, r"R36 and R37 and R38|R37 and R38|R38")

    def test_the_stale_r26_size_table_is_gone_and_points_at_the_budget_file(self):
        body = r26(self.workflows)
        self.assertNotIn("8 000", body)
        self.assertNotIn("12 000", body)
        self.assertIn("context-budget.json", body)

    def test_the_routing_row_no_longer_says_do_not_dispatch_at_all(self):
        row = next(line for line in self.claude.splitlines()
                   if line.startswith("| ") and "`local-coder` agent (haiku" in line)
        self.assertNotIn("do not dispatch this agent at all", row)
        self.assertNotIn("Local code generation against a spec", row)
        self.assertIn("PLAN:", row)

    def test_the_export_region_carries_a_section_on_the_plan_contract(self):
        region = flat(export_region(self.claude))
        for phrase in ("plan files", "executor", "tier", "plan_contract.py"):
            self.assertIn(phrase, region)

    def test_no_model_tag_appears_in_the_definition_files(self):
        for label, text in (("agent", self.agent), ("r38", r38(self.workflows)),
                            ("export", export_region(self.claude))):
            with self.subTest(where=label):
                self.assertIsNone(MODEL_TAG.search(text), label)


def missing_skill_note(text: str) -> list:
    """What a process description lacks of the skill-per-step note: the three skills named, R36
    cited as the basis, a skill for each step and any task, and a similar toolset allowed."""
    body = flat(text)
    wanted = list(SKILLS) + ["R36", "each step", "speckit"]
    return [phrase for phrase in wanted if phrase not in body]


class TestSkillForEveryStep(unittest.TestCase):
    """Owner decision D13, 2026-10-17: every step of the process uses a skill (R36 says all
    tasks, any task, need one): brainstorming for the request, writing-plans for the plan
    files, executing-plans for the execution. A similar toolset such as speckit may replace
    them, and the skill is still named."""

    def test_r38_the_export_region_and_loopdev_carry_the_note(self):
        workflows = WORKFLOWS.read_text(encoding="utf-8")
        claude = CLAUDE_MD.read_text(encoding="utf-8")
        for label, text in (("R38", r38(workflows)), ("export", export_region(claude)),
                            ("loopdev", LOOPDEV.read_text(encoding="utf-8"))):
            with self.subTest(where=label):
                self.assertEqual(missing_skill_note(text), [])

    def test_the_note_says_ruflow_is_not_verified_rather_than_naming_it_as_a_tool(self):
        body = flat(r38(WORKFLOWS.read_text(encoding="utf-8")))
        self.assertIn("ruflow", body)
        self.assertIn("not installed or verified", body)

    def test_the_finder_can_fail(self):
        full = " ".join(SKILLS) + " R36 each step speckit"
        self.assertEqual(missing_skill_note(full), [])
        for name in SKILLS:
            self.assertEqual(missing_skill_note(full.replace(name, "x")), [name])
        self.assertEqual(missing_skill_note(full.replace("R36", "x")), ["R36"])


class TestNegativeControls(unittest.TestCase):
    def test_the_tag_finder_can_fail(self):
        self.assertIsNotNone(MODEL_TAG.search("run vendor-a:9b today"))
        self.assertIsNotNone(MODEL_TAG.search("model qwen3:8b"))
        self.assertIsNone(MODEL_TAG.search("a port such as localhost:8080 is fine"))

    def test_the_block_helpers_stop_at_their_boundaries(self):
        text = "x **R38 - a** body\n\n## Next\nafter"
        self.assertNotIn("after", r38(text))
        marked = "pre <!-- RT-EXPORT:BEGIN --> in <!-- RT-EXPORT:END --> post"
        self.assertNotIn("post", export_region(marked))
        table = "**R26 - x** | 8 000 |\n\n**R29 - y** 12 000"
        self.assertNotIn("12 000", r26(table))


if __name__ == "__main__":
    unittest.main()
