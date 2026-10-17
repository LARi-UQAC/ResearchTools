"""
review-loop-guard.py - PreToolUse gate on the Skill tool that stops a review loop at the bounds
the owner declared (R35 as amended by the local coding contract, plan 2).

R35 once repeated /code-review and /security-review "until no finding" with no maximum, and
nothing enforced a stop: 7 unbounded iterations were measured on 2026-10-17. This hook refuses a
guarded review skill when the branch has no declared bounds, or when a bound is spent. The
bounds and the decision live in `loop_bounds.py` (skill loop-engineer); this file only reads the
payload, asks it, and exits.

WHAT IT GUARDS: the skills listed in review-loop-guard.json `guarded_skills`, invoked through the
Skill tool. A refused call exits 2 and writes the reason, with the command to run, on stderr. An
allowed call counts one round for that skill and saves the state; a refused call never does. The
first allowed call after `init` also adopts the payload's `transcript_path` as the token baseline
when `init` was given none, because the session does not know its own transcript path.

WHAT IT CANNOT GUARD: a user who edits the state file, a skill run some other way than the Skill
tool, and a review typed as a slash command if Claude Code expands it without a Skill tool call.
`init --max-rounds 1` is the documented one-shot for that case.

EXIT CODES (R12): 0 allow, OR the gate is disabled, OR the call is not ours to judge, OR any
dependency is missing; 2 refusal by design. Every failure path returns 0 and prints nothing
(R11, the 2026-08-27 incident: a declared hook whose script was missing refused nine tools for
four turns): a missing or broken config, no git, a repository that git does not answer for, a
missing loop_bounds module, a malformed payload, an unexpected exception.

DOCUMENTED (Claude Code docs "Hooks", fetched 2026-10-17): the matcher name for this tool is
`Skill`, the stdin payload carries tool_name, tool_input, cwd and transcript_path, and exit code
2 blocks a PreToolUse call with stderr as the error.
NOT VERIFIED (R15): the key holding the skill name inside tool_input is not documented. This
hook reads `skill` and falls back to `name`. A live firing on this machine is plan 11's job.
"""

import importlib.util
import json
import os
import sys
from pathlib import Path

CONFIG_NAME = "review-loop-guard.json"
TOOL_NAME = "Skill"
NAME_KEYS = ("skill", "name")


def read_config(hook_dir):
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the gate's settings from the JSON beside the hook.

    Inputs:
        hook_dir (str): folder holding the hook and its config

    Outputs:
        config (dict | None): {"guarded": set, "candidates": list}, or None when the gate is
        disabled or the file is missing, unreadable or incomplete (R11).
    --------------------------------------------------------------------------
    """
    try:
        with open(os.path.join(hook_dir, CONFIG_NAME), encoding="utf-8-sig") as handle:
            raw = json.load(handle)
        if raw["enabled"]["value"] is not True:
            return None
        guarded = raw["guarded_skills"]["value"]
        candidates = raw["loop_bounds_candidates"]["value"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(guarded, list) or not isinstance(candidates, list):
        return None
    return {"guarded": {str(s).lstrip("/") for s in guarded}, "candidates": candidates}


def load_engine(candidates, hook_dir):
    """
    --------------------------------------------------------------------------
    Purpose:
        Import loop_bounds.py by path from the first candidate that exists.

    Inputs:
        candidates (list[str]): paths; a leading ~ is the home directory and a relative path
        is resolved from the hook's own folder
        hook_dir (str): folder holding the hook

    Outputs:
        module (module | None): the engine, or None when no candidate exists or loads.
    --------------------------------------------------------------------------
    """
    for candidate in candidates:
        path = os.path.expanduser(str(candidate))
        if not os.path.isabs(path):
            path = os.path.normpath(os.path.join(hook_dir, path))
        if not os.path.isfile(path):
            continue
        try:
            spec = importlib.util.spec_from_file_location("loop_bounds_for_guard", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        except Exception:  # noqa: BLE001 - a broken engine must disable the gate, not refuse
            return None
    return None


def skill_name(payload):
    """
    --------------------------------------------------------------------------
    Purpose:
        Extract the invoked skill's name from a PreToolUse payload for the Skill tool.

    Inputs:
        payload (object): the parsed stdin JSON

    Outputs:
        name (str | None): the name without a leading slash, or None when this is not a
        well-formed Skill call.
    --------------------------------------------------------------------------
    """
    if not isinstance(payload, dict) or payload.get("tool_name") != TOOL_NAME:
        return None
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    for key in NAME_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lstrip("/")
    return None


def adopt_transcript(engine, state, transcript_path):
    """
    --------------------------------------------------------------------------
    Purpose:
        Give a state that was initialised without a transcript the payload's one as the token
        baseline, so the budget can be measured from the first round on.

    Inputs:
        engine (module): loop_bounds
        state (dict): the branch state, modified in place
        transcript_path (object): the payload's transcript_path

    Outputs:
        None. Side effect: state["transcript"] and ["transcript_offset"] set when the state had
        none and the file exists.
    --------------------------------------------------------------------------
    """
    if state.get("transcript") or not isinstance(transcript_path, str):
        return
    try:
        offset = os.path.getsize(transcript_path)
    except OSError:
        return
    state["transcript"], state["transcript_offset"] = transcript_path, offset


def judge(payload, config, engine):
    """
    --------------------------------------------------------------------------
    Purpose:
        Decide one Skill call and, when it is allowed, count the round.

    Inputs:
        payload (dict): the parsed stdin JSON
        config (dict): from read_config
        engine (module): loop_bounds

    Outputs:
        reason (str | None): the refusal text, or None to allow.
    --------------------------------------------------------------------------
    """
    skill = skill_name(payload)
    if skill is None or skill not in config["guarded"]:
        return None
    cwd = Path(payload["cwd"] if isinstance(payload.get("cwd"), str) else os.getcwd())
    bounds_config = engine.load_config()
    path = engine.state_path(cwd, config=bounds_config)
    branch = engine.current_branch(cwd, config=bounds_config)
    if path is None or branch is None:
        return None
    state = engine.load_state(path, branch)
    tokens = engine.tokens_used(state, bounds_config) if state else None
    allowed, reason = engine.decide(state, skill, tokens)
    if not allowed:
        return "[REVIEW LOOP GUARD] " + reason
    adopt_transcript(engine, state, payload.get("transcript_path"))
    engine.record_invocation(state, skill)
    engine.save_state(path, branch, state)
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
        hook_dir = os.path.dirname(os.path.abspath(__file__))
        config = read_config(hook_dir)
        if config is None or skill_name(payload) not in config["guarded"]:
            sys.exit(0)
        engine = load_engine(config["candidates"], hook_dir)
        if engine is None:
            sys.exit(0)
        reason = judge(payload, config, engine)
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 - R11: a bug here must never refuse a tool
        sys.exit(0)
    if reason:
        sys.stderr.write(reason + "\n")
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
