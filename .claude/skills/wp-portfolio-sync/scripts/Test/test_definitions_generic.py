"""
test_definitions_generic.py - R7 regression guard for the skill, agent,
command and templates: no owner identity, the agent's tool surface and
pause/checklist contract, and the example mapping's own validity.

Reads the five files as text; no model, no network.
"""
import json
import unittest
from pathlib import Path

import _fixtures  # noqa: F401

import render
import push_wp

_TEST_DIR = Path(__file__).resolve().parent
_SKILL_DIR = _TEST_DIR.parents[1]
_REPO_ROOT = _TEST_DIR.parents[4]

SKILL_MD = _SKILL_DIR / "SKILL.md"
MAPPING_EXAMPLE = _SKILL_DIR / "templates" / "mapping.example.yaml"
COOKIES_EXAMPLE = _SKILL_DIR / "templates" / "cookies.json.example"
AGENT_MD = _REPO_ROOT / ".claude" / "agents" / "wp-portfolio-agent.md"
COMMAND_MD = _REPO_ROOT / ".claude" / "commands" / "portfolio.md"

ALL_FILES = (SKILL_MD, MAPPING_EXAMPLE, COOKIES_EXAMPLE, AGENT_MD, COMMAND_MD)


class TestNoOwnerIdentity(unittest.TestCase):
    def test_no_owner_identity(self):
        for path in ALL_FILES:
            text = path.read_text(encoding="utf-8")
            for forbidden in ("Otis", "martinotis", "/martinotis"):
                self.assertNotIn(forbidden, text, "%s contains %r" % (path, forbidden))


class TestAgentContract(unittest.TestCase):
    def setUp(self):
        self.text = AGENT_MD.read_text(encoding="utf-8")

    def test_agent_tools_read_bash_only(self):
        lines = [l.strip() for l in self.text.splitlines() if l.strip().startswith("tools:")]
        self.assertEqual(lines, ["tools: Read, Bash"])

    def test_agent_has_pause_and_checklist(self):
        self.assertIn("PIPELINE-PAUSED @ preview-approval", self.text)
        self.assertIn("--apply --yes", self.text)
        self.assertIn("PIPELINE INCOMPLETE", self.text)

    def test_agent_has_two_distinct_approval_pauses(self):
        # PR #50 review, M6: a clean preview (Step 3) must not by itself authorize
        # the write (Step 5) - Step 4's own dry run needs its own pause.
        self.assertIn("PIPELINE-PAUSED @ apply-approval", self.text)
        step4_index = self.text.index("### Step 4")
        step5_index = self.text.index("### Step 5")
        self.assertIn("PIPELINE-PAUSED @ apply-approval", self.text[step4_index:step5_index])

    def test_agent_one_shot_rule(self):
        step4_index = self.text.index("### Step 4")
        step5_index = self.text.index("### Step 5")
        step4_text = self.text[step4_index:step5_index]
        self.assertIn("would-change", step4_text)
        self.assertIn("source", step4_text)


class TestSkillDescription(unittest.TestCase):
    def test_skill_first_sentence_triggers(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        desc_line = next(l for l in text.splitlines() if l.strip().startswith("description:"))
        description = desc_line.split(":", 1)[1].strip().strip('"')
        first_sentence = description.split(". ")[0]
        self.assertIn("WordPress", first_sentence)
        self.assertIn("XML", first_sentence)
        self.assertGreaterEqual(len(first_sentence), 120)


class TestTemplates(unittest.TestCase):
    def test_template_cookies_is_json(self):
        data = json.loads(COOKIES_EXAMPLE.read_text(encoding="utf-8"))
        self.assertEqual(data, [])

    def test_template_mapping_valid(self):
        import yaml

        mapping = yaml.safe_load(MAPPING_EXAMPLE.read_text(encoding="utf-8"))
        render.load_render_settings(mapping, str(MAPPING_EXAMPLE))
        push_wp.validate_mapping(mapping)

        bad_mapping = dict(mapping)
        bad_mapping["entries"] = list(mapping["entries"]) + [
            {
                "cv_path": "financement",
                "page_id": 999,
                "mode": "split",
                "renderer": "phq",
                "recent_marker": "phq-recent",
                "history_marker": "phq-historique",
            }
        ]
        with self.assertRaises(Exception):
            push_wp.validate_mapping(bad_mapping)


if __name__ == "__main__":
    unittest.main()
