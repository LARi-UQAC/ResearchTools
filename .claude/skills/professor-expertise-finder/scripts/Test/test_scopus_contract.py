import re
import unittest
from pathlib import Path

# This skill's SKILL.md/agent.md instruct an agent to call the SIBLING
# `scopus` skill's `publications` CLI mode (author_documents()) for a
# professor's recent, approved-publisher-flagged document list (Workflow
# 6). 2026-10-09 review finding: a prior round of this same PR had already
# miswritten which mode carries this contract without checking the real
# code (R14). This is a pure TEXT check on scopus_api.py's own source -
# no import, no network, no dependency on that skill's own requirements -
# so a future change to that contract fails HERE instead of silently
# going stale in this skill's workflow instructions.
SCOPUS_API_PATH = (Path(__file__).resolve().parents[3] / "scopus" / "scripts"
                   / "scopus_api.py")


class ScopusContractTest(unittest.TestCase):
    def setUp(self):
        if not SCOPUS_API_PATH.exists():
            self.skipTest(f"sibling scopus skill not found at {SCOPUS_API_PATH} "
                           "(expected when this skill is vendored standalone)")
        self.source = SCOPUS_API_PATH.read_text(encoding="utf-8")

    def test_author_documents_function_exists(self):
        self.assertIn("def author_documents(", self.source)

    def test_author_documents_returns_approved_publisher(self):
        match = re.search(r"def author_documents\(.*?\n(?=def |\Z)", self.source, re.S)
        self.assertIsNotNone(match, "could not isolate author_documents()'s body")
        self.assertIn("approved_publisher", match.group(0))

    def test_author_documents_sorts_most_recent_first(self):
        match = re.search(r"def author_documents\(.*?\n(?=def |\Z)", self.source, re.S)
        self.assertIsNotNone(match)
        self.assertIn('"-coverDate"', match.group(0))

    def test_publications_mode_dispatches_to_author_documents(self):
        self.assertIn('"publications":', self.source)
        match = re.search(r'"publications":\s*lambda.*?author_documents\(', self.source, re.S)
        self.assertIsNotNone(match, "the 'publications' CLI mode must call author_documents()")


if __name__ == "__main__":
    unittest.main(verbosity=2)
