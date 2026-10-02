"""
parse_cv.py - generic XML-to-JSON parser for a non-CIHR CV export.

Stage: a fallback for a CV XML that is not a CIHR generic-cv export.
Preserves the XML tree shape so mapping.yaml can reference any top-level
section by a dotted cv_path (e.g. "cv.experience").
"""
import argparse
import json
import sys

try:
    import defusedxml.ElementTree as ET
except ImportError:  # pragma: no cover - degrades to stdlib
    import xml.etree.ElementTree as ET

from wp_common import configure_streams
from wp_errors import WpRefusal, exit_code_for
from wp_paths import contained_path, resolve_data_dir


def _strip_ns(tag):
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def elem_to_obj(elem):
    """
    --------------------------------------------------------------------------
    Purpose:
        Turn an XML element into a JSON-shaped object: repeated sibling
        tags become a list, a leaf with no children becomes its text.

    Inputs:
        elem (xml.etree.ElementTree.Element): the element to convert.

    Outputs:
        obj: a str for a leaf, else a dict keyed by namespace-stripped tag
        name, with "_text" holding any text alongside child elements.
    --------------------------------------------------------------------------
    """
    children = list(elem)
    text = (elem.text or "").strip()
    if not children:
        return text
    obj = {}
    if text:
        obj["_text"] = text
    for child in children:
        key = _strip_ns(child.tag)
        value = elem_to_obj(child)
        if key in obj:
            if not isinstance(obj[key], list):
                obj[key] = [obj[key]]
            obj[key].append(value)
        else:
            obj[key] = value
    return obj


def main(argv=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        CLI entry point: parse a generic CV XML export into JSON under the
        researcher's data folder.

    Inputs:
        argv (list[str] or None): CLI arguments; None reads sys.argv.

    Outputs:
        exit_code (int): 0 on success, 1 on a parse failure, 2 on a refusal
        by design (spec section 6).
    --------------------------------------------------------------------------
    """
    configure_streams()
    parser = argparse.ArgumentParser(description="Parse a generic CV XML export into JSON.")
    parser.add_argument("xml")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--out", default="cv.json")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        data_dir = resolve_data_dir(args.data_dir)
        out_path = contained_path(data_dir, args.out)
    except WpRefusal as exc:
        print("REFUS: %s" % exc, file=sys.stderr)
        return exit_code_for(exc)

    try:
        root = ET.parse(args.xml).getroot()
    except ET.ParseError as exc:
        print("ERROR: invalid XML: %s" % exc, file=sys.stderr)
        return 1
    except OSError as exc:
        print("ERROR: cannot read file: %s" % exc, file=sys.stderr)
        return 1

    root_key = _strip_ns(root.tag)
    data = {root_key: elem_to_obj(root)}
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)

    top = data[root_key]
    keys = list(top.keys()) if isinstance(top, dict) else []
    print("Wrote %s" % out_path, file=sys.stderr)
    print("Top-level sections (use as cv_path in mapping.yaml): %s" % keys, file=sys.stderr)

    if args.json:
        print(json.dumps({"out": str(out_path), "sections": keys}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
