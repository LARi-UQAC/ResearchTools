"""
cv_inventory.py - CRUD over the durable master CV-contributions inventory.

Stage: the persistence layer the narrative-cv skill is built around. This
module never reaches the network and never calls Scopus or extract-contributions
itself - the calling agent runs those (bash), then hands ONE validated item at
a time to `add`. Keeping the network call outside this module is what makes
the module's own offline tests possible with no mocked HTTP (R20/R21).

The inventory is one YAML file, living in the external CV project directory
(never inside ResearchTools - R7), one entry per candidate contribution or
experience:

    schema_version: 1
    updated: "YYYY-MM-DD"
    items:
      - id: <stable slug, a citekey for a publication or a hand-chosen one>
        source: scopus | manual
        kind: publication | non_publication
        category: <one of contribution_types.json's categories[].id>
        title: <str>
        doi: <str or null>
        date: "YYYY" or "YYYY-MM"
        role: <str, the candidate's own role/contribution>
        contribution_summary: <str, one or two sentences>
        clienteles: [<clientele id>, ...]
        keywords: [<str>, ...]
        supervised_names: [<str>, ...]   # already carrying the '*' suffix
        coauthors_bold: [<str>, ...]     # names to bold in a citation
        used_in: [<competition slug>, ...]
        added: "YYYY-MM-DD"
        last_verified: "YYYY-MM-DD"

CLI: init | add | list | stats | mark-used. Every write is dry-run by default
except through an explicit apply (R16 spirit): `add`/`mark-used` refuse to
write unless the caller passes --yes, and print what would change otherwise.
"""
import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cv_common import CvDataError, load_contribution_types  # noqa: E402

SCHEMA_VERSION = 1
_DATE_RE = re.compile(r"^\d{4}(-\d{2})?$")
REQUIRED_ITEM_KEYS = (
    "id", "source", "kind", "category", "title", "date",
    "contribution_summary", "clienteles",
)


class InventoryError(Exception):
    """Raised when the inventory file or a candidate item is malformed."""


def _today():
    return date.today().isoformat()


def load_inventory(path):
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the inventory YAML, or synthesize an empty one if the file does
        not exist yet (a fresh inventory is a valid starting state, not an
        error).

    Inputs:
        path (str or Path): inventory YAML file

    Outputs:
        inventory (dict): {"schema_version", "updated", "items"}

    Raises:
        InventoryError: the file exists but is not a well-formed inventory
    --------------------------------------------------------------------------
    """
    target = Path(path)
    if not target.is_file():
        return {"schema_version": SCHEMA_VERSION, "updated": None, "items": []}
    with open(target, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict) or not isinstance(data.get("items", []), list):
        raise InventoryError("not a well-formed inventory (expected a mapping with an 'items' list): %s" % target)
    data.setdefault("schema_version", SCHEMA_VERSION)
    data.setdefault("items", [])
    return data


def save_inventory(path, inventory):
    """Write `inventory` back to `path`, stamping `updated` to today."""
    inventory["updated"] = _today()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        yaml.safe_dump(inventory, handle, allow_unicode=True, sort_keys=False)


def validate_item(item, known_category_ids, known_clientele_ids):
    """
    --------------------------------------------------------------------------
    Purpose:
        Check one candidate item against the closed vocabularies before it
        can be appended, so a typo'd category or clientele fails here rather
        than silently degrading a later selection or render step.

    Inputs:
        item (dict): the candidate item
        known_category_ids (set): valid contribution_types.json category ids
        known_clientele_ids (set): valid contribution_types.json clientele ids

    Outputs:
        None

    Raises:
        InventoryError: a required key is missing, or a value falls outside
            its closed vocabulary
    --------------------------------------------------------------------------
    """
    missing = [key for key in REQUIRED_ITEM_KEYS if not item.get(key) and item.get(key) != 0]
    if missing:
        raise InventoryError("item is missing required key(s): %s" % ", ".join(missing))
    if item["source"] not in ("scopus", "manual"):
        raise InventoryError("item.source must be 'scopus' or 'manual', got %r" % item["source"])
    if item["kind"] not in ("publication", "non_publication"):
        raise InventoryError("item.kind must be 'publication' or 'non_publication', got %r" % item["kind"])
    if item["category"] not in known_category_ids:
        raise InventoryError(
            "item.category %r is not in contribution_types.json (%s)"
            % (item["category"], ", ".join(sorted(known_category_ids))))
    if not _DATE_RE.match(str(item["date"])):
        raise InventoryError("item.date %r must be 'YYYY' or 'YYYY-MM'" % item["date"])
    clienteles = item["clienteles"]
    if not isinstance(clienteles, list) or not clienteles:
        raise InventoryError("item.clienteles must be a non-empty list")
    unknown = [c for c in clienteles if c not in known_clientele_ids]
    if unknown:
        raise InventoryError(
            "item.clienteles has unknown id(s) %s; known ids are %s"
            % (unknown, ", ".join(sorted(known_clientele_ids))))


def find_duplicate(inventory, item):
    """Return the existing item that collides with `item` on id or DOI, else None."""
    for existing in inventory["items"]:
        if existing.get("id") == item.get("id"):
            return existing
        doi = item.get("doi")
        if doi and existing.get("doi") == doi:
            return existing
    return None


def add_item(path, item, types_path=None, yes=False):
    """
    --------------------------------------------------------------------------
    Purpose:
        Validate and append one item to the inventory at `path`.

    Details:
        A duplicate (same id, or same non-empty DOI) is reported and refused
        rather than appended twice - the inventory is meant to be run
        repeatedly across grant cycles, and a silent duplicate would double
        an item's weight in every later selection.

    Inputs:
        path (str or Path): inventory YAML file
        item (dict): the candidate item (see module docstring for shape)
        types_path (str, Path or None): contribution_types.json override
        yes (bool): actually write; without it, validate and report only

    Outputs:
        result (dict): {"status": "added"|"duplicate"|"dry_run", "item": item,
                         "of": <existing item, when status == "duplicate">}

    Raises:
        InventoryError: the item fails validate_item()
    --------------------------------------------------------------------------
    """
    types = load_contribution_types(types_path)
    known_categories = {c["id"] for c in types["categories"]}
    known_clienteles = {c["id"] for c in types["clienteles"]}
    validate_item(item, known_categories, known_clienteles)

    inventory = load_inventory(path)
    duplicate = find_duplicate(inventory, item)
    if duplicate is not None:
        return {"status": "duplicate", "item": item, "of": duplicate}

    item.setdefault("used_in", [])
    item.setdefault("added", _today())
    item.setdefault("last_verified", _today())

    if not yes:
        return {"status": "dry_run", "item": item}

    inventory["items"].append(item)
    save_inventory(path, inventory)
    return {"status": "added", "item": item}


def mark_used(path, item_id, competition_slug, yes=False):
    """Append `competition_slug` to the item's used_in list, once."""
    inventory = load_inventory(path)
    target = next((i for i in inventory["items"] if i.get("id") == item_id), None)
    if target is None:
        raise InventoryError("no item with id %r in %s" % (item_id, path))
    if competition_slug in target.get("used_in", []):
        return {"status": "already_marked", "id": item_id}
    if not yes:
        return {"status": "dry_run", "id": item_id}
    target.setdefault("used_in", []).append(competition_slug)
    save_inventory(path, inventory)
    return {"status": "marked", "id": item_id}


def list_items(path, category=None, clientele=None, since=None, kind=None):
    """Return items filtered by category / clientele / kind / a minimum date."""
    inventory = load_inventory(path)
    items = inventory["items"]
    if category:
        items = [i for i in items if i.get("category") == category]
    if clientele:
        items = [i for i in items if clientele in i.get("clienteles", [])]
    if kind:
        items = [i for i in items if i.get("kind") == kind]
    if since:
        items = [i for i in items if str(i.get("date", "")) >= since]
    return items


def stats(path):
    """
    --------------------------------------------------------------------------
    Purpose:
        Summarize the inventory: counts per category and per kind, and a
        staleness signal (days since the most recent scopus-sourced item was
        added) the agent uses to decide whether a refresh is due.

    Inputs:
        path (str or Path): inventory YAML file

    Outputs:
        summary (dict): {"total", "by_category", "by_kind",
                          "most_recent_scopus_added", "days_since_scopus_refresh"}
    --------------------------------------------------------------------------
    """
    inventory = load_inventory(path)
    items = inventory["items"]
    by_category = {}
    by_kind = {}
    scopus_dates = []
    for item in items:
        by_category[item.get("category", "?")] = by_category.get(item.get("category", "?"), 0) + 1
        by_kind[item.get("kind", "?")] = by_kind.get(item.get("kind", "?"), 0) + 1
        if item.get("source") == "scopus" and item.get("added"):
            scopus_dates.append(item["added"])
    most_recent = max(scopus_dates) if scopus_dates else None
    days_since = None
    if most_recent:
        days_since = (datetime.today().date() - date.fromisoformat(most_recent)).days
    return {
        "total": len(items),
        "by_category": by_category,
        "by_kind": by_kind,
        "most_recent_scopus_added": most_recent,
        "days_since_scopus_refresh": days_since,
    }


def _cmd_init(args):
    inventory = load_inventory(args.path)
    if args.yes:
        save_inventory(args.path, inventory)
        print(json.dumps({"status": "initialized", "path": str(args.path)}))
    else:
        print(json.dumps({"status": "dry_run", "would_write": str(args.path)}))


def _cmd_add(args):
    with open(args.from_json, "r", encoding="utf-8") as handle:
        item = json.load(handle)
    result = add_item(args.path, item, types_path=args.types, yes=args.yes)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _cmd_list(args):
    items = list_items(args.path, category=args.category, clientele=args.clientele,
                        since=args.since, kind=args.kind)
    print(json.dumps(items, ensure_ascii=False, indent=2))


def _cmd_stats(args):
    print(json.dumps(stats(args.path), ensure_ascii=False, indent=2))


def _cmd_mark_used(args):
    result = mark_used(args.path, args.id, args.competition, yes=args.yes)
    print(json.dumps(result, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init")
    p_init.add_argument("--path", required=True)
    p_init.add_argument("--yes", action="store_true")
    p_init.set_defaults(func=_cmd_init)

    p_add = sub.add_parser("add")
    p_add.add_argument("--path", required=True)
    p_add.add_argument("--from-json", required=True)
    p_add.add_argument("--types")
    p_add.add_argument("--yes", action="store_true")
    p_add.set_defaults(func=_cmd_add)

    p_list = sub.add_parser("list")
    p_list.add_argument("--path", required=True)
    p_list.add_argument("--category")
    p_list.add_argument("--clientele")
    p_list.add_argument("--kind")
    p_list.add_argument("--since")
    p_list.set_defaults(func=_cmd_list)

    p_stats = sub.add_parser("stats")
    p_stats.add_argument("--path", required=True)
    p_stats.set_defaults(func=_cmd_stats)

    p_used = sub.add_parser("mark-used")
    p_used.add_argument("--path", required=True)
    p_used.add_argument("--id", required=True)
    p_used.add_argument("--competition", required=True)
    p_used.add_argument("--yes", action="store_true")
    p_used.set_defaults(func=_cmd_mark_used)

    args = parser.parse_args()
    try:
        args.func(args)
    except (InventoryError, CvDataError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
