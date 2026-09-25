"""
rt_store - the ONLY module in rt-observe that knows PostgreSQL exists.

Phase 1 of the journal-durable plan (docs/superpowers/todo/2026-09-24-rt-observe-
journal-durable.md). Persistence is an OPTIONAL layer, by construction: rt-observe's
own reason for being is standard-library-only with zero harness required, and a lab
member's fresh clone must render the same mirror matrix with no database installed
at all. So this module answers "is a store configured, and if so is it usable" and
degrades to a NullStore that does nothing rather than raising, whenever the layer is
simply absent.

Three states, and they are NOT the same thing:
  * `observe-config.json` declares no "postgres" block at all -> disabled BY DESIGN.
    NullStore, reason "not configured". This is the default shipped state and it is
    not an error (R8): most clones of this repository will never stand up a
    database, and the whole point of Phase 1 is that nothing regresses for them.
  * A "postgres" block IS declared but a required key is missing -> that block was
    an operator's deliberate intent to turn the layer on, so an incomplete one is a
    real misconfiguration and raises StoreError naming the missing key and this
    file (R3), never a silent NullStore.
  * The block is complete but the connection fails (driver absent, network down,
    bad credentials) -> StoreUnavailable, carrying the reason, caught by every
    caller and reported as an unavailable panel rather than crashing the dashboard.

The password is read from the environment (`RT_PG_PASSWORD`), never from the config
file (`.claude/rules/security.md`: never commit a secret). `psycopg` is imported
lazily, inside `PostgresStore.connect()`, so its absence costs nothing to every
other module in this skill that does not touch the database.
"""
import argparse
import io
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent

REQUIRED_KEYS = ("host", "port", "dbname", "user")
PASSWORD_ENV_VAR = "RT_PG_PASSWORD"

# The three tables Phase 2 asks for, at most. Mutable, relational, correctable -
# the opposite of the immutable audit stream, which lives in OpenObserve instead
# (rt_openobserve.py), never here (section 2.2 of the plan).
SCHEMA_STATEMENTS = [
    ("persons", """
        CREATE TABLE IF NOT EXISTS rt_persons (
            person_id   TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            email       TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """),
    ("person_identifiers", """
        CREATE TABLE IF NOT EXISTS rt_person_identifiers (
            identifier_id   TEXT PRIMARY KEY,
            person_id       TEXT NOT NULL REFERENCES rt_persons(person_id),
            kind            TEXT NOT NULL,
            value           TEXT NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (kind, value)
        )
    """),
    ("snapshot_history", """
        CREATE TABLE IF NOT EXISTS rt_snapshot_history (
            snapshot_id     BIGSERIAL PRIMARY KEY,
            person_id       TEXT NOT NULL REFERENCES rt_persons(person_id),
            container_id    TEXT,
            taken_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            summary         JSONB NOT NULL
        )
    """),
]

# kind values a person_identifier row may carry (R5: an enum-like literal comes
# from one table).
IDENTIFIER_KINDS = ("system_account", "container", "openobserve_org")


class StoreError(RuntimeError):
    """A declared postgres block is incomplete or malformed. Named, never
    defaulted (R3)."""


class StoreUnavailable(RuntimeError):
    """A complete configuration exists but the store could not be reached (driver
    missing, connection refused, authentication failed). Caught by every caller
    and reported as an unavailable panel, never raised to the dashboard."""


class NullStore:
    """The zero-service default. Every method answers 'not configured' rather
    than raising, so a caller that forgets to check `available` still gets a
    clear reason instead of an AttributeError."""

    available = False

    def __init__(self, reason):
        self.reason = reason

    def counts(self):
        return {"status": "unavailable", "reason": self.reason}

    def people(self, limit=None):
        return {"status": "unavailable", "reason": self.reason}

    def migrate(self, dry_run=True):
        raise StoreUnavailable(self.reason)

    def close(self):
        pass


class PostgresStore:
    """
    --------------------------------------------------------------------------
    Purpose:
        The one class that imports psycopg, and only when instantiated.

    Inputs:
        values (dict): {"host", "port", "dbname", "user", "password"}
        connector (callable): psycopg.connect look-alike, injected for tests so
                              the whole suite runs with no real database (R21)

    Outputs:
        PostgresStore
    --------------------------------------------------------------------------
    """

    available = True

    def __init__(self, values, connector=None):
        self.values = dict(values)
        self._connector = connector
        self._conn = None

    def _connect(self):
        if self._conn is not None:
            return self._conn
        connect = self._connector
        if connect is None:
            try:
                import psycopg
            except ImportError as exc:
                raise StoreUnavailable(
                    "the postgres block in observe-config.json is complete, but "
                    "the psycopg driver is not installed in this interpreter: %s"
                    % exc)
            connect = psycopg.connect
        try:
            self._conn = connect(
                host=self.values["host"], port=self.values["port"],
                dbname=self.values["dbname"], user=self.values["user"],
                password=self.values.get("password"),
                connect_timeout=self.values.get("connect_timeout_s", 5))
        except Exception as exc:                          # noqa: BLE001
            # Any driver-raised exception (OperationalError and friends) becomes
            # one typed failure the rest of this skill already knows how to
            # render: unavailable, with a reason, never a crash (R8).
            raise StoreUnavailable(
                "could not connect to postgres://%s@%s:%s/%s: %s"
                % (self.values["user"], self.values["host"],
                   self.values["port"], self.values["dbname"], exc))
        return self._conn

    def close(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:                             # noqa: BLE001
                pass
            self._conn = None

    def counts(self):
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM rt_persons")
                persons = cur.fetchone()[0]
                cur.execute("SELECT count(*) FROM rt_person_identifiers")
                identifiers = cur.fetchone()[0]
                cur.execute("SELECT count(*) FROM rt_snapshot_history")
                snapshots = cur.fetchone()[0]
        except Exception as exc:                          # noqa: BLE001
            return {"status": "unavailable",
                    "reason": "the identity tables could not be read: %s: %s. "
                              "Has `rt_store.py --migrate --yes` been run?"
                              % (type(exc).__name__, exc)}
        return {"status": "ok", "persons": persons,
                "identifiers": identifiers, "snapshots": snapshots}

    def people(self, limit=None):
        conn = self._connect()
        query = ("SELECT person_id, display_name, email FROM rt_persons "
                 "ORDER BY display_name")
        if limit:
            query += " LIMIT %d" % int(limit)
        try:
            with conn.cursor() as cur:
                cur.execute(query)
                rows = cur.fetchall()
        except Exception as exc:                          # noqa: BLE001
            return {"status": "unavailable",
                    "reason": "rt_persons could not be read: %s: %s"
                              % (type(exc).__name__, exc)}
        return {"status": "ok",
                "people": [{"person_id": r[0], "display_name": r[1],
                           "email": r[2]} for r in rows]}

    def migrate(self, dry_run=True):
        """
        ----------------------------------------------------------------------
        Purpose:
            Create the three tables if absent. Idempotent (CREATE TABLE IF NOT
            EXISTS), dry-run by default (R16), machine-readable report (R17).

        Inputs:
            dry_run (bool): when true, executes nothing

        Outputs:
            report (dict): {"applied", "statements": [{"table", "sql"}]}
        ----------------------------------------------------------------------
        """
        report = {"applied": not dry_run,
                  "statements": [{"table": name, "sql": " ".join(sql.split())}
                                for name, sql in SCHEMA_STATEMENTS]}
        if dry_run:
            return report
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                for _, sql in SCHEMA_STATEMENTS:
                    cur.execute(sql)
            conn.commit()
        except Exception as exc:                          # noqa: BLE001
            report["applied"] = False
            report["error"] = "%s: %s" % (type(exc).__name__, exc)
        return report


def _required(config_postgres, key, path):
    if key not in config_postgres or config_postgres[key] in (None, ""):
        raise StoreError(
            "observe-config.json declares a 'postgres' block but it has no "
            "'%s'. A block once declared is a deliberate intent to enable this "
            "layer, so it must be complete (%s)." % (key, path))
    return config_postgres[key]


def get_store(config, env=None, connector=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the optional 'postgres' block and return the right store: a
        NullStore when the layer is not configured at all, a PostgresStore when
        it is, raising StoreError only for a block that is present but broken.

    Inputs:
        config (dict): the parsed observe-config.json
        env (Mapping): os.environ look-alike, injected for tests (R21)
        connector (callable): psycopg.connect look-alike, injected for tests

    Outputs:
        store (NullStore or PostgresStore)
    --------------------------------------------------------------------------
    """
    env = env if env is not None else os.environ
    postgres = config.get("postgres")
    if not postgres:
        return NullStore(
            "observe-config.json declares no 'postgres' block; the identity "
            "and audit-mapping layer is optional and disabled by design on "
            "this clone")
    values = {key: _required(postgres, key, "observe-config.json:postgres")
              for key in REQUIRED_KEYS}
    password = env.get(PASSWORD_ENV_VAR)
    if password is None:
        raise StoreError(
            "observe-config.json declares a 'postgres' block, but the "
            "%s environment variable is not set. The password never lives in "
            "the config file (.claude/rules/security.md)." % PASSWORD_ENV_VAR)
    values["password"] = password
    values["connect_timeout_s"] = postgres.get("connect_timeout_s", 5)
    return PostgresStore(values, connector=connector)


def collect(repo_root, home, config, now=None, env=None, connector=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        The rt-observe collector contract for the identity/audit-mapping panel:
        fn(...) -> dict, never raising, always naming its own unavailability.

    Inputs:
        repo_root, home (Path): injected roots, unused here but kept for the
                                same signature every other collector carries
        config (dict): parsed observe-config.json
        now (datetime): injected clock (R19)
        env, connector: injected seams for the offline suite (R21)

    Outputs:
        state (dict)
    --------------------------------------------------------------------------
    """
    try:
        store = get_store(config, env=env, connector=connector)
    except StoreError as exc:
        return {"status": "unavailable", "reason": str(exc)}
    try:
        counts = store.counts()
    except StoreUnavailable as exc:
        return {"status": "unavailable", "reason": str(exc)}
    finally:
        store.close()
    if counts.get("status") != "ok":
        return counts
    stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    counts["collected_at"] = stamp
    return counts


def _load_config():
    path = SKILL_ROOT / "observe-config.json"
    with io.open(path, encoding="utf-8-sig") as handle:
        return json.loads(handle.read())


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="The optional identity/audit-mapping store (PostgreSQL). "
                    "Absent 'postgres' config is a supported, non-error state.")
    parser.add_argument("--check", action="store_true",
                        help="report whether a store is configured and reachable")
    parser.add_argument("--migrate", action="store_true",
                        help="create the three tables if absent")
    parser.add_argument("--yes", action="store_true",
                        help="apply the migration (default is --dry-run, R16)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    config = _load_config()
    try:
        store = get_store(config)
    except StoreError as exc:
        sys.stderr.write("%s\n" % exc)
        return 2

    if args.migrate:
        try:
            report = store.migrate(dry_run=not args.yes)
        except StoreUnavailable as exc:
            sys.stderr.write("%s\n" % exc)
            return 1
        if args.json:
            json.dump(report, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            sys.stdout.write("applied=%s\n" % report["applied"])
            for stmt in report["statements"]:
                sys.stdout.write("  %s\n" % stmt["table"])
        return 0 if report.get("applied") or not args.yes else 1

    # --check, or no verb at all
    if not store.available:
        sys.stdout.write("store: not configured (%s)\n" % store.reason)
        return 0
    try:
        counts = store.counts()
    except StoreUnavailable as exc:
        sys.stderr.write("%s\n" % exc)
        return 1
    finally:
        store.close()
    if args.json:
        json.dump(counts, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write("store: %s\n" % counts)
    return 0 if counts.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
