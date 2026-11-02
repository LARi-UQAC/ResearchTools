"""
Offline tests for talk_validate.py: the document-skills validator is located rather
than hardcoded (env var first, then the newest cache match), the built-in checks
fire on a dangling r:embed and on a chart with a secondary axis but no declared
axes, and the web target refuses an external URL.
"""
import contextlib
import io
import os
import pathlib
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixtures as fx  # noqa: E402

import talk_validate as tv  # noqa: E402

CHART_BAD = (
    '<?xml version="1.0"?><c:chartSpace xmlns:c="http://schemas.openxmlformats.org/'
    'drawingml/2006/chart"><c:chart><c:plotArea><c:lineChart>'
    "<c:secondaryValAxis/></c:lineChart></c:plotArea></c:chart></c:chartSpace>"
)
CHART_GOOD = (
    '<?xml version="1.0"?><c:chartSpace xmlns:c="http://schemas.openxmlformats.org/'
    'drawingml/2006/chart"><c:chart><c:plotArea><c:lineChart/>'
    "<c:catAx></c:catAx><c:valAx></c:valAx></c:plotArea></c:chart></c:chartSpace>"
)


class TestPluginDiscovery(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def _cache(self, hashes):
        made = []
        for h in hashes:
            folder = os.path.join(self.dir, "document-skills", h, "skills", "pptx",
                                  "scripts", "office")
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, "validate.py")
            with open(path, "w", encoding="utf8") as fh:
                fh.write("# stub\n")
            made.append(path)
            time.sleep(0.01)
        return made

    def test_the_environment_variable_wins(self):
        explicit = os.path.join(self.dir, "explicit_validate.py")
        with open(explicit, "w", encoding="utf8") as fh:
            fh.write("# stub\n")
        self._cache(["aaa"])
        pattern = os.path.join(self.dir, "document-skills", "*", "skills", "pptx",
                               "scripts", "office", "validate.py")
        found = tv.find_plugin_validator({"DOCUMENT_SKILLS_PPTX": explicit}, pattern)
        self.assertEqual(found, explicit)

    def test_the_newest_cache_entry_wins_when_several_are_installed(self):
        made = self._cache(["f17010c9bb48", "b99ff01c2210"])
        newest = made[-1]
        os.utime(newest, (time.time() + 10, time.time() + 10))
        pattern = os.path.join(self.dir, "document-skills", "*", "skills", "pptx",
                               "scripts", "office", "validate.py")
        self.assertEqual(tv.find_plugin_validator({}, pattern), newest)

    def test_no_match_returns_none_so_the_builtin_checks_run(self):
        pattern = os.path.join(self.dir, "nothing", "*", "validate.py")
        self.assertIsNone(tv.find_plugin_validator({}, pattern))


class TestPackageChecks(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_a_dangling_relationship_is_caught(self):
        deck = os.path.join(self.dir, "dangling.pptx")
        fx.build_pptx(deck, [{"body": fx.pic_xml(), "notes": "x",
                              "media": True, "dangling": True}])
        problems = tv.check_package(deck)
        self.assertTrue(any("no relationship declares it" in p for p in problems))

    def test_a_resolved_relationship_passes(self):
        deck = os.path.join(self.dir, "ok.pptx")
        fx.build_pptx(deck, [{"body": fx.pic_xml(), "notes": "x", "media": True}])
        self.assertEqual(tv.check_package(deck), [])

    def test_a_secondary_axis_without_declared_axes_is_caught(self):
        deck = os.path.join(self.dir, "chart_bad.pptx")
        fx.build_pptx(deck, [{"body": fx.graphic_frame_xml(), "notes": "x"}],
                      charts={"chart1.xml": CHART_BAD})
        problems = tv.check_package(deck)
        self.assertTrue(any("secondary value axis" in p for p in problems))

    def test_a_chart_declaring_both_axes_passes(self):
        deck = os.path.join(self.dir, "chart_ok.pptx")
        fx.build_pptx(deck, [{"body": fx.graphic_frame_xml(), "notes": "x"}],
                      charts={"chart1.xml": CHART_GOOD})
        self.assertEqual(tv.check_package(deck), [])


class TestWebTarget(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def _html(self, name, body):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf8") as fh:
            fh.write(body)
        return path

    def test_a_cdn_font_fails_the_self_containment_rule(self):
        page = self._html("cdn.html",
                          '<link href="https://api.fontshare.com/v2/css?f[]=x">')
        problems = tv.check_web(page)
        self.assertTrue(problems)
        self.assertIn("external URL", problems[0])

    def test_a_remote_image_fails(self):
        page = self._html("img.html", '<img src="http://example.org/fig.png">')
        self.assertTrue(tv.check_web(page))

    def test_a_remote_css_url_fails(self):
        page = self._html("css.html",
                          "<style>body{background:url('https://cdn.example/x.png')}</style>")
        self.assertTrue(tv.check_web(page))

    def test_an_inlined_deck_passes(self):
        page = self._html("inline.html",
                          '<img src="data:image/png;base64,iVBORw0KG"><style>'
                          "body{font-family:Calibri}</style>")
        self.assertEqual(tv.check_web(page), [])

    # A relative reference works on the build machine and breaks once the deck is
    # copied anywhere else, so it is the same failure as a CDN link, only quieter.

    def test_a_relative_image_fails(self):
        page = self._html("rel_img.html", '<img src="figures/fig1.png">')
        problems = tv.check_web(page)
        self.assertEqual(len(problems), 1)
        self.assertIn("figures/fig1.png", problems[0])

    def test_a_relative_stylesheet_fails(self):
        page = self._html("rel_css.html", '<link rel="stylesheet" href="deck.css">')
        problems = tv.check_web(page)
        self.assertEqual(len(problems), 1)
        self.assertIn("deck.css", problems[0])

    def test_a_relative_css_url_fails_with_or_without_quotes(self):
        for css in ("url(img/bg.png)", "url('img/bg.png')", 'url( "img/bg.png" )'):
            with self.subTest(css=css):
                page = self._html("rel_url.html", "<style>body{background:%s}</style>" % css)
                problems = tv.check_web(page)
                self.assertEqual(len(problems), 1)
                self.assertIn("img/bg.png", problems[0])

    def test_a_protocol_relative_reference_fails(self):
        # //host/x.js is fetched over the network just as https:// is.
        page = self._html("proto.html", '<script src="//cdn.example/x.js"></script>')
        self.assertTrue(tv.check_web(page))

    def test_inline_fragment_and_mail_references_pass(self):
        # Negative control: a check that flags these would refuse every real deck.
        page = self._html(
            "allowed.html",
            '<img src="data:image/png;base64,iVBORw0KG">'
            '<a href="#/3">next</a><a href="mailto:student@example.org">mail</a>'
            "<svg><rect fill=\"url(#grad)\"/></svg>"
            "<style>.b{background:url(data:image/png;base64,iVBORw0KG)}</style>",
        )
        self.assertEqual(tv.check_web(page), [])

    def test_src_inside_a_script_string_is_not_an_attribute(self):
        # The deck's own script may mention src= in a string or set a property; only
        # an HTML attribute or a CSS url() loads anything when the page opens.
        page = self._html(
            "script.html",
            '<script>const hint = "src=" + n; el.src = "#"; // the src= attribute</script>',
        )
        self.assertEqual(tv.check_web(page), [])

    def test_url_in_slide_text_or_notes_is_not_a_reference(self):
        # R35 round 2: the CSS url() scan ran over every line, so a bullet or a speaker
        # note that MENTIONS url(...) failed the deck; a browser loads nothing for it.
        for body in ('<li>use url(data) here</li>',
                     '<script>const NOTES = ["the CSS url(logo.png) call"];</script>',
                     '<p>see\nurl(figures/a.png) in the text</p>'):
            with self.subTest(body=body):
                self.assertEqual(tv.check_web(self._html("prose.html", body)), [])

    def test_url_in_a_tag_spread_over_several_lines_is_still_a_reference(self):
        # R35 round 3: the round-2 scoping read tags one line at a time, so the url()
        # of a tag spread over lines - the template's own <polyline>, or a newline a
        # model value carries into a style attribute - was no longer reported.
        for body in ('<polyline fill="none" stroke-width="3"\n'
                     '          stroke="url(//host.example/p.svg#g)"\n'
                     '          points="0,0 1,1"/>',
                     '<span class="chip" style="background:#000;\n'
                     'background-image:url(a.png)">x</span>',
                     '<div title="a&gt;b"\n style="background:url(a.png)"></div>'):
            with self.subTest(body=body):
                problems = tv.check_web(self._html("multi.html", body))
                self.assertEqual(len(problems), 1, problems)
                self.assertIn("multi.html:2", problems[0])

    def test_a_form_feed_or_line_separator_does_not_shift_the_report(self):
        # R35 round 4: url() findings were numbered by "\n" and every other finding by
        # str.splitlines, which also breaks on \f and U+2028, so after slide text
        # carrying one the two disagreed and one reference could be reported twice.
        for sep in ("\f", " ", "\x85"):
            with self.subTest(sep=repr(sep)):
                body = (f"<p>a{sep}b</p>\n"
                        '<img src="https://e.example/x.png" '
                        'style="background:url(https://e.example/y.png)">')
                problems = tv.check_web(self._html("sep.html", body))
                self.assertEqual(len(problems), 1, problems)
                self.assertIn("sep.html:2", problems[0])

    def test_url_in_a_caption_or_label_attribute_is_not_a_reference(self):
        # R35 round 7: every attribute of a tag was scanned, so a caption carried into
        # alt, or a chart title into aria-label, that MENTIONS url() failed the deck.
        for body in ('<img src="data:image/png;base64,AA" alt="Loss via url(cache.png)">',
                     '<svg role="img" aria-label="Rate url(x)"></svg>',
                     '<a href="#/2" title="see url(a.png)">next</a>'):
            with self.subTest(body=body):
                self.assertEqual(tv.check_web(self._html("label.html", body)), [])

    def test_url_inside_the_deck_script_is_not_a_reference(self):
        # Negative control for the whole-document scan: a comparison in the deck's own
        # script must not open a "tag" that swallows the code after it.
        body = ("<script>\nfor (let i = 0; i<slides.length; i++) {\n"
                "  el.style.background = 'url(a.png)';\n}\n</script>")
        self.assertEqual(tv.check_web(self._html("script.html", body)), [])

    def test_url_in_a_style_attribute_or_block_is_still_a_reference(self):
        # Negative control: where a browser does resolve url(), it is still reported,
        # including a <style> block spread over several lines.
        for body in ('<div style="background:url(fig.png)"></div>',
                     '<style>\n.band {\n  background: url(fig.png);\n}\n</style>',
                     '<svg><rect fill="url(paint.svg#g)"/></svg>'):
            with self.subTest(body=body):
                problems = tv.check_web(self._html("style.html", body))
                self.assertEqual(len(problems), 1, problems)

    def test_an_external_reference_in_any_case_or_spacing_is_reported(self):
        # R35 round 1: the reference loop skipped every http(s) value on the belief
        # that the external-URL pattern had reported it, but that pattern is
        # case-sensitive and wants the scheme right after the quote, so these four
        # passed --web as "clean" while a browser loads every one of them.
        for body in ('<img src="HTTPS://example.org/x.png">',
                     '<link href="Https://fonts.example.org/f.css">',
                     '<div style="background:URL(HTTP://example.org/c)"></div>',
                     '<img src=" https://example.org/x.png">'):
            with self.subTest(body=body):
                problems = tv.check_web(self._html("case.html", body))
                self.assertEqual(len(problems), 1, problems)

    def test_an_external_reference_is_reported_once(self):
        # Preserve the existing message, and do not report the same URL twice.
        page = self._html("ext.html", '<img src="https://example.org/fig.png">')
        problems = tv.check_web(page)
        self.assertEqual(len(problems), 1)
        self.assertIn("external URL", problems[0])


class TestOverlaps(unittest.TestCase):
    """A caption under a logo and a heading colliding with the row beneath it are
    both bounding-box overlaps, and they were the two most frequent defects."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def _deck(self, name, body):
        path = os.path.join(self.dir, name)
        fx.build_pptx(path, [{"body": body, "notes": "x"}])
        return path

    def test_two_shapes_on_top_of_each_other_are_named(self):
        body = (fx.sp_xml("Caption", "Fig. 1", x_in=1.0, y_in=6.5, w_in=3.0, h_in=0.4)
                + fx.pic_xml("Wordmark", x_in=1.2, y_in=6.5, w_in=3.0, h_in=0.4))
        warnings = tv.check_overlaps(self._deck("overlap.pptx", body))
        self.assertTrue(warnings)
        self.assertIn("Caption", warnings[0])
        self.assertIn("Wordmark", warnings[0])

    def test_shapes_side_by_side_do_not_trip_it(self):
        body = (fx.sp_xml("Left", "a", x_in=0.5, y_in=2.0, w_in=4.0, h_in=1.0)
                + fx.sp_xml("Right", "b", x_in=5.0, y_in=2.0, w_in=4.0, h_in=1.0))
        self.assertEqual(tv.check_overlaps(self._deck("apart.pptx", body)), [])

    def test_a_touching_edge_is_not_an_overlap(self):
        body = (fx.sp_xml("Top", "a", x_in=1.0, y_in=1.0, w_in=4.0, h_in=1.0)
                + fx.sp_xml("Below", "b", x_in=1.0, y_in=2.0, w_in=4.0, h_in=1.0))
        self.assertEqual(tv.check_overlaps(self._deck("touch.pptx", body)), [])

    def test_a_sliver_overlap_stays_below_the_tolerance(self):
        # Text frames are wider than their glyphs, so a few percent is normal.
        body = (fx.sp_xml("A", "a", x_in=1.0, y_in=1.0, w_in=4.0, h_in=1.0)
                + fx.sp_xml("B", "b", x_in=1.0, y_in=1.95, w_in=4.0, h_in=1.0))
        self.assertEqual(tv.check_overlaps(self._deck("sliver.pptx", body)), [])


class TestPaletteAndSize(unittest.TestCase):
    def test_a_triad_that_differs_only_in_hue_is_flagged(self):
        # #C0392B and #0A7930 sit at the same relative luminance (0.143 / 0.140):
        # red and green of one lightness carry no information for roughly one man
        # in twelve, nor on a washed-out projector.
        warnings = tv.check_palette({"s1": "C0392B", "s2": "0A7930", "s3": "F1C40F"})
        self.assertTrue(any("s1" in w and "s2" in w for w in warnings))

    def test_the_case_deck_triad_is_flagged_and_that_is_a_real_finding(self):
        # Measured on the delivered deck: green 0.155, amber 0.258, red 0.108. The
        # green and the red sit 0.047 apart, so the two classes that matter most
        # (safe against danger) are the pair a colour-blind viewer cannot separate.
        warnings = tv.check_palette({"s1": "2E7D32", "s2": "C57A00", "s3": "B3221F"})
        self.assertTrue(any("s1" in w and "s3" in w for w in warnings))

    def test_the_recommended_triad_passes(self):
        # green 0.155, amber 0.582, red 0.052 - separated in lightness, so the
        # classes survive greyscale, projection and colour blindness.
        self.assertEqual(tv.check_palette({"s1": "2E7D32", "s2": "F1C40F",
                                           "s3": "7B1E1E"}), [])

    def test_a_triad_separated_in_lightness_passes(self):
        self.assertEqual(tv.check_palette({"s1": "2E7D32", "s2": "F1C40F",
                                           "s3": "7B1E1E"}), [])

    def test_an_absent_triad_is_not_an_error(self):
        self.assertEqual(tv.check_palette({}), [])

    def test_an_oversized_deck_is_reported(self):
        path = os.path.join(tempfile.mkdtemp(), "big.pptx")
        fx.build_pptx(path, [{"body": "", "notes": "x"}])
        self.assertEqual(tv.check_size(path), [])
        self.assertTrue(tv.check_size(path, max_mb=0.000001))


class TestOpenAfterCheck(unittest.TestCase):
    """--open hands a CLEAN web deck to the system browser; nothing else ever opens it.

    webbrowser.open is patched in every case: no test here starts a browser.
    """

    def setUp(self):
        # R35 round 12 (R21): the no-display guard reads the platform and the display, so
        # every case runs on a pinned desktop platform; the Unix cases override it.
        platform = mock.patch.object(tv.sys, "platform", "win32")
        platform.start()
        self.addCleanup(platform.stop)
        self.dir = tempfile.mkdtemp()
        self.clean = self._html("clean.html", '<img src="data:image/png;base64,iVBORw0KG">')
        self.bad = self._html("bad.html", '<img src="figures/fig1.png">')

    def _html(self, name, body):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf8") as fh:
            fh.write(body)
        return path

    def _main(self, argv, opener_result=True, opener_error=None):
        err = io.StringIO()
        with mock.patch.object(tv.webbrowser, "open", return_value=opener_result,
                               side_effect=opener_error) as opener, \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = tv.main(argv)
        return code, opener, err.getvalue()

    def test_a_clean_deck_with_open_is_opened_once_as_a_file_uri(self):
        code, opener, _ = self._main(["--web", self.clean, "--open"])
        self.assertEqual(code, 0)
        opener.assert_called_once()
        uri = opener.call_args.args[0]
        self.assertTrue(uri.startswith("file:"), uri)
        self.assertEqual(uri, pathlib.Path(os.path.abspath(self.clean)).as_uri())

    def test_a_deck_with_findings_exits_1_and_never_opens(self):
        code, opener, _ = self._main(["--web", self.bad, "--open"])
        self.assertEqual(code, 1)
        opener.assert_not_called()

    def test_a_clean_deck_without_open_never_opens(self):
        # Suppression is the absence of --open (the /talk --no-open opt-out drops it).
        code, opener, _ = self._main(["--web", self.clean])
        self.assertEqual(code, 0)
        opener.assert_not_called()

    def test_an_unreadable_deck_with_open_exits_2_and_never_opens(self):
        code, opener, _ = self._main(["--web", os.path.join(self.dir, "absent.html"), "--open"])
        self.assertEqual(code, 2)
        opener.assert_not_called()

    def test_open_without_web_is_a_usage_refusal(self):
        code, opener, err = self._main(["--beamer", "main.tex", "--open"])
        self.assertEqual(code, 2)
        self.assertIn("--open", err)
        opener.assert_not_called()

    def test_open_with_no_web_deck_names_the_missing_flag(self):
        # R35 round 12 (R20): the other cause of the refusal, with no --beamer at all.
        for argv in (["--open"], ["deck.pptx", "--open"]):
            with self.subTest(argv=argv):
                code, opener, err = self._main(argv)
                self.assertEqual(code, 2)
                self.assertIn("--web is missing", err)
                opener.assert_not_called()

    def test_a_terminal_only_unix_session_is_never_handed_to_a_browser(self):
        # R35 round 9: with no display, the standard library falls back to a console
        # browser (lynx, w3m) and waits on it with no timeout (R10), hanging the run.
        # BROWSER is removed too (R35 round 11, R21): a devcontainer or VS Code Remote
        # terminal sets it, and the verdict must not depend on the machine.
        env = {k: v for k, v in os.environ.items()
               if k not in ("DISPLAY", "WAYLAND_DISPLAY", "BROWSER")}
        with mock.patch.object(tv.sys, "platform", "linux"), \
                mock.patch.dict(tv.os.environ, env, clear=True):
            code, opener, err = self._main(["--web", self.clean, "--open"])
        self.assertEqual(code, 0)
        opener.assert_not_called()
        self.assertIn("by hand", err)

    def test_cygwin_is_guarded_like_any_unix_session(self):
        # R35 round 13: Cygwin Python's webbrowser takes the Unix path (console browsers
        # waited on with no timeout), so it must not be exempted like native Windows.
        env = {k: v for k, v in os.environ.items()
               if k not in ("DISPLAY", "WAYLAND_DISPLAY", "BROWSER")}
        with mock.patch.object(tv.sys, "platform", "cygwin"), \
                mock.patch.dict(tv.os.environ, env, clear=True):
            code, opener, err = self._main(["--web", self.clean, "--open"])
        self.assertEqual(code, 0)
        opener.assert_not_called()
        self.assertIn("by hand", err)

    def test_a_browser_named_by_the_user_is_honoured_without_a_display(self):
        # R35 round 10: BROWSER (wslview under WSL, an SSH-forwarded opener) works with no
        # display; the round-9 guard must not override the user's own choice.
        env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
        env["BROWSER"] = "wslview"
        with mock.patch.object(tv.sys, "platform", "linux"), \
                mock.patch.dict(tv.os.environ, env, clear=True):
            code, opener, _ = self._main(["--web", self.clean, "--open"])
        self.assertEqual(code, 0)
        opener.assert_called_once()

    def test_a_unix_session_with_a_display_still_opens(self):
        # Positive control: the guard is about the missing display, not about Unix.
        with mock.patch.object(tv.sys, "platform", "linux"), \
                mock.patch.dict(tv.os.environ, {"DISPLAY": ":0"}):
            code, opener, _ = self._main(["--web", self.clean, "--open"])
        self.assertEqual(code, 0)
        opener.assert_called_once()

    def test_open_with_beamer_is_a_usage_refusal(self):
        # R35 round 5: --beamer runs first and returns 0, so a --web deck given beside it
        # was neither checked nor opened while the run reported success.
        code, opener, err = self._main(["--web", self.clean, "--beamer", "main.tex", "--open"])
        self.assertEqual(code, 2)
        self.assertIn("--open", err)
        # R35 round 8: the refusal must name the real cause, --beamer, not a missing --web.
        self.assertIn("--beamer", err)
        opener.assert_not_called()

    def test_a_browser_that_does_not_open_leaves_the_clean_verdict(self):
        # The check passed; failing to launch a browser is said, not turned into a FAIL.
        for result, error in ((False, None), (None, tv.webbrowser.Error("no browser"))):
            with self.subTest(result=result, error=error):
                code, opener, err = self._main(["--web", self.clean, "--open"],
                                               opener_result=result, opener_error=error)
                self.assertEqual(code, 0)
                opener.assert_called_once()
                self.assertIn("clean.html", err)
                self.assertIn("by hand", err)


class TestMainDispatch(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_the_web_mode_exit_code_follows_the_finding(self):
        bad = os.path.join(self.dir, "bad.html")
        with open(bad, "w", encoding="utf8") as fh:
            fh.write('<script src="https://cdn.example/x.js"></script>')
        self.assertEqual(tv.main(["--web", bad]), 1)

    def test_the_web_mode_without_open_is_unchanged(self):
        clean = os.path.join(self.dir, "clean.html")
        with open(clean, "w", encoding="utf8") as fh:
            fh.write('<img src="data:image/png;base64,iVBORw0KG">')
        self.assertEqual(tv.main(["--web", clean]), 0)

    def test_the_beamer_mode_hands_off_to_latex(self):
        self.assertEqual(tv.main(["--beamer", "main.tex"]), 0)

    def test_a_clean_deck_passes_the_builtin_path(self):
        deck = os.path.join(self.dir, "clean.pptx")
        fx.build_pptx(deck, [{"body": fx.pic_xml() + fx.sp_xml(sz=1600), "notes": "x",
                              "media": True}])
        with mock.patch.object(tv, "find_plugin_validator", return_value=None):
            self.assertEqual(tv.main([deck, "--original", "gabarit.pptx"]), 0)

    def test_a_deck_below_the_font_floor_fails(self):
        deck = os.path.join(self.dir, "small.pptx")
        fx.build_pptx(deck, [{"body": fx.pic_xml() + fx.sp_xml("Body 1", "t", sz=1200),
                              "notes": "x", "media": True}])
        with mock.patch.object(tv, "find_plugin_validator", return_value=None):
            self.assertEqual(tv.main([deck, "--audience", "field"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
