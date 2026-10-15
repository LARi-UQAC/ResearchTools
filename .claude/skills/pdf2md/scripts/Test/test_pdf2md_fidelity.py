"""Offline tests for pdf2md_fidelity. No PDF, network or model is touched:
every case works on short synthetic chapter text (fictitious prose, R34)
shaped like what the two readers really produce, measured 2026-10-11 on a
162-page thesis: the PDF reader splits a paragraph at each page break and
puts a running header and a page number in between, renders accented
letters as placeholders, and renders formulas as italic fragments, while
pdf2md output keeps formulas inside $...$ and marks headings with '#'.

Each defect class has a positive case (the defect is reported) and a
negative control (the clean or merely noisy input is NOT reported), since a
check that cannot fail proves nothing (R20)."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pdf2md_fidelity import (
    SEVERITY_ERROR,
    align_paragraphs,
    SEVERITY_WARNING,
    Heading,
    caption_labels,
    check_chapters,
    citation_numbers,
    citation_occurrences,
    clean_pdf_text,
    compare_captions,
    compare_citations,
    compare_headings,
    compare_paragraphs,
    locate_in_output,
    numbered_equation_counts,
    drop_running_headers,
    extract_headings,
    equation_numbers,
    find_image_analysis_issues,
    find_embedded_images,
    find_equation_issues,
    find_html_residue,
    fold_letters,
    load_fidelity_config,
    prose_words,
    render_fidelity_md,
    split_paragraphs,
    strip_math_and_images,
)

# Thresholds injected here rather than read from the shipped file, so a later
# recalibration of pdf2md-fidelity.json cannot silently change what these
# cases prove (R21). test_shipped_config_* checks the file's own shape.
CONFIG = {
    "min_prose_tokens": 12,
    "min_token_letters": 3,
    "min_prose_ratio": 0.6,
    "ngram_chars": 12,
    "paragraph_missing_below": 0.5,
    "locate_chunk_words": 40,
    "locate_secondary_vote_share": 0.5,
    "locate_max_span_paragraphs": 3,
    "duplicate_vote_tolerance": 0.9,
    "out_of_order_min_displacement": 2,
    "running_header_min_repeats": 3,
    "running_header_min_letters": 15,
    "caption_sentence_words": ["presents", "illustrates", "shows", "and", "contain", "is"],
    "figure_image_window_lines": 30,
    "citation_min_letters": 2,
    "title_match_ratio": 0.8,
    "pdf_noise_markers": ["<br>", "----- Start of picture text -----"],
    "html_residue_pattern": r"<(?:span|small|div)\b",
    "unnumbered_heading_severity": "warning",
}

P1 = "The orchard keepers measured rainfall across every terrace during the long dry season and recorded each reading in a shared notebook."
P2 = "Beekeepers later compared those notebooks against hive weights, which showed that honey production fell sharply whenever the terraces stayed dry."
P3 = "A second survey asked neighbouring villages whether irrigation channels had been repaired, and most replied that volunteers had cleared the stones."
P4 = "Finally the committee summarised its findings in a short report, recommending that the notebooks be digitised before the next harvest begins."
P5 = "Several families also described how the old wells recovered slowly after the first autumn storms, although none of them kept written records."


def kinds(issues):
    return [issue.kind for issue in issues]


class TestConfig(unittest.TestCase):
    def test_shipped_config_loads_every_key(self):
        config = load_fidelity_config()
        self.assertEqual(set(config), set(CONFIG))
        self.assertIn(config["unnumbered_heading_severity"], (SEVERITY_ERROR, SEVERITY_WARNING))

    def test_missing_key_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg.json"
            path.write_text(json.dumps({"ngram_chars": {"value": 12, "provenance": "t"}}), encoding="utf-8")
            with self.assertRaises(KeyError) as context:
                load_fidelity_config(path)
            self.assertIn("min_prose_tokens", str(context.exception))

    def test_absent_file_is_an_error(self):
        with self.assertRaises(FileNotFoundError):
            load_fidelity_config(Path("does-not-exist.json"))

    def test_bad_severity_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg.json"
            data = {key: {"value": value, "provenance": "t"} for key, value in CONFIG.items()}
            data["unnumbered_heading_severity"]["value"] = "fatal"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_fidelity_config(path)


class TestNormalisation(unittest.TestCase):
    def test_fold_removes_accents_digits_and_punctuation(self):
        self.assertEqual(fold_letters("Réseaux, 3 DÉLAIS!"), "reseauxdelais")

    def test_fold_drops_a_garbled_character_instead_of_failing(self):
        self.assertEqual(fold_letters("DISTRIBU�E"), "distribue")

    def test_prose_words_drop_short_tokens_and_math_fragments(self):
        words = prose_words("Consider _n_ agents ( _V, E_ ) over graphs", min_letters=3)
        self.assertEqual(words, ["consider", "agents", "over", "graphs"])

    def test_strip_math_removes_inline_display_and_image_and_keeps_line_count(self):
        text = "alpha $x = 1$ beta\n$$\ny = 2\n$$\ngamma ![](data:image/jpeg;base64,AAAA) delta"
        stripped = strip_math_and_images(text)
        self.assertNotIn("$", stripped)
        self.assertNotIn("data:", stripped)
        self.assertEqual(stripped.count("\n"), text.count("\n"))
        self.assertIn("alpha", stripped)
        self.assertIn("delta", stripped)


class TestParagraphs(unittest.TestCase):
    def test_split_keeps_start_lines(self):
        paragraphs = split_paragraphs("first line\nsecond line\n\nthird\n")
        self.assertEqual([(p.text, p.line) for p in paragraphs], [("first line second line", 1), ("third", 4)])

    def test_heading_and_picture_marker_end_a_paragraph_and_are_not_paragraphs(self):
        text = "before\n## **1.2 Title**\nafter\n**==> picture [10 x 10] intentionally omitted <==**\nlast"
        self.assertEqual([p.text for p in split_paragraphs(text)], ["before", "after", "last"])

    def test_running_header_repeated_is_dropped_and_a_unique_paragraph_kept(self):
        header = split_paragraphs("4.1. ARTICLE SOUMIS\n\n83\n\n4.1. ARTICLE SOUMIS\n\n4.1. ARTICLE SOUMIS\n\n" + P1)
        kept = drop_running_headers(header, min_repeats=3)
        self.assertEqual([p.text for p in kept], ["83", P1])

    def test_page_numbers_with_different_digits_collapse_to_one_header_key(self):
        paragraphs = split_paragraphs("page 83\n\npage 84\n\npage 85\n\n" + P2)
        self.assertEqual([p.text for p in drop_running_headers(paragraphs, min_repeats=3)], [P2])


class TestExtractHeadings(unittest.TestCase):
    def test_numbered_unnumbered_and_chapter_heading(self):
        text = "## CHAPITRE 4\n## **4.1 Article soumis** \n## **Abstract**\n#### 4.1.2 Preliminaries and Problem Description\n"
        headings = extract_headings(text)
        self.assertEqual(
            [(h.number, h.title) for h in headings],
            [((4, 1), "Article soumis"), (None, "Abstract"), ((4, 1, 2), "Preliminaries and Problem Description")],
        )
        self.assertEqual([h.line for h in headings], [2, 3, 4])

    def test_text_that_is_not_a_heading_is_ignored(self):
        self.assertEqual(extract_headings("4.1 Article soumis\nplain prose\n"), [])


class TestCompareHeadings(unittest.TestCase):
    PDF = "## **4.1 Article soumis**\n\n## **4.1.1 Introduction**\n\ntext\n\n## **4.1.2 Method**\n\n## **4.2 Conclusion du chapitre**\n"

    def test_clean_chapter_reports_nothing(self):
        output = "### 4.1 Article soumis\n\n#### 4.1.1 Introduction\n\ntext\n\n#### 4.1.2 Method\n\n### 4.2 Conclusion du chapitre\n"
        self.assertEqual(compare_headings(4, self.PDF, output, CONFIG), [])

    def test_lost_numbered_headings_are_errors_naming_the_heading(self):
        output = "### 4.1 Article soumis\n\ntext\n\n#### 4.1.2 Method\n"
        issues = compare_headings(4, self.PDF, output, CONFIG)
        self.assertEqual(kinds(issues), ["missing_heading", "missing_heading"])
        self.assertTrue(all(issue.severity == SEVERITY_ERROR for issue in issues))
        self.assertIn("4.1.1 Introduction", issues[0].detail)
        self.assertIn("4.2 Conclusion du chapitre", issues[1].detail)

    def test_a_heading_whose_title_survives_as_plain_text_says_so_with_its_line(self):
        output = "### 4.1 Article soumis\n\nIntroduction\n\ntext\n\n#### 4.1.2 Method\n\n### 4.2 Conclusion du chapitre\n"
        (issue,) = compare_headings(4, self.PDF, output, CONFIG)
        self.assertEqual(issue.output_line, 3)
        self.assertIn("plain text", issue.detail)

    def test_unnumbered_heading_loss_uses_the_configured_severity(self):
        pdf = "## **Abstract**\n\ntext\n"
        warning = compare_headings(4, pdf, "text\n", CONFIG)
        self.assertEqual((kinds(warning), warning[0].severity), (["missing_heading"], SEVERITY_WARNING))
        error = compare_headings(4, pdf, "text\n", {**CONFIG, "unnumbered_heading_severity": "error"})
        self.assertEqual(error[0].severity, SEVERITY_ERROR)

    def test_an_unnumbered_label_that_survives_as_a_plain_line_is_not_a_lost_heading(self):
        pdf = "## **Statut de soumission : Article soumis.**\n\ntext\n"
        output = "Statut de soumission : Article soumis.\n\ntext\n"
        self.assertEqual(compare_headings(4, pdf, output, CONFIG), [])

    def test_an_unnumbered_heading_present_in_the_output_is_not_reported(self):
        self.assertEqual(compare_headings(4, "## **Abstract**\n", "##### Abstract\n", CONFIG), [])

    def test_headings_out_of_order_are_reported(self):
        output = "### 4.1 Article soumis\n\n#### 4.1.2 Method\n\n#### 4.1.1 Introduction\n\n### 4.2 Conclusion du chapitre\n"
        issues = compare_headings(4, self.PDF, output, CONFIG)
        self.assertEqual(kinds(issues), ["out_of_order_heading"])

    def test_title_that_differs_is_a_warning_and_a_close_title_is_not(self):
        pdf = "## **4.1 Article soumis**\n"
        far = compare_headings(4, pdf, "### 4.1 Completely different words\n", CONFIG)
        self.assertEqual((kinds(far), far[0].severity), (["heading_title_mismatch"], SEVERITY_WARNING))
        self.assertEqual(compare_headings(4, pdf, "### 4.1 Article soumis.\n", CONFIG), [])


class TestCompareParagraphs(unittest.TestCase):
    def pdf(self, *parts):
        return "\n\n".join(parts)

    def test_identical_content_reports_nothing(self):
        text = self.pdf(P1, P2, P3)
        self.assertEqual(compare_paragraphs(4, text, text, CONFIG), [])

    def test_a_paragraph_missing_from_the_output_is_an_error_with_an_excerpt(self):
        issues = compare_paragraphs(4, self.pdf(P1, P2, P3), self.pdf(P1, P3), CONFIG)
        self.assertEqual(kinds(issues), ["missing_paragraph"])
        self.assertTrue(issues[0].pdf_excerpt.startswith("Beekeepers later compared"))

    def test_paragraphs_in_a_different_order_are_reported(self):
        issues = compare_paragraphs(4, self.pdf(P1, P2, P3, P4), self.pdf(P4, P1, P2, P3), CONFIG)
        self.assertEqual(kinds(issues), ["out_of_order_paragraph"])
        self.assertTrue(issues[0].pdf_excerpt.startswith("Finally the committee"))
        self.assertEqual(issues[0].output_line, 1)

    def test_a_paragraph_repeated_in_the_output_is_a_duplicate(self):
        issues = compare_paragraphs(4, self.pdf(P1, P2), self.pdf(P1, P2, P2), CONFIG)
        self.assertEqual(kinds(issues), ["duplicate_paragraph"])

    def test_a_paragraph_repeated_in_the_pdf_as_well_is_not_a_duplicate(self):
        text = self.pdf(P1, P2, P2)
        self.assertEqual(compare_paragraphs(4, text, text, CONFIG), [])

    def test_prose_only_in_the_output_is_an_extra_warning(self):
        issues = compare_paragraphs(4, self.pdf(P1, P2), self.pdf(P1, P2, P5), CONFIG)
        self.assertEqual(kinds(issues), ["extra_paragraph"])
        self.assertEqual(issues[0].severity, SEVERITY_WARNING)

    def test_a_pdf_paragraph_split_by_a_page_break_with_header_is_not_flagged(self):
        words = P1.split()
        first, second = " ".join(words[:10]), " ".join(words[10:])
        pdf = self.pdf(P2, first, "4.1. ARTICLE SOUMIS", "83", second, "4.1. ARTICLE SOUMIS", "84", P3, "4.1. ARTICLE SOUMIS")
        output = self.pdf(P2, P1, P3)
        self.assertEqual(compare_paragraphs(4, pdf, output, CONFIG), [])

    def test_formulas_in_the_output_do_not_create_extra_content(self):
        output = P1.replace("rainfall", "rainfall $x_{ij} = \\frac{a}{b}$") + "\n\n$$\ny = 1\n$$\n\n" + P2
        pdf = self.pdf(P1.replace("rainfall", "rainfall _x_ _ij_ = _a_ _b_"), P2)
        self.assertEqual(compare_paragraphs(4, pdf, output, CONFIG), [])

    def test_a_formula_only_pdf_paragraph_is_not_reported_missing(self):
        formula = "_A_ 22 _[A]_[11] = _w[i]_ ( _k_ ) _→ α ∈_ R[1] _[×][n]_ _, . . . ,_ _n_ _i_ _j_ _h_"
        self.assertEqual(compare_paragraphs(4, self.pdf(P1, formula), P1, CONFIG), [])

    def test_a_garbled_accent_in_the_pdf_still_matches_the_clean_output(self):
        clean = "Les réseaux distribués des agents mesurent chaque délai de communication pendant que les robots avancent lentement vers leur cible commune."
        garbled = clean.replace("é", "�")
        self.assertEqual(compare_paragraphs(4, garbled, clean, CONFIG), [])

    def test_figure_text_and_table_rows_in_the_pdf_are_not_judged(self):
        figure = "**----- Start of picture text -----**<br> " + P3 + "<br>"
        table = "||Table 2.1<br>|An overview of methods| " + P4
        self.assertEqual(compare_paragraphs(4, self.pdf(P1, figure, table), P1, CONFIG), [])

    def test_a_short_paragraph_is_not_judged(self):
        self.assertEqual(compare_paragraphs(4, self.pdf(P1, "Too short to check."), P1, CONFIG), [])


class TestCleanPdfText(unittest.TestCase):
    HEADER = "CHAPITRE 4. CONSENSUS DANS LES SYSTEMES MULTI-AGENTS AVEC {} DELAIS DE COMMUNICATION"

    def test_running_headers_with_a_changing_page_number_are_removed_and_lines_keep_their_numbers(self):
        text = "\n\n".join([self.HEADER.format(80), P1, self.HEADER.format(82), P2, self.HEADER.format(84)])
        cleaned = clean_pdf_text(text, CONFIG)
        self.assertEqual(len(cleaned.split("\n")), len(text.split("\n")))
        self.assertNotIn("CONSENSUS", cleaned)
        self.assertIn(P1, cleaned)
        self.assertIn(P2, cleaned)

    def test_a_short_repeated_line_is_real_text_and_stays(self):
        text = "\n".join(["_Proof._"] * 5 + [P1])
        self.assertEqual(clean_pdf_text(text, CONFIG).count("_Proof._"), 5)

    def test_a_long_line_repeated_fewer_times_than_the_threshold_stays(self):
        text = "\n".join([self.HEADER.format(80), P1, self.HEADER.format(82)])
        self.assertIn("CONSENSUS", clean_pdf_text(text, CONFIG))

    def test_page_numbers_and_figure_text_are_removed(self):
        text = "\n".join(["83 ", "**83**", "**==> picture [10 x 10] intentionally omitted <==**", "**----- Start of picture text -----**<br>0.8 200<br>", P1])
        self.assertEqual(clean_pdf_text(text, CONFIG).split(), P1.split())


class TestCaptionLabels(unittest.TestCase):
    def labels(self, text, kind):
        return [label for label, _line in caption_labels(text, CONFIG)[kind]]

    def test_a_caption_counts_and_an_in_text_sentence_about_the_same_label_does_not(self):
        text = "Figure 3.8 presents the desired positions of the robots.\n\nFigure 3.8 The desired and actual positions of the robots.\n"
        self.assertEqual(self.labels(text, "figure"), ["3.8"])
        self.assertEqual(caption_labels(text, CONFIG)["figure"][0][1], 3)

    def test_a_label_repeated_as_a_caption_counts_once(self):
        text = "Figure 2.1 Overview of the method.\n\nFigure 2.1 Overview of the method.\n"
        self.assertEqual(self.labels(text, "figure"), ["2.1"])

    def test_table_markup_before_the_label_is_ignored_and_the_sentence_form_is_not_a_caption(self):
        text = "||Table 3.3<br>The fuzzy control rules|\n\nTable 3.2 and Table 3.3 contain all the rules.\n"
        self.assertEqual(self.labels(text, "table"), ["3.3"])

    def test_a_sub_panel_reference_is_not_a_caption(self):
        self.assertEqual(self.labels("Figure 3.9(b) shows that the controller limits oscillations.\n", "figure"), [])

    def test_french_tableau_counts(self):
        self.assertEqual(self.labels("Tableau 5.1 Parametres de simulation.\n", "table"), ["5.1"])


class TestCompareCaptions(unittest.TestCase):
    PDF = "Figure 3.1 First plot of the run.\n\nTable 3.1 Parameters of the model.\n"

    def kinds(self, output):
        return kinds(compare_captions(3, self.PDF, output, CONFIG))

    def test_a_complete_chapter_reports_nothing(self):
        output = "![](a.png)\n\nFigure 3.1 First plot of the run.\n\nTable 3.1 Parameters of the model.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
        self.assertEqual(self.kinds(output), [])

    def test_a_lost_caption_is_reported_for_each_kind(self):
        self.assertEqual(sorted(self.kinds("text only\n")), ["figure_caption_missing", "table_caption_missing"])

    def test_a_figure_caption_without_an_image_is_reported_and_an_image_far_above_is_not_enough(self):
        no_image = "Figure 3.1 First plot of the run.\n\nTable 3.1 Parameters of the model.\n\n<table><tr><td>1</td></tr></table>\n"
        self.assertEqual(self.kinds(no_image), ["figure_without_image"])
        far = "![](a.png)\n" + "\n".join(["filler"] * 40) + "\nFigure 3.1 First plot of the run.\n\nTable 3.1 Parameters of the model.\n\n<table></table>\n"
        self.assertEqual(self.kinds(far), ["figure_without_image"])

    def test_a_heading_between_the_image_and_the_caption_stops_the_search(self):
        output = "![](a.png)\n\n## Next section\n\nFigure 3.1 First plot of the run.\n\nTable 3.1 Parameters.\n\n| a |\n|---|\n"
        self.assertEqual(self.kinds(output), ["figure_without_image"])

    def test_panel_labels_between_image_and_caption_are_allowed(self):
        output = "![](a.png)\n\n(a)\n\n![](b.png)\n\n(b)\n\nFigure 3.1 First plot of the run.\n\nTable 3.1 Parameters.\n\n<table></table>\n"
        self.assertEqual(self.kinds(output), [])

    def test_a_table_caption_with_no_table_is_reported(self):
        output = "![](a.png)\n\nFigure 3.1 First plot of the run.\n\nTable 3.1 Parameters of the model.\n\nonly prose follows here.\n"
        self.assertEqual(self.kinds(output), ["table_without_content"])


class TestImageAnalysisBlocks(unittest.TestCase):
    TABLE = "<details>\n<summary>line</summary>\n\n| Time(s) | x1 |\n| --- | --- |\n| 0 | ~2.0 |\n</details>"
    DIAGRAM = "<details>\n<summary>flowchart</summary>\n\nThis diagram illustrates the control system architecture.\n</details>"

    def test_a_table_of_values_read_from_a_plot_is_an_error_with_its_line(self):
        text = "prose\n\n![](a.png)\n\n" + self.TABLE + "\n\nFigure 3.8 caption\n"
        (issue,) = find_image_analysis_issues(3, text)
        self.assertEqual((issue.kind, issue.severity, issue.output_line), ("image_analysis_block", SEVERITY_ERROR, 5))
        self.assertIn("'line'", issue.detail)
        self.assertEqual(issue.pdf_excerpt, "| Time(s) | x1 |")

    def test_a_description_of_a_diagram_is_one_too(self):
        # Measured 2026-10-11: the same <details> wrapper carries a sentence the thesis does not contain.
        (issue,) = find_image_analysis_issues(3, "![](a.png)\n\n" + self.DIAGRAM + "\n")
        self.assertIn("'flowchart'", issue.detail)

    def test_every_block_is_reported(self):
        self.assertEqual(len(find_image_analysis_issues(3, self.TABLE + "\n\n" + self.DIAGRAM + "\n")), 2)

    def test_an_ordinary_table_and_ordinary_prose_are_not_blocks(self):
        self.assertEqual(find_image_analysis_issues(3, "| a | b |\n|---|---|\n| 1 | 2 |\n\nplain prose\n"), [])


class TestOutOfOrderDisplacement(unittest.TestCase):
    ORDER = [P1, P2, P3, P4, P5]

    def test_a_shift_of_one_paragraph_is_not_reported_and_a_far_one_is(self):
        pdf = "\n\n".join(self.ORDER)
        near = "\n\n".join([P1, P3, P2, P4, P5])
        far = "\n\n".join([P5, P1, P2, P3, P4])
        self.assertEqual(kinds(compare_paragraphs(4, pdf, near, CONFIG)), [])
        self.assertEqual(kinds(compare_paragraphs(4, pdf, far, CONFIG)), ["out_of_order_paragraph"])

    def test_the_displacement_is_the_distance_from_the_interval_the_neighbours_allow(self):
        pdf = "\n\n".join(self.ORDER)
        alignment = align_paragraphs(pdf, "\n\n".join([P5, P1, P2, P3, P4]), CONFIG)
        self.assertEqual(list(alignment.displacement.values()), [4])


class TestEquationNumbers(unittest.TestCase):
    def eq(self, number_text):
        return "$$\nx = y" + number_text + "\n$$\n"

    def test_tags_and_a_trailing_number_written_as_text_are_both_read(self):
        text = self.eq(r", \tag {3.24}") + self.eq(", (3. 2 5)") + self.eq(r", \tag {3.26}")
        self.assertEqual([(label, form) for label, _l, form in equation_numbers(text)], [((3, 24), "tag"), ((3, 25), "trailing"), ((3, 26), "tag")])

    def test_a_gap_in_the_numbering_is_a_missing_equation(self):
        text = self.eq(r"\tag {3.1}") + self.eq(r"\tag {3.2}") + self.eq(r"\tag {3.4}")
        (issue,) = find_equation_issues(3, text)
        self.assertEqual(issue.kind, "equation_number_gap")
        self.assertIn("(3.3)", issue.detail)

    def test_a_number_left_as_text_is_a_warning_not_a_gap(self):
        issues = find_equation_issues(3, self.eq(r"\tag {3.1}") + self.eq(", (3. 2)"))
        self.assertEqual(kinds(issues), ["equation_number_unformatted"])
        self.assertEqual(issues[0].severity, SEVERITY_WARNING)

    def test_a_repeated_number_is_an_error(self):
        self.assertEqual(kinds(find_equation_issues(3, self.eq(r"\tag {3.1}") + self.eq(r"\tag {3.1}"))), ["equation_number_duplicate"])

    def test_unnumbered_equations_are_not_counted_or_reported(self):
        self.assertEqual(find_equation_issues(3, self.eq("")), [])
        self.assertEqual(numbered_equation_counts(self.eq("")), (0, 0))

    def test_expected_is_the_highest_number_and_found_the_distinct_count(self):
        text = self.eq(r"\tag {3.1}") + self.eq(r"\tag {3.2}") + self.eq(r"\tag {3.4}")
        self.assertEqual(numbered_equation_counts(text), (4, 3))

    def test_a_number_inside_ordinary_math_is_not_taken_for_an_equation_number(self):
        self.assertEqual(equation_numbers("$$\nf(3.5) = x\n$$\n"), [])


class TestCitations(unittest.TestCase):
    def numbers(self, text):
        return citation_numbers(text, CONFIG)

    def test_prose_citations_count_with_every_number_of_a_group(self):
        self.assertEqual(self.numbers("as shown in [14] and by Smith et al. [6, 38]."), [14, 6, 38])

    def test_matrix_indices_the_pdf_reader_prints_do_not_count(self):
        # Verbatim shapes measured 2026-10-11 on the real PDF reading.
        text = "_w[i] ∈_ R _[1]_ [1] and _[≥][η][A][for][all][k][≥]_ [0] and = [( _w_ [2] and _A_ 22 [11]"
        self.assertEqual(self.numbers(text), [])

    def test_a_citation_inside_a_formula_of_the_output_is_not_counted(self):
        self.assertEqual(self.numbers("the set $x \\in [1, 2]$ is bounded"), [])

    def test_a_missing_reference_and_a_repeat_deficit_are_both_errors(self):
        # A citation lost leaves a claim without its source; measured
        # 2026-10-11: mineru read "[14]:" as a fragment of mathematics.
        pdf = "see [14] and again [14] and also [87] and then [9]."
        out = "see [14] and also [9]."
        issues = compare_citations(3, pdf, out, CONFIG)
        self.assertEqual([(i.kind, i.severity) for i in issues], [("citation_missing", SEVERITY_ERROR), ("citation_undercounted", SEVERITY_ERROR)])
        self.assertIn("[87]", issues[0].detail)
        self.assertIn("[14]", issues[1].detail)

    def test_an_occurrence_carries_its_bracket_its_following_punctuation_and_the_five_words_before_it(self):
        (occurrence,) = citation_occurrences("From the priority update rule, the following holds [14]: next", CONFIG)
        self.assertEqual(occurrence["numbers"], [14])
        self.assertEqual((occurrence["bracket"], occurrence["after"]), ("[14]", ":"))
        self.assertEqual(occurrence["words"], ["update", "rule", "the", "following", "holds"])

    def test_equal_citations_report_nothing(self):
        self.assertEqual(compare_citations(3, "see [14] and [6, 38].", "see [14] and [6, 38].", CONFIG), [])


class TestFloatsAndLookAlikes(unittest.TestCase):
    CAPTION = "Figure 2.1 Overview of the method together with the sensors, the terraces, the notebooks and the volunteers used during the long dry season."

    def test_a_caption_far_from_where_the_pdf_reader_put_it_is_not_out_of_order(self):
        # Measured 2026-10-11: the PDF reader leaves a float where the page
        # layout put it, mineru where the text refers to it. Moving it in a
        # repair detached figures 3.8 and 3.9 from their images.
        pdf = "\n\n".join([P1, P2, P3, P4, P5, self.CAPTION])
        output = "\n\n".join([self.CAPTION, P1, P2, P3, P4, P5])
        self.assertEqual(kinds(compare_paragraphs(4, pdf, output, CONFIG)), [])
        self.assertEqual(align_paragraphs(pdf, output, CONFIG).missing, [])

    def test_an_in_text_sentence_about_a_figure_still_takes_part_in_the_order(self):
        sentence = "Figure 2.1 shows the sensors, and the survey is described in the following paragraphs of the text."
        pdf = "\n\n".join([P1, P2, P3, P4, P5, sentence])
        output = "\n\n".join([sentence, P1, P2, P3, P4, P5])
        self.assertEqual(kinds(compare_paragraphs(4, pdf, output, CONFIG)), ["out_of_order_paragraph"])

    def test_a_restated_paragraph_is_matched_to_the_occurrence_the_pdf_order_implies(self):
        # Measured 2026-10-11: a theorem statement restated later tied with its
        # first occurrence, and the first one was taken, reporting a displacement
        # of dozens that was not there.
        pdf = "\n\n".join([P1, P2, P3, P4])
        fillers = [P5, P5.replace("old wells", "new wells"), P5.replace("autumn", "winter")]
        output = "\n\n".join([P1, P3, *fillers, P2, P3, P4])
        self.assertNotIn("out_of_order_paragraph", kinds(compare_paragraphs(4, pdf, output, CONFIG)))
        self.assertEqual([position for _paragraph, position in align_paragraphs(pdf, output, CONFIG).matched], [0, 5, 6, 7])

    def test_a_genuinely_moved_paragraph_is_still_reported_next_to_a_look_alike(self):
        pdf = "\n\n".join([P1, P2, P3, P4, P5])
        output = "\n\n".join([P4, P1, P2, P3, P5])
        self.assertEqual(kinds(compare_paragraphs(4, pdf, output, CONFIG)), ["out_of_order_paragraph"])


class TestDeterminism(unittest.TestCase):
    # Two output paragraphs of the same length, 61 letters and 12 words each,
    # and one PDF paragraph that is the first followed by the second: each
    # output paragraph holds exactly 50 of the PDF paragraph's fingerprints,
    # a real tie that the winner of used to depend on set-iteration order.
    HALF_A = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima"
    HALF_B = "mike nine oscar papa quebec romeo sierra tango umber victor whiskey xray"
    SEEDS = ("1", "2", "3", "4", "5", "6", "7", "8")

    def test_the_two_halves_really_tie(self):
        self.assertEqual(sum(len(word) for word in self.HALF_A.split()), sum(len(word) for word in self.HALF_B.split()))

    def test_a_real_tie_goes_to_the_earliest_paragraph(self):
        alignment = align_paragraphs(self.HALF_A + " " + self.HALF_B, self.HALF_B + "\n\n" + self.HALF_A, CONFIG)
        self.assertEqual([position for _paragraph, position in alignment.matched], [0])

    def test_the_alignment_does_not_depend_on_the_hash_seed(self):
        import subprocess

        code = (
            "import json, sys; sys.path.insert(0, sys.argv[1]); import pdf2md_fidelity as f; "
            "d = json.loads(sys.argv[2]); a = f.align_paragraphs(d['pdf'], d['out'], d['config']); "
            "print([position for _p, position in a.matched])"
        )
        payload = json.dumps({"pdf": self.HALF_A + " " + self.HALF_B, "out": self.HALF_A + "\n\n" + self.HALF_B, "config": CONFIG})
        scripts = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        answers = set()
        for seed in self.SEEDS:
            run = subprocess.run(
                [sys.executable, "-c", code, scripts, payload], capture_output=True, text=True, timeout=60, env={**os.environ, "PYTHONHASHSEED": seed}
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            answers.add(run.stdout.strip())
        self.assertEqual(answers, {"[0]"})


class TestLocateInOutput(unittest.TestCase):
    OUTPUT = "\n\n".join(["intro", P1 + " $x = 1$", "$$\ny = 2\n$$", P2, P3]) + "\n"

    def test_a_page_is_located_to_the_lines_of_its_paragraphs(self):
        page = P2 + " " + P3
        start, end = locate_in_output(page, self.OUTPUT, CONFIG)
        lines = self.OUTPUT.splitlines()
        self.assertTrue(lines[start - 1].startswith("Beekeepers later"))
        self.assertTrue(lines[end - 1].startswith("A second survey"))

    def test_a_chunk_matching_a_paragraph_far_away_does_not_stretch_the_range(self):
        # CONFIG allows a span of 3 paragraph positions. The page's own three
        # paragraphs sit together; a fourth chunk matches a paragraph 9 later.
        near = [P1, P2, P3]
        output = "\n\n".join(near + [P5, P5.replace("old wells", "new wells"), P5.replace("autumn", "winter"), P5.replace("families", "farmers"), P5.replace("slowly", "quickly"), P5.replace("written", "formal"), P4]) + "\n"
        page = " ".join(near) + " " + P4
        start, end = locate_in_output(page, output, CONFIG)
        lines = output.splitlines()
        self.assertTrue(lines[start - 1].startswith("The orchard keepers"))
        self.assertTrue(lines[end - 1].startswith("A second survey"))

    def test_a_page_of_unrelated_text_is_not_located(self):
        self.assertIsNone(locate_in_output(P5 + " " + P4, self.OUTPUT, CONFIG))

    def test_a_page_with_no_prose_is_not_located(self):
        self.assertIsNone(locate_in_output("_A_ 22 _[A]_[11] = _w[i]_ _k_", self.OUTPUT, CONFIG))


class TestEmbeddedImages(unittest.TestCase):
    def test_each_data_uri_image_is_an_error_with_its_line(self):
        text = "line one\n\n![](data:image/jpeg;base64,/9j/4AAQ)\n\nlast"
        issues = find_embedded_images(4, text)
        self.assertEqual((kinds(issues), issues[0].output_line, issues[0].severity), (["embedded_image"], 3, SEVERITY_ERROR))

    def test_a_normal_image_link_is_not_reported(self):
        self.assertEqual(find_embedded_images(4, "![figure](assets/figures/a.png)"), [])


class TestHtmlResidue(unittest.TestCase):
    def test_footnote_span_is_an_error_with_its_line(self):
        text = 'prose\n<small><span class="docvortex-page-footnote">note</span></small>\n'
        (issue,) = find_html_residue(4, text, CONFIG)
        self.assertEqual((issue.kind, issue.severity, issue.output_line), ("html_residue", SEVERITY_ERROR, 2))

    def test_br_inside_a_table_cell_is_not_residue(self):
        self.assertEqual(find_html_residue(4, "| a<br>b | c |\n|---|---|\n", CONFIG), [])


class TestCheckChapters(unittest.TestCase):
    def test_clean_document_has_no_error(self):
        chapters = {4: ("", "## **4.1 Article soumis**\n\n" + P1 + "\n\n" + P2)}
        outputs = {4: ("chapitre4", "### 4.1 Article soumis\n\n" + P1 + "\n\n" + P2)}
        report = check_chapters(chapters, outputs, CONFIG)
        self.assertEqual((report["error_count"], report["warning_count"], report["chapters"]["4"]), (0, 0, []))

    def test_totals_and_counts_aggregate_by_kind_and_severity(self):
        pdf = {4: ("", "## **4.1 Article soumis**\n\n" + P1 + "\n\n" + P2)}
        output = {4: ("chapitre4", "![](data:image/jpeg;base64,AAAA)\n\n" + P1 + "\n\n" + P5)}
        report = check_chapters(pdf, output, CONFIG)
        self.assertEqual(report["totals"], {"embedded_image": 1, "missing_heading": 1, "missing_paragraph": 1, "extra_paragraph": 1})
        self.assertEqual((report["error_count"], report["warning_count"]), (3, 1))

    def test_a_chapter_on_one_side_only_is_reported(self):
        report = check_chapters({3: ("", P1)}, {4: ("chapitre4", P1)}, CONFIG)
        self.assertEqual(report["totals"], {"chapter_missing_in_output": 1, "chapter_missing_in_pdf": 1})
        self.assertEqual(report["error_count"], 1)

    def test_real_shape_regression_conclusion_placed_before_the_article(self):
        pdf = {4: ("", "## **4.1 Article soumis**\n\n" + P1 + "\n\n" + P2 + "\n\n" + P3 + "\n\n## **4.2 Conclusion du chapitre**\n\n" + P4)}
        output = {4: ("chapitre4", P4 + "\n\n### 4.1 Article soumis\n\n" + P1 + "\n\n" + P2 + "\n\n" + P3)}
        report = check_chapters(pdf, output, CONFIG)
        self.assertEqual(report["totals"], {"missing_heading": 1, "out_of_order_paragraph": 1})

    def test_render_lists_every_issue_and_a_clean_chapter(self):
        pdf = {3: ("", P1), 4: ("", "## **4.1 Article soumis**\n\n" + P1)}
        output = {3: ("chapitre3", P1), 4: ("chapitre4", P1)}
        rendered = render_fidelity_md(check_chapters(pdf, output, CONFIG))
        self.assertIn("Chapter 3: no issue", rendered)
        self.assertIn("| missing_heading | error |", rendered)
        self.assertIn("1 error(s)", rendered)


if __name__ == "__main__":
    unittest.main()
