"""
model_resolver.py - the model resolver for the deterministic Ollama bridge (P4 Task 3).

A model is never adopted because it is new. It is adopted because it beat the incumbent on
a frozen task set drawn from this repository (qualification/tasks.json). This module is the
ONLY writer of .claude/local-model-state.json, and ollama_bridge.py's resolve_model() is the
ONLY caller of this module's resolve() (see ollama_bridge.py, function resolve_model, for the
seam: it does `import model_resolver` then `model_resolver.resolve()`).

Ruling on the file name: the plan's own File Structure calls this resolve_model.py, but
ollama_bridge.py (closed, mutation-tested) already does `import model_resolver` followed by
`model_resolver.resolve()`. Renaming an import inside verified code for a cosmetic reason is
the wrong trade, so this module is named model_resolver.py instead, next to the bridge in the
same scripts/ directory.

Three CLI verbs, one library function:
  --list              installed models ('ollama list') cross-referenced against the declared
                       candidates in local-models.json; prints eligible/ineligible plus the
                       REASON for every ineligible entry.
  --resolve            prints exactly one tag on stdout, no decoration, so it is usable in a
                       shell substitution ($(...) or backticks).
  --qualify <tag>      runs the frozen task set (qualification/tasks.json) against <tag> and
                       adopts it into local-model-state.json ONLY if it beats the incumbent's
                       last recorded score. A loss changes nothing and exits non-zero.
  --role <kind>        modifier for --resolve and --qualify (P4). With --resolve, prints the
                       tag adopted for that role. With --qualify, runs only that role's slice
                       of the frozen set and adopts the winner for that role alone.
  resolve() -> str      the library seam ollama_bridge.py calls. Checks the LARI_LOCAL_MODEL
                       environment override first (forces a tag WITHOUT touching the state
                       file - useful for a one-off manual run, and it is how
                       run_qualification_tasks itself forces a candidate during --qualify,
                       so qualification never depends on, or mutates, the very state it might
                       update); otherwise reads local-model-state.json's "current" tag. A
                       missing or empty state file is an EXPLICIT ResolverError, never a
                       silent default: an unattended loop that silently fell back to a weaker
                       model once is exactly the defect (D7 in ollama_bridge.py) this plan
                       removes, and a resolver that guesses when its own bookkeeping is absent
                       would reintroduce the same shape of bug one layer up.

No hardcoded model tag anywhere in this file. Every tag this module ever returns or compares
comes from one of three data sources: the LARI_LOCAL_MODEL environment variable, the declared
candidates in local-models.json, or local-model-state.json. The ONE deliberate named-tag
exception in the whole P4 plan is not in this file: it is the seeding action described in the
plan (Step 5) and recorded as DATA in local-models.json's "notes" field for ornith:9b-gpu -
the GPU-tuned variant already built in P4 Task 1/2 from Modelfile.ornith-9b-gpu (FROM
ornith:9b, num_ctx 8192, num_gpu 99). The Modelfile keeps its FROM tag; local-model-state.json
records which variant was actually qualified from it.

Writer versus coder qualification (see qualification/tasks.json's own header for the fuller
statement): a coder task is graded by a real assertion against real behaviour - an executable
oracle. A writer task has no such oracle for whether the prose is GOOD; it can only be gated
on deterministic, mechanical properties (hygiene - already enforced by ollama_bridge.run_bridge
before a body is ever written to a target file - plus structure, language, length, and
frontmatter keys, all checked here). Passing every writer task proves the candidate follows
format instructions, not that its prose is good. This is weaker evidence than a coder win, and
is stated again in tasks.json's own header so a reader of --qualify's own output is not the
only place that caveat lives.

Structure-gate pitfall (measured earlier in this plan): a FIXED five-heading gate wrongly
failed a good generation whose brief had deliberately asked for two sections only. The writer
check built by _build_writer_verify_command therefore reads required_sections from the TASK
ITSELF (qualification/tasks.json), never from a constant list in this file - see that
function's docstring.

Standard library only: argparse, datetime, json, logging, os, re, subprocess, sys, tempfile,
pathlib, typing. ollama_bridge is imported LAZILY, only inside run_qualification_tasks, so
--list and --resolve (used constantly, and expected to be fast and low-dependency) never pay
for importing it. ollama_bridge.py is stdlib-only itself, so this stays within the stdlib-only
constraint either way.

Fix round 1 (adversarial review; each numbered finding addressed at its implementation):
  F1 CRITICAL, phantom tag - resolve() never checked the installed inventory: a state file
      naming an uninstalled tag, or a LARI_LOCAL_MODEL override naming one, was handed to the
      bridge unchecked, which is exactly the silent-failure shape this module exists to
      prevent (the daemon would then answer with an opaque transport error instead of this
      module's own explicit refusal). Fixed by _verify_installed(), called on BOTH paths
      inside resolve() (see that function).
  F2 IMPORTANT, dead policy - local-models.json's "policy" object (qualification_mode,
      require_declared, require_installed, win_rule, bootstrap_rule) was declared but never
      read; cmd_qualify hardcoded the behaviour instead. All five fields are now read by
      _load_policy() and genuinely drive cmd_qualify: qualification_mode and win_rule are
      checked against a supported-values set and refuse explicitly on an unrecognised value
      (_SUPPORTED_QUALIFICATION_MODES, _WIN_RULES); require_declared and require_installed
      gate their respective checks; bootstrap_rule gates whether a missing incumbent may be
      seeded. local-models.json's *_description companion fields are documentation only, kept
      separate from the enforced bare keys so a reader cannot mistake prose for policy.
  F3 IMPORTANT, summed win rule - the old rule summed coder and writer passes into one
      scalar, so a challenger could win by gaining in one role while regressing the other (the
      seeded incumbent's own 3/6 - all 3 writer tasks passed, all 3 coder tasks failed - makes
      this concrete: a challenger flipping that split would have tied or beaten the old scalar
      while making the coder role strictly worse). Fixed at the RULE level, not the structure:
      _win_rule_no_regression_strict_gain requires no regression in ANY role and a strict gain
      in at least one (see run_qualification_tasks's new "by_kind" breakdown and
      _write_state's "score.by_kind"). The limitation this finding recorded as out of scope -
      one `current` tag serving BOTH roles - was closed by P4 below.
  F4 IMPORTANT, loose language gate - three-of-twelve substring-padded marker hits could
      false-PASS English prose containing a stray French word or two, which is the dangerous
      direction (a false PASS adopts a worse model; the heading regex's false-FAIL direction
      was judged already safe and left alone). Tightened to three conjoined thresholds: a
      larger marker set counted by word boundary (not substring padding), a minimum count of
      French-accented Latin characters, and a minimum accented-character DENSITY (accents per
      character of body), so a long English document diluted with one or two accented loan
      words cannot clear the density leg. See the writer-check source, "if params['language']".
  F5 MINOR, non-atomic write - _write_state wrote STATE_PATH directly; a crash mid-write
      would leave the one file this module writes corrupt, and an unreadable state file is a
      hard stop for every later run by this module's own design. Fixed: write to a sibling
      ".tmp" file, then os.replace() over STATE_PATH (atomic on both POSIX and Windows).

Fix round 2, item 1: F4's three thresholds still false-PASSed English idiom-stacking (a
string built entirely of French noun phrases borrowed whole into English - "creme de la
creme", "au contraire", "du coup", "coup de grace", "de facto" - cleared marker_hits and, in
the reviewer's own environment, the accent thresholds too). Added a FOURTH, additive
requirement: a minimum number of DISTINCT hits from a smaller function_words list (les, des,
est, qui, dans, pour, avec, sont, cette, nous, plus, sur) that specifically targets
clause-level grammar (a verb, a relative pronoun, a preposition anchoring a verb phrase) -
words a borrowed noun-phrase idiom structurally lacks, unlike the articles/prepositions that
DO ride along inside the borrowed phrase itself. See the writer-check source's own comment
block for the threshold (2) and why it is a judgment call, not a measured constant.

P4 (open-items pass, 2026-08-14), per-role current tag: `current` no longer decides which
model every role gets. local-model-state.json carries a "current_by_role" map
(role -> {tag, passed, total, adopted}) that resolve(role) reads, ollama_bridge passes
through from its own --role flag, and `--qualify <tag> --role <kind>` contests one role at a
time. The concrete defect: the seeded incumbent passes 3/3 writer tasks and 0/3 coder tasks,
and local-coder was being handed that same writer model, because neither resolve() nor the
bridge could express "the coder one". A coder-specialised challenger could never fix that
under the overall win rule either, since it cannot beat a writer model at writer tasks. A
role with no adopted tag falls back to `current`, which is the pre-P4 behaviour and therefore
never a downgrade. A role run refuses to seed an empty state file: only a full qualification
may decide the global tag.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# .../loop-engineer/scripts/model_resolver.py
SCRIPTS_DIR = Path(__file__).resolve().parent
LOOP_ENGINEER_DIR = SCRIPTS_DIR.parent
CLAUDE_DIR = LOOP_ENGINEER_DIR.parent.parent
QUALIFICATION_DIR = LOOP_ENGINEER_DIR / "qualification"

# The three data files. Every one of these is a path, never a model tag, and every one is a
# module-level constant so a test can redirect it with unittest.mock.patch.object without
# touching the real repository files.
LOCAL_MODELS_PATH = CLAUDE_DIR / "local-models.json"
STATE_PATH = CLAUDE_DIR / "local-model-state.json"
# Written by optimize_ollama.py --sweep and by the opt-local-vram-llm skill. The resolver
# reads it only to break an exact tie: task passes measure code quality, this file measures
# what the card can actually hold, and the two answer different questions.
MODEL_CONFIG_PATH = CLAUDE_DIR / "local-model-config.json"
TASKS_PATH = QUALIFICATION_DIR / "tasks.json"

# Forces a tag without touching local-model-state.json (module docstring, resolve()).
ENV_OVERRIDE_VAR = "LARI_LOCAL_MODEL"

OLLAMA_LIST_TIMEOUT_S = 30.0

# P7 (open-items pass, 2026-08-14): the four thresholds of the writer tasks' French-language
# gate, in ONE place, injected into the generated check rather than written inside it.
#
# THESE ARE JUDGMENT CALLS, NOT MEASURED CONSTANTS. They were chosen against single worked
# examples during fix rounds 1 and 2 - one English paragraph carrying stray French tokens,
# one string of French idioms borrowed whole into English, one genuine French vault note -
# and not against a labelled corpus. Every one of them separates those examples correctly,
# which is evidence that they are not absurd, and nothing more than that.
#
# What each one guards, and the direction of its error:
#   min_marker_hits          6   raw French function-word occurrences. Too low false-PASSes
#                                English prose; too high false-FAILs a short French note.
#   min_accent_count         2   accented characters anywhere in the body. English text has
#                                near zero, so this is the cheap discriminator; a French
#                                text with fewer than two is possible but rare.
#   min_accent_density    0.01   accents per body character. This is what a LONG English
#                                document with a couple of loan words fails, where a raw
#                                count alone would pass it.
#   min_distinct_function_hits 2 DISTINCT clause-level function words. An English sentence
#                                stacking borrowed noun phrases hits zero; a real French
#                                clause hits two almost by construction.
#
# The false-PASS direction is the dangerous one: it adopts a worse model. A false FAIL only
# refuses a good candidate, which the operator sees immediately in the run output.
#
# To replace any of these with a MEASURED value, the honest procedure is a labelled corpus
# (genuine French notes from the vault, English prose, and the idiom-stacking adversarial
# shape), each threshold swept while the other three are held, reporting false-pass and
# false-fail counts at each step. Until that is run, they stay labelled as judgment.
# A single task may override any of them through a "language_thresholds" object in
# qualification/tasks.json, so a sweep needs no code edit.
LANGUAGE_GATE_THRESHOLDS = {
    "min_marker_hits": 6,
    "min_accent_count": 2,
    "min_accent_density": 0.01,
    "min_distinct_function_hits": 2,
}


class ResolverError(RuntimeError):
    """
    Raised on every resolver refusal: a missing or empty local-model-state.json, an
    undeclared or uninstalled --qualify target, a missing or empty local-models.json or
    qualification/tasks.json, or an unreachable/failing 'ollama list'. There is no silent
    fallback path anywhere in this module - every failure mode raises this instead of
    returning a guessed tag.
    """


def _ollama_list_raw() -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        The sole process boundary to the local Ollama inventory: runs
        'ollama list' and returns its raw stdout. Every test in
        test_model_resolver.py patches this function by name, so no test
        ever shells out to the real 'ollama' binary (the brief's own
        instruction: "Patch the inventory call").

    Inputs:
        none.

    Outputs:
        result (str): the raw stdout of 'ollama list' (header row plus one
        row per installed model).

    Raises:
        ResolverError: the 'ollama' binary is not on PATH, the call timed
        out, or it exited non-zero (daemon unreachable, etc.). Never falls
        back to an empty or cached inventory.
    --------------------------------------------------------------------------
    """
    try:
        proc = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=OLLAMA_LIST_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ResolverError(f"[RESOLVER] cannot run 'ollama list': {exc}") from exc
    if proc.returncode != 0:
        raise ResolverError(
            f"[RESOLVER] 'ollama list' exited {proc.returncode}: {proc.stderr.strip()}"
        )
    return proc.stdout


def list_installed_models() -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Parse the NAME column out of 'ollama list' output. The header row
        (whatever its exact wording) is skipped positionally: real 'ollama
        list' output prints exactly one header row before the model rows.

    Inputs:
        none.

    Outputs:
        result (list[str]): installed tags, in the order 'ollama list'
        printed them; empty when nothing is installed.
    --------------------------------------------------------------------------
    """
    raw = _ollama_list_raw()
    lines = raw.splitlines()
    names: list[str] = []
    for line in lines[1:]:
        parts = line.split()
        if parts:
            names.append(parts[0])
    return names


def _load_json_file(path: Path, empty_message: str, missing_message: str) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Shared strict JSON loader for the three data files: refuse a missing
        file, refuse an empty file, and refuse invalid JSON, each with an
        explicit message naming the path - never a silent default.

    Inputs:
        path (Path): the file to load.
        empty_message (str): message used when the file exists but is blank.
        missing_message (str): message used when the file does not exist.

    Outputs:
        result (dict): the parsed JSON document.

    Raises:
        ResolverError: missing, empty, or invalid JSON.
    --------------------------------------------------------------------------
    """
    if not path.exists():
        raise ResolverError(missing_message)
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        raise ResolverError(empty_message)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ResolverError(f"[RESOLVER] {path} is not valid JSON: {exc}") from exc


def _load_local_models() -> dict[str, dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Load the declared candidates from local-models.json, keyed by tag.

    Inputs:
        none.

    Outputs:
        result (dict[str, dict]): tag -> its candidate record (role, declared
        date, notes, ...); empty when the file declares no candidates.

    Raises:
        ResolverError: see _load_json_file.
    --------------------------------------------------------------------------
    """
    data = _load_json_file(
        LOCAL_MODELS_PATH,
        empty_message=f"[RESOLVER] candidate declaration file at {LOCAL_MODELS_PATH} is empty.",
        missing_message=f"[RESOLVER] no candidate declaration file at {LOCAL_MODELS_PATH}.",
    )
    by_tag: dict[str, dict[str, Any]] = {}
    for candidate in data.get("candidates", []):
        tag = candidate.get("tag")
        if tag:
            by_tag[tag] = candidate
    return by_tag


def _load_tasks() -> list[dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Load the frozen qualification task set.

    Inputs:
        none.

    Outputs:
        result (list[dict]): the "tasks" array.

    Raises:
        ResolverError: missing, empty, invalid JSON, or a "tasks" array that
        is present but empty.
    --------------------------------------------------------------------------
    """
    data = _load_json_file(
        TASKS_PATH,
        empty_message=f"[RESOLVER] frozen task set at {TASKS_PATH} is empty.",
        missing_message=f"[RESOLVER] no frozen task set at {TASKS_PATH}.",
    )
    tasks = data.get("tasks", [])
    if not tasks:
        raise ResolverError(f"[RESOLVER] frozen task set at {TASKS_PATH} declares no tasks.")
    return tasks


def _load_state_strict() -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Load local-model-state.json for resolve(): a missing file, an empty
        file, invalid JSON, or a file with no "current" tag are all explicit
        errors. This is the one place D7's "no silent fallback" rule is
        enforced for the resolver's own bookkeeping (test 6 of the brief).

    Inputs:
        none.

    Outputs:
        result (dict): the parsed state document, guaranteed to carry a
        truthy "current" key.

    Raises:
        ResolverError: missing, empty, invalid JSON, or no "current" tag.
    --------------------------------------------------------------------------
    """
    data = _load_json_file(
        STATE_PATH,
        empty_message=(
            f"[RESOLVER] state file at {STATE_PATH} is empty; run "
            "'model_resolver.py --qualify <tag>' first. Refusing to guess a default (D7)."
        ),
        missing_message=(
            f"[RESOLVER] no state file at {STATE_PATH}; run "
            "'model_resolver.py --qualify <tag>' first. Refusing to guess a default (D7)."
        ),
    )
    current = data.get("current")
    if not current:
        raise ResolverError(
            f"[RESOLVER] state file at {STATE_PATH} has no 'current' tag; run "
            "'model_resolver.py --qualify <tag>' first."
        )
    return data


def _load_state_for_qualify() -> dict[str, Any] | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Load local-model-state.json for --qualify, where a missing or empty
        file means "no incumbent yet" rather than an error: Step 5 of this
        plan (seed the state with the currently built variant) MUST be able
        to run before any state file exists. A file that exists, is
        non-empty, but is not valid JSON is still a hard error - a corrupt
        existing file is a different problem than a not-yet-seeded one.

    Inputs:
        none.

    Outputs:
        result (dict | None): the parsed state document, or None when there
        is no incumbent yet (missing or empty file).

    Raises:
        ResolverError: the file exists, is non-empty, and is not valid JSON.
    --------------------------------------------------------------------------
    """
    if not STATE_PATH.exists():
        return None
    raw = STATE_PATH.read_text(encoding="utf-8").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ResolverError(f"[RESOLVER] {STATE_PATH} is not valid JSON: {exc}") from exc


def _verify_installed(tag: str) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Fix round 1, F1 (CRITICAL): a resolved tag is worthless if it is not
        actually installed - the bridge would hand it to the daemon and the
        operator would get an opaque transport error instead of the explicit
        refusal this whole module exists to provide. Checked for BOTH
        resolve() paths (state-file "current" and the LARI_LOCAL_MODEL
        override), never for one only.

    Inputs:
        tag (str): the tag resolve() is about to return.

    Outputs:
        None.

    Raises:
        ResolverError: `tag` is absent from 'ollama list', naming the
        missing tag explicitly. Never lets a phantom tag through.
    --------------------------------------------------------------------------
    """
    installed = list_installed_models()
    if tag not in installed:
        raise ResolverError(
            f"[RESOLVER] resolved tag '{tag}' is not installed (absent from 'ollama list'); "
            "refusing to hand a phantom tag to the bridge rather than let it fail downstream "
            "with an opaque transport error (D7, fix round 1 F1)."
        )


def resolve(role: str | None = None) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        The library seam ollama_bridge.py's resolve_model() calls
        (`model_resolver.resolve(role)`). Checks LARI_LOCAL_MODEL first
        (forces a tag WITHOUT touching local-model-state.json); otherwise
        returns the qualified tag from local-model-state.json - the one
        adopted for `role` when the state names one, and the overall
        "current" tag otherwise. Fix round 1 (F1): BOTH paths are
        additionally verified against the installed inventory before being
        returned - a tag that resolves but is not installed is exactly the
        phantom-tag failure this module exists to prevent, whether it came
        from the state file or from the override.

        P4 (open-items pass, 2026-08-14): `role` closes the limitation this
        module's own docstring recorded as out of scope for fix round 1.
        Until now one tag served BOTH roles, so the incumbent, a writer
        model scoring 0/3 on the coder tasks, was also handed to
        local-coder. A role with no adopted tag of its own falls back to
        "current", which is exactly the pre-P4 behaviour, so the fallback
        never returns a WEAKER model than the one that would have been
        returned before this parameter existed: it returns the same one.
        That is why the fallback is not a D7 silent downgrade.

    Inputs:
        role (str | None): task kind ("writer", "coder", ... - whatever
            qualification/tasks.json declares as a `kind`). None asks for
            the overall current tag, as before.

    Outputs:
        result (str): the resolved Ollama tag, guaranteed to be installed.

    Raises:
        ResolverError: no override is set AND the state file is missing,
        empty, invalid JSON, or has no 'current' tag; OR the resolved tag
        (from either path) is not installed. Never returns a guessed,
        default, or phantom tag.
    --------------------------------------------------------------------------
    """
    override = os.environ.get(ENV_OVERRIDE_VAR, "").strip()
    if override:
        _verify_installed(override)
        return override
    state = _load_state_strict()
    tag = state["current"]
    if role:
        entry = (state.get("current_by_role") or {}).get(role)
        if isinstance(entry, dict) and entry.get("tag"):
            tag = entry["tag"]
    _verify_installed(tag)
    return tag


def cmd_list() -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Implement --list: every installed tag ('ollama list') cross-
        referenced against the declared candidates in local-models.json.
        Prints one line per tag: the tag, eligible/ineligible, and for every
        ineligible tag the REASON (brief requirement).

    Inputs:
        none.

    Outputs:
        result (int): 0 (this command does not fail on ineligible entries -
        that is its normal, informative output, not an error).
    --------------------------------------------------------------------------
    """
    declared = _load_local_models()
    installed = list_installed_models()
    installed_set = set(installed)

    rows: list[tuple[str, bool, str]] = []
    for tag in installed:
        candidate = declared.get(tag)
        if candidate is None:
            rows.append((tag, False, "not declared as a candidate in local-models.json"))
        else:
            role = candidate.get("role", "role unspecified")
            rows.append((tag, True, f"declared candidate ({role})"))
    for tag, candidate in declared.items():
        if tag not in installed_set:
            role = candidate.get("role", "role unspecified")
            rows.append((tag, False, f"declared ({role}) but not installed ('ollama list' does not show it)"))

    for tag, eligible, reason in rows:
        status = "eligible" if eligible else "ineligible"
        print(f"{tag}\t{status}\t{reason}")
    return 0


def cmd_resolve(role: str | None = None) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Implement --resolve: print exactly one tag on stdout, no decoration,
        so `$(model_resolver.py --resolve)` in a shell is the tag alone.
        With --role, print the tag adopted for that role (P4).

    Inputs:
        role (str | None): task kind, or None for the overall current tag.

    Outputs:
        result (int): 0 on success, 1 on a ResolverError (message on
        stderr, nothing printed on stdout).
    --------------------------------------------------------------------------
    """
    tag = resolve(role)
    print(tag)
    return 0


def _run_one_task(bridge_module: Any, task: dict[str, Any], tmp_dir: Path) -> tuple[bool, str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Dispatch a single qualification task through the deterministic
        bridge (ollama_bridge.run_bridge), which already resolves the forced
        candidate tag (via LARI_LOCAL_MODEL, set by the caller,
        run_qualification_tasks), generates, strips reasoning, scans hygiene,
        writes the candidate body to a throwaway target file, and runs the
        task-specific verify command built below.

    Inputs:
        bridge_module (module): the imported ollama_bridge module (passed in
            rather than imported here, so this function has no import
            side-effect of its own).
        task (dict): one entry from qualification/tasks.json.
        tmp_dir (Path): a throwaway directory for this qualification run's
            prompt/target/log files - never inside the repository.

    Outputs:
        result (tuple[bool, str]): (passed, a short detail string for the
        per-task record).
    --------------------------------------------------------------------------
    """
    task_id = task.get("id", "task")
    kind = task.get("kind")
    prompt_path = tmp_dir / f"{task_id}.prompt.txt"
    prompt_path.write_text(task.get("prompt", ""), encoding="utf-8")
    # A coder candidate is a Python MODULE and must be named like one. Measured
    # 2026-08-14: the target used to be "<task_id>.out" for every kind, and
    # importlib.util.spec_from_file_location infers its loader from the EXTENSION - for
    # ".out" it returns a spec whose loader is None, so the verify died with
    # "AttributeError: 'NoneType' object has no attribute 'loader'" before running a
    # single case. Every coder task therefore failed for every model, always: that is the
    # whole of the incumbent's recorded coder 0/3, and of the challenger's. The same
    # generated module, byte for byte, passes all five cases when the file ends in ".py".
    suffix = ".py" if kind == "coder" else ".out"
    target_path = tmp_dir / f"{task_id}{suffix}"
    log_path = tmp_dir / f"{task_id}.log.jsonl"

    if kind == "coder":
        verify_command = _build_coder_verify_command(task)
    elif kind == "writer":
        verify_command = _build_writer_verify_command(task)
    else:
        return False, f"unknown task kind {kind!r}"

    rc = bridge_module.run_bridge(
        prompt_path=prompt_path,
        verify_command=verify_command,
        target_path=target_path,
        seed=bridge_module.DEFAULT_SEED,
        log_path=log_path,
    )
    return rc == 0, f"run_bridge rc={rc}"


def run_qualification_tasks(tag: str, tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run every task in the frozen set against `tag` through the
        deterministic bridge, forcing `tag` via the LARI_LOCAL_MODEL override
        for the duration of the run (restored on exit, success or failure) so
        qualification never reads and never depends on local-model-state.json
        - the very file --qualify might go on to update. Imports
        ollama_bridge lazily (module docstring) so --list/--resolve never pay
        for it.

    Inputs:
        tag (str): the candidate Ollama tag being qualified.
        tasks (list[dict]): the frozen task set (qualification/tasks.json's
            "tasks" array).

    Outputs:
        result (dict): {"tag": tag, "passed": int, "total": int,
        "ratio": float, "by_kind": {kind: {"passed": int, "total": int}, ...},
        "results": [{"id", "kind", "passed", "detail"}, ...]}. "by_kind" is
        the per-role breakdown fix round 1 (F3) requires: the win rule
        compares roles separately rather than the flat "passed" scalar, so
        a challenger cannot buy a win in one role by regressing another.
    --------------------------------------------------------------------------
    """
    import ollama_bridge  # local import: see module and function docstrings.

    results: list[dict[str, Any]] = []
    previous_override = os.environ.get(ENV_OVERRIDE_VAR)
    os.environ[ENV_OVERRIDE_VAR] = tag
    try:
        with tempfile.TemporaryDirectory(prefix="lari-qualify-") as tmp:
            tmp_path = Path(tmp)
            for task in tasks:
                passed, detail = _run_one_task(ollama_bridge, task, tmp_path)
                results.append({
                    "id": task.get("id", "?"),
                    "kind": task.get("kind", "?"),
                    "passed": passed,
                    "detail": detail,
                })
    finally:
        if previous_override is None:
            os.environ.pop(ENV_OVERRIDE_VAR, None)
        else:
            os.environ[ENV_OVERRIDE_VAR] = previous_override

    passed_count = sum(1 for r in results if r["passed"])
    total = len(results)
    by_kind: dict[str, dict[str, int]] = {}
    for r in results:
        entry = by_kind.setdefault(r["kind"], {"passed": 0, "total": 0})
        entry["total"] += 1
        if r["passed"]:
            entry["passed"] += 1
    return {
        "tag": tag,
        "passed": passed_count,
        "total": total,
        "ratio": (passed_count / total) if total else 0.0,
        "by_kind": by_kind,
        "results": results,
    }


def _build_coder_verify_command(task: dict[str, Any]) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the executable oracle for a coder task: load the candidate's
        generated module from the target file via importlib, call the
        declared entrypoint against every declared case, and exit 0 only if
        every case's return value matches the expected value exactly (tuples
        compared as lists, matching how JSON round-trips them). This is the
        SAME oracle logic for every coder task in the frozen set - nothing
        here is task-specific except the data (entrypoint, cases) pulled
        from `task` itself, so there is no per-task oracle file to maintain.

    Inputs:
        task (dict): a coder task; must carry "entrypoint" (str) and "cases"
            (list of {"args": [...], "expect": ...}).

    Outputs:
        result (list[str]): a pre-tokenized command for
        ollama_bridge.run_verify - [sys.executable, "-c", <script>,
        "{target}"] - using the list form specifically because run_verify's
        own docstring warns that shlex.split on a Windows path string is
        unsafe; the list form never goes through shlex at all.
    --------------------------------------------------------------------------
    """
    entrypoint = task["entrypoint"]
    cases = task.get("cases", [])
    # Double-encode: the inner json.dumps(cases) is the JSON text; the outer json.dumps
    # turns that JSON text into a valid Python string literal (quoting/escaping handled by
    # json.dumps itself), so the generated script can json.loads() it back verbatim.
    cases_literal = json.dumps(json.dumps(cases))
    entrypoint_repr = repr(entrypoint)  # entrypoint is a plain identifier string; a direct
    # Python repr() is a valid string literal on its own, no JSON round-trip needed here.
    script = (
        "import importlib.util, sys, json\n"
        f"cases = json.loads({cases_literal})\n"
        "spec = importlib.util.spec_from_file_location('candidate', sys.argv[1])\n"
        # Named refusal instead of an AttributeError: spec_from_file_location infers the
        # loader from the file EXTENSION and hands back loader=None for anything it does
        # not recognise as Python. That produced 'NoneType' has no attribute 'loader',
        # which reads as a broken candidate and was in fact a wrongly named target file.
        "if spec is None or spec.loader is None:\n"
        "    print('cannot import %r as Python: no loader for that file extension' %\n"
        "          sys.argv[1], file=sys.stderr)\n"
        "    sys.exit(1)\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(mod)\n"
        f"fn = getattr(mod, {entrypoint_repr})\n"
        "failures = []\n"
        "for i, case in enumerate(cases):\n"
        "    args = case['args']\n"
        "    expect = case['expect']\n"
        "    try:\n"
        "        got = fn(*args)\n"
        "    except Exception as exc:\n"
        "        failures.append('case %d: raised %r' % (i, exc))\n"
        "        continue\n"
        "    got_cmp = list(got) if isinstance(got, tuple) else got\n"
        "    if got_cmp != expect:\n"
        "        failures.append('case %d: got %r, expected %r' % (i, got, expect))\n"
        "if failures:\n"
        "    for line in failures:\n"
        "        print(line, file=sys.stderr)\n"
        "    sys.exit(1)\n"
        "print('PASS')\n"
    )
    return [sys.executable, "-c", script, "{target}"]


# Generic writer gate: reads its parameters from PARAMS_PLACEHOLDER, substituted per task by
# _build_writer_verify_command. No heading list, language, length range, or frontmatter key
# is hardcoded here - see that function's docstring for the structure-gate pitfall this
# avoids.
_WRITER_CHECK_SOURCE = """
import json, re, sys

params = json.loads(PARAMS_PLACEHOLDER)
target = sys.argv[1]
with open(target, encoding="utf-8") as fh:
    text = fh.read()

failures = []
body = text

frontmatter_keys = params["frontmatter_keys"]
if frontmatter_keys:
    if not text.startswith("---"):
        failures.append("frontmatter missing: file does not start with '---'")
    else:
        end = text.find("\\n---", 3)
        if end == -1:
            failures.append("frontmatter missing its closing '---' line")
        else:
            fm_block = text[3:end]
            body = text[end + 4:]
            present_keys = set(re.findall(r"(?m)^([A-Za-z_]+)\\s*:", fm_block))
            for key in frontmatter_keys:
                if key not in present_keys:
                    failures.append("frontmatter missing key '%s'" % key)

for section in params["required_sections"]:
    pattern = re.compile(r"(?m)^#{1,6}\\s*" + re.escape(section) + r"\\s*$")
    if not pattern.search(body):
        failures.append("missing required section heading '%s'" % section)

body_len = len(body.strip())
if body_len < params["min_length_chars"]:
    failures.append("body too short: %d chars < %d" % (body_len, params["min_length_chars"]))
if body_len > params["max_length_chars"]:
    failures.append("body too long: %d chars > %d" % (body_len, params["max_length_chars"]))

if params["language"] == "fr":
    # Fix round 1 (F4): the language gate errs toward false PASS if it is too loose - a
    # wrongly-passed qualification adopts a worse model - so this is the direction to
    # tighten, unlike the heading regex (which errs toward false FAIL, the safe direction,
    # and was left alone). Word-boundary counting (not substring/space-padding) over a
    # LARGER marker set, combined with a French-accented-character density requirement:
    # English prose containing a stray French token or two has near-zero accented
    # characters, so it fails the density leg even on the rare case where it clears the
    # marker-word count by chance.
    markers = [
        "le", "la", "les", "une", "un", "des", "est", "pour", "dans", "avec", "pas", "de",
        "et", "du", "au", "aux", "ne", "que", "qui", "sur", "plus", "cette", "ces", "son",
        "sa", "ses", "nous", "vous", "il", "elle", "sont", "ont",
    ]
    lowered_body = body.lower()
    marker_hits = 0
    for m in markers:
        marker_hits += len(re.findall(r"\\b" + re.escape(m) + r"\\b", lowered_body))
    accented = set(chr(c) for c in [
        0x00e0, 0x00e2, 0x00e4, 0x00e9, 0x00e8, 0x00ea, 0x00eb, 0x00ee, 0x00ef,
        0x00f4, 0x00f6, 0x00f9, 0x00fb, 0x00fc, 0x00ff, 0x00e7, 0x0153,
    ])  # a a a e e e e i i o o u u u y c oe (French-accented Latin letters, by codepoint
    # so the source file carries no literal accented character of its own - keeps this
    # script's own bytes plain ASCII while still recognising them in candidate text).
    accent_count = sum(1 for ch in lowered_body if ch in accented)
    accent_density = accent_count / max(1, len(body))
    # P7 (open-items pass): the four thresholds are injected from
    # model_resolver.LANGUAGE_GATE_THRESHOLDS, not written here, so a reader finds one
    # place that states what they are and what evidence would move them. See that
    # constant's own comment: they are judgment calls, and they are labelled as such.
    thresholds = params["language_thresholds"]
    min_marker_hits = thresholds["min_marker_hits"]
    min_accent_count = thresholds["min_accent_count"]
    min_accent_density = thresholds["min_accent_density"]

    # Fix round 2, item 1: a discriminator English idiom-stacking cannot satisfy. Measured
    # false pass against the three thresholds above: "Creme de la creme, au contraire, du
    # coup, coup de grace, de facto. Her fiancee's resume: cafe." - English borrows French
    # NOUN PHRASES whole, articles and all ("de", "la", "du", "au"), which is exactly why a
    # marker-word COUNT is gameable by idiom-stacking. What an idiom borrowed as a fixed
    # phrase does NOT carry over is the grammar of a full clause: a verb ("est", "sont"), a
    # relative pronoun ("qui"), or a preposition anchoring a verb phrase ("dans", "pour",
    # "avec", "sur", "cette", "les", "des", "nous", "plus"). This function_words list is a
    # subset of the broader markers list above, kept separate because what is required here
    # is DISTINCT words hit, not total occurrences - repeating one borrowed word many times
    # must not substitute for a sentence that actually uses several different ones.
    function_words = ["les", "des", "est", "qui", "dans", "pour", "avec", "sont", "cette", "nous", "plus", "sur"]
    distinct_function_hits = sum(
        1 for w in function_words
        if re.search(r"\\b" + re.escape(w) + r"\\b", lowered_body)
    )
    # Judgment call, not a measured constant (documented as such): 2 distinct hits out of a
    # 12-word list that specifically targets CLAUSE-level grammar (a verb or a preposition
    # tied to one) is a low bar for a genuine French sentence of any real length, even a
    # short one, because a real clause almost always pairs at least a verb with a
    # preposition or determiner from this list. An idiom fragment borrowed into English is a
    # noun phrase or a fixed exclamation, not a full clause, so it structurally lacks these
    # words entirely (the measured false pass above hits zero of them) - 2 already separates
    # the two categories without demanding three or more, which risked failing a short but
    # genuine one-clause sentence.
    min_distinct_function_hits = thresholds["min_distinct_function_hits"]

    if (marker_hits < min_marker_hits or accent_count < min_accent_count
            or accent_density < min_accent_density
            or distinct_function_hits < min_distinct_function_hits):
        failures.append(
            "language gate: %d French marker word hit(s) (need >= %d), %d accented "
            "character(s) (need >= %d), density %.4f (need >= %.4f), %d distinct French "
            "function word(s) hit (need >= %d); ALL FOUR thresholds must be met" % (
                marker_hits, min_marker_hits, accent_count, min_accent_count,
                accent_density, min_accent_density,
                distinct_function_hits, min_distinct_function_hits,
            )
        )

if failures:
    for line in failures:
        print(line, file=sys.stderr)
    sys.exit(1)
print("PASS")
"""


def _build_writer_verify_command(task: dict[str, Any]) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the deterministic gate for a writer task: structure (required
        section headings), language (a French-marker-word heuristic,
        documented as a heuristic - not an NLP language detector, which
        would need a third-party dependency and this module is stdlib
        only), length range, and required frontmatter keys. Hygiene is NOT
        re-checked here: ollama_bridge.run_bridge already scans and retries
        on a hygiene violation before a body ever reaches write_target, so
        by the time this verify command runs, the candidate text has
        already passed that gate (the brief's "deterministic gates the
        bridge already applies").

        Structure-gate pitfall (measured earlier in this plan): a FIXED
        five-heading gate wrongly failed a good generation whose brief had
        deliberately asked for two sections only. required_sections is
        therefore read from `task` itself on every call - there is no
        constant heading list anywhere in this module - so a task that asks
        for two sections is graded on two sections, and a task that asks for
        four is graded on four.

    Inputs:
        task (dict): a writer task; may carry "required_sections" (list),
            "language" (str, only "fr" is checked today), "min_length_chars"
            / "max_length_chars" (int), and "frontmatter_keys" (list). Every
            field defaults to "no constraint" when absent.

    Outputs:
        result (list[str]): a pre-tokenized command for
        ollama_bridge.run_verify (list form; see
        _build_coder_verify_command's docstring for why).
    --------------------------------------------------------------------------
    """
    params = {
        "required_sections": task.get("required_sections", []),
        "language": task.get("language", ""),
        "min_length_chars": task.get("min_length_chars", 0),
        "max_length_chars": task.get("max_length_chars", 10**9),
        "frontmatter_keys": task.get("frontmatter_keys", []),
        # P7: injected, never written inside the generated script, and overridable per task
        # so a future measurement can move a threshold without editing this module.
        "language_thresholds": {
            **LANGUAGE_GATE_THRESHOLDS,
            **(task.get("language_thresholds") or {}),
        },
    }
    params_literal = json.dumps(json.dumps(params))
    script = _WRITER_CHECK_SOURCE.replace("PARAMS_PLACEHOLDER", params_literal)
    return [sys.executable, "-c", script, "{target}"]


def _role_ratio(entry: dict[str, Any] | None) -> float:
    """
    --------------------------------------------------------------------------
    Purpose:
        Score one role's record as a ratio. Compared as a RATIO rather than
        as a raw pass count because the frozen task set can grow: 2 passes
        out of 3 is better than 2 out of 6, and a raw-count comparison would
        call that a tie and keep the worse tag. With an unchanged task set
        the two comparisons are identical, which is the ordinary case.

    Inputs:
        entry (dict | None): {"passed": int, "total": int, ...}, or None.

    Outputs:
        ratio (float): passed / total; 0.0 when the entry is absent or
        declares no task at all (never a ZeroDivisionError).
    --------------------------------------------------------------------------
    """
    if not isinstance(entry, dict):
        return 0.0
    total = int(entry.get("total", 0) or 0)
    if total <= 0:
        return 0.0
    return int(entry.get("passed", 0) or 0) / total


def _atomic_write_state(state: dict[str, Any]) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Write local-model-state.json atomically (fix round 1, F5): the new
        content goes to a sibling temporary file first, then os.replace()
        moves it over STATE_PATH in one filesystem operation. Factored out
        of _write_state so the per-role writer below shares the exact same
        discipline rather than growing a second, subtly different write path.

    Inputs:
        state (dict): the complete state document to persist.

    Outputs:
        None. STATE_PATH is created (parents included) or replaced.
    --------------------------------------------------------------------------
    """
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, indent=2, ensure_ascii=False) + "\n"
    tmp_path = STATE_PATH.with_name(STATE_PATH.name + ".tmp")
    tmp_path.write_text(payload, encoding="utf-8")
    os.replace(tmp_path, STATE_PATH)


def _merge_current_by_role(
    previous: dict[str, Any] | None,
    tag: str,
    by_kind: dict[str, dict[str, int]],
    today: str,
) -> dict[str, dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the "current_by_role" map for an OVERALL adoption (P4). One
        tag used to serve every role, which is the defect this map removes:
        the incumbent was adopted on a combined score and then handed to
        local-coder as well, although it passed 0 of the 3 coder tasks.
        A role changes hands only on a strict gain in THAT role, so an
        overall winner never quietly takes a role it is worse at; it keeps
        the role's existing tag instead.

    Inputs:
        previous (dict | None): the prior state document, or None on seed.
        tag (str): the newly adopted tag.
        by_kind (dict): the run's per-role breakdown.
        today (str): ISO date recorded on each role that changed hands.

    Outputs:
        merged (dict): role -> {"tag", "passed", "total", "adopted"}.
    --------------------------------------------------------------------------
    """
    merged: dict[str, dict[str, Any]] = {}
    prior = (previous or {}).get("current_by_role") or {}
    for role, entry in prior.items():
        if isinstance(entry, dict) and entry.get("tag"):
            merged[role] = dict(entry)

    for role, score in by_kind.items():
        candidate = {
            "tag": tag,
            "passed": int(score.get("passed", 0)),
            "total": int(score.get("total", 0)),
            "adopted": today,
        }
        if role not in merged or _role_ratio(candidate) > _role_ratio(merged[role]):
            merged[role] = candidate
    return merged


def _write_role_state(
    role: str,
    tag: str,
    role_score: dict[str, int],
    previous: dict[str, Any],
    today: str,
) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Adopt `tag` for ONE role. Everything else in the state document is
        carried over untouched: "current", "score" and "qualified_at" still
        describe the last FULL qualification, because a role run executes
        only that role's slice of the frozen task set and therefore cannot
        speak for the whole set. Writing it into "current" would be claiming
        a measurement that was never taken.

    Inputs:
        role (str): the task kind being adopted.
        tag (str): the winning tag for that role.
        role_score (dict): {"passed": int, "total": int} for that role.
        previous (dict): the prior state document (never None: a role run
            refuses when there is no incumbent - see cmd_qualify).
        today (str): ISO date for the history entry and the adoption stamp.

    Outputs:
        None. STATE_PATH is replaced atomically.
    --------------------------------------------------------------------------
    """
    by_role = {}
    for existing_role, entry in (previous.get("current_by_role") or {}).items():
        if isinstance(entry, dict) and entry.get("tag"):
            by_role[existing_role] = dict(entry)
    previous_entry = by_role.get(role)
    by_role[role] = {
        "tag": tag,
        "passed": int(role_score.get("passed", 0)),
        "total": int(role_score.get("total", 0)),
        "adopted": today,
    }

    history = list(previous.get("history", []))
    history.append({
        "date": today,
        "tag": tag,
        "action": f"promote-role:{role}",
        "score": {role: by_role[role]},
        "previous": previous_entry,
    })

    state = dict(previous)
    state["current_by_role"] = by_role
    state["history"] = history
    _atomic_write_state(state)


def _write_state(tag: str, result: dict[str, Any], previous: dict[str, Any] | None) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Record a FULL qualification: the new state document (current tag,
        its score, its per-role map, a fresh qualified_at timestamp) plus
        one dated history entry APPENDED to whatever history already existed
        - the history list is never overwritten. The per-role half is
        delegated to _merge_current_by_role, and the write itself to
        _atomic_write_state, which _write_role_state shares.

    Inputs:
        tag (str): the newly qualified tag.
        result (dict): run_qualification_tasks's return value for `tag`.
        previous (dict | None): the prior state document (None on the
            bootstrap / seed case - see _load_state_for_qualify).

    Outputs:
        None. STATE_PATH is created (parents included) or overwritten,
        atomically (fix round 1, F5): the new content is written to a
        sibling temporary file first, then os.replace() moves it over
        STATE_PATH in one filesystem operation. This module is the ONLY
        writer of the one file that names the current model, and by this
        module's own design an unreadable state file is a hard stop for
        every later run (_load_state_strict) - a partial write from a crash
        mid-write would self-inflict exactly that. os.replace is atomic on
        both POSIX and Windows when source and destination are on the same
        filesystem, which they always are here (same parent directory).
    --------------------------------------------------------------------------
    """
    today = datetime.now(timezone.utc).date().isoformat()
    by_kind = result.get("by_kind", {})
    score = {
        "passed": result["passed"],
        "total": result["total"],
        "ratio": result["ratio"],
        "by_kind": by_kind,
    }
    history = list(previous.get("history", [])) if previous else []
    history.append({
        "date": today,
        "tag": tag,
        "action": "seed" if previous is None else "promote",
        "score": score,
        "previous": None if previous is None else {
            "tag": previous.get("current"),
            "score": previous.get("score"),
        },
    })
    state = {
        "current": tag,
        "current_by_role": _merge_current_by_role(previous, tag, by_kind, today),
        "score": score,
        "qualified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "history": history,
    }
    _atomic_write_state(state)


def _load_policy() -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Load the "policy" object from local-models.json. Fix round 1 (F2):
        this object used to be declared but never read - qualification_mode,
        require_declared, require_installed, win_rule, and bootstrap_rule now
        each genuinely drive cmd_qualify (see that function and _WIN_RULES /
        _SUPPORTED_QUALIFICATION_MODES below); a stale or misspelled value in
        any of the enum-like fields (qualification_mode, win_rule) is an
        explicit ResolverError rather than a silently ignored key.

    Inputs:
        none.

    Outputs:
        result (dict): the "policy" object; empty dict if the key is absent
        (every consumer below applies its own documented default in that
        case, via .get with a default, never a bare KeyError).

    Raises:
        ResolverError: see _load_json_file (missing file, empty file,
        invalid JSON).
    --------------------------------------------------------------------------
    """
    data = _load_json_file(
        LOCAL_MODELS_PATH,
        empty_message=f"[RESOLVER] candidate declaration file at {LOCAL_MODELS_PATH} is empty.",
        missing_message=f"[RESOLVER] no candidate declaration file at {LOCAL_MODELS_PATH}.",
    )
    return data.get("policy", {})


# Fix round 1 (F2): the only qualification_mode this module implements. A policy.json that
# names anything else is refused explicitly rather than silently accepted - this turns the
# field from documentation into a real, enforced version guard.
_SUPPORTED_QUALIFICATION_MODES = frozenset({"beat_incumbent"})


def _win_rule_no_regression_strict_gain(
    challenger_by_kind: dict[str, dict[str, int]],
    incumbent_by_kind: dict[str, dict[str, int]],
    **_context: Any,
) -> tuple[bool, str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Fix round 1 (F3): the win rule, fixed at the RULE level rather than
        by adding structure. The old rule summed coder and writer passes
        into one scalar, so a challenger could win by gaining in one role
        while regressing the other - measured directly: the seeded
        incumbent (ornith:9b-gpu) scores 3/6 by passing all 3 writer tasks
        and failing all 3 coder tasks, and a challenger that flipped that
        exact split (0 writer, 3 coder) would have tied the old scalar and a
        challenger doing even slightly better overall would have won while
        making the coder-role behaviour strictly WORSE. The new rule: a
        challenger must not regress (fewer tasks passed) in ANY role present
        on either side, and must strictly gain in at least one role. A tie
        in every role is not a win (no regression, but also no gain).

        Known limitation, deliberately left for a later task (see the module
        docstring): this compares roles but `current` is still a single tag
        for the whole bridge - ollama_bridge.resolve_model() takes no role
        argument and is closed. A model that wins overall because it is
        strong at coder tasks and merely ties (not regresses) at writer
        tasks becomes "current" for BOTH roles, even though a role-specific
        incumbent might still be preferable for writer work. Splitting
        `current` into per-role tags is out of scope for this round.

    Inputs:
        challenger_by_kind (dict): the candidate's run_qualification_tasks
            "by_kind" breakdown, e.g. {"coder": {"passed": 3, "total": 3},
            "writer": {"passed": 0, "total": 3}}.
        incumbent_by_kind (dict): the incumbent's recorded "by_kind"
            breakdown from local-model-state.json's "score" object (may be
            an older state document lacking this key - see the ".get" below,
            which treats an absent role as {"passed": 0, "total": 0}).

    Outputs:
        result (tuple[bool, str]): (win, human-readable reason) - the reason
        is used verbatim in cmd_qualify's stdout/stderr message so the
        per-role comparison is legible, not just the final bool.
    --------------------------------------------------------------------------
    """
    all_kinds = sorted(set(challenger_by_kind) | set(incumbent_by_kind))
    gained_any = False
    per_role_notes: list[str] = []
    for kind in all_kinds:
        c = challenger_by_kind.get(kind, {"passed": 0, "total": 0})
        i = incumbent_by_kind.get(kind, {"passed": 0, "total": 0})
        per_role_notes.append(f"{kind} {c.get('passed', 0)}/{c.get('total', 0)} vs incumbent {i.get('passed', 0)}/{i.get('total', 0)}")
        if c.get("passed", 0) < i.get("passed", 0):
            return False, (
                f"regressed in role '{kind}': {c.get('passed', 0)} < incumbent's "
                f"{i.get('passed', 0)} ({'; '.join(per_role_notes)})"
            )
        if c.get("passed", 0) > i.get("passed", 0):
            gained_any = True
    if not gained_any:
        return False, f"no strict gain in any role, a tie everywhere is not a win ({'; '.join(per_role_notes)})"
    return True, f"no regression in any role, strict gain in at least one ({'; '.join(per_role_notes)})"


def measured_budget(tag: str, config_path: Path = MODEL_CONFIG_PATH) -> dict[str, Any] | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Report the retained VRAM measurement for a tag, or None when the tag
        has none. A tag with no entry has no configuration that was ever found
        admissible on this card, which is a fact about the card and not a
        missing file to work around.

    Inputs:
        tag (str): the model tag to look up.
        config_path (Path): the measurement document (default MODEL_CONFIG_PATH).

    Outputs:
        result (dict | None): {"num_ctx", "decode_tps"} for the retained rung,
        or None when the tag is absent or its entry names no retained window.
    --------------------------------------------------------------------------
    """
    try:
        document = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    entry = document.get("models", {}).get(tag)
    if not entry or not entry.get("retained_num_ctx"):
        return None
    rung = entry.get("retained_rung_measurement", {})
    decode_tps = rung.get("decode_tps")
    if decode_tps is None:
        rates = sorted(rung.get("throughputs_tok_s", []))
        decode_tps = rates[len(rates) // 2] if rates else 0.0
    return {"num_ctx": entry["retained_num_ctx"], "decode_tps": decode_tps}


def _win_rule_tie_broken_by_measured_budget(
    challenger_by_kind: dict[str, dict[str, int]],
    incumbent_by_kind: dict[str, dict[str, int]],
    *,
    challenger_tag: str = "",
    incumbent_tag: str = "",
    config_path: Path = MODEL_CONFIG_PATH,
    **_context: Any,
) -> tuple[bool, str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        The base rule, with one addition: when the two models pass exactly the
        same tasks in every role, break the tie on the measured VRAM budget
        rather than declaring no winner.

        Why a tie deserves a tie-break at all. The task set grades code
        quality, and equal scores mean it cannot separate the two. The
        measurement document grades what the card can hold, which is a
        different question and was never asked here. Leaving the incumbent in
        place on a tie is only defensible while the incumbent is itself a
        configuration this repository would accept, and it need not be: a tag
        can be the incumbent and still have NO admissible measured
        configuration, because it was adopted before the sweep existed.
        Measured 2026-08-28: the coder incumbent is fully resident only at a
        512-token window, where it leaves 83 MiB free against a 300 MiB floor,
        so its sweep retained nothing and wrote no entry.

        Regression and strict gain are unchanged - the tie-break never
        overrides a task-set verdict, it only decides the case the task set
        declared even.

    Inputs:
        challenger_by_kind (dict): the candidate's per-role breakdown.
        incumbent_by_kind (dict): the incumbent's recorded per-role breakdown.
        challenger_tag (str): the candidate's tag, for the measurement lookup.
        incumbent_tag (str): the incumbent's tag, for the same.
        config_path (Path): the measurement document.

    Outputs:
        result (tuple[bool, str]): (win, human-readable reason).
    --------------------------------------------------------------------------
    """
    win, reason = _win_rule_no_regression_strict_gain(challenger_by_kind, incumbent_by_kind)
    if win or "no strict gain in any role" not in reason:
        return win, reason

    challenger = measured_budget(challenger_tag, config_path)
    incumbent = measured_budget(incumbent_tag, config_path)
    if challenger is None:
        return False, (
            f"{reason}, and the challenger has no retained VRAM measurement to break it on")
    if incumbent is None:
        return True, (
            f"{reason}, but the incumbent has NO admissible measured configuration on this "
            f"card while the challenger retains {challenger['num_ctx']} tokens at "
            f"{challenger['decode_tps']:.2f} tok/s")
    if (challenger["num_ctx"] > incumbent["num_ctx"]
            and challenger["decode_tps"] >= incumbent["decode_tps"]):
        return True, (
            f"{reason}, broken on the measured budget: {challenger['num_ctx']} tokens at "
            f"{challenger['decode_tps']:.2f} tok/s against the incumbent's "
            f"{incumbent['num_ctx']} at {incumbent['decode_tps']:.2f}")
    return False, (
        f"{reason}, and the measured budget does not favour the challenger either "
        f"({challenger['num_ctx']} tokens at {challenger['decode_tps']:.2f} tok/s against "
        f"{incumbent['num_ctx']} at {incumbent['decode_tps']:.2f})")


# Fix round 1 (F2): dispatch table so policy.win_rule genuinely selects the comparison
# function - changing it to an unrecognized key is an explicit refusal (see cmd_qualify),
# not a silently ignored string. Only one strategy is implemented today; the table exists so
# a second one can be added later without another round of "policy nobody reads".
_WIN_RULES = {
    "no_regression_strict_gain_by_role": _win_rule_no_regression_strict_gain,
    "no_regression_strict_gain_by_role_tie_broken_by_measured_budget":
        _win_rule_tie_broken_by_measured_budget,
}


def _format_by_kind(by_kind: dict[str, dict[str, int]]) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Render a by_kind breakdown as "coder 3/3, writer 0/3" (sorted by
        kind name for determinism), for cmd_qualify's own output - fix round
        1 (F3) requires the per-role scores to be legible in the CLI output,
        not just in the JSON state file.

    Inputs:
        by_kind (dict): {kind: {"passed": int, "total": int}, ...}.

    Outputs:
        result (str): the rendered summary; "(no tasks)" if by_kind is empty.
    --------------------------------------------------------------------------
    """
    if not by_kind:
        return "(no tasks)"
    return ", ".join(f"{kind} {v.get('passed', 0)}/{v.get('total', 0)}" for kind, v in sorted(by_kind.items()))


TIE_BREAK_WIN_RULE = "no_regression_strict_gain_by_role_tie_broken_by_measured_budget"


def _adopt_role(
    tag: str,
    role: str,
    result: dict[str, Any],
    incumbent: dict[str, Any] | None,
    win_rule_key: str = "",
) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Decide and record a ROLE adoption (P4), the second half of
        cmd_qualify's --role path. Kept separate so the overall path below
        reads exactly as it did before this parameter existed.

        The incumbent for a role is, in order: its entry in
        current_by_role, then the role's slice of the last full
        qualification's score (attributed to "current"), then nothing. That
        second step matters for the transition: a state file written before
        P4 has no current_by_role at all, yet it does record by_kind, so the
        first role contest still runs against a real measured score rather
        than against an empty record that anything would beat.

    Inputs:
        tag (str): the challenger.
        role (str): the task kind contested.
        result (dict): run_qualification_tasks over that role's tasks only.
        incumbent (dict | None): the prior state document, or None.

    Outputs:
        result (int): 0 when the role was adopted, 1 on a refusal or a loss
        (nothing written).
    --------------------------------------------------------------------------
    """
    challenger = {
        "passed": int(result["passed"]),
        "total": int(result["total"]),
    }
    summary = f"{challenger['passed']}/{challenger['total']}"

    if incumbent is None:
        print(
            f"[RESOLVER] refusing to qualify {tag} for role {role!r}: {STATE_PATH} has no "
            "incumbent at all. Run a full '--qualify <tag>' first; a single role's slice of "
            "the task set must not be what seeds the global tag.",
            file=sys.stderr,
        )
        return 1

    by_role = incumbent.get("current_by_role") or {}
    entry = by_role.get(role)
    if isinstance(entry, dict) and entry.get("tag"):
        incumbent_tag = entry["tag"]
        incumbent_entry = entry
    else:
        # No per-role record yet: fall back to the role's slice of the last full run,
        # which the state file has carried in score.by_kind since fix round 1 (F3).
        incumbent_tag = incumbent.get("current")
        incumbent_entry = (incumbent.get("score", {}).get("by_kind", {}) or {}).get(role)

    incumbent_summary = (
        f"{int(incumbent_entry.get('passed', 0))}/{int(incumbent_entry.get('total', 0))}"
        if isinstance(incumbent_entry, dict) else "no recorded score"
    )

    challenger_ratio = _role_ratio(challenger)
    incumbent_ratio = _role_ratio(incumbent_entry)
    tie_break_reason = ""
    if challenger_ratio < incumbent_ratio or (
            challenger_ratio == incumbent_ratio and win_rule_key != TIE_BREAK_WIN_RULE):
        print(
            f"[RESOLVER] {tag} did not qualify for role {role!r} against {incumbent_tag}: "
            f"{summary} vs {incumbent_summary}, which is not a strict gain; {STATE_PATH} "
            "left unchanged.",
            file=sys.stderr,
        )
        return 1
    if challenger_ratio == incumbent_ratio:
        # The task set graded the two even, so it has said all it can. Under this policy the
        # tie goes to the measured VRAM budget, which answers a different question and was
        # never asked here. A tie is only broken, never a regression.
        won, tie_break_reason = _win_rule_tie_broken_by_measured_budget(
            {role: challenger}, {role: incumbent_entry if isinstance(incumbent_entry, dict) else {}},
            challenger_tag=tag, incumbent_tag=incumbent_tag or "")
        if not won:
            print(
                f"[RESOLVER] {tag} did not qualify for role {role!r} against {incumbent_tag}: "
                f"{tie_break_reason}; {STATE_PATH} left unchanged.",
                file=sys.stderr,
            )
            return 1

    today = datetime.now(timezone.utc).date().isoformat()
    _write_role_state(role, tag, challenger, incumbent, today)
    print(
        f"[RESOLVER] {tag} qualified for role {role!r}, beating {incumbent_tag}: "
        f"{summary} vs {incumbent_summary}"
        + (f" ({tie_break_reason})" if tie_break_reason else "")
        + f"; now current for that role in {STATE_PATH} "
        f"(the overall 'current' tag is unchanged)."
    )
    return 0


def cmd_score(tag: str, role: str | None, record: bool = False, as_json: bool = False) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run the frozen task set against `tag` and report what it scored,
        writing nothing. Measuring a field of candidates previously required
        --qualify, whose whole purpose is to change the adopted tag, so the
        only way to read a number for a candidate you did not want to adopt
        was to read it out of a refusal message.

        Reports per task, not only the totals, because a ten-task set exists
        precisely so that two candidates on the same total can still be told
        apart by WHICH tasks each failed.

    Inputs:
        tag (str): the model tag to score.
        role (str | None): restrict to one task kind, or None for all.

    Outputs:
        result (int): 0 when the run completed, 1 when the task set could not
        be loaded or the role names no task.

    Raises:
        ResolverError: the task set is missing or malformed.
    --------------------------------------------------------------------------
    """
    tasks = _load_tasks()
    if role:
        tasks = [t for t in tasks if t.get("kind") == role]
        if not tasks:
            print(f"[RESOLVER] no task of kind {role!r} in {TASKS_PATH}.", file=sys.stderr)
            return 1

    result = run_qualification_tasks(tag, tasks)
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
        if not record:
            return 0
    else:
        for entry in result["results"]:
            print(f"  {'PASS' if entry['passed'] else 'FAIL'}  {entry['kind']:6} {entry['id']}")
    summary = (f"[RESOLVER] {tag} scored {result['passed']}/{result['total']} "
               f"({_format_by_kind(result['by_kind'])})")
    if not record:
        print(summary + "; nothing written.")
        return 0

    if not role:
        print(f"{summary}; --record needs --role: a refreshed score belongs to one role's "
              f"entry, and there is no whole-set record to refresh.", file=sys.stderr)
        return 1
    state = _load_state_for_qualify() or {}
    entry = (state.get("current_by_role") or {}).get(role) or {}
    if entry.get("tag") != tag:
        print(f"{summary}; refusing --record: {tag} is not the current tag for role {role!r} "
              f"({entry.get('tag') or 'none'} is). --record refreshes an incumbent's stale "
              f"number, it never changes which tag is current - use --qualify for that.",
              file=sys.stderr)
        return 1

    role_score = {"passed": int(result["by_kind"].get(role, {}).get("passed", 0)),
                  "total": int(result["by_kind"].get(role, {}).get("total", 0))}
    _write_role_state(role, tag, role_score, state,
                      datetime.now(timezone.utc).date().isoformat())
    print(f"{summary}; recorded for role {role!r} in {STATE_PATH} (same tag, refreshed score).")
    return 0


def build_matrix(tags: list[str], tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Score every tag on EVERY task and return the per-task grid plus each
        tag's measured GPU budget, so a comparison is computed rather than
        transcribed.

        Scoring a candidate only on the role it is declared for is how, on
        2026-08-28, a tag passing 18 of 20 held the coder role while a tag
        passing 20 of 20 sat unscored on coder tasks. The comparison must
        cover the whole set for every candidate or it measures the choice of
        what to measure.

        A tag with no entry in local-model-config.json is reported as NOT
        RUNNABLE rather than as zero. The bridge refuses such a tag because
        there is no measured context window to run against, so no task
        executes; counting those as failures reads a harness refusal as a
        capability, which is the defect class this repository has now hit
        three times.

    Inputs:
        tags (list[str]): the tags to score, in report order.
        tasks (list[dict]): the frozen task set.

    Outputs:
        result (dict): {"task_ids": [...], "rows": {tag: {"runnable": bool,
        "why": str, "per_task": {id: bool}, "by_kind": {...},
        "passed": int, "total": int, "budget": dict | None}}}.
    --------------------------------------------------------------------------
    """
    task_ids = [t.get("id", "?") for t in tasks]
    rows: dict[str, Any] = {}
    for tag in tags:
        budget = measured_budget(tag)
        if budget is None:
            rows[tag] = {
                "runnable": False, "budget": None, "per_task": {}, "by_kind": {},
                "passed": 0, "total": 0,
                "why": "no measured context window in local-model-config.json, so the bridge "
                       "refuses the tag and no task executes; this is not a score of zero",
            }
            continue
        result = run_qualification_tasks(tag, tasks)
        rows[tag] = {
            "runnable": True, "budget": budget, "why": "",
            "per_task": {r["id"]: bool(r["passed"]) for r in result["results"]},
            "by_kind": result["by_kind"],
            "passed": result["passed"], "total": result["total"],
        }
    return {"task_ids": task_ids, "rows": rows}


def _render_matrix(matrix: dict[str, Any], kinds: list[str]) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Render the per-task grid and the comparative summary as text.

    Inputs:
        matrix (dict): the output of build_matrix.
        kinds (list[str]): task kinds to summarise, in column order.

    Outputs:
        result (str): the two tables, ready to print.
    --------------------------------------------------------------------------
    """
    tags = list(matrix["rows"])
    width = max((len(t) for t in tags), default=10) + 2
    lines = ["", "Per-task matrix (PASS / FAIL / n-r = not runnable)", ""]
    lines.append("task".ljust(34) + "".join(t.ljust(width) for t in tags))
    for task_id in matrix["task_ids"]:
        cells = ""
        for tag in tags:
            row = matrix["rows"][tag]
            cells += ("n-r" if not row["runnable"]
                      else ("PASS" if row["per_task"].get(task_id) else "FAIL")).ljust(width)
        lines.append(task_id.ljust(34) + cells)

    header = ("model".ljust(24) + "".join(k.ljust(10) for k in kinds)
              + "total".ljust(10) + "num_ctx".ljust(10) + "tok/s".ljust(10))
    lines += ["", "Comparative summary", "", header]
    order = sorted(tags, key=lambda t: (-matrix["rows"][t]["passed"], t))
    for tag in order:
        row = matrix["rows"][tag]
        if not row["runnable"]:
            lines.append(tag.ljust(24) + "NOT RUNNABLE: " + row["why"])
            continue
        cells = "".join(
            f"{row['by_kind'].get(k, {}).get('passed', 0)}/"
            f"{row['by_kind'].get(k, {}).get('total', 0)}".ljust(10) for k in kinds)
        lines.append(
            tag.ljust(24) + cells
            + f"{row['passed']}/{row['total']}".ljust(10)
            + str(row["budget"]["num_ctx"]).ljust(10)
            + f"{row['budget']['decode_tps']:.2f}".ljust(10))
    return "\n".join(lines)


def cmd_matrix(as_json: bool = False) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Implement --matrix: score every declared AND installed candidate on
        every task, then print the per-task grid and the comparative summary.
        Writes nothing.

    Inputs:
        as_json (bool): emit the raw structure instead of the tables.

    Outputs:
        result (int): 0 when the run completed, 1 when no candidate is both
        declared and installed.

    Raises:
        ResolverError: the task set or the declaration file is unreadable.
    --------------------------------------------------------------------------
    """
    tasks = _load_tasks()
    declared = _load_local_models()
    installed = set(list_installed_models())
    tags = [t for t in declared if t in installed]
    if not tags:
        print(f"[RESOLVER] no tag in {LOCAL_MODELS_PATH} is installed; nothing to compare.",
              file=sys.stderr)
        return 1

    matrix = build_matrix(tags, tasks)
    if as_json:
        print(json.dumps(matrix, indent=2, sort_keys=True))
        return 0
    print(_render_matrix(matrix, _known_task_kinds(tasks)))
    print("\n[RESOLVER] nothing written; --matrix only measures.")
    return 0


def _known_task_kinds(tasks: list[dict[str, Any]]) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        The roles this repository actually declares, read from the frozen
        task set rather than written as a constant here. The module's "no
        hardcoded tag" discipline applies to roles for the same reason: a
        constant list would silently disagree with tasks.json the day a kind
        is added.

    Inputs:
        tasks (list[dict]): the frozen task set.

    Outputs:
        kinds (list[str]): sorted distinct "kind" values.
    --------------------------------------------------------------------------
    """
    return sorted({str(t.get("kind", "")).strip() for t in tasks if t.get("kind")})


def cmd_qualify(tag: str, role: str | None = None) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Implement --qualify <tag>: refuse an undeclared or uninstalled tag
        (each gate itself controlled by policy.require_declared /
        policy.require_installed - fix round 1, F2), run the frozen task set
        against it, and adopt it into local-model-state.json ONLY if the
        configured win rule (policy.win_rule, fix round 1 F3) says it wins
        against the incumbent's last recorded per-role score, or there is no
        incumbent yet and policy.bootstrap_rule allows seeding. A loss or a
        refused bootstrap changes nothing on disk and exits non-zero.

        With `role` (P4), the run is scoped to ONE role: only that role's
        slice of the frozen task set is executed, the comparison is against
        that role's own incumbent, and a win rewrites only
        current_by_role[role] - "current", "score" and "qualified_at" keep
        describing the last full qualification. This is the path a
        role-specialised model needs: a coder model cannot beat a writer
        model on the writer tasks, so under the overall win rule alone it
        could never be adopted for anything, and local-coder would keep
        being served the writer model that scores 0/3 on coder tasks.
        A role run never SEEDS: with no incumbent at all it refuses and asks
        for a full qualification first, because a partial task set must not
        be the thing that decides the global tag.

    Inputs:
        tag (str): the candidate Ollama tag to qualify.
        role (str | None): restrict to one task kind, or None for the full
            frozen set (the pre-P4 behaviour, unchanged).

    Outputs:
        result (int): 0 on a win (state updated) or an allowed bootstrap
        seed, 1 on a refusal (undeclared, not installed, unsupported policy
        value, unknown role, bootstrap disabled) or a loss (state unchanged).

    Raises:
        ResolverError: policy.qualification_mode or policy.win_rule names an
        unsupported value - propagates to main(), which prints it and
        returns 1 (fix round 1, F2: this is what makes those two fields
        genuinely enforced rather than decorative).
    --------------------------------------------------------------------------
    """
    policy = _load_policy()

    mode = policy.get("qualification_mode")
    if mode not in _SUPPORTED_QUALIFICATION_MODES:
        raise ResolverError(
            f"[RESOLVER] {LOCAL_MODELS_PATH}'s policy.qualification_mode is {mode!r}, not "
            f"one of the supported values {sorted(_SUPPORTED_QUALIFICATION_MODES)}; refusing "
            "rather than proceeding under an unrecognised mode."
        )

    win_rule_key = policy.get("win_rule")
    if win_rule_key not in _WIN_RULES:
        raise ResolverError(
            f"[RESOLVER] {LOCAL_MODELS_PATH}'s policy.win_rule is {win_rule_key!r}, not one "
            f"of the supported values {sorted(_WIN_RULES)}; refusing rather than proceeding "
            "under an unrecognised win rule."
        )
    win_rule_fn = _WIN_RULES[win_rule_key]

    require_declared = policy.get("require_declared", True)
    require_installed = policy.get("require_installed", True)
    allow_bootstrap = policy.get("bootstrap_rule", True)

    declared = _load_local_models()
    if require_declared and tag not in declared:
        print(
            f"[RESOLVER] refusing to qualify {tag}: not declared as a candidate in "
            f"{LOCAL_MODELS_PATH} (policy.require_declared is true).",
            file=sys.stderr,
        )
        return 1

    if require_installed:
        installed = set(list_installed_models())
        if tag not in installed:
            print(
                f"[RESOLVER] refusing to qualify {tag}: not installed (absent from "
                "'ollama list'; policy.require_installed is true).",
                file=sys.stderr,
            )
            return 1

    tasks = _load_tasks()
    if role:
        kinds = _known_task_kinds(tasks)
        if role not in kinds:
            print(
                f"[RESOLVER] refusing to qualify {tag} for role {role!r}: no task of that "
                f"kind in {TASKS_PATH} (declared kinds: {', '.join(kinds) or 'none'}).",
                file=sys.stderr,
            )
            return 1
        tasks = [t for t in tasks if t.get("kind") == role]

    result = run_qualification_tasks(tag, tasks)
    incumbent = _load_state_for_qualify()

    if role:
        return _adopt_role(tag, role, result, incumbent, win_rule_key)

    if incumbent is None:
        if not allow_bootstrap:
            print(
                f"[RESOLVER] refusing to qualify {tag}: no incumbent yet in {STATE_PATH} and "
                "policy.bootstrap_rule is false; seeding is disabled by policy.",
                file=sys.stderr,
            )
            return 1
        _write_state(tag, result, previous=None)
        print(
            f"[RESOLVER] {tag} qualified at {result['passed']}/{result['total']} "
            f"({_format_by_kind(result['by_kind'])}) (no prior incumbent; {STATE_PATH} seeded)."
        )
        return 0

    incumbent_by_kind = incumbent.get("score", {}).get("by_kind", {})
    win, reason = win_rule_fn(result["by_kind"], incumbent_by_kind)

    if not win:
        print(
            f"[RESOLVER] {tag} did not qualify against incumbent {incumbent.get('current')}: "
            f"{reason}; {STATE_PATH} left unchanged.",
            file=sys.stderr,
        )
        return 1

    _write_state(tag, result, previous=incumbent)
    print(
        f"[RESOLVER] {tag} qualified, beating {incumbent.get('current')}: {reason}; "
        f"now current in {STATE_PATH}."
    )
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the CLI: exactly one of --list, --resolve, --qualify TAG.

    Inputs:
        none.

    Outputs:
        result (argparse.ArgumentParser): the configured parser.
    --------------------------------------------------------------------------
    """
    parser = argparse.ArgumentParser(
        description="Model resolver for the loop-engineer bridge (P4 Task 3): declares which "
                     "local Ollama tag is current, and qualifies a new one against the frozen "
                     "task set. Never hardcodes a tag."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="list installed tags with eligibility and reason")
    group.add_argument("--resolve", action="store_true", help="print the current tag, nothing else")
    group.add_argument("--qualify", type=str, metavar="TAG", help="qualify TAG against the frozen task set")
    group.add_argument(
        "--matrix", action="store_true",
        help="score EVERY declared and installed candidate on EVERY task, then print the "
             "per-task grid and the comparative summary. Writes nothing. Exists because a "
             "candidate scored only on its declared role is not comparable: an 18/20 tag held "
             "the coder role while a 20/20 tag sat unscored on coder tasks.")
    group.add_argument(
        "--score", type=str, metavar="TAG",
        help="run the frozen task set against TAG and report the result, changing NOTHING. "
             "Comparing candidates used to require --qualify, which writes state as a side "
             "effect, so measuring a field of candidates meant either adopting one or reading "
             "a refusal message for the number.")
    parser.add_argument(
        "--json", action="store_true",
        help="with --score, print the result as JSON on stdout instead of a per-task list, so "
             "a comparison across candidates is assembled from data rather than by parsing a "
             "human-readable log.")
    parser.add_argument(
        "--record", action="store_true",
        help="with --score, write the measured score into local-model-state.json for a tag "
             "that is ALREADY current for that role. Refreshes a stale record; it can never "
             "change which tag is current. Needed because an incumbent's recorded score is "
             "frozen at whatever task set existed when it was adopted, and a later challenger "
             "is then compared against a number from a different set.")
    parser.add_argument(
        "--role", type=str, default=None, metavar="KIND",
        help="task kind (as declared by qualification/tasks.json, e.g. writer or coder). "
             "With --resolve, print the tag adopted for that role. With --qualify, run only "
             "that role's tasks and adopt the winner for that role alone, leaving the "
             "overall current tag untouched (P4). Not valid with --list.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        CLI entry point.

    Inputs:
        argv (list[str] | None): argument vector (defaults to sys.argv[1:]).

    Outputs:
        result (int): process exit code.
    --------------------------------------------------------------------------
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.role and args.list:
        print("[RESOLVER] --role does not apply to --list; it lists every installed tag.",
              file=sys.stderr)
        return 1

    try:
        if args.list:
            return cmd_list()
        if args.resolve:
            return cmd_resolve(args.role)
        if args.qualify:
            return cmd_qualify(args.qualify, args.role)
        if args.score:
            return cmd_score(args.score, args.role, args.record, args.json)
        if args.matrix:
            return cmd_matrix(args.json)
    except ResolverError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
