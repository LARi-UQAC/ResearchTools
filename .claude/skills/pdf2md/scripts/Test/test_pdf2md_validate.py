"""Offline tests for pdf2md_validate. No real PDF, network, or Ollama call
happens: extract_pdf_chapters takes an injected reader, and the CLI's model and
PDF-page effects are patched at module level (R20/R21). Fixtures below are pinned to real shapes
measured this session against the 162-page UQAC thesis: pymupdf4llm never
marks "CHAPITRE N" as a markdown heading (it is plain prose in its output),
the bibliography heading is "LISTE DES REFERENCES" (not bare "REFERENCES"),
and chapters 2-4 (embedded published articles) show mojibake on accented
characters that chapters 1/5 (native thesis prose) do not."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pdf2md_validate import (
    ChapterComparison,
    _main,
    build_report_table,
    compare_chapters,
    compute_metrics,
    count_citation_markers,
    count_figures,
    count_sections,
    count_subsections,
    count_tables,
    count_words,
    error_pct,
    extract_pdf_chapters,
    extract_pdf_single,
    find_chapter_page_range,
    load_output_single,
    flag_mismatched_chapters,
    load_config,
    load_output_chapters,
    render_report_md,
    split_pdf_text_into_chapters,
)

# The slice of the fidelity configuration the measures read, injected so the
# suite gives one verdict on any clone (R21).
FID = {
    "running_header_min_repeats": 3,
    "running_header_min_letters": 15,
    "pdf_noise_markers": ["<br>", "----- Start of picture text -----"],
    "caption_sentence_words": ["presents", "illustrates", "shows", "and", "contain", "is"],
    "citation_min_letters": 2,
}

# Pinned verbatim to the real pymupdf4llm extraction of the 162-page thesis,
# 2026-10-10: "CHAPITRE 3. ..." appears as PLAIN PROSE, never "#"-prefixed,
# which is why extract_pdf_chapters cannot reuse pdf2md_postprocess's own
# heading-based find_headings/split_frontmatter_and_chapters.
REAL_PDF_EXTRACT_SAMPLE = """\
47

des priorites sont caracterisees.

CHAPITRE 3. OPTIMISATION CONVEXE DISTRIBUEE MULTI-AGENTS AVEC 48 PRIORITES VARIABLES DANS LE TEMPS

## **3.1 Article soumis**

## **Abstract**

Real-world multi-agent systems often operate in dynamic environments.

## **3.1.1 Introduction**

The study of multi-agent systems (MAS) has received significant attention [6, 38].
"""

# Pinned verbatim (line numbers and heading text) to the real thesis's
# bibliography section, 2026-10-10: the heading is "LISTE DES REFERENCES",
# which starts with "LISTE", not "REFERENCES" or "BIBLIOGRAPHIE" -- the
# exact reason pdf2md_postprocess's own _BIBLIOGRAPHY_HEADING_RE (anchored
# on the bare word) would also miss it.
REAL_BIBLIOGRAPHY_BLEED_SAMPLE = """\
CHAPITRE 5

## **DISCUSSION GENERALE ET CONCLUSION**

## **5.1 Resume de la these**

Cette these a propose plusieurs contributions.

## **LISTE DES REFERENCES**

[1] Author. Title. Venue, 2020.

LISTE DES REFERENCES

[2] Second author. Second title. Venue, 2021.
"""


class TestCountWords(unittest.TestCase):
    def test_counts_whitespace_tokens(self):
        self.assertEqual(count_words("one two three", min_letters=2), 3)

    def test_survives_mojibake_replacement_characters(self):
        # Regression: this PDF's embedded font garbles accented French
        # characters identically under pymupdf4llm and raw PyMuPDF
        # page.get_text() (measured: "DISTRIBU?E" for "DISTRIBUEE"), but a
        # replaced glyph does not introduce a whitespace boundary where
        # none existed, so word COUNTS stay valid even when individual
        # characters are corrupted.
        self.assertEqual(count_words("DISTRIBU�E MULTI-AGENTS", min_letters=2), 2)

    def test_empty_text_is_zero(self):
        self.assertEqual(count_words("", min_letters=2), 0)

    def test_formulas_are_not_words(self):
        # Measured 2026-10-11: LaTeX source between dollar signs was counted
        # as words, making a math-heavy chapter thousands of words longer.
        text = r"the agents $\mathcal { G } = ( \mathcal { V } , \mathcal { E } )$ converge $$ x _ { i } ( k + 1 ) = \sum _ { j } w _ { ij } $$ quickly"
        self.assertEqual(count_words(text, min_letters=2), 4)  # the, agents, converge, quickly

    def test_the_pdf_readers_variable_fragments_are_not_words(self):
        # The PDF reader renders math as italic one-letter fragments, numbers and brackets.
        self.assertEqual(count_words("the agents _n_ _i_ _j_ 22 [11] = ( _V, E_ ) converge", min_letters=2), 3)

    def test_a_base64_image_is_not_words(self):
        self.assertEqual(count_words("before ![](data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAA) after", min_letters=2), 2)

    def test_the_same_prose_counts_the_same_with_or_without_formulas_around_it(self):
        prose = "consensus is reached when every agent holds the same value"
        with_math = "consensus is reached when $x_{ij} = 1$ every agent $$ y = z $$ holds the same value"
        self.assertEqual(count_words(prose, min_letters=2), count_words(with_math, min_letters=2))

    def test_min_letters_is_the_threshold(self):
        self.assertEqual(count_words("a is the", min_letters=1), 3)
        self.assertEqual(count_words("a is the", min_letters=3), 1)


class TestCountTables(unittest.TestCase):
    def test_a_table_is_counted_by_its_caption_label(self):
        text = "Table 3.1 The terminologies.\n\n| a | b |\n|---|---|\n\nTable 3.2 The fuzzy rules.\n\n<table><tr><td>1</td></tr></table>\n"
        self.assertEqual(count_tables(text, FID), 2)

    def test_html_tables_count_and_the_tables_mineru_adds_from_plots_do_not(self):
        # Measured 2026-10-11: 4 real tables per side, but the markdown
        # separators counted 4 against 10 (HTML tables missed, 8 chart tables added).
        text = "Table 3.2 Rules.\n\n<table></table>\n\n<details>\n<summary>line</summary>\n\n| t | x |\n|---|---|\n| 0 | ~2 |\n</details>\n"
        self.assertEqual(count_tables(text, FID), 1)

    def test_a_caption_seen_twice_counts_once_and_prose_counts_zero(self):
        self.assertEqual(count_tables("Table 3.3 Rules.\n\n||Table 3.3<br>Rules|\n", FID), 1)
        self.assertEqual(count_tables("just a sentence with | a pipe | in it", FID), 0)


class TestCountFigures(unittest.TestCase):
    def test_a_figure_is_counted_by_its_caption_label_once(self):
        text = "Figure 3.8 presents the positions.\n\nFigure 3.8 The desired and actual positions.\n\nFigure 3.9 The motion variables.\n"
        self.assertEqual(count_figures(text, FID), 2)

    def test_bold_wrapped_and_french_captions_count_and_cross_references_do_not(self):
        self.assertEqual(count_figures("**Figure 1.1** Legend here", FID), 1)
        self.assertEqual(count_figures("As shown in Figure 3.4, the result holds.", FID), 0)
        self.assertEqual(count_figures("Figure 3.9(b) shows the angle.", FID), 0)


class TestCountCitationMarkers(unittest.TestCase):
    def test_counts_individual_numbers_not_bracket_groups(self):
        # "[1, 2]" is TWO citation occurrences, not one bracket group.
        self.assertEqual(count_citation_markers("see the methods [1, 2] and [3]", FID), 3)

    def test_matrix_indices_and_footnote_calls_are_not_citations(self):
        # Verbatim shapes of the PDF reading: indices after a symbol, and a
        # footnote call attached to its word ("follows[3]").
        text = "_w[i] \u2208_ R _[1]_ [1] and = [( _w_ [2] but also as follows[3] :"
        self.assertEqual(count_citation_markers(text, FID), 0)

    def test_no_citations_is_zero(self):
        self.assertEqual(count_citation_markers("no citations here", FID), 0)


class TestHeadingNumberCounts(unittest.TestCase):
    def test_two_part_number_is_a_section(self):
        self.assertEqual(count_sections("## 2.1 Foo"), 1)
        self.assertEqual(count_subsections("## 2.1 Foo"), 0)

    def test_three_part_number_is_a_subsection(self):
        self.assertEqual(count_sections("### 2.1.2 Bar"), 0)
        self.assertEqual(count_subsections("### 2.1.2 Bar"), 1)

    def test_unnumbered_heading_counts_as_neither(self):
        # "Abstract"/"Avant-propos" are real thesis headings with no
        # number at all -- neither a section nor a subsection here.
        self.assertEqual(count_sections("## Abstract"), 0)
        self.assertEqual(count_subsections("## Abstract"), 0)

    def test_heading_depth_does_not_matter(self):
        # Regression: pymupdf4llm flattens "3.1" and "3.1.1" to the SAME
        # "##" depth in the real extraction, so depth cannot be used to
        # tell a section from a subsection -- only the number pattern can.
        self.assertEqual(count_sections("## 3.1 Article"), 1)
        self.assertEqual(count_subsections("## 3.1.1 Introduction"), 1)

    def test_number_not_in_a_heading_line_is_not_counted(self):
        self.assertEqual(count_sections("the result in 2.1 was confirmed"), 0)

    def test_bold_wrapped_number_still_counted(self):
        self.assertEqual(count_sections("## **3.1 Article soumis**"), 1)


class TestSplitPdfTextIntoChapters(unittest.TestCase):
    def test_finds_chapter_by_plain_prose_line_not_a_heading(self):
        # Regression: find_headings (pdf2md_postprocess's own splitter)
        # requires a "#"-prefixed line and finds ZERO chapters here,
        # because pymupdf4llm never marks "CHAPITRE N" as a heading in its
        # real output -- confirmed live, this is why a dedicated,
        # heading-syntax-agnostic splitter exists for the PDF side.
        chapters = split_pdf_text_into_chapters(REAL_PDF_EXTRACT_SAMPLE)
        self.assertIn(3, chapters)
        self.assertIn("multi-agent systems", chapters[3])

    def test_repeated_running_header_does_not_create_a_second_chapter(self):
        text = "CHAPITRE 2\nbody one\nCHAPITRE 2\nmore body\nCHAPITRE 3\nbody two"
        chapters = split_pdf_text_into_chapters(text)
        self.assertEqual(sorted(chapters), [2, 3])
        self.assertIn("more body", chapters[2])

    def test_bibliography_truncates_the_last_chapter(self):
        # Regression, measured live: without this, "LISTE DES REFERENCES"
        # (which pdf2md_postprocess's own heading regex, anchored on the
        # bare word, would ALSO miss) swallowed a 190-reference
        # bibliography whole into the last chapter's body, inflating its
        # word and citation counts far past pdf2md's own output.
        chapters = split_pdf_text_into_chapters(REAL_BIBLIOGRAPHY_BLEED_SAMPLE)
        self.assertIn(5, chapters)
        self.assertNotIn("Author. Title.", chapters[5])
        self.assertIn("Cette these a propose", chapters[5])

    def test_no_chapter_markers_yields_empty_dict(self):
        self.assertEqual(split_pdf_text_into_chapters("just prose, no chapters"), {})

    def test_last_chapter_with_no_bibliography_runs_to_end_of_document(self):
        text = "CHAPITRE 1\nbody one\nCHAPITRE 2\nbody two, no bibliography follows"
        chapters = split_pdf_text_into_chapters(text)
        self.assertIn("no bibliography follows", chapters[2])

    def test_a_bibliography_like_line_before_the_last_chapter_does_not_block_the_real_one(self):
        # Regression (/code-review finding): the original search found the
        # FIRST bibliography-heading-shaped line in the WHOLE document via
        # a single next(...) call. A table-of-contents entry or an early
        # running header matching the pattern EXACTLY (the bibliography
        # heading alone on its own line, the same shape pymupdf4llm's real
        # running-header repeats take), appearing BEFORE the last chapter
        # even starts, locked onto that early match and the function
        # never looked any further -- so the REAL bibliography, later in
        # the document, was never found and the last chapter ran to end
        # of document, swallowing it whole. The search is now scoped to
        # lines after the last chapter's own start only. (A true
        # table-of-contents line carrying a page number, e.g. "Liste des
        # references ... 150", does NOT match _BIBLIOGRAPHY_LINE_RE at
        # all -- that regex requires nothing after the heading word -- so
        # this fixture uses the shape that DOES match early: a bare
        # repeated heading line, as a front-matter list-of-contents
        # heading legitimately could be.)
        text = (
            "LISTE DES REFERENCES\n\n"
            "CHAPITRE 1\nintro body\n\n"
            "CHAPITRE 2\nreal chapter body\n\n"
            "LISTE DES REFERENCES\n\n[1] Author. Title.\n"
        )
        chapters = split_pdf_text_into_chapters(text)
        self.assertIn(2, chapters)
        self.assertNotIn("Author. Title.", chapters[2])
        self.assertIn("real chapter body", chapters[2])


class TestExtractPdfChapters(unittest.TestCase):
    def test_uses_the_injected_reader_not_a_real_pdf(self):
        calls = []

        def fake_reader(path):
            calls.append(path)
            return ("CHAPITRE 1\nbody", [])

        chapters = extract_pdf_chapters("fake.pdf", reader=fake_reader)
        self.assertEqual(calls, ["fake.pdf"])
        self.assertIn(1, chapters)
        self.assertEqual(chapters[1][1], "CHAPITRE 1\nbody")


class TestLoadOutputChapters(unittest.TestCase):
    def test_recovers_chapter_number_from_the_files_own_heading(self):
        # Regression: Introduction.md/Conclusion.md filenames do not embed
        # the chapter number -- it must come from the file's OWN first
        # "CHAPITRE N" line, matching the real output's shape exactly
        # ("## CHAPITRE 1" as the first line of Introduction.md).
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            content_dir = Path(tmp) / "content"
            content_dir.mkdir()
            (content_dir / "Introduction.md").write_text("## CHAPITRE 1\n\nintro body", encoding="utf-8")
            (content_dir / "chapitre2.md").write_text("## CHAPITRE 2\n\nchapter two body", encoding="utf-8")
            (content_dir / "Conclusion.md").write_text("## CHAPITRE 5\n\nconclusion body", encoding="utf-8")
            (content_dir / "frontmatter.md").write_text("front matter, never a chapter", encoding="utf-8")

            chapters = load_output_chapters(Path(tmp))
        self.assertEqual(sorted(chapters), [1, 2, 5])
        self.assertIn("intro body", chapters[1][1])
        self.assertIn("chapter two body", chapters[2][1])
        self.assertIn("conclusion body", chapters[5][1])

    def test_missing_content_dir_returns_empty_dict(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_output_chapters(Path(tmp)), {})

    def test_falls_back_to_filename_number_when_no_heading_found(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            content_dir = Path(tmp) / "content"
            content_dir.mkdir()
            (content_dir / "chapitre3.md").write_text("no recognizable heading at all", encoding="utf-8")
            chapters = load_output_chapters(Path(tmp))
        self.assertIn(3, chapters)


class TestCompareChapters(unittest.TestCase):
    def test_chapter_in_both_sides_reports_both_metrics(self):
        pdf_chapters = {1: ("", "one two three")}
        out_chapters = {1: ("ch1", "one two")}
        rows = compare_chapters(pdf_chapters, out_chapters, word_min_letters=2, fidelity_config=FID)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].in_pdf)
        self.assertTrue(rows[0].in_output)
        self.assertEqual(rows[0].pdf_metrics["words"], 3)
        self.assertEqual(rows[0].output_metrics["words"], 2)

    def test_chapter_missing_from_pdf_side_is_flagged_not_dropped(self):
        pdf_chapters = {}
        out_chapters = {1: ("ch1", "some words")}
        rows = compare_chapters(pdf_chapters, out_chapters, word_min_letters=2, fidelity_config=FID)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0].in_pdf)
        self.assertTrue(rows[0].in_output)
        self.assertEqual(rows[0].pdf_metrics["words"], 0)

    def test_chapter_missing_from_output_side_is_flagged_not_dropped(self):
        pdf_chapters = {1: ("", "some words")}
        out_chapters = {}
        rows = compare_chapters(pdf_chapters, out_chapters, word_min_letters=2, fidelity_config=FID)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].in_pdf)
        self.assertFalse(rows[0].in_output)


class TestFlagMismatchedChapters(unittest.TestCase):
    def _row(self, number, in_pdf, in_output, pdf_words, out_words):
        zero = {m: 0 for m in ("words", "sections", "subsections", "tables", "figures", "citation_markers", "equations_rough")}
        pdf_metrics = dict(zero, words=pdf_words)
        out_metrics = dict(zero, words=out_words)
        return ChapterComparison(chapter=number, in_pdf=in_pdf, in_output=in_output, pdf_metrics=pdf_metrics, output_metrics=out_metrics)

    def test_missing_from_either_side_is_always_flagged(self):
        rows = [self._row(1, False, True, 0, 100)]
        self.assertEqual(flag_mismatched_chapters(rows, word_tolerance_pct=50), [1])

    def test_small_word_count_difference_is_not_flagged(self):
        rows = [self._row(1, True, True, 1000, 1050)]
        self.assertEqual(flag_mismatched_chapters(rows, word_tolerance_pct=15), [])

    def test_large_word_count_difference_is_flagged(self):
        rows = [self._row(1, True, True, 1000, 200)]
        self.assertEqual(flag_mismatched_chapters(rows, word_tolerance_pct=15), [1])

    def test_zero_pdf_words_does_not_divide_by_zero(self):
        rows = [self._row(1, True, True, 0, 500)]
        self.assertEqual(flag_mismatched_chapters(rows, word_tolerance_pct=15), [])


class TestErrorPct(unittest.TestCase):
    def test_relative_to_the_pdf_reading_in_either_direction(self):
        self.assertEqual(error_pct(200, 250), 25.0)
        self.assertEqual(error_pct(200, 150), 25.0)

    def test_equal_counts_are_zero(self):
        self.assertEqual(error_pct(7, 7), 0.0)

    def test_nothing_in_the_pdf_is_zero_when_the_output_has_nothing_and_a_full_miss_otherwise(self):
        self.assertEqual(error_pct(0, 0), 0.0)
        self.assertEqual(error_pct(0, 3), 100.0)


class TestReportTable(unittest.TestCase):
    NAMES = {1: "chapitre1.md", 2: "chapitre2.md"}

    def rows(self, pdf1, out1, pdf2, out2):
        return compare_chapters({1: ("", pdf1), 2: ("", pdf2)}, {1: ("chapitre1", out1), 2: ("chapitre2", out2)}, word_min_letters=2, fidelity_config=FID)

    def test_rows_are_the_measures_and_columns_are_the_files_with_the_two_error_edges(self):
        rows = self.rows("one two three four", "one two three four", "one two", "one two three four")
        lines = render_report_md(rows, self.NAMES).splitlines()
        self.assertEqual(lines[0], "| Measure | chapitre1.md | chapitre2.md | Global error (%) |")
        self.assertEqual(lines[1], "|---|---|---|---|")
        self.assertTrue(lines[2].startswith("| words | 4 / 4 | 2 / 4 |"))
        measure_rows = [line for line in lines[2:] if line.startswith("| ") and not line.startswith("| Error")]
        self.assertEqual(len(measure_rows), 7)
        self.assertTrue(lines[9].startswith("| Error (%) |"))

    def test_the_global_error_of_a_measure_is_the_sum_of_gaps_over_the_sum_of_pdf_counts(self):
        # words: file 1 PDF 4 output 4, file 2 PDF 2 output 4 -> gap 2 over PDF total 6.
        table = build_report_table(self.rows("one two three four", "one two three four", "one two", "one two three four"), self.NAMES)
        self.assertAlmostEqual(table["measures"]["words"]["global_error_pct"], 2 / 6 * 100)
        self.assertEqual(table["measures"]["words"]["cells"]["chapitre2.md"], {"pdf": 2, "output": 4, "error_pct": 100.0})

    def test_an_excess_in_one_file_does_not_cancel_a_deficit_in_another(self):
        # file 1 has 2 words too many, file 2 has 2 too few: a net-zero total, but a real 50% error.
        table = build_report_table(self.rows("one two", "one two three four", "one two three four", "one two"), self.NAMES)
        self.assertAlmostEqual(table["measures"]["words"]["global_error_pct"], 4 / 6 * 100)

    def test_the_error_of_a_file_is_the_mean_of_its_cell_errors_over_all_measures(self):
        table = build_report_table(self.rows("one two three four", "one two three four", "one two", "one two three four"), self.NAMES)
        # file 2: words 100%, every other measure 0% (nothing in either) -> mean 100 / 7.
        self.assertAlmostEqual(table["file_error_pct"]["chapitre2.md"], 100 / 7)
        self.assertEqual(table["file_error_pct"]["chapitre1.md"], 0.0)

    def test_the_corner_is_the_mean_of_the_global_errors(self):
        table = build_report_table(self.rows("one two three four", "one two three four", "one two", "one two three four"), self.NAMES)
        expected = sum(table["measures"][metric]["global_error_pct"] for metric in table["measures"]) / 7
        self.assertAlmostEqual(table["overall_error_pct"], expected)

    def test_a_perfect_conversion_is_zero_everywhere(self):
        table = build_report_table(self.rows("one two", "one two", "three four", "three four"), self.NAMES)
        self.assertEqual((table["overall_error_pct"], set(table["file_error_pct"].values())), (0.0, {0.0}))

    def test_a_chapter_without_a_file_name_is_headed_by_its_number(self):
        rows = compare_chapters({1: ("", "one two")}, {}, word_min_letters=2, fidelity_config=FID)
        self.assertEqual(build_report_table(rows, {})["files"], ["chapter 1"])

    def test_the_percentages_are_defined_under_the_table(self):
        report = render_report_md(self.rows("one two", "one two", "three four", "three four"), self.NAMES)
        self.assertIn("|output - PDF| / PDF x 100", report)
        self.assertIn("Last row", report)
        self.assertIn("Last column", report)

    def test_the_table_is_part_of_the_json_result(self):
        import io
        import json
        from contextlib import redirect_stdout
        from unittest.mock import patch

        import pdf2md_validate

        pdf = {1: ("", "one two three")}
        out = {1: ("chapitre1", "one two three")}
        stdout = io.StringIO()
        with patch.object(pdf2md_validate, "extract_pdf_chapters", lambda *a, **k: pdf), patch.object(pdf2md_validate, "load_output_chapters", lambda *a, **k: out), redirect_stdout(stdout):
            pdf2md_validate._main(["x.pdf", "-o", "out", "--json"])
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["table"]["files"], ["chapitre1.md"])
        self.assertIn("| Measure | chapitre1.md | Global error (%) |", result["report_md"])


class TestRenderReportMd(unittest.TestCase):
    def test_renders_one_row_per_measure_with_pdf_and_output_in_the_cell(self):
        rows = compare_chapters({1: ("", "one two")}, {1: ("ch1", "one two three")}, word_min_letters=2, fidelity_config=FID)
        report = render_report_md(rows, {1: "ch1.md"})
        self.assertIn("| words | 2 / 3 | 50.0 |", report)

    def test_missing_chapter_gets_a_note(self):
        rows = compare_chapters({}, {1: ("ch1", "words")}, word_min_letters=2, fidelity_config=FID)
        report = render_report_md(rows)
        self.assertIn("not found on the PDF side", report)

    def test_the_equation_row_states_that_its_reference_is_the_numbering_not_the_pdf(self):
        # R8 -- the PDF reader cannot read equation numbers, and the report
        # must not present the numbering as a PDF reading.
        rows = compare_chapters({1: ("", "x")}, {1: ("ch1", "x")}, word_min_letters=2, fidelity_config=FID)
        report = render_report_md(rows)
        self.assertIn("numbered equations (expected from numbering)", report)


class TestNumberedEquationsMeasure(unittest.TestCase):
    EQ = "$$\nx = y, \\tag {3.%d}\n$$\n\n"

    def row(self, numbers):
        out = "".join(self.EQ % n for n in numbers)
        (row,) = compare_chapters({3: ("", "prose only")}, {3: ("chapitre3", out)}, word_min_letters=2, fidelity_config=FID)
        return row

    def test_a_complete_numbering_reads_expected_equal_found(self):
        row = self.row([1, 2, 3])
        self.assertEqual((row.pdf_metrics["numbered_equations"], row.output_metrics["numbered_equations"]), (3, 3))

    def test_a_missing_equation_reads_as_a_deficit_not_as_a_pdf_reading(self):
        row = self.row([1, 2, 4])
        self.assertEqual((row.pdf_metrics["numbered_equations"], row.output_metrics["numbered_equations"]), (4, 3))

    def test_a_chapter_with_no_numbered_equation_reads_zero_on_both_sides(self):
        row = self.row([])
        self.assertEqual((row.pdf_metrics["numbered_equations"], row.output_metrics["numbered_equations"]), (0, 0))


class TestPdfSideIsCleanedBeforeCounting(unittest.TestCase):
    def test_running_headers_and_figure_text_do_not_inflate_the_pdf_side(self):
        # Measured 2026-10-11: about 900 words of repeated chapter titles and
        # 25 labels read out of a figure made one chapter look much longer
        # on the PDF side than in the markdown.
        header = "CHAPITRE 4. CONSENSUS DANS LES SYSTEMES MULTI-AGENTS AVEC {} DELAIS DE COMMUNICATION"
        body = "The agents exchange values over the network and converge to a common value."
        pdf = "\n\n".join([header.format(80), body, header.format(82), body, header.format(84), "rithms [116, 152]<br>Communication<br>delay [31]<br>"])
        out = "\n\n".join([body, body])
        (row,) = compare_chapters({4: ("", pdf)}, {4: ("chapitre4", out)}, word_min_letters=2, fidelity_config=FID)
        self.assertEqual(row.pdf_metrics["words"], row.output_metrics["words"])
        self.assertEqual(row.pdf_metrics["citation_markers"], 0)


class TestLoadConfig(unittest.TestCase):
    def test_shipped_config_loads_all_keys(self):
        config = load_config()
        self.assertIn("word_count_mismatch_threshold_pct", config)
        self.assertIn("math_symbol_chars", config)

    def test_missing_file_is_refused_not_defaulted(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                load_config(Path(tmp) / "does-not-exist.json")

    def test_missing_key_is_named_not_silently_defaulted(self):
        import json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            incomplete = Path(tmp) / "incomplete.json"
            incomplete.write_text(json.dumps({"word_count_mismatch_threshold_pct": {"value": 10}}), encoding="utf-8")
            with self.assertRaises(KeyError) as ctx:
                load_config(incomplete)
            self.assertIn("math_symbol_chars", str(ctx.exception))


class TestChapterPageRange(unittest.TestCase):
    """find_chapter_page_range on injected page texts (no real PDF)."""

    def test_find_chapter_page_range_from_injected_page_texts(self):
        page_texts = ["CHAPITRE 2 ...", "more of chapter 2", "CHAPITRE 3 ..."]
        self.assertEqual(find_chapter_page_range("fake.pdf", 2, page_texts=page_texts), (0, 1))

    def test_find_chapter_page_range_last_chapter_runs_to_end(self):
        page_texts = ["CHAPITRE 2 ...", "CHAPITRE 3 ...", "more of chapter 3"]
        self.assertEqual(find_chapter_page_range("fake.pdf", 3, page_texts=page_texts), (1, 2))

    def test_find_chapter_page_range_not_found_is_none(self):
        self.assertIsNone(find_chapter_page_range("fake.pdf", 99, page_texts=["CHAPITRE 1"]))

    def test_cross_reference_sentence_is_not_mistaken_for_a_chapter_start(self):
        # Regression (/code-review finding, confirmed live): the original
        # implementation used _CHAPTER_NUMBER_RE (case-insensitive,
        # matches anywhere in the line), so a page's own body sentence
        # "Chapitre 2 a montre que..." (title case, mid-paragraph) was
        # read as chapter 2's start -- cutting chapter 1's real page range
        # short. The fix requires _CHAPTER_START_RE's literal uppercase
        # match, checked per LINE.
        page_texts = [
            "CHAPITRE 1\nsome intro text",
            "Chapitre 2 a montre que la methode fonctionne.\nmore chapter 1 body",
            "CHAPITRE 2\nreal chapter 2 start",
        ]
        self.assertEqual(find_chapter_page_range("fake.pdf", 1, page_texts=page_texts), (0, 1))

    def test_table_of_contents_entry_in_title_case_does_not_start_a_chapter_early(self):
        # The same uppercase-only fix also closes the table-of-contents
        # false-positive the review named separately: this real thesis's
        # own front-matter symbol-list table refers to chapters in title
        # case ("... Chapitre 2 ..."), never full caps, so it is correctly
        # never read as a chapter start.
        page_texts = ["Table des symboles: voir Chapitre 2 pour le detail.", "CHAPITRE 2\nreal start"]
        self.assertEqual(find_chapter_page_range("fake.pdf", 2, page_texts=page_texts), (1, 1))

    def test_bibliography_page_truncates_the_last_chapters_range(self):
        # Regression (/code-review finding): without this, a flagged last
        # chapter with no "CHAPITRE N+1" to stop it rendered the
        # bibliography and appendix pages too -- measured live, chapter 3
        # of the real thesis rendered 32 pages into one request (pages
        # 69-100) and timed out.
        page_texts = ["CHAPITRE 3\nbody page 1", "more body page 2", "LISTE DES REFERENCES\n[1] Author."]
        self.assertEqual(find_chapter_page_range("fake.pdf", 3, page_texts=page_texts), (0, 1))

    def test_max_pages_caps_the_range_from_its_start(self):
        # Regression: the first live run had no cap at all. max_pages
        # bounds the range to a request size the local model can answer
        # within the configured timeout.
        page_texts = ["CHAPITRE 5\nbody"] + [f"page {i}" for i in range(20)]
        self.assertEqual(find_chapter_page_range("fake.pdf", 5, page_texts=page_texts, max_pages=3), (0, 2))

    def test_max_pages_does_not_extend_a_range_that_is_already_shorter(self):
        page_texts = ["CHAPITRE 1\nbody", "more body", "CHAPITRE 2\nnext"]
        self.assertEqual(find_chapter_page_range("fake.pdf", 1, page_texts=page_texts, max_pages=50), (0, 1))

    def test_an_earlier_bare_bibliography_heading_does_not_block_finding_the_real_one(self):
        # Regression (second /code-review round): the first fix applied
        # the after-start scoping to split_pdf_text_into_chapters but left
        # the ORIGINAL whole-document-first-match bug here, in the
        # page-level function --vlm-check actually calls. A bare
        # bibliography-heading-shaped line on an EARLIER page (page 0, a
        # front-matter heading in the general case) must not lock onto
        # that match and silently disable the cutoff for the real
        # bibliography inside this chapter's own range.
        page_texts = [
            "LISTE DES REFERENCES",
            "CHAPITRE 3\nbody page 1",
            "more body page 2",
            "LISTE DES REFERENCES\n[1] Author.",
        ]
        self.assertEqual(find_chapter_page_range("fake.pdf", 3, page_texts=page_texts), (1, 2))

    def test_max_pages_below_one_is_refused(self):
        # Regression: a 0 or negative cap silently produced an empty
        # page range (end < start) rather than a clear refusal.
        page_texts = ["CHAPITRE 1\nbody"]
        with self.assertRaises(ValueError):
            find_chapter_page_range("fake.pdf", 1, page_texts=page_texts, max_pages=0)


class TestMainChecks(unittest.TestCase):
    """The CLI wiring of --fidelity and --vlm-check. Every real effect (PDF
    read, page text, model call) is patched at module level, since _main has
    no injection seam of its own for them."""

    PROSE = "The orchard keepers measured rainfall across every terrace during the long dry season and recorded each reading in a shared notebook."

    def run_main(self, argv, vlm_report=None):
        import io
        from contextlib import redirect_stderr, redirect_stdout
        from unittest.mock import patch

        import pdf2md_validate

        calls = {}

        def fake_vlm(*args, **kwargs):
            calls.update(kwargs)
            return vlm_report

        pdf = {1: ("", "## **1.1 Intro**\n\n" + self.PROSE)}
        out = {1: ("chapitre1", self.PROSE)}  # the heading is lost: one fidelity error
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(pdf2md_validate, "extract_pdf_chapters", lambda *a, **k: pdf), \
                patch.object(pdf2md_validate, "load_output_chapters", lambda *a, **k: out), \
                patch.object(pdf2md_validate, "_read_page_texts", lambda *a, **k: ["CHAPITRE 1", "body"]), \
                patch.object(pdf2md_validate.pdf2md_vlmcheck, "run_vlm_fidelity", fake_vlm), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            code = pdf2md_validate._main(argv)
        return code, stdout.getvalue(), stderr.getvalue(), calls

    def test_without_flags_no_check_runs_and_the_report_is_unchanged(self):
        import json

        code, out, _err, _calls = self.run_main(["x.pdf", "-o", "out", "--json"])
        result = json.loads(out)
        self.assertEqual((code, result["fidelity"], result["vlm_check"]), (0, None, None))

    def test_fidelity_reports_the_lost_heading_and_strict_turns_it_into_exit_1(self):
        import json

        code, out, _err, _calls = self.run_main(["x.pdf", "-o", "out", "--fidelity", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["fidelity"]["totals"], {"missing_heading": 1})
        strict_code, _out, _err, _calls = self.run_main(["x.pdf", "-o", "out", "--fidelity", "--strict", "--json"])
        self.assertEqual(strict_code, 1)

    def test_vlm_check_without_a_model_tag_is_refused_with_exit_2(self):
        code, _out, err, calls = self.run_main(["x.pdf", "-o", "out", "--vlm-check"])
        self.assertEqual(code, 2)
        self.assertIn("--vlm-check-model", err)
        self.assertEqual(calls, {})

    def test_vlm_check_passes_the_operators_tag_and_returns_its_report(self):
        import json

        report = {"chapters": {}, "issue_count": 0, "error_count": 0, "unchecked_chapters": {}}
        code, out, _err, calls = self.run_main(["x.pdf", "-o", "out", "--vlm-check", "--vlm-check-model", "operator-tag", "--json"], vlm_report=report)
        self.assertEqual(code, 0)
        self.assertEqual(calls["model_tag"], "operator-tag")
        self.assertEqual(json.loads(out)["vlm_check"], report)

    def test_strict_fails_on_a_formula_issue_and_on_a_page_that_could_not_be_checked(self):
        for report in (
            {"chapters": {}, "issue_count": 1, "error_count": 0, "unchecked_chapters": {}},
            {"chapters": {}, "issue_count": 0, "error_count": 1, "unchecked_chapters": {}},
        ):
            code, _out, _err, _calls = self.run_main(["x.pdf", "-o", "out", "--vlm-check", "--vlm-check-model", "t", "--strict", "--json"], vlm_report=report)
            self.assertEqual(code, 1)


class TestSingleLayout(unittest.TestCase):
    """The single-document layout (an article or a talk source): the whole
    document is compared as ONE unit, numbered 1, bibliography cut off on both
    sides. Measured on no real article yet: these are structural tests."""

    PDF_TEXT = (
        "Fast Planning\n\n1 Introduction\n\nPlanning is hard and we study it here.\n\n"
        "2 Method\n\nWe learn a heuristic.\n\nReferences\n\n[1] A. Author. Title. 2019.\n[2] B. Author. Title. 2020.\n"
    )

    def _out_dir(self, text, layout="single"):
        import json
        import tempfile
        from pathlib import Path

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out_dir = Path(tmp.name)
        (out_dir / "main.md").write_text(text, encoding="utf-8")
        (out_dir / "pdf2md-layout.json").write_text(json.dumps({"layout": layout}), encoding="utf-8")
        return out_dir

    def test_the_pdf_side_is_one_document_cut_at_the_last_bibliography_heading(self):
        chapters = extract_pdf_single("x.pdf", reader=lambda _p: (self.PDF_TEXT, []))
        self.assertEqual(list(chapters), [1])
        body = chapters[1][1]
        self.assertIn("We learn a heuristic", body)
        self.assertNotIn("A. Author", body)

    def test_a_references_word_early_in_the_pdf_does_not_cut_the_document(self):
        text = "References\n\nTable of contents line\n\n" + self.PDF_TEXT
        body = extract_pdf_single("x.pdf", reader=lambda _p: (text, []))[1][1]
        self.assertIn("We learn a heuristic", body)

    def test_the_output_side_reads_main_md_without_its_bibliography(self):
        out_dir = self._out_dir("# Fast Planning\n\n## 1 Introduction\n\nbody text here\n\n## References\n\n[1] A. Author. Title. 2019.\n")
        chapters = load_output_single(out_dir)
        self.assertEqual(list(chapters), [1])
        self.assertIn("body text here", chapters[1][1])
        self.assertNotIn("A. Author", chapters[1][1])

    def test_a_single_output_with_no_main_md_is_an_explicit_error(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                load_output_single(Path(tmp))

    def test_layout_dispatch_uses_the_single_loader_only_for_a_single_directory(self):
        thesis_dir = self._out_dir("whatever", layout="thesis")
        self.assertEqual(load_output_chapters(thesis_dir), {})  # no content/: the thesis loader finds nothing

    def test_vlm_check_is_refused_for_a_single_layout_before_any_pdf_is_read(self):
        out_dir = self._out_dir("# T\n\nbody\n")
        code = _main(["does-not-exist.pdf", "-o", str(out_dir), "--vlm-check", "--vlm-check-model", "tag"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
