"""
python_libs - regenerate the two Python library tables of manual chapter 02 and report every
omission between the code, the requirements files and the data file.

Reads the data file the installer reads (scripts/lib/rt-python-requirements.json), scans the
imports of every .py under .claude/skills, .claude/hooks and scripts with ast, maps import names to
distributions through scripts/docs/python-libs-notes.json (data, R6), and fills the text between
`<!-- python-libs:begin NAME -->` and `<!-- python-libs:end NAME -->` in the chapter.

Standard library only, deterministic (R19): no clock and no machine-measured value in the output.
Modes: --write (rewrite the tables), --check (report, write nothing), --drift (compare the pins with
an environment's installed versions, write nothing). Exit codes (R12): 0 clean, 1 findings,
2 refusal. --json prints a machine-readable report (R17).

Called by scripts/test/verify-python-libs.ps1, which run-all-checks.ps1 runs.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Callable

SCAN_ROOTS = (".claude/skills", ".claude/hooks", "scripts")
REQ_LINE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*(.*)$")
BEGIN = "<!-- python-libs:begin {name} -->"
END = "<!-- python-libs:end {name} -->"
# Seconds allowed for `pip list` in --drift (R10). Chosen 2026-10-22: it answers in a few
# seconds on this machine; the ceiling only has to be finite.
PIP_LIST_TIMEOUT_S = 120


class Refusal(Exception):
    """A refusal by design (exit 2): a missing marker, a path outside the root."""


def normalize(name: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        PEP 503 normal form of a distribution name.

    Inputs:
        name (str): a distribution or import name.

    Outputs:
        str: lower case, every run of - _ . replaced by a single dash.
    --------------------------------------------------------------------------
    """
    return re.sub(r"[-_.]+", "-", name).lower()


def _is_link(path: Path) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        True for a symbolic link or a Windows junction (any reparse point), which the
        scan never follows out of the root.

    Inputs:
        path (Path): a directory entry.

    Outputs:
        bool: whether the entry is a link of either kind.
    --------------------------------------------------------------------------
    """
    if path.is_symlink():
        return True
    try:
        attrs = os.lstat(path).st_file_attributes  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return False
    return bool(attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _iter_py(root: Path, skip_dirs: list) -> list:
    """
    --------------------------------------------------------------------------
    Purpose:
        Every .py file under the scan roots, sorted, skipping the named folders and links.

    Inputs:
        root (Path): the repository root.
        skip_dirs (list): folder names never entered.

    Outputs:
        list[Path]: the files, sorted by relative path.
    --------------------------------------------------------------------------
    """
    skip = set(skip_dirs)
    found = []
    for rel in SCAN_ROOTS:
        base = root / rel
        if not base.is_dir() or _is_link(base):
            continue
        for current, dirs, files in os.walk(base, followlinks=False):
            here = Path(current)
            dirs[:] = sorted(d for d in dirs if d not in skip and not _is_link(here / d))
            for f in sorted(files):
                if f.endswith(".py") and not _is_link(here / f):
                    found.append(here / f)
    return sorted(found, key=lambda p: p.relative_to(root).as_posix())


def _scope(root: Path, path: Path) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        The owner of a file: the skill name, 'hooks', or 'scripts/<dir>'.

    Inputs:
        root (Path): the repository root.
        path (Path): a scanned file.

    Outputs:
        str: the scope name.
    --------------------------------------------------------------------------
    """
    parts = path.relative_to(root).parts
    if parts[:2] == (".claude", "skills") and len(parts) > 3:
        return parts[2]
    if parts[:2] == (".claude", "hooks"):
        return "hooks"
    if parts[0] == "scripts" and len(parts) > 2:
        return "scripts/" + parts[1]
    return "scripts"


class _ImportVisitor(ast.NodeVisitor):
    """Collect absolute top-level import names with a guarded flag per occurrence."""

    def __init__(self) -> None:
        self.found = []  # list of (name, guarded)
        self._depth = 0

    def _guarded_body(self, node: ast.AST) -> None:
        self._depth += 1
        self.generic_visit(node)
        self._depth -= 1

    visit_FunctionDef = _guarded_body
    visit_AsyncFunctionDef = _guarded_body

    def visit_Try(self, node: ast.Try) -> None:
        self._depth += 1
        for child in node.body:
            self.visit(child)
        self._depth -= 1
        for child in node.handlers + node.orelse + node.finalbody:
            self.visit(child)

    visit_TryStar = visit_Try

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.found.append((alias.name.split(".")[0], self._depth > 0))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level == 0 and node.module:
            self.found.append((node.module.split(".")[0], self._depth > 0))


def scan_imports(root: Path, skip_dirs: list, files_cap: int = 3) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Map every third-party top-level import name under the scan roots to where it is used.

    Details:
        Standard library names (sys.stdlib_module_names) and local modules (the stem of any
        scanned .py file, or the name of a scanned folder holding .py files) are dropped, as
        are relative imports. An import inside a function or a try body is guarded.

    Inputs:
        root (Path): the repository root.
        skip_dirs (list): folder names never entered.
        files_cap (int): how many file paths to keep per import.

    Outputs:
        dict: name -> {"scopes": sorted list, "guarded_only": bool, "files": sorted capped list}.
    --------------------------------------------------------------------------
    """
    files = _iter_py(root, skip_dirs)
    local = {p.stem for p in files} | {p.parent.name for p in files}
    stdlib = set(getattr(sys, "stdlib_module_names", ())) | set(sys.builtin_module_names)
    out: dict = {}
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        visitor = _ImportVisitor()
        visitor.visit(tree)
        rel = path.relative_to(root).as_posix()
        for name, guarded in visitor.found:
            if name in stdlib or name in local or name == "__future__":
                continue
            entry = out.setdefault(name, {"scopes": set(), "guarded_only": True, "files": set()})
            entry["scopes"].add(_scope(root, path))
            entry["guarded_only"] = entry["guarded_only"] and guarded
            entry["files"].add(rel)
    return {k: {"scopes": sorted(v["scopes"]), "guarded_only": v["guarded_only"],
                "files": sorted(v["files"])[:files_cap]} for k, v in sorted(out.items())}


def parse_requirements(path: Path) -> list:
    """
    --------------------------------------------------------------------------
    Purpose:
        The requirement lines of one file. Comment lines, blank lines and option lines
        (-r, -c, --index-url and the like) are skipped.

    Inputs:
        path (Path): a requirements file.

    Outputs:
        list[dict]: each with name (PEP 503), display, spec, pinned (bool), version (str or
        ""), marker, optional (the trailing comment says optional).
    --------------------------------------------------------------------------
    """
    return parse_requirement_lines(path.read_text(encoding="utf-8").splitlines())


def parse_requirement_lines(lines: list) -> list:
    """
    --------------------------------------------------------------------------
    Purpose:
        parse_requirements on lines already read (a file, or a tool spec of the data file).

    Inputs:
        lines (list[str]): requirement lines.

    Outputs:
        list[dict]: as parse_requirements.
    --------------------------------------------------------------------------
    """
    result = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        comment = ""
        if " #" in line:
            line, comment = line.split(" #", 1)
        marker = ""
        if ";" in line:
            line, marker = line.split(";", 1)
        m = REQ_LINE.match(line.strip())
        if not m:
            continue
        spec = (m.group(2) or "") + m.group(3).strip()
        pin = re.search(r"==\s*([^\s,]+)", spec)
        result.append({
            "name": normalize(m.group(1)),
            "display": m.group(1),
            "spec": spec,
            "pinned": pin is not None,
            "version": pin.group(1) if pin else "",
            "marker": marker.strip(),
            "optional": "optional" in comment.lower(),
        })
    return result


def load_environments(data: Path) -> list:
    """
    --------------------------------------------------------------------------
    Purpose:
        The environments of the data file the installer reads.

    Inputs:
        data (Path): rt-python-requirements.json.

    Outputs:
        list[dict]: name, why, requirements (relative paths in file order), tools (specs).

    Raises:
        Refusal: the file is absent, does not parse, or has no 'environments' list.
    --------------------------------------------------------------------------
    """
    try:
        doc = json.loads(data.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Refusal(f"data file unreadable: {data} ({exc})") from exc
    envs = doc.get("environments")
    if not isinstance(envs, list) or not envs:
        raise Refusal(f"data file {data}: key 'environments' is missing or empty")
    return [{"name": e["name"], "why": e.get("why", ""),
             "requirements": [r["path"] for r in e.get("requirements", [])],
             "tools": [t["spec"] for t in e.get("tools", [])]} for e in envs]


def load_notes(notes: Path) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        The notes file: per distribution its import names and flags, plus scan settings.

    Inputs:
        notes (Path): python-libs-notes.json.

    Outputs:
        dict: the parsed notes, with distribution keys normalised.

    Raises:
        Refusal: the file is absent, does not parse, or lacks a required key (R3).
    --------------------------------------------------------------------------
    """
    try:
        doc = json.loads(notes.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Refusal(f"notes file unreadable: {notes} ({exc})") from exc
    for key in ("skip_dirs", "files_cap", "unused_check_environments", "docs_direct",
                "role_table_environments", "distributions"):
        if key not in doc:
            raise Refusal(f"notes file {notes}: key '{key}' is missing")
    doc["dists"] = {normalize(k): dict(v, display=k) for k, v in doc["distributions"].items()}
    return doc


def _req_label(rel: str) -> str:
    parts = rel.split("/")
    if parts[:2] == [".claude", "skills"] and len(parts) > 2:
        return parts[2]
    return rel


def _declarations(root: Path, envs: list) -> dict:
    """env name -> dist -> list of {label, entry} (tools count as declarations)."""
    out: dict = {}
    for env in envs:
        table = out.setdefault(env["name"], {})
        for rel in env["requirements"]:
            path = root / rel
            if not path.is_file():
                continue
            for entry in parse_requirements(path):
                table.setdefault(entry["name"], []).append({"label": _req_label(rel), "entry": entry})
        for spec in env["tools"]:
            for entry in parse_requirement_lines([spec]):
                table.setdefault(entry["name"], []).append({"label": "data file tools", "entry": entry})
    return out


def _import_to_dist(name: str, notes: dict, declared: set) -> str | None:
    for dist, info in notes["dists"].items():
        if name in info.get("imports", []):
            return dist
    if normalize(name) in declared:
        return normalize(name)
    return None


def find_findings(root: Path, envs: list, notes: dict, imports: dict) -> list:
    """
    --------------------------------------------------------------------------
    Purpose:
        Every omission between the code, the requirements files and the data file.

    Details:
        Errors: undeclared (an import mapped to a distribution no file declares), unmapped (an
        import the notes do not map and no file declares under its own name), unregistered-file
        (a requirements file the data file does not name), missing-file (a named path that does
        not exist), pin-conflict (one library pinned to two versions in one environment).
        Warning: unused (a declared library nothing imports and the notes do not excuse).

    Inputs:
        root (Path): repository root. envs (list): load_environments. notes (dict): load_notes.
        imports (dict): scan_imports.

    Outputs:
        list[dict]: level, kind, detail; sorted.
    --------------------------------------------------------------------------
    """
    found = []
    decl = _declarations(root, envs)
    declared_all = {d for table in decl.values() for d in table}
    named = {rel for env in envs for rel in env["requirements"]}

    for env in envs:
        for rel in env["requirements"]:
            if not (root / rel).is_file():
                found.append({"level": "error", "kind": "missing-file",
                              "detail": f"{rel} is named by {env['name']} and does not exist"})
    on_disk = []
    skills = root / ".claude" / "skills"
    if skills.is_dir():
        for current, dirs, files in os.walk(skills, followlinks=False):
            here = Path(current)
            dirs[:] = sorted(d for d in dirs if not _is_link(here / d))
            if "requirements.txt" in files:
                on_disk.append(here / "requirements.txt")
    on_disk += list(root.glob("requirements-docs.txt"))
    for path in sorted(on_disk):
        rel = path.relative_to(root).as_posix()
        if rel not in named:
            found.append({"level": "error", "kind": "unregistered-file",
                          "detail": f"{rel} exists and the data file does not name it"})

    used = set()
    for name, info in imports.items():
        dist = _import_to_dist(name, notes, declared_all)
        where = ", ".join(info["scopes"])
        if dist is None:
            found.append({"level": "error", "kind": "unmapped",
                          "detail": f"import {name} (in {where}) maps to no distribution: add it to the notes file"})
            continue
        used.add(dist)
        if dist not in declared_all:
            found.append({"level": "error", "kind": "undeclared",
                          "detail": f"import {name} (in {where}) needs {notes['dists'].get(dist, {}).get('display', dist)}, which no requirements file declares"})

    for env in envs:
        for dist, decls in sorted(decl.get(env["name"], {}).items()):
            versions = sorted({d["entry"]["version"] for d in decls if d["entry"]["pinned"]})
            if len(versions) > 1:
                where = "; ".join(f"{d['entry']['version']} in {d['label']}" for d in decls if d["entry"]["pinned"])
                found.append({"level": "error", "kind": "pin-conflict",
                              "detail": f"{dist} is pinned to {len(versions)} versions in {env['name']}: {where}"})
            if env["name"] in notes["unused_check_environments"] and dist not in used:
                info = notes["dists"].get(dist, {})
                if not info.get("runtime_only") and not info.get("note"):
                    found.append({"level": "warning", "kind": "unused",
                                  "detail": f"{dist} is declared in {env['name']} and nothing imports it"})
    return sorted(found, key=lambda f: (f["level"], f["kind"], f["detail"]))


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_tables(root: Path, envs: list, notes: dict, imports: dict) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        The Markdown table of each environment, with no machine-measured value.

    Inputs:
        root (Path), envs (list), notes (dict), imports (dict): as find_findings.

    Outputs:
        dict: environment name -> table text (no trailing newline).
    --------------------------------------------------------------------------
    """
    decl = _declarations(root, envs)
    declared_all = {d for table in decl.values() for d in table}
    uses: dict = {}
    for name, info in imports.items():
        dist = _import_to_dist(name, notes, declared_all)
        key = dist or normalize(name)
        u = uses.setdefault(key, {"imports": set(), "scopes": set(), "guarded": True})
        u["imports"].add(name)
        u["scopes"].update(info["scopes"])
        u["guarded"] = u["guarded"] and info["guarded_only"]

    tables = {}
    # An import nobody declares is listed, unticked, in the first environment only:
    # that is the environment every skill script runs in.
    first = envs[0]["name"] if envs else ""
    role_envs = set(notes["role_table_environments"])
    docs_direct = {normalize(d) for d in notes["docs_direct"]}
    for env in envs:
        rows = []
        full = env["name"] not in role_envs
        table = decl.get(env["name"], {})
        dists = set(table)
        if env["name"] == first:
            dists |= {d for d in uses if d not in declared_all}
        for dist in sorted(dists, key=lambda d: (notes["dists"].get(d, {}).get("display") or d).lower()):
            decls = table.get(dist, [])
            info = notes["dists"].get(dist, {})
            display = info.get("display") or (decls[0]["entry"]["display"] if decls else dist)
            box = "☑" if decls else "☐"
            pins = sorted({d["entry"]["version"] if d["entry"]["pinned"] else (d["entry"]["spec"] or "unpinned") for d in decls})
            where = "; ".join(f"{d['label']} `{d['entry']['spec'] or 'unpinned'}`" for d in decls) or "none"
            u = uses.get(dist)
            imp = ", ".join(sorted(u["imports"])) if u else (", ".join(info.get("imports", [])) or "(none)")
            used_by = ", ".join(sorted(u["scopes"])) if u else "-"
            optional = "yes" if (info.get("optional") or any(d["entry"]["optional"] for d in decls) or (u and u["guarded"])) else ""
            note = info.get("note", "")
            if full:
                rows.append(f"| {box} | `{_cell(display)}` | {_cell(imp)} | {_cell(', '.join(pins) or '-')} | {_cell(where)} | {_cell(used_by)} | {optional} | {_cell(note)} |")
            else:
                role = "direct" if dist in docs_direct else "transitive"
                rows.append(f"| {box} | `{_cell(display)}` | {_cell(', '.join(pins) or '-')} | {role} | {_cell(note)} |")
        if full:
            head = "| Declared | Library | Import | Pin | Declared in | Used by | Optional | Note |\n|---|---|---|---|---|---|---|---|"
        else:
            head = "| Declared | Library | Pin | Role | Note |\n|---|---|---|---|---|"
        tables[env["name"]] = head + ("\n" + "\n".join(rows) if rows else "")
    return tables


def _span(doc: str, name: str) -> tuple:
    begin, end = BEGIN.format(name=name), END.format(name=name)
    i = doc.find(begin)
    j = doc.find(end, i + len(begin)) if i >= 0 else -1
    if i < 0:
        raise Refusal(f"marker not found: {begin}")
    if j < 0:
        raise Refusal(f"marker not found: {end}")
    return i + len(begin), j


def apply_markers(doc: str, tables: dict) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Replace the text between each environment's begin and end markers by its table.

    Inputs:
        doc (str): the chapter text.
        tables (dict): render_tables.

    Outputs:
        str: the new chapter text; identical on a second application.

    Raises:
        Refusal: a marker is missing, so nothing is appended at the end.
    --------------------------------------------------------------------------
    """
    for name in tables:
        _span(doc, name)
    for name, table in tables.items():
        start, stop = _span(doc, name)
        doc = doc[:start] + "\n" + table + "\n" + doc[stop:]
    return doc


def _pip_list(python: Path) -> dict:
    """Installed distributions of one interpreter, through `pip list --format json`."""
    proc = subprocess.run([str(python), "-m", "pip", "list", "--format", "json", "--disable-pip-version-check"],
                          capture_output=True, text=True, timeout=PIP_LIST_TIMEOUT_S, check=False)
    if proc.returncode != 0:
        raise Refusal(f"pip list failed for {python}: {proc.stderr.strip()[-300:]}")
    return {normalize(p["name"]): p["version"] for p in json.loads(proc.stdout)}


def drift(root: Path, data: Path, provider: Callable[[str], dict | None]) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Compare the pins of each environment with the versions installed in it. Read-only.

    Inputs:
        root (Path): the repository root.
        data (Path): the data file.
        provider (callable): environment name -> {normalised name: version}, or None when the
            environment is absent.

    Outputs:
        dict: environments: list of {name, present, differs: [{name, pinned, installed}],
        undeclared: sorted names installed and declared nowhere in that environment}.
    --------------------------------------------------------------------------
    """
    envs = load_environments(data)
    decl = _declarations(root, envs)
    report = []
    for env in envs:
        installed = provider(env["name"])
        entry = {"name": env["name"], "present": installed is not None, "differs": [], "undeclared": []}
        if installed is not None:
            table = decl.get(env["name"], {})
            for dist, decls in sorted(table.items()):
                pins = {d["entry"]["version"] for d in decls if d["entry"]["pinned"]}
                have = installed.get(dist)
                if pins and have not in pins:
                    entry["differs"].append({"name": dist, "pinned": ", ".join(sorted(pins)), "installed": have or "absent"})
            entry["undeclared"] = sorted(d for d in installed if d not in table)
        report.append(entry)
    return {"environments": report}


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def main(argv: list | None = None) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Command line entry point.

    Inputs:
        argv (list): the arguments, defaulting to sys.argv[1:].

    Outputs:
        int: 0 clean, 1 findings, 2 refusal. --write rewrites the chapter (a side effect).
    --------------------------------------------------------------------------
    """
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Regenerate and check the Python library tables of manual chapter 02.")
    parser.add_argument("--root", default=str(here.parent.parent))
    parser.add_argument("--data", default=None)
    parser.add_argument("--notes", default=None)
    parser.add_argument("--doc", default=None)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--drift", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    data = Path(args.data) if args.data else root / "scripts" / "lib" / "rt-python-requirements.json"
    notes_path = Path(args.notes) if args.notes else root / "scripts" / "docs" / "python-libs-notes.json"
    doc_path = Path(args.doc) if args.doc else root / "docs" / "manual" / "02-profiles.md"

    def emit(report: dict, lines: list) -> None:
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            for line in lines:
                print(line)

    try:
        if args.drift:
            def provider(name: str) -> dict | None:
                py = root / name / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
                return _pip_list(py) if py.is_file() else None
            report = drift(root, data, provider)
            bad = any(e["differs"] for e in report["environments"])
            lines = []
            for e in report["environments"]:
                if not e["present"]:
                    lines.append(f"{e['name']}: not present")
                    continue
                lines.append(f"{e['name']}: {len(e['differs'])} pin(s) differ, {len(e['undeclared'])} installed and undeclared")
                lines += [f"  differs: {d['name']} pinned {d['pinned']}, installed {d['installed']}" for d in e["differs"]]
                lines += [f"  undeclared: {n}" for n in e["undeclared"]]
            emit(dict(report, ok=not bad), lines)
            return 1 if bad else 0

        if not _inside(doc_path, root):
            raise Refusal(f"--doc resolves outside --root: {doc_path}")
        envs = load_environments(data)
        notes = load_notes(notes_path)
        imports = scan_imports(root, notes["skip_dirs"], int(notes["files_cap"]))
        findings = find_findings(root, envs, notes, imports)
        tables = render_tables(root, envs, notes, imports)
        current = doc_path.read_text(encoding="utf-8") if doc_path.is_file() else ""
        wanted = apply_markers(current, tables)
        if args.write:
            if wanted != current:
                with open(doc_path, "w", encoding="utf-8", newline="") as fh:
                    fh.write(wanted)
        elif wanted != current:
            findings.append({"level": "error", "kind": "stale-table",
                             "detail": f"{doc_path.name}: the tables differ from what --write would produce"})
    except Refusal as exc:
        emit({"ok": False, "refusal": str(exc), "findings": [], "environments": []}, [f"REFUSED: {exc}"])
        return 2

    errors = [f for f in findings if f["level"] == "error"]
    report = {"ok": not errors, "findings": findings, "environments": [e["name"] for e in envs]}
    lines = [f"{f['level'].upper()} {f['kind']}: {f['detail']}" for f in findings]
    lines.append(f"{len(errors)} error(s), {len(findings) - len(errors)} warning(s)")
    emit(report, lines)
    return 1 if errors else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
