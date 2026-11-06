"""
test_browser_login.py - offline tests for the secret providers of the browser rung.

No vault, no keyring backend and no network: the command runner, the executable
lookup, the environment and the keyring module are all injected. The fixture
secrets are obviously fake. The point of the suite is the refusals (each named)
and the guarantee that a secret never reaches a log line, an exception text or
a repr.

Run:
    cd .claude/skills/scopus/scripts
    python -m unittest Test.test_browser_login
"""

import logging
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

import browser_login  # noqa: E402

SECRET = "S3cr3t-Pw-FIXTURE!"
TOTP = "424242"
ITEM = "example-institution"


class FakeRun:
    """Stand-in for subprocess.run keyed by the first sub-command word."""

    def __init__(self, answers):
        self.answers = answers          # {"status": (rc, out, err), ...} or an Exception
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append((list(cmd), kwargs))
        key = next((k for k in self.answers if k in cmd), None)
        answer = self.answers[key] if key else (1, "", "")
        if isinstance(answer, BaseException):
            raise answer
        rc, out, err = answer
        return subprocess.CompletedProcess(cmd, rc, stdout=out, stderr=err)


BW_UNLOCKED = '{"status":"unlocked"}'


def _bw(answers=None, env=None, found=True):
    """Common arguments for the bitwarden backend with everything injected."""
    base = {"status": (0, BW_UNLOCKED, ""), "password": (0, SECRET + "\n", ""),
            "totp": (0, TOTP + "\n", "")}
    base.update(answers or {})
    run = FakeRun(base)
    return run, dict(provider="bitwarden", timeout_s=7, run=run,
                     which=lambda name: ("C:/tools/bw.exe" if found else None),
                     env=env if env is not None else {"BW_SESSION": "SESSION-FIXTURE"})


class LogCatcher:
    """Collect every log record of every logger while a block runs."""

    def __enter__(self):
        self.records = []
        outer = self

        class _H(logging.Handler):
            def emit(self, record):
                outer.records.append(record.getMessage())
        self._h = _H(level=logging.DEBUG)
        root = logging.getLogger()
        self._old = root.level
        root.setLevel(logging.DEBUG)
        root.addHandler(self._h)
        return self

    def __exit__(self, *exc):
        root = logging.getLogger()
        root.removeHandler(self._h)
        root.setLevel(self._old)
        return False


class TestKeyring(unittest.TestCase):

    def test_reads_the_password_for_service_and_user(self):
        fake = mock.Mock()
        fake.get_password.return_value = SECRET
        got = browser_login.get_password(ITEM, provider="keyring", timeout_s=5,
                                         username="someone", keyring_module=fake)
        self.assertEqual(got, SECRET)
        fake.get_password.assert_called_once_with(ITEM, "someone")

    def test_a_missing_entry_is_a_named_refusal(self):
        fake = mock.Mock()
        fake.get_password.return_value = None
        with self.assertRaises(browser_login.LoginError) as ctx:
            browser_login.get_password(ITEM, provider="keyring", timeout_s=5,
                                       username="someone", keyring_module=fake)
        self.assertIn(ITEM, str(ctx.exception))

    def test_no_user_name_is_a_refusal_before_any_lookup(self):
        fake = mock.Mock()
        with self.assertRaises(browser_login.LoginError) as ctx:
            browser_login.get_password(ITEM, provider="keyring", timeout_s=5,
                                       username=None, keyring_module=fake)
        self.assertIn("user name", str(ctx.exception))
        fake.get_password.assert_not_called()

    def test_the_package_absent_names_the_remedy(self):
        with mock.patch.dict(sys.modules, {"keyring": None}):
            with self.assertRaises(browser_login.LoginError) as ctx:
                browser_login.get_password(ITEM, provider="keyring", timeout_s=5,
                                           username="someone")
        self.assertIn("pip install keyring", str(ctx.exception))

    def test_a_backend_failure_names_its_type_but_not_its_text(self):
        fake = mock.Mock()
        fake.get_password.side_effect = RuntimeError("leaks " + SECRET)
        with self.assertRaises(browser_login.LoginError) as ctx:
            browser_login.get_password(ITEM, provider="keyring", timeout_s=5,
                                       username="someone", keyring_module=fake)
        self.assertIn("RuntimeError", str(ctx.exception))
        self.assertNotIn(SECRET, str(ctx.exception))


class TestBitwarden(unittest.TestCase):

    def test_reads_the_password_after_checking_the_vault_is_unlocked(self):
        run, kwargs = _bw()
        got = browser_login.get_password(ITEM, **kwargs)
        self.assertEqual(got, SECRET)                       # trailing newline stripped
        self.assertEqual([c[0][1] for c in run.calls], ["status", "get"])
        self.assertEqual(run.calls[1][0][2:4], ["password", ITEM])

    def test_every_subprocess_has_a_timeout_and_never_asks_a_question(self):
        run, kwargs = _bw()
        browser_login.get_password(ITEM, **kwargs)
        for cmd, kw in run.calls:
            self.assertEqual(kw["timeout"], 7)
            self.assertIn("--nointeraction", cmd)
            self.assertIs(kw["stdin"], subprocess.DEVNULL)
            self.assertEqual(kw["env"]["BW_SESSION"], "SESSION-FIXTURE")

    def test_no_secret_is_ever_on_a_command_line(self):
        run, kwargs = _bw()
        browser_login.get_password(ITEM, **kwargs)
        for cmd, _ in run.calls:
            self.assertNotIn(SECRET, " ".join(cmd))
            self.assertNotIn("SESSION-FIXTURE", " ".join(cmd))

    def test_the_executable_missing_names_the_remedy(self):
        _, kwargs = _bw(found=False)
        with self.assertRaises(browser_login.LoginError) as ctx:
            browser_login.get_password(ITEM, **kwargs)
        self.assertIn("winget install Bitwarden.CLI", str(ctx.exception))

    def test_no_session_in_the_environment_is_a_refusal_naming_the_variable(self):
        run, kwargs = _bw(env={})
        with self.assertRaises(browser_login.LoginError) as ctx:
            browser_login.get_password(ITEM, **kwargs)
        self.assertIn("BW_SESSION", str(ctx.exception))
        self.assertEqual(run.calls, [])

    def test_a_locked_vault_is_a_refusal_and_reads_nothing(self):
        run, kwargs = _bw({"status": (0, '{"status":"locked"}', "")})
        with self.assertRaises(browser_login.LoginError) as ctx:
            browser_login.get_password(ITEM, **kwargs)
        self.assertIn("locked", str(ctx.exception))
        self.assertIn("bw unlock", str(ctx.exception))
        self.assertEqual(len(run.calls), 1)                 # never reached `get`

    def test_not_logged_in_names_bw_login(self):
        _, kwargs = _bw({"status": (0, '{"status":"unauthenticated"}', "")})
        with self.assertRaises(browser_login.LoginError) as ctx:
            browser_login.get_password(ITEM, **kwargs)
        self.assertIn("bw login", str(ctx.exception))

    def test_an_unreadable_status_is_a_refusal_not_a_guess(self):
        for answer in ((0, "not json", ""), (1, "", "boom"), (0, '{"x":1}', "")):
            _, kwargs = _bw({"status": answer})
            with self.subTest(answer=answer), self.assertRaises(browser_login.LoginError):
                browser_login.get_password(ITEM, **kwargs)

    def test_a_missing_item_is_a_named_refusal(self):
        _, kwargs = _bw({"password": (1, "", "Not found.")})
        with self.assertRaises(browser_login.LoginError) as ctx:
            browser_login.get_password(ITEM, **kwargs)
        self.assertIn(ITEM, str(ctx.exception))

    def test_an_empty_password_is_a_refusal(self):
        _, kwargs = _bw({"password": (0, "\n", "")})
        with self.assertRaises(browser_login.LoginError):
            browser_login.get_password(ITEM, **kwargs)

    def test_a_timeout_is_a_named_refusal(self):
        _, kwargs = _bw({"status": subprocess.TimeoutExpired(cmd="bw", timeout=7)})
        with self.assertRaises(browser_login.LoginError) as ctx:
            browser_login.get_password(ITEM, **kwargs)
        self.assertIn("timed out", str(ctx.exception))
        self.assertIn("7", str(ctx.exception))

    def test_an_os_error_launching_the_tool_is_a_refusal(self):
        _, kwargs = _bw({"status": OSError("no such file")})
        with self.assertRaises(browser_login.LoginError):
            browser_login.get_password(ITEM, **kwargs)

    def test_every_provider_call_reads_and_writes_utf8(self):
        # Review round 1: without an explicit encoding the pipe uses the Windows
        # codepage, so a password with an accent is decoded to the wrong text.
        run, kwargs = _bw()
        browser_login.get_password(ITEM, **kwargs)
        self.assertTrue(run.calls)
        for _cmd, call_kwargs in run.calls:
            self.assertEqual(call_kwargs.get("encoding"), "utf-8")

    def test_output_that_is_not_utf8_is_a_refusal_not_a_crash(self):
        # Review round 1: UnicodeDecodeError escaped the rung and aborted a whole run.
        bad = UnicodeDecodeError("utf-8", b"\x81", 0, 1, "invalid start byte")
        _, kwargs = _bw({"status": bad})
        with self.assertRaises(browser_login.LoginError) as ctx:
            browser_login.get_password(ITEM, **kwargs)
        self.assertIn("UTF-8", str(ctx.exception))
        self.assertNotIn("\\x81", str(ctx.exception))


class TestKeepassxc(unittest.TestCase):
    """Unverified against a real keepassxc-cli (not installed here, R15): the
    command line is asserted against a fake runner only."""

    def _kw(self, answers=None, env=None, found=True):
        run = FakeRun(answers or {"show": (0, SECRET + "\n", "")})
        env = {"KEEPASSXC_DATABASE": "C:/vault/db.kdbx", "KEEPASSXC_PASSWORD": "master-fixture"} \
            if env is None else env
        return run, dict(provider="keepassxc", timeout_s=9, run=run,
                         which=lambda name: ("C:/tools/keepassxc-cli.exe" if found else None),
                         env=env)

    def test_reads_the_password_attribute_of_the_entry(self):
        run, kwargs = self._kw()
        self.assertEqual(browser_login.get_password(ITEM, **kwargs), SECRET)
        cmd, kw = run.calls[0]
        self.assertEqual(cmd[1:4], ["show", "-q", "-a"])
        self.assertIn("Password", cmd)
        self.assertEqual(cmd[-2:], ["C:/vault/db.kdbx", ITEM])
        self.assertEqual(kw["timeout"], 9)

    def test_the_master_password_goes_through_stdin_never_the_command_line(self):
        run, kwargs = self._kw()
        browser_login.get_password(ITEM, **kwargs)
        cmd, kw = run.calls[0]
        self.assertNotIn("master-fixture", " ".join(cmd))
        self.assertEqual(kw["input"], "master-fixture\n")

    def test_without_a_master_password_stdin_is_closed(self):
        run, kwargs = self._kw(env={"KEEPASSXC_DATABASE": "C:/vault/db.kdbx"})
        browser_login.get_password(ITEM, **kwargs)
        self.assertIs(run.calls[0][1]["stdin"], subprocess.DEVNULL)
        self.assertNotIn("input", run.calls[0][1])

    def test_a_key_file_is_passed_by_path(self):
        run, kwargs = self._kw(env={"KEEPASSXC_DATABASE": "C:/vault/db.kdbx",
                                    "KEEPASSXC_KEYFILE": "C:/vault/key.keyx"})
        browser_login.get_password(ITEM, **kwargs)
        cmd = run.calls[0][0]
        self.assertEqual(cmd[cmd.index("--key-file") + 1], "C:/vault/key.keyx")

    def test_refusals_are_named(self):
        _, kwargs = self._kw(found=False)
        with self.assertRaises(browser_login.LoginError) as ctx:
            browser_login.get_password(ITEM, **kwargs)
        self.assertIn("keepassxc-cli", str(ctx.exception))
        _, kwargs = self._kw(env={})
        with self.assertRaises(browser_login.LoginError) as ctx:
            browser_login.get_password(ITEM, **kwargs)
        self.assertIn("KEEPASSXC_DATABASE", str(ctx.exception))
        _, kwargs = self._kw({"show": (1, "", "Error while reading the database")})
        with self.assertRaises(browser_login.LoginError) as ctx:
            browser_login.get_password(ITEM, **kwargs)
        self.assertIn("KEEPASSXC_PASSWORD", str(ctx.exception))
        _, kwargs = self._kw({"show": subprocess.TimeoutExpired(cmd="x", timeout=9)})
        with self.assertRaises(browser_login.LoginError) as ctx:
            browser_login.get_password(ITEM, **kwargs)
        self.assertIn("timed out", str(ctx.exception))


class TestProviderChoice(unittest.TestCase):

    def test_an_unknown_provider_is_refused_never_replaced(self):
        with self.assertRaises(browser_login.LoginError) as ctx:
            browser_login.get_password(ITEM, provider="lastpass", timeout_s=5)
        self.assertIn("lastpass", str(ctx.exception))
        for known in browser_login.SECRET_PROVIDERS:
            self.assertIn(known, str(ctx.exception))

    def test_a_failing_provider_never_falls_back_to_another(self):
        # R8: a locked Bitwarden vault must not quietly turn into a keyring lookup.
        keyring = mock.Mock()
        _, kwargs = _bw({"status": (0, '{"status":"locked"}', "")})
        with mock.patch.dict(sys.modules, {"keyring": keyring}):
            with self.assertRaises(browser_login.LoginError):
                browser_login.get_password(ITEM, **kwargs)
        keyring.get_password.assert_not_called()

    def test_a_non_positive_timeout_is_refused(self):
        for bad in (0, -1, None, True):
            with self.subTest(bad=bad), self.assertRaises(browser_login.LoginError):
                browser_login.get_password(ITEM, provider="bitwarden", timeout_s=bad)


class TestOneTimeCodes(unittest.TestCase):

    def test_refused_unless_the_flag_allows_it(self):
        run, kwargs = _bw()
        with self.assertRaises(browser_login.LoginError) as ctx:
            browser_login.get_totp(ITEM, allow=False, **kwargs)
        self.assertIn("allow_totp_from_vault", str(ctx.exception))
        self.assertEqual(run.calls, [])

    def test_allowed_reads_the_code_and_warns_that_both_factors_share_a_vault(self):
        run, kwargs = _bw()
        with LogCatcher() as logs:
            got = browser_login.get_totp(ITEM, allow=True, **kwargs)
        self.assertEqual(got, TOTP)
        self.assertEqual(run.calls[1][0][2], "totp")
        self.assertTrue(any("one vault" in m for m in logs.records))
        self.assertFalse(any(TOTP in m for m in logs.records))

    def test_keyring_stores_no_one_time_codes(self):
        with self.assertRaises(browser_login.LoginError):
            browser_login.get_totp(ITEM, allow=True, provider="keyring", timeout_s=5,
                                   username="someone", keyring_module=mock.Mock())


class TestNoSecretLeaks(unittest.TestCase):
    """The secret never reaches a log line, an exception text or a repr."""

    def _assert_clean(self, logs, error=None):
        for message in logs.records:
            self.assertNotIn(SECRET, message)
            self.assertNotIn("SESSION-FIXTURE", message)
        if error is not None:
            for text in (str(error), repr(error), repr(error.args)):
                self.assertNotIn(SECRET, text)
                self.assertNotIn("SESSION-FIXTURE", text)

    def test_success_path_logs_no_secret(self):
        _, kwargs = _bw()
        with LogCatcher() as logs:
            browser_login.get_password(ITEM, **kwargs)
        self._assert_clean(logs)

    def test_every_failure_path_leaks_nothing_even_when_the_tool_prints_the_secret(self):
        failing = [
            {"password": (1, SECRET, SECRET)},                       # stderr and stdout echo it
            {"status": (0, '{"status":"locked"}' + SECRET, SECRET)},
            {"status": (1, SECRET, SECRET)},
            {"status": subprocess.TimeoutExpired(cmd=["bw", SECRET], timeout=7,
                                                 output=SECRET.encode(), stderr=SECRET.encode())},
        ]
        for answers in failing:
            _, kwargs = _bw(answers)
            with self.subTest(answers=list(answers)), LogCatcher() as logs:
                with self.assertRaises(browser_login.LoginError) as ctx:
                    browser_login.get_password(ITEM, **kwargs)
                self._assert_clean(logs, ctx.exception)

    def test_the_login_error_has_no_chained_context_carrying_output(self):
        _, kwargs = _bw({"status": subprocess.TimeoutExpired(cmd="bw", timeout=7,
                                                             output=SECRET.encode())})
        with self.assertRaises(browser_login.LoginError) as ctx:
            browser_login.get_password(ITEM, **kwargs)
        self.assertIsNone(ctx.exception.__cause__)
        self.assertTrue(ctx.exception.__suppress_context__)


if __name__ == "__main__":
    unittest.main()
