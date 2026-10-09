"""
test_parse_cv.py - offline tests for parse_cv.py (the generic XML parser).

Ports the draft's elem_to_obj test with a fictitious name, and adds the
invalid-XML, input/output-containment (D7), dry-run (R16), and CIHR-export
refusal (D2 - the generic parser has no section filtering at all, so a
CIHR/CCV export routed here instead of cihr_cv.py would publish whatever
the tree holds, supervision included) cases this skill's contract requires.
"""
import contextlib
import io
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import _fixtures  # noqa: F401
from _fixtures import write_cihr_xml

import parse_cv


class TestElemToObj(unittest.TestCase):
    def test_repeated_siblings_become_list(self):
        root = ET.fromstring(
            "<cv><name>Camille Exemple</name><pub>A</pub><pub>B</pub></cv>"
        )
        obj = parse_cv.elem_to_obj(root)
        self.assertEqual(obj["name"], "Camille Exemple")
        self.assertEqual(obj["pub"], ["A", "B"])

    def test_text_and_children_mixed(self):
        root = ET.fromstring("<cv>intro<child>x</child></cv>")
        obj = parse_cv.elem_to_obj(root)
        self.assertEqual(obj["_text"], "intro")
        self.assertEqual(obj["child"], "x")


class TestMain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name) / "data"
        self.data_dir.mkdir()
        self.xml_path = self.data_dir / "cv.xml"
        self.xml_path.write_text(
            "<cv><name>Camille Exemple</name><experience>A</experience></cv>", encoding="utf-8"
        )

    def test_writes_generic_json(self):
        code = parse_cv.main([str(self.xml_path), "--data-dir", str(self.data_dir), "--out", "cv.json"])
        self.assertEqual(code, 0)
        data = json.loads((self.data_dir / "cv.json").read_text(encoding="utf-8"))
        self.assertEqual(data["cv"]["name"], "Camille Exemple")

    def test_relative_xml_resolved_against_data_dir(self):
        code = parse_cv.main(["cv.xml", "--data-dir", str(self.data_dir), "--out", "cv.json"])
        self.assertEqual(code, 0)
        self.assertTrue((self.data_dir / "cv.json").exists())

    def test_xml_outside_data_dir_refused(self):
        outside = Path(self.tmp.name) / "outside.xml"
        outside.write_text("<cv/>", encoding="utf-8")
        code = parse_cv.main([str(outside), "--data-dir", str(self.data_dir)])
        self.assertEqual(code, 2)

    def test_invalid_xml_returns_1(self):
        bad = self.data_dir / "bad.xml"
        bad.write_text("<cv><unclosed>", encoding="utf-8")
        code = parse_cv.main([str(bad), "--data-dir", str(self.data_dir)])
        self.assertEqual(code, 1)

    def test_out_contained(self):
        code = parse_cv.main(
            [str(self.xml_path), "--data-dir", str(self.data_dir), "--out", "..\\x.json"]
        )
        self.assertEqual(code, 2)

    def test_json_report(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = parse_cv.main(
                [str(self.xml_path), "--data-dir", str(self.data_dir), "--out", "cv.json", "--json"]
            )
        self.assertEqual(code, 0)
        report = json.loads(buf.getvalue())
        self.assertIn("out", report)

    def test_dry_run_writes_nothing(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = parse_cv.main(
                [str(self.xml_path), "--data-dir", str(self.data_dir), "--out", "cv.json", "--dry-run", "--json"]
            )
        self.assertEqual(code, 0)
        self.assertFalse((self.data_dir / "cv.json").exists())
        report = json.loads(buf.getvalue())
        self.assertTrue(report["dry_run"])

    def test_json_report_on_refusal(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = parse_cv.main([str(self.xml_path), "--data-dir", str(self.data_dir), "--out", "..\\x.json", "--json"])
        self.assertEqual(code, 2)
        report = json.loads(buf.getvalue())
        self.assertEqual(report["exit_code"], 2)

    def test_json_report_on_invalid_xml(self):
        bad = self.data_dir / "bad.xml"
        bad.write_text("<cv><unclosed>", encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = parse_cv.main([str(bad), "--data-dir", str(self.data_dir), "--json"])
        self.assertEqual(code, 1)
        report = json.loads(buf.getvalue())
        self.assertEqual(report["exit_code"], 1)

    def test_cihr_export_refused(self):
        cihr_xml = self.data_dir / "cihr_export.xml"
        write_cihr_xml(cihr_xml)
        code = parse_cv.main([str(cihr_xml), "--data-dir", str(self.data_dir)])
        self.assertEqual(code, 1)
        self.assertFalse((self.data_dir / "cv.json").exists())


if __name__ == "__main__":
    unittest.main()
