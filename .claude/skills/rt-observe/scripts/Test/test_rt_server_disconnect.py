"""
A browser that refreshes closes its connection while the server is still writing
the answer. On Windows that raised ConnectionAbortedError (WinError 10053) out of
the handler, and socketserver printed a long traceback in the console for what is
an ordinary event (2026-11-09). The handler now treats a vanished client as
nothing to report, and ONLY that: any other error still propagates (R20).

No port is bound and no process is spawned: the handler is driven in memory over
a fake socket whose write fails, as test_rt_state.py does.
"""
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import rt_server  # noqa: E402

REQUEST = b"GET /api/ping HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"


class _GoneSocket:
    """A socket whose peer has already left: every write raises `error`."""

    def __init__(self, error):
        self._error = error
        self._rfile = io.BytesIO(REQUEST)

    def makefile(self, mode="rb", *_args, **_kwargs):
        return io.BytesIO() if "w" in mode else self._rfile

    def sendall(self, _data):
        raise self._error

    def close(self):
        pass


class _Server:
    server_address = ("127.0.0.1", 8787)


def handler_class():
    return rt_server.make_handler(
        lambda max_age=None: {}, "token", None, [],
        started="2026-11-09T00:00:00", port=8787)


def drive(error):
    return handler_class()(_GoneSocket(error), ("127.0.0.1", 51234), _Server())


class ClientGone(unittest.TestCase):

    def test_an_aborted_connection_raises_nothing(self):
        handler = drive(ConnectionAbortedError(10053, "connection aborted"))
        self.assertTrue(handler.close_connection)

    def test_a_reset_connection_raises_nothing(self):
        self.assertTrue(drive(ConnectionResetError(10054, "reset")).close_connection)

    def test_a_broken_pipe_raises_nothing(self):
        self.assertTrue(drive(BrokenPipeError(32, "broken pipe")).close_connection)

    def test_any_other_error_still_propagates(self):
        with self.assertRaises(ValueError):
            drive(ValueError("a defect, not a client that left"))

    def test_an_unrelated_os_error_still_propagates(self):
        with self.assertRaises(PermissionError):
            drive(PermissionError(13, "denied"))

    def test_a_normal_request_still_answers(self):
        class _Keep(io.BytesIO):
            def close(self):
                pass

        class _Socket:
            def __init__(self):
                self.out = _Keep()
                self._rfile = io.BytesIO(REQUEST)

            def makefile(self, mode="rb", *_a, **_k):
                return self.out if "w" in mode else self._rfile

            def sendall(self, data):
                self.out.write(data)

            def close(self):
                pass

        sock = _Socket()
        handler_class()(sock, ("127.0.0.1", 51234), _Server())
        self.assertIn(b"200", sock.out.getvalue().split(b"\r\n", 1)[0])


if __name__ == "__main__":
    unittest.main()
