"""
local_coder_driver - run a whole progress.md on the local coder model, with aider-setup's input.

The local-coder agent launches this once per effort. For every plan of the ledger that still has an
open line, it submits to the coder model exactly the files aider-plan.ps1 hands aider (conventions,
rules, spec, plan, skill stage, progress, the files the plan names, then the plan message), sized by
the same context-budget.json and skills.json, in ONE call per plan. It writes the files the reply
carries, runs the plan's own test files, and ticks or blocks the plan in progress.md. A failing plan
is retried with the reopen skill and the failing output, then blocked, and the next plan still runs.
Nothing is truncated: a file over its ceiling or a prompt over the window is refused (R8).

Why it exists (measured 2026-11-05, Issue #104): the agent used to hand-pick 1245 to 4225 tokens of
prompt per file inside a 16384 window, the model never saw the rules, the spec or the conventions,
and the cloud ended up writing the code. Rule R39: code is generated locally only.

Exit codes: 0 every plan done or skipped, 1 a plan blocked or refused, 2 refusal before any plan
(configuration, budget or ledger unusable).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

SCRIPTS_DIR = Path(__file__).resolve().parent
SKILLS_DIR = SCRIPTS_DIR.parent.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
# The real dependencies live in driver_deps.py (Issue #104); re-exported under the old name.
from driver_deps import BridgeDeps  # noqa: E402,F401
DEFAULT_CONFIG = SCRIPTS_DIR.parent / "local-coder-driver.json"
CONFIG_KEYS = ("code_extensions", "data_extensions", "aider_config_dir", "write_message",
               "fix_message", "reopen_message", "reply_format", "test_timeout_s",
               "request_timeout_s", "failure_lines", "audit_exclude", "git_timeout_s")
# Same separators as Get-PlanTargets in aider-plan-core.ps1, so both harnesses find the same files.
_SEPARATORS = re.compile(r"[ \t\r\n,;:()\[\]{}\"'`<>|!?]+")
_SECTION_RE = re.compile(r"^## (\S+\.md)\s*$")
_TEST_LINE_RE = re.compile(r"^\s*-\s*Test:\s*`?([^`\s]+)`?")


class DriverError(ValueError):
    """Raised when a file, a key or a ceiling makes a prompt impossible to build honestly."""


def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read local-coder-driver.json as plain values.

    Inputs:
        path (Path): the configuration file.

    Outputs:
        config (dict): one plain value per key of CONFIG_KEYS.

    Raises:
        DriverError: the file is unreadable or a key is missing, naming it (R3).
    --------------------------------------------------------------------------
    """
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DriverError(f"cannot read {path}: {exc}") from exc
    config = {}
    for key in CONFIG_KEYS:
        entry = raw.get(key)
        if not isinstance(entry, dict) or "value" not in entry:
            raise DriverError(f"{path} declares no '{key}'")
        config[key] = entry["value"]
    return config


def _source(raw: str, home: Path) -> Path:
    """
    --------------------------------------------------------------------------
    Purpose:
        Turn a path of context-budget.json or skills.json into the file read:
        the same installed file aider-plan.ps1 reads.

    Inputs:
        raw (str): the path as written, with its {{HOME}} token.
        home (Path): the home folder; injected so a test reads no real one (R21).

    Outputs:
        path (Path): the file to read.
    --------------------------------------------------------------------------
    """
    return Path(raw.replace("{{HOME}}", str(home)))


def plan_targets(plan: Path, root: Path, config: dict) -> list[Path]:
    """
    --------------------------------------------------------------------------
    Purpose:
        List the files a plan names, as Get-PlanTargets does for aider.

    Details:
        The front matter (the R38 header) is skipped. A token is a target when
        its extension is a code or data extension of the config; a path that
        resolves outside root is dropped (R24). Order of first appearance.

    Inputs:
        plan (Path): the plan file.
        root (Path): the repository root.
        config (dict): from load_config.

    Outputs:
        targets (list[Path]): resolved paths, existing or to be created.
    --------------------------------------------------------------------------
    """
    text = plan.read_text(encoding="utf-8")
    lines = text.split("\n")
    if len(lines) > 1 and lines[0].strip("﻿ \r") == "---":
        for index in range(1, len(lines)):
            if lines[index].strip(" \r") == "---":
                text = "\n".join(lines[index + 1:])
                break
    extensions = {e.lower() for e in config["code_extensions"] + config["data_extensions"]}
    base = Path(root).resolve()
    found: list[Path] = []
    for token in _SEPARATORS.split(text):
        # Trailing dots only: `.claude/x.py` keeps its leading dot (Get-PlanTargets trims both sides).
        word = token.strip("*#").rstrip(".")
        if Path(word).suffix.lower() not in extensions:
            continue
        resolved = (base / word).resolve()
        if base not in resolved.parents or resolved in found:
            continue
        found.append(resolved)
    return found


def _test_files(plan: Path) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        List the `- Test:` files of a plan, the suites the driver runs.

    Inputs:
        plan (Path): the plan file.

    Outputs:
        paths (list[str]): relative paths, in plan order.
    --------------------------------------------------------------------------
    """
    found = []
    for line in plan.read_text(encoding="utf-8").splitlines():
        match = _TEST_LINE_RE.match(line)
        if match and match.group(1) not in found:
            found.append(match.group(1))
    return found


def _stage_files(skills: dict, stage: str, home: Path) -> list[Path]:
    """
    --------------------------------------------------------------------------
    Purpose:
        List the skill files of one stage, with aider-setup's bundle rule.

    Details:
        A 'bundle' is its SKILL.md plus every Markdown file that SKILL.md
        names beside it, one level only (skills.json '_bundle_rule').

    Inputs:
        skills (dict): skills.json content.
        stage (str): 'write' or 'reopen'.
        home (Path): the home folder holding .config/aider.

    Outputs:
        files (list[Path]): the stage's files, in order.

    Raises:
        DriverError: the stage is absent from skills.json.
    --------------------------------------------------------------------------
    """
    entry = skills.get("stages", {}).get(stage)
    if not isinstance(entry, dict):
        raise DriverError(f"skills.json declares no stage '{stage}'")
    if "bundle" in entry:
        folder = _source(entry["bundle"], home)
        main = folder / "SKILL.md"
        files = [main]
        if main.is_file():
            for name in re.findall(r"[\w.-]+\.md", main.read_text(encoding="utf-8")):
                if name != "SKILL.md" and folder / name not in files:
                    files.append(folder / name)
        return files
    return [_source(raw, home) for raw in entry.get("files", [])]


def _read_checked(path: Path, ceiling: int, label: str, counter: Callable[[str], int]) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read one file of the set and hold it to its ceiling.

    Inputs:
        path (Path): the file.
        ceiling (int): its token ceiling from the budget.
        label (str): the budget key, named in a refusal.
        counter (Callable): text -> tokens.

    Outputs:
        text (str): the whole file.

    Raises:
        DriverError: the file is missing or over its ceiling (never cut, R8).
    --------------------------------------------------------------------------
    """
    if not path.is_file():
        raise DriverError(f"{label}: {path} does not exist")
    text = path.read_text(encoding="utf-8")
    tokens = counter(text)
    if tokens > ceiling:
        raise DriverError(f"{label}: {path.name} is {tokens} tokens, over its ceiling {ceiling}")
    return text


def file_set(plan: Path, root: Path, budget: dict, skills: dict, stage: str, config: dict,
             home: Path, counter: Callable[[str], int]) -> list[tuple[str, Path]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build aider-setup's file set for one plan, in aider-plan.ps1's order,
        every file checked against its ceiling.

    Inputs:
        plan (Path): the plan file; spec.md and progress.md sit beside it.
        root (Path): the repository root.
        budget (dict): context-budget.json content.
        skills (dict): skills.json content.
        stage (str): skill stage, 'write' or 'reopen'.
        config (dict): from load_config.
        home (Path): the home folder holding .config/aider.
        counter (Callable): text -> tokens.

    Outputs:
        files (list[tuple[str, Path]]): (label, path) for conventions, rules,
            spec, plan, skill files, progress, then every existing target.

    Raises:
        DriverError: a file is missing, over its ceiling, or a key is absent.
    --------------------------------------------------------------------------
    """
    ceilings = budget["ceilings"]
    effort = plan.parent
    entries: list[tuple[str, Path, int]] = []
    for raw in budget["always_on_files"]:
        path = _source(raw, home)
        entries.append((path.name, path, int(ceilings[path.name])))
    entries.append(("spec.md", effort / "spec.md", int(ceilings["spec.md"])))
    entries.append(("plan.md", plan, int(ceilings["plan.md"])))
    stage_ceiling = int(skills["stages"][stage]["ceiling"])
    stage_paths = _stage_files(skills, stage, home)
    stage_text = ""
    for path in stage_paths:
        stage_text += _read_checked(path, stage_ceiling, f"skill stage {stage}", counter)
    if counter(stage_text) > stage_ceiling:
        raise DriverError(f"skill stage {stage} is over its ceiling {stage_ceiling}")
    entries.extend((f"skill {stage}", path, stage_ceiling) for path in stage_paths)
    entries.append(("progress.md", effort / "progress.md", int(ceilings["progress.md"])))
    entries.extend(("code_file", path, int(ceilings["code_file"]))
                   for path in plan_targets(plan, root, config) if path.is_file())
    for label, path, ceiling in entries:
        _read_checked(path, ceiling, label, counter)
    return [(label, path) for label, path, _ in entries]


def build_prompt(files: list[tuple[str, Path]], root: Path, message: str, config: dict,
                 to_create: list[str], failure: str | None) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Assemble the prompt: every file whole under its own header, then the
        plan message, the files to create, the failing output and the reply
        format.

    Inputs:
        files (list[tuple[str, Path]]): from file_set.
        root (Path): the repository root, for relative headers.
        message (str): the plan message, already formatted.
        config (dict): from load_config.
        to_create (list[str]): targets that do not exist yet.
        failure (str | None): failing test output or a reply refusal, on a retry.

    Outputs:
        prompt (str): the full prompt.
    --------------------------------------------------------------------------
    """
    base = Path(root).resolve()
    parts = []
    for _, path in files:
        resolved = Path(path).resolve()
        name = resolved.relative_to(base).as_posix() if base in resolved.parents else path.name
        parts.append(f"### {name}\n\n{resolved.read_text(encoding='utf-8')}")
    parts.append(f"### Task\n\n{message}")
    if to_create:
        parts.append("Files to create: " + ", ".join(to_create))
    if failure:
        parts.append(f"### Failure\n\n{failure}")
    parts.append(config["reply_format"])
    return "\n\n".join(parts) + "\n"


def open_plans(progress: Path) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        List the plan sections of progress.md that still hold an open line.

    Inputs:
        progress (Path): the ledger.

    Outputs:
        names (list[str]): plan file names, in ledger order.
    --------------------------------------------------------------------------
    """
    names, current = [], None
    for line in progress.read_text(encoding="utf-8").splitlines():
        match = _SECTION_RE.match(line)
        if match:
            current = match.group(1)
        elif current and line.startswith("- [ ]") and current not in names:
            names.append(current)
    return names


def open_lines(progress: Path, plan_name: str) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        List the open lines of one plan's section of progress.md.

    Inputs:
        progress (Path): the ledger.
        plan_name (str): the section name.

    Outputs:
        lines (list[str]): the `- [ ]` lines, text after the mark, in order.
    --------------------------------------------------------------------------
    """
    found, current = [], None
    for line in progress.read_text(encoding="utf-8").splitlines():
        match = _SECTION_RE.match(line)
        if match:
            current = match.group(1)
        elif current == plan_name and line.startswith("- [ ]"):
            found.append(line[5:].strip())
    return found


def tick(progress: Path, plan_name: str, done: bool, note: str) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Record a plan's outcome in progress.md: every open line ticked, or the
        first open line blocked with its reason.

    Inputs:
        progress (Path): the ledger.
        plan_name (str): the section name.
        done (bool): True ticks, False blocks.
        note (str): one line, appended to the ticked or blocked line.

    Outputs:
        None. Rewrites progress.md.
    --------------------------------------------------------------------------
    """
    lines = progress.read_text(encoding="utf-8").split("\n")
    current, blocked = None, False
    for index, line in enumerate(lines):
        match = _SECTION_RE.match(line)
        if match:
            current = match.group(1)
            continue
        if current != plan_name or not line.startswith("- [ ]"):
            continue
        if done:
            lines[index] = f"- [x]{line[5:]} (local: {note})"
        elif not blocked:
            lines[index] = f"- [!]{line[5:]} - {note}"
            blocked = True
    progress.write_text("\n".join(lines), encoding="utf-8")


def _write_reply(reply: str, root: Path, allowed: list[Path], split: Callable) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Write the files a reply carries, all or none.

    Inputs:
        reply (str): the model's answer.
        root (Path): the repository root.
        allowed (list[Path]): the plan's targets, the only writable paths.
        split (Callable): the bridge's split_files.

    Outputs:
        written (list[str]): relative paths written.

    Raises:
        DriverError: a path outside root or not named by the plan (R24), or a
            reply the bridge cannot split; nothing is written then.
    --------------------------------------------------------------------------
    """
    base = Path(root).resolve()
    try:
        files = split(reply)
    except Exception as exc:  # the bridge raises its own BridgeError type
        raise DriverError(str(exc)) from exc
    plan_out = []
    for name, body in files:
        target = (base / name).resolve()
        if base not in target.parents:
            raise DriverError(f"reply writes {name}, outside the repository")
        if target not in allowed:
            raise DriverError(f"reply writes {name}, a file the plan does not name")
        plan_out.append((name, target, body))
    for _, target, body in plan_out:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return [name for name, _, _ in plan_out]


def _tail(text: str, lines: int) -> str:
    """Purpose: keep the last `lines` lines, where a test names its failure. Inputs: text (str),
    lines (int). Outputs: str."""
    return "\n".join(text.strip().splitlines()[-lines:])


def _run_plan(plan: Path, root: Path, deps: Any, budget: dict, skills: dict, config: dict,
              home: Path, split: Callable) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run one plan: one model call per attempt, write, test, retry.

    Inputs:
        plan (Path): the plan file.
        root (Path): the repository root.
        deps (Any): contract, tag, window, count, generate, runner (see run).
        budget, skills, config (dict): the three configuration files.
        home (Path): the home folder holding .config/aider.
        split (Callable): the bridge's split_files.

    Outputs:
        result (dict): plan, status (done, blocked, refused, skipped),
            attempts, note.
    --------------------------------------------------------------------------
    """
    result = {"plan": plan.name, "status": "skipped", "attempts": 0, "note": ""}
    contract = deps.contract(plan)
    if contract["executor"] != "local-coder":
        result["note"] = f"executor {contract['executor']}"
        return result
    tag = deps.tag(contract["role"])
    window = deps.window(tag, contract["role"])
    reserve = int(budget["reserve"]["reply_tokens"])
    targets = plan_targets(plan, root, config)
    to_create = [p.relative_to(Path(root).resolve()).as_posix() for p in targets if not p.is_file()]
    tests = _test_files(plan)
    # A plan the wrapper's audit reopened (its open lines start with `audit:`) runs as aider runs a
    # reopened plan: reopen skill and reopen message from the first attempt (plan 13 task 4).
    reopened = any(line.startswith("audit:") for line in open_lines(plan.parent / "progress.md", plan.name))
    failure = None
    for attempt in range(1, int(budget["tests"]["max_fix_attempts"]) + 1):
        stage = "reopen" if reopened or attempt > 1 else "write"
        try:
            files = file_set(plan, root, budget, skills, stage, config, home, deps.count)
        except DriverError as exc:
            return {**result, "status": "refused", "note": str(exc)}
        key = "fix_message" if failure is not None else ("reopen_message" if reopened else "write_message")
        message = config[key].format(plan=plan.name)
        prompt = build_prompt(files, root, message, config, to_create, failure)
        if deps.count(prompt) + reserve > window:
            return {**result, "status": "refused",
                    "note": f"prompt + reply {deps.count(prompt) + reserve} over window {window}"}
        result["attempts"] = attempt
        reply = deps.generate(prompt, tag, window, reserve, float(config["request_timeout_s"]))
        try:
            _write_reply(reply, root, targets, split)
        except DriverError as exc:
            failure = f"The reply was refused: {exc}"
            continue
        outputs, ok = [], True
        for test in tests:
            code, output = deps.runner([sys.executable, test], root, float(config["test_timeout_s"]))
            outputs.append(output)
            ok = ok and code == 0
        if ok:
            return {**result, "status": "done", "note": _tail(outputs[-1] if outputs else "", 1)}
        failure = _tail("\n".join(outputs), int(config["failure_lines"]))
    return {**result, "status": "blocked", "note": _tail(failure or "", 1)}


def run(progress: Path, root: Path, deps: Any, budget: dict, skills: dict, config: dict,
        home: Path | None = None, split: Callable | None = None) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run every plan of progress.md that has an open line, to the end.

    Inputs:
        progress (Path): the ledger; plans sit beside it.
        root (Path): the repository root.
        deps (Any): an object with contract(plan), tag(role), window(tag,
            role), count(text), generate(prompt, tag, window, reserve,
            timeout) and runner(command, cwd, timeout); injected (R21).
        budget, skills, config (dict): context-budget.json, skills.json and
            local-coder-driver.json content.
        home (Path | None): the home folder holding .config/aider; None is
            the user's own.
        split (Callable | None): reply splitter; None uses the bridge's.

    Outputs:
        report (dict): plans (one result each), done, blocked, refused,
            skipped counts. Ticks or blocks progress.md per plan.
    --------------------------------------------------------------------------
    """
    if split is None:
        import ollama_bridge
        split = ollama_bridge.split_files
    home = Path.home() if home is None else home
    report: dict = {"plans": []}
    for name in open_plans(progress):
        plan = progress.parent / name
        result = _run_plan(plan, root, deps, budget, skills, config, home, split)
        report["plans"].append(result)
        if result["status"] == "done":
            tick(progress, name, True, result["note"])
        elif result["status"] in ("blocked", "refused"):
            tick(progress, name, False, f"{result['status']}: {result['note']}")
    for status in ("done", "blocked", "refused", "skipped"):
        report[status] = sum(1 for p in report["plans"] if p["status"] == status)
    return report


def dry_run(progress: Path, root: Path, budget: dict, skills: dict, config: dict,
            home: Path, counter: Callable[[str], int]) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build every first prompt and count it; call nothing, write nothing (R16).

    Inputs:
        progress (Path), root (Path), budget, skills, config (dict),
        home (Path), counter (Callable): as for run.

    Outputs:
        report (dict): plans with their files and prompt_tokens, or the
            refusal reason.
    --------------------------------------------------------------------------
    """
    report: dict = {"plans": []}
    for name in open_plans(progress):
        plan = progress.parent / name
        entry: dict = {"plan": name}
        try:
            files = file_set(plan, root, budget, skills, "write", config, home, counter)
            message = config["write_message"].format(plan=name)
            prompt = build_prompt(files, root, message, config, [], None)
            entry["files"] = [str(path) for _, path in files]
            entry["prompt_tokens"] = counter(prompt)
        except DriverError as exc:
            entry["refused"] = str(exc)
        report["plans"].append(entry)
    return report


def _git(root: Path, args: list[str], config: dict, env: dict | None) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run one read or restore git command on the repository (never a
        commit, reset or push).

    Inputs:
        root (Path): the repository root.
        args (list[str]): git arguments.
        config (dict): from load_config (git_timeout_s, R10).
        env (dict | None): environment; None inherits the process one.

    Outputs:
        stdout (str): the command's output, stripped.

    Raises:
        DriverError: git is missing, times out or exits non-zero.
    --------------------------------------------------------------------------
    """
    try:
        done = subprocess.run(["git", "-C", str(root), *args], env=env, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=float(config["git_timeout_s"]))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DriverError(f"git {args[0]} failed: {exc}") from exc
    if done.returncode != 0:
        raise DriverError(f"git {args[0]} exited {done.returncode}: {done.stderr.strip()}")
    return done.stdout.strip()


_REPARSE_POINT = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT: a symlink or a junction on Windows


def _is_link(path: Path) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Tell whether a path is a link of any kind, without following it.

    Details:
        os.path.islink misses a Windows junction before Python 3.12, so the
        reparse-point attribute of lstat is read as well.

    Inputs:
        path (Path): the path to inspect.

    Outputs:
        is_link (bool): True for a symlink or a junction.
    --------------------------------------------------------------------------
    """
    import os
    if os.path.islink(path):
        return True
    try:
        attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & _REPARSE_POINT)


def state_dir(sandbox: Path) -> Path:
    """Purpose: the folder holding the audit state and backups, beside the sandbox and never
    inside it, so the auditor's writable copies and the restore data stay apart. Inputs: sandbox
    (Path). Outputs: Path."""
    sandbox = Path(sandbox).resolve()
    return sandbox.with_name(sandbox.name + ".state")


def _inside(root: Path, rel: str) -> Path | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Join a relative path to root without following any link, and keep it
        only when it stays inside root (R24).

    Inputs:
        root (Path): the resolved repository root.
        rel (str): a relative posix path from a fingerprint.

    Outputs:
        path (Path | None): the joined path, or None when it leaves root.
    --------------------------------------------------------------------------
    """
    import os
    joined = os.path.normpath(os.path.join(str(root), rel))
    if joined == str(root) or os.path.commonpath([joined, str(root)]) != str(root):
        return None
    return Path(joined)


def _fingerprint(root: Path, skip: set[Path], config: dict) -> dict[str, str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Hash every project file, as Get-ProjectFingerprint does for aider,
        never following a link.

    Details:
        A link (file symlink, directory symlink or junction) is recorded as
        its own entry 'link:<target>' and never descended into, so a link
        planted during the audit is seen as a new entry and removed itself.

    Inputs:
        root (Path): the repository root, resolved.
        skip (set[Path]): files left out (the effort's progress.md, audit.md).
        config (dict): audit_exclude dirs and name prefixes.

    Outputs:
        hashes (dict[str, str]): relative posix path -> sha256 or link marker.
    --------------------------------------------------------------------------
    """
    import hashlib
    import os
    exclude = config["audit_exclude"]

    def excluded(name: str) -> bool:
        return name in exclude["dirs"] or any(name.startswith(p) for p in exclude["prefixes"])

    hashes: dict[str, str] = {}
    for folder, dirs, files in os.walk(root, followlinks=False):
        kept = []
        for name in dirs:
            if excluded(name):
                continue
            path = Path(folder) / name
            if _is_link(path):
                hashes[path.relative_to(root).as_posix()] = "link:" + os.readlink(path)
            else:
                kept.append(name)
        dirs[:] = kept
        for name in files:
            if excluded(name):
                continue
            path = Path(folder) / name
            if path in skip:
                continue
            rel = path.relative_to(root).as_posix()
            if _is_link(path):
                hashes[rel] = "link:" + os.readlink(path)
            else:
                hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _effort_files(progress: Path) -> tuple[Path, Path]:
    """Purpose: the effort's ledger and audit report. Inputs: progress (Path). Outputs: (progress,
    audit.md) resolved."""
    progress = Path(progress).resolve()
    return progress, progress.parent / "audit.md"


def audit_begin(progress: Path, root: Path, sandbox: Path, config: dict,
                env: dict | None = None) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Open the audit sandbox: copies of progress.md and audit.md for the
        wrapper to write, and a fingerprint of the project to judge the audit
        by its effect (aider-plan.ps1 lines 776-860, R9).

    Details:
        The state and the backups go to state_dir(sandbox), a sibling the
        auditor is never given, apart from its writable copies. A process of
        the same user that rewrites state and backups consistently cannot be
        detected by a same-user tool; that residual risk is accepted, as in
        aider-setup.

    Inputs:
        progress (Path): the effort's ledger; audit.md sits beside it.
        root (Path): the repository root.
        sandbox (Path): a folder outside root.
        config (dict): from load_config.
        env (dict | None): git environment; None inherits.

    Outputs:
        report (dict): sandbox, state, files hashed, backups made.

    Raises:
        DriverError: the sandbox or its state folder is inside root (R24),
            the ledger is a link or outside root, or git fails.
    --------------------------------------------------------------------------
    """
    import shutil
    root, sandbox = Path(root).resolve(), Path(sandbox).resolve()
    state = state_dir(sandbox)
    for folder in (sandbox, state):
        if folder == root or root in folder.parents:
            raise DriverError(f"{folder} must sit outside the repository {root}")
    ledger, audit = _effort_files(progress)
    for path in (ledger, audit):
        if _is_link(path) or root not in path.parents:
            raise DriverError(f"{path} is a link or outside the repository")
    sandbox.mkdir(parents=True, exist_ok=True)
    (state / "backup").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ledger, sandbox / "progress.md")
    (sandbox / "audit.md").write_text(audit.read_text(encoding="utf-8") if audit.is_file() else "",
                                      encoding="utf-8")
    hashes = _fingerprint(root, {ledger, audit}, config)
    backups = []
    for line in _git(root, ["status", "--porcelain", "-uall"], config, env).splitlines():
        rel = line[3:].split(" -> ")[-1].strip('"')
        if rel in hashes and not hashes[rel].startswith("link:"):
            target = state / "backup" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / rel, target)
            backups.append(rel)
    head = _git(root, ["rev-parse", "HEAD"], config, env)
    (state / "state.json").write_text(json.dumps({
        "head": head, "hashes": hashes, "backups": backups,
        "ledger": str(ledger), "audit": str(audit)}), encoding="utf-8")
    return {"sandbox": str(sandbox), "state": str(state), "files": len(hashes),
            "backups": len(backups)}


def _remove(path: Path) -> None:
    """Purpose: delete a planted entry itself: a link (never its target), a file, or an empty
    folder. Inputs: path (Path). Outputs: None."""
    import os
    if _is_link(path) and path.is_dir():
        os.rmdir(path)  # removes a directory link or junction, never what it points to
    else:
        os.unlink(path)


def _replace_file(source: Path, target: Path) -> None:
    """Purpose: write source's bytes at target through a temporary file and os.replace, which
    replaces a link at target rather than writing through it. The temp file has a random name and
    is created exclusively (tempfile.mkstemp, O_EXCL), so an entry planted at a guessable name is
    never opened (security review of 018a93e). Inputs: source, target (Path). Outputs: None."""
    import os
    import tempfile
    handle, name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(Path(source).read_bytes())
        os.replace(name, target)
    except BaseException:
        if os.path.lexists(name):
            os.unlink(name)
        raise


def audit_end(progress: Path, root: Path, sandbox: Path, config: dict,
              env: dict | None = None) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Close the audit sandbox: restore every project file the audit
        touched, then copy the wrapper's audit.md and progress.md back
        (Restore-ProjectIfTouched, aider-plan.ps1 lines 863-900).

    Details:
        Every check runs before anything is changed: the ledger, the report
        and the sandbox copies must not be links and the ledger paths must
        match the ones recorded; each backup must still hash to its recorded
        value. Then a new entry is removed itself (a link is unlinked, its
        target kept); a changed or deleted file comes back from its backup
        when it was not committed, else from git. A moved HEAD is reported
        and never reset (aider runs git reset --hard here; that command is
        the owner's).

    Inputs:
        progress (Path), root (Path), sandbox (Path), config (dict),
        env (dict | None): as for audit_begin.

    Outputs:
        report (dict): touched (relative paths restored or removed) and
            head_moved (bool).

    Raises:
        DriverError: no state (audit_begin never ran), a link or a moved
            ledger, a backup that no longer matches its hash, or git fails;
            nothing is restored or copied back then.
    --------------------------------------------------------------------------
    """
    import hashlib
    root, sandbox = Path(root).resolve(), Path(sandbox).resolve()
    state_path = state_dir(sandbox) / "state.json"
    if not state_path.is_file():
        raise DriverError(f"no {state_path}: run --audit-begin first")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    ledger, audit = _effort_files(progress)
    if (str(ledger), str(audit)) != (state["ledger"], state["audit"]):
        raise DriverError("the ledger paths differ from the ones recorded at --audit-begin")
    for path in (ledger, audit, sandbox / "progress.md", sandbox / "audit.md"):
        if _is_link(path):
            raise DriverError(f"{path} became a link during the audit; nothing restored or copied")
    before, backups = state["hashes"], set(state["backups"])
    backup_root = state_dir(sandbox) / "backup"
    for rel in sorted(backups):
        copy = _inside(backup_root, rel)
        if (copy is None or _is_link(copy) or not copy.is_file()
                or hashlib.sha256(copy.read_bytes()).hexdigest() != before.get(rel)):
            raise DriverError(f"the backup of {rel} was changed during the audit; nothing restored")
    after = _fingerprint(root, {ledger, audit}, config)
    touched = []
    for rel in sorted(set(before) | set(after)):
        if before.get(rel) == after.get(rel):
            continue
        full = _inside(root, rel)
        if full is None:
            continue
        if rel in after and (rel not in before or after[rel].startswith("link:")):
            _remove(full)
        if rel in before and not before[rel].startswith("link:"):
            if rel in backups:
                full.parent.mkdir(parents=True, exist_ok=True)
                _replace_file(backup_root / rel, full)
            else:
                _git(root, ["checkout", "--", rel], config, env)
        touched.append(rel)
    head_moved = _git(root, ["rev-parse", "HEAD"], config, env) != state["head"]
    # The report comes back only now, after the restore, so restoring a trespass can never also
    # discard the auditor's own output (aider-plan.ps1, same order).
    _replace_file(sandbox / "progress.md", ledger)
    _replace_file(sandbox / "audit.md", audit)
    return {"touched": touched, "head_moved": head_moved}


def main(argv: list[str] | None = None) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Command line: run or dry-run a whole progress.md, or open and close
        the audit sandbox.

    Inputs:
        argv (list[str] | None): --progress, --root, --dry-run, --json,
            --audit-begin or --audit-end with --sandbox.

    Outputs:
        code (int): run: 0 all done or skipped, 1 a plan blocked or refused;
            --audit-end: 0 nothing touched, 1 something restored or HEAD
            moved; 2 refusal. Prints a JSON report with --json.
    --------------------------------------------------------------------------
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Run a progress.md on the local coder model.")
    parser.add_argument("--progress", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--audit-begin", action="store_true")
    parser.add_argument("--audit-end", action="store_true")
    parser.add_argument("--sandbox", type=Path)
    args = parser.parse_args(argv)
    sys.path.insert(0, str(SCRIPTS_DIR))
    if args.audit_begin or args.audit_end:
        try:
            if args.sandbox is None or (args.audit_begin and args.audit_end):
                raise DriverError("give exactly one of --audit-begin, --audit-end, with --sandbox")
            step = audit_begin if args.audit_begin else audit_end
            report = step(args.progress, args.root, args.sandbox, load_config())
        except (DriverError, OSError, ValueError, KeyError) as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(report, ensure_ascii=False, indent=2 if args.json else None))
        return 1 if report.get("touched") or report.get("head_moved") else 0
    try:
        config = load_config()
        config_dir = _source(config["aider_config_dir"], Path.home())
        budget = json.loads((config_dir / "context-budget.json").read_text(encoding="utf-8"))
        skills = json.loads((config_dir / "skills.json").read_text(encoding="utf-8"))
        if not args.progress.is_file():
            raise DriverError(f"no ledger at {args.progress}")
        deps = BridgeDeps(args.root)
        if args.dry_run:
            report = dry_run(args.progress, args.root, budget, skills, config, Path.home(), deps.count)
        else:
            report = run(args.progress, args.root, deps, budget, skills, config, Path.home())
    except (DriverError, OSError, ValueError, KeyError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.json else None))
    if args.dry_run:
        return 1 if any("refused" in p for p in report["plans"]) else 0
    return 1 if report.get("blocked") or report.get("refused") else 0


if __name__ == "__main__":
    sys.exit(main())
