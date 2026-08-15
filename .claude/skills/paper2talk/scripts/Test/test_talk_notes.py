"""
Offline tests for talk_notes.py: the slide-number placeholder is not a spoken word,
notes are resolved through the relationship parts even when the notesSlide numbering
is shuffled, sections aggregate, and the tolerance decides the exit code.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixtures as fx  # noqa: E402

import talk_notes as tn  # noqa: E402


def words(n):
    return " ".join(f"w{i}" for i in range(n))


class TestNotesExtraction(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_slide_number_placeholder_is_not_counted(self):
        deck = os.path.join(self.dir, "a.pptx")
        fx.build_pptx(deck, [{"body": "", "notes": "one two three"}])
        notes = tn.notes_by_slide(deck)
        self.assertEqual(notes[1], "one two three")
        self.assertEqual(tn.word_count(notes[1]), 3)

    def test_notes_are_mapped_through_the_rels_not_by_number(self):
        # slide 1 points at notesSlide9 and slide 2 at notesSlide4: matching N to N
        # would swap the two, which is the failure this mapping exists to prevent.
        deck = os.path.join(self.dir, "shuffled.pptx")
        fx.build_pptx(deck, [
            {"body": "", "notes": "alpha", "notes_part": 9},
            {"body": "", "notes": "beta", "notes_part": 4},
        ])
        notes = tn.notes_by_slide(deck)
        self.assertEqual(notes[1], "alpha")
        self.assertEqual(notes[2], "beta")

    def test_a_slide_without_notes_reads_empty(self):
        deck = os.path.join(self.dir, "b.pptx")
        fx.build_pptx(deck, [{"body": "", "notes": None}])
        self.assertEqual(tn.notes_by_slide(deck)[1], "")


class TestTiersAndBudget(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.deck = os.path.join(self.dir, "deck.pptx")
        # 1 title (65 words), 2 content (130 each), 1 thanks (65), 1 backup (ignored).
        fx.build_pptx(self.deck, [
            {"body": "", "notes": words(65)},
            {"body": fx.pic_xml(), "notes": words(130)},
            {"body": fx.pic_xml(), "notes": words(130)},
            {"body": "", "notes": words(65)},
            {"body": "", "notes": words(400)},
        ])

    def test_a_deck_on_its_tier_targets_passes(self):
        # 65 + 130 + 130 + 65 = 390 words in the slot, which is exactly 3.0 min at
        # 130 wpm; the backup slide's 400 words are outside it.
        rc = tn.main([self.deck, "--minutes", "3", "--safety-margin", "0",
                      "--title", "1", "--thanks", "4", "--backup", "5", "--json"])
        self.assertEqual(rc, 0)

    def test_backup_words_stay_out_of_the_slot(self):
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            tn.main([self.deck, "--minutes", "4", "--safety-margin", "0",
                     "--title", "1", "--thanks", "4", "--backup", "5", "--json"])
        result = json.loads(buf.getvalue())
        self.assertEqual(result["total_words"], 65 + 130 + 130 + 65)
        self.assertEqual(result["cadence"]["n_content"], 2)
        self.assertEqual(result["cadence"]["n_backup"], 1)

    def test_tiers_can_be_read_from_the_model(self):
        import io
        import contextlib
        model_path = os.path.join(self.dir, "model.json")
        with open(model_path, "w", encoding="utf8") as fh:
            json.dump(fx.model([
                {"n": 1, "kind": "title", "title": "T", "blocks": [], "notes": ""},
                {"n": 2, "kind": "content", "title": "A", "blocks": [], "notes": ""},
                {"n": 3, "kind": "content", "title": "B", "blocks": [], "notes": ""},
                {"n": 4, "kind": "thanks", "title": "Thanks", "blocks": [], "notes": ""},
                {"n": 5, "kind": "backup", "title": "Refs", "blocks": [], "notes": ""},
            ]), fh)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            tn.main([self.deck, "--minutes", "4", "--safety-margin", "0",
                     "--model", model_path, "--json"])
        result = json.loads(buf.getvalue())
        self.assertEqual(result["cadence"]["n_content"], 2)
        self.assertEqual(result["cadence"]["n_title_thanks"], 2)

    def test_section_drift_beyond_tolerance_exits_one(self):
        budget = os.path.join(self.dir, "budget.json")
        with open(budget, "w", encoding="utf8") as fh:
            json.dump({"Introduction": {"slides": [2, 3], "target_words": 100}}, fh)
        rc = tn.main([self.deck, "--minutes", "4", "--safety-margin", "0",
                      "--title", "1", "--thanks", "4", "--backup", "5",
                      "--budget", budget, "--tolerance", "5", "--json"])
        self.assertEqual(rc, 1)

    def test_the_aim_is_below_the_slot_by_default(self):
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            tn.main([self.deck, "--minutes", "13", "--json"])
        result = json.loads(buf.getvalue())
        self.assertAlmostEqual(result["target_minutes"], 11.5, places=6)
        self.assertAlmostEqual(result["target_words"], 11.5 * 130, places=6)


class TestStructuredNotes(unittest.TestCase):
    """The notes template's labels are scaffolding, not words anybody says."""

    def test_labels_do_not_count_towards_the_spoken_budget(self):
        structured = (
            "WHAT TO SAY: the blink interval widens with fatigue\n"
            "KEY POINT: one model is usable\n"
            "TIMING: 60 s\n"
            "TRANSITION: which brings us to the zones\n"
            "ANTICIPATED QUESTIONS: why not EEG?\n"
        )
        plain = ("the blink interval widens with fatigue one model is usable 60 s "
                 "which brings us to the zones why not EEG?")
        self.assertEqual(tn.word_count(structured), tn.word_count(plain))

    def test_the_french_labels_are_stripped_too(self):
        self.assertEqual(tn.word_count("POINT CLE: un seul modele est utilisable"), 5)

    def test_a_colon_inside_a_sentence_is_not_a_label(self):
        self.assertEqual(tn.word_count("the result: it works"), 4)


class TestExhibitCoverage(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def _model(self, keywords):
        return fx.model([
            {"n": 1, "kind": "content", "title": "A",
             "blocks": [{"kind": "figure", "asset": "fig5_evolution.png",
                         "keywords": keywords}],
             "notes": ""},
        ])

    def test_an_exhibit_nobody_mentions_is_reported(self):
        deck = os.path.join(self.dir, "c.pptx")
        fx.build_pptx(deck, [{"body": fx.pic_xml(), "notes": "we move on quickly"}])
        notes = tn.notes_by_slide(deck)
        shown = tn.exhibits_by_slide(deck)
        warnings = tn.coverage_warnings(notes, shown, self._model(["blink", "interval"]))
        self.assertTrue(any("never discussed" in w for w in warnings))

    def test_coverage_matches_a_subject_keyword_not_the_filename(self):
        deck = os.path.join(self.dir, "d.pptx")
        fx.build_pptx(deck, [{"body": fx.pic_xml(),
                              "notes": "the blink interval widens with fatigue"}])
        notes = tn.notes_by_slide(deck)
        shown = tn.exhibits_by_slide(deck)
        warnings = tn.coverage_warnings(notes, shown, self._model(["blink", "interval"]))
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
