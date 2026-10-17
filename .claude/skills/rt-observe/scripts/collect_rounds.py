"""
collect_rounds - the `rounds` snapshot section: every plan stage of a round folder, and the
review loop of every worktree (local coding contract, plan 6, task 3).

The dashboard already reads a root `PROGRESS.md` (collect_progress.py, another shape). A round
folder (`spec.md`, `plan<N>.md`, `progress.md`) and its review loop were invisible. This
collector reads the folders named by `paths.round_roots`, counts the marks of each
`## plan<N>.md` section of the ledger (`- [ ]` open, `- [x]` done, `- [!]` blocked, and only
those), takes each plan's `executor` and `tier` from its header through `plan_contract.parse_header`
(a plan with no or an invalid header has a null executor, never a crash), and reports the
review-loop state kept in the git directory of the clone and of every worktree.

The git directory is read as plain FILES, never through a git command, exactly as collect_repo
does: sessions here may not invoke git, and this collector must work from a bare clone. A
malformed ledger line is named in `ledger_errors`, not fatal. A section that cannot be answered
is `unavailable` WITH ITS REASON (R8, R11). Every string passes through `rt_redact`.
"""
import importlib.util
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import rt_redact
from collect_local import ConfigKeyError, _cfg

SCRIPTS_DIR = Path(__file__).resolve().parent
PLAN_NAME = re.compile(r"^plan(\d*)\.md$")
SECTION = re.compile(r"^##\s+(plan\d*\.md)\b")
MARK = re.compile(r"^\s*-\s*\[(.)\]")
MARKS = {" ": "open", "x": "done", "!": "blocked"}


def _load_contract(home):
    """
    --------------------------------------------------------------------------
    Purpose:
        Import plan_contract.py by path, from the sibling skill first and from the installed
        copy under the home directory second.

    Inputs:
        home (Path): the home directory

    Outputs:
        module (module | None): plan_contract, or None when it cannot be loaded.
    --------------------------------------------------------------------------
    """
    candidates = [SCRIPTS_DIR.parent.parent / "loop-engineer" / "scripts" / "plan_contract.py",
                  Path(home) / ".claude" / "skills" / "loop-engineer" / "scripts"
                  / "plan_contract.py"]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            spec = importlib.util.spec_from_file_location("plan_contract_for_rounds", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        except Exception:  # noqa: BLE001 - an unloadable contract only costs the headers
            return None
    return None


def _header(contract, path, tiers):
    """
    --------------------------------------------------------------------------
    Purpose:
        The executor and tier a plan declares, or None for both.

    Inputs:
        contract (module | None): plan_contract
        path (Path): the plan file
        tiers (dict | None): the declared tiers, None when they cannot be read

    Outputs:
        pair (tuple): (executor, tier), each a declared value or None. A value the contract
        does not know (a header that parses but is wrong) is None, never shown as if valid.
    --------------------------------------------------------------------------
    """
    if contract is None:
        return None, None
    try:
        header = contract.parse_header(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return None, None
    executor, tier = header.get("executor"), header.get("tier")
    known_tiers = set(tiers) if tiers else None
    return (executor if executor in contract.EXECUTORS else None,
            tier if isinstance(tier, str) and (known_tiers is None or tier in known_tiers)
            else None)


def _parse_ledger(text):
    """
    --------------------------------------------------------------------------
    Purpose:
        Count the marks of each `## plan<N>.md` section of a progress ledger.

    Inputs:
        text (str): the ledger text

    Outputs:
        result (tuple): (sections, errors) where sections maps a plan file name to
        {"open", "done", "blocked"} counts and errors names every list line whose mark is none
        of the three allowed ones.
    --------------------------------------------------------------------------
    """
    sections, errors, current = {}, [], None
    for number, line in enumerate(text.split("\n"), 1):
        found = SECTION.match(line)
        if found:
            current = found.group(1)
            sections.setdefault(current, {"open": 0, "done": 0, "blocked": 0})
            continue
        if line.startswith("## "):
            current = None
            continue
        mark = MARK.match(line)
        if not mark:
            continue
        if mark.group(1) not in MARKS:
            errors.append("line %d: unknown mark [%s]" % (number, mark.group(1)))
        elif current:
            sections[current][MARKS[mark.group(1)]] += 1
    return sections, errors


def _round(folder, repo_root, contract, tiers):
    """
    --------------------------------------------------------------------------
    Purpose:
        Describe one round folder.

    Inputs:
        folder (Path): a folder holding a progress.md
        repo_root (Path): the repository root, for the relative folder name
        contract (module | None): plan_contract
        tiers (dict | None): the declared tiers

    Outputs:
        round (dict): folder, plans (name, executor, tier, task counts, state) and ledger_errors.
    --------------------------------------------------------------------------
    """
    try:
        sections, errors = _parse_ledger(
            (folder / "progress.md").read_text(encoding="utf-8", errors="replace"))
    except OSError as exc:
        sections, errors = {}, ["progress.md unreadable (%s)" % exc.__class__.__name__]
    plans = []
    names = sorted((p for p in folder.iterdir() if p.is_file() and PLAN_NAME.match(p.name)),
                   key=lambda p: int(PLAN_NAME.match(p.name).group(1) or 0))
    for path in names:
        counts = sections.get(path.name, {"open": 0, "done": 0, "blocked": 0})
        total = counts["open"] + counts["done"] + counts["blocked"]
        if counts["blocked"]:
            state = "blocked"
        elif total and counts["done"] == total:
            state = "done"
        else:
            state = "open"
        executor, tier = _header(contract, path, tiers)
        plans.append({"name": path.name, "executor": executor, "tier": tier,
                      "tasks_total": total, "tasks_done": counts["done"],
                      "tasks_blocked": counts["blocked"], "state": state})
    try:
        label = folder.relative_to(repo_root).as_posix()
    except ValueError:
        label = folder.name
    return {"folder": label, "plans": plans, "ledger_errors": errors}


def _round_folders(repo_root, roots, cap):
    """
    --------------------------------------------------------------------------
    Purpose:
        Find the folders under the configured roots that hold a progress.md.

    Inputs:
        repo_root (Path): the repository root
        roots (list[str]): repository-relative root folders
        cap (int): the most folders returned

    Outputs:
        folders (list[Path]): the root itself when it holds a progress.md, then each child
        folder that does, sorted, at most `cap`.
    --------------------------------------------------------------------------
    """
    found = []
    for rel in roots:
        base = Path(repo_root) / rel
        if (base / "progress.md").is_file():
            found.append(base)
        if base.is_dir():
            found += sorted(c for c in base.iterdir()
                            if c.is_dir() and (c / "progress.md").is_file())
    return found[:cap]


def _git_dirs(repo_root):
    """
    --------------------------------------------------------------------------
    Purpose:
        List the git directories of the clone and of its worktrees, from plain files.

    Inputs:
        repo_root (Path): the repository root

    Outputs:
        dirs (list[tuple]): (label, path) with "main clone" for the common directory and the
        worktree name for each `worktrees/<name>`; empty when there is no .git.
    --------------------------------------------------------------------------
    """
    dot = Path(repo_root) / ".git"
    common = None
    try:
        if dot.is_dir():
            common = dot
        elif dot.is_file():
            text = dot.read_text(encoding="utf-8").strip()
            own = Path(text.split(":", 1)[1].strip()) if text.startswith("gitdir:") else None
            if own is not None:
                own = own if own.is_absolute() else Path(repo_root) / own
                pointer = own / "commondir"
                common = (own / pointer.read_text(encoding="utf-8").strip()).resolve() \
                    if pointer.is_file() else own
    except OSError:
        return []
    if common is None:
        return []
    dirs = [("main clone", common)]
    work = common / "worktrees"
    if work.is_dir():
        dirs += [(child.name, child) for child in sorted(work.iterdir()) if child.is_dir()]
    return dirs


def _review_loops(repo_root, state_file_name):
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the review-loop state of every git directory and branch.

    Inputs:
        repo_root (Path): the repository root
        state_file_name (str): the loop_bounds state file name

    Outputs:
        loops (list[dict]): worktree, branch, rounds_used (the largest per-skill count, the
        one that binds), max_rounds, max_tokens, plateau and ticks (the finding counts). A
        missing or corrupt file contributes nothing.
    --------------------------------------------------------------------------
    """
    loops = []
    for label, git_dir in _git_dirs(repo_root):
        try:
            document = json.loads((git_dir / state_file_name).read_text(encoding="utf-8"))
            branches = document["branches"].items()
        except (OSError, ValueError, KeyError, AttributeError):
            continue
        for branch, state in branches:
            if not isinstance(state, dict):
                continue
            invocations = [v for v in (state.get("invocations") or {}).values()
                           if isinstance(v, int) and not isinstance(v, bool)]
            ticks = [t.get("findings") for t in (state.get("ticks") or [])
                     if isinstance(t, dict)]
            loops.append({"worktree": label, "branch": branch,
                          "rounds_used": max(invocations, default=0),
                          "max_rounds": state.get("max_rounds"),
                          "max_tokens": state.get("max_tokens"),
                          "plateau": state.get("plateau"), "ticks": ticks})
    return loops


def collect(repo_root, home, now, config):
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the `rounds` section.

    Inputs:
        repo_root (Path): the repository root
        home (Path): the home directory every string is redacted against
        now (datetime): the injected clock (R19)
        config (dict): parsed observe-config.json (paths.round_roots, caps.rounds_max)

    Outputs:
        state (dict): status "ok" with proven_by, proven_at, rounds, review_loops and
        collected_at, or status "unavailable" with a named reason. Never raises.
    --------------------------------------------------------------------------
    """
    try:
        roots = _cfg(config, "paths", "round_roots")
        cap = _cfg(config, "caps", "rounds_max")
    except ConfigKeyError as exc:
        return {"status": "unavailable", "reason": str(exc)}
    contract = _load_contract(home)
    state_file = "rt-review-loop.json"
    if contract is not None:
        try:
            state_file = contract.loop_bounds.config_value(
                contract.loop_bounds.load_config(), "state_file_name")
        except (OSError, ValueError, KeyError):
            pass
    tiers = None
    if contract is not None:
        try:
            tiers = contract.load_tiers()
        except (OSError, ValueError):
            tiers = None
    folders = _round_folders(repo_root, roots, cap)
    rounds = [_round(folder, Path(repo_root), contract, tiers) for folder in folders]
    loops = _review_loops(repo_root, state_file)
    if not rounds and not loops:
        return {"status": "unavailable",
                "reason": "no round folder with a progress.md under: %s" % ", ".join(roots)}
    newest = max(((f / "progress.md").stat().st_mtime for f in folders), default=None)
    state = {"status": "ok",
             "proven_by": rounds[0]["folder"] + "/progress.md" if rounds else "review-loop state",
             "proven_at": (datetime.fromtimestamp(newest, timezone.utc).isoformat(timespec="seconds")
                           if newest is not None else None),
             "rounds": rounds, "review_loops": loops,
             "collected_at": now.isoformat(timespec="seconds")}
    return rt_redact.redact_json(state, home)
