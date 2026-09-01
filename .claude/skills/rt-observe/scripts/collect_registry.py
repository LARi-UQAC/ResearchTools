"""
collect_registry - is the canonical definition set itself well formed.

The mirror matrix answers "did the fan-out reach every harness". This answers the
question underneath it: is what we are fanning out actually valid. A definition
whose frontmatter does not parse mirrors perfectly into every dialect and works
in none of them, so a green matrix over a broken definition is the worst kind of
green.

Checks, per definition file: the frontmatter parses, `name:` is present and
matches the filename, `description:` is present and non-empty, and the file is
English-only per R22. The language check is ADVISORY and says so: it can see an
accented character and a French function word, and it cannot see whether a French
string is a deliberate emitted deliverable string, which R22 permits. It reports;
it never fails a run.

Standard library only. Takes its root as an argument, reads nothing else.
"""
import io
import re
from pathlib import Path

FRONTMATTER = re.compile(r"(?s)\A---\r?\n(.*?)\r?\n---\r?\n")
NAME_LINE = re.compile(r"(?m)^name:\s*(.+?)\s*$")
DESCRIPTION_LINE = re.compile(r"(?m)^description:\s*(.+?)\s*$")

# A small, deliberately conservative signal. Accented characters alone are not
# enough - an English definition may quote a French deliverable string, which R22
# allows - so a hit needs an accented character AND a French function word.
ACCENTED = re.compile(r"[à-ÿÀ-Ý]")
FRENCH_WORDS = re.compile(
    r"(?i)(?<![\w-])(le|la|les|une|des|dans|pour|avec|sans|est|sont|cette|"
    r"qui|que|plus|tout|toute|entre|selon|apres|avant|donc|ainsi)(?![\w-])")


def _strip_quotes(value):
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _inspect(path, expected_name, kind):
    """One definition file, judged. Returns a finding dict or None when clean."""
    problems = []
    advisories = []
    try:
        text = io.open(path, encoding="utf-8").read()
    except OSError as exc:
        return {"kind": kind, "name": expected_name, "path": str(path),
                "problems": ["unreadable: %s" % exc], "advisories": []}

    match = FRONTMATTER.match(text)
    if match is None:
        # Commands are allowed to ship without frontmatter: install.ps1 promotes
        # their H1 to a description. So this is only a problem for the kinds that
        # require it.
        if kind in ("agent", "skill"):
            problems.append(
                "no YAML frontmatter, so every dialect mirror of it is generated "
                "from nothing and the definition is unreachable by name")
        block = ""
    else:
        block = match.group(1)

    if block:
        name_found = NAME_LINE.search(block)
        desc_found = DESCRIPTION_LINE.search(block)
        if kind in ("agent", "skill"):
            if name_found is None:
                problems.append("frontmatter has no name:")
            elif _strip_quotes(name_found.group(1)) != expected_name:
                problems.append(
                    "frontmatter name: is %r but the file is named %r, so a "
                    "harness that indexes by one and loads by the other misses it"
                    % (_strip_quotes(name_found.group(1)), expected_name))
            if desc_found is None or not _strip_quotes(desc_found.group(1)).strip():
                problems.append(
                    "frontmatter has no non-empty description:, which is the only "
                    "text a harness sees when deciding whether to trigger it")

    body = text[match.end():] if match else text
    if ACCENTED.search(body) and FRENCH_WORDS.search(body):
        advisories.append(
            "reads as mixed-language: R22 keeps definition files English-only, so "
            "a rule stays searchable in one language. French belongs only in "
            "strings a deliverable emits, which this check cannot tell apart.")

    if not problems and not advisories:
        return None
    return {"kind": kind, "name": expected_name, "path": str(path),
            "problems": problems, "advisories": advisories}


def collect(repo_root, now=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Validate every canonical definition and report what is malformed.

    Inputs:
        repo_root (Path): repository root
        now (datetime): injected, for the receipt (R19)

    Outputs:
        state (dict): {"status", "counts", "findings", "clean"}
    --------------------------------------------------------------------------
    """
    root = Path(repo_root) / ".claude"
    if not root.is_dir():
        return {"status": "unavailable",
                "reason": "no .claude directory under %s, so there is no "
                          "canonical definition set to validate" % repo_root}

    stamp = now.isoformat(timespec="seconds") if now else None
    findings = []
    counts = {}

    for kind, folder, pattern in (("agent", "agents", "*.md"),
                                  ("command", "commands", "*.md"),
                                  ("rule", "rules", "*.md")):
        directory = root / folder
        files = sorted(directory.glob(pattern)) if directory.is_dir() else []
        counts[folder] = len(files)
        for path in files:
            finding = _inspect(path, path.stem, kind)
            if finding:
                findings.append(finding)

    skills_dir = root / "skills"
    skill_dirs = sorted(d for d in skills_dir.iterdir()
                        if d.is_dir()) if skills_dir.is_dir() else []
    counts["skills"] = 0
    for directory in skill_dirs:
        skill_md = directory / "SKILL.md"
        if not skill_md.exists():
            findings.append({
                "kind": "skill", "name": directory.name, "path": str(skill_md),
                "problems": ["the directory has no SKILL.md, so Codex cannot "
                             "index it and the installer has nothing to mirror"],
                "advisories": []})
            continue
        counts["skills"] += 1
        finding = _inspect(skill_md, directory.name, "skill")
        if finding:
            findings.append(finding)

    broken = [f for f in findings if f["problems"]]
    return {
        "status": "ok",
        "proven_by": "filesystem",
        "proven_at": stamp,
        "counts": counts,
        "findings": findings,
        "clean": not broken,
        "problem_count": len(broken),
        "advisory_count": len([f for f in findings if f["advisories"]]),
    }
