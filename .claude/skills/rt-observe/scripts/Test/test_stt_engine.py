"""Tests for stt_engine.py. Never loads a real STT model - the loader is
always injected, so this suite runs with no faster-whisper install (R21)."""
import io
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

CONFIG = {"voice": {"stt": {
    "engine": {"value": "faster-whisper"}, "model_size": {"value": "small"},
    "compute_type": {"value": "float16"}, "device": {"value": "cuda"},
    "language": {"value": None},
    "vad_filter": {"value": True},
    "vad_min_silence_ms": {"value": 500},
    "condition_on_previous_text": {"value": False}}}}


class _FakeSegment:
    def __init__(self, text):
        self.text = text


class _FakeModel:
    def __init__(self, segments):
        self.segments = segments
        self.calls = 0
        self.last_language = None
        self.last_kwargs = {}

    def transcribe(self, audio, language=None, **kwargs):
        self.calls += 1
        self.last_language = language
        self.last_kwargs = kwargs
        return self.segments, {"language": language or "en"}


class TranscribeCase(unittest.TestCase):
    def test_joins_segment_text(self):
        import stt_engine
        stt_engine.reset_loaded_model()
        model = _FakeModel([_FakeSegment("is this "), _FakeSegment("stale")])
        text = stt_engine.transcribe(b"fake-audio-bytes", CONFIG,
                                     loader=lambda: model)
        self.assertEqual(text, "is this stale")

    def test_loader_is_called_only_once_for_two_calls(self):
        import stt_engine
        stt_engine.reset_loaded_model()
        model = _FakeModel([_FakeSegment("hi")])
        calls = {"n": 0}

        def loader():
            calls["n"] += 1
            return model

        stt_engine.transcribe(b"a", CONFIG, loader=loader)
        stt_engine.transcribe(b"b", CONFIG, loader=loader)
        self.assertEqual(calls["n"], 1)

    def test_missing_dependency_is_a_named_error(self):
        import stt_engine

        def loader():
            raise ModuleNotFoundError("No module named 'faster_whisper'")

        stt_engine.reset_loaded_model()
        with self.assertRaises(stt_engine.SttUnavailable) as caught:
            stt_engine.transcribe(b"a", CONFIG, loader=loader)
        self.assertIn("requirements-voice.txt", str(caught.exception))

    def test_empty_transcription_returns_empty_string(self):
        import stt_engine
        model = _FakeModel([])
        stt_engine.reset_loaded_model()
        text = stt_engine.transcribe(b"silence", CONFIG, loader=lambda: model)
        self.assertEqual(text, "")

    def test_language_argument_is_passed_to_the_model(self):
        import stt_engine
        model = _FakeModel([_FakeSegment("bonjour")])
        stt_engine.reset_loaded_model()
        stt_engine.transcribe(b"a", CONFIG, loader=lambda: model, language="fr")
        self.assertEqual(model.last_language, "fr")

    def test_raw_bytes_are_wrapped_in_a_file_like_object(self):
        # faster-whisper's WhisperModel.transcribe() accepts a path, a
        # file-like object, or an ndarray - never a plain bytes object,
        # which it hands to PyAV's av.open() and fails on. A browser
        # MediaRecorder upload arrives here as raw bytes.
        import stt_engine
        model = _FakeModel([_FakeSegment("ok")])
        captured = {}
        original = model.transcribe

        def spy(audio, language=None, **kwargs):
            captured["audio"] = audio
            return original(audio, language=language, **kwargs)

        model.transcribe = spy
        stt_engine.reset_loaded_model()
        stt_engine.transcribe(b"raw-audio-bytes", CONFIG, loader=lambda: model)
        self.assertIsInstance(captured["audio"], io.BytesIO)
        self.assertEqual(captured["audio"].getvalue(), b"raw-audio-bytes")

    def test_an_unsupported_language_is_refused_not_silently_ignored(self):
        import stt_engine
        model = _FakeModel([_FakeSegment("ok")])
        stt_engine.reset_loaded_model()
        with self.assertRaises(ValueError):
            stt_engine.transcribe(b"a", CONFIG, loader=lambda: model,
                                  language="de")

    def test_devoir2_anti_hallucination_options_reach_the_model(self):
        """Devoir2 measured Whisper transcribing silence and pure tones as
        subtitle credits; its fix is the VAD filter plus no conditioning on
        the previous text. The live preview re-transcribes a buffer that is
        often mostly silence, so the same options must reach this model."""
        import stt_engine
        model = _FakeModel([_FakeSegment("ok")])
        stt_engine.reset_loaded_model()
        stt_engine.transcribe(b"a", CONFIG, loader=lambda: model)
        self.assertIs(model.last_kwargs["vad_filter"], True)
        self.assertEqual(
            model.last_kwargs["vad_parameters"]["min_silence_duration_ms"], 500)
        self.assertIs(model.last_kwargs["condition_on_previous_text"], False)

    def test_a_missing_option_key_is_named_not_defaulted(self):
        import stt_engine
        broken = {"voice": {"stt": dict(CONFIG["voice"]["stt"])}}
        del broken["voice"]["stt"]["vad_filter"]
        stt_engine.reset_loaded_model()
        with self.assertRaises(KeyError) as caught:
            stt_engine.transcribe(b"a", broken,
                                  loader=lambda: _FakeModel([]))
        self.assertIn("vad_filter", str(caught.exception))

    def test_two_concurrent_first_calls_load_the_model_once(self):
        """The dashboard's HTTP server is threaded: a live-preview request and
        the final one can both arrive before the model exists."""
        import stt_engine
        stt_engine.reset_loaded_model()
        loads = []

        def slow_loader():
            loads.append(1)
            time.sleep(0.2)
            return _FakeModel([_FakeSegment("ok")])

        threads = [threading.Thread(
            target=stt_engine.transcribe, args=(b"a", CONFIG),
            kwargs={"loader": slow_loader}) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(loads), 1)


class WarmCase(unittest.TestCase):
    def test_warm_loads_once_and_runs_one_transcription(self):
        import stt_engine
        stt_engine.reset_loaded_model()
        model = _FakeModel([])
        self.assertIsNone(stt_engine.warm(CONFIG, loader=lambda: model))
        self.assertEqual(model.calls, 1)

    def test_warm_never_raises_and_reports_why(self):
        import stt_engine
        stt_engine.reset_loaded_model()

        def broken():
            raise ModuleNotFoundError("No module named 'faster_whisper'")

        reason = stt_engine.warm(CONFIG, loader=broken)
        self.assertIn("requirements-voice", reason)


class CudaDllCase(unittest.TestCase):
    """Ported from Devoir2's _ajouter_repertoires_dll_cuda: without it,
    ctranslate2 raised `cublas64_12.dll is not found` on the first real
    calculation on this machine, which has no system CUDA Toolkit."""

    def _spec_for(self, root):
        class _Spec:
            submodule_search_locations = [str(root)]
        return _Spec()

    def test_cuda_adds_each_package_bin_to_the_search_path(self):
        import stt_engine
        tmp = Path(tempfile.mkdtemp())
        for pkg in ("cublas", "cudnn"):
            (tmp / pkg / "bin").mkdir(parents=True)
        added = []
        env = {"PATH": "C:\\existing"}
        stt_engine.add_cuda_dll_dirs(
            "cuda", platform="win32",
            find_spec=lambda name: self._spec_for(tmp / name.split(".")[1]),
            add_dll_directory=added.append, environ=env)
        self.assertEqual(len(added), 2)
        self.assertIn(str(tmp / "cublas" / "bin"), env["PATH"])
        self.assertIn("C:\\existing", env["PATH"])

    def test_cpu_touches_nothing(self):
        import stt_engine
        added = []
        env = {"PATH": "C:\\existing"}
        stt_engine.add_cuda_dll_dirs(
            "cpu", platform="win32", find_spec=lambda name: None,
            add_dll_directory=added.append, environ=env)
        self.assertEqual(added, [])
        self.assertEqual(env["PATH"], "C:\\existing")

    def test_an_absent_nvidia_parent_package_does_not_raise(self):
        """Devoir2's measured defect: find_spec('nvidia.cublas') raises
        ModuleNotFoundError when the parent 'nvidia' is wholly absent."""
        import stt_engine

        def raising(name):
            raise ModuleNotFoundError("No module named 'nvidia'")

        stt_engine.add_cuda_dll_dirs(
            "cuda", platform="win32", find_spec=raising,
            add_dll_directory=lambda p: None, environ={"PATH": ""})


if __name__ == "__main__":
    unittest.main()
