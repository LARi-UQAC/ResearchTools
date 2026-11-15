"""
test_agents_retrieval_chain.py - every agent that calls download_pdf.py stays inside it.

Documentation test (R15): it proves the rule is WRITTEN where each agent reads it,
never that a model obeyed it. Origin, measured 2026-11-05: download_pdf.py ended its
chain at tier 7, so an agent facing a missing closed-access paper improvised the
Playwright MCP on ScienceDirect, where a Cloudflare Turnstile blocks it and the
publisher footer reserves text-and-data-mining rights. The chain now includes a
real browser rung with the owner's institutional sign-in and records every rung's
outcome, so an agent has nothing left to improvise: it reports refs/_failed.md.

Run:
    python .claude/hooks/Test/test_agents_retrieval_chain.py
"""

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
AGENTS = REPO / ".claude" / "agents"

# The plan's eight agents; any other agent that mentions download_pdf.py is found
# by scanning, so a future agent is held to the same rule without editing this file.
PLANNED = (
    "scopus-auditor.md", "paper-auditor.md", "thesis-auditor.md",
    "thesis-proposal-auditor.md", "scopus-researcher.md", "reviewer-response.md",
    "bib-cleaner.md", "litreview-updater.md",
)

RULE = "never fetch a paper's PDF through the Playwright MCP"
REPORT = "report the per-rung reasons listed in `refs/_failed.md`"


def agents_calling_download_pdf(directory: Path) -> list[Path]:
    """Every agent definition that names download_pdf.py."""
    return sorted(p for p in directory.glob("*.md")
                  if "download_pdf.py" in p.read_text(encoding="utf-8"))


def carries_rule(text: str) -> bool:
    """True when the rule, and the instruction to report, follow the first download_pdf.py."""
    first = text.find("download_pdf.py")
    if first < 0:
        return False
    tail = text[first:]
    flat = re.sub(r"\s+", " ", tail)
    return RULE in flat and REPORT in flat


class TestRetrievalChainRule(unittest.TestCase):

    def test_the_finder_sees_the_planned_agents(self):
        found = {p.name for p in agents_calling_download_pdf(AGENTS)}
        for name in PLANNED:
            self.assertIn(name, found, "%s no longer mentions download_pdf.py" % name)

    def test_every_agent_that_calls_download_pdf_carries_the_rule(self):
        for path in agents_calling_download_pdf(AGENTS):
            with self.subTest(agent=path.name):
                self.assertTrue(carries_rule(path.read_text(encoding="utf-8")),
                                "%s has no 'stay inside the chain' rule after its "
                                "download_pdf.py step" % path.name)

    def test_the_rule_names_the_chain_it_defers_to(self):
        # Without this sentence the rule reads as a bare ban and an agent that cannot
        # get a paper has no reason to believe the script already tried a browser.
        for path in agents_calling_download_pdf(AGENTS):
            flat = re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))
            with self.subTest(agent=path.name):
                self.assertIn("including a real browser with the owner's institutional sign-in",
                              flat)

    def test_a_schedulable_agent_tells_an_unattended_run_to_skip_the_browser(self):
        # Review round 1: the browser rung is on by default and opens a visible window,
        # so a scheduled run with nobody at the keyboard would wait on a click that
        # never comes. The agent that documents scheduling must say how to avoid it.
        text = (AGENTS / "litreview-updater.md").read_text(encoding="utf-8")
        flat = re.sub(r"\s+", " ", text)
        unattended = flat[flat.find("**Unattended**"):]
        self.assertIn("--no-browser", unattended[:1500])

    def test_finder_negative_controls(self):
        # A check that cannot fail is not a check.
        self.assertFalse(carries_rule("python download_pdf.py bib x.bib\nNothing else."))
        self.assertFalse(carries_rule("No script is named here at all. " + RULE + " " + REPORT))
        before = RULE + " " + REPORT + "\npython download_pdf.py bib x.bib"
        self.assertFalse(carries_rule(before), "a rule written BEFORE the step does not count")
        ok = "python download_pdf.py bib x.bib\n" + RULE + "\n" + REPORT
        self.assertTrue(carries_rule(ok))
        self.assertFalse(carries_rule("python download_pdf.py\n" + RULE))   # report missing


if __name__ == "__main__":
    unittest.main()
