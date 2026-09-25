"""
aider-defect-check.py - has any of the ten known defects come back?

Reads aider-defects.json beside it and tests each signature against a project
and its run log. Exit 0 clean, 1 at least one recurrence, 2 a refusal by design
(R12).

Why a registry and not a memory: seven of the ten were invisible to inspection
and visible only to a run, and a defect nobody re-tests for is a defect that
comes back quietly. Each entry here carries a signature that can be evaluated
against artefacts the run leaves behind - a defect whose recurrence cannot be
detected is deliberately left out rather than listed and never checked.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import time
import sys

EXIT_OK = 0
EXIT_RECURRED = 1
EXIT_REFUSED = 2

HERE = pathlib.Path(__file__).resolve().parent


class Refusal(Exception):
    pass


def read_run_log(path: pathlib.Path):
    """
    --------------------------------------------------------------------------
    Purpose:
        Decode the driver's transcript, which Tee-Object writes as UTF-16, and
        report whether it looked like a single encoding.

    Inputs:
        path (Path): the run log

    Outputs:
        (text, mixed) (tuple of str and bool): the text, and whether the file
            appears to hold two encodings
    --------------------------------------------------------------------------
    """
    raw = path.read_bytes()
    if not raw:
        return "", False
    text = raw.decode("utf-16", errors="replace")
    # A UTF-8 region decoded as UTF-16 comes out as ASCII separated by the
    # bytes of its neighbours, which shows up as an implausible run of single
    # characters between spaces. Measured on the mixed log of 2026-09-05.
    spaced = len(re.findall(r"(?:[A-Za-z] ){6,}", text))
    return text, spaced > 0


def completed_plans(project: pathlib.Path):
    """The plans whose ledger section carries at least one tick.

    Anything a plan produces is judged only after the plan has run: aider
    CREATES the files it is given and fills them when it has parsed a
    complete edit block, so mid-write every one of them is zero bytes.
    """
    plans = project / "docs" / "superpowers" / "plans"
    progress = plans / "progress.md"
    if not progress.is_file():
        return []
    ledger = progress.read_text(encoding="utf-8", errors="replace")
    done = []
    for plan in sorted(plans.glob("plan*.md")):
        parts = ledger.split("## " + plan.name)
        if len(parts) < 2:
            continue
        if "[x]" in parts[1].split(chr(10) + "## ")[0]:
            done.append(plan)
    return done


def files_created_empty(project: pathlib.Path, extensions):
    """Zero-byte files a COMPLETED plan named.

    Restricted to completed plans for the reason above. Reporting a file a
    plan is still writing makes the check fire on every healthy run, which
    is the same as not having it.
    """
    named = set()
    for plan in completed_plans(project):
        text = plan.read_text(encoding="utf-8", errors="replace")
        for path in project.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in extensions:
                continue
            if ".venv" in path.parts or ".git" in path.parts:
                continue
            if path.name in text and path.stat().st_size == 0:
                named.add(str(path.relative_to(project)))
    return sorted(named)


def named_but_absent(project: pathlib.Path, names):
    """A file a plan names and the project lacks, judged only for plans that
    have actually RUN.

    Judging an unrun plan reports every file the project will ever create,
    which on a run five minutes old is all of them.
    """
    plans = project / "docs" / "superpowers" / "plans"
    if not plans.is_dir():
        return []
    progress = plans / "progress.md"
    ledger = (progress.read_text(encoding="utf-8", errors="replace")
              if progress.is_file() else "")
    wanted = set()
    for plan in sorted(plans.glob("plan*.md")):
        parts = ledger.split("## " + plan.name)
        if len(parts) < 2:
            continue
        section = parts[1].split(chr(10) + "## ")[0]
        if "[x]" not in section:
            continue
        text = plan.read_text(encoding="utf-8", errors="replace")
        for name in names:
            if name in text:
                wanted.add(name)
    return sorted(n for n in wanted if not (project / n).exists())


def bom_files(project: pathlib.Path, home: pathlib.Path, since: float = 0.0):
    """Every file THIS run wrote, checked for a byte order mark.

    `since` excludes artefacts of earlier runs. Without it the check reports
    a record written before the fix landed - history, not a recurrence.
    """
    candidates = []
    progress = project / "docs" / "superpowers" / "plans" / "progress.md"
    audit = project / "docs" / "superpowers" / "plans" / "audit.md"
    candidates += [progress, audit]
    runs = home / ".aider-plan" / "runs"
    if runs.is_dir():
        candidates += sorted(runs.glob("*.json"))
    hits = []
    for path in candidates:
        if not path.is_file() or path.stat().st_mtime < since:
            continue
        if path.read_bytes()[:3] == b"\xef\xbb\xbf":
            hits.append(str(path))
    return hits


def misplaced_audit_lines(project: pathlib.Path, run_log_text: str = ""):
    """A reopen line stranded under a plan the run has already moved past.

    NOT simply a line under a fully ticked plan: that is what a correct audit
    produces, since reopening a plan means adding an unticked line to a
    section whose other steps are done. The defect is the line surviving
    under a plan the driver has since left, where nothing will look again.
    """
    # Which plans the run has started, in order, from the driver transcript.
    started = re.findall(r"==\s*Plan:\s*(\S+)", run_log_text or "")
    latest = started[-1] if started else None
    progress = project / "docs" / "superpowers" / "plans" / "progress.md"
    if not progress.is_file():
        return []
    text = progress.read_text(encoding="utf-8", errors="replace")
    sections, current = {}, None
    for line in text.splitlines():
        heading = re.match(r"^\s*##\s+(\S+)\s*$", line)
        if heading:
            current = heading.group(1)
            sections[current] = []
            continue
        if current:
            sections[current].append(line)
    hits = []
    for name, body in sections.items():
        audit_lines = [l for l in body if re.match(r"^\s*-\s*\[ \]\s*audit:", l)]
        if not audit_lines:
            continue
        # An audit line is legitimate only while its own plan is still open. If
        # every non-audit step is ticked, the plan reads as finished and the
        # line will never be acted on - which is exactly D8.
        steps = [l for l in body if re.match(r"^\s*-\s*\[", l)
                 and not re.match(r"^\s*-\s*\[ \]\s*audit:", l)]
        if not (steps and all("[x]" in l for l in steps)):
            continue
        # Stranded only if the run has moved on. With no run log the question
        # cannot be answered, so nothing is claimed (R8: no silent guess).
        if latest is None or name == latest:
            continue
        hits.append("%s carries %d unresolved audit line(s) while the run has "
                    "moved on to %s" % (name, len(audit_lines), latest))
    return hits


def orphan_ledger_lines(project: pathlib.Path, run_log_text: str = ""):
    """Audit lines whose plan has no section in audit.md.

    The report is what a person reads in the morning; the ledger line is its
    consequence. A line whose finding was never written down leaves the run
    blocked with its reason nowhere, which is what happened to plan1 on its
    second round on 2026-09-06.

    Unlike D8 this needs no run log: both files are on disk and the question
    - does this plan have a section in the report - is answerable at any
    moment, including while the run is still going.
    """
    plans = project / "docs" / "superpowers" / "plans"
    progress = plans / "progress.md"
    report = plans / "audit.md"
    if not progress.is_file():
        return []
    # No report at all yet means no audit has run, which is not this defect.
    if not report.is_file():
        return []
    # The driver names the plans whose audit wrote nothing. Without that the
    # question cannot be answered: by round 2 every plan has a section from
    # round 1, so "has a section" proves nothing about THIS round.
    silent = set()
    for match in re.finditer(r"==\s*Plan:\s*(\S+)|the audit wrote nothing to audit\.md",
                             run_log_text or ""):
        if match.group(1):
            current_plan = match.group(1)
        else:
            silent.add(current_plan)
    if not silent:
        return []
    reported = silent
    text = progress.read_text(encoding="utf-8", errors="replace")
    hits, current = [], None
    for line in text.splitlines():
        heading = re.match(r"^\s*##\s+(\S+)\s*$", line)
        if heading:
            current = heading.group(1)
            continue
        if current and re.match(r"^\s*-\s*\[ \]\s*audit:", line):
            if current in reported:
                hits.append("%s: %s  (the audit wrote nothing that round)"
                            % (current, line.strip()))
    return hits


def audit_logs_ending_in_question(project: pathlib.Path, run_log_text: str = ""):
    """A reviewer transcript that ENDED on a question.

    Only for rounds the driver has reported finishing. A transcript read
    while the reviewer is still writing ends mid-sentence by definition, and
    a tail that happens to carry a question mark then looks exactly like the
    defect. Measured 2026-09-06: reported at 13:05, clean at 13:09.
    """
    logs = project / "docs" / "superpowers" / "plans" / ".logs"
    if not logs.is_dir():
        return []
    # How many audit rounds the driver has declared over, in order. The Nth
    # such line closes the Nth audit log.
    finished = len(re.findall(
        r"audit report grew by|the audit wrote nothing to audit\.md",
        run_log_text or ""))
    if finished == 0:
        return []
    hits = []
    for index, path in enumerate(sorted(logs.glob("*audit*.log"))):
        if index >= finished:
            break          # this round has not been declared over yet
        raw = path.read_bytes()
        if not raw:
            continue
        text = raw.decode("utf-16", errors="replace")
        tail = text.strip()[-400:]
        if re.search(r"\?\s*$", tail) or re.search(
                r"(?i)voulez-vous|shall I|would you like me to|do you want me to", tail):
            hits.append(path.name)
    return hits


def evaluate(defect, project, run_log_text, run_log_mixed, run_log_path, home,
             since=0.0):
    """Return a list of concrete findings for one defect, empty when clean."""
    sig = dict(defect["signature"])
    sig["_since"] = since
    kind = sig["kind"]

    if kind == "file_empty":
        return files_created_empty(project, set(sig["extensions"]))
    if kind == "named_but_absent":
        return named_but_absent(project, sig["names"])
    if kind == "bom":
        return bom_files(project, home, sig.get("_since", 0.0))
    if kind == "ledger_placement":
        return misplaced_audit_lines(project, run_log_text)
    if kind == "orphan_ledger_line":
        return orphan_ledger_lines(project, run_log_text)
    if kind == "audit_log_question":
        return audit_logs_ending_in_question(project, run_log_text)
    if kind == "encoding_mixed":
        return ["the run log holds two encodings"] if run_log_mixed else []
    if kind == "log_missing":
        if run_log_path is None:
            return []
        if not run_log_path.is_file():
            return ["no run log at %s" % run_log_path]
        # A run that started seconds ago has an empty log and no banner yet, so
        # asking then reports every healthy launch as a failure. Ask whether
        # the producer has had TIME to produce before asking what it produced -
        # the same correction the five over-eager signatures needed.
        min_age = sig.get("min_log_age_seconds", 0)
        if min_age:
            age = time.time() - run_log_path.stat().st_mtime
            if age < min_age:
                return []
        if "== Night run" not in run_log_text and "== Project:" not in run_log_text:
            return ["the run log stops before the driver banner"]
        return []
    if kind == "log_regex":
        if not run_log_text:
            return []
        found = re.search(sig["pattern"], run_log_text)
        return [found.group(0)[:120].replace(chr(10), " ")] if found else []

    raise Refusal("unknown signature kind %r in %s" % (kind, defect["id"]))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split(chr(10))[1])
    parser.add_argument("--project", required=True, help="the project to examine")
    parser.add_argument("--run-log", default=None, help="the driver's transcript")
    parser.add_argument("--registry", default=None, help="aider-defects.json")
    parser.add_argument("--json", dest="json_out", default=None,
                        help="write a machine-readable report here (R17)")
    args = parser.parse_args(argv)

    try:
        project = pathlib.Path(args.project)
        if not project.is_dir():
            raise Refusal("no project at %s" % project)
        registry_path = pathlib.Path(args.registry) if args.registry else HERE / "aider-defects.json"
        if not registry_path.is_file():
            raise Refusal("no defect registry at %s" % registry_path)
        registry = json.loads(registry_path.read_text(encoding="utf-8"))

        run_log_path = pathlib.Path(args.run_log) if args.run_log else None
        text, mixed = "", False
        if run_log_path and run_log_path.is_file():
            text, mixed = read_run_log(run_log_path)

        home = pathlib.Path.home()
        # Artefacts older than this run belong to a previous one, and history
        # reported as a recurrence is a false alarm.
        since = 0.0
        if run_log_path and run_log_path.is_file():
            since = run_log_path.stat().st_ctime
        results, recurred = [], 0
        for defect in registry["defects"]:
            findings = evaluate(defect, project, text, mixed, run_log_path, home,
                                since)
            results.append({"id": defect["id"], "title": defect["title"],
                            "findings": findings})
            if findings:
                recurred += 1

        print("Defect check against %s" % project)
        if run_log_path:
            print("  run log: %s%s" % (run_log_path,
                                       "" if (run_log_path and run_log_path.is_file())
                                       else "  (absent)"))
        print()
        for row in results:
            mark = "RECURRED" if row["findings"] else "clean"
            print("  %-4s %-8s %s" % (row["id"], mark, row["title"]))
            for finding in row["findings"][:6]:
                print("         -> %s" % finding)
        print()
        print("%d of %d defect(s) recurred." % (recurred, len(results)))

        if args.json_out:
            pathlib.Path(args.json_out).write_text(
                json.dumps({"project": str(project), "recurred": recurred,
                            "results": results}, indent=2),
                encoding="utf-8")
            print("report -> %s" % args.json_out)

        return EXIT_RECURRED if recurred else EXIT_OK

    except Refusal as exc:
        print("REFUSED: %s" % exc, file=sys.stderr)
        return EXIT_REFUSED
    except json.JSONDecodeError as exc:
        print("REFUSED: the registry does not parse: %s" % exc, file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
