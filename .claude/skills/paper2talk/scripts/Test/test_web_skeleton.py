"""
Offline tests for assets/web_skeleton.html.j2, the LARI web deck: a fixture model is rendered
through the real template with generated images and fictitious authors (R34), and the HTML is
asserted as text. What these tests pin is the lab identity of the compiled Beamer reference
(green #006341, title box, banner and logo on the title slide only, a frame-title band, a
footer row of its own) and the self-containment of the file. A browser is never opened here;
the visual comparison is the manual check of plan 4.

Needs Jinja2, imported at the top so the suite runner reports the suite NOT RUN, rather than
FAILED, on a machine without it.
"""
import os
import re
import sys
import tempfile
import unittest

import jinja2  # noqa: F401  (the suite's one third-party dependency, see the docstring)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixtures as fx  # noqa: E402

import talk_model as tm  # noqa: E402
import talk_rules as rules  # noqa: E402
import talk_validate as tv  # noqa: E402

WEB_TEMPLATE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "assets", "web_skeleton.html.j2")

# Leading bytes only: the template embeds whatever embed_asset returns.
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x01" * 24
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x02" * 24
FIGURE_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x03" * 24

SECTION_RE = re.compile(r'<section class="slide[^"]*"[^>]*data-kind="(\w+)"[^>]*>(.*?)</section>',
                        re.S)


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


class _Deck(unittest.TestCase):
    """Builds the lab folder, a figure and a six-kind fixture model once per test."""

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.lab = os.path.join(self.base, "gabarit_slides")
        _write(os.path.join(self.lab, rules.LAB_ASSET_FILES["banner"]), JPEG_BYTES)
        _write(os.path.join(self.lab, rules.LAB_ASSET_FILES["logo"]), PNG_BYTES)
        self.model_dir = os.path.join(self.base, "deck")
        _write(os.path.join(self.model_dir, "figures", "fig1.png"), FIGURE_BYTES)
        self.banner_uri = tm.embed_asset(rules.LAB_ASSET_FILES["banner"], self.lab, 10 ** 6)
        self.logo_uri = tm.embed_asset(rules.LAB_ASSET_FILES["logo"], self.lab, 10 ** 6)

    def model(self, slides=None, palette=None, **meta):
        meta.setdefault("title", "Fictitious digital twin for a test cell")
        meta.setdefault("subtitle", "A fixture subtitle")
        meta.setdefault("authors", ["Wick, J.", "Doe, A."])
        meta.setdefault("institute", "Example Institute")
        meta.setdefault("date", "1 January 2030")
        meta.setdefault("aspect", "16:9")
        model = fx.model(slides if slides is not None else self.six_slides(), **meta)
        model["palette"] = {} if palette is None else palette
        return model

    @staticmethod
    def six_slides():
        figure = {"kind": "figure", "asset": "figures/fig1.png", "caption": "Fig. 1 probe",
                  "keywords": ["probe"]}
        return [
            {"n": 1, "kind": "title", "title": "Fictitious digital twin", "blocks": [],
             "notes": "opening"},
            {"n": 2, "kind": "outline", "title": "Outline", "blocks": [], "notes": "plan"},
            {"n": 3, "kind": "divider", "title": "Method", "blocks": [], "notes": "turn"},
            {"n": 4, "kind": "content", "title": "A measured claim", "section": "Method",
             "blocks": [figure], "notes": "the probe figure"},
            {"n": 5, "kind": "content", "title": "A second claim", "section": "Results",
             "blocks": [{"kind": "takeaway", "text": "It holds", "alert": True}],
             "notes": "probe"},
            {"n": 6, "kind": "thanks", "title": "Questions", "blocks": [], "notes": "close"},
            {"n": 7, "kind": "backup", "title": "Appendix", "blocks": [], "notes": ""},
        ]

    def render(self, model):
        out = os.path.join(self.base, "deck.html")
        tm.render_template(model, WEB_TEMPLATE, out, model_dir=self.model_dir,
                           lab_dir=self.lab)
        self.out = out
        with open(out, encoding="utf8") as fh:
            return fh.read()

    def sections(self, html):
        return SECTION_RE.findall(html)


class TestHeader(_Deck):
    def test_the_template_declares_its_kinds_and_needs_the_lab_assets(self):
        declared = tm.template_requirements(WEB_TEMPLATE)
        self.assertEqual(declared["supported-kinds"], set(rules.KINDS))
        self.assertEqual(declared["requires"], {"lab-assets"})
        self.assertEqual(declared["supported-blocks"], set(tm.BLOCK_KINDS))


class TestLabIdentity(_Deck):
    def test_the_default_brand_is_the_lab_green(self):
        html = self.render(self.model())
        self.assertIn("--brand: #006341", html)
        self.assertNotIn("5A7210", html.upper())     # the retired stand-in green

    def test_the_logo_appears_once_and_only_on_the_title_slide(self):
        html = self.render(self.model())
        self.assertEqual(html.count(self.logo_uri), 1)
        for kind, body in self.sections(html):
            self.assertEqual(self.logo_uri in body, kind == "title", kind)

    def test_the_banner_is_on_the_title_slide(self):
        html = self.render(self.model())
        title = [body for kind, body in self.sections(html) if kind == "title"][0]
        self.assertIn(self.banner_uri, title)
        self.assertIn('class="title-box"', title)
        for text in ("A fixture subtitle", "Wick, J.", "Example Institute", "1 January 2030"):
            self.assertIn(text, title)

    def test_every_non_title_slide_has_the_title_band(self):
        html = self.render(self.model())
        for kind, body in self.sections(html):
            if kind in ("title", "divider"):
                continue
            self.assertIn('class="frametitle"', body, kind)

    def test_each_kind_has_its_own_layout(self):
        html = self.render(self.model())
        for kind in rules.KINDS:
            self.assertRegex(html, rf'<section class="slide layout-{kind}"', kind)

    def test_the_outline_lists_the_sections_in_order(self):
        html = self.render(self.model())
        outline = [body for kind, body in self.sections(html) if kind == "outline"][0]
        self.assertLess(outline.find("<li>Method</li>"), outline.find("<li>Results</li>"))
        self.assertGreaterEqual(outline.find("<li>Method</li>"), 0)

    def test_the_closing_slide_shows_its_text_as_a_large_green_headline(self):
        # Reference page 21: "Questions?" large, bold and green, not a boxed block.
        html = self.render(self.model())
        rule = re.search(r"\.layout-thanks \.block-body\s*\{([^}]*)\}", html)
        self.assertIsNotNone(rule, "no closing-slide rule for the block body")
        self.assertIn("var(--brand)", rule.group(1))
        self.assertIn("background: none", rule.group(1))

    def test_an_alert_block_is_drawn_as_a_red_block(self):
        html = self.render(self.model())
        self.assertIn('class="block alert"', html)

    def test_no_serif_face_is_used(self):
        html = self.render(self.model())
        for face in ("Cambria", "Caladea", "Georgia"):
            self.assertNotIn(face, html)
        for decl in re.findall(r"font-family:([^;}\"]*)", html):
            self.assertNotRegex(decl, r"(?<!sans-)\bserif\b", decl)


class TestFooter(_Deck):
    def test_the_footer_is_on_every_non_title_slide_only(self):
        # spec.md: the footer belongs on every NON-title slide, once, with the short
        # fields, the date and n / N (n counted over the whole deck).
        html = self.render(self.model(short_title="Twin probe", short_author="Wick et al."))
        sections = self.sections(html)
        for k, (kind, body) in enumerate(sections, start=1):
            footers = re.findall(r'<footer class="footline">(.*?)</footer>', body, re.S)
            if kind == "title":
                self.assertEqual(footers, [], f"slide {k} is the title slide")
                self.assertNotIn("footline", body)
                continue
            self.assertEqual(len(footers), 1, f"slide {k} ({kind})")
            for expected in ("Wick et al.", "Twin probe", "1 January 2030",
                             f"{k} / {len(sections)}"):
                self.assertIn(expected, footers[0], f"slide {k}")

    def test_without_short_forms_the_footer_shows_what_validation_checks(self):
        # One rule: the footer author box is exactly the field _footer_problems measures.
        html = self.render(self.model())
        footer = re.search(r'<footer class="footline">(.*?)</footer>', html, re.S).group(1)
        self.assertIn("Wick, J., Doe, A.", footer)
        self.assertIn("Fictitious digital twin for a test cell", footer)

    def test_the_footer_is_a_row_of_its_own_outside_the_content(self):
        html = self.render(self.model())
        for kind, body in self.sections(html):
            if kind == "title":
                continue
            self.assertLess(body.find('class="slide-body"'), body.find('class="footline"'))

    def test_a_one_slide_deck_renders(self):
        # A single non-title slide, so its footer shows the counter at its limit.
        html = self.render(self.model(slides=[self.six_slides()[3]]))
        self.assertIn("1 / 1", html)


class TestSelfContained(_Deck):
    def test_no_network_or_external_reference(self):
        html = self.render(self.model())
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)
        self.assertNotRegex(html, r"<script[^>]*\bsrc=")
        self.assertNotIn("@import", html)
        self.assertNotIn("figures/fig1.png", html)

    def test_the_rendered_deck_passes_the_offline_check(self):
        self.render(self.model())
        self.assertEqual(tv.check_web(self.out), [])


class TestInteractions(_Deck):
    """Task 7: each behaviour leaves a structural marker; the browser smoke check is extra."""

    def script(self, html):
        return re.search(r"<script>(.*?)</script>", html, re.S).group(1)

    def css(self, html):
        return re.search(r"<style>(.*?)</style>", html, re.S).group(1)

    def deck_config(self, html):
        import json
        return json.loads(re.search(r"const DECK = (\{.*?\});", html, re.S).group(1))

    def test_the_script_reads_one_json_config(self):
        model = self.model()
        config = self.deck_config(self.render(model))
        self.assertEqual(config["swipe_threshold_px"], rules.WEB_INTERACTION["swipe_threshold_px"])
        self.assertEqual(len(config["pacing"]), len(model["slides"]))
        for got, want in zip(config["pacing"], tm.slide_pacing(model)):
            self.assertAlmostEqual(got, want, places=6)

    def test_the_threshold_comes_from_the_context_not_the_markup(self):
        from unittest import mock
        with mock.patch.dict(rules.WEB_INTERACTION, {"swipe_threshold_px": 55}):
            config = self.deck_config(self.render(self.model()))
        self.assertEqual(config["swipe_threshold_px"], 55)

    def test_keys_are_ignored_while_typing_or_with_a_modifier(self):
        js = self.script(self.render(self.model()))
        self.assertIn("isContentEditable", js)
        self.assertRegex(js, r"INPUT|TEXTAREA|SELECT")
        for flag in ("ctrlKey", "altKey", "metaKey"):
            self.assertIn(flag, js)

    def test_the_counter_and_progress_follow_the_slide(self):
        html = self.render(self.model())
        self.assertIn('id="counter"', html)
        self.assertIn('id="progress-bar"', html)
        js = self.script(html)
        self.assertIn("counter", js)
        self.assertIn("progressBar.style.width", js)

    def test_the_hash_is_read_clamped_and_written(self):
        js = self.script(self.render(self.model()))
        self.assertIn("function slideFromHash", js)
        self.assertIn(r"/^#\/(\d+)$/", js)            # only #/<digits>; anything else ignored
        self.assertRegex(js, r"Math\.min\(\s*slides\.length")  # past the end clamps to last
        self.assertRegex(js, r"Math\.max\(\s*1")                # zero clamps to first
        self.assertIn("history.replaceState", js)
        self.assertIn("hashchange", js)

    def test_fullscreen_blackout_help_and_notes_have_their_keys(self):
        html = self.render(self.model())
        js = self.script(html)
        self.assertIn("requestFullscreen", js)
        self.assertIn("exitFullscreen", js)
        self.assertIn('id="blackout"', html)
        self.assertIn("'.'", js)
        for key in ("'f'", "'b'", "'?'", "'n'", "'Escape'"):
            self.assertIn(key, js)

    def test_the_help_overlay_is_an_accessible_dialog(self):
        html = self.render(self.model())
        help_box = re.search(r'<div id="help"[^>]*>', html)
        self.assertIsNotNone(help_box)
        for attr in ('role="dialog"', 'aria-modal="true"', 'aria-labelledby="help-title"',
                     "hidden"):
            self.assertIn(attr, help_box.group(0))
        self.assertIn('id="help-title"', html)
        self.assertIn('id="help-close"', html)

    def test_click_advances_but_not_on_interactive_elements(self):
        js = self.script(self.render(self.model()))
        self.assertIn("addEventListener('click'", js)
        self.assertRegex(js, r"closest\('a, button, input, select, textarea")

    def _handler(self, js, event):
        opener = f"document.addEventListener('{event}'"
        start = js.index(opener)
        end = js.find("addEventListener(", start + len(opener))
        return js[start:end if end != -1 else len(js)]

    def test_a_click_while_the_help_is_open_does_not_turn_the_page(self):
        # R35 round 3: keys are inert behind the open dialog, but a click beside it
        # still advanced the hidden deck and started the talk clock.
        click = self._handler(self.script(self.render(self.model())), "click")
        guard = click.find("!help.hidden")
        self.assertNotEqual(guard, -1, click)
        self.assertLess(guard, click.index("go(index + 1)"))

    def test_a_swipe_cancels_the_click_the_browser_would_synthesize(self):
        # R35 round 3: on a phone the threshold is a few screen pixels, inside the tap
        # slop, so the same gesture fired a swipe AND a click and skipped a slide.
        touchend = self._handler(self.script(self.render(self.model())), "touchend")
        cancel = touchend.find("e.preventDefault()")
        self.assertNotEqual(cancel, -1, touchend)
        self.assertLess(touchend.index("DECK.swipe_threshold_px"), cancel)
        self.assertLess(cancel, touchend.index("go(index"))

    def test_a_swipe_is_ignored_on_the_open_help_and_on_the_notes(self):
        # R35 round 4: the click was made inert behind the modal help in round 3, but a
        # swipe still turned the page there, and inside the presenter's notes panel.
        start = self._handler(self.script(self.render(self.model())), "touchstart")
        self.assertIn("!help.hidden", start)
        self.assertIn("closest('#help, .notes')", start)

    def _function(self, js, name):
        start = js.index(f"function {name}(")
        return js[start:js.index("\nfunction ", start + 1)]

    def test_the_clock_starts_only_when_the_slide_really_changes(self):
        # R35 round 4: Left on slide 1 started the clock although the deck did not move.
        go = self._function(self.script(self.render(self.model())), "go")
        self.assertLess(go.index("Math.min(slides.length - 1"), go.index("started = Date.now()"))

    def test_pacing_counts_from_the_slide_the_clock_started_on(self):
        # R35 rounds 4 to 6. The clock starts on the move AWAY from a slide, so that
        # slide was spoken before it ran (round 4: counting it showed "ahead" all talk).
        # The first counted slide is the one that move REACHED, whichever the direction
        # (round 5: a backward start counted nothing; round 6: moving forward again then
        # dropped the slides already spoken). Exactly this rule, nothing looser.
        js = self.script(self.render(self.model()))
        go = self._function(js, "go")
        pacing = self._function(js, "updatePacing")
        self.assertIn("started = Date.now(); startFirst = target;", go)
        self.assertIn("const first = started === null ? 0 : Math.min(startFirst, index);",
                      pacing)
        self.assertIn("DECK.pacing.slice(first, index + 1)", pacing)
        self.assertNotIn("startIndex", js)

    def test_a_move_while_blacked_out_only_brings_the_slide_back(self):
        # R35 round 10: a click on the black screen only unblanks, but a key (a clicker's
        # PageDown) or a swipe moved the deck unseen and could start the clock.
        js = self.script(self.render(self.model()))
        keydown = self._handler(js, "keydown")
        guard = keydown.find("if (!blackout.hidden && NAV_KEYS.includes(e.key))")
        self.assertNotEqual(guard, -1, keydown)
        self.assertLess(guard, keydown.index("go(index + 1)"))
        touchend = self._handler(js, "touchend")
        self.assertLess(touchend.index("!blackout.hidden"), touchend.index("go(index"))

    def test_the_help_states_what_a_move_does_on_the_black_screen(self):
        # R35 round 11: the in-deck key list must not promise "next slide" for a key that
        # only brings the slide back while the screen is black.
        html = self.render(self.model())
        help_box = html[html.index('<div id="help"'):html.index("</div>", html.index('<div id="help"'))]
        self.assertIn("black screen; any move first brings the slide back", help_box)

    def test_a_null_title_prints_nothing_in_the_footer(self):
        # R35 round 6: the footer title fell back to meta.title, and a null one printed
        # "None" on every slide, the class round 4 fixed for the date.
        html = self.render(self.model(title=None))
        self.assertNotIn('<span class="foot-title">None</span>', html)
        self.assertIn('<span class="foot-title"></span>', html)

    def test_a_missing_date_prints_nothing_in_the_footer(self):
        # R35 round 4: default('') covers an undefined date only; null printed "None".
        html = self.render(self.model(date=None))
        self.assertNotIn(">None<", html)
        self.assertIn('<span class="foot-date"></span>', html)

    def test_a_single_touch_swipe_moves_and_multi_touch_never_does(self):
        js = self.script(self.render(self.model()))
        self.assertIn("touchstart", js)
        self.assertIn("touchend", js)
        self.assertIn("touches.length > 1", js)
        self.assertIn("DECK.swipe_threshold_px", js)

    def test_slide_changes_are_announced(self):
        html = self.render(self.model())
        live = re.search(r'<div id="announce"[^>]*>', html)
        self.assertIsNotNone(live)
        self.assertIn('aria-live="polite"', live.group(0))
        self.assertIn("aria-hidden", self.script(html))   # inactive slides are hidden

    def test_the_notes_panel_shows_pacing(self):
        html = self.render(self.model())
        self.assertIn('id="pacing"', html)
        self.assertIn("DECK.pacing", self.script(html))

    def test_print_hides_the_chrome_and_keeps_the_footer(self):
        css = self.css(self.render(self.model()))
        printed = re.search(r"@media print \{(.*)\}\s*$", css, re.S).group(1)
        # Every element outside the stage is chrome; one left visible after the last
        # page break prints an extra page (measured: 8 pages for 7 slides).
        for chrome in ("#counter", "#progress", "#help", "#blackout", "#announce", ".notes"):
            self.assertIn(chrome, printed)
        hidden = re.findall(r"([^{}]*)\{\s*display:\s*none", printed)
        self.assertFalse(any(".footline" in sel for sel in hidden), hidden)

    def test_reduced_motion_removes_transitions(self):
        css = self.css(self.render(self.model()))
        self.assertRegex(css, r"prefers-reduced-motion: reduce\)\s*\{[^}]*transition: none")


class TestStageFit(_Deck):
    """The 1920x1080 canvas is scaled as a whole and centred on any viewport.

    Measured in Edge before the fix: the stage was centred by CSS grid, and an item larger
    than its grid track starts at the container's corner, so after scale() about its own
    centre it landed at 960*(1-s), 540*(1-s) - 403 px right of where it belongs at
    1280x720, cropped on the right. Centring now comes from the stage's own position.
    """

    def css(self, html):
        return re.search(r"<style>(.*?)</style>", html, re.S).group(1)

    def test_the_logical_canvas_is_unchanged(self):
        css = self.css(self.render(self.model()))
        self.assertIn("--slide-w: 1920px", css)
        self.assertIn("--slide-h: 1080px", css)

    def test_the_stage_is_centred_by_its_own_position(self):
        css = self.css(self.render(self.model()))
        rule = re.search(r"#stage \{([^}]*)\}", css).group(1)
        for decl in ("position: absolute", "left: 50%", "top: 50%",
                     "transform-origin: center center"):
            self.assertIn(decl, rule)

    def test_fit_scales_to_the_smaller_ratio_about_the_centre(self):
        js = re.search(r"<script>(.*?)</script>", self.render(self.model()), re.S).group(1)
        fit = re.search(r"function fit\(\) \{(.*?)\n\}", js, re.S).group(1)
        self.assertIn("Math.min(vw / sw, vh / sh)", fit)
        self.assertIn("'translate(-50%, -50%) scale(' + scale + ')'", fit)

    def test_print_puts_the_stage_back_in_the_flow(self):
        css = self.css(self.render(self.model()))
        printed = re.search(r"@media print \{(.*)\}\s*$", css, re.S).group(1)
        rule = re.search(r"#stage \{([^}]*)\}", printed).group(1)
        self.assertIn("transform: none !important", rule)
        self.assertIn("position: static", rule)


class TestEscaping(_Deck):
    def test_markup_in_titles_and_notes_is_escaped(self):
        slides = self.six_slides()
        slides[3]["title"] = "<b>Wick & Doe</b> \"quoted\""
        slides[3]["notes"] = "end of notes </script><script>alert(1)</script>"
        html = self.render(self.model(slides=slides))
        self.assertNotIn("<b>Wick & Doe</b>", html)
        self.assertIn("&lt;b&gt;Wick &amp; Doe&lt;/b&gt;", html)
        self.assertEqual(html.count("</script>"), 1)     # only the deck's own closing tag


if __name__ == "__main__":
    unittest.main(verbosity=2)
