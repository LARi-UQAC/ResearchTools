"""
collect_repo - what this clone can prove about itself.

Four facts, each with its receipt: whether the offline suite last passed and how
long ago, which domain profile is active, whether the branch the work belongs
on is the branch checked out, and whether the suite interpreter (.venv-skills, in
this clone or the main clone) exists. The last one was added 2026-10-16: the
environment was emptied on 2026-10-06 and nothing reported it for a week.

The green stamp is read with encoding="utf-8-sig". It carries a UTF-8 BOM,
because PowerShell wrote it, and plain utf-8 RAISES on it (measured 2026-08-30).
An absent stamp means "not proven", never "green": the file is deleted by the
runner on any failure, so its absence is the failure signal and reading it as
"nothing to report" would invert the meaning exactly.

The branch is read from .git/HEAD, which is a plain text file. That is a file
read and not a git command, which matters here: this toolkit's sessions are
forbidden to invoke git at all, and every session in a directory shares one
.git/HEAD, so a peer switching branch moves it underneath you. Measured
2026-08-30: work planned for a feature branch was about to be written onto main
for exactly that reason.
"""
import io
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rt_redact import home_tilde  # noqa: E402

ACTIVE_PROFILE = re.compile(r"(?m)^active_profile:\s*(\S+)\s*$")
HEAD_REF = re.compile(r"^ref:\s*refs/heads/(.+?)\s*$")


def _age_seconds(path, now):
    try:
        return max(0.0, now.timestamp() - path.stat().st_mtime)
    except OSError:
        return None


def _green_stamp(repo_root, now, stale_after_s):
    path = Path(repo_root) / ".rt-green.json"
    if not path.exists():
        return {
            "status": "unavailable",
            "value": "not proven",
            "reason": "no .rt-green.json. The runner DELETES it on any failure, "
                      "so its absence means the suite last failed or never ran - "
                      "never that everything is fine.",
        }
    try:
        stamp = json.loads(io.open(path, encoding="utf-8-sig").read())
    except ValueError as exc:
        return {"status": "unavailable", "value": "unreadable",
                "reason": ".rt-green.json does not parse: %s" % exc}

    outcomes = stamp.get("outcomes", [])
    suites = stamp.get("suites", {})
    age = _age_seconds(path, now)
    aged = age is not None and age > stale_after_s
    return {
        "status": "ok",
        "value": "green",
        "proven_by": "run-offline-tests.ps1",
        "proven_at": stamp.get("generated"),
        "age_seconds": None if age is None else int(age),
        "aged": aged,
        "reason": ("this stamp is older than the configured ceiling, so it says "
                   "the suite passed then, not that it would pass now"
                   if aged else None),
        "suites": suites,
        "outcome_count": len(outcomes),
        "code_files_hashed": len(stamp.get("code_hashes", {})),
        "elapsed_s": stamp.get("elapsed_s"),
        # Which kind of interpreter produced the stamp (explicit, venv, main-repo-venv,
        # path-fallback). A stamp from a PATH python did not exercise the suites whose
        # packages that python lacks, so the reader needs to be able to tell.
        "interpreter_source": stamp.get("interpreter_source"),
    }


def active_profile(repo_root):
    """Public since 2026-08-31: rt_actions substitutes {profile} into
    install.ps1's argv from here, rather than spelling a profile name of its
    own. install.ps1 with no -Profile PROMPTS, and a prompt in a headless run
    hangs until the timeout, so this is the one reader (R2)."""
    return _active_profile(repo_root)


def _active_profile(repo_root):
    path = Path(repo_root) / ".claude" / "CLAUDE.md"
    if not path.exists():
        return {"status": "unavailable",
                "reason": "no .claude/CLAUDE.md, which is where the "
                          "machine-readable active_profile line lives"}
    try:
        text = io.open(path, encoding="utf-8").read()
    except OSError as exc:
        return {"status": "unavailable", "reason": str(exc)}
    found = ACTIVE_PROFILE.search(text)
    if not found:
        return {"status": "unavailable",
                "reason": "no active_profile: line in .claude/CLAUDE.md"}
    name = found.group(1)
    profile_file = Path(repo_root) / "profiles" / (name + ".yaml")
    return {
        "status": "ok",
        "value": name,
        "proven_by": ".claude/CLAUDE.md",
        "profile_file_exists": profile_file.exists(),
        "reason": (None if profile_file.exists() else
                   "the selector names %r but profiles/%s.yaml does not exist, so "
                   "every profile-aware agent falls back or refuses" % (name, name)),
    }


def _branch(repo_root):
    """The checked-out branch, read as a FILE. Never a git invocation."""
    head = Path(repo_root) / ".git" / "HEAD"
    if not head.exists():
        return {"status": "unavailable",
                "reason": "no .git/HEAD; this is not a git working tree, which is "
                          "a normal configuration for an exported copy"}
    try:
        first = io.open(head, encoding="utf-8").readline().strip()
    except OSError as exc:
        return {"status": "unavailable", "reason": str(exc)}
    found = HEAD_REF.match(first)
    if not found:
        return {"status": "ok", "value": "detached",
                "proven_by": ".git/HEAD",
                "reason": "HEAD is detached, so commits would belong to no branch"}
    return {"status": "ok", "value": found.group(1), "proven_by": ".git/HEAD"}


VENV_DIR = ".venv-skills"
# Both venv layouts: Windows puts the interpreter under Scripts, POSIX under bin.
VENV_INTERPRETERS = ("Scripts/python.exe", "bin/python")
GITDIR_LINE = re.compile(r"^gitdir:\s*(.+?)\s*$")


def main_clone_root(repo_root):
    """
    --------------------------------------------------------------------------
    Purpose:
        The root of the MAIN clone that owns repo_root. In a linked worktree
        .git is a FILE naming the worktree's private git directory, and that
        directory's `commondir` file points at the main clone's .git. Both are
        ordinary text, so no git command is needed (this module's rule).

    Inputs:
        repo_root (Path): the clone or worktree root

    Outputs:
        root (Path): the main clone root, or repo_root itself when this is the
        main clone, a folder with no .git, or anything unreadable.
    --------------------------------------------------------------------------
    """
    repo_root = Path(repo_root)
    dot_git = repo_root / ".git"
    if not dot_git.is_file():
        return repo_root
    try:
        # `with` so no handle outlives the call: this runs on every snapshot refresh,
        # and an open handle on a worktree's gitdir files can block its removal.
        with io.open(dot_git, encoding="utf-8") as handle:
            found = GITDIR_LINE.match(handle.readline())
        if not found:
            return repo_root
        gitdir = Path(found.group(1))
        if not gitdir.is_absolute():
            gitdir = repo_root / gitdir
        with io.open(gitdir / "commondir", encoding="utf-8") as handle:
            commondir = handle.readline().strip()
        common = (gitdir / commondir).resolve()
    except (OSError, ValueError):
        return repo_root
    return common.parent if common.name == ".git" else repo_root


HOME_LINE = re.compile(r"(?m)^\s*home\s*=\s*(.+?)\s*$")


def _missing_base(venv):
    """
    --------------------------------------------------------------------------
    Purpose:
        The base interpreter folder pyvenv.cfg points at when that folder is
        gone. A launcher stub that outlived its base still has a python.exe, and
        every caller then dies with "No Python at ...".

    Inputs:
        venv (Path): the .venv-skills folder

    Outputs:
        folder (str): the missing base folder, or "" when it exists or the file
        cannot be read (an unreadable cfg proves nothing, so it is not "broken")
    --------------------------------------------------------------------------
    """
    try:
        with io.open(Path(venv) / "pyvenv.cfg", encoding="utf-8") as handle:
            found = HOME_LINE.search(handle.read())
    except OSError:
        return ""
    if not found or Path(found.group(1)).is_dir():
        return ""
    return found.group(1)


def _venv_probe(root):
    """
    --------------------------------------------------------------------------
    Purpose:
        Say what a clone's .venv-skills holds, on either layout.

    Inputs:
        root (Path or str): the clone whose environment is probed

    Outputs:
        probe (dict): {"state": "present" | "empty" | "absent", "python": path}.
        "empty" is a folder with no interpreter, the 2026-10-06 state.
    --------------------------------------------------------------------------
    """
    base = Path(root) / VENV_DIR
    for rel in VENV_INTERPRETERS:
        if (base / rel).is_file():
            missing = _missing_base(base)
            if missing:
                return {"state": "broken", "python": str(base / rel), "missing_base": missing}
            return {"state": "present", "python": str(base / rel)}
    if base.is_dir():
        return {"state": "empty", "python": str(base / VENV_INTERPRETERS[0])}
    return {"state": "absent", "python": str(base / VENV_INTERPRETERS[0])}


def _interpreter(repo_root, home=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        The suite interpreter, or the reason there is none. Never PATH: since
        2026-10-16 the launchers refuse instead of falling back, and this
        section says the same thing they say (R8). Every path in the result is
        rewritten under `~` (rt_redact), because the snapshot is rendered in a
        browser and the account name must not travel with it.

    Inputs:
        repo_root (Path or str): the clone or worktree
        home (Path): home directory to hide; defaults to the current user's

    Outputs:
        state (dict): {"status": "ok", "value", "source", "proven_by"} or
        {"status": "unavailable", "value": "no interpreter", "reason"}
    --------------------------------------------------------------------------
    """
    result = _interpreter_raw(repo_root)
    home = Path.home() if home is None else home
    for key in ("value", "reason"):
        if key in result:
            result[key] = home_tilde(result[key], home)
    return result


def _interpreter_raw(repo_root):
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve the interpreter without redaction: this clone's .venv-skills,
        then the main clone's when repo_root is a linked worktree.

    Inputs:
        repo_root (Path or str): the clone or worktree

    Outputs:
        state (dict): same shape as _interpreter, paths in full
    --------------------------------------------------------------------------
    """
    repo_root = Path(repo_root)
    main = main_clone_root(repo_root)
    roots = [("venv", repo_root)]
    if main != repo_root:
        roots.append(("main-repo-venv", main))
    probes = []
    for source, root in roots:
        probe = _venv_probe(root)
        probe["source"] = source
        probes.append(probe)
        if probe["state"] == "present":
            return {"status": "ok", "value": probe["python"], "source": source,
                    "proven_by": VENV_DIR + " (filesystem)"}
    wording = {"empty": "folder EMPTY or damaged", "absent": "absent"}
    notes = ["%s [%s]" % (p["python"],
                          "BROKEN: its base interpreter folder is gone (%s)" % p["missing_base"]
                          if p["state"] == "broken" else wording[p["state"]])
             for p in probes]
    return {
        "status": "unavailable",
        "value": "no interpreter",
        "reason": "no %s interpreter. Looked at: %s. Launchers refuse rather than "
                  "use a python from PATH. Rebuild with: setup.ps1 -InstallPython "
                  "(run from %s)" % (VENV_DIR, "; ".join(notes), main),
    }


def collect(repo_root, now, stale_after_s, home=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Report the clone's own provable state: green stamp, profile, branch,
        and the suite interpreter.

    Inputs:
        repo_root (Path): repository root
        now (datetime): injected clock (R19)
        stale_after_s (int): configured ceiling past which a green stamp is aged
        home (Path): home directory hidden as `~` in the interpreter paths;
                     defaults to the current user's

    Outputs:
        state (dict): {"status", "green", "profile", "branch", "interpreter"}
    --------------------------------------------------------------------------
    """
    repo_root = Path(repo_root)
    return {
        "status": "ok",
        "root": str(repo_root),
        "green": _green_stamp(repo_root, now, stale_after_s),
        "profile": _active_profile(repo_root),
        "branch": _branch(repo_root),
        "interpreter": _interpreter(repo_root, home),
    }
