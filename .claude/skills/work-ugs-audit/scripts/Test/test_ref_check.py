"""
Offline tests of ref_check.py. Hosts are fictitious, the resolver and the connector are fakes, and no socket is
opened: the pinned connections are checked with socket.create_connection replaced.
"""
import io
import json
import ssl
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ref_check  # noqa: E402

ISO = {"name": "ISO", "looks_like": r"ISO\s*\d{4}", "regex": r"ISO\s*\d{4}:\d{4}"}
PUBLIC = "8.8.8.8"
TIMEOUT = 1.0
REFUSED_ADDRESSES = {
    "loopback": "127.0.0.1",
    "private range": "192.168.1.1",
    "link-local": "169.254.1.1",
    "shared address space": "100.64.0.1",
    "IPv4-mapped loopback": "::ffff:127.0.0.1",
    "6to4 embedding a private address": "2002:ac10:0001::1",
    "NAT64 embedding a private address": "64:ff9b::c0a8:101",
}


def resolver_for(*addresses):
    """A resolver that answers the same addresses for every host."""
    return lambda host: list(addresses)


def connector_returning(*answers):
    """A connector that answers each call with the next answer and records its arguments."""
    calls = []
    queue = list(answers)

    def connect(address, port, host, use_tls, timeout, target):
        calls.append((address, port, host, use_tls, timeout, target))
        answer = queue.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    connect.calls = calls
    return connect


class ClassifyAndCitationTests(unittest.TestCase):
    """Kinds, form and citation."""

    def test_kinds_are_told_apart(self):
        self.assertEqual(ref_check.classify("ISO 9001", [ISO]), "standard")
        self.assertEqual(ref_check.classify("https://example.com", [ISO]), "url")
        self.assertEqual(ref_check.classify("Some book", [ISO]), "other")

    def test_a_malformed_standard_is_reported(self):
        self.assertEqual(ref_check.check("ISO 9001", "", [ISO], None, TIMEOUT, 0)["status"], "malformed")

    def test_a_well_formed_standard_is_cited_by_its_identifier(self):
        result = ref_check.check("ISO9001:2015", "According to ISO9001:2015 the process", [ISO], None, TIMEOUT, 0)
        self.assertEqual(result, {"kind": "standard", "status": "form-ok", "cited": True})

    def test_an_uncited_reference_is_reported(self):
        result = ref_check.check("ISO9001:2015", "No citation here.", [ISO], None, TIMEOUT, 0)
        self.assertFalse(result["cited"])

    def test_accented_text_is_searched(self):
        result = ref_check.check("ISO9001:2015", "Une référence ISO9001:2015 éèê.", [ISO], None, TIMEOUT, 0)
        self.assertTrue(result["cited"])

    def test_a_plain_reference_is_cited_when_its_text_is_in_the_body(self):
        self.assertTrue(ref_check.check("Some book", "see Some book p. 3", [], None, TIMEOUT, 0)["cited"])
        self.assertFalse(ref_check.check("Some book", "nothing", [], None, TIMEOUT, 0)["cited"])


class AddressGuardTests(unittest.TestCase):
    """Which addresses are public, and what happens to the others."""

    def test_every_non_public_address_is_refused_and_never_contacted(self):
        for label, address in REFUSED_ADDRESSES.items():
            with self.subTest(label):
                connect = connector_returning(200)
                result = ref_check.check("https://example.com", "", [], connect, TIMEOUT, 0, resolver_for(address), 0)
                self.assertEqual(result["status"], "refused")
                self.assertEqual(connect.calls, [])

    def test_public_addresses_are_allowed_including_a_nat64_wrapped_public_one(self):
        for address in (PUBLIC, "64:ff9b::808:808", "2001:4860:4860::8888"):
            with self.subTest(address):
                result = ref_check.check("https://example.com", "", [], connector_returning(200), TIMEOUT, 0,
                                         resolver_for(address), 0)
                self.assertEqual(result["status"], "reachable")

    def test_a_host_that_does_not_resolve_is_refused(self):
        result = ref_check.check("https://nowhere.example", "", [], connector_returning(200), TIMEOUT, 0,
                                 resolver_for(), 0)
        self.assertEqual(result["status"], "refused")

    def test_a_text_that_is_not_an_address_is_not_public(self):
        self.assertFalse(ref_check.is_public_host("example.com", resolver_for("not-an-address")))

    def test_without_a_resolver_a_url_is_refused(self):
        self.assertEqual(ref_check.check("https://example.com", "", [], connector_returning(200), TIMEOUT, 0)["status"],
                         "refused")

    def test_a_scheme_other_than_http_is_refused(self):
        connect = connector_returning(200)
        result = ref_check.check("ftp://example.com/file", "", [], connect, TIMEOUT, 0, resolver_for(PUBLIC), 0)
        self.assertEqual(result["status"], "refused")
        self.assertEqual(connect.calls, [])


class ConnectValidatedTests(unittest.TestCase):
    """The connection goes to the validated address."""

    def test_the_connector_receives_the_validated_address_the_host_name_and_the_path(self):
        connect = connector_returning(200)
        ref_check.connect_validated("https://example.com/a/b?x=1", resolver_for("10.0.0.1", PUBLIC), connect, TIMEOUT)
        self.assertEqual(connect.calls, [(PUBLIC, 443, "example.com", True, TIMEOUT, "/a/b?x=1")])

    def test_a_plain_http_url_uses_port_80_without_tls_and_a_default_path(self):
        connect = connector_returning(200)
        ref_check.connect_validated("http://example.com", resolver_for(PUBLIC), connect, TIMEOUT)
        self.assertEqual(connect.calls, [(PUBLIC, 80, "example.com", False, TIMEOUT, "/")])

    def test_the_resolver_is_called_once_per_hop(self):
        count = []

        def resolve(host):
            count.append(host)
            return [PUBLIC]

        ref_check.connect_validated("https://example.com", resolve, connector_returning(200), TIMEOUT)
        self.assertEqual(count, ["example.com"])

    def test_no_public_address_raises_with_the_reason(self):
        with self.assertRaises(ValueError) as raised:
            ref_check.connect_validated("https://example.com", resolver_for("127.0.0.1"), connector_returning(200),
                                        TIMEOUT)
        self.assertIn("No validated public address", str(raised.exception))

    def test_a_url_without_a_host_raises(self):
        with self.assertRaises(ValueError):
            ref_check.connect_validated("https://", resolver_for(PUBLIC), connector_returning(200), TIMEOUT)


class PinnedConnectionTests(unittest.TestCase):
    """The real connection classes pin the socket to the address and keep the host name."""

    def test_a_tls_connection_opens_the_address_and_names_the_host(self):
        context = MagicMock(spec=ssl.SSLContext)
        raw_socket = MagicMock()
        with patch("ref_check.socket.create_connection", return_value=raw_socket) as create:
            conn = ref_check._PinnedHTTPSConnection("example.com", 443, PUBLIC, TIMEOUT, context)
            conn.connect()
        create.assert_called_once_with((PUBLIC, 443), TIMEOUT)
        context.wrap_socket.assert_called_once_with(raw_socket, server_hostname="example.com")

    def test_a_plain_connection_opens_the_address_and_sends_the_host_header(self):
        sent = []
        fake_socket = MagicMock()
        fake_socket.sendall.side_effect = sent.append
        with patch("ref_check.socket.create_connection", return_value=fake_socket) as create:
            conn = ref_check._PinnedHTTPConnection("example.com", 80, PUBLIC, TIMEOUT)
            conn.request("HEAD", "/page")
        create.assert_called_once_with((PUBLIC, 80), TIMEOUT)
        request = b"".join(sent)
        self.assertTrue(request.startswith(b"HEAD /page HTTP/1.1"))
        self.assertIn(b"Host: example.com", request)

    def test_the_real_connector_closes_the_connection_when_the_request_fails(self):
        with patch("ref_check.socket.create_connection", side_effect=OSError("refused")):
            with self.assertRaises(OSError):
                ref_check._request_pinned(PUBLIC, 80, "example.com", False, TIMEOUT, "/")


class StatusTests(unittest.TestCase):
    """Reachable, blocked, unreachable, retries and redirects, with a fake connector."""

    def status(self, connect, retries=0, max_redirects=0, resolver=None):
        return ref_check.check("https://example.com", "", [], connect, TIMEOUT, retries,
                               resolver or resolver_for(PUBLIC), max_redirects)["status"]

    def test_the_status_codes_are_named(self):
        self.assertEqual(self.status(connector_returning(200)), "reachable")
        self.assertEqual(self.status(connector_returning(403)), "blocked")
        self.assertEqual(self.status(connector_returning(401)), "blocked")
        self.assertEqual(self.status(connector_returning(404)), "unreachable")
        self.assertEqual(self.status(connector_returning(500)), "unreachable")

    def test_a_connection_failure_is_retried_as_many_times_as_asked(self):
        connect = connector_returning(OSError("a"), OSError("b"), OSError("c"))
        self.assertEqual(self.status(connect, retries=2), "unreachable")
        self.assertEqual(len(connect.calls), 3)

    def test_a_retry_that_succeeds_gives_reachable(self):
        self.assertEqual(self.status(connector_returning(OSError("a"), 200), retries=1), "reachable")

    def test_a_redirect_is_followed_and_validated_at_every_hop(self):
        connect = connector_returning((302, "https://next.example/landing"), 200)
        self.assertEqual(self.status(connect, max_redirects=1), "reachable")
        self.assertEqual(connect.calls[1][2:], ("next.example", True, TIMEOUT, "/landing"))

    def test_a_relative_redirect_stays_on_the_same_host(self):
        connect = connector_returning((301, "/moved"), 200)
        self.assertEqual(self.status(connect, max_redirects=1), "reachable")
        self.assertEqual(connect.calls[1][2], "example.com")
        self.assertEqual(connect.calls[1][5], "/moved")

    def test_a_redirect_to_a_private_host_is_refused(self):
        def resolve(host):
            return ["192.168.0.1"] if host == "private.example" else [PUBLIC]

        connect = connector_returning((302, "https://private.example/"), 200)
        self.assertEqual(self.status(connect, max_redirects=1, resolver=resolve), "refused")
        self.assertEqual(len(connect.calls), 1)

    def test_a_redirect_to_another_scheme_is_refused(self):
        connect = connector_returning((302, "ftp://example.com/file"), 200)
        self.assertEqual(self.status(connect, max_redirects=1), "refused")

    def test_more_redirects_than_allowed_is_unreachable(self):
        connect = connector_returning((302, "https://a.example/"), (302, "https://b.example/"), 200)
        self.assertEqual(self.status(connect, max_redirects=1), "unreachable")


class CommandLineTests(unittest.TestCase):
    """main: refusals exit 2, a good run prints JSON."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.refs = self.tmp / "refs.txt"
        self.body = self.tmp / "body.txt"
        self.refs.write_text("ISO9001:2015\n\nSome book\n", encoding="utf-8")
        self.body.write_text("The text cites ISO9001:2015 only.", encoding="utf-8")

    def tearDown(self):
        for path in self.tmp.iterdir():
            path.unlink()
        self.tmp.rmdir()

    def test_a_missing_refs_file_is_a_refusal(self):
        with self.assertRaises(SystemExit) as raised:
            ref_check.main(["--refs", str(self.tmp / "absent.txt"), "--body", str(self.body)])
        self.assertEqual(raised.exception.code, 2)

    def test_a_missing_patterns_file_is_a_refusal(self):
        with self.assertRaises(SystemExit) as raised:
            ref_check.main(["--refs", str(self.refs), "--body", str(self.body), "--patterns", str(self.tmp / "no.json")])
        self.assertEqual(raised.exception.code, 2)

    def test_a_missing_configuration_key_is_a_refusal(self):
        with patch("ref_check.ugs_config.load", return_value={}):
            with self.assertRaises(SystemExit) as raised:
                ref_check.main(["--refs", str(self.refs), "--body", str(self.body)])
        self.assertEqual(raised.exception.code, 2)

    def test_the_shipped_configuration_holds_every_key_the_module_reads(self):
        config = ref_check.ugs_config.load(ref_check.ugs_config.default_path())
        for key in ref_check.CONFIG_KEYS:
            self.assertIn(key, config)

    def test_a_run_prints_one_result_per_reference_with_its_index(self):
        patterns = self.tmp / "patterns.json"
        patterns.write_text(json.dumps([ISO]), encoding="utf-8")
        out = io.StringIO()
        with redirect_stdout(out):
            ref_check.main(["--refs", str(self.refs), "--body", str(self.body), "--patterns", str(patterns)])
        results = json.loads(out.getvalue())
        self.assertEqual([item["index"] for item in results], [1, 2])
        self.assertEqual(results[0], {"kind": "standard", "status": "form-ok", "cited": True, "index": 1})
        self.assertEqual(results[1]["kind"], "other")


if __name__ == "__main__":
    unittest.main()
