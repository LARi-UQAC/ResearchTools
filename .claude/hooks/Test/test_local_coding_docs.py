"""
test_local_coding_docs - the documentation says WHY local models go through the bridge, and
what is unsupported or untried (local coding contract, plan 8, R14, R15).

Offline, reads documentation only. Seven documents carried the explanation "cloud runs on the
subscription auth, no gateway" in slightly different words, and the Claude Code documentation
(read 2026-10-17) does not support it. The three facts that replace it:

  1. Claude Code has one API endpoint per process and no per-subagent endpoint, environment or
     provider, so a subagent cannot be pointed at Ollama while the main session stays on
     Anthropic. That, and not the subscription, is why the bridge exists.
  2. Switching the whole session with `claude-switch.ps1` works and was measured here, but
     Anthropic documents that it does not support routing Claude Code to non-Claude models
     through a gateway, and Remote Control is unavailable.
  3. A model ID Claude Code does not recognise is assumed to have a 200K window unless
     `CLAUDE_CODE_MAX_CONTEXT_TOKENS` is set, and whether that variable is capped at the
     model's own window is not documented and is untried here.

A sentence copied into seven files drifts, so this suite reads all seven. Each finder has its
negative control (R20). It proves the facts are WRITTEN, never that they are still true.
"""
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ALL = {
    "LOOP.md": REPO / ".claude" / "skills" / "loop-engineer" / "references" / "LOOP.md",
    "SKILL.md": REPO / ".claude" / "skills" / "loop-engineer" / "SKILL.md",
    "loopdev.md": REPO / ".claude" / "commands" / "loopdev.md",
    "workflows.md": REPO / ".claude" / "rules" / "workflows.md",
    "Architecture.md": REPO / "Architecture.md",
    "contributor-notes.md": REPO / "docs" / "contributor-notes.md",
    "05-agents.md": REPO / "docs" / "manual" / "05-agents.md",
}
SWITCH_DOCS = ("workflows.md", "contributor-notes.md", "Architecture.md")

RETIRED = re.compile(
    r"cannot resolve a local model name|\bno gateway\b|no separate API key|"
    r"no gateway and no", re.IGNORECASE)
FACT1 = "one API endpoint per process"
FACT2 = "does not support routing Claude Code to non-Claude models"
FACT3 = "CLAUDE_CODE_MAX_CONTEXT_TOKENS"
# A claim that a subagent runs on a local model (not documented): "a subagent can run on",
# "subagents run on a local model". "cannot be pointed" is the opposite and must pass.
SUBAGENT_LOCAL = re.compile(
    r"\bsubagents?\b[^.]{0,40}\b(can|may|will)\b[^.]{0,30}\b(run|runs|use|uses)\b"
    r"[^.]{0,30}\b(local|ollama)\b", re.IGNORECASE)


def flat(text: str) -> str:
    """Collapse whitespace so a phrase wrapped across lines is still found."""
    return re.sub(r"\s+", " ", text)


def read(name: str) -> str:
    """A document of the set, whitespace collapsed."""
    return flat(ALL[name].read_text(encoding="utf-8"))


class TestFacts(unittest.TestCase):
    def test_the_retired_wording_is_gone_from_all_seven(self):
        for name in ALL:
            with self.subTest(file=name):
                self.assertIsNone(RETIRED.search(read(name)), name)

    def test_fact_1_is_present_in_all_seven(self):
        for name in ALL:
            with self.subTest(file=name):
                self.assertIn(FACT1, read(name))

    def test_facts_2_and_3_are_present_in_the_three_switch_documents(self):
        for name in SWITCH_DOCS:
            with self.subTest(file=name):
                body = read(name)
                self.assertIn(FACT2, body)
                self.assertIn("Remote Control", body)
                self.assertIn(FACT3, body)
                self.assertIn("untried", body)

    def test_the_session_switch_names_the_authentication_detail(self):
        body = read("workflows.md")
        self.assertIn("ANTHROPIC_AUTH_TOKEN", body)
        self.assertIn("takes precedence over the subscription login", body)

    def test_the_loop_documents_name_the_session_role_and_the_unwired_loop(self):
        for name in ("LOOP.md", "SKILL.md"):
            with self.subTest(file=name):
                body = read(name)
                self.assertIn("not wired", body)
                self.assertIn("loop_bounds.py", body)
        loop = read("LOOP.md")
        self.assertIn("session", loop)
        self.assertIn("262144", loop)

    def test_no_file_claims_a_subagent_runs_on_a_local_model(self):
        for name in ALL:
            with self.subTest(file=name):
                self.assertIsNone(SUBAGENT_LOCAL.search(read(name)), name)


class TestNegativeControls(unittest.TestCase):
    def test_the_retired_finder_can_fail(self):
        for phrase in ("No gateway; cloud stays on subscription auth",
                       "because subscription auth cannot resolve a local model name",
                       "no gateway and no separate API key are involved"):
            self.assertIsNotNone(RETIRED.search(flat(phrase)), phrase)
        self.assertIsNone(RETIRED.search("a gateway is documented as unsupported"))

    def test_the_subagent_claim_finder_can_fail_and_passes_the_true_sentence(self):
        self.assertIsNotNone(SUBAGENT_LOCAL.search("A subagent can run on a local model."))
        self.assertIsNone(SUBAGENT_LOCAL.search(
            "so a subagent cannot be pointed at Ollama while the main session stays on Anthropic"))


if __name__ == "__main__":
    unittest.main()
