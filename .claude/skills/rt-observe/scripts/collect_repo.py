"""
collect_repo - what this clone can prove about itself.

Three facts, each with its receipt: whether the offline suite last passed and how
long ago, which domain profile is active, and whether the branch the work belongs
on is the branch checked out.

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
from pathlib import Path

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
    }


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


def collect(repo_root, now, stale_after_s):
    """
    --------------------------------------------------------------------------
    Purpose:
        Report the clone's own provable state: green stamp, profile, branch.

    Inputs:
        repo_root (Path): repository root
        now (datetime): injected clock (R19)
        stale_after_s (int): configured ceiling past which a green stamp is aged

    Outputs:
        state (dict): {"status", "green", "profile", "branch"}
    --------------------------------------------------------------------------
    """
    repo_root = Path(repo_root)
    return {
        "status": "ok",
        "root": str(repo_root),
        "green": _green_stamp(repo_root, now, stale_after_s),
        "profile": _active_profile(repo_root),
        "branch": _branch(repo_root),
    }
