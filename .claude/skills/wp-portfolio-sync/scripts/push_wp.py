"""
push_wp.py - push the researcher's rendered portfolio sections into
WordPress pages via the REST API.

Stage: the final step of the migration (D1). Reads and writes
content.raw, never content.rendered (D8). The anti-fabrication gate runs
here before any network call, in both dry run and --apply (D6). Every
write is verified by a read-back GET (spec section 9, review focus 5).
"""
import argparse
import html
import json
import os
import re
import sys

import yaml

from render import PHASE1_RENDERERS, load_render_settings, render_entry
from verify_titles import verify_mapping
from wp_common import (
    configure_streams,
    client_from_config,
    get_path,
    make_session,
    render_block,
    site_base,
)
from wp_config import load_config
from wp_errors import WpRefusal, WpSyncError, WpWriteUnconfirmed, exit_code_for
from wp_paths import contained_path, resolve_data_dir


def validate_mapping(mapping):
    """
    --------------------------------------------------------------------------
    Purpose:
        Validate a parsed mapping.yaml document before it drives any push.

    Inputs:
        mapping (dict): the parsed mapping.yaml document.

    Outputs:
        none.

    Raises:
        WpRefusal: naming the entry index, for an empty entries list; a
        missing key required by the entry's mode; a non-int page_id; an
        unknown mode; renderer "phq" (D2); a renderer outside
        PHASE1_RENDERERS; a distinctions entry with no valid subkey; a
        duplicate (page_id, marker) pair across the whole mapping; a
        'replace' page shared with another entry; or a public_path not
        starting with "/".
    --------------------------------------------------------------------------
    """
    entries = mapping.get("entries")
    if not entries or not isinstance(entries, list):
        raise WpRefusal("mapping.yaml: 'entries' must be a non-empty list")
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise WpRefusal("entry %d: must be a mapping, got %s" % (index, type(entry).__name__))

    page_id_counts = {}
    for entry in entries:
        page_id_counts[entry.get("page_id")] = page_id_counts.get(entry.get("page_id"), 0) + 1

    seen_pairs = set()
    for index, entry in enumerate(entries):
        prefix = "entry %d" % index
        if not isinstance(entry.get("cv_path"), str) or not entry["cv_path"]:
            raise WpRefusal("%s: missing or invalid 'cv_path'" % prefix)
        page_id = entry.get("page_id")
        if not isinstance(page_id, int) or isinstance(page_id, bool):
            raise WpRefusal("%s: 'page_id' must be an int" % prefix)
        mode = entry.get("mode")
        if mode not in ("markers", "replace", "split"):
            raise WpRefusal("%s: unknown mode %r" % (prefix, mode))

        if mode == "markers":
            marker = entry.get("marker")
            if not isinstance(marker, str) or not marker:
                raise WpRefusal("%s: mode 'markers' requires 'marker'" % prefix)
            pair = (page_id, marker)
            if pair in seen_pairs:
                raise WpRefusal("%s: duplicate (page_id, marker) pair %r" % (prefix, pair))
            seen_pairs.add(pair)
        elif mode == "split":
            renderer = entry.get("renderer")
            if renderer == "phq":
                raise WpRefusal(
                    "%s: renderer 'phq' is refused: supervision is published from ThesisTracker, "
                    "never from the CV XML (D2)" % prefix
                )
            if renderer not in PHASE1_RENDERERS:
                raise WpRefusal("%s: unknown renderer %r (expected one of %s)" % (prefix, renderer, PHASE1_RENDERERS))
            if renderer == "distinctions" and entry.get("subkey") not in ("prix", "contributions_cles"):
                raise WpRefusal("%s: distinctions entry requires subkey 'prix' or 'contributions_cles'" % prefix)
            for key in ("recent_marker", "history_marker"):
                value = entry.get(key)
                if not isinstance(value, str) or not value:
                    raise WpRefusal("%s: mode 'split' requires %r" % (prefix, key))
                pair = (page_id, value)
                if pair in seen_pairs:
                    raise WpRefusal("%s: duplicate (page_id, marker) pair %r" % (prefix, pair))
                seen_pairs.add(pair)
        else:  # replace
            if page_id_counts.get(page_id, 0) > 1:
                raise WpRefusal("%s: page %s is used by a 'replace' entry and by another entry" % (prefix, page_id))

        public_path = entry.get("public_path")
        if public_path is not None and not str(public_path).startswith("/"):
            raise WpRefusal("%s: public_path must start with '/'" % prefix)


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
    return pattern.sub(start + "\n" + block + "\n" + end, content)


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


def section_size(data, entry):
    """
    --------------------------------------------------------------------------
    Purpose:
        Count the records of a mapping entry's section, so an empty one can
        be refused before it is pushed over real content.

    Inputs:
        data (dict): the parsed cihr.json document.
        entry (dict): one mapping.yaml entry.

    Outputs:
        size (int): the record count, including a distinctions entry's own
        subkey; 1 for a non-empty, non-list node (e.g. a generic dotted
        path from parse_cv.py), 0 for an absent or empty one.
    --------------------------------------------------------------------------
    """
    try:
        node = get_path(data, entry["cv_path"])
    except KeyError:
        return 0
    if entry.get("mode") == "split" and entry["cv_path"] == "distinctions":
        node = (node or {}).get(entry.get("subkey"), [])
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
            node = get_path(data, cv_path)
            page["blocks"].append({"marker": entry["marker"], "label": label, "html": render_block(node, entry.get("heading", ""))})
        else:  # replace
            node = get_path(data, cv_path)
            page["blocks"].append({"marker": None, "label": label, "html": render_block(node, entry.get("heading", ""))})

    return [pages_by_id[page_id] for page_id in order]


def _process_page(client, page, apply):
    page_id = page["page_id"]
    route = "/wp-json/wp/v2/pages/%d" % page_id
    notes = list(page.get("notes", []))

    try:
        body = client.get_json(route, {"context": "edit", "_fields": "content"})
    except WpSyncError as exc:
        return {"page_id": page_id, "labels": page["labels"], "status": "failed", "blocks": [], "error": str(exc), "notes": notes}

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

    status_code = None
    body_text = ""
    try:
        status_code, body_text = client.put_json(route, {"content": working})
    except WpWriteUnconfirmed as exc:
        notes = notes + ["write unconfirmed: %s" % exc]

    if status_code is not None and status_code not in (200, 201):
        return {
            "page_id": page_id,
            "labels": page["labels"],
            "status": "failed",
            "blocks": block_reports,
            "error": "HTTP %s: %s" % (status_code, (body_text or "")[:200]),
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


def run_push(client, pages, apply):
    """
    --------------------------------------------------------------------------
    Purpose:
        Push every planned page: one GET, at most one PUT, and (when a PUT
        was attempted) one read-back GET, per page.

    Inputs:
        client: a WpClient (or a fake with the same get_json/put_json contract).
        pages (list[dict]): plan_pages' result.
        apply (bool): False means dry run - no PUT is ever sent.

    Outputs:
        results (list[dict]): one {"page_id", "labels", "status", "blocks",
        "error", "notes"} per page. status is one of "unchanged",
        "would-change", "updated" or "failed".
    --------------------------------------------------------------------------
    """
    return [_process_page(client, page, apply) for page in pages]


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
                if section_size(data, entry) == 0:
                    raise WpRefusal(
                        "entry %r (page %s) has an empty section; pass --allow-empty-section to override"
                        % (entry["cv_path"], entry["page_id"])
                    )

        gate_report = verify_mapping(data, mapping, data_dir, settings)
        if gate_report["unapproved"]:
            for cv_path, title in gate_report["unapproved"]:
                print("TITRE NON APPROUVE [%s] %s" % (cv_path, title), file=sys.stderr)
            raise WpRefusal("%d unapproved title(s); push refused" % len(gate_report["unapproved"]))

        site = site_base(mapping, environ)
        if client_factory is not None:
            client = client_factory(data_dir, environ, site)
        else:
            client = client_from_config(make_session(data_dir, environ), site, load_config())
    except WpRefusal as exc:
        print("REFUS: %s" % exc, file=sys.stderr)
        return exit_code_for(exc)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print("ERREUR: %s" % exc, file=sys.stderr)
        return 1

    pages = plan_pages(mapping, data, data_dir, settings)
    results = run_push(client, pages, args.apply)

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
