"""
Offline tests for docx_track.py (word2latex, tracked changes in an existing Word file).

The .docx fixtures are built in a temporary folder with python-docx from fictitious text
(R34), so no Word, no network and no real manuscript are needed. The suite is skipped,
not failed, when python-docx or lxml is absent.
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

try:
    import docx  # noqa: F401
    from lxml import etree
    import docx_track as dt  # noqa: E402
    HAVE_DEPS = True
except ImportError:
    HAVE_DEPS = False

AUTHOR = "Test Reviewer"
DATE = "2026-01-01T00:00:00Z"


def make_docx(path: Path) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Write a small .docx: one paragraph split over three runs, one paragraph
        holding a complex field (a fictitious citation), one plain paragraph, and a
        repeated sentence for the ambiguity case.

    Inputs:
        path (Path): output file.

    Outputs:
        None. Writes the file.
    --------------------------------------------------------------------------
    """
    import docx as _docx
    from docx.oxml.ns import qn

    d = _docx.Document()
    p = d.add_paragraph()
    for t in ("The robot tracks ", "the refer", "ence trajectory."):
        p.add_run(t)
    p2 = d.add_paragraph()
    p2.add_run("As shown in ")
    for kind, text in (("begin", None), ("instr", " ADDIN EN.CITE "), ("separate", None),
                       ("text", "[17]"), ("end", None)):
        r = p2.add_run(text if kind == "text" else "")
        if kind in ("begin", "separate", "end"):
            fc = etree.SubElement(r._r, qn("w:fldChar"))
            fc.set(qn("w:fldCharType"), kind)
        elif kind == "instr":
            it = etree.SubElement(r._r, qn("w:instrText"))
            it.text = text
    p2.add_run(", the gain is fixed.")
    d.add_paragraph("A plain closing sentence.")
    d.add_paragraph("Repeated text here.")
    d.add_paragraph("Repeated text here.")
    d.save(str(path))


@unittest.skipUnless(HAVE_DEPS, "python-docx or lxml not installed")
class DocxTrackTest(unittest.TestCase):
    """Behaviour of the edit operations, the refusals and the read-back."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.src = self.dir / "in.docx"
        make_docx(self.src)
        self.out = self.dir / "out.docx"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_edits(self, edits: list[dict], dry_run: bool = False) -> "dt.Report":
        return dt.apply_file(self.src, edits, self.out, AUTHOR, DATE, dry_run)

    def accepted(self) -> list[str]:
        return dt.view_texts(dt.read_document(self.out), accepted=True)

    def test_replace_across_runs(self) -> None:
        rep = self.run_edits([{"op": "replace", "find": "reference trajectory", "with": "desired path"}])
        self.assertEqual(rep.fails, [])
        self.assertTrue(rep.verified)
        self.assertIn("The robot tracks the desired path.", self.accepted())
        root = dt.read_document(self.out)
        dels = "".join(t.text for t in root.iter(dt.w("delText")))
        self.assertEqual(dels, "reference trajectory")
        ins = root.find(f".//{dt.w('ins')}")
        self.assertEqual(ins.get(dt.w("author")), AUTHOR)
        self.assertEqual(ins.get(dt.w("date")), DATE)

    def test_insert_after_and_before(self) -> None:
        rep = self.run_edits([
            {"op": "insert_after", "anchor": "The robot tracks", "text": " closely"},
            {"op": "insert_before", "anchor": "A plain", "text": "Finally, "},
        ])
        self.assertEqual(rep.fails, [])
        acc = self.accepted()
        self.assertIn("The robot tracks closely the reference trajectory.", acc)
        self.assertIn("Finally, A plain closing sentence.", acc)
        self.assertTrue(rep.verified)

    def test_delete(self) -> None:
        rep = self.run_edits([{"op": "delete", "find": " closing"}])
        self.assertIn("A plain sentence.", self.accepted())
        self.assertTrue(rep.verified)

    def test_insert_paragraphs_marks_paragraph_insertion(self) -> None:
        rep = self.run_edits([{"op": "insert_paragraphs_after", "anchor": "A plain closing",
                               "paragraphs": ["New one.", "New two."], "highlight": "cyan"}])
        acc = self.accepted()
        i = acc.index("A plain closing sentence.")
        self.assertEqual(acc[i + 1:i + 3], ["New one.", "New two."])
        root = dt.read_document(self.out)
        marks = root.findall(f".//{dt.w('pPr')}/{dt.w('rPr')}/{dt.w('ins')}")
        self.assertEqual(len(marks), 2)
        hls = [h.get(dt.w("val")) for h in root.iter(dt.w("highlight"))]
        self.assertEqual(hls, ["cyan", "cyan"])
        self.assertTrue(rep.verified)

    def test_not_found_writes_nothing(self) -> None:
        rep = self.run_edits([{"op": "delete", "find": "absent words"}])
        self.assertEqual(len(rep.fails), 1)
        self.assertIn("not found", rep.fails[0]["reason"])
        self.assertFalse(self.out.exists())

    def test_ambiguous_then_occurrence(self) -> None:
        rep = self.run_edits([{"op": "replace", "find": "Repeated", "with": "Unique"}])
        self.assertIn("ambiguous (2 matches)", rep.fails[0]["reason"])
        rep = self.run_edits([{"op": "replace", "find": "Repeated", "with": "Unique", "occurrence": 2}])
        self.assertEqual(rep.fails, [])
        self.assertEqual(self.accepted()[-2:], ["Repeated text here.", "Unique text here."])

    def test_field_result_is_refused(self) -> None:
        rep = self.run_edits([{"op": "replace", "find": "[17]", "with": "[18]"}])
        self.assertIn("field", rep.fails[0]["reason"])
        rep = self.run_edits([{"op": "insert_after", "anchor": "As shown in [17]", "text": " x"}])
        self.assertIn("field", rep.fails[0]["reason"])

    def test_text_next_to_field_is_allowed(self) -> None:
        rep = self.run_edits([{"op": "insert_before", "anchor": ", the gain", "text": " {Doe, 2020}"}])
        self.assertEqual(rep.fails, [])
        self.assertIn("As shown in [17] {Doe, 2020}, the gain is fixed.", self.accepted())

    def test_render_hint_does_not_block_a_split_but_a_tab_does(self) -> None:
        root = dt.read_document(self.src)
        p = [q for q in dt.body_paragraphs(root) if dt.paragraph_text(q) == "A plain closing sentence."][0]
        run = p.find(dt.w("r"))
        run.insert(1, etree.Element(dt.w("lastRenderedPageBreak")))
        rev = dt.Reviser(root, AUTHOR, DATE)
        dt.apply_edit(root, rev, {"op": "replace", "find": "plain", "with": "short"})
        self.assertIn("A short closing sentence.", dt.view_texts(root, accepted=True))
        self.assertEqual(len(list(root.iter(dt.w("lastRenderedPageBreak")))), 1)
        p2 = [q for q in dt.body_paragraphs(root) if dt.paragraph_text(q).startswith("The robot")][0]
        p2.find(dt.w("r")).insert(1, etree.Element(dt.w("tab")))
        with self.assertRaises(dt.EditError):
            dt.apply_edit(root, rev, {"op": "replace", "find": "robot", "with": "arm"})

    def test_one_failure_blocks_every_edit(self) -> None:
        rep = self.run_edits([{"op": "delete", "find": " closing"}, {"op": "delete", "find": "nowhere"}])
        self.assertEqual(rep.applied, ["#1"])
        self.assertEqual(len(rep.fails), 1)
        self.assertFalse(self.out.exists())

    def test_dry_run_writes_nothing(self) -> None:
        rep = self.run_edits([{"op": "delete", "find": " closing"}], dry_run=True)
        self.assertEqual(rep.applied, ["#1"])
        self.assertFalse(self.out.exists())

    def test_revision_ids_unique(self) -> None:
        self.run_edits([{"op": "replace", "find": "reference trajectory", "with": "path"},
                        {"op": "insert_paragraphs_after", "anchor": "A plain", "paragraphs": ["X."]}])
        root = dt.read_document(self.out)
        ids = [e.get(dt.w("id")) for e in root.iter(dt.w("ins"), dt.w("del"))]
        self.assertEqual(len(ids), len(set(ids)))

    def test_other_parts_byte_identical(self) -> None:
        self.run_edits([{"op": "delete", "find": " closing"}])
        with zipfile.ZipFile(self.src) as a, zipfile.ZipFile(self.out) as b:
            for name in a.namelist():
                if name != dt.DOC_PART:
                    self.assertEqual(a.read(name), b.read(name), name)

    def test_document_part_keeps_word_declaration(self) -> None:
        self.run_edits([{"op": "delete", "find": " closing"}])
        with zipfile.ZipFile(self.out) as z:
            head = z.read(dt.DOC_PART)[:80]
        self.assertTrue(head.startswith(b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'))
        self.assertNotIn(b"<?xml version='1.0'", head)

    def test_verify_detects_a_changed_original(self) -> None:
        self.run_edits([{"op": "delete", "find": " closing"}])
        tampered = dt.read_document(self.out)
        for t in tampered.iter(dt.w("t")):
            if t.text == "A plain":
                t.text = "B plain"
        self.assertFalse(dt.verify(dt.read_document(self.src), tampered))

    def test_unknown_op_and_missing_key(self) -> None:
        rep = self.run_edits([{"op": "move", "find": "x"}, {"op": "replace", "find": "A plain"}])
        self.assertIn("unknown op", rep.fails[0]["reason"])
        self.assertIn("needs key", rep.fails[1]["reason"])

    def test_cli_exit_codes(self) -> None:
        edits = self.dir / "edits.json"
        edits.write_text(json.dumps({"edits": [{"op": "delete", "find": " closing"}]}), encoding="utf-8")
        base = ["apply", str(self.src), str(edits), "--author", AUTHOR, "--date", DATE]
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(dt.main(base + ["-o", str(self.src)]), 2)
            self.assertEqual(dt.main(base + ["-o", str(self.out)]), 0)
            edits.write_text(json.dumps({"edits": [{"op": "delete", "find": "zzz"}]}), encoding="utf-8")
            self.assertEqual(dt.main(base + ["-o", str(self.dir / "o2.docx")]), 1)
            edits.write_text("[]", encoding="utf-8")
            self.assertEqual(dt.main(base + ["-o", str(self.dir / "o3.docx")]), 2)

    def test_paragraphs_listing(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(dt.main(["paragraphs", str(self.src), "--json"]), 0)
        rows = json.loads(buf.getvalue())
        self.assertIn("As shown in [17], the gain is fixed.", [r["text"] for r in rows])


if __name__ == "__main__":
    unittest.main()
