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
EXTRA_FILES = ("privacy-lib.sh", "privacy-extra.awk", "fixture-path-allow.txt")
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

    def test_the_deny_list_still_works_when_betterleaks_is_not_found(self):
        # The deny-list scan needs no betterleaks. Run with a PATH that cannot find it.
        (self.hooks / "private-terms.txt").write_text("Quenby\n", encoding="utf-8")
        (self.hooks / "privacy-rules.toml").unlink()
        self.commit("by Quenby\n")
        self.assertNotEqual(self.push().returncode, 0)

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
        self.env = isolated_env(self.tmp)
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
        root = self.make_students("Ab")
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
