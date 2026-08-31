"""
test_codex_mirror - no skill silently stops being reachable from Codex.

Offline, no install run: reads the canonical skill files and applies install.ps1's
own rules, with BOTH budgets parsed FROM the installer so the test cannot keep
passing after someone changes them.

Why it exists. Codex discovers skills by scanning `.agents/skills` from the
working directory up to the repository root, and builds a list from each
SKILL.md's name and description. That list is capped: 2% of the model's context
window, or 8000 characters when the window is unknown. Over the cap Codex
shortens descriptions itself, then omits skills with a warning. So a skill can
stop being reachable with nothing here failing - the same silent class as an
agent whose Copilot mirror degrades to a stub, which is what
test_agent_mirror_ceiling.py exists for.

Measured 2026-08-28: the untrimmed name+description list for this repo is 9417
characters against a 8000 budget, already over. install.ps1 therefore trims each
description to whole sentences under a computed per-skill cap, keeping the first
sentence unconditionally because it carries the trigger. This test proves the
trimming actually fits, that no skill is left with an empty trigger, and that the
second Codex ceiling - project_doc_max_bytes over the concatenated AGENTS.md
chain - is not exceeded either.

Both ceilings are Codex-side defaults a user can raise. They are the conservative
case, so passing here means the mirror works on an unconfigured Codex.
"""
import io
import json
import math
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SKILLS = REPO / ".claude" / "skills"
INSTALLER = REPO / "install.ps1"
POLICY = REPO / "mirror-policy.json"

# Both Codex ceilings moved out of install.ps1 into mirror-policy.json on
# 2026-08-30, so the rt-observe collector can read the same intent without
# running PowerShell. This suite reads the policy, and asserts the installer
# does not restate either value: two declarations of one budget drift, and the
# drift is silent (R0, R2).
RESTATED_BUDGET = re.compile(r"\$CodexSkillListBudget\s*=\s*\d")
RESTATED_DOCBYTES = re.compile(r"\$CodexDocMaxBytes\s*=\s*\d")
FRONTMATTER = re.compile(r"(?s)\A---\r?\n(.*?)\r?\n---\r?\n")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def unquote(value: str) -> str:
    """Strip one matching pair of surrounding YAML quotes, as install.ps1 does."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def read_single_quoted(value: str) -> str:
    """Read a single-quoted YAML scalar, the form install.ps1 emits.

    Deliberately strict: an unterminated quote raises rather than being tolerated,
    because tolerating it here is what would let a broken mirror pass the suite.
    """
    if not (len(value) >= 2 and value.startswith("'") and value.endswith("'")):
        raise ValueError(f"not a terminated single-quoted scalar: {value[:80]}")
    return value[1:-1].replace("''", "'")


def read_frontmatter(path: Path):
    """Return (name, description) with a folded description joined, not truncated.

    One skill (recommendation-letter) writes its description over ten indented
    continuation lines. Reading only the `description:` line would mirror a
    fragment of the trigger, so the fold is part of the contract being tested.
    """
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER.match(text)
    if not match:
        raise AssertionError(f"no YAML frontmatter in {path}")
    lines = match.group(1).split("\n")
    name = description = None
    for i, line in enumerate(lines):
        if re.match(r"^name:\s*(.+)$", line):
            name = re.match(r"^name:\s*(.+)$", line).group(1).strip()
            continue
        if line.startswith("description:"):
            head = line[len("description:"):].strip()
            # A block scalar indicator (>, |, >-, |-) is syntax, not text.
            if re.fullmatch(r"[>|][-+]?\d*", head):
                head = ""
            parts = [head]
            for nxt in lines[i + 1:]:
                if re.match(r"^\s+\S", nxt):
                    parts.append(nxt.strip())
                else:
                    break
            description = unquote(" ".join(p for p in parts if p).strip())
    return name, description


def limit_description(text: str, cap: int) -> str:
    """install.ps1's Limit-Description, restated. First sentence always survives."""
    if len(text) <= cap:
        return text
    sentences = SENTENCE_SPLIT.split(text)
    kept = sentences[0]
    for s in sentences[1:]:
        if len(kept) + 1 + len(s) > cap:
            break
        kept = f"{kept} {s}"
    return kept


class CodexMirrorTest(unittest.TestCase):
    def setUp(self):
        self.installer = io.open(INSTALLER, encoding="utf-8").read()
        self.assertTrue(
            POLICY.exists(),
            f"mirror-policy.json is missing at {POLICY}. It carries both Codex "
            "ceilings, and install.ps1 refuses to run without it.")
        self.policy = json.loads(io.open(POLICY, encoding="utf-8").read())
        self.budget = self._policy_int("codex_skill_list_budget")
        self.doc_max_bytes = self._policy_int("codex_doc_max_bytes")

        self.skills = {}
        for skill_md in sorted(SKILLS.glob("*/SKILL.md")):
            name, desc = read_frontmatter(skill_md)
            self.assertIsNotNone(name, f"{skill_md} has no name:")
            self.assertIsNotNone(desc, f"{skill_md} has no description:")
            self.skills[name] = desc
        self.assertGreater(len(self.skills), 0, "no skills found to mirror")

        overhead = sum(len(n) for n in self.skills)
        self.cap = math.floor((self.budget - overhead) / len(self.skills))

    def _policy_int(self, key):
        thresholds = self.policy.get("thresholds", {})
        self.assertIn(
            key, thresholds,
            "mirror-policy.json declares no thresholds.%s, so this test can no "
            "longer see the rule it is checking" % key)
        value = thresholds[key].get("value")
        self.assertIsInstance(
            value, int, "thresholds.%s.value is not an integer: %r" % (key, value))
        return value

    def test_the_installer_reads_both_ceilings_rather_than_restating_them(self):
        """One budget, one declaration. A restated copy drifts silently: the
        installer would trim against its own number while the dashboard reported
        by-design against the policy's."""
        self.assertIsNone(
            RESTATED_BUDGET.search(self.installer),
            "install.ps1 assigns a literal to $CodexSkillListBudget again. It must "
            "read thresholds.codex_skill_list_budget from mirror-policy.json.")
        self.assertIsNone(
            RESTATED_DOCBYTES.search(self.installer),
            "install.ps1 assigns a literal to $CodexDocMaxBytes again. It must read "
            "thresholds.codex_doc_max_bytes from mirror-policy.json.")
        self.assertIn(
            "mirror-policy.json", self.installer,
            "install.ps1 no longer mentions mirror-policy.json, so nothing reads the "
            "policy and the matrix cannot tell by-design from lost.")

    def test_the_restatement_control_can_actually_fail(self):
        """A check that cannot fail is not a check: both patterns are proven to
        fire on the exact text they exist to catch, and to stay silent on the
        parameter form that is now correct."""
        self.assertIsNotNone(
            RESTATED_BUDGET.search("    [int]$CodexSkillListBudget = 8000,"))
        self.assertIsNotNone(
            RESTATED_DOCBYTES.search("    [int]$CodexDocMaxBytes = 32768,"))
        self.assertIsNone(RESTATED_BUDGET.search("    [int]$CodexSkillListBudget,"))
        self.assertIsNone(RESTATED_DOCBYTES.search("    [int]$CodexDocMaxBytes,"))

    def trimmed(self):
        return {n: limit_description(d, self.cap) for n, d in self.skills.items()}

    def test_the_trimmed_skill_list_fits_the_codex_budget(self):
        total = sum(len(n) + len(d) for n, d in self.trimmed().items())
        self.assertLessEqual(
            total, self.budget,
            f"the trimmed Codex skill list is {total} chars against a "
            f"{self.budget} budget, so Codex shortens descriptions itself and "
            "then omits skills with a warning - a skill stops being reachable "
            "and install.ps1 reports it only as a [WARN] line")

    def test_no_skill_mirrors_with_an_empty_trigger(self):
        """A mirror with no description is a skill Codex can never fire."""
        empty = sorted(n for n, d in self.trimmed().items() if not d.strip())
        self.assertEqual(
            empty, [],
            f"these skills would mirror with an empty description: {empty}")

    def test_every_description_keeps_its_whole_first_sentence(self):
        """The first sentence carries the trigger. Trimming may drop later
        sentences, never cut one in half, which would leave a fragment that reads
        as a different instruction than the author wrote."""
        for name, full in self.skills.items():
            kept = limit_description(full, self.cap)
            first = SENTENCE_SPLIT.split(full)[0]
            self.assertTrue(
                kept.startswith(first),
                f"{name}: trimmed description does not open on its own first "
                f"sentence:\n  first: {first[:120]}\n  kept:  {kept[:120]}")
            self.assertTrue(
                full.startswith(kept),
                f"{name}: trimmed description is not a prefix of the original, "
                "so the trim rewrote rather than shortened it")

    def test_a_folded_description_is_joined_not_truncated(self):
        """Negative control on the parser itself: at least one skill in this repo
        folds its description over continuation lines, and reading one line would
        silently mirror a fragment. If that skill is ever reflowed this test must
        be pointed at whichever one folds, not deleted."""
        folded = []
        for skill_md in sorted(SKILLS.glob("*/SKILL.md")):
            text = skill_md.read_text(encoding="utf-8")
            lines = FRONTMATTER.match(text).group(1).split("\n")
            for i, line in enumerate(lines):
                if line.startswith("description:"):
                    if i + 1 < len(lines) and re.match(r"^\s+\S", lines[i + 1]):
                        folded.append(skill_md)
                    break
        self.assertTrue(
            folded, "no skill folds its description any more; this test now "
                    "proves nothing and should be re-pointed or removed")
        for skill_md in folded:
            _, desc = read_frontmatter(skill_md)
            first_line = None
            lines = FRONTMATTER.match(
                skill_md.read_text(encoding="utf-8")).group(1).split("\n")
            for line in lines:
                if line.startswith("description:"):
                    first_line = line[len("description:"):].strip()
                    break
            self.assertGreater(
                len(desc), len(first_line),
                f"{skill_md}: folded description was read as its first line only")

    def test_the_budget_rule_can_actually_fail(self):
        """R20. Without this, a trim that silently returned the whole string
        would pass every assertion above on a repo that happens to fit."""
        oversized = {f"skill{i}": "x" * 4000 for i in range(10)}
        overhead = sum(len(n) for n in oversized)
        cap = math.floor((self.budget - overhead) / len(oversized))
        total = sum(len(n) + len(limit_description(d, cap))
                    for n, d in oversized.items())
        self.assertGreater(
            total, self.budget,
            "a list of ten 4000-char single-sentence descriptions must exceed "
            "the budget even after trimming, since the first sentence is kept "
            "whole; if it does not, the trim is silently rewriting text")

    def test_the_agents_md_chain_fits_project_doc_max_bytes(self):
        """Codex concatenates one AGENTS.md per directory from the git root down
        to the cwd and stops adding files once the combined size reaches
        project_doc_max_bytes. Over the cap the deepest file, the one closest to
        the work, is the one dropped."""
        root = REPO / "AGENTS.md"
        nested = SKILLS / "AGENTS.md"
        if not root.exists():
            self.skipTest("AGENTS.md not generated yet (run install.ps1)")
        chain = root.stat().st_size
        if nested.exists():
            chain += nested.stat().st_size
        self.assertLessEqual(
            chain, self.doc_max_bytes,
            f"the AGENTS.md chain is {chain} bytes against Codex's "
            f"{self.doc_max_bytes}-byte project_doc_max_bytes, so the tail is "
            "dropped and the deepest guidance is the part lost")

    def test_generated_mirrors_use_the_exact_SKILL_md_casing(self):
        """Codex discovery is case-sensitive on the entry file: a SKILL.MD is not
        found. Only checks what exists, so the suite still runs before a first
        install."""
        mirror_root = REPO / ".agents" / "skills"
        if not mirror_root.is_dir():
            self.skipTest(".agents/skills not generated yet (run install.ps1)")
        for d in sorted(p for p in mirror_root.iterdir() if p.is_dir()):
            entries = {p.name for p in d.iterdir() if p.is_file()}
            self.assertIn(
                "SKILL.md", entries,
                f"{d.name}: Codex requires the entry file named exactly "
                f"'SKILL.md'; found {sorted(entries)}")

    def test_every_generated_description_is_a_terminated_yaml_scalar(self):
        """The defect this test was written for. Measured 2026-08-28: the first
        generated set carried the source's OWN double quotes into the mirror and
        then trimmed the string mid-scalar, so 11 of 15 mirrors shipped
        `description: "Use this...` with no closing quote. That frontmatter does
        not parse, and a skill whose frontmatter does not parse is a skill Codex
        never offers - with install.ps1 reporting a green [OK] for every one."""
        mirror_root = REPO / ".agents" / "skills"
        if not mirror_root.is_dir():
            self.skipTest(".agents/skills not generated yet (run install.ps1)")
        broken = []
        for skill_md in sorted(mirror_root.glob("*/SKILL.md")):
            fm = FRONTMATTER.match(skill_md.read_text(encoding="utf-8"))
            self.assertIsNotNone(fm, f"{skill_md}: no frontmatter")
            line = next((l for l in fm.group(1).split("\n")
                         if l.startswith("description:")), None)
            self.assertIsNotNone(line, f"{skill_md}: no description:")
            raw = line[len("description:"):].strip()
            try:
                value = read_single_quoted(raw)
            except ValueError as exc:
                broken.append(f"{skill_md.parent.name}: {exc}")
                continue
            if not value.strip():
                broken.append(f"{skill_md.parent.name}: empty description")
        self.assertEqual(
            broken, [],
            "these Codex mirrors carry frontmatter that does not parse:\n  "
            + "\n  ".join(broken))

    def test_generated_description_matches_the_trimmed_canonical_value(self):
        """Guards the other direction: the mirror must carry the intended value,
        not merely something that parses."""
        mirror_root = REPO / ".agents" / "skills"
        if not mirror_root.is_dir():
            self.skipTest(".agents/skills not generated yet (run install.ps1)")
        expected = self.trimmed()
        for name, want in expected.items():
            skill_md = mirror_root / name / "SKILL.md"
            if not skill_md.exists():
                continue                     # covered by the mirror-exists test
            fm = FRONTMATTER.match(skill_md.read_text(encoding="utf-8"))
            line = next(l for l in fm.group(1).split("\n")
                        if l.startswith("description:"))
            got = read_single_quoted(line[len("description:"):].strip())
            self.assertEqual(
                got, want,
                f"{name}: mirrored description differs from the trimmed "
                "canonical one; re-run install.ps1")

    def test_every_canonical_skill_has_a_mirror_once_generated(self):
        mirror_root = REPO / ".agents" / "skills"
        if not mirror_root.is_dir():
            self.skipTest(".agents/skills not generated yet (run install.ps1)")
        mirrored = {p.name for p in mirror_root.iterdir() if p.is_dir()}
        missing = sorted(set(self.skills) - mirrored)
        self.assertEqual(
            missing, [],
            f"these skills have no Codex mirror; re-run install.ps1: {missing}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
