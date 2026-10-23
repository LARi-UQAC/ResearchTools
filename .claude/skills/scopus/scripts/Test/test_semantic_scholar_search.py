"""
test_semantic_scholar_search.py - offline tests for semantic_scholar_api.search_papers.

No network: requests.get is patched, and the throttle is neutralised so the
suite does not sleep. Fictitious records only (R34).
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import semantic_scholar_api as s2  # noqa: E402


class _Resp:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status: int, body: dict | None = None) -> None:
        self.status_code = status
        self._body = body or {}
        self.text = str(self._body)

    def json(self) -> dict:
        return self._body


class SearchPapersTest(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(s2, "_throttle", lambda: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_returns_records_and_sends_year_and_limit(self) -> None:
        body = {"total": 2, "data": [{"title": "Paper A"}, {"title": "Paper B"}]}
        with mock.patch.object(s2.requests, "get", return_value=_Resp(200, body)) as get:
            records = s2.search_papers("quantity takeoff", year="2025-2026", limit=5)
        self.assertEqual([r["title"] for r in records], ["Paper A", "Paper B"])
        url = get.call_args.args[0]
        params = get.call_args.kwargs["params"]
        self.assertTrue(url.endswith("/paper/search"))
        self.assertEqual(params["year"], "2025-2026")
        self.assertEqual(params["limit"], 5)
        self.assertEqual(params["query"], "quantity takeoff")

    def test_no_year_filter_when_year_is_none(self) -> None:
        with mock.patch.object(s2.requests, "get", return_value=_Resp(200, {"data": []})) as get:
            s2.search_papers("floor plan")
        self.assertNotIn("year", get.call_args.kwargs["params"])

    def test_http_error_yields_empty_list_not_exception(self) -> None:
        with mock.patch.object(s2.requests, "get", return_value=_Resp(403)):
            self.assertEqual(s2.search_papers("floor plan"), [])

    def test_empty_query_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            s2.search_papers("   ")

    def test_limit_outside_bounds_is_refused(self) -> None:
        for bad in (0, s2._SEARCH_PAGE_MAX + 1):
            with self.assertRaises(ValueError):
                s2.search_papers("floor plan", limit=bad)


if __name__ == "__main__":
    unittest.main()
