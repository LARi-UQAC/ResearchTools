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
            lambda: {}, "the-token", PAGE, [], page_vars=vars_now)
        first = call(handler, "GET", "/")
        second = call(handler, "GET", "/")
        self.assertEqual(2, len(calls), "the view block was not rebuilt")
        self.assertIn('"poll_ms": 1000', first.text)
        self.assertIn('"poll_ms": 2000', second.text)

    def test_the_page_is_served_with_both_placeholders_filled(self):
        handler = rt_server.make_handler(
            lambda: {}, "the-token", PAGE, [],
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
