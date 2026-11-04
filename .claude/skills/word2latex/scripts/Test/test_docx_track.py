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

    # ---- Review round 1 (2026-11-04): each case below failed on commit 75b494d ----

    def _rewrite(self, mutate) -> Path:
        """Write a copy of the fixture whose document part was changed by `mutate(root)`."""
        root = dt.read_document(self.src)
        mutate(root)
        path = self.dir / "variant.docx"
        dt.write_docx(self.src, path, root)
        return path

    def _para(self, root, prefix: str):
        return [q for q in dt.body_paragraphs(root) if dt.paragraph_text(q).startswith(prefix)][0]

    def test_prior_tracked_insertion_still_verifies(self) -> None:
        # A co-author's earlier insertion is kept by the accepted view and dropped by the
        # rejected one; comparing those two views made every such file a MISMATCH.
        def mutate(root):
            run = self._para(root, "A plain").find(dt.w("r"))
            ins = etree.Element(dt.w("ins"))
            for k, v in (("id", "900"), ("author", "Earlier Author"), ("date", DATE)):
                ins.set(dt.w(k), v)
            run.addprevious(ins)
            ins.append(run)
        src = self._rewrite(mutate)
        rep = dt.apply_file(src, [{"op": "delete", "find": "robot "}], self.out, AUTHOR, DATE, False)
        self.assertEqual(rep.fails, [])
        self.assertTrue(rep.verified)

    def test_field_spanning_paragraphs_is_refused_in_its_middle(self) -> None:
        # An EndNote bibliography field opens in one paragraph and closes in a later one;
        # resetting the depth per paragraph let an edit land in the middle of it.
        def mutate(root):
            first = self._para(root, "Repeated")
            begin = etree.SubElement(first, dt.w("r"))
            etree.SubElement(begin, dt.w("fldChar")).set(dt.w("fldCharType"), "begin")
            etree.SubElement(begin, dt.w("instrText")).text = " ADDIN EN.REFLIST "
            etree.SubElement(begin, dt.w("fldChar")).set(dt.w("fldCharType"), "separate")
            middle = etree.Element(dt.w("p"))
            etree.SubElement(etree.SubElement(middle, dt.w("r")), dt.w("t")).text = "Middle entry of the list."
            first.addnext(middle)
            last = [q for q in dt.body_paragraphs(root) if dt.paragraph_text(q) == "Repeated text here."][-1]
            end = etree.SubElement(last, dt.w("r"))
            etree.SubElement(end, dt.w("fldChar")).set(dt.w("fldCharType"), "end")
        src = self._rewrite(mutate)
        rep = dt.apply_file(src, [{"op": "replace", "find": "Middle entry", "with": "Other"}],
                            self.out, AUTHOR, DATE, False)
        self.assertEqual(len(rep.fails), 1)
        self.assertIn("field", rep.fails[0]["reason"])
        # Control: text after the field closed is still editable.
        rep = dt.apply_file(src, [{"op": "replace", "find": "A plain", "with": "A short"}],
                            self.out, AUTHOR, DATE, False)
        self.assertEqual(rep.fails, [])

    def test_fully_covered_run_with_a_tab_is_not_deleted(self) -> None:
        # A run "Name:<tab>Doe" read as "Name:Doe" and, covered whole, went into w:del
        # with its tab, while the read-back (which ignores tabs) still passed.
        def mutate(root):
            run = self._para(root, "A plain").find(dt.w("r"))
            for t in run.findall(dt.w("t")):
                run.remove(t)
            etree.SubElement(run, dt.w("t")).text = "Name:"
            etree.SubElement(run, dt.w("tab"))
            etree.SubElement(run, dt.w("t")).text = "Doe"
        src = self._rewrite(mutate)
        for find in ("Name:Doe", "Name:\tDoe"):
            with self.subTest(find=find):
                rep = dt.apply_file(src, [{"op": "delete", "find": find}], self.out, AUTHOR, DATE, False)
                self.assertEqual(len(rep.fails), 1)
                self.assertFalse(self.out.exists())

    def test_malformed_edit_is_a_failure_not_a_crash(self) -> None:
        for bad in ({"op": "delete", "find": 5}, {"op": "insert_paragraphs_after", "anchor": "A plain",
                                                  "paragraphs": "Hello"}, "not an object"):
            with self.subTest(bad=bad):
                rep = self.run_edits([bad])
                self.assertEqual(len(rep.fails), 1)
                self.assertFalse(self.out.exists())

    def test_input_that_is_not_a_docx_is_a_refusal(self) -> None:
        fake = self.dir / "renamed.docx"
        fake.write_bytes(b"not a zip archive")
        edits = self.dir / "edits.json"
        edits.write_text(json.dumps({"edits": [{"op": "delete", "find": "x"}]}), encoding="utf-8")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(dt.main(["paragraphs", str(fake)]), 2)
            self.assertEqual(dt.main(["apply", str(fake), str(edits), "-o", str(self.out),
                                      "--author", AUTHOR, "--date", DATE]), 2)

    # ---- Review round 2 (2026-11-04): each case below failed on commit 5282c21 ----

    def _open_field_after_first_repeated(self, root) -> None:
        """Open a field at the end of the first 'Repeated' paragraph, close it in the second."""
        first = self._para(root, "Repeated")
        begin = etree.SubElement(first, dt.w("r"))
        etree.SubElement(begin, dt.w("fldChar")).set(dt.w("fldCharType"), "begin")
        etree.SubElement(begin, dt.w("instrText")).text = " ADDIN EN.REFLIST "
        etree.SubElement(begin, dt.w("fldChar")).set(dt.w("fldCharType"), "separate")
        last = [q for q in dt.body_paragraphs(root) if dt.paragraph_text(q) == "Repeated text here."][-1]
        etree.SubElement(etree.SubElement(last, dt.w("r")), dt.w("fldChar")).set(dt.w("fldCharType"), "end")

    def test_new_paragraphs_are_never_written_inside_a_field(self) -> None:
        src = self._rewrite(self._open_field_after_first_repeated)
        for occ in (1, 2):
            with self.subTest(occurrence=occ):
                rep = dt.apply_file(src, [{"op": "insert_paragraphs_after", "anchor": "Repeated",
                                           "occurrence": occ, "paragraphs": ["X."]}],
                                    self.out, AUTHOR, DATE, False)
                self.assertEqual(len(rep.fails), 1)
                self.assertIn("field", rep.fails[0]["reason"])
        # Control: a paragraph outside the field still takes new paragraphs.
        rep = dt.apply_file(src, [{"op": "insert_paragraphs_after", "anchor": "A plain",
                                   "paragraphs": ["X."]}], self.out, AUTHOR, DATE, False)
        self.assertEqual(rep.fails, [])

    def test_match_across_a_footnote_reference_is_refused(self) -> None:
        def mutate(root):
            p = self._para(root, "A plain")
            run = p.find(dt.w("r"))
            run.find(dt.w("t")).text = "A plain"
            ref = etree.Element(dt.w("r"))
            etree.SubElement(ref, dt.w("footnoteReference")).set(dt.w("id"), "1")
            tail = etree.Element(dt.w("r"))
            etree.SubElement(tail, dt.w("t")).text = " closing sentence."
            run.addnext(ref)
            ref.addnext(tail)
        src = self._rewrite(mutate)
        rep = dt.apply_file(src, [{"op": "replace", "find": "plain closing", "with": "short"}],
                            self.out, AUTHOR, DATE, False)
        self.assertEqual(len(rep.fails), 1)
        self.assertFalse(self.out.exists())
        rep = dt.apply_file(src, [{"op": "replace", "find": "plain", "with": "short"}],
                            self.out, AUTHOR, DATE, False)
        self.assertEqual(rep.fails, [])
        self.assertTrue(rep.verified)

    def _template_rpr(self, root, *children) -> None:
        run = self._para(root, "A plain").find(dt.w("r"))
        rpr = run.find(dt.w("rPr"))
        if rpr is None:
            rpr = etree.Element(dt.w("rPr"))
            run.insert(0, rpr)
        for el in children:
            rpr.append(el)

    def test_inserted_text_does_not_copy_a_formatting_revision(self) -> None:
        def mutate(root):
            change = etree.Element(dt.w("rPrChange"))
            for k, v in (("id", "12"), ("author", "Earlier Author"), ("date", DATE)):
                change.set(dt.w(k), v)
            etree.SubElement(change, dt.w("rPr"))
            self._template_rpr(root, change)
        src = self._rewrite(mutate)
        rep = dt.apply_file(src, [{"op": "insert_after", "anchor": "A plain", "text": " short"}],
                            self.out, AUTHOR, DATE, False)
        self.assertEqual(rep.fails, [])
        root = dt.read_document(self.out)
        self.assertEqual(root.findall(f".//{dt.w('ins')}//{dt.w('rPrChange')}"), [])
        # The anchor run is split in two; both halves keep the formatting revision, each
        # under its own id (a deepcopy alone gave both halves id 12).
        self.assertEqual(len(list(root.iter(dt.w("rPrChange")))), 2)
        ids = [e.get(dt.w("id")) for e in root.iter() if e.get(dt.w("id")) is not None
               and etree.QName(e).localname in ("ins", "del", "rPrChange")]
        self.assertEqual(len(ids), len(set(ids)))

    def test_highlight_keeps_the_schema_order_of_rpr(self) -> None:
        def mutate(root):
            self._template_rpr(root, etree.Element(dt.w("sz")), etree.Element(dt.w("u")),
                               etree.Element(dt.w("lang")))
        src = self._rewrite(mutate)
        rep = dt.apply_file(src, [{"op": "insert_after", "anchor": "A plain", "text": " short",
                                   "highlight": "cyan"}], self.out, AUTHOR, DATE, False)
        self.assertEqual(rep.fails, [])
        rpr = dt.read_document(self.out).find(f".//{dt.w('ins')}/{dt.w('r')}/{dt.w('rPr')}")
        names = [etree.QName(c).localname for c in rpr]
        self.assertLess(names.index("sz"), names.index("highlight"))
        self.assertLess(names.index("highlight"), names.index("u"))

    def test_failed_read_back_leaves_nothing_on_disk(self) -> None:
        orig = dt.verify
        dt.verify = lambda a, b: False
        try:
            rep = self.run_edits([{"op": "delete", "find": " closing"}])
        finally:
            dt.verify = orig
        self.assertFalse(rep.verified)
        self.assertIsNone(rep.written)
        self.assertFalse(self.out.exists())
        self.assertEqual([p.name for p in self.dir.iterdir() if p.suffix == ".tmp"], [])

    # ---- Review round 3 (2026-11-04): each case below failed on commit f75b536 ----

    def test_more_malformed_edits_fail_cleanly(self) -> None:
        for bad in ({"op": ["replace"], "find": "A plain", "with": "B"},
                    {"op": "replace", "find": "A plain", "with": None},
                    {"op": "replace", "find": "A plain", "with": ""},
                    {"op": "insert_after", "anchor": "A plain", "text": ""},
                    {"op": "insert_after", "anchor": "A plain", "text": " x", "highlight": "Cyan"}):
            with self.subTest(bad=bad):
                rep = self.run_edits([bad])
                self.assertEqual(len(rep.fails), 1)
                self.assertFalse(self.out.exists())

    def test_bad_date_or_missing_output_folder_is_a_refusal(self) -> None:
        edits = self.dir / "edits.json"
        edits.write_text(json.dumps({"edits": [{"op": "delete", "find": " closing"}]}), encoding="utf-8")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(dt.main(["apply", str(self.src), str(edits), "-o", str(self.out),
                                      "--author", AUTHOR, "--date", "2026-10-30"]), 2)
            self.assertEqual(dt.main(["apply", str(self.src), str(edits), "-o",
                                      str(self.dir / "absent" / "o.docx"), "--author", AUTHOR,
                                      "--date", DATE]), 2)
        self.assertFalse(self.out.exists())

    # ---- Review round 4 (2026-11-04): each case below failed on commit ff7e985 ----

    def test_new_paragraphs_after_a_paragraph_holding_a_closed_citation(self) -> None:
        # Round 2 refused every paragraph holding a citation field, closed or not, which
        # made the op unusable in a reviewer response; only an open field must block it.
        rep = self.run_edits([{"op": "insert_paragraphs_after", "anchor": "the gain is fixed",
                               "paragraphs": ["X."]}])
        self.assertEqual(rep.fails, [])
        self.assertTrue(rep.verified)

    def test_locked_output_is_a_refusal(self) -> None:
        edits = self.dir / "edits.json"
        edits.write_text(json.dumps({"edits": [{"op": "delete", "find": " closing"}]}), encoding="utf-8")
        orig = dt.write_docx

        def locked(*a, **k):
            raise PermissionError(13, "The process cannot access the file")
        dt.write_docx = locked
        try:
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = dt.main(["apply", str(self.src), str(edits), "-o", str(self.out),
                                "--author", AUTHOR, "--date", DATE])
        finally:
            dt.write_docx = orig
        self.assertEqual(code, 2)

    def test_paragraphs_listing(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(dt.main(["paragraphs", str(self.src), "--json"]), 0)
        rows = json.loads(buf.getvalue())
        self.assertIn("As shown in [17], the gain is fixed.", [r["text"] for r in rows])


if __name__ == "__main__":
    unittest.main()
