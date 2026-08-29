#!/usr/bin/env python3
"""
daemon_phantoms.py - the dead-link drain of the vault event daemon.

Split from daemon_drains.py for two reasons. The file passed the 4096-token
ceiling with both drains in it, and the two drains fail differently: the
consolidation drain APPENDS an edge, which a journalled size undoes, while this
one SUBSTITUTES text mid-file, which a size cannot undo at all.

That asymmetry is why phantom repair was once ruled out of the daemon entirely.
The objection was answered rather than waived: vault_journal.snapshot keeps the
note's whole previous text before every substitution, so a bad repair is one
undo away, and nothing is applied when no journal is given.

Three further limits. The model may answer REPOINT, DROP or LEAVE. A repoint is
constrained by a schema built from the deterministic report's OWN suggestions,
so the model cannot name a note nobody proposed - the structural half of "never
invent a target", the prompt carrying the other half. A drop wraps the link in
backticks, keeping the author's words while killing the link, rather than
deleting a sentence to satisfy a link count. And a repoint goes through
vault_consolidate.apply_map, whose guardrails are already tested: it refuses any
map entry that is not a bracketed wiki-link, and any path resolving outside the
vault.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import daemon_states as ds  # noqa: E402
import vault_journal  # noqa: E402
from daemon_states import ob  # noqa: E402

CONSOLIDATE = SCRIPTS / "vault_consolidate.py"


class _null_context:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


PHANTOM_SCHEMA_BASE = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["repoint", "drop", "leave"]},
        "target": {"type": "string"},
        "why": {"type": "string"},
    },
    "required": ["action", "why"],
}

PHANTOM_PREFIX = (
    "A note links to something that does not exist in the vault. Decide what to\n"
    "do with that dead link.\n"
    "REPOINT when one of the suggested targets is plainly the note the author\n"
    "meant, the same subject under another name. Give it in target, spelled\n"
    "exactly as suggested.\n"
    "DROP when the link points at a folder, a project name, or an idea nobody\n"
    "ever wrote a note about. The words stay in the sentence, the link goes.\n"
    "LEAVE when the note it names is one somebody plainly intends to write.\n"
    "Answer only from what is shown below. Never invent a target: a dead link\n"
    "is not proof the target ever existed, and a plausible name is not a note.\n"
    "Answer with the JSON object only.\n"
)


def phantom_report(vault: Path, timeout_s: float) -> dict:
    """Run the deterministic dead-link audit and return its phantoms."""
    result = subprocess.run(
        [sys.executable, str(CONSOLIDATE), "--vault", str(vault), "--mode", "links"],
        capture_output=True, text=True, timeout=timeout_s)
    if result.returncode != 0:
        raise ds.EventRefused(f"link audit failed: {result.stderr.strip()[:200]}")
    try:
        return json.loads(result.stdout).get("phantoms", {})
    except ValueError as exc:
        raise ds.EventRefused(f"link report is not JSON: {exc}") from exc


def judge_phantom(target: str, entry: dict, model: str, window: int,
                  timeout: float) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Ask the local model about ONE dead link, from the shown evidence only.

        The suggested targets come from the deterministic report and the schema
        constrains the answer to them, so the model cannot name a note nobody
        proposed. That is the structural half of "do not invent". The prompt
        carries the other half, because a schema cannot tell a plausible guess
        from a real memory, and a phantom is not proof its target ever existed.

    Inputs:
        target (str): the unresolved link text
        entry (dict): its sources and scored suggestions, from the report
        model (str), window (int), timeout (float): the call

    Outputs:
        verdict (dict): action, optional target, why, and the phantom itself.
    --------------------------------------------------------------------------
    """
    suggestions = [s.get("target", "") for s in entry.get("suggestions", [])]
    schema = json.loads(json.dumps(PHANTOM_SCHEMA_BASE))
    if suggestions:
        schema["properties"]["target"]["enum"] = suggestions
    sources = ", ".join(entry.get("sources", []))
    named = ", ".join(suggestions) if suggestions else "none"
    prompt = (PHANTOM_PREFIX
              + f"\nDead link: [[{target}]]\n"
              + f"Notes that use it: {sources}\n"
              + f"Suggested targets: {named}\n")
    raw = ds.call_model(prompt, model, window, timeout, fmt=schema)
    try:
        verdict = json.loads(raw)
    except ValueError as exc:
        raise ds.EventRefused(f"phantom verdict is not JSON: {exc}") from exc
    verdict["phantom"] = target
    return verdict


def drain_phantoms(vault: Path, model: str, window: int, config: dict,
                   journal_path=None, lock=None) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Let the local model clean every dead link, and apply only what is safe.

    Inputs:
        vault (Path), model (str), window (int): the run
        config (dict): daemon-config.json, for the per-drain bound
        journal_path (Path | None): where the pre-edit snapshots go
        lock: a context manager serializing the writes, or None in a test

    Outputs:
        report (dict): repointed, dropped, left and errors, each with the
        model's reason. A repair is NEVER applied without a journal: the
        snapshot is what makes a mid-file substitution undoable, and without it
        this drain would be the irreversible operation it was once refused for
        being.
    --------------------------------------------------------------------------
    """
    import outbox_io
    import vault_consolidate as vc
    max_phantoms = outbox_io.require(config, "daemon", "phantom_max_per_drain")
    timeout = outbox_io.require(config, "probe", "request_timeout_s")

    report = {"repointed": [], "dropped": [], "left": [], "errors": []}
    phantoms = phantom_report(vault, timeout)
    mapping = {}
    drops = []
    touched = set()
    for target in sorted(phantoms)[:max_phantoms]:
        entry = phantoms[target]
        try:
            verdict = judge_phantom(target, entry, model, window, timeout)
        except (ds.EventRefused, ob.BridgeError) as exc:
            report["errors"].append({"phantom": target, "why": str(exc)})
            continue
        action = verdict.get("action")
        why = verdict.get("why", "")
        if action == "repoint" and verdict.get("target"):
            mapping["[[" + target + "]]"] = "[[" + verdict["target"] + "]]"
            report["repointed"].append({"phantom": target,
                                        "target": verdict["target"], "why": why})
        elif action == "drop":
            # Backticks keep the words and kill the link. Deleting the sentence
            # would remove an author's meaning to satisfy a link count. This
            # cannot go through apply_map, which by design refuses a
            # replacement that is not itself a bracketed wiki-link.
            drops.append(target)
            report["dropped"].append({"phantom": target, "why": why})
        else:
            report["left"].append({"phantom": target, "why": why})
        touched.update(entry.get("sources", []))

    if not mapping and not drops:
        return report
    if journal_path is None:
        report["errors"].append(
            {"phantom": "*", "why": "no journal: refusing an unundoable rewrite"})
        return report

    context = lock if lock is not None else _null_context()
    with context:
        for rel in sorted(touched):
            note = Path(vault) / rel
            if note.exists():
                vault_journal.snapshot(journal_path, rel,
                                       note.read_text(encoding="utf-8"),
                                       "phantom drain")
        if mapping:
            applied = vc.apply_map(str(vault), mapping, write=True)
            report["applied"] = {
                "modified": applied.get("modified", []),
                "refused_map_entries": applied.get("refused_map_entries", []),
                "refused_paths": applied.get("refused_paths", []),
            }
        if drops:
            report["neutralised"] = neutralise_links(vault, sorted(touched), drops)
            if not report["neutralised"]:
                # R9: read back the effect, never the verdict. A drop that
                # changed no note leaves the link alive, so the next audit
                # reports the same phantom and the drain never converges - six
                # times in a row on 2026-08-28, once every drain_idle_s.
                report["errors"].append({
                    "phantom": ", ".join(drops),
                    "why": "dropped, but no note changed: the link survives and "
                           "the next drain will judge it again"})
    return report


def neutralise_links(vault: Path, rels: list, targets: list) -> list:
    """
    --------------------------------------------------------------------------
    Purpose:
        Turn a dead link into plain backticked text, in the notes that use it.

        Neither apply_map nor its _rewrite_prose_preserving_code helper can do
        this: apply_map validates every replacement as a bracketed wiki-link,
        and the helper always emits one, so both can repoint and neither can
        neutralise. What is reused is the part that matters for correctness,
        vault_consolidate's CODE_REGION pattern, so a link already shown as an
        example inside backticks or a fence is left exactly as it is.

    Inputs:
        vault (Path): the vault root
        rels (list): the notes to edit, already snapshotted by the caller
        targets (list): the phantom link texts to neutralise

    Outputs:
        modified (list): the notes actually changed
    --------------------------------------------------------------------------
    """
    import vault_consolidate as vc
    patterns = [_link_pattern(t) for t in targets]
    modified = []
    for rel in rels:
        note = Path(vault) / rel
        if not note.exists():
            continue
        text = note.read_text(encoding="utf-8")
        out = []
        cursor = 0
        for region in vc.CODE_REGION.finditer(text):
            out.append(_neutralise_prose(text[cursor:region.start()], patterns))
            out.append(region.group(0))       # code regions pass through whole
            cursor = region.end()
        out.append(_neutralise_prose(text[cursor:], patterns))
        rewritten = "".join(out)
        if rewritten != text:
            note.write_text(rewritten, encoding="utf-8", newline="")
            modified.append(rel)
    return modified


def _link_pattern(target: str):
    """
    --------------------------------------------------------------------------
    Purpose:
        Match every written form of one wiki-link: bare, aliased with a pipe,
        and with a heading anchor. The phantom's NAME is only the target part,
        because vault_consolidate.LINK captures it that way, so matching the
        literal string "[[name]]" misses every link the author gave a label.

        Measured 2026-08-28 on the first live drill. Two phantoms,
        `[[Assistive-feeding-robot/Decisions|Decisions]]` and an aliased link
        to a note ending in .md, were judged DROP on six consecutive drains,
        fifteen minutes apart, and neutralised nothing each time: the literal
        replace never matched, the link survived, the next audit reported it
        again. A drop that cannot bite is worse than no drop, because the
        report says the link was handled and the drain never converges.

    Inputs:
        target (str): the phantom link text, without alias or heading

    Outputs:
        pattern (re.Pattern): matches the whole link, alias and anchor included
    --------------------------------------------------------------------------
    """
    return re.compile(r"\[\[" + re.escape(target) + r"(?:[|#][^\]]*)?\]\]")


def _neutralise_prose(segment: str, patterns: list) -> str:
    """Backtick the WHOLE matched link, so an aliased link keeps its label.
    Idempotent by construction: a link already wrapped sits inside a code span,
    and the caller hands code regions through untouched."""
    for pattern in patterns:
        segment = pattern.sub(lambda m: "`" + m.group(0) + "`", segment)
    return segment
