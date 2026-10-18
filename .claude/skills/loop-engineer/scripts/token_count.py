"""
token_count.py - one counter for any text source (local coding contract, plan 1, task 3).

Why it exists. The size ceilings of `context-budget.json` (spec, plans, progress, audit, code
file) are only enforceable if something counts tokens the same way everywhere. Three counters
already exist and none is a tool: `Get-TokenCount` in `aider-plan-core.ps1`, `count_tokens` in
`aider-rules-sync.py` and `estimate_tokens` in `context_budget.py`. They are left alone because
the aider kit is standalone. This module counts files, folders, standard input and literal text,
whatever their provenance, and says how much to trust each figure.

Three methods:

  tiktoken  an installed encoder, `cl100k_base` by default, the one aider uses. Exact for that
            encoder. Refused, never replaced by a guess, when the encoder cannot load.
  chars     characters over `chars_per_token`, rounded up. Always `exact` false. `auto` falls
            back to it when no encoder loads and says why in `note`.
  ollama    the resident model's own tokenizer, through the bridge's probe. Refused with the
            daemon's reason when it is down.

A ceiling check never treats an estimate as exact: `within_ceiling` multiplies an estimate by
the configured margin first (measured 0.99 to 1.20 real over estimated on twelve files,
2026-10-17, so 1.25), and an exact count must simply be at most the ceiling.

Exit codes of the CLI (R12): 0 ok, 2 refusal by design (a source over --max, a refused method),
1 failure (a path that does not exist). Standard library only; `tiktoken` and the bridge are
imported lazily and only when asked for.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import math
import sys
import threading
from pathlib import Path
from typing import Any, BinaryIO, Callable, Iterator, NamedTuple

SCRIPTS_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPTS_DIR / "token-count.json"
METHODS = ("auto", "tiktoken", "chars", "ollama")


class TokenCountError(ValueError):
    """A count that cannot be given honestly, with the reason."""


class TokenCount(NamedTuple):
    """One count: the figure, how it was obtained and whether it is exact."""

    tokens: int
    method: str
    exact: bool
    note: str | None


def load_config(path: Path = CONFIG_PATH) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read token-count.json, whose entries are {value, provenance} pairs (R4).

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
        config (dict): the parsed token-count.json.
        key (str): the entry name.

    Outputs:
        value (Any): the entry's "value" field.

    Raises:
        KeyError: the entry or its "value" field is absent (R3), naming the key.
    --------------------------------------------------------------------------
    """
    item = config.get(key)
    if not isinstance(item, dict) or "value" not in item:
        raise KeyError(f"token-count.json declares no usable '{key}' entry")
    return item["value"]


def _load_encoder(name: str, timeout_s: float | None = None) -> tuple[Any | None, str | None]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Load a tiktoken encoder lazily, turning every failure into a stated reason.

    Details:
        The load runs in a daemon thread and is abandoned after `timeout_s`, because an
        encoding file that is not cached is downloaded and this runs inside a hook (R10).

    Inputs:
        name (str): the encoding name, for example cl100k_base.
        timeout_s (float | None): seconds to wait, `encoder_load_timeout_s` when omitted.

    Outputs:
        result (tuple): (encoder, None) or (None, reason). A missing package, a timeout and an
        encoding file that needs the network are all reasons, never exceptions.
    --------------------------------------------------------------------------
    """
    try:
        import tiktoken  # noqa: PLC0415 - lazy by design, absent on many machines
    except ImportError:
        return None, "tiktoken is not installed"
    if timeout_s is None:
        timeout_s = config_value(load_config(), "encoder_load_timeout_s")
    box: dict[str, Any] = {}

    def load() -> None:
        try:
            box["encoder"] = tiktoken.get_encoding(name)
        except Exception as exc:  # noqa: BLE001 - network or cache failures vary by version
            box["error"] = exc

    worker = threading.Thread(target=load, daemon=True)
    worker.start()
    worker.join(timeout_s)
    if worker.is_alive():
        return None, f"tiktoken timed out loading {name} after {timeout_s} s"
    if "error" in box:
        return None, f"tiktoken could not load {name}: {box['error']}"
    return box["encoder"], None


def _ollama_probe(text: str, model_tag: str) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Ask the resident model's own tokenizer through the bridge's existing probe.

    Inputs:
        text (str): the text to count.
        model_tag (str): the Ollama tag, named by the caller (never by this module, R2).

    Outputs:
        tokens (int): the daemon's prompt_eval_count.

    Raises:
        Exception: whatever the bridge raises when the daemon is down or no window is known.
    --------------------------------------------------------------------------
    """
    import ollama_bridge  # noqa: PLC0415 - sibling module, only needed for this method

    return ollama_bridge.probe_prompt_tokens(text, model_tag,
                                             ollama_bridge._resolve_num_ctx(model_tag))


def count_text(text: str, method: str = "auto", *, encoder: Any | None = None,
               model_tag: str | None = None, config: dict | None = None,
               probe: Callable[[str, str], int] | None = None,
               encoding: str | None = None) -> TokenCount:
    """
    --------------------------------------------------------------------------
    Purpose:
        Count the tokens of one text and say how far the figure can be trusted.

    Inputs:
        text (str): the text.
        method (str): auto, tiktoken, chars or ollama.
        encoder (Any | None): an object with encode(text), injected by tests or callers.
        model_tag (str | None): required for the ollama method.
        config (dict | None): parsed token-count.json, loaded when omitted.
        probe (Callable | None): replacement for the daemon probe, for tests.
        encoding (str | None): encoding name overriding the configured one.

    Outputs:
        count (TokenCount): the figure, its method, exactness and an optional note.

    Raises:
        TokenCountError: unknown method, tiktoken asked for but not loadable, ollama asked for
        with no tag or with the daemon refusing.
    --------------------------------------------------------------------------
    """
    if method not in METHODS:
        raise TokenCountError(f"unknown method {method!r}; use one of {', '.join(METHODS)}")
    config = config if config is not None else load_config()
    if method == "ollama":
        return _count_ollama(text, model_tag, probe)
    reason = None
    if method in ("auto", "tiktoken"):
        if encoder is None:
            encoder, reason = _load_encoder(encoding or config_value(config, "encoding"))
        if encoder is not None:
            return TokenCount(len(encoder.encode(text)), "tiktoken", True, None)
        if method == "tiktoken":
            raise TokenCountError(f"method tiktoken refused: {reason}")
    estimate = math.ceil(len(text) / config_value(config, "chars_per_token"))
    note = "estimate, not exact"
    if reason:
        note += f" ({reason})"
    return TokenCount(estimate, "chars", False, note)


def _count_ollama(text: str, model_tag: str | None,
                  probe: Callable[[str, str], int] | None) -> TokenCount:
    """
    --------------------------------------------------------------------------
    Purpose:
        Count with the resident model's tokenizer.

    Inputs:
        text (str): the text.
        model_tag (str | None): the Ollama tag.
        probe (Callable | None): replacement probe, for tests.

    Outputs:
        count (TokenCount): an exact count with method ollama.

    Raises:
        TokenCountError: no tag given, or the probe failed, with its reason.
    --------------------------------------------------------------------------
    """
    if not model_tag:
        raise TokenCountError("method ollama needs --model-tag (this module never names a tag)")
    try:
        tokens = (probe or _ollama_probe)(text, model_tag)
    except Exception as exc:  # noqa: BLE001 - any daemon or bridge failure is a refusal
        raise TokenCountError(f"method ollama refused: {exc}") from exc
    return TokenCount(int(tokens), "ollama", True, None)


def within_ceiling(count: TokenCount, ceiling: int, margin: float) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Check a count against a size ceiling without trusting an estimate.

    Inputs:
        count (TokenCount): the count.
        ceiling (int): the maximum allowed.
        margin (float): factor applied to an estimate before the comparison.

    Outputs:
        ok (bool): an exact count must be at most the ceiling, an estimate times the margin
        must be.
    --------------------------------------------------------------------------
    """
    figure = count.tokens if count.exact else count.tokens * margin
    return figure <= ceiling


def _read_source(path: Path, config: dict) -> tuple[str | None, str | None]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read one file for counting, skipping and naming what cannot be counted.

    Inputs:
        path (Path): the file.
        config (dict): parsed token-count.json.

    Outputs:
        result (tuple): (text, None) or (None, skipped reason).
    --------------------------------------------------------------------------
    """
    limit = config_value(config, "max_file_bytes")
    try:
        if path.stat().st_size > limit:
            return None, f"skipped: larger than {limit} bytes"
        data = path.read_bytes()
    except OSError as exc:
        return None, f"skipped: unreadable ({exc.__class__.__name__})"
    if b"\x00" in data[:config_value(config, "binary_probe_bytes")]:
        return None, "skipped: binary file"
    return data.decode("utf-8", errors="replace"), None


def iter_sources(paths: list[str], glob: str | None, *, config: dict | None = None,
                 stdin: BinaryIO | None = None) -> Iterator[tuple[str, str | None, str | None]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Turn paths, folders and standard input into named texts.

    Details:
        Folders are walked recursively in sorted order, skipping the configured directory
        names, and the glob filters file names. A binary or oversized file is yielded with a
        reason instead of text. Bytes decode as UTF-8 with replacement, so any file counts.

    Inputs:
        paths (list[str]): files, folders, or "-" for standard input.
        glob (str | None): file-name pattern applied when walking a folder.
        config (dict | None): parsed token-count.json, loaded when omitted.
        stdin (BinaryIO | None): replacement for sys.stdin.buffer, for tests.

    Outputs:
        sources (Iterator): (name, text, skipped_reason), exactly one of the last two set.
    --------------------------------------------------------------------------
    """
    config = config if config is not None else load_config()
    skip_dirs = set(config_value(config, "skip_dir_names"))
    for raw in paths:
        if raw == "-":
            data = (stdin or sys.stdin.buffer).read()
            yield "<stdin>", data.decode("utf-8", errors="replace"), None
            continue
        path = Path(raw)
        if path.is_dir():
            for item in sorted(p for p in path.rglob("*") if p.is_file()):
                if skip_dirs & set(item.relative_to(path).parts[:-1]):
                    continue
                if glob and not fnmatch.fnmatch(item.name, glob):
                    continue
                text, why = _read_source(item, config)
                yield str(item), text, why
        elif path.is_file():
            text, why = _read_source(path, config)
            yield raw, text, why
        else:
            yield raw, None, "not found"


def _build_parser() -> argparse.ArgumentParser:
    """
    --------------------------------------------------------------------------
    Purpose:
        Declare the CLI.

    Inputs:
        None.

    Outputs:
        parser (argparse.ArgumentParser): the configured parser.
    --------------------------------------------------------------------------
    """
    parser = argparse.ArgumentParser(description="Count tokens of any text source.")
    parser.add_argument("sources", nargs="*", help="files, folders, or - for stdin")
    parser.add_argument("--text", action="append", default=[], help="literal text, repeatable")
    parser.add_argument("--glob", help="file-name pattern when walking a folder")
    parser.add_argument("--method", default="auto", choices=METHODS)
    parser.add_argument("--encoding", help="tiktoken encoding, the configured one by default")
    parser.add_argument("--model-tag", help="Ollama tag for --method ollama")
    parser.add_argument("--max", type=int, help="ceiling per source, exit 2 when one is over")
    parser.add_argument("--json", action="store_true", help="print a JSON report")
    return parser


def main(argv: list[str] | None = None, *, config: dict | None = None,
         stdin: BinaryIO | None = None) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Command-line entry point: count every source and optionally enforce a ceiling.

    Inputs:
        argv (list[str] | None): arguments, sys.argv[1:] when omitted.
        config (dict | None): parsed token-count.json, loaded when omitted.
        stdin (BinaryIO | None): replacement for sys.stdin.buffer, for tests.

    Outputs:
        exit_code (int): 0 ok, 2 refusal (over --max, refused method), 1 failure (missing path).
        A report is printed on stdout, as JSON with --json.
    --------------------------------------------------------------------------
    """
    args = _build_parser().parse_args(argv)
    config = config if config is not None else load_config()
    margin = config_value(config, "estimate_margin")
    named = [(f"<text {i}>", text, None) for i, text in enumerate(args.text, 1)]
    rows: list[dict] = []
    unchecked: list[str] = []
    code = 0
    try:
        for name, text, why in [*named, *iter_sources(args.sources, args.glob, config=config,
                                                      stdin=stdin)]:
            row: dict[str, Any] = {"name": name, "tokens": None, "method": None, "exact": None,
                                   "note": None, "skipped": why, "over": False}
            if text is not None:
                count = count_text(text, args.method, model_tag=args.model_tag, config=config,
                                   encoding=args.encoding)
                row.update(tokens=count.tokens, method=count.method, exact=count.exact,
                           note=count.note)
                if args.max is not None and not within_ceiling(count, args.max, margin):
                    row["over"] = True
                    code = max(code, 2)
            elif why == "not found":
                code = max(code, 1)
            elif args.max is not None:
                # A source too large, binary or unreadable to count cannot be shown to be
                # under the ceiling, so the check refuses instead of passing it.
                unchecked.append(name)
                code = max(code, 2)
            rows.append(row)
    except TokenCountError as exc:
        print(json.dumps({"error": str(exc)}) if args.json else f"refused: {exc}")
        return 2
    counted = [r for r in rows if r["tokens"] is not None]
    report = {"sources": rows, "total_tokens": sum(r["tokens"] for r in counted),
              "all_exact": all(r["exact"] for r in counted), "ceiling": args.max,
              "over": [r["name"] for r in rows if r["over"]], "unchecked": unchecked}
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        for r in rows:
            label = r["skipped"] or f"{r['tokens']} tokens ({r['method']}"
            label += "" if r["skipped"] else (", exact)" if r["exact"] else ", estimate)")
            print(f"{r['name']}: {label}{' OVER' if r['over'] else ''}")
        print(f"total: {report['total_tokens']} tokens")
        if unchecked:
            print("unchecked against the ceiling: " + ", ".join(unchecked))
    return code


if __name__ == "__main__":
    sys.exit(main())
