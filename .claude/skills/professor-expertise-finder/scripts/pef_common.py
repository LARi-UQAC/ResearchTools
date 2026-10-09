#!/usr/bin/env python3
"""Shared helpers for the professor-expertise-finder skill.

One implementation of the name/location normalization and the data-root
resolution, imported by table.py, exclusions.py, file_search.py, and
selections.py. Nothing here is specific to one of those scripts; a change
here changes all four call sites at once rather than drifting between
four near-copies.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import unicodedata
from pathlib import Path

DATA_ROOT_ENV = "PROFESSOR_EXPERTISE_DATA"

CONFIG_PATH = Path(__file__).resolve().parent / "pef_config.json"
COLUMN_HINTS_PATH = Path(__file__).resolve().parent / "pef_column_hints.json"
UNIVERSITY_ALIASES_PATH = Path(__file__).resolve().parent / "pef_university_aliases.json"


def data_root() -> Path:
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve the root directory the skill's data instances (location
        tables, batch registries) live under.

    Inputs:
        None (reads the PROFESSOR_EXPERTISE_DATA environment variable).

    Outputs:
        root (Path): the value of PROFESSOR_EXPERTISE_DATA when set, else
            pef_config.json's documented `default_data_root` (R1 - the
            default lives in a config file, never as a literal inside this
            script; a professor who wants a different root sets the
            environment variable rather than editing any file).

    Raises:
        FileNotFoundError, ValueError: see load_config() - raised only when
            PROFESSOR_EXPERTISE_DATA is unset, since the env var path never
            needs the config file at all.
    --------------------------------------------------------------------------
    """
    value = os.environ.get(DATA_ROOT_ENV)
    if value:
        # expanduser() too: SKILL.md and pef_config.json's own documented
        # default use the ~/... tilde form, and a user following that
        # exact syntax for the env var must not get a literal "~"
        # subdirectory of the current working directory (2026-10-08,
        # fourth code-review round).
        return Path(value).expanduser()
    return Path(load_config()["default_data_root"]).expanduser()


def load_config() -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the skill's policy constants (rubric subscore values, the
        retain threshold, the per-university cap, the data-root default,
        the recent-years window) from pef_config.json.

    Inputs:
        None.

    Outputs:
        config (dict): the parsed JSON object.

    Raises:
        FileNotFoundError: pef_config.json is missing.
        ValueError: the file exists but is not valid JSON, or a required
            key is absent (R3 - a missing configuration value is an
            explicit error, never a silent default).
    --------------------------------------------------------------------------
    """
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"missing policy config: {CONFIG_PATH}")
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed policy config {CONFIG_PATH}: {exc}") from exc
    for key in ("subscore_values", "retain_threshold", "max_per_university",
                "default_data_root", "recent_years_window"):
        if key not in config:
            raise ValueError(f"policy config {CONFIG_PATH} is missing key {key!r}")
    return config


def load_column_hints(section: str) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read one script's column-name synonym lists (e.g. exclusions.py's
        NAME_COLS) from pef_column_hints.json, so a new synonym from a
        reference file's export is a data-file edit, not a code change
        (R6 - a list of literals is data; 2026-10-08 code review finding).

    Inputs:
        section (str): "file_search" or "exclusions" - the top-level key
            of pef_column_hints.json this caller owns.

    Outputs:
        hints (dict): that section's synonym lists, e.g.
            {"name_hints": [...], "expertise_hints": [...]}.

    Raises:
        FileNotFoundError: pef_column_hints.json is missing.
        ValueError: the file is not valid JSON, or `section` is absent.
    --------------------------------------------------------------------------
    """
    if not COLUMN_HINTS_PATH.exists():
        raise FileNotFoundError(f"missing column-hints config: {COLUMN_HINTS_PATH}")
    try:
        data = json.loads(COLUMN_HINTS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed column-hints config {COLUMN_HINTS_PATH}: {exc}") from exc
    if section not in data:
        raise ValueError(f"column-hints config {COLUMN_HINTS_PATH} is missing section {section!r}")
    return data[section]


def write_json(json_path: str | None, payload: dict) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Write a command's machine-readable report, when one was requested
        (R17). One implementation shared by every script in this skill,
        rather than a near-copy per call site - a 2026-10-08 code-review
        finding noted one such copy had silently dropped
        `ensure_ascii=False`, escaping accented names in that one report
        only.

    Inputs:
        json_path (str | None): destination path, or None to skip. The
            human stdout lines are always printed regardless of this flag.
        payload (dict): the structured result to serialize.

    Outputs:
        None. Writes json_path when given, as UTF-8 with no ASCII escaping.
    --------------------------------------------------------------------------
    """
    if json_path:
        Path(json_path).write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                                    encoding="utf-8")


@contextlib.contextmanager
def atomic_open(path: Path, **open_kwargs):
    """
    --------------------------------------------------------------------------
    Purpose:
        Write a file atomically: everything goes to a sibling `.tmp` file,
        which is renamed onto `path` only once the writer finishes without
        raising. A crash or interruption mid-write therefore never leaves a
        half-written table or registry in place of the last good one -
        2026-10-09 review finding: `table.py`/`selections.py`/`exclusions.py`
        previously wrote `open(path, "w")` directly, the same gap
        `outbox_io.stage()` already closes for the Obsidian vault outbox.

    Inputs:
        path (Path): the final destination.
        **open_kwargs: forwarded to `Path.open` (e.g. newline="", encoding=).

    Outputs:
        file handle (contextmanager): yields an open file handle for `path`'s
            `.tmp` sibling; on a clean exit, `os.replace()`s it onto `path`.
            On an exception, the `.tmp` file is left for inspection rather
            than silently discarded or promoted.
    --------------------------------------------------------------------------
    """
    tmp = path.with_name(path.name + ".tmp")
    fh = tmp.open("w", **open_kwargs)
    try:
        yield fh
    finally:
        fh.close()
    os.replace(tmp, path)


def load_university_aliases() -> dict[str, str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the acronym -> canonical-full-name map used to recognize that
        "UQAC" and "Université du Québec à Chicoutimi" are the same
        institution for the no-reuse / university-cap / conflict-of-interest
        checks (2026-10-09 review finding: exact normalized-string equality
        let a spelling variant silently bypass every one of those rules).

    Inputs:
        None.

    Outputs:
        aliases (dict[str, str]): normalized acronym -> normalized canonical
            name (both already run through `norm()`).

    Raises:
        FileNotFoundError: pef_university_aliases.json is missing.
        ValueError: the file exists but is not valid JSON.
            (2026-10-09 code-review round 6: this used to return {} on
            either condition, silently degrading every university-cap,
            conflict-of-interest and no-reuse check to exact-string
            matching with no message - the same silent weaker-resource
            substitution R8 forbids. Its siblings load_config() and
            load_column_hints() already raise on the identical shape of
            failure; this now matches them (R2 - one owner, one rule).)
    --------------------------------------------------------------------------
    """
    if not UNIVERSITY_ALIASES_PATH.exists():
        raise FileNotFoundError(f"missing university-aliases config: {UNIVERSITY_ALIASES_PATH}")
    try:
        data = json.loads(UNIVERSITY_ALIASES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed university-aliases config "
                         f"{UNIVERSITY_ALIASES_PATH}: {exc}") from exc
    return {norm(k): norm(v) for k, v in data.items() if not k.startswith("_")}


def canonical_university(text: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve a university name to a canonical normalized form, so a
        well-known acronym and its full name compare equal. Anything not in
        the alias table is returned normalized but otherwise unchanged -
        this is a known-aliases lookup, not a fuzzy matcher, and never
        invents a match between two strings it does not recognize.

    Inputs:
        text (str): a free-text university name.

    Outputs:
        canonical (str): the normalized canonical name when `text`
            normalizes to a known acronym OR to a known canonical name
            itself; otherwise `norm(text)` unchanged.
    --------------------------------------------------------------------------
    """
    folded = norm(text)
    if not folded:
        return folded
    aliases = load_university_aliases()
    if folded in aliases:
        return aliases[folded]
    if folded in aliases.values():
        return folded
    return folded


def slugify(text: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Turn a free-text location or batch name into a filesystem-safe,
        accent-free slug used as a directory name.

    Inputs:
        text (str): e.g. "Canada, Ontario", "France, Île-de-France",
            "Worldwide", "Concours 2027".

    Outputs:
        slug (str): lowercase ASCII, words joined by single hyphens. A text
            with no Latin alphanumeric character at all (e.g. a location or
            batch name written only in a non-Latin script) gets a short
            hash of its own exact text instead of the bare literal
            "unspecified", so two DIFFERENT such names do not collide into
            the SAME data instance - a 2026-10-09 review finding: two
            unrelated batches named only in a non-Latin script would
            otherwise share one selections.csv and cross-contaminate the
            no-reuse rule.

    Details:
        This is a deterministic function: the SAME input text always
        produces the SAME slug, by construction. It cannot and does not
        separate two batches that are both, literally, named "" or " " -
        no hash of identical text can distinguish identical text from
        itself. That case is refused upstream, at the CLI
        (table.py/selections.py's own `--location`/`--batch`), rather than
        guessed at here (2026-10-09 code-review round 6, correcting an
        earlier overclaim that this function alone handled "left blank by
        mistake").
    --------------------------------------------------------------------------
    """
    folded = unicodedata.normalize("NFKD", text)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    folded = re.sub(r"[^a-zA-Z0-9]+", "-", folded.lower()).strip("-")
    folded = re.sub(r"-+", "-", folded)
    if folded:
        return folded
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    return f"unspecified-{digest}"


def norm(text: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Fold a name or university string for case/accent/whitespace
        -insensitive comparison.

    Inputs:
        text (str | None): any free-text field; None is treated as "".

    Outputs:
        folded (str): lowercase, accent-stripped, non-alphanumeric runs
            collapsed to a single space, trimmed.
    --------------------------------------------------------------------------
    """
    folded = unicodedata.normalize("NFKD", text or "")
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", folded.lower()).strip()


def name_key(text: str) -> tuple[str, ...]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build a word-order-insensitive comparison key for a person's name,
        so "Jane Doe" and "Doe, Jane" match.

    Inputs:
        text (str): a full name, in any word order.

    Outputs:
        key (tuple[str, ...]): the normalized words of the name, sorted.
    --------------------------------------------------------------------------
    """
    return tuple(sorted(norm(text).split()))
