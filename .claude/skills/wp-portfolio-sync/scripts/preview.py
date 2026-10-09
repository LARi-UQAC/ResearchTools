"""
preview.py - offline report of what push_wp.py would change. No network
call is ever made here.

Stage: the agent's Step 3, run before any --apply. Shows every entry's
target page, sizes, notes and the gate verdict, plus a stale-ref_year
warning.
"""
import argparse
import datetime
import json
import os
import sys

import yaml

from render import load_render_settings, render_entry
from verify_titles import verify_mapping
from wp_common import configure_streams, error_report, site_base
from wp_config import CONFIG_NAME, config_value, load_config
from wp_errors import WpRefusal, WpSyncError, exit_code_for
from wp_paths import contained_path, resolve_data_dir


def stale_ref_year_note(ref_year, today_year):
    """
    --------------------------------------------------------------------------
    Purpose:
        Warn when mapping.yaml's ref_year has fallen behind the current
        year, so the 6-year window does not drift silently (spec review
        focus 4).

    Inputs:
        ref_year (int): mapping.yaml's ref_year.
        today_year (int): the current year, injected by the caller (R19).

    Outputs:
        note (str or None): a message when ref_year < today_year, else None.
    --------------------------------------------------------------------------
    """
    if ref_year < today_year:
        return "ref_year (%d) is older than the current year (%d); update it in mapping.yaml" % (ref_year, today_year)
    return None


def main(argv=None, today_year=None, environ=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        CLI entry point: print what push_wp.py would change, with no
        network call.

    Inputs:
        argv (list[str] or None): CLI arguments; None reads sys.argv.
        today_year (int or None): injected current year for the stale-note
        check; None reads datetime.date.today().year once, here (R19).
        environ (Mapping[str, str] or None): the process environment;
        None reads os.environ.

    Outputs:
        exit_code (int): 0 when the gate is clean, 1 when it is not, 2 on a
        refusal by design.
    --------------------------------------------------------------------------
    """
    configure_streams()
    environ = environ if environ is not None else os.environ
    if today_year is None:
        today_year = datetime.date.today().year

    parser = argparse.ArgumentParser(description="Preview what push_wp.py would change. No network call.")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--cv", default="cihr.json")
    parser.add_argument("--mapping", default="config/mapping.yaml")
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
        with open(cv_file, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        site = site_base(mapping, environ)
        config = load_config()
        snippet_chars = config_value(config, "preview.snippet_chars", CONFIG_NAME)
    except WpRefusal as exc:
        return _fail("REFUS: %s" % exc, str(exc), exit_code_for(exc))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return _fail("ERREUR: %s" % exc, str(exc), 1)

    print("Site : %s" % site, file=sys.stderr)
    entries_report = []
    for entry in mapping.get("entries", []):
        mode = entry.get("mode")
        renderer = entry.get("renderer")
        notes = []
        recent_chars = history_chars = 0
        print(
            "[%s] -> page %s (mode=%s%s)"
            % (entry.get("cv_path"), entry.get("page_id"), mode, ", renderer=" + renderer if renderer else ""),
            file=sys.stderr,
        )
        if mode == "split":
            try:
                recent, history, notes = render_entry(entry, data, data_dir, settings)
                recent_chars, history_chars = len(recent), len(history)
                for label, block in (("RECENT", recent), ("HISTORIQUE", history)):
                    snippet = block[:snippet_chars].replace("\n", " ")
                    print(
                        "    %s (%d car.) : %s%s" % (label, len(block), snippet, "…" if len(block) > snippet_chars else ""),
                        file=sys.stderr,
                    )
            except (WpSyncError, WpRefusal) as exc:
                notes = ["render failed: %s" % exc]
                print("    ERREUR : %s" % exc, file=sys.stderr)
        for note in notes:
            print("    note : %s" % note, file=sys.stderr)
        entries_report.append(
            {
                "cv_path": entry.get("cv_path"),
                "page_id": entry.get("page_id"),
                "mode": mode,
                "renderer": renderer,
                "recent_chars": recent_chars,
                "history_chars": history_chars,
                "notes": notes,
            }
        )

    stale_note = stale_ref_year_note(settings.ref_year, today_year)
    notes_out = []
    if stale_note:
        print(stale_note, file=sys.stderr)
        notes_out.append(stale_note)

    try:
        gate_report = verify_mapping(data, mapping, data_dir, settings)
    except WpRefusal as exc:
        return _fail("REFUS: %s" % exc, str(exc), exit_code_for(exc))
    for cv_path, title in gate_report["unapproved"]:
        print("TITRE NON APPROUVE [%s] %s" % (cv_path, title), file=sys.stderr)

    if args.json:
        print(json.dumps({"site": site, "entries": entries_report, "gate": gate_report, "notes": notes_out}, ensure_ascii=False))

    return 1 if gate_report["unapproved"] else 0


if __name__ == "__main__":
    sys.exit(main())
