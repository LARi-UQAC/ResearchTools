"""
local-coder-dispatch-guard.py - PreToolUse gate on the Agent tool that refuses a `local-coder`
dispatch with no valid plan (local coding contract, plan 3, decision D1: one plan is one
dispatch, tracked in progress.md).

A dispatch prompt must carry a line `PLAN: <path>` naming a plan file. The plan must satisfy the
contract of `plan_contract.py` (skill loop-engineer): a header with `executor`, `tier` and the
three review bounds, the tier's file limit, the size ceilings of `context-budget.json`, a path
inside the repository (the worktree or its main clone, resolved before it is compared, R24). The
executor must be `local-coder`, and the aider kit must be present (the folder `kit_dir` of the
configuration holds every file of `kit_files`), because dispatching a local agent with no kit
only wastes the Haiku wrapper. The resolver is no longer asked for a role.

WHAT IT CANNOT DO: it reads the prompt text, so a prompt that names a valid plan but asks for
something else passes, and an Agent call that omits the dispatch tool altogether is not seen.
It judges the plan's form, not what the plan asks for.

EXIT CODES (R12): 0 allow, OR the gate is disabled, OR the call is not ours to judge, OR a
dependency is missing; 2 refusal by design with the reason and the fix on stderr. Every failure
path returns 0 and prints nothing (R11, the 2026-08-27 incident): a missing or broken config, a
missing plan_contract module or tier table, a malformed payload, an unexpected exception. A
missing context-budget.json skips the size ceilings only and the header is still judged.

DOCUMENTED (Claude Code docs "Hooks", fetched 2026-10-17): the matcher for this tool is `Agent`,
tool_input carries `subagent_type` and `prompt`, exit 2 blocks.
NOT VERIFIED (R15): a live firing on this machine, which plan 11 checks.
"""

import importlib.util
import json
import os
import sys
from pathlib import Path

CONFIG_NAME = "local-coder-dispatch-guard.json"
TOOL_NAME = "Agent"
TAG = "[LOCAL-CODER DISPATCH GUARD] "


def read_config(hook_dir):
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the gate's settings from the JSON beside the hook.

    Inputs:
        hook_dir (str): folder holding the hook and its config

    Outputs:
        config (dict | None): the settings, or None when the gate is disabled or the file is
        missing, unreadable or incomplete (R11).
    --------------------------------------------------------------------------
    """
    try:
        with open(os.path.join(hook_dir, CONFIG_NAME), encoding="utf-8-sig") as handle:
            raw = json.load(handle)
        if raw["enabled"]["value"] is not True:
            return None
        config = {
            "agents": {str(a) for a in raw["guarded_agents"]["value"]},
            "prefix": str(raw["plan_line_prefix"]["value"]),
            "contract": list(raw["plan_contract_candidates"]["value"]),
            "tiers": list(raw["tiers_candidates"]["value"]),
            "kit_dir": os.path.expanduser(str(raw["kit_dir"]["value"])),
            "kit_files": list(raw["kit_files"]["value"]),
        }
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return config if config["prefix"] else None


def first_existing(candidates, hook_dir):
    """
    --------------------------------------------------------------------------
    Purpose:
        Pick the first candidate path that exists.

    Inputs:
        candidates (list[str]): a leading ~ is the home directory, a relative path is resolved
        from the hook's folder
        hook_dir (str): folder holding the hook

    Outputs:
        path (str | None): the first existing file, or None.
    --------------------------------------------------------------------------
    """
    for candidate in candidates:
        path = os.path.expanduser(str(candidate))
        if not os.path.isabs(path):
            path = os.path.normpath(os.path.join(hook_dir, path))
        if os.path.isfile(path):
            return path
    return None


def load_module(path, name):
    """
    --------------------------------------------------------------------------
    Purpose:
        Import a python file by path.

    Inputs:
        path (str): the file
        name (str): the module name to register it under

    Outputs:
        module (module | None): the module, or None when it cannot be loaded.
    --------------------------------------------------------------------------
    """
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:  # noqa: BLE001 - a broken dependency disables the gate, never refuses
        return None


def plan_line(prompt, prefix):
    """
    --------------------------------------------------------------------------
    Purpose:
        Find the plan path a dispatch prompt names.

    Inputs:
        prompt (object): the prompt text
        prefix (str): the line prefix, for example PLAN:

    Outputs:
        path (str | None): the text after the prefix of the first line carrying it, with
        surrounding quotes or backticks removed, or None.
    --------------------------------------------------------------------------
    """
    if not isinstance(prompt, str):
        return None
    for line in prompt.splitlines():
        if line.strip().startswith(prefix):
            value = line.strip()[len(prefix):].strip().strip("`'\"")
            return value or None
    return None


def kit_missing(kit_dir: Path, required: list[str]) -> str | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Check if the aider kit is present and complete.

    Inputs:
        kit_dir (Path): the directory of the aider kit
        required (list[str]): list of file paths relative to kit_dir that must exist

    Outputs:
        str | None: None if all files exist, otherwise a refusal message naming the first missing file.
    --------------------------------------------------------------------------
    """
    for rel in required:
        if not (kit_dir / rel).is_file():
            return f"the aider kit is missing {rel}; the aider-setup skill is not installed."
    return None


def judge(payload, config, contract, tiers_path):
    """
    --------------------------------------------------------------------------
    Purpose:
        Judge one guarded dispatch.

    Inputs:
        payload (dict): the parsed stdin JSON
        config (dict): from read_config
        contract (module): plan_contract
        tiers_path (str): the tier table

    Outputs:
        reason (str | None): the refusal text, or None to allow.
    --------------------------------------------------------------------------
    """
    cwd = Path(payload["cwd"] if isinstance(payload.get("cwd"), str) else os.getcwd())
    named = plan_line(payload["tool_input"].get("prompt"), config["prefix"])
    if named is None:
        return (f"a local-coder dispatch must name its plan. Add a line "
                f"`{config['prefix']} <path to planN.md>` to the prompt; the plan needs the "
                "header executor, tier and bounds (see skill loop-engineer, plan_contract.py).")
    plan = Path(os.path.expanduser(named))
    plan = plan if plan.is_absolute() else cwd / plan
    tiers = contract.load_tiers(Path(tiers_path))
    try:
        ceilings = contract.load_budget(contract.budget_candidates(Path(tiers_path)))
    except (OSError, contract.PlanError):
        ceilings = None
    roots = contract.repository_roots(cwd) or [cwd]
    try:
        header = contract.validate(plan, roots, tiers, ceilings=ceilings)
    except contract.PlanError as exc:
        return f"the plan breaks the contract: {exc}"
    if header["executor"] != "local-coder":
        return (f"the plan names executor {header['executor']}, so it is not a local-coder "
                "plan. Run it with its own executor, or change the header.")
    
    missing = kit_missing(Path(config["kit_dir"]), config["kit_files"])
    if missing:
        return missing
    return None


def main():
    """
    --------------------------------------------------------------------------
    Purpose:
        Hook entry point: read the payload on stdin, exit 0 or 2.

    Inputs:
        None (stdin carries the PreToolUse JSON).

    Outputs:
        None. Calls sys.exit(0) to allow or sys.exit(2) with the reason on stderr.
    --------------------------------------------------------------------------
    """
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict) or payload.get("tool_name") != TOOL_NAME:
            sys.exit(0)
        tool_input = payload.get("tool_input")
        hook_dir = os.path.dirname(os.path.abspath(__file__))
        config = read_config(hook_dir)
        if (config is None or not isinstance(tool_input, dict)
                or tool_input.get("subagent_type") not in config["agents"]):
            sys.exit(0)
        contract_path = first_existing(config["contract"], hook_dir)
        tiers_path = first_existing(config["tiers"], hook_dir)
        if contract_path is None or tiers_path is None:
            sys.exit(0)
        contract = load_module(contract_path, "plan_contract_for_guard")
        if contract is None:
            sys.exit(0)
        reason = judge(payload, config, contract, tiers_path)
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 - R11: a bug here must never refuse a tool
        sys.exit(0)
    if reason:
        sys.stderr.write(TAG + reason + "\n")
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
