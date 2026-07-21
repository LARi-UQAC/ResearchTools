# recommendation-letter Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a `recommendation-letter` ResearchTools skill (+ `/recommendation-letter` command) that generates six letter types (four authored, two template-filled forms) in LaTeX -> PDF from a candidate's own files.

**Architecture:** A two-track, stdlib-only Python pipeline. Constants (preamble, letterhead, signatures, the acceptance/dispense French form templates, gender/degree maps, funding blocks, immigration paragraphs) live in `letter_templates.py`. All logic (config load, LaTeX escape, dates, candidate reference, funding paragraph, style-hygiene linter, gender/conditional resolution, two-track assembly, pdflatex compile) lives in `generate_letter.py`. `SKILL.md` runs the elicitation and, for the four persuasive types, authors the body prose (`body_tex`) that the script wraps; the two form types are fully assembled by the script.

**Tech Stack:** Python 3.8+ standard library only (`argparse`, `json`, `os`, `sys`, `re`, `subprocess`, `datetime`, `unicodedata`, `pathlib`). `pdflatex` external, optional (graceful degradation). No third-party dependency -> no `requirements.txt`, no `pip-audit` surface.

## Global Constraints

- Python standard library only. No third-party imports anywhere in the skill scripts.
- Output directory is `out/` (repo writing standard). Filenames: `letter_<surname>_<letter_type>.tex` / `.pdf`; surname = last whitespace token of `candidate_name`, lowercased, ASCII-folded.
- LaTeX output uses UTF-8 accented characters directly (preamble loads `\usepackage[utf8]{inputenc}`); do NOT emit `\'e`-style accent macros. This is a deliberate simplification from the integration doc so the style-hygiene linter and the templates stay readable.
- Placeholder token for missing fields is `[À COMPLÉTER]` (French). Detection also matches the legacy `[TO COMPLETE]`.
- Style hygiene (hard constraint on any produced text, per `.claude/CLAUDE.md`): no U+200B/U+200C/U+200D, no U+2026, no em/en dash (— –), no U+E0000-E007F tag chars, no smart quotes (" " ' '), no stray `**` or leading `#`. Straight quotes only. AI-usage target < 20 %.
- Six `letter_type` values: `scholarship`, `academic_position`, `industry_position`, `appreciation` (authored track, fr+en); `acceptance`, `dispense` (form track, fr only).
- `candidate_status`: `applicant` | `current_student` | `graduated`.
- `funding_provider`: `supervisor` | `candidate` | `combination`.
- English-only definition files (SKILL.md, command, code, comments). French appears only in emitted deliverable strings (templates, letter text).
- Counts before this work: 10 skills, 15 agents, 19 commands -> after: 11 skills, 20 commands.
- Skill directory: `.claude/skills/recommendation-letter/`. Prefix shell commands with `rtk`. Work stays on branch `feat/recommendation-letter-skill`.

---

## File Structure

```
.claude/skills/recommendation-letter/
  SKILL.md                              # workflow + elicitation (Task 12)
  scripts/
    letter_templates.py                 # all string constants + maps (Tasks 1,7,8,9)
    generate_letter.py                  # CLI + logic (Tasks 1-11)
    Test/
      test_generate_letter.py           # offline unit tests (Tasks 1-11)
  references/
    quality-patterns.md                 # authored-track patterns (Task 13)
  evals/
    evals.json + 9 test_*.json          # eval configs (Task 11)
.claude/commands/recommendation-letter.md   # thin command (Task 12)
README.md, Architecture.md,
.claude/CLAUDE.md, .claude/rules/workflows.md, install.ps1   # inventory + mirrors (Task 14)
```

Run every `python`/`pytest` command from the repo root
`c:\Martin Otis\OutilsLogiciels\ResearchTools`. Tests use only `unittest`
(stdlib) so they run with the base interpreter, no venv, no network.

---

### Task 1: Package skeleton, config load, CLI, filename helper

**Files:**
- Create: `.claude/skills/recommendation-letter/scripts/letter_templates.py`
- Create: `.claude/skills/recommendation-letter/scripts/generate_letter.py`
- Create: `.claude/skills/recommendation-letter/scripts/Test/test_generate_letter.py`

**Interfaces:**
- Produces: `load_config(path) -> dict`; `surname_slug(candidate_name) -> str`; `parse_args(argv) -> argparse.Namespace`; module runs as `python generate_letter.py --config X --output out/ [--no-compile] [--strict]`.

- [ ] **Step 1: Write the failing test**

`.claude/skills/recommendation-letter/scripts/Test/test_generate_letter.py`:

```python
"""
Offline unit tests for generate_letter.py. Standard library only:
no network, no pdflatex, no model load. Run: python -m unittest -v
(from the scripts/ dir) or via the path command in the plan.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import generate_letter as gl


class TestConfigAndFilenames(unittest.TestCase):
    def test_load_config_reads_json(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as fh:
            json.dump({"letter_type": "appreciation", "language": "en"}, fh)
            path = fh.name
        try:
            cfg = gl.load_config(path)
            self.assertEqual(cfg["letter_type"], "appreciation")
        finally:
            os.unlink(path)

    def test_load_config_invalid_json_raises(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as fh:
            fh.write("{not valid json")
            path = fh.name
        try:
            with self.assertRaises(ValueError):
                gl.load_config(path)
        finally:
            os.unlink(path)

    def test_surname_slug_folds_accents_and_lowercases(self):
        self.assertEqual(gl.surname_slug("Candidat Exemple Charlie"), "charlie")
        self.assertEqual(gl.surname_slug("Candidate Exemple Foxtrot"), "foxtrot")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk python -m unittest discover -s ".claude/skills/recommendation-letter/scripts/Test" -v`
Expected: FAIL / ERROR `ModuleNotFoundError: No module named 'generate_letter'`.

- [ ] **Step 3: Create the empty templates module**

`.claude/skills/recommendation-letter/scripts/letter_templates.py`:

```python
"""
letter_templates.py - all embedded string constants and lookup maps for the
recommendation-letter skill. No logic here; generate_letter.py imports these.
Kept separate so the assembly logic stays small and testable.
"""
```

- [ ] **Step 4: Write minimal implementation**

`.claude/skills/recommendation-letter/scripts/generate_letter.py`:

```python
"""
generate_letter.py - recommendation-letter skill.

Two-track LaTeX letter generator (stdlib only). Authored track: the caller
supplies body_tex, the script wraps it. Form track (acceptance, dispense):
the script assembles a fixed French template from config fields.

Quality patterns (see references/quality-patterns.md): direct opening verdict,
quantified claims, named funding sources, future collaboration, availability.
Style hygiene: no invisible chars, no em dash, straight quotes (< 20% AI-usage).
"""
import argparse
import json
import os
import sys
import unicodedata


def load_config(path):
    """Read a JSON config file. Raises ValueError on a parse error."""
    with open(path, "r", encoding="utf-8") as fh:
        try:
            return json.load(fh)
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid JSON config: %s" % exc)


def surname_slug(candidate_name):
    """Last whitespace token, ASCII-folded, lowercased. '' if empty."""
    if not candidate_name:
        return ""
    token = candidate_name.strip().split()[-1]
    folded = unicodedata.normalize("NFKD", token)
    folded = folded.encode("ascii", "ignore").decode("ascii")
    return folded.lower()


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Generate a LAR.i letter (LaTeX/PDF).")
    p.add_argument("--config", required=True, help="Path to the JSON config.")
    p.add_argument("--output", default="out", help="Output directory (default: out).")
    p.add_argument("--no-compile", action="store_true", help="Emit .tex only.")
    p.add_argument("--strict", action="store_true",
                   help="Fail (exit 3) on any style-hygiene violation.")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        config = load_config(args.config)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    # Assembly wired in later tasks.
    _ = config
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `rtk python -m unittest discover -s ".claude/skills/recommendation-letter/scripts/Test" -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
rtk git add .claude/skills/recommendation-letter/scripts
rtk git commit -m "feat(recommendation-letter): script skeleton, config load, CLI"
```

---

### Task 2: LaTeX escaping and date formatting

**Files:**
- Modify: `.claude/skills/recommendation-letter/scripts/generate_letter.py`
- Test: `.claude/skills/recommendation-letter/scripts/Test/test_generate_letter.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `escape_latex(value) -> str`; `format_date(iso_or_empty, language) -> str` (fr "Le 27 mars 2026", en "March 27, 2026"); `format_date_dispense(iso_or_empty) -> str` ("le 4 mars 2026"). When the date is empty, both use a fixed fallback `"[À COMPLÉTER]"` (no `datetime.now()` in tests -> deterministic; production passes an explicit date).

- [ ] **Step 1: Write the failing test** (append a class)

```python
class TestEscapeAndDates(unittest.TestCase):
    def test_escape_latex_specials(self):
        self.assertEqual(gl.escape_latex("R&D 50% #1 a_b $x {y} ~ ^"),
                         r"R\&D 50\% \#1 a\_b \$x \{y\} \textasciitilde{} \textasciicircum{}")

    def test_escape_keeps_accents(self):
        self.assertEqual(gl.escape_latex("étudiante à l'UQAC"),
                         "étudiante à l'UQAC")

    def test_format_date_fr(self):
        self.assertEqual(gl.format_date("2026-03-27", "fr"), "Le 27 mars 2026")

    def test_format_date_en(self):
        self.assertEqual(gl.format_date("2026-03-27", "en"), "March 27, 2026")

    def test_format_date_dispense(self):
        self.assertEqual(gl.format_date_dispense("2026-03-04"), "le 4 mars 2026")

    def test_format_date_empty_is_placeholder(self):
        self.assertEqual(gl.format_date("", "fr"), "[À COMPLÉTER]")
```

- [ ] **Step 2: Run to verify it fails**

Run: `rtk python -m unittest discover -s ".claude/skills/recommendation-letter/scripts/Test" -v`
Expected: FAIL `AttributeError: module 'generate_letter' has no attribute 'escape_latex'`.

- [ ] **Step 3: Write minimal implementation** (add to `generate_letter.py`)

```python
PLACEHOLDER = "[À COMPLÉTER]"

_LATEX_ESCAPES = [
    ("&", r"\&"), ("%", r"\%"), ("#", r"\#"), ("_", r"\_"),
    ("$", r"\$"), ("{", r"\{"), ("}", r"\}"),
    ("~", r"\textasciitilde{}"), ("^", r"\textasciicircum{}"),
]

MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
             "août", "septembre", "octobre", "novembre", "décembre"]
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December"]


def escape_latex(value):
    """Escape LaTeX specials in a plain-text scalar. Accents pass through."""
    if value is None:
        return ""
    out = str(value)
    for src, dst in _LATEX_ESCAPES:
        out = out.replace(src, dst)
    return out


def _split_iso(iso):
    """('2026','03','27') -> (2026, 3, 27) or None on any failure."""
    try:
        y, m, d = iso.split("-")
        return int(y), int(m), int(d)
    except (ValueError, AttributeError):
        return None


def format_date(iso, language):
    parts = _split_iso(iso)
    if parts is None:
        return PLACEHOLDER
    y, m, d = parts
    if language == "fr":
        return "Le %d %s %d" % (d, MONTHS_FR[m - 1], y)
    return "%s %d, %d" % (MONTHS_EN[m - 1], d, y)


def format_date_dispense(iso):
    parts = _split_iso(iso)
    if parts is None:
        return PLACEHOLDER
    y, m, d = parts
    return "le %d %s %d" % (d, MONTHS_FR[m - 1], y)
```

- [ ] **Step 4: Run to verify it passes**

Run: `rtk python -m unittest discover -s ".claude/skills/recommendation-letter/scripts/Test" -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
rtk git add .claude/skills/recommendation-letter/scripts
rtk git commit -m "feat(recommendation-letter): latex escaping and date formatting"
```

---

### Task 3: candidate_reference derivation (status x gender)

**Files:**
- Modify: `.claude/skills/recommendation-letter/scripts/generate_letter.py`
- Test: `.claude/skills/recommendation-letter/scripts/Test/test_generate_letter.py`

**Interfaces:**
- Produces: `derive_candidate_reference(config) -> str`; `status_title_warnings(config) -> list[str]`.
- Rules (section 5 of the spec): `graduated` -> uses `candidate_title` + name ("le Dr X" / "Dr. X"); `current_student` -> "X, étudiant(e) au <program>" / "X, a student in the <program>"; `applicant` -> "le candidat / M./Mme X" / "the candidate X". Gender: F -> étudiante / la candidate. Warn on graduated-without-doctoral-title and on applicant/current_student carrying "Dr.".

- [ ] **Step 1: Write the failing test** (append a class)

```python
def _cfg(**kw):
    base = {"candidate_name": "Candidat Exemple Bravo", "candidate_gender": "M",
            "candidate_status": "graduated", "candidate_title": "Dr.",
            "candidate_program": "génie", "language": "fr"}
    base.update(kw)
    return base


class TestCandidateReference(unittest.TestCase):
    def test_graduated_fr_uses_title(self):
        ref = gl.derive_candidate_reference(_cfg(status_ok=True))
        self.assertIn("Dr.", ref)
        self.assertIn("Candidat Exemple Bravo", ref)

    def test_current_student_fr_masc(self):
        ref = gl.derive_candidate_reference(
            _cfg(candidate_status="current_student", candidate_title="M.",
                 candidate_program="doctorat en ingénierie"))
        self.assertIn("étudiant au doctorat en ingénierie", ref)
        self.assertNotIn("étudiante", ref)

    def test_current_student_fr_fem(self):
        ref = gl.derive_candidate_reference(
            _cfg(candidate_gender="F", candidate_status="current_student",
                 candidate_name="Candidate Exemple Foxtrot", candidate_program="maîtrise"))
        self.assertIn("étudiante au maîtrise", ref)

    def test_applicant_fr_fem(self):
        ref = gl.derive_candidate_reference(
            _cfg(candidate_gender="F", candidate_status="applicant",
                 candidate_name="Candidate Exemple India"))
        self.assertIn("la candidate", ref)
        self.assertIn("Candidate Exemple India", ref)

    def test_current_student_en(self):
        ref = gl.derive_candidate_reference(
            _cfg(candidate_status="current_student", candidate_title="Mr.",
                 candidate_program="PhD program", language="en"))
        self.assertIn("a student in the PhD program", ref)

    def test_warn_graduated_without_title(self):
        warns = gl.status_title_warnings(
            _cfg(candidate_status="graduated", candidate_title="M."))
        self.assertTrue(any("doctoral title" in w for w in warns))

    def test_warn_applicant_with_dr(self):
        warns = gl.status_title_warnings(
            _cfg(candidate_status="applicant", candidate_title="Dr."))
        self.assertTrue(any("Dr." in w for w in warns))
```

- [ ] **Step 2: Run to verify it fails**

Run: `rtk python -m unittest discover -s ".claude/skills/recommendation-letter/scripts/Test" -v`
Expected: FAIL `has no attribute 'derive_candidate_reference'`.

- [ ] **Step 3: Write minimal implementation** (add to `generate_letter.py`)

```python
_DOCTORAL_TITLES = ("Dr.", "Dr", "Pr.", "Pr", "Pre.", "Dre.", "Prof.")


def derive_candidate_reference(config):
    """Canonical way to name the candidate, per status + gender + language."""
    name = config.get("candidate_name", "") or PLACEHOLDER
    status = config.get("candidate_status", "applicant")
    title = config.get("candidate_title", "")
    program = config.get("candidate_program", "") or PLACEHOLDER
    fem = config.get("candidate_gender", "M") == "F"
    lang = config.get("language", "fr")
    if status == "graduated":
        if lang == "fr":
            article = "la" if fem else "le"
            return ("%s %s %s" % (article, title, name)).strip()
        return ("%s %s" % (title, name)).strip()
    if status == "current_student":
        if lang == "fr":
            word = "étudiante" if fem else "étudiant"
            return "%s, %s au %s" % (name, word, program)
        return "%s, a student in the %s" % (name, program)
    # applicant
    if lang == "fr":
        noun = "la candidate" if fem else "le candidat"
        return "%s (%s)" % (noun, name)
    return "the candidate %s" % name


def status_title_warnings(config):
    warns = []
    status = config.get("candidate_status", "applicant")
    title = (config.get("candidate_title", "") or "").strip()
    if status == "graduated" and title not in _DOCTORAL_TITLES:
        warns.append("status is 'graduated' but candidate_title '%s' is not a "
                     "doctoral title" % title)
    if status in ("applicant", "current_student") and title in ("Dr.", "Dr", "Dre.", "Pr.", "Pr"):
        warns.append("status is '%s' but candidate_title is a doctoral title "
                     "'%s'" % (status, title))
    return warns
```

- [ ] **Step 4: Run to verify it passes**

Run: `rtk python -m unittest discover -s ".claude/skills/recommendation-letter/scripts/Test" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add .claude/skills/recommendation-letter/scripts
rtk git commit -m "feat(recommendation-letter): candidate reference + status/title warnings"
```

---

### Task 4: Style-hygiene linter

**Files:**
- Modify: `.claude/skills/recommendation-letter/scripts/generate_letter.py`
- Test: `.claude/skills/recommendation-letter/scripts/Test/test_generate_letter.py`

**Interfaces:**
- Produces: `style_hygiene_violations(text) -> list[str]` (one string per distinct violation kind found).

- [ ] **Step 1: Write the failing test** (append a class)

```python
class TestStyleHygiene(unittest.TestCase):
    def test_clean_text_has_no_violations(self):
        self.assertEqual(gl.style_hygiene_violations("Straight text, no tricks."), [])

    def test_flags_em_dash(self):
        v = gl.style_hygiene_violations("a — b")
        self.assertTrue(any("dash" in x for x in v))

    def test_flags_zero_width(self):
        v = gl.style_hygiene_violations("a​b")
        self.assertTrue(any("zero-width" in x for x in v))

    def test_flags_ellipsis_and_smart_quotes(self):
        v = gl.style_hygiene_violations("he said “hi”…")
        self.assertTrue(any("ellipsis" in x for x in v))
        self.assertTrue(any("smart quote" in x for x in v))

    def test_flags_stray_markdown(self):
        v = gl.style_hygiene_violations("**bold** left over")
        self.assertTrue(any("markdown" in x for x in v))
```

- [ ] **Step 2: Run to verify it fails**

Run: `rtk python -m unittest discover -s ".claude/skills/recommendation-letter/scripts/Test" -v`
Expected: FAIL `has no attribute 'style_hygiene_violations'`.

- [ ] **Step 3: Write minimal implementation** (add to `generate_letter.py`; add `import re` at top)

```python
# add near the top imports:
import re

_ZERO_WIDTH = ("​", "‌", "‍")
_SMART_QUOTES = ("“", "”", "‘", "’")


def style_hygiene_violations(text):
    """Return a list of style-hygiene problems (empty if clean).

    Enforces the .claude/CLAUDE.md 'Style hygiene' list on generated prose:
    invisible chars, ellipsis char, em/en dash, unicode tags, smart quotes,
    and stray markdown bold/heading marks.
    """
    text = text or ""
    found = []
    if any(z in text for z in _ZERO_WIDTH):
        found.append("zero-width character (U+200B/C/D)")
    if "…" in text:
        found.append("ellipsis character (U+2026) - use ...")
    if "—" in text or "–" in text:
        found.append("em/en dash (— –) - use a hyphen or parentheses")
    if any(0xE0000 <= ord(c) <= 0xE007F for c in text):
        found.append("unicode tag character (U+E0000-E007F)")
    if any(q in text for q in _SMART_QUOTES):
        found.append("smart quote - use straight quotes")
    if "**" in text or re.search(r"(?m)^\s*#", text):
        found.append("stray markdown (** or leading #)")
    return found
```

- [ ] **Step 4: Run to verify it passes**

Run: `rtk python -m unittest discover -s ".claude/skills/recommendation-letter/scripts/Test" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add .claude/skills/recommendation-letter/scripts
rtk git commit -m "feat(recommendation-letter): style-hygiene linter"
```

---

### Task 5: Gender placeholders + generic placeholder replacement

**Files:**
- Modify: `.claude/skills/recommendation-letter/scripts/letter_templates.py`
- Modify: `.claude/skills/recommendation-letter/scripts/generate_letter.py`
- Test: `.claude/skills/recommendation-letter/scripts/Test/test_generate_letter.py`

**Interfaces:**
- Produces (templates): `GENDER_MAP` dict of `{placeholder: (male, female)}`.
- Produces (logic): `apply_gender(text, gender) -> str`; `fill_scalars(text, mapping) -> str` (replaces `%%KEY%%` with escaped values; leaves unresolved `%%...%%` for the caller to detect).

- [ ] **Step 1: Write the failing test** (append a class)

```python
class TestGenderAndFill(unittest.TestCase):
    def test_apply_gender_female(self):
        out = gl.apply_gender(r"accepté%%GENDER_E%% et %%GENDER_HEUREUX%%", "F")
        self.assertEqual(out, "acceptée et heureuse")

    def test_apply_gender_male_empty_e(self):
        out = gl.apply_gender(r"invité%%GENDER_E%%", "M")
        self.assertEqual(out, "invité")

    def test_apply_gender_il_elle(self):
        self.assertEqual(gl.apply_gender("%%GENDER_IL%% travaille", "F"), "Elle travaille")

    def test_fill_scalars_escapes_values(self):
        out = gl.fill_scalars("Objet: %%TARGET%%", {"TARGET": "R&D lab"})
        self.assertEqual(out, r"Objet: R\&D lab")

    def test_fill_scalars_leaves_unknown(self):
        out = gl.fill_scalars("x %%MISSING%%", {})
        self.assertIn("%%MISSING%%", out)
```

- [ ] **Step 2: Run to verify it fails**

Run: `rtk python -m unittest discover -s ".claude/skills/recommendation-letter/scripts/Test" -v`
Expected: FAIL `has no attribute 'apply_gender'`.

- [ ] **Step 3a: Add the gender map to `letter_templates.py`**

```python
# Gender placeholders for the French form templates (acceptance, dispense).
# {placeholder_without_percents: (male, female)}
GENDER_MAP = {
    "GENDER_E": ("", "e"),
    "GENDER_CELUI": ("celui-ci", "celle-ci"),
    "GENDER_HEUREUX": ("heureux", "heureuse"),
    "GENDER_IL": ("Il", "Elle"),
    "GENDER_DE_ETUDIANT": ("de l'étudiant", "de l'étudiante"),
    "SALUTATION": ("Monsieur,", "Madame,"),
}
```

- [ ] **Step 3b: Add the logic to `generate_letter.py`** (add `import letter_templates as tpl` at top)

```python
# add near the top imports:
import letter_templates as tpl


def apply_gender(text, gender):
    """Replace %%GENDER_*%% / %%SALUTATION%% placeholders. Applied last."""
    idx = 1 if gender == "F" else 0
    out = text
    for key, pair in tpl.GENDER_MAP.items():
        out = out.replace("%%%%%s%%%%" % key, pair[idx])
    return out


def fill_scalars(text, mapping):
    """Replace %%KEY%% with escape_latex(value) for each key in mapping."""
    out = text
    for key, value in mapping.items():
        out = out.replace("%%%%%s%%%%" % key, escape_latex(value))
    return out
```

Note: `"%%%%%s%%%%" % key` produces the literal `%%KEY%%` (each `%%` is one escaped percent in the format string).

- [ ] **Step 4: Run to verify it passes**

Run: `rtk python -m unittest discover -s ".claude/skills/recommendation-letter/scripts/Test" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add .claude/skills/recommendation-letter/scripts
rtk git commit -m "feat(recommendation-letter): gender placeholders + scalar fill"
```

---

### Task 6: Funding paragraph builder (funding_provider branching)

**Files:**
- Modify: `.claude/skills/recommendation-letter/scripts/generate_letter.py`
- Test: `.claude/skills/recommendation-letter/scripts/Test/test_generate_letter.py`

**Interfaces:**
- Produces: `build_funding_paragraph(config) -> str`. Branches on `funding_provider` first, then `funding_model`. Returns `[À COMPLÉTER : détails du financement]` when nothing resolves. `%%GENDER_E%%` tokens inside are left for `apply_gender` to resolve later.

- [ ] **Step 1: Write the failing test** (append a class)

```python
class TestFunding(unittest.TestCase):
    def test_supervisor_mitacs_acceleration(self):
        p = gl.build_funding_paragraph(
            {"funding_provider": "supervisor",
             "funding_model": "mitacs_acceleration"})
        self.assertIn("MITACS Accélération", p)
        self.assertIn("12 500", p)

    def test_supervisor_befm(self):
        p = gl.build_funding_paragraph(
            {"funding_provider": "supervisor", "funding_model": "befm"})
        self.assertIn("BEFM", p)

    def test_candidate_self_funded(self):
        p = gl.build_funding_paragraph(
            {"funding_provider": "candidate", "funding_model": "self_funded"})
        self.assertIn("son propre financement", p)

    def test_candidate_external_scholarship(self):
        p = gl.build_funding_paragraph(
            {"funding_provider": "candidate", "funding_model": "scholarship",
             "funding_source_details": "PFLA (ELAP), 8600$ pour 4 mois"})
        self.assertIn("PFLA (ELAP)", p)

    def test_combination_has_both(self):
        p = gl.build_funding_paragraph(
            {"funding_provider": "combination", "funding_model": "befm",
             "funding_source_details": "et une bourse familiale"})
        self.assertIn("BEFM", p)
        self.assertIn("bourse familiale", p)

    def test_unresolved_placeholder(self):
        p = gl.build_funding_paragraph({"funding_provider": "supervisor"})
        self.assertIn("[À COMPLÉTER", p)
```

- [ ] **Step 2: Run to verify it fails**

Run: `rtk python -m unittest discover -s ".claude/skills/recommendation-letter/scripts/Test" -v`
Expected: FAIL `has no attribute 'build_funding_paragraph'`.

- [ ] **Step 3: Write minimal implementation** (add to `generate_letter.py`)

The digit-group separator is a narrow no-break space ` ` (LaTeX-safe under
utf8, matches the "12 500$" style in the real letters).

```python
_NNBSP = " "  # narrow no-break space for money grouping


def _supervisor_funding(config):
    model = config.get("funding_model", "") or ""
    amount = str(config.get("funding_amount", "") or "")
    parts = []
    if "mitacs_bso" in model:
        parts.append("L'étudiant%%GENDER_E%% a obtenu la bourse d'études "
                     "supérieures de MITACS (BSO) qui couvre 15" + _NNBSP + "000$ sur un an.")
    if "befm" in model:
        parts.append("Une bourse d'exemption des frais majorés (BEFM) de "
                     "12" + _NNBSP + "000$/an est également accordée.")
    if "mitacs_acceleration" in model:
        parts.append("Chaque unité de stage MITACS Accélération octroie une "
                     "bourse de 12" + _NNBSP + "500$, sous réserve de l'acceptation "
                     "des partenaires industriels et de la disponibilité des fonds.")
    if "mitacs_gra" in model:
        parts.append("L'étudiant%%GENDER_E%% bénéficie du programme MITACS "
                     "Globalink Research Award.")
    if "internal" in model:
        parts.append("L'étudiant%%GENDER_E%% pourra aussi agir comme "
                     "assistant%%GENDER_E%% de recherche (environ 2500$/an) et "
                     "auxiliaire d'enseignement (environ 2500$/an) au sein du LAR.i.")
    if amount and not parts:
        parts.append("Le montant de la bourse est de %s$/an, conditionnel à la "
                     "performance dans les activités de recherche." % amount)
    return parts


def _candidate_funding(config):
    model = config.get("funding_model", "") or ""
    details = config.get("funding_source_details", "") or ""
    parts = []
    if "self_funded" in model:
        parts.append("L'étudiant%%GENDER_E%% assure son propre financement "
                     "(ressources personnelles ou familiales).")
    if "scholarship" in model:
        base = "L'étudiant%%GENDER_E%% assure son propre financement au moyen "
        base += "d'une bourse externe"
        base += (" (%s)." % details) if details else "."
        parts.append(base)
        details = ""  # consumed
    if details:
        parts.append(details)
    return parts


def build_funding_paragraph(config):
    provider = config.get("funding_provider", "")
    parts = []
    if provider in ("supervisor", "combination"):
        parts += _supervisor_funding(config)
    if provider in ("candidate", "combination"):
        parts += _candidate_funding(config)
    extra = config.get("funding_source_details", "") or ""
    if provider == "supervisor" and extra and extra not in " ".join(parts):
        parts.append(extra)
    if not parts:
        return "[À COMPLÉTER : détails du financement]"
    return " ".join(parts)
```

- [ ] **Step 4: Run to verify it passes**

Run: `rtk python -m unittest discover -s ".claude/skills/recommendation-letter/scripts/Test" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add .claude/skills/recommendation-letter/scripts
rtk git commit -m "feat(recommendation-letter): funding paragraph with provider branching"
```

---

### Task 7: Shared scaffold + authored-track assembly + word count

**Files:**
- Modify: `.claude/skills/recommendation-letter/scripts/letter_templates.py`
- Modify: `.claude/skills/recommendation-letter/scripts/generate_letter.py`
- Test: `.claude/skills/recommendation-letter/scripts/Test/test_generate_letter.py`

**Interfaces:**
- Produces (templates): `PREAMBLE`, `LETTERHEAD_FR`, `LETTERHEAD_EN`, `SIGNATURE_FR`, `SIGNATURE_EN`.
- Produces (logic): `count_words(body_tex) -> int`; `assemble_authored(config) -> str` (full .tex string for the four authored types).

- [ ] **Step 1: Write the failing test** (append a class)

```python
class TestAuthoredAssembly(unittest.TestCase):
    def test_count_words_strips_commands(self):
        n = gl.count_words(r"\textbf{Bonjour} le monde entier")
        self.assertEqual(n, 4)  # Bonjour, le, monde, entier

    def test_assemble_authored_wraps_body(self):
        cfg = {"letter_type": "appreciation", "language": "fr",
               "date": "2026-03-27", "candidate_name": "Candidat Exemple Tango",
               "candidate_status": "graduated", "candidate_title": "Dr.",
               "target": "prix", "body_tex": "Corps de la lettre ici."}
        tex = gl.assemble_authored(cfg)
        self.assertIn(r"\begin{document}", tex)
        self.assertIn("Corps de la lettre ici.", tex)
        self.assertIn("Martin J.-D. Otis", tex)
        self.assertIn("Le 27 mars 2026", tex)

    def test_assemble_authored_en_uses_english_blocks(self):
        cfg = {"letter_type": "academic_position", "language": "en",
               "date": "2023-06-03", "candidate_name": "Candidat Exemple Bravo",
               "candidate_status": "graduated", "candidate_title": "Dr.",
               "target": "Professor position", "body_tex": "Body."}
        tex = gl.assemble_authored(cfg)
        self.assertIn("Best regards", tex)
        self.assertIn("Full Professor", tex)
```

- [ ] **Step 2: Run to verify it fails**

Run: `rtk python -m unittest discover -s ".claude/skills/recommendation-letter/scripts/Test" -v`
Expected: FAIL `has no attribute 'count_words'`.

- [ ] **Step 3a: Add scaffold constants to `letter_templates.py`**

```python
PREAMBLE = r"""\documentclass[11pt, letterpaper]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage[%%BABEL_LANGUAGE%%]{babel}
\usepackage[top=2.0cm, bottom=2.0cm, left=2.54cm, right=2.54cm]{geometry}
\usepackage{graphicx}
\usepackage{xcolor}
\usepackage[hidelinks]{hyperref}
\usepackage{parskip}
\setlength{\parskip}{6pt}
\setlength{\parindent}{0pt}
\usepackage{fancyhdr}
\pagestyle{fancy}
\fancyhf{}
\renewcommand{\headrulewidth}{0pt}
\renewcommand{\footrulewidth}{0pt}
"""

LETTERHEAD_FR = r"""\begin{document}
\noindent
\IfFileExists{uqac_logo.png}{\includegraphics[width=5cm]{uqac_logo.png}\hfill}{}%
\begin{minipage}[t]{0.55\textwidth}
\raggedleft\small
Professeur Martin Otis\\
Département des sciences appliquées\\
Université du Québec à Chicoutimi (UQAC)\\
555, boul.\ de l'Université, Chicoutimi (QC)\\
Canada, G7H 2B1
\end{minipage}
\vspace{12pt}\hrule\vspace{12pt}
"""

LETTERHEAD_EN = r"""\begin{document}
\noindent
\IfFileExists{uqac_logo.png}{\includegraphics[width=5cm]{uqac_logo.png}\hfill}{}%
\begin{minipage}[t]{0.55\textwidth}
\raggedleft\small
Professor Martin Otis\\
Department of Applied Sciences\\
Université du Québec à Chicoutimi (UQAC)\\
555, boul.\ de l'Université, Chicoutimi (QC)\\
Canada, G7H 2B1
\end{minipage}
\vspace{12pt}\hrule\vspace{12pt}
"""

SIGNATURE_FR = r"""\vspace{18pt}
Cordialement,

\vspace{24pt}
\textbf{Martin J.-D. Otis, ing. M.Sc.A. Ph.D.}\\
{\small Professeur titulaire en génie électrique et informatique de l'UQAC}\\
{\small Membre RISUQ, Centre CISD \& Regroupement ReSMIQ}\\
{\small Responsable du Laboratoire d'Automatique et de Robotique interactive (LAR.i)}\\
{\small Tél.~: (418) 545-5011 (poste 2577)}\\
{\small Courriel~: \href{mailto:Martin_Otis@uqac.ca}{Martin\_Otis@uqac.ca}}\\
{\small Site Web~: \href{https://lari.uqac.ca}{lari.uqac.ca}}
\end{document}
"""

SIGNATURE_EN = r"""\vspace{18pt}
Best regards,

\vspace{24pt}
\textbf{Martin J.-D. Otis, P.Eng., M.Sc.A., Ph.D.}\\
{\small Full Professor in Electrical and Computer Engineering, UQAC}\\
{\small Member RISUQ, CISD Centre \& ReSMIQ Group}\\
{\small Director, Interactive Automation and Robotics Laboratory (LAR.i)}\\
{\small Tel.: (418) 545-5011 (ext.\ 2577)}\\
{\small Email: \href{mailto:Martin_Otis@uqac.ca}{Martin\_Otis@uqac.ca}}\\
{\small Web: \href{https://lari.uqac.ca}{lari.uqac.ca}}
\end{document}
"""
```

- [ ] **Step 3b: Add assembly logic to `generate_letter.py`**

```python
def count_words(body_tex):
    """Count words in body prose. Strips LaTeX commands and braces first."""
    text = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", " ", body_tex or "")
    text = text.replace("{", " ").replace("}", " ")
    text = re.sub(r"[~^_&%$#\\]", " ", text)
    return len([w for w in text.split() if w])


def _babel(language):
    return "french" if language == "fr" else "english"


def assemble_authored(config):
    """Full .tex for scholarship/academic_position/industry_position/appreciation."""
    lang = config.get("language", "fr")
    preamble = tpl.PREAMBLE.replace("%%BABEL_LANGUAGE%%", _babel(lang))
    letterhead = tpl.LETTERHEAD_FR if lang == "fr" else tpl.LETTERHEAD_EN
    signature = tpl.SIGNATURE_FR if lang == "fr" else tpl.SIGNATURE_EN
    date = format_date(config.get("date", ""), lang)
    salutation = "Madame, Monsieur," if lang == "fr" else "Dear Members of the Committee,"
    ref = config.get("reference_number", "") or ""
    subject_word = "Objet~:" if lang == "fr" else "Subject:"
    ref_line = ("\\hfill %s\n\n" % escape_latex(ref)) if ref else ""
    subject = "\\textbf{%s %s %s}\n\n" % (
        subject_word,
        ("Lettre concernant" if lang == "fr" else "Regarding"),
        escape_latex(config.get("target", "") or PLACEHOLDER))
    body = config.get("body_tex", "") or ("[À COMPLÉTER : corps de la lettre]"
                                          if lang == "fr" else "[TO COMPLETE: body]")
    return "".join([preamble, letterhead, ref_line, date, "\n\n", subject,
                    salutation, "\n\n", body, "\n\n", signature])
```

- [ ] **Step 4: Run to verify it passes**

Run: `rtk python -m unittest discover -s ".claude/skills/recommendation-letter/scripts/Test" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add .claude/skills/recommendation-letter/scripts
rtk git commit -m "feat(recommendation-letter): scaffold constants + authored-track assembly"
```

---

### Task 8: Acceptance form template + conditional blocks

**Files:**
- Modify: `.claude/skills/recommendation-letter/scripts/letter_templates.py`
- Modify: `.claude/skills/recommendation-letter/scripts/generate_letter.py`
- Test: `.claude/skills/recommendation-letter/scripts/Test/test_generate_letter.py`

**Interfaces:**
- Produces (templates): `TEMPLATE_ACCEPTANCE_FR`, `DEGREE_DESCRIPTION` dict.
- Produces (logic): `build_acceptance(config) -> str` (full .tex). Resolves degree, collaborators sentence, MITACS opportunity sentence, funding paragraph (Task 6), prerequisites paragraph, project-details paragraph; then gender, then scalar fill.

- [ ] **Step 1: Write the failing test** (append a class)

```python
class TestAcceptance(unittest.TestCase):
    def _cfg(self, **kw):
        base = {"letter_type": "acceptance", "language": "fr",
                "date": "2023-05-23", "candidate_name": "Candidat Exemple Delta",
                "candidate_gender": "M", "candidate_status": "applicant",
                "degree_level": "msc",
                "project_description": "le diagnostic des systèmes hybrides",
                "funding_provider": "supervisor",
                "funding_model": "mitacs_acceleration", "funding_amount": "12500",
                "tools_technologies": "RoboDK et CodeSys",
                "project_end_date": "décembre 2025"}
        base.update(kw)
        return base

    def test_no_unresolved_placeholders(self):
        tex = gl.build_acceptance(self._cfg())
        self.assertNotIn("%%", tex)

    def test_subject_line_and_project(self):
        tex = gl.build_acceptance(self._cfg())
        self.assertIn("Confirmation d'acceptation de Candidat Exemple Delta", tex)
        self.assertIn("maîtrise de recherche", tex)
        self.assertIn("le diagnostic des systèmes hybrides", tex)

    def test_female_gender_agreement(self):
        tex = gl.build_acceptance(self._cfg(candidate_gender="F",
                                            candidate_name="Candidate Exemple Foxtrot",
                                            degree_level="msc"))
        self.assertIn("acceptée", tex)
        self.assertIn("heureuse", tex)

    def test_prerequisites_omitted_when_empty(self):
        tex = gl.build_acceptance(self._cfg(prerequisites=""))
        self.assertNotIn("propédeutique", tex)

    def test_prerequisites_present(self):
        tex = gl.build_acceptance(self._cfg(prerequisites="l'examen doctoral et deux cours"))
        self.assertIn("propédeutique", tex)
```

- [ ] **Step 2: Run to verify it fails**

Run: `rtk python -m unittest discover -s ".claude/skills/recommendation-letter/scripts/Test" -v`
Expected: FAIL `has no attribute 'build_acceptance'`.

- [ ] **Step 3a: Add the template + degree map to `letter_templates.py`**

```python
DEGREE_DESCRIPTION = {
    "msc": "une maîtrise de recherche (deuxième cycle)",
    "phd": "une thèse de doctorat (troisième cycle, profil recherche)",
    "phd_eng": "une thèse (doctorat en ingénierie, troisième cycle)",
    "research_stay": "un séjour de recherche",
}

TEMPLATE_ACCEPTANCE_FR = r"""%%LETTERHEAD_FR%%

%%DATE%%

\textbf{Objet~: Confirmation d'acceptation de %%CANDIDATE_NAME%% au sein du Laboratoire LAR.i de l'Université du Québec à Chicoutimi (UQAC).}

\vspace{6pt}

%%SALUTATION%%

En tant que futur directeur de recherche de l'étudiant%%GENDER_E%%, je confirme que %%GENDER_CELUI%% a été accepté%%GENDER_E%% pour réaliser %%DEGREE_DESCRIPTION%% au sein du laboratoire LAR.i de l'Université du Québec à Chicoutimi (UQAC). L'équipe du LAR.i est très %%GENDER_HEUREUX%% de recevoir %%CANDIDATE_NAME%%. Son projet de recherche porte sur %%PROJECT_DESCRIPTION%%. %%LAB_COLLABORATORS_SENTENCE%% %%MITACS_OPPORTUNITY_SENTENCE%%

%%PROJECT_DETAILS_PARAGRAPH%%

%%FUNDING_PARAGRAPH%%

%%PREREQUISITES_PARAGRAPH%%

Nous restons disponibles pour toutes questions concernant la situation %%GENDER_DE_ETUDIANT%% sous notre supervision.

Veuillez agréer l'expression de nos sentiments les meilleurs.

%%SIGNATURE_FR%%
"""
```

- [ ] **Step 3b: Add `build_acceptance` to `generate_letter.py`**

```python
def _clean_spaces(text):
    """Collapse the blank runs left by omitted conditional sentences."""
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text


def _acceptance_conditionals(config):
    model = config.get("funding_model", "") or ""
    collab = config.get("lab_collaborators", "") or ""
    collab_sentence = ("%%GENDER_IL%% travaillera avec " + collab + "."
                       if collab else "")
    if "mitacs_acceleration" in model:
        partner = config.get("partner_company", "") or ""
        clause = ("avec le partenaire industriel " + partner if partner else "")
        mitacs_sentence = ("%%GENDER_IL%% aura l'opportunité de réaliser un ou "
                           "plusieurs stages MITACS Accélération " + clause + ".")
    elif "mitacs_gra" in model:
        mitacs_sentence = ("%%GENDER_IL%% bénéficie du programme MITACS "
                           "Globalink Research Award.")
    else:
        mitacs_sentence = ""
    tools = config.get("tools_technologies", "") or ""
    end = config.get("project_end_date", "") or ""
    if tools:
        details = ("%%GENDER_IL%% sera responsable de la conception sous " + tools
                   + ".")
        if end:
            details += " Ce projet s'étendra jusqu'à la fin du mois de " + end + "."
        project_details = details
    else:
        project_details = ""
    prereq = config.get("prerequisites", "") or ""
    if prereq:
        prereq_par = ("Notez que l'acceptation est assortie d'une propédeutique "
                      "(condition) : la réussite de " + prereq + ". "
                      "L'étudiant%%GENDER_E%% pourra bénéficier d'une bourse à "
                      "condition de réussir ces cours.")
    else:
        prereq_par = ""
    return {
        "LAB_COLLABORATORS_SENTENCE": collab_sentence,
        "MITACS_OPPORTUNITY_SENTENCE": mitacs_sentence,
        "PROJECT_DETAILS_PARAGRAPH": project_details,
        "FUNDING_PARAGRAPH": build_funding_paragraph(config),
        "PREREQUISITES_PARAGRAPH": prereq_par,
        "DEGREE_DESCRIPTION": tpl.DEGREE_DESCRIPTION.get(
            config.get("degree_level", ""), "[À COMPLÉTER : niveau d'études]"),
    }


def build_acceptance(config):
    gender = config.get("candidate_gender", "M")
    text = tpl.TEMPLATE_ACCEPTANCE_FR
    text = text.replace("%%LETTERHEAD_FR%%",
                        tpl.LETTERHEAD_FR.replace("%%BABEL_LANGUAGE%%", "french"))
    text = tpl.PREAMBLE.replace("%%BABEL_LANGUAGE%%", "french") + text.replace(
        tpl.LETTERHEAD_FR, tpl.LETTERHEAD_FR)  # preamble prepended once
    text = text.replace("%%SIGNATURE_FR%%", tpl.SIGNATURE_FR)
    text = text.replace("%%DATE%%", format_date(config.get("date", ""), "fr"))
    # raw (non-escaped) conditional blocks - they contain LaTeX-safe French
    for key, value in _acceptance_conditionals(config).items():
        text = text.replace("%%%%%s%%%%" % key, value)
    # scalar (escaped) fields
    text = fill_scalars(text, {
        "CANDIDATE_NAME": config.get("candidate_name", "") or PLACEHOLDER,
        "PROJECT_DESCRIPTION": config.get("project_description", "") or PLACEHOLDER,
    })
    text = apply_gender(text, gender)
    return _clean_spaces(text)
```

Note on the preamble line: `TEMPLATE_ACCEPTANCE_FR` starts with the
`%%LETTERHEAD_FR%%` token; `build_acceptance` swaps in `LETTERHEAD_FR` and
prepends `PREAMBLE`. Keep the two `.replace` calls exactly as written so the
`\begin{document}` from the letterhead appears once, after the preamble.

- [ ] **Step 4: Run to verify it passes**

Run: `rtk python -m unittest discover -s ".claude/skills/recommendation-letter/scripts/Test" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add .claude/skills/recommendation-letter/scripts
rtk git commit -m "feat(recommendation-letter): acceptance form template + conditionals"
```

---

### Task 9: Dispense form template + immigration + 120-day logic

**Files:**
- Modify: `.claude/skills/recommendation-letter/scripts/letter_templates.py`
- Modify: `.claude/skills/recommendation-letter/scripts/generate_letter.py`
- Test: `.claude/skills/recommendation-letter/scripts/Test/test_generate_letter.py`

**Interfaces:**
- Produces (templates): `TEMPLATE_DISPENSE_FR`, `IMMIGRATION_PARAGRAPH_STANDARD`, `IMMIGRATION_EXTRA_CLAUSE`, `CONDITIONAL_SENTENCE`.
- Produces (logic): `stay_days(start, end) -> int|None`; `build_dispense(config) -> tuple[str, list[str]]` (returns the .tex and any warnings, e.g. the > 120 day warning).

- [ ] **Step 1: Write the failing test** (append a class)

```python
class TestDispense(unittest.TestCase):
    def _cfg(self, **kw):
        base = {"letter_type": "dispense", "language": "fr", "date": "2026-03-04",
                "candidate_name": "Candidat Exemple Golf", "candidate_gender": "M",
                "candidate_address": "12 rue de l'Exemple, Villeneuve, France",
                "stay_start": "2026/05/01", "stay_end": "2026/07/31",
                "remuneration": "aucune", "weekly_hours": "40",
                "home_institution": "Institut Exemple B",
                "tasks_description": "Conception d'un modèle LBM en PyTorch",
                "conditional_scholarship": "false"}
        base.update(kw)
        return base

    def test_stay_days(self):
        self.assertEqual(gl.stay_days("2026/05/01", "2026/07/31"), 91)
        self.assertEqual(gl.stay_days("2027/01/04", "2027/04/30"), 116)
        self.assertIsNone(gl.stay_days("bad", "2027/04/30"))

    def test_no_unresolved_placeholders(self):
        tex, _ = gl.build_dispense(self._cfg())
        self.assertNotIn("%%", tex)

    def test_immigration_paragraph_present(self):
        tex, _ = gl.build_dispense(self._cfg())
        self.assertIn("dispense de permis de travail", tex)
        self.assertIn("120 jours", tex)

    def test_conditional_sentence_precedes_immigration(self):
        tex, _ = gl.build_dispense(self._cfg(conditional_scholarship="true",
                                             conditional_scholarship_name="PFLA (ELAP)"))
        i_cond = tex.index("conditionnelle à l'obtention")
        i_imm = tex.index("dispense de permis de travail")
        self.assertLess(i_cond, i_imm)
        self.assertIn("PFLA (ELAP)", tex)

    def test_over_120_days_warns_and_adds_clause(self):
        tex, warns = gl.build_dispense(self._cfg(stay_start="2026/02/02",
                                                 stay_end="2026/07/03"))  # 151 d
        self.assertTrue(any("120" in w for w in warns))
        self.assertIn("validation auprès de l'immigration", tex)

    def test_female_salutation(self):
        tex, _ = gl.build_dispense(self._cfg(candidate_gender="F",
                                             candidate_name="Candidate Exemple India"))
        self.assertIn("Madame,", tex)
        self.assertIn("invitée", tex)
```

- [ ] **Step 2: Run to verify it fails**

Run: `rtk python -m unittest discover -s ".claude/skills/recommendation-letter/scripts/Test" -v`
Expected: FAIL `has no attribute 'stay_days'`.

- [ ] **Step 3a: Add constants to `letter_templates.py`**

```python
IMMIGRATION_PARAGRAPH_STANDARD = (
    "Vous êtes responsable de vérifier sur le site Web d'Immigration Canada "
    "quelles exigences d'autorisation d'entrée au Canada s'appliquent à votre "
    "situation et de tenir compte des délais à prévoir pour le traitement des "
    "demandes au Canada et dans les bureaux canadiens des visas à l'étranger. "
    "En vertu de la dispense de permis de travail visant les périodes de "
    "recherche en milieu universitaire de courte durée (120 jours ou moins) en "
    "vigueur depuis juin 2017, vous pourriez être autorisé à travailler au "
    "Canada sans permis de travail. Veuillez consulter le site d'Immigration "
    "Canada pour déterminer votre admissibilité")

IMMIGRATION_EXTRA_CLAUSE = (
    ", autrement, une validation auprès de l'immigration est requise de votre part")

CONDITIONAL_SENTENCE = (
    "Cette lettre est conditionnelle à l'obtention de la bourse "
    "%%CONDITIONAL_SCHOLARSHIP_NAME%%. ")

TEMPLATE_DISPENSE_FR = r"""\documentclass[11pt, letterpaper]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage[french]{babel}
\usepackage[top=2.0cm, bottom=2.0cm, left=2.54cm, right=2.54cm]{geometry}
\usepackage[hidelinks]{hyperref}
\usepackage{parskip}
\setlength{\parindent}{0pt}
\begin{document}

\noindent Chicoutimi, %%DATE%%

\vspace{12pt}

\noindent %%CANDIDATE_NAME_UPPER%%\\
%%CANDIDATE_ADDRESS%%

\vspace{12pt}

\noindent\textbf{Objet~: SÉJOUR DE RECHERCHE en tant que chercheur%%GENDER_E%% invité%%GENDER_E%% à l'Université du Québec à Chicoutimi pour MOINS DE 120 JOURS}

\vspace{12pt}

\noindent %%SALUTATION%%

\vspace{6pt}

J'ai le plaisir de vous inviter à effectuer un séjour de recherche à l'Université du Québec à Chicoutimi sous ma direction considérant que vous jouez un rôle important dans le projet de recherche et que vous possédez une expertise dans un domaine lié aux travaux de recherche visés.

\vspace{6pt}

\begin{tabular}{@{}p{5.5cm}p{9.5cm}@{}}
\textbf{Lieu de séjour~:} & Université du Québec à Chicoutimi\\
  & 555, boul.\ de l'Université\\
  & Chicoutimi, Québec, Canada\\[6pt]
\textbf{Responsable~:} & Martin Otis\\[6pt]
\textbf{Dates~:} & Du %%STAY_START%% au %%STAY_END%% inclusivement.\\[6pt]
\textbf{Rémunération~:} & %%REMUNERATION%%\\[6pt]
\textbf{Nombre d'heures hebdomadaires~:} & %%WEEKLY_HOURS%%\\[6pt]
\textbf{Nom de l'établissement d'origine~:} & %%HOME_INSTITUTION%%\\[6pt]
\textbf{Titre du poste~:} & Chercheur%%GENDER_E%% invité%%GENDER_E%%\\[6pt]
\textbf{Tâches~:} & %%TASKS_DESCRIPTION%%\\
\end{tabular}

\vspace{12pt}

%%CONDITIONAL_PARAGRAPH%%%%IMMIGRATION_PARAGRAPH%%.

\vspace{6pt}

N'hésitez pas à communiquer avec moi si vous avez besoin de renseignements complémentaires.

\vspace{12pt}

Sincères salutations,

\vspace{24pt}

\noindent\textbf{Martin J.-D. Otis, ing. M.Sc.A. Ph.D.}\\
{\small Professeur titulaire -- Université du Québec à Chicoutimi}\\
{\small \href{https://lari.uqac.ca}{lari.uqac.ca}}

\end{document}
"""
```

- [ ] **Step 3b: Add logic to `generate_letter.py`** (add `import datetime` at top)

```python
# add near the top imports:
import datetime


def stay_days(start, end):
    """Inclusive-exclusive day span between two YYYY/MM/DD dates, or None."""
    fmt = "%Y/%m/%d"
    try:
        d0 = datetime.datetime.strptime(start, fmt)
        d1 = datetime.datetime.strptime(end, fmt)
    except (ValueError, TypeError):
        return None
    return (d1 - d0).days


def build_dispense(config):
    warns = []
    gender = config.get("candidate_gender", "M")
    text = tpl.TEMPLATE_DISPENSE_FR
    text = text.replace("%%DATE%%", format_date_dispense(config.get("date", "")))
    # immigration + conditional
    immigration = tpl.IMMIGRATION_PARAGRAPH_STANDARD
    days = stay_days(config.get("stay_start", ""), config.get("stay_end", ""))
    if days is not None and days > 120:
        warns.append("Stay duration is %d days, exceeds the 120-day work-permit "
                     "exemption; subject line still says MOINS DE 120 JOURS - verify."
                     % days)
        immigration = immigration + tpl.IMMIGRATION_EXTRA_CLAUSE
    conditional = ""
    if str(config.get("conditional_scholarship", "")).lower() == "true":
        conditional = tpl.CONDITIONAL_SENTENCE.replace(
            "%%CONDITIONAL_SCHOLARSHIP_NAME%%",
            config.get("conditional_scholarship_name", "") or PLACEHOLDER)
    text = text.replace("%%CONDITIONAL_PARAGRAPH%%", conditional)
    text = text.replace("%%IMMIGRATION_PARAGRAPH%%", immigration)
    # scalar fills
    text = fill_scalars(text, {
        "CANDIDATE_ADDRESS": config.get("candidate_address", "") or PLACEHOLDER,
        "STAY_START": config.get("stay_start", "") or PLACEHOLDER,
        "STAY_END": config.get("stay_end", "") or PLACEHOLDER,
        "REMUNERATION": config.get("remuneration", "") or PLACEHOLDER,
        "WEEKLY_HOURS": str(config.get("weekly_hours", "") or "40"),
        "HOME_INSTITUTION": config.get("home_institution", "") or PLACEHOLDER,
        "TASKS_DESCRIPTION": config.get("tasks_description", "") or PLACEHOLDER,
    })
    name_upper = (config.get("candidate_name", "") or PLACEHOLDER).upper()
    text = text.replace("%%CANDIDATE_NAME_UPPER%%", escape_latex(name_upper))
    text = apply_gender(text, gender)
    return text, warns
```

- [ ] **Step 4: Run to verify it passes**

Run: `rtk python -m unittest discover -s ".claude/skills/recommendation-letter/scripts/Test" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add .claude/skills/recommendation-letter/scripts
rtk git commit -m "feat(recommendation-letter): dispense form + immigration + 120-day logic"
```

---

### Task 10: Two-track dispatch, warnings, paired output, main()

**Files:**
- Modify: `.claude/skills/recommendation-letter/scripts/generate_letter.py`
- Test: `.claude/skills/recommendation-letter/scripts/Test/test_generate_letter.py`

**Interfaces:**
- Produces: `generate(config) -> list[dict]` where each dict is `{"letter_type","tex","warnings","words"}`; `collect_warnings(config, body_or_none) -> list[str]`; `write_outputs(results, config, output_dir, compile_pdf, strict) -> int`. `main()` wires config -> generate -> write_outputs.
- `generate` dispatches: authored types -> one result via `assemble_authored`; `acceptance`/`dispense` -> the form builders; `invitation_pair == both` -> both acceptance and dispense results.

- [ ] **Step 1: Write the failing test** (append a class)

```python
class TestDispatch(unittest.TestCase):
    def test_authored_single_result(self):
        cfg = {"letter_type": "scholarship", "language": "fr", "date": "2026-03-27",
               "candidate_name": "Candidat Exemple Alpha", "candidate_status": "applicant",
               "candidate_gender": "M", "target": "PFLA", "body_tex": "Corps."}
        res = gl.generate(cfg)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["letter_type"], "scholarship")

    def test_invitation_pair_both_yields_two(self):
        cfg = {"letter_type": "acceptance", "language": "fr", "invitation_pair": "both",
               "date": "2025-12-28", "candidate_name": "Candidate Exemple India",
               "candidate_gender": "F", "candidate_status": "applicant",
               "degree_level": "research_stay", "project_description": "VLA robotique",
               "funding_provider": "supervisor", "funding_model": "mitacs_gra",
               "candidate_address": "Ville-Test, Pays-Exemple", "stay_start": "2026/04/01",
               "stay_end": "2026/06/24", "remuneration": "MITACS GRA",
               "home_institution": "Université Exemple C",
               "tasks_description": "VLA robotique", "conditional_scholarship": "false"}
        res = gl.generate(cfg)
        types = sorted(r["letter_type"] for r in res)
        self.assertEqual(types, ["acceptance", "dispense"])

    def test_collect_warnings_flags_placeholder(self):
        warns = gl.collect_warnings(
            {"letter_type": "appreciation", "language": "fr",
             "candidate_status": "graduated", "candidate_title": "M."},
            "body with [À COMPLÉTER] token")
        self.assertTrue(any("À COMPLÉTER" in w or "placeholder" in w.lower() for w in warns))
        self.assertTrue(any("doctoral title" in w for w in warns))

    def test_write_outputs_no_compile(self):
        import tempfile, os
        cfg = {"letter_type": "appreciation", "language": "fr", "date": "2026-03-27",
               "candidate_name": "Candidat Exemple Tango", "candidate_status": "graduated",
               "candidate_title": "Dr.", "target": "prix", "body_tex": "Corps."}
        res = gl.generate(cfg)
        d = tempfile.mkdtemp()
        code = gl.write_outputs(res, cfg, d, compile_pdf=False, strict=False)
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(os.path.join(d, "letter_tango_appreciation.tex")))
```

- [ ] **Step 2: Run to verify it fails**

Run: `rtk python -m unittest discover -s ".claude/skills/recommendation-letter/scripts/Test" -v`
Expected: FAIL `has no attribute 'generate'`.

- [ ] **Step 3: Write minimal implementation** (add to `generate_letter.py`)

```python
_AUTHORED = ("scholarship", "academic_position", "industry_position", "appreciation")


def collect_warnings(config, body_or_none):
    warns = list(status_title_warnings(config))
    probe = body_or_none if body_or_none is not None else ""
    if PLACEHOLDER in probe or "[TO COMPLETE]" in probe:
        warns.append("placeholder %s present - manual editing needed" % PLACEHOLDER)
    if body_or_none:
        for v in style_hygiene_violations(body_or_none):
            warns.append("style hygiene: " + v)
        limit = str(config.get("limit", ""))
        if "word" in limit:
            digits = "".join(ch for ch in limit if ch.isdigit())
            if digits and count_words(body_or_none) > int(digits):
                warns.append("body is %d words, limit is %s"
                             % (count_words(body_or_none), limit))
    return warns


def generate(config):
    ltype = config.get("letter_type", "")
    pair = config.get("invitation_pair", "")
    results = []
    if ltype in _AUTHORED:
        tex = assemble_authored(config)
        body = config.get("body_tex", "")
        results.append({"letter_type": ltype, "tex": tex,
                        "warnings": collect_warnings(config, body),
                        "words": count_words(body)})
        return results
    make_acc = ltype == "acceptance" or pair in ("both", "acceptance_only")
    make_dis = ltype == "dispense" or pair in ("both", "dispense_only")
    if ltype == "acceptance" and pair == "dispense_only":
        make_acc, make_dis = False, True
    if ltype == "dispense" and pair == "acceptance_only":
        make_acc, make_dis = True, False
    if pair == "both":
        make_acc = make_dis = True
    if make_acc:
        tex = build_acceptance(config)
        results.append({"letter_type": "acceptance", "tex": tex,
                        "warnings": collect_warnings(config, None), "words": 0})
    if make_dis:
        tex, w = build_dispense(config)
        results.append({"letter_type": "dispense", "tex": tex,
                        "warnings": collect_warnings(config, None) + w, "words": 0})
    return results


def write_outputs(results, config, output_dir, compile_pdf, strict):
    os.makedirs(output_dir, exist_ok=True)
    surname = surname_slug(config.get("candidate_name", "")) or "candidate"
    exit_code = 0
    for res in results:
        stem = "letter_%s_%s" % (surname, res["letter_type"])
        tex_path = os.path.join(output_dir, stem + ".tex")
        with open(tex_path, "w", encoding="utf-8") as fh:
            fh.write(res["tex"])
        print("Wrote %s (%d words)" % (tex_path, res["words"]))
        for w in res["warnings"]:
            print("WARNING: " + w, file=sys.stderr)
        hygiene = style_hygiene_violations(res["tex"])
        if hygiene and strict:
            for h in hygiene:
                print("STRICT style hygiene: " + h, file=sys.stderr)
            exit_code = 3
        if compile_pdf:
            compile_latex(tex_path, output_dir)
    return exit_code
```

Update `main()` to call the pipeline (replace the `_ = config` stub):

```python
def main(argv=None):
    args = parse_args(argv)
    try:
        config = load_config(args.config)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    results = generate(config)
    return write_outputs(results, config, args.output,
                         compile_pdf=not args.no_compile, strict=args.strict)
```

`compile_latex` is defined in Task 11; until then run tests with `compile_pdf=False`
(the test does exactly this).

- [ ] **Step 4: Run to verify it passes**

Run: `rtk python -m unittest discover -s ".claude/skills/recommendation-letter/scripts/Test" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add .claude/skills/recommendation-letter/scripts
rtk git commit -m "feat(recommendation-letter): two-track dispatch, warnings, paired output"
```

---

### Task 11: pdflatex compile + page count + eval configs

**Files:**
- Modify: `.claude/skills/recommendation-letter/scripts/generate_letter.py`
- Create: `.claude/skills/recommendation-letter/evals/evals.json`
- Create: `.claude/skills/recommendation-letter/evals/test_scholarship_fr.json`
- Create: `.claude/skills/recommendation-letter/evals/test_academic_en.json`
- Create: `.claude/skills/recommendation-letter/evals/test_academic_fr.json`
- Create: `.claude/skills/recommendation-letter/evals/test_acceptance_msc.json`
- Create: `.claude/skills/recommendation-letter/evals/test_acceptance_phd.json`
- Create: `.claude/skills/recommendation-letter/evals/test_acceptance_female.json`
- Create: `.claude/skills/recommendation-letter/evals/test_dispense.json`
- Create: `.claude/skills/recommendation-letter/evals/test_dispense_conditional.json`
- Create: `.claude/skills/recommendation-letter/evals/test_both_pair.json`
- Test: `.claude/skills/recommendation-letter/scripts/Test/test_generate_letter.py`

**Interfaces:**
- Produces: `compile_latex(tex_path, output_dir) -> bool`; `count_pdf_pages(pdf_path) -> int`.

- [ ] **Step 1: Write the failing test** (append a class — page count runs on a byte fixture, no pdflatex)

```python
class TestCompileHelpers(unittest.TestCase):
    def test_count_pdf_pages_from_bytes(self):
        import tempfile, os
        data = (b"%PDF-1.5\n/Type /Pages /Count 2\n/Type /Page\n/Type /Page\n%%EOF")
        fd, path = tempfile.mkstemp(suffix=".pdf")
        os.write(fd, data); os.close(fd)
        try:
            self.assertEqual(gl.count_pdf_pages(path), 2)
        finally:
            os.unlink(path)

    def test_compile_latex_missing_pdflatex_returns_false(self):
        # When pdflatex is absent, compile_latex must not raise.
        import tempfile, os
        d = tempfile.mkdtemp()
        tex = os.path.join(d, "x.tex")
        with open(tex, "w", encoding="utf-8") as fh:
            fh.write(r"\documentclass{article}\begin{document}x\end{document}")
        result = gl.compile_latex(tex, d)  # True or False, never an exception
        self.assertIn(result, (True, False))
```

- [ ] **Step 2: Run to verify it fails**

Run: `rtk python -m unittest discover -s ".claude/skills/recommendation-letter/scripts/Test" -v`
Expected: FAIL `has no attribute 'count_pdf_pages'`.

- [ ] **Step 3: Write minimal implementation** (add to `generate_letter.py`; add `import subprocess` at top)

```python
# add near the top imports:
import subprocess


def count_pdf_pages(pdf_path):
    """Approximate page count: /Type /Page minus /Type /Pages occurrences."""
    with open(pdf_path, "rb") as fh:
        content = fh.read()
    return content.count(b"/Type /Page") - content.count(b"/Type /Pages")


def compile_latex(tex_path, output_dir):
    """Compile .tex to .pdf via pdflatex (two passes). False if unavailable."""
    cmd = ["pdflatex", "-interaction=nonstopmode",
           "-output-directory", output_dir, tex_path]
    try:
        for _ in range(2):
            subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        print("INFO: pdflatex unavailable or timed out (%s); .tex only." % exc,
              file=sys.stderr)
        return False
    pdf_path = tex_path[:-4] + ".pdf" if tex_path.endswith(".tex") else tex_path + ".pdf"
    if os.path.exists(pdf_path):
        for ext in (".aux", ".log", ".out"):
            aux = tex_path[:-4] + ext if tex_path.endswith(".tex") else None
            if aux and os.path.exists(aux):
                os.remove(aux)
        pages = count_pdf_pages(pdf_path)
        print("Compiled %s (%d page(s))" % (pdf_path, pages))
        return True
    return False
```

- [ ] **Step 4: Create the eval configs**

`evals/test_scholarship_fr.json` (authored track needs a `body_tex`; keep short):

```json
{
  "letter_type": "scholarship", "language": "fr",
  "target": "Programme des futurs leaders dans les Amériques (PFLA)",
  "target_institution": "Université du Québec à Chicoutimi",
  "limit": "350 words", "date": "2026-03-27",
  "candidate_name": "Candidat Exemple Alpha", "candidate_gender": "M",
  "candidate_status": "applicant", "candidate_title": "M.",
  "candidate_program": "Baccalauréat en génie de maintenance industrielle",
  "funding_provider": "candidate", "funding_model": "scholarship",
  "body_tex": "Par la présente, j'appuie sans réserve la candidature de le candidat (Candidat Exemple Alpha) au Programme des futurs leaders dans les Amériques. Son dossier montre une moyenne de 8,9 sur 10 et une expertise en systèmes pneumatiques et hydrauliques. Il sera intégré au projet IndustrialDiagnosis au LAR.i et au CURAL, sur la maintenance prédictive des cuves d'électrolyse par intelligence artificielle. Je demeure disponible pour tout complément d'information."
}
```

`evals/test_academic_en.json`:

```json
{
  "letter_type": "academic_position", "language": "en",
  "target": "Professor position", "target_institution": "University of Sherbrooke",
  "limit": "2 pages", "date": "2023-06-03",
  "candidate_name": "Candidat Exemple Bravo", "candidate_gender": "M",
  "candidate_status": "graduated", "candidate_title": "Dr.",
  "candidate_program": "Ph.D. in Engineering, UQAC",
  "body_tex": "I recommend Dr. Candidat Exemple Bravo without reservation for a faculty position. Over three years as his research director, he published first-author papers in journals with impact factors above 3 and contributed to MITACS Acceleration and NSERC projects. He taught Human-Robot Interaction at the graduate level and Industrial Automation to undergraduates. I remain available to provide further information."
}
```

`evals/test_academic_fr.json`:

```json
{
  "letter_type": "academic_position", "language": "fr",
  "target": "Poste de professeur", "target_institution": "Université de Moncton",
  "limit": "2 pages", "reference_number": "REF-2025-001", "date": "2025-02-14",
  "candidate_name": "Candidat Exemple Charlie", "candidate_gender": "M",
  "candidate_status": "graduated", "candidate_title": "Dr.",
  "candidate_program": "Doctorat en ingénierie, UQAC",
  "body_tex": "Je recommande le Dr Candidat Exemple Charlie pour un poste de professeur. Sous ma direction de 2020 à 2024, il a publié trois revues (Elsevier, IF 3; Springer, IF 9,1). Il s'est impliqué dans les Commissions de l'UQAC et a géré un projet industriel difficile dont la solution sert encore dans trois autres projets. Nous prévoyons collaborer sur des subventions CRSNG et MITACS. Je demeure disponible pour tout complément."
}
```

`evals/test_acceptance_msc.json`:

```json
{
  "letter_type": "acceptance", "language": "fr", "invitation_pair": "acceptance_only",
  "date": "2023-05-23", "candidate_name": "Candidat Exemple Delta",
  "candidate_gender": "M", "candidate_status": "applicant", "candidate_title": "M.",
  "degree_level": "msc",
  "project_description": "le diagnostic des systèmes hybrides dans les systèmes manufacturiers flexibles liés à l'industrie 5.0",
  "lab_collaborators": "un étudiant au doctorat déjà en place",
  "funding_provider": "supervisor", "funding_model": "mitacs_acceleration",
  "funding_amount": "12500", "project_end_date": "décembre 2025",
  "tools_technologies": "RoboDK et CodeSys, XCOS avec Python/FBD", "prerequisites": ""
}
```

`evals/test_acceptance_phd.json`:

```json
{
  "letter_type": "acceptance", "language": "fr", "invitation_pair": "acceptance_only",
  "date": "2026-05-12", "candidate_name": "Candidat Exemple Echo",
  "candidate_gender": "M", "candidate_status": "applicant", "candidate_title": "M.",
  "degree_level": "phd_eng",
  "project_description": "la conception d'un jumeau numérique des cuves d'aluminium",
  "lab_collaborators": "un autre étudiant au doctorat déjà en place",
  "funding_provider": "supervisor", "funding_model": "combination",
  "funding_amount": "35000",
  "funding_source_details": "Bourse de 35 000$CAN/an sur trois ans, conditionnelle à la réussite de l'examen doctoral et de deux cours.",
  "project_end_date": "janvier 2029",
  "tools_technologies": "capteurs virtuels et modèles d'analyse du flux tendu",
  "prerequisites": "l'examen doctoral et deux cours"
}
```

`evals/test_acceptance_female.json`:

```json
{
  "letter_type": "acceptance", "language": "fr", "invitation_pair": "acceptance_only",
  "date": "2023-12-15", "candidate_name": "Candidate Exemple Foxtrot",
  "candidate_gender": "F", "candidate_status": "applicant", "candidate_title": "Mme",
  "degree_level": "msc",
  "project_description": "la conception d'un robot hybride pour opérer des sous-stations électriques en réalité étendue",
  "lab_collaborators": "une équipe déjà en place",
  "funding_provider": "supervisor", "funding_model": "mitacs_acceleration",
  "mitacs_reference": "IT00001", "partner_company": "Entreprise Exemple inc.",
  "partner_description": "Entreprise Exemple inc. est une entreprise en démarrage en conception et mise en service d'installations robotiques.",
  "prerequisites": ""
}
```

`evals/test_dispense.json`:

```json
{
  "letter_type": "dispense", "language": "fr", "invitation_pair": "dispense_only",
  "date": "2026-03-04", "candidate_name": "Candidat Exemple Golf", "candidate_gender": "M",
  "candidate_address": "12 rue de l'Exemple, 00000 Villeneuve, France",
  "stay_start": "2026/05/01", "stay_end": "2026/07/31", "remuneration": "aucune",
  "weekly_hours": "40", "home_institution": "Institut Exemple B",
  "tasks_description": "Conception d'un modèle Large de Comportements (LBM) en système robotique autonome au format ONNX dans PyTorch",
  "conditional_scholarship": "false"
}
```

`evals/test_dispense_conditional.json`:

```json
{
  "letter_type": "dispense", "language": "fr", "invitation_pair": "dispense_only",
  "date": "2026-03-13", "candidate_name": "Candidat Exemple Alpha",
  "candidate_gender": "M",
  "candidate_address": "avenue de l'Exemple 11, Quartier Modele, 00000 Ville-Test, Pays-Exemple",
  "stay_start": "2027/01/04", "stay_end": "2027/04/30",
  "remuneration": "Offerte par la bourse PFLA (ELAP), 8600$ pour 4 mois",
  "weekly_hours": "40", "home_institution": "Université Exemple A",
  "tasks_description": "Système d'optimisation et de maintenance d'une cuve par intelligence artificielle (LLM) dans la production primaire de l'aluminium",
  "conditional_scholarship": "true", "conditional_scholarship_name": "PFLA (ELAP)"
}
```

`evals/test_both_pair.json`:

```json
{
  "letter_type": "acceptance", "language": "fr", "invitation_pair": "both",
  "date": "2025-12-28", "candidate_name": "Candidate Exemple India", "candidate_gender": "F",
  "candidate_status": "applicant", "candidate_title": "Mme",
  "candidate_address": "12 rue de l'Exemple, Ville-Test, Pays-Exemple",
  "degree_level": "research_stay",
  "project_description": "la conception d'un modèle Vision-Langage-Action (VLA) en robotique agricole",
  "funding_provider": "supervisor", "funding_model": "mitacs_gra",
  "funding_amount": "6000", "mitacs_reference": "IT00002",
  "stay_start": "2026/04/01", "stay_end": "2026/06/24",
  "remuneration": "Offerte par MITACS programme GRA, IT00002, 6000$",
  "weekly_hours": "40", "home_institution": "Université Exemple C",
  "tasks_description": "Conception d'un modèle Vision-Langage-Action (VLA) en robotique agricole",
  "conditional_scholarship": "false"
}
```

`evals/evals.json`:

```json
{
  "skill_name": "recommendation-letter",
  "evals": [
    {"id": 1, "config": "test_scholarship_fr.json",
     "assert": ["exit 0", "no %%", "word count <= 350", "mentions PFLA"]},
    {"id": 2, "config": "test_academic_en.json",
     "assert": ["exit 0", "babel english", "mentions MITACS/NSERC"]},
    {"id": 3, "config": "test_academic_fr.json",
     "assert": ["exit 0", "contains REF-2025-001", "mentions Elsevier and Springer"]},
    {"id": 4, "config": "test_acceptance_msc.json",
     "assert": ["exit 0", "no %%", "maîtrise de recherche", "RoboDK"]},
    {"id": 5, "config": "test_acceptance_phd.json",
     "assert": ["exit 0", "no %%", "doctorat en ingénierie", "propédeutique"]},
    {"id": 6, "config": "test_acceptance_female.json",
     "assert": ["exit 0", "no %%", "acceptée", "heureuse", "Entreprise Exemple inc."]},
    {"id": 7, "config": "test_dispense.json",
     "assert": ["exit 0", "no %%", "dispense de permis de travail", "aucune"]},
    {"id": 8, "config": "test_dispense_conditional.json",
     "assert": ["exit 0", "conditionnelle à l'obtention", "PFLA (ELAP)"]},
    {"id": 9, "config": "test_both_pair.json",
     "assert": ["exit 0", "two tex files", "acceptance + dispense", "invitée"]}
  ]
}
```

- [ ] **Step 5: Run the unit tests, then smoke-run the evals with --no-compile**

Run: `rtk python -m unittest discover -s ".claude/skills/recommendation-letter/scripts/Test" -v`
Expected: PASS (all classes).

Then smoke-run every eval config (no LaTeX needed):

```bash
for f in .claude/skills/recommendation-letter/evals/test_*.json; do
  rtk python .claude/skills/recommendation-letter/scripts/generate_letter.py \
    --config "$f" --output "$TMPDIR/rl" --no-compile || echo "FAILED $f"
done
rtk grep -l "%%" "$TMPDIR"/rl/*.tex && echo "UNRESOLVED PLACEHOLDER" || echo "clean"
```

Expected: every config prints a `Wrote ...` line, exit 0; the `grep` reports `clean`
(no `%%` left). `test_both_pair.json` writes two `.tex` files.

- [ ] **Step 6: Commit**

```bash
rtk git add .claude/skills/recommendation-letter/scripts .claude/skills/recommendation-letter/evals
rtk git commit -m "feat(recommendation-letter): pdflatex compile, page count, eval configs"
```

---

### Task 12: SKILL.md + command wrapper

**Files:**
- Create: `.claude/skills/recommendation-letter/SKILL.md`
- Create: `.claude/commands/recommendation-letter.md`

**Interfaces:** none (documentation/config files).

- [ ] **Step 1: Write `SKILL.md`**

Frontmatter `name` + trigger-rich `description` (English body; French only in the
example deliverable strings). Cover: the two tracks, candidate_status logic,
funding_provider, the ingest -> elicit -> author -> generate -> validate -> deliver
workflow, output to `out/`, and the script call. Reproduce the section-10 workflow of
the spec. Include the acceptance/dispense/invitation trigger phrases
(`lettre d'appui`, `lettre de recommandation`, `lettre d'appréciation`,
`lettre d'acceptation`, `lettre d'invitation`, `lettre de dispense`,
`work permit exemption`, PFLA, ELAP, MITACS, CRSNG, FRQNT).

Key body content (write it in full in the file):

```markdown
---
name: recommendation-letter
description: >
  Generate support, recommendation, appreciation, acceptance, and dispense
  (short-stay invitation) letters for students and candidates of Prof. Martin
  Otis / LAR.i, in LaTeX compiled to PDF. Ingests the candidate's own files
  (CV, transcript, project description, motivation letter) and highlights both
  the candidate's dossier and the professor's own experience. Trigger on:
  recommendation letter, support letter, appreciation letter, acceptance
  letter, invitation letter, dispense / work permit exemption letter, lettre
  d'appui, lettre de recommandation, lettre d'appréciation, lettre
  d'acceptation, lettre d'invitation, lettre de dispense, PFLA, ELAP, CRSNG,
  FRQNT, MITACS, or /recommendation-letter.
allowed-tools: [Read, Write, Edit, Bash, AskUserQuestion, Glob]
---

# Recommendation Letter Generator

Two tracks. Authored track (scholarship, academic_position, industry_position,
appreciation; fr or en): Claude writes the body prose. Form track (acceptance,
dispense; fr only): the script fills a fixed template. All output goes to out/.

## Candidate status (drives titling)
- applicant: admission candidate, not yet a student -> "le candidat / M. X".
- current_student: on the team, not graduated -> "X, étudiant(e) au <programme>".
- graduated: degree done -> "le Dr X" / "Dr. X".

## Funding provider (acceptance/dispense)
- supervisor: you fund via an organism (MITACS, CRSNG, FRQNT, BEFM, internal).
- candidate: candidate's own funding (external scholarship, or self/family funded).
- combination: both.

## Workflow
1. Ingest candidate files from $ARGUMENTS (folder or paths): extract GPA,
   courses, publications, project facts, dates.
2. Elicit gaps (AskUserQuestion): Round 1 context (letter_type, language,
   target, limit; for forms invitation_pair + funding_provider); Round 2
   profile (incl. candidate_status); Round 3 type-specific + the professor's
   own experience with the candidate. Flag missing values [À COMPLÉTER].
3. Confirm the JSON summary + candidate reference preview.
4. Author body_tex (authored track only): opening verdict, dossier highlights,
   the professor's own experience, honest weighing, availability. No em dash,
   straight quotes, no invisible characters (AI-usage < 20%).
5. Generate: write the config to the scratchpad and run
   python .claude/skills/recommendation-letter/scripts/generate_letter.py
   --config <json> --output out/
6. Read warnings; fix body / fields; re-run.
7. Deliver the .tex and .pdf from out/ (two of each when invitation_pair=both).

## Notes
- Reproduce the exact administrative wording for acceptance/dispense; the
  script owns it. Do not paraphrase the immigration paragraph.
- Never fabricate a grade, a publication, or a funding amount. If a fact is
  not in the candidate files or given by the professor, leave [À COMPLÉTER].
```

- [ ] **Step 2: Write `.claude/commands/recommendation-letter.md`**

```markdown
# Recommendation, support, appreciation, acceptance, and dispense letters

Generate a LAR.i / Prof. Otis letter in LaTeX -> PDF. Read the skill at
`.claude/skills/recommendation-letter/SKILL.md` and follow its workflow.

1. Resolve candidate files from the arguments (a folder, a list of paths, or
   the file open in the IDE) and extract the facts.
2. Elicit the missing context with AskUserQuestion (letter type, language,
   candidate_status, funding_provider for acceptance/dispense, invitation
   pairing).
3. For the four authored types, write the body prose (highlight the candidate
   dossier and the professor's own experience; style hygiene, AI-usage < 20%).
   For acceptance/dispense, only collect field values.
4. Write the JSON config to the scratchpad and run:
   `python .claude/skills/recommendation-letter/scripts/generate_letter.py --config <json> --output out/`
5. Resolve every warning, then deliver the .tex and .pdf from out/.

For an invitation for a new international student, offer both the acceptance
and the dispense letter (invitation_pair=both).

$ARGUMENTS

Respond in French unless the active file is in English.
```

- [ ] **Step 3: Verify the skill loads (no runtime, just presence)**

Run: `rtk ls .claude/skills/recommendation-letter`
Expected: `SKILL.md`, `scripts`, `references` (Task 13), `evals`.

- [ ] **Step 4: Commit**

```bash
rtk git add .claude/skills/recommendation-letter/SKILL.md .claude/commands/recommendation-letter.md
rtk git commit -m "feat(recommendation-letter): SKILL.md workflow + /command wrapper"
```

---

### Task 13: references/quality-patterns.md

**Files:**
- Create: `.claude/skills/recommendation-letter/references/quality-patterns.md`

**Interfaces:** none.

- [ ] **Step 1: Write the reference doc** (authored-track guidance; English)

Content: the "patterns to replicate" and "anti-patterns" from the base plan's
Appendix A, plus the candidate_status phrasing table and a note that the
professor's own experience must appear as a distinct, concrete paragraph.

```markdown
# Quality patterns for authored letters

Claude reads this when writing body_tex for scholarship / academic_position /
industry_position / appreciation letters.

## Replicate
1. Direct opening verdict: first sentence states the relationship and a clear
   recommendation. Do not bury it.
2. Quantified claims: back each assertion with a number or named example
   (impact factor, GPA, project name, number of students).
3. Named funding sources: CRSNG, FRQNT, MITACS, FRQ-NT by name.
4. The professor's own experience: one concrete paragraph on working with the
   candidate (a difficult project handled, a result delivered), distinct from
   the candidate's self-presentation.
5. Future collaboration: closing names planned co-supervision, co-authorship,
   or joint grants.
6. Availability: offer to provide more information.
7. Specific course names and levels, not "he taught courses".

## Avoid
1. Generic superlatives without evidence.
2. Repeating the same point across paragraphs.
3. Passive voice that weakens the recommendation.
4. Skills listed without context.
5. Paragraphs over 8 sentences.
6. Leftover placeholder text or [À COMPLÉTER] tokens in the final letter.
7. Em dashes, smart quotes, invisible characters (AI-usage < 20%).

## Candidate reference by status
- applicant: "le candidat / M./Mme X" (never "étudiant").
- current_student: "X, étudiant(e) au <programme>".
- graduated: "le Dr X" / "Dr. X".
```

- [ ] **Step 2: Commit**

```bash
rtk git add .claude/skills/recommendation-letter/references
rtk git commit -m "docs(recommendation-letter): authored-track quality patterns"
```

---

### Task 14: Inventory + mirror updates, regenerate, verify, commit

**Files:**
- Modify: `README.md`
- Modify: `Architecture.md`
- Modify: `.claude/CLAUDE.md`
- Modify: `.claude/rules/workflows.md`
- Modify: `install.ps1`
- Regenerated by `install.ps1`: `.github/`, `.opencode/`, `.continue/`, `CONVENTIONS.md`

**Interfaces:** none (docs + generated mirrors).

- [ ] **Step 1: `.claude/CLAUDE.md` routing table** — add a row after the `word2latex` row:

```markdown
| Draft a support, recommendation, appreciation, acceptance, or dispense (short-stay invitation) letter from a candidate's files | `recommendation-letter` skill | `/recommendation-letter` |
```

- [ ] **Step 2: `.claude/rules/workflows.md`** — add a row to the "Research and writing flows" table:

```markdown
| Draft a recommendation / support / appreciation / acceptance / dispense letter | `/recommendation-letter` | `recommendation-letter` skill | LaTeX letter(s) compiled to PDF in `out/` |
```

- [ ] **Step 3: `README.md`** — bump the skill count 10 -> 11 in the three
places it appears (the "**N skills**" header, the "N ship" sentence, the
File-Locations "(N skills)"), bump the command count 19 -> 20 (header +
File-Locations "(N commands)"), add the skills-table row, a `### recommendation-letter`
subsection, a Prerequisites `pdflatex` row (if not already present), the
Commands-table row, and both File-Locations tree entries (fix the `└──`/`├──`
connector on the previous last skill and last command). First locate them:

Run: `rtk grep -n "skills" README.md | rtk grep -iE "[0-9]+ skills"` and
`rtk grep -n "word2latex" README.md`
to find the exact count strings and the tree anchor, then edit each.

The `### recommendation-letter` subsection text:

```markdown
### recommendation-letter

Generates support, recommendation, appreciation, acceptance, and dispense
(short-stay invitation) letters in LaTeX -> PDF for Prof. Otis / LAR.i. Two
tracks: Claude authors the four persuasive types (fr/en); a stdlib-only Python
script fills the fixed French acceptance/dispense forms (candidate status,
funding provider, 120-day work-permit exemption, paired output). Entry point:
`/recommendation-letter`, `.claude/skills/recommendation-letter/SKILL.md`.
```

- [ ] **Step 4: `Architecture.md`** — bump the skill inventory 10 -> 11 and add
the command + skill to the mermaid graph with a direct `command -> skill` edge
(no agent). Locate the anchor:

Run: `rtk grep -n "geolocalisation\|word2latex" Architecture.md`
Then add, near the other user-invoked skills:

```
    cRL["/recommendation-letter"] --> sRL["recommendation-letter skill"]
```

and note in the "Command -> agent -> skill matrix" prose that
`recommendation-letter` (like `geolocalisation`) is user-invoked with no agent
and is therefore omitted from that matrix.

- [ ] **Step 5: `install.ps1`** — add `recommendation-letter` to the Copilot
skills-pointer sentence (the `Helper skills (...)` text, per the memory
checklist ~line 236). Locate it:

Run: `rtk grep -n "Helper skills\|skills-pointer\|geolocalisation" install.ps1`
Then append `recommendation-letter` to that sentence's skill list.

- [ ] **Step 6: Regenerate the mirrors**

Run: `rtk pwsh -File install.ps1 -Profile engineering`
(or `powershell -File install.ps1 -Profile engineering` if `pwsh` is absent).
Expected: it reports writing `.github/`, `.opencode/`, `.continue/`,
`CONVENTIONS.md`, and emits `.github/prompts/recommendation-letter.prompt.md`.

- [ ] **Step 7: Verify wiring**

Run:
```bash
rtk grep -n "recommendation-letter" .claude/CLAUDE.md README.md Architecture.md \
  .claude/rules/workflows.md .github/copilot-instructions.md \
  .github/prompts/recommendation-letter.prompt.md .continue/rules/researchtools.md
```
Expected: a hit in each canonical file and in the regenerated Copilot prompt +
Continue rule. (OpenCode/Copilot-agent mirrors are per-agent; a skill has none,
so absence there is expected — discoverability is via the routing table + the
prompt.)

- [ ] **Step 8: Run the full offline test suite once more**

Run: `rtk python -m unittest discover -s ".claude/skills/recommendation-letter/scripts/Test" -v`
Expected: PASS (all classes, no regression).

- [ ] **Step 9: Commit canonical + mirrors together**

```bash
rtk git add .claude README.md Architecture.md install.ps1 .github .opencode .continue CONVENTIONS.md
rtk git commit -m "feat: register recommendation-letter skill + command, regenerate mirrors"
```

---

## Self-Review

**1. Spec coverage.** Every spec section maps to a task: purpose/scope -> Task 12/global; two-track -> Tasks 7-10; candidate_status -> Task 3; funding_provider -> Task 6; JSON schema -> Tasks 1-10 (fields consumed where used); style-hygiene linter -> Task 4; acceptance template -> Task 8; dispense + immigration + 120-day -> Task 9; paired output -> Task 10; compile + page count -> Task 11; tests -> Tasks 1-11; eval configs -> Task 11; SKILL.md + command -> Task 12; references -> Task 13; inventory + mirrors (README/Architecture/routing/workflows/install.ps1) -> Task 14; non-goals (no requirements.txt, no Obsidian, root CLAUDE.md untouched, no French command file) -> respected throughout.

**2. Placeholder scan.** No "TBD"/"handle edge cases"/"similar to Task N": every code step carries real code; every test step carries real assertions. The `[À COMPLÉTER]` string is intended output content, not a plan placeholder.

**3. Type consistency.** Function names are stable across tasks: `load_config`, `surname_slug`, `escape_latex`, `format_date`, `format_date_dispense`, `derive_candidate_reference`, `status_title_warnings`, `style_hygiene_violations`, `apply_gender`, `fill_scalars`, `build_funding_paragraph`, `count_words`, `assemble_authored`, `build_acceptance`, `stay_days`, `build_dispense`, `generate`, `collect_warnings`, `write_outputs`, `compile_latex`, `count_pdf_pages`. Templates live in `letter_templates.py` imported as `tpl`. `generate` returns a list of `{"letter_type","tex","warnings","words"}`; `write_outputs` consumes exactly that shape.

Known implementation watch-point for the executor: in Task 8 `build_acceptance`, the preamble-prepend + letterhead-swap lines are fiddly; verify the emitted `.tex` has exactly one `\begin{document}` and one `\end{document}` before moving on (a quick `rtk grep -c "begin{document}" out/letter_*_acceptance.tex` after the Task 11 smoke run). If the double-replace reads awkwardly, the equivalent clean form is: `text = PREAMBLE_FR + TEMPLATE_ACCEPTANCE_FR.replace("%%LETTERHEAD_FR%%", LETTERHEAD_FR_BODY)` where `LETTERHEAD_FR_BODY` is the letterhead without its own `\begin{document}`; keep whichever the executor verifies compiles.
