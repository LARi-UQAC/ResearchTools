"""
test_tex_check.py - offline unit tests for the latex-hygiene skill's
tex_check.py CLI and its sibling modules (tex_common, tex_chars, tex_aiscan,
tex_aiscan_text, tex_wc, tex_abstract, tex_braces, tex_par, tex_citecov).

No real .tex file, no network, no API key, no model load: every case builds
its LaTeX source as a synthetic Python string and writes it to a tmp
directory created for the test. Modeled on
.claude/skills/extract-statistic/scripts/Test/test_section_scan.py.

Run:
    cd .claude/skills/latex-hygiene/scripts
    python Test/test_tex_check.py -v
"""

import sys
import tempfile
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent
sys.path.insert(0, str(_SCRIPTS))

import tex_aiscan  # noqa: E402
import tex_aiscan_text  # noqa: E402
import tex_braces  # noqa: E402
import tex_chars  # noqa: E402
import tex_citecov  # noqa: E402
import tex_common  # noqa: E402
import tex_par  # noqa: E402
import tex_abstract  # noqa: E402
import tex_refcov  # noqa: E402
import tex_wc  # noqa: E402


def _write(tmp_dir: Path, name: str, content: str) -> str:
    path = tmp_dir / name
    path.write_text(content, encoding="utf-8")
    return str(path)


class TestAcceptedResolve(unittest.TestCase):
    """Case 1 and 2: the changes-package resolver (tex_common.resolve_accepted)."""

    def test_replaced_nested_inside_added_yields_new_only(self):
        # A \replaced nested inside an \added must resolve to just the
        # replacement text, never the concatenation of both branches.
        src = r"\added{\replaced{a}{b}}"
        self.assertEqual(tex_common.resolve_accepted(src), "a")

    def test_deleted_disappears_from_accepted_count(self):
        src = "Keep this. \\deleted{Drop this entirely.} Keep this too."
        resolved = tex_common.resolve_accepted(src)
        self.assertNotIn("Drop this entirely", resolved)
        self.assertIn("Keep this too", resolved)


class TestCommentStripping(unittest.TestCase):
    """Case 3: an escaped \\% is not a comment start."""

    def test_escaped_percent_not_treated_as_comment(self):
        src = r"Discount is 50\% off this week. % but this is a real comment"
        stripped = tex_common.strip_comments(src)
        self.assertIn("50\\% off this week", stripped)
        self.assertNotIn("real comment", stripped)


class TestDoubleDash(unittest.TestCase):
    """Case 4: '--' counted, '---' not counted, as an aiscan em_dash hit."""

    def test_double_dash_counted_triple_dash_not(self):
        src = (
            "\\section{Intro}\n"
            "A short phrase -- like this one -- appears here for once.\n"
            "A page range 10---20 must never be flagged as a hit at all.\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), "double_dash.tex", src)
            result = tex_aiscan.scan_aiscan([path])
        em_dash_hits = result["signals"]["em_dash"]["hits"]
        self.assertEqual(len(em_dash_hits), 2)


class TestBraceDepth(unittest.TestCase):
    """Case 5: negative brace depth reported at the offending line, not EOF."""

    def test_negative_depth_reported_at_correct_line(self):
        src = "\\section{A}\nfine line one\nfine line two\nan extra close } here\nmore text after\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), "brace.tex", src)
            result = tex_braces.scan_braces([path])
        info = result["files"][path]
        self.assertEqual(info["first_negative_line"], 4)
        self.assertFalse(result["balanced"])


class TestParInsideMacro(unittest.TestCase):
    """Case 6: \\par detected in the SECOND argument of \\replaced."""

    def test_par_in_second_replaced_argument_detected(self):
        src = (
            "\\replaced{first arg is fine}{second arg has\n\na blank line inside it}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), "par.tex", src)
            result = tex_par.scan_par([path])
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["files"][path][0]["macro"], "replaced")

    def test_first_argument_alone_is_not_enough(self):
        # A blank line only inside the FIRST argument of \replaced must still
        # be caught (the whole macro span is scanned, not just arg 2), but a
        # macro with no blank line anywhere must report clean.
        src = "\\added{no blank line in here at all}\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), "par_clean.tex", src)
            result = tex_par.scan_par([path])
        self.assertEqual(result["total"], 0)


class TestCiteCoverage(unittest.TestCase):
    """Case 7: \\cite{a,b} feeds two keys; a missing key is dangling."""

    def test_cite_list_splits_and_flags_dangling(self):
        tex_src = "Some text \\cite{keyA,keyB} more text.\n"
        bib_src = "@article{keyA,\n  title={Present},\n}\n"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tex_path = _write(tmp_path, "paper.tex", tex_src)
            bib_path = _write(tmp_path, "refs.bib", bib_src)
            result = tex_citecov.scan_citecov([tex_path], bib_path)
        self.assertEqual(result["cited_count"], 2)
        self.assertEqual(result["dangling"], ["keyB"])


class TestAbstract(unittest.TestCase):
    """Case 8: abstract words counted outside macros, keywords on the comma."""

    def test_abstract_words_and_keywords(self):
        src = (
            "\\begin{abstract}\n"
            "This is a short abstract with exactly nine words.\n"
            "\\end{abstract}\n"
            "\\begin{IEEEkeywords}\n"
            "robotics, control, diagnosis\n"
            "\\end{IEEEkeywords}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), "abstract.tex", src)
            result = tex_abstract.scan_abstract(path)
        self.assertEqual(result["abstract_words"], 9)
        self.assertEqual(result["keyword_count"], 3)


class TestSectionAttribution(unittest.TestCase):
    """Case 9: a hit in subsection B is reported against B, not section A."""

    def test_hit_in_subsection_attributed_to_subsection(self):
        src = (
            "\\section{A}\n"
            "Text in section A only, nothing unusual to report here.\n"
            "\\subsection{B}\n"
            "Furthermore, this sentence sits inside subsection B alone.\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), "sections.tex", src)
            result = tex_aiscan.scan_aiscan([path])
        phrase_hits = result["signals"]["ai_transition_phrase"]["hits"]
        self.assertEqual(len(phrase_hits), 1)
        self.assertEqual(phrase_hits[0]["section"], "B")


class TestPronounScan(unittest.TestCase):
    """Case 10: \\item and \\mine do not match; a real 'we' does."""

    def test_item_and_mine_macro_do_not_match(self):
        # The negative lookbehind on the backslash is what keeps \item and
        # \mine{...} from matching; a real mid-sentence lowercase "we" still
        # does.
        src = "\\item some content\n\\mine{something}\nThis method, we believe, generalizes well.\n"
        hits = tex_aiscan_text.scan_pronouns(src, section_map=None, path="p.tex")
        tokens = [h["token"] for h in hits]
        self.assertNotIn("I", tokens)
        self.assertEqual(tokens, ["we"])

    def test_sentence_initial_capitalized_we_matches(self):
        # Most first-person prose in a paper starts the sentence ("We
        # propose", "Our contribution"), so the Title-case spelling must
        # match too, not just the mid-sentence lowercase one.
        src = "We propose a new controller. Our contribution is threefold.\n"
        hits = tex_aiscan_text.scan_pronouns(src, section_map=None, path="p.tex")
        tokens = [h["token"] for h in hits]
        self.assertIn("We", tokens)
        self.assertIn("Our", tokens)

    def test_all_caps_us_does_not_match(self):
        # "US" (United States) and other all-caps acronyms must not be
        # mistaken for the pronoun "us"; only "us" and "Us" are recognized.
        src = "Manufacturing plants in the US rely on this method.\n"
        hits = tex_aiscan_text.scan_pronouns(src, section_map=None, path="p.tex")
        tokens = [h["token"] for h in hits]
        self.assertNotIn("US", tokens)
        self.assertEqual(tokens, [])


class TestListDetection(unittest.TestCase):
    """Case 11: list detection finds \\begin{itemize}."""

    def test_itemize_environment_detected(self):
        src = "\\begin{itemize}\n\\item one\n\\item two\n\\end{itemize}\n"
        lists = tex_aiscan_text.scan_lists(src, section_map=None)
        self.assertEqual(len(lists), 1)
        self.assertEqual(lists[0]["env"], "itemize")


class TestForbiddenChars(unittest.TestCase):
    """Case 12: chars flags MULT SIGN, DEGREE, MINUS SIGN."""

    def test_chars_flags_mult_degree_minus(self):
        src = "The angle is 45\u00b0 and 3\u00d74 uses a true minus \u2212 sign.\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), "chars.tex", src)
            result = tex_chars.scan_chars([path])
        names = {hit["name"] for hit in result["files"][path]}
        self.assertIn("DEGREE", names)
        self.assertIn("MULT SIGN", names)
        self.assertIn("MINUS SIGN", names)


class TestWordCountAndPageEstimate(unittest.TestCase):
    """wc subcommand: floats excluded, page estimate from documentclass options."""

    def test_floats_excluded_from_prose_count(self):
        # Body-only fragment, the shape wc actually runs on (sections/*.tex),
        # so the float block is the only thing that could pollute the count.
        src = (
            "\\begin{table}\nignored table words that must not be counted here\n\\end{table}\n"
            "Five simple prose words counted here today.\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), "wc.tex", src)
            result = tex_wc.scan_wc([path])
        self.assertEqual(result["files"][path]["prose_words"], 7)
        self.assertEqual(result["files"][path]["floats"], 1)
        self.assertEqual(result["total_floats"], 1)

    def test_two_column_ten_pt_page_estimate(self):
        src = "\\documentclass[10pt,twocolumn]{IEEEtran}\n\\begin{document}\n\\end{document}\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), "main.tex", src)
            layout = tex_wc.detect_layout([path])
        self.assertTrue(layout["two_column"])
        self.assertEqual(layout["font_size"], 10)
        rate, exact = tex_wc.words_per_page(layout["two_column"], layout["font_size"])
        self.assertEqual(rate, 750)
        self.assertTrue(exact)


class TestRefCoverage(unittest.TestCase):
    """refcov: uncited labels, dangling references, duplicate labels."""

    def test_uncited_dangling_and_duplicate_labels(self):
        src = (
            "\\section{Intro}\n"
            "See Figure~\\ref{fig:one} and Table~\\ref{tab:missing}.\n"
            "\\label{fig:one}\n"
            "\\label{fig:one}\n"
            "\\label{fig:unused}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), "refs.tex", src)
            result = tex_refcov.scan_refcov([path])
        self.assertEqual(result["uncited_labels"], ["fig:unused"])
        self.assertEqual(result["dangling_references"], ["tab:missing"])
        self.assertEqual(len(result["duplicate_labels"]), 1)
        dup = result["duplicate_labels"][0]
        self.assertEqual(dup["key"], "fig:one")
        self.assertEqual([entry["line"] for entry in dup["lines"]], [3, 4])

    def test_eqref_cref_autoref_all_count_as_references(self):
        src = (
            "\\label{eq:one}\n\\label{fig:two}\n\\label{tab:three}\n"
            "\\eqref{eq:one} \\cref{fig:two} \\autoref{tab:three}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), "refs2.tex", src)
            result = tex_refcov.scan_refcov([path])
        self.assertEqual(result["uncited_labels"], [])
        self.assertEqual(result["dangling_references"], [])


class TestEnvironmentBalance(unittest.TestCase):
    """braces: \\begin{env}/\\end{env} stack, distinct from curly-brace depth."""

    def test_mismatched_environment_reported_with_both_lines(self):
        src = "\\begin{itemize}\n\\item a\n\\end{enumerate}\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), "env.tex", src)
            result = tex_braces.scan_braces([path])
        self.assertFalse(result["env_balanced"])
        self.assertTrue(result["balanced"])  # curly braces alone are fine
        mismatch = result["files"][path]["environments"]["first_mismatch"]
        self.assertEqual(mismatch["type"], "mismatched_end")
        self.assertEqual(mismatch["expected_env"], "itemize")
        self.assertEqual(mismatch["expected_line"], 1)
        self.assertEqual(mismatch["found_env"], "enumerate")
        self.assertEqual(mismatch["line"], 3)

    def test_unclosed_environment_at_eof(self):
        src = "\\begin{table}\nsome content\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), "unclosed.tex", src)
            result = tex_braces.scan_braces([path])
        self.assertFalse(result["env_balanced"])
        unclosed = result["files"][path]["environments"]["unclosed_at_eof"]
        self.assertEqual(unclosed, [{"env": "table", "line": 1}])

    def test_balanced_environments_pass(self):
        src = "\\begin{table}\n\\begin{itemize}\n\\item a\n\\end{itemize}\n\\end{table}\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), "balanced.tex", src)
            result = tex_braces.scan_braces([path])
        self.assertTrue(result["env_balanced"])


if __name__ == "__main__":
    unittest.main()
