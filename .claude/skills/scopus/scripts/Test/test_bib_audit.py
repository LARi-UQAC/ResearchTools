"""
Offline unit tests for bib_audit.py (no network, no API key): the scopus_api.py
driver is never invoked because every Scopus answer is pre-loaded in the cache
the audit reads, and the one test that does exercise the driver patches it.

Covers the production lessons the script encodes: a dataset DOI absent from
Scopus is not a broken reference, no injected line may contain '@' (BibTeX has
no comment syntax), and a rerun over the annotated copy must not stack a second
set of flags.

Run with the project Python:
  python .claude/skills/scopus/scripts/Test/test_bib_audit.py
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import bib_audit  # noqa: E402
import scopus_api  # noqa: E402


BIB_SOURCE = """\
@article{smith2024energy,
  author  = {Smith, Jane and Doe, John},
  title   = {Energy minimization for disassembly of end-of-life battery packs},
  journal = {IEEE Transactions on Automation Science and Engineering},
  year    = {2024},
  doi     = {10.1109/TASE.2024.1},
}

@article{smith2024energybis,
  author  = {Smith, Jane and Doe, John},
  title   = {Energy minimization for disassembly of end-of-life battery modules},
  journal = {IEEE Transactions on Automation Science and Engineering},
  year    = {2024},
  doi     = {10.1109/TASE.2024.2},
}

@article{nojournal2023study,
  author  = {Roe, Richard},
  title   = {A study without a journal field},
  year    = {2023},
}

@inproceedings{conf2023paper,
  author  = {Roe, Richard},
  title   = {A conference paper},
  year    = {2023},
}

@article{wrongdoi2022control,
  author  = {Tremblay, Marie},
  title   = {Adaptive control of a redundant manipulator},
  journal = {IEEE Transactions on Robotics},
  year    = {2022},
  doi     = {10.1109/TRO.2022.9},
}

@misc{lab2024dataset,
  author       = {Lab, Research},
  title        = {Companion dataset},
  year         = {2024},
  howpublished = {OSF},
  doi          = {10.17605/OSF.IO/ABCDE},
}
"""

CITE_CACHE = {
    "10.1109/TASE.2024.1": {
        "title": "Energy minimization for disassembly of end-of-life battery packs",
        "authors": [{"surname": "Smith", "given_name": "Jane"}],
        "journal": "IEEE Transactions on Automation Science and Engineering",
        "issn": "15455955 15583783",
    },
    "10.1109/TASE.2024.2": {
        "title": "Energy minimization for disassembly of end-of-life battery modules",
        "authors": [{"surname": "Smith", "given_name": "Jane"}],
        "journal": "IEEE Transactions on Automation Science and Engineering",
        "issn": "15455955 15583783",
    },
    "10.1109/TRO.2022.9": {
        # Close title, different first author: the DOI does not describe the entry.
        "title": "Adaptive control of a redundant manipulator arm",
        "authors": [{"surname": "Nakamura", "given_name": "Yoshihiko"}],
        "journal": "IEEE Transactions on Robotics",
        "issn": "15523098",
    },
    "10.17605/OSF.IO/ABCDE": {
        "_error": "ERROR 404: RESOURCE_NOT_FOUND The resource specified cannot be found."
    },
}

METRIC_CACHE = {
    "15455955 15583783": {
        "title": "IEEE Transactions on Automation Science and Engineering",
        "venue_type": "journal", "issn_used": "1545-5955", "publisher": "IEEE",
        "sjr": "1.842", "sjr_applicable": True, "cite_score": "11.5",
        "pct": 93, "quartile": "Q1",
    },
    "15523098": {
        "title": "IEEE Transactions on Robotics", "venue_type": "journal",
        "issn_used": "1552-3098", "publisher": "IEEE", "sjr": "3.001",
        "sjr_applicable": True, "cite_score": "14.2", "pct": 97, "quartile": "Q1",
    },
}


def _write(directory: str, name: str, content: str) -> str:
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
    return path


def _fresh_cache() -> dict:
    return {"cite": dict(CITE_CACHE), "metrics": dict(METRIC_CACHE)}


def _run_audit(source: str):
    """Parse and audit a .bib entirely from the cache (offline, no subprocess)."""
    entries = bib_audit.parse_bib(source)
    return entries, bib_audit.audit(entries, _fresh_cache(), offline=True)


class TestParseBib(unittest.TestCase):

    def test_types_keys_and_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            entries = bib_audit.parse_bib(_write(tmp, "refs.bib", BIB_SOURCE))
        self.assertEqual(len(entries), 6)
        self.assertEqual(entries[0]["type"], "article")
        self.assertEqual(entries[0]["key"], "smith2024energy")
        self.assertEqual(entries[0]["fields"]["doi"], "10.1109/TASE.2024.1")
        self.assertEqual(entries[3]["type"], "inproceedings")
        self.assertEqual(entries[5]["fields"]["howpublished"], "OSF")

    def test_commented_entry_is_not_parsed(self):
        source = BIB_SOURCE + "\n% @article{excluded2020, title = {Commented out}, }\n"
        with tempfile.TemporaryDirectory() as tmp:
            entries = bib_audit.parse_bib(_write(tmp, "refs.bib", source))
        self.assertNotIn("excluded2020", [e["key"] for e in entries])


class TestDuplicates(unittest.TestCase):

    def test_title_duplicate_flagged_on_both_sides(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, result = _run_audit(_write(tmp, "refs.bib", BIB_SOURCE))
        flags_a = result["findings"]["smith2024energy"]["flags"]
        flags_b = result["findings"]["smith2024energybis"]["flags"]
        self.assertTrue(any("DUPLICATE: smith2024energybis" in f for f in flags_a))
        self.assertTrue(any("DUPLICATE: smith2024energy " in f or
                            "DUPLICATE: smith2024energy]" in f for f in flags_b))
        self.assertIn(["smith2024energy", "smith2024energybis"],
                      result["summary"]["duplicate_pairs"])

    def test_exact_doi_duplicate_flagged(self):
        source = BIB_SOURCE.replace("10.1109/TASE.2024.2", "10.1109/TASE.2024.1")
        with tempfile.TemporaryDirectory() as tmp:
            _, result = _run_audit(_write(tmp, "refs.bib", source))
        self.assertTrue(any("DUPLICATE DOI" in f
                            for f in result["findings"]["smith2024energybis"]["flags"]))


class TestRequiredFields(unittest.TestCase):

    def test_article_without_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, result = _run_audit(_write(tmp, "refs.bib", BIB_SOURCE))
        self.assertIn("[MISSING FIELD: journal]",
                      result["findings"]["nojournal2023study"]["flags"])

    def test_inproceedings_without_booktitle(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, result = _run_audit(_write(tmp, "refs.bib", BIB_SOURCE))
        self.assertIn("[MISSING FIELD: booktitle]",
                      result["findings"]["conf2023paper"]["flags"])

    def test_missing_doi_flagged_on_article_and_inproceedings(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, result = _run_audit(_write(tmp, "refs.bib", BIB_SOURCE))
        self.assertCountEqual(result["summary"]["missing_doi"],
                              ["nojournal2023study", "conf2023paper"])

    def test_author_or_editor_satisfies_book(self):
        source = ("@book{ed2020handbook,\n  editor = {Roe, R.},\n"
                  "  title = {Handbook},\n  publisher = {Springer},\n  year = {2020},\n}\n")
        with tempfile.TemporaryDirectory() as tmp:
            _, result = _run_audit(_write(tmp, "refs.bib", source))
        self.assertEqual(result["findings"]["ed2020handbook"]["flags"], [])


class TestDoiValidation(unittest.TestCase):

    def test_close_title_but_different_first_author_is_a_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, result = _run_audit(_write(tmp, "refs.bib", BIB_SOURCE))
        flags = result["findings"]["wrongdoi2022control"]["flags"]
        self.assertTrue(any(f.startswith("[DOI MISMATCH") for f in flags))
        self.assertIn("wrongdoi2022control", result["summary"]["doi_mismatch"])

    def test_matching_record_is_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, result = _run_audit(_write(tmp, "refs.bib", BIB_SOURCE))
        flags = result["findings"]["smith2024energy"]["flags"]
        self.assertFalse(any("DOI MISMATCH" in f or "DOI INVALID" in f for f in flags))

    def test_dataset_doi_404_is_not_an_invalid_doi(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, result = _run_audit(_write(tmp, "refs.bib", BIB_SOURCE))
        flags = result["findings"]["lab2024dataset"]["flags"]
        self.assertTrue(any("DOI NOT IN SCOPUS" in f for f in flags))
        self.assertEqual(result["summary"]["doi_invalid"], [])
        self.assertIn("lab2024dataset", result["summary"]["doi_not_in_scopus"])

    def test_missing_article_doi_404_is_an_invalid_doi(self):
        source = BIB_SOURCE.replace("10.1109/TRO.2022.9", "10.1109/TRO.2022.404")
        entries = None
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, "refs.bib", source)
            entries = bib_audit.parse_bib(path)
            cache = _fresh_cache()
            cache["cite"]["10.1109/TRO.2022.404"] = {"_error": "ERROR 404: RESOURCE_NOT_FOUND"}
            result = bib_audit.audit(entries, cache, offline=True)
        self.assertIn("wrongdoi2022control", result["summary"]["doi_invalid"])

    def test_transport_error_is_unverified_not_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, "refs.bib", BIB_SOURCE)
            entries = bib_audit.parse_bib(path)
            cache = _fresh_cache()
            cache["cite"]["10.1109/TASE.2024.1"] = {"_error": "timeout"}
            result = bib_audit.audit(entries, cache, offline=True)
        self.assertIn("smith2024energy", result["summary"]["doi_unverified"])
        self.assertEqual(result["summary"]["doi_invalid"], [])


class TestPublisherApproval(unittest.TestCase):

    def test_ieee_journal_is_approved(self):
        name, approved = bib_audit.publisher_status(
            "IEEE", "IEEE Transactions on Robotics", "", "")
        self.assertEqual((name, approved), ("IEEE", True))

    def test_frontiers_is_not_approved_despite_robotics_in_the_name(self):
        name, approved = bib_audit.publisher_status(
            "", "Frontiers in Robotics and AI", "", "")
        self.assertFalse(approved)
        self.assertEqual(name, "Frontiers Media")

    def test_repository_host_is_not_a_publisher(self):
        _, approved = bib_audit.publisher_status("", "", "", "OSF")
        self.assertFalse(approved)

    def test_unknown_publisher_is_undetermined_not_rejected(self):
        name, approved = bib_audit.publisher_status("", "Journal of Obscure Studies", "", "")
        self.assertEqual((name, approved), ("unknown", None))


class TestQuartileBoundaries(unittest.TestCase):
    """The percentile -> quartile mapping lives in scopus_api.py (single source);
    bib_audit consumes the `quartile` field it returns."""

    def test_boundaries(self):
        self.assertEqual(scopus_api.quartile_from_percentile(75), "Q1")
        self.assertEqual(scopus_api.quartile_from_percentile(74), "Q2")
        self.assertEqual(scopus_api.quartile_from_percentile(50), "Q2")
        self.assertEqual(scopus_api.quartile_from_percentile(49), "Q3")
        self.assertEqual(scopus_api.quartile_from_percentile(25), "Q3")
        self.assertEqual(scopus_api.quartile_from_percentile(24), "Q4")
        self.assertEqual(scopus_api.quartile_from_percentile(None), "")

    def test_low_quartile_flags_low_impact(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, "refs.bib", BIB_SOURCE)
            entries = bib_audit.parse_bib(path)
            cache = _fresh_cache()
            cache["metrics"]["15523098"] = dict(cache["metrics"]["15523098"],
                                                pct=30, quartile="Q3")
            result = bib_audit.audit(entries, cache, offline=True)
        self.assertIn("wrongdoi2022control", result["summary"]["low_impact"])

    def test_sjr_not_applicable_is_not_low_impact(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, "refs.bib", BIB_SOURCE)
            entries = bib_audit.parse_bib(path)
            cache = _fresh_cache()
            cache["metrics"]["15523098"] = {"venue_type": "book series", "sjr": "",
                                            "sjr_applicable": False, "cite_score": "2.1",
                                            "publisher": "Springer"}
            result = bib_audit.audit(entries, cache, offline=True)
        self.assertEqual(result["summary"]["low_impact"], [])
        self.assertIn("wrongdoi2022control", result["summary"]["venue_not_applicable"])
        self.assertNotIn("[JOURNAL NOT RANKED]",
                         result["findings"]["wrongdoi2022control"]["flags"])


class TestVenueTypeNormalization(unittest.TestCase):
    """The Serial Title API answers 'conferenceproceeding' without a space; a
    plain equality test declared Procedia CIRP unrankable and dropped its
    quartile (measured on the TCAS-I corpus)."""

    def test_spaceless_conference_proceeding_is_normalized(self):
        self.assertEqual(scopus_api.normalize_venue_type("conferenceproceeding"),
                         "conference proceeding")
        self.assertIn(scopus_api.normalize_venue_type("conferenceproceeding"),
                      scopus_api.SJR_APPLICABLE_TYPES)

    def test_known_types(self):
        self.assertEqual(scopus_api.normalize_venue_type("Journal"), "journal")
        self.assertEqual(scopus_api.normalize_venue_type("bookseries"), "book series")
        self.assertNotIn(scopus_api.normalize_venue_type("bookseries"),
                         scopus_api.SJR_APPLICABLE_TYPES)
        self.assertEqual(scopus_api.normalize_venue_type(""), "unknown")


class TestBibTeXInvariants(unittest.TestCase):

    def test_no_injected_line_contains_an_at_sign(self):
        # BibTeX has no comment syntax: any '@' between entries starts a new one.
        # The publisher below reaches an injected flag line, so the sanitizer is
        # exercised rather than merely asserted over clean text.
        source = BIB_SOURCE.replace(
            "@article{nojournal2023study,",
            "@article{nojournal2023study,\n  publisher = {Obscure @ Press},")
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, "refs.bib", source)
            entries, result = _run_audit(path)
            clean = bib_audit.generate_clean_bib(path, result["findings"])
        self.assertIn("PUBLISHER NOT APPROVED",
                      " ".join(result["findings"]["nojournal2023study"]["flags"]))
        self.assertIn("Obscure [at] Press", clean)
        injected = [line for line in clean.split("\n") if line.startswith("%")]
        self.assertTrue(injected)
        for line in injected:
            self.assertNotIn("@", line)

    def test_entries_are_preserved_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, "refs.bib", BIB_SOURCE)
            entries, result = _run_audit(path)
            clean = bib_audit.generate_clean_bib(path, result["findings"])
        original = [e["key"] for e in entries]
        rewritten = [line.split("{", 1)[1].rstrip(",")
                     for line in clean.split("\n") if line.startswith("@")]
        self.assertEqual(original, rewritten)


class TestIdempotence(unittest.TestCase):

    def test_second_run_does_not_double_the_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = _write(tmp, "refs.bib", BIB_SOURCE)
            _, first_result = _run_audit(source)
            first = bib_audit.generate_clean_bib(source, first_result["findings"])
            clean_path = _write(tmp, "refs_clean.bib", first)

            _, second_result = _run_audit(clean_path)
            second = bib_audit.generate_clean_bib(clean_path, second_result["findings"])

        self.assertEqual(first.count("[DUPLICATE"), second.count("[DUPLICATE"))
        self.assertEqual(first.count("% Journal:"), second.count("% Journal:"))
        self.assertEqual(first.count(bib_audit.FLAGS_BEGIN),
                         second.count(bib_audit.FLAGS_BEGIN))
        self.assertEqual(first.count(bib_audit.HEADER_BEGIN), 1)
        self.assertEqual(second.count(bib_audit.HEADER_BEGIN), 1)
        # A fixed point: only the "Source:" header line legitimately differs, so
        # the file stops changing after the first run instead of drifting.
        drop_source = lambda text: [line for line in text.split("\n")
                                    if not line.startswith("% Source:")]
        self.assertEqual(drop_source(first), drop_source(second))


class TestScopusDriver(unittest.TestCase):
    """The only test that exercises the subprocess layer, with scopus_api.py faked."""

    def test_metrics_are_requested_by_issn(self):
        payload = {"results": [{"issn_used": "1545-5955", "sjr": "1.8",
                                "sjr_applicable": True, "quartile": "Q1", "pct": 93}]}
        with mock.patch.object(bib_audit, "_run_scopus", return_value=payload) as runner:
            metrics = bib_audit.fetch_metrics("IEEE Transactions on Robotics", "15523098")
        args = runner.call_args[0][0]
        self.assertEqual(args[0], "journal")
        self.assertIn("--issn", args)
        self.assertEqual(args[args.index("--issn") + 1], "15523098")
        self.assertEqual(metrics["quartile"], "Q1")

    def test_charmap_crash_is_retried_under_utf8(self):
        # A cp1252 'charmap' crash on Windows is a defect of the console encoding,
        # not a missing Scopus record; the retry is what recovers the entry.
        answers = [{"_error": "UnicodeEncodeError: 'charmap' codec can't encode"},
                   {"title": "Recovered record"}]
        with mock.patch.object(bib_audit, "_run_scopus", side_effect=answers) as runner:
            record = bib_audit.fetch_cite("10.1109/TASE.2024.1")
        self.assertEqual(record["title"], "Recovered record")
        self.assertEqual(runner.call_count, 2)
        self.assertTrue(runner.call_args.kwargs.get("force_utf8"))

    def test_offline_never_calls_scopus(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, "refs.bib", BIB_SOURCE)
            entries = bib_audit.parse_bib(path)
            with mock.patch.object(bib_audit, "_run_scopus") as runner:
                bib_audit.audit(entries, {"cite": {}, "metrics": {}}, offline=True)
        runner.assert_not_called()


class TestReport(unittest.TestCase):

    def test_report_holds_counters_and_no_recommendation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, "refs.bib", BIB_SOURCE)
            entries, result = _run_audit(path)
            machine = bib_audit.build_machine_summary(entries, result, path)
            report = bib_audit.generate_report(entries, result, machine, path)
        self.assertIn("# BibTeX Audit Report", report)
        self.assertIn("## Temporal Distribution", report)
        self.assertIn("## Venue Metrics", report)
        self.assertEqual(machine["total_entries"], 6)
        self.assertEqual(machine["corpus_language"], "en")
        self.assertEqual(machine["by_type"]["article"], 4)

    def test_french_corpus_is_detected(self):
        source = ("@article{fr2024etude,\n  author = {Otis, Martin},\n"
                  "  title = {Une etude de la commande des robots pour la mesure "
                  "de la charge des operateurs},\n"
                  "  journal = {Revue de robotique},\n  year = {2024},\n}\n")
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, "refs.bib", source)
            entries, result = _run_audit(path)
            machine = bib_audit.build_machine_summary(entries, result, path)
        self.assertEqual(machine["corpus_language"], "fr")


if __name__ == "__main__":
    unittest.main(verbosity=1)
