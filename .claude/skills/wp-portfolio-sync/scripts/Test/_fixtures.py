"""
_fixtures.py - shared test fixtures for the wp-portfolio-sync skill.

Stage: imported by every test_*.py in this folder. Never discovered as a
suite itself (leading underscore), per run-offline-tests.ps1's discovery
rule.
"""
import sys
from pathlib import Path

# scripts/Test/_fixtures.py -> parents[1] is scripts/
SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def make_data_dir(root, files):
    """
    --------------------------------------------------------------------------
    Purpose:
        Build a fictitious researcher data folder for an offline test, never
        touching a real data folder or /tmp (R21).

    Inputs:
        root (Path): a tempfile.TemporaryDirectory() path or similar scratch
            root; the data folder is created at root/data.
        files (dict[str, str]): relative path -> UTF-8 text content. Parent
            directories are created as needed.

    Outputs:
        data_dir (Path): root/data, existing, with every file written.
    --------------------------------------------------------------------------
    """
    data_dir = Path(root) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    for relative, text in files.items():
        target = data_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return data_dir


class FakeResponse:
    """
    --------------------------------------------------------------------------
    Purpose:
        A fake requests.Response, for WpClient tests that never touch the
        network.

    Inputs:
        status_code (int): the HTTP status to report.
        json_data: the object .json() returns; None makes .json() raise
            ValueError, matching a response with no JSON body.
        text (str): the raw body, used for an error message's first 200 chars.

    Outputs:
        none (state object).
    --------------------------------------------------------------------------
    """

    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        if self._json_data is None:
            raise ValueError("no JSON body")
        return self._json_data


class _FakeCookieJar:
    """A fake requests.Session.cookies jar: records every .set() call."""

    def __init__(self):
        self.set_calls = []

    def set(self, name, value, domain="", path="/"):
        self.set_calls.append((name, value, domain, path))


class FakeSession:
    """
    --------------------------------------------------------------------------
    Purpose:
        A fake requests.Session for WpClient tests: consumes a fixed list of
        responses/exceptions in order, regardless of whether .get or .put
        reads next, and records every call for assertion.

    Inputs:
        outcomes (list): FakeResponse instances or exception instances,
            consumed in call order by whichever of .get/.put is invoked.

    Outputs:
        none (state object). `.calls` holds (method, url, params_or_json,
        timeout) tuples in call order.
    --------------------------------------------------------------------------
    """

    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls = []
        self.auth = None
        self.cookies = _FakeCookieJar()

    def _consume(self, method, url, params_or_json, timeout):
        self.calls.append((method, url, params_or_json, timeout))
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def get(self, url, params=None, timeout=None):
        return self._consume("GET", url, params, timeout)

    def put(self, url, json=None, timeout=None):
        return self._consume("PUT", url, json, timeout)
