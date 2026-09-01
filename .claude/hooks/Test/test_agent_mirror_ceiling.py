"""
test_agent_mirror_ceiling - no agent silently loses its Copilot mirror.

Offline, no install run: reads the canonical agent files and applies
install.ps1's own rule, with the threshold parsed FROM the installer so the test
cannot keep passing after someone changes it.

Why it exists. install.ps1 degrades an agent whose BODY exceeds
CopilotStubThreshold into a ~1700-character stub that says "read the real file",
prints the word `stub`, and exits 0. Nothing fails. Measured 2026-08-28:
local-writer.md crossed the line at 28822 body chars and mirrored as a stub for
three regenerations before anyone read the installer output closely enough.

Seven agents are stubs by design and have always been - the mechanism exists for
them. So the test is not "everything must fit"; it is "the set of stubs is
exactly this, and it changes only on purpose". A new name in the failure means a
mirror was just lost. A missing name means someone trimmed an agent under the
ceiling and should take it off the list.
"""
import io
import re
import unittest
from pathlib import Path

AGENTS = Path(__file__).resolve().parents[2] / "agents"
INSTALLER = Path(__file__).resolve().parents[3] / "install.ps1"

FRONTMATTER = re.compile(r"(?s)\A---\n.*?\n---\n")
THRESHOLD_LINE = re.compile(r"\$CopilotStubThreshold\s*=\s*(\d+)")
HARD_LIMIT_LINE = re.compile(r"\$out\.Length\s*-gt\s*(\d+)")

# Long-form agents that have never fitted the Copilot ceiling. Their mirror is a
# stub pointing at the canonical file, which is the intended outcome for them.
KNOWN_STUBS = {
    "cover-paper.md",
    "paper-auditor.md",
    "reviewer-response.md",
    "scopus-auditor.md",
    "scopus-researcher.md",
    "thesis-auditor.md",
    "thesis-proposal-auditor.md",
}


def body_of(path: Path) -> str:
    text = io.open(path, encoding="utf-8").read()
    match = FRONTMATTER.match(text)
    return text[match.end():].lstrip("\n") if match else text


class AgentMirrorCeilingTest(unittest.TestCase):
    def setUp(self):
        self.installer = io.open(INSTALLER, encoding="utf-8").read()
        match = THRESHOLD_LINE.search(self.installer)
        self.assertIsNotNone(
            match, "install.ps1 no longer declares $CopilotStubThreshold, so "
                   "this test can no longer see the rule it is checking")
        self.threshold = int(match.group(1))
        self.sizes = {p.name: len(body_of(p)) for p in sorted(AGENTS.glob("*.md"))}

    def test_no_agent_outside_the_known_list_mirrors_as_a_stub(self):
        lost = {name: size for name, size in self.sizes.items()
                if size > self.threshold and name not in KNOWN_STUBS}
        self.assertEqual(
            lost, {},
            f"these agents now exceed the {self.threshold}-char body ceiling, so "
            "GitHub Copilot receives a stub instead of their instructions and "
            "install.ps1 reports it only as the word 'stub': "
            + ", ".join(f"{n} at {s}" for n, s in sorted(lost.items())))

    def test_an_agent_trimmed_under_the_ceiling_leaves_the_known_list(self):
        """Keeps the baseline honest: a list that is never pruned stops meaning
        anything, and would hide a mirror silently going missing later."""
        recovered = {name for name in KNOWN_STUBS
                     if self.sizes.get(name, self.threshold + 1) <= self.threshold}
        self.assertEqual(
            recovered, set(),
            "these agents now fit and mirror in full; remove them from "
            f"KNOWN_STUBS: {sorted(recovered)}")

    def test_a_full_mirror_stays_under_the_installers_hard_limit(self):
        """The stub threshold is a proxy. The rule that actually throws is the
        installer's own check on the generated file, frontmatter included."""
        hard = int(HARD_LIMIT_LINE.search(self.installer).group(1))
        for path in sorted(AGENTS.glob("*.md")):
            if path.name in KNOWN_STUBS:
                continue                      # its mirror is the small stub
            generated = len(io.open(path, encoding="utf-8").read())
            self.assertLess(
                generated, hard,
                f"{path.name} would generate a Copilot profile of {generated} "
                f"chars, over the installer's {hard} limit, and the run would throw")

    def test_every_known_stub_still_exists(self):
        missing = sorted(n for n in KNOWN_STUBS if n not in self.sizes)
        self.assertEqual(missing, [],
                         f"KNOWN_STUBS names agents that are gone: {missing}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
