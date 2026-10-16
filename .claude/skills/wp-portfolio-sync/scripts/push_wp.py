"""
push_wp.py - push the researcher's rendered portfolio sections into
WordPress pages via the REST API.

Stage: the final step of the migration (D1). Reads and writes
content.raw, never content.rendered (D8). The anti-fabrication gate runs
here before any network call, in both dry run and --apply (D6). Every
write is verified by a read-back GET (spec section 9, review focus 5).
"""
import argparse
import datetime
import html
import json
import os
import re
import sys

import yaml

from render import load_render_settings, render_entry, split_entry_items, validate_mapping
from verify_titles import verify_mapping
from wp_common import (
    atomic_write_text,
    configure_streams,
    client_from_config,
    error_report,
    get_path,
    make_session,
    render_block,
    site_base,
)
from wp_config import CONFIG_NAME, config_value, load_config
from wp_errors import WpRefusal, WpSyncError, WpWriteUnconfirmed, exit_code_for
from wp_paths import contained_path, resolve_data_dir


def block_inner(content, marker):
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the current text between one cvsync marker pair.

    Inputs:
        content (str): the page's current raw content.
        marker (str): the marker name.

    Outputs:
        inner (str or None): the text between the markers when the pair
        occurs exactly once, else None (ambiguous or absent).
    --------------------------------------------------------------------------
    """
    start = "<!-- cvsync:%s -->" % marker
    end = "<!-- /cvsync:%s -->" % marker
    pattern = re.compile(re.escape(start) + r"(.*?)" + re.escape(end), re.DOTALL)
    matches = pattern.findall(content)
    if len(matches) == 1:
        return matches[0]
    return None


def replace_between_markers(content, marker, block):
    """
    --------------------------------------------------------------------------
    Purpose:
        Replace the text between one cvsync marker pair with a new block.

    Inputs:
        content (str): the page's current raw content.
        marker (str): the marker name.
        block (str): the new HTML to place between the markers.

    Outputs:
        new_content (str): content with the marker pair's inner text replaced.

    Raises:
        WpSyncError: the marker pair occurs zero times or more than once,
        naming the marker.
    --------------------------------------------------------------------------
    """
    start = "<!-- cvsync:%s -->" % marker
    end = "<!-- /cvsync:%s -->" % marker
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
    count = len(pattern.findall(content))
    if count != 1:
        raise WpSyncError(
            "markers %r occur %d time(s) in the page (expected exactly 1). Add\n  %s\n  ...\n  %s\n"
            "at the intended spot, then retry." % (marker, count, start, end)
        )
    replacement = start + "\n" + block + "\n" + end
    return pattern.sub(lambda _match: replacement, content)


def normalize_block(text):
    """
    --------------------------------------------------------------------------
    Purpose:
        Normalise a block of text for a change comparison that ignores
        line-ending style and surrounding whitespace.

    Inputs:
        text (str or None): the text to normalise.

    Outputs:
        normalised (str): "" for None, else \\r\\n -> \\n, then stripped.
    --------------------------------------------------------------------------
    """
    return (text or "").replace("\r\n", "\n").strip()


def section_size(data, entry, data_dir, settings):
    """
    --------------------------------------------------------------------------
    Purpose:
        Count the records of a mapping entry's section, so an empty one can
        be refused before it is pushed over real content. For a split-mode
        entry this counts records AFTER extras/exclusions/status filtering
        (M1, PR #50 review): a raw, non-empty section that filtering empties
        must read as empty, or the guard never catches it and the live page
        is overwritten with a boilerplate "Cumul : 0 subventions" block.
        markers/replace entries have no such pipeline, so they still count
        the raw node.

    Inputs:
        data (dict): the parsed cihr.json document.
        entry (dict): one mapping.yaml entry.
        data_dir (Path): the resolved researcher data folder (read by the
        split-mode filter for config/exclusions.yaml and *_extra.yaml).
        settings (render.RenderSettings): carries excluded_funding_statuses.

    Outputs:
        size (int): the record count, including a distinctions entry's own
        subkey; 1 for a non-empty, non-list node (e.g. a generic dotted
        path from parse_cv.py), 0 for an absent or empty one.

    Raises:
        WpRefusal: for a split-mode entry, transitively from
        split_entry_items -> _validate_extra_items (M3) when the entry's
        *_extra.yaml is malformed. Every caller of this function must
        catch WpRefusal (code-review finding, PR #50 round 3: an
        unguarded call site is exactly how this was missed once already).
    --------------------------------------------------------------------------
    """
    if entry.get("mode") == "split":
        if entry["cv_path"] not in data:
            return 0
        items, _notes = split_entry_items(entry, data, data_dir, settings)
        return len(items)
    try:
        node = get_path(data, entry["cv_path"])
    except KeyError:
        return 0
    if isinstance(node, list):
        return len(node)
    return 1 if node else 0


def plan_pages(mapping, data, data_dir, settings):
    """
    --------------------------------------------------------------------------
    Purpose:
        Render every mapping entry and group the resulting blocks by page,
        in order of first appearance, so each page gets exactly one GET,
        one PUT and one read-back GET regardless of how many entries
        target it.

    Inputs:
        mapping (dict): the validated mapping.yaml document.
        data (dict): the parsed cihr.json document.
        data_dir (Path): the resolved researcher data folder.
        settings: a render.RenderSettings.

    Outputs:
        pages (list[dict]): one {"page_id", "labels", "blocks", "notes"}
        per page, "blocks" a list of {"marker", "label", "html"}.
    --------------------------------------------------------------------------
    """
    pages_by_id = {}
    order = []
    for entry in mapping.get("entries", []):
        page_id = entry["page_id"]
        if page_id not in pages_by_id:
            pages_by_id[page_id] = {"page_id": page_id, "labels": [], "blocks": [], "notes": []}
            order.append(page_id)
        page = pages_by_id[page_id]
        cv_path = entry["cv_path"]
        subkey = entry.get("subkey")
        label = cv_path + (":" + subkey if subkey else "")
        page["labels"].append(label)
        mode = entry.get("mode")

        if mode == "split":
            recent, history, notes = render_entry(entry, data, data_dir, settings)
            page["notes"].extend("%s: %s" % (label, note) for note in notes)
            page["blocks"].append({"marker": entry["recent_marker"], "label": label + ":recent", "html": recent})
            # The history marker is always planned, even when history is empty
            # (an exclusion or a changed ref_year can empty it between runs):
            # otherwise a block already populated by an earlier push is never
            # revisited and stays stale on the live page indefinitely.
            if history.strip():
                heading = entry.get("history_heading", "Historique")
                history_html = "<h3>%s</h3>\n%s" % (html.escape(heading), history)
            else:
                history_html = ""
            page["blocks"].append({"marker": entry["history_marker"], "label": label + ":history", "html": history_html})
        elif mode == "markers":
            try:
                node = get_path(data, cv_path)
            except KeyError:
                node = None
            page["blocks"].append({"marker": entry["marker"], "label": label, "html": render_block(node, entry.get("heading", ""))})
        else:  # replace
            try:
                node = get_path(data, cv_path)
            except KeyError:
                node = None
            page["blocks"].append({"marker": None, "label": label, "html": render_block(node, entry.get("heading", ""))})

    return [pages_by_id[page_id] for page_id in order]


def _utc_now():
    """
    --------------------------------------------------------------------------
    Purpose:
        The current time in UTC, as an aware datetime (L4, PR #50 review):
        datetime.datetime.utcnow() is deprecated since 3.12 and returns a
        naive datetime that is easy to mix up with local time by accident.

    Inputs:
        none

    Outputs:
        now (datetime.datetime): timezone-aware, UTC.
    --------------------------------------------------------------------------
    """
    return datetime.datetime.now(datetime.timezone.utc)


def _write_backup(data_dir, page_id, raw_content, now):
    """
    --------------------------------------------------------------------------
    Purpose:
        Snapshot a page's content.raw exactly as it was read, before any
        PUT touches it (M5, PR #50 review: a hand-edit overwritten with no
        warning had no way back).

    Inputs:
        data_dir (Path): the resolved researcher data folder.
        page_id (int): the WordPress page id.
        raw_content (str): the page's content.raw before this push's edits.
        now (callable): takes no arguments, returns an object with
        strftime (tests inject a fixed one; _utc_now by default - R19:
        never read directly inside the logic under test).

    Outputs:
        path (Path): the backup file written, under
        <data_dir>/backups/page-<page_id>-<timestamp>.html.
    --------------------------------------------------------------------------
    """
    backups_dir = contained_path(data_dir, "backups")
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = now().strftime("%Y%m%dT%H%M%SZ")
    path = backups_dir / ("page-%d-%s.html" % (page_id, stamp))
    atomic_write_text(path, raw_content)
    return path


def _process_page(client, page, apply, data_dir=None, now=None, snippet_chars=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Push one planned page: GET its current content, apply every block,
        and (in --apply) PUT the result and verify it with a read-back GET.
        Before writing, re-checks the page's modified_gmt against the value
        from the initial GET and refuses rather than overwriting if it
        changed - someone edited the page while this push was running (Q6,
        PR #50 review, owner decision 2026-10-16). A pre-image backup is
        taken right before the PUT regardless (M5).

    Inputs:
        client: a WpClient (or a fake with the same get_json/put_json contract).
        page (dict): one plan_pages() entry ("page_id", "labels", "blocks", "notes").
        apply (bool): False means dry run - no PUT, no concurrent-edit
        re-check, no backup; the function stops at "would-change".
        data_dir (Path or None): when given, enables the pre-image backup
        (M5); None skips it (no researcher data folder at hand, e.g. a test).
        now (callable or None): see _write_backup; None uses the real clock.
        snippet_chars (int or None): how much of a failed PUT's response
        body to keep in the error message (config key
        http.error_body_snippet_chars). None loads it here directly, for a
        caller with no config already in hand (e.g. a test); main() always
        passes the value it already loaded in its own try/except WpRefusal
        block, so a missing key is refused before any page is processed
        rather than raised uncaught here (code-review finding, PR #50
        round 3).

    Outputs:
        result (dict): {"page_id", "labels", "status", "blocks", "error",
        "notes"}. status is one of "unchanged", "would-change", "updated"
        or "failed" - including a page changed concurrently, a replace
        error, a dropped read, or a write that failed its read-back.
    --------------------------------------------------------------------------
    """
    page_id = page["page_id"]
    route = "/wp-json/wp/v2/pages/%d" % page_id
    notes = list(page.get("notes", []))

    try:
        body = client.get_json(route, {"context": "edit", "_fields": "content,modified_gmt"})
    except WpSyncError as exc:
        return {"page_id": page_id, "labels": page["labels"], "status": "failed", "blocks": [], "error": str(exc), "notes": notes}

    initial_modified_gmt = (body or {}).get("modified_gmt")
    raw = ((body or {}).get("content") or {}).get("raw")
    if raw is None:
        return {
            "page_id": page_id,
            "labels": page["labels"],
            "status": "failed",
            "blocks": [],
            "error": "the credential lacks edit rights: content.raw is absent (rendered content is never used)",
            "notes": notes,
        }

    working = raw
    block_reports = []
    any_changed = False
    replace_error = None
    for block in page["blocks"]:
        marker = block["marker"]
        new_html = block["html"]
        old_inner = working if marker is None else (block_inner(working, marker) or "")
        changed = normalize_block(old_inner) != normalize_block(new_html)
        any_changed = any_changed or changed
        block_reports.append({"marker": marker, "label": block["label"], "old_chars": len(old_inner), "new_chars": len(new_html), "changed": changed})
        if marker is None:
            working = new_html
        else:
            try:
                working = replace_between_markers(working, marker, new_html)
            except WpSyncError as exc:
                replace_error = str(exc)
                break

    if replace_error is not None:
        return {"page_id": page_id, "labels": page["labels"], "status": "failed", "blocks": block_reports, "error": replace_error, "notes": notes}

    if not any_changed:
        return {"page_id": page_id, "labels": page["labels"], "status": "unchanged", "blocks": block_reports, "error": None, "notes": notes}

    if not apply:
        return {"page_id": page_id, "labels": page["labels"], "status": "would-change", "blocks": block_reports, "error": None, "notes": notes}

    if initial_modified_gmt is None:
        notes = notes + ["modified_gmt unavailable - concurrent-edit check skipped"]
    else:
        try:
            recheck_body = client.get_json(route, {"_fields": "modified_gmt"})
        except WpSyncError as exc:
            return {"page_id": page_id, "labels": page["labels"], "status": "failed", "blocks": block_reports, "error": "concurrent-edit re-check failed: %s" % exc, "notes": notes}
        current_modified_gmt = (recheck_body or {}).get("modified_gmt")
        if current_modified_gmt != initial_modified_gmt:
            return {
                "page_id": page_id,
                "labels": page["labels"],
                "status": "failed",
                "blocks": block_reports,
                "error": (
                    "page changed since it was read (modified_gmt %r -> %r); someone edited it "
                    "while this push ran - refusing to overwrite, retry the push"
                    % (initial_modified_gmt, current_modified_gmt)
                ),
                "notes": notes,
            }

    if data_dir is not None:
        backup_path = _write_backup(data_dir, page_id, raw, now or _utc_now)
        notes = notes + ["pre-image backed up to %s" % backup_path]

    status_code = None
    body_text = ""
    try:
        status_code, body_text = client.put_json(route, {"content": working})
    except WpWriteUnconfirmed as exc:
        notes = notes + ["write unconfirmed: %s" % exc]

    if status_code is not None and status_code not in (200, 201):
        if snippet_chars is None:
            snippet_chars = config_value(load_config(), "http.error_body_snippet_chars", CONFIG_NAME)
        return {
            "page_id": page_id,
            "labels": page["labels"],
            "status": "failed",
            "blocks": block_reports,
            "error": "HTTP %s: %s" % (status_code, (body_text or "")[:snippet_chars]),
            "notes": notes,
        }

    try:
        readback_body = client.get_json(route, {"context": "edit", "_fields": "content"})
    except WpSyncError as exc:
        return {"page_id": page_id, "labels": page["labels"], "status": "failed", "blocks": block_reports, "error": "read-back failed: %s" % exc, "notes": notes}

    readback_raw = ((readback_body or {}).get("content") or {}).get("raw")
    verified = readback_raw is not None
    if verified:
        check_content = readback_raw
        for block in page["blocks"]:
            marker = block["marker"]
            actual = check_content if marker is None else (block_inner(check_content, marker) or "")
            if normalize_block(actual) != normalize_block(block["html"]):
                verified = False
                break

    if not verified:
        return {"page_id": page_id, "labels": page["labels"], "status": "failed", "blocks": block_reports, "error": "write not verified by read-back", "notes": notes}

    return {"page_id": page_id, "labels": page["labels"], "status": "updated", "blocks": block_reports, "error": None, "notes": notes}


def run_push(client, pages, apply, data_dir=None, now=None, snippet_chars=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Push every planned page: one GET, at most one PUT, and (when a PUT
        was attempted) one read-back GET, per page.

    Inputs:
        client: a WpClient (or a fake with the same get_json/put_json contract).
        pages (list[dict]): plan_pages' result.
        apply (bool): False means dry run - no PUT is ever sent.
        data_dir (Path or None): when given, content.raw is snapshotted to
        <data_dir>/backups/ before each PUT (M5); None skips the backup
        (a caller with no researcher data folder at hand, e.g. a test).
        now (callable or None): see _write_backup; None uses the real clock.
        snippet_chars (int or None): forwarded to _process_page; see its
        own docstring. main() always supplies it.

    Outputs:
        results (list[dict]): one {"page_id", "labels", "status", "blocks",
        "error", "notes"} per page. status is one of "unchanged",
        "would-change", "updated" or "failed".
    --------------------------------------------------------------------------
    """
    return [
        _process_page(client, page, apply, data_dir=data_dir, now=now, snippet_chars=snippet_chars)
        for page in pages
    ]


def main(argv=None, environ=None, client_factory=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        CLI entry point: validate, gate, then push the researcher's
        portfolio sections to WordPress.

    Inputs:
        argv (list[str] or None): CLI arguments; None reads sys.argv.
        environ (Mapping[str, str] or None): the process environment;
        None reads os.environ (tests inject a fake).
        client_factory (callable or None): when given, called as
        client_factory(data_dir, environ, site) to build the HTTP client;
        tests use this to inject a fake client with no network at all.

    Outputs:
        exit_code (int): 0 on success, 1 if any page failed (a WpSyncError
        at setup also returns 1), 2 on a refusal by design. Every refusal
        (bad mapping, --apply without --yes, an empty section, a gate
        failure) happens before any client is built.
    --------------------------------------------------------------------------
    """
    configure_streams()
    environ = environ if environ is not None else os.environ
    parser = argparse.ArgumentParser(description="Push the researcher's CV content into WordPress pages.")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--cv", default="cihr.json")
    parser.add_argument("--mapping", default="config/mapping.yaml")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--allow-empty-section", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    def _fail(line, message, code):
        print(line, file=sys.stderr)
        if args.json:
            print(json.dumps(error_report(message, code), ensure_ascii=False))
        return code

    try:
        data_dir = resolve_data_dir(args.data_dir)
        mapping_file = contained_path(data_dir, args.mapping)
        cv_file = contained_path(data_dir, args.cv)
        if not mapping_file.is_file():
            raise WpRefusal("mapping file not found: %s" % mapping_file)
        if not cv_file.is_file():
            raise WpRefusal("CV JSON file not found: %s" % cv_file)
        with open(mapping_file, "r", encoding="utf-8") as handle:
            mapping = yaml.safe_load(handle)
        if not isinstance(mapping, dict):
            raise WpRefusal("mapping.yaml does not parse to a mapping: %s" % mapping_file)
        settings = load_render_settings(mapping, str(mapping_file))
        validate_mapping(mapping)
        with open(cv_file, "r", encoding="utf-8") as handle:
            data = json.load(handle)

        if args.apply and not args.yes:
            raise WpRefusal("--apply requires --yes")

        if not args.allow_empty_section:
            for entry in mapping["entries"]:
                if section_size(data, entry, data_dir, settings) == 0:
                    raise WpRefusal(
                        "entry %r (page %s) has an empty section; pass --allow-empty-section to override"
                        % (entry["cv_path"], entry["page_id"])
                    )

        gate_report = verify_mapping(data, mapping, data_dir, settings)
        if gate_report["unapproved"]:
            for cv_path, title in gate_report["unapproved"]:
                print("TITRE NON APPROUVE [%s] %s" % (cv_path, title), file=sys.stderr)
            raise WpRefusal("%d unapproved title(s); push refused" % len(gate_report["unapproved"]))

        config = load_config()
        snippet_chars = config_value(config, "http.error_body_snippet_chars", CONFIG_NAME)

        site = site_base(mapping, environ)
        if client_factory is not None:
            client = client_factory(data_dir, environ, site)
        else:
            client = client_from_config(make_session(data_dir, environ, require_nonce=True), site, config)
        pages = plan_pages(mapping, data, data_dir, settings)
    except WpRefusal as exc:
        return _fail("REFUS: %s" % exc, str(exc), exit_code_for(exc))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return _fail("ERREUR: %s" % exc, str(exc), 1)

    results = run_push(client, pages, args.apply, data_dir=data_dir, snippet_chars=snippet_chars)

    print("Site : %s  (--apply=%s)" % (site, "OUI" if args.apply else "non, simulation"), file=sys.stderr)
    for result in results:
        print("[page %s] %s: %s" % (result["page_id"], ", ".join(result["labels"]), result["status"]), file=sys.stderr)
        for note in result["notes"]:
            print("  note: %s" % note, file=sys.stderr)
        if result["error"]:
            print("  erreur: %s" % result["error"], file=sys.stderr)

    failed = any(r["status"] == "failed" for r in results)

    if args.json:
        print(
            json.dumps(
                {"site": site, "apply": args.apply, "gate": gate_report, "pages": results, "exit_code": 1 if failed else 0},
                ensure_ascii=False,
            )
        )

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
