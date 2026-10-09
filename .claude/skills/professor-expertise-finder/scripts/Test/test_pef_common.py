import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

import pef_common  # noqa: E402
from pef_common import (atomic_open, canonical_university, data_root,  # noqa: E402
                         load_column_hints, load_config, load_university_aliases,
                         name_key, norm, slugify)


class PefCommonTest(unittest.TestCase):
    def test_slugify_strips_accents_and_collapses(self):
        self.assertEqual(slugify("France, Île-de-France"), "france-ile-de-france")

    def test_slugify_empty_input_gets_a_hash_suffix_not_a_bare_literal(self):
        # 2026-10-09 review finding: two unrelated batches with no Latin
        # alphanumeric name at all used to collapse to the literal
        # "unspecified" and share one data instance.
        slug_a = slugify("   ")
        slug_b = slugify("???")
        self.assertTrue(slug_a.startswith("unspecified-"))
        self.assertNotEqual(slug_a, slug_b)
        self.assertEqual(slugify("   "), slug_a)  # same input -> same slug

    def test_norm_folds_case_accent_and_punctuation(self):
        self.assertEqual(norm("É. Doe-Smith"), "e doe smith")
        self.assertEqual(norm(None), "")

    def test_name_key_is_order_insensitive(self):
        self.assertEqual(name_key("Jane Doe"), name_key("Doe, Jane"))
        self.assertNotEqual(name_key("Jane Doe"), name_key("Jane Doey"))

    def test_data_root_defaults_when_env_unset(self):
        # The default lives in pef_config.json's default_data_root, never as a
        # Python literal in this module (R1, 2026-10-08 code review finding).
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PROFESSOR_EXPERTISE_DATA", None)
            self.assertNotIn("DEFAULT_DATA_ROOT", dir(pef_common))
            self.assertEqual(data_root(), Path("~/workspace/professor-expertise").expanduser())

    def test_data_root_honors_env_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"PROFESSOR_EXPERTISE_DATA": tmp}):
                self.assertEqual(data_root(), Path(tmp))

    def test_data_root_env_override_expands_tilde(self):
        # Fourth 2026-10-08 round: SKILL.md and pef_config.json's own default
        # use the ~/... syntax, but the env-var path skipped expanduser(), so
        # following that exact documented syntax for the env var produced a
        # literal "~" subdirectory instead of the home directory.
        with mock.patch.dict(os.environ, {"PROFESSOR_EXPERTISE_DATA": "~/workspace/professor-expertise"}):
            self.assertEqual(data_root(), Path("~/workspace/professor-expertise").expanduser())
            self.assertNotIn("~", str(data_root()))

    def test_data_root_reads_a_custom_config_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            custom = tmp_path / "pef_config.json"
            custom.write_text(json.dumps({
                "subscore_values": [0, 0.5, 1], "retain_threshold": 1.5,
                "max_per_university": 1, "default_data_root": str(tmp_path / "custom"),
                "recent_years_window": 5,
            }), encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("PROFESSOR_EXPERTISE_DATA", None)
                with mock.patch.object(pef_common, "CONFIG_PATH", custom):
                    self.assertEqual(data_root(), tmp_path / "custom")

    def test_load_config_reads_the_shipped_file(self):
        config = load_config()
        self.assertEqual(config["subscore_values"], [0, 0.5, 1])
        self.assertEqual(config["max_per_university"], 1)
        self.assertEqual(config["retain_threshold"], 1.5)
        self.assertEqual(config["default_data_root"], "~/workspace/professor-expertise")
        self.assertEqual(config["recent_years_window"], 5)

    def test_load_config_missing_file_raises(self):
        with mock.patch.object(pef_common, "CONFIG_PATH", Path("/does/not/exist.json")):
            with self.assertRaises(FileNotFoundError):
                load_config()

    def test_load_config_malformed_json_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "pef_config.json"
            bad.write_text("{not json", encoding="utf-8")
            with mock.patch.object(pef_common, "CONFIG_PATH", bad):
                with self.assertRaises(ValueError):
                    load_config()

    def test_load_config_missing_key_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            incomplete = Path(tmp) / "pef_config.json"
            incomplete.write_text(json.dumps({"subscore_values": [0, 0.5, 1]}), encoding="utf-8")
            with mock.patch.object(pef_common, "CONFIG_PATH", incomplete):
                with self.assertRaises(ValueError):
                    load_config()

    def test_load_column_hints_reads_the_shipped_sections(self):
        file_search_hints = load_column_hints("file_search")
        self.assertIn("name", file_search_hints["name_hints"])
        exclusions_hints = load_column_hints("exclusions")
        self.assertIn("first_name", exclusions_hints["first_cols"])

    def test_load_column_hints_missing_section_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            partial = Path(tmp) / "pef_column_hints.json"
            partial.write_text(json.dumps({"file_search": {}}), encoding="utf-8")
            with mock.patch.object(pef_common, "COLUMN_HINTS_PATH", partial):
                with self.assertRaises(ValueError):
                    load_column_hints("exclusions")

    def test_load_column_hints_missing_file_raises(self):
        with mock.patch.object(pef_common, "COLUMN_HINTS_PATH", Path("/does/not/exist.json")):
            with self.assertRaises(FileNotFoundError):
                load_column_hints("file_search")

    def test_load_university_aliases_reads_the_shipped_file(self):
        # 2026-10-09 review finding: exact-string university equality let a
        # spelling variant bypass the no-reuse/cap/conflict-of-interest
        # checks. The shipped file must at least resolve the flagship
        # example the review gave.
        aliases = load_university_aliases()
        self.assertEqual(aliases.get("uqac"), norm("Université du Québec à Chicoutimi"))

    def test_canonical_university_resolves_a_known_acronym(self):
        self.assertEqual(canonical_university("UQAC"),
                          canonical_university("Université du Québec à Chicoutimi"))

    def test_canonical_university_never_invents_a_match(self):
        # A known-aliases lookup, not a fuzzy matcher: two different,
        # unlisted universities must never canonicalize to the same string.
        self.assertNotEqual(canonical_university("Random University A"),
                             canonical_university("Random University B"))

    def test_canonical_university_missing_alias_file_degrades_to_norm(self):
        with mock.patch.object(pef_common, "UNIVERSITY_ALIASES_PATH", Path("/does/not/exist.json")):
            self.assertEqual(canonical_university("UQAC"), norm("UQAC"))

    def test_atomic_open_writes_the_final_file_and_leaves_no_tmp_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.csv"
            with atomic_open(target, encoding="utf-8") as fh:
                fh.write("hello")
            self.assertEqual(target.read_text(encoding="utf-8"), "hello")
            self.assertFalse(target.with_name("out.csv.tmp").exists())

    def test_atomic_open_leaves_the_previous_file_untouched_on_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.csv"
            target.write_text("original", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                with atomic_open(target, encoding="utf-8") as fh:
                    fh.write("partial")
                    raise RuntimeError("simulated crash mid-write")
            self.assertEqual(target.read_text(encoding="utf-8"), "original")


if __name__ == "__main__":
    unittest.main(verbosity=2)
