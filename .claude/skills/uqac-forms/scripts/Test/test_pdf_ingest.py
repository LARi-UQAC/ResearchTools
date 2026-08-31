"""
Offline unit tests for pdf_ingest.py (no network, no API key): the validated
PDF-ingest contract that RT-1 publishes and TT-8 reimplements in Node.

Every rule of that contract gets a test, because the contract exists to be met by
two independent implementations. A rule with no test is a rule the second
implementation is free to drop, which is exactly what happened on the Node side
before the contract was written down.

requests.get is patched, so no test reaches the network.
Run with the project Python: python .claude/skills/uqac-forms/scripts/Test/test_pdf_ingest.py
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pdf_ingest  # noqa: E402

PDF_BODY = b"%PDF-1.7\nbody\n%%EOF"


class _FakeResponse:
    """Minimal stand-in for a streamed requests.Response."""

    def __init__(self, body: bytes, status: int = 200,
                 headers: dict | None = None) -> None:
        self._body = body
        self.status_code = status
        self.headers = headers or {"Content-Type": "application/pdf"}
        self.closed = False
        self.chunks_yielded = 0

    def iter_content(self, chunk_size: int):
        for i in range(0, len(self._body), chunk_size):
            self.chunks_yielded += 1
            yield self._body[i:i + chunk_size]

    def close(self) -> None:
        self.closed = True


class _EndlessResponse(_FakeResponse):
    """A source that never stops sending. Only a streaming cap can survive it."""

    def __init__(self) -> None:
        super().__init__(b"%PDF-1.7")

    def iter_content(self, chunk_size: int):
        yield b"%PDF-1.7"
        while True:
            self.chunks_yielded += 1
            yield b"x" * chunk_size


class _IngestTestCase(unittest.TestCase):
    """Shared temporary directory and requests.get patching."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dest = os.path.join(self.tmp.name, "form.pdf")
        self._real_get = pdf_ingest.requests.get
        self.calls: list = []

    def tearDown(self) -> None:
        pdf_ingest.requests.get = self._real_get
        self.tmp.cleanup()

    def serve(self, *responses) -> None:
        """Answer successive requests.get calls with the given responses."""
        queue = list(responses)

        def fake_get(url, **kwargs):
            self.calls.append((url, kwargs))
            return queue.pop(0) if len(queue) > 1 else queue[0]

        pdf_ingest.requests.get = fake_get

    def part_files(self) -> list:
        return [n for n in os.listdir(self.tmp.name) if n.endswith(".part")]


class TestAcceptsAValidPdf(_IngestTestCase):

    def test_writes_the_body_and_returns_the_path(self) -> None:
        self.serve(_FakeResponse(PDF_BODY))
        path = pdf_ingest.fetch_pdf(
            "https://www.uqac.ca/srf/rapport.pdf", self.dest)
        self.assertEqual(path, self.dest)
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), PDF_BODY)

    def test_leaves_no_part_file_behind_on_success(self) -> None:
        self.serve(_FakeResponse(PDF_BODY))
        pdf_ingest.fetch_pdf("https://www.uqac.ca/f.pdf", self.dest)
        self.assertEqual(self.part_files(), [])


class TestMagicBytes(_IngestTestCase):

    def test_rejects_an_html_access_page_served_with_http_200(self) -> None:
        # UQAC answers 200 with an access page when a form moves, so the status
        # code alone never proves a PDF.
        self.serve(_FakeResponse(b"<html><body>Acces refuse</body></html>",
                                 headers={"Content-Type": "text/html"}))
        self.assertIsNone(pdf_ingest.fetch_pdf("https://www.uqac.ca/f.pdf", self.dest))
        self.assertFalse(os.path.exists(self.dest))
        self.assertEqual(self.part_files(), [])

    def test_rejects_a_body_that_only_starts_to_look_like_a_pdf(self) -> None:
        self.serve(_FakeResponse(b"%PD-not-a-pdf"))
        self.assertIsNone(pdf_ingest.fetch_pdf("https://www.uqac.ca/f.pdf", self.dest))

    def test_rejects_an_empty_body(self) -> None:
        self.serve(_FakeResponse(b""))
        self.assertIsNone(pdf_ingest.fetch_pdf("https://www.uqac.ca/f.pdf", self.dest))


class TestSizeCap(_IngestTestCase):

    def test_leaves_no_partial_file_when_the_cap_is_exceeded(self) -> None:
        oversized = b"%PDF-1.7" + b"x" * (pdf_ingest.MAX_PDF_BYTES + 10)
        self.serve(_FakeResponse(oversized))
        self.assertIsNone(pdf_ingest.fetch_pdf("https://www.uqac.ca/f.pdf", self.dest))
        self.assertFalse(os.path.exists(self.dest))
        self.assertEqual(self.part_files(), [])

    def test_the_cap_is_enforced_during_the_stream_not_after_it(self) -> None:
        # The rule the Node side gets wrong: a cap applied after the body is
        # already in memory cannot prevent the allocation it exists to prevent.
        # An endless source proves the difference. If this hangs, it regressed.
        endless = _EndlessResponse()
        self.serve(endless)
        self.assertIsNone(pdf_ingest.fetch_pdf("https://www.uqac.ca/f.pdf", self.dest))
        ceiling = pdf_ingest.MAX_PDF_BYTES // pdf_ingest.CHUNK_BYTES + 2
        self.assertLessEqual(endless.chunks_yielded, ceiling)

    def test_a_caller_may_lower_the_cap(self) -> None:
        self.serve(_FakeResponse(b"%PDF-1.7" + b"x" * 4096))
        self.assertIsNone(pdf_ingest.fetch_pdf(
            "https://www.uqac.ca/f.pdf", self.dest, max_bytes=64))


class TestScheme(_IngestTestCase):

    def test_refuses_a_non_https_url_outright(self) -> None:
        self.serve(_FakeResponse(PDF_BODY))
        self.assertIsNone(pdf_ingest.fetch_pdf("http://www.uqac.ca/f.pdf", self.dest))
        self.assertEqual(self.calls, [], "a non-https URL must not be requested at all")

    def test_refuses_a_redirect_that_downgrades_to_http(self) -> None:
        # The rule the Node side gets wrong: checking only the URL the caller
        # typed is not a scheme check.
        self.serve(_FakeResponse(b"", status=302,
                                 headers={"Location": "http://www.uqac.ca/f.pdf"}))
        self.assertIsNone(pdf_ingest.fetch_pdf("https://www.uqac.ca/f.pdf", self.dest))
        self.assertEqual(len(self.calls), 1, "the downgraded hop must not be fetched")

    def test_follows_a_redirect_that_stays_on_https(self) -> None:
        self.serve(
            _FakeResponse(b"", status=302,
                          headers={"Location": "https://www.uqac.ca/moved.pdf"}),
            _FakeResponse(PDF_BODY))
        path = pdf_ingest.fetch_pdf("https://www.uqac.ca/f.pdf", self.dest)
        self.assertEqual(path, self.dest)
        self.assertEqual(self.calls[1][0], "https://www.uqac.ca/moved.pdf")

    def test_resolves_a_relative_redirect_against_the_current_url(self) -> None:
        self.serve(
            _FakeResponse(b"", status=302, headers={"Location": "/srf/moved.pdf"}),
            _FakeResponse(PDF_BODY))
        pdf_ingest.fetch_pdf("https://www.uqac.ca/a/f.pdf", self.dest)
        self.assertEqual(self.calls[1][0], "https://www.uqac.ca/srf/moved.pdf")


class TestRedirectCap(_IngestTestCase):

    def test_gives_up_after_the_cap(self) -> None:
        loop = _FakeResponse(b"", status=302,
                             headers={"Location": "https://www.uqac.ca/again.pdf"})
        self.serve(loop)
        self.assertIsNone(pdf_ingest.fetch_pdf("https://www.uqac.ca/f.pdf", self.dest))
        self.assertLessEqual(len(self.calls), pdf_ingest.MAX_REDIRECTS + 1)

    def test_a_redirect_without_a_location_is_a_failure_not_a_crash(self) -> None:
        self.serve(_FakeResponse(b"", status=302, headers={}))
        self.assertIsNone(pdf_ingest.fetch_pdf("https://www.uqac.ca/f.pdf", self.dest))


class TestTransport(_IngestTestCase):

    def test_a_timeout_is_always_passed_to_requests(self) -> None:
        # Without one, a source that accepts and then stalls holds the caller
        # open indefinitely.
        self.serve(_FakeResponse(PDF_BODY))
        pdf_ingest.fetch_pdf("https://www.uqac.ca/f.pdf", self.dest)
        self.assertEqual(self.calls[0][1].get("timeout"),
                         pdf_ingest.REQUEST_TIMEOUT_S)

    def test_redirects_are_never_delegated_to_requests(self) -> None:
        # requests cannot re-check the scheme between hops, so it must not be
        # the thing that follows them.
        self.serve(_FakeResponse(PDF_BODY))
        pdf_ingest.fetch_pdf("https://www.uqac.ca/f.pdf", self.dest)
        self.assertIs(self.calls[0][1].get("allow_redirects"), False)

    def test_an_error_status_is_a_failure(self) -> None:
        self.serve(_FakeResponse(b"", status=404))
        self.assertIsNone(pdf_ingest.fetch_pdf("https://www.uqac.ca/f.pdf", self.dest))

    def test_a_network_error_is_reported_not_raised(self) -> None:
        def explode(url, **kwargs):
            raise pdf_ingest.requests.RequestException("connection reset")

        pdf_ingest.requests.get = explode
        self.assertIsNone(pdf_ingest.fetch_pdf("https://www.uqac.ca/f.pdf", self.dest))


class TestDigests(_IngestTestCase):

    def test_sha256_file_is_stable_and_64_characters(self) -> None:
        path = os.path.join(self.tmp.name, "x.pdf")
        with open(path, "wb") as handle:
            handle.write(PDF_BODY)
        first = pdf_ingest.sha256_file(path)
        self.assertEqual(first, pdf_ingest.sha256_file(path))
        self.assertEqual(len(first), 64)

    def test_sha256_bytes_agrees_with_sha256_file(self) -> None:
        path = os.path.join(self.tmp.name, "x.pdf")
        with open(path, "wb") as handle:
            handle.write(PDF_BODY)
        self.assertEqual(pdf_ingest.sha256_bytes(PDF_BODY),
                         pdf_ingest.sha256_file(path))

    def test_the_digest_matches_the_value_the_node_side_computes(self) -> None:
        # Frozen so the two implementations of the contract cannot drift apart
        # silently. Recomputed by hand:
        #   node -e "crypto.createHash('sha256').update(Buffer.from('%PDF-1.7\\nbody\\n%%EOF')).digest('hex')"
        self.assertEqual(
            pdf_ingest.sha256_bytes(PDF_BODY),
            "c8e838a61303dddd519d1171802bc781f371d1307a811d4aa86632c7aa577745")


class TestCommandLine(_IngestTestCase):

    def run_main(self, argv: list) -> tuple:
        """Run main(argv) and return (exit code, parsed JSON on stdout)."""
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = pdf_ingest.main(argv)
        return code, json.loads(buffer.getvalue())

    def test_reports_the_digest_on_success(self) -> None:
        self.serve(_FakeResponse(PDF_BODY))
        code, payload = self.run_main(["https://www.uqac.ca/f.pdf", self.dest])
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["sha256"], pdf_ingest.sha256_bytes(PDF_BODY))

    def test_a_refusal_is_machine_readable_and_exits_nonzero(self) -> None:
        # A caller parsing stdout should not have to scrape the log to learn
        # that nothing was written.
        self.serve(_FakeResponse(b"<html>Acces refuse</html>"))
        code, payload = self.run_main(["https://www.uqac.ca/f.pdf", self.dest])
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertFalse(os.path.exists(self.dest))

    def test_the_cap_can_be_lowered_from_the_command_line(self) -> None:
        self.serve(_FakeResponse(b"%PDF-1.7" + b"x" * 4096))
        code, _ = self.run_main(
            ["https://www.uqac.ca/f.pdf", self.dest, "--max-bytes", "64"])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
