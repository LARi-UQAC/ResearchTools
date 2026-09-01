"""
Offline tests for talk_doctor.py: the preflight reports per target, distinguishes
"absent" from "not probed", and fails only on a hard requirement. Every probe is
patched, so nothing is imported, installed or launched.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import talk_doctor as td  # noqa: E402


def fake_env(python_ok=True, which_ok=True):
    """Patch the two probes; which_ok may be a set of available commands."""
    def which(name):
        if isinstance(which_ok, (set, frozenset)):
            return f"/usr/bin/{name}" if name in which_ok else None
        return f"/usr/bin/{name}" if which_ok else None

    def py(module):
        if isinstance(python_ok, (set, frozenset)):
            return module in python_ok
        return python_ok

    return mock.patch.object(td.shutil, "which", side_effect=which), \
        mock.patch.object(td, "_python_ok", side_effect=py)


class TestDiagnose(unittest.TestCase):
    def test_a_complete_machine_can_build_every_target(self):
        w, p = fake_env()
        with w, p:
            report = td.diagnose(check_com=False)
        self.assertTrue(all(report["buildable"].values()))
        self.assertEqual(report["blockers"], [])

    def test_no_jinja_blocks_beamer_and_web_but_not_pptx(self):
        w, p = fake_env(python_ok={"pptx", "pypdf", "defusedxml", "fitz"})
        with w, p:
            report = td.diagnose(check_com=False)
        self.assertTrue(report["buildable"]["pptx"])
        self.assertFalse(report["buildable"]["beamer"])
        self.assertFalse(report["buildable"]["web"])

    def test_no_pdflatex_blocks_beamer_alone(self):
        w, p = fake_env(which_ok={"pdftoppm", "soffice", "node", "drawio"})
        with w, p:
            report = td.diagnose(check_com=False)
        self.assertFalse(report["buildable"]["beamer"])
        self.assertTrue(report["buildable"]["web"])

    def test_missing_poppler_is_reported_as_no_visual_qa(self):
        w, p = fake_env(which_ok={"soffice", "pdflatex", "node"})
        with w, p:
            report = td.diagnose(check_com=False)
        self.assertFalse(report["can_inspect_pages"])
        self.assertIn("pdftoppm", report["blockers"])

    def test_soffice_alone_is_enough_to_render(self):
        w, p = fake_env(which_ok={"soffice", "pdftoppm"})
        with w, p:
            report = td.diagnose(check_com=False)
        self.assertTrue(report["can_render_pdf"])

    def test_a_skipped_com_probe_is_unknown_not_absent(self):
        w, p = fake_env(which_ok={"pdftoppm"})
        with w, p, mock.patch.object(td.sys, "platform", "win32"):
            report = td.diagnose(check_com=False)
        self.assertIsNone(report["can_render_pdf"])

    def test_every_row_says_what_breaks_without_it(self):
        w, p = fake_env()
        with w, p:
            report = td.diagnose(check_com=False)
        for row in report["rows"]:
            self.assertTrue(row["without"].strip(), row["name"])
            self.assertTrue(row["targets"])

    def test_one_target_only_narrows_the_report(self):
        w, p = fake_env()
        with w, p:
            report = td.diagnose("web", check_com=False)
        self.assertEqual(set(report["buildable"]), {"web"})
        self.assertNotIn("pdflatex", [r["name"] for r in report["rows"]])


class TestCli(unittest.TestCase):
    def test_a_buildable_target_exits_zero(self):
        w, p = fake_env()
        with w, p:
            self.assertEqual(td.main(["--target", "web", "--no-com", "--json"]), 0)

    def test_an_unbuildable_target_exits_one(self):
        w, p = fake_env(python_ok=False)
        with w, p:
            self.assertEqual(td.main(["--target", "web", "--no-com", "--json"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
