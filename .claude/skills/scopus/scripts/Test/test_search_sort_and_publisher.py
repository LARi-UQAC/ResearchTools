"""
test_search_sort_and_publisher - offline unit tests for the 2026-08-12 corrections
to the scopus skill: search ordering, query scope, DOI-prefix publisher, and the
validate ambiguity guard.

Regression guards, each for a measured defect:

1. `search` sent NO sort parameter, so Scopus answered by descending date: the
   most recent and least cited papers, never a founding work. On
   TITLE-ABS-KEY(free space optical communication) the five first hits were all
   2026 papers cited 0 to 3 times, and Khalighi 2014 (2434 citations) was
   unreachable. The default is now -citedby-count.
2. Citation ordering makes an UNQUALIFIED query actively harmful: searching ALL
   fields, "free space optical communication" answered Elements of Information
   Theory, QUANTUM ESPRESSO and GEANT4. Bare keywords are now wrapped in
   TITLE-ABS-KEY(), and only when the query names no field of its own.
3. `argparse` refuses `--sort -coverDate` (a value starting with a dash reads as
   a new option), which is why the dash-free aliases exist.
4. `prism:publisher` is misleading (a learned society where 10.1007 says
   Springer, "Academic Press" for an Elsevier imprint, two empty fields), so the
   publisher is derived from the DOI prefix.
5. `validate` let a client take results[0], which on a measured title was a
   corrigendum to an unrelated paper.

No network, no API key: every function under test is pure string handling, and
the two that print are driven through a stubbed HTTP layer.
"""
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scopus_api  # noqa: E402
from doi_publisher import annotate, doi_prefix, publisher_by_prefix  # noqa: E402


class TestQualifyQuery(unittest.TestCase):
    """Bare keywords get a field scope; an explicit field is left alone."""

    def test_bare_keywords_are_wrapped(self):
        query, qualified = scopus_api.qualify_query("free space optical communication")
        self.assertEqual(query, "TITLE-ABS-KEY(free space optical communication)")
        self.assertTrue(qualified)

    def test_boolean_keywords_without_a_field_are_still_wrapped(self):
        """AND / OR are not field names, so the query is still unscoped."""
        query, qualified = scopus_api.qualify_query("soft robotics AND (actuator OR gripper)")
        self.assertEqual(query, "TITLE-ABS-KEY(soft robotics AND (actuator OR gripper))")
        self.assertTrue(qualified)

    def test_title_abs_key_is_not_double_wrapped(self):
        query, qualified = scopus_api.qualify_query("TITLE-ABS-KEY(free space optical)")
        self.assertEqual(query, "TITLE-ABS-KEY(free space optical)")
        self.assertFalse(qualified)

    def test_au_id_passes_through(self):
        """cover-paper's publication list must keep its exact meaning."""
        query, qualified = scopus_api.qualify_query("AU-ID(57210200087)")
        self.assertEqual(query, "AU-ID(57210200087)")
        self.assertFalse(qualified)

    def test_hyphenated_and_plain_field_codes_pass_through(self):
        for raw in ('TITLE("a paper")', "SRCTITLE(IEEE Access)",
                    "AUTHLASTNAME(Otis)", "DOI(10.1109/x)"):
            with self.subTest(raw=raw):
                self.assertEqual(scopus_api.qualify_query(raw), (raw, False))

    def test_pubyear_filter_passes_through(self):
        """litreview-updater's windowed delta query must not be rewrapped."""
        raw = "robot AND PUBYEAR AFT 2024"
        self.assertEqual(scopus_api.qualify_query(raw), (raw, False))

    def test_empty_query_is_not_wrapped(self):
        self.assertEqual(scopus_api.qualify_query("   "), ("", False))


class TestResolveSort(unittest.TestCase):
    """The alias table exists because argparse rejects a dashed value."""

    def test_default_is_most_cited_first(self):
        self.assertEqual(scopus_api.DEFAULT_SEARCH_SORT, "-citedby-count")

    def test_aliases_resolve_to_api_values(self):
        self.assertEqual(scopus_api.resolve_sort("cited"), "-citedby-count")
        self.assertEqual(scopus_api.resolve_sort("recent"), "-coverDate")
        self.assertEqual(scopus_api.resolve_sort("oldest"), "coverDate")

    def test_canonical_values_pass_through(self):
        self.assertEqual(scopus_api.resolve_sort("-coverDate"), "-coverDate")
        self.assertEqual(scopus_api.resolve_sort("relevancy"), "relevancy")
        self.assertEqual(scopus_api.resolve_sort("none"), "none")

    def test_alias_is_case_insensitive(self):
        self.assertEqual(scopus_api.resolve_sort("  ReCent "), "-coverDate")

    def test_unknown_value_exits_rather_than_sorting_silently(self):
        """A bad value must not reach Scopus, which answers 200 unsorted."""
        with self.assertRaises(SystemExit) as raised:
            with redirect_stdout(io.StringIO()):
                scopus_api.resolve_sort("by-citations")
        self.assertEqual(raised.exception.code, 2)


class TestDoiPublisher(unittest.TestCase):

    def test_prefix_from_bare_doi(self):
        self.assertEqual(doi_prefix("10.1109/COMST.2014.2329501"), "10.1109")

    def test_prefix_from_url_and_doi_scheme(self):
        self.assertEqual(doi_prefix("https://doi.org/10.1007/s10846-020-01307-9"), "10.1007")
        self.assertEqual(doi_prefix("doi:10.1016/j.cosrev.2023.100614"), "10.1016")

    def test_missing_doi_is_a_measurement_not_an_error(self):
        self.assertEqual(doi_prefix(""), "")
        self.assertEqual(doi_prefix(None), "")
        self.assertEqual(publisher_by_prefix(""), "")

    def test_known_publishers(self):
        self.assertEqual(publisher_by_prefix("10.1007/x"), "Springer")
        self.assertEqual(publisher_by_prefix("10.1109/x"), "IEEE")
        self.assertEqual(publisher_by_prefix("10.1016/x"), "Elsevier")

    def test_biomed_central_divergence_is_deliberate(self):
        """10.1186 is out of list in the book repo and IN list here. Do not align."""
        self.assertEqual(publisher_by_prefix("10.1186/s12984-020-00668-4"), "BioMed Central")

    def test_unknown_prefix_is_named_empty_not_guessed(self):
        self.assertEqual(publisher_by_prefix("10.99999/unknown"), "")

    def test_annotate_adds_both_fields_in_place(self):
        record = {"doi": "10.3390/s21051234"}
        self.assertIs(annotate(record), record)
        self.assertEqual(record["doi_prefix"], "10.3390")
        self.assertEqual(record["publisher_by_prefix"], "MDPI")


class TestTitleSimilarity(unittest.TestCase):

    def test_identical_titles_score_one(self):
        self.assertEqual(scopus_api._title_similarity("A review of X", "A review of X"), 1.0)

    def test_normalization_ignores_case_and_punctuation(self):
        self.assertEqual(
            scopus_api._title_similarity("Deep Learning: A Review", "deep learning a review"), 1.0)

    def test_corrigendum_scores_far_below_the_real_paper(self):
        """The measured failure: results[0] was a corrigendum to another paper."""
        asked = "Deep learning for unmanned aerial vehicles detection: A review"
        real = "Deep learning for unmanned aerial vehicles detection: A review"
        corrigendum = ("Corrigendum to Photovoltaic thermal imaging fault detection "
                       "using a convolutional network")
        self.assertGreater(scopus_api._title_similarity(asked, real),
                           scopus_api._title_similarity(asked, corrigendum))

    def test_empty_input_scores_zero(self):
        self.assertEqual(scopus_api._title_similarity("", "something"), 0.0)
        self.assertEqual(scopus_api._title_similarity("something", ""), 0.0)


class _FakeResponse:
    """Minimal stand-in for requests.Response, enough for _check_response."""

    status_code = 200

    def __init__(self, payload):
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def _search_payload(entries, total=None):
    return {"search-results": {
        "opensearch:totalResults": str(total if total is not None else len(entries)),
        "entry": entries,
    }}


class TestSearchParameters(unittest.TestCase):
    """The sort parameter must actually reach Scopus, and be reported back."""

    def _run(self, **kwargs):
        captured = {}

        def fake_get(url, headers=None, params=None, timeout=None):
            captured["params"] = params
            return _FakeResponse(_search_payload([{
                "dc:title": "Survey on free space optical communication",
                "prism:doi": "10.1109/COMST.2014.2329501",
                "citedby-count": "2438",
                "prism:coverDate": "2014-01-01",
            }]))

        buffer = io.StringIO()
        with patch.object(scopus_api.requests, "get", fake_get), redirect_stdout(buffer):
            scopus_api._search("free space optical communication", 5, "KEY", None, **kwargs)
        return captured["params"], json.loads(buffer.getvalue())

    def test_default_sends_citation_sort_and_scoped_query(self):
        params, out = self._run()
        self.assertEqual(params["sort"], "-citedby-count")
        self.assertEqual(params["query"], "TITLE-ABS-KEY(free space optical communication)")
        self.assertEqual(out["sort"], "-citedby-count")
        self.assertTrue(out["query_qualified"])

    def test_recency_caller_gets_date_sort(self):
        params, out = self._run(sort="-coverDate")
        self.assertEqual(params["sort"], "-coverDate")
        self.assertEqual(out["sort"], "-coverDate")

    def test_sort_none_sends_no_parameter_at_all(self):
        """The escape hatch back to the legacy Scopus ordering."""
        params, out = self._run(sort="none")
        self.assertNotIn("sort", params)
        self.assertEqual(out["sort"], "none")

    def test_raw_query_disables_the_field_scope(self):
        params, out = self._run(raw_query=True)
        self.assertEqual(params["query"], "free space optical communication")
        self.assertFalse(out["query_qualified"])

    def test_year_min_wraps_the_scoped_query(self):
        params, _ = self._run(year_min=2022)
        self.assertEqual(params["query"],
                         "(TITLE-ABS-KEY(free space optical communication)) AND PUBYEAR > 2021")

    def test_results_carry_the_derived_publisher(self):
        _, out = self._run()
        self.assertEqual(out["results"][0]["doi_prefix"], "10.1109")
        self.assertEqual(out["results"][0]["publisher_by_prefix"], "IEEE")


class TestValidateGuard(unittest.TestCase):
    """validate must never let a client take results[0] on faith."""

    def _run(self, ref, responses):
        """responses: list of (total, entries) tuples, consumed in order."""
        sent = []

        def fake_get(url, headers=None, params=None, timeout=None):
            sent.append(params["query"])
            total, entries = responses[min(len(sent) - 1, len(responses) - 1)]
            return _FakeResponse(_search_payload(entries, total))

        buffer = io.StringIO()
        with patch.object(scopus_api.requests, "get", fake_get), redirect_stdout(buffer):
            scopus_api._validate(ref, "KEY", None)
        return sent, json.loads(buffer.getvalue())

    def test_phrase_form_is_tried_first(self):
        sent, out = self._run("A precise title", [(1, [{"dc:title": "A precise title"}])])
        self.assertEqual(sent, ['TITLE("A precise title")'])
        self.assertEqual(out["query_form"], "phrase")
        self.assertFalse(out["ambiguous"])

    def test_loose_form_is_the_fallback_so_recall_is_never_lost(self):
        sent, out = self._run("Odd title", [(0, []), (1, [{"dc:title": "Odd title"}])])
        self.assertEqual(sent, ['TITLE("Odd title")', "TITLE(Odd title)"])
        self.assertEqual(out["query_form"], "loose")
        self.assertEqual(out["total_found"], 1)

    def test_several_hits_are_flagged_ambiguous_with_a_warning(self):
        _, out = self._run("Deep learning for unmanned aerial vehicles detection: A review", [(6, [
            {"dc:title": "Corrigendum to Photovoltaic thermal imaging fault detection",
             "prism:doi": "10.1016/j.engappai.2025.113587"},
            {"dc:title": "Deep learning for unmanned aerial vehicles detection: A review",
             "prism:doi": "10.1016/j.cosrev.2023.100614"},
        ])])
        self.assertTrue(out["ambiguous"])
        self.assertIn("Do NOT take results[0]", out["warning"])
        # The point of the guard: the best match is NOT the first record.
        self.assertEqual(out["best_match_index"], 1)

    def test_schema_has_no_found_and_no_record_key(self):
        """The documented schema drift that produced four false NOT FOUND verdicts."""
        _, out = self._run("Anything", [(1, [{"dc:title": "Anything"}])])
        self.assertNotIn("found", out)
        self.assertNotIn("record", out)
        for key in ("mode", "query", "total_found", "results", "ambiguous",
                    "best_match_index", "warning", "scopus_query", "query_form"):
            self.assertIn(key, out)

    def test_zero_hits_say_so_explicitly(self):
        _, out = self._run("Nonexistent", [(0, [])])
        self.assertEqual(out["total_found"], 0)
        self.assertFalse(out["ambiguous"])
        self.assertIsNone(out["best_match_index"])
        self.assertIn("No record", out["warning"])

    def test_embedded_quote_cannot_truncate_the_phrase_query(self):
        sent, _ = self._run('A "quoted" title', [(1, [{"dc:title": "A quoted title"}])])
        self.assertEqual(sent[0], 'TITLE("A quoted title")')

    def test_results_carry_similarity_and_publisher(self):
        _, out = self._run("A precise title", [(1, [
            {"dc:title": "A precise title", "prism:doi": "10.1007/x"}])])
        self.assertEqual(out["results"][0]["title_similarity"], 1.0)
        self.assertEqual(out["results"][0]["publisher_by_prefix"], "Springer")


class TestAuthorIdExtraction(unittest.TestCase):

    def test_au_id_wrapper_form(self):
        self.assertEqual(scopus_api.extract_au_id("AU-ID(57210200087)"), "57210200087")

    def test_bare_digits(self):
        self.assertEqual(scopus_api.extract_au_id("57210200087"), "57210200087")

    def test_case_and_spacing_tolerated(self):
        self.assertEqual(scopus_api.extract_au_id("au-id( 57210200087 )"), "57210200087")

    def test_a_person_name_is_not_an_identifier(self):
        self.assertEqual(scopus_api.extract_au_id("Otis, Martin"), "")
        self.assertEqual(scopus_api.extract_au_id(""), "")

    def test_short_number_is_not_mistaken_for_an_au_id(self):
        """A year or a page number must not be read as an identifier."""
        self.assertEqual(scopus_api.extract_au_id("2024"), "")


class TestHIndex(unittest.TestCase):

    def test_reference_case_matches_the_published_value(self):
        """MEASURED: AU-ID 57210200087, top-25 citation counts -> h = 19, the
        same value Semantic Scholar publishes for the same person."""
        counts = [83, 77, 60, 60, 51, 49, 39, 38, 35, 34, 31, 30, 24, 24, 21,
                  20, 20, 20, 20, 19, 18, 17, 15, 15, 15]
        self.assertEqual(scopus_api.h_index(counts), 19)

    def test_definition_boundary(self):
        self.assertEqual(scopus_api.h_index([3, 3, 3]), 3)
        self.assertEqual(scopus_api.h_index([2, 2, 2]), 2)
        self.assertEqual(scopus_api.h_index([10, 1, 1]), 1)

    def test_no_papers_and_no_citations(self):
        self.assertEqual(scopus_api.h_index([]), 0)
        self.assertEqual(scopus_api.h_index([0, 0, 0]), 0)

    def test_order_does_not_matter(self):
        self.assertEqual(scopus_api.h_index([1, 9, 4, 4]), 3)
        self.assertEqual(scopus_api.h_index([4, 4, 9, 1]), 3)


class _ErrorResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class TestAuthorizationErrorDetection(unittest.TestCase):
    """An unlicensed PRODUCT must not be reported as an invalid KEY."""

    _AUTH_ERROR = {"service-error": {"status": {
        "statusCode": "AUTHORIZATION_ERROR",
        "statusText": "The requestor is not authorized to access the requested view or fields"}}}

    def test_401_authorization_error_is_recognised(self):
        self.assertTrue(scopus_api._is_authorization_error(
            _ErrorResponse(401, self._AUTH_ERROR)))

    def test_403_authorization_error_is_recognised(self):
        self.assertTrue(scopus_api._is_authorization_error(
            _ErrorResponse(403, self._AUTH_ERROR)))

    def test_a_genuinely_invalid_key_is_not_swallowed(self):
        self.assertFalse(scopus_api._is_authorization_error(
            _ErrorResponse(401, {"service-error": {"status": {
                "statusCode": "AUTHENTICATION_ERROR"}}})))

    def test_success_and_other_codes_are_not_authorization_errors(self):
        self.assertFalse(scopus_api._is_authorization_error(_ErrorResponse(200, {})))
        self.assertFalse(scopus_api._is_authorization_error(_ErrorResponse(429, {})))


class TestAuthorModeDegradation(unittest.TestCase):
    """The mode must answer something useful instead of exiting."""

    _AUTH_ERROR = {"service-error": {"status": {"statusCode": "AUTHORIZATION_ERROR"}}}

    def test_name_falls_back_to_semantic_scholar_with_an_actionable_note(self):
        def fake_get(url, headers=None, params=None, timeout=None):
            return _ErrorResponse(401, self._AUTH_ERROR)

        def fake_request(path, params):
            self.assertEqual(path, "/author/search")
            return {"data": [{"authorId": "2370681", "name": "M. Otis",
                              "affiliations": [], "paperCount": 62,
                              "citationCount": 1046, "hIndex": 19}]}

        buffer = io.StringIO()
        with patch.object(scopus_api.requests, "get", fake_get), \
             patch.object(scopus_api.s2, "_request", fake_request), \
             redirect_stdout(buffer):
            scopus_api._author("Martin Otis", "KEY", None, 3)
        out = json.loads(buffer.getvalue())

        self.assertEqual(out["source"], "semantic-scholar-fallback")
        self.assertEqual(out["scopus_author_api"], "unlicensed")
        self.assertEqual(out["results"][0]["h_index"], 19)
        # No Scopus identifier may be invented on this path.
        self.assertIsNone(out["results"][0]["author_id"])
        self.assertIn("AU-ID(<digits>)", out["note"])

    def test_fallback_survives_semantic_scholar_being_down(self):
        def fake_get(url, headers=None, params=None, timeout=None):
            return _ErrorResponse(401, self._AUTH_ERROR)

        def boom(path, params):
            raise RuntimeError("S2 unreachable")

        buffer, errors = io.StringIO(), io.StringIO()
        with patch.object(scopus_api.requests, "get", fake_get), \
             patch.object(scopus_api.s2, "_request", boom), \
             patch.object(sys, "stderr", errors), redirect_stdout(buffer):
            scopus_api._author("Martin Otis", "KEY", None, 3)
        out = json.loads(buffer.getvalue())
        self.assertEqual(out["results"], [])
        self.assertEqual(out["source"], "semantic-scholar-fallback")

    def test_au_id_uses_the_entitled_search_api_and_computes_the_h_index(self):
        pages = [[{"dc:title": f"Paper {i}", "citedby-count": str(c),
                   "prism:coverDate": "2014-01-01", "prism:doi": "10.1109/x",
                   "affiliation": [{"affilname": "Universite du Quebec a Chicoutimi"}]}
                  for i, c in enumerate([83, 77, 60, 2, 1])]]
        seen = {}

        def fake_get(url, headers=None, params=None, timeout=None):
            seen["url"], seen["params"] = url, params
            return _FakeResponse(_search_payload(pages[0], total=5))

        buffer = io.StringIO()
        with patch.object(scopus_api.requests, "get", fake_get), redirect_stdout(buffer):
            scopus_api._author("AU-ID(57210200087)", "KEY", None, 3)
        out = json.loads(buffer.getvalue())

        self.assertEqual(seen["url"], scopus_api.SEARCH_URL)   # not the author endpoint
        self.assertEqual(seen["params"]["query"], "AU-ID(57210200087)")
        self.assertEqual(seen["params"]["sort"], "-citedby-count")
        self.assertEqual(out["source"], "scopus-search-by-au-id")

        profile = out["results"][0]
        self.assertEqual(profile["author_id"], "57210200087")
        self.assertEqual(profile["documents"], 5)
        self.assertEqual(profile["h_index"], 3)          # 83, 77, 60 >= 3
        self.assertEqual(profile["affiliation"], "Universite du Quebec a Chicoutimi")
        self.assertEqual(len(profile["top_papers"]), 3)  # honours --count
        self.assertIsNone(profile["coauthors"])          # never invented

    def test_explicit_au_id_flag_wins_over_the_query(self):
        def fake_get(url, headers=None, params=None, timeout=None):
            return _FakeResponse(_search_payload([], total=0))

        buffer = io.StringIO()
        with patch.object(scopus_api.requests, "get", fake_get), redirect_stdout(buffer):
            scopus_api._author("Martin Otis", "KEY", None, 5, au_id="12345678")
        out = json.loads(buffer.getvalue())
        self.assertEqual(out["scopus_query"], "AU-ID(12345678)")
        self.assertEqual(out["results"][0]["author_id"], "12345678")


if __name__ == "__main__":
    unittest.main(verbosity=2)
