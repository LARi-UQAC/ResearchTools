"""
Offline tests for cv_common.py: filename compliance (normes_presentation.pdf),
contribution-types loading, and author-identity resolution. No network, no
LaTeX, no dependency on the machine's real active profile (R21) - every
profile/contribution-types file used here is a fixture under tempfile.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv_common  # noqa: E402


class TestBuildFrqFilename(unittest.TestCase):
    def test_builds_compliant_filename(self):
        name = cv_common.build_frq_filename("Otis", "XXXYY1234", "CVdescriptif")
        self.assertEqual(name, "OTIS_XXXYY1234_CVdescriptif.pdf")

    def test_strips_accents_and_forbidden_characters(self):
        name = cv_common.build_frq_filename("Émond-Larose", "ABCDE1234", "CV (final)")
        # accents stripped, hyphen kept (not in the forbidden set), space and
        # parentheses removed.
        self.assertEqual(name, "EMOND-LAROSE_ABCDE1234_CVfinal.pdf")

    def test_rejects_malformed_frq_id(self):
        with self.assertRaises(cv_common.CvDataError):
            cv_common.build_frq_filename("Otis", "12345678", "CV")

    def test_truncates_to_fifty_characters(self):
        long_title = "Titre" * 20
        name = cv_common.build_frq_filename("Otis", "XXXYY1234", long_title)
        self.assertLessEqual(len(name), 50)
        self.assertTrue(name.endswith(".pdf"))

    def test_refuses_when_truncation_leaves_no_usable_title(self):
        # surname alone already consumes nearly the whole 50-character budget
        with self.assertRaises(cv_common.CvDataError):
            cv_common.build_frq_filename("A" * 40, "XXXYY1234", "SomeTitle")


class TestLoadContributionTypes(unittest.TestCase):
    def test_missing_file_raises(self):
        with self.assertRaises(cv_common.CvDataError):
            cv_common.load_contribution_types("/no/such/file.json")

    def test_malformed_json_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text("{not json", encoding="utf-8")
            with self.assertRaises(cv_common.CvDataError):
                cv_common.load_contribution_types(bad)

    def test_real_shipped_file_loads_and_has_expected_shape(self):
        data = cv_common.load_contribution_types()
        self.assertIn("sections", data)
        self.assertIn("clienteles", data)
        self.assertEqual(data["sections"]["2"]["max_items"], 10)
        self.assertEqual(data["page_budget"]["fr"], 6)
        self.assertEqual(data["page_budget"]["en"], 5)


class TestLoadAuthorIdentity(unittest.TestCase):
    def _write_profile(self, tmp, body):
        path = Path(tmp) / "profile.yaml"
        path.write_text(body, encoding="utf-8")
        return path

    def test_missing_profile_raises(self):
        with self.assertRaises(cv_common.CvDataError):
            cv_common.load_author_identity(path="/no/such/profile.yaml")

    def test_missing_author_block_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_profile(tmp, "name: engineering\n")
            with self.assertRaises(cv_common.CvDataError):
                cv_common.load_author_identity(path=path)

    def test_missing_required_key_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_profile(tmp, "author:\n  name: Jane Doe\n")
            with self.assertRaises(cv_common.CvDataError):
                cv_common.load_author_identity(path=path)

    def test_complete_author_block_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_profile(
                tmp,
                "author:\n"
                "  name: Jane Doe\n"
                "  email: jane@example.org\n"
                "  institution: Example University\n"
                "  department: Example Department\n",
            )
            identity = cv_common.load_author_identity(path=path)
            self.assertEqual(identity["name"], "Jane Doe")


class TestLoadCvProjectDir(unittest.TestCase):
    def _write_profile(self, tmp, body):
        path = Path(tmp) / "profile.yaml"
        path.write_text(body, encoding="utf-8")
        return path

    def test_missing_profile_raises(self):
        with self.assertRaises(cv_common.CvDataError):
            cv_common.load_cv_project_dir(path="/no/such/profile.yaml")

    def test_missing_cv_block_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_profile(tmp, "name: engineering\n")
            with self.assertRaises(cv_common.CvDataError):
                cv_common.load_cv_project_dir(path=path)

    def test_empty_project_dir_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_profile(tmp, "cv:\n  project_dir: \"\"\n")
            with self.assertRaises(cv_common.CvDataError):
                cv_common.load_cv_project_dir(path=path)

    def test_configured_project_dir_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_profile(tmp, 'cv:\n  project_dir: "C:\\\\Example\\\\CV_Project"\n')
            result = cv_common.load_cv_project_dir(path=path)
            self.assertEqual(str(result), r"C:\Example\CV_Project")


if __name__ == "__main__":
    unittest.main()
