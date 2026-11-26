import json
import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ugs_text import (
    PromptError,
    StepContext,
    fill,
    prompt_section,
    page_blocks,
    select_pages,
    split_body_and_references,
    detect_language,
    load_hints,
    read_pages,
    load_prompts,
    load_schemas,
    load_section_terms,
)
SECTION_TERMS_FILE = Path(__file__).resolve().parent.parent.parent / 'assets' / 'section_terms.json'


class TestUgsText(unittest.TestCase):

    def test_fill_replaces_every_slot(self):
        template = "Hello {{NAME}}, you are {{AGE}}."
        values = {"NAME": "Alice", "AGE": "30"}
        self.assertEqual(fill(template, values), "Hello Alice, you are 30.")

    def test_fill_does_not_expand_a_value_twice(self):
        template = "Value: {{A}}"
        values = {"A": "{{B}}"}
        self.assertEqual(fill(template, values), "Value: {{B}}")

    def test_fill_raises_on_an_unfilled_slot_and_on_an_unknown_value(self):
        with self.assertRaises(PromptError) as ctx1:
            fill("Hello {{NAME}}", {})
        self.assertIn("NAME", str(ctx1.exception))

        with self.assertRaises(PromptError) as ctx2:
            fill("Hello", {"NAME": "Alice"})
        self.assertIn("NAME", str(ctx2.exception))

    def test_prompt_section_returns_one_body(self):
        text = "## Intro\nHello\n## Body\nWorld\n## End\nBye"
        self.assertEqual(prompt_section(text, "Body"), "World")

    def test_prompt_section_missing_raises(self):
        text = "## Intro\nHello"
        with self.assertRaises(PromptError) as ctx:
            prompt_section(text, "Missing")
        self.assertIn("Missing", str(ctx.exception))

    def test_page_blocks_tag_each_page(self):
        pages = ["Page 1 text", "Page 2 text"]
        result = page_blocks(pages, [1, 2])
        self.assertEqual(result, "### Page 1\nPage 1 text\n### Page 2\nPage 2 text")

    def test_all_pages_when_they_fit(self):
        pages = ["# Title\nText 1", "# Title\nText 2"]
        item = {"title": "Title", "criteria": [], "checklist": []}
        count = lambda text: len(text.split())
        result = select_pages(item, pages, 100, count, 3)
        self.assertEqual(result, [1, 2])

    def test_matching_headings_select_pages_when_they_do_not_fit(self):
        pages = [
            "# Introduction\nUnrelated text here",
            "# Methodology\nSpecific methodology details",
            "# Conclusion\nUnrelated text here"
        ]
        item = {"title": "Methodology", "criteria": ["methodology"], "checklist": []}
        count = lambda text: len(text.split())
        result = select_pages(item, pages, 10, count, 3)
        self.assertEqual(result, [2])

    def test_an_item_with_only_a_title_and_its_exact_text_selects_pages_by_the_words_of_the_text(self):
        pages = [
            "# Introduction\nUnrelated text here",
            "# Risques\nSpecific details about the risks",
            "# Conclusion\nUnrelated text here"
        ]
        item = {"id": "I01", "title": "Revue", "max_points": 1,
                "text": "## 1. Revue (/1)\n\nAnalyser et traiter les risques du projet."}
        count = lambda text: len(text.split())
        self.assertEqual(select_pages(item, pages, 10, count, 3), [2])

    def test_the_pages_matching_most_keywords_are_kept_first_when_the_budget_holds_one(self):
        pages = [
            "# Introduction projet\nTexte court",
            "# Analyse des risques du projet\nTexte court",
            "# Conclusion\nTexte court"
        ]
        item = {"id": "I01", "title": "Revue", "max_points": 1,
                "text": "## 1. Revue (/1)\n\nAnalyser les risques du projet, introduction comprise."}
        count = lambda text: len(text.split())
        chosen = select_pages(item, pages, 12, count, 3)  # a page block is 8, 11 and 7 words: only one fits
        self.assertEqual(chosen, [2])
        self.assertNotIn(1, chosen)

    def test_selected_pages_come_back_in_page_order(self):
        pages = ["# Risques\nA", "# Autre\nB", "# Risques projet\nC"]
        item = {"id": "I01", "title": "Risques projet", "max_points": 1, "criteria": [], "checklist": []}
        count = lambda text: len(text.split())
        self.assertEqual(select_pages(item, pages, 100, count, 3), [1, 2, 3])
        # budget for two of the three pages: the two matching ones come back in page order, never best first
        self.assertEqual(select_pages(item, pages, 14, count, 3), [1, 3])

    def test_accented_heading_matches_an_unaccented_word(self):
        pages = [
            "# Introduction\nText",
            "# Méthodologie\nText"
        ]
        item = {"title": "Methodology", "criteria": [], "checklist": []}
        count = lambda text: len(text.split())
        result = select_pages(item, pages, 10, count, 3)
        self.assertEqual(result, [2])

    def test_a_page_over_budget_is_skipped_not_cut(self):
        pages = [
            "# Intro\n" + "word " * 100,
            "# Match\n" + "word " * 5
        ]
        item = {"title": "Match", "criteria": [], "checklist": []}
        count = lambda text: len(text.split())
        result = select_pages(item, pages, 20, count, 3)
        self.assertEqual(result, [2])

    def test_nothing_fits_gives_an_empty_list(self):
        pages = [
            "# Intro\n" + "word " * 100,
            "# Match\n" + "word " * 100
        ]
        item = {"title": "Match", "criteria": [], "checklist": []}
        count = lambda text: len(text.split())
        result = select_pages(item, pages, 10, count, 3)
        self.assertEqual(result, [])

    def test_references_after_a_numbered_heading(self):
        pages = [
            "Body text",
            "7. Références\n[1] Author. Title.",
            "Next section"
        ]
        body, refs = split_body_and_references(pages)
        self.assertEqual(body, "Body text")
        self.assertEqual(refs, [{"page": 2, "text": "[1] Author. Title."}])

    def test_numbered_dot_references_are_entries_and_not_headings(self):
        pages = ["Intro text.\n\n## References\n1. Smith, J. 2020. A paper.\n2. Doe, A. 2021. Another."]
        body, refs = split_body_and_references(pages)
        self.assertEqual(body, "Intro text.")
        self.assertEqual([r["text"] for r in refs], ["1. Smith, J. 2020. A paper.", "2. Doe, A. 2021. Another."])

    def test_a_numbered_section_heading_after_the_list_still_ends_it(self):
        pages = ["Intro.\n\n## References\n1. Smith, J. 2020. A paper.\n\n7. Conclusion\nThe end."]
        _, refs = split_body_and_references(pages)
        self.assertEqual([r["text"] for r in refs], ["1. Smith, J. 2020. A paper."])

    def test_reference_word_in_a_sentence_is_not_a_heading(self):
        pages = [
            "The references are important.",
            "## References\n[1] Author. Title."
        ]
        body, refs = split_body_and_references(pages)
        self.assertEqual(body, "The references are important.")
        self.assertEqual(refs, [{"page": 2, "text": "[1] Author. Title."}])

    def test_entries_with_continuation_lines(self):
        pages = [
            "## References",
            "[1] Author.",
            "    Title.",
            "[2] Other."
        ]
        _, refs = split_body_and_references(pages)
        self.assertEqual(len(refs), 2)
        self.assertEqual(refs[0]["text"], "[1] Author.\n    Title.")
        self.assertEqual(refs[1]["text"], "[2] Other.")

    def test_entries_split_on_blank_lines_without_markers(self):
        pages = [
            "## References",
            "First entry",
            "",
            "Second entry"
        ]
        _, refs = split_body_and_references(pages)
        self.assertEqual(len(refs), 2)
        self.assertEqual(refs[0]["text"], "First entry")
        self.assertEqual(refs[1]["text"], "Second entry")

    def test_no_reference_heading_gives_empty_list(self):
        pages = ["Body text", "More text"]
        body, refs = split_body_and_references(pages)
        self.assertEqual(body, "Body text\nMore text")
        self.assertEqual(refs, [])

    def test_entry_page_is_where_it_starts(self):
        pages = [
            "## References",
            "[1] First",
            "Page 2 content",
            "[2] Second"
        ]
        _, refs = split_body_and_references(pages)
        # Pages are numbered from 1: "[1] First" starts on page 2 and "[2] Second" on page 4.
        self.assertEqual([r["page"] for r in refs], [2, 4])
        self.assertEqual(refs[0]["text"], "[1] First\nPage 2 content")

    def test_a_deeper_heading_does_not_end_the_references(self):
        pages = ["## References\n[1] First.\n### Books\n[2] Second.\n## Appendix\n[3] Not a reference."]
        _, refs = split_body_and_references(pages)
        self.assertEqual([r["text"] for r in refs], ["[1] First.\n### Books", "[2] Second."])

    def test_detect_language_french_and_english_and_tie(self):
        hints = {
            "fr": ["le", "la"],
            "en": ["the", "of"]
        }
        self.assertEqual(detect_language(["le la le"], hints), "fr")
        self.assertEqual(detect_language(["the of the"], hints), "en")
        self.assertEqual(detect_language(["the of the"], hints), "en")

    def test_no_text_layer_is_refused_not_english(self):
        """Pages with no word of either hint list give no decision: the English default is not used (R8)."""
        from ugs_text import LanguageUndecidable
        hints = {"fr": ["le", "la"], "en": ["the", "of"]}
        with self.assertRaises(LanguageUndecidable) as ctx:
            detect_language(["", "   "], hints)
        self.assertIn("text layer", str(ctx.exception))
        self.assertTrue(issubclass(LanguageUndecidable, ValueError))

    def test_tie_is_refused(self):
        """A tie between the French and the English score gives no decision and is refused, not read as English."""
        from ugs_text import LanguageUndecidable
        hints = {"fr": ["le", "la"], "en": ["the", "of"]}
        with self.assertRaises(LanguageUndecidable):
            detect_language(["le the"], hints)

    def test_load_hints_names_a_missing_key(self):
        import json
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            json.dump({"fr": {"value": ["le"]}}, f)
            path = Path(f.name)
        
        with self.assertRaises(PromptError) as ctx:
            load_hints(path)
        self.assertIn("en", str(ctx.exception))
        path.unlink()

    def test_read_pages_in_numeric_order(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            pages_dir = work_dir / "R01" / "pages"
            pages_dir.mkdir(parents=True)
            (pages_dir / "p002.md").write_text("Page 2")
            (pages_dir / "p001.md").write_text("Page 1")
            (pages_dir / "p010.md").write_text("Page 10")
            
            result = read_pages(work_dir, "R01")
            self.assertEqual(result, ["Page 1", "Page 2", "Page 10"])

    def test_load_schemas_names_a_missing_key(self):
        import json
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            json.dump({"existing": {}}, f)
            path = Path(f.name)
        
        with self.assertRaises(PromptError) as ctx:
            load_schemas(path, ["missing_key"])
        self.assertIn("missing_key", str(ctx.exception))
        path.unlink()


class TestSectionTermsAndAppendices(unittest.TestCase):
    """Plan 25 task 2: appendix pages after the references are body pages, and a section term selects its page.
    Every text is fictitious (R34); the terms file is written in a temporary folder (R21)."""

    def count(self, text):
        """Count the words of a text as the token proxy."""
        return len(text.split())

    def test_appendix_pages_after_references_are_body(self):
        pages = ["Intro text.", "## References\n[1] Fictitious Author, 2020.", "## Annexe A\nBilan fictif des heures."]
        body, refs = split_body_and_references(pages)
        self.assertIn("Bilan fictif des heures.", body)
        self.assertEqual([ref["text"] for ref in refs], ["[1] Fictitious Author, 2020."])

    def test_a_section_term_selects_its_page(self):
        long_page = "## Introduction\n" + " ".join(["mot"] * 60)
        pages = [long_page, "## Bilan heures\nFiche fictive."]
        item = {"id": "I07", "title": "Analyse des feuilles de temps", "max_points": 0.5}
        terms = [["feuilles de temps", "bilan des heures", "heures", "timesheet"]]
        self.assertEqual(select_pages(item, pages, 40, self.count, 3, []), [])
        self.assertEqual(select_pages(item, pages, 40, self.count, 3, terms), [2])

    def test_the_section_terms_file_is_read_and_a_missing_key_is_named(self):
        folder = Path(tempfile.mkdtemp())
        good = folder / "terms.json"
        good.write_text(json.dumps({"groups": [["budget", "courbe en S"]]}), encoding="utf-8")
        self.assertEqual(load_section_terms(good), [["budget", "courbe en S"]])
        bad = folder / "broken.json"
        bad.write_text(json.dumps({"other": []}), encoding="utf-8")
        with self.assertRaises(ValueError) as raised:
            load_section_terms(bad)
        self.assertIn("groups", str(raised.exception))
        self.assertTrue(load_section_terms(SECTION_TERMS_FILE))


if __name__ == '__main__':
    unittest.main()
