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

# Tools the model session must never have. Mirrors review-mirror.json forbidden_* by design:
# the test restates them so a config edit that empties the list is caught here.
FORBIDDEN_TOOLS = ("Bash", "Write", "Edit", "MultiEdit", "NotebookEdit", "Agent", "Task")
AGENT_ACTION_INPUTS_BANNED = ("plugins:", "plugin_marketplaces:", "track_progress:", "use_sticky_comment:")
READ_TOOLS = ("Read", "Grep", "Glob")
DENIED_ROOTS = ("/proc", "/sys", "/run")


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

    def test_forbidden_tool_list_is_not_emptied(self):
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        listed = set(cfg["forbidden_tools"]["value"])
        for tool in FORBIDDEN_TOOLS:
            self.assertIn(tool, listed)

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

    def test_sanitize_is_idempotent_and_keeps_plain_text(self):
        s = self.mod.sanitize
        text = "A plain sentence, 3 < 4, code `x` and a list.\n- item"
        self.assertEqual(s(text), text)
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
            [{"type": "result", "subtype": "success", "is_error": False, "result": "  \n" + marker}],
        ):
            with self.assertRaises(self.mod.ReviewError):
                self.mod.extract_review(msgs, self.cfg)

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
        with self.assertRaises(self.mod.ReviewError):
            self.mod.build_issue_body("> text", "bad login\n@evil", 9, True)


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
        self.assertFalse(any("@octo" in (c[1] or "") for c in second.writes()))

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
