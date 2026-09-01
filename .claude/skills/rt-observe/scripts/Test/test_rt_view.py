"""
test_rt_view - the served page, checked without a browser.

What a browser proves (layout, overlap, contrast at render time) was measured by
hand with Playwright while the page was built. What a browser CANNOT prove is
that the page and the rest of the repository still agree tomorrow, and that is
what this suite is for. Every case here is a cannot-disagree check between two
files that would otherwise drift in silence:

- the token block inlined in the page against `assets/rt-tokens.css`, which is
  the shared file other emitters are meant to adopt. The page inlines it so it
  still renders without its server, and a copy with no check is the drift this
  repository keeps legislating against;
- the placeholders the page carries against the ones `rt_server` substitutes,
  because a renamed placeholder ships a page with `__RT_...__` printed on it;
- every `CFG.canvas.<key>` the page reads against `observe-config.json`, because
  a typo there is `undefined` arithmetic and a silently broken layout;
- every cell state `collect_mirrors` can emit against the page's own state
  table, because a state the legend does not know renders as a blank cell - and
  a blank cell reading as "fine" is the exact defect the matrix exists to
  prevent;
- the offline contract: no external URL of any kind, since the page is served
  with no network at render time.
"""
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import collect_mirrors  # noqa: E402
import rt_server  # noqa: E402
import rt_state  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent.parent
SKILL_ROOT = SCRIPTS.parent
REPO_ROOT = SKILL_ROOT.parent.parent.parent
PAGE = SKILL_ROOT / "assets" / "rt_state.html"
TOKENS = REPO_ROOT / "assets" / "rt-tokens.css"

TOKEN_LINE = re.compile(r"^\s*(--rt-[a-z0-9-]+)\s*:\s*(.+?);\s*$", re.MULTILINE)


def read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def token_blocks(css):
    """Split a stylesheet into its three token scopes, keyed by scope, each a
    dict of declarations. Comments are stripped first so a commented-out value
    is never read as a declaration."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    scopes = {}
    for label, pattern in (
            ("light", r":root\s*\{(.*?)\n\}"),
            ("media", r"prefers-color-scheme:\s*dark\).*?\{\s*:root:not\(\[data-theme=\"light\"\]\)\s*\{(.*?)\n  \}"),
            ("stamp", r":root\[data-theme=\"dark\"\]\s*\{(.*?)\n\}")):
        match = re.search(pattern, css, flags=re.DOTALL)
        if match:
            scopes[label] = dict(TOKEN_LINE.findall(match.group(1)))
    return scopes


class TokensDoNotDrift(unittest.TestCase):
    """The page inlines the shared token file. One truth, one check."""

    def setUp(self):
        self.page = read(PAGE)
        self.css = read(TOKENS)
        self.assertTrue(PAGE.is_file(), "%s is missing" % PAGE)
        self.assertTrue(TOKENS.is_file(), "%s is missing" % TOKENS)

    def test_every_shared_token_appears_in_the_page_with_the_same_value(self):
        shared = token_blocks(self.css)
        inlined = token_blocks(self.page)
        self.assertEqual(set(shared), set(inlined),
                         "the page and the shared file declare different scopes")
        for scope, declarations in shared.items():
            for name, value in declarations.items():
                with self.subTest(scope=scope, token=name):
                    self.assertIn(name, inlined[scope],
                                  "%s is not inlined in the page" % name)
                    self.assertEqual(
                        _norm(value), _norm(inlined[scope][name]),
                        "%s differs between the page and rt-tokens.css" % name)

    def test_the_page_declares_no_token_the_shared_file_lacks(self):
        # The other direction: a token invented in the page would never reach
        # the emitter that adopts the shared file next.
        shared = token_blocks(self.css)
        inlined = token_blocks(self.page)
        for scope, declarations in inlined.items():
            extra = set(declarations) - set(shared.get(scope, {}))
            self.assertEqual(set(), extra,
                             "%s declares %s, which rt-tokens.css does not"
                             % (scope, sorted(extra)))

    def test_the_drift_check_can_actually_fail(self):
        """The negative control. Without it, a comparison that silently matched
        nothing would pass on any pair of files."""
        planted = self.css.replace("--rt-alarm: #c0322f;",
                                   "--rt-alarm: #ff0000;")
        self.assertNotEqual(planted, self.css)
        shared = token_blocks(planted)
        inlined = token_blocks(self.page)
        self.assertNotEqual(shared["light"]["--rt-alarm"],
                            inlined["light"]["--rt-alarm"])

    def test_both_dark_scopes_carry_the_same_values(self):
        """A viewer's explicit choice and the OS setting must land on the same
        palette, or the toggle changes the design rather than the mode."""
        scopes = token_blocks(self.page)
        self.assertEqual({k: _norm(v) for k, v in scopes["media"].items()},
                         {k: _norm(v) for k, v in scopes["stamp"].items()})


def _norm(value):
    return re.sub(r"\s+", " ", value).strip()


class PageContract(unittest.TestCase):
    def setUp(self):
        self.page = read(PAGE)

    def test_the_placeholders_are_the_ones_the_server_substitutes(self):
        for placeholder in (rt_server.TOKEN_PLACEHOLDER,
                            rt_server.VIEW_CONFIG_PLACEHOLDER):
            with self.subTest(placeholder=placeholder):
                self.assertIn(placeholder, self.page,
                              "the server substitutes %s and the page never "
                              "carries it" % placeholder)

    def test_no_placeholder_is_left_unaccounted_for(self):
        # A page shipping an unsubstituted __RT_...__ prints it to the operator.
        known = {rt_server.TOKEN_PLACEHOLDER, rt_server.VIEW_CONFIG_PLACEHOLDER}
        found = set(re.findall(r"__RT_[A-Z_]+__", self.page))
        self.assertEqual(set(), found - known,
                         "the page carries placeholders nothing substitutes")

    def test_every_canvas_key_the_page_reads_is_configured(self):
        keys = set(re.findall(r"CFG\.canvas\.([a-z_]+)", self.page))
        self.assertTrue(keys, "no canvas keys found; the check is not checking")
        configured = rt_state.view_config(rt_state.load_config())["canvas"]
        for key in sorted(keys):
            with self.subTest(key=key):
                self.assertIn(key, configured,
                              "the page reads CFG.canvas.%s and "
                              "observe-config.json declares no such value" % key)

    def test_the_poll_interval_comes_from_the_config(self):
        self.assertIn("CFG.poll_ms", self.page)
        self.assertIn("poll_ms",
                      rt_state.view_config(rt_state.load_config()))

    def test_every_state_the_collector_can_emit_is_in_the_page_table(self):
        """A state with no entry renders as a blank cell, and a blank cell reads
        as 'fine'. That is the one misreading this matrix exists to prevent."""
        emitted = {collect_mirrors.OK, collect_mirrors.BY_DESIGN,
                   collect_mirrors.STUBBED, collect_mirrors.TRIMMED,
                   collect_mirrors.STALE, collect_mirrors.LOST,
                   collect_mirrors.ORPHAN, collect_mirrors.UNKNOWN}
        table = set(re.findall(r'"([a-z-]+)":\s*\{ code:', self.page))
        self.assertEqual(emitted, table,
                         "the page's state table and the collector disagree")
        order = re.search(r"var STATE_ORDER = \[(.*?)\];", self.page,
                          flags=re.DOTALL)
        self.assertIsNotNone(order)
        listed = set(re.findall(r'"([a-z-]+)"', order.group(1)))
        self.assertEqual(emitted, listed,
                         "a state is missing from the legend's order")

    def test_every_state_carries_a_code_or_is_the_silent_one(self):
        # Colour alone cannot carry these states: one man in twelve has a colour
        # vision deficiency, and the measured red-green pair collapses to
        # deuteran Delta E 4.1. So every state but `ok` has a two-letter code.
        codes = dict(re.findall(r'"([a-z-]+)":\s*\{ code: "([A-Z?]*)"',
                                self.page))
        self.assertEqual("", codes["ok"], "ok must be silent")
        for state, code in codes.items():
            if state == "ok":
                continue
            with self.subTest(state=state):
                self.assertTrue(code, "%s has no code" % state)
        self.assertEqual(len(set(codes.values())), len(codes),
                         "two states share a code: %s" % codes)

    def test_the_offline_contract_holds(self):
        """No CDN, no webfont, no network at render time. A page that reaches
        out is a page that breaks on the machine this toolkit is cloned to."""
        for url in re.findall(r'(?:src|href)="([^"]+)"', self.page):
            with self.subTest(url=url[:60]):
                self.assertFalse(url.startswith(("http://", "https://", "//")),
                                 "external reference: %s" % url)
        self.assertNotIn("@import", self.page)
        self.assertNotIn("fonts.googleapis", self.page)

    def test_the_page_script_parses(self):
        """The cheapest test here and the one that would have saved the most
        time. Measured 2026-08-31: a patch left one call unclosed, the whole
        script failed to parse, and NOTHING on the page rendered - and because
        an empty page mutates no DOM, the instrument watching for repaints
        reported it as perfectly stable. A false pass from a dead page.

        Skipped rather than failed where node is absent: the repository does not
        require it, and a check that cannot run must not read as a defect (R11).
        """
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not on PATH; the page script cannot be parsed")
        blocks = re.findall(r"<script>\n(.*?)</script>", read(PAGE), re.S)
        self.assertEqual(1, len(blocks), "expected exactly one script block")
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "page.js"
            script.write_text(blocks[0], encoding="utf-8")
            done = subprocess.run([node, "--check", str(script)],
                                  capture_output=True, text=True,
                                  errors="replace", timeout=60)
        self.assertEqual(0, done.returncode,
                         "the page script does not parse:\n" + done.stderr)

    def test_the_page_posts_an_id_and_never_a_command(self):
        """The whole safety argument of the action layer, on the page side.
        What the page sends decides nothing beyond WHICH whitelisted id runs, so
        the body keys are enumerated here: an argv, a path or a shell reaching
        the server would mean the whitelist had stopped being the only thing
        that decides what executes.

        The check is on the POSTED KEYS rather than on script names appearing
        anywhere in the file, because the page legitimately names install.ps1 in
        prose when it tells a reader how to fix a stale manifest."""
        allowed = set(["id", "token", "confirm", "dry_run", "target", "text"])
        bodies = re.findall(r"postAction\(\{([^}]*)\}", self.page, re.S)
        self.assertTrue(bodies, "no postAction call found; the finder is broken")
        for body in bodies:
            keys = set(re.findall(r"([a-z_]+):", body))
            with self.subTest(body=body.strip()[:60]):
                self.assertTrue(keys <= allowed, sorted(keys - allowed))
        script = re.search(r"<script>\n(.*?)</script>", self.page, re.S).group(1)
        for forbidden in ("-ExecutionPolicy", "cmd.exe", "argv:"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, script)
        posted = re.search(r"function postAction\(body\) \{(.*?)\n\}",
                           script, re.S).group(1)
        self.assertIn("body.token = TOKEN", posted)

    def test_every_action_id_the_page_names_is_declared(self):
        """The page names ids from the server's catalogue, so it should name
        almost none of its own. The one it does - the inbox id the compose
        dialog posts - is checked rather than exempted, since a renamed action
        would leave a Send button posting to nothing."""
        catalog = json.loads(read(SKILL_ROOT / "actions.json"))
        declared = set(a["id"] for a in catalog["actions"])
        named = set(re.findall(r"id: ['\"]([a-z_]+\.[a-z_]+)['\"]", self.page))
        self.assertTrue(named, "no action id found; the finder matched nothing")
        for action_id in named:
            with self.subTest(action=action_id):
                self.assertIn(action_id, declared)

    def test_the_id_finder_can_actually_fail(self):
        """The negative control for the case above."""
        planted = "var body = { id: 'nope.invented' };"
        found = set(re.findall(r"id: ['\"]([a-z_]+\.[a-z_]+)['\"]", planted))
        self.assertEqual({"nope.invented"}, found)

    def test_the_page_reads_mcp_as_its_own_section(self):
        """The 2026-08-31 split. MCP moved out of state.services onto its own
        timer, and a page still reading services.mcp would render an empty
        roster - which reads as 'no servers configured' (R8)."""
        self.assertIn("state.mcp", self.page)
        self.assertNotIn("services.mcp", self.page)

    def test_transient_action_state_is_never_kept_in_the_markup(self):
        """The rail is morphed on every poll, so an armed confirm or a typed
        message held in the DOM would be reconciled away mid-use. Both live in
        module state instead, and the compose box is a dialog appended to the
        body, outside every morphed container."""
        script = re.search(r"<script>\n(.*?)</script>", self.page, re.S).group(1)
        for name in ("var actionArmed", "var actionRunning", "var actionResult"):
            with self.subTest(name=name):
                self.assertIn(name, script)
        self.assertIn('createElement("dialog")', script)

    def test_an_unavailable_action_renders_a_reason_and_no_button(self):
        """A dead button is worse than an absent one: it teaches the operator
        that the dashboard is unreliable, and it hides the actual cause."""
        script = re.search(r"<script>\n(.*?)</script>", self.page, re.S).group(1)
        entry = re.search(r"function actionEntry\(entry\) \{(.*?)\n\}",
                          script, re.S).group(1)
        guard = entry.index("if (!entry.available)")
        self.assertLess(guard, entry.index("data-act-run"),
                        "the availability guard must come before any button")
        self.assertIn("unavailable here: ", entry)

    def test_the_quality_floor_is_declared(self):
        self.assertIn("prefers-reduced-motion", self.page)
        self.assertIn(":focus-visible", self.page)
        self.assertEqual(1, len(re.findall(r"<h1[ >]", self.page)),
                         "the document needs exactly one top-level heading")

    def test_nothing_renders_below_ten_pixels(self):
        """The audit of the rendered page measured a 9px floor, which is too
        small for a panel read mid-task. Ten is the floor now, and this keeps
        it: any literal font-size in the page, and the smallest scale token."""
        for size in re.findall(r"font-size:\s*(\d+)px", self.page):
            with self.subTest(size=size):
                self.assertGreaterEqual(int(size), 10)
        scale = token_blocks(read(PAGE))["light"]
        for name, value in scale.items():
            if not re.match(r"--rt-t\d+$", name):
                continue
            literal = re.match(r"^(\d+)px$", value.strip())
            if literal:
                with self.subTest(token=name):
                    self.assertGreaterEqual(int(literal.group(1)), 10)


class TabbedLayout(unittest.TestCase):
    """Phase 9. The sheet became two independent tab strips and stopped
    scrolling, and both claims are checked here as cannot-disagree comparisons
    between the markup and the script beside it.

    What a browser proves - that nothing actually overflows at 385, 768, 1080,
    1440 and 1920 - was measured with Playwright when the phase landed. What it
    cannot prove is that a later edit will not quietly drop a panel out of every
    strip, which is the failure this class exists to catch: a panel with no tab
    is not a smaller dashboard, it is a dashboard that answers a question it no
    longer asks."""

    def setUp(self):
        self.page = read(PAGE)
        # The BODY only. Cutting at <body> keeps a CSS selector such as
        # .tab[aria-selected="true"] out of the element count, and cutting at
        # the config block keeps an id mentioned in a JS string from being read
        # as an element that exists.
        self.markup = self.page.split("<body>")[1].split(
            '<script id="rt-view-config"')[0]
        self.script = re.search(r"<script>\n(.*?)</script>",
                                self.page, re.S).group(1)

    def _ids(self):
        return set(re.findall(r'\bid="([a-z0-9-]+)"', self.markup))

    def test_every_view_tab_has_a_pane_and_every_pane_a_tab(self):
        tabs = re.findall(r'data-view="([a-z]+)"', self.markup)
        panes = re.findall(r'id="pane-([a-z]+)"', self.markup)
        self.assertTrue(tabs, "no view tab found; the finder is broken")
        self.assertEqual(tabs, panes,
                         "the view strip and the panes disagree, in content or "
                         "in order")
        listed = re.search(r"var VIEW_TABS = \[(.*?)\];", self.script)
        self.assertIsNotNone(listed, "VIEW_TABS is not declared")
        self.assertEqual(tabs, re.findall(r'"([a-z]+)"', listed.group(1)),
                         "the script switches tabs the markup does not carry")

    def test_the_rail_strip_and_the_rail_renderer_name_the_same_panels(self):
        """The rail's six panels are named in two places - the static buttons
        and the renderer list. A third copy is how a tab starts pointing at a
        panel nobody builds, so the two that remain are compared."""
        buttons = re.findall(r'data-rail-tab="([a-z]+)"', self.markup)
        self.assertEqual(6, len(buttons), "expected six rail tabs")
        # Scoped to the RAIL_TABS block itself. Unscoped, this finder also
        # matched the session filter's own {id, label} entries, and reported a
        # disagreement that did not exist.
        block = re.search(r"var RAIL_TABS = \[(.*?)\n\];", self.script, re.S)
        self.assertIsNotNone(block, "RAIL_TABS is not declared")
        declared = re.findall(r'\{ id: "([a-z]+)", label:', block.group(1))
        self.assertEqual(buttons, declared,
                         "the rail strip and RAIL_TABS disagree")
        for name in buttons:
            with self.subTest(tab=name):
                self.assertIn('id="rtab-%s"' % name, self.markup,
                              "the script looks up rtab-%s by id" % name)

    def test_no_panel_was_dropped_in_the_move_to_tabs(self):
        """Every host the renderers write into still exists. A missing one is a
        silent panel: `getElementById` returns null, the render returns early,
        and the tab shows an empty box with no error anywhere."""
        hosts = ["mx-scroll", "mx-legend", "mx-detail", "mx-receipt", "mx-note",
                 "mx-filter", "fanout", "fleet", "fleet-note", "rail", "foot",
                 "head-id", "head-verdict", "theme", "theme-now", "tip"]
        present = self._ids()
        for host in hosts:
            with self.subTest(host=host):
                self.assertIn(host, present,
                              "%s no longer exists in the markup" % host)

    def test_the_finder_for_a_dropped_panel_can_actually_fail(self):
        """The negative control. Without it the case above passes on a page
        whose ids it never managed to read."""
        self.assertNotIn("mx-scroll-that-never-existed", self._ids())
        self.assertTrue(self._ids(), "no ids parsed at all")

    def test_the_tab_strips_are_wired_for_a_screen_reader(self):
        for strip in ("view-tabs", "rail-tabs"):
            with self.subTest(strip=strip):
                self.assertRegex(self.markup,
                                 r'role="tablist"[^>]*id="%s"' % strip)
        self.assertEqual(len(re.findall(r'role="tab"', self.markup)),
                         len(re.findall(r'aria-selected=', self.markup)),
                         "every tab carries aria-selected and nothing else does")
        ids = self._ids()
        for target in re.findall(r'aria-controls="([a-z0-9-]+)"', self.markup):
            with self.subTest(target=target):
                self.assertIn(target, ids,
                              "aria-controls points at %s, which does not exist"
                              % target)
        panels = re.findall(r'role="tabpanel"', self.markup)
        self.assertEqual(5, len(panels),
                         "four view panes plus the rail are tab panels")

    def test_which_tab_is_in_front_is_a_wrapped_per_viewer_convenience(self):
        """Same contract as the theme control: a browser that blocks storage
        THROWS on read, and a tab strip must never break the page it sits on."""
        for key in ('VIEW_KEY = "rt-observe-view"',
                    'RAIL_KEY = "rt-observe-rail"'):
            with self.subTest(key=key):
                self.assertIn(key, self.script)
        for name in ("storedChoice", "remember"):
            body = re.search(r"function %s\(.*?\n\}" % name, self.script, re.S)
            self.assertIsNotNone(body, "%s is not declared" % name)
            with self.subTest(name=name):
                self.assertIn("try {", body.group(0))
                self.assertIn("catch (error)", body.group(0))
                self.assertIn("localStorage", body.group(0))

    def test_the_tab_state_never_lives_in_the_morphed_markup(self):
        """The rail is rebuilt on every poll. The active panel is stamped on the
        STAGED node inside renderRail, so the morph carries it; an attribute
        written after the morph would survive exactly one poll."""
        body = re.search(r"function renderRail\(state\) \{(.*?)\n\}",
                         self.script, re.S).group(1)
        self.assertLess(body.index("panel.dataset.active"),
                        body.index("morph(document.getElementById"),
                        "the active panel must be stamped before the morph")
        self.assertIn("railPlaceholder", self.script)

    def test_the_page_itself_cannot_scroll(self):
        """The acceptance test of this phase, in its structural half: the sheet
        is the viewport and every overflow is handed to a pane. Measured in a
        browser as well - this is what keeps it true after the next edit."""
        self.assertIn("html, body { height: 100%; overflow: hidden; }",
                      self.page)
        for rule in (".pane .panel-body { flex: 1; min-height: 0; overflow: auto; }",
                     "#rail { flex: 1; min-height: 0; overflow-y: auto; }"):
            with self.subTest(rule=rule[:28]):
                self.assertIn(rule, self.page)
        self.assertNotIn("max-height: calc(100vh", self.page,
                         "a viewport-height cap inside a bounded pane can only "
                         "disagree with the pane")

    def test_the_canvas_is_never_solved_for_a_pane_that_is_not_on_screen(self):
        """A hidden element measures zero wide. Solved there, the layout would
        be cached under a shape describing no width and reused when the tab came
        back, which is a diagram drawn for a window that never existed."""
        canvas = re.search(r"function renderCanvas\(state\) \{(.*?)\n\}",
                           self.script, re.S).group(1)
        self.assertLess(canvas.index("getClientRects"),
                        canvas.index("getBoundingClientRect"),
                        "the visibility guard must come before any measurement")
        apply_view = re.search(r"function applyViewTab\(\) \{(.*?)\n\}",
                               self.script, re.S).group(1)
        self.assertIn("sim.shape = null", apply_view)
        self.assertIn("renderCanvas(lastState)", apply_view)


class InteractionLayer(unittest.TestCase):
    """Phase 10. One hover-detail implementation for every object in every tab,
    rounded corners from one token, and boxes that can be dragged without their
    edges coming loose.

    The rule under all of it is that a fact has ONE explanation. The fan-out
    edge reading `1 lost` and the matrix cell reading `LO` are two views of the
    same mirror, and two tooltip implementations are two chances to describe it
    differently - which is how a dashboard starts disagreeing with itself."""

    def setUp(self):
        self.page = read(PAGE)
        self.script = re.search(r"<script>\n(.*?)</script>",
                                self.page, re.S).group(1)

    def _fn(self, name):
        body = re.search(r"function %s\(.*?\n\}" % name, self.script, re.S)
        self.assertIsNotNone(body, "%s is not declared" % name)
        return body.group(0)

    def test_only_one_thing_in_the_page_writes_the_detail_panel(self):
        """Not one per panel. If a second writer appears, the two will drift -
        and the one that drifts is the one nobody is looking at."""
        self.assertEqual(1, len(re.findall(r"function showDetail\(", self.script)))
        self.assertEqual(1, len(re.findall(r"function placeTip\(", self.script)))
        self.assertEqual(1, self.script.count('tip.textContent = ""'),
                         "something other than showDetail empties the panel")
        self.assertEqual(1, self.script.count('tip.dataset.show = "1"'),
                         "something other than placeTip opens the panel")
        self.assertNotIn("function showTip(", self.script,
                         "the cell-only tooltip should have become the registry")

    def test_every_kind_that_opts_in_has_a_provider_and_the_reverse(self):
        used = set(re.findall(r'data-detail="([a-z]+)"', self.page))
        used |= set(re.findall(r'dataset\.detail = "([a-z]+)"', self.script))
        provided = set(re.findall(r'registerDetail\("([a-z]+)"', self.script))
        self.assertTrue(used, "no data-detail kind found; the finder is broken")
        self.assertEqual(used, provided,
                         "a kind opts in with no provider, or a provider exists "
                         "for a kind nothing uses")

    def test_the_kind_finder_can_actually_fail(self):
        """The negative control for the case above."""
        planted = 'registerDetail("invented", function () {})'
        self.assertEqual({"invented"},
                         set(re.findall(r'registerDetail\("([a-z]+)"', planted)))

    def test_every_state_a_collector_can_emit_has_something_to_say(self):
        """Part G asks that hovering explain the internal state. A state whose
        explanation is empty is a hover that opens a blank panel, which reads as
        'nothing is wrong here' - the misreading this matrix exists to stop."""
        means = dict(re.findall(r'"([a-z-]+)":\s*\{ code: "[A-Z?]*",\s*'
                                r'label: "[a-z ]+",\s*means: "([^"]+)"',
                                self.page))
        emitted = {collect_mirrors.OK, collect_mirrors.BY_DESIGN,
                   collect_mirrors.STUBBED, collect_mirrors.TRIMMED,
                   collect_mirrors.STALE, collect_mirrors.LOST,
                   collect_mirrors.ORPHAN, collect_mirrors.UNKNOWN}
        self.assertEqual(emitted, set(means),
                         "a state the collector emits carries no explanation")
        for state, text in means.items():
            with self.subTest(state=state):
                self.assertGreater(len(text), 20,
                                   "%s explains itself in %d characters"
                                   % (state, len(text)))
        cell = self._fn("registerDetail")  # the first registration is the cell
        self.assertIn("STATES[host.dataset.state]", self.script)
        self.assertIn("row.reason", cell + self.script)

    def test_the_worked_example_is_reachable_from_the_edge(self):
        """The plan names it: the fan-out edge reads `1 lost` and WHICH mirror
        was lost could not be reached from the diagram at all. The name now
        rides on the edge, and the thin line gets an invisible hit target,
        because a one-pixel path is not something a hand can find."""
        build = self._fn("buildGraph")
        self.assertIn("edge.problems.push", build)
        self.assertIn("name: row.name", build)
        draw = self._fn("drawGraph")
        self.assertIn('class="edge-hit"', draw)
        self.assertIn('data-detail="gedge"', draw)
        self.assertIn('data-detail="gnode"', draw)
        self.assertIn("edge.problems", self.script)

    def test_a_dragged_box_keeps_its_edges_attached(self):
        """Not by updating them: by there being nothing to update. Every path is
        emitted FROM the node coordinates on each draw, so a second copy of the
        geometry - the thing that could fall out of step - does not exist."""
        draw = self._fn("drawGraph")
        self.assertIn("a.x.toFixed(1)", draw)
        self.assertIn("b.y.toFixed(1)", draw)
        move = re.search(r'addEventListener\("pointermove", function \(event\) \{'
                         r'(.*?)\n\}\);', self.script, re.S).group(1)
        self.assertIn("node.x = clamp", move)
        self.assertIn("node.y = clamp", move)
        self.assertLess(move.index("node.y = clamp"), move.index("drawGraph("),
                        "the box must move before the drawing is redrawn")
        self.assertIn("sim.positions[node.id]", move)

    def test_a_drag_survives_the_next_poll(self):
        """A box put somewhere by hand that jumps back two seconds later is
        worse than one that cannot be moved: the operator learns the page is
        lying about something. The held-position path is what keeps it."""
        canvas = self._fn("renderCanvas")
        self.assertIn("sim.positions", canvas)
        self.assertIn("sim.graph = graph", canvas)
        self.assertIn("sim.dims = ", canvas)

    def test_rounded_corners_come_from_one_token(self):
        """One token, so the whole page turns the same corner. The token file
        itself is compared against the page by the drift case above."""
        self.assertIn("--rt-radius:", self.page)
        self.assertGreaterEqual(self.page.count("var(--rt-radius)"), 3)
        self.assertIn("svg.fanout .node rect { rx: var(--rt-radius); }",
                      self.page)

    def test_the_detail_row_cap_is_configured_and_not_written_in(self):
        """R0. An edge listing all 134 mirrors would be a second matrix, so the
        panel names a few and says how many more - and how many is a number the
        configuration owns."""
        self.assertIn("CFG.detail_rows", self.script)
        self.assertIn("detail_rows",
                      rt_state.view_config(rt_state.load_config()))


class RealTimeTab(unittest.TestCase):
    """Phase 11. The tab is adapter-fed, so the page's job is to draw what it is
    given and to say so when it is given nothing - an idle flow and an
    unreportable one look identical on a diagram and mean opposite things."""

    def setUp(self):
        self.page = read(PAGE)
        self.script = re.search(r"<script>\n(.*?)</script>",
                                self.page, re.S).group(1)

    def _fn(self, name):
        body = re.search(r"function %s\(.*?\n\}" % name, self.script, re.S)
        self.assertIsNotNone(body, "%s is not declared" % name)
        return body.group(0)

    def test_the_tab_draws_from_the_adapter_and_invents_no_state_list(self):
        """The state machine is named once, by the adapter. The page reads
        `flow_states` off the harness rather than carrying its own copy."""
        self.assertIn("harness.flow_states", self.script)
        self.assertIn("machine.flow_states", self.script)
        for state_id in ("session_start", "post_tool", "reasoning"):
            with self.subTest(state=state_id):
                self.assertNotIn('"%s", "' % state_id, self.script)

    def test_a_harness_that_reports_no_flow_is_never_drawn_as_an_agent(self):
        """An idle agent and an unreportable one look identical on a diagram and
        mean opposite things, so a session whose harness reports no timeline
        contributes no node at all, and a harness that is not ok says why."""
        model = self._fn("laneModel")
        self.assertIn('flow.status !== "ok"', model)
        live = self._fn("renderLive")
        self.assertIn("unavailable(box", live)

    def test_the_drawing_is_the_agent_flow_language(self):
        """Read from the reference the operator named rather than invented: an
        agent is a NODE with a token ring, its calls are labelled boxes on
        curved wires around it, a subagent hangs off its parent on a curve, and
        the shared memories sit apart."""
        graph = self._fn("agentGraph")
        for mark in ("fx-hex", "fx-ring", "fx-call", "fx-wire", "fx-spawn",
                     "fx-shared-box"):
            with self.subTest(mark=mark):
                self.assertIn(mark, graph)
        self.assertNotIn("function flowSvg(", self.script,
                         "the lane drawing was replaced, not left beside it")
        self.assertIn("function hexPath(", self.script)
        self.assertIn("function ringPath(", self.script)

    def test_the_layout_is_deterministic(self):
        """The same flow must draw the same picture twice. A force simulation
        would not, and a diagram that rearranges itself under a poll is one
        nobody can point at (R19 in spirit)."""
        graph = self._fn("agentGraph")
        for forbidden in ("Math.random", "Date.now("):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, graph)

    def test_a_tool_is_one_box_however_often_it_ran(self):
        """Grouping only CONSECUTIVE runs left a line of identical `Bash` boxes
        separated by whatever ran between them, which is a picture of the
        transcript rather than of the work. A tool is one box, carrying how many
        times it was called and when it last was."""
        events = self._fn("laneEvents")
        self.assertIn("var byName = {}", events)
        self.assertIn("group.count += 1", events)
        self.assertIn("group.calls.push", events,
                      "every individual call is kept for the hover panel")
        graph = self._fn("agentGraph")
        self.assertIn("fx-call-count", graph)
        self.assertIn("fx-call-at", graph)
        self.assertIn("clock(event.at)", graph,
                      "the box carries a timestamp, not just a count")

    def test_a_working_agent_is_visibly_alive(self):
        """The operator's test of this panel: while something is happening it
        has to LOOK like it. A still diagram fails that however correct it is,
        so a working node breathes and sends a ping outward - and an idle one
        does neither, which is what makes the difference readable."""
        graph = self._fn("agentGraph")
        self.assertIn("fx-agent--live", graph)
        self.assertIn("fx-ping", graph)
        self.assertIn("!REDUCED", graph,
                      "the ping is motion, and motion is a preference")
        self.assertIn('attributeName="r"', graph,
                      "a circle's radius is geometry, so the ping is SMIL "
                      "rather than CSS")
        self.assertIn("svg.flowgraph .fx-agent--live .fx-hex {", self.page)
        self.assertIn("@keyframes fx-breathe", self.page)
        self.assertIn("svg.flowgraph .fx-agent--idle .fx-hex {", self.page)

    def test_the_tools_drawn_are_the_most_recently_used(self):
        """Measured by the operator: `Write` went missing from a session that
        had just written a file, because the cap kept the first tools seen
        rather than the last ones used."""
        graph = self._fn("agentGraph")
        self.assertIn("ordered", graph)
        self.assertIn("CFG.flow_groups", graph,
                      "how many groups are drawn is configured (R0)")
        self.assertIn("flow_groups",
                      rt_state.view_config(rt_state.load_config()))

    def test_a_live_tool_is_lit_and_a_quiet_one_is_dimmed(self):
        """A tool that ran an hour ago and a tool running right now were the
        same box. Live means the agent is working AND this is the tool it last
        used - a session waiting for a prompt is using nothing."""
        events = self._fn("laneEvents")
        self.assertIn("group.live = true", events)
        graph = self._fn("agentGraph")
        self.assertIn('lane.state !== "idle"', graph)
        self.assertIn("fx-call--live", graph)
        self.assertIn("fx-call--quiet", graph)
        self.assertIn("svg.flowgraph .fx-call--quiet { opacity: 0.45; }",
                      self.page)
        self.assertIn("@keyframes fx-pulse", self.page)
        self.assertIn("prefers-reduced-motion", self.page,
                      "the pulse is motion, and motion is a preference")

    def test_the_hover_lists_one_line_per_call(self):
        """Asked for in these words: Bash, time, status, one line each. The box
        says how many and when last; the panel says each."""
        lines = self._fn("callLines")
        self.assertIn("clock(call.at)", lines)
        self.assertIn('"failed"', lines)
        self.assertIn('"ok"', lines)
        self.assertIn('"out"', lines)
        self.assertIn("CFG.detail_rows", self._fn("agentGraph"),
                      "how many lines a panel lists is configured (R0)")
        provider = re.search(r'registerDetail\("step", function \(host\) \{'
                             r"(.*?)\n\}\);", self.script, re.S).group(1)
        self.assertIn("detailCalls", provider)
        self.assertIn("detailFailures", provider)

    def test_a_tool_is_coloured_by_family_and_never_by_severity(self):
        """Colour carries IDENTITY here - a shell call told from a file write at
        a glance. The alarm hue stays reserved for the one state that must never
        be missed, which is what the deuteranopia measurement bought."""
        family = self._fn("toolFamily")
        for name in ("run", "read", "write", "net"):
            with self.subTest(family=name):
                self.assertIn('"%s"' % name, family)
                self.assertIn("--rt-tool-%s" % name, self.page)
        self.assertNotIn("--rt-alarm", self._fn("agentGraph"))

    def test_a_hook_is_drawn_as_a_hook_and_named(self):
        """Asked for in those words, twice: the thing itself rather than a
        label, and the NAME rather than the file that implements it."""
        glyph = self._fn("hookGlyph")
        self.assertIn("fx-hook", glyph)
        self.assertIn("a4.5,4.5 0 1,0", glyph, "the bend of the hook")
        graph = self._fn("agentGraph")
        self.assertIn("hookGlyph(", graph)
        self.assertIn("fx-hook-label", graph)
        self.assertIn("svg.flowgraph .fx-hook--blocked {", self.page)

    def test_a_skill_and_a_subagent_are_not_drawn_as_tool_calls(self):
        model = self._fn("laneModel")
        self.assertIn('kind: "subagent"', model)
        self.assertIn("flow.subagents", model)
        graph = self._fn("agentGraph")
        self.assertIn('event.kind === "skill" ? "skill"', graph)
        self.assertIn("fx-call--skill", self.page)
        self.assertIn("fx-agent--subagent", self.page)

    def test_the_shared_boxes_say_what_they_are_holding(self):
        """Asked for: the outbox, visible on the vault box and listed on hover,
        and kept in step with the daemon. It is rebuilt from the filesystem on
        every collection, so a note the daemon consumes leaves the list on the
        next poll - there is nothing to synchronise by hand, which is the only
        way two views of one queue stay honest."""
        held = self._fn("sharedState")
        self.assertIn("daemon.pending", held)
        self.assertIn("pending_total", held)
        self.assertIn("nothing waiting to be written", held,
                      "an empty outbox says so rather than showing a blank")
        self.assertIn("the daemon is not running", held,
                      "a queue nobody is draining is a different fact from an "
                      "empty one")
        self.assertIn("graph.nodes", held)
        graph = self._fn("agentGraph")
        self.assertIn("data-detail-lines", graph)
        self.assertIn("fx-shared-count", graph)
        self.assertIn("detailLines", self.script,
                      "one provider draws a sentence and a list alike")

    def test_the_shared_memories_are_reached_by_every_agent(self):
        shared = re.search(r"var SHARED_NODES = \[(.*?)\];", self.script,
                           re.S).group(1)
        for name in ("obsidian", "graphify", "internet"):
            with self.subTest(node=name):
                self.assertIn('id: "%s"' % name, shared)
        links = self._fn("sharedLinks")
        self.assertIn('to: "internet"', links)
        self.assertIn('to: "obsidian"', links)
        self.assertIn("mcp:", links)

    def test_history_stays_and_can_be_picked_back_up(self):
        """Any past call can be picked back up and held highlighted. The picked
        step lives in a module variable, because the graph is rebuilt on every
        poll."""
        self.assertIn("var pickedStep = null", self.script)
        self.assertIn("fx-call--picked", self.script)
        self.assertIn("svg.flowgraph .fx-call--picked rect {", self.page)
        self.assertIn("data-step-id", self.script)

    def test_the_legend_names_what_the_drawing_actually_uses(self):
        """Four marks, four meanings, said once. A legend that names a mark the
        drawing stopped using is worse than none."""
        legend = self._fn("flowLegend")
        for name in ("agent", "call", "hook", "memory"):
            with self.subTest(mark=name):
                self.assertIn('"%s"' % name, legend)
                self.assertIn(".fx-legend-mark--%s" % name, self.page)
        for gone in ("--input", "--output"):
            with self.subTest(gone=gone):
                self.assertNotIn(".fx-legend-mark%s" % gone, self.page)

    def test_each_budget_has_its_own_colour_and_full_outranks_it(self):
        """Three bars, three colours, and the agent ring drawn in the SESSION
        colour so a ring and its bar read as one measurement. Full is orange in
        all three, which is why orange is not one of the three: a bar cannot be
        full of itself."""
        for key in ("session", "week", "supplement"):
            with self.subTest(budget=key):
                self.assertIn(".live-bar--%s i { background: "
                              "var(--rt-budget-%s); }" % (key, key), self.page)
        self.assertIn(".live-bar--full i { background: var(--rt-budget-full); }",
                      self.page)
        meter = self._fn("meterRow")
        self.assertIn('"live-bar live-bar--" + spec.key', meter,
                      "the bar takes its colour from which budget it is")
        self.assertIn("svg.flowgraph .fx-ring {", self.page)
        ring = re.search(r"svg\.flowgraph \.fx-ring \{(.*?)\}", self.page,
                         re.S).group(1)
        self.assertIn("var(--rt-budget-session)", ring,
                      "the ring is the session bar, drawn round the agent")
        self.assertIn("svg.flowgraph .fx-ring--full { stroke: "
                      "var(--rt-budget-full); }", self.page)

    def test_the_token_figure_under_an_agent_is_a_figure_not_a_state(self):
        """It is read, not judged, so it takes the one colour reserved for a
        number rather than any of the status hues."""
        spend = re.search(r"svg\.flowgraph \.fx-agent-spend \{(.*?)\}",
                          self.page, re.S).group(1)
        self.assertIn("var(--rt-budget-figure)", spend)
        graph = self._fn("agentGraph")
        self.assertIn("fx-agent-spend", graph)
        self.assertIn("thousands(tokens.held)", graph)

    def test_nothing_is_drawn_outside_the_figure(self):
        """Reported: boxes left the frame. The frame was a guess and the content
        was not, so every placement now reports its extremities and the viewBox
        is whatever contains them - and a call box is clamped into the band
        between its agent and the shared column before it is drawn."""
        graph = self._fn("agentGraph")
        self.assertIn("var mark = function (x, y)", graph)
        self.assertIn("bounds.minX", graph)
        self.assertIn("Math.max(leftEdge + callW / 2", graph,
                      "a call box is clamped, not merely positioned")
        self.assertIn("vx.toFixed(0)", graph,
                      "the frame comes from the measured bounds")
        self.assertNotIn("viewBox=\"0 0 ", graph,
                         "a frame starting at the origin is the guess that put "
                         "boxes outside it")

    def test_a_hook_that_fired_is_bold_and_a_quiet_one_is_not(self):
        """Asked for in those words. The column lists every hook that COULD run
        on this agent, and the ones that did are bold - a declared hook that has
        not fired since the tail began is not a hook that is missing."""
        rows = self._fn("hookRows")
        self.assertIn("fired: true", rows)
        self.assertIn("fired: false", rows)
        self.assertIn("no firing inside the transcript tail", rows)
        self.assertIn(
            "svg.flowgraph .fx-hook-label--fired { fill: #cfe0e8; "
            "font-weight: 700; }", self.page,
            "a fired hook is bold, and a declared one is not")

    def test_a_failed_result_is_marked_where_it_happened(self):
        """`Fail is a result, and it is impossible to track` - the operator. A
        failure now marks the call it answers, with a TRIANGLE as well as a
        colour, so it survives a colour vision deficiency for the same reason
        the matrix carries two-letter codes."""
        events = self._fn("laneEvents")
        self.assertIn("lastCall.failed = !!step.error", events)
        self.assertIn("group.failures += 1", events,
                      "a group says how many of its calls failed")
        mark = self._fn("failMark")
        self.assertIn("fx-fail", mark)
        self.assertIn(" Z", mark, "a closed triangle, not a line")
        graph = self._fn("agentGraph")
        self.assertIn("event.failed ? failMark(", graph)
        self.assertIn("hook.exit ? failMark(", graph)
        self.assertIn("svg.flowgraph .fx-fail { fill: var(--rt-alarm); }",
                      self.page)
        self.assertIn("fx-wire--failed", graph)

    def test_the_canvas_is_its_own_surface(self):
        """The sheet is a drafting ground; this tab is an instrument panel, and
        the reference reads as one because the drawing is lit against a dark
        field. The glow and the ring gradient are SVG, so the graph stays one
        self-contained element with no external anything."""
        self.assertIn(".live-graph {", self.page)
        self.assertIn("radial-gradient", self.page)
        graph = self._fn("agentGraph")
        self.assertIn('id="fxglow"', graph)
        self.assertIn("feGaussianBlur", graph)
        self.assertNotIn('id="fxring"', graph,
                         "the ring takes the session budget colour now, so the "
                         "gradient it used to borrow is a def nothing "
                         "references")

    def test_the_refresh_input_is_as_wide_as_the_maximum_inputs(self):
        """Measured by the operator: at five characters it could not be typed
        into, which is how a control becomes decoration."""
        refresh = re.search(r"\.refresh input \{(.*?)\n\}", self.page,
                            re.S).group(1)
        meter = re.search(r"\.live-meter input \{(.*?)\n\}", self.page,
                          re.S).group(1)
        self.assertIn("width: 8ch;", refresh)
        self.assertIn("width: 7ch;", meter)
        self.assertIn("appearance: textfield;", refresh,
                      "the browser spinner ate the width the value needed")
        script = self.script
        self.assertIn("document.activeElement !== input", script,
                      "the value is rewritten on every render, except while "
                      "the operator is typing into it")

    def test_the_live_step_and_the_travelled_edges_are_marked(self):
        machine = re.search(r"function machineSvg\(states, live, travelled, "
                            r"hooks, declared\) \{(.*?)\n\}", self.script,
                            re.S).group(1)
        self.assertIn("m-box--live", machine)
        self.assertIn("m-edge--travelled", machine)
        self.assertIn("animateMotion", machine)
        self.assertIn("!REDUCED", machine,
                      "the only moving thing on the page must respect reduced "
                      "motion")
        self.assertIn("svg.machine .m-edge--travelled {", self.page)

    def test_the_runner_is_the_one_accent_that_is_not_a_status(self):
        """A second STATUS hue was measured to collapse under deuteranopia on
        this surface, which is why the eight matrix states carry codes. The
        runner is exempt because nothing is decided by seeing it: it marks
        motion, and the step it marks is already filled dark."""
        self.assertIn("--rt-runner:", self.page)
        self.assertIn("svg.machine .m-runner { fill: var(--rt-runner); }",
                      self.page)
        self.assertEqual(1, self.page.count("var(--rt-runner)"),
                         "the runner colour must mark exactly one thing")

    def test_the_flow_cap_and_the_idle_threshold_are_configured(self):
        config = rt_state.load_config()
        self.assertIn("flow_steps", config["caps"])
        self.assertIn("session_idle", config["staleness_seconds"])


class SessionFilter(unittest.TestCase):
    """The Sessions strip and the Real-Time Process tab ask the same question -
    is this session working, waiting, or unreportable - so they must not answer
    it twice. One classifier, one control, both panels."""

    def setUp(self):
        self.page = read(PAGE)
        self.script = re.search(r"<script>\n(.*?)</script>",
                                self.page, re.S).group(1)

    def _fn(self, pattern):
        found = re.search(pattern, self.script, re.S)
        self.assertIsNotNone(found, "not found: %s" % pattern)
        return found.group(1)

    def test_one_classifier_serves_both_panels(self):
        self.assertEqual(1, len(re.findall(r"function sessionClass\(",
                                           self.script)))
        self.assertEqual(1, len(re.findall(r"function renderFilter\(",
                                           self.script)))
        for panel in ("renderFleet", "renderLive"):
            body = self._fn(r"function %s\(state\) \{(.*?)\n\}" % panel)
            with self.subTest(panel=panel):
                self.assertIn("sessionShown(session)", body)
                self.assertIn("hiddenNote(hidden)", body)

    def test_the_three_classes_are_different_facts_and_stay_apart(self):
        """`no flow reported` is a statement about the HARNESS, `idle` is one
        about the session. Merged into "nothing happening" they would hide a
        Copilot session that is running hard."""
        listed = self._fn(r"var SESSION_CLASSES = \[(.*?)\];")
        self.assertEqual(["active", "idle", "noflow"],
                         re.findall(r'id: "([a-z]+)"', listed))
        body = self._fn(r"function sessionClass\(session\) \{(.*?)\n\}")
        self.assertLess(body.index('flow.status !== "ok"'),
                        body.index('flow.state === "idle"'),
                        "a harness that reports nothing cannot be called idle")

    def test_a_filtered_panel_says_how_many_it_is_hiding(self):
        """A filter that hides without saying turns an empty panel into a false
        answer - the same defect as a blank matrix cell reading as fine."""
        body = self._fn(r"function hiddenNote\(hidden\) \{(.*?)\n\}")
        self.assertIn("hidden by the filter", body)
        self.assertIn("Every session here is hidden by the filter above",
                      self.script)

    def test_blocked_storage_shows_everything(self):
        """The safe direction. A filter defaulting to hidden is how a session
        goes missing on a machine whose browser blocks site data."""
        body = self._fn(r"function storedFilter\(\) \{(.*?)\n\}")
        self.assertIn("catch (error)", body)
        self.assertIn("on[entry.id] = true", body)
        self.assertIn('SESSION_FILTER_KEY = "rt-observe-sessions"', self.script)

    def test_both_panels_carry_the_control(self):
        markup = self.page.split("<body>")[1].split(
            '<script id="rt-view-config"')[0]
        for host in ("fleet-filter", "live-filter"):
            with self.subTest(host=host):
                self.assertIn('id="%s"' % host, markup)
                self.assertIn('renderFilter("%s")' % host, self.script)


class ServedPage(unittest.TestCase):
    """The server's own handling of the page, with no socket involved."""

    def test_the_view_block_is_rebuilt_per_request_not_at_startup(self):
        """Measured 2026-08-31 on a running dashboard: the markup was re-read
        from disk on every request while the view config was serialised ONCE at
        startup. Adding a key to observe-config.json and refreshing therefore
        gave a page whose script read `undefined` for it - which produced NaN
        arithmetic and an animation that silently ran one frame instead of
        failing. Two files read at different times are two truths."""
        from test_rt_state import call
        calls = []

        def vars_now():
            calls.append(1)
            return {rt_server.VIEW_CONFIG_PLACEHOLDER:
                    json.dumps({"poll_ms": 1000 * len(calls), "canvas": {}})}

        handler = rt_server.make_handler(
            lambda max_age=None: {}, "the-token", PAGE, [], page_vars=vars_now)
        first = call(handler, "GET", "/")
        second = call(handler, "GET", "/")
        self.assertEqual(2, len(calls), "the view block was not rebuilt")
        self.assertIn('"poll_ms": 1000', first.text)
        self.assertIn('"poll_ms": 2000', second.text)

    def test_the_page_is_served_with_both_placeholders_filled(self):
        handler = rt_server.make_handler(
            lambda max_age=None: {}, "the-token", PAGE, [],
            page_vars={rt_server.VIEW_CONFIG_PLACEHOLDER:
                       json.dumps({"poll_ms": 2000, "canvas": {}})})
        # Drive _page through the same in-memory harness test_rt_state uses,
        # imported here rather than duplicated.
        from test_rt_state import call
        response = call(handler, "GET", "/")
        self.assertEqual(200, response.status)
        self.assertNotIn("__RT_", response.text)
        self.assertIn("the-token", response.text)
        self.assertIn('"poll_ms": 2000', response.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
