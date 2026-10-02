"""
discover.py - list WordPress pages (id, slug, title, link) via the REST
API, so their ids can be filled into config/mapping.yaml's page_id values.

Stage: a one-time setup step (agent Step 2, first run only). Never called
by preview.py or push_wp.py.
"""
import argparse
import json
import os
import sys

import yaml

from wp_common import configure_streams, client_from_config, make_session, site_base
from wp_config import CONFIG_NAME, config_value, load_config
from wp_errors import WpRefusal, WpSyncError, exit_code_for
from wp_paths import contained_path, resolve_data_dir


def fetch_pages(client, per_page):
    """
    --------------------------------------------------------------------------
    Purpose:
        List every WordPress page, paginating until a batch is empty or
        shorter than per_page.

    Inputs:
        client: a WpClient (or a fake with the same get_json contract).
        per_page (int): the page size requested per call.

    Outputs:
        pages (list[dict]): one {"id", "slug", "title", "link"} per page,
        "title" being title.rendered.
    --------------------------------------------------------------------------
    """
    pages = []
    page_number = 1
    while True:
        batch = client.get_json(
            "/wp-json/wp/v2/pages", {"per_page": per_page, "page": page_number, "_fields": "id,slug,title,link"}
        )
        if not batch:
            break
        pages.extend({"id": p["id"], "slug": p["slug"], "title": p["title"]["rendered"], "link": p["link"]} for p in batch)
        if len(batch) < per_page:
            break
        page_number += 1
    return pages


def main(argv=None, environ=None, client_factory=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        CLI entry point: discover every WordPress page and write it as JSON.

    Inputs:
        argv (list[str] or None): CLI arguments; None reads sys.argv.
        environ (Mapping[str, str] or None): the process environment;
        None reads os.environ (tests inject a fake).
        client_factory (callable or None): when given, called as
        client_factory(data_dir, environ, site) to build the HTTP client.

    Outputs:
        exit_code (int): 0 on success, 1 on a WpSyncError (a 401 included),
        2 on a refusal by design.
    --------------------------------------------------------------------------
    """
    configure_streams()
    environ = environ if environ is not None else os.environ
    parser = argparse.ArgumentParser(description="Discover WordPress pages for mapping.yaml.")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--site")
    parser.add_argument("--out", default="config/pages.json")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        data_dir = resolve_data_dir(args.data_dir)
        out_path = contained_path(data_dir, args.out)
        mapping_file = contained_path(data_dir, "config/mapping.yaml")
        mapping = None
        if mapping_file.is_file():
            with open(mapping_file, "r", encoding="utf-8") as handle:
                mapping = yaml.safe_load(handle)
        site = site_base(mapping, environ, args.site)
        config = load_config()
        per_page = config_value(config, "rest.per_page", CONFIG_NAME)
    except WpRefusal as exc:
        print("REFUS: %s" % exc, file=sys.stderr)
        return exit_code_for(exc)

    if client_factory is not None:
        client = client_factory(data_dir, environ, site)
    else:
        client = client_from_config(make_session(data_dir, environ), site, config)

    try:
        pages = fetch_pages(client, per_page)
    except WpSyncError as exc:
        print("ERREUR: %s" % exc, file=sys.stderr)
        return 1

    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(pages, handle, ensure_ascii=False, indent=2)

    print("%d pages -> %s" % (len(pages), out_path), file=sys.stderr)
    for p in pages:
        print("  %5s  %-30s %s" % (p["id"], p["slug"], p["title"]), file=sys.stderr)

    if args.json:
        print(json.dumps({"out": str(out_path), "count": len(pages), "pages": pages}, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    sys.exit(main())
