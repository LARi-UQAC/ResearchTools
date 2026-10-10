"""Offline tests for pdf2md_postprocess, pinned to the two real splice-defect
shapes measured on a 162-page UQAC thesis conversion, 2026-10-10: a sentence
split by a repeated running header, and a repeated header sitting right
after an equation block (which must NOT be merged into the equation)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pdf2md_postprocess import (
    _load_thresholds,
    _main,
    chapter_filenames,
    find_headings,
    find_spurious_headings,
    process_document,
    render_main_md,
    split_frontmatter_and_chapters,
    strip_splice_headings,
)

# Verbatim shape of the real defect (chapter 1, lines ~330-334 of the real
# these.md produced this session): a sentence broken by a repeated running
# header that duplicates an earlier section heading's text.
REAL_PROSE_SPLICE_EXAMPLE = """\
### 1.1 Contexte et motivation

Cette thèse traite de problèmes. L'étude de revue présentée au

### 1.1. CONTEXTE ET MOTIVATION

Chapitre 2 a montré que la plupart des méthodes existantes."""

# Verbatim shape of the second real defect: a chapter-title running header,
# with a page number fused in ("AVEC 54 PRIORITÉS" instead of "AVEC
# PRIORITÉS"), sitting right after a closed $$ math block.
REAL_MATH_ADJACENT_SPLICE_EXAMPLE = """\
# CHAPITRE 3. OPTIMISATION CONVEXE DISTRIBUÉE AVEC PRIORITÉS VARIABLES

## Proposed update rule

The priority vector w^i in [14] is updated as

$$
w^i(k+1) = w^i(k),\\tag{3.3}
$$

## CHAPITRE 3. OPTIMISATION CONVEXE DISTRIBUÉE AVEC 54 PRIORITÉS VARIABLES

where w^i denotes the priority vector of agent i."""


class TestFindHeadings(unittest.TestCase):
    def test_finds_headings_outside_math(self):
        headings = find_headings(REAL_MATH_ADJACENT_SPLICE_EXAMPLE.splitlines())
        texts = [h.text for h in headings]
        self.assertIn("Proposed update rule", texts)

    def test_does_not_treat_math_fence_hash_as_heading(self):
        # Negative control: a line starting with "#" inside a $$ fence
        # (hypothetical, LaTeX comment-like) must not be read as a heading.
        lines = ["$$", "# not a heading, inside math", "$$"]
        self.assertEqual(find_headings(lines), [])

    def test_chapter_number_extracted_from_start_of_text(self):
        headings = find_headings(REAL_MATH_ADJACENT_SPLICE_EXAMPLE.splitlines())
        chapter_headings = [h for h in headings if h.chapter_number is not None]
        self.assertTrue(all(h.chapter_number == 3 for h in chapter_headings))


class TestFindSpuriousHeadings(unittest.TestCase):
    def test_first_occurrence_of_a_heading_is_never_spurious(self):
        headings = find_headings(REAL_PROSE_SPLICE_EXAMPLE.splitlines())
        spurious = find_spurious_headings(headings)
        first_heading_texts = {h.text for h in headings} - {h.text for h in spurious}
        self.assertIn("1.1 Contexte et motivation", first_heading_texts)

    def test_repeated_heading_is_flagged_spurious(self):
        headings = find_headings(REAL_PROSE_SPLICE_EXAMPLE.splitlines())
        spurious = find_spurious_headings(headings)
        self.assertEqual(len(spurious), 1)
        self.assertEqual(spurious[0].text, "1.1. CONTEXTE ET MOTIVATION")

    def test_repeated_chapter_heading_with_fused_page_number_is_flagged(self):
        # The "54" fused into the title must not prevent the digit-tolerant
        # fuzzy match from recognizing it as a repeat of the real chapter title.
        headings = find_headings(REAL_MATH_ADJACENT_SPLICE_EXAMPLE.splitlines())
        spurious = find_spurious_headings(headings)
        spurious_texts = {h.text for h in spurious}
        self.assertIn("CHAPITRE 3. OPTIMISATION CONVEXE DISTRIBUÉE AVEC 54 PRIORITÉS VARIABLES", spurious_texts)

    def test_two_genuinely_different_headings_are_not_flagged(self):
        # Negative control: distinct section titles must survive.
        lines = ["### 1.1 Contexte", "", "text", "", "### 1.2 Objectifs", "", "more text"]
        headings = find_headings(lines)
        self.assertEqual(find_spurious_headings(headings), [])

    def test_bare_chapter_headings_with_different_numbers_are_never_flagged(self):
        # Regression, measured 2026-10-10 on a real 162-page thesis: once
        # title_leveling cleaned every running header down to a bare
        # "CHAPITRE N" (no title words left), digit-stripping made
        # "CHAPITRE 1".."CHAPITRE 5" all normalize to the identical string
        # "chapitre", so chapters 2-5 were wrongly deleted as repeats of
        # chapter 1 -- the whole rest of the document silently merged into
        # chapitre1.md. This is the exact real shape, verbatim.
        lines = ["## CHAPITRE 1", "", "ch1 body", "", "## CHAPITRE 2", "", "ch2 body",
                 "", "## CHAPITRE 3", "", "ch3 body", "", "## CHAPITRE 4", "",
                 "ch4 body", "", "## CHAPITRE 5", "", "ch5 body"]
        headings = find_headings(lines)
        spurious = find_spurious_headings(headings)
        spurious_chapter_numbers = {h.chapter_number for h in spurious}
        self.assertEqual(spurious_chapter_numbers, set())

    def test_a_genuinely_repeated_chapter_heading_is_still_flagged(self):
        # Positive control for the fix above: the chapter-number gate must
        # not disable detection entirely -- a true repeat of the SAME
        # chapter number (the original splice-defect shape) must still be
        # caught.
        lines = ["## CHAPITRE 1", "", "text", "", "## CHAPITRE 1", "", "more text"]
        headings = find_headings(lines)
        spurious = find_spurious_headings(headings)
        self.assertEqual(len(spurious), 1)
        self.assertEqual(spurious[0].chapter_number, 1)


class TestStripSpliceHeadings(unittest.TestCase):
    def test_prose_splice_is_rejoined_into_one_sentence(self):
        lines = REAL_PROSE_SPLICE_EXAMPLE.splitlines()
        headings = find_headings(lines)
        spurious = find_spurious_headings(headings)
        cleaned, removed = strip_splice_headings(lines, spurious)
        cleaned_text = "\n".join(cleaned)
        self.assertEqual(removed, 1)
        self.assertIn("présentée au Chapitre 2 a montré que", cleaned_text)
        self.assertNotIn("CONTEXTE ET MOTIVATION\n\nChapitre 2", cleaned_text)

    def test_math_adjacent_splice_is_removed_without_corrupting_equation(self):
        lines = REAL_MATH_ADJACENT_SPLICE_EXAMPLE.splitlines()
        headings = find_headings(lines)
        spurious = find_spurious_headings(headings)
        cleaned, removed = strip_splice_headings(lines, spurious)
        cleaned_text = "\n".join(cleaned)
        self.assertEqual(removed, 1)
        # The equation's own closing fence must survive untouched.
        self.assertIn("w^i(k+1) = w^i(k)", cleaned_text)
        self.assertNotIn("$$ where w^i", cleaned_text)
        # And the heading itself must be gone.
        self.assertNotIn("AVEC 54 PRIORITÉS", cleaned_text)

    def test_no_spurious_headings_is_a_no_op(self):
        lines = ["# Real heading", "", "text"]
        cleaned, removed = strip_splice_headings(lines, [])
        self.assertEqual(cleaned, lines)
        self.assertEqual(removed, 0)


class TestSplitFrontmatterAndChapters(unittest.TestCase):
    def setUp(self):
        self.document = (
            "# Thesis title\n\n## Résumé\n\nabstract text\n\n"
            "# CHAPITRE 1\n\n### INTRODUCTION\n\nchapter one body\n\n"
            "# CHAPITRE 2\n\nchapter two body\n\n"
            "## RÉFÉRENCES\n\n[1] Author. Title. Venue, 2020."
        )

    def test_frontmatter_is_everything_before_first_chapter(self):
        lines = self.document.splitlines()
        split = split_frontmatter_and_chapters(lines, find_headings(lines))
        self.assertIn("Résumé", split.frontmatter)
        self.assertNotIn("CHAPITRE 1", split.frontmatter)

    def test_each_chapter_gets_its_own_body(self):
        lines = self.document.splitlines()
        split = split_frontmatter_and_chapters(lines, find_headings(lines))
        self.assertIn(1, split.chapters)
        self.assertIn(2, split.chapters)
        self.assertIn("chapter one body", split.chapters[1][1])
        self.assertIn("chapter two body", split.chapters[2][1])
        self.assertNotIn("chapter two body", split.chapters[1][1])

    def test_bibliography_is_held_out_of_the_last_chapter(self):
        lines = self.document.splitlines()
        split = split_frontmatter_and_chapters(lines, find_headings(lines))
        self.assertIsNotNone(split.bibliography)
        self.assertNotIn("RÉFÉRENCES", split.chapters[2][1])

    def test_no_chapters_found_puts_everything_in_frontmatter(self):
        lines = ["# Just a document", "", "with no chapters"]
        split = split_frontmatter_and_chapters(lines, find_headings(lines))
        self.assertEqual(split.chapters, {})
        self.assertIn("Just a document", split.frontmatter)

    def test_lone_inline_citation_does_not_trigger_bibliography(self):
        # Regression, measured 2026-10-10 on the real thesis: a document
        # with NO actual "RÉFÉRENCES"/"BIBLIOGRAPHIE" heading in its mineru
        # output (common -- the heading can be lost/mangled) falls back to
        # the "[N] ..." line shape, which also matches an ordinary in-text
        # citation like "[40] presented a method..." sitting alone in prose.
        # That single line must NOT be read as the start of the
        # bibliography -- doing so swallowed the rest of a real thesis,
        # chapter 5 included, into a 1.5 MB "bibliography".
        document = (
            "# CHAPITRE 1\n\n"
            "Smith [40] presented a method for this.\n\n"
            "more ordinary prose continues here for a while.\n\n"
            "# CHAPITRE 2\n\nchapter two body, untouched"
        )
        lines = document.splitlines()
        split = split_frontmatter_and_chapters(lines, find_headings(lines))
        self.assertIsNone(split.bibliography)
        self.assertIn("chapter two body, untouched", split.chapters[2][1])

    def test_dense_run_of_numbered_references_is_still_detected(self):
        # Positive control: the density gate must not disable detection of
        # a genuine bibliography with no heading, only a lone inline cite.
        entries = "\n\n".join(f"[{n}] Author {n}. Title {n}. Venue, 2020." for n in range(1, 10))
        document = "# CHAPITRE 1\n\nbody\n\n" + entries
        lines = document.splitlines()
        split = split_frontmatter_and_chapters(lines, find_headings(lines))
        self.assertIsNotNone(split.bibliography)
        self.assertIn("[1] Author 1", split.bibliography)


class TestProcessDocument(unittest.TestCase):
    def test_end_to_end_on_real_prose_example(self):
        split, removed = process_document("# CHAPITRE 1\n\n" + REAL_PROSE_SPLICE_EXAMPLE)
        self.assertEqual(removed, 1)
        self.assertIn(1, split.chapters)


class TestChapterFilenames(unittest.TestCase):
    def test_first_chapter_is_introduction(self):
        names = chapter_filenames([1, 2, 3])
        self.assertEqual(names[1], "Introduction.md")

    def test_last_chapter_is_conclusion(self):
        names = chapter_filenames([1, 2, 3])
        self.assertEqual(names[3], "Conclusion.md")

    def test_middle_chapters_keep_plain_name(self):
        names = chapter_filenames([1, 2, 3, 4, 5])
        self.assertEqual(names[2], "chapitre2.md")
        self.assertEqual(names[3], "chapitre3.md")
        self.assertEqual(names[4], "chapitre4.md")

    def test_works_with_non_contiguous_chapter_numbers(self):
        # Chapter numbers come from whatever CHAPITRE N headings survived --
        # not guaranteed contiguous if one was lost upstream.
        names = chapter_filenames([1, 3, 7])
        self.assertEqual(names[1], "Introduction.md")
        self.assertEqual(names[7], "Conclusion.md")
        self.assertEqual(names[3], "chapitre3.md")

    def test_single_chapter_is_not_special_cased(self):
        # Negative control: with only one chapter there is nothing to
        # distinguish it from, so it must NOT be guessed as either.
        names = chapter_filenames([1])
        self.assertEqual(names[1], "chapitre1.md")

    def test_empty_input_returns_empty(self):
        self.assertEqual(chapter_filenames([]), {})

    def test_exactly_two_chapters_both_get_named(self):
        names = chapter_filenames([1, 2])
        self.assertEqual(names, {1: "Introduction.md", 2: "Conclusion.md"})


class TestRenderMainMd(unittest.TestCase):
    def test_lists_frontmatter_chapters_and_bibliography_in_order(self):
        rendered = render_main_md(
            frontmatter_path="frontmatter.md",
            chapter_paths={1: ("Introduction.md", "CHAPITRE 1"), 2: ("Conclusion.md", "CHAPITRE 2")},
            bibliography_path="bibliography.md",
        )
        self.assertIn("[Front matter](frontmatter.md)", rendered)
        self.assertIn("[Introduction (CHAPITRE 1)](Introduction.md)", rendered)
        self.assertIn("[Conclusion (CHAPITRE 2)](Conclusion.md)", rendered)
        self.assertIn("[Bibliography](bibliography.md)", rendered)
        # Order: frontmatter before chapter 1 before chapter 2 before biblio.
        self.assertLess(rendered.index("frontmatter.md"), rendered.index("Introduction.md"))
        self.assertLess(rendered.index("Introduction.md"), rendered.index("Conclusion.md"))
        self.assertLess(rendered.index("Conclusion.md"), rendered.index("bibliography.md"))

    def test_no_bibliography_line_when_none_found(self):
        rendered = render_main_md(frontmatter_path="frontmatter.md", chapter_paths={}, bibliography_path=None)
        self.assertNotIn("Bibliography", rendered)

    def test_chapter_with_no_title_falls_back_to_a_generic_label(self):
        rendered = render_main_md(frontmatter_path="frontmatter.md", chapter_paths={2: ("chapitre2.md", "")}, bibliography_path=None)
        self.assertIn("[Chapitre 2](chapitre2.md)", rendered)

    def test_introduction_and_conclusion_filenames_get_a_clarifying_label(self):
        # The link target alone (Introduction.md) doesn't say so in the
        # label text unless rendered deliberately -- this is what makes
        # main.md readable as a table of contents rather than a bare file
        # list.
        rendered = render_main_md(
            frontmatter_path="frontmatter.md",
            chapter_paths={1: ("Introduction.md", "CHAPITRE 1"), 5: ("Conclusion.md", "CHAPITRE 5")},
            bibliography_path=None,
        )
        self.assertIn("[Introduction (CHAPITRE 1)](Introduction.md)", rendered)
        self.assertIn("[Conclusion (CHAPITRE 5)](Conclusion.md)", rendered)


class TestMainWritesBibliography(unittest.TestCase):
    def test_output_files_land_under_a_src_subfolder(self):
        # thesis-auditor.md:98 looks for "src/main.tex" when given a
        # directory -- pdf2md's own output must nest the same way
        # (main.md replacing main.tex) so an --output-dir handed to pdf2md
        # can be handed to thesis-auditor unchanged.
        import tempfile
        from pathlib import Path

        document = "# CHAPITRE 1\n\nbody\n\n# CHAPITRE 2\n\nmore body"
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "these.md"
            source.write_text(document, encoding="utf-8")
            out_dir = Path(tmp) / "project"
            _main([str(source), "-o", str(out_dir)])
            self.assertTrue((out_dir / "src" / "main.md").exists())
            self.assertTrue((out_dir / "src" / "Introduction.md").exists())
            self.assertTrue((out_dir / "src" / "Conclusion.md").exists())
            self.assertFalse((out_dir / "main.md").exists())

    def test_bibliography_md_is_actually_written_when_found(self):
        # Regression: _main computed split.bibliography and reported
        # bibliography_found=True but never wrote it to any file,
        # silently discarding the references stage 6 depends on.
        import tempfile
        from pathlib import Path

        document = (
            "# CHAPITRE 1\n\nchapter body\n\n"
            "## RÉFÉRENCES\n\n[1] Author. Title. Venue, 2020."
        )
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "these.md"
            source.write_text(document, encoding="utf-8")
            out_dir = Path(tmp) / "out"
            exit_code = _main([str(source), "-o", str(out_dir)])
            self.assertEqual(exit_code, 0)
            bib_path = out_dir / "src" / "bibliography.md"
            self.assertTrue(bib_path.exists())
            self.assertIn("[1] Author", bib_path.read_text(encoding="utf-8"))

    def test_no_bibliography_path_in_report_when_none_found(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "these.md"
            source.write_text("# CHAPITRE 1\n\nno bibliography here", encoding="utf-8")
            out_dir = Path(tmp) / "out"
            _main([str(source), "-o", str(out_dir)])
            self.assertFalse((out_dir / "src" / "bibliography.md").exists())
            self.assertFalse((out_dir / "bibliography.md").exists())


class TestLoadThresholds(unittest.TestCase):
    """R0/R3: the heuristic thresholds come from a config file beside the
    module, not a code literal, and a broken config is an explicit error."""

    def test_shipped_config_loads_all_three_keys(self):
        values = _load_thresholds()
        self.assertEqual(set(values), {
            "fuzzy_match_ratio", "bibliography_density_window", "bibliography_density_min_matches",
        })
        self.assertAlmostEqual(values["fuzzy_match_ratio"], 0.85)
        self.assertEqual(values["bibliography_density_window"], 30)
        self.assertEqual(values["bibliography_density_min_matches"], 5)

    def test_missing_file_is_refused_not_defaulted(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does-not-exist.json"
            with self.assertRaises(FileNotFoundError):
                _load_thresholds(missing)

    def test_missing_key_is_named_not_silently_defaulted(self):
        import json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            incomplete = Path(tmp) / "incomplete.json"
            incomplete.write_text(
                json.dumps({"fuzzy_match_ratio": {"value": 0.9, "provenance": "x"}}), encoding="utf-8"
            )
            with self.assertRaises(KeyError) as ctx:
                _load_thresholds(incomplete)
            self.assertIn("bibliography_density_window", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
