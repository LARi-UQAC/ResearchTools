"""
Offline tests for vram_probe.py - the read-only stage of the VRAM optimizer.

Every function there answers a question about the machine without changing it, so these
tests replace the three sources of truth (the manifest tree, `ollama show`, the daemon log)
with fixtures. No network, no GPU, no Ollama daemon.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SCRIPTS))

import vram_probe as vp  # noqa: E402


def _write_manifest(root: Path, name: str, tag: str, layers: list[dict]) -> None:
    path = root / name / tag
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"layers": layers}), encoding="utf-8")


class TestManifestLayers(unittest.TestCase):
    def test_a_vision_tag_reports_its_projector_beside_the_model(self):
        # Measured 2026-08-27: the writer's base tag ships a 5368 MiB model layer plus an
        # 879 MiB projector, and not naming the projector is what bought back the margin.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_manifest(root, "vendor-a", "9b", [
                {"mediaType": "application/vnd.ollama.image.model", "size": 5629046784,
                 "digest": "sha256:aaa"},
                {"mediaType": "application/vnd.ollama.image.projector", "size": 921698304,
                 "digest": "sha256:bbb"},
            ])
            layers = vp.manifest_layers("vendor-a:9b", manifests_root=root)

        self.assertEqual({layer["kind"] for layer in layers}, {"model", "projector"})
        self.assertIsNotNone(vp.projector_layer(layers))
        self.assertEqual(vp.model_layer(layers)["digest"], "sha256:aaa")

    def test_a_tag_with_vision_baked_in_reports_no_projector(self):
        # The counter-case, also measured: one model layer with vision inside the GGUF, so
        # there is nothing to strip and that margin cannot be recovered at all.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_manifest(root, "vendor-b", "9b", [
                {"mediaType": "application/vnd.ollama.image.model", "size": 6594494464,
                 "digest": "sha256:ccc"},
                {"mediaType": "application/vnd.ollama.image.license", "size": 11357,
                 "digest": "sha256:ddd"},
            ])
            layers = vp.manifest_layers("vendor-b:9b", manifests_root=root)

        self.assertIsNone(vp.projector_layer(layers))

    def test_a_registry_nested_manifest_is_found_too(self):
        # Pulled models nest under registry.ollama.ai/library; locally created ones do not.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_manifest(root / "registry.ollama.ai" / "library", "vendor-c", "7b", [
                {"mediaType": "application/vnd.ollama.image.model", "size": 4683075040,
                 "digest": "sha256:eee"},
            ])
            layers = vp.manifest_layers("vendor-c:7b", manifests_root=root)

        self.assertEqual(len(layers), 1)

    def test_a_bare_name_resolves_to_the_latest_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_manifest(root, "vendor-d", "latest", [
                {"mediaType": "application/vnd.ollama.image.model", "size": 100,
                 "digest": "sha256:fff"},
            ])
            self.assertEqual(len(vp.manifest_layers("vendor-d", manifests_root=root)), 1)

    def test_an_unknown_tag_raises_rather_than_returning_empty(self):
        # An empty list would read as "this model has no layers" and let the caller build on
        # a fact that was never established.
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(vp.ProbeError):
                vp.manifest_layers("absent:1b", manifests_root=Path(tmp))

    def test_a_manifest_without_a_model_layer_raises(self):
        self.assertRaises(vp.ProbeError, vp.model_layer, [{"kind": "license", "size": 1,
                                                           "digest": "sha256:zzz"}])


class TestNativeMaxContext(unittest.TestCase):
    def test_context_length_is_read_from_ollama_show(self):
        show = "  Model\n    architecture        qwen2\n    context length      32768\n"
        with mock.patch.object(vp, "_ollama_show", return_value=show):
            self.assertEqual(vp.native_max_context("vendor-c:7b"), 32768)

    def test_a_show_without_a_context_length_raises(self):
        with mock.patch.object(vp, "_ollama_show", return_value="  Model\n"):
            with self.assertRaises(vp.ProbeError):
                vp.native_max_context("vendor-c:7b")


class TestDaemonSettings(unittest.TestCase):
    def test_the_last_server_config_line_wins(self):
        # The log accumulates one 'server config' line per daemon start, so a restart
        # appends rather than replaces; reading the first would report a stale setting and
        # the sweep would then attribute its numbers to a value the daemon no longer has.
        log = (
            'time=1 level=INFO msg="server config" env="map[OLLAMA_KV_CACHE_TYPE:f16 '
            'OLLAMA_NUM_PARALLEL:1]"\n'
            'time=2 level=INFO msg="server config" env="map[OLLAMA_KV_CACHE_TYPE:q8_0 '
            'OLLAMA_NUM_PARALLEL:1]"\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "server.log"
            path.write_text(log, encoding="utf-8")
            settings = vp.daemon_settings(server_log=path)

        self.assertEqual(settings["OLLAMA_KV_CACHE_TYPE"], "q8_0")
        self.assertEqual(settings["OLLAMA_NUM_PARALLEL"], "1")

    def test_a_missing_log_raises_rather_than_assuming_a_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(vp.ProbeError):
                vp.daemon_settings(server_log=Path(tmp) / "absent.log")

    def test_a_log_without_a_server_config_line_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "server.log"
            path.write_text("time=1 level=INFO msg=\"listening\"\n", encoding="utf-8")
            with self.assertRaises(vp.ProbeError):
                vp.daemon_settings(server_log=path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
