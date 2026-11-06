"""
browser_login.py - secret providers and sign-in vocabulary for the browser rung.

Stage: rung 8 of download_pdf.py (see browser_fetch.py). The browser rung may have
to sign in to the owner's institution before a paywalled article opens. This
module fetches the secret for that sign-in from the provider the configuration
names: the operating system store (keyring), the Bitwarden command line tool, or
KeePassXC. It also owns the closed vocabularies browser-fetch.json is checked
against (R5): the provider names and the sign-in step actions.

Rules this module keeps:
  - A secret is returned to the caller and goes nowhere else. It is never logged,
    never put on a command line, never placed in an exception text, and the
    exception raised for a failure never chains the failed command's output.
  - A provider that cannot do its job is a named refusal (LoginError). There is no
    silent switch to another provider (R8): a locked Bitwarden vault does not turn
    into a keyring lookup.
  - Every subprocess has a timeout (R10) and is told not to ask a question
    (--nointeraction, stdin closed or fed), so a locked vault cannot hang a run.
  - A one-time code is read from a vault only when the caller passes allow=True,
    and each use logs a warning that both factors then sit in one vault.

Verification status (R15): the keyring and Bitwarden command lines follow the
documented CLI and are tested against a fake runner. The KeePassXC command line is
tested against a fake runner only, keepassxc-cli not being installed here.
"""

import json
import logging
import os
import shutil
import subprocess
from typing import Any, Callable, Mapping

logger = logging.getLogger(__name__)

SECRET_PROVIDERS = ("keyring", "bitwarden", "keepassxc")
STEP_ACTIONS = ("fill_username", "fill_password", "fill_totp", "click")

BW_SESSION_ENV = "BW_SESSION"
KEEPASSXC_DATABASE_ENV = "KEEPASSXC_DATABASE"
KEEPASSXC_PASSWORD_ENV = "KEEPASSXC_PASSWORD"
KEEPASSXC_KEYFILE_ENV = "KEEPASSXC_KEYFILE"


class LoginError(RuntimeError):
    """A secret provider or a sign-in step could not do its job; the text names why."""


def _check_timeout(timeout_s: Any) -> None:
    """Refuse a timeout that is not a positive number (R10: never an unbounded wait)."""
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) or timeout_s <= 0:
        raise LoginError("the provider timeout must be a positive number of seconds")


def _call(run: Callable[..., Any], cmd: list[str], timeout_s: float, tool: str,
          **extra: Any) -> Any:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run one provider command with a timeout and no terminal interaction, and
        turn every way it can fail to launch into a LoginError that carries no
        output of the command (the output may hold the secret).

    Inputs:
        run: subprocess.run or a stand-in.
        cmd (list): the command line; it never holds a secret.
        timeout_s (float): seconds before the call is abandoned.
        tool (str): a short name for messages.
        extra: further keyword arguments for run (env, input, stdin).

    Outputs:
        completed: the CompletedProcess-like result.

    Raises:
        LoginError: the call timed out or the tool could not be started.
    --------------------------------------------------------------------------
    """
    try:
        return run(cmd, capture_output=True, text=True, timeout=timeout_s, **extra)
    except subprocess.TimeoutExpired:
        raise LoginError("%s timed out after %s s" % (tool, timeout_s)) from None
    except OSError as exc:
        raise LoginError("cannot run %s (%s)" % (tool, type(exc).__name__)) from None


def _keyring_password(item: str, username: str | None, keyring_module: Any) -> str:
    """Read (service=item, username) from the operating system store."""
    if not username or not str(username).strip():
        raise LoginError("keyring needs a user name for the sign-in (the host's "
                         "username_env variable is empty or unset)")
    module = keyring_module
    if module is None:
        try:
            import keyring as module  # type: ignore[no-redef]
        except ImportError:
            raise LoginError("the keyring package is not installed: pip install keyring") from None
    try:
        secret = module.get_password(item, username)
    except Exception as exc:  # keyring backends raise many types; none may leak text
        raise LoginError("the keyring backend failed (%s)" % type(exc).__name__) from None
    if not secret:
        raise LoginError("no password stored in the keyring for service %r" % item)
    return secret


def _bitwarden(item: str, what: str, timeout_s: float, run: Callable[..., Any],
               which: Callable[[str], str | None], env: Mapping[str, str]) -> str:
    """Read the password or the one-time code of a Bitwarden item with `bw`."""
    exe = which("bw")
    if not exe:
        raise LoginError("the Bitwarden CLI (bw) was not found on PATH: "
                         "winget install Bitwarden.CLI")
    if not str(env.get(BW_SESSION_ENV, "")).strip():
        raise LoginError("%s is not set: run `bw unlock` and export the session key it prints"
                         % BW_SESSION_ENV)
    child_env = dict(env)
    common = {"env": child_env, "stdin": subprocess.DEVNULL}

    done = _call(run, [exe, "status", "--nointeraction"], timeout_s, "bw status", **common)
    try:
        status = json.loads(done.stdout).get("status")
    except (ValueError, AttributeError):
        status = None
    if done.returncode != 0 or status is None:
        raise LoginError("bw status gave no usable answer")
    if status == "unauthenticated":
        raise LoginError("Bitwarden is not logged in: run `bw login`")
    if status != "unlocked":
        raise LoginError("the Bitwarden vault is locked: run `bw unlock` and export %s"
                         % BW_SESSION_ENV)

    done = _call(run, [exe, "get", what, item, "--nointeraction"], timeout_s,
                 "bw get %s" % what, **common)
    value = (done.stdout or "").rstrip("\r\n")
    if done.returncode != 0:
        raise LoginError("Bitwarden item %r was not found or cannot be read" % item)
    if not value:
        raise LoginError("Bitwarden item %r has no %s" % (item, what))
    return value


def _keepassxc(item: str, what: str, timeout_s: float, run: Callable[..., Any],
               which: Callable[[str], str | None], env: Mapping[str, str]) -> str:
    """Read the password or the one-time code of a KeePassXC entry with keepassxc-cli."""
    exe = which("keepassxc-cli")
    if not exe:
        raise LoginError("keepassxc-cli was not found on PATH")
    database = str(env.get(KEEPASSXC_DATABASE_ENV, "")).strip()
    if not database:
        raise LoginError("%s is not set: it names the .kdbx database" % KEEPASSXC_DATABASE_ENV)
    cmd = [exe, "show", "-q"]
    cmd += ["-a", "Password"] if what == "password" else ["-t"]
    keyfile = str(env.get(KEEPASSXC_KEYFILE_ENV, "")).strip()
    if keyfile:
        cmd += ["--key-file", keyfile]
    cmd += [database, item]
    master = str(env.get(KEEPASSXC_PASSWORD_ENV, ""))
    if master:
        extra: dict[str, Any] = {"input": master + "\n"}
    else:
        extra = {"stdin": subprocess.DEVNULL}
    done = _call(run, cmd, timeout_s, "keepassxc-cli", **extra)
    value = (done.stdout or "").rstrip("\r\n")
    if done.returncode != 0 or not value:
        raise LoginError("keepassxc-cli could not read entry %r: the database may be locked "
                         "(set %s or %s) or the entry does not exist"
                         % (item, KEEPASSXC_PASSWORD_ENV, KEEPASSXC_KEYFILE_ENV))
    return value


def _fetch(item: str, what: str, provider: str, timeout_s: Any, username: str | None,
           env: Mapping[str, str] | None, run: Callable[..., Any],
           which: Callable[[str], str | None], keyring_module: Any) -> str:
    """Dispatch to one provider; there is no fallback to another."""
    _check_timeout(timeout_s)
    environment = os.environ if env is None else env
    if provider == "keyring":
        if what != "password":
            raise LoginError("the keyring stores no one-time codes")
        return _keyring_password(item, username, keyring_module)
    if provider == "bitwarden":
        return _bitwarden(item, what, timeout_s, run, which, environment)
    if provider == "keepassxc":
        return _keepassxc(item, what, timeout_s, run, which, environment)
    raise LoginError("unknown secret provider %r: choose one of %s"
                     % (provider, ", ".join(SECRET_PROVIDERS)))


def get_password(item: str, provider: str, *, timeout_s: Any, username: str | None = None,
                 env: Mapping[str, str] | None = None,
                 run: Callable[..., Any] = subprocess.run,
                 which: Callable[[str], str | None] = shutil.which,
                 keyring_module: Any = None) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Return the password stored under `item` in the named secret provider.

    Inputs:
        item (str): keyring service, Bitwarden item name, or KeePassXC entry path.
        provider (str): one of SECRET_PROVIDERS.
        timeout_s (float): seconds allowed to each provider command (R10).
        username (str | None): the account name, needed by the keyring only.
        env (Mapping | None): environment to read BW_SESSION and the KEEPASSXC_*
            variables from; default os.environ.
        run, which, keyring_module: injection points for tests.

    Outputs:
        password (str): the secret. It is not logged anywhere by this module.

    Raises:
        LoginError: unknown provider, tool or package absent, vault locked or
            not logged in, item missing, empty secret, timeout. The text never
            holds a secret or the failed command's output.
    --------------------------------------------------------------------------
    """
    return _fetch(item, "password", provider, timeout_s, username, env, run, which,
                  keyring_module)


def get_totp(item: str, provider: str, *, allow: bool, timeout_s: Any,
             username: str | None = None, env: Mapping[str, str] | None = None,
             run: Callable[..., Any] = subprocess.run,
             which: Callable[[str], str | None] = shutil.which,
             keyring_module: Any = None) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Return the current one-time code of `item` from a vault, only when the
        configuration allows it. The default is that a person approves MFA.

    Inputs:
        item, provider, timeout_s, username, env, run, which, keyring_module: as
            get_password.
        allow (bool): the config's allow_totp_from_vault.

    Outputs:
        code (str): the one-time code. A warning is logged on every use saying
        both factors now sit in one vault; the code itself is never logged.

    Raises:
        LoginError: allow is False, the provider keeps no codes, or any of the
            get_password failures.
    --------------------------------------------------------------------------
    """
    if not allow:
        raise LoginError("reading a one-time code from a vault is disabled: set "
                         "allow_totp_from_vault to true in browser-fetch.json to permit it")
    code = _fetch(item, "totp", provider, timeout_s, username, env, run, which, keyring_module)
    logger.warning("[LOGIN] a one-time code was read from the %s vault: password and second "
                   "factor now sit in one vault, which weakens the second factor", provider)
    return code
