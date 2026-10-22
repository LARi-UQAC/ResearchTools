"""
test_manual_local_coding - chapter 12 of the manual ("Local coding and the cloud") and its
flowchart source (local coding contract, plan 9, R13, R14, R15, R20, R31, R33).

Offline, reads documentation only. No existing test covers the manual or the navigation, so this
one checks what none does: the chapter exists and is in `mkdocs.yml`, the README chapter table
and the landing page; its inline `mermaid` block is byte-identical to the `.mmd` source that
`code-style.md` asks to keep beside it; every ceiling it quotes equals the value in
`context-budget.json`, read here (a drift test); every relative link resolves; it names the four
execution paths and the unsupported and untried facts; it names no model tag (R2) and describes
no subagent on a local model; and its dated numbers carry a date.

Plan 10 extends this file. Each finder has its negative control (R20). It proves the chapter is
WRITTEN and consistent, never that it is the best explanation.
"""
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_memory_triggers import RULES as WORKFLOWS_RULES  # noqa: E402
from test_memory_triggers import read_table as memory_rows  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
CHAPTER = REPO / "docs" / "manual" / "10-local-coding.md"
DIAGRAM = REPO / "docs" / "manual" / "diagrams" / "local-coding-flow.mmd"
MKDOCS = REPO / "mkdocs.yml"
README = REPO / "README.md"
INDEX = REPO / "docs" / "index.md"
BUDGET = REPO / ".claude" / "skills" / "aider-setup" / "config" / "context-budget.json"

MODEL_TAG = re.compile(r"\b[a-z][a-z0-9._-]*:[0-9]+(?:\.[0-9]+)?b\b")
SUBAGENT_LOCAL = re.compile(
    r"\bsubagents?\b[^.]{0,40}\b(can|may|will)\b[^.]{0,30}\b(run|runs|use|uses)\b"
    r"[^.]{0,30}\b(local|ollama)\b", re.IGNORECASE)
LINK = re.compile(r"\]\(([^)\s]+)\)")
DATE = re.compile(r"\b20\d\d-\d\d-\d\d\b")
CEILING_KEYS = ("spec.md", "plan.md", "progress.md", "audit.md", "code_file")


def flat(text: str) -> str:
    """Collapse whitespace so a phrase wrapped across lines is still found."""
    return re.sub(r"\s+", " ", text)


def mermaid_block(text: str) -> str:
    """The body of the first fenced mermaid block of a text."""
    found = re.search(r"```mermaid\n(.*?)\n```", text, re.S)
    return found.group(1) if found else ""


def broken_links(text: str, base: Path) -> list:
    """Relative links (not URLs, not anchors only) whose target does not exist."""
    bad = []
    for target in LINK.findall(text):
        if re.match(r"[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
            continue
        if not (base / target.split("#")[0]).exists():
            bad.append(target)
    return bad


def section(text: str, heading: str) -> str:
    """The text of a level-2 section, from its heading to the next level-2 heading."""
    start = text.index("## " + heading)
    stop = text.find("\n## ", start + 4)
    return text[start:stop if stop != -1 else len(text)]


def table_values(text: str, keys) -> dict:
    """Values of table rows written as | `key` | number | in a text."""
    out = {}
    for key in keys:
        found = re.search(r"\|\s*`%s`\s*\|\s*([0-9 ]+?)\s*\|" % re.escape(key), text)
        out[key] = int(found.group(1).replace(" ", "")) if found else None
    return out


class TestChapter(unittest.TestCase):
    def setUp(self):
        self.text = CHAPTER.read_text(encoding="utf-8")

    def test_the_chapter_is_in_the_navigation_the_readme_and_the_landing_page(self):
        self.assertIn("manual/10-local-coding.md", MKDOCS.read_text(encoding="utf-8"))
        self.assertIn("docs/manual/10-local-coding.md", README.read_text(encoding="utf-8"))
        self.assertIn("manual/10-local-coding.md", INDEX.read_text(encoding="utf-8"))
        self.assertTrue(self.text.startswith("# Local coding and the cloud"))

    def test_the_inline_flowchart_is_byte_identical_to_the_mmd_source(self):
        source = DIAGRAM.read_text(encoding="utf-8").rstrip("\n")
        self.assertEqual(mermaid_block(self.text), source)
        self.assertTrue(source.startswith("flowchart TD"))
        for name in ("local-coder", "aider", "bounds", "owner merges"):
            self.assertIn(name, source)

    def test_every_quoted_ceiling_equals_the_budget_file(self):
        ceilings = json.loads(BUDGET.read_text(encoding="utf-8"))["ceilings"]
        quoted = table_values(section(self.text, "Size ceilings"), CEILING_KEYS)
        for key in CEILING_KEYS:
            with self.subTest(key=key):
                self.assertEqual(quoted[key], ceilings[key])

    def test_every_relative_link_resolves(self):
        self.assertEqual(broken_links(self.text, CHAPTER.parent), [])

    def test_the_four_paths_the_facts_and_the_hooks_are_named(self):
        body = flat(self.text)
        for phrase in ("executing-plans", "local-coder", "aider", "claude-switch.ps1",
                       "one API endpoint per process", "untried",
                       "does not support routing Claude Code to non-Claude models",
                       "CLAUDE_CODE_MAX_CONTEXT_TOKENS", "review-loop-guard.py",
                       "local-coder-dispatch-guard.py", "plan_contract.py",
                       "token_count.py", "context-budget.json", "loop_bounds.py"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, body)

    def test_the_262k_path_is_the_wrapper_plus_the_bridge_not_a_local_subagent(self):
        body = flat(self.text)
        self.assertIn("low-cost cloud model wrapper", body)
        self.assertIn("session role", body)
        self.assertIsNone(SUBAGENT_LOCAL.search(body))

    def test_no_model_tag_appears_in_the_chapter_or_the_diagram(self):
        for label, text in (("chapter", self.text),
                            ("diagram", DIAGRAM.read_text(encoding="utf-8"))):
            with self.subTest(where=label):
                self.assertIsNone(MODEL_TAG.search(text))

    def test_every_row_of_the_role_table_carries_a_date(self):
        rows = [line for line in section(self.text, "Roles, windows and speed").splitlines()
                if line.startswith("| ") and not line.startswith("| Tier")
                and not line.startswith("|---")]
        self.assertGreaterEqual(len(rows), 3)
        for row in rows:
            with self.subTest(row=row[:40]):
                self.assertRegex(row, DATE)


MANUAL = REPO / "docs" / "manual"
BEGIN, END = "<!-- local-coding:begin -->", "<!-- local-coding:end -->"
# Each neighbouring chapter: the names its added text must carry. "file" names must also exist
# in the repository (R14), "text" names are not files (a state file kept in a git directory,
# a snapshot section).
NEIGHBOURS = {
    "06-skills.md": {"plan_contract.py": "file", "token_count.py": "file",
                     "loop_bounds.py": "file"},
    "11-aider-pipeline.md": {"context-budget.json": "file", "plan-tiers.json": "file"},
    "12-rt-observe-dashboard.md": {"collect_local.py": "file", "collect_rounds.py": "file",
                                   "local_calls": "text", "rounds": "text"},
    "04-commands.md": {"loop_bounds.py": "file", "review-loop-guard.py": "file"},
    "16-file-locations.md": {"plan_contract.py": "file", "review-loop-guard.py": "file",
                             "local-coder-dispatch-guard.py": "file",
                             "plan-tiers.json": "file", "rt-review-loop.json": "text",
                             "10-local-coding.md": "file"},
}


def region(text: str) -> str:
    """The text a chapter carries between the local-coding markers, or an empty string."""
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        return ""
    return text[text.index(BEGIN) + len(BEGIN):text.index(END)]


def region_problems(text: str, names: dict, base: Path) -> list:
    """What is wrong with the added text of a neighbouring chapter, as a list of reasons."""
    added = region(text)
    if not added:
        return ["no local-coding region"]
    problems = []
    if "10-local-coding.md" not in LINK.findall(added) and not any(
            t.startswith("10-local-coding.md") for t in LINK.findall(added)):
        problems.append("no link to chapter 12")
    for name, kind in names.items():
        if name not in added:
            problems.append("does not name " + name)
        elif kind == "file" and not any(REPO.rglob(name)):
            problems.append(name + " does not exist in the repository")
    if MODEL_TAG.search(added):
        problems.append("names a model tag")
    problems += ["broken link " + b for b in broken_links(added, base)]
    return problems


# Model families that must not be named in the chapter or the figure: the process stays general
# for any cloud model (owner decision 2026-10-17). A list of data, extended when a family appears.
MODEL_FAMILIES = ("haiku", "sonnet", "opus", "fable", "gemini", "gpt", "qwen", "llama", "gemma",
                  "mistral", "tofino", "rosedale", "ossington", "deepseek", "grok")


def node_id(diagram: str, needle: str):
    """The id of the first node whose label holds `needle`, or None."""
    found = re.search(r"\b(\w+)[\[{][^\]}\n]*" + re.escape(needle), diagram)
    return found.group(1) if found else None


def has_edge(diagram: str, source, target, label: str = "") -> bool:
    """True when `source -- label --> target` appears, a chained edge included."""
    if not source or not target:
        return False
    middle = rf"--\s*{label}\s*-->" if label else r"-->"
    pattern = rf"\b{source}\b(?:[\[{{][^\n]*?[\]}}])?\s*{middle}\s*{target}\b"
    return re.search(pattern, diagram) is not None


def named_models(text: str) -> list:
    """The model families named in a text, as whole words."""
    return [m for m in MODEL_FAMILIES if re.search(rf"\b{m}\b", text, re.IGNORECASE)]


class TestProcessFigure(unittest.TestCase):
    """The defects the owner found in the figure on 2026-10-17, plus the silence rule."""

    def setUp(self):
        self.diagram = DIAGRAM.read_text(encoding="utf-8")
        self.text = CHAPTER.read_text(encoding="utf-8")

    def label_of(self, ident: str) -> str:
        return re.search(rf'\b{ident}\["([^"]*)"', self.diagram).group(1)

    def test_memory_is_consulted_before_the_brainstorm_through_local_writer(self):
        memory = node_id(self.diagram, "Consult both memories")
        brainstorm = node_id(self.diagram, "superpowers:brainstorming")
        self.assertIsNotNone(memory)
        self.assertTrue(has_edge(self.diagram, memory, brainstorm))
        for word in ("local-writer", "vault", "graph"):
            self.assertIn(word, self.label_of(memory))

    def test_the_loop_stops_on_safe_to_merge_and_a_bound_is_not_the_only_exit(self):
        safe = node_id(self.diagram, "Safe to merge")
        upkeep = node_id(self.diagram, "Memory upkeep")
        bound = node_id(self.diagram, "Bound reached")
        stop = node_id(self.diagram, "ask the owner")
        pull_request = node_id(self.diagram, "Pull request")
        self.assertTrue(all((safe, upkeep, bound, stop, pull_request)))
        self.assertTrue(has_edge(self.diagram, safe, upkeep, "yes"))
        self.assertTrue(has_edge(self.diagram, safe, bound, "no"))
        self.assertTrue(has_edge(self.diagram, bound, stop, "yes"))
        self.assertFalse(has_edge(self.diagram, bound, pull_request, "yes"))

    def test_the_last_step_writes_lessons_and_updates_the_graph_through_local_writer(self):
        upkeep = node_id(self.diagram, "Memory upkeep")
        self.assertTrue(has_edge(self.diagram, upkeep, node_id(self.diagram, "Pull request")))
        for word in ("local-writer", "vault", "graph"):
            self.assertIn(word, self.label_of(upkeep))

    def test_no_model_is_named_and_the_roles_are_general(self):
        for label, text in (("chapter", self.text), ("figure", self.diagram)):
            with self.subTest(where=label):
                self.assertEqual(named_models(text), [])
        body = flat(self.text)
        self.assertIn("low-cost cloud model", body)
        self.assertIn("edge cloud model", body)

    def test_the_chapter_states_the_endpoint_limit_once_and_generally(self):
        body = flat(self.text)
        self.assertEqual(body.count("has no endpoint of its own"), 1)

    def test_memory_is_silent_in_the_figure_and_the_chapter(self):
        self.assertIn("silent", self.diagram)
        self.assertIn("prints nothing in the chat", flat(self.text))

    def test_the_chapter_table_repeats_the_rule_rows(self):
        rows = memory_rows(WORKFLOWS_RULES.read_text(encoding="utf-8"))
        table = section(self.text, "When memory is read and written")
        for event, action, *_ in rows:
            with self.subTest(event=event):
                self.assertRegex(table, re.escape(event) + r"[^\n]*\|\s*" + re.escape(action))

    def test_the_figure_finders_can_fail(self):
        self.assertEqual(named_models("a Haiku wrapper and tofino"), ["haiku", "tofino"])
        self.assertEqual(named_models("a low-cost cloud model"), [])
        graph = 'A["x"] --> B\n    B -- yes --> C[go]'
        self.assertTrue(has_edge(graph, "B", "C", "yes"))
        self.assertFalse(has_edge(graph, "B", "C", "no"))
        self.assertIsNone(node_id(graph, "absent"))


AIDER_CHAPTER = REPO / "docs" / "manual" / "11-aider-pipeline.md"
AIDER_DEEP_DIVE = REPO / "docs" / "aider-setup.md"
AIDER_DIR = REPO / ".claude" / "skills" / "aider-setup"
RULES_HEADER = re.compile(r"^Rules: \d+ \(R0-R(\d+)\)", re.MULTILINE)


def says_orchestrator_product(text: str) -> bool:
    """True when a text names Claude Code, which a harness-neutral chapter must not."""
    return "Claude Code" in text


class TestAiderChapter(unittest.TestCase):
    """Chapter 06 after the local coding contract (request of the PR #84 session, 2026-10-17)."""

    def setUp(self):
        self.text = AIDER_CHAPTER.read_text(encoding="utf-8")
        self.body = flat(self.text)

    def test_the_chapter_and_the_deep_dive_name_no_orchestrating_product(self):
        self.assertFalse(says_orchestrator_product(self.text))
        self.assertFalse(says_orchestrator_product(AIDER_DEEP_DIVE.read_text(encoding="utf-8")))
        row = next(line for line in CHAPTER.read_text(encoding="utf-8").splitlines()
                   if line.startswith("| Two or more plans"))
        self.assertFalse(says_orchestrator_product(row))

    def test_local_coder_is_described_as_one_whole_plan(self):
        for phrase in ("one whole plan", "PLAN: <path>", "local-coder-dispatch-guard.py",
                       "audits nothing", "several plans"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.body)
        self.assertNotIn("single-step", self.body)

    def test_the_driver_ignores_the_header_and_the_named_things_exist(self):
        self.assertIn("neither validates nor uses", self.body)
        self.assertIn("Get-PlanTargets", self.body)
        core = AIDER_DIR / "scripts" / "aider-plan-core.ps1"
        self.assertTrue((AIDER_DIR / "scripts" / "Test" / "verify-aider-plan.ps1").exists())
        self.assertIn("function Get-PlanTargets", core.read_text(encoding="utf-8"))

    def test_the_review_bounds_do_not_govern_the_aider_loop(self):
        self.assertIn("do not govern", self.body)
        self.assertIn("never merges", self.body)

    def test_the_rules_coverage_is_the_one_the_generated_file_declares(self):
        header = RULES_HEADER.search((AIDER_DIR / "config" / "rules.md").read_text(encoding="utf-8"))
        self.assertIsNotNone(header)
        self.assertIn(f"R0 to R{header.group(1)}", self.body)
        self.assertNotIn("cannot drift", self.body)

    def test_the_overview_does_not_say_harness_twice(self):
        self.assertIn("independent local-coding pipeline that needs no interactive harness", self.body)

    def test_the_rules_paragraph_is_exact_about_abridging_and_the_missing_rules(self):
        # The generated file abridges only its longest rules, and R28 to R38 were never synced.
        header = (AIDER_DIR / "config" / "rules.md").read_text(encoding="utf-8")
        self.assertIn("Some rules are abridged", header)
        self.assertNotIn("one abridged entry per rule", self.body)
        self.assertIn("with the longest ones abridged", self.body)
        self.assertIn("the rules after R27, among them R35", self.body)

    def test_the_ceiling_table_equals_the_budget_file(self):
        ceilings = json.loads(BUDGET.read_text(encoding="utf-8"))["ceilings"]
        quoted = table_values(self.text, ("spec.md", "plan.md", "progress.md", "audit.md"))
        for key, value in quoted.items():
            with self.subTest(key=key):
                self.assertEqual(value, ceilings[key])

    def test_the_finder_can_fail(self):
        self.assertTrue(says_orchestrator_product("needs no Claude Code"))
        self.assertFalse(says_orchestrator_product("needs no interactive harness"))


class TestNeighbouringChapters(unittest.TestCase):
    def test_each_neighbour_links_to_chapter_12_and_names_what_exists(self):
        for name, names in NEIGHBOURS.items():
            with self.subTest(file=name):
                text = (MANUAL / name).read_text(encoding="utf-8")
                self.assertEqual(region_problems(text, names, MANUAL), [])

    def test_the_aider_chapter_quotes_the_ceilings_the_budget_file_holds(self):
        ceilings = json.loads(BUDGET.read_text(encoding="utf-8"))["ceilings"]
        added = region((MANUAL / "11-aider-pipeline.md").read_text(encoding="utf-8"))
        quoted = table_values(added, ("plan.md", "progress.md", "spec.md", "audit.md"))
        for key, value in quoted.items():
            with self.subTest(key=key):
                self.assertEqual(value, ceilings[key])

    def test_the_commands_chapter_no_longer_documents_the_unwired_budget_flag(self):
        text = (MANUAL / "04-commands.md").read_text(encoding="utf-8")
        self.assertNotIn("`/loopdev --budget <max_usd>", text)
        self.assertNotIn("`--budget` required", text)


class TestSkillForEveryStep(unittest.TestCase):
    """Owner decision D13 (2026-10-17): the process names a skill at each step."""

    STEPS = ("request", "plan files", "execution", "review", "pull request")

    def setUp(self):
        self.text = CHAPTER.read_text(encoding="utf-8")
        self.diagram = DIAGRAM.read_text(encoding="utf-8")

    def test_the_chapter_has_a_table_with_a_skill_for_every_step(self):
        body = section(self.text, "A skill for every step")
        rows = [line for line in body.splitlines() if line.startswith("| ")
                and not line.startswith("| Step") and not line.startswith("|---")]
        self.assertGreaterEqual(len(rows), len(self.STEPS))
        for step in self.STEPS:
            with self.subTest(step=step):
                found = [r for r in rows if r.lower().startswith("| " + step)]
                self.assertEqual(len(found), 1)
                cells = [c.strip() for c in found[0].strip("|").split("|")]
                self.assertTrue(cells[1], "no skill for the step " + step)
        for phrase in ("R36", "superpowers:brainstorming", "superpowers:writing-plans",
                       "superpowers:executing-plans", "speckit", "not installed or verified"):
            self.assertIn(phrase, flat(body))

    def test_the_flowchart_names_the_three_skills_on_their_nodes(self):
        for node, skill in (("A", "superpowers:brainstorming"),
                            ("D", "superpowers:writing-plans"),
                            ("H", "superpowers:executing-plans")):
            with self.subTest(node=node):
                self.assertRegex(self.diagram, r"\b%s\[[^\]]*%s" % (node, re.escape(skill)))

    def test_the_inline_block_still_equals_the_source(self):
        self.assertEqual(mermaid_block(self.text), self.diagram.rstrip("\n"))


class TestNegativeControls(unittest.TestCase):
    def test_the_region_checker_fails_without_a_link_a_name_or_a_region(self):
        names = {"loop_bounds.py": "file"}
        good = BEGIN + "See [chapter 12](10-local-coding.md): `loop_bounds.py`." + END
        self.assertEqual(region_problems(good, names, MANUAL), [])
        self.assertIn("no link to chapter 12",
                      region_problems(good.replace("](10-local-coding.md)", "]()"), names, MANUAL))
        self.assertIn("does not name loop_bounds.py",
                      region_problems(BEGIN + "[x](10-local-coding.md)" + END, names, MANUAL))
        self.assertEqual(region_problems("nothing", names, MANUAL), ["no local-coding region"])
        self.assertIn("no_such_script.py does not exist in the repository",
                      region_problems(BEGIN + "[x](10-local-coding.md) no_such_script.py" + END,
                                      {"no_such_script.py": "file"}, MANUAL))
        self.assertIn("names a model tag", region_problems(
            BEGIN + "[x](10-local-coding.md) loop_bounds.py vendor-a:9b" + END, names, MANUAL))

    def test_the_link_finder_can_fail(self):
        base = CHAPTER.parent
        self.assertEqual(broken_links("[x](00-purpose.md) [y](https://a.b) [z](#top)", base), [])
        self.assertEqual(broken_links("[gone](no-such-chapter.md#a)", base),
                         ["no-such-chapter.md#a"])

    def test_the_mermaid_finder_and_the_drift_comparison_can_fail(self):
        text = "x\n```mermaid\nflowchart TD\n    A --> B\n```\ny"
        self.assertEqual(mermaid_block(text), "flowchart TD\n    A --> B")
        self.assertNotEqual(mermaid_block(text.replace("B", "C")), "flowchart TD\n    A --> B")
        self.assertEqual(mermaid_block("no fence here"), "")

    def test_the_table_reader_and_the_tag_finder_can_fail(self):
        self.assertEqual(table_values("| `spec.md` | 4 000 |", ("spec.md", "plan.md")),
                         {"spec.md": 4000, "plan.md": None})
        self.assertIsNotNone(MODEL_TAG.search("run vendor-a:9b"))
        self.assertIsNone(DATE.search("measured recently"))


if __name__ == "__main__":
    unittest.main()
