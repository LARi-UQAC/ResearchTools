"""
test_git_privacy_guard - the global git privacy guard (.claude/hooks/git/).

Why it exists. Measured 2026-10-01: the PUBLIC repository carried an account name,
a machine path, code-permanent-shaped values, student emails and a real name, in
current files and in history. Nothing ran at commit time; the only check
(verify-no-personal-data.ps1) was manual and red. The guard is a betterleaks rules
file used by a global pre-commit hook and by the privacy-scan CI workflow.

Offline, no network. Every git call runs with GIT_CONFIG_GLOBAL pointed at a
scratch file and GIT_CONFIG_NOSYSTEM set, so the operator's real global config
(which holds core.hooksPath once installed) is never read or written. The
betterleaks cases skip when the binary is absent; the static cases always run.
Expected duration: about 30 seconds (each git commit spawns the hook and betterleaks).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOKS = Path(__file__).resolve().parents[1] / "git"
REPO = Path(__file__).resolve().parents[3]
RULES = HOOKS / "privacy-rules.toml"
# The extra scan (deny list and fixture paths) shipped beside the hooks, 2026-10-12.
EXTRA_FILES = ("privacy-lib.sh", "privacy-extra.awk", "fixture-path-allow.txt", "privacy-guard.conf")
WORKFLOW = REPO / ".github" / "workflows" / "privacy-scan.yml"
RULE_IDS = ("windows-home-account", "posix-home-account", "posix-users-account",
            "quebec-code-permanent", "uqac-student-email", "frq-identifier")


def find_betterleaks():
    """
    --------------------------------------------------------------------------
    Purpose:
        Locate the betterleaks binary the hook itself would find.

    Inputs:
        None

    Outputs:
        path (str or None): the executable, or None when not installed
    --------------------------------------------------------------------------
    """
    found = shutil.which("betterleaks")
    if found:
        return found
    packages = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    for candidate in packages.glob("Betterleaks*/betterleaks.exe"):
        return str(candidate)
    return None


BETTERLEAKS = find_betterleaks()


def isolated_env(tmp, **extra):
    """Environment for a git call that never touches the real global or system config."""
    cfg = Path(tmp) / "gitconfig"
    cfg.touch()
    env = dict(os.environ, GIT_CONFIG_GLOBAL=str(cfg), GIT_CONFIG_NOSYSTEM="1")
    env.update(extra)
    return env


def run(cmd, cwd, env):
    """Run a command with a 60 s timeout (R10); return the CompletedProcess."""
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=60)


SAMPLE_HITS = {
    "windows-home-account": "path C:\\Users\\jdoe\\.config\\x",  # betterleaks:allow (deliberate sample)
    "posix-home-account": "home /home/jdoe/projects",  # betterleaks:allow (deliberate sample)
    "quebec-code-permanent": "code ABCD12345678 here",  # betterleaks:allow (deliberate sample)
    "uqac-student-email": "mail jane.doe@etu.uqac.ca",  # betterleaks:allow (deliberate sample)
    "frq-identifier": "frq QWERT5678 id",  # betterleaks:allow (deliberate sample)
    "posix-users-account": "log /c/Users/jdoe/x",  # betterleaks:allow (deliberate sample)
}
# Shapes the round-2 local review (R35) found missing; each must still be caught.
SAMPLE_HITS_EXTRA = {
    "posix-users-account": 'mac "/Users/jdoe/Library"',  # betterleaks:allow (deliberate sample)
    "windows-home-account": "path C:\\Users\\Hélène\\x",  # betterleaks:allow (deliberate sample)
    "quebec-code-permanent": "code abcd12345678 here",  # betterleaks:allow (deliberate sample)
}
SAMPLE_CLEAN = (
    "placeholder C:\\Users\\x\\.claude C:\\Users\\someone\\bin C:/Users/<you>/ {{HOME}}/x\n"
    "home /home/user/x\n"
    "mac /Users/Shared/x and a url https://example.org/users/bob\n"
    "code XXXX000000 XXXX12345678\n"
    "frq XXXYY1234 ABCDE1234 and a citation key smith2020\n"
    "allowed C:\\Users\\jdoe\\x betterleaks:allow\n"
)


class StaticContract(unittest.TestCase):
    """The files agree with each other; runs with no binary at all."""

    def test_rules_file_declares_every_rule_and_extends_the_defaults(self):
        text = RULES.read_text(encoding="utf-8")
        for rule_id in RULE_IDS:
            self.assertIn('id = "%s"' % rule_id, text)
        self.assertRegex(text, r"(?m)^\[extend\]\s*\nuseDefault = true")

    def test_rules_file_parses_as_toml(self):
        try:
            import tomllib
        except ImportError:
            self.skipTest("tomllib needs Python 3.11+")
        data = tomllib.loads(RULES.read_text(encoding="utf-8"))
        self.assertEqual(sorted(r["id"] for r in data["rules"]), sorted(RULE_IDS))

    def test_workflow_points_at_the_rules_file_that_exists(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        rel = RULES.relative_to(REPO).as_posix()
        self.assertIn(rel, text)
        self.assertTrue(RULES.is_file())

    def test_workflow_pins_actions_by_sha_and_the_binary_by_checksum(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
        uses = re.findall(r"uses:\s*([^\s#]+)", code)
        self.assertTrue(uses)
        for ref in uses:
            self.assertRegex(ref, r"@[0-9a-f]{40}$", ref)
        self.assertRegex(text, r"\b[0-9a-f]{64}\s+bl\.tgz")

    def test_workflow_scans_every_push_and_decides_with_the_trusted_rules(self):
        # PR #40 review: a main-only push filter left other branches unscanned, and a
        # rules file from the checkout under review could weaken its own verdict.
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("branches:", text)
        authoritative = text.index("(authoritative, trusted rules)")
        candidate = text.index("(informational)")
        self.assertLess(authoritative, candidate)
        verdict_step = text[authoritative:candidate]
        self.assertIn("rules=.privacy-guard/.claude/hooks/git/privacy-rules.toml", verdict_step)
        self.assertIn("continue-on-error: true", text[candidate:])

    def test_trusted_rules_predate_the_change_on_a_push_to_main(self):
        # PR #40 review of e566eda: on a push to main, "main" IS the commit being
        # scanned, so it could weaken its own rules. The fetch must use a pinned ref.
        text = WORKFLOW.read_text(encoding="utf-8")
        fetch = text[text.index("name: Fetch the shared rules"):text.index("name: Install betterleaks")]
        self.assertIn("ref: ${{ env.TRUSTED_REF }}", fetch)
        self.assertNotIn("ref: main", fetch)
        picker = text[text.index("name: Pick the trusted rules revision"):text.index("name: Fetch the shared rules")]
        self.assertIn("github.event.before", picker)

    def test_the_verdict_cannot_be_switched_off_by_the_change_under_review(self):
        # Local security review of 43e380d (R35): an ignore file in the PR checkout
        # suppressed findings (measured with betterleaks 1.4.1), and a missing trusted
        # rules file fell back to the PR's own rules forever, not only at bootstrap.
        text = WORKFLOW.read_text(encoding="utf-8")
        step = text[text.index("(authoritative, trusted rules)"):text.index("(informational)")]
        self.assertLess(step.index("rm -f .gitleaksignore .betterleaksignore"), step.index("\"$bl\" stdin"))
        self.assertIn("exit 1", step)
        self.assertIn('git log --oneline -1 "$logref" -- .claude/hooks/git/privacy-rules.toml', step)

    def test_ci_feeds_text_with_merges_and_bootstraps_on_the_trusted_ref(self):
        # Round 2 (R35): `betterleaks git` honoured a .gitattributes -diff and skipped
        # merge content (both reproduced); the bootstrap asked origin/main, which on the
        # merge of this guard already has the rules, so main would have gone red; a new
        # branch scanned the whole history, where a 2026-08-25 commit still holds a leak.
        text = WORKFLOW.read_text(encoding="utf-8")
        step = text[text.index("(authoritative, trusted rules)"):text.index("(informational)")]
        self.assertIn("git log -p --text -m -U0 --pretty=medium --no-color --no-ext-diff --no-textconv", step)
        self.assertIn("\"$bl\" stdin", step)
        self.assertNotIn("betterleaks git", step)
        self.assertIn("set -o pipefail", step)
        self.assertIn('logref=$TRUSTED_REF', step)
        self.assertIn('range="origin/$DEFAULT..$HEAD"', text)

    def test_a_branch_never_trusts_its_own_previous_commit(self):
        # Copilot on f422053: a feature-branch push trusted github.event.before, so a
        # rules-only first push could weaken the rules for the second. The pre-push
        # revision is allowed ONLY for a push to ResearchTools main.
        text = WORKFLOW.read_text(encoding="utf-8")
        picker = text[text.index("name: Pick the trusted rules revision"):text.index("name: Fetch the shared rules")]
        self.assertIn("github.ref == 'refs/heads/main'", picker)
        self.assertIn("github.event_name == 'push'", picker)
        self.assertNotIn("pull_request.base.sha", picker)
        self.assertRegex(picker, r"ref=main\n")

    def test_ci_rescans_on_retarget_against_the_live_base_and_added_lines_only(self):
        # Round 3 (R35): base.sha goes stale on a retarget; a non-default push must be
        # judged against the default branch; removed lines must not be refused.
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("types: [opened, synchronize, reopened, edited]", text)
        self.assertIn('range="origin/$BASE_REF..$HEAD"', text)
        self.assertIn('range="origin/$DEFAULT..$HEAD"', text)
        self.assertNotIn("pull_request.base.sha", text)
        self.assertEqual(text.count("-U0 --pretty=medium --no-color"), 2)
        self.assertEqual(text.count('cd "$RUNNER_TEMP"'), 2)

    def test_installer_chains_every_documented_hook_except_the_measured_two(self):
        # githooks(5) of git 2.53, read from the installed githooks.adoc on 2026-10-02.
        documented = {
            "applypatch-msg", "pre-applypatch", "post-applypatch", "pre-commit",
            "pre-merge-commit", "prepare-commit-msg", "commit-msg", "post-commit",
            "pre-rebase", "post-checkout", "post-merge", "pre-push", "pre-receive", "update",
            "proc-receive", "post-receive", "post-update", "reference-transaction",
            "push-to-checkout", "pre-auto-gc", "post-rewrite", "sendemail-validate",
            "fsmonitor-watchman", "p4-changelist", "p4-prepare-changelist",
            "p4-post-changelist", "p4-pre-submit", "post-index-change"}
        text = (HOOKS / "install-git-hooks.ps1").read_text(encoding="utf-8")

        def names(var):
            block = re.search(r"\$%s = @\((.*?)\)" % var, text, re.S).group(1)
            return set(re.findall(r'"([a-z0-9-]+)"', block))

        chained, excluded = names("ChainNames"), names("ExcludedHooks")
        privacy = names("PrivacyHookNames") | {"pre-push"}
        self.assertEqual(excluded, {"reference-transaction", "post-index-change"})
        # Round 2 (R35): a clean merge runs only pre-merge-commit, so the privacy
        # script is installed under that name too.
        self.assertEqual(privacy, {"pre-commit", "pre-merge-commit", "pre-push"})
        # Round 3: pre-push is its own privacy script, not a plain chain.
        self.assertIn('@{ from = "pre-push"; to = "pre-push" }', text)
        self.assertIn("--includes --get core.hooksPath", text)
        self.assertEqual(chained | excluded | privacy, documented)
        self.assertFalse(chained & privacy)
        self.assertFalse(chained & excluded)

    def test_shell_scripts_have_no_carriage_return(self):
        # Git's sh fails with '\r: command not found' on a CRLF hook.
        for name in ("pre-commit", "pre-push", "_chain", "privacy-lib.sh", "privacy-extra.awk"):
            self.assertNotIn(b"\r", (HOOKS / name).read_bytes(), name)

    def test_extra_scan_files_carry_the_installer_ownership_marker(self):
        # The installer refuses a file in the target that does not carry one of its markers.
        for name in EXTRA_FILES:
            self.assertIn("installed by install-git-hooks.ps1",
                          (HOOKS / name).read_text(encoding="utf-8"), name)

    def test_the_deny_list_is_never_a_tracked_file(self):
        # Publishing the list would be the leak it prevents.
        for name in ("private-terms.txt", "private-terms.extra.txt"):
            self.assertFalse((HOOKS / name).exists(), name)


@unittest.skipUnless(BETTERLEAKS, "betterleaks not installed")
class RulesDetect(unittest.TestCase):
    """Each rule fires on its sample and stays silent on placeholders."""

    def scan(self, content):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "sample.txt").write_text(content, encoding="utf-8")
            report = Path(tmp) / "r.json"
            run([BETTERLEAKS, "dir", "--no-banner", "--redact", "--config", str(RULES),
                 "--report-format", "json", "--report-path", str(report), str(tmp)],
                tmp, isolated_env(tmp))
            return [f["RuleID"] for f in (json.loads(report.read_text(encoding="utf-8")) or [])]

    def test_each_rule_catches_its_sample(self):
        for rule_id, line in SAMPLE_HITS.items():
            with self.subTest(rule=rule_id):
                self.assertIn(rule_id, self.scan(line + "\n"))

    def test_shapes_found_missing_by_the_local_review_are_caught(self):
        for rule_id, line in SAMPLE_HITS_EXTRA.items():
            with self.subTest(line=line):
                self.assertIn(rule_id, self.scan(line + "\n"))

    def test_a_users_path_at_the_start_of_an_added_line_is_caught(self):
        # Round 3: the hooks feed "+..." lines, and file:///Users/... has a "/" before it.
        for line in ("+/Users/jdoe/x", "url file:///Users/jdoe/x"):  # betterleaks:allow (deliberate sample)
            with self.subTest(line=line):
                self.assertIn("posix-users-account", self.scan(line + "\n"))

    def test_placeholders_and_the_allow_marker_pass(self):
        self.assertEqual(self.scan(SAMPLE_CLEAN), [])


@unittest.skipUnless(shutil.which("git"), "git not installed")
class HookEndToEnd(unittest.TestCase):
    """Real commits in a scratch repository whose local core.hooksPath is a copy of the hooks."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.hooks = Path(self.tmp) / "hooks"
        self.hooks.mkdir()
        for name in ("pre-commit", "privacy-rules.toml") + EXTRA_FILES:
            shutil.copy(HOOKS / name, self.hooks / name)
        shutil.copy(HOOKS / "pre-commit", self.hooks / "pre-merge-commit")
        shutil.copy(HOOKS / "_chain", self.hooks / "post-commit")
        shutil.copy(HOOKS / "_chain", self.hooks / "commit-msg")
        self.repo = Path(self.tmp) / "repo"
        self.repo.mkdir()
        self.env = isolated_env(self.tmp, USERNAME="zqacct", USER="zqacct")
        for cmd in (["git", "init", "-q", "."],
                    ["git", "config", "user.email", "t@example.org"],
                    ["git", "config", "user.name", "t"],
                    ["git", "config", "core.hooksPath", self.hooks.as_posix()]):
            run(cmd, self.repo, self.env)

    def commit(self, content, name="f.txt", env=None, message="t"):
        env = env or self.env
        target = self.repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        run(["git", "add", name], self.repo, env)
        return run(["git", "commit", "-qm", message], self.repo, env)

    def write_terms(self, *terms, extra=False):
        """Write the machine-local deny list the way the installer does (fictitious names only, R34)."""
        name = "private-terms.extra.txt" if extra else "private-terms.txt"
        (self.hooks / name).write_text("# comment\n\n" + "\n".join(terms) + "\n", encoding="utf-8")

    def repo_hook(self, name, marker):
        hook = self.repo / ".git" / "hooks" / name
        hook.write_text("#!/bin/sh\necho ran > '%s'\n" % (self.repo / marker).as_posix(),
                        encoding="utf-8", newline="\n")
        hook.chmod(0o755)

    def test_clean_commit_passes_and_chains_the_repository_hooks(self):
        self.repo_hook("pre-commit", "pre.marker")
        self.repo_hook("post-commit", "post.marker")
        result = self.commit("nothing personal here\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.repo / "pre.marker").exists(), "repository pre-commit not chained")
        self.assertTrue((self.repo / "post.marker").exists(), "repository post-commit not chained")

    def test_a_third_repository_hook_is_chained_too(self):
        self.repo_hook("commit-msg", "msg.marker")
        result = self.commit("nothing personal here\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.repo / "msg.marker").exists(), "repository commit-msg not chained")

    def test_short_account_inside_a_word_passes(self):
        # PR #40 review: account "dev" must not match "device" or "devops".
        env = dict(self.env, USERNAME="dev", USER="dev")
        result = self.commit("device driver and devops notes\n", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_short_account_as_a_token_is_refused(self):
        env = dict(self.env, USERNAME="dev", USER="dev")
        result = self.commit("owner dev here\n", name="owner.txt", env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("owner.txt", result.stderr)

    def test_account_name_is_refused_without_echoing_the_line(self):
        result = self.commit("secret line zqacct here\n", name="notes.txt")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("notes.txt", result.stderr)
        self.assertNotIn("secret line", result.stderr)

    def test_allow_marker_lets_a_deliberate_line_through(self):
        result = self.commit("zqacct betterleaks:allow\n")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_opt_out_lets_a_private_repository_through(self):
        run(["git", "config", "privacyguard.enabled", "false"], self.repo, self.env)
        result = self.commit("zqacct C:\\Users\\jdoe\\x\n")  # betterleaks:allow (deliberate sample)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(BETTERLEAKS, "betterleaks not installed")
    def test_personal_data_shape_is_refused(self):
        result = self.commit("config C:\\Users\\jdoe\\.config\\x\n")  # betterleaks:allow (deliberate sample)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("privacy guard", result.stderr)

    # Round 2 of the local review (R35): bypasses reproduced against the previous hook.

    @unittest.skipUnless(BETTERLEAKS, "betterleaks not installed")
    def test_a_gitattributes_no_diff_cannot_hide_content(self):
        (self.repo / ".gitattributes").write_text("* -diff\n", encoding="utf-8")
        run(["git", "add", ".gitattributes"], self.repo, self.env)
        result = self.commit("config C:\\Users\\jdoe\\.config\\x\n", name="hidden.md")  # betterleaks:allow (deliberate sample)
        self.assertNotEqual(result.returncode, 0, "a -diff attribute hid the staged content")

    def test_a_content_line_starting_with_plus_plus_is_still_checked(self):
        # With -U0 an added line "++ x" appears as "+++ x", once taken for a file header.
        result = self.commit("++ zqacct notes\n", name="plus.md")
        self.assertNotEqual(result.returncode, 0)

    def test_the_account_name_in_a_staged_path_is_refused(self):
        result = self.commit("nothing personal\n", name="zqacct-session.txt")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("zqacct-session.txt", result.stderr)

    @unittest.skipUnless(BETTERLEAKS, "betterleaks not installed")
    def test_a_merge_commit_is_checked(self):
        # A clean merge runs pre-merge-commit only, never pre-commit.
        self.assertEqual(self.commit("base\n").returncode, 0)
        run(["git", "checkout", "-qb", "side"], self.repo, self.env)
        (self.repo / "side.md").write_text("code ABCD12345678\n", encoding="utf-8")  # betterleaks:allow (deliberate sample)
        run(["git", "add", "side.md"], self.repo, self.env)
        run(["git", "commit", "-qm", "side", "--no-verify"], self.repo, self.env)
        run(["git", "checkout", "-q", "-"], self.repo, self.env)
        result = run(["git", "merge", "--no-ff", "-q", "-m", "merge", "side"], self.repo, self.env)
        self.assertNotEqual(result.returncode, 0, "a clean merge brought content in unchecked")


    # 2026-10-12 (PR #69): a real student name inside a data-folder path passed every rule,
    # because a name has no shape. The machine-local deny list is what can refuse it.

    def test_a_deny_list_term_in_an_added_line_is_refused_without_echoing_it(self):
        self.write_terms("Quenby")
        result = self.commit("path C:\\Work\\Zorblat Quenby\\x\n", name="fixture.md")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fixture.md", result.stderr)
        self.assertNotIn("Quenby", result.stderr)

    def test_a_deny_list_term_is_matched_in_any_case_and_only_as_a_whole_token(self):
        self.write_terms("Quenby")
        self.assertNotEqual(self.commit("by QUENBY\n", name="a.md").returncode, 0)
        run(["git", "reset", "-q"], self.repo, self.env)  # a refused commit leaves its file staged
        self.assertEqual(self.commit("quenbyville and unquenbyed\n", name="b.md").returncode, 0)

    def test_a_deny_list_term_in_a_staged_path_is_refused(self):
        self.write_terms("Quenby")
        result = self.commit("nothing personal\n", name="notes-quenby.md")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("notes-quenby.md", result.stderr)

    def test_a_hand_written_extra_list_is_read_too(self):
        self.write_terms("Quenby", extra=True)
        self.assertNotEqual(self.commit("by Quenby\n").returncode, 0)

    def test_a_multi_word_term_matches_the_whole_phrase(self):
        self.write_terms("Zorblat Quenby")
        self.assertNotEqual(self.commit("by Zorblat Quenby\n", name="a.md").returncode, 0)
        run(["git", "reset", "-q"], self.repo, self.env)  # a refused commit leaves its file staged
        self.assertEqual(self.commit("Zorblat alone\n", name="b.md").returncode, 0)

    def test_the_allow_marker_and_the_opt_out_still_apply_to_a_deny_list_term(self):
        self.write_terms("Quenby")
        self.assertEqual(self.commit("Quenby betterleaks:allow\n", name="a.md").returncode, 0)
        run(["git", "config", "privacyguard.enabled", "false"], self.repo, self.env)
        self.assertEqual(self.commit("Quenby\n", name="b.md").returncode, 0)

    def test_a_term_shorter_than_the_configured_floor_is_ignored(self):
        self.write_terms("Ab")
        self.assertEqual(self.commit("an Ab here\n").returncode, 0)
        run(["git", "config", "privacyguard.minTermLength", "2"], self.repo, self.env)
        self.assertNotEqual(self.commit("an Ab here\n", name="b.md").returncode, 0)

    def test_removing_a_deny_list_term_is_not_refused(self):
        self.write_terms("Quenby")
        (self.repo / "old.md").write_text("by Quenby\nkeep\n", encoding="utf-8")
        run(["git", "add", "old.md"], self.repo, self.env)
        run(["git", "commit", "-qm", "old", "--no-verify"], self.repo, self.env)
        self.assertEqual(self.commit("keep\n", name="old.md").returncode, 0)

    # 2026-10-15, PR #71 round 1 (Issue #70 H2, M1, M4 and the local /code-review at high effort).

    def reset(self):
        run(["git", "reset", "-q"], self.repo, self.env)  # a refused commit leaves its file staged

    def test_deleting_a_file_whose_path_carries_a_term_is_not_refused(self):
        # H2: the pre-commit diff already drops deletions; this pins that both stages agree.
        self.write_terms("Quenby")
        (self.repo / "notes-quenby.md").write_text("keep\n", encoding="utf-8")
        run(["git", "add", "notes-quenby.md"], self.repo, self.env)
        run(["git", "commit", "-qm", "old", "--no-verify"], self.repo, self.env)
        run(["git", "rm", "-q", "notes-quenby.md"], self.repo, self.env)
        result = run(["git", "commit", "-qm", "cleanup"], self.repo, self.env)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_term_inside_a_snake_case_or_camel_case_name_is_refused(self):
        # An identifier or a data folder is written data_<name>_run or Data<Name>; underscore,
        # digit and a case change are not word boundaries for a name.
        self.write_terms("Quenby")
        for index, line in enumerate(("data_quenby_run\n", "DataQuenby\n", "quenby2024 folder\n")):
            result = self.commit(line, name="f%d.md" % index)
            self.assertNotEqual(result.returncode, 0, line)
            self.reset()

    def test_a_term_still_does_not_match_inside_an_ordinary_longer_word(self):
        self.write_terms("Quenby")
        self.assertEqual(self.commit("quenbyville unquenbyed Quenbyish\n", name="a.md").returncode, 0)

    def test_a_term_in_a_non_ascii_path_is_refused_without_octal_escapes(self):
        # core.quotepath would print the path as "donn\303\251es-quenby.md" in the diff header.
        self.write_terms("Quenby")
        result = self.commit("nothing personal\n", name="donn\u00e9es-quenby.md")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("\\303", result.stderr)

    def test_a_utf8_bom_on_the_hand_written_list_does_not_disable_its_first_term(self):
        (self.hooks / "private-terms.extra.txt").write_bytes(b"\xef\xbb\xbfQuenby\nSecondterm\n")
        self.assertNotEqual(self.commit("by Quenby\n", name="a.md").returncode, 0)
        self.reset()
        self.assertNotEqual(self.commit("by Secondterm\n", name="b.md").returncode, 0)

    def test_a_global_diff_noprefix_cannot_hide_a_fixture_path_or_a_term_in_a_path(self):
        # Round 3: with diff.noprefix the "+++ " path lost its first two characters, so a
        # top-level tests/ file was no longer a fixture and a leading folder escaped the check.
        run(["git", "config", "diff.noprefix", "true"], self.repo, self.env)
        run(["git", "config", "privacyguard.absolutePaths", "refuse"], self.repo, self.env)
        self.assertNotEqual(self.commit('p = "C:\\\\Kestrel\\\\data"\n', name="tests/test_x.py").returncode, 0)
        self.reset()
        self.write_terms("Quenby")
        self.assertNotEqual(self.commit("nothing personal\n", name="quenby/x.md").returncode, 0)

    def test_a_utf16_list_file_is_reported_and_never_counted_as_usable(self):
        # Security review LOW 3: PowerShell 5.1 `>>` and Notepad's "Unicode" write UTF-16, whose
        # NUL bytes made every term unmatchable while the file still counted as a usable list.
        (self.hooks / "private-terms.extra.txt").write_bytes("Quenby\n".encode("utf-16"))
        result = self.commit("by Quenby\n", name="a.md")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("UTF-16", result.stderr)
        self.assertIn("private-terms.extra.txt", result.stderr)
        self.assertIn("no usable term", result.stderr)

    def test_a_nul_byte_list_without_a_bom_is_reported_too(self):
        (self.hooks / "private-terms.txt").write_bytes(b"Q\x00u\x00e\x00n\x00b\x00y\x00\n")
        result = self.commit("by Quenby\n", name="a.md")
        self.assertIn("UTF-16", result.stderr)

    def test_a_good_list_still_works_beside_a_utf16_one(self):
        (self.hooks / "private-terms.extra.txt").write_bytes("Zorblat\n".encode("utf-16"))
        self.write_terms("Quenby")
        self.assertNotEqual(self.commit("by Quenby\n", name="a.md").returncode, 0)

    def test_a_header_only_deny_list_is_reported_not_silent(self):
        # Issue #70 / review: a list holding no usable term guards nothing and said nothing.
        self.write_terms()
        result = self.commit("by Quenby\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no usable term", result.stderr)

    def test_an_awk_that_cannot_run_the_scan_says_so_and_does_not_block(self):
        # A bad regex typed in fixture-path-allow.txt makes awk exit non-zero on the first
        # drive path. That used to switch the whole scan off with no message at all.
        self.write_terms("Quenby")
        (self.hooks / "fixture-path-allow.txt").write_text("^[A-Za-z]:(\n", encoding="utf-8")
        result = self.commit('p = "C:\\\\Kestrel\\\\data"\n', name="Test/test_x.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("could not run", result.stderr)

    # Round 2 of the local review (2026-10-15).

    def test_a_drive_path_after_a_backslash_escape_or_inside_a_file_url_is_still_reported(self):
        # The left-boundary rule that stops "https://" must not hide a real path that follows
        # a literal \n or sits inside file:///, the way serialized logs reach a fixture.
        run(["git", "config", "privacyguard.absolutePaths", "refuse"], self.repo, self.env)
        for index, line in enumerate((r'x = "out\nC:\\Kestrel\\x"', r'x = "out\tD:\\Kestrel\\x"',
                                      'u = "file:///D:/Kestrel/y"', 'u = "file:///C:/Kestrel/z"')):
            result = self.commit(line + "\n", name="Test/test_p%d.py" % index)
            self.assertNotEqual(result.returncode, 0, line)
            self.reset()

    def test_a_term_in_a_directory_whose_name_contains_space_b_slash_is_refused(self):
        # "quenby b/x.md" makes the diff header ambiguous for a split on the last " b/".
        self.write_terms("Quenby")
        result = self.commit("nothing personal\n", name="quenby b/x.md")
        self.assertNotEqual(result.returncode, 0)

    def test_a_bad_path_allowlist_does_not_disable_the_name_check(self):
        # The path check reads regexes from a hand-edited file; a typo there made awk die and
        # the name check, which needs none of it, died with it.
        self.write_terms("Quenby")
        (self.hooks / "fixture-path-allow.txt").write_text("^[A-Za-z]:(\n", encoding="utf-8")
        result = self.commit('by Quenby and p = "C:\\\\Kestrel\\\\data"\n', name="Test/test_x.py")
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn("could not run", result.stderr)
        self.assertNotIn("Quenby", result.stderr)

    def test_a_url_in_a_test_file_is_not_an_absolute_drive_path(self):
        run(["git", "config", "privacyguard.absolutePaths", "refuse"], self.repo, self.env)
        result = self.commit('u = "https://example.org/x"\n', name="Test/test_u.py")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_generic_data_root_is_not_allowlisted(self):
        # A real run's folder is most often D:\data\<person>; allowlisting the root hid it.
        run(["git", "config", "privacyguard.absolutePaths", "refuse"], self.repo, self.env)
        result = self.commit('p = "D:\\\\data\\\\Kestrel"\n', name="Test/test_x.py")
        self.assertNotEqual(result.returncode, 0)

    def test_the_path_warning_names_its_remedy(self):
        result = self.commit('p = "C:\\\\Kestrel\\\\data"\n', name="Test/test_x.py")
        self.assertIn("absolutePaths", result.stderr)

    def test_a_copy_of_the_deny_list_itself_is_refused_at_commit(self):
        # Every line of the list is a term, so staging the list into a repository trips the
        # same scan. Defence in depth behind the global ignore, and the claim it makes about
        # the list never being committable is proven here rather than deduced.
        self.write_terms("Quenby", "Zorblat")
        for name in ("private-terms.txt", "private-terms.extra.txt", "notes/terms-copy.txt"):
            copy = (self.hooks / "private-terms.txt").read_text(encoding="utf-8")
            result = self.commit(copy, name=name)
            self.assertNotEqual(result.returncode, 0, name)
            self.assertNotIn("Quenby", result.stderr)
            self.reset()

    def test_no_deny_list_at_all_is_a_silent_pass(self):
        result = self.commit("by Quenby\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("deny", result.stderr)

    def test_a_missing_extra_scan_library_is_a_silent_pass(self):
        # R11: a hook whose own dependency is absent must not refuse the commit.
        self.write_terms("Quenby")
        (self.hooks / "privacy-lib.sh").unlink()
        self.assertEqual(self.commit("by Quenby\n").returncode, 0)

    def test_an_absolute_path_in_a_test_file_is_warned_by_default_and_not_blocked(self):
        result = self.commit('p = "C:\\\\Kestrel\\\\data"\n', name="Test/test_x.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Test/test_x.py", result.stderr)
        self.assertIn("absolute drive path", result.stderr)

    def test_an_absolute_path_in_a_test_file_is_refused_when_configured(self):
        run(["git", "config", "privacyguard.absolutePaths", "refuse"], self.repo, self.env)
        result = self.commit('p = "C:\\\\Kestrel\\\\data"\n', name="Test/test_x.py")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Kestrel", result.stderr)

    def test_an_allowlisted_fictitious_root_and_a_non_test_file_are_not_reported(self):
        run(["git", "config", "privacyguard.absolutePaths", "refuse"], self.repo, self.env)
        self.assertEqual(self.commit('p = "C:\\\\Work\\\\Demo"\n', name="Test/test_x.py").returncode, 0)
        self.assertEqual(self.commit('see C:\\Kestrel\\data\n', name="docs/note.md").returncode, 0)
        self.assertEqual(self.commit('p = "C:\\\\Kestrel" betterleaks:allow\n', name="Test/test_y.py").returncode, 0)

    def test_the_path_check_can_be_switched_off(self):
        run(["git", "config", "privacyguard.absolutePaths", "off"], self.repo, self.env)
        result = self.commit('p = "C:\\\\Kestrel\\\\data"\n', name="Test/test_x.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("absolute drive path", result.stderr)

    @unittest.skipUnless(BETTERLEAKS, "betterleaks not installed")
    def test_removing_a_leaking_line_is_not_refused(self):
        # Round 3: only ADDED lines are scanned, so cleaning up old data must pass.
        (self.repo / "old.md").write_text("code ABCD12345678\nkeep\n", encoding="utf-8")  # betterleaks:allow (deliberate sample)
        run(["git", "add", "old.md"], self.repo, self.env)
        run(["git", "commit", "-qm", "old", "--no-verify"], self.repo, self.env)
        result = self.commit("keep\n", name="old.md")
        self.assertEqual(result.returncode, 0, result.stderr)


@unittest.skipUnless(shutil.which("git") and BETTERLEAKS, "git or betterleaks not installed")
class PrePushEndToEnd(unittest.TestCase):
    """Round 3: pre-push scans what a push publishes, whatever made the commits."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        hooks = Path(self.tmp) / "hooks"
        hooks.mkdir()
        for name in ("pre-push", "privacy-rules.toml") + EXTRA_FILES:
            shutil.copy(HOOKS / name, hooks / name)
        self.hooks = hooks
        self.env = isolated_env(self.tmp, USERNAME="zqacct", USER="zqacct")
        remote = Path(self.tmp) / "remote.git"
        run(["git", "init", "-q", "--bare", str(remote)], self.tmp, self.env)
        self.repo = Path(self.tmp) / "repo"
        self.repo.mkdir()
        for cmd in (["git", "init", "-q", "-b", "main", "."],
                    ["git", "config", "user.email", "t@example.org"],
                    ["git", "config", "user.name", "t"],
                    ["git", "config", "core.hooksPath", hooks.as_posix()],
                    ["git", "remote", "add", "origin", remote.as_posix()]):
            run(cmd, self.repo, self.env)

    def commit(self, content, message="t"):
        (self.repo / "f.md").write_text(content, encoding="utf-8")
        run(["git", "add", "f.md"], self.repo, self.env)
        run(["git", "commit", "-qm", message, "--no-verify"], self.repo, self.env)

    def push(self):
        return run(["git", "push", "-q", "origin", "main"], self.repo, self.env)

    def test_clean_push_passes_and_chains_the_repository_pre_push(self):
        hook = self.repo / ".git" / "hooks" / "pre-push"
        marker = self.repo / "push.marker"
        hook.write_text("#!/bin/sh\ncat > '%s'\n" % marker.as_posix(), encoding="utf-8", newline="\n")
        hook.chmod(0o755)
        self.commit("nothing personal\n")
        result = self.push()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("refs/heads/main", marker.read_text(encoding="utf-8"), "stdin not chained")

    def test_a_no_verify_commit_is_refused_at_push(self):
        self.commit("code ABCD12345678\n")  # betterleaks:allow (deliberate sample)
        result = self.push()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("privacy guard", result.stderr)

    def test_a_leak_in_a_commit_message_is_refused_at_push(self):
        self.commit("nothing personal\n", message="from C:\\Users\\jdoe\\x")  # betterleaks:allow (deliberate sample)
        self.assertNotEqual(self.push().returncode, 0)

    def test_a_oneline_pretty_config_cannot_hide_a_message(self):
        # Round-3 review: format.pretty=oneline put the message on the commit line, unscanned.
        run(["git", "config", "format.pretty", "oneline"], self.repo, self.env)
        self.commit("nothing personal\n", message="from C:\\Users\\jdoe\\x")  # betterleaks:allow (deliberate sample)
        self.assertNotEqual(self.push().returncode, 0)

    # 2026-10-12: the deny list must also stop a --no-verify commit and a commit message.

    def test_a_deny_list_term_in_a_no_verify_commit_is_refused_at_push(self):
        (self.hooks / "private-terms.txt").write_text("Quenby\n", encoding="utf-8")
        self.commit("by Quenby\n")
        result = self.push()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("f.md", result.stderr)
        self.assertNotIn("Quenby", result.stderr)

    def test_a_deny_list_term_in_a_commit_message_is_refused_at_push(self):
        (self.hooks / "private-terms.txt").write_text("Quenby\n", encoding="utf-8")
        self.commit("nothing personal\n", message="notes for Quenby")
        result = self.push()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("commit message", result.stderr)

    def test_a_clean_push_passes_with_a_deny_list_present(self):
        (self.hooks / "private-terms.txt").write_text("Quenby\n", encoding="utf-8")
        self.commit("nothing personal\n")
        self.assertEqual(self.push().returncode, 0)

    def test_the_deny_list_still_works_when_the_betterleaks_scan_is_skipped(self):
        # The deny-list scan needs no betterleaks. Removing the rules file takes the same
        # branch as a missing binary ([ -n "$bl" ] && [ -f "$rules" ] false), which is what
        # this exercises; a PATH without the binary is not staged here (Issue #70 M4a).
        (self.hooks / "private-terms.txt").write_text("Quenby\n", encoding="utf-8")
        (self.hooks / "privacy-rules.toml").unlink()
        self.commit("by Quenby\n")
        self.assertNotEqual(self.push().returncode, 0)

    # 2026-10-15, PR #71 round 1.

    def commit_file(self, name, content, message="t"):
        target = self.repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        run(["git", "add", name], self.repo, self.env)
        run(["git", "commit", "-qm", message, "--no-verify"], self.repo, self.env)

    def remove_after_first_push(self, name):
        """Publish a file, then add the deny list, then commit its removal (the remediation)."""
        self.commit_file(name, "keep\n")
        self.assertEqual(self.push().returncode, 0)
        (self.hooks / "private-terms.txt").write_text("Quenby\n", encoding="utf-8")

    def test_deleting_a_file_whose_path_carries_a_term_is_not_refused_at_push(self):
        # Issue #70 H2: the cleanup of a leaked path was refused at push, passed at commit.
        self.remove_after_first_push("notes-quenby.md")
        run(["git", "rm", "-q", "notes-quenby.md"], self.repo, self.env)
        run(["git", "commit", "-qm", "cleanup", "--no-verify"], self.repo, self.env)
        result = self.push()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_renaming_a_file_away_from_a_term_path_is_not_refused_at_push(self):
        self.remove_after_first_push("notes-quenby.md")
        run(["git", "mv", "notes-quenby.md", "notes-clean.md"], self.repo, self.env)
        run(["git", "commit", "-qm", "rename", "--no-verify"], self.repo, self.env)
        self.assertEqual(self.push().returncode, 0)

    def test_renaming_a_file_onto_a_term_path_is_refused_at_push(self):
        self.remove_after_first_push("notes-clean.md")
        run(["git", "mv", "notes-clean.md", "notes-quenby.md"], self.repo, self.env)
        run(["git", "commit", "-qm", "rename", "--no-verify"], self.repo, self.env)
        self.assertNotEqual(self.push().returncode, 0)

    def test_a_deletion_does_not_hide_a_term_added_elsewhere_in_the_same_push(self):
        # The deletion exemption must not end the scan of what follows it in the stream.
        self.remove_after_first_push("notes-quenby.md")
        run(["git", "rm", "-q", "notes-quenby.md"], self.repo, self.env)
        (self.repo / "other.md").write_text("by Quenby\n", encoding="utf-8")
        run(["git", "add", "other.md"], self.repo, self.env)
        run(["git", "commit", "-qm", "mixed", "--no-verify"], self.repo, self.env)
        self.assertNotEqual(self.push().returncode, 0)

    def test_a_term_in_the_commit_author_is_refused_at_push(self):
        (self.hooks / "private-terms.txt").write_text("Quenby\n", encoding="utf-8")
        (self.repo / "f.md").write_text("nothing personal\n", encoding="utf-8")
        run(["git", "add", "f.md"], self.repo, self.env)
        run(["git", "commit", "-qm", "t", "--no-verify", "--author", "Quenby Z <z@example.org>"],
            self.repo, self.env)
        result = self.push()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Quenby", result.stderr)
        self.assertIn("rewrite the author", result.stderr)  # round 3: no marker can sit in an Author line

    def test_only_new_commits_are_scanned_after_the_first_push(self):
        self.commit("nothing personal\n")
        self.assertEqual(self.push().returncode, 0)
        self.commit("still nothing\n")
        self.assertEqual(self.push().returncode, 0)


POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")


@unittest.skipUnless(POWERSHELL and shutil.which("git"), "PowerShell or git not installed")
class Installer(unittest.TestCase):
    """install-git-hooks.ps1 against a scratch global config, never the real one."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        # XDG_CONFIG_HOME: the installer writes the global git ignore there when core.excludesFile
        # is unset, which must never be the real ~/.config of whoever runs the suite.
        self.xdg = Path(self.tmp) / "xdg"
        self.env = isolated_env(self.tmp, XDG_CONFIG_HOME=str(self.xdg))
        self.target = Path(self.tmp) / "hooks"

    def install(self, *args):
        return run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                    str(HOOKS / "install-git-hooks.ps1"), "-Target", str(self.target), *args],
                   self.tmp, self.env)

    def global_hooks_path(self):
        return run(["git", "config", "--global", "--get", "core.hooksPath"], self.tmp, self.env).stdout.strip()

    def test_dry_run_changes_nothing(self):
        result = self.install("-DryRun")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.target.exists())
        self.assertEqual(self.global_hooks_path(), "")

    def test_install_copies_the_hooks_and_sets_core_hooks_path(self):
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name in ("pre-commit", "privacy-rules.toml", "pre-push", "commit-msg"):
            self.assertTrue((self.target / name).is_file(), name)
        # Round 3: pre-push is the privacy script, not the plain chain.
        self.assertEqual((self.target / "pre-push").read_bytes(), (HOOKS / "pre-push").read_bytes())
        self.assertEqual(Path(self.global_hooks_path()), self.target)

    def test_foreign_hook_already_in_the_target_is_refused_not_overwritten(self):
        # PR #40 review: core.hooksPath equal to the target does not prove ownership.
        self.target.mkdir()
        foreign = "#!/bin/sh\necho another manager\n"
        (self.target / "pre-push").write_text(foreign, encoding="utf-8")
        run(["git", "config", "--global", "core.hooksPath", self.target.as_posix()], self.tmp, self.env)
        result = self.install()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("pre-push", result.stdout)
        self.assertEqual((self.target / "pre-push").read_text(encoding="utf-8"), foreign)
        self.assertFalse((self.target / "pre-commit").exists())

    def test_reinstall_over_its_own_files_succeeds(self):
        self.assertEqual(self.install().returncode, 0)
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_uninstall_unsets_and_leaves_the_files(self):
        self.assertEqual(self.install().returncode, 0)
        result = self.install("-Uninstall")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.global_hooks_path(), "")
        self.assertTrue((self.target / "pre-commit").is_file())

    def test_uninstall_dry_run_changes_nothing(self):
        self.assertEqual(self.install().returncode, 0)
        result = self.install("-Uninstall", "-DryRun")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(Path(self.global_hooks_path()), self.target)

    def test_install_copies_the_extra_scan_files(self):
        self.assertEqual(self.install().returncode, 0)
        for name in EXTRA_FILES:
            self.assertEqual((self.target / name).read_bytes(), (HOOKS / name).read_bytes(), name)

    def make_students(self, *names):
        root = Path(self.tmp) / "students"
        for n in names:
            (root / "2026" / n).mkdir(parents=True)
        return root

    def test_terms_from_writes_the_split_names_and_prints_only_a_count(self):
        root = self.make_students("ZorblatQuenby", "Ab")
        result = self.install("-TermsFrom", str(root))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        terms = [l for l in (self.target / "private-terms.txt").read_text(encoding="utf-8").splitlines()
                 if l and not l.startswith("#")]
        self.assertEqual(sorted(t.lower() for t in terms), ["quenby", "zorblat", "zorblatquenby"])
        self.assertNotIn("Quenby", result.stdout + result.stderr)
        self.assertIn("3 deny-list terms", result.stdout)

    def test_terms_from_skips_the_year_level_and_short_fragments(self):
        root = self.make_students("Ab", "Zorblat")
        self.assertEqual(self.install("-TermsFrom", str(root)).returncode, 0)
        text = (self.target / "private-terms.txt").read_text(encoding="utf-8")
        self.assertNotIn("2026", text)
        self.assertNotRegex(text, r"(?mi)^ab$")

    def test_terms_from_leaves_the_hand_written_extra_list_alone(self):
        self.target.mkdir()
        extra = self.target / "private-terms.extra.txt"
        extra.write_text("Handmade\n", encoding="utf-8")
        root = self.make_students("ZorblatQuenby")
        self.assertEqual(self.install("-TermsFrom", str(root)).returncode, 0)
        self.assertEqual(extra.read_text(encoding="utf-8"), "Handmade\n")

    def test_terms_from_dry_run_writes_nothing(self):
        root = self.make_students("ZorblatQuenby")
        result = self.install("-TermsFrom", str(root), "-DryRun")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.target.exists())

    def test_terms_from_a_missing_directory_is_refused_and_writes_nothing(self):
        result = self.install("-TermsFrom", str(Path(self.tmp) / "no-such-dir"))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertFalse(self.target.exists())

    # 2026-10-15, PR #71 round 1 (Issue #70 M1, M2 and the local review).

    def read_terms(self):
        text = (self.target / "private-terms.txt").read_text(encoding="utf-8")
        return sorted(l.lower() for l in text.splitlines() if l and not l.startswith("#"))

    def test_terms_from_drops_ordinary_words_listed_in_the_stopword_file(self):
        # M1: a folder fragment equal to a common word would refuse ordinary prose everywhere.
        root = self.make_students("ZorblatGrant")
        result = self.install("-TermsFrom", str(root))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        terms = self.read_terms()
        self.assertIn("zorblat", terms)
        self.assertNotIn("grant", terms)
        self.assertIn("excluded", result.stdout)

    def test_the_stopword_file_is_lowercase_data_that_ships_with_the_hooks(self):
        words = [l for l in (HOOKS / "deny-term-stopwords.txt").read_text(encoding="utf-8").splitlines()
                 if l and not l.startswith("#")]
        self.assertIn("grant", words)
        self.assertTrue(all(w == w.lower() and w == w.strip() for w in words))

    def test_the_minimum_term_length_has_one_owner(self):
        # M2: the installer and the hook each carried a literal 4, and the installer's filter
        # made a lower privacyguard.minTermLength unable to take effect for generated terms.
        conf = (HOOKS / "privacy-guard.conf").read_text(encoding="utf-8")
        self.assertRegex(conf, r"(?m)^min_term_length=\d+$")
        installer = (HOOKS / "install-git-hooks.ps1").read_text(encoding="utf-8")
        library = (HOOKS / "privacy-lib.sh").read_text(encoding="utf-8")
        self.assertNotRegex(installer, r"\$TermMinLength\s*=\s*\d")
        self.assertNotRegex(library, r"min_len=\d")

    def test_terms_from_honours_the_git_config_floor_the_hook_also_reads(self):
        # Same effective floor on both sides: lowering privacyguard.minTermLength must reach
        # the generated list, not only the hand-written one.
        root = self.make_students("ZorblatAb")
        self.assertEqual(self.install("-TermsFrom", str(root)).returncode, 0)
        self.assertNotIn("ab", self.read_terms())
        run(["git", "config", "--global", "privacyguard.minTermLength", "2"], self.tmp, self.env)
        self.assertEqual(self.install("-TermsFrom", str(root)).returncode, 0)
        self.assertIn("ab", self.read_terms())

    def test_terms_from_with_nothing_found_is_refused_and_keeps_the_previous_list(self):
        first = self.make_students("ZorblatQuenby")
        self.assertEqual(self.install("-TermsFrom", str(first)).returncode, 0)
        before = (self.target / "private-terms.txt").read_bytes()
        empty = Path(self.tmp) / "empty-root"
        empty.mkdir()
        result = self.install("-TermsFrom", str(empty))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual((self.target / "private-terms.txt").read_bytes(), before)

    # The owner runs the command for every NEW student, so the list is only ever APPENDED to:
    # a rerun used to rewrite it wholesale, which dropped a graduated student's name and
    # erased a line added by hand.

    def second_root(self, *names):
        root = Path(self.tmp) / "more-students"
        for n in names:
            (root / "2026" / n).mkdir(parents=True)
        return root

    def test_a_new_student_is_appended_and_the_existing_file_is_never_rewritten(self):
        first = self.make_students("ZorblatQuenby")
        self.assertEqual(self.install("-TermsFrom", str(first)).returncode, 0)
        before = (self.target / "private-terms.txt").read_bytes()
        result = self.install("-TermsFrom", str(self.second_root("FenwickOrmond")))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        after = (self.target / "private-terms.txt").read_bytes()
        self.assertTrue(after.startswith(before), "the existing bytes were not preserved")
        self.assertEqual(self.read_terms(), sorted(["zorblat", "quenby", "zorblatquenby",
                                                    "fenwick", "ormond", "fenwickormond"]))
        self.assertIn("3 added", result.stdout)
        self.assertNotIn("Fenwick", result.stdout + result.stderr)

    def test_a_student_who_left_the_disk_stays_in_the_list(self):
        # Graduating folders are archived or deleted; their names must keep being refused.
        first = self.make_students("ZorblatQuenby")
        self.assertEqual(self.install("-TermsFrom", str(first)).returncode, 0)
        self.assertEqual(self.install("-TermsFrom", str(self.second_root("FenwickOrmond"))).returncode, 0)
        self.assertIn("quenby", self.read_terms())

    def test_running_the_same_folder_again_adds_nothing_and_changes_no_byte(self):
        root = self.make_students("ZorblatQuenby")
        self.assertEqual(self.install("-TermsFrom", str(root)).returncode, 0)
        before = (self.target / "private-terms.txt").read_bytes()
        result = self.install("-TermsFrom", str(root))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.target / "private-terms.txt").read_bytes(), before)
        self.assertIn("0 added", result.stdout)

    def test_a_line_added_by_hand_to_the_generated_list_survives_a_run(self):
        root = self.make_students("ZorblatQuenby")
        self.assertEqual(self.install("-TermsFrom", str(root)).returncode, 0)
        listing = self.target / "private-terms.txt"
        with listing.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write("Handmade\n")
        self.assertEqual(self.install("-TermsFrom", str(self.second_root("FenwickOrmond"))).returncode, 0)
        self.assertIn("handmade", self.read_terms())

    def test_a_term_is_not_appended_twice_whatever_its_case_and_a_missing_final_newline_is_handled(self):
        self.target.mkdir()
        (self.target / "private-terms.txt").write_bytes(b"# header\nZORBLAT")  # no final newline
        root = self.make_students("ZorblatQuenby")
        self.assertEqual(self.install("-TermsFrom", str(root)).returncode, 0)
        lines = [l for l in (self.target / "private-terms.txt").read_text(encoding="utf-8").splitlines()
                 if l and not l.startswith("#")]
        self.assertEqual(sorted(l.lower() for l in lines), ["quenby", "zorblat", "zorblatquenby"])
        self.assertEqual(len(lines), len(set(l.lower() for l in lines)))

    def test_the_refusal_json_carries_no_path(self):
        # The human line names a category; the JSON report used to carry target and
        # previous_hooks_path, which hold the account name.
        root = self.make_students("ZorblatQuenby")
        self.synced_target("OneDrive")
        result = self.install("-TermsFrom", str(root), "-Json")
        self.assertEqual(result.returncode, 2)
        shown = result.stdout + result.stderr
        self.assertNotIn(self.tmp, shown)
        self.assertNotIn(self.tmp.replace("\\", "/"), shown)

    def test_more_sync_clients_and_french_folder_names_are_refused_but_a_lookalike_is_not(self):
        root = self.make_students("ZorblatQuenby")
        for parts in (("Box",), ("Mon Drive",), ("Mon disque",), ("MEGA",), ("MEGAsync",), ("Sync",)):
            self.synced_target(*parts)
            self.assertEqual(self.install("-TermsFrom", str(root)).returncode, 2, parts)
        # The negative control: an ordinary local folder that merely starts like a client.
        self.synced_target("mega-study")
        self.assertEqual(self.install("-TermsFrom", str(root)).returncode, 0)

    def test_a_blank_marker_line_cannot_turn_into_a_marker_that_matches_everything(self):
        markers = (HOOKS / "sync-folder-markers.txt").read_text(encoding="utf-8").splitlines()
        self.assertTrue(all(l == l.strip() for l in markers if l), "a marker line carries stray whitespace")

    def test_fragments_below_the_length_floor_are_counted_and_kept_for_review(self):
        # Security review LOW 2: a short surname (Li, Wu, Kim) was skipped with no sign at all.
        root = self.make_students("ZorblatKim")
        result = self.install("-TermsFrom", str(root))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("1 fragments set aside", result.stdout)
        review = (self.target / "private-terms.excluded.txt").read_text(encoding="utf-8")
        self.assertIn("kim", review.lower())
        self.assertNotIn("Kim", result.stdout + result.stderr)
        self.assertNotIn("kim", self.read_terms())

    def test_a_utf16_generated_list_is_refused_and_left_untouched(self):
        self.target.mkdir()
        raw = "Handmade\n".encode("utf-16")
        (self.target / "private-terms.txt").write_bytes(raw)
        result = self.install("-TermsFrom", str(self.make_students("ZorblatQuenby")))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("UTF-16", result.stdout)
        self.assertEqual((self.target / "private-terms.txt").read_bytes(), raw)

    def test_a_relative_target_is_judged_where_it_is_written_not_where_the_process_started(self):
        # Round 3: Test-SyncedFolder resolved a relative -Target against the process directory
        # while the writes followed PowerShell's location, so a cd into a synced folder escaped it.
        root = self.make_students("ZorblatQuenby")
        synced = Path(self.tmp) / "OneDrive"
        synced.mkdir()
        script = str(HOOKS / "install-git-hooks.ps1")
        cmd = "Set-Location -LiteralPath '%s'; & '%s' -Target .\\hooks -TermsFrom '%s'; exit $LASTEXITCODE" % (synced, script, root)
        result = run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd], self.tmp, self.env)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertFalse((synced / "hooks").exists())

    def test_a_folder_name_starting_with_a_hash_does_not_break_the_run(self):
        root = self.make_students("#ZorblatQuenby")
        result = self.install("-TermsFrom", str(root))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("zorblat", self.read_terms())

    def test_an_empty_fragment_is_not_reported_as_set_aside(self):
        root = self.make_students("Zorblat_")
        result = self.install("-TermsFrom", str(root))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("fragments set aside", result.stdout)

    def test_the_words_dropped_as_ordinary_are_kept_in_a_review_file_not_shown(self):
        # A real surname can equal a common word; the operator must be able to see which
        # fragments fell out, without the installer printing them.
        root = self.make_students("ZorblatGrant")
        result = self.install("-TermsFrom", str(root))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        review = (self.target / "private-terms.excluded.txt").read_text(encoding="utf-8")
        self.assertIn("grant", review.lower())
        self.assertNotIn("Grant", result.stdout + result.stderr)
        self.assertIn("private-terms.excluded.txt", result.stdout)
        ignored = (self.xdg / "git" / "ignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("private-terms.excluded.txt", ignored)

    def test_terms_from_adds_an_ascii_folded_spelling_of_an_accented_name(self):
        root = self.make_students("Jérémie")
        self.assertEqual(self.install("-TermsFrom", str(root)).returncode, 0)
        terms = self.read_terms()
        self.assertIn("jeremie", terms)
        self.assertIn("jérémie", terms)

    # 2026-10-15: the deny list holds real names, so it is never written where a sync client or a
    # network share would copy it off the machine, and it is ignored by git everywhere.

    def synced_target(self, *parts):
        self.target = Path(self.tmp).joinpath(*parts) / "hooks"

    def test_terms_from_is_refused_in_a_folder_named_after_a_sync_client(self):
        root = self.make_students("ZorblatQuenby")
        for parts in (("OneDrive",), ("OneDrive - Example Org",), ("Dropbox", "x"),
                      ("Google Drive",), ("iCloudDrive",), ("Nextcloud",)):
            self.synced_target(*parts)
            result = self.install("-TermsFrom", str(root))
            self.assertEqual(result.returncode, 2, "%s: %s" % (parts, result.stdout + result.stderr))
            self.assertIn("synchroniz", result.stdout.lower())
            self.assertFalse(self.target.exists(), "something was written under %s" % (parts,))
            self.assertNotIn("Quenby", result.stdout + result.stderr)

    def test_the_refusal_names_the_category_and_never_the_path(self):
        root = self.make_students("ZorblatQuenby")
        self.synced_target("OneDrive")
        result = self.install("-TermsFrom", str(root))
        self.assertIn("-Uninstall", result.stdout)
        self.assertNotIn(self.tmp, result.stdout + result.stderr)

    def test_a_dry_run_is_refused_in_a_synced_folder_too(self):
        root = self.make_students("ZorblatQuenby")
        self.synced_target("OneDrive")
        self.assertEqual(self.install("-TermsFrom", str(root), "-DryRun").returncode, 2)

    def test_the_onedrive_environment_root_counts_whatever_its_name(self):
        root = self.make_students("ZorblatQuenby")
        sync_root = Path(self.tmp) / "plainname"
        sync_root.mkdir()
        # os.environ upper-cases names on Windows: drop every spelling first, or a real
        # ONEDRIVE and this OneDrive would both reach the child and the winner is arbitrary.
        for key in [k for k in self.env if k.lower() == "onedrive"]:
            del self.env[key]
        self.env["OneDrive"] = str(sync_root)
        self.target = sync_root / "deeper" / "hooks"
        self.assertEqual(self.install("-TermsFrom", str(root)).returncode, 2)

    def test_a_network_share_is_refused_without_touching_it(self):
        root = self.make_students("ZorblatQuenby")
        self.target = Path("\\\\zz-no-such-host\\share\\hooks")
        result = self.install("-TermsFrom", str(root))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("network", result.stdout)

    @unittest.skipUnless(os.name == "nt", "junctions are a Windows feature")
    def test_a_junction_into_a_synced_folder_is_refused(self):
        root = self.make_students("ZorblatQuenby")
        real = Path(self.tmp) / "OneDrive" / "inner"
        real.mkdir(parents=True)
        link = Path(self.tmp) / "innocent-link"
        made = run(["cmd", "/c", "mklink", "/J", str(link), str(real)], self.tmp, self.env)
        self.assertEqual(made.returncode, 0, made.stdout + made.stderr)
        self.target = link / "hooks"
        result = self.install("-TermsFrom", str(root))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertFalse((real / "hooks").exists())

    def test_a_plain_install_in_a_synced_folder_still_works_and_warns_about_a_list_there(self):
        self.synced_target("OneDrive")
        self.assertEqual(self.install().returncode, 0)
        (self.target / "private-terms.extra.txt").write_text("Handmade\n", encoding="utf-8")
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("WARNING a deny list already sits in a synchronized", result.stdout)

    def test_a_local_folder_is_not_mistaken_for_a_synced_one(self):
        # The negative control: without it every refusal above would pass on a detector that
        # refuses everything.
        root = self.make_students("ZorblatQuenby")
        self.assertEqual(self.install("-TermsFrom", str(root)).returncode, 0)

    def test_terms_from_adds_the_list_to_the_global_git_ignore_once(self):
        root = self.make_students("ZorblatQuenby")
        self.assertEqual(self.install("-TermsFrom", str(root)).returncode, 0)
        self.assertEqual(self.install("-TermsFrom", str(root)).returncode, 0)
        lines = (self.xdg / "git" / "ignore").read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines.count("private-terms.txt"), 1)
        self.assertEqual(lines.count("private-terms.extra.txt"), 1)

    def test_a_copy_of_the_list_dropped_in_a_repository_is_ignored_by_git(self):
        root = self.make_students("ZorblatQuenby")
        self.assertEqual(self.install("-TermsFrom", str(root)).returncode, 0)
        repo = Path(self.tmp) / "repo"
        repo.mkdir()
        run(["git", "init", "-q", "."], repo, self.env)
        shutil.copy(self.target / "private-terms.txt", repo / "private-terms.txt")
        checked = run(["git", "check-ignore", "-q", "private-terms.txt"], repo, self.env)
        self.assertEqual(checked.returncode, 0, "git does not ignore a copy of the list")

    def test_the_ignore_honours_a_configured_excludes_file(self):
        configured = Path(self.tmp) / "my-ignore"
        run(["git", "config", "--global", "core.excludesFile", str(configured)], self.tmp, self.env)
        root = self.make_students("ZorblatQuenby")
        self.assertEqual(self.install("-TermsFrom", str(root)).returncode, 0)
        self.assertIn("private-terms.txt", configured.read_text(encoding="utf-8"))
        self.assertFalse((self.xdg / "git" / "ignore").exists())

    def test_install_without_a_deny_list_says_so(self):
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("no deny list yet", result.stdout)

    def test_another_hooks_path_is_refused_not_overwritten(self):
        run(["git", "config", "--global", "core.hooksPath", "C:/other/hooks"], self.tmp, self.env)
        result = self.install()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(self.global_hooks_path(), "C:/other/hooks")
        self.assertFalse(self.target.exists())


if __name__ == "__main__":
    unittest.main()
