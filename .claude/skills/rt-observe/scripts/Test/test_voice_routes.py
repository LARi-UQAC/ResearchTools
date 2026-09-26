"""Tests for the two voice routes on rt_server.py's handler."""
import io
import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import rt_server  # noqa: E402
from test_rt_state import TOKEN, _FakeSocket, _Keep, Response  # noqa: E402


def call_raw(handler_cls, method, path, raw_body=b"", content_type="application/octet-stream",
            headers=None):
    """Like test_rt_state.call(), but for a non-JSON body (audio bytes)."""
    raw = "%s %s HTTP/1.1\r\nHost: 127.0.0.1\r\n" % (method, path)
    raw += "Content-Type: %s\r\n" % content_type
    raw += "Content-Length: %d\r\n" % len(raw_body)
    for key, val in (headers or {}).items():
        raw += "%s: %s\r\n" % (key, val)
    raw += "\r\n"
    rfile = io.BytesIO(raw.encode("latin-1") + raw_body)
    wfile = _Keep()
    handler_cls(_FakeSocket(rfile, wfile), ("127.0.0.1", 51234), _FakeServerStub())
    return Response(wfile.getvalue())


class _FakeServerStub:
    server_address = ("127.0.0.1", 8787)


def handler_for(voice_transcribe=None, voice_ask=None, caps=None):
    return rt_server.make_handler(
        lambda max_age=None: {"generated": "2026-09-26T12:00:00+00:00"},
        TOKEN, None, [], voice_transcribe=voice_transcribe,
        voice_ask=voice_ask, caps=caps,
        started="2026-09-26T12:00:00+00:00", port=8787)


class TranscribeRouteCase(unittest.TestCase):
    def test_no_callable_installed_answers_501(self):
        handler = handler_for()
        response = call_raw(handler, "POST", "/api/voice/transcribe",
                            raw_body=b"audio",
                            headers={"X-RT-Session-Token": TOKEN})
        self.assertEqual(response.status, 501)

    def test_missing_token_header_is_refused(self):
        handler = handler_for(
            voice_transcribe=lambda body, language="auto": "is this stale")
        response = call_raw(handler, "POST", "/api/voice/transcribe",
                            raw_body=b"audio-bytes")
        self.assertEqual(response.status, 403)

    def test_cross_origin_transcribe_is_refused(self):
        handler = handler_for(
            voice_transcribe=lambda body, language="auto": "is this stale")
        response = call_raw(handler, "POST", "/api/voice/transcribe",
                            raw_body=b"audio-bytes",
                            headers={"X-RT-Session-Token": TOKEN,
                                    "Origin": "https://evil.example"})
        self.assertEqual(response.status, 403)
        self.assertIn("cross-origin", response.json()["reason"])

    def test_transcribes_and_returns_text(self):
        handler = handler_for(
            voice_transcribe=lambda body, language="auto": "is this stale")
        response = call_raw(handler, "POST", "/api/voice/transcribe",
                            raw_body=b"audio-bytes",
                            headers={"X-RT-Session-Token": TOKEN})
        self.assertEqual(response.status, 200)
        self.assertEqual(response.json()["text"], "is this stale")

    def test_engine_unavailable_is_reported_not_crashed(self):
        import stt_engine

        def raiser(_body, language="auto"):
            raise stt_engine.SttUnavailable("faster-whisper is not installed")

        handler = handler_for(voice_transcribe=raiser)
        response = call_raw(handler, "POST", "/api/voice/transcribe",
                            raw_body=b"audio",
                            headers={"X-RT-Session-Token": TOKEN})
        self.assertEqual(response.status, 503)
        self.assertIn("not installed", response.json()["reason"])

    def test_language_query_param_is_forwarded(self):
        captured = {}

        def transcribe(body, language="auto"):
            captured["language"] = language
            return "c'est perime"

        handler = handler_for(voice_transcribe=transcribe)
        response = call_raw(handler, "POST",
                            "/api/voice/transcribe?language=fr",
                            raw_body=b"audio-bytes",
                            headers={"X-RT-Session-Token": TOKEN})
        self.assertEqual(response.status, 200)
        self.assertEqual(captured["language"], "fr")

    def test_no_language_query_param_defaults_to_auto(self):
        captured = {}

        def transcribe(body, language="auto"):
            captured["language"] = language
            return "ok"

        handler = handler_for(voice_transcribe=transcribe)
        call_raw(handler, "POST", "/api/voice/transcribe",
                raw_body=b"audio-bytes",
                headers={"X-RT-Session-Token": TOKEN})
        self.assertEqual(captured["language"], "auto")

    def test_an_unsupported_language_query_param_is_refused(self):
        handler = handler_for(
            voice_transcribe=lambda body, language="auto": "unreachable")
        response = call_raw(handler, "POST",
                            "/api/voice/transcribe?language=de",
                            raw_body=b"audio-bytes",
                            headers={"X-RT-Session-Token": TOKEN})
        self.assertEqual(response.status, 400)


class AskRouteCase(unittest.TestCase):
    def _post_json(self, handler, path, body, headers=None):
        from test_rt_state import call
        return call(handler, "POST", path, body=body, headers=headers)

    def test_requires_a_valid_token(self):
        handler = handler_for(voice_ask=lambda q, language="auto": {"status": "ok"})
        response = self._post_json(handler, "/api/voice/ask",
                                   {"token": "wrong", "question": "x"})
        self.assertEqual(response.status, 403)

    def test_cross_origin_ask_is_refused(self):
        handler = handler_for(voice_ask=lambda q, language="auto": {"status": "ok"})
        response = self._post_json(
            handler, "/api/voice/ask", {"token": TOKEN, "question": "x"},
            headers={"Origin": "https://evil.example"})
        self.assertEqual(response.status, 403)

    def test_refuses_an_empty_question(self):
        handler = handler_for(voice_ask=lambda q, language="auto": {"status": "ok"})
        response = self._post_json(handler, "/api/voice/ask",
                                   {"token": TOKEN, "question": "   "})
        self.assertEqual(response.status, 400)

    def test_refuses_an_oversized_question(self):
        handler = handler_for(voice_ask=lambda q, language="auto": {"status": "ok"},
                              caps={"voice_question_chars": 500})
        response = self._post_json(
            handler, "/api/voice/ask",
            {"token": TOKEN, "question": "x" * 501})
        self.assertEqual(response.status, 400)

    def test_forwards_a_valid_question_and_returns_the_answer(self):
        captured = {}

        def ask(question, language="auto"):
            captured["question"] = question
            return {"status": "ok", "answer_text": "no, all green"}

        handler = handler_for(voice_ask=ask)
        response = self._post_json(handler, "/api/voice/ask",
                                   {"token": TOKEN, "question": "is this stale"})
        self.assertEqual(response.status, 200)
        self.assertEqual(response.json()["answer_text"], "no, all green")
        self.assertEqual(captured["question"], "is this stale")

    def test_language_field_is_forwarded(self):
        captured = {}

        def ask(question, language="auto"):
            captured["language"] = language
            return {"status": "ok"}

        handler = handler_for(voice_ask=ask)
        self._post_json(handler, "/api/voice/ask",
                        {"token": TOKEN, "question": "x", "language": "fr"})
        self.assertEqual(captured["language"], "fr")

    def test_no_language_field_defaults_to_auto(self):
        captured = {}

        def ask(question, language="auto"):
            captured["language"] = language
            return {"status": "ok"}

        handler = handler_for(voice_ask=ask)
        self._post_json(handler, "/api/voice/ask",
                        {"token": TOKEN, "question": "x"})
        self.assertEqual(captured["language"], "auto")

    def test_an_unsupported_language_field_is_refused(self):
        handler = handler_for(voice_ask=lambda q, language="auto": {"status": "ok"})
        response = self._post_json(
            handler, "/api/voice/ask",
            {"token": TOKEN, "question": "x", "language": "de"})
        self.assertEqual(response.status, 400)


if __name__ == "__main__":
    unittest.main()
