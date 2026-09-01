"""
context_budget.py - the planning-time context-budget gate for the local-model bridge
(P4 Task 5).

Task 4 measured the local model's real ceiling on this machine (16384 tokens for
ornith:9b-gpu, under q8_0 KV cache, at 100 percent GPU residency) and wrote it to
`.claude/local-model-config.json`. The head model that WRITES a plan has a large context
window; the local agent that EXECUTES a dispatched task works inside that measured, much
smaller one. Ollama 0.32.9 does not raise an error when a prompt exceeds `num_ctx` - it
silently truncates the prompt to exactly `num_ctx // 2 + 2` tokens and reports success (the
fingerprint `ollama_bridge.py` itself refuses on, at generation time). By the time that
happens, the part of the prompt most likely to be missing is the tail, which is where an
instruction usually lives. So the check belongs at planning time, before a task is ever
dispatched, not only at generation time inside the bridge.

Two CLI verbs:

  --task <spec.json>   estimates the token cost of a task bundle (a JSON manifest of named
                        items, each either inline text or a file path) and compares the
                        total against the window read from local-model-config.json, minus a
                        reserve for the model's own reply. Exits 0 and prints the remaining
                        margin when the bundle fits; exits 1 and names the single heaviest
                        item when it does not, so the caller knows what to trim or split
                        first rather than dispatching a task that will be silently truncated.

  --scan <path>         walks a directory (or checks a single file) and reports every file
                        estimated to exceed a QUARTER of the measured window - the repo rule
                        this same measurement motivates (see .claude/rules/code-style.md).
                        Sorted by descending size, so the worst offender is named first.
                        This command only NAMES files to split; it never edits or splits one.

Both verbs read the window through read_retained_num_ctx(), which is also imported by
ollama_bridge.py (see that module's DEFAULT_NUM_CTX) so the planning-time gate here and the
generation-time gate there can never silently drift apart by reading two different numbers
for the same measured fact. Both ERROR EXPLICITLY when local-model-config.json is missing,
empty, invalid JSON, or lacks the field being asked for - never falling back to a hardcoded
default. A silent default is exactly how a gate stops gating: the whole point of measuring
the window in Task 4 was so nothing downstream has to guess it again.

Token estimation here is a heuristic, not an exact count: unlike ollama_bridge.py's
probe_prompt_tokens (a real round trip to the daemon's own tokenizer), this module has no
running daemon to ask at plan time - the entire point is to decide BEFORE a task is
dispatched. CHARS_PER_TOKEN=4.0 is the commonly used rough average for English prose (about
4 characters per token), which is a realistic planning estimate rather than the bridge's
own PREFILTER_CHARS_PER_TOKEN=0.5 (that one is deliberately pessimistic by roughly 8x,
because its only job is to catch the obviously enormous before paying for a probe round
trip - it must never be the reason a prompt is accepted). This module's estimate can be
wrong in either direction for a given file; the reserve subtracted from the window in
check_task_budget, and the quarter-window margin used by --scan, both exist to leave room
for that heuristic to be imprecise without the gate becoming useless.

Standard library only: argparse, json, math, os, sys, typing, pathlib, __future__. No
`requests`, no `ollama` Python package - the same constraint the sibling scripts in this
directory (ollama_bridge.py, model_resolver.py, optimize_ollama.py) already carry.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, NamedTuple

# .../loop-engineer/scripts/context_budget.py - mirrors the layout already used by
# model_resolver.py and optimize_ollama.py in this same directory.
SCRIPTS_DIR = Path(__file__).resolve().parent
LOOP_ENGINEER_DIR = SCRIPTS_DIR.parent
CLAUDE_DIR = LOOP_ENGINEER_DIR.parent.parent

# Machine-local, gitignored (written by optimize_ollama.py --sweep, P4 Task 4). Never a
# source deliverable; a caller pointing --config elsewhere (as every test in this suite
# does) never touches this path.
DEFAULT_CONFIG_PATH = CLAUDE_DIR / "local-model-config.json"

# Rough average for English prose; see the module docstring for why this differs from
# ollama_bridge.py's own, deliberately pessimistic pre-filter ratio.
CHARS_PER_TOKEN = 4.0

# Mirrors ollama_bridge.py's own RESPONSE_RESERVE_TOKENS (1024): tokens set aside for the
# local model's own reply inside the window, so a task that fills the window with input
# alone would leave the model no room to answer. Kept as an independent constant rather
# than imported from ollama_bridge.py, because ollama_bridge.py imports THIS module (for
# read_retained_num_ctx) - importing back would create a cycle. If the bridge's own
# reserve is ever re-measured, this paired constant should be re-checked alongside it.
TASK_RESPONSE_RESERVE_TOKENS = 1024

# The repository rule this module exists to enforce (see .claude/rules/code-style.md): no
# source file should exceed a quarter of the measured window.
QUARTER_WINDOW_DIVISOR = 4

# Directories that are never source text meant for a prompt: version control internals,
# caches, virtual environments, dependency trees, and generated LaTeX output (out/, per
# this repo's own convention that LaTeX output lives in a sub-directory named out/).
EXCLUDED_DIR_NAMES = frozenset({
    ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "node_modules", "dist", "build", "out", ".vscode", ".playwright-mcp", "post-media",
})
_VENV_DIR_PREFIXES = (".venv", "venv", "env")

# Extensions that are never usefully read as prompt text; skipped without attempting a
# decode. Anything else is still subject to the UTF-8 decode check in iter_source_files,
# which is the actual safety net for a binary type not on this list.
EXCLUDED_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp",
    ".pdf", ".docx", ".xlsx", ".pptx", ".doc", ".xls", ".ppt",
    ".zip", ".7z", ".tar", ".gz", ".rar",
    ".exe", ".dll", ".so", ".bin", ".pyc", ".pyo", ".pyd",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".mp3", ".mp4", ".wav", ".avi", ".mov",
    ".db", ".sqlite", ".sqlite3", ".log",
})


class ContextBudgetError(RuntimeError):
    """Base class for every explicit refusal in this module. Never caught silently by a
    CLI path - main() reports the message and exits 1, and a direct caller of the library
    functions sees the same message via the exception itself."""


class ConfigError(ContextBudgetError):
    """Raised by read_retained_num_ctx: local-model-config.json is missing, empty, invalid
    JSON, names no matching model entry, or the entry has no usable retained_num_ctx. There
    is no fallback default anywhere in this path - that is the entire point of this gate."""


class TaskSpecError(ContextBudgetError):
    """Raised by load_task_items: the --task manifest is missing, empty, invalid JSON, has
    no items, or an item is malformed (no name, no content, or a path that cannot be read)."""


def estimate_tokens(text: str) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        A planning-time heuristic token estimate (see the module docstring for
        why this cannot be an exact count the way ollama_bridge.py's real
        probe is).

    Inputs:
        text (str): the content being sized.

    Outputs:
        result (int): ceil(len(text) / CHARS_PER_TOKEN), at least 1 for
        non-empty text, 0 for empty text.
    --------------------------------------------------------------------------
    """
    if not text:
        return 0
    return max(1, math.ceil(len(text) / CHARS_PER_TOKEN))


def read_retained_num_ctx(config_path: Path, model_tag: str | None = None) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        The single shared reader for the measured context window, imported by
        BOTH this module's own --task/--scan gates and by ollama_bridge.py's
        DEFAULT_NUM_CTX (P4 Task 5's repository rule against writing this
        logic twice). Reads models[<tag>].retained_num_ctx from
        local-model-config.json (written by optimize_ollama.py --sweep, P4
        Task 4) and never substitutes a default when the file, the entry, or
        the field is missing.

    Inputs:
        config_path (Path): path to local-model-config.json.
        model_tag (str | None): the model whose retained_num_ctx is wanted.
            When None, the config's single declared model is used; a config
            declaring zero or more than one model then requires an explicit
            tag, since there is no way to guess which one a caller means.

    Outputs:
        result (int): the measured retained_num_ctx for the resolved model.

    Raises:
        ConfigError: the file does not exist, is empty, is not valid JSON,
        declares no "models" object, the requested (or, with no tag given,
        the sole) model entry is absent, or that entry has no integer
        retained_num_ctx field. Every message names the path and, where
        relevant, the tag, so the caller sees exactly what is missing rather
        than a bare KeyError or FileNotFoundError.
    --------------------------------------------------------------------------
    """
    if not config_path.exists():
        raise ConfigError(
            f"[CONTEXT-BUDGET] no local-model-config.json at {config_path}; run "
            "optimize_ollama.py --sweep <tag> first (P4 Task 4). Refusing to assume a "
            "default context window (D2's own lesson, applied at planning time)."
        )
    raw = config_path.read_text(encoding="utf-8").strip()
    if not raw:
        raise ConfigError(f"[CONTEXT-BUDGET] {config_path} is empty; refusing to guess a window.")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"[CONTEXT-BUDGET] {config_path} is not valid JSON: {exc}") from exc

    models = data.get("models")
    if not isinstance(models, dict) or not models:
        raise ConfigError(
            f"[CONTEXT-BUDGET] {config_path} declares no models; refusing to guess a window."
        )

    if model_tag is not None:
        tag = model_tag
    elif len(models) == 1:
        tag = next(iter(models))
    else:
        raise ConfigError(
            f"[CONTEXT-BUDGET] {config_path} declares {len(models)} models "
            f"({sorted(models)}); pass an explicit model tag, there is no way to guess "
            "which one a caller means."
        )

    entry = models.get(tag)
    if not isinstance(entry, dict):
        raise ConfigError(
            f"[CONTEXT-BUDGET] {config_path} has no entry for model '{tag}'."
        )
    window = entry.get("retained_num_ctx")
    if not isinstance(window, int) or window <= 0:
        raise ConfigError(
            f"[CONTEXT-BUDGET] {config_path}'s entry for '{tag}' has no usable "
            "retained_num_ctx (missing, non-integer, or non-positive)."
        )
    return window


class TaskItemSize(NamedTuple):
    """One named, sized item inside a --task bundle. `source` is a short human-readable
    origin ('inline text' or the file path) used only in diagnostic output."""
    name: str
    tokens: int
    source: str


def load_task_items(spec_path: Path) -> list[TaskItemSize]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Parse a --task manifest into sized items. The manifest is a JSON
        object {"items": [...]}; every item carries a "name" and exactly one
        of "text" (sized directly) or "path" (read as UTF-8 and sized). A
        relative "path" is resolved against the manifest's OWN directory, so
        a manifest can reference sibling files without needing absolute
        paths spelled out by whoever wrote it.

    Inputs:
        spec_path (Path): path to the task manifest JSON file.

    Outputs:
        result (list[TaskItemSize]): one entry per declared item, in
        manifest order.

    Raises:
        TaskSpecError: the manifest is missing, empty, invalid JSON, has no
        "items" array, has an empty "items" array, or any item is malformed
        (no "name", neither or both of "text"/"path" present, or a "path"
        that does not exist or cannot be decoded as UTF-8).
    --------------------------------------------------------------------------
    """
    if not spec_path.exists():
        raise TaskSpecError(f"[CONTEXT-BUDGET] no task spec at {spec_path}.")
    raw = spec_path.read_text(encoding="utf-8").strip()
    if not raw:
        raise TaskSpecError(f"[CONTEXT-BUDGET] task spec {spec_path} is empty.")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TaskSpecError(f"[CONTEXT-BUDGET] task spec {spec_path} is not valid JSON: {exc}") from exc

    raw_items = data.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise TaskSpecError(f"[CONTEXT-BUDGET] task spec {spec_path} declares no items.")

    items: list[TaskItemSize] = []
    for i, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            raise TaskSpecError(f"[CONTEXT-BUDGET] task spec {spec_path}: item {i} is not an object.")
        name = raw_item.get("name")
        if not name:
            raise TaskSpecError(f"[CONTEXT-BUDGET] task spec {spec_path}: item {i} has no 'name'.")
        has_text = "text" in raw_item
        has_path = "path" in raw_item
        if has_text == has_path:
            raise TaskSpecError(
                f"[CONTEXT-BUDGET] task spec {spec_path}: item '{name}' must carry exactly "
                "one of 'text' or 'path'."
            )
        if has_text:
            text = str(raw_item["text"])
            items.append(TaskItemSize(name=name, tokens=estimate_tokens(text), source="inline text"))
        else:
            item_path = Path(raw_item["path"])
            if not item_path.is_absolute():
                item_path = (spec_path.parent / item_path).resolve()
            if not item_path.exists():
                raise TaskSpecError(
                    f"[CONTEXT-BUDGET] task spec {spec_path}: item '{name}' points at "
                    f"{item_path}, which does not exist."
                )
            try:
                text = item_path.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise TaskSpecError(
                    f"[CONTEXT-BUDGET] task spec {spec_path}: item '{name}' at {item_path} "
                    f"is not valid UTF-8 text: {exc}"
                ) from exc
            items.append(TaskItemSize(name=name, tokens=estimate_tokens(text), source=str(item_path)))
    return items


class BudgetResult(NamedTuple):
    """The outcome of checking a task bundle against the measured window. `margin_tokens`
    is budget_tokens - total_tokens: non-negative exactly when the bundle is compliant."""
    items: list[TaskItemSize]
    total_tokens: int
    window: int
    reserve_tokens: int
    budget_tokens: int
    margin_tokens: int
    heaviest: TaskItemSize | None

    @property
    def compliant(self) -> bool:
        return self.margin_tokens >= 0


def check_task_budget(items: list[TaskItemSize], window: int) -> BudgetResult:
    """
    --------------------------------------------------------------------------
    Purpose:
        Compare a task bundle's total estimated size against the measured
        window, minus TASK_RESPONSE_RESERVE_TOKENS held back for the local
        model's own reply. This is the planning-time counterpart of
        ollama_bridge.py's check_budget: same shape of decision (a reserve
        subtracted from the window), applied before a task is ever
        dispatched rather than at generation time.

    Inputs:
        items (list[TaskItemSize]): the sized bundle (see load_task_items).
        window (int): the measured retained_num_ctx (see
            read_retained_num_ctx).

    Outputs:
        result (BudgetResult): total, budget, margin, and the single
        heaviest item (by tokens; None only if items is empty), so a caller
        refusing an oversized task can name exactly what to trim first.
    --------------------------------------------------------------------------
    """
    total = sum(item.tokens for item in items)
    budget = window - TASK_RESPONSE_RESERVE_TOKENS
    margin = budget - total
    heaviest = max(items, key=lambda item: item.tokens, default=None)
    return BudgetResult(
        items=items, total_tokens=total, window=window,
        reserve_tokens=TASK_RESPONSE_RESERVE_TOKENS, budget_tokens=budget,
        margin_tokens=margin, heaviest=heaviest,
    )


def format_task_report(result: BudgetResult, spec_label: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Render a BudgetResult as the exact CLI message: the remaining margin
        on a compliant task, or the heaviest item on an oversized one, so the
        caller (a plan-writing head model deciding whether to dispatch)
        always sees which single item is worth trimming or splitting first.

    Inputs:
        result (BudgetResult): from check_task_budget.
        spec_label (str): a short label for the task (its manifest path),
            used only for the message.

    Outputs:
        result (str): a one-line, human-readable report.
    --------------------------------------------------------------------------
    """
    if result.compliant:
        return (
            f"OK: {spec_label} fits with margin {result.margin_tokens} token(s) "
            f"(used {result.total_tokens} of {result.budget_tokens} budget token(s); "
            f"window {result.window}, reserve {result.reserve_tokens})."
        )
    over_by = -result.margin_tokens
    heaviest = result.heaviest
    heaviest_note = (
        f"heaviest item '{heaviest.name}' (~{heaviest.tokens} token(s), {heaviest.source})"
        if heaviest is not None else "no items"
    )
    return (
        f"REFUSED: {spec_label} exceeds budget by {over_by} token(s) "
        f"(total {result.total_tokens} > budget {result.budget_tokens}; "
        f"window {result.window}, reserve {result.reserve_tokens}). "
        f"Split or trim the {heaviest_note} first."
    )


def cmd_task(spec_path: Path, config_path: Path, model_tag: str | None) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Implement --task: load the window, load and size the bundle, and
        print exactly one report line.

    Inputs:
        spec_path (Path): the --task manifest.
        config_path (Path): local-model-config.json (or an override).
        model_tag (str | None): explicit model tag, or None to use the
            config's sole declared model.

    Outputs:
        result (int): 0 when the bundle is compliant, 1 when it is oversized
        or a ConfigError/TaskSpecError was raised (message on stderr either
        way, never a bare traceback).
    --------------------------------------------------------------------------
    """
    try:
        window = read_retained_num_ctx(config_path, model_tag)
        items = load_task_items(spec_path)
    except ContextBudgetError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    result = check_task_budget(items, window)
    message = format_task_report(result, str(spec_path))
    if result.compliant:
        print(message)
        return 0
    print(message, file=sys.stderr)
    return 1


class ScanEntry(NamedTuple):
    """One file found by --scan to exceed the quarter-window threshold."""
    path: Path
    size_chars: int
    tokens: int


def _is_excluded_dir(name: str) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Decide whether a directory name is noise (version control, caches,
        virtual environments, generated output) that --scan should never
        walk into. Deliberately narrow: a dot-prefixed directory that is NOT
        on this list (".claude", ".github", ".opencode", ".continue") is
        walked normally, since agent and skill definitions live there.

    Inputs:
        name (str): a single path component (the directory's own name, not
            a full path).

    Outputs:
        result (bool): True when the directory should be pruned from the
        walk.
    --------------------------------------------------------------------------
    """
    if name in EXCLUDED_DIR_NAMES:
        return True
    lowered = name.lower()
    return any(lowered.startswith(prefix) for prefix in _VENV_DIR_PREFIXES)


def iter_source_files(root: Path) -> list[Path]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Enumerate every file under root that is plausibly prompt-able source
        text: not inside an excluded directory (_is_excluded_dir), not a
        symlink or junction (avoids a reparse-point walk loop), and not one
        of the binary extensions in EXCLUDED_EXTENSIONS. A file that passes
        this filter may still turn out not to decode as UTF-8; that is
        checked later, where the file is actually read, rather than here.

    Inputs:
        root (Path): a directory to walk, or a single file to check
            directly.

    Outputs:
        result (list[Path]): every candidate file path, in os.walk order (no
        particular sort - the caller sorts by size).
    --------------------------------------------------------------------------
    """
    if root.is_file():
        return [] if root.suffix.lower() in EXCLUDED_EXTENSIONS else [root]

    found: list[Path] = []
    for dirpath, dirnames, filenames in _walk_pruned(root):
        for filename in filenames:
            file_path = dirpath / filename
            if file_path.suffix.lower() in EXCLUDED_EXTENSIONS:
                continue
            if file_path.is_symlink():
                continue
            found.append(file_path)
    return found


def _walk_pruned(root: Path):
    """
    --------------------------------------------------------------------------
    Purpose:
        A thin wrapper around os.walk that prunes excluded directories
        in-place (the standard os.walk idiom: mutating dirnames before it is
        used to descend) and yields Path objects instead of raw strings, so
        iter_source_files stays free of os.walk's string-vs-Path bookkeeping.
        Never follows symlinks (os.walk's own default), which also keeps a
        reparse-point directory from being walked twice.

    Inputs:
        root (Path): the directory to walk.

    Outputs:
        result: yields (Path, list[str], list[str]) tuples, one per
        directory visited, mirroring os.walk's own three-tuple shape.
    --------------------------------------------------------------------------
    """
    import os
    for dirpath_str, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not _is_excluded_dir(d)]
        yield Path(dirpath_str), dirnames, filenames


def scan_oversized_files(root: Path, window: int) -> list[ScanEntry]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Implement the measurement behind --scan: every candidate file under
        root (iter_source_files) whose estimated token count exceeds a
        quarter of window is reported, sorted by descending size so the
        worst offender is named first. A file that fails to decode as UTF-8
        is skipped (it is not usable prompt text either way, so it cannot
        violate a rule about prompt-sized source files).

    Inputs:
        root (Path): directory (or single file) to scan.
        window (int): the measured retained_num_ctx.

    Outputs:
        result (list[ScanEntry]): entries with tokens > window //
        QUARTER_WINDOW_DIVISOR, sorted by size_chars descending, ties broken
        by path for a deterministic order.
    --------------------------------------------------------------------------
    """
    threshold = window // QUARTER_WINDOW_DIVISOR
    entries: list[ScanEntry] = []
    for file_path in iter_source_files(root):
        try:
            text = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        size_chars = len(text)
        tokens = estimate_tokens(text)
        if tokens > threshold:
            entries.append(ScanEntry(path=file_path, size_chars=size_chars, tokens=tokens))
    entries.sort(key=lambda entry: (-entry.size_chars, str(entry.path)))
    return entries


def cmd_scan(path: Path, config_path: Path, model_tag: str | None) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Implement --scan: print every file exceeding the quarter-window
        threshold, sorted by descending size. This command only NAMES files
        to split; it never edits or splits one (that is a separate, later
        task by design).

    Inputs:
        path (Path): directory (or single file) to scan.
        config_path (Path): local-model-config.json (or an override).
        model_tag (str | None): explicit model tag, or None to use the
            config's sole declared model.

    Outputs:
        result (int): 0 on a completed scan (whether or not any file
        exceeded the threshold), 1 on a ConfigError or a missing path
        (message on stderr, never a bare traceback).
    --------------------------------------------------------------------------
    """
    try:
        window = read_retained_num_ctx(config_path, model_tag)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not path.exists():
        print(f"[CONTEXT-BUDGET] no such path to scan: {path}", file=sys.stderr)
        return 1

    threshold = window // QUARTER_WINDOW_DIVISOR
    entries = scan_oversized_files(path, window)
    print(
        f"# scan of {path}: files exceeding a quarter of the window "
        f"({threshold} tokens; window {window})"
    )
    if not entries:
        print("(none)")
        return 0
    print("path\tchars\test_tokens")
    for entry in entries:
        print(f"{entry.path}\t{entry.size_chars}\t{entry.tokens}")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the CLI: exactly one of --task or --scan, plus an optional
        --config override (every test in this suite uses it, so no test
        touches the real, machine-local local-model-config.json) and an
        optional --model-tag for a config declaring more than one model.

    Inputs:
        none.

    Outputs:
        result (argparse.ArgumentParser): the configured parser.
    --------------------------------------------------------------------------
    """
    parser = argparse.ArgumentParser(
        description="Planning-time context-budget gate (P4 Task 5): refuses to dispatch a "
                     "task the local model's measured window cannot hold, and names "
                     "source files that already exceed a quarter of that window."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--task", type=Path, default=None, metavar="SPEC", dest="task_spec")
    group.add_argument("--scan", type=Path, default=None, metavar="PATH", dest="scan_path")
    parser.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG_PATH, dest="config_path",
        help="override local-model-config.json (default: %(default)s)",
    )
    parser.add_argument("--model-tag", type=str, default=None, dest="model_tag")
    return parser


def main(argv: list[str] | None = None) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        CLI entry point.

    Inputs:
        argv (list[str] | None): argument vector (defaults to sys.argv[1:]).

    Outputs:
        result (int): process exit code from cmd_task or cmd_scan.
    --------------------------------------------------------------------------
    """
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.task_spec is not None:
        return cmd_task(args.task_spec, args.config_path, args.model_tag)
    return cmd_scan(args.scan_path, args.config_path, args.model_tag)


if __name__ == "__main__":
    sys.exit(main())
