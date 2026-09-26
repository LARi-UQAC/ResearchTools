"""Tests for stt_engine.py. Never loads a real STT model - the loader is
always injected, so this suite runs with no faster-whisper install (R21)."""
import io
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

CONFIG = {"voice": {"stt": {
    "engine": {"value": "faster-whisper"}, "model_size": {"value": "small"},
    "compute_type": {"value": "int8"}, "device": {"value": "cpu"},
    "language": {"value": None}}}}


class _FakeSegment:
    def __init__(self, text):
        self.text = text


class _FakeModel:
    def __init__(self, segments):
        self.segments = segments
        self.calls = 0
        self.last_language = None

    def transcribe(self, audio, language=None):
        self.calls += 1
        self.last_language = language
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

        def spy(audio, language=None):
            captured["audio"] = audio
            return original(audio, language=language)

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


if __name__ == "__main__":
    unittest.main()
