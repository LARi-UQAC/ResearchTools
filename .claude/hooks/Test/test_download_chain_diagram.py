"""
test_download_chain_diagram.py - the download logigram of the manual is the code's chain.

Documentation test (R15, 2026-11-06): chapter 06 of the manual draws the download process
of download_pdf.py as a logigram, and docs/manual/diagrams/download-chain.mmd is its
source. download_one is nine hand-written blocks in a row, each "call the download, record
its outcome, return on success". This test proves the figure has the same shape: the
inline block equals the source file, every download is in the order and under the name the
code uses, every precondition the code skips on is drawn, a failure always goes to the next
block, a success always stops, a preview is rejected exactly where the code rejects it, and
the last failure reaches the manual list. It proves the figure is consistent with the code,
never that the code behaves as drawn: that is test_download_pdf.py.

Run:
    python .claude/hooks/Test/test_download_chain_diagram.py
"""

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
MANUAL = REPO / "docs" / "manual" / "06-skills.md"
DIAGRAM = REPO / "docs" / "manual" / "diagrams" / "download-chain.mmd"
CODE = REPO / ".claude" / "skills" / "scopus" / "scripts" / "download_pdf.py"
HEADING = "#### How a paper is downloaded"

# Display word of each rung's code name that its box must carry.
LABEL_WORD = {
    "elsevier": "elsevier", "semantic_scholar": "semantic scholar", "publisher": "publisher",
    "unpaywall": "unpaywall", "arxiv": "arxiv", "pmc": "pubmed central",
    "landing": "landing", "browser": "chrome",
}

# Where each rung's precondition is drawn, and the word its decision carries. The same word
# must appear in the text the code records when it skips that rung (CODE_SKIP).
PRECONDITION = {1: "SCOPUS_API_KEY", 2: "Semantic Scholar", 4: "UNPAYWALL_EMAIL",
                5: "arXiv id", 6: "PMCID", 7: "HTML", 8: "playwright"}
CODE_SKIP = {1: "no SCOPUS_API_KEY set", 2: "semantic_scholar_api module",
             4: "no UNPAYWALL_EMAIL set", 5: "no arXiv id", 6: "no PMCID",
             7: "HTML tiers disabled", 8: "playwright package not installed"}

# The first node of each rung as the diagram draws it (a decision when the rung has a
# precondition, else the download box), and the node after the last rung.
ENTRY = {1: "P1", 2: "P2", 3: "D3", 4: "P4", 5: "L", 6: "P6", 7: "P7", 8: "P8", 9: "M1"}


def mermaid_after(text: str, heading: str) -> str:
    """The body of the first fenced mermaid block that follows a heading."""
    start = text.find(heading)
    if start < 0:
        return ""
    found = re.search(r"```mermaid\n(.*?)\n```", text[start:], re.S)
    return found.group(1) if found else ""


def edges(source: str) -> set:
    """(from, label, to) for every arrow; node texts are removed first."""
    plain = re.sub(r'\["[^"]*"\]|\{"[^"]*"\}', "", source)
    return {(a, label, b) for a, label, b in
            re.findall(r"(\w+)\s*(?:--\s*(\w+)\s*)?-->\s*(\w+)", plain)}


def labels(source: str) -> dict:
    """Node id -> its text."""
    return dict(re.findall(r'(\w+)(?:\[|\{)"([^"]*)"(?:\]|\})', source))


def code_names(code: str) -> dict:
    """Rung number -> name, read from the calls that record each rung's outcome."""
    names = {int(n): name for n, name in
             re.findall(r'(?:pdf_rung|format_rung)\((\d), "(\w+)"', code)}
    names.update({int(n): name for n, name in
                  re.findall(r'_note_attempt\(attempts, (\d), "(\w+)"', code)})
    return names


def code_kinds(code: str) -> tuple:
    """(pdf rungs, rungs whose PDF is checked for a preview), read from the pdf_rung calls."""
    pdf, gated = set(), set()
    for match in re.finditer(r"pdf_rung\((\d),", code):
        n = int(match.group(1))
        pdf.add(n)
        if "check_preview=False" not in code[match.start(): match.start() + 220]:
            gated.add(n)
    return pdf, gated


def shape_problems(source: str, gated: set) -> list:
    """What differs between the drawn chain and the one the code has."""
    arrows, problems = edges(source), []

    def need(a, label, b):
        if (a, label, b) not in arrows:
            problems.append("missing arrow %s -- %s --> %s" % (a, label, b))

    for n in range(1, 9):
        nxt = ENTRY[n + 1]
        if n in PRECONDITION:
            need("P%d" % n, "no", nxt)
            need("P%d" % n, "yes", "D%d" % n)
        if n == 8:
            need("D8", "", "R8")
            need("R8", "yes", nxt)
            need("R8", "no", "Q8")
        else:
            need("D%d" % n, "", "Q%d" % n)
        need("Q%d" % n, "no", nxt)
        if n in gated:
            need("Q%d" % n, "yes", "V%d" % n)
            need("V%d" % n, "yes", "X%d" % n)
            need("X%d" % n, "", nxt)
            need("V%d" % n, "no", "OK")
        else:
            need("Q%d" % n, "yes", "OK")
    for edge in (("M1", "yes", "M2"), ("M1", "no", "M3"), ("M3", "yes", "M4"),
                 ("M3", "no", "M5"), ("M2", "", "END"), ("M4", "", "END"), ("M5", "", "END")):
        need(*edge)
    if [e for e in arrows if e[0] in ("OK", "END", "SK", "Z0")]:
        problems.append("a stop node must not have an outgoing arrow")
    return problems


def name_problems(source: str, names: dict, code: str) -> list:
    """Download boxes carry the code's names, and every precondition matches the code's skip text."""
    problems, boxes = [], labels(source)
    for n in range(1, 9):
        word = LABEL_WORD.get(names.get(n, ""))
        text = boxes.get("D%d" % n, "").lower()
        if word is None:
            problems.append("the code has no known rung %d (%r)" % (n, names.get(n)))
        elif ("download %d" % n) not in text or word not in text:
            problems.append("D%d should say 'Download %d' and %r, says %r" % (n, n, word, text))
    for n, word in PRECONDITION.items():
        if word.lower() not in boxes.get("P%d" % n, "").lower():
            problems.append("P%d should name %r" % (n, word))
        if CODE_SKIP[n] not in code:
            problems.append("the code no longer says %r" % CODE_SKIP[n])
    return problems


class TestDownloadLogigram(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.manual = MANUAL.read_text(encoding="utf-8")
        cls.source = DIAGRAM.read_text(encoding="utf-8").rstrip("\n")
        cls.code = CODE.read_text(encoding="utf-8")
        cls.names = code_names(cls.code)
        cls.pdf, cls.gated = code_kinds(cls.code)

    def test_the_inline_block_equals_the_source_file(self):
        self.assertEqual(mermaid_after(self.manual, HEADING), self.source)
        self.assertTrue(self.source.startswith("flowchart TD"))

    def test_the_code_has_the_rungs_the_figure_assumes(self):
        self.assertEqual(sorted(self.names), list(range(1, 10)))
        self.assertEqual(self.names[9], "manual")
        self.assertEqual(self.pdf, {1, 2, 3, 8})
        self.assertEqual(self.gated, {1, 3, 8}, "the preview check moved: redraw the figure")

    def test_the_chain_has_the_shape_of_the_code(self):
        self.assertEqual(shape_problems(self.source, self.gated), [])

    def test_the_downloads_and_their_preconditions_match_the_code(self):
        self.assertEqual(name_problems(self.source, self.names, self.code), [])

    def test_the_table_lists_the_same_eight_downloads(self):
        rows = re.findall(r"^\| ([1-9]) \|", self.manual, re.M)
        self.assertEqual(rows, [str(n) for n in range(1, 9)])


class TestNegativeControls(unittest.TestCase):
    """A check that cannot fail is not a check (R20)."""

    def setUp(self):
        self.source = DIAGRAM.read_text(encoding="utf-8").rstrip("\n")
        self.code = CODE.read_text(encoding="utf-8")
        self.names = code_names(self.code)
        self.gated = code_kinds(self.code)[1]

    def _broken(self, old, new):
        broken = self.source.replace(old, new)
        self.assertNotEqual(broken, self.source, "the mutation did not apply")
        return broken

    def test_a_failure_that_skips_a_download_is_found(self):
        self.assertTrue(shape_problems(self._broken("Q3 -- no --> P4", "Q3 -- no --> L"),
                                       self.gated))

    def test_a_missing_stop_is_found(self):
        self.assertTrue(shape_problems(self._broken("    Q5 -- yes --> OK\n", ""), self.gated))

    def test_a_missing_precondition_branch_is_found(self):
        self.assertTrue(shape_problems(self._broken("P4 -- no --> L\n", ""), self.gated))

    def test_a_preview_check_drawn_where_the_code_has_none_is_found(self):
        # Download 2 has no preview check in the code; drawing one must fail.
        self.assertTrue(shape_problems(self.source, self.gated | {2}))

    def test_the_last_failure_not_reaching_the_manual_list_is_found(self):
        self.assertTrue(shape_problems(self._broken("Q8 -- no --> M1", "Q8 -- no --> D1"),
                                       self.gated))

    def test_an_arrow_out_of_a_stop_is_found(self):
        self.assertTrue(shape_problems(self.source + "\n    OK --> D1", self.gated))

    def test_a_swapped_download_name_is_found(self):
        broken = self._broken("Download 4: Unpaywall", "Download 4: arXiv")
        self.assertTrue(name_problems(broken, self.names, self.code))

    def test_a_rung_the_code_renamed_is_found(self):
        renamed = dict(self.names)
        renamed[3] = "mirror"
        self.assertTrue(name_problems(self.source, renamed, self.code))

    def test_a_skip_text_the_code_dropped_is_found(self):
        self.assertTrue(name_problems(self.source, self.names,
                                      self.code.replace("no UNPAYWALL_EMAIL set", "x")))

    def test_the_block_finder_returns_nothing_without_the_heading(self):
        self.assertEqual(mermaid_after("```mermaid\nflowchart TD\n```", HEADING), "")


if __name__ == "__main__":
    unittest.main()
