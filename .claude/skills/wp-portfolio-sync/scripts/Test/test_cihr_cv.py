"""
test_cihr_cv.py - offline tests for cihr_cv.py.

Proves: the four-key, no-supervision contract (D2), data minimisation (the
student name is never written even though the XML carries it), nested
section discovery, the wrong-root and zero-record refusals, and both
input and output containment (D7: the XML itself lives under --data-dir,
same as cihr.json).
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

import cihr_cv
import wp_paths


class TestParseCihr(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.xml_path = Path(self.tmp.name) / "cv.xml"
        write_cihr_xml(self.xml_path)
        self.root = ET.parse(str(self.xml_path)).getroot()

    def test_keys_and_counts(self):
        data = cihr_cv.parse_cihr(self.root)
        self.assertEqual(
            set(data.keys()), {"financement", "implications", "services_communaute", "distinctions"}
        )
        self.assertEqual(len(data["financement"]), 2)
        self.assertEqual(len(data["implications"]), 2)
        self.assertEqual(len(data["services_communaute"]), 3)
        self.assertEqual(len(data["distinctions"]["prix"]), 1)
        self.assertEqual(len(data["distinctions"]["contributions_cles"]), 1)

    def test_no_supervision_key(self):
        data = cihr_cv.parse_cihr(self.root)
        self.assertNotIn("supervision", data)

    def test_nested_services_found(self):
        data = cihr_cv.parse_cihr(self.root)
        kinds = {item["type"] for item in data["services_communaute"]}
        self.assertEqual(kinds, {"media", "entreprise", "evenement"})


class TestMain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name) / "data"
        self.data_dir.mkdir()
        self.xml_path = self.data_dir / "cv.xml"
        write_cihr_xml(self.xml_path)

    def test_student_never_written(self):
        out = self.data_dir / "cihr.json"
        code = cihr_cv.main(
            [str(self.xml_path), "--data-dir", str(self.data_dir), "--out", "cihr.json"]
        )
        self.assertEqual(code, 0)
        text = out.read_text(encoding="utf-8")
        self.assertNotIn("Étudiante Témoin Zeta", text)

    def test_relative_xml_resolved_against_data_dir(self):
        out = self.data_dir / "cihr.json"
        code = cihr_cv.main(["cv.xml", "--data-dir", str(self.data_dir), "--out", "cihr.json"])
        self.assertEqual(code, 0)
        self.assertTrue(out.exists())

    def test_xml_outside_data_dir_refused(self):
        outside_xml = Path(self.tmp.name) / "outside.xml"
        write_cihr_xml(outside_xml)
        code = cihr_cv.main([str(outside_xml), "--data-dir", str(self.data_dir)])
        self.assertEqual(code, 2)

    def test_xml_parent_escape_refused(self):
        outside_xml = Path(self.tmp.name) / "outside.xml"
        write_cihr_xml(outside_xml)
        code = cihr_cv.main(["..\\outside.xml", "--data-dir", str(self.data_dir)])
        self.assertEqual(code, 2)

    def test_wrong_root_refused(self):
        bad_xml = self.data_dir / "bad.xml"
        ET.ElementTree(ET.Element("cv")).write(str(bad_xml))
        code = cihr_cv.main([str(bad_xml), "--data-dir", str(self.data_dir)])
        self.assertEqual(code, 1)

    def test_zero_records_refused(self):
        empty_xml = self.data_dir / "empty.xml"
        ET.ElementTree(ET.Element("generic-cv")).write(str(empty_xml))
        code = cihr_cv.main([str(empty_xml), "--data-dir", str(self.data_dir), "--out", "empty.json"])
        self.assertEqual(code, 1)
        self.assertFalse((self.data_dir / "empty.json").exists())

    def test_out_outside_data_dir_refused(self):
        code = cihr_cv.main(
            [str(self.xml_path), "--data-dir", str(self.data_dir), "--out", "..\\x.json"]
        )
        self.assertEqual(code, 2)

    def test_data_dir_in_repo_refused(self):
        code = cihr_cv.main([str(self.xml_path), "--data-dir", str(wp_paths.repo_root())])
        self.assertEqual(code, 2)

    def test_json_report(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cihr_cv.main(
                [str(self.xml_path), "--data-dir", str(self.data_dir), "--out", "cihr.json", "--json"]
            )
        self.assertEqual(code, 0)
        report = json.loads(buf.getvalue())
        self.assertEqual(report["counts"]["financement"], 2)

    def test_dry_run_writes_nothing(self):
        out = self.data_dir / "cihr.json"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cihr_cv.main(
                [str(self.xml_path), "--data-dir", str(self.data_dir), "--out", "cihr.json", "--dry-run", "--json"]
            )
        self.assertEqual(code, 0)
        self.assertFalse(out.exists())
        report = json.loads(buf.getvalue())
        self.assertTrue(report["dry_run"])
        self.assertEqual(report["counts"]["financement"], 2)


if __name__ == "__main__":
    unittest.main()
