"""
collect_progress - where a plan actually stands, cross-checked against the plan.

Reads a PROGRESS.md in the shape this repository ALREADY defines, rather than
inventing a second convention: `.claude/agents/authoring-loop.md` and
`.claude/agents/thesis-to-paper.md` both specify per-step checkboxes, a
NEXT ACTION line, and state lines, with a cold-resume protocol that reads the
file and continues at NEXT ACTION.

What makes this more than a Markdown viewer is the cross-check. The phases named
in PROGRESS.md are compared against the `### Phase N` headings of the plan it
points at, and a phase present in the plan but absent from PROGRESS.md is
reported `unreported` - a state of its own, neither done nor pending. That is the
failure mode of every hand-maintained progress file: it stops being updated while
still looking complete.

What it CANNOT catch, stated so nobody assumes otherwise: a phase marked done
that was not done. Nothing in a Markdown file proves work happened. So a phase
claiming done with no evidence is rendered `unproven` rather than green, which is
the same receipt discipline the rest of the snapshot uses (R4, R13).

Marker vocabulary is borrowed from PROGRESS_RT.md, which is a different registry
for different work but had the good idea first.
"""
import io
import re
from pathlib import Path

# `- [x] Phase 3 - server, then the designed view | evidence: <what proves it>`
CHECKBOX = re.compile(
    r"(?m)^\s*[-*]\s*\[(?P<marker>[ xX~!Rr\-])\]\s*(?P<label>[^|\n]+?)"
    r"(?:\|\s*evidence:\s*(?P<evidence>[^\n]+))?\s*$")
NEXT_ACTION = re.compile(r"(?mi)^\s*\**\s*NEXT ACTION\s*\**\s*:?\s*(.+?)\s*$")
PLAN_LINE = re.compile(r"(?mi)^\s*plan:\s*(\S+)\s*$")
STATE_LINE = re.compile(r"(?m)^\s*[-*]\s*(?P<key>[A-Za-z][\w \-]{0,40}?):\s*(?P<value>[^\n]+?)\s*$")
PHASE_IN_LABEL = re.compile(r"(?i)\bphase\s+(\d+)\b")
PLAN_PHASE_HEADING = re.compile(r"(?mi)^#{2,4}\s*Phase\s+(\d+)\s*(?:[-—:]\s*(.*))?$")

MARKER_STATE = {
    "x": "done",
    "X": "done",
    " ": "todo",
    "~": "in-progress",
    "!": "blocked",
    "R": "review",
    "r": "review",
    "-": "deferred",
}


def _parse_progress(text):
    phases = {}
    order = []
    for match in CHECKBOX.finditer(text):
        label = match.group("label").strip()
        marker = match.group("marker")
        evidence = (match.group("evidence") or "").strip() or None
        number = PHASE_IN_LABEL.search(label)
        key = int(number.group(1)) if number else None
        entry = {
            "number": key,
            "label": label,
            "state": MARKER_STATE.get(marker, "todo"),
            "evidence": evidence,
        }
        # A phase claiming done with nothing to point at is not green. This is
        # the one judgement this collector makes, and it makes it consistently.
        if entry["state"] == "done" and not evidence:
            entry["state"] = "unproven"
            entry["reason"] = ("marked done with no `| evidence:` segment, so "
                               "nothing here shows the work happened")
        if key is not None and key in phases:
            continue
        if key is not None:
            phases[key] = entry
        order.append(entry)
    return phases, order


def _plan_phases(plan_path):
    try:
        text = io.open(plan_path, encoding="utf-8").read()
    except OSError:
        return None
    found = {}
    for match in PLAN_PHASE_HEADING.finditer(text):
        number = int(match.group(1))
        found.setdefault(number, (match.group(2) or "").strip())
    return found


def collect(repo_root, now=None, progress_name="PROGRESS.md"):
    """
    --------------------------------------------------------------------------
    Purpose:
        Report plan progression, and whether the progress file still matches the
        plan it claims to track.

    Inputs:
        repo_root (Path): repository root
        now (datetime): injected clock, for the receipt (R19)
        progress_name (str): the progress file's name, injected for tests

    Outputs:
        state (dict): {"status", "phases", "next_action", "plan", "crosscheck"}
    --------------------------------------------------------------------------
    """
    repo_root = Path(repo_root)
    path = repo_root / progress_name
    stamp = now.isoformat(timespec="seconds") if now else None

    if not path.exists():
        return {
            "status": "unavailable",
            "reason": "no %s at the repository root. Progression is reported from "
                      "that file in the shape authoring-loop and thesis-to-paper "
                      "already define; without it there is nothing to report and "
                      "nothing is inferred from the plan alone." % progress_name,
        }

    try:
        text = io.open(path, encoding="utf-8").read()
    except OSError as exc:
        return {"status": "unavailable", "reason": "%s unreadable: %s"
                                                   % (progress_name, exc)}

    phases, order = _parse_progress(text)
    next_action = NEXT_ACTION.search(text)
    plan_found = PLAN_LINE.search(text)

    state_lines = {}
    for match in STATE_LINE.finditer(text):
        key = match.group("key").strip().lower()
        if key in ("plan",) or key.startswith("evidence"):
            continue
        state_lines.setdefault(key, match.group("value").strip())

    crosscheck = {"status": "unavailable",
                  "reason": "no `plan:` line in %s, so the phase list cannot be "
                            "compared against the plan it tracks and a silently "
                            "abandoned phase would not show" % progress_name}
    plan_rel = None

    if plan_found:
        plan_rel = plan_found.group(1)
        plan_path = repo_root / plan_rel
        plan_phases = _plan_phases(plan_path)
        if plan_phases is None:
            crosscheck = {
                "status": "unavailable",
                "reason": "%s names plan %s, which does not exist or cannot be "
                          "read" % (progress_name, plan_rel),
            }
        else:
            unreported = sorted(n for n in plan_phases if n not in phases)
            unknown = sorted(n for n in phases if n not in plan_phases)
            for number in unreported:
                phases[number] = {
                    "number": number,
                    "label": ("Phase %d %s" % (number, plan_phases[number])).strip(),
                    "state": "unreported",
                    "evidence": None,
                    "reason": "this phase exists in the plan and has no line in "
                              "%s at all, so its state is unknown rather than "
                              "pending" % progress_name,
                }
            crosscheck = {
                "status": "ok",
                "plan": plan_rel,
                "plan_phase_count": len(plan_phases),
                "unreported": unreported,
                "unknown_to_the_plan": unknown,
                "agrees": not unreported and not unknown,
                "proven_by": plan_rel,
                "proven_at": stamp,
            }

    ordered = [phases[k] for k in sorted(phases)]
    ordered += [e for e in order if e["number"] is None]

    totals = {}
    for entry in ordered:
        totals[entry["state"]] = totals.get(entry["state"], 0) + 1

    return {
        "status": "ok",
        "proven_by": progress_name,
        "proven_at": stamp,
        "file": progress_name,
        "plan": plan_rel,
        "phases": ordered,
        "totals": totals,
        "next_action": next_action.group(1).strip() if next_action else None,
        "next_action_missing_reason": (
            None if next_action else
            "no NEXT ACTION line, so a cold session cannot tell where to resume"),
        "state_lines": state_lines,
        "crosscheck": crosscheck,
    }
