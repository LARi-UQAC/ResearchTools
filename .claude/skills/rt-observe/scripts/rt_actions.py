"""
rt_actions - the dashboard's write half: a closed whitelist, run and judged.

The dangerous half of this tool, so the design removes the danger rather than
guarding it.

  * An action id maps to a FIXED argv list held in `actions.json`. The HTTP body
    carries an id, a token, a confirm flag - and for the inbox, a target and a
    message. **Nothing from the request ever enters argv**, so there is no
    injection surface to review. A token in {braces} inside an argv entry is
    resolved from a CLOSED server-side table (R5), and a token that table does
    not name is a refusal rather than a substitution.
  * Every id points at a script that already exists in this repository and is
    already tested. This module adds no capability; it makes an existing one
    reachable.
  * `--dry-run` prints the resolved argv and executes nothing (R16). A
    destructive id additionally requires an explicit confirm.
  * Every run appends one JSON record to the action log (R17), the same
    append-only shape as `vault_journal.py`.
  * **Judged by effect, not by exit code (R9).** `restart-ollama.ps1` is the
    documented case of a script exiting 0 while an orphaned child keeps its
    VRAM, so an action that declares a verifier is reported FAILED when the
    effect did not happen, whatever the exit code said. A null verifier is
    reported as "claims no verifiable effect", never as success.

Availability, not optimism: an action whose interpreter is absent from PATH is
reported unavailable WITH its reason and is never offered as a button that fails
on click. That is the same rule the MCP roster follows one layer down.

Every timeout, cap and path comes from `observe-config.json` (R0); the catalogue
itself is data in `actions.json` (R6).
"""
import argparse
import io
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rt_redact import home_tilde  # noqa: E402

SKILL_ROOT = Path(__file__).resolve().parent.parent

# A target names a directory under the inbox root and nothing else. Anchored,
# with no separator and no dot-dot in the class, so containment is decided
# before a path is built rather than after (R24).
TARGET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
TOKEN_RE = re.compile(r"\{([a-z_]+)\}")

# name -> (snapshot section it reads, predicate(section) -> (ok, detail))
VERIFIERS = {
    "mirrors_no_lost": ("mirrors", lambda s: (
        s.get("totals", {}).get("lost", 0) == 0
        and s.get("totals", {}).get("stale", 0) == 0,
        "lost=%s stale=%s" % (s.get("totals", {}).get("lost"),
                              s.get("totals", {}).get("stale")))),
    "daemon_running": ("services", lambda s: (
        bool(s.get("vault_daemon", {}).get("running")),
        "vault_daemon.running=%s" % s.get("vault_daemon", {}).get("running"))),
    "ollama_resident": ("services", lambda s: (
        (s.get("local_models", {}).get("resident_count") or 0) > 0,
        "resident_count=%s" % s.get("local_models", {}).get("resident_count"))),
    "green_stamp": ("repo_state", lambda s: (
        s.get("green", {}).get("value") == "green",
        "green=%s" % s.get("green", {}).get("value"))),
}


class ActionsError(RuntimeError):
    """The catalogue itself is missing or malformed. Named, never defaulted."""


def load_actions(skill_root=None):
    path = Path(skill_root or SKILL_ROOT) / "actions.json"
    if not path.exists():
        raise ActionsError(
            "actions.json not found at %s. It is the closed whitelist of "
            "everything the dashboard may run; with no whitelist there is no "
            "safe default, so no action is offered." % path)
    try:
        data = json.loads(io.open(path, encoding="utf-8-sig").read())
    except ValueError as exc:
        raise ActionsError("actions.json does not parse: %s" % exc)
    if not isinstance(data.get("actions"), list):
        raise ActionsError("actions.json declares no 'actions' list")
    return data


def _tail(text, limit):
    """Keep the END of captured output. A Python traceback names its exception
    on its LAST line while its opening frames are identical on every failure,
    which is why two full drill runs were once spent reaching a one-line
    NameError that head-truncation had thrown away (obsidian-cli, 2026-08-30)."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return "..." + text[-limit:]


class Runner:
    """
    --------------------------------------------------------------------------
    Purpose:
        Hold the catalogue, decide what may run, run it, judge it by effect and
        record it. Everything it touches - the clock, the subprocess, the PATH
        lookup, the section collector - is injected, so the whole suite runs
        offline without spawning a process (R19, R21).

    Inputs:
        repo_root (Path), home (Path): injected roots
        values (dict): {"timeout_s", "action_log", "inbox_root",
                        "message_chars", "output_tail_chars"}
        catalog (dict): parsed actions.json, loaded when omitted
        section_fn (callable): name -> freshly collected section, for the
                               effect check. None means verification is
                               unavailable and SAYS so rather than passing.
        which, run, clock, ident, profile_fn (callable): injected seams

    Outputs:
        Runner
    --------------------------------------------------------------------------
    """

    def __init__(self, repo_root, home, values, catalog=None, section_fn=None,
                 which=None, run=None, clock=None, ident=None, profile_fn=None,
                 settings_path=None):
        self.repo_root = Path(repo_root)
        self.home = Path(home)
        self.values = dict(values)
        self.catalog = catalog if catalog is not None else load_actions()
        self.section_fn = section_fn
        self._which = which or shutil.which
        self._run = run or subprocess.run
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._ident = ident or (lambda: secrets.token_hex(8))
        self._profile_fn = profile_fn or self._active_profile
        self.settings_path = (Path(settings_path) if settings_path
                              else self.home / ".claude" / "settings.json")
        self._by_id = {a["id"]: a for a in self.catalog["actions"]}

    # -- resolution -----------------------------------------------------
    def _active_profile(self):
        import collect_repo
        found = collect_repo.active_profile(self.repo_root)
        return found.get("value") if found.get("status") == "ok" else None

    def _binaries(self):
        return (self.catalog.get("argv_tokens", {})
                .get("binaries", {}))

    def _resolve_binary(self, name):
        candidates = self._binaries().get(name)
        if not candidates:
            return None, ("actions.json names no binary candidates for {%s}"
                          % name)
        for candidate in candidates:
            # The RESOLVED path, not the bare name: on Windows the launcher is
            # claude.CMD and a bare name fails [WinError 2] with no shell.
            found = self._which(candidate)
            if found:
                return found, None
        return None, ("none of %s is on PATH, so this action is not offered "
                      "rather than offered and failing on click"
                      % ", ".join(candidates))

    def resolve_argv(self, action):
        """Substitute the closed token table. Returns (argv, reason): a reason
        means the action is unavailable and nothing is spawned."""
        argv = []
        for index, item in enumerate(action.get("argv", [])):
            tokens = TOKEN_RE.findall(item)
            resolved = item
            for token in tokens:
                if token in self._binaries():
                    if index != 0:
                        return None, ("{%s} is a binary token and may only be "
                                      "argv[0]" % token)
                    path, reason = self._resolve_binary(token)
                    if path is None:
                        return None, reason
                    resolved = resolved.replace("{%s}" % token, path)
                elif token == "repo_root":
                    resolved = resolved.replace("{repo_root}",
                                                str(self.repo_root))
                elif token == "profile":
                    profile = self._profile_fn()
                    if not profile:
                        return None, ("the active profile cannot be read from "
                                      ".claude/CLAUDE.md, and this action must "
                                      "not guess one: install.ps1 with no "
                                      "-Profile prompts, and a prompt in a "
                                      "headless run hangs until the timeout")
                    resolved = resolved.replace("{profile}", str(profile))
                else:
                    # An unknown token is a refusal and never a passthrough: a
                    # literal {x} reaching a command line is how a placeholder
                    # becomes an argument nobody intended.
                    return None, ("actions.json uses {%s}, which is not in the "
                                  "closed token table" % token)
            argv.append(resolved)
        if not argv:
            return None, "this action declares no argv"
        script = self._declared_script(argv)
        if script is not None and not Path(script).exists():
            return None, ("%s does not exist in this clone"
                          % home_tilde(script, self.home))
        return argv, None

    @staticmethod
    def _declared_script(argv):
        for index, item in enumerate(argv):
            if item == "-File" and index + 1 < len(argv):
                return argv[index + 1]
        return None

    # -- catalogue ------------------------------------------------------
    def catalogue(self):
        """What the page renders. Each entry says whether it can run HERE, and
        an entry that cannot carries the reason instead of a dead button."""
        entries = []
        for action in self.catalog["actions"]:
            entry = {
                "id": action["id"],
                "label": action["label"],
                "what": action["what"],
                "kind": action.get("kind", "process"),
                "destructive": bool(action.get("destructive")),
                "confirm": action.get("confirm"),
                "verify": action.get("verify"),
            }
            if entry["kind"] == "inbox":
                entry["available"] = True
                entry["argv"] = None
            else:
                argv, reason = self.resolve_argv(action)
                entry["available"] = argv is not None
                entry["reason"] = reason
                entry["argv"] = [home_tilde(a, self.home) for a in (argv or [])]
            entries.append(entry)
        return entries

    # -- running --------------------------------------------------------
    def run(self, body):
        """
        ----------------------------------------------------------------------
        Purpose:
            The one entry point the server calls, after its own token gate.

        Inputs:
            body (dict): {"id", "confirm", "dry_run", and for the inbox
                          "target" and "text"}

        Outputs:
            result (dict): status, http_status, and the receipt of what ran
        ----------------------------------------------------------------------
        """
        action_id = body.get("id")
        action = self._by_id.get(action_id)
        if action is None:
            return self._refused(404, "no action %r is on the whitelist. The "
                                      "whitelist is closed: an id that is not "
                                      "in actions.json cannot be run."
                                 % action_id, action_id)
        dry_run = bool(body.get("dry_run"))
        if action.get("destructive") and not dry_run and body.get("confirm") is not True:
            return self._refused(
                409, action.get("confirm")
                or "this action is destructive and needs an explicit confirm",
                action_id, extra={"needs_confirm": True})

        if action.get("kind") == "inbox":
            return self._send_inbox(action, body, dry_run)

        argv, reason = self.resolve_argv(action)
        if argv is None:
            return self._record(dict(
                status="unavailable", http_status=503, id=action_id,
                reason=reason, argv=None, dry_run=dry_run))

        timeout_s = action.get("timeout_seconds", self.values["timeout_s"])
        shown = [home_tilde(a, self.home) for a in argv]
        if dry_run:
            return self._record(dict(
                status="ok", http_status=200, id=action_id, dry_run=True,
                argv=shown, timeout_seconds=timeout_s, exit_code=None,
                verified=None,
                verify_detail="--dry-run resolved the argv and spawned nothing"))

        started = time.time()
        try:
            done = self._run(argv, capture_output=True, text=True,
                             errors="replace", timeout=timeout_s, check=False,
                             cwd=str(self.repo_root))
        except subprocess.TimeoutExpired:
            return self._record(dict(
                status="failed", http_status=200, id=action_id, argv=shown,
                dry_run=False, exit_code=None,
                duration_s=round(time.time() - started, 1),
                reason="it did not finish within %ss and was stopped"
                       % timeout_s, verified=False,
                verify_detail="killed on its timeout, so no effect is claimed"))
        except OSError as exc:
            return self._record(dict(
                status="unavailable", http_status=503, id=action_id,
                argv=shown, dry_run=False, exit_code=None,
                reason="it could not be started: %s" % exc))

        duration = round(time.time() - started, 1)
        cap = self.values["output_tail_chars"]
        verified, detail = self._verify(action)
        exit_code = done.returncode
        # R9: the exit code is evidence, not the verdict. An action that exits 0
        # while its effect did not happen is FAILED, and says which of the two
        # disagreed.
        if exit_code != 0:
            status = "failed"
        elif verified is False:
            status = "failed"
        else:
            status = "ok"
        return self._record(dict(
            status=status, http_status=200, id=action_id, argv=shown,
            dry_run=False, exit_code=exit_code, duration_s=duration,
            # Redact BEFORE truncating, never after. Measured while writing
            # this suite: truncation keeps the END of the output, so a path cut
            # in the middle no longer starts with the home prefix and the
            # redaction then matches nothing - the account name survives in the
            # fragment that is published.
            stdout_tail=_tail(home_tilde(done.stdout, self.home), cap),
            stderr_tail=_tail(home_tilde(done.stderr, self.home), cap),
            verified=verified, verify_detail=detail,
            reason=("it exited 0 and the effect it claims did not happen: %s"
                    % detail) if (exit_code == 0 and verified is False) else None))

    def _verify(self, action):
        """Re-read the state the action claims to have changed."""
        name = action.get("verify")
        if not name:
            return None, "this action declares no verifiable effect"
        if name not in VERIFIERS:
            return None, "actions.json names verifier %r, which does not exist" % name
        if self.section_fn is None:
            return None, ("no collector is wired into this runner, so the "
                          "effect was not checked")
        section_name, predicate = VERIFIERS[name]
        try:
            section = self.section_fn(section_name)
        except Exception as exc:                        # noqa: BLE001
            return None, ("the %s section could not be re-read: %s: %s"
                          % (section_name, type(exc).__name__, exc))
        if not isinstance(section, dict) or section.get("status") not in (
                "ok", None):
            return None, ("the %s section is %s, so the effect could not be "
                          "checked: %s" % (section_name, section.get("status"),
                                           section.get("reason")))
        try:
            ok, detail = predicate(section)
        except Exception as exc:                        # noqa: BLE001
            return None, "the effect check raised: %s: %s" % (
                type(exc).__name__, exc)
        return bool(ok), detail

    # -- the inbox ------------------------------------------------------
    def _inbox_root(self):
        root = self.values["inbox_root"]
        text = str(root)
        if text.startswith("~/"):
            return self.home / text[2:]
        return Path(text)

    def _reachable(self):
        """The same predicate the Claude Code adapter reports per session: is a
        delivery hook actually declared. A message written into a directory
        nobody drains is the vault drop that sat in working/ for an hour."""
        path = self.settings_path
        if not path.exists():
            return False
        try:
            return "rt-inbox" in io.open(path, encoding="utf-8-sig").read()
        except OSError:
            return False

    def _send_inbox(self, action, body, dry_run):
        target = body.get("target")
        if not isinstance(target, str) or not TARGET_RE.match(target):
            return self._refused(
                400, "a target names one directory under the inbox root: "
                     "letters, digits, dot, dash and underscore only. %r is "
                     "not one, and a path is never built from it to find out."
                     % (target,), action["id"])
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            return self._refused(400, "an empty message is not sent",
                                 action["id"])
        cap = self.values["message_chars"]
        if len(text) > cap:
            return self._refused(
                400, "the message is %d characters and the cap is %d. It is "
                     "refused rather than truncated: a truncated instruction "
                     "delivered as a whole one is worse than none."
                     % (len(text), cap), action["id"])

        root = self._inbox_root().resolve()
        folder = (root / target).resolve()
        # Resolve first, then contain (R24). A junction or a dot-dot that walks
        # out of the root is refused, never clamped back in.
        if folder != root and root not in folder.parents:
            return self._refused(
                400, "the resolved target leaves the inbox root", action["id"])
        message_id = self._ident()
        stamp = self._clock().isoformat(timespec="seconds")
        record = {"id": message_id, "from": "rt-dashboard", "sent": stamp,
                  "target": target, "text": text}
        destination = folder / ("%s.json" % message_id)
        reachable = self._reachable()
        delivery = "queued" if reachable else "unreachable"
        detail = (None if reachable else
                  "no rt-inbox delivery hook is declared in %s, so this message "
                  "would sit unread. It is written and reported unreachable, "
                  "never as delivered."
                  % home_tilde(str(self.settings_path), self.home))
        if dry_run:
            return self._record(dict(
                status="ok", http_status=200, id=action["id"], dry_run=True,
                argv=None, wrote=home_tilde(str(destination), self.home),
                delivery=delivery, verified=None,
                verify_detail="--dry-run wrote nothing"))
        try:
            folder.mkdir(parents=True, exist_ok=True)
            # Atomic, the same staging discipline as outbox_io.stage(): a reader
            # never sees a half-written message.
            tmp = folder / ("%s.tmp" % message_id)
            with io.open(tmp, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(record, indent=2, ensure_ascii=False))
            os.replace(str(tmp), str(destination))
        except OSError as exc:
            return self._record(dict(
                status="failed", http_status=200, id=action["id"], argv=None,
                dry_run=False, reason="the message could not be written: %s" % exc))
        return self._record(dict(
            status="ok", http_status=200, id=action["id"], argv=None,
            dry_run=False, exit_code=0,
            wrote=home_tilde(str(destination), self.home),
            delivery=delivery, verified=None, verify_detail=detail))

    # -- the record -----------------------------------------------------
    def _refused(self, http_status, reason, action_id, extra=None):
        payload = dict(status="refused", http_status=http_status,
                       id=action_id, reason=reason)
        payload.update(extra or {})
        return self._record(payload)

    def _record(self, payload):
        """Append one JSON line per attempt, refusals included (R17). The log
        lives outside the repository, so it is never committed."""
        payload.setdefault("at", self._clock().isoformat(timespec="seconds"))
        path = self.values["action_log"]
        text = str(path)
        target = (self.home / text[2:]) if text.startswith("~/") else Path(text)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with io.open(target, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False,
                                        default=str) + "\n")
        except (OSError, ValueError) as exc:
            # ValueError as well as OSError: a configured path carrying a null
            # byte raises ValueError inside io.open, and letting that escape
            # would turn a completed action into a 500 that says nothing about
            # what actually ran. The action still happened; say the RECORD
            # failed rather than claiming the action did (R8).
            payload["log_error"] = "the action log could not be appended: %s" % exc
        return payload


def runner_values(config, config_value):
    """The configured values this module needs, read once by the caller so no
    key is spelled twice (R0, R2)."""
    return {
        "timeout_s": config_value(config, "timeouts_seconds", "action_default"),
        "action_log": config_value(config, "paths", "action_log"),
        "inbox_root": config_value(config, "paths", "inbox_root"),
        "message_chars": config_value(config, "caps", "inbox_message_chars"),
        "output_tail_chars": config_value(config, "caps", "output_tail_chars"),
    }


def _cli_runner(args):
    import rt_state
    config = rt_state.load_config()
    repo_root = Path(args.repo_root or rt_state.REPO_ROOT)
    home = Path(args.home) if args.home else Path.home()
    builders = rt_state.section_builders(repo_root, home, config)

    def section_fn(name):
        return builders[name](datetime.now(timezone.utc))

    return Runner(repo_root, home,
                  runner_values(config, rt_state.config_value),
                  section_fn=section_fn)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run one whitelisted rt-observe action, or list them.")
    parser.add_argument("--list", action="store_true",
                        help="print the whitelist and whether each can run here")
    parser.add_argument("--run", metavar="ID", default=None,
                        help="run one action by id")
    parser.add_argument("--dry-run", action="store_true",
                        help="resolve the argv and execute nothing (R16)")
    parser.add_argument("--yes", action="store_true",
                        help="confirm a destructive action (R16)")
    parser.add_argument("--json", action="store_true",
                        help="emit the machine-readable record (R17)")
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--home", default=None)
    args = parser.parse_args(argv)

    try:
        runner = _cli_runner(args)
    except ActionsError as exc:
        sys.stderr.write("%s\n" % exc)
        return 2

    if args.list or not args.run:
        entries = runner.catalogue()
        if args.json:
            json.dump(entries, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            for entry in entries:
                mark = "  " if entry["available"] else "! "
                sys.stdout.write("%s%-18s %s%s\n" % (
                    mark, entry["id"], entry["label"],
                    "  [confirm]" if entry["destructive"] else ""))
                if not entry["available"]:
                    sys.stdout.write("    unavailable: %s\n" % entry["reason"])
        return 0 if args.list else 2

    result = runner.run({"id": args.run, "confirm": bool(args.yes),
                         "dry_run": bool(args.dry_run)})
    if args.json:
        json.dump(result, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        sys.stdout.write("%s %s\n" % (result["status"], result["id"]))
        for key in ("reason", "argv", "exit_code", "verified", "verify_detail",
                    "wrote", "delivery"):
            if result.get(key) is not None:
                sys.stdout.write("  %-14s %s\n" % (key, result[key]))
        for key in ("stdout_tail", "stderr_tail"):
            if result.get(key):
                sys.stdout.write("  %s\n    %s\n"
                                 % (key, result[key].replace("\n", "\n    ")))
    # R12: 0 ran and its effect held, 1 it failed, 2 a refusal by design.
    if result["status"] == "ok":
        return 0
    if result["status"] == "refused":
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
