"""
test_discover_preview.py - offline tests for discover.py and preview.py.

Proves: pagination stops on an empty or short batch, per_page comes from
wp-sync-config.json, output containment, the site-conflict refusal, a 401
returning 1, the stale ref_year note, the injected-year CLI boundary
(R19), the gate feeding preview's exit code, and that preview makes no
network call at all.
"""
import contextlib
import io
import json
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import _fixtures  # noqa: F401
from _fixtures import grant

import discover
import preview
import wp_errors


class _PagingClient:
    def __init__(self, batches):
        self.batches = list(batches)
        self.gets = []

    def get_json(self, route, params):
        self.gets.append((route, params))
        index = params["page"] - 1
        if index < len(self.batches):
            return self.batches[index]
        return []


class _UnauthorizedClient:
    def get_json(self, route, params):
        raise wp_errors.WpSyncError(
            "401 Unauthorized for %s - check WP_APP_USER/WP_APP_PASSWORD" % route, status_code=401
        )


class _ExactBoundaryClient:
    """Simulates WordPress's own behaviour: a page beyond the last one answers
    400 rest_post_invalid_page_number, never an empty batch, when the site's
    total page count is an exact multiple of per_page."""

    def __init__(self, full_batches):
        self.full_batches = list(full_batches)
        self.gets = []

    def get_json(self, route, params):
        self.gets.append((route, params))
        index = params["page"] - 1
        if index < len(self.full_batches):
            return self.full_batches[index]
        raise wp_errors.WpSyncError("HTTP 400 for %s" % route, status_code=400)


def _page(id_, slug):
    return {"id": id_, "slug": slug, "title": {"rendered": "Titre %s" % slug}, "link": "https://portfolio.example.org/researcher/%s" % slug}


class TestFetchPages(unittest.TestCase):
    def test_pagination_short_page(self):
        client = _PagingClient([[_page(1, "a"), _page(2, "b")], [_page(3, "c")]])
        pages = discover.fetch_pages(client, 2)
        self.assertEqual([p["id"] for p in pages], [1, 2, 3])
        self.assertEqual(len(client.gets), 2)

    def test_pagination_empty_page(self):
        client = _PagingClient([[]])
        pages = discover.fetch_pages(client, 100)
        self.assertEqual(pages, [])

    def test_pagination_exact_boundary_stops(self):
        client = _ExactBoundaryClient([[_page(1, "a"), _page(2, "b")]])
        pages = discover.fetch_pages(client, 2)
        self.assertEqual([p["id"] for p in pages], [1, 2])
        self.assertEqual(len(client.gets), 2)

    def test_pagination_real_error_still_raises(self):
        class _AlwaysFails:
            def get_json(self, route, params):
                raise wp_errors.WpSyncError("HTTP 500 for %s" % route, status_code=500)

        with self.assertRaises(wp_errors.WpSyncError):
            discover.fetch_pages(_AlwaysFails(), 100)


class TestDiscoverMain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name) / "data"
        self.data_dir.mkdir()
        (self.data_dir / "config").mkdir()

    def test_per_page_from_config(self):
        client = _PagingClient([[_page(1, "a")]])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = discover.main(
                ["--data-dir", str(self.data_dir), "--site", "https://portfolio.example.org/researcher", "--json"],
                environ={},
                client_factory=lambda *a: client,
            )
        self.assertEqual(code, 0)
        self.assertEqual(client.gets[0][1]["per_page"], 100)

    def test_discover_out_contained(self):
        client = _PagingClient([[]])
        code = discover.main(
            ["--data-dir", str(self.data_dir), "--site", "https://portfolio.example.org/researcher", "--out", "..\\x.json"],
            environ={},
            client_factory=lambda *a: client,
        )
        self.assertEqual(code, 2)

    def test_discover_site_conflict(self):
        (self.data_dir / "config" / "mapping.yaml").write_text(
            "site: https://portfolio.example.org/researcher\nentries: []\n", encoding="utf-8"
        )
        client = _PagingClient([[]])
        code = discover.main(
            ["--data-dir", str(self.data_dir), "--site", "https://other.example.org"],
            environ={},
            client_factory=lambda *a: client,
        )
        self.assertEqual(code, 2)

    def test_discover_401_returns_1(self):
        code = discover.main(
            ["--data-dir", str(self.data_dir), "--site", "https://portfolio.example.org/researcher"],
            environ={},
            client_factory=lambda *a: _UnauthorizedClient(),
        )
        self.assertEqual(code, 1)

    def test_missing_credentials_refused_not_raised(self):
        # No client_factory: exercises the real make_session/client_from_config path.
        code = discover.main(
            ["--data-dir", str(self.data_dir), "--site", "https://portfolio.example.org/researcher"],
            environ={},
        )
        self.assertEqual(code, 2)

    def test_dry_run_writes_nothing(self):
        client = _PagingClient([[_page(1, "a")]])
        out = self.data_dir / "config" / "pages.json"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = discover.main(
                ["--data-dir", str(self.data_dir), "--site", "https://portfolio.example.org/researcher", "--dry-run", "--json"],
                environ={},
                client_factory=lambda *a: client,
            )
        self.assertEqual(code, 0)
        self.assertFalse(out.exists())
        report = json.loads(buf.getvalue())
        self.assertTrue(report["dry_run"])
        self.assertEqual(report["count"], 1)


class TestStaleNote(unittest.TestCase):
    def test_stale_note(self):
        self.assertIsNotNone(preview.stale_ref_year_note(2026, 2027))
        self.assertIsNone(preview.stale_ref_year_note(2026, 2026))


class TestPreviewMain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name) / "data"
        self.data_dir.mkdir()
        (self.data_dir / "config").mkdir()
        (self.data_dir / "config" / "mapping.yaml").write_text(
            "site: https://portfolio.example.org/researcher\n"
            "ref_year: 2026\n"
            "recent_window: 6\n"
            "recent_label: Six dernières années\n"
            "excluded_funding_statuses: []\n"
            "entries:\n"
            "  - cv_path: financement\n"
            "    page_id: 201\n"
            "    mode: split\n"
            "    renderer: financement\n"
            "    recent_marker: fin-r\n"
            "    history_marker: fin-h\n",
            encoding="utf-8",
        )
        (self.data_dir / "cihr.json").write_text(json.dumps({"financement": [grant()]}, ensure_ascii=False), encoding="utf-8")

    def test_preview_injected_year(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = preview.main(["--data-dir", str(self.data_dir), "--json"], today_year=2030, environ={})
        self.assertEqual(code, 0)
        report = json.loads(buf.getvalue())
        self.assertTrue(any("2030" in n for n in report["notes"]))

    def test_preview_gate_failure_exit_1(self):
        with unittest.mock.patch(
            "preview.verify_mapping",
            return_value={"unapproved": [["financement", "Titre Inventé"]], "not_covered": []},
        ):
            code = preview.main(["--data-dir", str(self.data_dir)], today_year=2026, environ={})
        self.assertEqual(code, 1)

    def test_preview_shows_empty_section_after_exclusion(self):
        # M1 second half (PR #50 review): preview.py must surface the same
        # empty-after-exclusion refusal push_wp.py would raise, so the
        # approval step is not blind to it.
        (self.data_dir / "config" / "mapping.yaml").write_text(
            "site: https://portfolio.example.org/researcher\n"
            "ref_year: 2026\n"
            "recent_window: 6\n"
            "recent_label: Six dernières années\n"
            "excluded_funding_statuses: [Refuse]\n"
            "entries:\n"
            "  - cv_path: financement\n"
            "    page_id: 201\n"
            "    mode: split\n"
            "    renderer: financement\n"
            "    recent_marker: fin-r\n"
            "    history_marker: fin-h\n",
            encoding="utf-8",
        )
        self.data_dir.joinpath("cihr.json").write_text(
            json.dumps({"financement": [grant(statut="Refuse")]}, ensure_ascii=False), encoding="utf-8"
        )
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = preview.main(["--data-dir", str(self.data_dir), "--json"], today_year=2026, environ={})
        self.assertEqual(code, 0)
        report = json.loads(buf.getvalue())
        entry_notes = report["entries"][0]["notes"]
        self.assertTrue(any("empty section" in n for n in entry_notes))

    def test_preview_makes_no_network_call(self):
        with unittest.mock.patch("wp_common.make_session", side_effect=AssertionError("network touched")):
            code = preview.main(["--data-dir", str(self.data_dir)], today_year=2026, environ={})
        self.assertEqual(code, 0)

    def test_json_report_on_refusal(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = preview.main(
                ["--data-dir", str(self.data_dir), "--mapping", "config/nope.yaml", "--json"],
                today_year=2026,
                environ={},
            )
        self.assertEqual(code, 2)
        report = json.loads(buf.getvalue())
        self.assertEqual(report["exit_code"], 2)

    def test_malformed_extras_file_refused_not_raised(self):
        # code-review finding #1 (PR #50 round 3): section_size() now
        # transitively raises WpRefusal (via split_entry_items ->
        # _validate_extra_items, M3) for a malformed *_extra.yaml, but
        # preview.py's call to it sat OUTSIDE any try/except - a record
        # missing a required key used to crash preview.main() uncaught
        # while push_wp.main() on the same setup correctly refused.
        (self.data_dir / "config" / "mapping.yaml").write_text(
            "site: https://portfolio.example.org/researcher\n"
            "ref_year: 2026\n"
            "recent_window: 6\n"
            "recent_label: Six dernières années\n"
            "excluded_funding_statuses: []\n"
            "entries:\n"
            "  - cv_path: implications\n"
            "    page_id: 202\n"
            "    mode: split\n"
            "    renderer: implications\n"
            "    recent_marker: impl-r\n"
            "    history_marker: impl-h\n",
            encoding="utf-8",
        )
        self.data_dir.joinpath("cihr.json").write_text(
            json.dumps(
                {
                    "implications": [
                        {
                            "categorie": "comite",
                            "nom": "Comité Fictif",
                            "role": "Membre",
                            "organisation": "Org Fictive",
                            "debut": "2024/1",
                            "fin": "",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        # Missing the required "role" key - _validate_extra_items refuses this.
        self.data_dir.joinpath("config", "implications_extra.yaml").write_text(
            "- categorie: comite\n  nom: Comité Extra Incomplet\n  organisation: ''\n  debut: '2020/1'\n  fin: ''\n",
            encoding="utf-8",
        )
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = preview.main(["--data-dir", str(self.data_dir), "--json"], today_year=2026, environ={})
        # The gate (verify_mapping) catches the same WpRefusal independently
        # and reports it as an unapproved/render-failed entry, so exit is 1
        # (a reportable failure) - the point of this test is that preview.main()
        # returns a code at all instead of raising uncaught.
        self.assertEqual(code, 1)
        report = json.loads(buf.getvalue())
        entry_notes = report["entries"][0]["notes"]
        self.assertTrue(any("missing required key" in n for n in entry_notes))
        self.assertTrue(any("render failed" in cv_path_title[1] for cv_path_title in report["gate"]["unapproved"]))
        # section_size() and render_entry() both raise the SAME WpRefusal for
        # this entry; once section_size's own except appends the note, the
        # render_entry try block must not run a second time and duplicate it
        # (code-review re-review finding, PR #50 round 3).
        render_failed_notes = [n for n in entry_notes if n.startswith("render failed")]
        self.assertEqual(len(render_failed_notes), 1, entry_notes)

    def test_malformed_extras_yaml_syntax_refused_not_raised(self):
        # code-review finding (PR #50 round 3, re-review): a syntactically
        # malformed *_extra.yaml raises yaml.YAMLError, not WpRefusal, deep
        # inside split_entry_items -> _load_yaml_list_or_dict. push_wp.py's
        # top-level try/except already catches (OSError, ValueError,
        # yaml.YAMLError) around its own section_size/verify_mapping calls;
        # preview.py's per-entry try blocks only caught WpRefusal/WpSyncError.
        (self.data_dir / "config" / "mapping.yaml").write_text(
            "site: https://portfolio.example.org/researcher\n"
            "ref_year: 2026\n"
            "recent_window: 6\n"
            "recent_label: Six dernières années\n"
            "excluded_funding_statuses: []\n"
            "entries:\n"
            "  - cv_path: implications\n"
            "    page_id: 202\n"
            "    mode: split\n"
            "    renderer: implications\n"
            "    recent_marker: impl-r\n"
            "    history_marker: impl-h\n",
            encoding="utf-8",
        )
        self.data_dir.joinpath("cihr.json").write_text(
            json.dumps(
                {
                    "implications": [
                        {
                            "categorie": "comite",
                            "nom": "Comité Fictif",
                            "role": "Membre",
                            "organisation": "Org Fictive",
                            "debut": "2024/1",
                            "fin": "",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        # Syntactically invalid YAML (unbalanced flow sequence), not merely
        # a well-formed-but-incomplete record.
        self.data_dir.joinpath("config", "implications_extra.yaml").write_text(
            "- categorie: [comite\n",
            encoding="utf-8",
        )
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = preview.main(["--data-dir", str(self.data_dir), "--json"], today_year=2026, environ={})
        # The per-entry section_size() check degrades gracefully (one
        # "render failed" note, printed to stderr above); the SAME
        # yaml.YAMLError then recurs inside verify_mapping()'s own
        # render_entry() call, which is not per-entry recoverable the way
        # the entries loop is - preview.py reports it the same way it
        # already reports a gate-level WpRefusal (error_report shape),
        # rather than crashing uncaught.
        self.assertEqual(code, 1)
        report = json.loads(buf.getvalue())
        self.assertIn("while parsing a flow sequence", report["error"])

    def test_split_entry_missing_cv_path_refused_not_raised(self):
        # code-review finding (PR #50 round 3, re-review): push_wp.main()
        # calls validate_mapping() before ever reaching section_size(), so a
        # split entry missing cv_path is refused cleanly; preview.py never
        # called validate_mapping, so the same input raised KeyError('cv_path')
        # uncaught out of section_size().
        (self.data_dir / "config" / "mapping.yaml").write_text(
            "site: https://portfolio.example.org/researcher\n"
            "ref_year: 2026\n"
            "recent_window: 6\n"
            "recent_label: Six dernières années\n"
            "excluded_funding_statuses: []\n"
            "entries:\n"
            "  - page_id: 201\n"
            "    mode: split\n"
            "    renderer: financement\n"
            "    recent_marker: fin-r\n"
            "    history_marker: fin-h\n",
            encoding="utf-8",
        )
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = preview.main(["--data-dir", str(self.data_dir), "--json"], today_year=2026, environ={})
        self.assertEqual(code, 2)
        report = json.loads(buf.getvalue())
        self.assertIn("cv_path", report["error"])

    def test_extras_file_os_error_refused_not_raised(self):
        # code-review finding (PR #50 round 3, re-review): preview.py's
        # per-entry and gate try/except blocks caught WpRefusal/WpSyncError/
        # yaml.YAMLError but not OSError, unlike push_wp.main()'s single
        # top-level try/except which already covers (OSError, ValueError,
        # yaml.YAMLError) for the equivalent code path - an OSError while
        # reading a malformed/inaccessible *_extra.yaml (permission error,
        # deleted mid-run) used to crash preview.main() uncaught.
        (self.data_dir / "config" / "mapping.yaml").write_text(
            "site: https://portfolio.example.org/researcher\n"
            "ref_year: 2026\n"
            "recent_window: 6\n"
            "recent_label: Six dernières années\n"
            "excluded_funding_statuses: []\n"
            "entries:\n"
            "  - cv_path: implications\n"
            "    page_id: 202\n"
            "    mode: split\n"
            "    renderer: implications\n"
            "    recent_marker: impl-r\n"
            "    history_marker: impl-h\n",
            encoding="utf-8",
        )
        self.data_dir.joinpath("cihr.json").write_text(
            json.dumps(
                {
                    "implications": [
                        {
                            "categorie": "comite",
                            "nom": "Comité Fictif",
                            "role": "Membre",
                            "organisation": "Org Fictive",
                            "debut": "2024/1",
                            "fin": "",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        with unittest.mock.patch("render._load_yaml_list_or_dict", side_effect=OSError("disk read error")):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = preview.main(["--data-dir", str(self.data_dir), "--json"], today_year=2026, environ={})
        self.assertEqual(code, 1)
        report = json.loads(buf.getvalue())
        self.assertIn("disk read error", report["error"])

    def test_gate_refusal_caught_not_raised(self):
        with unittest.mock.patch("preview.verify_mapping", side_effect=wp_errors.WpRefusal("denylist missing")):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = preview.main(
                    ["--data-dir", str(self.data_dir), "--json"], today_year=2026, environ={}
                )
        self.assertEqual(code, 2)
        report = json.loads(buf.getvalue())
        self.assertIn("denylist missing", report["error"])


if __name__ == "__main__":
    unittest.main()
