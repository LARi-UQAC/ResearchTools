"""
Offline unit tests for letter_identity.py: no network, no pdflatex, no model
load. Every profile read here is a fixture written into a temporary directory,
so the machine's own profiles/ and its active-profile selector are never
touched and the result does not depend on which profile the operator last
selected.

The cases that matter are the refusals. A letter signed with the wrong name,
laboratory and phone number is a wrong answer that reads as a right one, so a
profile carrying no identity must stop the run and say which key it wanted -
never borrow one from another profile (R8, R3).

Run from the repo root:
    python -m unittest discover -s ".claude/skills/recommendation-letter/scripts/Test" -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import letter_identity


COMPLETE_PROFILE = """\
name: fixture
author:
  name: Fixture Nom
  letter:
    letterhead_fr: ["Professeure Fixture Nom", "Universite de Fixture"]
    letterhead_en: ["Professor Fixture Nom", "Fixture University"]
    signature_name_fr: Fixture A.-B. Nom, ing. Ph.D.
    signature_name_en: Fixture A.-B. Nom, P.Eng., Ph.D.
    signature_lines_fr:
      - Responsable du laboratoire FIXLAB
      - "Courriel~: \\\\href{mailto:a@b.ca}{a\\\\_b}"
    signature_lines_en: ["Director of the FIXLAB laboratory"]
    dispense_lines_fr: ["Professeure titulaire"]
    responsible_name: Fixture Nom
    lab_acronym: FIXLAB
"""


def write(directory, name, text):
    path = Path(directory) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestActiveProfileName(unittest.TestCase):
    def test_reads_the_machine_readable_line(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, ".claude/CLAUDE.md",
                  "# header\n\n```yaml\nactive_profile: fixture\n```\n\nprose\n")
            self.assertEqual(letter_identity.active_profile_name(root), "fixture")

    def test_falls_back_to_the_french_prose_line(self):
        """The documented second spelling, kept in step by install.ps1."""
        with tempfile.TemporaryDirectory() as root:
            write(root, ".claude/CLAUDE.md", "# header\n\nProfil actif : cosmetic\n")
            self.assertEqual(letter_identity.active_profile_name(root), "cosmetic")

    def test_machine_line_wins_over_prose(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, ".claude/CLAUDE.md",
                  "active_profile: fixture\n\nProfil actif : cosmetic\n")
            self.assertEqual(letter_identity.active_profile_name(root), "fixture")

    def test_missing_selector_file_names_it(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(letter_identity.IdentityError) as caught:
                letter_identity.active_profile_name(root)
            self.assertIn("CLAUDE.md", str(caught.exception))

    def test_selector_without_a_profile_line_is_an_error(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, ".claude/CLAUDE.md", "# a file with no selector at all\n")
            with self.assertRaises(letter_identity.IdentityError) as caught:
                letter_identity.active_profile_name(root)
            self.assertIn("active_profile", str(caught.exception))


class TestProfilePath(unittest.TestCase):
    def test_path_follows_the_active_profile(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, ".claude/CLAUDE.md", "active_profile: fixture\n")
            path = letter_identity.profile_path(root)
            self.assertEqual(path.name, "fixture.yaml")
            self.assertEqual(path.parent.name, "profiles")


class TestLoadIdentity(unittest.TestCase):
    def test_returns_the_latex_ready_strings_verbatim(self):
        with tempfile.TemporaryDirectory() as root:
            path = write(root, "fixture.yaml", COMPLETE_PROFILE)
            identity = letter_identity.load_identity(path)
            self.assertEqual(identity["lab_acronym"], "FIXLAB")
            self.assertEqual(identity["signature_name_fr"],
                             "Fixture A.-B. Nom, ing. Ph.D.")
            # A backslash written "\\" in the YAML reaches the caller as one
            # backslash, so \href survives into the .tex as a macro.
            self.assertIn(r"\href{mailto:a@b.ca}{a\_b}",
                          identity["signature_lines_fr"][1])

    def test_resolves_through_the_active_profile_when_no_path_is_given(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, ".claude/CLAUDE.md", "active_profile: fixture\n")
            write(root, "profiles/fixture.yaml", COMPLETE_PROFILE)
            identity = letter_identity.load_identity(root=root)
            self.assertEqual(identity["responsible_name"], "Fixture Nom")

    def test_missing_profile_file_names_it(self):
        with tempfile.TemporaryDirectory() as root:
            missing = Path(root) / "profiles" / "absent.yaml"
            with self.assertRaises(letter_identity.IdentityError) as caught:
                letter_identity.load_identity(missing)
            self.assertIn("absent.yaml", str(caught.exception))

    def test_profile_without_a_letter_block_is_refused_not_borrowed(self):
        """The cosmetic-profile case: an author, but nobody to sign a letter."""
        with tempfile.TemporaryDirectory() as root:
            path = write(root, "no-letter.yaml",
                         "name: fixture\nauthor:\n  name: Fixture Nom\n")
            with self.assertRaises(letter_identity.IdentityError) as caught:
                letter_identity.load_identity(path)
            message = str(caught.exception)
            self.assertIn("author.letter", message)
            self.assertIn("no-letter.yaml", message)

    def test_profile_without_an_author_block_is_refused(self):
        with tempfile.TemporaryDirectory() as root:
            path = write(root, "no-author.yaml", "name: fixture\nscopus: {}\n")
            with self.assertRaises(letter_identity.IdentityError) as caught:
                letter_identity.load_identity(path)
            self.assertIn("author", str(caught.exception))

    def test_a_missing_key_is_named_before_anything_is_rendered(self):
        with tempfile.TemporaryDirectory() as root:
            partial = COMPLETE_PROFILE.replace(
                "    lab_acronym: FIXLAB\n", "")
            path = write(root, "partial.yaml", partial)
            with self.assertRaises(letter_identity.IdentityError) as caught:
                letter_identity.load_identity(path)
            self.assertIn("lab_acronym", str(caught.exception))

    def test_an_empty_value_counts_as_missing(self):
        with tempfile.TemporaryDirectory() as root:
            empty = COMPLETE_PROFILE.replace(
                "    responsible_name: Fixture Nom\n",
                "    responsible_name: \"\"\n")
            path = write(root, "empty.yaml", empty)
            with self.assertRaises(letter_identity.IdentityError) as caught:
                letter_identity.load_identity(path)
            self.assertIn("responsible_name", str(caught.exception))

    def test_a_scalar_document_is_refused(self):
        with tempfile.TemporaryDirectory() as root:
            path = write(root, "scalar.yaml", "just a string\n")
            with self.assertRaises(letter_identity.IdentityError):
                letter_identity.load_identity(path)

    def test_a_python_object_tag_does_not_construct(self):
        """safe_load, never load: a profile is data and must stay data."""
        with tempfile.TemporaryDirectory() as root:
            path = write(root, "evil.yaml",
                         "author: !!python/object/apply:os.system ['echo pwned']\n")
            with self.assertRaises(Exception) as caught:
                letter_identity.load_identity(path)
            # A ConstructorError from yaml, not a letter that got written.
            self.assertNotIsInstance(caught.exception, SystemExit)


class TestShippedProfiles(unittest.TestCase):
    """The repository's own profiles, read as data rather than as machine state.

    These files are tracked, so unlike a measured configuration they say the
    same thing on every clone (R21 bars a test from reading machine-local
    measured config, not from reading a versioned data file).
    """

    def setUp(self):
        self.profiles = letter_identity.repo_root() / "profiles"
        if not self.profiles.is_dir():
            self.skipTest("profiles/ not found beside this checkout")

    def test_engineering_profile_carries_a_complete_identity(self):
        identity = letter_identity.load_identity(self.profiles / "engineering.yaml")
        self.assertEqual(len(identity["letterhead_fr"]),
                         len(identity["letterhead_en"]))
        for key in letter_identity.REQUIRED_KEYS:
            self.assertTrue(identity[key], key)

    def test_the_template_profile_documents_every_required_key(self):
        text = (self.profiles / "_template.yaml").read_text(encoding="utf-8")
        for key in letter_identity.REQUIRED_KEYS:
            self.assertIn(key + ":", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
