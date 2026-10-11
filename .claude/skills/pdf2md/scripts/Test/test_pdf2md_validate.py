"""Offline tests for pdf2md_validate. No real PDF, network, or Ollama call
happens: extract_pdf_chapters/ask_local_vlm_for_counts/render_pdf_pages_to_images
all take injected seams (R20/R21). Fixtures below are pinned to real shapes
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
    ask_local_vlm_for_counts,
    build_vlm_check_prompt,
    compare_chapters,
    compute_metrics,
    count_citation_markers,
    count_equations_rough,
    count_figures,
    count_sections,
    count_subsections,
    count_tables,
    count_words,
    extract_pdf_chapters,
    find_chapter_page_range,
    flag_mismatched_chapters,
    load_config,
    load_output_chapters,
    render_pdf_pages_to_images,
    render_report_md,
    split_pdf_text_into_chapters,
)

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
        self.assertEqual(count_words("one two three"), 3)

    def test_survives_mojibake_replacement_characters(self):
        # Regression: this PDF's embedded font garbles accented French
        # characters identically under pymupdf4llm and raw PyMuPDF
        # page.get_text() (measured: "DISTRIBU?E" for "DISTRIBUEE"), but a
        # replaced glyph does not introduce a whitespace boundary where
        # none existed, so word COUNTS stay valid even when individual
        # characters are corrupted.
        self.assertEqual(count_words("DISTRIBU�E MULTI-AGENTS"), 2)

    def test_empty_text_is_zero(self):
        self.assertEqual(count_words(""), 0)


class TestCountTables(unittest.TestCase):
    def test_counts_one_table_by_its_separator_row(self):
        self.assertEqual(count_tables("| a | b |\n|---|---|\n| 1 | 2 |"), 1)

    def test_two_tables_count_two(self):
        text = "| a |\n|---|\n| 1 |\n\nprose\n\n| c |\n|---|\n| 2 |"
        self.assertEqual(count_tables(text), 2)

    def test_prose_with_no_table_counts_zero(self):
        self.assertEqual(count_tables("just a sentence with | a pipe | in it"), 0)


class TestCountFigures(unittest.TestCase):
    def test_counts_figure_and_fig_captions(self):
        self.assertEqual(count_figures("Figure 3: a plot\nFig. 4 another\nsome prose"), 2)

    def test_case_insensitive_and_bold_wrapped(self):
        self.assertEqual(count_figures("**FIGURE 1** Legend here"), 1)

    def test_figure_mentioned_mid_sentence_not_counted(self):
        # Only a caption LINE (figure number at the start) counts, not a
        # cross-reference like "see Figure 3 for details" buried in prose.
        self.assertEqual(count_figures("As shown in Figure 3, the result holds."), 0)


class TestCountCitationMarkers(unittest.TestCase):
    def test_counts_individual_numbers_not_bracket_groups(self):
        # "[1, 2]" is TWO citation occurrences, not one bracket group --
        # distinct from pdf2md_refs.py's unique reference_count.
        self.assertEqual(count_citation_markers("see [1, 2] and [3]"), 3)

    def test_no_citations_is_zero(self):
        self.assertEqual(count_citation_markers("no citations here"), 0)


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


class TestCountEquationsRough(unittest.TestCase):
    SYMBOLS = "=+-*/^_<>"

    def test_delimited_block_counts_one(self):
        self.assertEqual(count_equations_rough("$$x = 1$$", min_symbols_per_line=99, math_symbol_chars=self.SYMBOLS), 1)

    def test_inline_delimited_span_counts_one(self):
        self.assertEqual(count_equations_rough("the value $x=1$ here", min_symbols_per_line=99, math_symbol_chars=self.SYMBOLS), 1)

    def test_dense_symbol_line_without_delimiters_counts_one(self):
        self.assertEqual(count_equations_rough("a = b + c - d", min_symbols_per_line=3, math_symbol_chars=self.SYMBOLS), 1)

    def test_prose_line_below_threshold_counts_zero(self):
        self.assertEqual(count_equations_rough("this is ordinary prose, a=1 only", min_symbols_per_line=5, math_symbol_chars=self.SYMBOLS), 0)

    def test_delimited_line_not_double_counted_by_symbol_density(self):
        # A line already counted via $$ delimiters must not ALSO be
        # counted again by the symbol-density scan.
        count = count_equations_rough("$$a = b + c - d$$", min_symbols_per_line=1, math_symbol_chars=self.SYMBOLS)
        self.assertEqual(count, 1)


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
        rows = compare_chapters(pdf_chapters, out_chapters, math_min_symbols=99, math_symbol_chars="=")
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].in_pdf)
        self.assertTrue(rows[0].in_output)
        self.assertEqual(rows[0].pdf_metrics["words"], 3)
        self.assertEqual(rows[0].output_metrics["words"], 2)

    def test_chapter_missing_from_pdf_side_is_flagged_not_dropped(self):
        pdf_chapters = {}
        out_chapters = {1: ("ch1", "some words")}
        rows = compare_chapters(pdf_chapters, out_chapters, math_min_symbols=99, math_symbol_chars="=")
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0].in_pdf)
        self.assertTrue(rows[0].in_output)
        self.assertEqual(rows[0].pdf_metrics["words"], 0)

    def test_chapter_missing_from_output_side_is_flagged_not_dropped(self):
        pdf_chapters = {1: ("", "some words")}
        out_chapters = {}
        rows = compare_chapters(pdf_chapters, out_chapters, math_min_symbols=99, math_symbol_chars="=")
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


class TestRenderReportMd(unittest.TestCase):
    def test_renders_one_row_per_metric(self):
        rows = compare_chapters({1: ("", "one two")}, {1: ("ch1", "one two three")}, math_min_symbols=99, math_symbol_chars="=")
        report = render_report_md(rows)
        self.assertIn("| 1 | words | 2 | 3 | +1 |", report)

    def test_missing_chapter_gets_a_note(self):
        rows = compare_chapters({}, {1: ("ch1", "words")}, math_min_symbols=99, math_symbol_chars="=")
        report = render_report_md(rows)
        self.assertIn("not found on the PDF side", report)

    def test_equations_label_states_it_is_a_rough_estimate(self):
        # R8 -- the report must never present the heuristic as an exact count.
        rows = compare_chapters({1: ("", "x")}, {1: ("ch1", "x")}, math_min_symbols=99, math_symbol_chars="=")
        report = render_report_md(rows)
        self.assertIn("equations (rough estimate)", report)


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


class TestVlmCheckSeams(unittest.TestCase):
    """UNVERIFIED LIVE (module docstring): every effect here is injected,
    proving the plumbing is correct, never that a real model call succeeds
    or that its counts are accurate."""

    def test_build_vlm_check_prompt_asks_for_json_only(self):
        prompt = build_vlm_check_prompt()
        self.assertIn("JSON", prompt)
        self.assertIn("equations", prompt)

    def test_find_chapter_page_range_from_injected_page_texts(self):
        page_texts = ["CHAPITRE 2 ...", "more of chapter 2", "CHAPITRE 3 ..."]
        self.assertEqual(find_chapter_page_range("fake.pdf", 2, page_texts=page_texts), (0, 1))

    def test_find_chapter_page_range_last_chapter_runs_to_end(self):
        page_texts = ["CHAPITRE 2 ...", "CHAPITRE 3 ...", "more of chapter 3"]
        self.assertEqual(find_chapter_page_range("fake.pdf", 3, page_texts=page_texts), (1, 2))

    def test_find_chapter_page_range_not_found_is_none(self):
        self.assertIsNone(find_chapter_page_range("fake.pdf", 99, page_texts=["CHAPITRE 1"]))

    def test_render_pdf_pages_to_images_uses_the_injected_renderer(self):
        import tempfile
        from pathlib import Path

        calls = []

        def fake_renderer(pdf_path, page_index, dpi, out_dir):
            calls.append((pdf_path, page_index, dpi))
            path = out_dir / f"page_{page_index}.png"
            path.write_bytes(b"fake-png")
            return path

        with tempfile.TemporaryDirectory() as tmp:
            paths = render_pdf_pages_to_images("fake.pdf", (0, 1), Path(tmp), dpi=150, renderer=fake_renderer)
        self.assertEqual(len(paths), 2)
        self.assertEqual(calls, [("fake.pdf", 0, 150), ("fake.pdf", 1, 150)])

    def test_ask_local_vlm_for_counts_parses_the_injected_response(self):
        import json
        import tempfile
        from pathlib import Path

        captured = {}

        def fake_caller(url, data, timeout):
            captured["url"] = url
            captured["body"] = json.loads(data)
            return json.dumps({"response": json.dumps({"equations": 3, "tables": 1, "figures": 0, "sections": 2, "subsections": 1})}).encode()

        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "page_1.png"
            image_path.write_bytes(b"fake-png")
            result = ask_local_vlm_for_counts(
                [image_path], model_tag="operator-named-tag", base_url="http://localhost:11434", timeout_s=30, caller=fake_caller
            )
        self.assertEqual(result["equations"], 3)
        self.assertEqual(captured["url"], "http://localhost:11434/api/generate")
        self.assertEqual(captured["body"]["model"], "operator-named-tag")
        self.assertNotIn("Qwen", json.dumps(captured["body"]))  # R2: never a hardcoded tag

    def test_ask_local_vlm_for_counts_raises_on_unparsable_response(self):
        import tempfile
        from pathlib import Path

        def fake_caller(url, data, timeout):
            return b"not json at all"

        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "page_1.png"
            image_path.write_bytes(b"fake-png")
            with self.assertRaises(ValueError):
                ask_local_vlm_for_counts([image_path], model_tag="tag", base_url="http://localhost:11434", timeout_s=30, caller=fake_caller)


if __name__ == "__main__":
    unittest.main()
