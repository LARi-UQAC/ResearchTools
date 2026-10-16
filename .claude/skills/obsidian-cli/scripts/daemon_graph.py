#!/usr/bin/env python3
"""
daemon_graph.py - the voice-ask queue's read-only link to a project's own
code graph (graphify).

Mirrors daemon_ask.py's seam: that module answers "what happens to a
question about the vault", this one answers "what happens to the question's
matched PROJECT" - turning the question into English keywords a graph can
search, resolving the vault hit that answered it to a repository via that
project's own `repo:` frontmatter property, and running `graphify query`
read-only against it. Neither module imports the other's prompts.

Governance (.claude/rules/security.md "Graph access safety"): the only
caller of this module is daemon_ask.answer(), itself reached only for an ask
request that already declared `from: rt-dashboard` (daemon_ask.read_request's
gate). This module never runs `graphify update` or `graphify save-result` -
only `query` - and never writes to the vault or to graphify-out/ itself.

A vault note's `repo:` property is untrusted input (R24): `_resolve_repo_claim`
only runs `graphify query` with a `repo:` value's resolved path as cwd when
that path also appears in `load_allowed_roots()`'s machine-local, gitignored
allowlist (`.claude/local-ask-graph-roots.json`) - absent or unparsable
degrades to an empty allowlist, refusing every claim, never to an open one.
"""
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import daemon_states  # noqa: E402
import outbox_io  # noqa: E402

# Same shape as daemon_states._FRONT / _FIELD (the one simple frontmatter
# reader this skill already has for `key: value` blocks): a `---` delimited
# header, then one `key: value` per line. Kept as its own copy rather than
# importing daemon_states' private names, since each reader looks for a
# different key and a shared regex module would be one more file for a
# two-line pattern.
import re  # noqa: E402

_FRONT = re.compile(r"(?s)\A---\n(.*?)\n---\n")
_FIELD = re.compile(r"(?m)^(\w+):\s*(.*)$")


class GraphRefused(RuntimeError):
    """The graph cannot be reached or queried; the caller reports a
    catalogue sentence instead of this message (daemon_ask.graph_sentence)."""


def keywords_schema() -> dict:
    """The JSON schema constraining extract_keywords' model call, same shape
    as daemon_states.classify_schema."""
    return {
        "type": "object",
        "properties": {
            "keywords_en": {
                "type": "array",
                "items": {"type": "string", "minLength": 1, "maxLength": 40},
                "minItems": 1,
            },
            "question_language": {"type": "string", "enum": ["fr", "en"]},
        },
        "required": ["keywords_en", "question_language"],
    }


KEYWORDS_PREFIX = (
    "You turn a spoken question about a software project into English "
    "keywords for a code search tool. The tool's index only understands "
    "English code-identifier-style terms (file names, function names, "
    "module names), never the question's own language. Reply with a short "
    "list of such keywords, and name the language the question below is "
    "actually written in.\n"
)


def extract_keywords(question: str, model: str, window: int, timeout: float,
                     max_keywords: int) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Turn a voice question into English keywords for `graphify query`,
        via one schema-constrained model call.

    Inputs:
        question (str): the caller's question, already stripped
        model (str): the resolved writer-role tag
        window (int): the measured retained window for that tag
        timeout (float): socket timeout in seconds (R10)
        max_keywords (int): cap on the returned keyword count (R0)

    Outputs:
        result (dict): {"keywords_en": [str, ...], "question_language":
        "fr" | "en"}, truncated to `max_keywords` entries in the model's own
        order.

    Raises:
        GraphRefused: the model call failed (daemon_states.ob.BridgeError or
        daemon_states.EventRefused), the reply is not JSON, is not an
        object, names no non-empty list of keywords, or names a language
        outside the schema's own enum (a model that ignored the schema).
    --------------------------------------------------------------------------
    """
    prompt = KEYWORDS_PREFIX + f"\nQuestion: {question}\n"
    try:
        raw = daemon_states.call_model(prompt, model, window, timeout,
                                       fmt=keywords_schema())
    except (daemon_states.ob.BridgeError, daemon_states.EventRefused) as exc:
        raise GraphRefused(f"keyword extraction failed: {exc}") from exc
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise GraphRefused(
            f"keyword extraction reply is not JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise GraphRefused("keyword extraction reply is not an object")
    keywords = parsed.get("keywords_en")
    if not isinstance(keywords, list) or not keywords or not all(
            isinstance(k, str) and k.strip() for k in keywords):
        raise GraphRefused(
            "keyword extraction returned no keywords")
    language = parsed.get("question_language")
    if language not in ("fr", "en"):
        raise GraphRefused(
            f"keyword extraction named an unsupported language {language!r}")
    return {"keywords_en": keywords[:max_keywords],
           "question_language": language}


def read_repo_property(index_path: Path) -> "str | None":
    """
    --------------------------------------------------------------------------
    Purpose:
        Read one `index.md`'s `repo:` frontmatter value, as a probe rather
        than a parse the caller must separately guard: every failure mode
        (missing file, no frontmatter, no `repo:` key, a blank value) is
        `None`, never an exception.

    Inputs:
        index_path (Path): the candidate `index.md`

    Outputs:
        value (str | None): the raw `repo:` value, or None.
    --------------------------------------------------------------------------
    """
    try:
        text = index_path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = _FRONT.match(text)
    if not match:
        return None
    fields = dict(_FIELD.findall(match.group(1)))
    value = fields.get("repo", "").strip()
    return value or None


_ALLOWED_ROOTS_FILENAME = "local-ask-graph-roots.json"


def allowed_roots_path() -> Path:
    """The machine-local allowlist's fixed location, `.claude/` beside the
    repo's other machine-local config (`local-model-config.json` and
    siblings), derived from this file's own location rather than a literal
    (R18)."""
    return SCRIPTS.parents[2] / _ALLOWED_ROOTS_FILENAME


def load_allowed_roots(path: "Path | None" = None) -> list:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the machine-local allowlist of repository roots daemon_graph may
        point `graphify query`'s cwd at (R24). A vault note's `repo:` value is
        untrusted input - it may name any absolute path a local process can
        write, including a future consolidation or phantom-repair edit - so
        the daemon trusts only a root that ALSO appears here, a file the vault
        itself cannot write.

    Details:
        Gitignored and absent from a fresh clone by design: the mapped repos
        sit under this operator's own account directory, and committing their
        absolute paths to the public repo would leak the account path
        (R34, `verify-no-personal-data.ps1`). An absent or unparsable file
        degrades to an empty allowlist (R8: fail closed, not fail open) rather
        than raising, since every ask call must still answer the vault part
        even when the graph part cannot be trusted this call.

    Inputs:
        path (Path | None): override for tests; defaults to
        `.claude/local-ask-graph-roots.json`.

    Outputs:
        roots (list[Path]): each configured entry, resolved once. Empty when
        the file is absent, is not valid JSON, is not a `{"allowed_roots":
        [...]}` object, or names no usable string entries.
    --------------------------------------------------------------------------
    """
    target = path or allowed_roots_path()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries = raw.get("allowed_roots") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        return []
    return [Path(p).resolve() for p in entries
           if isinstance(p, str) and p.strip()]


def _resolve_repo_claim(value: str, allowed_roots: list) -> dict:
    """One `repo:` value's own validation, independent of which hit or
    folder produced it: absolute, resolves inside the configured allowlist
    (R24 - resolved first, then compared, never clamped), exists, holds a
    graph."""
    path = Path(value)
    if not path.is_absolute():
        return {"entity": None, "reason": f"repo: '{value}' is not absolute"}
    resolved = path.resolve()
    if not allowed_roots:
        return {"entity": None,
               "reason": "no repository is allowlisted "
                         f"({_ALLOWED_ROOTS_FILENAME} is absent, unparsable, "
                         "or empty) - refusing by default"}
    if resolved not in allowed_roots:
        return {"entity": None,
               "reason": f"repo: '{value}' resolves outside the configured "
                         "allowlist"}
    if not resolved.is_dir():
        return {"entity": None,
               "reason": f"repo: '{value}' does not exist"}
    if not (resolved / "graphify-out" / "graph.json").is_file():
        return {"entity": None,
               "reason": f"repo: '{value}' has no graph "
                         "(graphify-out/graph.json)"}
    return {"repo": resolved}


def _resolve_one_hit(vault: Path, hit: dict, search_roots: list,
                     allowed_roots: list) -> dict:
    """Walk one hit's path upward from its own folder toward its matching
    search root, returning the first index.md's repo: claim (valid or not -
    the nearest claim decides, never a more distant one)."""
    rel_parts = Path(hit["rel"]).parts
    matching_root = None
    for root in search_roots:
        root_parts = Path(root).parts
        if rel_parts[:len(root_parts)] == root_parts:
            matching_root = root_parts
            break
    if matching_root is None:
        return {"entity": None,
               "reason": f"{hit['rel']} is outside the configured search "
                         "roots"}
    folder_parts = rel_parts[:-1]  # the note's own folder, note excluded
    for depth in range(len(folder_parts), len(matching_root) - 1, -1):
        folder_rel = Path(*folder_parts[:depth]) if depth else Path(".")
        index_path = vault / folder_rel / "index.md"
        value = read_repo_property(index_path)
        if value is None:
            continue
        claim = _resolve_repo_claim(value, allowed_roots)
        if "repo" in claim:
            return {"entity": Path(folder_rel).name, "repo": claim["repo"]}
        return claim
    return {"entity": None,
           "reason": f"{hit['rel']}: no repo: property found above it"}


def entity_repo(vault: Path, hits: list, search_roots: list,
               allowed_roots: "list | None" = None) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve the vault's own best-matching hits to the repository of the
        project they belong to, via that project's `index.md` `repo:`
        property.

    Inputs:
        vault (Path): the vault root
        hits (list): daemon_ask.search_vault's own hit shape, in rank order
        search_roots (list): the configured vault-relative search roots
        allowed_roots (list[Path] | None): the resolved allowlist a `repo:`
        claim must land inside (R24); `None` loads `load_allowed_roots()`'s
        default location, so a caller can inject a fixture allowlist in tests
        without touching the real machine-local file.

    Outputs:
        result (dict): {"entity": <folder name>, "repo": Path} on success,
        trying each hit in order and returning on the FIRST one that
        resolves; {"entity": None, "reason": str} when none does (the
        reason of the LAST hit tried, or "no vault hit to resolve" when
        `hits` is empty).
    --------------------------------------------------------------------------
    """
    if not hits:
        return {"entity": None, "reason": "no vault hit to resolve"}
    if allowed_roots is None:
        allowed_roots = load_allowed_roots()
    last_reason = None
    for hit in hits:
        result = _resolve_one_hit(vault, hit, search_roots, allowed_roots)
        if "repo" in result:
            return result
        last_reason = result["reason"]
    return {"entity": None, "reason": last_reason}


def query_graph(repo: Path, keywords: list, budget_tokens: int,
                max_chars: int, timeout: float) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run `graphify query` read-only against one resolved repository.
        Never runs `update` or `save-result` - the only subcommand this
        function ever builds is `query`.

    Inputs:
        repo (Path): the resolved, validated repository root
        keywords (list): English keyword strings, joined with single spaces
        budget_tokens (int): forwarded as `--budget` (R0)
        max_chars (int): cap on the returned text (R0)
        timeout (float): the subprocess timeout in seconds (R10)

    Outputs:
        result (dict): {"text": str, "built": "<ISO date or None>"} on
        success, or {"text": None, "reason": str} on failure (the CLI not
        on PATH, a timeout, a non-zero exit, empty output, or every keyword
        refused - see Details).

    Details:
        `keywords` comes from a local model's own output, not a fixed
        catalogue, and the joined string becomes the ONE positional argv
        element graphify's "query" subcommand reads. A keyword beginning
        with "-" could be read as an option by whatever argument parser
        graphify uses even as a single token (true of argparse positionals,
        for instance) - unverifiable here since the CLI is not installed in
        this sandbox (R14), so rather than guess at a `--` separator this
        refuses any keyword starting with "-" before the join, which needs
        no knowledge of graphify's own parsing.
    --------------------------------------------------------------------------
    """
    binary = shutil.which("graphify")
    if binary is None:
        return {"text": None,
               "reason": "graphify CLI not found on PATH"}
    safe_keywords = [k for k in keywords if not k.startswith("-")]
    if not safe_keywords:
        return {"text": None,
               "reason": "every keyword begins with '-', refused rather "
                         "than risk it being read as an option by graphify"}
    argv = [binary, "query", " ".join(safe_keywords), "--budget",
           str(budget_tokens)]
    try:
        result = subprocess.run(argv, cwd=repo, timeout=timeout,
                                capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return {"text": None,
               "reason": f"graphify query timed out after {timeout}s"}
    except OSError as exc:
        return {"text": None, "reason": f"graphify query failed: {exc}"}
    if result.returncode != 0:
        return {"text": None,
               "reason": f"graphify query exited {result.returncode}: "
                         f"{outbox_io.tail(result.stderr)}"}
    text = (result.stdout or "").strip()
    if not text:
        return {"text": None,
               "reason": f"graphify query returned no output for "
                         f"{' '.join(safe_keywords)!r}"}
    built = None
    try:
        mtime = (repo / "graphify-out" / "graph.json").stat().st_mtime
        built = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
    except OSError:
        pass
    return {"text": text[:max_chars], "built": built}
