"""
wp_common.py - shared helpers and the bounded HTTP client for wp-portfolio-sync.

Stage: imported by cihr_cv.py, render.py, verify_titles.py, push_wp.py,
discover.py and preview.py. Holds no module-level `import requests`: the
package is imported lazily, only where a real network call is about to be
made, so the offline suite never needs it installed (R18: a local copy of
configure_streams, same intent as extract-statistic's, kept separate
because each skill's import boundary differs).
"""
import html
import json
import os
import re
import sys
import time
from pathlib import Path

from wp_errors import WpRefusal, WpSyncError, WpWriteUnconfirmed
from wp_config import CONFIG_NAME, config_value
from wp_paths import contained_path


def configure_streams():
    """
    --------------------------------------------------------------------------
    Purpose:
        Make stdout/stderr able to carry any glyph a mapping.yaml or a CIHR
        export uses, so printing a report cannot fail on one character.

    Inputs:
        none

    Outputs:
        none. Never raises: a stream without .reconfigure is skipped, and a
        reconfigure that itself fails degrades to errors="replace" alone,
        then to doing nothing (R8: never a silent crash over output hygiene).
    --------------------------------------------------------------------------
    """
    for stream in (sys.stdout, sys.stderr):
        if not hasattr(stream, "reconfigure"):
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError, LookupError):
            try:
                stream.reconfigure(errors="replace")
            except (ValueError, OSError):
                pass


def norm_ws(text):
    """
    --------------------------------------------------------------------------
    Purpose:
        Collapse any run of whitespace to a single space and strip the ends.

    Inputs:
        text: any value, or None.

    Outputs:
        normalised (str): "" for None, else the collapsed, stripped text.
    --------------------------------------------------------------------------
    """
    if text is None:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def parse_year(datestr):
    """
    --------------------------------------------------------------------------
    Purpose:
        Extract a 19xx/20xx year from a date string such as "2025/5",
        "2017-08-07" or "2025".

    Inputs:
        datestr (str): the raw date field from a CIHR record, or "".

    Outputs:
        year (int or None): the first 4-digit year found, or None when the
        input is empty or carries no such year.
    --------------------------------------------------------------------------
    """
    if not datestr:
        return None
    match = re.search(r"(19|20)\d{2}", datestr)
    return int(match.group(0)) if match else None


def fmt_ym(datestr):
    """
    --------------------------------------------------------------------------
    Purpose:
        Format a CIHR date as month/year, e.g. "2025/5" -> "05/2025".

    Inputs:
        datestr (str): the raw date field.

    Outputs:
        formatted (str): "MM/YYYY" when a month is found, else the bare year,
        else the original string unchanged, else "" for an empty input.
    --------------------------------------------------------------------------
    """
    if not datestr:
        return ""
    match = re.match(r"\s*(\d{4})[/-](\d{1,2})", datestr)
    if match:
        return "%02d/%s" % (int(match.group(2)), match.group(1))
    year = parse_year(datestr)
    return str(year) if year else datestr


def fmt_amount(val):
    """
    --------------------------------------------------------------------------
    Purpose:
        Format a funding amount with space thousands separators and a
        trailing dollar sign, e.g. "185000" -> "185 000 $".

    Inputs:
        val: a numeric string, number, or anything unparsable.

    Outputs:
        formatted (str): the formatted amount, or str(val) unchanged when it
        cannot be parsed as a number.
    --------------------------------------------------------------------------
    """
    try:
        number = int(float(str(val).replace(" ", "").replace(",", ".")))
    except (ValueError, TypeError):
        return str(val)
    return "{:,}".format(number).replace(",", " ") + " $"


def atomic_write_text(path, text, encoding="utf-8"):
    """
    --------------------------------------------------------------------------
    Purpose:
        Write text to path atomically - a reader of path never observes a
        partially written file (L1, PR #50 review). A sibling `.tmp` file
        is written in full, then renamed over path in one filesystem call.

    Inputs:
        path (Path or str): the destination file.
        text (str): the full content to write.
        encoding (str): the text encoding (default utf-8).

    Outputs:
        none. path exists with exactly text in it, or the write raised
        before path was ever touched.
    --------------------------------------------------------------------------
    """
    path = Path(path)
    tmp_path = path.with_name(path.name + ".tmp")
    with open(tmp_path, "w", encoding=encoding) as handle:
        handle.write(text)
    os.replace(tmp_path, path)


def error_report(message, exit_code):
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the one machine-readable shape every CLI script in this
        skill prints under --json on a refusal or a failure (L7, PR #50
        review): before this, --json only ever emitted a report on
        success, so a caller scripting against it saw nothing at all on
        the exact runs it most needed to detect (R17).

    Inputs:
        message (str): the human-readable error text (REFUS:/ERREUR:
        without that prefix).
        exit_code (int): the exit code this run is about to return.

    Outputs:
        report (dict): {"error": message, "exit_code": exit_code}.
    --------------------------------------------------------------------------
    """
    return {"error": message, "exit_code": exit_code}


def split_recent_history(items, date_key, ref_year, window):
    """
    --------------------------------------------------------------------------
    Purpose:
        Split a list of records into (recent, history) under the N-year
        rule: a record is recent when it has no end date, or its end year is
        >= ref_year - window + 1 (D10: ref_year and window carry no default,
        since a silently stale default is the defect this fixes).

    Inputs:
        items (list[dict]): records to split.
        date_key (str): the field holding the end date, e.g. "fin".
        ref_year (int): the reference year the window is counted back from.
        window (int): the window size in years.

    Outputs:
        (recent, history) (tuple[list, list]): the two partitions, in their
        original relative order.
    --------------------------------------------------------------------------
    """
    recent, history = [], []
    for item in items:
        year = parse_year(item.get(date_key) or "")
        if year is None or year >= ref_year - window + 1:
            recent.append(item)
        else:
            history.append(item)
    return recent, history


def get_path(data, dotted):
    """
    --------------------------------------------------------------------------
    Purpose:
        Walk a dotted path (e.g. "cv.experience") into nested dicts.

    Inputs:
        data (dict): the root document.
        dotted (str): a dot-separated key path.

    Outputs:
        node: the value found at the path.

    Raises:
        KeyError: a path segment is not present, naming the full path and
        the segment it got stuck at.
    --------------------------------------------------------------------------
    """
    node = data
    for part in dotted.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            raise KeyError("path %r not found (stuck at %r)" % (dotted, part))
    return node


def to_html(node, _depth=0):
    """
    --------------------------------------------------------------------------
    Purpose:
        Render an arbitrary JSON-shaped node (dict/list/scalar) as generic
        HTML, with dict keys shown in <strong>.

    Inputs:
        node: a dict, list, string, None, or other scalar.
        _depth (int): recursion depth, for internal use only.

    Outputs:
        html_text (str): the rendered fragment, "" for None.
    --------------------------------------------------------------------------
    """
    escape = html.escape
    if node is None:
        return ""
    if isinstance(node, str):
        return "<p>%s</p>" % escape(node)
    if isinstance(node, list):
        items = "".join("<li>%s</li>" % to_html(item, _depth + 1) for item in node)
        return "<ul>%s</ul>" % items
    if isinstance(node, dict):
        parts = []
        for key, value in node.items():
            if key == "_text":
                parts.append("<p>%s</p>" % escape(str(value)))
            elif isinstance(value, (dict, list)):
                parts.append("<p><strong>%s</strong></p>%s" % (escape(key), to_html(value, _depth + 1)))
            else:
                parts.append("<p><strong>%s:</strong> %s</p>" % (escape(key), escape(str(value))))
        return "".join(parts)
    return "<p>%s</p>" % escape(str(node))


def render_block(node, heading=""):
    """
    --------------------------------------------------------------------------
    Purpose:
        Render a node as HTML with an optional leading <h3> heading.

    Inputs:
        node: passed through to to_html.
        heading (str): an optional heading, escaped.

    Outputs:
        html_text (str): the heading (if any) followed by to_html(node).
    --------------------------------------------------------------------------
    """
    heading_html = "<h3>%s</h3>" % html.escape(heading) if heading else ""
    return heading_html + to_html(node)


def _inline(text):
    """
    --------------------------------------------------------------------------
    Purpose:
        Apply inline Markdown (bold, links) to one already-escaped line of
        md_to_html output.

    Inputs:
        text (str): one line of Markdown, not yet escaped.

    Outputs:
        html_text (str): the escaped text with **bold** and [label](url)
        converted to <strong>/<a>.
    --------------------------------------------------------------------------
    """
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', escaped)
    return escaped


def md_to_html(md):
    """
    --------------------------------------------------------------------------
    Purpose:
        Convert a minimal Markdown subset (headings, lists, bold, links,
        pipe tables) to HTML, for a config/historique/*.md static file.

    Inputs:
        md (str): the Markdown source.

    Outputs:
        html_text (str): the rendered HTML, one block per source line/group.
    --------------------------------------------------------------------------
    """
    out = []
    in_list = False
    in_table = False
    for raw in md.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            if in_list:
                out.append("</ul>")
                in_list = False
            if in_table:
                out.append("</tbody></table>")
                in_table = False
            continue
        if stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if not in_table:
                out.append("<table><tbody>")
                in_table = True
            if all(set(c) <= set("-: ") for c in cells):
                continue
            out.append("<tr>" + "".join("<td>%s</td>" % _inline(c) for c in cells) + "</tr>")
            continue
        if in_table:
            out.append("</tbody></table>")
            in_table = False
        if stripped.startswith("### "):
            out.append("<h4>%s</h4>" % _inline(stripped[4:]))
        elif stripped.startswith("## "):
            out.append("<h3>%s</h3>" % _inline(stripped[3:]))
        elif stripped.startswith("# "):
            out.append("<h2>%s</h2>" % _inline(stripped[2:]))
        elif stripped.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append("<li>%s</li>" % _inline(stripped[2:]))
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append("<p>%s</p>" % _inline(stripped))
    if in_list:
        out.append("</ul>")
    if in_table:
        out.append("</tbody></table>")
    return "\n".join(out)


def site_base(mapping, environ, cli_site=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve the single WordPress site URL from among mapping.yaml,
        --site and WP_BASE, refusing a disagreement (D9: mapping.yaml's
        `site` is the one source of truth; an environment value that
        disagrees is a refusal, not a silent override).

    Inputs:
        mapping (dict or None): the loaded mapping.yaml, or None.
        environ (Mapping[str, str]): the process environment (or a fake).
        cli_site (str or None): an explicit --site CLI argument.

    Outputs:
        url (str): the agreed site URL, without a trailing slash.

    Raises:
        WpRefusal: no source gives a URL; two sources disagree, naming each
        source and its value; or the URL does not start with "https://".
    --------------------------------------------------------------------------
    """
    candidates = {}
    if mapping and mapping.get("site"):
        candidates["mapping.yaml"] = str(mapping["site"]).rstrip("/")
    if cli_site:
        candidates["--site"] = str(cli_site).rstrip("/")
    env_site = environ.get("WP_BASE")
    if env_site:
        candidates["WP_BASE"] = str(env_site).rstrip("/")
    if not candidates:
        raise WpRefusal("no site URL given: set mapping.yaml's site, --site, or WP_BASE")
    distinct = set(candidates.values())
    if len(distinct) > 1:
        detail = ", ".join("%s=%s" % (key, value) for key, value in candidates.items())
        raise WpRefusal("site URL disagreement: %s" % detail)
    url = next(iter(distinct))
    if not url.startswith("https://"):
        raise WpRefusal("site URL must start with https://: %s" % url)
    return url


class WpClient:
    """
    --------------------------------------------------------------------------
    Purpose:
        A bounded HTTP client over a requests.Session-like object: GET
        retries on a retryable exception or a 5xx status, PUT never retries
        (D5).

    Inputs:
        session: a requests.Session or a fake with .get/.put(url, ..., timeout=).
        base_url (str): the site's REST API base, no trailing slash.
        timeout_s (float): per-request timeout in seconds.
        get_retries (int): extra GET attempts beyond the first.
        retry_backoff_s (float): seconds slept before each GET retry (never
        before the first attempt); 0 sleeps nothing (R0, from config).
        retryable (tuple[type, ...] or None): exception types to retry on;
        None resolves lazily to requests' ConnectionError/Timeout.

    Outputs:
        none (state object).
    --------------------------------------------------------------------------
    """

    def __init__(self, session, base_url, timeout_s, get_retries, retry_backoff_s=0, retryable=None):
        self.session = session
        self.base_url = base_url
        self.timeout_s = timeout_s
        self.get_retries = get_retries
        self.retry_backoff_s = retry_backoff_s
        self._retryable = retryable

    @property
    def retryable(self):
        """
        --------------------------------------------------------------------------
        Purpose:
            Resolve and cache the retryable exception tuple, importing
            requests only the first time this is actually needed.

        Inputs:
            none

        Outputs:
            retryable (tuple[type, ...]): the given tuple, or
            (requests.exceptions.ConnectionError, requests.exceptions.Timeout).
        --------------------------------------------------------------------------
        """
        if self._retryable is None:
            import requests

            self._retryable = (requests.exceptions.ConnectionError, requests.exceptions.Timeout)
        return self._retryable

    def get_json(self, route, params):
        """
        --------------------------------------------------------------------------
        Purpose:
            GET route with up to 1 + get_retries attempts, retrying on a
            retryable exception or a 5xx status.

        Inputs:
            route (str): the REST route, appended to base_url.
            params (dict): query parameters.

        Outputs:
            body: the parsed JSON response body.

        Raises:
            WpSyncError: a 401 (naming WP_APP_USER/WP_APP_PASSWORD), any
            other 4xx but 429 (naming the status), a non-JSON body, or
            attempts exhausted (naming the route and the last cause). A 429
            (rate limited) is retried like a 5xx rather than raised.
        --------------------------------------------------------------------------
        """
        last_exc = None
        attempts = 1 + self.get_retries
        for attempt in range(attempts):
            if attempt > 0 and self.retry_backoff_s:
                time.sleep(self.retry_backoff_s)
            try:
                response = self.session.get(self.base_url + route, params=params, timeout=self.timeout_s)
            except self.retryable as exc:
                last_exc = exc
                continue
            if response.status_code == 401:
                raise WpSyncError(
                    "401 Unauthorized for %s - check WP_APP_USER/WP_APP_PASSWORD" % route,
                    status_code=401,
                )
            if response.status_code == 429 or response.status_code >= 500:
                last_exc = WpSyncError("HTTP %d for %s" % (response.status_code, route), status_code=response.status_code)
                continue
            if response.status_code >= 400:
                raise WpSyncError("HTTP %d for %s" % (response.status_code, route), status_code=response.status_code)
            try:
                return response.json()
            except ValueError as exc:
                raise WpSyncError("response body for %s is not JSON" % route) from exc
        raise WpSyncError("exhausted retries for %s: %s" % (route, last_exc))

    def put_json(self, route, payload):
        """
        --------------------------------------------------------------------------
        Purpose:
            PUT payload to route exactly once; PUT is never retried (D5).

        Inputs:
            route (str): the REST route, appended to base_url.
            payload (dict): the JSON body to send.

        Outputs:
            (status_code, text) (tuple[int, str]): the raw response.

        Raises:
            WpWriteUnconfirmed: a retryable exception occurred - the write's
            outcome is unknown, not necessarily a failure.
        --------------------------------------------------------------------------
        """
        try:
            response = self.session.put(self.base_url + route, json=payload, timeout=self.timeout_s)
        except self.retryable as exc:
            raise WpWriteUnconfirmed(str(exc)) from exc
        return response.status_code, response.text


def client_from_config(session, base_url, config):
    """
    --------------------------------------------------------------------------
    Purpose:
        Build a WpClient reading its timeout and retry count from a loaded
        wp-sync-config.json document.

    Inputs:
        session: a requests.Session or a fake.
        base_url (str): the site's REST API base.
        config (dict): the document returned by wp_config.load_config.

    Outputs:
        client (WpClient): configured from http.timeout_s, http.get_retries
        and http.retry_backoff_s.
    --------------------------------------------------------------------------
    """
    timeout_s = config_value(config, "http.timeout_s", CONFIG_NAME)
    get_retries = config_value(config, "http.get_retries", CONFIG_NAME)
    retry_backoff_s = config_value(config, "http.retry_backoff_s", CONFIG_NAME)
    return WpClient(session, base_url, timeout_s, get_retries, retry_backoff_s=retry_backoff_s)


def make_session(data_dir, environ, session_factory=None, require_nonce=False):
    """
    --------------------------------------------------------------------------
    Purpose:
        Build an authenticated session: an Application Password when both
        WP_APP_USER and WP_APP_PASSWORD are set, else a cookie file.

    Inputs:
        data_dir (Path): the resolved researcher data folder.
        environ (Mapping[str, str]): the process environment (or a fake).
        session_factory (callable or None): when given, called with no
        arguments to build the session object (tests inject a fake); when
        None, requests is imported here, and only here, and
        requests.Session() is used.
        require_nonce (bool): True for a caller that will PUT (push_wp.py);
        when cookie authentication is used with no WP_NONCE set, a read-only
        caller (discover.py) is let through unchanged (a nonce is only
        checked by WordPress on a write), but a write-capable caller is
        refused up front rather than failing later on each PUT.

    Outputs:
        session: the built, authenticated session object. Under cookie
        authentication, session.headers["X-WP-Nonce"] is set from WP_NONCE
        when that variable is present, whatever require_nonce is.

    Raises:
        WpRefusal: the 'requests' package is not installed (naming the pip
        command); WP_COOKIES names a path escaping data_dir (R24); the
        cookie file is malformed (named by path only, never by content);
        cookie authentication is used with require_nonce=True and no
        WP_NONCE is set; or no credentials are configured at all (naming
        the two environment variables and the cookie path). No message
        ever contains a password, a cookie value, or a nonce.
    --------------------------------------------------------------------------
    """
    if session_factory is not None:
        session = session_factory()
    else:
        try:
            import requests
        except ImportError as exc:
            raise WpRefusal(
                "the 'requests' package is not installed: run "
                "'pip install -r requirements.txt' in this skill's scripts/ directory"
            ) from exc

        session = requests.Session()

    user = environ.get("WP_APP_USER")
    password = environ.get("WP_APP_PASSWORD")
    if user and password:
        session.auth = (user, password)
        return session

    cookie_path_raw = environ.get("WP_COOKIES")
    if cookie_path_raw:
        cookie_file = contained_path(data_dir, cookie_path_raw)
    else:
        cookie_file = Path(data_dir) / "config" / "cookies.json"
    if cookie_file.is_file():
        try:
            with open(cookie_file, "r", encoding="utf-8") as handle:
                entries = json.load(handle)
            if not isinstance(entries, list):
                raise ValueError("cookie file is not a JSON list")
            for entry in entries:
                name = entry["name"]
                value = entry["value"]
                session.cookies.set(name, value, domain=entry.get("domain", ""), path=entry.get("path", "/"))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise WpRefusal("cookie file is malformed: %s" % cookie_file) from exc

        nonce = environ.get("WP_NONCE")
        if nonce:
            session.headers["X-WP-Nonce"] = nonce
        elif require_nonce:
            raise WpRefusal(
                "cookie authentication cannot write without WP_NONCE: set it to the "
                "nonce a logged-in WordPress session returns (the 'X-WP-Nonce' header "
                "of a GET to /wp-json with that session's cookies), or use "
                "WP_APP_USER/WP_APP_PASSWORD instead"
            )
        return session

    raise WpRefusal(
        "no credentials: set WP_APP_USER/WP_APP_PASSWORD, or provide a cookie file at %s" % cookie_file
    )
