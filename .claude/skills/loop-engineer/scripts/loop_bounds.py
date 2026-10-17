"""
loop_bounds.py - stores and decides the bounds of a review loop (R35 as amended by the local
coding contract, plan 1).

Why it exists. R35 once said to repeat /code-review and /security-review "until it returns no
finding", with no maximum. Measured 2026-10-17: seven unbounded iterations and no question put
to the owner, while `loop_engineer.py --loop` is a stub that exits, so max-iters, patience and
budget were never applied by anything. This module is the one place those three numbers live.

Three bounds, all positive integers, all asked of the owner before the first round:

  max_rounds  the number of times ONE guarded review skill may be invoked in the loop.
  max_tokens  input + cache_creation + output tokens spent since the loop was initialised.
              Cache reads are excluded (a cached prompt is re-read on every message and would
              count one conversation dozens of times), and money is not counted because no
              plan, invoice or payment method is readable from this machine.
  plateau     how many consecutive rounds may fail to lower the finding count before the loop
              stops. It needs plateau + 1 ticks to trigger, so fewer ticks always allow a round.

State is one small JSON file inside the git directory of the current worktree, so it is never
committed and two worktrees never share it, and it is keyed by branch inside that file. The
module has no model and no network. A transcript that is missing, malformed or larger than the
configured cap yields "unknown" tokens, and "unknown" never blocks (R11): only a bound that was
measured can refuse.

Exit codes of the CLI (R12): 0 ok or allowed, 2 refusal by design (a bad bound, no bounds
declared, a bound reached, a re-init without --yes), 1 failure (not a repository, git absent).
Every state-changing verb offers --dry-run (R16) and every verb offers --json (R17).

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPTS_DIR / "loop-bounds.json"

# Tokens counted per message, in the same way rt-observe's collect_usage.py counts them.
USAGE_KEYS = ("input_tokens", "cache_creation_input_tokens", "output_tokens")
BOUND_KEYS = ("max_rounds", "max_tokens", "plateau")
DETACHED_KEY = "(detached HEAD)"
# The remedy names THIS script by absolute path: the review-loop hook is installed globally and
# refuses in every project, where a repo-relative path would not exist.
INIT_COMMAND = (f'python "{Path(__file__).resolve()}" init '
                "--max-rounds N --max-tokens N --plateau N --yes")


def canonical_skill(name: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        One counter per review skill, whatever the spelling it was invoked under:
        `code-review`, `/code-review` and the plugin form `code-review:code-review` are the
        same skill, and counting them apart would allow max_rounds times the spellings.

    Inputs:
        name (str): the skill name as invoked.

    Outputs:
        name (str): the part after the last colon, without a leading slash.
    --------------------------------------------------------------------------
    """
    return str(name).strip().lstrip("/").split(":")[-1]


class BoundsError(ValueError):
    """A bound or a count that is not acceptable, named by its key."""


def load_config(path: Path = CONFIG_PATH) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read loop-bounds.json, whose entries are {value, provenance} pairs (R4).

    Inputs:
        path (Path): the configuration file, the skill's own by default.

    Outputs:
        config (dict): the parsed file.

    Raises:
        FileNotFoundError: the file is absent.
        ValueError: the file is not valid JSON.
    --------------------------------------------------------------------------
    """
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc


def config_value(config: dict, key: str) -> Any:
    """
    --------------------------------------------------------------------------
    Purpose:
        Return the "value" of one configuration entry.

    Inputs:
        config (dict): the parsed loop-bounds.json.
        key (str): the entry name.

    Outputs:
        value (Any): the entry's "value" field.

    Raises:
        KeyError: the entry or its "value" field is absent (R3), naming the key and file.
    --------------------------------------------------------------------------
    """
    entry = config.get(key)
    if not isinstance(entry, dict) or "value" not in entry:
        raise KeyError(f"loop-bounds.json declares no usable '{key}' entry")
    return entry["value"]


def git_output(cwd: Path, args: list[str], config: dict) -> str | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run one git command with the configured timeout (R10).

    Inputs:
        cwd (Path): directory to run in.
        args (list[str]): arguments after "git".
        config (dict): parsed loop-bounds.json.

    Outputs:
        stdout (str | None): stripped output, or None when git is absent, the directory is
        missing, the command fails or the timeout expires.
    --------------------------------------------------------------------------
    """
    try:
        done = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                              timeout=config_value(config, "git_timeout_s"), check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def state_path(cwd: Path, *, config: dict | None = None) -> Path | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Locate the state file inside the git directory of the worktree holding cwd.

    Inputs:
        cwd (Path): any directory inside a repository or worktree.
        config (dict | None): parsed loop-bounds.json, loaded when omitted.

    Outputs:
        path (Path | None): <git-dir>/<state_file_name>, or None outside a repository, when
        git is absent, or after the timeout.
    --------------------------------------------------------------------------
    """
    config = config if config is not None else load_config()
    git_dir = git_output(Path(cwd), ["rev-parse", "--absolute-git-dir"], config)
    if not git_dir:
        return None
    return Path(git_dir) / config_value(config, "state_file_name")


def current_branch(cwd: Path, *, config: dict | None = None) -> str | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Name the branch state is keyed by.

    Inputs:
        cwd (Path): any directory inside a repository.
        config (dict | None): parsed loop-bounds.json, loaded when omitted.

    Outputs:
        branch (str | None): the branch name, a fixed key for a detached HEAD, or None when
        git cannot answer.
    --------------------------------------------------------------------------
    """
    config = config if config is not None else load_config()
    name = git_output(Path(cwd), ["branch", "--show-current"], config)
    if name is None:
        return None
    return name or DETACHED_KEY


def _read_document(path: Path) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the whole state file, tolerating absence and corruption.

    Inputs:
        path (Path): the state file.

    Outputs:
        document (dict): {"branches": {...}}, empty when the file is missing or unreadable.
    --------------------------------------------------------------------------
    """
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"branches": {}}
    if not isinstance(doc, dict) or not isinstance(doc.get("branches"), dict):
        return {"branches": {}}
    return doc


def load_state(path: Path, branch: str) -> dict | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the state of one branch; the state of any other branch is never returned.

    Inputs:
        path (Path): the state file.
        branch (str): the branch key.

    Outputs:
        state (dict | None): the branch's state, or None when it was never initialised or the
        file is missing or corrupt.
    --------------------------------------------------------------------------
    """
    state = _read_document(path)["branches"].get(branch)
    return state if isinstance(state, dict) else None


def save_state(path: Path, branch: str, state: dict) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Store one branch's state, keeping the other branches, through a temporary file and
        os.replace so a reader never sees a half-written file.

    Inputs:
        path (Path): the state file.
        branch (str): the branch key.
        state (dict): the state to store.

    Outputs:
        None. Side effect: the file at path now holds the state under the branch key.
    --------------------------------------------------------------------------
    """
    path = Path(path)
    doc = _read_document(path)
    doc["branches"][branch] = state
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _positive_int(key: str, value: Any) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Accept only a strictly positive int; a bool, a string and a float are refused.

    Inputs:
        key (str): the bound's name, quoted in the refusal.
        value (Any): the candidate.

    Outputs:
        value (int): the same value.

    Raises:
        BoundsError: the value is not a positive int, naming the key.
    --------------------------------------------------------------------------
    """
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BoundsError(f"{key} must be a positive integer, got {value!r}")
    return value


def init_state(branch: str, max_rounds: int, max_tokens: int, plateau: int,
               transcript: Path | None, now_iso: str) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the state of a new review loop from the owner's three bounds.

    Inputs:
        branch (str): the branch the loop runs on.
        max_rounds (int): rounds allowed per guarded skill.
        max_tokens (int): token budget from now on.
        plateau (int): consecutive non-improving rounds tolerated.
        transcript (Path | None): the session transcript whose growth is measured, if known.
        now_iso (str): the creation time, injected by the caller (R19).

    Outputs:
        state (dict): the new state; transcript_offset is the transcript's size now, or None.

    Raises:
        BoundsError: a bound is not a positive integer, naming the key.
    --------------------------------------------------------------------------
    """
    bounds = {key: _positive_int(key, val) for key, val in
              zip(BOUND_KEYS, (max_rounds, max_tokens, plateau))}
    offset = None
    if transcript is not None:
        try:
            offset = Path(transcript).stat().st_size
        except OSError:
            offset = None
    return {"branch": branch, **bounds, "transcript": str(transcript) if transcript else None,
            "transcript_offset": offset, "created": now_iso, "invocations": {}, "ticks": []}


def record_invocation(state: dict, skill: str) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Count one invocation of a guarded skill.

    Inputs:
        state (dict): the loop state, modified in place.
        skill (str): the guarded skill's name.

    Outputs:
        None. Side effect: state["invocations"][skill] grows by one.
    --------------------------------------------------------------------------
    """
    counts = state.setdefault("invocations", {})
    key = canonical_skill(skill)
    counts[key] = int(counts.get(key, 0)) + 1


def tick(state: dict, findings: int, now_iso: str) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Record how many findings a finished review round returned.

    Inputs:
        state (dict): the loop state, modified in place.
        findings (int): the finding count, zero or more.
        now_iso (str): the time, injected by the caller (R19).

    Outputs:
        None. Side effect: one entry appended to state["ticks"].

    Raises:
        BoundsError: findings is not a non-negative int.
    --------------------------------------------------------------------------
    """
    if isinstance(findings, bool) or not isinstance(findings, int) or findings < 0:
        raise BoundsError(f"findings must be a non-negative integer, got {findings!r}")
    state.setdefault("ticks", []).append({"findings": findings, "at": now_iso})


def tokens_since(transcript: Path, offset: int, max_bytes: int) -> int | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Sum the tokens a session spent after a byte offset of its transcript.

    Details:
        Counts input + cache_creation + output per message and skips cache reads. A malformed
        line is skipped. Anything that prevents an honest answer returns None.

    Inputs:
        transcript (Path): the JSONL session transcript.
        offset (int): bytes before this position are ignored.
        max_bytes (int): when more than this many bytes lie after the offset, give up.

    Outputs:
        tokens (int | None): the sum, or None when the file is missing, unreadable or too big.
    --------------------------------------------------------------------------
    """
    try:
        with open(transcript, "rb") as handle:
            size = os.fstat(handle.fileno()).st_size
            if size - offset > max_bytes:
                return None
            handle.seek(min(offset, size))
            data = handle.read()
    except OSError:
        return None
    total = 0
    for raw in data.decode("utf-8", errors="replace").splitlines():
        try:
            usage = json.loads(raw)["message"]["usage"]
            total += sum(int(usage.get(key) or 0) for key in USAGE_KEYS)
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    return total


def _plateaued(state: dict) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Tell whether the last `plateau` rounds all failed to lower the finding count.

    Inputs:
        state (dict): the loop state.

    Outputs:
        stalled (bool): True when plateau + 1 ticks exist and each of the last `plateau`
        transitions is equal or rising.
    --------------------------------------------------------------------------
    """
    counts = [t["findings"] for t in state.get("ticks", [])]
    window = state["plateau"] + 1
    if len(counts) < window:
        return False
    last = counts[-window:]
    return all(later >= earlier for earlier, later in zip(last, last[1:]))


def decide(state: dict | None, skill: str, tokens_used: int | None) -> tuple[bool, str | None]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Decide whether one more round of a guarded review skill may start.

    Inputs:
        state (dict | None): the branch's loop state, None when never initialised.
        skill (str): the guarded skill about to run.
        tokens_used (int | None): tokens spent since init, None when unknown (never blocks).

    Outputs:
        decision (tuple[bool, str | None]): (True, None) or (False, a reason naming the bound
        reached and the way out).
    --------------------------------------------------------------------------
    """
    if state is None:
        return False, (f"no review-loop bounds are declared for this branch. Ask the owner for "
                       f"max rounds, max tokens and plateau, then run: {INIT_COMMAND}")
    skill = canonical_skill(skill)
    used = int(state.get("invocations", {}).get(skill, 0))
    if used >= state["max_rounds"]:
        return False, (f"max_rounds reached for {skill}: {used} of {state['max_rounds']}. "
                       "Stop, report what remains and ask the owner whether to raise it.")
    if tokens_used is not None and tokens_used > state["max_tokens"]:
        return False, (f"max_tokens exceeded: {tokens_used} used of {state['max_tokens']}. "
                       "Stop, report what remains and ask the owner whether to raise it.")
    if _plateaued(state):
        return False, (f"plateau: the last {state['plateau']} rounds did not lower the finding "
                       "count. Stop, report what remains and ask the owner.")
    return True, None


def _now() -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        The wall clock for the CLI boundary only; logic receives time as an argument (R19).

    Inputs:
        None.

    Outputs:
        now_iso (str): current UTC time, ISO 8601.
    --------------------------------------------------------------------------
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def tokens_used(state: dict, config: dict) -> int | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Tokens spent since init, or None when the state names no readable transcript.

    Inputs:
        state (dict): the loop state.
        config (dict): parsed loop-bounds.json.

    Outputs:
        tokens (int | None): the sum from tokens_since, or None.
    --------------------------------------------------------------------------
    """
    transcript, offset = state.get("transcript"), state.get("transcript_offset")
    if not transcript or offset is None:
        return None
    return tokens_since(Path(transcript), offset, config_value(config, "transcript_scan_max_bytes"))


def _build_parser() -> argparse.ArgumentParser:
    """
    --------------------------------------------------------------------------
    Purpose:
        Declare the CLI: init, status, tick, check.

    Inputs:
        None.

    Outputs:
        parser (argparse.ArgumentParser): the configured parser.
    --------------------------------------------------------------------------
    """
    parser = argparse.ArgumentParser(description="Review-loop bounds engine (R35).")
    parser.add_argument("--cwd", default=".", help="directory inside the repository")
    parser.add_argument("--json", action="store_true", help="print a JSON report")
    sub = parser.add_subparsers(dest="verb", required=True)
    init = sub.add_parser("init", help="declare the three bounds for this branch")
    for key in BOUND_KEYS:
        init.add_argument("--" + key.replace("_", "-"), dest=key, type=int)
    init.add_argument("--from-plan", help="take the three bounds from this plan's header")
    init.add_argument("--transcript", help="session transcript whose growth is measured")
    init.add_argument("--dry-run", action="store_true", help="write nothing")
    init.add_argument("--yes", action="store_true", help="overwrite existing state")
    sub.add_parser("status", help="show this branch's state")
    tick_cmd = sub.add_parser("tick", help="record the finding count of a finished round")
    tick_cmd.add_argument("--findings", type=int, required=True)
    tick_cmd.add_argument("--dry-run", action="store_true", help="write nothing")
    check = sub.add_parser("check", help="may another round of SKILL start?")
    check.add_argument("--skill", required=True)
    check.add_argument("--record", action="store_true", help="count the round when allowed")
    return parser


def main(argv: list[str] | None = None) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Command-line entry point: init, status, tick and check.

    Inputs:
        argv (list[str] | None): arguments, sys.argv[1:] when omitted.

    Outputs:
        exit_code (int): 0 ok or allowed, 2 refusal by design, 1 failure. A report is printed
        on stdout, as JSON with --json.
    --------------------------------------------------------------------------
    """
    args = _build_parser().parse_args(argv)
    report: dict[str, Any] = {"verb": args.verb}
    code = _run(args, report)
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print(report.get("error") or report.get("reason") or json.dumps(report, sort_keys=True))
    return code


def _run(args: argparse.Namespace, report: dict) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Execute one verb and fill the report.

    Inputs:
        args (argparse.Namespace): parsed arguments.
        report (dict): filled in place.

    Outputs:
        exit_code (int): 0, 1 or 2 as described in main.
    --------------------------------------------------------------------------
    """
    try:
        config = load_config()
        cwd = Path(args.cwd)
        path = state_path(cwd, config=config)
        branch = current_branch(cwd, config=config)
    except (OSError, ValueError, KeyError) as exc:
        report["error"] = f"loop_bounds configuration problem: {exc}"
        return 1
    if path is None or branch is None:
        report["error"] = f"{cwd} is not inside a git repository (or git did not answer)"
        return 1
    report.update(branch=branch, state_file=str(path))
    state = load_state(path, branch)
    if args.verb == "init":
        return _init(args, report, config, path, branch, state)
    if args.verb == "status":
        report["initialised"] = state is not None
        if state is not None:
            report.update({k: state[k] for k in (*BOUND_KEYS, "invocations", "ticks")})
            report["tokens_used"] = tokens_used(state, config)
        return 0
    if state is None:
        report.update(error=None, allowed=False, reason=decide(None, "", None)[1])
        return 2 if args.verb == "check" else _refuse_no_state(report)
    if args.verb == "tick":
        try:
            tick(state, args.findings, _now())
        except BoundsError as exc:
            report["error"] = str(exc)
            return 2
        report["findings"] = args.findings
        report["dry_run"] = args.dry_run
        if not args.dry_run:
            save_state(path, branch, state)
        return 0
    allowed, reason = decide(state, args.skill, tokens_used(state, config))
    report.update(skill=args.skill, allowed=allowed, reason=reason,
                  tokens_used=tokens_used(state, config))
    if allowed and args.record:
        record_invocation(state, args.skill)
        save_state(path, branch, state)
    return 0 if allowed else 2


def _refuse_no_state(report: dict) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Refuse a verb that needs bounds when none were declared.

    Inputs:
        report (dict): the report, whose error field gets the reason.

    Outputs:
        exit_code (int): always 2.
    --------------------------------------------------------------------------
    """
    report["error"] = report["reason"]
    return 2


def _bounds_from_plan(plan: Path, cwd: Path) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the three bounds from a plan's header, through the plan contract.

    Details:
        Validates the header, the tier's file limit and the plan's location, not the size
        ceilings (the dispatch guard checks those).

    Inputs:
        plan (Path): the plan file.
        cwd (Path): a directory inside the repository, to find the allowed roots.

    Outputs:
        bounds (dict): {max_rounds, max_tokens, plateau}.

    Raises:
        ValueError: the plan breaks the contract (plan_contract.PlanError), naming the key.
        OSError: the tier file cannot be read.
    --------------------------------------------------------------------------
    """
    import plan_contract  # noqa: PLC0415 - imports this module, so only loaded when asked

    tiers = plan_contract.load_tiers()
    roots = plan_contract.repository_roots(cwd) or [cwd]
    return plan_contract.validate(plan, roots, tiers)["bounds"]


def _init(args: argparse.Namespace, report: dict, config: dict, path: Path, branch: str,
          existing: dict | None) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run the init verb: validate, refuse an unconfirmed overwrite, write unless dry run.

    Inputs:
        args (argparse.Namespace): parsed arguments.
        report (dict): filled in place.
        config (dict): parsed loop-bounds.json.
        path (Path): the state file.
        branch (str): the branch key.
        existing (dict | None): the branch's current state.

    Outputs:
        exit_code (int): 0 written or dry run, 2 refused.
    --------------------------------------------------------------------------
    """
    transcript = Path(args.transcript) if args.transcript else None
    given = {key: getattr(args, key) for key in BOUND_KEYS if getattr(args, key) is not None}
    if args.from_plan and given:
        report["error"] = "--from-plan replaces --max-rounds, --max-tokens and --plateau: give one or the other"
        return 2
    if args.from_plan:
        try:
            given = _bounds_from_plan(Path(args.from_plan), Path(args.cwd))
        except OSError as exc:
            report["error"] = f"plan contract configuration problem: {exc}"
            return 1
        except ValueError as exc:  # PlanError is a ValueError
            report["error"] = str(exc)
            return 2
    elif len(given) < len(BOUND_KEYS):
        report["error"] = ("give --max-rounds, --max-tokens and --plateau, or --from-plan "
                           "<plan file>")
        return 2
    try:
        state = init_state(branch, given["max_rounds"], given["max_tokens"], given["plateau"],
                           transcript, _now())
    except BoundsError as exc:
        report["error"] = str(exc)
        return 2
    report.update(dry_run=args.dry_run, state=state)
    if existing is not None and not args.yes and not args.dry_run:
        report["error"] = ("bounds already declared for this branch; re-run with --yes to "
                           "overwrite them (a re-init resets the round counters)")
        return 2
    if not args.dry_run:
        save_state(path, branch, state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
