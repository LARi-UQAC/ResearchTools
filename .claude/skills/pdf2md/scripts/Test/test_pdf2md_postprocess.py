"""Offline tests for pdf2md_postprocess, pinned to the two real splice-defect
shapes measured on a 162-page UQAC thesis conversion, 2026-10-10: a sentence
split by a repeated running header, and a repeated header sitting right
after an equation block (which must NOT be merged into the equation)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pdf2md_postprocess import (
    find_headings,
    find_spurious_headings,
    process_document,
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


class TestProcessDocument(unittest.TestCase):
    def test_end_to_end_on_real_prose_example(self):
        split, removed = process_document("# CHAPITRE 1\n\n" + REAL_PROSE_SPLICE_EXAMPLE)
        self.assertEqual(removed, 1)
        self.assertIn(1, split.chapters)


if __name__ == "__main__":
    unittest.main()
