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
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CHAPTER = REPO / "docs" / "manual" / "12-local-coding.md"
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
        self.assertIn("manual/12-local-coding.md", MKDOCS.read_text(encoding="utf-8"))
        self.assertIn("docs/manual/12-local-coding.md", README.read_text(encoding="utf-8"))
        self.assertIn("manual/12-local-coding.md", INDEX.read_text(encoding="utf-8"))
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
        self.assertIn("Haiku wrapper", body)
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


class TestNegativeControls(unittest.TestCase):
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
