#!/usr/bin/env python3
"""
daemon_states.py - the per-state handlers of the vault event daemon.

Split from vault_daemon.py on the state boundary, because a source file above a
quarter of the measured window stops fitting in the local model's context and in
a reviewer's head. The loop, the polling and the lifecycle live in the other
file; what one event DOES lives here.

Two states call the model, and both are grammar-constrained rather than parsed
hopefully: measured 2026-08-28 on this daemon, a JSON schema sent in the
request's `format` field was honoured, enum included
(.claude/local-capability-probe.json). The instructions are assembled as a fixed
prefix followed by the variable tail, because the same measurement showed a
shared prefix prefilling in 635 ms against 2741 ms for one never seen.

The model is never named here. ollama_bridge.resolve_model asks the resolver,
which refuses rather than substituting a weaker tag.
"""
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
BRIDGE_DIR = SCRIPTS.parents[1] / "loop-engineer" / "scripts"
for _path in (str(SCRIPTS), str(BRIDGE_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import context_budget  # noqa: E402
import ollama_bridge as ob  # noqa: E402
# Re-exported on purpose: callers and tests reach the taxonomy as ds.<name>, and
# the split is a size boundary, not a change of interface.
from daemon_taxonomy import (  # noqa: E402,F401
    EXCLUDED_FOLDERS, FOLDER_GLOSSES, PROJECTS, PROJECT_NATURES, RESOURCES,
    folder_glosses, folder_menu, technology_folders)

_FRONT = re.compile(r"(?s)\A---\n(.*?)\n---\n?")
_FIELD = re.compile(r"(?m)^([A-Za-z_]+):\s*(.+?)\s*$")
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


class EventRefused(RuntimeError):
    """The event cannot be filed and must be parked with this reason."""


def read_drop(path: Path) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Parse one raw knowledge drop: minimal machine-written frontmatter
        (source, subject, optional project) and a free-text body. A drop
        carries NO path and no directive; deciding those is the daemon's job.

    Inputs:
        path (Path): the .md file in outbox/raw/

    Outputs:
        drop (dict): source, subject, project, body, slug

    Raises:
        EventRefused: no frontmatter, or no subject to file the note under.
    --------------------------------------------------------------------------
    """
    text = path.read_text(encoding="utf-8")
    match = _FRONT.match(text)
    if not match:
        raise EventRefused("drop has no frontmatter block")
    fields = dict(_FIELD.findall(match.group(1)))
    subject = fields.get("subject", "").strip()
    if not subject:
        raise EventRefused("drop names no subject")
    return {
        "source": fields.get("source", "unknown").strip(),
        "subject": subject,
        "project": fields.get("project", "").strip(),
        "body": text[match.end():].strip(),
        "slug": slugify(subject),
    }


def slugify(subject: str) -> str:
    slug = _SLUG_STRIP.sub("-", subject.lower()).strip("-")
    return slug[:60] or "note"


def classify_schema(folders: list) -> dict:
    return {
        "type": "object",
        "properties": {
            "scope": {"type": "string", "enum": ["reusable", "project"]},
            "technology": {"type": "string", "enum": folders or ["Methode"]},
            "project": {"type": "string"},
            "confidence": {"type": "number"},
        },
        "required": ["scope", "technology", "confidence"],
    }


CLASSIFY_PREFIX = (
    "You file knowledge drops into a personal note vault.\n"
    "A REUSABLE learning is one another project would hit again: a tool that\n"
    "misbehaves, a root cause, a rule that holds next time. It is filed under\n"
    "the technology where the defect lives, never under a project name.\n"
    "A PROJECT drop is state true of one project only, and is appended to that\n"
    "project's decision log.\n"
    "Only the source names the project, and naming one does NOT decide the\n"
    "scope: a drop often names the project it came from while carrying a\n"
    "lesson any project would hit again, and that is reusable. Choose project\n"
    "only when the drop records what happened in that one project.\n"
    "When no project is named below, project state is impossible: answer\n"
    "reusable, and name the technology where the defect lives.\n"
    "Never invent a project name.\n"
    "Answer with the JSON object only. Set confidence to how sure you are, from\n"
    "0 to 1. Say a low number when the drop could plausibly go two ways: a low\n"
    "number is read as a request for a human, and costs nothing.\n"
)

DRAFT_PREFIX = (
    "You write one atomic note for a personal knowledge vault, in French.\n"
    "Structure, in this order: a YAML frontmatter block delimited by ---, with\n"
    "the keys type, projet, domaine, date, tags; then the sections Contexte,\n"
    "Probleme, Cause racine, Correctif, Reutilisation, each as a level 2\n"
    "heading.\n"
    "Style: straight quotes only, no em dash, no ellipsis character, no emoji,\n"
    "no zero-width character. Short sentences. State what was measured and\n"
    "what follows from it, never a summary of the input.\n"
    "Write no wiki link unless you are naming a note that exists.\n"
    "Output the note only, with no fence around it.\n"
)


def call_model(prompt: str, model: str, window: int, timeout: float,
               fmt=None) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        One model call: budget the prompt against the measured window, post it
        through the bridge's sole network boundary, strip any reasoning block.

    Inputs:
        prompt (str): the assembled prompt, fixed prefix first
        model (str): the resolved tag
        window (int): the measured retained window for THAT tag
        timeout (float): socket timeout in seconds
        fmt (dict | None): a JSON schema to constrain the answer

    Outputs:
        text (str): the reply body, reasoning removed

    Raises:
        EventRefused: the prompt does not fit the window. Over budget is a
        parked event, NEVER a wider window: Ollama does not reject an oversized
        prompt, it truncates it and answers anyway.
    --------------------------------------------------------------------------
    """
    items = [context_budget.TaskItemSize(
        "prompt", context_budget.estimate_tokens(prompt), "assembled prompt")]
    budget = context_budget.check_task_budget(items, window)
    if not budget.compliant:
        raise EventRefused(
            f"prompt is {budget.total_tokens} tokens against a budget of "
            f"{budget.budget_tokens}; the event is parked, not truncated")
    response = ob._post_generate(
        ob.build_payload(prompt, model, ob.DEFAULT_SEED, window, fmt=fmt),
        timeout)
    return ob.strip_reasoning((response.get("response") or "").strip())


def classify(drop: dict, folders: list, model: str, window: int,
             timeout: float) -> dict:
    """Ask which shelf the drop belongs on. The answer is schema-constrained,
    so an off-enum technology cannot come back; a daemon reading this still
    checks, because a probe is a measurement and not a guarantee."""
    import json
    prompt = (CLASSIFY_PREFIX
              + "\nFolders available, and what each one holds:\n"
              + folder_menu(folders, folder_glosses()) + "\n"
              + f"\nSubject: {drop['subject']}\n"
              + (f"Project named by the source: {drop['project']}\n"
                 if drop["project"] else "")
              + f"\n{drop['body']}\n")
    raw = call_model(prompt, model, window, timeout, fmt=classify_schema(folders))
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise EventRefused(f"classification is not JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise EventRefused("classification is not an object")
    return parsed


def route(classification: dict, drop: dict, vault: Path, folders: list,
          threshold: float, today: str) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Turn a classification into a destination, in pure Python. Everything
        this function refuses is a parked event with a stated reason, which is
        the only cheap defence against a confident wrong answer: the structural
        gates never look at truth.

    Inputs:
        classification (dict): the model's answer
        drop (dict): the parsed drop
        vault (Path): the vault root
        folders (list): the technology enum built at run time
        threshold (float): the confidence below which nothing is filed
        today (str): YYYY-MM-DD, injected so a run is reproducible (R19)

    Outputs:
        route (dict): rel, action, and the note slug

    Raises:
        EventRefused: low confidence, an off-enum technology, or a project
        scope naming no project that exists on disk.
    --------------------------------------------------------------------------
    """
    confidence = classification.get("confidence")
    if not isinstance(confidence, (int, float)):
        raise EventRefused("classification carries no confidence")
    if confidence < threshold:
        raise EventRefused(
            f"confidence {confidence} is under the {threshold} threshold")
    scope = classification.get("scope")
    if scope == "reusable":
        technology = classification.get("technology")
        if technology not in folders:
            raise EventRefused(f"technology {technology!r} is not a live folder")
        rel = unique_note_path(vault, f"{RESOURCES}/{technology}", drop["slug"],
                               today)
        return {"rel": rel, "action": "create", "slug": drop["slug"]}
    if scope == "project":
        # The SOURCE decides which project a write lands in, never the model.
        # Measured 2026-08-28 on the first live drill: asked to classify a drop
        # that declared no project at all, the local model answered scope
        # "project" with an invented project name, at 0.90 confidence; and a
        # drop that did declare "ResearchTools" came back as "ResearchTools -
        # <its own subject>". Both were above the 0.7 threshold, so confidence
        # caught neither, and routing a write from either string appends a
        # learning to a decision log nobody chose. What the model answered is
        # kept in the event report and used for nothing.
        name = drop["project"]
        if not name:
            raise EventRefused(
                "project scope but the source declared no project; a project "
                "named only by the model is never used to route a write")
        for nature in PROJECT_NATURES:
            candidate = Path(vault) / PROJECTS / nature / name
            if candidate.is_dir():
                return {"rel": f"{PROJECTS}/{nature}/{name}/Decisions.md",
                        "action": "append", "slug": drop["slug"]}
        raise EventRefused(f"project {name!r} has no directory in {PROJECTS}")
    raise EventRefused(f"scope {scope!r} is neither reusable nor project")


def unique_note_path(vault: Path, folder: str, slug: str, today: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Never append a new learning into an existing note that happens to share
        its name. Merging two unrelated learnings into one file is worse than a
        near-duplicate, and relating near-duplicates is the consolidation
        drain's job, not the filer's. The date suffix keeps every drop atomic.

    Inputs:
        vault (Path): the vault root
        folder (str): the vault-relative destination folder
        slug (str): the note slug
        today (str): YYYY-MM-DD, injected

    Outputs:
        rel (str): a vault-relative path no note currently occupies
    --------------------------------------------------------------------------
    """
    root = Path(vault)
    if not (root / folder / f"{slug}.md").exists():
        return f"{folder}/{slug}.md"
    dated = f"{slug}-{today}"
    if not (root / folder / f"{dated}.md").exists():
        return f"{folder}/{dated}.md"
    counter = 2
    while (root / folder / f"{dated}-{counter}.md").exists():
        counter += 1
    return f"{folder}/{dated}-{counter}.md"


def unresolved_links(vault: Path, body: str) -> list:
    """Every wiki-link in a draft that designates no existing note. Obsidian
    links notes, not folders, so a link to a folder name can never resolve.
    Code spans and fences are stripped first, since an illustrative link
    wrapped in backticks is deliberately not a live link."""
    import outbox_io
    prose = outbox_io.CODE_SPAN.sub(" ", outbox_io.FENCE.sub(" ", body))
    targets = {m.strip() for m in outbox_io.LINK.findall(prose)}
    if not targets:
        return []
    try:
        known = outbox_io.vault_link_names(Path(vault))
    except OSError:
        return []
    return sorted(t for t in targets if t not in known)


def draft(drop: dict, route_info: dict, classification: dict, model: str,
          window: int, timeout: float, today: str, max_attempts: int,
          vault=None) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Write the note body locally, and reject a body carrying a banned
        character instead of patching it in place. A patched body hides that
        the model does not follow the style paragraph; a retry measures it.

    Inputs:
        drop (dict), route_info (dict), classification (dict): the event
        model (str), window (int), timeout (float): the call
        today (str): the note's date, injected
        max_attempts (int): finite retry budget (R10)

    Outputs:
        body (str): the note text

    Raises:
        EventRefused: every attempt violated style hygiene.
    --------------------------------------------------------------------------
    """
    prompt = (DRAFT_PREFIX
              + f"\ntype: {'apprentissage' if classification.get('scope') == 'reusable' else 'decision'}\n"
              + f"date: {today}\n"
              + f"destination: {route_info['rel']}\n"
              + f"\nSubject: {drop['subject']}\n\n{drop['body']}\n")
    violations = []
    for _ in range(max_attempts):
        body = call_model(prompt, model, window, timeout)
        violations = ob.scan_hygiene(body)
        if not violations and body.strip():
            return body.strip() + "\n"
    raise EventRefused(
        "draft never passed style hygiene: " + "; ".join(violations or ["empty body"]))
