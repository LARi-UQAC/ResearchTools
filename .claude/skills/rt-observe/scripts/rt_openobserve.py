"""
rt_openobserve - the ONLY module that knows OpenObserve exists.

Phase 2/3 of the journal-durable plan. OpenObserve holds the IMMUTABLE half of the
new journal: agent traces, tool calls, and the rt-observe action-audit log (section
2.2 of the plan). PostgreSQL (rt_store.py) holds the mutable half - identity and
account-to-container mapping - because OpenObserve's own documentation states data
is immutable once ingested and only a whole retention period can be dropped, which
is the wrong shape for a correctable identity table but the right one for a log.

Standard library only (urllib), matching rt-observe's own zero-dependency promise:
the persistence layer is optional, so nothing here may require `requests` or any
package the rest of the skill does not already need. Every HTTP call carries an
explicit timeout from observe-config.json (R10) and never raises past its own
function: every public function returns a typed (ok, detail) or a dict carrying
its own status, exactly like every other collector in this skill (R8).

Credentials (`RT_OO_USER` / `RT_OO_PASSWORD`) come from the environment, never from
observe-config.json (security.md). Redaction happens BEFORE a record is built into
a request body, never after: `rt_redact.home_tilde` is applied recursively to every
string value, so an account name never leaves the machine (Phase 2's explicit
confidentiality requirement).

NOT VERIFIED THIS SESSION (2026-09-24): the plan's section 2.4 asks that the
official OpenObserve/Claude-Code integration page, and whether the harness's native
OTLP exporter (`CLAUDE_CODE_ENABLE_TELEMETRY=1`, `OTEL_EXPORTER_OTLP_ENDPOINT`)
reaches OpenObserve directly, both be checked by a live fetch before writing a
collector. That check needs a network fetch this session could not perform without
delegating to a subagent, which the operator's instructions for this session
forbade. So this module implements OpenObserve's documented plain JSON bulk-
ingestion endpoint (`POST /api/{org}/{stream}/_json`) and its SQL search endpoint
(`POST /api/{org}/_search`) rather than the OTLP protocol, as the simpler path that
needs no protobuf dependency - a deliberate substitution, stated rather than
silent (R8), and recorded as an open item for the operator to verify against a
running instance.

Known limitation, not worked around (Phase, section 2.3, pitfall 2): the open-
source edition of OpenObserve has no per-role access control, so every account that
can reach the ingestion/search endpoints can read every stream. Acceptable among
five lab colleagues on one machine; not a boundary this module can add.
"""
import io
import json
import os
import sys
import urllib.error
import urllib.request
from base64 import b64encode
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rt_redact import home_tilde  # noqa: E402

SKILL_ROOT = Path(__file__).resolve().parent.parent

USER_ENV_VAR = "RT_OO_USER"
PASSWORD_ENV_VAR = "RT_OO_PASSWORD"
REQUIRED_KEYS = ("base_url", "org")

# The plan's measured pitfall 1: OpenObserve's own default for
# ZO_INGEST_ALLOWED_UPTO is 5 hours, and an event older than that is dropped in
# silence by the server. This module cannot change a server-side environment
# variable; it can only warn, loudly, in the operator-facing text (R13: a
# measured number carries its date and what measured it - here, the plan's own
# section 2.3, verified against the OpenObserve documentation on 2026-09-24).
INGEST_WINDOW_HOURS_DEFAULT = 5
INGEST_WINDOW_ENV_VAR = "ZO_INGEST_ALLOWED_UPTO"


class OpenObserveError(RuntimeError):
    """A declared 'openobserve' block is incomplete. Named, never defaulted (R3)."""


def _redact(value, home):
    """Recursively apply home_tilde to every string in a JSON-shaped value, so a
    payload is redacted BEFORE it is serialized into a request body (Phase 2's
    confidentiality requirement: before the send, not after)."""
    if isinstance(value, str):
        return home_tilde(value, home)
    if isinstance(value, dict):
        return {k: _redact(v, home) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, home) for v in value]
    return value


def load_oo_config(config, env=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the optional 'openobserve' block. Absence is disabled-by-design
        (None, None); presence with a missing key is OpenObserveError (R3).

    Inputs:
        config (dict): parsed observe-config.json
        env (Mapping): os.environ look-alike, injected for tests (R21)

    Outputs:
        values (dict) or None, reason (str) or None
    --------------------------------------------------------------------------
    """
    env = env if env is not None else os.environ
    block = config.get("openobserve")
    if not block:
        return None, ("observe-config.json declares no 'openobserve' block; "
                      "the trace/audit journal is optional and disabled by "
                      "design on this clone")
    values = {}
    for key in REQUIRED_KEYS:
        if key not in block or not block[key]:
            raise OpenObserveError(
                "observe-config.json declares an 'openobserve' block but it "
                "has no '%s'. A block once declared is a deliberate intent to "
                "enable this layer, so it must be complete." % key)
        values[key] = block[key]
    values["user"] = env.get(USER_ENV_VAR)
    values["password"] = env.get(PASSWORD_ENV_VAR)
    if values["user"] is None or values["password"] is None:
        raise OpenObserveError(
            "observe-config.json declares an 'openobserve' block, but %s and "
            "%s are not both set in the environment. Credentials never live "
            "in the config file (.claude/rules/security.md)."
            % (USER_ENV_VAR, PASSWORD_ENV_VAR))
    values["streams"] = block.get("streams", {"audit": "rt_audit",
                                              "traces": "rt_traces"})
    return values, None


def _auth_header(values):
    token = b64encode(("%s:%s" % (values["user"], values["password"]))
                      .encode("utf-8")).decode("ascii")
    return "Basic %s" % token


def _post(url, values, body_bytes, timeout_s, opener=None):
    request = urllib.request.Request(
        url, data=body_bytes, method="POST",
        headers={"Content-Type": "application/json",
                "Authorization": _auth_header(values)})
    opener = opener or urllib.request.urlopen
    try:
        with opener(request, timeout=timeout_s) as response:
            return True, response.read().decode("utf-8", errors="replace"), None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[-300:]
        return False, None, "%s answered HTTP %s: %s" % (url, exc.code, detail)
    except urllib.error.URLError as exc:
        return False, None, "%s could not be reached: %s" % (url, exc.reason)
    except OSError as exc:
        return False, None, "%s could not be reached: %s" % (url, exc)


def send_json(values, stream_key, records, home, timeout_s, opener=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Ingest one or more records into an OpenObserve stream over its plain
        JSON bulk endpoint. Every record is redacted before it is serialized -
        never after - so an account name never reaches the wire.

    Inputs:
        values (dict): from load_oo_config
        stream_key (str): "audit" or "traces", looked up in values["streams"]
        records (list[dict]): the records to send
        home (Path): the home directory to redact (R21, injected)
        timeout_s (float): explicit timeout (R10)
        opener (callable): urllib.request.urlopen look-alike, injected for tests

    Outputs:
        ok (bool), reason (str or None)
    --------------------------------------------------------------------------
    """
    stream = values["streams"].get(stream_key)
    if not stream:
        return False, ("no stream is configured for %r under "
                       "openobserve.streams" % stream_key)
    redacted = [_redact(r, home) for r in records]
    url = "%s/api/%s/%s/_json" % (values["base_url"].rstrip("/"),
                                  values["org"], stream)
    body = json.dumps(redacted, ensure_ascii=False).encode("utf-8")
    ok, _, reason = _post(url, values, body, timeout_s, opener=opener)
    return ok, reason


def search(values, stream_key, sql, timeout_s, page_size, max_pages,
          opener=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Read a stream back with a bounded number of pages (R10): a panel read
        standing up does not need a full history, and an unbounded read is how
        a collector hangs on a large retained stream.

    Inputs:
        values (dict): from load_oo_config
        stream_key (str): "audit" or "traces"
        sql (str): the SQL query body OpenObserve's _search API accepts
        timeout_s (float): explicit timeout per request (R10)
        page_size, max_pages (int): pagination bounds (R10)
        opener (callable): injected for tests

    Outputs:
        ok (bool), rows (list) or None, reason (str) or None, truncated (bool)
    --------------------------------------------------------------------------
    """
    stream = values["streams"].get(stream_key)
    if not stream:
        return False, None, (
            "no stream is configured for %r under openobserve.streams"
            % stream_key), False
    url = "%s/api/%s/_search" % (values["base_url"].rstrip("/"), values["org"])
    rows = []
    truncated = False
    for page in range(max_pages):
        body = json.dumps({
            "query": {"sql": sql, "from": page * page_size, "size": page_size}
        }).encode("utf-8")
        ok, text, reason = _post(url, values, body, timeout_s, opener=opener)
        if not ok:
            return False, None, reason, False
        try:
            parsed = json.loads(text)
        except ValueError as exc:
            return False, None, ("%s returned a body that does not parse as "
                                 "JSON: %s" % (url, exc)), False
        hits = parsed.get("hits", [])
        rows.extend(hits)
        if len(hits) < page_size:
            break
        if page == max_pages - 1:
            truncated = True
    return True, rows, None, truncated


def remind_ingest_window():
    """The operator-facing note for the plan's pitfall 1: what to check and set
    before replaying old transcripts, since this module cannot read or change a
    remote server's own environment."""
    return (
        "OpenObserve's default ZO_INGEST_ALLOWED_UPTO is %d hours; any event "
        "older than that is DROPPED IN SILENCE on ingest, no error, no partial "
        "count. Before replaying historical transcripts, raise %s on the "
        "OpenObserve process and verify by reading one old record back with "
        "search() afterward (R9) - never trust a 200 response on send_json as "
        "proof the record landed."
        % (INGEST_WINDOW_HOURS_DEFAULT, INGEST_WINDOW_ENV_VAR))


def verify_ingest_window(values, stream_key, marker_record, home, timeout_s,
                         search_timeout_s, page_size, max_pages, opener=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        R9: verify an old-timestamped record was actually ingested by reading
        it back, rather than trusting send_json's HTTP 200. Operator-run, not
        part of the automatic offline suite: it needs a live OpenObserve.

    Inputs:
        values (dict): from load_oo_config
        stream_key (str): the stream the marker was sent to
        marker_record (dict): must carry a unique "_rt_marker" field
        home (Path): for redaction (R21)
        timeout_s, search_timeout_s (float): explicit timeouts (R10)
        page_size, max_pages (int): search pagination bounds

    Outputs:
        verified (bool), detail (str)
    --------------------------------------------------------------------------
    """
    marker = marker_record.get("_rt_marker")
    if not marker:
        return False, "marker_record carries no '_rt_marker' field to look for"
    ok, reason = send_json(values, stream_key, [marker_record], home,
                           timeout_s, opener=opener)
    if not ok:
        return False, "send failed, so nothing to verify: %s" % reason
    sql = "SELECT * WHERE _rt_marker = '%s'" % marker
    ok, rows, reason, _ = search(values, stream_key, sql, search_timeout_s,
                                 page_size, max_pages, opener=opener)
    if not ok:
        return False, "the marker could not be read back: %s" % reason
    if not rows:
        return False, ("the marker was accepted on send but is absent on "
                       "read-back - most likely %s (%s)"
                       % (remind_ingest_window(), sql))
    return True, "marker found on read-back"
