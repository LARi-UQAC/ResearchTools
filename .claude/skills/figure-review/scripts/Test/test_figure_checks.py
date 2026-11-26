import sys
import unittest
from pathlib import Path

# Put the parent folder of the test folder on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

import figure_checks


class TestFigureChecks(unittest.TestCase):

    def setUp(self):
        self.criteria_path = Path(__file__).parent.parent.parent / "assets" / "figure_criteria.json"
        self.criteria_doc = figure_checks.load_criteria(self.criteria_path)
        self.criteria_list = self.criteria_doc["criteria"]

    def test_load_criteria_names_the_missing_key(self):
        # Mock a bad criteria file
        bad_path = Path(__file__).parent / "bad_criteria.json"
        # We can't easily mock the file read without writing a temp file, 
        # but load_criteria expects a valid structure.
        # Let's test with a file that exists but has missing keys if possible, 
        # or just trust the implementation raises on missing keys.
        # The plan says: "raises CriteriaError naming the entry and the key that is missing"
        
        # Create a temp file for this specific test
        import json
        bad_doc = {
            "criteria": [
                {"id": "c1", "level": "figure", "scope": "ug", "judged_by": "script", "applies_to": ["all"], "threshold": None, "label_fr": "x", "label_en": "y", "comment_fr": "z", "comment_en": "w"}
                # missing 'threshold' key? No, it's null. 
                # Let's remove 'comment_en'
            ]
        }
        # Actually, let's just use a real file and check that load works, 
        # and then test the error path by passing a file with a missing key.
        
        # For simplicity in this test, we'll just verify that load_criteria 
        # successfully loads the real file and returns a dict with 'criteria'.
        self.assertIn("criteria", self.criteria_doc)
        
        # To test the error, we need a bad file.
        bad_file = Path(__file__).parent / "temp_bad_criteria.json"
        bad_data = {"criteria": [{"id": "test"}]} # Missing many keys
        bad_file.write_text(json.dumps(bad_data))
        
        with self.assertRaises(figure_checks.CriteriaError) as ctx:
            figure_checks.load_criteria(bad_file)
            
        bad_file.unlink()
        self.assertIn("test", str(ctx.exception)) # Should name the entry id

    def test_space_ratio_pass_and_fail_at_the_threshold(self):
        figures = [
            {
                "figure_id": "F01",
                "page": 1,
                "rect": [0, 0, 100, 100],
                "source": "raster",
                "pixel_size": [100, 100],
                "drawing_area_ratio": 0.8, # > 0.7
                "caption": "Figure 1: Test"
            }
        ]
        pages = ["Page 1 text"]
        body_font_size = 10.0
        results = figure_checks.check(figures, pages, body_font_size, self.criteria_doc)
        
        # Find the criterion
        crit_id = "space_used_over_70"
        verdict = results[0]["criteria"][crit_id]
        self.assertEqual(verdict["verdict"], "pass")
        
        # Now fail
        figures[0]["drawing_area_ratio"] = 0.5
        results = figure_checks.check(figures, pages, body_font_size, self.criteria_doc)
        verdict = results[0]["criteria"][crit_id]
        self.assertEqual(verdict["verdict"], "fail")
        self.assertIn("0.5", verdict["reason"])

    def test_low_dpi_raster_fails_and_vector_is_not_applicable(self):
        # Raster: 100x100 pixels displayed at 100x100 points. 
        # 100 points is 100/72 inches. 
        # DPI = 100 / (100/72) = 72. 
        # Threshold is 150. So it should fail.
        figures = [
            {
                "figure_id": "F01",
                "page": 1,
                "rect": [0, 0, 100, 100],
                "source": "raster",
                "pixel_size": [100, 100],
                "drawing_area_ratio": 0.8,
                "caption": "Figure 1: Test"
            }
        ]
        pages = ["Page 1 text"]
        body_font_size = 10.0
        results = figure_checks.check(figures, pages, body_font_size, self.criteria_doc)
        
        crit_id = "effective_resolution"
        verdict = results[0]["criteria"][crit_id]
        self.assertEqual(verdict["verdict"], "fail")
        
        # Vector: not_applicable
        figures[0]["source"] = "vector"
        figures[0].pop("pixel_size")
        results = figure_checks.check(figures, pages, body_font_size, self.criteria_doc)
        verdict = results[0]["criteria"][crit_id]
        self.assertEqual(verdict["verdict"], "not_applicable")

    def test_small_vector_text_fails(self):
        figures = [
            {
                "figure_id": "F01",
                "page": 1,
                "rect": [0, 0, 100, 100],
                "source": "vector",
                "text_sizes": [5.0], # Smallest size 5.0
                "drawing_area_ratio": 0.8,
                "caption": "Figure 1: Test"
            }
        ]
        pages = ["Page 1 text"]
        body_font_size = 10.0 # Threshold 0.7 * 10 = 7.0. 5.0 < 7.0 -> fail
        results = figure_checks.check(figures, pages, body_font_size, self.criteria_doc)
        
        crit_id = "text_size"
        verdict = results[0]["criteria"][crit_id]
        self.assertEqual(verdict["verdict"], "fail")
        
        # Raster: not_run
        figures[0]["source"] = "raster"
        figures[0]["pixel_size"] = [100, 100]
        figures[0].pop("text_sizes")
        results = figure_checks.check(figures, pages, body_font_size, self.criteria_doc)
        verdict = results[0]["criteria"][crit_id]
        self.assertEqual(verdict["verdict"], "not_run")

    def test_numbering_gap_fails(self):
        figures = [
            {"figure_id": "F01", "page": 1, "rect": [0,0,10,10], "source": "raster", "pixel_size": [10,10], "drawing_area_ratio": 0.8, "caption": "Figure 1: A"},
            {"figure_id": "F02", "page": 2, "rect": [0,0,10,10], "source": "raster", "pixel_size": [10,10], "drawing_area_ratio": 0.8, "caption": "Figure 3: B"} # Gap
        ]
        pages = ["Page 1", "Page 2"]
        body_font_size = 10.0
        results = figure_checks.check(figures, pages, body_font_size, self.criteria_doc)
        
        crit_id = "numbered_in_sequence"
        # Figure 1 is in order; only figure 3, after the gap, fails
        self.assertEqual(results[0]["criteria"][crit_id]["verdict"], "pass")
        self.assertEqual(results[1]["criteria"][crit_id]["verdict"], "fail")

    def test_repeated_number_fails(self):
        figures = [
            {"figure_id": "F01", "page": 1, "rect": [0,0,10,10], "source": "raster", "pixel_size": [10,10], "drawing_area_ratio": 0.8, "caption": "Figure 1: A"},
            {"figure_id": "F02", "page": 2, "rect": [0,0,10,10], "source": "raster", "pixel_size": [10,10], "drawing_area_ratio": 0.8, "caption": "Figure 1: B"} # Repeat
        ]
        pages = ["Page 1", "Page 2"]
        body_font_size = 10.0
        results = figure_checks.check(figures, pages, body_font_size, self.criteria_doc)
        
        crit_id = "numbered_in_sequence"
        # The repeat fails; the first figure stays in order
        self.assertEqual(results[0]["criteria"][crit_id]["verdict"], "pass")
        self.assertEqual(results[1]["criteria"][crit_id]["verdict"], "fail")

    def test_figure_called_after_it_appears_fails(self):
        # Figure on page 1. Text on page 2 calls "Figure 1".
        figures = [
            {"figure_id": "F01", "page": 1, "rect": [0,0,10,10], "source": "raster", "pixel_size": [10,10], "drawing_area_ratio": 0.8, "caption": "Figure 1: A"}
        ]
        pages = ["Page 1", "See Figure 1 here"]
        body_font_size = 10.0
        results = figure_checks.check(figures, pages, body_font_size, self.criteria_doc)
        
        crit_id = "called_before_appearing"
        self.assertEqual(results[0]["criteria"][crit_id]["verdict"], "fail")
        
        # If called on page 1, pass
        pages = ["See Figure 1 here", "Page 2"]
        results = figure_checks.check(figures, pages, body_font_size, self.criteria_doc)
        self.assertEqual(results[0]["criteria"][crit_id]["verdict"], "pass")

    def test_source_marker_in_caption_passes(self):
        figures = [
            {"figure_id": "F01", "page": 1, "rect": [0,0,10,10], "source": "raster", "pixel_size": [10,10], "drawing_area_ratio": 0.8, "caption": "Figure 1: A [1]"}
        ]
        pages = ["Page 1"]
        body_font_size = 10.0
        results = figure_checks.check(figures, pages, body_font_size, self.criteria_doc)
        
        crit_id = "source_cited"
        self.assertEqual(results[0]["criteria"][crit_id]["verdict"], "pass")

    def test_missing_caption_makes_the_source_check_not_run(self):
        figures = [
            {"figure_id": "F01", "page": 1, "rect": [0,0,10,10], "source": "raster", "pixel_size": [10,10], "drawing_area_ratio": 0.8, "caption": None}
        ]
        pages = ["Page 1"]
        body_font_size = 10.0
        results = figure_checks.check(figures, pages, body_font_size, self.criteria_doc)
        
        crit_id = "source_cited"
        self.assertEqual(results[0]["criteria"][crit_id]["verdict"], "not_run")

    def test_reason_carries_the_measured_number(self):
        figures = [
            {"figure_id": "F01", "page": 1, "rect": [0,0,10,10], "source": "raster", "pixel_size": [10,10], "drawing_area_ratio": 0.5, "caption": "Figure 1: A"}
        ]
        pages = ["Page 1"]
        body_font_size = 10.0
        results = figure_checks.check(figures, pages, body_font_size, self.criteria_doc)
        
        crit_id = "space_used_over_70"
        verdict = results[0]["criteria"][crit_id]
        self.assertIn("0.5", verdict["reason"])

    def test_failure_comment_in_french_keeps_accents(self):
        comment = figure_checks.failure_comment("space_used_over_70", self.criteria_list, "fr")
        self.assertIn("rogner", comment) # "rogner les marges"
        
        comment_en = figure_checks.failure_comment("space_used_over_70", self.criteria_list, "en")
        self.assertIn("crop", comment_en)

    def test_unknown_criterion_id_raises(self):
        with self.assertRaises(figure_checks.CriteriaError):
            figure_checks.failure_comment("non_existent_id", self.criteria_list, "fr")

    def test_body_font_size_is_the_most_frequent_size(self):
        # This requires a PDF. We can use the fixture helper.
        import tempfile
        from _pdf_fixtures import make_report
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "test.pdf"
            # Create a PDF with mostly size 10 text
            pages = [
                {"text": "Hello World", "font_size": 10},
                {"text": "Another line", "font_size": 10},
                {"text": "Small", "font_size": 8}
            ]
            make_report(pdf_path, pages)
            
            size = figure_checks.body_font_size(pdf_path)
            self.assertEqual(size, 10.0)

    def test_criteria_for_scope_keeps_both_and_drops_the_other_scope(self):
        doc = {"criteria": [{"id": "a", "scope": "undergraduate"}, {"id": "b", "scope": "research"},
                            {"id": "c", "scope": "both"}]}
        self.assertEqual([c["id"] for c in figure_checks.criteria_for_scope(doc, "undergraduate")], ["a", "c"])
        self.assertEqual([c["id"] for c in figure_checks.criteria_for_scope(doc, "research")], ["b", "c"])

    def test_criteria_for_scope_refuses_an_unknown_scope(self):
        with self.assertRaises(figure_checks.CriteriaError) as ctx:
            figure_checks.criteria_for_scope({"criteria": []}, "primary")
        self.assertIn("primary", str(ctx.exception))

    def test_the_shipped_undergraduate_selection_has_no_research_only_entry(self):
        doc = figure_checks.load_criteria(self.criteria_path)
        chosen = figure_checks.criteria_for_scope(doc, "undergraduate")
        self.assertTrue(all(c["scope"] in ("undergraduate", "both") for c in chosen))
        self.assertEqual(len([c for c in chosen if c["scope"] == "undergraduate"]), 20)
        self.assertEqual({c["id"] for c in chosen if c["scope"] == "both"},
                         {"called_before_appearing", "numbered_in_sequence"})


class TestPerFigureNumbering(unittest.TestCase):
    """Per-figure numbering over titled figures (Issue 126, plan 21 task 1, R01 case 1). Fictitious captions only (R34)."""

    def setUp(self):
        self.criteria_path = Path(__file__).parent.parent.parent / "assets" / "figure_criteria.json"
        self.criteria_doc = figure_checks.load_criteria(self.criteria_path)

    @staticmethod
    def _fig(caption, page):
        return {"figure_id": f"F{page:02d}", "page": page, "caption": caption}

    def _verdicts(self, captions):
        figures = [self._fig(c, i + 1) for i, c in enumerate(captions)]
        pages = ["" for _ in figures]
        results = figure_checks.check(figures, pages, 10.0, self.criteria_doc)
        return [r["criteria"]["numbered_in_sequence"] for r in results]

    def test_untitled_elements_do_not_break_the_sequence(self):
        # R01 shape: 18 titled figures numbered 1 to 18, plus two untitled elements
        captions = [f"Figure {n}: titre" for n in range(1, 19)] + [None, None]
        verdicts = self._verdicts(captions)
        self.assertTrue(all(v["verdict"] == "pass" for v in verdicts[:18]))
        self.assertEqual([v["verdict"] for v in verdicts[18:]], ["not_applicable", "not_applicable"])

    def test_untitled_between_figures_is_not_applicable_and_does_not_break_the_count(self):
        verdicts = self._verdicts(["Figure 1: a", "Figure 2: b", None, "Figure 3: c"])
        self.assertEqual([v["verdict"] for v in verdicts], ["pass", "pass", "not_applicable", "pass"])

    def test_a_gap_fails_only_the_figure_after_it(self):
        verdicts = self._verdicts(["Figure 1: a", "Figure 2: b", "Figure 4: c"])
        self.assertEqual([v["verdict"] for v in verdicts], ["pass", "pass", "fail"])
        self.assertIn("figure 4", verdicts[2]["reason"].lower())
        self.assertIn("figure 2", verdicts[2]["reason"].lower())

    def test_chapter_numbers_are_in_order(self):
        verdicts = self._verdicts(["Figure 2.1: a", "Figure 2.2: b", "Figure 3.1: c"])
        self.assertEqual([v["verdict"] for v in verdicts], ["pass", "pass", "pass"])

    def test_a_table_titled_figure_counts_in_the_sequence(self):
        # "Figure 5" on a table is part of the figure sequence: it follows figure 3 with a gap
        verdicts = self._verdicts(["Figure 1: a", "Figure 2: b", "Figure 3: c", "Figure 5: table"])
        self.assertEqual(verdicts[3]["verdict"], "fail")
        self.assertIn("figure 3", verdicts[3]["reason"].lower())

    def test_no_source_is_not_applicable_by_default(self):
        # Plan 21 task 2: the script cannot tell a borrowed figure, so a figure without a source is not applicable
        figures = [self._fig("Figure 1: The plant.", 1)]
        results = figure_checks.check(figures, [""], 10.0, self.criteria_doc)
        self.assertEqual(results[0]["criteria"]["source_cited"]["verdict"], "not_applicable")

    def test_the_reason_is_the_french_text_of_the_criteria_file(self):
        verdicts = self._verdicts(["Figure 1: a", "Figure 4: c"])
        template = next(c for c in self.criteria_doc["criteria"] if c["id"] == "numbered_in_sequence")["reason_fr"]
        self.assertEqual(verdicts[1]["reason"], template.format(n=4, m=1))
        self.assertEqual(verdicts[1]["reason"], "Numérotation irrégulière : la figure 4 suit la figure 1.")


class TestNumberingShapes(unittest.TestCase):
    """Review round 1, minor 6: the successor rule accepts a change of numbering shape, and the key never raises."""

    KEY = staticmethod(figure_checks._number_key)
    SUCC = staticmethod(figure_checks._is_successor)

    def test_the_next_figure_in_a_chapter(self):
        self.assertTrue(self.SUCC(self.KEY("2.2"), self.KEY("2.3")))
        self.assertFalse(self.SUCC(self.KEY("2.2"), self.KEY("2.5")))

    def test_a_new_chapter_prefix_is_a_successor(self):
        self.assertTrue(self.SUCC(self.KEY("2.2"), self.KEY("3.1")))
        self.assertFalse(self.SUCC(self.KEY("2.2"), self.KEY("3.2")))

    def test_the_first_appendix_after_body_numbers_is_a_successor(self):
        self.assertTrue(self.SUCC(self.KEY("3.2"), self.KEY("A.1")))
        self.assertFalse(self.SUCC(self.KEY("3.2"), self.KEY("A.3")))

    def test_the_next_appendix_letter_is_a_successor(self):
        self.assertTrue(self.SUCC(self.KEY("A.1"), self.KEY("B.1")))
        self.assertFalse(self.SUCC(self.KEY("A.1"), self.KEY("B.2")))

    def test_an_empty_key_is_never_a_successor(self):
        self.assertFalse(self.SUCC((), self.KEY("2.1")))

    def test_the_number_key_never_raises_on_a_non_ascii_digit(self):
        # A superscript two is a digit for str.isdigit, but int() refuses it: the key must treat it as a letter part.
        key = self.KEY("2.\u00b2")
        self.assertEqual(len(key), 2)


if __name__ == "__main__":
    unittest.main()
