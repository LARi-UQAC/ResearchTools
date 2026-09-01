"""
Offline tests for talk_model.py: every block kind survives the model, a renderer
raises on a block it cannot draw instead of dropping it, and the budget the model
computes is the same one talk_notes.py measures on the built deck.
"""
import io
import json
import contextlib
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixtures as fx  # noqa: E402

import talk_model as tm  # noqa: E402
import talk_notes as tn  # noqa: E402

BLOCK_SAMPLES = {
    "bullets": {"kind": "bullets", "items": ["a", "b"]},
    "figure": {"kind": "figure", "asset": "f.png", "keywords": ["blink"]},
    "takeaway": {"kind": "takeaway", "text": "it works"},
    "cards": {"kind": "cards", "items": [{"title": "A", "text": "x"}]},
    "chips": {"kind": "chips", "items": [{"label": "low", "color": "2E7D32"}]},
    "stats": {"kind": "stats", "items": [{"value": "95.2 %", "label": "accuracy"}]},
    "table": {"kind": "table", "rows": [["h1", "h2"], ["a", "b"]], "keywords": ["h1"]},
    "matrix": {"kind": "matrix", "rows": [[0.9, 0.1], [0.2, 0.8]], "keywords": ["matrix"]},
    "zoneband": {"kind": "zoneband", "zones": [{"fraction": 0.5, "label": "safe"}],
                 "keywords": ["zone"]},
    "chart": {"kind": "chart", "series": [{"name": "s", "points": [[0, 0], [1, 1]]}],
              "keywords": ["curve"]},
    "equation": {"kind": "equation", "tex": "y = ax + b", "keywords": ["slope"]},
}


class TestBlockVocabulary(unittest.TestCase):
    def test_every_declared_kind_has_a_sample_and_round_trips(self):
        self.assertEqual(set(BLOCK_SAMPLES), set(tm.BLOCK_KINDS))
        for kind, block in BLOCK_SAMPLES.items():
            model = fx.model([{"n": 1, "kind": "content", "title": "T",
                               "blocks": [block, BLOCK_SAMPLES["figure"]],
                               "notes": "blink slope h1 matrix zone curve"}])
            reloaded = json.loads(json.dumps(model))
            self.assertEqual(reloaded["slides"][0]["blocks"][0]["kind"], kind)
            problems = tm.validate_model(reloaded)
            self.assertEqual(problems, [], f"{kind}: {problems}")

    def test_a_block_missing_a_required_field_is_reported(self):
        model = fx.model([{"n": 1, "kind": "content", "title": "T",
                           "blocks": [{"kind": "figure", "keywords": ["x"]}],
                           "notes": "x"}])
        self.assertTrue(any("missing 'asset'" in p for p in tm.validate_model(model)))

    def test_an_unknown_block_kind_is_reported(self):
        model = fx.model([{"n": 1, "kind": "content", "title": "T",
                           "blocks": [{"kind": "carousel"}], "notes": ""}])
        self.assertTrue(any("unknown block kind" in p for p in tm.validate_model(model)))

    def test_exhibit_classification(self):
        for kind in ("figure", "table", "chart", "matrix", "zoneband", "equation"):
            self.assertIn(kind, tm.EXHIBIT_KINDS)
        for kind in ("bullets", "cards", "chips", "stats", "takeaway"):
            self.assertNotIn(kind, tm.EXHIBIT_KINDS)


class TestRendererContract(unittest.TestCase):
    def test_a_renderer_raises_rather_than_dropping_a_block(self):
        model = fx.model([{"n": 1, "kind": "content", "title": "T",
                           "blocks": [BLOCK_SAMPLES["zoneband"]], "notes": "zone"}])
        with self.assertRaises(tm.RendererGap) as ctx:
            tm.assert_renderable(model, {"bullets", "figure"}, "toy_renderer")
        self.assertIn("zoneband", str(ctx.exception))
        self.assertIn("toy_renderer", str(ctx.exception))

    def test_a_template_declares_what_it_implements(self):
        assets = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "assets",
        )
        for name in ("beamer_skeleton.tex.j2", "web_skeleton.html.j2"):
            declared = tm.supported_blocks(os.path.join(assets, name))
            self.assertEqual(declared, set(tm.BLOCK_KINDS), name)


class TestBudgetAgreement(unittest.TestCase):
    def test_the_model_budget_matches_what_talk_notes_measures(self):
        notes = {1: " ".join(f"w{i}" for i in range(65)),
                 2: " ".join(f"w{i}" for i in range(130)),
                 3: " ".join(f"w{i}" for i in range(43)),
                 4: " ".join(f"w{i}" for i in range(300))}
        model = fx.model([
            {"n": 1, "kind": "title", "title": "T", "blocks": [], "notes": notes[1]},
            {"n": 2, "kind": "content", "title": "A",
             "blocks": [BLOCK_SAMPLES["figure"]], "notes": notes[2] + " blink"},
            {"n": 3, "kind": "divider", "title": "Method", "blocks": [],
             "notes": notes[3]},
            {"n": 4, "kind": "backup", "title": "Refs", "blocks": [], "notes": notes[4]},
        ])
        tmpdir = tempfile.mkdtemp()
        model_path = os.path.join(tmpdir, "model.json")
        with open(model_path, "w", encoding="utf8") as fh:
            json.dump(model, fh)

        deck = os.path.join(tmpdir, "deck.pptx")
        fx.build_pptx(deck, [
            {"body": "", "notes": model["slides"][0]["notes"]},
            {"body": fx.pic_xml(), "notes": model["slides"][1]["notes"]},
            {"body": "", "notes": model["slides"][2]["notes"]},
            {"body": "", "notes": model["slides"][3]["notes"]},
        ])

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            tn.main([deck, "--minutes", "13", "--model", model_path, "--json"])
        measured = json.loads(buf.getvalue())
        computed = tm.model_totals(model)

        self.assertEqual(computed["total_words"], measured["total_words"])
        self.assertAlmostEqual(computed["total_minutes"], measured["total_minutes"],
                               places=6)
        self.assertEqual(computed["n_content"], measured["cadence"]["n_content"])


class TestNumberIntegrity(unittest.TestCase):
    """No number reaches a slide unless the paper states it."""

    SOURCE = ["95.2", "32", "941", "1950", "0.84"]

    def _model(self, title, blocks=None):
        return fx.model([
            {"n": 3, "kind": "content", "title": title,
             "blocks": blocks or [BLOCK_SAMPLES["figure"]],
             "notes": "blink"},
        ])

    def test_a_number_from_the_paper_passes(self):
        model = self._model("Six models reach 95.2 % on 32 algorithms")
        self.assertEqual(tm.check_numbers(model, self.SOURCE), [])

    def test_a_number_that_is_in_no_source_sentence_is_flagged(self):
        model = self._model("Six models reach 98.7 % accuracy")
        problems = tm.check_numbers(model, self.SOURCE)
        self.assertTrue(any("98.7" in p for p in problems))

    def test_a_decimal_comma_in_the_source_still_matches(self):
        model = self._model("The interval reaches 95.2 %")
        self.assertEqual(tm.check_numbers(model, ["95,2"]), [])

    def test_a_thousands_space_in_the_source_still_matches(self):
        model = self._model("Budget of 1950 words")
        self.assertEqual(tm.check_numbers(model, ["1 950"]), [])

    def test_small_integers_are_not_treated_as_claims(self):
        # Slide numbers, "three states", "2 x 2" - not evidence, not flagged.
        model = self._model("Three zones, two thresholds")
        self.assertEqual(tm.check_numbers(model, self.SOURCE), [])

    def test_numbers_inside_blocks_are_checked_too(self):
        model = self._model("Results", [
            {"kind": "table", "rows": [["Model", "Accuracy"], ["SVM", "77.4 %"]],
             "keywords": ["accuracy"]},
        ])
        problems = tm.check_numbers(model, self.SOURCE)
        self.assertTrue(any("77.4" in p for p in problems))


if __name__ == "__main__":
    unittest.main(verbosity=2)
