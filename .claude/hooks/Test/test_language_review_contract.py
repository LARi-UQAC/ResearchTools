"""
test_language_review_contract - documentation test for the language-review migration (Issue #104, plan 2).

Proves the five research agents and manual chapter 04 point to the language-review skill instead of
restating a language table, that every language flag each agent printed before the migration is still
printed and still defined in the table (no behaviour change), and that reviewer-response still
classifies every content code. It proves the text is written, never that a model obeys it (R15).
Fixture text for the negative control is fictitious (R34).
"""

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SKILL = REPO / ".claude" / "skills" / "language-review"
sys.path.insert(0, str(SKILL / "scripts"))

import lang_table_check as ltc  # noqa: E402

TABLE = SKILL / "assets" / "language_categories.json"
AGENTS = ("paper-auditor", "thesis-auditor", "thesis-proposal-auditor", "scopus-auditor",
          "reviewer-response")
POINTER = ".claude/skills/language-review/"
CONTENT_CODES = ("SC", "M", "R", "D", "FT", "EQ", "REF", "Q", "MAJ")
# The composition flags each auditor printed before the migration (snapshot 2026-11-05, plan 2 step 1).
COMPOSITION_FLAGS = {
    "ACTIVE VOICE UNJUSTIFIED", "PRONOUN I FORBIDDEN", "PRONOUN WE OUT OF SCOPE",
    "INFORMAL LANGUAGE", "SEMICOLON IN PROSE", "SENTENCE TOO LONG", "SENTENCE FRAGMENT",
    "LIST IN PROSE SECTION", "CONTRIBUTIONS AS LIST",
}
BEFORE = {name: COMPOSITION_FLAGS for name in AGENTS[:4]}
BEFORE["reviewer-response"] = set()


def _agent(name: str) -> str:
    """Purpose: read one agent definition. Inputs: name (str). Outputs: text (str)."""
    return (REPO / ".claude" / "agents" / f"{name}.md").read_text(encoding="utf-8")


def _language_rows(text: str, codes: set[str]) -> list[str]:
    """
    Purpose: find Markdown table rows whose first cell is a language code.
    Inputs: text (str); codes (set[str]) language codes, G and S included.
    Outputs: rows (list[str]) offending lines.
    """
    rows = []
    for line in text.splitlines():
        match = re.match(r"^\|\s*([A-Z]{1,6})\s*\|", line)
        if match and match.group(1) in codes:
            rows.append(line)
    return rows


class ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.table = ltc.load_table(TABLE)
        self.codes = {entry["code"] for entry in self.table} | {"G", "S"}

    def test_each_agent_points_to_the_language_skill(self) -> None:
        for name in AGENTS:
            text = _agent(name)
            self.assertIn(POINTER, text, name)
            self.assertIn("language_categories.json", text, name)

    def test_no_agent_restates_the_language_table(self) -> None:
        for name in AGENTS:
            self.assertEqual(_language_rows(_agent(name), self.codes), [], name)

    def test_every_flag_an_agent_prints_is_in_the_table(self) -> None:
        for name in AGENTS:
            text = _agent(name)
            self.assertEqual(ltc.unknown_flags(text, self.table), set(), name)
            self.assertEqual(ltc.flags_in(text, self.table), BEFORE[name], name)

    def test_rule_numbers_and_actions_are_unchanged(self) -> None:
        by_flag = {e["flag"]: e for e in self.table if e["flag"]}
        expected = {"ACTIVE VOICE UNJUSTIFIED": "R1.2", "PRONOUN I FORBIDDEN": "R1.4",
                    "PRONOUN WE OUT OF SCOPE": "R1.5", "INFORMAL LANGUAGE": "R1.6",
                    "SEMICOLON IN PROSE": "R1.7", "SENTENCE TOO LONG": "R1.8",
                    "SENTENCE FRAGMENT": "R2.4", "LIST IN PROSE SECTION": "R2.6",
                    "CONTRIBUTIONS AS LIST": "R2.7"}
        for flag, rule in expected.items():
            self.assertEqual(by_flag[flag]["rule"], rule, flag)
            self.assertEqual(by_flag[flag]["latex_action"], "replaced", flag)
        direct = {e["code"] for e in self.table if e["latex_action"] == "direct_fix"}
        self.assertEqual(direct, {"SP", "AG", "PN", "TYPO"})

    def test_reviewer_response_still_classifies_content_codes(self) -> None:
        text = _agent("reviewer-response")
        for code in CONTENT_CODES:
            self.assertRegex(text, rf"(?m)^\|\s*{code}\s*\|", code)

    def test_chapter_04_points_to_the_skill_instead_of_the_table(self) -> None:
        text = (REPO / "docs" / "manual" / "04-commands.md").read_text(encoding="utf-8")
        self.assertIn("language-review", text)
        self.assertEqual(_language_rows(text, self.codes), [])
        for code in CONTENT_CODES:
            self.assertRegex(text, rf"(?m)^\|\s*{code}\s*\|", code)

    def test_the_finder_reports_a_planted_unknown_flag(self) -> None:
        planted = "## Section P - Composition\n\n**Issue:** [SEMICOLON IN PROSE / RUN-ON WORDING]\n"
        self.assertEqual(ltc.unknown_flags(planted, self.table), {"RUN-ON WORDING"})
        self.assertEqual(_language_rows("| G | Grammar |\n| SC | x |", self.codes), ["| G | Grammar |"])


if __name__ == "__main__":
    unittest.main()
