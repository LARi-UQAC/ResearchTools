"""
test_daemon_classify - what the daemon ASKS the local model, and what it
refuses to do with the answer.

Split from test_vault_daemon when that file passed the 4096-token ceiling, on
the seam the daemon already has: this suite covers CLASSIFY and ROUTE, plus the
folder taxonomy the classification is constrained to, while the write path,
collisions, queues and crash recovery stay next door. The shared fixture vault
lives in _daemon_fixtures so the two halves cannot drift apart while both pass.

The refusals are the point. The daemon files knowledge unattended, so every gate
here is structural, and not one of them can look at whether an answer is TRUE -
which is why the cases carrying a date are the ones a live drill measured rather
than the ones a fixture suggested.
"""
import json
import unittest
from unittest import mock

from _daemon_fixtures import CONFIG, DaemonCase, GOOD_NOTE, TAG, WINDOW, ds, reply, vd  # noqa: F401


class DaemonClassifyTest(DaemonCase):
    def test_low_confidence_is_parked_rather_than_guessed(self):
        drop = self._drop()
        report = self._run(drop, {"scope": "reusable", "technology": "Ollama",
                                  "confidence": 0.4})
        self.assertIn("under the 0.7 threshold", report["parked"])
        self.assertTrue((self.outbox / "needs-review" / drop.name).exists())
        self.assertFalse(any((self.vault / "30_Ressources/Ollama").iterdir()))

    def test_an_off_enum_technology_is_refused(self):
        """The schema constrains the answer, but a probe is a measurement and
        not a guarantee, so the daemon checks the enum again in Python."""
        report = self._run(self._drop(), {"scope": "reusable",
                                          "technology": "Kubernetes",
                                          "confidence": 0.99})
        self.assertIn("not a live folder", report["parked"])

    def test_the_retired_catch_all_folder_is_not_an_option(self):
        self.assertNotIn("Logiciel", ds.technology_folders(self.vault))

    def test_a_project_with_no_directory_is_refused(self):
        report = self._run(self._drop(project="NoSuchProject"),
                           {"scope": "project", "technology": "Ollama",
                            "project": "NoSuchProject", "confidence": 0.9})
        self.assertIn("has no directory", report["parked"])

    def test_a_project_scope_on_a_drop_declaring_none_is_refused(self):
        """Measured 2026-08-28: on a drop with no project key, the model
        answered scope 'project' and named a project absent from the drop, at
        0.90. Only that name having no directory saved the vault."""
        report = self._run(self._drop(),
                           {"scope": "project", "technology": "Ollama",
                            "project": "Graphify", "confidence": 0.9})
        self.assertIn("source declared no project", report["parked"])
        self.assertFalse((self.vault / "10_Projets" / "Logiciels" / "Graphify").exists())

    def test_the_declared_project_outranks_the_models_answer(self):
        """Same measurement, other half: a drop declaring ResearchTools came
        back as 'ResearchTools - <its subject>', and that string decided the
        route."""
        drop = self._drop(project="ResearchTools")
        report = self._run(drop, {"scope": "project", "technology": "Ollama",
                                  "project": "ResearchTools - a lock was left behind",
                                  "confidence": 0.95})
        self.assertIsNone(report["parked"])
        self.assertTrue((self.vault / "10_Projets/Logiciels/ResearchTools"
                         / "Decisions.md").exists())
        self.assertEqual(report["source_project"], "ResearchTools")
        self.assertEqual(report["model_project"],
                         "ResearchTools - a lock was left behind",
                         "recorded, so a divergence shows in the tuning log")

    def test_the_classify_prompt_forbids_inventing_a_project(self):
        """The router refuses a project the source did not name, so the rule
        belongs in the prompt too. It must sit in the FIXED prefix, not the
        per-drop suffix, to stay inside the measured prefix cache. The rule is
        stated in BOTH directions on purpose: an earlier one-sided version said
        only what to do when no project is named, and the very next live run
        filed a genuine project entry as a resource note."""
        self.assertIn("Never invent a project name", ds.CLASSIFY_PREFIX)
        self.assertIn("naming one does NOT decide the", ds.CLASSIFY_PREFIX)

    def test_a_reusable_drop_naming_its_project_is_flagged_not_refused(self):
        """The documented raw drop is a reusable lesson carrying the project it
        came from, so this combination is legitimate and must file normally. It
        is also how a real project entry goes to the wrong shelf, at 0.95, so
        the report carries one greppable field instead of a silent misfiling."""
        drop = self._drop(project="ResearchTools")
        report = self._run(drop, {"scope": "reusable", "technology": "Ollama",
                                  "confidence": 0.95})
        self.assertIsNone(report["parked"])
        self.assertTrue(report["scope_divergence"])
        self.assertTrue((self.vault / "30_Ressources/Ollama"
                         / "a-lock-was-left-behind.md").exists())

    def test_no_divergence_when_the_scopes_agree(self):
        report = self._run(self._drop(), {"scope": "reusable",
                                          "technology": "Ollama",
                                          "confidence": 0.9})
        self.assertFalse(report["scope_divergence"])

    def test_a_folder_is_offered_with_what_it_holds_not_only_its_name(self):
        """Measured 2026-08-28: shown bare names, the model filed an outbox-lock
        note into Docker, a two-note folder. A name invites association; a line
        saying what the shelf is for does not."""
        menu = ds.folder_menu(["Docker", "Ollama"],
                              {"Docker": "container images", "Ollama": "the daemon"})
        self.assertEqual(menu, "- Docker: container images\n- Ollama: the daemon")

    def test_a_folder_with_no_gloss_is_still_offered_by_name(self):
        """A folder created after the data file was written must not vanish
        from the menu: the enum is built from disk, not from this file."""
        self.assertEqual(ds.folder_menu(["Nouveau"], {"Docker": "x"}), "- Nouveau")

    def test_a_missing_gloss_file_degrades_to_bare_names(self):
        self.assertEqual(ds.folder_glosses(self.tmp / "absent.json"), {})

    def test_the_shipped_gloss_file_covers_the_folders_it_names(self):
        """Guards the data itself: a file that parses but carries no folders
        would silently be the same as having none."""
        glosses = ds.folder_glosses()
        self.assertIn("Docker", glosses)
        self.assertIn("container", glosses["Docker"].lower())
        self.assertTrue(all(isinstance(v, str) and v for v in glosses.values()))

    def test_a_classification_that_is_not_json_is_parked(self):
        with mock.patch.object(vd.ob, "_post_generate",
                               return_value=reply("I would say reusable.")):
            report = self.daemon.handle(self._drop(), TAG, WINDOW)
        self.assertIn("not JSON", report["parked"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
