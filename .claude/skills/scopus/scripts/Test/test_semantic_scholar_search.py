"""
test_semantic_scholar_search.py - offline tests for semantic_scholar_api.search_papers.

No network: requests.get is patched, and the throttle is neutralised so the
suite does not sleep. Fictitious records only (R34).
"""

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
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

    def test_http_error_is_raised_not_read_as_no_match(self) -> None:
        # A discovery source must not report a failed request as "no papers" (R8).
        for status in (403, 429, 500, 400):
            with mock.patch.object(s2.requests, "get", return_value=_Resp(status)), \
                 mock.patch.object(s2.time, "sleep", lambda _s: None):
                with self.assertRaises(s2.SearchError):
                    s2.search_papers("floor plan")

    def test_a_real_empty_answer_is_an_empty_list(self) -> None:
        with mock.patch.object(s2.requests, "get", return_value=_Resp(200, {"total": 0})):
            self.assertEqual(s2.search_papers("floor plan"), [])

    def test_year_syntax_is_checked_before_any_request(self) -> None:
        for good in ("2026", "2025-2026", "2025-", "-2015"):
            with mock.patch.object(s2.requests, "get", return_value=_Resp(200, {"data": []})):
                s2.search_papers("floor plan", year=good)
        for bad in ("2025-26", "2025..2026", "last5", "20255"):
            with mock.patch.object(s2.requests, "get") as get:
                with self.assertRaises(ValueError):
                    s2.search_papers("floor plan", year=bad)
                get.assert_not_called()

    def test_a_bool_limit_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            s2.search_papers("floor plan", limit=True)

    def test_empty_query_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            s2.search_papers("   ")

    def test_limit_outside_bounds_is_refused(self) -> None:
        for bad in (0, s2._SEARCH_PAGE_MAX + 1):
            with self.assertRaises(ValueError):
                s2.search_papers("floor plan", limit=bad)


class SearchCliTest(unittest.TestCase):
    """The CLI exit codes testing.md documents: 0 done, 1 failure, 2 refusal (R12)."""

    def setUp(self) -> None:
        patcher = mock.patch.object(s2, "_throttle", lambda: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, argv: list) -> tuple:
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch.object(sys, "argv", ["semantic_scholar_api.py", *argv]), \
             redirect_stdout(out), redirect_stderr(err):
            try:
                s2.main()
                code = 0
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue()

    def test_empty_query_bad_limit_and_bad_year_exit_2(self) -> None:
        for argv in (["search", "  "], ["search", "floor plan", "--limit", "0"],
                     ["search", "floor plan", "--year", "2025-26"]):
            with mock.patch.object(s2.requests, "get") as get:
                self.assertEqual(self._run(argv)[0], 2, argv)
                get.assert_not_called()

    def test_search_flags_outside_search_mode_exit_2(self) -> None:
        for argv in (["match", "Some title", "--year", "2024"], ["paper", "10.1/x", "--limit", "5"]):
            with mock.patch.object(s2.requests, "get") as get:
                self.assertEqual(self._run(argv)[0], 2, argv)
                get.assert_not_called()

    def test_failed_request_exits_1_and_prints_no_result(self) -> None:
        with mock.patch.object(s2.requests, "get", return_value=_Resp(403)):
            code, out = self._run(["search", "floor plan"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")

    def test_success_exits_0_with_records(self) -> None:
        body = {"total": 1, "data": [{"title": "Paper A"}]}
        with mock.patch.object(s2.requests, "get", return_value=_Resp(200, body)):
            code, out = self._run(["search", "floor plan"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["count"], 1)

    def test_main_puts_stdout_on_utf8(self) -> None:
        # A cp1252 console cannot encode U+2212; the abstract must still print.
        raw = io.BytesIO()
        cp1252 = io.TextIOWrapper(raw, encoding="cp1252")
        body = {"total": 1, "data": [{"title": "A", "abstract": "x − y"}]}
        with mock.patch.object(sys, "argv", ["semantic_scholar_api.py", "search", "q"]), \
             mock.patch.object(sys, "stdout", cp1252), \
             mock.patch.object(s2.requests, "get", return_value=_Resp(200, body)):
            s2.main()
            sys.stdout.flush()
        self.assertIn("−".encode("utf-8"), raw.getvalue())


if __name__ == "__main__":
    unittest.main()
