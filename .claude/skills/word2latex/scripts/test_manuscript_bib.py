#!/usr/bin/env python3
"""
test_manuscript_bib.py — Deterministic tests for the word2latex manuscript
bibliography module. No .docx, no network, no model load — a synthetic
markdown fixture only. See .claude/rules/testing.md.

Run either way:
    python -m pytest .claude/skills/word2latex/scripts/test_manuscript_bib.py -v
    python .claude/skills/word2latex/scripts/test_manuscript_bib.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import manuscript_bib as mb  # noqa: E402

# Synthetic fixture: two same-lastname/same-year authors force a key collision,
# a third with no DOI forces @misc, and four citation forms appear in the body.
FIXTURE = """\
Intro paragraph with a pandoc superscript claim.\\textsuperscript{1}
A unicode-superscript range claim.¹⁻³
An IEEE inline claim [2,3] and an out-of-range bracket [99].
A code-like token array[1] must stay, and \\item[1] must stay.
An unresolved superscript.\\textsuperscript{5}

# Bibliography
1. Smith J. A great paper. Journal of Things. 2020. doi: 10.1000/aaa
2. Smith K. Another paper. Journal of Things. 2020. doi: 10.1000/bbb
3. Doe J. Third paper without doi. Some Venue. 2019.
"""

LINES = FIXTURE.splitlines()
ENTRIES = mb.parse_bib_entries(LINES)
NUM_TO_KEY = {e["num"]: e["key"] for e in ENTRIES}
CITED, BRACKETS = mb.convert_citations(FIXTURE, NUM_TO_KEY, brackets=True)
BIB = mb.render_bibtex(ENTRIES)


def test_entry_count() -> None:
    assert len(ENTRIES) == 3


def test_keys_and_collision() -> None:
    # First occurrence stays bare; the colliding second gets suffix 'a'
    # (faithful to docx2latex.py collision logic).
    assert NUM_TO_KEY == {1: "smith2020", 2: "smith2020a", 3: "doe2019"}


def test_doi_and_year_extracted() -> None:
    assert ENTRIES[0]["doi"] == "10.1000/aaa"
    assert ENTRIES[0]["year"] == "2020"
    assert ENTRIES[2]["doi"] == ""


def test_texsuperscript_to_cite() -> None:
    assert r"\cite{smith2020}" in CITED


def test_unicode_superscript_range_to_cite() -> None:
    assert r"\cite{smith2020,smith2020a,doe2019}" in CITED


def test_bracket_to_cite_when_resolvable() -> None:
    assert r"\cite{smith2020a,doe2019}" in CITED
    assert BRACKETS == 1  # only [2,3] converts; [99] does not


def test_bracket_left_alone_when_unresolved_or_guarded() -> None:
    assert "[99]" in CITED           # out of range -> untouched
    assert "array[1]" in CITED       # word-char lookbehind -> untouched
    assert r"\item[1]" in CITED      # backslash/word lookbehind -> untouched


def test_unresolved_superscript_becomes_refN() -> None:
    assert r"\cite{ref5}" in CITED


def test_bibtex_entry_types_and_url() -> None:
    assert "@article{smith2020," in BIB
    assert "@misc{doe2019," in BIB
    assert "https://doi.org/10.1000/aaa" in BIB


def _run() -> int:
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    print(f"\n{'ALL PASSED' if not failures else f'{failures} FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_run())
