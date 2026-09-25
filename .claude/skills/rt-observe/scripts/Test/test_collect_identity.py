"""
test_collect_identity - the rt_state.section_builders contract over rt_store.

A thin wrapper, so its own suite is thin: it proves the wrapper hands its
arguments through correctly and never adds a failure mode rt_store.py's own
suite does not already cover.
"""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import collect_identity  # noqa: E402
import rt_store  # noqa: E402

NOW = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)


class CollectIdentityTest(unittest.TestCase):
    def test_unconfigured_is_unavailable_with_a_reason(self):
        state = collect_identity.collect(Path("/repo"), Path("/home"), {},
                                         now=NOW)
        self.assertEqual(state["status"], "unavailable")
        self.assertTrue(state["reason"])

    def test_a_declared_but_incomplete_block_is_unavailable_not_a_crash(self):
        """A refusal path (R20)."""
        config = {"postgres": {"host": "db"}}
        state = collect_identity.collect(Path("/repo"), Path("/home"), config,
                                         now=NOW, env={})
        self.assertEqual(state["status"], "unavailable")

    def test_a_configured_store_reports_counts(self):
        def connector(**kwargs):
            class Cursor:
                def __enter__(self): return self
                def __exit__(self, *e): return False
                def execute(self, sql): self._sql = sql
                def fetchone(self):
                    return (2,) if "rt_persons" in self._sql else (0,)
            class Conn:
                def cursor(self): return Cursor()
                def close(self): pass
            return Conn()
        config = {"postgres": {"host": "db", "port": 5432, "dbname": "rt",
                               "user": "lar"}}
        state = collect_identity.collect(
            Path("/repo"), Path("/home"), config, now=NOW,
            env={rt_store.PASSWORD_ENV_VAR: "pw"}, connector=connector)
        self.assertEqual(state["status"], "ok")
        self.assertEqual(state["persons"], 2)


if __name__ == "__main__":
    unittest.main()
