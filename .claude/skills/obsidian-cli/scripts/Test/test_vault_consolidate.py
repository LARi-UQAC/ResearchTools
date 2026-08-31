"""
test_vault_consolidate - offline checks for the phantom-link audit.

No network, no Obsidian, no real vault: every case builds a fake vault in
tempfile.mkdtemp(). Cases in PhantomTest cover detection, cases in ApplyTest
cover the guarded rewrite and the non-regression of the default mode (see
the plan of 2026-08-13, fix round 1 of 2026-08-14, residual fix round 2 of
2026-08-14: the whole-map validation gate and the split refusal report).
"""
import contextlib
import importlib.util
import io
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "vault_consolidate.py"
spec = importlib.util.spec_from_file_location("vc", SCRIPT)
vc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vc)


def _junctions_supported() -> bool:
    """Probe once whether directory junctions can be created here, so the
    escape-guard test can skip loudly instead of silently passing without
    ever exercising the guard it is meant to prove."""
    probe_root = Path(tempfile.mkdtemp())
    try:
        target = probe_root / "target"
        target.mkdir()
        link = probe_root / "link"
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
        )
        ok = result.returncode == 0
        if ok:
            subprocess.run(["cmd", "/c", "rmdir", str(link)], capture_output=True)
        return ok
    except OSError:
        return False
    finally:
        shutil.rmtree(probe_root, ignore_errors=True)


JUNCTIONS_SUPPORTED = _junctions_supported()


class VaultTestBase(unittest.TestCase):
    def setUp(self):
        self.vault = Path(tempfile.mkdtemp())

    def write(self, rel: str, text: str) -> Path:
        p = self.vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="")
        return p

    def phantoms(self):
        notes = vc.load(str(self.vault))
        return vc.find_phantoms(notes, vc.build_names(notes))


class PhantomTest(VaultTestBase):
    def test_alias_resolves_and_is_not_a_phantom(self):
        self.write("30_Ressources/Obsidian/a.md",
                   '---\naliases: ["Readable Name"]\n---\nbody\n')
        self.write("30_Ressources/Obsidian/b.md", "see [[Readable Name]]\n")
        self.assertEqual(self.phantoms(), {})

    def test_link_inside_a_fence_is_not_counted(self):
        self.write("30_Ressources/Obsidian/b.md",
                   "text\n```\n[[Nowhere]]\n```\nand `[[AlsoNowhere]]`\n")
        self.assertEqual(self.phantoms(), {})

    def test_link_from_archives_is_ignored(self):
        self.write("90_Archives/old.md", "see [[Deleted Note]]\n")
        self.assertEqual(self.phantoms(), {})

    def test_unresolved_target_is_reported_with_a_suggestion(self):
        self.write("30_Ressources/Obsidian/outbox-write-path.md", "body\n")
        self.write("30_Ressources/Obsidian/b.md", "see [[outbox write path]]\n")
        found = self.phantoms()
        self.assertIn("outbox write path", found)
        self.assertEqual(found["outbox write path"]["sources"],
                         ["30_Ressources/Obsidian/b.md"])
        self.assertTrue(found["outbox write path"]["suggestions"])

    def test_why_labels_name_matches_and_aliases(self):
        self.write("Root.md", "body\n")
        self.write("30_Ressources/MyFolder/MyNote.md", "body\n")
        self.write("30_Ressources/Technology/theory.md",
                   '---\naliases: ["Control Theory"]\n---\nbody\n')
        self.write("30_Ressources/TestLinks/links.md",
                   "[[root]] [[30_ressources/myfolder/mynote]] [[control theory]]\n")
        found = self.phantoms()
        self.assertIn("root", found)
        self.assertIn("30_ressources/myfolder/mynote", found)
        self.assertIn("control theory", found)
        root_sugg = found["root"]["suggestions"][0]
        path_sugg = found["30_ressources/myfolder/mynote"]["suggestions"][0]
        alias_sugg = found["control theory"]["suggestions"][0]
        self.assertEqual(root_sugg["why"], "basename")
        self.assertEqual(root_sugg["score"], 1.0)
        self.assertEqual(path_sugg["why"], "basename")
        self.assertEqual(path_sugg["score"], 1.0)
        self.assertEqual(alias_sugg["why"], "alias")
        self.assertEqual(alias_sugg["score"], 1.0)


class ApplyTest(VaultTestBase):
    def tearDown(self):
        link = getattr(self, "_junction", None)
        if link is not None and link.exists():
            # rmdir on a junction removes only the reparse point, never the
            # target directory it points at; shutil.rmtree would recurse
            # through it and could delete the outside fixture instead. Runs
            # even if the test body raised, so a failing test does not
            # leave a junction behind.
            subprocess.run(["cmd", "/c", "rmdir", str(link)], capture_output=True)
        super().tearDown()

    def _make_junction_to_outside(self) -> Path:
        # A real note in a temp directory OUTSIDE the fake vault, reached
        # through a junction placed INSIDE the fake vault. glob discovers
        # the note under the vault path (recursive glob follows a junction
        # like any other directory), but os.path.realpath resolves it to
        # the outside directory, which is what makes apply_map's escape
        # guard fire, unlike a plain sibling file, which glob never
        # visits at all because it is outside the vault tree it enumerates.
        outside_dir = Path(tempfile.mkdtemp())
        outside_note = outside_dir / "note.md"
        outside_note.write_text("see [[Old]]\n", encoding="utf-8", newline="")
        self._junction = self.vault / "link"
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(self._junction), str(outside_dir)],
            check=True, capture_output=True,
        )
        return outside_note

    def test_dry_run_modifies_nothing(self):
        p = self.write("30_Ressources/Obsidian/b.md", "see [[Old]]\n")
        before = p.stat().st_mtime_ns, p.read_text(encoding="utf-8")
        vc.apply_map(str(self.vault), {"[[Old]]": "[[New]]"}, write=False)
        self.assertEqual((p.stat().st_mtime_ns, p.read_text(encoding="utf-8")), before)

    def test_apply_replaces_and_counts_modified_files(self):
        p = self.write("30_Ressources/Obsidian/b.md", "see [[Old]] and [[Old]]\n")
        self.write("30_Ressources/Obsidian/c.md", "no link here\n")
        report = vc.apply_map(str(self.vault), {"[[Old]]": "[[New]]"}, write=True)
        self.assertEqual(report["modified"], ["30_Ressources/Obsidian/b.md"])
        self.assertNotIn("[[Old]]", p.read_text(encoding="utf-8"))
        self.assertEqual(p.read_text(encoding="utf-8").count("[[New]]"), 2)

    def test_target_outside_the_vault_is_refused(self):
        outside = self.vault.parent / "elsewhere.md"
        outside.write_text("see [[Old]]\n", encoding="utf-8", newline="")
        report = vc.apply_map(str(self.vault), {"[[Old]]": "[[New]]"}, write=True)
        self.assertEqual(report["modified"], [])
        self.assertIn("[[Old]]", outside.read_text(encoding="utf-8"))

    @unittest.skipUnless(JUNCTIONS_SUPPORTED,
                          "directory junctions unavailable on this system")
    def test_refusal_exits_non_zero(self):
        outside_note = self._make_junction_to_outside()
        report = vc.apply_map(str(self.vault), {"[[Old]]": "[[New]]"}, write=True)
        self.assertIn("[[Old]]", outside_note.read_text(encoding="utf-8"))
        self.assertIn("link/note.md", report["refused_paths"])
        mapping = self.vault / "map.json"
        mapping.write_text('{"[[Old]]": "[[New]]"}', encoding="utf-8")
        code = vc.main(["--vault", str(self.vault), "--apply", str(mapping), "--yes"])
        self.assertNotEqual(code, 0, "a refusal must not read as a no-op")

    def test_write_uses_lf_only(self):
        # CRLF content deliberately: written verbatim (newline="" makes the
        # write helper a passthrough) so the fixture starts as CRLF, the
        # shape a note edited outside Obsidian can carry. Path.read_text()
        # would silently normalise CRLF back to "\n" on read and hide a
        # regression, so the assertion below reads raw bytes instead.
        p = self.write("30_Ressources/Obsidian/b.md", "see [[Old]]\r\nsecond line\r\n")
        vc.apply_map(str(self.vault), {"[[Old]]": "[[New]]"}, write=True)
        data = p.read_bytes()
        self.assertIn(b"[[New]]", data)
        self.assertNotIn(b"\r\n", data)

    def test_empty_key_is_refused_not_applied(self):
        # F1: an empty-string key must never rewrite every note character
        # by character. It is refused, not silently a no-op.
        p = self.write("30_Ressources/Obsidian/b.md", "abc\n")
        report = vc.apply_map(str(self.vault), {"": "X"}, write=True)
        self.assertEqual(report["modified"], [])
        self.assertTrue(report["refused_map_entries"])
        self.assertEqual(report["refused_paths"], [])
        self.assertEqual(p.read_text(encoding="utf-8"), "abc\n")

    def test_unbracketed_key_is_refused(self):
        # F2: a key not wrapped in [[...]] must never rewrite word
        # interiors ("Old" turning "Oldenburg" into "Newenburg").
        p = self.write("30_Ressources/Obsidian/b.md", "Oldenburg stands.\n")
        report = vc.apply_map(str(self.vault), {"Old": "New"}, write=True)
        self.assertEqual(report["modified"], [])
        self.assertTrue(report["refused_map_entries"])
        self.assertEqual(p.read_text(encoding="utf-8"), "Oldenburg stands.\n")

    def test_chained_keys_do_not_cascade(self):
        # F3: {"[[A]]": "[[B]]", "[[B]]": "[[C]]"} must leave a note that
        # said [[A]] as [[B]], never cascade on to [[C]] in the same pass.
        p = self.write("30_Ressources/Obsidian/b.md", "see [[A]]\n")
        mapping = {"[[A]]": "[[B]]", "[[B]]": "[[C]]"}
        report = vc.apply_map(str(self.vault), mapping, write=True)
        text = p.read_text(encoding="utf-8")
        self.assertIn("[[B]]", text)
        self.assertNotIn("[[C]]", text)
        self.assertEqual(report["modified"], ["30_Ressources/Obsidian/b.md"])

    def test_apply_respects_code_fence_and_archive_exclusions(self):
        # F4: apply must honour the same exclusions find_phantoms already
        # applies for detection - code fences, inline code, and 90_Archives
        # as a source - instead of rewriting text the links report never
        # flagged.
        p = self.write(
            "30_Ressources/Obsidian/b.md",
            "see [[Old]]\n\n```\n[[Old]]\n```\n\nand `[[Old]]` inline\n",
        )
        archived = self.write("90_Archives/old.md", "see [[Old]]\n")
        report = vc.apply_map(str(self.vault), {"[[Old]]": "[[New]]"}, write=True)
        text = p.read_text(encoding="utf-8")
        self.assertEqual(text.count("[[New]]"), 1)
        self.assertIn("```\n[[Old]]\n```", text)
        self.assertIn("`[[Old]]`", text)
        self.assertIn("[[Old]]", archived.read_text(encoding="utf-8"))
        self.assertEqual(report["modified"], ["30_Ressources/Obsidian/b.md"])

    def test_cross_drive_commonpath_error_is_refused_not_raised(self):
        # F5: os.path.commonpath raises ValueError across drives/UNC roots.
        # That must become a refusal for the one path involved, not an
        # unhandled exception that aborts the loop after earlier files in
        # sorted order were already rewritten.
        good = self.write("30_Ressources/Obsidian/good.md", "see [[Old]]\n")
        bad = self.write("30_Ressources/Obsidian/bad_note.md", "see [[Old]]\n")
        real_commonpath = vc.os.path.commonpath

        def fake_commonpath(paths):
            if any("bad_note" in str(p) for p in paths):
                raise ValueError("simulated cross-drive path")
            return real_commonpath(paths)

        with patch("os.path.commonpath", side_effect=fake_commonpath):
            report = vc.apply_map(str(self.vault), {"[[Old]]": "[[New]]"}, write=True)

        self.assertIn("30_Ressources/Obsidian/bad_note.md", report["refused_paths"])
        self.assertIn("[[Old]]", bad.read_text(encoding="utf-8"))
        self.assertEqual(report["modified"], ["30_Ressources/Obsidian/good.md"])
        self.assertIn("[[New]]", good.read_text(encoding="utf-8"))

    def test_cli_apply_without_yes_leaves_files_unchanged(self):
        # F6: main() with --apply and WITHOUT --yes is the dry-run gate
        # standing between a preview and a real rewrite. Nothing on disk
        # may change.
        p = self.write("30_Ressources/Obsidian/b.md", "see [[Old]]\n")
        before = p.read_text(encoding="utf-8")
        mapping = self.vault / "map.json"
        mapping.write_text('{"[[Old]]": "[[New]]"}', encoding="utf-8")
        code = vc.main(["--vault", str(self.vault), "--apply", str(mapping)])
        self.assertEqual(code, 0)
        self.assertEqual(p.read_text(encoding="utf-8"), before)

    def test_mixed_map_refuses_the_whole_run_and_writes_nothing(self):
        # Residual fix, round 2: a map that mixes one valid entry with one
        # malformed entry must refuse ENTIRELY. The valid entry's target
        # file must come out byte-identical, never half-rewritten.
        p = self.write("30_Ressources/Obsidian/good.md", "see [[Good]]\n")
        before = p.read_bytes()
        mixed_map = {"[[Good]]": "[[Fixed]]", "": "X"}
        report = vc.apply_map(str(self.vault), mixed_map, write=True)
        self.assertEqual(report["modified"], [])
        self.assertEqual(report["refused_paths"], [])
        self.assertEqual(len(report["refused_map_entries"]), 1)
        self.assertEqual(p.read_bytes(), before)

        mapping = self.vault / "map.json"
        mapping.write_text(
            '{"[[Good]]": "[[Fixed]]", "": "X"}', encoding="utf-8"
        )
        code = vc.main(["--vault", str(self.vault), "--apply", str(mapping), "--yes"])
        self.assertNotEqual(code, 0)
        self.assertEqual(p.read_bytes(), before)

    def test_map_refusal_message_does_not_claim_a_path_escaped(self):
        # The refused-map-entry message must name the map as the cause, and
        # must never claim a path resolved outside the vault when nothing
        # of the sort happened.
        self.write("30_Ressources/Obsidian/good.md", "see [[Good]]\n")
        mapping = self.vault / "map.json"
        mapping.write_text('{"": "X"}', encoding="utf-8")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = vc.main(["--vault", str(self.vault), "--apply", str(mapping), "--yes"])
        message = stderr.getvalue()
        self.assertNotEqual(code, 0)
        self.assertIn("map", message)
        self.assertIn("malformed", message)
        self.assertNotIn("outside the vault", message)

    def test_non_dict_map_is_refused_not_raised(self):
        # A JSON map that is not an object (a list here) must fail closed
        # with a refusal, not an AttributeError on mapping.items().
        report = vc.apply_map(str(self.vault), ["not", "a", "dict"], write=True)
        self.assertEqual(report["modified"], [])
        self.assertTrue(report["refused_map_entries"])
        self.assertEqual(report["refused_paths"], [])

    def test_bracketed_link_rejects_whitespace_only_inner_text(self):
        # A key or value of "[[ ]]" carries no real target: the inner text
        # is only whitespace.
        self.assertFalse(vc._is_bracketed_link("[[ ]]"))
        self.assertFalse(vc._is_bracketed_link("[[\t]]"))

    def test_bracketed_link_rejects_multiple_links_and_prose(self):
        # "[[A]] prose [[B]]" is two link targets plus free text, not one
        # bracketed target and nothing else.
        self.assertFalse(vc._is_bracketed_link("[[A]] prose [[B]]"))
        self.assertFalse(vc._is_bracketed_link("prose before [[A]]"))
        self.assertFalse(vc._is_bracketed_link("[[A]] prose after"))

    def test_bracketed_link_accepts_a_single_target(self):
        self.assertTrue(vc._is_bracketed_link("[[Old]]"))
        self.assertTrue(vc._is_bracketed_link("[[Old Note]]"))

    def test_candidates_mode_output_is_unchanged(self):
        self.write("30_Ressources/Obsidian/a.md",
                   '---\ntags: [obsidian, socket]\ndomaine: obsidian\n---\ntroncature socket pipe\n')
        self.write("30_Ressources/Obsidian/b.md",
                   '---\ntags: [obsidian, socket]\ndomaine: obsidian\n---\ntroncature socket pipe\n')
        notes = vc.load(str(self.vault))
        self.assertIn("30_Ressources/Obsidian/a.md", notes)
        self.assertEqual(len(notes), 2)


class PathSuffixResolutionTest(VaultTestBase):
    """P8: Obsidian resolves a link written as an intermediate path suffix, and the
    report used to flag it as a phantom because build_names indexes only the bare
    basename and the full path. An operator repairing that would have rewritten a
    working link."""

    def test_intermediate_path_suffix_is_not_a_phantom(self):
        self.write("10_Projets/Logiciels/DigitalTwinMill/Decisions.md", "body\n")
        self.write("30_Ressources/Obsidian/b.md", "see [[DigitalTwinMill/Decisions]]\n")
        self.assertEqual(self.phantoms(), {})

    def test_bare_basename_and_full_path_still_resolve(self):
        self.write("10_Projets/Logiciels/DigitalTwinMill/Decisions.md", "body\n")
        self.write("30_Ressources/Obsidian/b.md",
                   "[[Decisions]] and [[10_Projets/Logiciels/DigitalTwinMill/Decisions]]\n")
        self.assertEqual(self.phantoms(), {})

    def test_a_suffix_matching_no_note_is_still_a_phantom(self):
        self.write("10_Projets/Logiciels/DigitalTwinMill/Decisions.md", "body\n")
        self.write("30_Ressources/Obsidian/b.md", "see [[OtherProject/Decisions]]\n")
        self.assertIn("OtherProject/Decisions", self.phantoms())

    def test_suffix_must_break_on_a_folder_boundary(self):
        # "Mill/Decisions" is a substring of the path but not a path suffix: the
        # index is built on folder boundaries, not on characters.
        self.write("10_Projets/Logiciels/DigitalTwinMill/Decisions.md", "body\n")
        self.write("30_Ressources/Obsidian/b.md", "see [[Mill/Decisions]]\n")
        self.assertIn("Mill/Decisions", self.phantoms())


class AliasedLinkRepairTest(VaultTestBase):
    """P13: --apply could not repair an aliased link, the common Obsidian form. The
    detector strips the alias and reports the bare target, but the repair searched for
    the literal "[[target]]", which never matched. The dry run then reported
    "modified: []" with nothing refused, so an inability looked like a clean no-op."""

    def test_aliased_link_is_retargeted_and_keeps_its_label(self):
        p = self.write("30_Ressources/Obsidian/b.md",
                       "see [[DigitalTwinMill/Decisions|Decisions]]\n")
        report = vc.apply_map(str(self.vault),
                              {"[[DigitalTwinMill/Decisions]]": "[[10_Projets/Logiciels/DigitalTwinMill/Decisions]]"},
                              write=True)
        text = p.read_text(encoding="utf-8")
        self.assertEqual(report["modified"], ["30_Ressources/Obsidian/b.md"])
        self.assertIn("[[10_Projets/Logiciels/DigitalTwinMill/Decisions|Decisions]]", text)

    def test_heading_and_heading_plus_alias_forms_are_repaired(self):
        p = self.write("30_Ressources/Obsidian/b.md",
                       "[[Old#Section]] then [[Old#Section|Label]] then [[Old]]\n")
        vc.apply_map(str(self.vault), {"[[Old]]": "[[New]]"}, write=True)
        text = p.read_text(encoding="utf-8")
        self.assertIn("[[New#Section]]", text)
        self.assertIn("[[New#Section|Label]]", text)
        self.assertIn("[[New]]", text)
        self.assertNotIn("[[Old", text)

    def test_a_longer_target_sharing_the_prefix_is_left_alone(self):
        p = self.write("30_Ressources/Obsidian/b.md", "[[Old]] and [[Older]]\n")
        vc.apply_map(str(self.vault), {"[[Old]]": "[[New]]"}, write=True)
        text = p.read_text(encoding="utf-8")
        self.assertIn("[[New]]", text)
        self.assertIn("[[Older]]", text)

    def test_chained_keys_still_do_not_cascade(self):
        p = self.write("30_Ressources/Obsidian/b.md", "[[A]]\n")
        vc.apply_map(str(self.vault), {"[[A]]": "[[B]]", "[[B]]": "[[C]]"}, write=True)
        self.assertIn("[[B]]", p.read_text(encoding="utf-8"))

    def test_a_map_key_carrying_an_alias_is_refused(self):
        # The key names WHAT a link points at. "[[A|B]]" would silently mean "only the
        # occurrences whose alias happens to be B", which nobody authoring a map means.
        p = self.write("30_Ressources/Obsidian/b.md", "[[A|B]]\n")
        report = vc.apply_map(str(self.vault), {"[[A|B]]": "[[C]]"}, write=True)
        self.assertEqual(report["modified"], [])
        self.assertTrue(report["refused_map_entries"])
        self.assertIn("[[A|B]]", p.read_text(encoding="utf-8"))


class PhantomProvenanceTest(VaultTestBase):
    """P15: a phantom count is not a quality signal on its own. It moved 7 -> 8 -> 7
    across one evening purely because of notes that same work wrote."""

    def test_without_a_baseline_nothing_is_claimed_as_introduced(self):
        split = vc.split_inherited({"A": {}, "B": {}}, None)
        self.assertFalse(split["baseline_supplied"])
        self.assertEqual(split["inherited"], ["A", "B"])
        self.assertEqual(split["introduced"], [])

    def test_a_baseline_separates_inherited_from_introduced(self):
        split = vc.split_inherited({"A": {}, "C": {}}, {"A": {}, "B": {}})
        self.assertTrue(split["baseline_supplied"])
        self.assertEqual(split["inherited"], ["A"])
        self.assertEqual(split["introduced"], ["C"])
        self.assertEqual(split["resolved_since_baseline"], ["B"])

    def test_links_report_carries_the_provenance_block(self):
        self.write("30_Ressources/Obsidian/b.md", "see [[Nowhere]]\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = vc.main(["--vault", str(self.vault), "--mode", "links"])
        report = __import__("json").loads(out.getvalue())
        self.assertEqual(rc, 0)
        self.assertIn("Nowhere", report["phantoms"])
        self.assertFalse(report["provenance"]["baseline_supplied"])
        self.assertEqual(report["provenance"]["inherited"], ["Nowhere"])


class CliEntryPointTest(VaultTestBase):
    """The CLI's own main(), which every other case in this file bypasses by calling
    the functions directly.

    Measured 2026-08-30 on the live drill: `--mode candidates` died with
    `NameError: name 'collections' is not defined` at the line that counts term
    rarity. The import had left with the code moved out during the 2026-08-28 split
    while the usage stayed behind, and this 35-case suite stayed green throughout,
    because none of it ran main(). The daemon's consolidation drain is the ONLY
    caller of that entry point, so the defect was invisible until a drill that costs
    ten minutes and writes to the real vault.

    These cases run main() in-process on a fixture vault and assert its stdout
    parses. They are smoke tests on purpose: the behaviour is covered above, what is
    missing is proof that the entry point executes at all."""

    def setUp(self):
        super().setUp()
        self.write("30_Ressources/Python/lock-note.md",
                   "---\ntype: apprentissage\n---\n\nLocks and the outbox. See [[timeout-note]].\n")
        self.write("30_Ressources/Python/timeout-note.md",
                   "---\ntype: apprentissage\n---\n\nLocks and timeouts, another note.\n")
        self.write("10_Projets/Logiciels/Demo/Decisions.md",
                   "# Decisions\n\n- 2026-08-30 - something happened\n")

    def _run(self, *args) -> dict:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = vc.main(["--vault", str(self.vault), *args])
        self.assertEqual(code, 0)
        return __import__("json").loads(buffer.getvalue())

    def test_mode_candidates_runs_and_emits_its_report(self):
        report = self._run("--mode", "candidates", "--top", "15")
        self.assertIn("candidates", report)
        self.assertEqual(report["notes"], 3)

    def test_mode_links_runs_and_emits_its_report(self):
        report = self._run("--mode", "links")
        self.assertIn("phantoms", report)

    def test_the_default_mode_runs(self):
        # The mode the agent uses by hand, and the one a --mode typo falls back to.
        report = self._run()
        self.assertIn("candidates", report)


if __name__ == "__main__":
    unittest.main(verbosity=2)
