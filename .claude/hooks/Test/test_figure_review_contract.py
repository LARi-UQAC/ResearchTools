"""
Documentation contract of plan 10 (Issue #104): the four auditors and /tikz take their figure checks from the
figure-review skill instead of carrying their own lists. It proves the rule is written where each reader
looks, never that a model obeyed it (R15).

Each finder has a negative control on fictitious text, since a check that cannot fail proves nothing (R20).
"""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SKILL = ROOT / ".claude" / "skills" / "figure-review"
sys.path.insert(0, str(SKILL / "scripts"))

import figure_checks

AUDITORS = ("paper-auditor", "thesis-auditor", "thesis-proposal-auditor", "scopus-auditor")
FIGURE_STEP = {
    "paper-auditor": "### Step 4.5",
    "thesis-auditor": "### Step 9",
    "thesis-proposal-auditor": "### Step 9",
}
# The figure flags the auditors printed before the migration (snapshot of 2026-11-14, read from the four
# figure steps). Every one must stay reachable. [TABLE DETAIL NOT IN TABLENOTES] concerns tables only.
FLAGS_BEFORE = {
    "NOT CITED", "CITATION FAR", "INSUFFICIENT DESCRIPTION", "LOW RESOLUTION", "IMAGE FILE MISSING",
    "CAPTION MULTI-SENTENCE", "CAPTION NOT A SENTENCE", "CAPTION CARRIES EXPLANATION", "FIGURE NUMBERING WRONG",
}
TABLE_ONLY_FLAGS = {"TABLE DETAIL NOT IN TABLENOTES"}
# Fragments of the TikZ rule list. They live in figure_criteria.json now and nowhere else.
TIKZ_RULE_FRAGMENTS = ("node distance", "perpendicular", "align=center", "3-character", "on background layer")
TIKZ_IDS = ("tikz_node_line_breaks", "tikz_backgrounds_scaling", "tikz_arrows_perpendicular",
            "tikz_shapes_min_distance", "tikz_arrow_text_no_overlap", "tikz_anchored_positioning",
            "tikz_simple_for_tikzit")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def agent_text(name: str) -> str:
    return read(ROOT / ".claude" / "agents" / (name + ".md"))


def flags_in(text: str) -> set:
    """Every upper-case bracket flag of a text, `[NAME: <label>]` reduced to NAME."""
    return {m.group(1) for m in re.finditer(r"\[([A-Z][A-Z -]*[A-Z])(?::[^\]]*)?\]", text)}


def section(text: str, heading: str) -> str:
    """From the line starting with `heading` to the next heading or rule; empty when there is none."""
    lines = text.splitlines()
    for start, line in enumerate(lines):
        if line.startswith(heading):
            for end in range(start + 1, len(lines)):
                if re.match(r"(#{2,3} |---$)", lines[end]):
                    return "\n".join(lines[start:end])
            return "\n".join(lines[start:])
    return ""


def criteria_doc() -> dict:
    return figure_checks.load_criteria(SKILL / "assets" / "figure_criteria.json")


def criteria_flags(doc: dict) -> set:
    return {c["flag"].strip("[]") for c in doc["criteria"] if c.get("flag")}


class TestFigureReviewContract(unittest.TestCase):

    def test_each_auditor_and_tikz_point_to_figure_review(self):
        for name in AUDITORS:
            self.assertIn("figure-review", agent_text(name), name)
        self.assertIn("figure-review", read(ROOT / ".claude" / "commands" / "tikz.md"))

    def test_each_states_the_render_option_off_by_default(self):
        texts = {n: agent_text(n) for n in AUDITORS}
        texts["tikz"] = read(ROOT / ".claude" / "commands" / "tikz.md")
        for name, text in texts.items():
            self.assertIn("--render", text, name)
            self.assertRegex(text, r"off by default", name)

    def test_every_figure_flag_an_auditor_prints_is_in_the_criteria(self):
        known = criteria_flags(criteria_doc())
        printed = set()
        for name, heading in FIGURE_STEP.items():
            body = section(agent_text(name), heading)
            self.assertTrue(body, "figure step not found in " + name)
            flags = flags_in(body) - TABLE_ONLY_FLAGS
            self.assertEqual(flags - known, set(), name)
            printed |= flags
        self.assertEqual(FLAGS_BEFORE - known, set(), "a flag of the snapshot is no longer reachable")
        self.assertEqual(printed, FLAGS_BEFORE, "the figure flags printed today equal the snapshot")

    def test_no_auditor_restates_the_tikz_rule_list(self):
        texts = {n: agent_text(n) for n in AUDITORS}
        texts["tikz"] = read(ROOT / ".claude" / "commands" / "tikz.md")
        for name, text in texts.items():
            prose = re.sub(r"tikz_[a-z_]+", "", text)  # a criterion id may carry a fragment, a rule sentence may not
            for fragment in TIKZ_RULE_FRAGMENTS:
                self.assertNotIn(fragment, prose, "%s restates the TikZ rules (%s)" % (name, fragment))

    def test_the_tikz_rules_are_source_or_image_criteria_of_the_criteria_file(self):
        by_id = {c["id"]: c for c in criteria_doc()["criteria"]}
        for cid in TIKZ_IDS:
            self.assertIn(cid, by_id)
            self.assertIn("tikz", by_id[cid]["applies_to"], cid)
            self.assertIn(by_id[cid]["needs"], ("source", "image", "either"), cid)

    def test_tikz_command_names_the_criteria_file_and_keeps_the_drawio2tikz_exception(self):
        text = read(ROOT / ".claude" / "commands" / "tikz.md")
        self.assertIn("figure_criteria.json", text)
        self.assertIn("drawio2tikz", text)
        self.assertIn("tikz_anchored_positioning", text)
        self.assertIn("tikz_simple_for_tikzit", text)

    def test_undergraduate_scope_excludes_research_only_entries(self):
        doc = criteria_doc()
        research_only = {c["id"] for c in doc["criteria"] if c["scope"] == "research"}
        self.assertTrue(research_only, "there are research-only entries")
        chosen = {c["id"] for c in figure_checks.criteria_for_scope(doc, "undergraduate")}
        self.assertEqual(chosen & research_only, set())
        self.assertTrue({"cited_with_content", "text_size", "called_before_appearing"} <= chosen)
        research = {c["id"] for c in figure_checks.criteria_for_scope(doc, "research")}
        self.assertTrue(research_only <= research)
        self.assertNotIn("cited_with_content", research)

    # --- negative controls: the finders can fail ---

    def test_flag_finder_reports_an_unknown_flag(self):
        fictitious = "Flag `[BRAND NEW FLAG]` when a figure is odd, and `[CAPTION NOT A SENTENCE: <label>]`."
        self.assertEqual(flags_in(fictitious), {"BRAND NEW FLAG", "CAPTION NOT A SENTENCE"})
        self.assertNotEqual(flags_in(fictitious) - criteria_flags(criteria_doc()), set())

    def test_section_finder_returns_nothing_without_the_heading_and_stops_at_the_next_one(self):
        text = "### Step 4.5 - Figures\n`[NOT CITED]`\n\n### Step 5 - Other\n`[OTHER FLAG]`\n"
        self.assertEqual(section("no heading here", "### Step 4.5"), "")
        self.assertIn("NOT CITED", section(text, "### Step 4.5"))
        self.assertNotIn("OTHER FLAG", section(text, "### Step 4.5"))

    def test_rule_fragment_check_detects_a_planted_rule(self):
        planted = "use the positioning library and node distance, never absolute coordinates"
        self.assertTrue(any(f in planted for f in TIKZ_RULE_FRAGMENTS))


if __name__ == "__main__":
    unittest.main()
