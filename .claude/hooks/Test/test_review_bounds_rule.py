"""
test_review_bounds_rule - R35 as amended (a review loop stops at bounds the owner declared) is
written where every harness reads it.

Offline, reads documentation only (local coding contract, plan 2, task 3, R15). R35 once said
"repeat until it returns no finding" with no maximum, and 7 unbounded iterations were measured on
2026-10-17. The amended rule lives in `.claude/rules/workflows.md`, inside the RT-EXPORT region of
`.claude/CLAUDE.md` (exported to every project), in `.claude/commands/loopdev.md` and in the
loop-engineer skill. This suite fails when the rule disappears from one of them or when the
retired stopping phrase comes back.

Scope, stated rather than hidden: it proves the rule is WRITTEN. It cannot prove that a model
obeyed it, which is why the review-loop guard hook exists. Each finder has its negative control
on a fixture (R20).
"""
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO / ".claude" / "rules" / "workflows.md"
CLAUDE_MD = REPO / ".claude" / "CLAUDE.md"
LOOPDEV = REPO / ".claude" / "commands" / "loopdev.md"
SKILL = REPO / ".claude" / "skills" / "loop-engineer" / "SKILL.md"

# What every copy of the rule must name: the question to the owner, the two commands, the three
# bounds and the clean round.
REQUIRED = ("AskUserQuestion", "loop_bounds.py init", "tick --findings", "max_rounds",
            "max_tokens", "plateau", "a round with no finding")
RETIRED = re.compile(r"until\s+it\s+returns\s+no\s+finding", re.IGNORECASE)
# An INVOCATION of the unwired driver flag, not a sentence that says the flag is not wired.
STUB_CALL = re.compile(r"python\s+\"?[^\n]*loop_engineer\.py\"?\s+--loop")


def flat(text: str) -> str:
    """Collapse whitespace so a phrase wrapped across lines is still found."""
    return re.sub(r"\s+", " ", text)


def missing(text: str) -> list:
    """The required phrases absent from a text."""
    body = flat(text)
    return [p for p in REQUIRED if p not in body]


def r35_block(text: str) -> str:
    """The R35 paragraph group of workflows.md, up to the next level-2 heading."""
    start = text.index("**R35")
    end = text.find("\n## ", start)
    return text[start:end if end != -1 else len(text)]


def export_region(text: str) -> str:
    """The text between the RT-EXPORT markers of .claude/CLAUDE.md."""
    begin = text.index("<!-- RT-EXPORT:BEGIN -->")
    return text[begin:text.index("<!-- RT-EXPORT:END -->", begin)]


class TestAmendedRule(unittest.TestCase):
    def test_workflows_r35_names_every_stop_and_the_question(self):
        block = r35_block(WORKFLOWS.read_text(encoding="utf-8"))
        self.assertEqual(missing(block), [])

    def test_the_exported_region_carries_the_rule(self):
        region = export_region(CLAUDE_MD.read_text(encoding="utf-8"))
        self.assertEqual(missing(region), [])

    def test_the_commands_say_where_the_script_lives_outside_researchtools(self):
        # Code review 2026-10-17: the rule is exported to every project, where the
        # repo-relative path of loop_bounds.py does not exist.
        for label, text in (("R35", r35_block(WORKFLOWS.read_text(encoding="utf-8"))),
                            ("export", export_region(CLAUDE_MD.read_text(encoding="utf-8"))),
                            ("loopdev", LOOPDEV.read_text(encoding="utf-8"))):
            with self.subTest(where=label):
                self.assertIn("~/.claude/skills/loop-engineer", flat(text))

    def test_loopdev_and_the_skill_follow_the_procedure(self):
        for path in (LOOPDEV, SKILL):
            with self.subTest(path=path.name):
                body = flat(path.read_text(encoding="utf-8"))
                for phrase in ("AskUserQuestion", "loop_bounds.py init", "tick --findings"):
                    self.assertIn(phrase, body)

    def test_the_retired_stopping_phrase_is_gone_everywhere(self):
        for label, text in (
                ("workflows R35", r35_block(WORKFLOWS.read_text(encoding="utf-8"))),
                ("export region", export_region(CLAUDE_MD.read_text(encoding="utf-8"))),
                ("loopdev", LOOPDEV.read_text(encoding="utf-8")),
                ("skill", SKILL.read_text(encoding="utf-8"))):
            with self.subTest(where=label):
                self.assertIsNone(RETIRED.search(flat(text)))

    def test_loopdev_no_longer_runs_the_unwired_loop_flag(self):
        self.assertIsNone(STUB_CALL.search(LOOPDEV.read_text(encoding="utf-8")))
        self.assertIn("not wired", flat(SKILL.read_text(encoding="utf-8")))


class TestHandTypedReviewIsNotOverClaimed(unittest.TestCase):
    """Code review 2026-10-17: R35 said a review typed by hand is guarded the same way, while the
    hook's own header says it cannot guard that case and the skill-name key is unverified (R15).
    A bound the text promises and the hook does not keep is the seven-iteration case again."""

    def test_no_document_says_a_hand_typed_review_is_guarded(self):
        manual = REPO / "docs" / "manual"
        texts = {"R35": r35_block(WORKFLOWS.read_text(encoding="utf-8")),
                 "08-commands": (manual / "08-commands.md").read_text(encoding="utf-8"),
                 "12-local-coding": (manual / "12-local-coding.md").read_text(encoding="utf-8")}
        for label, text in texts.items():
            with self.subTest(where=label):
                body = flat(text)
                self.assertNotRegex(body, r"(?i)typed (by hand )?as a slash command is guarded")
                self.assertNotIn("is guarded too", body)
                self.assertNotIn("is guarded the same way", body)

    def test_r35_says_the_hand_typed_case_is_unverified(self):
        body = flat(r35_block(WORKFLOWS.read_text(encoding="utf-8")))
        self.assertIn("unverified", body)
        self.assertIn("--max-rounds 1", body)


class TestNegativeControls(unittest.TestCase):
    def test_the_retired_phrase_finder_can_fail(self):
        self.assertIsNotNone(RETIRED.search(flat("the loop repeats until it\nreturns no finding.")))

    def test_the_missing_finder_can_fail_and_pass(self):
        self.assertEqual(missing(" ".join(REQUIRED)), [])
        self.assertEqual(missing("nothing here"), list(REQUIRED))

    def test_the_stub_call_finder_can_fail(self):
        self.assertIsNotNone(STUB_CALL.search('python "scripts/loop_engineer.py" --loop --budget 2'))

    def test_the_block_extractors_stop_at_their_boundaries(self):
        text = "x **R35 - a** body\n\n## Next\nafter"
        self.assertNotIn("after", r35_block(text))
        marked = "pre <!-- RT-EXPORT:BEGIN --> in <!-- RT-EXPORT:END --> post"
        self.assertNotIn("post", export_region(marked))
        self.assertNotIn("pre", export_region(marked))


if __name__ == "__main__":
    unittest.main()
