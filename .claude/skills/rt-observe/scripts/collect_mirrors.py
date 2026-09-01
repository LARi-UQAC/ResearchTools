"""
collect_mirrors - the mirror matrix: canonical definitions against harness dialects.

Stage 1 of the rt-observe snapshot, and the part of it that needs no harness at
all: it compares files in a clone. A lab member on Codex, on Linux, with no
Claude Code and no PowerShell, gets this panel complete.

The question it answers is not "is this cell empty". Emptiness is easy to see and
means nothing on its own. The question is WHY it is empty, and there are two
answers that look identical on disk and could not be more different: the
generator skipped it deliberately, or the mirror was lost. Intent comes from
mirror-policy.json, presence comes from the filesystem, and what the last
generation actually did comes from .rt-mirrors.json when an install wrote one.

Standard library only, no network, no subprocess. Every path is taken as an
argument rather than read from the environment, so the suite can drive it against
a fixture tree under tempfile and never touch the live machine (R21).
"""
import hashlib
import io
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

# Cell states. Distinguishing the first two from LOST is the entire point of the
# matrix, so they are named rather than encoded as booleans (R5).
OK = "ok"                     # present, and nothing says it is degraded
BY_DESIGN = "by-design"       # the generator deliberately skips it
STUBBED = "stubbed"           # present, reduced to a pointer: body over the ceiling
TRIMMED = "trimmed"           # present, description shortened to fit a list budget
STALE = "stale"               # present, but the canonical source is newer
LOST = "lost"                 # absent with no design reason
ORPHAN = "orphan"             # present in the dialect with no canonical source
UNKNOWN = "unknown"           # the dialect is not installed here; nothing can be said

FRONTMATTER = re.compile(r"(?s)\A---\r?\n(.*?)\r?\n---\r?\n")
DESCRIPTION_LINE = re.compile(r"(?m)^description:\s*(.+)$")


class PolicyError(RuntimeError):
    """The policy is missing or malformed. Never defaulted: a matrix built on an
    invented policy would report by-design and lost interchangeably, which is
    worse than reporting nothing (R3, R8)."""


def _read_text(path):
    return io.open(path, encoding="utf-8").read()


def _read_json(path):
    """Reads UTF-8 with or without a BOM.

    .rt-green.json carries a BOM (measured 2026-08-30, PowerShell wrote it) and
    plain utf-8 raises on it. utf-8-sig reads both, so it is the only correct
    choice for any file this repository's PowerShell may have written.
    """
    return json.loads(io.open(path, encoding="utf-8-sig").read())


def load_policy(repo_root):
    """
    --------------------------------------------------------------------------
    Purpose:
        Read mirror-policy.json, the single declaration of generator intent.

    Inputs:
        repo_root (Path): the repository root holding mirror-policy.json

    Outputs:
        policy (dict): the parsed policy

    Raises:
        PolicyError: named and explicit when the file is absent or unparsable
    --------------------------------------------------------------------------
    """
    path = Path(repo_root) / "mirror-policy.json"
    if not path.exists():
        raise PolicyError(
            "mirror-policy.json not found at %s. It is the only declaration of "
            "which empty mirror cells are deliberate; without it the matrix "
            "cannot tell a by-design skip from a lost mirror." % path)
    try:
        return _read_json(path)
    except ValueError as exc:
        raise PolicyError("mirror-policy.json does not parse: %s" % exc)


def policy_hash(repo_root):
    path = Path(repo_root) / "mirror-policy.json"
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def canonical_definitions(repo_root):
    """
    --------------------------------------------------------------------------
    Purpose:
        Enumerate the canonical definition set: the rows of the matrix.

    Inputs:
        repo_root (Path): repository root

    Outputs:
        definitions (dict): {"agents": [names], "skills": [...], "commands":
                            [...], "rules": [...]}, each sorted
    --------------------------------------------------------------------------
    """
    root = Path(repo_root) / ".claude"
    agents = sorted(p.stem for p in (root / "agents").glob("*.md")) \
        if (root / "agents").is_dir() else []
    commands = sorted(p.stem for p in (root / "commands").glob("*.md")) \
        if (root / "commands").is_dir() else []
    rules = sorted(p.stem for p in (root / "rules").glob("*.md")) \
        if (root / "rules").is_dir() else []
    skills = []
    if (root / "skills").is_dir():
        skills = sorted(d.name for d in (root / "skills").iterdir()
                        if d.is_dir() and (d / "SKILL.md").exists())
    return {"agents": agents, "skills": skills, "commands": commands, "rules": rules}


def canonical_path(repo_root, source, name):
    root = Path(repo_root) / ".claude"
    if source == "agents":
        return root / "agents" / (name + ".md")
    if source == "commands":
        return root / "commands" / (name + ".md")
    if source == "rules":
        return root / "rules" / (name + ".md")
    if source == "skills":
        return root / "skills" / name / "SKILL.md"
    return None


def _expand(path_template, repo_root, home, name):
    """Resolve a target path template against this machine.

    `~` and `%APPDATA%` are expanded from the injected home rather than from the
    process environment, so a test can point the whole resolution at a temporary
    directory (R21). Resolve first, then compare (R24).
    """
    text = path_template.replace("{name}", name)
    if text.startswith("~/"):
        base = Path(home) / text[2:]
    elif "%APPDATA%" in text:
        base = Path(str(text).replace("%APPDATA%", str(Path(home) / "AppData" / "Roaming")))
    else:
        base = Path(repo_root) / text
    return Path(os.path.normpath(str(base)))


def _mirror_description(path):
    """The description a dialect mirror actually carries, for the trim check."""
    try:
        text = _read_text(path)
    except OSError:
        return None
    match = FRONTMATTER.match(text)
    block = match.group(1) if match else text
    found = DESCRIPTION_LINE.search(block)
    if not found:
        return None
    value = found.group(1).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value


def _canonical_description(path):
    return _mirror_description(path)


def load_manifest(repo_root):
    """.rt-mirrors.json if an install wrote one. An ENRICHMENT, never required."""
    path = Path(repo_root) / ".rt-mirrors.json"
    if not path.exists():
        return None
    try:
        return _read_json(path)
    except ValueError:
        return None


def _manifest_index(manifest):
    index = {}
    if not manifest:
        return index
    for record in manifest.get("verdicts", []):
        index[(record.get("target"), record.get("name"))] = record
    return index


def _receipt(value, proven_by, proven_at=None):
    """Every value carries its provenance. A bare state is never emitted."""
    return {"value": value, "proven_by": proven_by, "proven_at": proven_at}


def _skip_names(policy, target):
    key = target.get("skip_list")
    if not key:
        return set()
    entry = policy.get("skips", {}).get(key, {})
    return set(entry.get("values", []))


def _orphans_by_design(policy, target_id):
    entry = policy.get("orphans_by_design", {}).get(target_id, {})
    return set(entry.get("values", []))


def _target_root(target, repo_root, home):
    """The directory a target writes into, for the not-installed check.

    Split on the {name} placeholder rather than taking the parent of a probe
    path: a template may nest BELOW the name, as Codex's
    .agents/skills/{name}/SKILL.md does, and a probe's parent is then the
    per-skill directory rather than the column's root. Measured 2026-08-30 -
    that error reported the whole Codex column as not installed, and 15 real
    mirrors as 'unknown', on a machine where every one of them was present.
    """
    template = target["path"]
    if "{name}" not in template:
        return _expand(template, repo_root, home, "").parent
    prefix = template.split("{name}")[0]
    return _expand(prefix.rstrip("/\\"), repo_root, home, "")


def collect(repo_root, home, now=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the mirror matrix: every canonical definition against every
        harness dialect, each cell carrying a state and a receipt.

    Inputs:
        repo_root (Path): repository root
        home (Path): the home directory user-scoped dialects resolve against
        now (datetime): injected, never read from the clock, so a snapshot is
                        reproducible (R19)

    Outputs:
        snapshot (dict): {"status", "policy_hash", "manifest", "columns",
                          "rows", "totals"}
    --------------------------------------------------------------------------
    """
    repo_root = Path(repo_root)
    home = Path(home)
    stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")

    policy = load_policy(repo_root)
    definitions = canonical_definitions(repo_root)
    manifest = load_manifest(repo_root)
    verdicts = _manifest_index(manifest)

    columns = []
    rows = []
    totals = {state: 0 for state in
              (OK, BY_DESIGN, STUBBED, TRIMMED, STALE, LOST, ORPHAN, UNKNOWN)}

    for target in policy.get("targets", []):
        target_id = target["id"]
        source = target.get("source", "")
        installed = _target_root(target, repo_root, home).is_dir()
        columns.append({
            "id": target_id,
            "harness": target.get("harness", target_id),
            "scope": target.get("scope", "repo"),
            "source": source,
            "cardinality": target.get("cardinality", "per-definition"),
            "requires_flag": target.get("requires_flag"),
            "installed": installed,
            "note": target.get("note"),
        })

        if target.get("cardinality") == "single-file":
            path = _expand(target["path"], repo_root, home, "")
            state = OK if path.exists() else LOST
            reason = None
            if not path.exists():
                reason = "no file at %s" % target["path"]
            rows.append({
                "target": target_id,
                "source": source,
                "name": Path(target["path"]).name,
                "state": _receipt(state, "filesystem", stamp),
                "reason": reason,
                "note": target.get("note"),
            })
            totals[state] += 1
            continue

        # A dialect may mirror more than one kind of definition: the VS Code user
        # profile takes commands AND rules into one directory. Splitting on '+'
        # keeps each row attributed to the source it came from, so its canonical
        # path still resolves. Without this the whole column produced zero rows
        # and vanished from the matrix in silence, which the degradation contract
        # forbids more strongly than any wrong value.
        skips = _skip_names(policy, target)
        names = []
        for sub in source.split("+"):
            for name in definitions.get(sub, []):
                names.append(name)
                cell = _cell(repo_root, home, target, name, sub, skips,
                             verdicts, installed, stamp)
                rows.append(cell)
                totals[cell["state"]["value"]] += 1

        # Anything present in the dialect with no canonical row is an orphan.
        for orphan in _orphans(target, repo_root, home, names):
            state = BY_DESIGN if orphan in _orphans_by_design(policy, target_id) else ORPHAN
            rows.append({
                "target": target_id,
                "source": source,
                "name": orphan,
                "state": _receipt(state, "filesystem", stamp),
                "reason": ("declared in mirror-policy.json orphans_by_design"
                           if state == BY_DESIGN else
                           "present in the dialect with no canonical source; a rule "
                           "or agent may have been deleted without its mirror"),
                "note": None,
            })
            totals[state] += 1

    return {
        "status": "ok",
        "collected_at": stamp,
        "policy_hash": policy_hash(repo_root),
        "manifest": _manifest_receipt(manifest, repo_root, stamp),
        "counts": {k: len(v) for k, v in definitions.items()},
        "columns": columns,
        "rows": rows,
        "totals": totals,
    }


def _manifest_receipt(manifest, repo_root, stamp):
    """A missing manifest degrades ONE column of information and says so.

    It never reads as "all fine": the matrix is complete without it, but the
    question "did anything drift since the last install" becomes unanswerable,
    and an unanswerable question must be printed as such (R3, R8).
    """
    if manifest is None:
        return {
            "status": "unavailable",
            "reason": "no .rt-mirrors.json; run install.ps1 -Manifest. The matrix "
                      "below is complete, but drift SINCE the last install cannot "
                      "be reported because no install recorded what it did.",
        }
    stale_policy = manifest.get("policy_hash") != policy_hash(repo_root)
    return {
        "status": "ok",
        "generated": manifest.get("generated"),
        "personal_run": manifest.get("personal_run"),
        "policy_matches": not stale_policy,
        "reason": ("the manifest was written under a different mirror-policy.json, "
                   "so its verdicts describe rules that have since changed"
                   if stale_policy else None),
        "proven_at": stamp,
    }


def _orphans(target, repo_root, home, canonical_names):
    """Files in the dialect that no canonical definition accounts for."""
    template = target["path"]
    root = _target_root(target, repo_root, home)
    if not root.is_dir():
        return []
    leaf = Path(template).name
    if "{name}" in leaf:
        # The name is the FILE, as in .github/agents/{name}.agent.md
        prefix, _, suffix = leaf.partition("{name}")
        entries = [e.name for e in sorted(root.iterdir()) if e.is_file()]
    elif "{name}" in template:
        # The name is a DIRECTORY, as in .agents/skills/{name}/SKILL.md. Without
        # this branch a nested dialect can never report an orphan, so a skill
        # deleted from .claude/skills/ would leave its Codex mirror behind and
        # nothing would say so.
        prefix, suffix = "", ""
        entries = [e.name for e in sorted(root.iterdir()) if e.is_dir()]
    else:
        return []
    found = []
    for stem in entries:
        if not (stem.startswith(prefix) and stem.endswith(suffix)):
            continue
        name = stem[len(prefix):len(stem) - len(suffix)] if suffix else stem[len(prefix):]
        if name and name not in canonical_names:
            found.append(name)
    return found


def _cell(repo_root, home, target, name, source, skips, verdicts, installed, stamp):
    """One cell: the state of one definition in one dialect, with its receipt."""
    target_id = target["id"]
    path = _expand(target["path"], repo_root, home, name)
    source_path = canonical_path(repo_root, source, name)
    record = verdicts.get((target_id, name))

    def cell(state, reason, proven_by):
        return {
            "target": target_id,
            "source": source,
            "name": name,
            "state": _receipt(state, proven_by, stamp),
            "reason": reason,
            "path": target["path"].replace("{name}", name),
        }

    if name in skips:
        return cell(BY_DESIGN,
                    "named in mirror-policy.json skips.%s" % target.get("skip_list"),
                    "mirror-policy.json")

    # An absent directory means two different things depending on scope, and
    # conflating them is the same defect as conflating by-design with lost.
    # USER scope: the harness is not installed on this machine, so nothing can be
    # said about it and seventeen 'lost' cells would bury the real losses.
    # REPO scope: the mirrors are committed to the clone, so their absence IS the
    # loss - reporting it as 'unknown' would hide a tree that never generated.
    if not installed and target.get("scope") == "user":
        return cell(UNKNOWN,
                    "the %s dialect is not installed on this machine%s"
                    % (target.get("harness", target_id),
                       ("; it is written only by install.ps1 %s"
                        % target["requires_flag"]) if target.get("requires_flag") else ""),
                    "filesystem")

    if not path.exists():
        reason = "no file at %s" % target["path"].replace("{name}", name)
        if target.get("requires_flag"):
            reason += ("; this dialect is written only by install.ps1 %s, so an "
                       "agent added since the last such run never reached it"
                       % target["requires_flag"])
        return cell(LOST, reason, "filesystem")

    # Present. Ask the manifest what the generator decided, before inferring.
    if record and record.get("state") in (STUBBED, TRIMMED):
        detail = {k: v for k, v in record.items()
                  if k not in ("target", "name", "state")}
        out = cell(record["state"],
                   "install.ps1 recorded this verdict: %s" % detail,
                   ".rt-mirrors.json")
        return out

    inferred = _infer_degradation(target, path, source_path)
    if inferred:
        state, reason = inferred
        return cell(state, reason, "filesystem")

    if source_path is not None and source_path.exists():
        try:
            if source_path.stat().st_mtime > path.stat().st_mtime + 1:
                return cell(STALE,
                            "the canonical source is newer than its mirror; "
                            "re-run install.ps1",
                            "filesystem mtime")
        except OSError:
            pass

    return cell(OK, None, "filesystem")


def _infer_degradation(target, path, source_path):
    """Degradation read off the files, for a clone where no install has run.

    Only two dialects degrade, and each leaves a visible trace: a Copilot agent
    stub is far shorter than its source, and a Codex pointer carries a shortened
    description. Nothing else is guessed.
    """
    if target.get("degrades_to") == STUBBED:
        if source_path is None or not source_path.exists():
            return None
        try:
            mirror_len = path.stat().st_size
            source_len = source_path.stat().st_size
        except OSError:
            return None
        if source_len > 0 and mirror_len * 4 < source_len:
            return (STUBBED,
                    "the mirror is %d bytes against a %d-byte source, so it is the "
                    "pointer stub and not the instructions"
                    % (mirror_len, source_len))
        return None

    if target.get("degrades_to") == TRIMMED:
        if source_path is None or not source_path.exists():
            return None
        mirror_desc = _mirror_description(path)
        source_desc = _canonical_description(source_path)
        if mirror_desc is None or source_desc is None:
            return None
        if len(mirror_desc) < len(source_desc):
            return (TRIMMED,
                    "the mirrored description is %d characters against %d "
                    "canonical, trimmed to fit the Codex list budget"
                    % (len(mirror_desc), len(source_desc)))
        return None

    return None
