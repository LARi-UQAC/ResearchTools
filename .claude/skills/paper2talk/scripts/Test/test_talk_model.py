"""
Offline tests for talk_model.py: every block kind survives the model, a renderer
raises on a block it cannot draw instead of dropping it, and the budget the model
computes is the same one talk_notes.py measures on the built deck.
"""
import base64
import io
import json
import contextlib
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixtures as fx  # noqa: E402

import talk_model as tm  # noqa: E402
import talk_notes as tn  # noqa: E402
import talk_rules as rules  # noqa: E402

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


    def test_the_budgets_agree_on_a_deck_with_an_outline(self):
        # An outline costs what a divider costs, in both places that count it.
        notes = {1: " ".join(f"w{i}" for i in range(65)),
                 2: " ".join(f"w{i}" for i in range(43)),
                 3: " ".join(f"w{i}" for i in range(130))}
        model = fx.model([
            {"n": 1, "kind": "title", "title": "T", "blocks": [], "notes": notes[1]},
            {"n": 2, "kind": "outline", "title": "Outline", "blocks": [], "notes": notes[2]},
            {"n": 3, "kind": "content", "title": "A", "section": "Method",
             "blocks": [BLOCK_SAMPLES["figure"]], "notes": notes[3] + " blink"},
        ])
        tmpdir = tempfile.mkdtemp()
        model_path = os.path.join(tmpdir, "model.json")
        with open(model_path, "w", encoding="utf8") as fh:
            json.dump(model, fh)
        deck = os.path.join(tmpdir, "deck.pptx")
        fx.build_pptx(deck, [
            {"body": "", "notes": notes[1]},
            {"body": "", "notes": notes[2]},
            {"body": fx.pic_xml(), "notes": model["slides"][2]["notes"]},
        ])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            tn.main([deck, "--minutes", "13", "--model", model_path, "--json"])
        measured = json.loads(buf.getvalue())
        computed = tm.model_totals(model)
        self.assertEqual(computed["n_content"], 1)
        self.assertEqual(measured["cadence"]["n_content"], 1)
        self.assertEqual(measured["cadence"]["n_divider"], 1)
        self.assertEqual(computed["counts"]["divider"], 1)


class TestOutlineKind(unittest.TestCase):
    """outline is its own kind to draw and a divider to time; 1/3 min lives in one place."""

    def _slides(self, *sections):
        slides = [{"n": 1, "kind": "outline", "title": "Outline", "blocks": [],
                   "notes": "the plan"}]
        for i, section in enumerate(sections, start=2):
            slides.append({"n": i, "kind": "content", "title": f"S{i}", "section": section,
                           "blocks": [BLOCK_SAMPLES["figure"]], "notes": "blink"})
        return slides

    def test_outline_is_its_own_kind_and_a_divider_tier(self):
        slide = {"n": 1, "kind": "outline"}
        self.assertEqual(tm.slide_kind(slide), "outline")
        self.assertEqual(tm.slide_tier(slide), "divider")

    def test_the_divider_cost_is_not_duplicated(self):
        self.assertEqual(rules.KIND_TIER, {"outline": "divider"})
        self.assertNotIn("outline", rules.TIER_MINUTES)
        self.assertEqual(set(rules.KINDS), set(rules.TIERS) | {"outline"})
        self.assertEqual(rules.tier_words(rules.tier_of("outline")),
                         rules.tier_words("divider"))

    def test_an_outline_slide_is_budgeted_as_a_divider(self):
        rows = tm.budget_rows(fx.model([
            {"n": 1, "kind": "outline", "title": "O", "blocks": [], "notes": "x"},
            {"n": 2, "kind": "divider", "title": "D", "blocks": [], "notes": "x"},
        ]))
        self.assertEqual(rows[0]["tier"], "divider")
        self.assertEqual(rows[0]["target_words"], rows[1]["target_words"])

    def test_tier_of_an_unknown_kind_raises(self):
        with self.assertRaises(ValueError):
            rules.tier_of("poster")

    def test_an_unknown_kind_is_still_reported_by_validate_model(self):
        problems = tm.validate_model(fx.model([
            {"n": 1, "kind": "poster", "title": "P", "blocks": [], "notes": ""}]))
        self.assertTrue(any("poster" in p for p in problems))

    def test_outline_sections_are_distinct_and_in_order(self):
        model = fx.model(self._slides("Intro", "Method", "Intro", "Results"))
        self.assertEqual(tm.outline_sections(model), ["Intro", "Method", "Results"])

    def test_backup_sections_are_not_listed_by_the_outline(self):
        # R35 round 3: backup slides sit outside the talk slot (the budget excludes
        # them), so their section is never presented and must not be promised.
        slides = self._slides("Intro", "Results")
        slides.append({"n": 9, "kind": "backup", "section": "Appendix", "title": "B",
                       "blocks": [], "notes": ""})
        self.assertEqual(tm.outline_sections(fx.model(slides)), ["Intro", "Results"])

    def test_chrome_slides_do_not_list_their_own_section(self):
        # R35 round 4: an outline tagged section "Outline" listed itself, and alone it
        # satisfied the "a slide declares a section" check.
        slides = self._slides("Intro", "Results")
        slides[0]["section"] = "Outline"
        slides.insert(0, {"n": 0, "kind": "title", "section": "Opening", "title": "T",
                          "blocks": [], "notes": ""})
        slides.append({"n": 8, "kind": "thanks", "section": "Closing", "title": "Q",
                       "blocks": [], "notes": ""})
        self.assertEqual(tm.outline_sections(fx.model(slides)), ["Intro", "Results"])
        alone = self._slides()
        alone[0]["section"] = "Outline"
        problems = tm.validate_model(fx.model(alone))
        self.assertTrue(any("outline" in p and "section" in p for p in problems), problems)
        # R35 round 13: the refusal names the rule, or the author edits the wrong slide.
        self.assertTrue(any("no content or divider slide declares a section" in p
                            for p in problems), problems)

    def test_a_divider_section_is_listed(self):
        # Negative control: a divider opens a section of the talk and stays listed.
        slides = self._slides("Intro")
        slides.append({"n": 5, "kind": "divider", "section": "Method", "title": "Method",
                       "blocks": [], "notes": ""})
        self.assertEqual(tm.outline_sections(fx.model(slides)), ["Intro", "Method"])

    def test_an_outline_with_no_section_to_list_is_reported(self):
        problems = tm.validate_model(fx.model(self._slides()))
        # Not the unknown-kind message: the problem is that there is nothing to list.
        self.assertTrue(any("outline" in p and "slide 1" in p and "section" in p
                            for p in problems), problems)
        self.assertFalse(any("declares kind" in p for p in problems), problems)

    def test_a_template_lacking_outline_in_its_kinds_raises(self):
        base = tempfile.mkdtemp()
        template = os.path.join(base, "no_outline.html.j2")
        with open(template, "w", encoding="utf8") as fh:
            fh.write("{# supported-blocks: figure #}\n"
                     "{# supported-kinds: title content divider thanks backup #}\nX\n")
        with self.assertRaises(tm.RendererGap) as ctx:
            tm.render_template(fx.model(self._slides("Intro")), template,
                               os.path.join(base, "out.tex"))
        self.assertIn("outline", str(ctx.exception))

    def test_a_template_that_does_not_declare_kinds_accepts_outline(self):
        # Negative control: undeclared kinds mean every known kind, like blocks.
        base = tempfile.mkdtemp()
        template = os.path.join(base, "plain.html.j2")
        with open(template, "w", encoding="utf8") as fh:
            fh.write("{# supported-blocks: figure #}\nX\n")
        tm.render_template(fx.model(self._slides("Intro")), template,
                           os.path.join(base, "out.tex"))

    def test_the_beamer_template_declares_every_kind(self):
        declared = tm.template_requirements(BEAMER_TEMPLATE)["supported-kinds"]
        self.assertEqual(declared, set(rules.KINDS))

    def test_the_beamer_outline_lists_the_sections_in_order(self):
        base = tempfile.mkdtemp()
        out = os.path.join(base, "main.tex")
        tm.render_template(fx.model(self._slides("Intro", "Method", "Intro")),
                           BEAMER_TEMPLATE, out)
        with open(out, encoding="utf8") as fh:
            tex = fh.read()
        self.assertNotIn(r"\tableofcontents", tex)
        first, second = tex.find(r"\item Intro"), tex.find(r"\item Method")
        self.assertTrue(0 <= first < second, "sections missing or out of order")
        self.assertEqual(tex.count(r"\item Intro"), 1)

    def test_a_beamer_outline_draws_its_own_blocks_after_the_sections(self):
        # R35 round 2: the web and PowerPoint outlines draw the slide's blocks, the
        # Beamer outline frame dropped them while assert_renderable stayed silent.
        slides = self._slides("Intro", "Method")
        slides[0]["blocks"] = [{"kind": "takeaway", "text": "Fictitious plan claim"}]
        base = tempfile.mkdtemp()
        out = os.path.join(base, "main.tex")
        tm.render_template(fx.model(slides), BEAMER_TEMPLATE, out)
        with open(out, encoding="utf8") as fh:
            tex = fh.read()
        frame = tex[tex.find(r"\item Intro"):]
        frame = frame[:frame.find(r"\end{frame}")]
        self.assertIn("Fictitious plan claim", frame)
        self.assertLess(frame.find(r"\item Method"), frame.find("Fictitious plan claim"))

    def test_a_beamer_outline_with_no_sections_renders_no_empty_list(self):
        # An empty itemize is a LaTeX error, so nothing is emitted rather than a list.
        base = tempfile.mkdtemp()
        out = os.path.join(base, "main.tex")
        tm.render_template(fx.model(self._slides()), BEAMER_TEMPLATE, out)
        with open(out, encoding="utf8") as fh:
            tex = fh.read()
        self.assertIn("Outline", tex)
        self.assertNotRegex(tex, r"\\begin\{itemize\}\s*\\end\{itemize\}")


class TestTemplateContext(unittest.TestCase):
    """The web template is handed its pacing and interaction values; it invents none."""

    PROBE = ("{# supported-blocks: bullets figure #}\n"
             "PACING={{ pacing | tojson }}\nSWIPE={{ web.swipe_threshold_px }}\n")

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.template = os.path.join(self.base, "probe.html.j2")
        with open(self.template, "w", encoding="utf8") as fh:
            fh.write(self.PROBE)
        # .txt: default Jinja delimiters (a .tex output switches them) and no figure
        # embedding (only an .html output embeds), so the probe reads the raw context.
        self.out = os.path.join(self.base, "out.txt")

    def _slides(self, order=(1, 2, 3)):
        words = {1: 65, 2: 130, 3: 43}
        kinds = {1: "title", 2: "content", 3: "divider"}
        return [{"n": n, "kind": kinds[n], "title": f"S{n}",
                 "blocks": [BLOCK_SAMPLES["figure"]] if kinds[n] == "content" else [],
                 "notes": " ".join(f"w{i}" for i in range(words[n]))} for n in order]

    def _render(self, model, **kw):
        tm.render_template(model, self.template, self.out, **kw)
        with open(self.out, encoding="utf8") as fh:
            lines = dict(line.split("=", 1) for line in fh.read().splitlines() if "=" in line)
        return json.loads(lines["PACING"]), lines["SWIPE"]

    def test_the_operator_values_are_recorded(self):
        self.assertEqual(rules.WEB_INTERACTION["swipe_threshold_px"], 40)
        self.assertEqual(rules.FOOTER_FIELD_MAX_CHARS, 48)

    def test_pacing_equals_the_budget_seconds_of_each_slide(self):
        model = fx.model(self._slides())
        pacing, _ = self._render(model)
        expected = [row["seconds"] for row in tm.budget_rows(model)]
        self.assertEqual(len(pacing), 3)
        for got, want in zip(pacing, expected):
            self.assertAlmostEqual(got, want, places=6)

    def test_pacing_follows_the_order_the_slides_are_rendered_in(self):
        # budget_rows sorts by number; the template iterates the model's own order.
        model = fx.model(self._slides(order=(2, 1, 3)))
        pacing, _ = self._render(model)
        by_n = {row["slide"]: row["seconds"] for row in tm.budget_rows(model)}
        for got, n in zip(pacing, (2, 1, 3)):
            self.assertAlmostEqual(got, by_n[n], places=6)

    def test_pacing_follows_the_delivery_rate(self):
        model = fx.model(self._slides())
        slow, _ = self._render(model, wpm=65.0)
        normal, _ = self._render(model)
        self.assertAlmostEqual(slow[1], 2 * normal[1], places=6)

    def test_a_backup_slide_adds_nothing_to_the_pacing(self):
        # R35 round 7: backup slides sit outside the slot, but their notes' seconds were
        # added to the deck's planned time, so a presenter in the Q&A read "ahead".
        slides = self._slides() + [{"n": 4, "kind": "backup", "title": "B", "blocks": [],
                                    "notes": " ".join(f"w{i}" for i in range(150))}]
        pacing, _ = self._render(fx.model(slides))
        expected = [row["seconds"] for row in tm.budget_rows(fx.model(self._slides()))]
        self.assertEqual(len(pacing), 4)
        self.assertEqual(pacing[3], 0)
        for got, want in zip(pacing[:3], expected):
            self.assertAlmostEqual(got, want, places=6)

    def test_web_carries_the_swipe_threshold(self):
        _, swipe = self._render(fx.model(self._slides()))
        self.assertEqual(swipe, "40")

    def test_the_rendered_value_comes_from_talk_rules(self):
        # Proves the template is not holding its own copy of the number.
        with mock.patch.dict(rules.WEB_INTERACTION, {"swipe_threshold_px": 77}):
            _, swipe = self._render(fx.model(self._slides()))
        self.assertEqual(swipe, "77")


class TestFooterFields(unittest.TestCase):
    """A footer field too long for its box is reported, not clipped (a Beamer defect)."""

    LONG_TITLE = "A deliberately long fictitious title that cannot fit its footer box"
    LONG_AUTHORS = ["Wick, J.", "Doe, A.", "Roe, B.", "Poe, C.", "Moe, D.", "Zoe, E."]

    def _model(self, **meta):
        # Bullets, not a figure: an .html render embeds figures, and this suite is about
        # the footer, not about a figure file on disk.
        return fx.model([{"n": 1, "kind": "content", "title": "S1",
                          "blocks": [{"kind": "bullets", "items": ["a"]}], "notes": "blink"}],
                        **meta)

    def _problems(self, **meta):
        return [p for p in tm.footer_problems(self._model(**meta)) if "footer" in p]

    def _main(self, model, *argv):
        base = tempfile.mkdtemp()
        path = os.path.join(base, "talk_model.json")
        with open(path, "w", encoding="utf8") as fh:
            json.dump(model, fh)
        template = os.path.join(base, "plain.html.j2")
        with open(template, "w", encoding="utf8") as fh:
            fh.write("{# supported-blocks: bullets figure #}\nTITLE={{ meta.title }}\n")
        argv = [a.replace("{template}", template).replace("{base}", base) for a in argv]
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            tm.main([path, *argv])
        return [line for line in out.getvalue().splitlines() if "footer" in line]

    def test_validation_alone_does_not_report_a_web_footer(self):
        # R35 round 1: the cap guards the web footer, which alone reads short_title.
        # Reported by validate_model, it failed every Beamer and PowerPoint model with a
        # long title and named a remedy those targets never read.
        model = self._model(title=self.LONG_TITLE, authors=self.LONG_AUTHORS)
        self.assertEqual([p for p in tm.validate_model(model) if "footer" in p], [])
        self.assertEqual(self._main(model), [])
        self.assertEqual(self._main(model, "--render", "{template}",
                                    "--out", os.path.join("{base}", "deck.txt")), [])

    def test_a_web_render_with_json_prints_parseable_json(self):
        # R35 round 15 (R17): the footer check now runs only on an .html render, so its
        # one machine-readable form is --render ... --json, and the "rendered" line printed
        # before the JSON on stdout made that output unparseable.
        base = tempfile.mkdtemp()
        path = os.path.join(base, "talk_model.json")
        with open(path, "w", encoding="utf8") as fh:
            json.dump(self._model(title=self.LONG_TITLE), fh)
        template = os.path.join(base, "plain.html.j2")
        with open(template, "w", encoding="utf8") as fh:
            fh.write("{# supported-blocks: bullets figure #}\nTITLE={{ meta.title }}\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            tm.main([path, "--render", template, "--out", os.path.join(base, "d.html"), "--json"])
        report = json.loads(out.getvalue())
        self.assertTrue(any("short_title" in p for p in report["problems"]), report["problems"])

    def test_a_web_render_reports_the_long_footer_field(self):
        model = self._model(title=self.LONG_TITLE)
        lines = self._main(model, "--render", "{template}",
                           "--out", os.path.join("{base}", "deck.html"))
        self.assertTrue(any("short_title" in line for line in lines), lines)

    def test_the_fixture_fields_are_over_the_cap(self):
        self.assertGreater(len(self.LONG_TITLE), rules.FOOTER_FIELD_MAX_CHARS)
        self.assertGreater(len(", ".join(self.LONG_AUTHORS)), rules.FOOTER_FIELD_MAX_CHARS)

    def test_a_long_title_without_a_short_form_is_reported(self):
        problems = self._problems(title=self.LONG_TITLE)
        self.assertTrue(any("short_title" in p for p in problems), problems)

    def test_the_same_title_with_a_short_form_is_not(self):
        self.assertEqual(self._problems(title=self.LONG_TITLE, short_title="Short title"), [])

    def test_a_short_form_that_is_itself_too_long_is_reported(self):
        problems = self._problems(title=self.LONG_TITLE, short_title=self.LONG_TITLE)
        self.assertTrue(any("short_title" in p for p in problems), problems)

    def test_long_authors_without_a_short_form_are_reported(self):
        problems = self._problems(authors=self.LONG_AUTHORS)
        self.assertTrue(any("short_author" in p for p in problems), problems)

    def test_the_same_authors_with_a_short_form_are_not(self):
        self.assertEqual(self._problems(authors=self.LONG_AUTHORS, short_author="Wick et al."),
                         [])

    def test_fields_within_the_cap_are_not_reported(self):
        # Negative control: the default fixture title and author are short.
        self.assertEqual(self._problems(), [])


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


# Leading bytes of each accepted image type. The bodies after them are filler: the
# signature is what embed_asset reads, and a real decoder never runs here.
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 32
GIF_BYTES = b"GIF89a" + b"\x00" * 32
SVG_BYTES = b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg"></svg>'
SVG_BARE_BYTES = b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'
HTML_BYTES = b"<!doctype html><html><body>not an image</body></html>"

ASSETS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets")
WEB_TEMPLATE = os.path.join(ASSETS_DIR, "web_skeleton.html.j2")
BEAMER_TEMPLATE = os.path.join(ASSETS_DIR, "beamer_skeleton.tex.j2")


class TestAssetEmbedding(unittest.TestCase):
    """A web deck carries its figures inside the file; a path survives only off the web."""

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.root = os.path.join(self.base, "deck")
        os.makedirs(os.path.join(self.root, "figures"))
        self._write(os.path.join(self.root, "figures", "fig1.png"), PNG_BYTES)
        # A real file OUTSIDE the root, so a refusal proves containment and not absence.
        self.outside = os.path.join(self.base, "outside.png")
        self._write(self.outside, PNG_BYTES)
        self.cap = 1024
        # The web template requires the lab images (plan2 Task 6); a generated stand-in
        # folder lets these figure tests reach the figure code they are about.
        self.lab = os.path.join(self.base, "gabarit_slides")
        os.makedirs(self.lab)
        self._write(os.path.join(self.lab, rules.LAB_ASSET_FILES["banner"]), JPEG_BYTES)
        self._write(os.path.join(self.lab, rules.LAB_ASSET_FILES["logo"]), PNG_BYTES)

    @staticmethod
    def _write(path, data):
        with open(path, "wb") as fh:
            fh.write(data)

    def _figure_model(self):
        return fx.model([{"n": 1, "kind": "content", "title": "A figure",
                          "blocks": [{"kind": "figure", "asset": "figures/fig1.png",
                                      "caption": "Fig. 1", "keywords": ["probe"]}],
                          "notes": "the probe figure"}])

    def test_the_operator_cap_is_ten_mebibytes(self):
        self.assertEqual(rules.WEB_ASSET_MAX_BYTES, 10 * 1024 * 1024)

    def test_a_png_becomes_a_data_uri(self):
        uri = tm.embed_asset("figures/fig1.png", self.root, self.cap)
        self.assertTrue(uri.startswith("data:image/png;base64,"))
        self.assertEqual(base64.b64decode(uri.split(",", 1)[1]), PNG_BYTES)

    def test_jpeg_gif_and_svg_are_recognised(self):
        cases = {"a.jpg": (JPEG_BYTES, "image/jpeg"), "a.gif": (GIF_BYTES, "image/gif"),
                 "a.svg": (SVG_BYTES, "image/svg+xml"),
                 "b.svg": (SVG_BARE_BYTES, "image/svg+xml")}
        for name, (data, mime) in cases.items():
            with self.subTest(name=name):
                self._write(os.path.join(self.root, name), data)
                uri = tm.embed_asset(name, self.root, self.cap)
                self.assertTrue(uri.startswith(f"data:{mime};base64,"), uri[:40])

    def test_an_svg_with_a_doctype_or_comment_prologue_is_recognised(self):
        # R35 round 1: matplotlib and draw.io write a DOCTYPE before <svg>, Inkscape a
        # comment; both were refused as "not a recognised image".
        prologues = {
            "doctype.svg": (b'<?xml version="1.0" encoding="utf-8" standalone="no"?>\n'
                            b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN"\n'
                            b'  "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">\n'),
            "comment.svg": (b'<?xml version="1.0"?>\n'
                            b'<!-- Created with a fictitious editor -->\n'),
            "subset.svg": b'<!DOCTYPE svg [ <!ENTITY probe "x"> ]>\n<!-- a > b -->\n',
        }
        for name, prologue in prologues.items():
            with self.subTest(name=name):
                self._write(os.path.join(self.root, name), prologue + SVG_BARE_BYTES)
                uri = tm.embed_asset(name, self.root, self.cap)
                self.assertTrue(uri.startswith("data:image/svg+xml;base64,"), uri[:40])

    def test_a_prologue_followed_by_another_root_is_still_refused(self):
        # Negative control: skipping the prologue must not admit an HTML page.
        for name, data in (("page.svg", b"<!DOCTYPE html>\n<html></html>"),
                           ("note.svg", b"<!-- svg -->\n<html></html>"),
                           ("open.svg", b"<!-- never closed <svg></svg>")):
            with self.subTest(name=name):
                self._write(os.path.join(self.root, name), data)
                with self.assertRaises(tm.AssetError):
                    tm.embed_asset(name, self.root, self.cap)

    def test_an_asset_that_is_not_a_path_is_refused(self):
        # R35 round 7: a list, mapping or number as "asset" raised TypeError out of
        # os.path.join, an uncaught traceback, instead of the named refusal (exit 2).
        for asset in (["figures/fig1.png"], {"path": "figures/fig1.png"}, 5, None):
            with self.subTest(asset=asset):
                with self.assertRaises(tm.AssetError) as ctx:
                    tm.embed_asset(asset, self.root, self.cap)
                self.assertIn("path", str(ctx.exception))

    def test_a_missing_file_is_refused_by_name(self):
        with self.assertRaises(tm.AssetError) as ctx:
            tm.embed_asset("figures/absent.png", self.root, self.cap)
        self.assertIn("figures/absent.png", str(ctx.exception))

    def test_a_path_leaving_the_root_is_refused(self):
        # The file exists in both cases: the refusal must come from containment (R24).
        for path in ("../outside.png", self.outside):
            with self.subTest(path=path):
                with self.assertRaises(tm.AssetError) as ctx:
                    tm.embed_asset(path, self.root, self.cap)
                self.assertIn("outside", str(ctx.exception))

    def test_a_drive_relative_path_is_refused(self):
        # On Windows "C:x.png" means the current folder of drive C, not the root.
        with self.assertRaises(tm.AssetError):
            tm.embed_asset("C:outside.png", self.root, self.cap)

    def test_a_png_whose_bytes_are_html_is_refused(self):
        self._write(os.path.join(self.root, "figures", "fake.png"), HTML_BYTES)
        with self.assertRaises(tm.AssetError) as ctx:
            tm.embed_asset("figures/fake.png", self.root, self.cap)
        self.assertIn("figures/fake.png", str(ctx.exception))

    def test_a_file_over_the_cap_is_refused(self):
        self._write(os.path.join(self.root, "figures", "big.png"),
                    PNG_BYTES + b"\x00" * (self.cap + 1))
        with self.assertRaises(tm.AssetError) as ctx:
            tm.embed_asset("figures/big.png", self.root, self.cap)
        self.assertIn("figures/big.png", str(ctx.exception))

    def test_a_web_render_embeds_every_figure_and_passes_the_offline_check(self):
        import talk_validate as tv
        model = self._figure_model()
        out = os.path.join(self.base, "deck.html")
        tm.render_template(model, WEB_TEMPLATE, out, model_dir=self.root, lab_dir=self.lab)
        with open(out, encoding="utf8") as fh:
            html = fh.read()
        self.assertIn('src="data:image/png;base64,', html)
        self.assertNotIn("figures/fig1.png", html)
        self.assertEqual(tv.check_web(out), [])
        # The caller's model is not rewritten behind its back.
        self.assertNotIn("data_uri", model["slides"][0]["blocks"][0])

    def test_a_web_render_with_figures_and_no_model_dir_is_refused(self):
        with self.assertRaises(tm.AssetError) as ctx:
            tm.render_template(self._figure_model(), WEB_TEMPLATE,
                               os.path.join(self.base, "deck.html"), lab_dir=self.lab)
        self.assertIn("model's folder", str(ctx.exception))

    def test_a_beamer_render_keeps_the_plain_asset_path(self):
        # Negative control: LaTeX resolves the file itself, so nothing is embedded.
        out = os.path.join(self.base, "main.tex")
        tm.render_template(self._figure_model(), BEAMER_TEMPLATE, out, model_dir=self.root)
        with open(out, encoding="utf8") as fh:
            tex = fh.read()
        self.assertIn("figures/fig1.png", tex)
        self.assertNotIn("data:image", tex)

    def test_a_web_figure_without_an_asset_is_refused_cleanly(self):
        # validate_model already reports it; the render must refuse, not raise KeyError.
        model = self._figure_model()
        del model["slides"][0]["blocks"][0]["asset"]
        with self.assertRaises(tm.AssetError) as ctx:
            tm.render_template(model, WEB_TEMPLATE, os.path.join(self.base, "deck.html"),
                               model_dir=self.root, lab_dir=self.lab)
        self.assertIn("slide 1", str(ctx.exception))

    def test_the_cli_refuses_a_figure_without_an_asset_with_exit_2(self):
        model = self._figure_model()
        del model["slides"][0]["blocks"][0]["asset"]
        path = os.path.join(self.root, "talk_model.json")
        with open(path, "w", encoding="utf8") as fh:
            json.dump(model, fh)
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = tm.main([path, "--render", WEB_TEMPLATE, "--lab-dir", self.lab,
                            "--out", os.path.join(self.base, "deck.html")])
        self.assertEqual(code, 2)
        self.assertIn("no 'asset'", err.getvalue())

    def test_the_cli_refuses_a_missing_figure_with_exit_2(self):
        model = self._figure_model()
        model["slides"][0]["blocks"][0]["asset"] = "figures/absent.png"
        path = os.path.join(self.root, "talk_model.json")
        with open(path, "w", encoding="utf8") as fh:
            json.dump(model, fh)
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = tm.main([path, "--render", WEB_TEMPLATE, "--lab-dir", self.lab,
                            "--out", os.path.join(self.base, "deck.html")])
        self.assertEqual(code, 2)
        self.assertIn("figures/absent.png", err.getvalue())


# A template that needs the lab images declares it in its header, the same way it
# declares its blocks. These small templates stand in for the real ones, which do
# not declare it yet (plan2 Task 6).
LAB_TEMPLATE = ("{# supported-blocks: bullets #}\n"
                "{# requires: lab-assets #}\n"
                "BANNER={{ lab.banner }}\nLOGO={{ lab.logo }}\n")
PLAIN_TEMPLATE = "{# supported-blocks: bullets #}\nTITLE={{ meta.title }}\n"


class TestLabAssets(unittest.TestCase):
    """The lab images come from the gabarit folder named at render time, never a copy."""

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.lab = os.path.join(self.base, "gabarit_slides")
        os.makedirs(self.lab)
        self.banner = os.path.join(self.lab, rules.LAB_ASSET_FILES["banner"])
        self.logo = os.path.join(self.lab, rules.LAB_ASSET_FILES["logo"])
        for path, data in ((self.banner, JPEG_BYTES), (self.logo, PNG_BYTES)):
            with open(path, "wb") as fh:
                fh.write(data)
        self.lab_template = self._template("lab_skeleton.html.j2", LAB_TEMPLATE)
        self.plain_template = self._template("plain_skeleton.html.j2", PLAIN_TEMPLATE)
        self.model = fx.model([{"n": 1, "kind": "content", "title": "T",
                                "blocks": [{"kind": "bullets", "items": ["a"]}],
                                "notes": "a"}], title="Probe deck")
        self.model_path = os.path.join(self.base, "talk_model.json")
        with open(self.model_path, "w", encoding="utf8") as fh:
            json.dump(self.model, fh)
        self.out = os.path.join(self.base, "deck.html")

    def _template(self, name, text):
        path = os.path.join(self.base, name)
        with open(path, "w", encoding="utf8") as fh:
            fh.write(text)
        return path

    def _main(self, *extra):
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = tm.main([self.model_path, "--render", self.lab_template,
                            "--out", self.out, *extra])
        return code, err.getvalue()

    def test_the_canonical_filenames_are_the_operator_approved_ones(self):
        self.assertEqual(rules.LAB_ASSET_FILES,
                         {"banner": "en-tete1260.jpg", "logo": "LogoLARI_FINAL.png"})

    def test_the_header_declares_blocks_kinds_and_requirements(self):
        path = self._template("full.html.j2",
                              "{# supported-blocks: bullets figure #}\n"
                              "{# supported-kinds: title content #}\n"
                              "{# requires: lab-assets #}\n<html></html>\n")
        reqs = tm.template_requirements(path)
        self.assertEqual(reqs["supported-blocks"], {"bullets", "figure"})
        self.assertEqual(reqs["supported-kinds"], {"title", "content"})
        self.assertEqual(reqs["requires"], {"lab-assets"})

    def test_a_header_with_whitespace_control_is_read_the_same(self):
        # R35 round 1: "{#- requires: lab-assets -#}" parsed as key "- requires" and the
        # requirement vanished, so no --lab-dir was demanded.
        for opener, closer in (("{#-", "-#}"), ("((#-", "-#))")):
            with self.subTest(opener=opener):
                path = self._template("ws.html.j2",
                                      f"{opener} supported-kinds: title content {closer}\n"
                                      f"{opener} requires: lab-assets {closer}\n<html></html>\n")
                reqs = tm.template_requirements(path)
                self.assertEqual(reqs["supported-kinds"], {"title", "content"})
                self.assertEqual(reqs["requires"], {"lab-assets"})

    def test_a_blank_line_inside_the_header_drops_nothing(self):
        # R35 round 9: reading stopped at the first blank line, so a declaration below
        # it vanished in silence and the check failed open (every kind accepted, no lab).
        path = self._template("gap.html.j2",
                              "{# supported-blocks: bullets #}\n\n"
                              "{# supported-kinds: title content #}\n   \n"
                              "{# requires: lab-assets #}\n<html></html>\n"
                              "{# not-a-header: ignored #}\n")
        reqs = tm.template_requirements(path)
        self.assertEqual(reqs["supported-kinds"], {"title", "content"})
        self.assertEqual(reqs["requires"], {"lab-assets"})

    def test_a_byte_order_mark_hides_no_declaration(self):
        # R35 round 10: a template saved with a UTF-8 BOM (as some Windows editors do)
        # declared nothing, so every kind was accepted and --lab-dir was not demanded.
        path = os.path.join(self.base, "bom.html.j2")
        with open(path, "w", encoding="utf-8-sig") as fh:
            fh.write("{# supported-kinds: title content #}\n{# requires: lab-assets #}\n<html>\n")
        reqs = tm.template_requirements(path)
        self.assertEqual(reqs["supported-kinds"], {"title", "content"})
        self.assertEqual(reqs["requires"], {"lab-assets"})

    def test_a_key_declared_on_two_lines_keeps_both(self):
        # R35 round 10: a repeated key replaced the first line, so a requirement or a
        # wrapped block list silently lost its first half.
        path = self._template("twice.html.j2",
                              "{# supported-blocks: bullets figure #}\n"
                              "{# supported-blocks: table #}\n"
                              "{# requires: lab-assets #}\n{# requires: other #}\n<html>\n")
        reqs = tm.template_requirements(path)
        self.assertEqual(reqs["supported-blocks"], {"bullets", "figure", "table"})
        self.assertEqual(reqs["requires"], {"lab-assets", "other"})

    def test_a_refusal_carries_the_tag_once(self):
        # R35 round 10: the asset and lab refusals already start with the tag, and main
        # added it again: "[MODEL] [MODEL] ... requires the lab assets".
        code, err = self._main()
        self.assertEqual(code, 2)
        self.assertEqual(err.count(tm.TAG), 1, err)

    def test_the_header_still_ends_at_the_first_content_line(self):
        # Negative control: a comment after real content is not a declaration.
        path = self._template("late.html.j2",
                              "{# supported-blocks: bullets #}\n<html>\n"
                              "{# requires: lab-assets #}\n")
        self.assertEqual(tm.template_requirements(path)["requires"], set())

    def test_model_keys_never_override_what_the_render_computes(self):
        # R35 round 1: the .html path merged the whole model back over the context, so
        # a model key named lab, web, sections or pacing replaced the computed value
        # (a remote "lab" logo then passed --web with an uppercase scheme).
        probe = self._template("probe.html.j2", (
            "{# supported-blocks: bullets #}\n{# requires: lab-assets #}\n"
            "BANNER={{ lab.banner }}\nLOGO={{ lab.logo }}\n"
            "SWIPE={{ web.swipe_threshold_px }}\nSECTIONS={{ sections | join('|') }}\n"
            "PACING={{ pacing | length }}\nTITLE={{ slides[0].title }}\n"))
        model = dict(self.model)
        model.update({"lab": {"banner": "HTTP://evil.example/b.png",
                              "logo": "HTTP://evil.example/l.png"},
                      "web": {"swipe_threshold_px": 1}, "sections": ["Forged"],
                      "pacing": [99, 99, 99]})
        tm.render_template(model, probe, self.out, model_dir=self.base, lab_dir=self.lab)
        with open(self.out, encoding="utf8") as fh:
            out = dict(line.split("=", 1) for line in fh.read().splitlines() if "=" in line)
        self.assertTrue(out["BANNER"].startswith("data:image/jpeg;base64,"), out["BANNER"][:30])
        self.assertTrue(out["LOGO"].startswith("data:image/png;base64,"), out["LOGO"][:30])
        self.assertEqual(out["SWIPE"], "40")
        self.assertNotIn("Forged", out["SECTIONS"])
        self.assertEqual(out["PACING"], "1")
        # Positive control: the slides themselves still come from the model.
        self.assertEqual(out["TITLE"], "T")

    def test_an_undeclared_requirement_is_empty(self):
        self.assertEqual(tm.template_requirements(self.plain_template)["requires"], set())

    def test_load_lab_assets_returns_one_data_uri_per_role(self):
        lab = tm.load_lab_assets(self.lab)
        self.assertTrue(lab["banner"].startswith("data:image/jpeg;base64,"))
        self.assertTrue(lab["logo"].startswith("data:image/png;base64,"))

    def test_a_requiring_template_without_lab_dir_exits_2(self):
        code, err = self._main()
        self.assertEqual(code, 2)
        self.assertIn("--lab-dir", err)
        self.assertFalse(os.path.exists(self.out))

    def test_a_lab_folder_missing_the_logo_exits_2_naming_it(self):
        os.remove(self.logo)
        code, err = self._main("--lab-dir", self.lab)
        self.assertEqual(code, 2)
        self.assertIn("LogoLARI_FINAL.png", err)

    def test_a_lab_folder_that_does_not_exist_exits_2_naming_it(self):
        missing = os.path.join(self.base, "no_such_folder")
        code, err = self._main("--lab-dir", missing)
        self.assertEqual(code, 2)
        self.assertIn("no_such_folder", err)

    def test_the_context_holds_both_lab_images_as_data_uris(self):
        # Exit 1 here is the model's own content rule (a text-only slide), reported
        # after the render; exit 2 would be the refusal this test rules out.
        code, _ = self._main("--lab-dir", self.lab)
        self.assertNotEqual(code, 2)
        with open(self.out, encoding="utf8") as fh:
            text = fh.read()
        self.assertIn("BANNER=data:image/jpeg;base64,", text)
        self.assertIn("LOGO=data:image/png;base64,", text)

    def test_a_template_without_the_requirement_renders_without_the_flag(self):
        # Negative control: the Beamer and current web templates must keep working.
        tm.render_template(self.model, self.plain_template, self.out)
        with open(self.out, encoding="utf8") as fh:
            self.assertIn("TITLE=Probe deck", fh.read())


if __name__ == "__main__":
    unittest.main(verbosity=2)
