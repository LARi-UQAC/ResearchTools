"""Offline tests for pdf2md_repair. Everything is synthetic and fictitious
(R34) and runs in temporary directories: no PDF, no model, no network.

Each repair has a positive case (the defect is fixed), a negative control
(clean input is left byte-identical) and, for the whole chapter, the check
that matters: after the repair, the fidelity check finds fewer errors than
before (R9: the effect is measured, not assumed)."""

import base64
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pdf2md_fidelity as fidelity
import pdf2md_repair as repair

FIDELITY = {
    "min_prose_tokens": 12,
    "min_token_letters": 3,
    "min_prose_ratio": 0.6,
    "ngram_chars": 12,
    "paragraph_missing_below": 0.5,
    "locate_chunk_words": 40,
    "locate_secondary_vote_share": 0.5,
    "locate_max_span_paragraphs": 12,
    "duplicate_vote_tolerance": 0.9,
    "out_of_order_min_displacement": 3,
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
CONFIG = {
    "anchor_lookahead_paragraphs": 5,
    "heading_level_offset": 1,
    "assets_dir_name": "assets",
    "figures_dir_name": "figures",
    "image_extensions": {"jpeg": "jpg", "png": "png"},
    "footnote_pattern": r"<small><span[^>]*page-footnote[^>]*>(.*?)</span></small>",
    "backup_dir_name": "pdf2md-backup",
    "garbled_citation_span_max_chars": 80,
    "garbled_span_forbidden": ["=", "<", ">", "\\leq", "\\sum", "\\frac"],
    "removed_blocks_file": "image_analysis_removed.md",
    "glyph_image_max_bytes": 100,
    "glyph_image_replacement": "∎",
}

P1 = "The orchard keepers measured rainfall across every terrace during the long dry season and recorded each reading in a shared notebook."
P2 = "Beekeepers later compared those notebooks against hive weights, which showed that honey production fell sharply whenever the terraces stayed dry."
P3 = "A second survey asked neighbouring villages whether irrigation channels had been repaired, and most replied that volunteers had cleared the stones."
P4 = "Finally the committee summarised its findings in a short report, recommending that the notebooks be digitised before the next harvest begins."
P5 = "Several families also described how the old wells recovered slowly after the first autumn storms, although none of them kept written records."
P6 = "Teachers in the valley schools used the rainfall tables to explain seasonal change, and pupils copied the figures onto large wall charts every month."
P7 = "Meanwhile the cooperative bought a small drying shed so that harvested fruit could be stored safely whenever the autumn storms arrived early."
P8 = "The regional office eventually funded a second notebook for each village, asking volunteers to record spring flowering dates alongside the rainfall."

JPEG_BYTES = b"JPEGDATA-1" * 30      # 300 bytes: larger than the glyph threshold of CONFIG (100)
PNG_BYTES = b"PNGDATA-2" * 30
GLYPH_BYTES = b"tiny-square"          # 11 bytes: a symbol, not a figure
JPEG = base64.b64encode(JPEG_BYTES).decode("ascii")
PNG = base64.b64encode(PNG_BYTES).decode("ascii")
GLYPH = base64.b64encode(GLYPH_BYTES).decode("ascii")


def join(*parts):
    return "\n\n".join(parts) + "\n"


class TestConfig(unittest.TestCase):
    def test_shipped_config_has_every_key(self):
        self.assertEqual(set(repair.load_repair_config()), set(CONFIG))

    def test_missing_key_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            path.write_text(json.dumps({"backup_dir_name": {"value": "b", "provenance": "t"}}), encoding="utf-8")
            with self.assertRaises(KeyError) as context:
                repair.load_repair_config(path)
            self.assertIn("anchor_lookahead_paragraphs", str(context.exception))

    def test_absent_file_is_an_error(self):
        with self.assertRaises(FileNotFoundError):
            repair.load_repair_config(Path("absent.json"))


class TestMisreadCitations(unittest.TestCase):
    PDF = "The committee compared every notebook with the older survey and the following holds [14]: the totals agree."
    GARBLED = "The committee compared every notebook with the older survey and the following holds ${ \\sqrt { I } } { \\sqrt { J } } .$ the totals agree."

    def run_restore(self, output, pdf=None, config=CONFIG):
        return repair.restore_misread_citations(output, pdf or self.PDF, config, FIDELITY)

    def test_a_citation_read_as_math_is_put_back(self):
        text, restored, unplaced = self.run_restore(self.GARBLED)
        self.assertIn("holds [14]: the totals", text)
        self.assertNotIn("sqrt", text)
        self.assertEqual(len(restored), 1)
        self.assertEqual(unplaced, [])

    def test_no_deficit_leaves_the_text_byte_identical(self):
        intact = self.PDF
        text, restored, unplaced = self.run_restore(intact)
        self.assertEqual((text, restored, unplaced), (intact, [], []))

    def test_a_real_formula_is_never_replaced(self):
        formula = self.GARBLED.replace("{ \\sqrt { I } } { \\sqrt { J } } .", "x = \\frac { a } { b }")
        text, restored, unplaced = self.run_restore(formula)
        self.assertEqual(text, formula)
        self.assertEqual(restored, [])
        self.assertEqual(len(unplaced), 1)

    def test_a_span_longer_than_the_bound_is_left_alone(self):
        config = dict(CONFIG, garbled_citation_span_max_chars=10)
        text, restored, _ = self.run_restore(self.GARBLED, config=config)
        self.assertEqual(text, self.GARBLED)
        self.assertEqual(restored, [])

    def test_an_ambiguous_place_is_left_alone(self):
        twice = self.GARBLED + " " + self.GARBLED
        text, restored, unplaced = self.run_restore(twice, pdf=self.PDF)
        self.assertEqual(restored, [])
        self.assertEqual(text, twice)
        self.assertEqual(len(unplaced), 1)


class TestEmbeddedImages(unittest.TestCase):
    def test_images_become_files_and_relative_links_in_order(self):
        text = f"before\n\n![fig a](data:image/jpeg;base64,{JPEG})\n\nmiddle\n\n![](data:image/png;base64,{PNG})\n"
        new, figures = repair.extract_embedded_images(text, 3, CONFIG)
        self.assertEqual([name for name, _data in figures], ["chapter3_figure1.jpg", "chapter3_figure2.png"])
        self.assertEqual([data for _name, data in figures], [JPEG_BYTES, PNG_BYTES])
        self.assertIn("![fig a](../assets/figures/chapter3_figure1.jpg)", new)
        self.assertIn("![](../assets/figures/chapter3_figure2.png)", new)
        self.assertNotIn("base64", new)

    def test_whitespace_inside_the_data_is_tolerated(self):
        split = JPEG[:4] + "\n" + JPEG[4:]
        _new, figures = repair.extract_embedded_images(f"![](data:image/jpeg;base64,{split})", 1, CONFIG)
        self.assertEqual(figures[0][1], JPEG_BYTES)

    def test_an_unknown_type_and_undecodable_data_are_left_in_place(self):
        for image in (f"![](data:image/tiff;base64,{JPEG})", "![](data:image/jpeg;base64,AAA)"):
            new, figures = repair.extract_embedded_images(image, 1, CONFIG)
            self.assertEqual((new, figures), (image, []))

    def test_an_ordinary_image_link_is_not_touched(self):
        text = "![fig](assets/figures/a.png)"
        self.assertEqual(repair.extract_embedded_images(text, 1, CONFIG), (text, []))


class TestGlyphImages(unittest.TestCase):
    # Measured 2026-10-11 on the real thesis: mineru extracted each end-of-proof square as a
    # 1 KB image, which then looked like a figure and shifted the figure file numbering.
    def test_a_tiny_image_becomes_the_symbol_and_is_counted(self):
        text = f"Proof text.\n\n![](data:image/jpeg;base64,{GLYPH})\n\nNext paragraph.\n"
        new, count = repair.replace_glyph_images(text, CONFIG)
        self.assertEqual(count, 1)
        self.assertIn("∎", new)
        self.assertNotIn("base64", new)
        self.assertIn("Proof text.", new)
        self.assertIn("Next paragraph.", new)

    def test_a_real_figure_is_left_for_the_extraction(self):
        text = f"![fig](data:image/jpeg;base64,{JPEG})"
        self.assertEqual(repair.replace_glyph_images(text, CONFIG), (text, 0))

    def test_a_glyph_takes_no_figure_number(self):
        text = (f"![](data:image/jpeg;base64,{GLYPH})\n\n![a](data:image/jpeg;base64,{JPEG})\n\n"
                f"![](data:image/jpeg;base64,{GLYPH})\n\n![b](data:image/png;base64,{PNG})\n")
        new, glyphs = repair.replace_glyph_images(text, CONFIG)
        new, figures = repair.extract_embedded_images(new, 4, CONFIG)
        self.assertEqual(glyphs, 2)
        self.assertEqual([name for name, _d in figures], ["chapter4_figure1.jpg", "chapter4_figure2.png"])

    def test_undecodable_or_unknown_data_is_left_alone(self):
        for image in ("![](data:image/jpeg;base64,AAA)", f"![](data:image/tiff;base64,{GLYPH})"):
            self.assertEqual(repair.replace_glyph_images(image, CONFIG), (image, 0))

    def test_the_repair_report_carries_the_count(self):
        text = f"Proof.\n\n![](data:image/jpeg;base64,{GLYPH})\n"
        _t, _f, info = repair.repair_chapter(1, "unrelated pdf text", text, CONFIG, FIDELITY)
        self.assertEqual(info["glyph_images_replaced"], 1)


class TestImageAnalysisBlocks(unittest.TestCase):
    TABLE = "<details>\n<summary>line</summary>\n\n| Time(s) | x1 |\n| --- | --- |\n| 0 | ~2.0 |\n</details>"
    DIAGRAM = "<details>\n<summary>flowchart</summary>\n\nThis diagram illustrates the control system.\n</details>"

    def test_blocks_go_and_every_one_is_returned_with_its_chapter_line_title_and_body(self):
        text = "before\n\n![](a.png)\n\n" + self.TABLE + "\n\n(a)\n\n" + self.DIAGRAM + "\n\nFigure 3.8 caption\n"
        new, removed = repair.remove_image_analysis_blocks(text, 3)
        self.assertEqual(new, "before\n\n![](a.png)\n\n(a)\n\nFigure 3.8 caption\n")
        self.assertEqual([(b["chapter"], b["line"], b["title"]) for b in removed], [(3, 5, "line"), (3, 15, "flowchart")])
        self.assertIn("| 0 | ~2.0 |", removed[0]["body"])
        self.assertEqual(removed[1]["body"], "This diagram illustrates the control system.")

    def test_a_chapter_without_blocks_comes_back_byte_identical(self):
        text = "![](a.png)\n\nFigure 1.1 caption\n\n| a | b |\n|---|---|\n"
        self.assertEqual(repair.remove_image_analysis_blocks(text, 1), (text, []))

    def test_the_image_stays_when_its_analysis_goes(self):
        new, _removed = repair.remove_image_analysis_blocks("![](a.png)\n\n" + self.TABLE + "\n", 3)
        self.assertIn("![](a.png)", new)
        self.assertNotIn("<details>", new)


class TestEquationNumbers(unittest.TestCase):
    def test_a_number_left_as_text_becomes_a_tag_and_the_equation_is_untouched(self):
        text = "intro\n\n$$\nx ^ {i} (k + 1) = \\sum_ {j} a _ {j} x ^ {j} (k) - d, (3. 2 5)\n$$\n\nafter\n"
        new, count = repair.normalize_equation_numbers(text)
        self.assertEqual(count, 1)
        self.assertEqual(new, "intro\n\n$$\nx ^ {i} (k + 1) = \\sum_ {j} a _ {j} x ^ {j} (k) - d, \\tag {3.25}\n$$\n\nafter\n")

    def test_an_equation_already_tagged_is_left_alone(self):
        text = "$$\nx = y, \\tag {3.24}\n$$\n"
        self.assertEqual(repair.normalize_equation_numbers(text), (text, 0))

    def test_an_unnumbered_equation_and_a_call_inside_the_math_are_left_alone(self):
        text = "$$\nf(3.5) = x\n$$\n\n$$\ny = g(2)\n$$\n"
        self.assertEqual(repair.normalize_equation_numbers(text), (text, 0))

    def test_the_numbering_is_continuous_after_the_rewrite(self):
        text = "$$\na, \\tag {3.1}\n$$\n\n$$\nb, (3. 2)\n$$\n\n$$\nc, \\tag {3.3}\n$$\n"
        new, _count = repair.normalize_equation_numbers(text)
        self.assertEqual(fidelity.find_equation_issues(3, new), [])
        self.assertEqual([issue.kind for issue in fidelity.find_equation_issues(3, text)], ["equation_number_unformatted"])


class TestFootnotes(unittest.TestCase):
    def test_the_tags_go_and_the_text_stays(self):
        text = 'prose\n\n<small><span class="docvortex-page-footnote" data-block-type="page_footnote" style="x">1. A note with $x$ inside.</span></small>\n'
        new, count = repair.unwrap_footnotes(text, CONFIG)
        self.assertEqual(count, 1)
        self.assertIn("1. A note with $x$ inside.", new)
        self.assertNotIn("<small>", new)

    def test_text_without_footnotes_is_unchanged(self):
        self.assertEqual(repair.unwrap_footnotes("plain\n", CONFIG), ("plain\n", 0))


class TestRestoreHeadings(unittest.TestCase):
    PDF = "## **4.1 Article soumis**\n\n## **4.1.1 Introduction**\n\n" + join(P1, P2) + "\n## **4.1.2 Method**\n\n" + P3 + "\n"

    def restore(self, output):
        return repair.restore_headings(output, self.PDF, CONFIG, FIDELITY)

    def test_lost_headings_are_inserted_before_the_paragraph_that_follows_them_in_the_pdf(self):
        output = join(P1, P2, "#### 4.1.2 Method", P3)
        text, restored, unplaced = self.restore(output)
        self.assertEqual(unplaced, [])
        self.assertEqual([item["number"] for item in restored], ["4.1", "4.1.1"])
        self.assertIn("### 4.1 Article soumis\n\n#### 4.1.1 Introduction\n\n" + P1, text)

    def test_the_level_of_an_existing_heading_of_the_same_depth_is_reused(self):
        output = join(P1, P2, "##### 4.1.2 Method", P3)
        text, _restored, _unplaced = self.restore(output)
        self.assertIn("##### 4.1.1 Introduction", text)

    def test_a_title_that_survives_as_a_plain_line_is_promoted_not_duplicated(self):
        output = join("Introduction", P1, P2, "#### 4.1.2 Method", P3)
        text, restored, _unplaced = self.restore(output)
        self.assertEqual(text.count("Introduction"), 1)
        self.assertTrue(text.startswith("#### 4.1.1 Introduction\n"))
        self.assertEqual([item["method"] for item in restored], ["insert", "promote_plain_line"])

    def test_a_heading_with_no_locatable_paragraph_is_reported_and_nothing_is_written_for_it(self):
        pdf = "## **4.1 Article soumis**\n\n## **4.1.1 Introduction**\n\n" + P1 + "\n"
        output = join("#### 4.1.2 Method", P5)
        text, restored, unplaced = repair.restore_headings(output, pdf, CONFIG, FIDELITY)
        self.assertEqual((text, restored), (output, []))
        self.assertEqual([item["number"] for item in unplaced], ["4.1", "4.1.1"])

    def test_the_nearest_following_paragraph_present_in_the_output_is_the_anchor(self):
        output = join("#### 4.1.2 Method", P3)
        text, restored, unplaced = self.restore(output)
        self.assertEqual(unplaced, [])
        self.assertEqual([item["method"] for item in restored], ["insert", "insert"])
        self.assertIn("#### 4.1.1 Introduction\n\n" + P3, text)

    def test_nothing_is_changed_when_no_numbered_heading_is_missing(self):
        output = join("### 4.1 Article soumis", "#### 4.1.1 Introduction", P1, P2, "#### 4.1.2 Method", P3)
        self.assertEqual(self.restore(output), (output, [], []))

    def test_a_garbled_title_is_flagged_as_suspect(self):
        pdf = "## **4.1.1 R�sum�**\n\n" + P1 + "\n"
        _text, restored, _unplaced = repair.restore_headings(P1 + "\n", pdf, CONFIG, FIDELITY)
        self.assertTrue(restored[0]["title_suspect"])

    def test_without_a_matching_heading_the_depth_plus_offset_level_is_used(self):
        pdf = "## **4.1.1 Introduction**\n\n" + P1 + "\n"
        text, _restored, _unplaced = repair.restore_headings(P1 + "\n", pdf, CONFIG, FIDELITY)
        self.assertTrue(text.startswith("#### 4.1.1 Introduction\n\n"))


class TestRestoreOrder(unittest.TestCase):
    PDF = join(P1, P2, P3, P4, P5, P6, P7, P8)

    def test_a_far_displaced_paragraph_goes_back_to_its_place(self):
        output = join(P8, P1, P2, P3, P4, P5, P6, P7)
        text, moves, skipped = repair.restore_order(output, self.PDF, CONFIG, FIDELITY)
        self.assertEqual(text, self.PDF)
        self.assertEqual((len(moves), skipped), (1, []))
        self.assertTrue(moves[0]["excerpt"].startswith("The regional office"))

    def test_a_small_shift_is_left_alone_and_reported_as_skipped(self):
        output = join(P1, P3, P2, P4, P5, P6, P7, P8)
        text, moves, skipped = repair.restore_order(output, self.PDF, CONFIG, FIDELITY)
        self.assertEqual((text, moves), (output, []))
        self.assertEqual(len(skipped), 1)

    def test_clean_order_is_byte_identical(self):
        self.assertEqual(repair.restore_order(self.PDF, self.PDF, CONFIG, FIDELITY), (self.PDF, [], []))

    def test_two_displaced_paragraphs_keep_their_relative_order(self):
        output = join(P7, P8, P1, P2, P3, P4, P5, P6)
        text, moves, _skipped = repair.restore_order(output, self.PDF, CONFIG, FIDELITY)
        self.assertEqual(text, self.PDF)
        self.assertEqual(len(moves), 2)

    def test_a_formula_block_stays_with_the_paragraph_it_follows(self):
        output = P8 + "\n\n" + P1 + "\n\n$$\ny = 1\n$$\n\n" + join(P2, P3, P4, P5, P6, P7)
        text, _moves, _skipped = repair.restore_order(output, self.PDF, CONFIG, FIDELITY)
        self.assertIn(P1 + "\n\n$$\ny = 1\n$$\n\n" + P2, text)
        self.assertTrue(text.rstrip().endswith(P8))


class TestRepairChapter(unittest.TestCase):
    def test_all_four_defects_are_repaired_and_the_fidelity_errors_drop_to_zero(self):
        pdf = "## **4.1 Article soumis**\n\n## **4.1.1 Introduction**\n\n" + join(P1, P2, P3, P4, P5, P6, P7, P8)
        output = (
            P8
            + f"\n\n![](data:image/jpeg;base64,{JPEG})\n\n"
            + join(P1, P2, P3)
            + '<small><span class="docvortex-page-footnote">1. A footnote.</span></small>\n\n'
            + join(P4, P5, P6, P7)
        )
        before = fidelity.check_chapters({4: ("", pdf)}, {4: ("chapitre4", output)}, FIDELITY)["error_count"]
        text, figures, info = repair.repair_chapter(4, pdf, output, CONFIG, FIDELITY)
        after = fidelity.check_chapters({4: ("", pdf)}, {4: ("chapitre4", text)}, FIDELITY)
        self.assertGreater(before, 0)
        self.assertEqual(after["error_count"], 0, after["totals"])
        self.assertEqual((len(figures), info["footnotes"], len(info["headings"]), len(info["moves"])), (1, 1, 2, 1))

    def test_a_clean_chapter_comes_back_byte_identical_with_an_empty_report(self):
        pdf = "## **4.1 Article soumis**\n\n" + join(P1, P2)
        output = "### 4.1 Article soumis\n\n" + join(P1, P2)
        text, figures, info = repair.repair_chapter(4, pdf, output, CONFIG, FIDELITY)
        self.assertEqual((text, figures), (output, []))
        self.assertEqual((info["headings"], info["moves"], info["footnotes"], info["images"]), ([], [], 0, []))


class TestRepairOutput(unittest.TestCase):
    PDF_TEXT = "## **4.1 Article soumis**\n\n" + join(P1, P2, P3, P4, P5, P6, P7, P8)
    BROKEN = "## CHAPITRE 4\n\n" + join(P8, P1, P2, P3, P4, P5, P6, P7)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)
        (self.out / "content").mkdir()
        (self.out / "content" / "chapitre4.md").write_text(self.BROKEN, encoding="utf-8")
        self.pdf = {4: ("", self.PDF_TEXT)}

    def run_repair(self, apply):
        return repair.repair_output(self.pdf, self.out, CONFIG, FIDELITY, apply=apply)

    def test_a_dry_run_reports_the_effect_and_writes_nothing(self):
        report = self.run_repair(False)
        self.assertEqual(report["files_written"], [])
        self.assertLess(report["errors_after"], report["errors_before"])
        self.assertEqual((self.out / "content" / "chapitre4.md").read_text(encoding="utf-8"), self.BROKEN)
        self.assertFalse((self.out / "pdf2md-backup").exists())

    def test_apply_writes_the_file_backs_up_the_original_and_extracts_figures(self):
        (self.out / "content" / "chapitre4.md").write_text(self.BROKEN + f"\n![](data:image/jpeg;base64,{JPEG})\n", encoding="utf-8")
        report = self.run_repair(True)
        repaired = (self.out / "content" / "chapitre4.md").read_text(encoding="utf-8")
        self.assertIn("### 4.1 Article soumis", repaired)
        self.assertEqual((self.out / "assets" / "figures" / "chapter4_figure1.jpg").read_bytes(), JPEG_BYTES)
        self.assertIn("base64", (self.out / "pdf2md-backup" / "chapitre4.md").read_text(encoding="utf-8"))
        self.assertEqual(len(report["files_written"]), 2)
        self.assertEqual(self.run_repair(False)["errors_after"], 0)

    def test_an_existing_backup_makes_the_run_refuse_and_leaves_everything_untouched(self):
        (self.out / "pdf2md-backup").mkdir()
        (self.out / "pdf2md-backup" / "chapitre4.md").write_text("earlier original", encoding="utf-8")
        with self.assertRaises(repair.RepairRefused):
            self.run_repair(True)
        self.assertEqual((self.out / "content" / "chapitre4.md").read_text(encoding="utf-8"), self.BROKEN)
        self.assertEqual((self.out / "pdf2md-backup" / "chapitre4.md").read_text(encoding="utf-8"), "earlier original")

    def test_an_existing_figure_with_different_content_makes_the_run_refuse_before_any_write(self):
        (self.out / "content" / "chapitre4.md").write_text(self.BROKEN + f"\n![](data:image/jpeg;base64,{JPEG})\n", encoding="utf-8")
        figures = self.out / "assets" / "figures"
        figures.mkdir(parents=True)
        (figures / "chapter4_figure1.jpg").write_bytes(b"someone else's file")
        with self.assertRaises(repair.RepairRefused):
            self.run_repair(True)
        self.assertNotIn("### 4.1", (self.out / "content" / "chapitre4.md").read_text(encoding="utf-8"))
        self.assertFalse((self.out / "pdf2md-backup").exists())

    def test_a_chapter_the_pdf_does_not_have_is_skipped_and_named(self):
        report = repair.repair_output({}, self.out, CONFIG, FIDELITY, apply=True)
        self.assertIn("skipped", report["chapters"]["4"])
        self.assertEqual(report["files_written"], [])

    def test_the_report_renders_one_row_per_chapter(self):
        rendered = repair.render_repair_md(self.run_repair(False))
        self.assertIn("dry run", rendered)
        self.assertIn("| 4 | 0 | 0 | 0 | 0 | 1 | 0 | 1 | 0 |", rendered)


class TestMain(unittest.TestCase):
    def test_a_refusal_exits_2_and_a_clean_dry_run_exits_0(self):
        import io
        from contextlib import redirect_stderr, redirect_stdout

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "content").mkdir()
            (out / "content" / "chapitre4.md").write_text("## CHAPITRE 4\n\n" + join(P1, P2), encoding="utf-8")
            (out / "pdf2md-backup").mkdir()
            (out / "pdf2md-backup" / "x.md").write_text("x", encoding="utf-8")
            with patch.object(repair.validate, "extract_pdf_chapters", lambda *_a, **_k: {4: ("", join(P1, P2))}), redirect_stderr(io.StringIO()) as err, redirect_stdout(io.StringIO()):
                refused = repair._main(["x.pdf", "-o", str(out), "--yes"])
            self.assertEqual(refused, 2)
            self.assertIn("refused", err.getvalue())
            with patch.object(repair.validate, "extract_pdf_chapters", lambda *_a, **_k: {4: ("", join(P1, P2))}), redirect_stdout(io.StringIO()) as stdout:
                ok = repair._main(["x.pdf", "-o", str(out), "--json"])
            self.assertEqual(ok, 0)
            self.assertFalse(json.loads(stdout.getvalue())["applied"])


class TestSingleLayoutIsRefused(unittest.TestCase):
    def test_repair_refuses_a_single_document_directory_before_reading_the_pdf(self):
        import io
        from contextlib import redirect_stderr

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "pdf2md-layout.json").write_text('{"layout": "single"}', encoding="utf-8")
            with redirect_stderr(io.StringIO()) as err:
                code = repair._main(["does-not-exist.pdf", "-o", tmp])
        self.assertEqual(code, 2)
        self.assertIn("single", err.getvalue())


if __name__ == "__main__":
    unittest.main()
