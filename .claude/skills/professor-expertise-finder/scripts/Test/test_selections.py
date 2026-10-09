import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from selections import main  # noqa: E402


def run_main(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(argv)
    return rc, buf.getvalue()


class SelectionsTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmp = Path(self._tmpdir.name)
        self._orig_env = os.environ.get("PROFESSOR_EXPERTISE_DATA")
        os.environ["PROFESSOR_EXPERTISE_DATA"] = str(self.tmp)
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        if self._orig_env is None:
            os.environ.pop("PROFESSOR_EXPERTISE_DATA", None)
        else:
            os.environ["PROFESSOR_EXPERTISE_DATA"] = self._orig_env

    def _init_batch(self, batch="test-batch"):
        main(["init", "--batch", batch])
        return batch

    def test_no_reuse_across_applications_is_rejected(self):
        batch = self._init_batch()
        rc = main(["add", "--batch", batch, "--application", "Set 1",
                   "--professor", "Test Person", "--university", "Example University",
                   "--score", "4/5", "--status", "final"])
        self.assertEqual(rc, 0)
        # same person (name AND university both match a FINAL row elsewhere)
        rc, out = run_main(["add", "--batch", batch, "--application", "Set 2",
                             "--professor", "Test Person", "--university", "Example University",
                             "--score", "4/5", "--status", "final"])
        self.assertEqual(rc, 1)
        self.assertIn("REJECTED", out)
        rc, out = run_main(["check", "--batch", batch, "--professor", "Test Person"])
        self.assertEqual(rc, 1)
        self.assertIn("TAKEN", out)

    def test_homonym_at_a_different_university_is_not_rejected(self):
        # Two different real people can share a name - university disambiguates
        # (2026-10-08 code review finding: this used to be wrongly rejected).
        batch = self._init_batch()
        rc = main(["add", "--batch", batch, "--application", "Set 1",
                   "--professor", "John Smith", "--university", "University A",
                   "--score", "4/5", "--status", "final"])
        self.assertEqual(rc, 0)
        rc = main(["add", "--batch", batch, "--application", "Set 2",
                   "--professor", "John Smith", "--university", "University B",
                   "--score", "4/5", "--status", "final"])
        self.assertEqual(rc, 0)

    def test_homonyms_on_the_same_application_do_not_overwrite_each_other(self):
        # 2026-10-08, second code-review round: the idempotent-replace step
        # matched by name+application only, so adding a second "Alice Brown"
        # (a different person, different university) to the SAME application
        # silently deleted the first Alice Brown's own registration.
        batch = self._init_batch()
        rc = main(["add", "--batch", batch, "--application", "Set 1",
                   "--professor", "Alice Brown", "--university", "University A",
                   "--score", "4/5", "--status", "final"])
        self.assertEqual(rc, 0)
        rc = main(["add", "--batch", batch, "--application", "Set 1",
                   "--professor", "Alice Brown", "--university", "University B",
                   "--score", "3/5", "--status", "final"])
        self.assertEqual(rc, 0)
        _, out = run_main(["list", "--batch", batch])
        self.assertEqual(out.count("Alice Brown"), 2)
        self.assertIn("University A", out)
        self.assertIn("University B", out)
        self.assertIn("2 distinct professors", out)

    def test_final_add_without_university_is_rejected(self):
        # Without --university neither the conflict-of-interest check nor the
        # per-university cap can run at all - both used to be silently skipped
        # rather than refused (2026-10-08 code review finding).
        batch = self._init_batch()
        rc, out = run_main(["add", "--batch", batch, "--application", "Set 1",
                             "--professor", "Test Person", "--score", "4/5", "--status", "final"])
        self.assertEqual(rc, 1)
        self.assertIn("INVALID", out)
        rc = main(["check", "--batch", batch, "--professor", "Test Person"])
        self.assertEqual(rc, 0)  # the rejected add wrote nothing

    def test_proposed_add_without_university_is_rejected(self):
        # Third 2026-10-08 code-review round: only `final` required
        # --university, so a `proposed` add with none let finals_for()'s
        # disambiguation see an "unknown" university - which _same_person()
        # treats as a possible match - wrongly rejecting a different,
        # same-named professor as reuse.
        batch = self._init_batch()
        rc, out = run_main(["add", "--batch", batch, "--application", "Set 1",
                             "--professor", "Test Person", "--score", "3/5", "--status", "proposed"])
        self.assertEqual(rc, 1)
        self.assertIn("INVALID", out)

    def test_homonym_not_rejected_on_a_proposed_add(self):
        batch = self._init_batch()
        rc = main(["add", "--batch", batch, "--application", "Set 1",
                   "--professor", "John Smith", "--university", "University A",
                   "--score", "4/5", "--status", "final"])
        self.assertEqual(rc, 0)
        rc = main(["add", "--batch", batch, "--application", "Set 2",
                   "--professor", "John Smith", "--university", "University B",
                   "--score", "3/5", "--status", "proposed"])
        self.assertEqual(rc, 0)

    def test_university_cap_rejected_across_a_known_acronym_and_full_name(self):
        # 2026-10-09 review finding: exact-string university equality let a
        # spelling variant (UQAC vs its full name) silently bypass the cap.
        batch = self._init_batch()
        rc = main(["add", "--batch", batch, "--application", "Set 1",
                   "--professor", "Prof 0", "--university", "UQAC",
                   "--score", "3/5", "--status", "final"])
        self.assertEqual(rc, 0)
        rc = main(["add", "--batch", batch, "--application", "Set 1",
                   "--professor", "Prof 1",
                   "--university", "Université du Québec à Chicoutimi",
                   "--score", "3/5", "--status", "final"])
        self.assertEqual(rc, 1)

    def test_university_cap_rejected_past_configured_max(self):
        # max_per_university is 1 (SKILL.md Operating Rule 9, 2026-10-08): all
        # evaluators of one application must come from distinct universities.
        batch = self._init_batch()
        rc = main(["add", "--batch", batch, "--application", "Set 1",
                   "--professor", "Prof 0", "--university", "Same University",
                   "--score", "3/5", "--status", "final"])
        self.assertEqual(rc, 0)
        rc = main(["add", "--batch", batch, "--application", "Set 1",
                   "--professor", "Prof 1", "--university", "Same University",
                   "--score", "3/5", "--status", "final"])
        self.assertEqual(rc, 1)

    def test_conflict_of_interest_rejected_after_origin_declared(self):
        batch = self._init_batch()
        rc = main(["origin", "--batch", batch, "--application", "Set 1",
                   "--university", "Applicant University"])
        self.assertEqual(rc, 0)
        rc = main(["add", "--batch", batch, "--application", "Set 1",
                   "--professor", "Conflicted Prof", "--university", "Applicant University",
                   "--score", "4/5", "--status", "final"])
        self.assertEqual(rc, 1)

    def test_dry_run_writes_nothing(self):
        batch = self._init_batch()
        rc = main(["add", "--batch", batch, "--application", "Set 1",
                   "--professor", "Test Person", "--university", "Example University",
                   "--score", "4/5", "--status", "final", "--dry-run"])
        self.assertEqual(rc, 0)
        rc = main(["check", "--batch", batch, "--professor", "Test Person"])
        self.assertEqual(rc, 0)  # still AVAILABLE: the dry run above wrote nothing


if __name__ == "__main__":
    unittest.main(verbosity=2)
