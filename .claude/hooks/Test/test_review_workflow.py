"""
test_review_workflow - guards for .github/workflows/review.yml and scripts/ci/review_mirror.py.

Offline: no network, no `gh`, no model. The workflow is read as text, the script is loaded by
path and driven through an injected `gh` runner.

Why it exists (PR #67 review round 1, R15/R20/R23). The workflow holds a billed API key beside
an LLM that reads untrusted diffs, and nothing tested its properties: the "no Bash" claim was
false while `track_progress` was set (the action's tag mode adds Bash git commands and edit
rights, measured from the action source at the pinned SHA), the checkout kept the job token in
git config, and the Issue mirror was untestable shell inside YAML. Every static check below is
proven able to FAIL on a planted violation, since a check that cannot fail proves nothing.
"""
import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
WORKFLOW = REPO / ".github" / "workflows" / "review.yml"
SCRIPT = REPO / "scripts" / "ci" / "review_mirror.py"
CONFIG = REPO / "scripts" / "ci" / "review-mirror.json"

# Tools the model session must never have. The config holds an ALLOWLIST (allowed_tools), so this
# deny list is restated here on purpose: a config edit that lets one of these in is caught here.
FORBIDDEN_TOOLS = ("Bash", "Write", "Edit", "MultiEdit", "NotebookEdit", "Agent", "Task")
AGENT_ACTION_INPUTS_BANNED = ("plugins:", "plugin_marketplaces:", "track_progress:", "use_sticky_comment:")
READ_TOOLS = ("Read", "Grep", "Glob")
DENIED_ROOTS = ("/proc", "/sys", "/run")
# What GitHub still renders as a code span: the same run of backticks opens and closes it, the
# opener is not backslash-escaped, and it never crosses a blank line. Kept independent of the
# script's own pattern, so the test can disagree with the code it checks.
GFM_SPAN = re.compile(r"(?<![`\\])(`+)(?!`)((?:(?!\n[ \t]*\n).)+?)(?<!`)\1(?!`)", re.S)


def load_module():
    """Load scripts/ci/review_mirror.py by path (it is not on any import path)."""
    spec = importlib.util.spec_from_file_location("review_mirror", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def strip_comments(text):
    """Workflow text without full-line comments, so prose never satisfies a check."""
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def uses_lines(text):
    """Every `uses:` line of the workflow with its reference."""
    return re.findall(r"^\s*-?\s*uses:\s*(\S+)(.*)$", strip_comments(text), flags=re.M)


def run_blocks(text):
    """Bodies of every `run: |` block, as a list of strings."""
    blocks, lines, i = [], strip_comments(text).splitlines(), 0
    while i < len(lines):
        m = re.match(r"^(\s*)(-\s+)?run:\s*\|\s*$", lines[i])
        if m:
            indent, body, i = len(m.group(1)) + len(m.group(2) or ""), [], i + 1
            while i < len(lines) and (not lines[i].strip() or len(lines[i]) - len(lines[i].lstrip()) > indent):
                body.append(lines[i])
                i += 1
            blocks.append("\n".join(body))
        else:
            i += 1
    return blocks


def job_text(text, name):
    """Text of one top-level job, from `  name:` to the next job or end of file."""
    m = re.search(r"^  %s:\n(.*?)(?=^  [a-z][a-z-]*:\n|\Z)" % re.escape(name), text, flags=re.S | re.M)
    return m.group(1) if m else ""


def claude_args(text):
    """The folded text of the `claude_args:` input."""
    m = re.search(r"claude_args:\s*>-?\n((?:\s{12,}.*\n?)+)", text)
    return " ".join(m.group(1).split()) if m else ""


class TestWorkflowStatic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_every_uses_is_a_40_hex_sha_with_a_version_comment(self):
        found = uses_lines(self.text)
        self.assertGreaterEqual(len(found), 2)
        for ref, tail in found:
            self.assertRegex(ref, r"@[0-9a-f]{40}$", ref)
            self.assertIn("#", tail, "no version comment after " + ref)

    def test_pin_finder_reports_an_unpinned_reference(self):
        bad = "    steps:\n      - uses: actions/checkout@v4\n"
        self.assertEqual(len(uses_lines(bad)), 1)
        self.assertNotRegex(uses_lines(bad)[0][0], r"@[0-9a-f]{40}$")

    def test_no_pr_controlled_template_inside_a_run_block(self):
        for block in run_blocks(self.text):
            self.assertNotRegex(block, r"\$\{\{\s*github\.event\.pull_request\.", block[:80])
            self.assertNotRegex(block, r"\$\{\{\s*github\.head_ref", block[:80])

    def test_run_block_finder_sees_a_planted_template(self):
        bad = "      - run: |\n          echo ${{ github.event.pull_request.title }}\n"
        bad = "    steps:\n" + bad
        self.assertTrue(any("github.event.pull_request" in b for b in run_blocks(bad)))

    def test_agent_step_names_no_forbidden_tool_and_pins_the_tool_list(self):
        args = claude_args(self.text)
        self.assertTrue(args, "claude_args not found")
        for tool in FORBIDDEN_TOOLS:
            self.assertNotRegex(args.split("--disallowedTools")[0], r"\b%s\b" % tool)
        self.assertIn('--tools "Skill,Read,Grep,Glob"', args)
        self.assertNotIn("mcp__", args.split("--disallowedTools")[0])

    def test_disallowed_tools_cover_three_tools_times_three_roots(self):
        args = claude_args(self.text)
        for tool in READ_TOOLS:
            for root in DENIED_ROOTS:
                self.assertIn("%s(/%s/**)" % (tool, root), args)

    def test_tool_finder_reports_planted_bash(self):
        planted = 'claude_args: >-\n            --allowedTools "Skill,Bash(git add:*)"\n'
        self.assertIn("Bash", claude_args(planted))

    def test_no_plugin_or_tag_mode_input_is_set(self):
        body = strip_comments(self.text)
        for key in AGENT_ACTION_INPUTS_BANNED:
            self.assertNotIn(key, body, key)

    def test_every_checkout_drops_the_stored_credential(self):
        body = strip_comments(self.text)
        self.assertEqual(body.count("actions/checkout@"), body.count("persist-credentials: false"))
        self.assertGreaterEqual(body.count("persist-credentials: false"), 1)

    def test_secret_is_named_only_in_the_key_check_and_the_agent_input(self):
        lines = [ln for ln in strip_comments(self.text).splitlines() if "secrets.ANTHROPIC_API_KEY" in ln]
        self.assertEqual(len(lines), 2, lines)

    def test_no_job_holds_issues_write_and_the_agent_input(self):
        review, mirror = strip_comments(job_text(self.text, "review")), strip_comments(job_text(self.text, "mirror"))
        self.assertTrue(review and mirror)
        self.assertNotIn("issues: write", review)
        self.assertIn("issues: write", mirror)
        self.assertNotIn("secrets.", mirror)
        self.assertNotIn("claude-code-action", mirror)

    def test_review_job_holds_pull_requests_write_and_contents_read_only(self):
        review = job_text(self.text, "review")
        self.assertIn("pull-requests: write", review)
        self.assertNotIn("contents: write", self.text)

    def test_missing_secret_is_a_clean_skip_and_mirror_waits_for_reviewed(self):
        body = strip_comments(self.text)
        self.assertIn("steps.key.outputs.present", body)
        self.assertRegex(job_text(self.text, "mirror"), r"if:.*needs\.review\.outputs\.reviewed")
        self.assertIn("reviewed:", job_text(self.text, "review"))

    def test_workflow_calls_a_script_that_exists(self):
        called = set(re.findall(r"scripts/ci/[A-Za-z0-9_.-]+\.py", strip_comments(self.text)))
        self.assertTrue(called)
        for rel in called:
            self.assertTrue((REPO / rel).is_file(), rel)

    def test_the_agent_step_has_a_spend_cap_read_from_one_env_value(self):
        # Code review round 4: only the 30-minute job timeout bounded the billed step.
        args = claude_args(self.text)
        self.assertIn("--max-budget-usd ${{ env.MAX_BUDGET_USD }}", args)
        self.assertRegex(strip_comments(self.text), r'(?m)^env:\n  MAX_BUDGET_USD: "[0-9.]+"')

    def test_truncation_keeps_a_single_oversized_line_and_drops_partial_utf8(self):
        # Code review round 1: `head -c N | sed '$d'` deleted the only line of a one-line diff and
        # could hand the model half a multibyte character. Static check of the guard, since a shell
        # snippet is not run here.
        step = " ".join(b for b in run_blocks(self.text) if "pr.full.diff" in b)
        self.assertRegex(step, r"iconv -c -f UTF-8 -t UTF-8 > \S+ \|\| true")   # glibc iconv -c exits 1 when it drops bytes
        self.assertIn('tail -c1 "$RUNNER_TEMP/pr.diff"', step)                   # drop the last line only if it is partial
        self.assertRegex(step, r'wc -l < "\$RUNNER_TEMP/pr\.diff"\)" -gt 0 \]')
        self.assertIn("NO REVIEWABLE CHANGE", step)

    def test_diff_excludes_generated_mirrors_and_names_them(self):
        body = strip_comments(self.text)
        for pathspec in (":(exclude).continue", ":(exclude)CONVENTIONS.md", ":(exclude)AGENTS.md"):
            self.assertIn(pathspec, body)


class TestConfig(unittest.TestCase):
    def test_every_value_carries_provenance(self):
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        for key, entry in cfg.items():
            self.assertIn("provenance", entry, key)
            self.assertIn("value", entry, key)

    def test_argument_patterns_and_retry_delay_come_from_the_config(self):
        # Code review round 6, R0: the digit caps and the sha length were literals in the code.
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        for key in ("pr_pattern", "comment_id_pattern", "sha_pattern", "gh_retry_delay_seconds"):
            self.assertIn(key, cfg)
            self.assertIn("provenance", cfg[key])
        code = SCRIPT.read_text(encoding="utf-8")
        for literal in ("{1,9}", "{1,15}", "{40}"):
            self.assertNotIn(literal, code)

    def test_a_diff_with_nothing_to_review_does_not_start_the_billed_step(self):
        # Code review round 6: the NO REVIEWABLE CHANGE placeholder still paid for a session.
        body = strip_comments(WORKFLOW.read_text(encoding="utf-8"))
        self.assertIn("empty=true", body)
        for name in ("Run security-review and code-review", "Verify the session had no forbidden tool",
                     "Extract the reply", "Post or update the PR comment"):
            step = re.search(r"- name: %s\n(.*?)(?=\n      - name:|\n  mirror:|\Z)" % re.escape(name), body, re.S)
            self.assertIsNotNone(step, name)
            self.assertIn("steps.diff.outputs.empty != 'true'", step.group(1), name)

    def test_allowed_tool_list_is_exactly_the_four_and_matches_the_workflow(self):
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        allowed = cfg["allowed_tools"]["value"]
        self.assertEqual(sorted(allowed), sorted(["Skill", "Read", "Grep", "Glob"]))
        for tool in FORBIDDEN_TOOLS:
            self.assertNotIn(tool, allowed)
        args = claude_args(WORKFLOW.read_text(encoding="utf-8"))
        self.assertIn('--tools "%s"' % ",".join(allowed), args)

    def test_missing_key_is_a_named_error(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.json"
            p.write_text("{}", encoding="utf-8")
            with self.assertRaises(mod.ConfigError) as ctx:
                mod.load_config(p)
            self.assertIn("review_marker", str(ctx.exception))

    def test_missing_file_is_a_named_error(self):
        mod = load_module()
        with self.assertRaises(mod.ConfigError):
            mod.load_config(Path("no-such-config.json"))

    def test_an_entry_without_the_value_wrapper_is_a_named_error(self):
        # Code review round 4: `"gh_retries": 2` raised TypeError (and a string entry passed the
        # `in` test by accident) instead of the named ConfigError R3 asks for.
        mod = load_module()
        good = json.loads(CONFIG.read_text(encoding="utf-8"))
        for bad in (2, "valued", None, ["value"], {"provenance": "x"}):
            cfg = dict(good, gh_retries=bad)
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "c.json"
                p.write_text(json.dumps(cfg), encoding="utf-8")
                with self.assertRaises(mod.ConfigError) as ctx:
                    mod.load_config(p)
                self.assertIn("gh_retries", str(ctx.exception))

    def test_no_unused_pattern_is_left_in_the_sanitiser(self):
        # Code review round 4: a dead lookahead regex invites a "fix" that brings the bypass back.
        self.assertNotIn("_HTML", SCRIPT.read_text(encoding="utf-8"))


class TestPureLogic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_module()
        cls.cfg = cls.mod.load_config(CONFIG)

    def test_issue_number_only_from_a_line_starting_with_fixes_or_closes(self):
        f = self.mod.find_issue_number
        self.assertEqual(f("Intro\nFixes #12\n"), 12)
        self.assertEqual(f("  closes #7"), 7)
        self.assertIsNone(f("this prefixes #12 nothing"))
        self.assertIsNone(f('He said "Fixes #12" in passing'))
        self.assertIsNone(f(""))
        self.assertIsNone(f(None))
        # Code review round 1: a template example in a fence or an HTML comment selects nothing.
        self.assertIsNone(f("```\nFixes #1\n```\nno real link"))
        self.assertIsNone(f("<!--\nFixes #1\n-->\n"))
        self.assertIsNone(f("    Fixes #5\n"))      # code review round 3: an indented code block
        self.assertIsNone(f("\tFixes #5\n"))
        # Code review round 6: an HTML comment closed by an indented line must end the comment,
        # and a link on the same line as a closed comment still counts.
        self.assertEqual(f("<!--\n  Describe\n    -->\nFixes #65"), 65)
        self.assertEqual(f("<!-- x --> Fixes #65"), 65)
        self.assertEqual(f("<!-- a -->\n<!-- b\n-->\nCloses #8"), 8)
        # GitHub's own closing keywords and a list marker, but never a quote or a mid-line mention.
        for body, number in (("- Fixes #65", 65), ("* closes #3", 3), ("Resolves #7", 7), ("fixed #4", 4),
                             ("Closed #6", 6), ("resolve #2", 2), ("fix #9", 9)):
            self.assertEqual(f(body), number, body)
        for body in ("> Fixes #65", "see Fixes #65 here", "refixes #5", "Fixes: #5 maybe", "Fixes #5x"):
            self.assertIsNone(f(body), body)
        self.assertEqual(f("```\nFixes #1\n```\nFixes #9\n"), 9)
        self.assertEqual(f("<!-- Fixes #1 -->\nCloses #4"), 4)

    def test_sanitize_neutralises_mentions_refs_links_images_and_html(self):
        s = self.mod.sanitize
        out = s("ping @alice and @org/team, see #123 and acme/tool#9, "
                "[click](https://evil.example/x) ![img](https://evil.example/i.png) "
                "<img src=x> <!-- hidden --> https://bare.example/p")
        self.assertNotRegex(out, r"(?<!`)@alice")
        self.assertNotRegex(out, r"(?<!`)@org")
        self.assertNotRegex(out, r"(?<![`/\w])#123")
        self.assertNotRegex(out, r"(?<!`)acme/tool#9")
        self.assertNotIn("](", out)
        self.assertNotIn("<img", out)
        self.assertNotIn("<!--", out)
        self.assertNotRegex(out, r"(?<!`)https://bare\.example")
        self.assertIn("click", out)
        self.assertIn("img", out)

    def test_an_unmatched_backtick_does_not_shield_a_mention_or_reference(self):
        # Security review round 1: an opening backtick that is never closed is literal text in
        # GFM, so the old "previous character is a backtick" lookbehind left what followed live.
        s = self.mod.sanitize
        span = GFM_SPAN
        for raw in ("`@victim look", "`#12 x", "`owner/repo#5 y", "a ` b @victim", "``@victim",
                    "`a\n\n@victim ping`",          # code review round 1: a span never crosses a blank line
                    "\\`@victim` tail",             # code review round 1: a backslash-escaped backtick opens nothing
                    "``@victim`",                   # security round 2: a longer opening run needs an equal closer
                    "`a\n- @victim`"):              # a list line ends the paragraph, so no span crosses it
            out = s(raw)
            live = span.sub("", out)  # what GitHub still renders as live text
            self.assertNotIn("@victim", live, raw)
            self.assertNotRegex(live, r"(?<![\w/])#12", raw)
            self.assertNotIn("owner/repo#5", live, raw)
            self.assertEqual(s(s(raw)), s(raw), "not idempotent: " + raw)

    def test_balanced_code_spans_are_kept_as_one_clean_span(self):
        # Security round 3: every span in the output is rebuilt by the sanitiser, so a run of
        # backticks inside one becomes an apostrophe and the span is always a single backtick pair.
        s = self.mod.sanitize
        text = "call `foo()` and `@name` and ``a ` b`` then #7"
        out = s(text)
        self.assertIn("`foo()`", out)
        self.assertIn("`@name`", out)
        self.assertIn("`a ' b`", out)
        self.assertNotRegex(out, r"(?<![`\w/])#7")

    def test_autolinks_in_prose_are_wrapped_in_every_form(self):
        # Code review round 1: a URL in parentheses, www. and GH-123 autolink in plain prose.
        span = GFM_SPAN
        out = self.mod.sanitize("see (https://evil.example/x) and www.evil.example/y and GH-123 done")
        live = span.sub("", out)
        self.assertNotIn("https://", live)
        self.assertNotIn("www.", live)
        self.assertNotIn("GH-123", live)
        self.assertIn("done", live)

    def test_a_mention_inside_a_url_or_link_cannot_break_out_of_its_code_span(self):
        # Code review round 2: chained substitutions wrapped the URL, then matched @foo INSIDE the
        # wrapper, and the nested backticks closed the span early.
        for raw in ("see https://a.b/c?x=@foo now", "https://a.b/?q=#12", "[l](https://a.b/?q=@bob)",
                    "[@bob](http://x.example)", "[a](http://x`@bob`)", "www.a.b/@foo"):
            live = GFM_SPAN.sub("", self.mod.sanitize(raw))
            self.assertNotIn("@foo", live, raw)
            self.assertNotIn("@bob", live, raw)
            self.assertNotRegex(live, r"(?<![\w/])#12", raw)

    def test_html_character_references_cannot_smuggle_a_mention_or_reference(self):
        # Code review round 2: &#64; and &#35; decode to @ and # after the sanitiser has looked.
        for raw in ("&#64;victim", "&#x40;victim", "&#35;123 done", "&commat;victim"):
            live = GFM_SPAN.sub("", self.mod.sanitize(raw))
            self.assertNotIn("@victim", live, raw)
            self.assertNotIn("&#64;", live, raw)
            self.assertNotRegex(live, r"(?<![\w/])#123", raw)
        text = "AT&T and 3 < 4 and a ` b"
        self.assertEqual(self.mod.sanitize(self.mod.sanitize(text)), self.mod.sanitize(text))

    def live_lines(self, body):
        """Text GitHub still renders as live, line by line, with the quote prefix and spans removed."""
        lines = [ln[2:] if ln.startswith("> ") else ln.lstrip(">") for ln in body.split("\n")]
        return [GFM_SPAN.sub("·", ln) for ln in lines]   # a span is one inert character, never deleted

    def test_line_separators_inside_a_span_cannot_split_it_in_the_quote(self):
        # Security round 3: str.splitlines() breaks on \r, \x0b, \x0c, \x1c-\x1e, \x85 and  ,
        # which the old one-line span pattern allowed, so _quote cut a preserved span in two and a
        # block starter on the next line made the first backtick literal.
        for sep in ("\r", "\x0b", "\x0c", "\x1c", "\x85", " ", " "):
            for starter in ("- x", "# x", "> x", "1. x"):
                review = "## Automated multi-dimension review\n`@octocat [pwn](http://evil.example)" + sep + starter + "`"
                body = self.mod.build_pr_body(review, "a" * 40, 9, self.cfg)
                for live in self.live_lines(body):
                    self.assertNotIn("@octocat", live, repr(sep + starter))
                    self.assertNotIn("http://evil.example", live, repr(sep + starter))

    def test_the_length_cut_never_leaves_a_live_token(self):
        # Security round 3: _fit cut at a fixed index, inside a preserved span, so its closing
        # backtick was lost and the text inside went live.
        import copy
        small = copy.deepcopy(self.cfg)
        small["comment_max_chars"]["value"] = 400
        for pad in range(150, 215):
            review = ("## Automated multi-dimension review\n" + "a" * pad
                      + " `@octocat see [x](http://evil.example)` tail " + "b" * 600)
            body = self.mod.build_pr_body(review, "a" * 40, 9, small)
            self.assertLessEqual(len(body), 400)
            for live in self.live_lines(body):
                self.assertNotIn("@octocat", live, pad)
                self.assertNotIn("http://evil.example", live, pad)
                self.assertNotIn("`", live, pad)

    def test_an_entity_encoded_secret_is_redacted_after_decoding(self):
        # Code review round 3: redaction ran before character references were decoded.
        patterns = self.mod.val(self.cfg, "secret_patterns")
        out = self.mod.sanitize("key sk&#45;ant-abcdefghijklmnop12 end", patterns)
        self.assertNotIn("sk-ant-abcdefghijklmnop12", out)
        self.assertIn("(redacted)", out)
        self.assertNotIn("sk&#45;ant", out)

    def test_other_autolink_schemes_are_wrapped(self):
        # Code review round 3: cmark-gfm autolinks ftp:// and mailto: as well as http(s).
        out = self.mod.sanitize("see ftp://evil.example/x and mailto:a@b.example and xmpp:a@b.example")
        live = GFM_SPAN.sub("", out)
        self.assertNotIn("ftp://", live)
        self.assertNotIn("mailto:", live)
        self.assertNotIn("xmpp:", live)

    def test_every_code_span_in_the_output_is_one_clean_span(self):
        # The invariant that closes the class: no backtick survives outside a rebuilt span, and a
        # span never holds a backtick or a line break of its own.
        for raw in ("`` a ` b `` and `x\ty`", "```fence```", "`a\rb`", "a ` b ``` c", "``unclosed", "`@x` `@y`"):
            out = self.mod.sanitize(raw)
            self.assertNotIn("`", GFM_SPAN.sub("", out), raw)
            for span in GFM_SPAN.finditer(out):
                self.assertNotIn("\n", span.group(2), raw)
            self.assertNotRegex(out, r"``", raw)

    def test_invisible_and_bidi_characters_are_removed(self):
        # Code review round 7: tag characters (U+E0000-E007F), zero-width characters and bidi
        # overrides can carry text a human reviewer cannot see but another agent reads, or reverse
        # what a finding displays. The repository's own style hygiene forbids them.
        raw = ("clean \U000e0041\U000e0042 hidden ​‌‍⁠﻿ zero ‮ reversed "
               "⁦ isolate ⁩ end")
        out = self.mod.sanitize(raw)
        for ch in ("\U000e0041", "​", "‌", "‍", "⁠", "﻿", "‮", "⁦", "⁩"):
            self.assertNotIn(ch, out)
        self.assertIn("clean", out)
        self.assertIn("reversed", out)
        self.assertEqual(self.mod.sanitize(out), out)
        # also inside a code span, and a mention split by a zero-width character is still a mention
        self.assertNotIn("​", self.mod.sanitize("`a​b`"))
        live = GFM_SPAN.sub("·", self.mod.sanitize("@oct​ocat"))
        self.assertNotIn("@octocat", live)

    def test_one_oversized_line_is_cut_at_a_safe_space_not_dropped(self):
        # Code review round 7: _fit cut on the last newline, so a review that is one very long line
        # after its heading was dropped entirely and only the notice was posted.
        import copy
        small = copy.deepcopy(self.cfg)
        small["comment_max_chars"]["value"] = 600
        words = " ".join("word%d `code%d`" % (i, i) for i in range(400))
        body = self.mod.build_pr_body("## Automated multi-dimension review\n" + words, "a" * 40, 9, small)
        self.assertLessEqual(len(body), 600)
        self.assertIn("cut at", body)
        kept = body.split("(review cut at")[0]
        self.assertIn("word0", kept)
        self.assertGreater(len(kept), 300)                       # findings survive, not just the heading
        self.assertEqual(kept.count("`") % 2, 0)                 # the cut never leaves a span open
        self.assertNotRegex(kept.rstrip()[-8:], r"&#?\w*$")      # nor a half entity

    def test_the_error_text_cap_is_configuration(self):
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertIn("error_text_chars", cfg)
        self.assertIn("provenance", cfg["error_text_chars"])
        self.assertNotIn("[:200]", SCRIPT.read_text(encoding="utf-8"))

    def test_math_delimiters_cannot_turn_a_code_span_live(self):
        # Security round 6 (7686 strings rendered through GitHub): GitHub extracts $...$ math BEFORE
        # it parses code spans, so a span between two dollar signs became a <math-renderer> whose
        # text the mention and issue filters then read. No raw '$' may remain next to or between spans.
        for raw in ("$@octocat$", "$#1$", "$GH-1$", "Cost is $@octocat$ total", "$$@octocat$$", "$`@octocat`$",
                    "`x$` `@octocat` `$y`", "$ @octocat $", "a$b $@octocat$"):
            out = self.mod.sanitize(raw)
            self.assertNotIn("$", GFM_SPAN.sub("·", out), raw)        # outside spans: an entity
            for span in GFM_SPAN.finditer(out):
                self.assertNotIn("$", span.group(2), raw)                  # inside spans: no delimiter either
            self.assertEqual(self.mod.sanitize(out), out, raw)

    def test_gh_references_are_case_insensitive(self):
        # Security round 6: GitHub links gh-2 and Gh-1 as well as GH-1.
        for raw in ("see gh-2 here", "Gh-1", "gH-9"):
            live = GFM_SPAN.sub("·", self.mod.sanitize(raw))
            self.assertNotRegex(live, r"(?i)gh-[0-9]", raw)

    def test_a_link_replacement_cannot_glue_text_to_a_preceding_token_start(self):
        # Security round 6: `[text](url)` became bare `text`, so an `@`, `#` or `GH-` just before
        # it was joined to the text AFTER the token pass had looked, giving a live mention or reference.
        for raw in ("@[octocat](http://x)", "#[1](x)", "GH-[1](x)", "@[](x)", "@![name](x)", "@@[a](b)",
                    "@&#91;name](x)", "gh-[2](x)"):
            live = GFM_SPAN.sub("·", self.mod.sanitize(raw))
            self.assertNotRegex(live, r"@[A-Za-z_]", raw)
            self.assertNotRegex(live, r"(?<![\w/&])#[0-9]", raw)
            self.assertNotRegex(live, r"(?i)gh-[0-9]", raw)

    def test_a_pipe_inside_a_span_cannot_split_it_across_table_cells(self):
        # Security round 5 (rendered through GitHub's own API): table parsing runs before inline
        # parsing, so an unescaped `|` inside a code span ended the cell, left the opening backtick
        # in one cell and put the rest, a live mention, reference and link, in the next.
        review = ("## Automated multi-dimension review\n\n| a | b |\n|---|---|\n"
                  "| `x | @octocat #1 http://evil.example/p` | y |")
        body = self.mod.build_pr_body(review, "a" * 40, 9, self.cfg)
        for line in body.split("\n")[1:]:
            cells = line.split("|")
            for cell in cells:                       # every cell must hold balanced spans on its own
                self.assertEqual(cell.count("`") % 2, 0, repr(cell))
        for live in self.live_lines(body)[1:]:
            for bad in ("@octocat", "#1", "http://evil.example"):
                self.assertNotIn(bad, live)
        self.assertNotIn("|", GFM_SPAN.search(self.mod.sanitize("`a|b`")).group(2))

    def test_a_missing_comment_id_fails_the_post_step(self):
        # Code review round 5: no id in the answer meant no output, and the mirror then exited 2.
        with tempfile.TemporaryDirectory() as d:
            body = Path(d) / "r.md"
            body.write_text(MARK, encoding="utf-8")
            gh = FakeGh([("-X POST repos/o/r/issues/9/comments", "{}"), ("issues/9/comments", "[[]]")])
            rc = self.mod.main(["post-pr", "--repo", "o/r", "--pr", "9", "--sha", "a" * 40,
                                "--body-file", str(body), "--output-file", str(Path(d) / "out")], runner=gh)
            self.assertEqual(rc, 1)

    def test_every_init_message_is_checked_not_only_the_first(self):
        # Code review round 5: a later init (a resumed or compacted session) was never inspected.
        msgs = [{"type": "system", "subtype": "init", "tools": ["Skill"]},
                {"type": "system", "subtype": "init", "tools": ["Skill", "Bash"]}]
        self.assertEqual(self.mod.check_tools(msgs, self.cfg), ["Bash"])

    def test_the_session_ignores_project_settings_and_foreign_mcp_servers(self):
        # Code review round 5: the checkout holds .claude/settings.json with plugins, marketplaces
        # and an MCP roster, and the CLI reads project settings unless told not to.
        args = claude_args(WORKFLOW.read_text(encoding="utf-8"))
        self.assertIn("--setting-sources user", args)
        self.assertIn("--strict-mcp-config", args)

    def test_a_tag_assembled_around_a_token_cannot_become_html(self):
        # Security round 4: `<` was escaped only when a letter followed it IN THE SAME slice of
        # text. A `<` ending the slice before a link token got its letter from the link text, and
        # the `>` after the token was never escaped, so `<[a href="//e.example"]()>x<[/a]()>`
        # came out as a live, clickable <a> in the PR comment.
        for raw in ('- <[a href="//evil.example/login"]()>Sign in<[/a]()>',
                    '<[img src="//e.example/x.png"]()>', 'x <[img src="a](t) b">', "<@a>", "<#1>", "<GH-1>",
                    "<https://e.example/x>", "< a>", "<&#97; href=x>"):
            body = self.mod.build_pr_body("## Automated multi-dimension review\n" + raw, "a" * 40, 9, self.cfg)
            for live in self.live_lines(body)[1:]:
                self.assertNotRegex(live, r"<[!/A-Za-z?]", raw)
        out = self.mod.sanitize('<[a href="//e.example"]()>x')
        self.assertNotIn("<", out)
        self.assertEqual(self.mod.sanitize(out), out)

    def test_seeded_fuzz_no_live_token_and_stable_after_a_second_pass(self):
        # Four review rounds each found a new bypass in a hand-picked input. This walks 600 strings
        # built from the fragments that produced them, with a FIXED seed (R19), through the whole
        # posted body (sanitise, quote), and asserts the two properties that matter: nothing GitHub
        # would turn into a mention, reference, link, image or tag survives outside a code span,
        # and sanitising the output again changes nothing.
        import random
        rng = random.Random(20261016)
        frags = ["$", "$$", "gh-1", "Gh-2", "@[a](b)", "#[1](x)", "![n](u)", "|", "|---|", "| ", "---", "===", ":+1:", "~~", "~~~", "$$", "$", "\t", "\x0c", "​", "‮",
                 "`", "``", "```", "@a", "@org/team", "#1", "GH-1", "o/r#2", "[", "]", "](", "![", "http://x.example/p",
                 "www.x.example", "ftp://x.example", "\\", "&#96;", "&#64;", "&amp;", "&lt;", "&", "\n", "\n\n", "\r",
                 "\x0b", "\x85", " ", "<", "<!--", "-->", "<b>", "_", "*", "- ", "# ", "> ", "1. ", " ", "x", "sk-ant-abcdefghij"]
        patterns = self.mod.val(self.cfg, "secret_patterns")
        for n in range(600):
            raw = "".join(rng.choice(frags) for _ in range(rng.randint(1, 14)))
            once = self.mod.sanitize(raw, patterns)
            self.assertEqual(self.mod.sanitize(once, patterns), once, "not stable: %r" % raw)
            body = self.mod.build_pr_body("## Automated multi-dimension review\n" + raw, "a" * 40, 9, self.cfg)
            for live in self.live_lines(body)[1:]:       # line 0 is our own hidden marker
                # An entity is one inert character (never deleted: that would glue its neighbours);
                # &lt; stays as it is, since an escaped tag must not read as a tag.
                text = re.sub(r"&(?:#[0-9]+|amp);", "·", live)
                for bad in ("@a", "@org", "#1", "#2", "GH-1", "gh-1", "Gh-2", "$", "www.", "sk-ant-"):
                    self.assertNotIn(bad, text, "%s live in %r from %r" % (bad, text, raw))
                self.assertNotRegex(text, r"[A-Za-z][A-Za-z0-9+.-]*://", "scheme link live from %r" % raw)
                self.assertNotRegex(text, r"<[!/A-Za-z?]", "tag live from %r" % raw)
                self.assertNotIn("`", text, "stray backtick from %r" % raw)
                self.assertNotRegex(text, r"(?<!\\)!?\[[^\]]*\]\(", "link live from %r" % raw)

    def test_underscore_and_backslash_do_not_shield_a_token_and_sanitising_is_stable(self):
        # Security round 2, inputs observed live through GitHub's own markdown renderer: GitHub
        # links a mention after `_` or `*`, and a backslash before a token used to escape the
        # backtick that was meant to wrap it, leaving a live link or reference beside it.
        raws = ["_@octocat_", "**@octocat**", "\\#1", "\\GH-1", "\\octocat/hello-world#1", "\\@user",
                "\\http://evil.example/x", "http://x.example/a;@octocat,", "https://x.example/a?q=#1",
                "http://x.example/?u=GH-1", "http://x.example/?r=octocat/hello-world#1", "`` ` ``@user",
                "&lt;!-- rt-review:pr-5 --&gt;", "a&#96;@b", "x [a][r]\n[r]: //e.example/i.png"]
        for raw in raws:
            once = self.mod.sanitize(raw)
            live = re.sub(r"&#[0-9]+;", "", GFM_SPAN.sub("", once))  # an entity is text, not a reference
            self.assertNotRegex(live, r"@[A-Za-z]", raw)
            self.assertNotRegex(live, r"#[0-9]", raw)
            self.assertNotIn("GH-1", live, raw)
            self.assertNotIn("http://", live, raw)
            self.assertNotIn("<!--", once, raw)
            self.assertEqual(self.mod.sanitize(once), once, "not stable: " + raw)

    def test_reference_style_links_and_images_are_neutralised(self):
        s = self.mod.sanitize
        out = s("![a][r] and [text][r]\n\n[r]: //evil.example/x.png\n[tag] kept")
        self.assertNotRegex(out, r"(?<!\\)\[")
        self.assertIn("tag", out)
        self.assertEqual(s(out), out)

    def test_secret_shaped_text_is_redacted_before_posting(self):
        patterns = self.mod.val(self.cfg, "secret_patterns")
        fake = "sk-ant-api03-" + "A1b2C3d4E5f6G7h8I9j0"
        pr = self.mod.build_pr_body("## Automated multi-dimension review\nkey " + fake + " leaked", "a" * 40, 9, self.cfg)
        self.assertNotIn(fake, pr)
        self.assertIn("(redacted)", pr)
        self.assertTrue(patterns)
        clean = self.mod.build_pr_body("## Automated multi-dimension review\nplain text", "a" * 40, 9, self.cfg)
        self.assertNotIn("(redacted)", clean)

    def test_sanitize_is_idempotent_and_keeps_plain_text(self):
        s = self.mod.sanitize
        text = "A plain sentence, 3 < 4, code `x` and a list.\n- item"
        # Every '<' outside a code span is an entity since security round 4 (it renders as '<').
        self.assertEqual(s(text), text.replace("<", "&lt;"))
        raw = "@alice #5 [a](http://x.example) <b>"
        self.assertEqual(s(s(raw)), s(raw))

    def test_select_comment_takes_last_with_right_login_and_marker(self):
        m = "<!-- rt-review:pr-5 -->"
        comments = [
            {"id": 1, "user": {"login": "github-actions[bot]"}, "body": m + "\nold"},
            {"id": 2, "user": {"login": "someone"}, "body": m + "\nspoof"},
            {"id": 3, "user": {"login": "github-actions[bot]"}, "body": "no marker"},
            {"id": 4, "user": {"login": "github-actions[bot]"}, "body": m + "\nnew"},
        ]
        self.assertEqual(self.mod.select_comment(comments, m, "github-actions[bot]")["id"], 4)
        self.assertIsNone(self.mod.select_comment(comments[1:3], m, "github-actions[bot]"))

    def test_check_tools_reports_offenders_and_refuses_without_init(self):
        good = [{"type": "system", "subtype": "init", "tools": ["Skill", "Read", "Grep", "Glob"]}]
        bad = [{"type": "system", "subtype": "init", "tools": ["Skill", "Read", "Bash", "mcp__github_x__y"]}]
        self.assertEqual(self.mod.check_tools(good, self.cfg), [])
        self.assertEqual(sorted(self.mod.check_tools(bad, self.cfg)), ["Bash", "mcp__github_x__y"])
        # Code review round 1: an ALLOWLIST. A tool nobody thought to forbid is still refused.
        odd = [{"type": "system", "subtype": "init", "tools": ["Skill", "WebFetch", "Monitor", "PowerShell(x)"]}]
        self.assertEqual(sorted(self.mod.check_tools(odd, self.cfg)), ["Monitor", "PowerShell(x)", "WebFetch"])
        with self.assertRaises(self.mod.ToolListError):
            self.mod.check_tools([{"type": "result"}], self.cfg)
        with self.assertRaises(self.mod.ToolListError):
            self.mod.check_tools([{"type": "system", "subtype": "init"}], self.cfg)

    def test_extract_review_returns_the_last_success_result_with_marker_first(self):
        marker = self.cfg["review_marker"]["value"]
        msgs = [{"type": "result", "subtype": "success", "is_error": False, "result": marker + "\nline two\nbody"}]
        self.assertTrue(self.mod.extract_review(msgs, self.cfg).startswith(marker))

    def test_extract_review_refuses_error_missing_or_unmarked_results(self):
        marker = self.cfg["review_marker"]["value"]
        for msgs in (
            [],
            [{"type": "result", "subtype": "success", "is_error": True, "result": marker}],
            [{"type": "result", "subtype": "error_max_turns", "is_error": True}],
            [{"type": "result", "subtype": "success", "is_error": False, "result": "no marker here"}],
            [{"type": "result", "subtype": "success", "is_error": False, "result": "intro\n" + marker}],
        ):
            with self.assertRaises(self.mod.ReviewError):
                self.mod.extract_review(msgs, self.cfg)

    def test_extract_review_tolerates_leading_blank_space_from_the_model(self):
        # Code review round 2: a paid review must not be thrown away over a leading newline.
        marker = self.cfg["review_marker"]["value"]
        msgs = [{"type": "result", "subtype": "success", "is_error": False, "result": "\n  " + marker + "\nbody\n"}]
        self.assertEqual(self.mod.extract_review(msgs, self.cfg), marker + "\nbody")

    def test_validation_uses_a_full_match_and_a_bot_author_only_loses_the_mention(self):
        mod = self.mod
        self.assertIsNone(mod.valid_login("abc\n", self.cfg))
        self.assertIsNone(mod.valid_login("some-app[bot]", self.cfg))
        self.assertEqual(mod.valid_login("octo-cat", self.cfg), "octo-cat")
        body = mod.build_issue_body("> text", "some-app[bot]", 9, True, self.cfg)
        self.assertNotIn("@some-app", body)
        self.assertTrue(body.startswith("<!-- rt-review-mirror:pr-9 -->"))

    def test_comment_bodies_are_cut_to_the_configured_cap_with_a_notice(self):
        cap = self.mod.val(self.cfg, "comment_max_chars")
        self.assertLess(cap, 65536)
        long_review = "## Automated multi-dimension review\n" + "\n".join("- item %d" % i for i in range(cap))
        pr = self.mod.build_pr_body(long_review, "a" * 40, 9, self.cfg)
        self.assertLessEqual(len(pr), cap)
        self.assertIn("cut at", pr)
        issue = self.mod.build_issue_body("> " + "x" * (cap + 500), "octo", 9, True, self.cfg)
        self.assertLessEqual(len(issue), cap)
        short = self.mod.build_pr_body("## Automated multi-dimension review\nok", "a" * 40, 9, self.cfg)
        self.assertNotIn("cut at", short)

    def test_bodies_carry_marker_sha_and_blockquote_and_ping_only_on_create(self):
        pr = self.mod.build_pr_body("## Automated multi-dimension review\n@x said #4", "a" * 40, 9, self.cfg)
        self.assertTrue(pr.startswith("<!-- rt-review:pr-9 -->"))
        self.assertIn("a" * 40, pr)
        self.assertIn("> ## Automated multi-dimension review", pr)
        self.assertNotRegex(pr, r"(?<!`)@x")
        created = self.mod.build_issue_body("> text", "octo-cat", 9, True)
        updated = self.mod.build_issue_body("> text", "octo-cat", 9, False)
        self.assertIn("@octo-cat", created)
        self.assertNotIn("@octo-cat", updated)
        self.assertTrue(updated.startswith("<!-- rt-review-mirror:pr-9 -->"))
        hostile = self.mod.build_issue_body("> text", "bad login\n@evil", 9, True)
        self.assertNotIn("evil", hostile)


class FakeGh:
    """Injected `gh` runner. Records every call, answers from a route table."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, args, stdin=None):
        self.calls.append((list(args), stdin))
        key = " ".join(args)
        for needle, reply in self.routes:
            if needle in key:
                return reply if isinstance(reply, tuple) else (0, reply)
        return (1, "no route for " + key)

    def writes(self):
        return [c for c in self.calls if "-X" in c[0]]


MARK = "## Automated multi-dimension review"


class TestCommands(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_module()
        cls.cfg = cls.mod.load_config(CONFIG)

    def exec_file(self, d, msgs):
        p = Path(d) / "exec.json"
        p.write_text(json.dumps(msgs), encoding="utf-8")
        return str(p)

    def test_post_pr_creates_then_updates_in_place(self):
        with tempfile.TemporaryDirectory() as d:
            body = Path(d) / "r.md"
            body.write_text(MARK + "\nx", encoding="utf-8")
            first = FakeGh([("-X POST repos/o/r/issues/9/comments", '{"id": 77}'), ("issues/9/comments", "[[]]")])
            out = Path(d) / "gh_out"
            rc = self.mod.main(["post-pr", "--repo", "o/r", "--pr", "9", "--sha", "a" * 40,
                                "--body-file", str(body), "--output-file", str(out)], runner=first)
            self.assertEqual(rc, 0)
            self.assertEqual(len(first.writes()), 1)
            self.assertIn("comment_id=77", out.read_text(encoding="utf-8"))
            existing = [[{"id": 77, "user": {"login": "github-actions[bot]"}, "body": "<!-- rt-review:pr-9 -->\nold"}]]
            second = FakeGh([("-X PATCH repos/o/r/issues/comments/77", '{"id": 77}'), ("issues/9/comments", json.dumps(existing))])
            rc = self.mod.main(["post-pr", "--repo", "o/r", "--pr", "9", "--sha", "a" * 40,
                                "--body-file", str(body), "--output-file", str(out)], runner=second)
            self.assertEqual(rc, 0)
            self.assertEqual([c[0][2] for c in second.writes()], ["PATCH"])

    def test_post_pr_dry_run_calls_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            body = Path(d) / "r.md"
            body.write_text(MARK, encoding="utf-8")
            gh = FakeGh([])
            rc = self.mod.main(["post-pr", "--repo", "o/r", "--pr", "9", "--sha", "a" * 40,
                                "--body-file", str(body), "--dry-run"], runner=gh)
            self.assertEqual(rc, 0)
            self.assertEqual(gh.calls, [])

    def test_mirror_skips_cleanly_without_a_fixes_line_or_open_issue(self):
        gh = FakeGh([])
        self.assertEqual(self.mod.main(["mirror-issue", "--repo", "o/r", "--pr", "9", "--author", "octo",
                                        "--pr-comment-id", "77"], runner=gh, env={"PR_BODY": "no link"}), 0)
        self.assertEqual(gh.calls, [])
        closed = FakeGh([("api repos/o/r/issues/12", '{"state": "closed"}')])
        self.assertEqual(self.mod.main(["mirror-issue", "--repo", "o/r", "--pr", "9", "--author", "octo",
                                        "--pr-comment-id", "77"], runner=closed, env={"PR_BODY": "Fixes #12"}), 0)
        self.assertEqual(closed.writes(), [])
        as_pr = FakeGh([("api repos/o/r/issues/12", '{"state": "open", "pull_request": {}}')])
        self.assertEqual(self.mod.main(["mirror-issue", "--repo", "o/r", "--pr", "9", "--author", "octo",
                                        "--pr-comment-id", "77"], runner=as_pr, env={"PR_BODY": "Fixes #12"}), 0)
        self.assertEqual(as_pr.writes(), [])

    def pr_comment(self, body):
        return json.dumps({"id": 77, "user": {"login": "github-actions[bot]"}, "body": body})

    def test_mirror_fails_loudly_when_the_pr_comment_is_missing_or_not_ours(self):
        for reply in (self.pr_comment("no marker"),
                      json.dumps({"id": 77, "user": {"login": "someone"}, "body": "<!-- rt-review:pr-9 -->\nx"})):
            gh = FakeGh([("api repos/o/r/issues/12", '{"state": "open"}'),
                         ("issues/comments/77", reply)])
            rc = self.mod.main(["mirror-issue", "--repo", "o/r", "--pr", "9", "--author", "octo",
                                "--pr-comment-id", "77"], runner=gh, env={"PR_BODY": "Fixes #12"})
            self.assertEqual(rc, 1)
            self.assertEqual(gh.writes(), [])

    def test_mirror_creates_once_then_updates_and_never_repings(self):
        review = "<!-- rt-review:pr-9 -->\nReviewed commit: x\n> " + MARK
        base = [("api repos/o/r/issues/12", '{"state": "open"}'), ("issues/comments/77", self.pr_comment(review))]
        first = FakeGh(base + [("-X POST repos/o/r/issues/12/comments", '{"id": 5}'),
                               ("-X POST repos/o/r/issues/12/assignees", "{}"), ("issues/12/comments", "[[]]")])
        self.assertEqual(self.mod.main(["mirror-issue", "--repo", "o/r", "--pr", "9", "--author", "octo",
                                        "--pr-comment-id", "77"], runner=first, env={"PR_BODY": "Fixes #12"}), 0)
        self.assertTrue(any("@octo" in (c[1] or "") for c in first.writes()))
        mirrored = [[{"id": 5, "user": {"login": "github-actions[bot]"}, "body": "<!-- rt-review-mirror:pr-9 -->\nold"}]]
        second = FakeGh(base + [("-X PATCH repos/o/r/issues/comments/5", '{"id": 5}'),
                                ("issues/12/comments", json.dumps(mirrored))])
        self.assertEqual(self.mod.main(["mirror-issue", "--repo", "o/r", "--pr", "9", "--author", "octo",
                                        "--pr-comment-id", "77"], runner=second, env={"PR_BODY": "Fixes #12"}), 0)
        self.assertEqual([c[0][2] for c in second.writes()], ["PATCH"])
        # Code review round 1: the Issue's comments are listed ONCE per run, not once to decide the
        # ping and again to find the comment to update.
        for gh in (first, second):
            listings = [c for c in gh.calls if "--paginate" in c[0] and "issues/12/comments" in " ".join(c[0])]
            self.assertEqual(len(listings), 1)
        self.assertFalse(any("@octo" in (c[1] or "") for c in second.writes()))

    def test_the_target_issue_is_fetched_once_and_a_bad_answer_is_a_named_failure(self):
        # Code review round 4: the lookup was issued twice on failure, and a 200 with a body that
        # is not JSON raised an uncaught ValueError. A rate-limit message holding "404" is not a 404.
        ok = FakeGh([("api repos/o/r/issues/12", '{"state": "closed"}')])
        self.assertEqual(self.mod.main(["mirror-issue", "--repo", "o/r", "--pr", "9", "--author", "octo",
                                        "--pr-comment-id", "77"], runner=ok, env={"PR_BODY": "Fixes #12"}), 0)
        self.assertEqual(len([c for c in ok.calls if c[0][1:2] == ["repos/o/r/issues/12"]]), 1)
        html_body = FakeGh([("api repos/o/r/issues/12", "<html>bad gateway</html>")])
        self.assertEqual(self.mod.main(["mirror-issue", "--repo", "o/r", "--pr", "9", "--author", "octo",
                                        "--pr-comment-id", "77"], runner=html_body, env={"PR_BODY": "Fixes #12"}), 1)
        limited = FakeGh([("api repos/o/r/issues/12", (1, "API rate limit exceeded for user 4040404"))])
        self.assertEqual(self.mod.main(["mirror-issue", "--repo", "o/r", "--pr", "9", "--author", "octo",
                                        "--pr-comment-id", "77"], runner=limited, env={"PR_BODY": "Fixes #12"}), 1)

    def test_the_cut_notice_holds_no_square_bracket(self):
        # Code review round 4: the mirror's second pass turned the notice's brackets into entities,
        # so the Issue copy differed from the PR comment.
        import copy
        small = copy.deepcopy(self.cfg)
        small["comment_max_chars"]["value"] = 300
        body = self.mod.build_pr_body("## Automated multi-dimension review\n" + "\n".join("- item %d" % i for i in range(80)),
                                      "a" * 40, 9, small)
        self.assertIn("cut at", body)
        self.assertNotIn("[", body.split("cut at")[0].splitlines()[-1] if "[" in body.split("cut at")[0].splitlines()[-1] else "")
        notice = [ln for ln in body.splitlines() if "cut at" in ln][0]
        self.assertNotRegex(notice, r"[\[\]]")

    def test_a_missing_target_issue_is_a_clean_skip_but_other_errors_fail(self):
        # Code review round 3: a mistyped `Fixes #999` must not turn the check red after the paid
        # review was posted. Any other gh error is still a failure.
        absent = FakeGh([("api repos/o/r/issues/999", (1, "gh: Not Found (HTTP 404)"))])
        rc = self.mod.main(["mirror-issue", "--repo", "o/r", "--pr", "9", "--author", "octo",
                            "--pr-comment-id", "77"], runner=absent, env={"PR_BODY": "Fixes #999"})
        self.assertEqual(rc, 0)
        self.assertEqual(absent.writes(), [])
        broken = FakeGh([("api repos/o/r/issues/999", (1, "gh: Server Error (HTTP 500)"))])
        rc = self.mod.main(["mirror-issue", "--repo", "o/r", "--pr", "9", "--author", "octo",
                            "--pr-comment-id", "77"], runner=broken, env={"PR_BODY": "Fixes #999"})
        self.assertEqual(rc, 1)

    def test_the_real_runner_retries_only_transient_failures(self):
        # Code review round 6: a permanent 404, 403 or 422 was retried like a timeout.
        import subprocess as sp
        from unittest import mock
        runner = self.mod.make_runner(self.cfg)
        retries = self.mod.val(self.cfg, "gh_retries")

        def answer(code, err):
            return sp.CompletedProcess(["gh"], code, stdout="", stderr=err)

        for err, expected in (("gh: Not Found (HTTP 404)", 1), ("gh: Validation Failed (HTTP 422)", 1),
                              ("gh: Forbidden (HTTP 403)", 1), ("gh: Bad Gateway (HTTP 502)", retries + 1),
                              ("gh: Service Unavailable (HTTP 503)", retries + 1),
                              ("dial tcp: connection reset by peer", retries + 1)):
            with mock.patch.object(self.mod.subprocess, "run", return_value=answer(1, err)) as run, \
                    mock.patch.object(self.mod.time, "sleep"):
                runner(["api", "repos/o/r/issues/9"])
                self.assertEqual(run.call_count, expected, err)

    def test_the_real_runner_never_retries_a_post(self):
        # Code review round 3: a POST that timed out may already have created the comment, so a
        # retry posts a duplicate. A read is retried up to the configured count.
        import subprocess as sp
        from unittest import mock
        cfg = self.cfg
        retries = self.mod.val(cfg, "gh_retries")
        runner = self.mod.make_runner(cfg)
        with mock.patch.object(self.mod.subprocess, "run", side_effect=sp.TimeoutExpired("gh", 1)) as run:
            rc, _ = runner(["api", "-X", "POST", "repos/o/r/issues/9/comments", "--input", "-"], "{}")
            self.assertEqual(rc, 1)
            self.assertEqual(run.call_count, 1)
        with mock.patch.object(self.mod.subprocess, "run", side_effect=sp.TimeoutExpired("gh", 1)) as run, \
                mock.patch.object(self.mod.time, "sleep"):
            runner(["api", "repos/o/r/issues/9"])
            self.assertEqual(run.call_count, retries + 1)

    def test_mirror_with_a_bot_author_posts_without_mention_or_assignment(self):
        review = "<!-- rt-review:pr-9 -->\n> " + MARK
        gh = FakeGh([("api repos/o/r/issues/12", '{"state": "open"}'), ("issues/comments/77", self.pr_comment(review)),
                     ("-X POST repos/o/r/issues/12/comments", '{"id": 5}'), ("issues/12/comments", "[[]]")])
        rc = self.mod.main(["mirror-issue", "--repo", "o/r", "--pr", "9", "--author", "some-app[bot]",
                            "--pr-comment-id", "77"], runner=gh, env={"PR_BODY": "Fixes #12"})
        self.assertEqual(rc, 0)
        self.assertEqual(len(gh.writes()), 1)
        self.assertNotIn("@some-app", gh.writes()[0][1])

    def test_mirror_survives_an_assignee_failure(self):
        review = "<!-- rt-review:pr-9 -->\n> " + MARK
        gh = FakeGh([("api repos/o/r/issues/12", '{"state": "open"}'), ("issues/comments/77", self.pr_comment(review)),
                     ("-X POST repos/o/r/issues/12/comments", '{"id": 5}'), ("assignees", (1, "422 cannot assign")),
                     ("issues/12/comments", "[[]]")])
        self.assertEqual(self.mod.main(["mirror-issue", "--repo", "o/r", "--pr", "9", "--author", "octo",
                                        "--pr-comment-id", "77"], runner=gh, env={"PR_BODY": "Fixes #12"}), 0)

    def test_check_tools_command_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            good = self.exec_file(d, [{"type": "system", "subtype": "init", "tools": ["Skill", "Read"]}])
            self.assertEqual(self.mod.main(["check-tools", "--execution-file", good]), 0)
            bad = self.exec_file(d, [{"type": "system", "subtype": "init", "tools": ["Bash"]}])
            self.assertEqual(self.mod.main(["check-tools", "--execution-file", bad]), 2)
            nothing = self.exec_file(d, [])
            self.assertEqual(self.mod.main(["check-tools", "--execution-file", nothing]), 1)
            self.assertEqual(self.mod.main(["check-tools", "--execution-file", str(Path(d) / "absent.json")]), 1)

    def test_extract_command_writes_the_review_with_the_sha_line(self):
        with tempfile.TemporaryDirectory() as d:
            ef = self.exec_file(d, [{"type": "result", "subtype": "success", "is_error": False,
                                     "result": MARK + "\nran both\n- [x] item"}])
            out = Path(d) / "review.md"
            self.assertEqual(self.mod.main(["extract", "--execution-file", ef, "--out", str(out)]), 0)
            self.assertTrue(out.read_text(encoding="utf-8").startswith(MARK))
            bad = self.exec_file(d, [])
            self.assertEqual(self.mod.main(["extract", "--execution-file", bad, "--out", str(Path(d) / "x.md")]), 1)
            self.assertFalse((Path(d) / "x.md").exists())

    def test_invalid_pr_number_is_a_usage_refusal(self):
        with tempfile.TemporaryDirectory() as d:
            body = Path(d) / "r.md"
            body.write_text(MARK, encoding="utf-8")
            rc = self.mod.main(["post-pr", "--repo", "o/r", "--pr", "9; rm", "--sha", "a" * 40,
                                "--body-file", str(body)], runner=FakeGh([]))
            self.assertEqual(rc, 2)
            rc = self.mod.main(["post-pr", "--repo", "bad repo", "--pr", "9", "--sha", "a" * 40,
                                "--body-file", str(body)], runner=FakeGh([]))
            self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
