"""
test_rt_store - the optional PostgreSQL identity/audit-mapping layer.

Offline: no real database anywhere. `PostgresStore` is exercised with a fake
connector (a stand-in for psycopg.connect) that records what it was asked to run
against fake cursors, and the "driver absent" path is exercised with a connector
that raises ImportError rather than actually uninstalling psycopg (R21).

The recurring assertion, shared with every other collector in this skill: an
unconfigured layer is UNAVAILABLE WITH A NAMED REASON, never a crash and never a
silently empty section (R8).
"""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rt_store  # noqa: E402

NOW = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)


class FakeCursor:
    def __init__(self, rows_by_query, executed):
        self._rows_by_query = rows_by_query
        self._executed = executed
        self._last = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, *args):
        self._executed.append(" ".join(sql.split()))
        self._last = sql

    def fetchone(self):
        for needle, row in self._rows_by_query.items():
            if needle in self._last:
                return row
        return (0,)

    def fetchall(self):
        for needle, rows in self._rows_by_query.items():
            if needle in self._last:
                return rows
        return []


class FakeConnection:
    def __init__(self, rows_by_query=None, raise_on_execute=None):
        self.executed = []
        self.committed = False
        self.closed = False
        self._rows_by_query = rows_by_query or {}
        self._raise_on_execute = raise_on_execute

    def cursor(self):
        if self._raise_on_execute:
            raise self._raise_on_execute
        return FakeCursor(self._rows_by_query, self.executed)

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


def fake_connector(rows_by_query=None, raise_on_connect=None,
                   raise_on_execute=None):
    def connect(**kwargs):
        if raise_on_connect:
            raise raise_on_connect
        return FakeConnection(rows_by_query, raise_on_execute)
    return connect


class GetStoreTest(unittest.TestCase):
    def test_no_postgres_block_is_the_default_zero_service_state(self):
        store = rt_store.get_store({})
        self.assertIsInstance(store, rt_store.NullStore)
        self.assertFalse(store.available)
        self.assertIn("optional", store.reason)

    def test_a_declared_block_missing_a_key_is_an_explicit_error(self):
        config = {"postgres": {"host": "db", "port": 5432, "dbname": "rt"}}
        with self.assertRaises(rt_store.StoreError) as ctx:
            rt_store.get_store(config, env={})
        self.assertIn("'user'", str(ctx.exception))

    def test_a_declared_block_with_no_password_env_var_is_an_explicit_error(self):
        config = {"postgres": {"host": "db", "port": 5432, "dbname": "rt",
                               "user": "lar"}}
        with self.assertRaises(rt_store.StoreError) as ctx:
            rt_store.get_store(config, env={})
        self.assertIn(rt_store.PASSWORD_ENV_VAR, str(ctx.exception))

    def test_a_complete_block_yields_a_postgres_store(self):
        config = {"postgres": {"host": "db", "port": 5432, "dbname": "rt",
                               "user": "lar"}}
        store = rt_store.get_store(
            config, env={rt_store.PASSWORD_ENV_VAR: "secret"},
            connector=fake_connector())
        self.assertIsInstance(store, rt_store.PostgresStore)
        self.assertTrue(store.available)


class PostgresStoreTest(unittest.TestCase):
    def _store(self, **kw):
        config = {"postgres": {"host": "db", "port": 5432, "dbname": "rt",
                               "user": "lar"}}
        return rt_store.get_store(
            config, env={rt_store.PASSWORD_ENV_VAR: "secret"},
            connector=fake_connector(**kw))

    def test_counts_reads_the_three_tables(self):
        store = self._store(rows_by_query={
            "rt_persons": (3,), "rt_person_identifiers": (5,),
            "rt_snapshot_history": (11,)})
        counts = store.counts()
        self.assertEqual(counts["status"], "ok")
        self.assertEqual(counts["persons"], 3)
        self.assertEqual(counts["identifiers"], 5)
        self.assertEqual(counts["snapshots"], 11)

    def test_counts_on_a_broken_table_is_unavailable_not_a_crash(self):
        """A refusal path (R20): the tables were never migrated."""
        store = self._store(raise_on_execute=RuntimeError("relation does not exist"))
        counts = store.counts()
        self.assertEqual(counts["status"], "unavailable")
        self.assertIn("migrate", counts["reason"])

    def test_a_connection_failure_is_store_unavailable_not_a_crash(self):
        store = rt_store.get_store(
            {"postgres": {"host": "db", "port": 5432, "dbname": "rt",
                         "user": "lar"}},
            env={rt_store.PASSWORD_ENV_VAR: "secret"},
            connector=fake_connector(
                raise_on_connect=OSError("connection refused")))
        with self.assertRaises(rt_store.StoreUnavailable) as ctx:
            store.counts()
        self.assertIn("connection refused", str(ctx.exception))

    def test_missing_psycopg_is_store_unavailable_not_an_import_crash(self):
        """No connector injected and no real psycopg installed: the ImportError
        inside PostgresStore._connect must become StoreUnavailable."""
        store = rt_store.PostgresStore(
            {"host": "db", "port": 5432, "dbname": "rt", "user": "lar",
            "password": "x"})
        with mock.patch.dict(sys.modules, {"psycopg": None}):
            with self.assertRaises(rt_store.StoreUnavailable) as ctx:
                store._connect()
        self.assertIn("psycopg", str(ctx.exception))

    def test_migrate_dry_run_touches_nothing(self):
        connector = fake_connector()
        store = self._store()
        report = store.migrate(dry_run=True)
        self.assertFalse(report["applied"])
        self.assertEqual(len(report["statements"]), 3)

    def test_migrate_yes_creates_the_three_tables_idempotently(self):
        store = self._store()
        report = store.migrate(dry_run=False)
        self.assertTrue(report["applied"])
        # idempotent: a second run against the same fake connection succeeds
        # the same way, since the statements are CREATE TABLE IF NOT EXISTS
        report2 = store.migrate(dry_run=False)
        self.assertTrue(report2["applied"])


class NullStoreTest(unittest.TestCase):
    def test_null_store_never_raises_on_read(self):
        store = rt_store.NullStore("not configured")
        self.assertEqual(store.counts()["status"], "unavailable")
        self.assertEqual(store.people()["status"], "unavailable")

    def test_null_store_migrate_is_a_refusal(self):
        store = rt_store.NullStore("not configured")
        with self.assertRaises(rt_store.StoreUnavailable):
            store.migrate()


class CollectTest(unittest.TestCase):
    def test_collect_reports_unavailable_with_reason_when_unconfigured(self):
        state = rt_store.collect(Path("/repo"), Path("/home"), {}, now=NOW)
        self.assertEqual(state["status"], "unavailable")
        self.assertTrue(state["reason"])

    def test_collect_reports_ok_with_counts_when_configured(self):
        config = {"postgres": {"host": "db", "port": 5432, "dbname": "rt",
                               "user": "lar"}}
        state = rt_store.collect(
            Path("/repo"), Path("/home"), config, now=NOW,
            env={rt_store.PASSWORD_ENV_VAR: "secret"},
            connector=fake_connector(rows_by_query={
                "rt_persons": (1,), "rt_person_identifiers": (1,),
                "rt_snapshot_history": (0,)}))
        self.assertEqual(state["status"], "ok")
        self.assertEqual(state["persons"], 1)
        self.assertEqual(state["collected_at"], NOW.isoformat(timespec="seconds"))

    def test_collect_reports_a_declared_but_broken_block_as_unavailable(self):
        """A refusal path (R20): a real misconfiguration must not raise past
        the collector contract every other section relies on."""
        config = {"postgres": {"host": "db", "port": 5432, "dbname": "rt"}}
        state = rt_store.collect(Path("/repo"), Path("/home"), config, now=NOW,
                                 env={})
        self.assertEqual(state["status"], "unavailable")
        self.assertIn("'user'", state["reason"])


if __name__ == "__main__":
    unittest.main()
