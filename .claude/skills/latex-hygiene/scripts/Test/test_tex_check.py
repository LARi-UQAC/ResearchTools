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
import tex_check  # noqa: E402
import tex_report  # noqa: E402
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


# Two headings at the same level, one deeper heading nested inside the first,
# a float, a changes macro, and an accented French sentence: one fixture that
# every --section case below can interrogate from a different angle.
_SECTIONED = (
    "\\documentclass[11pt]{article}\n"
    "\\begin{document}\n"
    "\\subsection*{2.1~Sommaire du projet~:}\\label{sommaire}\n"
    "La detection automatique des batiments eleves ici.\n"
    "\\subsubsection*{Un titre plus profond}\n"
    "Ce texte appartient encore au sommaire.\n"
    "\\subsection*{2.2~Contexte du projet~:}\n"
    "Ce texte appartient au contexte et jamais au sommaire.\n"
    "\\end{document}\n"
)


class TestSectionWordCount(unittest.TestCase):
    """wc --section: per-section caps, the shape a grant form actually asks for."""

    def _fixture(self, tmp, src=_SECTIONED, name="sectioned.tex"):
        return _write(Path(tmp), name, src)

    def test_section_stops_at_next_same_level_heading(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._fixture(tmp)
            result = tex_wc.scan_wc_section([path], "2.1 Sommaire")
        self.assertFalse(result["refused"])
        # 7 words of the first sentence, the 4 of the nested heading title
        # (which is content of 2.1, and a grant form counts it), and the 6
        # of its body: 17, with not one word of 2.2.
        self.assertEqual(result["words"], 17)

    def test_deeper_heading_does_not_close_the_section(self):
        # The nested \subsubsection* body is inside 2.1, so the section span
        # must still contain it; without this case the previous one would
        # also pass on an implementation that stopped at ANY heading.
        with tempfile.TemporaryDirectory() as tmp:
            path = self._fixture(tmp)
            text = tex_common.strip_comments(tex_common.read_text(path))
            sections = tex_wc.list_sections(text)
        self.assertEqual(sections[1]["title"], "un titre plus profond")
        body = text[sections[0]["body_start"]:sections[0]["body_end"]]
        self.assertIn("Un titre plus profond", body)
        self.assertNotIn("jamais au sommaire", body)

    def test_accented_french_words_are_counted(self):
        # Regression for the 2026-09-12 tex_common.WORD fix: under the
        # ASCII-only class these four tokens counted 1 in total, two of them
        # counting zero.
        self.assertEqual(
            tex_common.count_words("\u00e9t\u00e9 o\u00f9 d\u00e9j\u00e0 d\u00e9tection"), 4)
        self.assertEqual(tex_common.count_words("the quick brown fox"), 4)

    def test_single_letter_words_stay_excluded_in_both_languages(self):
        # The two-character minimum is unchanged, so the accent fix moves no
        # English count for a reason other than an accent.
        self.assertEqual(tex_common.count_words("a"), 0)
        self.assertEqual(tex_common.count_words("\u00e0"), 0)

    def test_accepted_resolves_changes_inside_the_section(self):
        src = (
            "\\subsection*{Resume}\n"
            "\\replaced[id=MO]{deux mots}{quatre mots totalement inutiles}\n"
            "\\deleted[id=MO]{ces mots disparaissent}\n"
            "\\subsection*{Suite}\nautre chose\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = self._fixture(tmp, src, "changes.tex")
            raw = tex_wc.scan_wc_section([path], "Resume")
            acc = tex_wc.scan_wc_section([path], "Resume", accepted=True)
        self.assertEqual(acc["words"], 2)
        self.assertLess(acc["words"], raw["words"])

    def test_floats_are_excluded_from_the_section_count(self):
        src = (
            "\\subsection*{Avec flottant}\n"
            "\\begin{table}\nmots de tableau jamais comptes ici\n\\end{table}\n"
            "trois mots seulement\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = self._fixture(tmp, src, "float.tex")
            result = tex_wc.scan_wc_section([path], "Avec flottant")
        self.assertEqual(result["words"], 3)

    def test_absent_section_is_refused_and_names_the_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._fixture(tmp)
            result = tex_wc.scan_wc_section([path], "2.99 Inexistante")
        self.assertTrue(result["refused"])
        self.assertIn("not found", result["reason"])
        self.assertTrue(any("Sommaire" in c for c in result["candidates"]))
        self.assertEqual(result["words"], 0)

    def test_ambiguous_section_is_refused_as_ambiguous_not_as_absent(self):
        # "du projet" matches both headings. Reporting that as "not found"
        # sends the reader looking in the wrong file instead of naming the
        # section more fully, so the two refusals stay distinguishable.
        with tempfile.TemporaryDirectory() as tmp:
            path = self._fixture(tmp)
            result = tex_wc.scan_wc_section([path], "du projet")
        self.assertTrue(result["refused"])
        self.assertIn("ambiguous", result["reason"])
        self.assertNotIn("not found", result["reason"])

    def test_limit_exceeded_is_reported_with_its_overflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._fixture(tmp)
            result = tex_wc.scan_wc_section([path], "2.1 Sommaire", limit=10)
        self.assertTrue(result["over_limit"])
        self.assertEqual(result["overflow"], result["words"] - 10)
        self.assertTrue(tex_report.has_defect("wc", result))

    def test_limit_respected_is_not_a_defect(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._fixture(tmp)
            result = tex_wc.scan_wc_section([path], "2.1 Sommaire", limit=1000)
        self.assertFalse(result["over_limit"])
        self.assertFalse(tex_report.has_defect("wc", result))

    def test_plain_wc_is_still_never_a_defect(self):
        # Negative control for the widened has_defect predicate: the three
        # pre-existing wc shapes carry no over_limit key and must stay
        # informational under --strict.
        with tempfile.TemporaryDirectory() as tmp:
            path = self._fixture(tmp)
            plain = tex_wc.scan_wc([path])
            acc = tex_wc.scan_wc_accepted([path])
        self.assertFalse(tex_report.has_defect("wc", plain))
        self.assertFalse(tex_report.has_defect("wc", acc))

    def test_cli_exits_two_on_a_refusal_and_one_on_an_exceeded_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._fixture(tmp)
            self.assertEqual(
                tex_check.main(["wc", path, "--section", "2.99 Inexistante", "--json"]), 2)
            self.assertEqual(
                tex_check.main(["wc", path, "--section", "2.1 Sommaire",
                                "--limit", "1", "--strict", "--json"]), 1)
            self.assertEqual(
                tex_check.main(["wc", path, "--section", "2.1 Sommaire",
                                "--limit", "1000", "--strict", "--json"]), 0)

    def test_a_bold_pseudo_heading_opens_no_section(self):
        # Documented limit, asserted so it cannot drift into a silent wrong
        # answer: Mitacs section 2.4 is a \textbf line, not a \subsection.
        src = (
            "\\subsection*{Vraie section}\nun deux trois\n"
            "\\textbf{2.4~Fausse section~:}\nquatre cinq six\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = self._fixture(tmp, src, "bold.tex")
            sections = tex_wc.list_sections(tex_common.read_text(path))
            result = tex_wc.scan_wc_section([path], "Vraie section")
        self.assertEqual(len(sections), 1)
        self.assertEqual(result["words"], 8)


class TestFormHelpExcluded(unittest.TestCase):
    """Les consignes imprimees d'un formulaire ne sont pas les mots du demandeur.

    Mesure du 2026-09-12 sur la demande MITACS : le gabarit imprime « Veuillez
    fournir : a) un apercu du probleme de recherche... (Maximum de 300 mots) ».
    Ce texte est protege dans Word, donc il est sur la page sans appartenir au
    demandeur, et un plafond de 300 mots ne le compte pas.
    """

    def test_formhelp_content_is_out_of_a_section_count(self):
        src = (
            "\\subsection*{2.1 Sommaire}\n"
            "\\begin{formhelp}\n"
            "Veuillez fournir un apercu du probleme de recherche pose ici.\n"
            "\\end{formhelp}\n"
            "un deux trois\n"
            "\\subsection*{2.2 Suite}\nautre chose\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), "form.tex", src)
            result = tex_wc.scan_wc_section([path], "2.1 Sommaire")
        self.assertEqual(result["words"], 3)

    def test_formhelp_content_is_out_of_a_whole_file_count(self):
        # Le compteur de section et le compteur de fichier doivent partager la
        # meme definition de la prose, sinon ils divergent en silence.
        src = ("\\begin{formhelp}\ndix mots de consigne qui ne comptent jamais du tout ici\n"
               "\\end{formhelp}\nquatre mots du demandeur\n")
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), "form2.tex", src)
            result = tex_wc.scan_wc([path])
        self.assertEqual(result["total_prose_words"], 4)

    def test_text_outside_formhelp_is_still_counted(self):
        # Controle negatif : sans cette assertion, un strip trop large passerait.
        src = "avant la consigne\n\\begin{formhelp}\nconsigne\n\\end{formhelp}\napres la consigne\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), "form3.tex", src)
            result = tex_wc.scan_wc([path])
        self.assertEqual(result["total_prose_words"], 6)

    def test_a_formhelp_holding_a_list_is_removed_whole(self):
        src = ("\\subsection*{S}\n\\begin{formhelp}\n"
               "\\begin{enumerate}\n\\item premier point\n\\item second point\n"
               "\\end{enumerate}\n\\end{formhelp}\ndeux mots\n")
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), "form4.tex", src)
            result = tex_wc.scan_wc_section([path], "S")
        self.assertEqual(result["words"], 2)


if __name__ == "__main__":
    unittest.main()
