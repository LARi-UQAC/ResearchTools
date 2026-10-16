"""
test_wp_paths.py - offline tests for wp_paths.py.

Proves: --data-dir refusals (None, blank, missing, not-a-directory, inside
the repository) and contained_path's escape refusal (R24: resolve then
is_relative_to, never a string comparison).
"""
import tempfile
import unittest
from pathlib import Path

import _fixtures  # noqa: F401

import wp_errors
import wp_paths


class TestResolveDataDir(unittest.TestCase):
    def test_none_and_blank_refused(self):
        with self.assertRaises(wp_errors.WpRefusal):
            wp_paths.resolve_data_dir(None)
        with self.assertRaises(wp_errors.WpRefusal):
            wp_paths.resolve_data_dir("   ")

    def test_missing_dir_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "nope")
            with self.assertRaises(wp_errors.WpRefusal):
                wp_paths.resolve_data_dir(missing, repo=Path(tmp))

    def test_file_not_dir_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "file.txt"
            f.write_text("x", encoding="utf-8")
            with self.assertRaises(wp_errors.WpRefusal):
                wp_paths.resolve_data_dir(str(f), repo=Path(tmp))

    def test_inside_repo_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            sub = repo / "sub"
            sub.mkdir(parents=True)
            with self.assertRaises(wp_errors.WpRefusal):
                wp_paths.resolve_data_dir(str(sub), repo=repo)

    def test_outside_repo_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            data.mkdir()
            repo = Path(tmp) / "repo"
            repo.mkdir()
            result = wp_paths.resolve_data_dir(str(data), repo=repo)
            self.assertEqual(result, data.resolve())

    def test_real_repo_refused(self):
        with self.assertRaises(wp_errors.WpRefusal):
            wp_paths.resolve_data_dir(str(wp_paths.repo_root()))


class TestContainedPath(unittest.TestCase):
    def test_relative_candidate_contained(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            result = wp_paths.contained_path(d, "cihr.json")
            self.assertTrue(result.is_relative_to(d.resolve()))

    def test_parent_escape_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            with self.assertRaises(wp_errors.WpRefusal):
                wp_paths.contained_path(d, "../x.json")

    def test_absolute_outside_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "data"
            d.mkdir()
            outside = Path(tmp) / "other" / "x.json"
            with self.assertRaises(wp_errors.WpRefusal):
                wp_paths.contained_path(d, outside)

    def test_absolute_inside_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            inside = d / "config" / "mapping.yaml"
            result = wp_paths.contained_path(d, inside)
            self.assertEqual(result, inside.resolve())


if __name__ == "__main__":
    unittest.main()
