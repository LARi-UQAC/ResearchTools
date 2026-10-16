"""
review_mirror - the key-less half of .github/workflows/review.yml (PR #67, Issue #65).

Stage: CI, after the model session. The agent step holds ANTHROPIC_API_KEY and an LLM that reads
an untrusted diff, so everything that touches GitHub with model-written text lives here, in a
step that holds no key and no agent:

  check-tools   fail when the session's own tool list (the `init` message of the action's
                execution file) contains a forbidden tool, or cannot be read at all
  extract       pull the model's final reply out of the execution file
  post-pr       sanitise it and create or update ONE marked comment on the pull request
  mirror-issue  copy that comment onto the linked Issue, once, updated in place

Every `gh` call goes through an injectable runner, so the offline suite
(.claude/hooks/Test/test_review_workflow.py) never touches the network. Settings and their
provenance are in review-mirror.json beside this file (R0, R4). Exit codes (R12): 0 done or a
clean skip, 1 failure, 2 refusal by design (a forbidden tool, a malformed argument).
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().with_name("review-mirror.json")
REQUIRED_KEYS = (
    "review_marker", "bot_login", "pr_marker_template", "issue_marker_template", "allowed_tools",
    "author_pattern", "repo_pattern", "gh_timeout_seconds", "gh_retries",
    "secret_patterns",
)
EXIT_OK, EXIT_FAIL, EXIT_REFUSED = 0, 1, 2


class ConfigError(Exception):
    """A setting is missing from, or unreadable in, review-mirror.json."""


class ToolListError(Exception):
    """The execution file carries no readable tool list, so the guard cannot vouch for it."""


class ReviewError(Exception):
    """The model reply, a comment or an argument cannot be used as a review."""


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
        if not isinstance(cfg, dict) or key not in cfg or "value" not in cfg[key]:
            raise ConfigError("key '%s' missing from %s" % (key, path))
    return cfg


def val(cfg, key):
    """Purpose: the value of one configured key. Inputs: cfg (dict), key (str). Outputs: any."""
    return cfg[key]["value"]


def find_issue_number(pr_body):
    """
    Purpose:
        Return the issue number named by a line that STARTS with Fixes or Closes.

    Details:
        A sentence that merely contains the words, or a quoted line, never selects an issue.

    Inputs:
        pr_body (str | None): the pull request description.

    Outputs:
        number (int | None): the first matching issue number, else None.
    """
    fenced = commented = False
    for line in (pr_body or "").splitlines():
        stripped = line.strip()
        if commented:
            commented = "-->" not in line
            continue
        if stripped.startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced:
            continue
        if stripped.startswith("<!--"):
            commented = "-->" not in line
            continue
        m = re.match(r"^\s*(?:fixes|closes)\s+#([0-9]+)\b", line, flags=re.I)
        if m:
            return int(m.group(1))
    return None


_LINK = re.compile(r"(!?)\[([^\]\n]*)\]\(([^)\s]*)[^)\n]*\)")
_REPO_REF = re.compile(r"(?<![`\w/])([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[0-9]+)")
_ISSUE_REF = re.compile(r"(?<![`\w/&])#([0-9]+)\b")
_MENTION = re.compile(r"(?<![`\w@/])@([A-Za-z0-9_][A-Za-z0-9_/-]*)")
_URL = re.compile(r"(?<![`\w/&])((?:https?://|www\.)[^\s)>\]`]+)")
_GH_REF = re.compile(r"(?<![`\w/&-])(GH-[0-9]+)\b")
_HTML = re.compile(r"<(?=[!/A-Za-z?])")
_BRACKET = re.compile(r"(?<!\\)([\[\]])")
# A BALANCED code span: the same run of backticks opens and closes it, the opener is not
# backslash-escaped, and it stays on ONE line. Only these are inert in GFM, so only these are left
# alone. A backtick that never closes is literal text, and a span that would cross a line is
# treated as no span at all (stricter than GFM on purpose: a line starting a list, quote or
# heading ends the paragraph, so a multi-line span can hide live text on its second line).
_SPAN = re.compile(r"(?<!\\)(`+)(?!`)([^\n]+?)(?<!`)\1(?!`)")


def _neutralise(segment):
    """Purpose: make one stretch of text, outside any balanced code span, inert. Inputs:
    segment (str). Outputs: str."""
    out = segment.replace("`", "&#96;")
    out = _HTML.sub("&lt;", out)
    out = _LINK.sub(lambda m: "%s (`%s`)" % (m.group(2) or "link", m.group(3)) if m.group(3) else m.group(2), out)
    out = _URL.sub(lambda m: "`%s`" % m.group(1), out)
    out = _GH_REF.sub(lambda m: "`%s`" % m.group(1), out)
    out = _REPO_REF.sub(lambda m: "`%s`" % m.group(1), out)
    out = _ISSUE_REF.sub(lambda m: "`#%s`" % m.group(1), out)
    out = _MENTION.sub(lambda m: "`@%s`" % m.group(1), out)
    return _BRACKET.sub(r"\\\1", out)


def sanitize(text, secret_patterns=()):
    """
    Purpose:
        Make model-written markdown inert: no notification, no cross-reference, no remote
        image, no raw HTML, no secret-shaped token.

    Details:
        Balanced code spans are kept as written. In everything else a lone backtick becomes
        &#96; (it would otherwise shield the text after it, which GFM still renders live),
        mentions, #N and owner/repo#N references and bare URLs go into code spans, links and
        images become their text plus the target in a code span, a '<' that starts a tag or a
        comment is escaped, and every square bracket is escaped so a reference-style link or
        image cannot form. Applying it twice changes nothing more.

    Inputs:
        text (str): the model's reply.
        secret_patterns (iterable[str]): regexes whose matches are replaced by (redacted).

    Outputs:
        clean (str): the neutralised text.
    """
    for pattern in secret_patterns:
        text = re.sub(pattern, "(redacted)", text)
    pieces, last = [], 0
    for span in _SPAN.finditer(text):
        pieces.append(_neutralise(text[last:span.start()]))
        pieces.append(span.group(0))
        last = span.end()
    pieces.append(_neutralise(text[last:]))
    return "".join(pieces)


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
    for msg in messages:
        if isinstance(msg, dict) and msg.get("type") == "system" and msg.get("subtype") == "init":
            tools = msg.get("tools")
            if isinstance(tools, list):
                return [str(t) for t in tools]
    raise ToolListError("no system/init message with a tools list in the execution file")


def check_tools(messages, cfg):
    """
    Purpose:
        List the tools of the model session that are NOT on the allowlist (an allowlist, so a
        tool nobody thought to forbid is still refused).

    Inputs:
        messages (list): the parsed execution file (SDK messages).
        cfg (dict): the loaded configuration.

    Outputs:
        offenders (list[str]): forbidden tools found, empty when the session is clean.

    Raises:
        ToolListError: no readable init message (R8: never vouch for what cannot be read).
    """
    allowed = set(val(cfg, "allowed_tools"))
    return [tool for tool in _init_tools(messages) if tool.split("(", 1)[0] not in allowed]


def extract_review(messages, cfg):
    """
    Purpose:
        Return the model's final reply, refusing anything that is not a marked review.

    Inputs:
        messages (list): the parsed execution file.
        cfg (dict): the loaded configuration.

    Outputs:
        review (str): the reply text, starting with the configured marker line.

    Raises:
        ReviewError: no result message, an error result, an empty reply, or a reply whose first
            line is not the marker.
    """
    results = [m for m in messages if isinstance(m, dict) and m.get("type") == "result"]
    if not results:
        raise ReviewError("no result message in the execution file")
    last = results[-1]
    text = last.get("result")
    if last.get("subtype") != "success" or last.get("is_error") or not isinstance(text, str) or not text.strip():
        raise ReviewError("the session ended without a usable reply (subtype=%s)" % last.get("subtype"))
    if not text.startswith(val(cfg, "review_marker")):
        raise ReviewError("the reply does not start with the required marker line")
    return text


def _quote(text):
    return "\n".join("> " + ln if ln else ">" for ln in text.splitlines())


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
        body (str): the comment text.
    """
    marker = val(cfg, "pr_marker_template").format(pr=pr)
    return "%s\nReviewed commit: `%s`\n\n%s\n" % (marker, sha, _quote(sanitize(review, val(cfg, "secret_patterns"))))


def build_issue_body(quoted_review, author, pr, first, cfg=None):
    """
    Purpose:
        Build the Issue copy: hidden marker, author mention on creation only, review text.

    Inputs:
        quoted_review (str): the already sanitised, quoted review.
        author (str): the pull request author login.
        pr (int): the pull request number.
        first (bool): true when the comment is being created (the only time it pings).
        cfg (dict | None): configuration, defaulting to the shipped file.

    Outputs:
        body (str): the comment text.

    Raises:
        ReviewError: the author login does not match the GitHub username pattern.
    """
    cfg = cfg or load_config(CONFIG_PATH)
    if not re.match(val(cfg, "author_pattern"), author or ""):
        raise ReviewError("author is not a valid GitHub login")
    marker = val(cfg, "issue_marker_template").format(pr=pr)
    head = "@%s " % author if first else ""
    return "%s\n%sReview of pull request #%s, kept up to date by CI.\n\n%s\n" % (marker, head, pr, quoted_review)


def make_runner(cfg):
    """
    Purpose:
        Build the real `gh` runner with a timeout and a bounded retry count (R10).

    Inputs:
        cfg (dict): the loaded configuration.

    Outputs:
        runner (callable): runner(args, stdin=None) -> (returncode, stdout).
    """
    timeout, retries = val(cfg, "gh_timeout_seconds"), val(cfg, "gh_retries")

    def run(args, stdin=None):
        last = (1, "gh did not run")
        for _ in range(retries + 1):
            try:
                done = subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True,
                                      encoding="utf-8", timeout=timeout)
                last = (done.returncode, done.stdout if done.returncode == 0 else done.stderr or done.stdout)
            except (OSError, subprocess.TimeoutExpired) as exc:
                last = (1, str(exc))
            if last[0] == 0:
                break
        return last

    return run


def _gh_json(runner, args, stdin=None):
    rc, out = runner(args, stdin)
    if rc != 0:
        raise ReviewError("gh %s failed: %s" % (" ".join(args[:3]), (out or "").strip()[:200]))
    try:
        return json.loads(out) if out.strip() else {}
    except ValueError:
        raise ReviewError("gh returned text that is not JSON")


def _list_comments(runner, repo, number):
    pages = _gh_json(runner, ["api", "--paginate", "--slurp", "repos/%s/issues/%s/comments" % (repo, number)])
    return [c for page in pages for c in (page if isinstance(page, list) else [page])]


_UNSET = object()


def _upsert(runner, repo, number, marker, login, body, dry_run, read=True, existing=_UNSET):
    """
    Purpose:
        Create the marked comment, or update the existing one in place.

    Inputs:
        runner (callable): the gh runner.
        repo, number, marker, login, body: where to write, how to find our own comment, its text.
        dry_run (bool): when true nothing is written.
        read (bool): when false the existing comments are not even listed (post-pr dry run).
        existing (dict | None): the marked comment when the caller already listed the comments,
            so they are not listed a second time; left unset, they are listed here.

    Outputs:
        result (tuple): (action, comment id or None, existed).
    """
    if dry_run and not read:
        return "would-upsert", None, False
    if existing is _UNSET:
        existing = select_comment(_list_comments(runner, repo, number), marker, login)
    payload = json.dumps({"body": body})
    if dry_run:
        return ("would-update" if existing else "would-create", existing["id"] if existing else None, bool(existing))
    if existing:
        _gh_json(runner, ["api", "-X", "PATCH", "repos/%s/issues/comments/%s" % (repo, existing["id"]),
                          "--input", "-"], payload)
        return "updated", existing["id"], True
    made = _gh_json(runner, ["api", "-X", "POST", "repos/%s/issues/%s/comments" % (repo, number),
                             "--input", "-"], payload)
    return "created", made.get("id"), False


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReviewError("cannot read execution file %s: %s" % (path, exc))


def _report(**fields):
    print(json.dumps(fields, sort_keys=True))


def _cmd_check_tools(args, cfg):
    try:
        offenders = check_tools(_read_json(args.execution_file), cfg)
    except (ToolListError, ReviewError) as exc:
        print("[CI] cannot verify the tool list: %s" % exc, file=sys.stderr)
        _report(ok=False, reason=str(exc))
        return EXIT_FAIL
    _report(ok=not offenders, forbidden=offenders)
    if offenders:
        print("[CI] forbidden tools in the model session: %s" % ", ".join(offenders), file=sys.stderr)
        return EXIT_REFUSED
    return EXIT_OK


def _cmd_extract(args, cfg):
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
    if not re.fullmatch(r"[0-9]{1,9}", args.pr) or not re.match(val(cfg, "repo_pattern"), args.repo):
        print("[CI] refused: malformed --pr or --repo", file=sys.stderr)
        return False
    return True


def _cmd_post_pr(args, cfg, runner):
    if not _validate_target(args, cfg):
        return EXIT_REFUSED
    if not re.fullmatch(r"[0-9a-f]{40}", args.sha):
        print("[CI] refused: malformed --sha", file=sys.stderr)
        return EXIT_REFUSED
    pr = int(args.pr)
    try:
        review = Path(args.body_file).read_text(encoding="utf-8")
        body = build_pr_body(review, args.sha, pr, cfg)
        action, cid, _ = _upsert(runner, args.repo, pr, val(cfg, "pr_marker_template").format(pr=pr),
                                 val(cfg, "bot_login"), body, args.dry_run, read=False)
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
    if not _validate_target(args, cfg) or not re.fullmatch(r"[0-9]{1,15}", args.pr_comment_id):
        return EXIT_REFUSED
    issue = find_issue_number(env.get("PR_BODY", ""))
    if issue is None:
        print("[CI] no Fixes/Closes #N line in the PR body; Issue mirror skipped.")
        _report(ok=True, skipped="no-issue-line")
        return EXIT_OK
    pr = int(args.pr)
    try:
        target = _gh_json(runner, ["api", "repos/%s/issues/%s" % (args.repo, issue)])
        if target.get("pull_request") is not None or target.get("state") != "open":
            print("[CI] #%s is not an open Issue; Issue mirror skipped." % issue)
            _report(ok=True, skipped="not-an-open-issue")
            return EXIT_OK
        source = _gh_json(runner, ["api", "repos/%s/issues/comments/%s" % (args.repo, args.pr_comment_id)])
        pr_marker = val(cfg, "pr_marker_template").format(pr=pr)
        if (source.get("user") or {}).get("login") != val(cfg, "bot_login") or pr_marker not in (source.get("body") or ""):
            raise ReviewError("the review comment %s is missing or not written by %s" % (args.pr_comment_id, val(cfg, "bot_login")))
        # The PR body is already sanitised and quoted by build_pr_body; drop only its marker line
        # and run sanitize again, which is idempotent, in case the comment was edited by hand.
        quoted = sanitize("\n".join(ln for ln in source["body"].splitlines() if pr_marker not in ln).strip(),
                          val(cfg, "secret_patterns"))
        issue_marker = val(cfg, "issue_marker_template").format(pr=pr)
        existing = select_comment(_list_comments(runner, args.repo, issue), issue_marker, val(cfg, "bot_login"))
        body = build_issue_body(quoted, args.author, pr, existing is None, cfg)
        action, cid, existed = _upsert(runner, args.repo, issue, issue_marker, val(cfg, "bot_login"), body,
                                       args.dry_run, existing=existing)
        if not existed and not args.dry_run:
            rc, out = runner(["api", "-X", "POST", "repos/%s/issues/%s/assignees" % (args.repo, issue), "--input", "-"],
                             json.dumps({"assignees": [args.author]}))
            if rc != 0:
                print("[CI] could not assign %s; the comment was still posted." % args.author)
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
