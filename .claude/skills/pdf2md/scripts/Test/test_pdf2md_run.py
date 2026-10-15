"""Offline tests for `pdf2md.py run`. Every stage module is patched at the
attribute `_run_full_pipeline` imports at call time, so no pip, server or
conversion process is ever started (R20/R21).

Review 2026-10-15: H4 (a failed bootstrap under --yes proceeded to launch the
server) and M4 (`run` had no dry run, R16)."""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pdf2md
import pdf2md_bootstrap
import pdf2md_convert
import pdf2md_models
import pdf2md_server
from pdf2md_settings import load_pipeline_config

OK_REPORT = {"ok": True, "missing_packages": [], "applied": True}
FAILED_REPORT = {"ok": False, "missing_packages_after": ["mineru"], "applied": True}
HEALTHY = SimpleNamespace(healthy=True, listening=True, image_min_tokens_warning_present=False)
UNHEALTHY = SimpleNamespace(healthy=False, listening=False, image_min_tokens_warning_present=False)


class _Harness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = self.tmp.name
        self.launch_server = mock.Mock(return_value=mock.Mock(pid=777))
        self.launch_convert = mock.Mock(return_value=SimpleNamespace(pid=4242))
        self.resolve = mock.Mock(return_value=SimpleNamespace(binary="llama-server", n_ctx_train=8, model_gguf="m", mmproj_gguf="p", alias="a"))
        self.addCleanup(self.tmp.cleanup)

    def run_cli(self, bootstrap_report, extra=(), server_state=HEALTHY):
        argv = ["x.pdf", "-o", self.out, "--json", *extra]
        patches = [
            mock.patch.object(pdf2md_bootstrap, "run_bootstrap", return_value=bootstrap_report),
            mock.patch.object(pdf2md_models, "resolve_vlm_paths", self.resolve),
            mock.patch.object(pdf2md_server, "launch_server", self.launch_server),
            mock.patch.object(pdf2md_server, "wait_for_server", return_value=server_state),
            mock.patch.object(pdf2md_convert, "launch_convert", self.launch_convert),
        ]
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            for p in patches:
                p.start()
            try:
                code = pdf2md._run_full_pipeline(argv)
            finally:
                mock.patch.stopall()
        return code, buffer.getvalue()


class TestRunStopsOnAFailedBootstrap(_Harness):
    def test_a_failed_bootstrap_under_yes_exits_1_and_launches_nothing(self):
        code, _ = self.run_cli(FAILED_REPORT, extra=("--yes",))
        self.assertEqual(code, 1)
        self.launch_server.assert_not_called()
        self.launch_convert.assert_not_called()
        self.resolve.assert_not_called()

    def test_a_not_ok_dry_run_exits_2_and_launches_nothing(self):
        code, _ = self.run_cli(FAILED_REPORT)
        self.assertEqual(code, 2)
        self.launch_server.assert_not_called()


class TestRunIsADryRunByDefault(_Harness):
    def test_without_yes_nothing_is_launched_and_the_plan_is_printed(self):
        code, output = self.run_cli(OK_REPORT)
        self.assertEqual(code, 0)
        self.assertIn('"dry_run": true', output)
        self.launch_server.assert_not_called()
        self.launch_convert.assert_not_called()
        self.resolve.assert_not_called()  # resolving may touch the model registry

    def test_a_dry_run_creates_no_output_directory(self):
        target = os.path.join(self.out, "not-created")
        argv = ["x.pdf", "-o", target, "--json"]
        with mock.patch.object(pdf2md_bootstrap, "run_bootstrap", return_value=OK_REPORT), redirect_stdout(io.StringIO()):
            pdf2md._run_full_pipeline(argv)
        self.assertFalse(os.path.exists(target))

    def test_with_yes_the_server_and_the_conversion_are_launched_once_each(self):
        # Positive control: without it, "never launches" would pass the tests above.
        code, output = self.run_cli(OK_REPORT, extra=("--yes",))
        self.assertEqual(code, 0)
        self.launch_server.assert_called_once()
        self.launch_convert.assert_called_once()
        self.assertIn("4242", output)

    def test_an_unhealthy_server_stops_before_the_conversion(self):
        code, _ = self.run_cli(OK_REPORT, extra=("--yes",), server_state=UNHEALTHY)
        self.assertEqual(code, 1)
        self.launch_convert.assert_not_called()


class TestNoOrphanServer(_Harness):
    def test_an_unhealthy_server_is_terminated_not_left_running(self):
        proc = mock.Mock(pid=778)
        self.launch_server.return_value = proc
        self.run_cli(OK_REPORT, extra=("--yes",), server_state=UNHEALTHY)
        proc.terminate.assert_called_once()

    def test_a_healthy_server_is_left_running(self):
        proc = mock.Mock(pid=778)
        self.launch_server.return_value = proc
        self.run_cli(OK_REPORT, extra=("--yes",))
        proc.terminate.assert_not_called()

    def test_a_failing_conversion_launch_terminates_the_server(self):
        proc = mock.Mock(pid=778)
        self.launch_server.return_value = proc
        self.launch_convert.side_effect = OSError("no mineru-kit")
        with self.assertRaises(OSError):
            self.run_cli(OK_REPORT, extra=("--yes",))
        proc.terminate.assert_called_once()


class TestRunReadsItsDefaultsFromConfig(_Harness):
    def test_the_default_port_is_the_configured_one(self):
        seen = {}

        def fake_bootstrap(**kwargs):
            seen.update(kwargs)
            return OK_REPORT

        with mock.patch.object(pdf2md_bootstrap, "run_bootstrap", fake_bootstrap), redirect_stdout(io.StringIO()):
            pdf2md._run_full_pipeline(["x.pdf", "-o", self.out])
        self.assertIn(f":{load_pipeline_config()['port']}/", seen["expected_server_url"])

    def test_an_explicit_port_wins(self):
        seen = {}

        def fake_bootstrap(**kwargs):
            seen.update(kwargs)
            return OK_REPORT

        with mock.patch.object(pdf2md_bootstrap, "run_bootstrap", fake_bootstrap), redirect_stdout(io.StringIO()):
            pdf2md._run_full_pipeline(["x.pdf", "-o", self.out, "--port", "31999"])
        self.assertIn(":31999/", seen["expected_server_url"])


class TestSettingsFile(unittest.TestCase):
    def test_a_missing_key_is_named_with_its_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "pdf2md-pipeline.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('{"port": {"value": 1, "provenance": "x"}}')
            from pathlib import Path

            with self.assertRaises(RuntimeError) as caught:
                load_pipeline_config(Path(path))
        self.assertIn("pip_install_timeout_s", str(caught.exception))
        self.assertIn("pdf2md-pipeline.json", str(caught.exception))

    def test_every_shipped_value_carries_a_provenance(self):
        import json
        from pathlib import Path

        data = json.loads((Path(pdf2md.__file__).with_name("pdf2md-pipeline.json")).read_text(encoding="utf-8"))
        for key, entry in data.items():
            self.assertTrue(entry.get("provenance", "").strip(), f"{key} has no provenance (R4)")

    def test_requirements_txt_and_the_json_pins_agree(self):
        # Two lists naming one version is the drift this repo keeps legislating against.
        from pathlib import Path

        lines = Path(pdf2md.__file__).with_name("requirements.txt").read_text(encoding="utf-8").splitlines()
        in_requirements = {line.strip() for line in lines if line.strip().startswith("mineru")}
        self.assertEqual(in_requirements, set(load_pipeline_config()["pinned_packages"]))

    def test_every_pinned_package_is_an_exact_pin(self):
        for spec in load_pipeline_config()["pinned_packages"]:
            self.assertRegex(spec, r"^[A-Za-z0-9_.\-]+==\d+(\.\d+)*$")


if __name__ == "__main__":
    unittest.main()
