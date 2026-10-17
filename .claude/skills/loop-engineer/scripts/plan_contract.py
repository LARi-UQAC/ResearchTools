"""
plan_contract.py - validates a plan's header and resolves its tier to a resolver ROLE
(local coding contract, plan 3).

A plan carries three things in a front-matter header: `executor` (`local-coder`, `aider` or
`cloud`), `tier` (`simple`, `standard`, `large`) and `bounds` (`max_rounds`, `max_tokens`,
`plateau`, positive integers the owner chose). This module reads the header with the standard
library, checks it, enforces the file limit of the tier and the size ceilings of the plan, spec,
progress and audit files, and maps the tier to a resolver ROLE through `plan-tiers.json`.
`model_resolver.py` names the tag at run time, so no tag is written here (R2).

Contract, each point proven in Test/test_plan_contract.py:

  * A header that parses but is wrong (`"3"`, `0`, a bool, a list, an unknown key, an unknown
    tier or executor, a missing key) is refused and the key is named.
  * The plan path is resolved FIRST and must sit inside an allowed repository root (R24). The
    roots are the worktree and the main clone it belongs to, since a plan folder may live in
    the main clone while the work happens in a worktree.
  * The size ceilings come from `context-budget.json` (single source, spec D9), never from this
    code. A file exactly at its ceiling passes and one token over fails, an estimate is
    multiplied by the margin first, and a refusal names file, count, method and ceiling.
  * A tier resolves to ONE role. A `simple` plan whose `coder` role is unqualified becomes a
    `cloud` plan with the resolver's reason, and never borrows the `large` role (R8).

Exit codes of the CLI (R12): 0 ok, 2 refusal by design (a plan that breaks the contract), 1
failure (a configuration file that cannot be read). Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:  # a long-lived importer must not grow sys.path
    sys.path.insert(0, str(SCRIPTS_DIR))

import loop_bounds  # noqa: E402
import token_count  # noqa: E402

TIERS_PATH = SCRIPTS_DIR.parent / "plan-tiers.json"
EXECUTORS = ("local-coder", "aider", "cloud")
HEADER_KEYS = ("executor", "tier", "bounds")
BOUND_KEYS = loop_bounds.BOUND_KEYS
CEILING_KEYS = ("spec.md", "plan.md", "progress.md", "audit.md", "code_file")
FILE_LINE = re.compile(
    r"^\s*-\s*(?:\*\*)?(?:Create|Modify|Test):(?:\*\*)?\s*(?:`([^`]+)`|(\S+))")
class PlanError(ValueError):
    """A plan or a contract file that breaks the contract, with the key or file named."""


class RoleUnavailable(RuntimeError):
    """A resolver refusal: no qualified model for the role."""


def _scalar(value: str) -> Any:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read one front-matter value: a quoted string, an integer, a boolean, a flat list or a
        bare string. Quoting is how a test plants the string "3".

    Inputs:
        value (str): the text after the colon, stripped.

    Outputs:
        value (Any): str, int, bool or list[str].
    --------------------------------------------------------------------------
    """
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    if value.startswith("[") and value.endswith("]"):
        return [part.strip() for part in value[1:-1].split(",") if part.strip()]
    return value


def parse_header(text: str) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Parse the front matter between the first two `---` lines: top-level `key: value`
        lines and one nested mapping (`bounds:`) indented below its key.

    Inputs:
        text (str): the whole plan text.

    Outputs:
        header (dict): the parsed keys, values typed by _scalar.

    Raises:
        PlanError: no front matter, no closing line, a line that is not `key: value`, an
        indented line outside a mapping, or a duplicated key.
    --------------------------------------------------------------------------
    """
    lines = text.lstrip("﻿").replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        raise PlanError("the plan has no front matter: it must open with a --- line")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise PlanError("the front matter has no closing --- line") from None
    header: dict[str, Any] = {}
    current: str | None = None
    for raw in lines[1:end]:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        key, sep, value = raw.strip().partition(":")
        if not sep:
            raise PlanError(f"front matter line is not 'key: value': {raw.strip()!r}")
        target = header[current] if raw[0] in " \t" and current else header
        if raw[0] in " \t" and current is None:
            raise PlanError(f"indented front matter line outside a mapping: {raw.strip()!r}")
        if key in target:
            raise PlanError(f"front matter key '{key}' is given twice")
        value = value.strip()
        if raw[0] not in " \t" and value == "":
            header[key] = {}
            current = key
        else:
            target[key] = _scalar(value)
            current = current if raw[0] in " \t" else None
    return header


def _read_json(path: Path) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read a JSON object from a contract file.

    Inputs:
        path (Path): the file.

    Outputs:
        data (dict): the parsed object.

    Raises:
        OSError: the file cannot be read.
        PlanError: the file is not a JSON object.
    --------------------------------------------------------------------------
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise PlanError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise PlanError(f"{path} must hold a JSON object")
    return data


def load_tiers(path: Path = TIERS_PATH) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read plan-tiers.json into {tier: {"role": str, "max_files": int}}.

    Inputs:
        path (Path): the tier file, the skill's own by default.

    Outputs:
        tiers (dict): one entry per tier, each value taken from its {value, provenance} pair.

    Raises:
        PlanError: a tier lacks a key or holds a wrong value, naming key and file (R3).
        OSError: the file cannot be read.
    --------------------------------------------------------------------------
    """
    data = _read_json(path)
    tiers: dict[str, dict] = {}
    for name, entry in (data.get("tiers") or {}).items():
        out: dict[str, Any] = {}
        for key in ("role", "max_files"):
            item = entry.get(key) if isinstance(entry, dict) else None
            if not isinstance(item, dict) or "value" not in item:
                raise PlanError(f"{Path(path).name} declares no {key} for tier {name}")
            out[key] = item["value"]
        if not isinstance(out["role"], str) or not isinstance(out["max_files"], int) \
                or isinstance(out["max_files"], bool) or out["max_files"] < 1:
            raise PlanError(f"{Path(path).name} tier {name} needs a role string and a "
                            "positive integer max_files")
        tiers[name] = out
    if not tiers:
        raise PlanError(f"{Path(path).name} declares no tiers")
    return tiers


def budget_candidates(tiers_path: Path = TIERS_PATH) -> list[Path]:
    """
    --------------------------------------------------------------------------
    Purpose:
        List the context-budget.json files to try, in order, from plan-tiers.json.

    Inputs:
        tiers_path (Path): the tier file.

    Outputs:
        candidates (list[Path]): a leading ~ is the home directory, a relative path is
        resolved from the folder holding the tier file.

    Raises:
        PlanError: the entry is missing or not a list.
    --------------------------------------------------------------------------
    """
    item = _read_json(tiers_path).get("budget_candidates")
    if not isinstance(item, dict) or not isinstance(item.get("value"), list):
        raise PlanError(f"{Path(tiers_path).name} declares no budget_candidates list")
    base = Path(tiers_path).resolve().parent
    return [(base / Path(c).expanduser()).resolve() if not Path(c).expanduser().is_absolute()
            else Path(c).expanduser() for c in item["value"]]


def load_budget(candidates: list[Path]) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the size ceilings from the first candidate budget file that exists.

    Inputs:
        candidates (list[Path]): context-budget.json paths, tried in order.

    Outputs:
        ceilings (dict): {spec.md, plan.md, progress.md, audit.md, code_file} as ints.

    Raises:
        PlanError: no candidate exists (every one is named), or a ceiling is missing or not a
        positive integer, naming the key and the file (R3).
    --------------------------------------------------------------------------
    """
    for candidate in candidates:
        if not Path(candidate).is_file():
            continue
        block = _read_json(candidate).get("ceilings")
        out = {}
        for key in CEILING_KEYS:
            value = block.get(key) if isinstance(block, dict) else None
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise PlanError(f"{candidate} declares no usable ceilings.{key}")
            out[key] = value
        return out
    raise PlanError("no context-budget.json found; tried: "
                    + ", ".join(str(c) for c in candidates))


def repository_roots(cwd: Path) -> list[Path]:
    """
    --------------------------------------------------------------------------
    Purpose:
        The directories a plan may live in: the current worktree and the main clone.

    Inputs:
        cwd (Path): any directory inside the repository.

    Outputs:
        roots (list[Path]): resolved, without duplicates, empty outside a repository.
    --------------------------------------------------------------------------
    """
    config = loop_bounds.load_config()
    roots: list[Path] = []
    top = loop_bounds.git_output(Path(cwd), ["rev-parse", "--show-toplevel"], config)
    common = loop_bounds.git_output(
        Path(cwd), ["rev-parse", "--path-format=absolute", "--git-common-dir"], config)
    if top:
        roots.append(Path(top).resolve())
    if common and Path(common).name == ".git":
        roots.append(Path(common).parent.resolve())
    return list(dict.fromkeys(roots))


def _within(path: Path, roots: list[Path]) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Containment test on resolved paths, never on strings (R24).

    Inputs:
        path (Path): a resolved path.
        roots (list[Path]): resolved allowed roots.

    Outputs:
        inside (bool): True when path is a root or below one.
    --------------------------------------------------------------------------
    """
    return any(path == root or root in path.parents for root in roots)


def _check_header(header: dict, tiers: dict) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Check a parsed header against the contract and normalise it.

    Inputs:
        header (dict): from parse_header.
        tiers (dict): from load_tiers.

    Outputs:
        normalised (dict): {"executor", "tier", "bounds": {three ints}}.

    Raises:
        PlanError: an unknown or missing key, an unknown executor or tier, a bound that is
        not a positive int (a bool is refused), each naming the key.
    --------------------------------------------------------------------------
    """
    for key in header:
        if key not in HEADER_KEYS:
            raise PlanError(f"unknown front matter key '{key}'; allowed: {', '.join(HEADER_KEYS)}")
    for key in HEADER_KEYS:
        if key not in header:
            raise PlanError(f"front matter is missing the key '{key}'")
    # A list or mapping is unhashable: it must be a refusal here, not a TypeError the dispatch
    # guard would read as "not my business" (fail open).
    if not isinstance(header["executor"], str) or header["executor"] not in EXECUTORS:
        raise PlanError(f"executor must be one of {', '.join(EXECUTORS)}, got {header['executor']!r}")
    if not isinstance(header["tier"], str) or header["tier"] not in tiers:
        raise PlanError(f"tier must be one of {', '.join(tiers)}, got {header['tier']!r}")
    bounds = header["bounds"]
    if not isinstance(bounds, dict):
        raise PlanError("bounds must be a mapping of max_rounds, max_tokens and plateau")
    for key in bounds:
        if key not in BOUND_KEYS:
            raise PlanError(f"unknown bound '{key}'; allowed: {', '.join(BOUND_KEYS)}")
    checked = {}
    for key in BOUND_KEYS:
        value = bounds.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise PlanError(f"bounds.{key} must be a positive integer, got {value!r}")
        checked[key] = value
    return {"executor": header["executor"], "tier": header["tier"], "bounds": checked}


def _check_ceilings(plan: Path, ceilings: dict, counter: Callable, margin: float) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Enforce the size ceilings on the plan and on the spec, progress and audit files that
        sit in the same folder.

    Inputs:
        plan (Path): the plan file.
        ceilings (dict): from load_budget.
        counter (Callable): text -> TokenCount.
        margin (float): factor applied to an estimate before comparison.

    Outputs:
        None.

    Raises:
        PlanError: a file over its ceiling, naming file, count, method, whether it was an
        estimate, and the ceiling; or a ceiling key absent from the dict.
    --------------------------------------------------------------------------
    """
    targets = [(plan, "plan.md")]
    for name in ("spec.md", "progress.md", "audit.md"):
        if (plan.parent / name).is_file():
            targets.append((plan.parent / name, name))
    for path, key in targets:
        if key not in ceilings:
            raise PlanError(f"the budget declares no ceiling for {key}")
        count = counter(path.read_text(encoding="utf-8", errors="replace"))
        if not token_count.within_ceiling(count, ceilings[key], margin):
            kind = "exact" if count.exact else f"an estimate, times {margin}"
            raise PlanError(f"{path.name} is {count.tokens} tokens ({count.method}, {kind}), "
                            f"over its ceiling of {ceilings[key]}")


def validate(plan: Path, repo_root: Path | list[Path], tiers: dict, *,
             ceilings: dict | None = None, counter: Callable | None = None,
             margin: float | None = None) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Validate one plan file against the contract.

    Details:
        With ceilings None the size ceilings are not checked (a caller that only needs the
        header, such as loop_bounds init --from-plan, passes none); every other check runs.

    Inputs:
        plan (Path): the plan file.
        repo_root (Path | list[Path]): allowed root or roots; the plan must resolve inside one.
        tiers (dict): from load_tiers.
        ceilings (dict | None): from load_budget.
        counter (Callable | None): text -> TokenCount, token_count.count_text by default.
        margin (float | None): estimate margin, taken from token-count.json when omitted.

    Outputs:
        header (dict): {"plan", "executor", "tier", "bounds", "files"}.

    Raises:
        PlanError: any breach of the contract, naming the key or file.
    --------------------------------------------------------------------------
    """
    roots = [Path(r).resolve() for r in (repo_root if isinstance(repo_root, list) else [repo_root])]
    path = Path(plan).resolve()
    if not _within(path, roots):
        raise PlanError(f"{plan} resolves outside the repository ({', '.join(map(str, roots))})")
    if not path.is_file():
        raise PlanError(f"plan not found: {plan}")
    text = path.read_text(encoding="utf-8", errors="replace")
    header = _check_header(parse_header(text), tiers)
    files = set()
    for line in text.split("\n"):
        found = FILE_LINE.match(line)
        if not found:
            continue
        # An unquoted token is a file only when it looks like a path (has an extension);
        # prose such as `- Test: run the suite` is not, and trailing punctuation is not part
        # of a path.
        name = found.group(1) or found.group(2).rstrip(",;:.")
        if found.group(1) or re.fullmatch(r"[\w./\\-]*\w\.\w+", name):
            files.add(name)
    if not files:
        raise PlanError("the plan names no file: list each as `- Create: path`, `- Modify: path` "
                        "or `- Test: path`, otherwise the file limit of its tier cannot be checked")
    limit = tiers[header["tier"]]["max_files"]
    if len(files) > limit:
        raise PlanError(f"the plan names {len(files)} files, over the {limit} allowed for tier "
                        f"{header['tier']}")
    if ceilings is not None:
        config = token_count.load_config()
        if counter is None:
            # ONE encoder load for every file counted: a stalled download then costs a single
            # timeout, not one per file (R35 round 4).
            encoder, reason = token_count._load_encoder(token_count.config_value(config, "encoding"))
            if encoder is not None:
                counter = lambda t: token_count.count_text(t, encoder=encoder, config=config)  # noqa: E731
            else:
                def counter(t):
                    found = token_count.count_text(t, "chars", config=config)
                    return found._replace(note=f"estimate, not exact ({reason})")
        _check_ceilings(path, ceilings, counter,
                        margin if margin is not None
                        else token_count.config_value(config, "estimate_margin"))
    return {"plan": str(path), **header, "files": len(files)}


def resolve(header: dict, tiers: dict, resolver: Callable[[str], str]) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Turn a validated header into the executor that will actually run.

    Details:
        Only `local-coder` asks the resolver, once, with the tier's own role. A refusal gives
        the `cloud` executor with the resolver's own reason and never another role (R8).

    Inputs:
        header (dict): from validate.
        tiers (dict): from load_tiers.
        resolver (Callable): role -> tag, raising RoleUnavailable or RuntimeError to refuse.

    Outputs:
        result (dict): {executor, tier, role, tag, fallback, reason}.
    --------------------------------------------------------------------------
    """
    role = tiers[header["tier"]]["role"]
    base = {"executor": header["executor"], "tier": header["tier"], "role": role,
            "tag": None, "fallback": False, "reason": None}
    if header["executor"] != "local-coder":
        return base
    try:
        base["tag"] = resolver(role)
    except (RoleUnavailable, RuntimeError) as exc:
        return {**base, "executor": "cloud", "fallback": True, "reason": str(exc)}
    return base


def default_resolver(role: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Ask model_resolver for the qualified tag of a role, never falling back to another.

    Inputs:
        role (str): the resolver role.

    Outputs:
        tag (str): the tag the resolver names.

    Raises:
        RoleUnavailable: the resolver refuses, with its reason.
    --------------------------------------------------------------------------
    """
    import model_resolver  # noqa: PLC0415 - heavy, only needed to resolve

    try:
        return model_resolver.resolve(role, require_role=True)
    except model_resolver.ResolverError as exc:
        raise RoleUnavailable(str(exc)) from exc


def _build_parser() -> argparse.ArgumentParser:
    """
    --------------------------------------------------------------------------
    Purpose:
        Declare the CLI: validate and resolve.

    Inputs:
        None.

    Outputs:
        parser (argparse.ArgumentParser): the configured parser.
    --------------------------------------------------------------------------
    """
    parser = argparse.ArgumentParser(description="Plan contract: validate and resolve.")
    parser.add_argument("verb", choices=("validate", "resolve"))
    parser.add_argument("plan")
    parser.add_argument("--repo-root", action="append", default=[], type=Path,
                        help="allowed root, repeatable; default the worktree and main clone")
    parser.add_argument("--tiers", type=Path, default=TIERS_PATH)
    parser.add_argument("--budget", action="append", default=[], type=Path,
                        help="context-budget.json candidate, repeatable")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None, *,
         resolver: Callable[[str], str] | None = None) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Command-line entry point: validate a plan, or validate then resolve it.

    Inputs:
        argv (list[str] | None): arguments, sys.argv[1:] when omitted.
        resolver (Callable | None): replacement for default_resolver, for tests.

    Outputs:
        exit_code (int): 0 ok, 2 contract refusal, 1 unreadable configuration. The report is
        printed on stdout, as JSON with --json.
    --------------------------------------------------------------------------
    """
    args = _build_parser().parse_args(argv)
    report: dict[str, Any] = {}
    try:
        tiers = load_tiers(args.tiers)
        ceilings = load_budget(args.budget or budget_candidates(args.tiers))
        roots = args.repo_root or repository_roots(Path.cwd()) or [Path.cwd()]
    except (OSError, PlanError, ValueError) as exc:
        report["error"] = f"configuration problem: {exc}"
        _emit(report, args.json)
        return 1
    try:
        header = validate(Path(args.plan), roots, tiers, ceilings=ceilings)
        report.update(header)
        if args.verb == "resolve":
            report.update(resolve(header, tiers, resolver or default_resolver))
    except PlanError as exc:
        report["error"] = str(exc)
        _emit(report, args.json)
        return 2
    _emit(report, args.json)
    return 0


def _emit(report: dict, as_json: bool) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Print a report, as JSON or as one readable line.

    Inputs:
        report (dict): the report.
        as_json (bool): JSON when True.

    Outputs:
        None. Side effect: one print on stdout.
    --------------------------------------------------------------------------
    """
    if as_json:
        print(json.dumps(report, sort_keys=True))
    else:
        print(report.get("error") or " ".join(f"{k}={v}" for k, v in report.items()))


if __name__ == "__main__":
    sys.exit(main())
