"""
review_mirror - the key-less half of .github/workflows/review.yml (PR #67, Issue #65).

Stage: CI, after the model session. The agent step holds ANTHROPIC_API_KEY and an LLM that reads
an untrusted diff, so everything that touches GitHub with model-written text lives here, in a
step that holds no key and no agent:

  check-tools   fail when the session's own tool list (the `init` message of the action's
                execution file) holds a tool outside the allowlist, or cannot be read at all
  extract       pull the model's final reply out of the execution file
  post-pr       sanitise it and create or update ONE marked comment on the pull request
  mirror-issue  copy that comment onto the linked Issue, once, updated in place

Every `gh` call goes through an injectable runner, so the offline suite
(.claude/hooks/Test/test_review_workflow.py) never touches the network. Settings and their
provenance are in review-mirror.json beside this file (R0, R4). Exit codes (R12): 0 done or a
clean skip, 1 failure, 2 refusal by design (a forbidden tool, a malformed argument).
"""
import argparse
import html
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().with_name("review-mirror.json")
REQUIRED_KEYS = (
    "review_marker", "bot_login", "pr_marker_template", "issue_marker_template", "allowed_tools",
    "author_pattern", "repo_pattern", "gh_timeout_seconds", "gh_retries", "secret_patterns",
    "comment_max_chars", "pr_pattern", "comment_id_pattern", "sha_pattern", "gh_retry_delay_seconds",
    "error_text_chars", "invisible_characters",
)
# A gh failure worth another attempt: a server error, a timeout, or a dropped connection. A 404, 403
# or 422 is permanent and is never retried (code review round 6).
_TRANSIENT = re.compile(r"HTTP 5[0-9]{2}|timed? ?out|connection (?:reset|refused|aborted)|dial tcp|"
                        r"temporary failure|unexpected EOF|TLS handshake", re.I)
EXIT_OK, EXIT_FAIL, EXIT_REFUSED = 0, 1, 2


class ConfigError(Exception):
    """A setting is missing from, or unreadable in, review-mirror.json."""


class ToolListError(Exception):
    """The execution file carries no readable tool list, so the guard cannot vouch for it."""


class ReviewError(Exception):
    """The model reply, a comment or a GitHub answer cannot be used."""


def load_config(path):
    """
    Purpose:
        Read review-mirror.json and check every required key is present.

    Inputs:
        path (Path): the JSON file; each key maps to {"value", "provenance"}.

    Outputs:
        cfg (dict): the parsed file, unchanged.

    Raises:
        ConfigError: the file is missing, is not JSON, or lacks a required key (named).
    """
    try:
        cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError("cannot read %s: %s" % (path, exc))
    for key in REQUIRED_KEYS:
        if not isinstance(cfg, dict) or not isinstance(cfg.get(key), dict) or "value" not in cfg[key]:
            raise ConfigError("key '%s' missing from %s, or not a {value, provenance} object" % (key, path))
    return cfg


def val(cfg, key):
    """
    Purpose:
        Return the value of one configured key.

    Inputs:
        cfg (dict): the loaded configuration.
        key (str): a key of review-mirror.json.

    Outputs:
        value (any): the key's "value" entry.
    """
    return cfg[key]["value"]


def valid_login(login, cfg):
    """
    Purpose:
        Accept a GitHub login only when it matches the configured username pattern in full.

    Details:
        A full match, so a trailing newline does not pass. A '[bot]' account does not match, on
        purpose: it can neither be mentioned usefully nor assigned.

    Inputs:
        login (str | None): the candidate login.
        cfg (dict): the loaded configuration.

    Outputs:
        login (str | None): the login unchanged when valid, else None.
    """
    return login if isinstance(login, str) and re.fullmatch(val(cfg, "author_pattern"), login) else None


def find_issue_number(pr_body):
    """
    Purpose:
        Return the issue number named by a line that STARTS with Fixes or Closes.

    Details:
        A sentence that merely contains the words, a quoted line, a fenced block and an HTML
        comment never select an issue (a template example must not pick Issue #1).

    Inputs:
        pr_body (str | None): the pull request description.

    Outputs:
        number (int | None): the first matching issue number, else None.
    """
    fenced = commented = False
    for line in (pr_body or "").splitlines():
        if commented:
            if "-->" not in line:
                continue
            line, commented = line.split("-->", 1)[1], False
        line = re.sub(r"<!--.*?-->", "", line)
        if "<!--" in line:
            line, commented = line.split("<!--", 1)[0], True
        stripped = line.strip()
        if line.startswith(("    ", "\t")):      # an indented code block is an example, not a link
            continue
        if stripped.startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = re.match(r"^\s{0,3}(?:[-*+]\s+)?(?:fix(?:es|ed)?|close[sd]?|resolve[sd]?)\s+#([0-9]+)\b", line, flags=re.I)
        if m:
            return int(m.group(1))
    return None


# One alternation, applied in ONE pass, leftmost match first. Nothing a rule emits is looked at
# again, so a mention inside a URL cannot break out of the code span that wraps the URL, and there
# is no lookbehind to fool (an underscore, a backslash or an entity in front of a token).
_TOKEN = re.compile("|".join((
    r"(?P<link>(?P<bang>!?)\[(?P<ltext>[^\]\n]*)\]\((?P<ltarget>[^)\s]*)[^)\n]*\))",
    r"(?P<url>(?:[A-Za-z][A-Za-z0-9+.-]*://|www\.|mailto:|xmpp:)[^\s)>\]\x00\x01]+)",
    r"(?P<gh>(?i:GH)-[0-9]+)",
    # owner/repo/pull/N, github.com/owner/repo/issues/N and a bare /discussions/N all render as a
    # live cross-reference although none holds a '#' or a scheme (security round 7).
    r"(?P<path>(?:github\.com)?/?(?:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)?/(?:pull|issues|discussions)/[0-9]+)",
    r"(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[0-9]+)",
    r"(?P<issue>#[0-9]+)",
    r"(?P<mention>@[A-Za-z0-9_][A-Za-z0-9_/-]*)",
    # A bare commit hash becomes a live commit link once the commit exists. A hash always holds a
    # digit, which keeps hex-only words (facade, decade, effaced) out of the net.
    # No word boundary on purpose: one glued to a preceding token has none on the first pass and
    # gains one once that token is wrapped, which would make a second pass change the output.
    r"(?P<sha>(?=[0-9a-f]{7})(?=[0-9a-f]*[0-9])[0-9a-f]{7,40})",
    r"(?P<bracket>[\[\]])",
)))
# A BALANCED code span: the same run of backticks opens and closes it, the opener is neither
# escaped nor the tail of a longer run, and it stays on ONE line. Only these are inert in GFM, so
# only these are left alone. A span that would cross a line is treated as no span at all (stricter
# than GFM on purpose: a list, quote or heading line ends the paragraph, so a multi-line span can
# hide live text on its second line).
_SPAN = re.compile(r"(?<![`\\])(`+)(?!`)([^\n]+?)(?<!`)\1(?!`)")


def _replace_token(match):
    """
    Purpose:
        Turn one matched token into inert text.

    Inputs:
        match (re.Match): a match of _TOKEN.

    Details:
        Inside a span a '|' becomes a broken bar and a '$' a fullwidth dollar sign, because table
        parsing and math extraction both run BEFORE code spans and would otherwise reach through
        the span. A link is emitted with a leading space so that an '@', '#' or 'GH-' just before
        it can never be glued to the link text, which was a live mention (security round 6).

    Outputs:
        text (str): a code span around the token, the link text plus its target in a code span,
        or an entity for a square bracket.
    """
    kind = match.lastgroup
    if kind == "bracket":
        return "&#91;" if match.group(0) == "[" else "&#93;"
    if kind == "link":
        text = _tokens(match.group("ltext")) or "link"
        target = _span_safe(match.group("ltarget").replace("\x00", "'").replace("\x01", ""))
        return " %s (`%s`)" % (text, target) if target else " " + text
    return "`%s`" % _span_safe(match.group(0))


def _span_safe(text):
    """Purpose: remove from text the two characters that reach through a code span. Inputs:
    text (str). Outputs: str with '|' as a broken bar and '$' as a fullwidth dollar sign."""
    return text.replace("|", "¦").replace("$", "＄")


def _plain(text):
    """
    Purpose:
        Escape a stretch of text that sits BETWEEN tokens.

    Inputs:
        text (str): decoded text holding no token.

    Outputs:
        text (str): '&' as &amp; (an entity the model wrote in escaped form stays text) and EVERY
        '<' as &lt;. Unconditional on purpose: a lookahead for a following letter sees only this
        slice, and a '<' ending the slice before a link token took its letter from the link text
        (security review round 4), so a tag could be assembled around a token. Every '$' becomes
        a FULLWIDTH dollar sign, never the entity &#36;: GitHub decodes an entity before it
        extracts $...$ math, so the entity left the span between two of them read as math whose
        text the mention filter scans (security rounds 6 and 7).
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace("$", "＄")


def _tokens(segment):
    """
    Purpose:
        Run the single token pass over text that holds no balanced code span.

    Details:
        Tokens are found in the RAW text and wrapped as they are, so a URL keeps its '&' and '<'
        inside its code span (where they are literal). Only the text between tokens is escaped.

    Inputs:
        segment (str): decoded text, backticks and backslashes already held as placeholders.

    Outputs:
        text (str): the neutralised text.
    """
    out, last = [], 0
    for match in _TOKEN.finditer(segment):
        out.append(_plain(segment[last:match.start()]))
        out.append(_replace_token(match))
        last = match.end()
    out.append(_plain(segment[last:]))
    return "".join(out)


def _redact(text, secret_patterns):
    """Purpose: replace secret-shaped text. Inputs: text (str), secret_patterns (iterable[str]).
    Outputs: str, each match replaced by (redacted)."""
    for pattern in secret_patterns:
        text = re.sub(pattern, "(redacted)", text)
    return text


def _neutralise(segment, secret_patterns=()):
    """
    Purpose:
        Make one stretch of text, outside any balanced code span, inert.

    Details:
        Character references are decoded here, and only here: GitHub does not decode them inside
        a code span, so neither does this code, which also keeps a second pass stable. Secrets are
        redacted on the decoded text. Every backtick and backslash is held as a control
        placeholder while the token pass runs, so the pass can neither read them nor be fooled by
        them, and becomes an entity afterwards (so nothing can escape or open a span, and the
        '#96' of an entity is never read as a reference). Text between tokens has '&' and a
        tag-starting '<' escaped (see _tokens). Every backtick in a segment is a lone one,
        because the balanced spans were taken out by the caller.

    Inputs:
        segment (str): raw text outside balanced code spans.
        secret_patterns (iterable[str]): regexes redacted from the decoded text.

    Outputs:
        text (str): the neutralised text.
    """
    out = html.unescape(segment).replace("\x00", "").replace("\x01", "")
    out = _redact(out, secret_patterns).replace("`", "\x00").replace("\\", "\x01")
    return _tokens(out).replace("\x00", "&#96;").replace("\x01", "&#92;")


def sanitize(text, secret_patterns=()):
    """
    Purpose:
        Make model-written markdown inert: no notification, no cross-reference, no remote
        image, no raw HTML, no secret-shaped token.

    Details:
        In order: every line separator becomes '\\n' (str.splitlines, which _quote also uses, so
        no later step can cut a span the sanitiser kept whole); character references are decoded
        and control placeholders stripped; secret-shaped text is redacted on the DECODED text;
        each balanced one-line code span is REBUILT as a single span with no backtick inside, so
        every span in the output is one this function wrote; everything else goes through the
        token pass (mentions, #N, GH-N, owner/repo#N, URLs of any scheme, links, images, square
        brackets, raw HTML). Applying it twice changes nothing more.

    Inputs:
        text (str): the model's reply.
        secret_patterns (iterable[str]): regexes whose matches are replaced by (redacted).

    Outputs:
        clean (str): the neutralised text.
    """
    # Invisible and bidirectional characters can carry text a human reviewer cannot see but another
    # agent reads, or reverse what a finding displays. They go FIRST, before the line and trailing
    # newline handling (one removed last would leave a new trailing newline and break stability),
    # and so that one cannot split a token (a zero-width character between @ and a name).
    text = re.sub(_ACTIVE["invisible_characters"], "", text)
    text = "\n".join(text.splitlines()).rstrip("\n").replace("\x00", "").replace("\x01", "")
    # Spans are found on the RAW text, before any character reference is decoded, exactly as
    # GitHub reads it: an entity is never a span delimiter and is not decoded inside a span.
    pieces, last = [], 0
    for span in _SPAN.finditer(text):
        pieces.append(_neutralise(text[last:span.start()], secret_patterns))
        # '|' becomes a broken bar: table parsing runs BEFORE inline parsing, so a pipe inside a
        # span ends the table cell and leaves the span's two backticks in different cells.
        inner = _span_safe(_redact(span.group(2).replace("`", "'"), secret_patterns))
        pieces.append("`%s`" % inner)
        last = span.end()
    pieces.append(_neutralise(text[last:], secret_patterns))
    # Two code spans that touch would read as one run of backticks, so a space keeps them apart.
    return "".join(pieces).replace("``", "` `")


def select_comment(comments, marker, login):
    """
    Purpose:
        Pick the last comment written by `login` whose body carries `marker`.

    Inputs:
        comments (list[dict]): GitHub issue comments (id, user.login, body).
        marker (str): the hidden marker line.
        login (str): the only author trusted.

    Outputs:
        comment (dict | None): the last match, else None.
    """
    hits = [c for c in comments if (c.get("user") or {}).get("login") == login and marker in (c.get("body") or "")]
    return hits[-1] if hits else None


def _init_tools(messages):
    """
    Purpose:
        Read the tool lists of EVERY `init` message of the session (a resumed or compacted
        session writes more than one, and a later one must not escape the check).

    Inputs:
        messages (list): the parsed execution file.

    Outputs:
        tools (list[str]): the tool names of all init messages.

    Raises:
        ToolListError: no system/init message carries a tools list.
    """
    found, tools = False, []
    for msg in messages:
        if isinstance(msg, dict) and msg.get("type") == "system" and msg.get("subtype") == "init":
            listed = msg.get("tools")
            if isinstance(listed, list):
                found = True
                tools.extend(str(t) for t in listed)
    if not found:
        raise ToolListError("no system/init message with a tools list in the execution file")
    return tools


def check_tools(messages, cfg):
    """
    Purpose:
        List the tools of the model session that are NOT on the allowlist (an allowlist, so a
        tool nobody thought to forbid is still refused).

    Inputs:
        messages (list): the parsed execution file (SDK messages).
        cfg (dict): the loaded configuration.

    Outputs:
        offenders (list[str]): tools outside the allowlist, empty when the session is clean.

    Raises:
        ToolListError: no readable init message (R8: never vouch for what cannot be read).
    """
    allowed = set(val(cfg, "allowed_tools"))
    return [tool for tool in _init_tools(messages) if tool.split("(", 1)[0] not in allowed]


def extract_review(messages, cfg):
    """
    Purpose:
        Return the model's final reply, refusing anything that is not a marked review.

    Details:
        Leading blank space is tolerated, since a paid review must not be lost over a newline.

    Inputs:
        messages (list): the parsed execution file.
        cfg (dict): the loaded configuration.

    Outputs:
        review (str): the reply text, stripped, starting with the configured marker line.

    Raises:
        ReviewError: no result message, an error result, an empty reply, or a reply whose first
            non-blank line is not the marker.
    """
    results = [m for m in messages if isinstance(m, dict) and m.get("type") == "result"]
    if not results:
        raise ReviewError("no result message in the execution file")
    last = results[-1]
    text = last.get("result")
    if last.get("subtype") != "success" or last.get("is_error") or not isinstance(text, str) or not text.strip():
        raise ReviewError("the session ended without a usable reply (subtype=%s)" % last.get("subtype"))
    text = text.strip()
    if not text.startswith(val(cfg, "review_marker")):
        raise ReviewError("the reply does not start with the required marker line")
    return text


def _quote(text):
    """Purpose: prefix every line with a blockquote marker. Inputs: text (str). Outputs: str."""
    return "\n".join("> " + ln if ln else ">" for ln in text.splitlines())


def _fit(text, cap):
    """
    Purpose:
        Keep a comment under GitHub's length limit, saying so when text was cut.

    Inputs:
        text (str): the comment body.
        cap (int): the configured maximum number of characters.

    Details:
        The cut is made on a line boundary, never inside a line. Every code span the sanitiser
        writes sits on one line, so a cut can neither split a span (its closing backtick lost,
        the text inside live) nor an entity.

    Outputs:
        body (str): the text unchanged, or cut with a visible quoted notice, never longer than cap.
    """
    if len(text) <= cap:
        return text
    notice = "\n\n> (review cut at %d characters to fit a GitHub comment)\n" % cap
    keep = text[:cap - len(notice)]
    cut = keep.rfind("\n")
    if cut < len(keep) // 2:
        # No usable line break in the second half (one very long line after the heading): cut at
        # the last space instead, so the findings survive rather than only the heading.
        cut = keep.rfind(" ")
    keep = keep[:max(cut, 0)].rstrip()
    # A cut inside a code span would leave its opening backtick unclosed and the text after it
    # live, so drop back to before the last opener when the count is odd. A cut mid-entity goes too.
    while keep.count("`") % 2:
        keep = keep[:keep.rfind("`")].rstrip()
    keep = re.sub(r"&#?[A-Za-z0-9]*$", "", keep).rstrip()
    return keep + notice


def build_pr_body(review, sha, pr, cfg):
    """
    Purpose:
        Build the pull request comment: hidden marker, reviewed commit, sanitised blockquote.

    Inputs:
        review (str): the extracted reply.
        sha (str): the head commit that was reviewed.
        pr (int): the pull request number.
        cfg (dict): the loaded configuration.

    Outputs:
        body (str): the comment text, within the configured length cap.
    """
    marker = val(cfg, "pr_marker_template").format(pr=pr)
    quoted = _quote(sanitize(review, val(cfg, "secret_patterns")))
    return _fit("%s\nReviewed commit: `%s`\n\n%s\n" % (marker, sha, quoted), val(cfg, "comment_max_chars"))


def build_issue_body(quoted_review, author, pr, first, cfg=None):
    """
    Purpose:
        Build the Issue copy: hidden marker, author mention on creation only, review text.

    Details:
        An author that is not a plain username (a '[bot]' account, a hostile value) is simply not
        mentioned. The comment is still posted.

    Inputs:
        quoted_review (str): the already sanitised, quoted review.
        author (str): the pull request author login.
        pr (int): the pull request number.
        first (bool): true when the comment is being created (the only time it pings).
        cfg (dict | None): configuration, defaulting to the shipped file.

    Outputs:
        body (str): the comment text, within the configured length cap.
    """
    cfg = cfg or load_config(CONFIG_PATH)
    marker = val(cfg, "issue_marker_template").format(pr=pr)
    login = valid_login(author, cfg)
    head = "@%s " % login if first and login else ""
    body = "%s\n%sReview of pull request #%s, kept up to date by CI.\n\n%s\n" % (marker, head, pr, quoted_review)
    return _fit(body, val(cfg, "comment_max_chars"))


def make_runner(cfg):
    """
    Purpose:
        Build the real `gh` runner with a timeout and a bounded retry count (R10).

    Details:
        Only a transient failure (a timeout, a dropped connection, an HTTP 5xx) is retried, after
        a configured pause. A 404, 403 or 422 is permanent and ends the call at once, and a POST
        is never retried, since one that timed out may already have created its comment.

    Inputs:
        cfg (dict): the loaded configuration.

    Outputs:
        runner (callable): runner(args, stdin=None) -> (returncode, stdout or stderr).
    """
    timeout, retries = val(cfg, "gh_timeout_seconds"), val(cfg, "gh_retries")
    delay = val(cfg, "gh_retry_delay_seconds")

    def run(args, stdin=None):
        attempts = 1 if "POST" in args else retries + 1
        last = (1, "gh did not run")
        for attempt in range(attempts):
            try:
                done = subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True,
                                      encoding="utf-8", timeout=timeout)
                last = (done.returncode, done.stdout if done.returncode == 0 else done.stderr or done.stdout)
                transient = last[0] != 0 and bool(_TRANSIENT.search(last[1] or ""))
            except (OSError, subprocess.TimeoutExpired) as exc:
                last, transient = (1, str(exc)), True
            if last[0] == 0 or not transient:
                break
            if attempt < attempts - 1:
                time.sleep(delay)
        return last

    return run


def _gh_json(runner, args, stdin=None):
    """
    Purpose:
        Run one gh call and parse its JSON answer.

    Inputs:
        runner (callable): the gh runner.
        args (list[str]): arguments after `gh`.
        stdin (str | None): text sent on standard input.

    Outputs:
        data (any): the parsed JSON, {} for an empty answer.

    Raises:
        ReviewError: gh failed, or answered text that is not JSON.
    """
    rc, out = runner(args, stdin)
    return _parse_gh(rc, out, " ".join(args[:3]))


# Settings read by helpers that have no cfg argument. main() fills it from the configuration it
# loaded, so there is no second copy of any number here. A helper called before main() ran reads
# the shipped file once (R3: a missing key is still a named ConfigError, never a silent default).
class _Active(dict):
    """The configured values helpers need without a cfg argument, loaded on first use."""

    def __missing__(self, key):
        self.update({k: val(load_config(CONFIG_PATH), k) for k in ("error_text_chars", "invisible_characters")})
        return self[key]


_ACTIVE = _Active()


def _parse_gh(rc, out, what):
    """
    Purpose:
        Turn one gh answer into data, or into a named failure.

    Inputs:
        rc (int): gh's return code.
        out (str): its output (stdout on success, stderr on failure).
        what (str): a short label for the error message.

    Outputs:
        data (any): the parsed JSON, {} for an empty answer.

    Raises:
        ReviewError: a non-zero return code, or an answer that is not JSON.
    """
    if rc != 0:
        raise ReviewError("gh %s failed: %s" % (what, (out or "").strip()[:_ACTIVE["error_text_chars"]]))
    try:
        return json.loads(out) if (out or "").strip() else {}
    except ValueError:
        raise ReviewError("gh %s returned text that is not JSON" % what)


def _list_comments(runner, repo, number):
    """
    Purpose:
        List every comment of an issue or pull request, across pages.

    Inputs:
        runner (callable): the gh runner.
        repo (str): owner/name.
        number (int): issue or pull request number.

    Outputs:
        comments (list[dict]): the flattened comments.

    Raises:
        ReviewError: gh failed.
    """
    pages = _gh_json(runner, ["api", "--paginate", "--slurp", "repos/%s/issues/%s/comments" % (repo, number)])
    return [c for page in pages for c in (page if isinstance(page, list) else [page])]


def _upsert(runner, repo, number, body, existing, dry_run):
    """
    Purpose:
        Create the comment, or update the one the caller already found, in place.

    Inputs:
        runner (callable): the gh runner.
        repo (str): owner/name.
        number (int): the issue or pull request number.
        body (str): the comment text.
        existing (dict | None): the marked comment found by the caller, None when there is none.
        dry_run (bool): when true nothing is written.

    Outputs:
        result (tuple): (action, comment id or None, existed).

    Raises:
        ReviewError: a gh write failed.
    """
    if dry_run:
        return ("would-update" if existing else "would-create", existing["id"] if existing else None, bool(existing))
    payload = json.dumps({"body": body})
    if existing:
        _gh_json(runner, ["api", "-X", "PATCH", "repos/%s/issues/comments/%s" % (repo, existing["id"]),
                          "--input", "-"], payload)
        return "updated", existing["id"], True
    made = _gh_json(runner, ["api", "-X", "POST", "repos/%s/issues/%s/comments" % (repo, number),
                             "--input", "-"], payload)
    return "created", made.get("id"), False


def _read_json(path):
    """
    Purpose:
        Read a JSON file written by the action.

    Inputs:
        path (str): the file.

    Outputs:
        data (any): the parsed JSON.

    Raises:
        ReviewError: the file is missing or is not JSON.
    """
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReviewError("cannot read execution file %s: %s" % (path, exc))


def _report(**fields):
    """Purpose: print the machine-readable JSON report (R17). Inputs: report fields. Outputs:
    none, one JSON line on stdout."""
    print(json.dumps(fields, sort_keys=True))


def _cmd_check_tools(args, cfg):
    """
    Purpose:
        Subcommand check-tools: refuse a session whose tool list leaves the allowlist.

    Inputs:
        args (Namespace): parsed arguments (execution_file).
        cfg (dict): the loaded configuration.

    Outputs:
        code (int): 0 clean, 1 list unreadable, 2 a tool outside the allowlist. JSON on stdout.
    """
    try:
        offenders = check_tools(_read_json(args.execution_file), cfg)
    except (ToolListError, ReviewError) as exc:
        print("[CI] cannot verify the tool list: %s" % exc, file=sys.stderr)
        _report(ok=False, reason=str(exc))
        return EXIT_FAIL
    _report(ok=not offenders, forbidden=offenders)
    if offenders:
        print("[CI] tools outside the allowlist in the model session: %s" % ", ".join(offenders), file=sys.stderr)
        return EXIT_REFUSED
    return EXIT_OK


def _cmd_extract(args, cfg):
    """
    Purpose:
        Subcommand extract: write the model's marked reply to a file.

    Inputs:
        args (Namespace): parsed arguments (execution_file, out).
        cfg (dict): the loaded configuration.

    Outputs:
        code (int): 0 written, 1 no usable reply (nothing is written). JSON on stdout.
    """
    try:
        review = extract_review(_read_json(args.execution_file), cfg)
    except ReviewError as exc:
        print("[CI] no usable review: %s" % exc, file=sys.stderr)
        _report(ok=False, reason=str(exc))
        return EXIT_FAIL
    Path(args.out).write_text(review, encoding="utf-8")
    _report(ok=True, chars=len(review))
    return EXIT_OK


def _validate_target(args, cfg):
    """
    Purpose:
        Refuse a malformed --pr or --repo before it reaches a gh argument.

    Inputs:
        args (Namespace): parsed arguments (pr, repo).
        cfg (dict): the loaded configuration.

    Outputs:
        ok (bool): true when both match their pattern in full.
    """
    if not re.fullmatch(val(cfg, "pr_pattern"), args.pr) or not re.fullmatch(val(cfg, "repo_pattern"), args.repo):
        print("[CI] refused: malformed --pr or --repo", file=sys.stderr)
        return False
    return True


def _cmd_post_pr(args, cfg, runner):
    """
    Purpose:
        Subcommand post-pr: create or update the one marked pull request comment.

    Inputs:
        args (Namespace): parsed arguments (repo, pr, sha, body_file, output_file, dry_run).
        cfg (dict): the loaded configuration.
        runner (callable): the gh runner.

    Outputs:
        code (int): 0 posted or planned, 1 failure, 2 malformed argument. Appends
        comment_id=<id> to --output-file when given. A dry run calls gh not at all.
    """
    if not _validate_target(args, cfg):
        return EXIT_REFUSED
    if not re.fullmatch(val(cfg, "sha_pattern"), args.sha):
        print("[CI] refused: malformed --sha", file=sys.stderr)
        return EXIT_REFUSED
    pr = int(args.pr)
    if args.dry_run:
        _report(ok=True, action="would-upsert", comment_id=None)
        return EXIT_OK
    try:
        body = build_pr_body(Path(args.body_file).read_text(encoding="utf-8"), args.sha, pr, cfg)
        marker = val(cfg, "pr_marker_template").format(pr=pr)
        existing = select_comment(_list_comments(runner, args.repo, pr), marker, val(cfg, "bot_login"))
        action, cid, _ = _upsert(runner, args.repo, pr, body, existing, False)
        if cid is None:
            raise ReviewError("GitHub answered without a comment id, so the mirror job could not find the comment")
    except (OSError, ReviewError) as exc:
        print("[CI] post-pr failed: %s" % exc, file=sys.stderr)
        _report(ok=False, reason=str(exc))
        return EXIT_FAIL
    if args.output_file and cid is not None:
        with open(args.output_file, "a", encoding="utf-8") as fh:
            fh.write("comment_id=%s\n" % cid)
    _report(ok=True, action=action, comment_id=cid)
    return EXIT_OK


def _cmd_mirror(args, cfg, runner, env):
    """
    Purpose:
        Subcommand mirror-issue: copy the bot's PR comment onto the Issue named by `Fixes #N`.

    Details:
        A dry run still READS (the Issue, the PR comment, the Issue's comments) and writes
        nothing. A missing or foreign PR comment is a failure, never a silent skip.

    Inputs:
        args (Namespace): parsed arguments (repo, pr, author, pr_comment_id, dry_run).
        cfg (dict): the loaded configuration.
        runner (callable): the gh runner.
        env (dict): environment, PR_BODY is read from it.

    Outputs:
        code (int): 0 mirrored or cleanly skipped, 1 failure, 2 malformed argument.
    """
    if not _validate_target(args, cfg) or not re.fullmatch(val(cfg, "comment_id_pattern"), args.pr_comment_id):
        return EXIT_REFUSED
    issue = find_issue_number(env.get("PR_BODY", ""))
    if issue is None:
        print("[CI] no Fixes/Closes #N line in the PR body; Issue mirror skipped.")
        _report(ok=True, skipped="no-issue-line")
        return EXIT_OK
    pr = int(args.pr)
    try:
        rc, out = runner(["api", "repos/%s/issues/%s" % (args.repo, issue)])
        if rc != 0 and re.search(r"HTTP 404|Not Found", out or ""):
            print("[CI] #%s does not exist; Issue mirror skipped." % issue)
            _report(ok=True, skipped="issue-not-found")
            return EXIT_OK
        target = _parse_gh(rc, out, "repos/%s/issues/%s" % (args.repo, issue))
        if target.get("pull_request") is not None or target.get("state") != "open":
            print("[CI] #%s is not an open Issue; Issue mirror skipped." % issue)
            _report(ok=True, skipped="not-an-open-issue")
            return EXIT_OK
        source = _gh_json(runner, ["api", "repos/%s/issues/comments/%s" % (args.repo, args.pr_comment_id)])
        pr_marker = val(cfg, "pr_marker_template").format(pr=pr)
        if (source.get("user") or {}).get("login") != val(cfg, "bot_login") or pr_marker not in (source.get("body") or ""):
            raise ReviewError("the review comment %s is missing or not written by %s" % (args.pr_comment_id, val(cfg, "bot_login")))
        # The PR comment is already sanitised and quoted by build_pr_body. Drop only its marker
        # line and sanitise again (stable on its own output) in case it was edited by hand.
        quoted = sanitize("\n".join(ln for ln in source["body"].splitlines() if pr_marker not in ln).strip(),
                          val(cfg, "secret_patterns"))
        issue_marker = val(cfg, "issue_marker_template").format(pr=pr)
        existing = select_comment(_list_comments(runner, args.repo, issue), issue_marker, val(cfg, "bot_login"))
        body = build_issue_body(quoted, args.author, pr, existing is None, cfg)
        action, cid, existed = _upsert(runner, args.repo, issue, body, existing, args.dry_run)
        login = valid_login(args.author, cfg)
        if login and not existed and not args.dry_run:
            rc, _ = runner(["api", "-X", "POST", "repos/%s/issues/%s/assignees" % (args.repo, issue), "--input", "-"],
                           json.dumps({"assignees": [login]}))
            if rc != 0:
                print("[CI] could not assign %s; the comment was still posted." % login)
    except ReviewError as exc:
        print("[CI] mirror-issue failed: %s" % exc, file=sys.stderr)
        _report(ok=False, reason=str(exc))
        return EXIT_FAIL
    _report(ok=True, action=action, issue=issue, comment_id=cid)
    return EXIT_OK


def main(argv=None, runner=None, env=None):
    """
    Purpose:
        Command-line entry point for the four subcommands.

    Inputs:
        argv (list[str] | None): arguments, defaulting to sys.argv.
        runner (callable | None): gh runner, defaulting to the real one with timeout and retries.
        env (dict | None): environment, defaulting to os.environ (PR_BODY is read from it).

    Outputs:
        code (int): 0 done or clean skip, 1 failure, 2 refusal by design. A JSON report goes to
        stdout, human text to stderr.
    """
    parser = argparse.ArgumentParser(prog="review_mirror", description=__doc__.splitlines()[1])
    parser.add_argument("--config", default=str(CONFIG_PATH))
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("check-tools", "extract"):
        p = sub.add_parser(name)
        p.add_argument("--execution-file", required=True)
        if name == "extract":
            p.add_argument("--out", required=True)
    for name in ("post-pr", "mirror-issue"):
        p = sub.add_parser(name)
        p.add_argument("--repo", required=True)
        p.add_argument("--pr", required=True)
        p.add_argument("--dry-run", action="store_true")
        if name == "post-pr":
            p.add_argument("--sha", required=True)
            p.add_argument("--body-file", required=True)
            p.add_argument("--output-file")
        else:
            p.add_argument("--author", required=True)
            p.add_argument("--pr-comment-id", required=True)
    args = parser.parse_args(argv)
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print("[CI] %s" % exc, file=sys.stderr)
        return EXIT_FAIL
    _ACTIVE.update({k: val(cfg, k) for k in ("error_text_chars", "invisible_characters")})
    runner = runner or make_runner(cfg)
    env = os.environ if env is None else env
    if args.command == "check-tools":
        return _cmd_check_tools(args, cfg)
    if args.command == "extract":
        return _cmd_extract(args, cfg)
    if args.command == "post-pr":
        return _cmd_post_pr(args, cfg, runner)
    return _cmd_mirror(args, cfg, runner, env)


if __name__ == "__main__":
    sys.exit(main())
