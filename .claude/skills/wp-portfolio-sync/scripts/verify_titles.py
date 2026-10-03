"""
verify_titles.py - the anti-fabrication gate (incident 2026-09-30).

Stage: called by push_wp.py before any network call, in both dry run and
apply (D6). Checks, at the <strong> level, that every title a renderer
produced exists in an approved source: the parsed CV, the matching
renderer's own extras file, or a static seed (config/historique/*.md).
"""
import argparse
import html
import json
import re
import sys

import yaml

from render import item_title, load_render_settings, render_entry
from wp_common import configure_streams, norm_ws
from wp_errors import WpRefusal, WpSyncError, exit_code_for
from wp_paths import contained_path, resolve_data_dir

_STRONG_RE = re.compile(r"<strong>(.*?)</strong>", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_BOLD_MD_RE = re.compile(r"\*\*(.+?)\*\*")

_EXTRA_FILE_FOR_RENDERER = {
    "implications": "config/implications_extra.yaml",
    "services": "config/services_extra.yaml",
}


def seed_titles(markdown):
    """
    --------------------------------------------------------------------------
    Purpose:
        Extract the titles a static history seed file (config/historique/*.md)
        already approves: bold spans, table cells, list items and headings.

    Inputs:
        markdown (str): the raw Markdown source of a history_static file.

    Outputs:
        titles (set[str]): the normalised texts found, "" discarded.
    --------------------------------------------------------------------------
    """
    out = set()
    for raw in (markdown or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue
            for cell in cells:
                out.add(norm_ws(_BOLD_MD_RE.sub(r"\1", cell)))
            continue
        if line.startswith("#"):
            out.add(norm_ws(line.lstrip("#").strip()))
            continue
        if line.startswith("- "):
            out.add(norm_ws(_BOLD_MD_RE.sub(r"\1", line[2:])))
            continue
        for match in _BOLD_MD_RE.finditer(line):
            out.add(norm_ws(match.group(1)))
    out.discard("")
    return out


def approved_titles(data, entry, data_dir):
    """
    --------------------------------------------------------------------------
    Purpose:
        Compute the set of titles approved for one mapping entry: every
        record's own title from the CV JSON, plus (for implications) its
        organisation, plus the matching renderer's own extras file only
        (the historical bug: a student name approving a grant title).

    Inputs:
        entry (dict): one mapping.yaml entry.
        data (dict): the parsed cihr.json document.
        data_dir (Path): the resolved researcher data folder.

    Outputs:
        approved (set[str]): normalised titles, "" discarded.
    --------------------------------------------------------------------------
    """
    cv_path = entry["cv_path"]
    subkey = entry.get("subkey")
    section = data.get(cv_path)
    if cv_path == "distinctions":
        items = (section or {}).get(subkey, [])
    else:
        items = section or []

    approved = set()
    for item in items:
        approved.add(item_title(cv_path, item, subkey))
        if cv_path == "implications":
            approved.add(norm_ws(item.get("organisation", "")))

    renderer = entry.get("renderer")
    extra_file = _EXTRA_FILE_FOR_RENDERER.get(renderer)
    if renderer == "distinctions" and subkey == "prix":
        extra_file = "config/distinctions_extra.yaml"
    if extra_file:
        resolved = contained_path(data_dir, extra_file)
        if resolved.is_file():
            with open(resolved, "r", encoding="utf-8") as handle:
                extra_items = yaml.safe_load(handle) or []
            for item in extra_items:
                approved.add(item_title(cv_path, item, subkey))
                if cv_path == "implications":
                    approved.add(norm_ws(item.get("organisation", "")))

    approved.discard("")
    return approved


def find_unapproved(rendered_html, approved, seed=frozenset()):
    """
    --------------------------------------------------------------------------
    Purpose:
        Find every <strong> span of rendered HTML whose text is not an
        approved title or a seed title.

    Inputs:
        rendered_html (str): the HTML a renderer produced.
        approved (set[str]): approved_titles' result.
        seed (frozenset[str]): seed_titles' result, for a static seed file.

    Outputs:
        unapproved (list[str]): titles in neither set, in document order.
        A cumul label ("Cumul :", ...) is skipped because it is empty or
        ends with ":", never a fabricated title.
    --------------------------------------------------------------------------
    """
    bad = []
    for raw in _STRONG_RE.findall(rendered_html):
        text = norm_ws(_TAG_RE.sub("", html.unescape(raw)))
        if not text or text.endswith(":"):
            continue
        if text in approved or text in seed:
            continue
        bad.append(text)
    return bad


def verify_mapping(data, mapping, data_dir, settings):
    """
    --------------------------------------------------------------------------
    Purpose:
        Run the gate over every split entry of a mapping document.

    Inputs:
        data (dict): the parsed cihr.json document.
        mapping (dict): the parsed mapping.yaml document.
        data_dir (Path): the resolved researcher data folder.
        settings: a render.RenderSettings.

    Outputs:
        report (dict): {"unapproved": [[cv_path, title], ...],
        "not_covered": [cv_path, ...]}. A markers/replace entry is
        not_covered rather than checked, since its generic HTML puts JSON
        keys in <strong>. A render error is recorded as
        [cv_path, "<render failed: message>"].
    --------------------------------------------------------------------------
    """
    unapproved = []
    not_covered = []
    for entry in mapping.get("entries", []):
        cv_path = entry["cv_path"]
        if entry.get("mode") != "split":
            not_covered.append(cv_path)
            continue

        static_text = ""
        history_static = entry.get("history_static")
        if history_static:
            try:
                resolved = contained_path(data_dir, history_static)
            except WpRefusal:
                resolved = None
            if resolved is not None and resolved.is_file():
                static_text = resolved.read_text(encoding="utf-8")
        seed = seed_titles(static_text)

        try:
            recent, history, _notes = render_entry(entry, data, data_dir, settings)
        except (WpSyncError, WpRefusal) as exc:
            unapproved.append([cv_path, "<render failed: %s>" % exc])
            continue

        approved = approved_titles(data, entry, data_dir)
        for title in find_unapproved(recent + "\n" + history, approved, seed):
            unapproved.append([cv_path, title])

    return {"unapproved": unapproved, "not_covered": not_covered}


def main(argv=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        CLI entry point for the gate: verify every rendered title against
        its approved sources.

    Inputs:
        argv (list[str] or None): CLI arguments; None reads sys.argv.

    Outputs:
        exit_code (int): 0 when no title is unapproved, 1 otherwise, 2 on a
        refusal by design (missing/invalid mapping or CV JSON).
    --------------------------------------------------------------------------
    """
    configure_streams()
    parser = argparse.ArgumentParser(description="Verify every rendered title against approved sources.")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--cv", default="cihr.json")
    parser.add_argument("--mapping", default="config/mapping.yaml")
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
        with open(cv_file, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except WpRefusal as exc:
        print("REFUS: %s" % exc, file=sys.stderr)
        return exit_code_for(exc)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print("ERREUR: %s" % exc, file=sys.stderr)
        return 1

    report = verify_mapping(data, mapping, data_dir, settings)
    for cv_path, title in report["unapproved"]:
        print("TITRE NON APPROUVE [%s] %s" % (cv_path, title), file=sys.stderr)
    for cv_path in report["not_covered"]:
        print("non couvert par la verification : %s" % cv_path, file=sys.stderr)

    if args.json:
        print(json.dumps(report, ensure_ascii=False))

    return 1 if report["unapproved"] else 0


if __name__ == "__main__":
    sys.exit(main())
