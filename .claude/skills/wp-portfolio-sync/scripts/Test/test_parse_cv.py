"""
test_parse_cv.py - offline tests for parse_cv.py (the generic XML parser).

Ports the draft's elem_to_obj test with a fictitious name, and adds the
invalid-XML and output-containment cases this skill's contract requires.
"""
import contextlib
import io
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import _fixtures  # noqa: F401

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
        self.xml_path = Path(self.tmp.name) / "cv.xml"
        self.xml_path.write_text(
            "<cv><name>Camille Exemple</name><experience>A</experience></cv>", encoding="utf-8"
        )

    def test_writes_generic_json(self):
        code = parse_cv.main([str(self.xml_path), "--data-dir", str(self.data_dir), "--out", "cv.json"])
        self.assertEqual(code, 0)
        data = json.loads((self.data_dir / "cv.json").read_text(encoding="utf-8"))
        self.assertEqual(data["cv"]["name"], "Camille Exemple")

    def test_invalid_xml_returns_1(self):
        bad = Path(self.tmp.name) / "bad.xml"
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


if __name__ == "__main__":
    unittest.main()
