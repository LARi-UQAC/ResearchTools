"""
Offline suite for scripts/docs/python_libs.py, the generator of the two library tables of manual
chapter 02 and the check that finds an import no requirements file declares.

Measured 2026-10-22: the two tables were built by hand, and nine imports declared by no
requirements file were found that day by reading. Every fixture here is fictitious (R34) and built
in a temporary directory (R21); the real repository is read by the verifier
scripts/test/verify-python-libs.ps1, not here.

Proves: the scan (standard library, local modules, relative imports, guarded imports, junctions),
the mapping through the notes file, every finding kind and its level, the marker rewrite and its
refusals, determinism, the drift mode through an injected provider, and the JSON report. Does not
prove: what pip actually installed, which only --drift against a real environment shows.
"""

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "docs" / "python_libs.py"


def load_module():
    """
    --------------------------------------------------------------------------
    Purpose:
        Import python_libs.py by file path, since scripts/docs is not a package.

    Inputs:
        None

    Outputs:
        module: the loaded python_libs module.
    --------------------------------------------------------------------------
    """
    spec = importlib.util.spec_from_file_location("python_libs", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PL = load_module()

DOC = """# Fixture chapter

Intro.

<!-- python-libs:begin .venv-skills -->
old
<!-- python-libs:end .venv-skills -->

Between.

<!-- python-libs:begin .venv-docs -->
old
<!-- python-libs:end .venv-docs -->

Tail.
"""


class Fixture:
    """
    --------------------------------------------------------------------------
    Purpose:
        A fictitious repository root: skills, a data file, a notes file and a doc.

    Inputs:
        tmp (Path): the temporary directory to build in.

    Outputs:
        Fixture: paths to root, data, notes and doc, and helpers to edit them.
    --------------------------------------------------------------------------
    """

    def __init__(self, tmp: Path) -> None:
        self.root = tmp / "repo"
        self.root.mkdir()
        self.data = self.root / "scripts" / "lib" / "rt-python-requirements.json"
        self.notes = self.root / "scripts" / "docs" / "python-libs-notes.json"
        self.doc = self.root / "docs" / "manual" / "02-profiles.md"
        for p in (self.data, self.notes, self.doc):
            p.parent.mkdir(parents=True, exist_ok=True)
        self.doc.write_text(DOC, encoding="utf-8")
        self.write_py("alpha", "tool.py", "import json\nimport helper\nimport yaml\n")
        self.write_py("alpha", "helper.py", "X = 1\n")
        self.write_req("alpha", "PyYAML==6.0.3\n")
        (self.root / "requirements-docs.txt").write_text("mkdocs==1.6.1\nclick==8.5.0\n", encoding="utf-8")
        self.envs = [
            {"name": ".venv-skills", "why": "suite", "requirements": [
                {"path": ".claude/skills/alpha/scripts/requirements.txt", "why": "alpha", "exclude": []}],
             "tools": [{"spec": "pip-audit==2.10.1", "why": "audit"}]},
            {"name": ".venv-docs", "why": "site", "requirements": [
                {"path": "requirements-docs.txt", "why": "site", "exclude": []}], "tools": []},
        ]
        self.notes_data = {
            "skip_dirs": ["__pycache__", ".venv-skills"],
            "files_cap": 3,
            "unused_check_environments": [".venv-skills"],
            "docs_direct": ["mkdocs"],
            "role_table_environments": [".venv-docs"],
            "pip_list_timeout_s": 30,
            "distributions": {
                "PyYAML": {"imports": ["yaml"], "optional": False, "runtime_only": False, "note": ""},
                "acme-lib": {"imports": ["acmelib"], "optional": False, "runtime_only": False, "note": ""},
                "pip-audit": {"imports": [], "optional": False, "runtime_only": True, "note": "run as a module"},
            },
        }
        self.save()

    def write_py(self, skill: str, name: str, text: str) -> Path:
        path = self.root / ".claude" / "skills" / skill / "scripts" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def write_req(self, skill: str, text: str) -> Path:
        path = self.root / ".claude" / "skills" / skill / "scripts" / "requirements.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def save(self) -> None:
        self.data.write_text(json.dumps({"_comment": "fixture", "environments": self.envs,
                                         "settings": {}}, indent=2), encoding="utf-8")
        self.notes.write_text(json.dumps(self.notes_data, indent=2), encoding="utf-8")

    def run(self, *mode: str) -> tuple:
        out = io.StringIO()
        argv = ["--root", str(self.root), "--data", str(self.data), "--notes", str(self.notes),
                "--doc", str(self.doc), *mode]
        with redirect_stdout(out):
            code = PL.main(argv)
        return code, out.getvalue()

    def findings(self) -> list:
        code, text = self.run("--check", "--json")
        return json.loads(text)["findings"]


def kinds(findings: list) -> list:
    return sorted(f["kind"] for f in findings)


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.fx = Fixture(Path(self._tmp.name))
        # A first write so a stale table never hides the finding under test.
        self.fx.run("--write")

    def tearDown(self) -> None:
        self._tmp.cleanup()


class ScanTests(Base):
    def test_undeclared_import_is_an_error(self) -> None:
        self.fx.write_py("alpha", "uses.py", "import acmelib\n")
        found = [f for f in self.fx.findings() if f["kind"] == "undeclared"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["level"], "error")
        self.assertIn("acme-lib", found[0]["detail"])
        self.fx.write_req("alpha", "PyYAML==6.0.3\nacme-lib==1.0\n")
        self.fx.run("--write")
        self.assertNotIn("undeclared", kinds(self.fx.findings()))

    def test_stdlib_and_local_modules_are_ignored(self) -> None:
        imports = PL.scan_imports(self.fx.root, ["__pycache__"])
        self.assertNotIn("json", imports)
        self.assertNotIn("helper", imports)
        self.assertIn("yaml", imports)

    def test_relative_import_is_ignored(self) -> None:
        self.fx.write_py("alpha", "rel.py", "from . import helper\nfrom .zzzrelative import x\n")
        imports = PL.scan_imports(self.fx.root, ["__pycache__"])
        self.assertNotIn("zzzrelative", imports)

    def test_guarded_import_is_optional_not_missing(self) -> None:
        self.fx.write_py("alpha", "guard.py",
                         "try:\n    import acmelib\nexcept ImportError:\n    acmelib = None\n")
        imports = PL.scan_imports(self.fx.root, ["__pycache__"])
        self.assertTrue(imports["acmelib"]["guarded_only"])
        self.assertFalse(imports["yaml"]["guarded_only"])
        self.assertIn("undeclared", kinds(self.fx.findings()))

    def test_import_inside_a_function_is_guarded(self) -> None:
        self.fx.write_py("alpha", "lazy.py", "def f():\n    import acmelib\n")
        imports = PL.scan_imports(self.fx.root, ["__pycache__"])
        self.assertTrue(imports["acmelib"]["guarded_only"])

    def test_scope_names_the_skill(self) -> None:
        imports = PL.scan_imports(self.fx.root, ["__pycache__"])
        self.assertEqual(imports["yaml"]["scopes"], ["alpha"])

    @unittest.skipUnless(sys.platform == "win32", "junctions are a Windows feature")
    def test_scan_does_not_follow_a_junction(self) -> None:
        import _winapi
        outside = Path(self._tmp.name) / "outside"
        outside.mkdir()
        (outside / "evil.py").write_text("import zzzoutside\n", encoding="utf-8")
        link = self.fx.root / ".claude" / "skills" / "alpha" / "scripts" / "linked"
        _winapi.CreateJunction(str(outside), str(link))
        try:
            imports = PL.scan_imports(self.fx.root, ["__pycache__"])
            self.assertNotIn("zzzoutside", imports)
        finally:
            os.rmdir(link)
        self.assertTrue((outside / "evil.py").exists())


class MappingTests(Base):
    def test_alias_maps_import_to_distribution(self) -> None:
        self.assertNotIn("unmapped", kinds(self.fx.findings()))
        self.fx.write_py("alpha", "odd.py", "import zzzunknown\n")
        found = [f for f in self.fx.findings() if f["kind"] == "unmapped"]
        self.assertEqual(len(found), 1)
        self.assertIn("zzzunknown", found[0]["detail"])

    def test_identity_name_needs_no_notes_entry(self) -> None:
        self.fx.write_py("alpha", "req.py", "import requests\n")
        self.fx.write_req("alpha", "PyYAML==6.0.3\nrequests==2.34.2\n")
        self.fx.run("--write")
        self.assertEqual([], [f for f in self.fx.findings() if f["level"] == "error"])


class FileRegistryTests(Base):
    def test_registered_files(self) -> None:
        self.fx.write_req("beta", "acme-lib==1.0\n")
        found = [f for f in self.fx.findings() if f["kind"] == "unregistered-file"]
        self.assertEqual(len(found), 1)
        self.assertIn("beta", found[0]["detail"])
        self.fx.envs[0]["requirements"].append(
            {"path": ".claude/skills/ghost/scripts/requirements.txt", "why": "x", "exclude": []})
        self.fx.save()
        found = [f for f in self.fx.findings() if f["kind"] == "missing-file"]
        self.assertEqual(len(found), 1)
        self.assertIn("ghost", found[0]["detail"])


class PinTests(Base):
    def test_one_environment_one_version(self) -> None:
        self.fx.write_req("beta", "PyYAML==6.0.2\n")
        self.fx.envs[0]["requirements"].append(
            {"path": ".claude/skills/beta/scripts/requirements.txt", "why": "beta", "exclude": []})
        self.fx.save()
        found = [f for f in self.fx.findings() if f["kind"] == "pin-conflict"]
        self.assertEqual(len(found), 1)
        self.assertIn("pyyaml", found[0]["detail"].lower())

    def test_two_environments_may_differ(self) -> None:
        (self.fx.root / "requirements-docs.txt").write_text("mkdocs==1.6.1\nPyYAML==6.0.1\n", encoding="utf-8")
        self.assertNotIn("pin-conflict", kinds(self.fx.findings()))


class UnusedTests(Base):
    def test_unused_declaration_is_a_warning(self) -> None:
        self.fx.write_req("alpha", "PyYAML==6.0.3\nzzz-dormant==1.0\n")
        self.fx.run("--write")
        found = [f for f in self.fx.findings() if f["kind"] == "unused"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["level"], "warning")
        self.fx.notes_data["distributions"]["zzz-dormant"] = {
            "imports": [], "optional": False, "runtime_only": True, "note": "run as a command"}
        self.fx.save()
        self.fx.run("--write")
        self.assertNotIn("unused", kinds(self.fx.findings()))

    def test_unused_alone_does_not_fail_check(self) -> None:
        self.fx.write_req("alpha", "PyYAML==6.0.3\nzzz-dormant==1.0\n")
        self.fx.run("--write")
        code, _ = self.fx.run("--check")
        self.assertEqual(code, 0)


class MarkerTests(Base):
    def test_write_then_check_is_clean_and_idempotent(self) -> None:
        code, _ = self.fx.run("--check")
        self.assertEqual(code, 0)
        first = self.fx.doc.read_bytes()
        self.fx.run("--write")
        self.assertEqual(first, self.fx.doc.read_bytes())
        text = first.decode("utf-8")
        self.assertIn("Intro.", text)
        self.assertIn("Tail.", text)
        self.assertIn("`PyYAML`", text)

    def test_stale_table_fails_check(self) -> None:
        text = self.fx.doc.read_text(encoding="utf-8").replace("6.0.3", "6.0.9", 1)
        self.fx.doc.write_text(text, encoding="utf-8")
        code, out = self.fx.run("--check", "--json")
        self.assertEqual(code, 1)
        self.assertIn("stale-table", kinds(json.loads(out)["findings"]))
        self.fx.run("--write")
        self.assertEqual(self.fx.run("--check")[0], 0)

    def test_missing_markers_refuse(self) -> None:
        self.fx.doc.write_text("# no markers here\n", encoding="utf-8")
        code, out = self.fx.run("--write")
        self.assertEqual(code, 2)
        self.assertIn("python-libs:begin .venv-skills", out)
        self.assertEqual(self.fx.doc.read_text(encoding="utf-8"), "# no markers here\n")

    def test_doc_outside_root_is_refused(self) -> None:
        outside = Path(self._tmp.name) / "elsewhere.md"
        outside.write_text(DOC, encoding="utf-8")
        out = io.StringIO()
        with redirect_stdout(out):
            code = PL.main(["--root", str(self.fx.root), "--data", str(self.fx.data),
                            "--notes", str(self.fx.notes), "--doc", str(outside), "--write"])
        self.assertEqual(code, 2)
        self.assertEqual(outside.read_text(encoding="utf-8"), DOC)

    def test_output_has_no_machine_value(self) -> None:
        a = self.fx.doc.read_bytes()
        self.fx.run("--write")
        self.assertEqual(a, self.fx.doc.read_bytes())
        self.assertNotIn(b"installed", a.lower())


FULL_HEAD = "| Declared | Library | Import | Pin | Declared in | Used by | Optional | Note |"
ROLE_HEAD = "| Declared | Library | Pin | Role | Note |"


class TableShapeTests(Base):
    def add_third_environment(self) -> None:
        self.fx.write_py("beta", "conv.py", "import yaml\n")
        self.fx.write_req("beta", "PyYAML==6.0.1\n")
        self.fx.envs.append({"name": ".venv-gamma", "why": "conversion", "requirements": [
            {"path": ".claude/skills/beta/scripts/requirements.txt", "why": "beta", "exclude": []}],
            "tools": []})
        self.fx.save()
        doc = self.fx.doc.read_text(encoding="utf-8").replace(
            "Tail.", "<!-- python-libs:begin .venv-gamma -->\nold\n<!-- python-libs:end .venv-gamma -->\n\nTail.")
        self.fx.doc.write_text(doc, encoding="utf-8")

    def test_every_environment_not_listed_gets_the_full_table(self) -> None:
        self.add_third_environment()
        self.assertEqual(self.fx.run("--write")[0], 0)
        tables = PL.render_tables(self.fx.root, PL.load_environments(self.fx.data),
                                  PL.load_notes(self.fx.notes), {})
        self.assertTrue(tables[".venv-skills"].startswith(FULL_HEAD))
        self.assertTrue(tables[".venv-gamma"].startswith(FULL_HEAD))
        self.assertTrue(tables[".venv-docs"].startswith(ROLE_HEAD))
        self.assertIn("6.0.1", tables[".venv-gamma"])
        self.assertEqual(self.fx.run("--check")[0], 0)

    def test_role_table_follows_the_notes_key(self) -> None:
        self.fx.notes_data["role_table_environments"] = []
        self.fx.save()
        self.fx.run("--write")
        self.assertNotIn(ROLE_HEAD, self.fx.doc.read_text(encoding="utf-8"))

    def test_missing_role_key_refuses(self) -> None:
        del self.fx.notes_data["role_table_environments"]
        self.fx.save()
        code, out = self.fx.run("--check")
        self.assertEqual(code, 2)
        self.assertIn("role_table_environments", out)


class DriftTests(Base):
    def test_drift_reports_installed_against_pinned(self) -> None:
        before = self.fx.doc.read_bytes()
        provider = lambda env: ({"pyyaml": "6.0.2", "zzz-extra": "1.0", "pip-audit": "2.10.1"}
                                if env == ".venv-skills" else None)
        report = PL.drift(self.fx.root, self.fx.data, provider)
        envs = {e["name"]: e for e in report["environments"]}
        skills = envs[".venv-skills"]
        self.assertEqual([d["name"] for d in skills["differs"]], ["pyyaml"])
        self.assertEqual(skills["differs"][0]["pinned"], "6.0.3")
        self.assertEqual(skills["differs"][0]["installed"], "6.0.2")
        self.assertIn("zzz-extra", skills["undeclared"])
        self.assertFalse(envs[".venv-docs"]["present"])
        self.assertEqual(before, self.fx.doc.read_bytes())

    def test_drift_reports_a_pinned_library_that_is_absent(self) -> None:
        provider = lambda env: {"pip-audit": "2.10.1"} if env == ".venv-skills" else None
        report = PL.drift(self.fx.root, self.fx.data, provider)
        skills = report["environments"][0]
        self.assertEqual(skills["differs"], [{"name": "pyyaml", "pinned": "6.0.3", "installed": "absent"}])


class EnvironmentScopeTests(Base):
    def test_import_must_be_declared_in_the_environment_that_runs_it(self) -> None:
        # beta runs in .venv-gamma; yaml is declared only in .venv-skills (alpha).
        self.fx.write_py("beta", "conv.py", "import yaml\n")
        self.fx.write_req("beta", "acme-lib==1.0\n")
        self.fx.envs.append({"name": ".venv-gamma", "why": "conversion", "requirements": [
            {"path": ".claude/skills/beta/scripts/requirements.txt", "why": "beta", "exclude": []}],
            "tools": []})
        self.fx.save()
        self.fx.doc.write_text(self.fx.doc.read_text(encoding="utf-8") +
                               "\n<!-- python-libs:begin .venv-gamma -->\n<!-- python-libs:end .venv-gamma -->\n",
                               encoding="utf-8")
        found = [f for f in self.fx.findings() if f["kind"] == "undeclared"]
        self.assertEqual(len(found), 1)
        self.assertIn(".venv-gamma", found[0]["detail"])
        self.assertIn("beta", found[0]["detail"])
        self.fx.write_req("beta", "acme-lib==1.0\nPyYAML==6.0.3\n")
        self.assertNotIn("undeclared", kinds(self.fx.findings()))

    def test_an_excluded_line_is_not_a_declaration(self) -> None:
        self.fx.envs[0]["requirements"][0]["exclude"] = ["PyYAML"]
        self.fx.save()
        found = [f for f in self.fx.findings() if f["kind"] == "undeclared"]
        self.assertEqual(len(found), 1)
        self.assertIn("PyYAML", found[0]["detail"])


class DataValidationTests(Base):
    def test_a_requirement_without_path_is_refused_by_key(self) -> None:
        del self.fx.envs[0]["requirements"][0]["path"]
        self.fx.save()
        code, out = self.fx.run("--check")
        self.assertEqual(code, 2)
        self.assertIn("environments[0].requirements[0].path", out)

    def test_an_environment_without_name_is_refused_by_key(self) -> None:
        del self.fx.envs[1]["name"]
        self.fx.save()
        code, out = self.fx.run("--check")
        self.assertEqual(code, 2)
        self.assertIn("environments[1].name", out)

    def test_missing_pip_timeout_key_refuses(self) -> None:
        del self.fx.notes_data["pip_list_timeout_s"]
        self.fx.save()
        code, out = self.fx.run("--check")
        self.assertEqual(code, 2)
        self.assertIn("pip_list_timeout_s", out)


class PipListTests(unittest.TestCase):
    def test_a_timeout_is_a_refusal(self) -> None:
        def boom(*a, **k):
            raise PL.subprocess.TimeoutExpired(cmd="pip", timeout=1)
        with unittest.mock.patch.object(PL.subprocess, "run", boom):
            with self.assertRaises(PL.Refusal):
                PL._pip_list(Path("python"), 1)

    def test_output_that_is_not_json_is_a_refusal(self) -> None:
        done = PL.subprocess.CompletedProcess(args=[], returncode=0, stdout="WARNING: x\n[]", stderr="")
        with unittest.mock.patch.object(PL.subprocess, "run", lambda *a, **k: done):
            with self.assertRaises(PL.Refusal):
                PL._pip_list(Path("python"), 1)

    def test_the_timeout_is_passed_to_pip(self) -> None:
        seen = {}
        def run(*a, **k):
            seen.update(k)
            return PL.subprocess.CompletedProcess(args=[], returncode=0, stdout="[]", stderr="")
        with unittest.mock.patch.object(PL.subprocess, "run", run):
            self.assertEqual(PL._pip_list(Path("python"), 7), {})
        self.assertEqual(seen["timeout"], 7)


class DriftScopeTests(Base):
    def test_an_absent_environment_fails_drift(self) -> None:
        env_root = Path(self._tmp.name) / "empty-envs"
        env_root.mkdir()
        code, out = self.fx.run("--drift", "--env-root", str(env_root))
        self.assertEqual(code, 1)
        self.assertIn("not present", out)

    def test_main_clone_of_a_linked_worktree(self) -> None:
        main = Path(self._tmp.name) / "mainclone"
        gitdir = main / ".git" / "worktrees" / "wt"
        gitdir.mkdir(parents=True)
        (gitdir / "commondir").write_text("../..\n", encoding="utf-8")
        wt = Path(self._tmp.name) / "wt"
        wt.mkdir()
        (wt / ".git").write_text(f"gitdir: {gitdir.as_posix()}\n", encoding="utf-8")
        self.assertEqual(PL.main_clone(wt), main.resolve())
        self.assertEqual(PL.main_clone(main), main.resolve())
        (main / ".git" / "worktrees").rename(main / "moved")
        self.assertEqual(PL.main_clone(wt), wt.resolve())   # unreadable pointer: the clone itself

    def test_a_marker_line_absent_here_is_skipped_not_drift(self) -> None:
        self.fx.write_req("alpha", "PyYAML==6.0.3\nnvlib==1.0 ; sys_platform == \"win32\" or sys_platform == \"linux\"\n")
        provider = lambda env: ({"pyyaml": "6.0.3", "pip-audit": "2.10.1"} if env == ".venv-skills" else {})
        skills = PL.drift(self.fx.root, self.fx.data, provider)["environments"][0]
        self.assertEqual(skills["differs"], [])
        self.assertEqual(skills["skipped"], ["nvlib"])

    def test_a_marker_line_installed_at_another_version_is_drift(self) -> None:
        self.fx.write_req("alpha", "PyYAML==6.0.3\nnvlib==1.0 ; sys_platform == \"win32\"\n")
        provider = lambda env: ({"pyyaml": "6.0.3", "nvlib": "0.9", "pip-audit": "2.10.1"} if env == ".venv-skills" else {})
        skills = PL.drift(self.fx.root, self.fx.data, provider)["environments"][0]
        self.assertEqual([d["name"] for d in skills["differs"]], ["nvlib"])


class ReportTests(Base):
    def test_json_report_keys(self) -> None:
        code, out = self.fx.run("--check", "--json")
        report = json.loads(out)
        for key in ("ok", "findings", "environments"):
            self.assertIn(key, report)
        self.assertTrue(report["ok"])
        self.assertEqual(report["environments"], [".venv-skills", ".venv-docs"])

    def test_one_mode_is_required(self) -> None:
        with self.assertRaises(SystemExit):
            with redirect_stdout(io.StringIO()):
                PL.main(["--root", str(self.fx.root)])


if __name__ == "__main__":
    unittest.main()
