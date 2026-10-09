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
    from defusedxml.common import DefusedXmlException
except ImportError:  # degrades to stdlib: no entity-expansion guard, but never silent (R8)
    import xml.etree.ElementTree as ET

    DefusedXmlException = ()  # an empty except-tuple: nothing extra to catch without defusedxml
    print(
        "WARNING: defusedxml is not installed - falling back to plain xml.etree.ElementTree, "
        "with no protection against malicious XML entities ('pip install -r requirements.txt' "
        "in scripts/ to install it)",
        file=sys.stderr,
    )

from cihr_cv import ROOT_TAG as CIHR_ROOT_TAG
from wp_common import atomic_write_text, configure_streams, error_report
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
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    def _fail(line, message, code):
        print(line, file=sys.stderr)
        if args.json:
            print(json.dumps(error_report(message, code), ensure_ascii=False))
        return code

    try:
        data_dir = resolve_data_dir(args.data_dir)
        xml_path = contained_path(data_dir, args.xml)
        out_path = contained_path(data_dir, args.out)
    except WpRefusal as exc:
        return _fail("REFUS: %s" % exc, str(exc), exit_code_for(exc))

    try:
        root = ET.parse(str(xml_path)).getroot()
    except ET.ParseError as exc:
        return _fail("ERROR: invalid XML: %s" % exc, str(exc), 1)
    except DefusedXmlException as exc:
        return _fail("ERROR: XML refused (entity-expansion guard): %s" % exc, str(exc), 1)
    except OSError as exc:
        return _fail("ERROR: cannot read file: %s" % exc, str(exc), 1)

    root_key = _strip_ns(root.tag)
    if root_key == CIHR_ROOT_TAG:
        message = (
            "this is a CIHR/CCV generic-cv export - use cihr_cv.py instead, "
            "which has no supervision parser (D2). The generic parser applies no "
            "section filtering and would publish whatever the tree holds."
        )
        return _fail("ERROR: %s" % message, message, 1)

    data = {root_key: elem_to_obj(root)}
    top = data[root_key]
    keys = list(top.keys()) if isinstance(top, dict) else []

    if args.dry_run:
        print("SIMULATION: would write %s" % out_path, file=sys.stderr)
    else:
        atomic_write_text(out_path, json.dumps(data, ensure_ascii=False, indent=2))
        print("Wrote %s" % out_path, file=sys.stderr)
    print("Top-level sections (use as cv_path in mapping.yaml): %s" % keys, file=sys.stderr)

    if args.json:
        print(json.dumps({"out": str(out_path), "dry_run": args.dry_run, "sections": keys}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
