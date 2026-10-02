"""
test_push_wp.py - offline tests for push_wp.py.

Proves: raw-content-only reads (D8), the gate and both pre-flight refusals
run before any network call (D6), one GET+PUT+GET per page regardless of
how many entries target it, every write outcome run_push must distinguish
(dropped write, timeout-after-write, HTTP error), validate_mapping's
refusals, and that no secret ever reaches stdout/stderr.
"""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import _fixtures  # noqa: F401
from _fixtures import SCRIPTS, make_data_dir, grant

import wp_errors
import push_wp


def _write_mapping(data_dir, entries, extra=None):
    mapping = {
        "site": "https://portfolio.example.org/researcher",
        "ref_year": 2026,
        "recent_window": 6,
        "recent_label": "Six dernières années",
        "excluded_funding_statuses": [],
        "entries": entries,
    }
    if extra:
        mapping.update(extra)
    (data_dir / "config").mkdir(exist_ok=True)
    import yaml

    (data_dir / "config" / "mapping.yaml").write_text(yaml.safe_dump(mapping), encoding="utf-8")
    return mapping


def _write_cv(data_dir, data):
    (data_dir / "cihr.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _one_financement_entry(page_id=201):
    return {
        "cv_path": "financement",
        "page_id": page_id,
        "mode": "split",
        "renderer": "financement",
        "recent_marker": "fin-r",
        "history_marker": "fin-h",
    }


class TestReplaceBetweenMarkers(unittest.TestCase):
    def test_missing_marker_fails_naming_it(self):
        with self.assertRaises(wp_errors.WpSyncError) as ctx:
            push_wp.replace_between_markers("<p>no markers here</p>", "fin-r", "<p>new</p>")
        self.assertIn("fin-r", str(ctx.exception))

    def test_duplicate_marker_pair_fails(self):
        content = (
            "<!-- cvsync:fin-r -->a<!-- /cvsync:fin-r -->"
            "<!-- cvsync:fin-r -->b<!-- /cvsync:fin-r -->"
        )
        with self.assertRaises(wp_errors.WpSyncError) as ctx:
            push_wp.replace_between_markers(content, "fin-r", "<p>new</p>")
        self.assertIn("fin-r", str(ctx.exception))

    def test_single_pair_replaced(self):
        content = "<!-- cvsync:fin-r -->old<!-- /cvsync:fin-r -->"
        result = push_wp.replace_between_markers(content, "fin-r", "new")
        self.assertIn("new", result)
        self.assertNotIn("old", result)


class TestValidateMapping(unittest.TestCase):
    def test_empty_entries_refused(self):
        with self.assertRaises(wp_errors.WpRefusal):
            push_wp.validate_mapping({"entries": []})

    def test_missing_key_for_mode_refused(self):
        entry = {"cv_path": "financement", "page_id": 1, "mode": "split", "renderer": "financement"}
        with self.assertRaises(wp_errors.WpRefusal):
            push_wp.validate_mapping({"entries": [entry]})

    def test_page_id_not_int_refused(self):
        with self.assertRaises(wp_errors.WpRefusal):
            push_wp.validate_mapping({"entries": [{"cv_path": "x", "page_id": "1", "mode": "markers", "marker": "m"}]})

    def test_unknown_mode_refused(self):
        with self.assertRaises(wp_errors.WpRefusal):
            push_wp.validate_mapping({"entries": [{"cv_path": "x", "page_id": 1, "mode": "bogus"}]})

    def test_renderer_phq_refused(self):
        entry = dict(_one_financement_entry(), renderer="phq")
        with self.assertRaises(wp_errors.WpRefusal) as ctx:
            push_wp.validate_mapping({"entries": [entry]})
        self.assertIn("phq", str(ctx.exception))

    def test_renderer_outside_phase1_refused(self):
        entry = dict(_one_financement_entry(), renderer="bogus")
        with self.assertRaises(wp_errors.WpRefusal):
            push_wp.validate_mapping({"entries": [entry]})

    def test_duplicate_page_marker_pair_refused(self):
        a = {"cv_path": "x", "page_id": 1, "mode": "markers", "marker": "m"}
        b = {"cv_path": "y", "page_id": 1, "mode": "markers", "marker": "m"}
        with self.assertRaises(wp_errors.WpRefusal):
            push_wp.validate_mapping({"entries": [a, b]})

    def test_replace_page_shared_refused(self):
        a = {"cv_path": "x", "page_id": 1, "mode": "replace"}
        b = {"cv_path": "y", "page_id": 1, "mode": "markers", "marker": "m"}
        with self.assertRaises(wp_errors.WpRefusal):
            push_wp.validate_mapping({"entries": [a, b]})

    def test_public_path_must_start_with_slash(self):
        entry = dict(_one_financement_entry(), public_path="no-slash")
        with self.assertRaises(wp_errors.WpRefusal):
            push_wp.validate_mapping({"entries": [entry]})

    def test_valid_mapping_accepted(self):
        push_wp.validate_mapping({"entries": [_one_financement_entry()]})


class TestSectionSize(unittest.TestCase):
    def test_list_section(self):
        self.assertEqual(push_wp.section_size({"financement": [grant(), grant()]}, _one_financement_entry()), 2)

    def test_empty_list_section(self):
        self.assertEqual(push_wp.section_size({"financement": []}, _one_financement_entry()), 0)


class TestNormalizeBlock(unittest.TestCase):
    def test_crlf_and_strip(self):
        self.assertEqual(push_wp.normalize_block("  a\r\nb  \r\n"), "a\nb")


class TestRunPush(unittest.TestCase):
    def _fixture(self, tmp, entries, data, **client_kwargs):
        data_dir = make_data_dir(tmp, {})
        import render

        settings = render.RenderSettings(ref_year=2026, window=6, recent_label="Six dernières années", excluded_funding_statuses=())
        mapping = {"entries": entries}
        pages = push_wp.plan_pages(mapping, data, data_dir, settings)
        client = _fixtures.FakeClient(**client_kwargs)
        return pages, client

    def test_edit_context_and_raw_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            pages, client = self._fixture(
                tmp, [_one_financement_entry(201)], {"financement": [grant()]}, pages={}, raw_missing=True
            )
            results = push_wp.run_push(client, pages, apply=False)
            self.assertEqual(results[0]["status"], "failed")
            self.assertIn("content.raw", results[0]["error"])
            self.assertTrue(all(params.get("context") == "edit" for _route, params in client.gets))

    def test_dry_run_never_puts(self):
        with tempfile.TemporaryDirectory() as tmp:
            pages, client = self._fixture(tmp, [_one_financement_entry(201)], {"financement": [grant()]}, pages={201: "<!-- cvsync:fin-r -->old<!-- /cvsync:fin-r -->"})
            results = push_wp.run_push(client, pages, apply=False)
            self.assertEqual(results[0]["status"], "would-change")
            self.assertEqual(client.puts, [])

    def test_unchanged_not_put(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = {"financement": [grant()]}
            pages, client = self._fixture(tmp, [_one_financement_entry(201)], data, pages={})
            # Prime the fake page with content already matching the rendered blocks.
            built = ""
            for block in pages[0]["blocks"]:
                marker = block["marker"]
                built += "<!-- cvsync:%s -->\n%s\n<!-- /cvsync:%s -->" % (marker, block["html"], marker)
            client.pages[201] = built
            results = push_wp.run_push(client, pages, apply=True)
            self.assertEqual(results[0]["status"], "unchanged")
            self.assertEqual(client.puts, [])

    def test_one_put_per_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            entries = [_one_financement_entry(201), dict(_one_financement_entry(201), cv_path="implications", renderer="implications", recent_marker="imp-r", history_marker="imp-h")]
            data = {"financement": [grant()], "implications": []}
            pages, client = self._fixture(
                tmp,
                entries,
                data,
                pages={201: "<!-- cvsync:fin-r --><!-- /cvsync:fin-r --><!-- cvsync:fin-h --><!-- /cvsync:fin-h --><!-- cvsync:imp-r --><!-- /cvsync:imp-r -->"},
            )
            self.assertEqual(len(pages), 1)
            results = push_wp.run_push(client, pages, apply=True)
            self.assertEqual(len(client.puts), 1)
            self.assertEqual(len(client.gets), 2)

    def test_dropped_write_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            pages, client = self._fixture(
                tmp, [_one_financement_entry(201)], {"financement": [grant()]},
                pages={201: "<!-- cvsync:fin-r -->old<!-- /cvsync:fin-r --><!-- cvsync:fin-h --><!-- /cvsync:fin-h -->"},
                drop_writes=True,
            )
            results = push_wp.run_push(client, pages, apply=True)
            self.assertEqual(results[0]["status"], "failed")

    def test_put_timeout_confirmed_by_readback(self):
        with tempfile.TemporaryDirectory() as tmp:
            pages, client = self._fixture(
                tmp, [_one_financement_entry(201)], {"financement": [grant()]},
                pages={201: "<!-- cvsync:fin-r -->old<!-- /cvsync:fin-r --><!-- cvsync:fin-h --><!-- /cvsync:fin-h -->"},
                put_raises=wp_errors.WpWriteUnconfirmed("timeout"),
            )
            results = push_wp.run_push(client, pages, apply=True)
            self.assertEqual(results[0]["status"], "updated")
            self.assertTrue(any("timeout" in n for n in results[0]["notes"]))

    def test_put_timeout_lost_write_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            pages, client = self._fixture(
                tmp, [_one_financement_entry(201)], {"financement": [grant()]},
                pages={201: "<!-- cvsync:fin-r -->old<!-- /cvsync:fin-r --><!-- cvsync:fin-h --><!-- /cvsync:fin-h -->"},
                put_raises=wp_errors.WpWriteUnconfirmed("timeout"),
                drop_writes=True,
            )
            results = push_wp.run_push(client, pages, apply=True)
            self.assertEqual(results[0]["status"], "failed")

    def test_put_http_error_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            pages, client = self._fixture(
                tmp, [_one_financement_entry(201)], {"financement": [grant()]},
                pages={201: "<!-- cvsync:fin-r -->old<!-- /cvsync:fin-r --><!-- cvsync:fin-h --><!-- /cvsync:fin-h -->"},
                put_status=403,
            )
            results = push_wp.run_push(client, pages, apply=True)
            self.assertEqual(results[0]["status"], "failed")
            self.assertIn("403", results[0]["error"])


class TestMainCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name) / "data"
        self.data_dir.mkdir()

    def _mapping_and_cv(self, entries=None, data=None):
        entries = entries if entries is not None else [_one_financement_entry(201)]
        data = data if data is not None else {"financement": [grant()]}
        _write_mapping(self.data_dir, entries)
        _write_cv(self.data_dir, data)
        return data

    def test_apply_requires_yes(self):
        self._mapping_and_cv()
        client = _fixtures.FakeClient(pages={201: "<!-- cvsync:fin-r --><!-- /cvsync:fin-r --><!-- cvsync:fin-h --><!-- /cvsync:fin-h -->"})
        code = push_wp.main(
            ["--data-dir", str(self.data_dir), "--apply"],
            environ={},
            client_factory=lambda *a: client,
        )
        self.assertEqual(code, 2)
        self.assertEqual(client.gets, [])
        self.assertEqual(client.puts, [])

    def test_empty_section_refused(self):
        self._mapping_and_cv(data={"financement": []})
        client = _fixtures.FakeClient(pages={})
        code = push_wp.main(["--data-dir", str(self.data_dir)], environ={}, client_factory=lambda *a: client)
        self.assertEqual(code, 2)

    def test_empty_section_allowed_with_flag(self):
        self._mapping_and_cv(data={"financement": []})
        client = _fixtures.FakeClient(pages={201: "<!-- cvsync:fin-r --><!-- /cvsync:fin-r --><!-- cvsync:fin-h --><!-- /cvsync:fin-h -->"})
        code = push_wp.main(
            ["--data-dir", str(self.data_dir), "--allow-empty-section"],
            environ={},
            client_factory=lambda *a: client,
        )
        self.assertEqual(code, 0)

    def test_gate_blocks_before_network(self):
        self._mapping_and_cv()
        client = _fixtures.FakeClient(pages={})
        with unittest.mock.patch(
            "push_wp.verify_mapping",
            return_value={"unapproved": [["financement", "Titre Inventé"]], "not_covered": []},
        ):
            code = push_wp.main(["--data-dir", str(self.data_dir)], environ={}, client_factory=lambda *a: client)
        self.assertEqual(code, 2)
        self.assertEqual(client.gets, [])
        self.assertEqual(client.puts, [])

    def test_json_report_shape(self):
        self._mapping_and_cv()
        client = _fixtures.FakeClient(pages={201: "<!-- cvsync:fin-r --><!-- /cvsync:fin-r --><!-- cvsync:fin-h --><!-- /cvsync:fin-h -->"})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = push_wp.main(["--data-dir", str(self.data_dir), "--json"], environ={}, client_factory=lambda *a: client)
        self.assertEqual(code, 0)
        report = json.loads(buf.getvalue())
        for key in ("site", "apply", "gate", "pages", "exit_code"):
            self.assertIn(key, report)

    def test_secret_never_printed(self):
        self._mapping_and_cv()
        client = _fixtures.FakeClient(pages={201: "<!-- cvsync:fin-r --><!-- /cvsync:fin-r --><!-- cvsync:fin-h --><!-- /cvsync:fin-h -->"})
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            push_wp.main(
                ["--data-dir", str(self.data_dir), "--json"],
                environ={"WP_APP_USER": "alice", "WP_APP_PASSWORD": "S3CRET-PW"},
                client_factory=lambda *a: client,
            )
        self.assertNotIn("S3CRET-PW", out.getvalue())
        self.assertNotIn("S3CRET-PW", err.getvalue())

    def test_requests_not_imported(self):
        code = (
            "import sys; sys.path.insert(0, r'%s'); import push_wp, verify_titles, render; "
            "print('requests' in sys.modules)" % str(SCRIPTS)
        )
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.stdout.strip(), "False", result.stderr)


if __name__ == "__main__":
    unittest.main()
