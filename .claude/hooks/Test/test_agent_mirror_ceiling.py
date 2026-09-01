"""
test_agent_mirror_ceiling - no agent silently loses its Copilot mirror.

Offline, no install run: reads the canonical agent files and applies
install.ps1's own rule, with the threshold read FROM mirror-policy.json so the
test cannot keep passing after someone changes it.

Where the threshold lives changed on 2026-08-30. It used to be a literal in
install.ps1 and this suite parsed it out of the PowerShell. It is now
mirror-policy.json at the repository root, read by install.ps1 AND by the
rt-observe collector, so a reader who cannot run PowerShell can still tell a
deliberately empty mirror cell from a lost one. This suite therefore reads the
policy, and additionally asserts that install.ps1 does NOT restate the value -
two declarations of one threshold is the drift this move exists to prevent
(R0, R2).

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
import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
AGENTS = Path(__file__).resolve().parents[2] / "agents"
INSTALLER = REPO / "install.ps1"
POLICY = REPO / "mirror-policy.json"

FRONTMATTER = re.compile(r"(?s)\A---\n.*?\n---\n")

# The negative control: a literal assignment of either threshold anywhere in the
# installer means the value was restated rather than read, and the two copies
# will drift silently - the installer stubbing at its own number while the
# dashboard reports by-design against the policy's. Matching the ASSIGNMENT and
# the literal COMPARISON specifically, so the untyped parameter declaration and
# the comparison against $CopilotHardLimit both stay legal.
RESTATED_STUB = re.compile(r"\$CopilotStubThreshold\s*=\s*\d")
RESTATED_HARD = re.compile(r"\$out\.Length\s*-gt\s*\d")

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
        self.assertTrue(
            POLICY.exists(),
            f"mirror-policy.json is missing at {POLICY}. It carries the rule this "
            "suite checks, and install.ps1 refuses to run without it.")
        self.policy = json.loads(io.open(POLICY, encoding="utf-8").read())
        self.threshold = self._policy_int("copilot_stub_threshold")
        self.hard = self._policy_int("copilot_hard_limit")
        self.sizes = {p.name: len(body_of(p)) for p in sorted(AGENTS.glob("*.md"))}

    def _policy_int(self, key):
        thresholds = self.policy.get("thresholds", {})
        self.assertIn(
            key, thresholds,
            f"mirror-policy.json declares no thresholds.{key}, so this test can "
            "no longer see the rule it is checking")
        value = thresholds[key].get("value")
        self.assertIsInstance(
            value, int, f"thresholds.{key}.value is not an integer: {value!r}")
        return value

    def test_the_installer_reads_the_threshold_rather_than_restating_it(self):
        """One threshold, one declaration. Two copies drift, and the drift is
        silent: the installer would keep stubbing at its own number while the
        dashboard reported by-design against the policy's."""
        self.assertIsNone(
            RESTATED_STUB.search(self.installer),
            "install.ps1 assigns a literal to $CopilotStubThreshold again. It must "
            "read thresholds.copilot_stub_threshold from mirror-policy.json (R0, R2).")
        self.assertIsNone(
            RESTATED_HARD.search(self.installer),
            "install.ps1 compares the generated length against a literal again. It "
            "must use $CopilotHardLimit from mirror-policy.json (R0, R2).")
        self.assertIn(
            "mirror-policy.json", self.installer,
            "install.ps1 no longer mentions mirror-policy.json, so nothing reads "
            "the policy and the matrix cannot tell by-design from lost.")

    def test_the_negative_control_can_actually_fail(self):
        """A check that cannot fail is not a check. Both restatement patterns are
        proven to fire on the exact text they are meant to catch, so a green run
        above means the installer is clean rather than that the regex rotted."""
        self.assertIsNotNone(
            RESTATED_STUB.search("    [int]$CopilotStubThreshold = 28000,"))
        self.assertIsNotNone(
            RESTATED_HARD.search("    if ($out.Length -gt 30000) { throw }"))
        # And it must NOT fire on the forms that are now correct.
        self.assertIsNone(RESTATED_STUB.search("    [int]$CopilotStubThreshold,"))
        self.assertIsNone(
            RESTATED_HARD.search("    if ($out.Length -gt $CopilotHardLimit) { throw }"))

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
        hard = self.hard
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
