import sys
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
)


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
        self.assertEqual(detect_language(["le the"], hints), "en")

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


if __name__ == '__main__':
    unittest.main()
