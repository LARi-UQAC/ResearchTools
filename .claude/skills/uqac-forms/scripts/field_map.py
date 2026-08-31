"""
field_map.py - read the widgets out of a UQAC AcroForm PDF, and diff two reads.

Stage: inspection. Given a PDF it reports every form widget it contains; given
two of those reports it says what changed. It stores nothing and decides nothing
about meaning: which profile key fills which field is a TT-8 row edited in the
ThesisTracker UI, not a fact this module knows.

Two constraints carry this module, and both exist because of a specific way an
official form goes wrong:

  Byte-exact names. A field name is the PDF's own bytes. It is never trimmed,
  case-folded, slugified or re-encoded, because TT-8 stores what this returns
  and RT-3 fills by exactly that key. UQAC forms really do carry names with
  trailing spaces and names differing only by case, so a name tidied here is a
  field nobody can fill again. Every widget also carries name_hex, so a human
  comparing two dumps can see a difference that does not survive printing.

  On-states from /AP /N. A checkbox is checked by writing its own on-state,
  which is whatever the form's author chose: /Oui, /Yes, /1, /On. It is read
  from each widget's appearance dictionary rather than guessed, because writing
  /Yes to a box whose on-state is /Oui leaves it silently unchecked on a
  document that then looks complete.

diff_widgets returns the four keys TT-8's diffWidgets returns in Node
(api/_lib/drift.js), with the same meanings, so a drift report reads the same
whichever side computed it. Neither side diffs on_states today; see the plan's
Open items.
"""

import io
import logging
from typing import Any

from pypdf import PdfReader
from pypdf.generic import IndirectObject

logger = logging.getLogger(__name__)

# AcroForm field-type codes, mapped to the vocabulary the caller stores.
_FIELD_TYPES: dict[str, str] = {
    "/Tx": "text",
    "/Btn": "checkbox",
    "/Ch": "choice",
    "/Sig": "signature",
}

# Field flags from the PDF specification, table 227.
_READONLY_FLAG: int = 1 << 0
_RADIO_FLAG: int = 1 << 15
_PUSHBUTTON_FLAG: int = 1 << 16

# An on-state of Off is the unchecked state and is never a value to write.
_OFF_STATE: str = "Off"


def _resolve(value: Any) -> Any:
    """Follow an indirect reference, so callers never branch on object kind."""
    return value.get_object() if isinstance(value, IndirectObject) else value


def _inherited(annot: Any, key: str) -> Any:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read a field attribute that a widget may inherit from a parent field.
        A radio group declares /FT and /Ff once on the parent and repeats
        neither on the individual kids, so reading only the widget would report
        the group as untyped.

    Inputs:
        annot (Any): the widget annotation dictionary
        key (str): the attribute name, for example "/FT"

    Outputs:
        value (Any): the nearest value found walking up /Parent, or None
    --------------------------------------------------------------------------
    """
    node = annot
    seen = 0
    while node is not None and seen < 32:  # depth guard against a cyclic /Parent
        if key in node:
            return _resolve(node[key])
        node = _resolve(node.get("/Parent"))
        seen += 1
    return None


def _widget_type(annot: Any) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Classify one widget. A button is a checkbox, a radio or a pushbutton
        depending only on its flags, so the flags decide rather than the
        presence of on-states.

    Inputs:
        annot (Any): the widget annotation dictionary

    Outputs:
        kind (str): text, checkbox, radio, choice, signature, or unknown
    --------------------------------------------------------------------------
    """
    raw = _inherited(annot, "/FT")
    kind = _FIELD_TYPES.get(str(raw)) if raw is not None else None
    if kind is None:
        return "unknown"
    if kind == "checkbox":
        flags = int(_inherited(annot, "/Ff") or 0)
        if flags & _PUSHBUTTON_FLAG:
            # A pushbutton holds no value, so it is not a fillable field.
            return "unknown"
        if flags & _RADIO_FLAG:
            return "radio"
    return kind


def _on_states(annot: Any, kind: str) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the on-states a button will accept from its /AP /N appearance
        dictionary, excluding Off.

    Inputs:
        annot (Any): the widget annotation dictionary
        kind (str): the classified widget type; only a button has on-states

    Outputs:
        states (list[str]): on-state names without the leading slash, in
            document order. Empty for every non-button, and for a button that
            declares no appearance dictionary.
    --------------------------------------------------------------------------
    """
    # Only a button has on-states. For a text field, /AP /N is a single
    # appearance STREAM rather than a dictionary of states, and reading its
    # keys yields the stream's own attributes: BBox, Subtype, Matrix and the
    # rest. On a real UQAC form that produced six invented on-states on 25 of
    # 56 fields, which no synthetic fixture without an /AP would have shown.
    if kind not in ("checkbox", "radio"):
        return []

    appearance = _resolve(annot.get("/AP"))
    if not appearance:
        return []
    normal = _resolve(appearance.get("/N"))
    if not hasattr(normal, "keys"):
        return []

    states = []
    for key in normal.keys():
        name = str(key).lstrip("/")
        if name != _OFF_STATE:
            states.append(name)
    return states


def dump_widgets(pdf: str | bytes) -> list[dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Report every AcroForm widget in a PDF, in document order, with the
        exact name, the on-states, and enough position to detect a move.

    Inputs:
        pdf (str | bytes): a path, or the PDF body itself. Bytes are accepted
            because TT-8 holds the file as bytea and RT-5 receives a request
            body: requiring a path would force both to write a temporary file.

    Outputs:
        widgets (list[dict]): one entry per widget, each carrying name,
            name_hex, type, page (1-based), rect, on_states and readonly.
            A PDF with no form returns an empty list.
    --------------------------------------------------------------------------
    """
    source = io.BytesIO(pdf) if isinstance(pdf, (bytes, bytearray)) else pdf
    reader = PdfReader(source)

    widgets: list[dict[str, Any]] = []
    for index, page in enumerate(reader.pages, start=1):
        annots = _resolve(page.get("/Annots")) or []
        for ref in annots:
            annot = _resolve(ref)
            if not hasattr(annot, "get") or str(annot.get("/Subtype")) != "/Widget":
                continue
            raw_name = _inherited(annot, "/T")
            if raw_name is None:
                # A kid widget of a radio group carries no /T of its own, and
                # the parent's name has already been reported. Skipping it here
                # keeps one entry per named field.
                continue
            name = str(raw_name)
            rect = [float(v) for v in (_resolve(annot.get("/Rect")) or [0, 0, 0, 0])]
            flags = int(_inherited(annot, "/Ff") or 0)
            kind = _widget_type(annot)
            widgets.append({
                "name": name,
                # The exact bytes, so a trailing space or a look-alike accent is
                # visible in a report where the printed name is not.
                "name_hex": name.encode("utf-8").hex(),
                "type": kind,
                "page": index,
                "rect": rect,
                "on_states": _on_states(annot, kind),
                "readonly": bool(flags & _READONLY_FLAG),
            })
    return widgets


def diff_widgets(before: list[dict[str, Any]],
                 after: list[dict[str, Any]]) -> dict[str, list[str]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Say what changed between two widget dumps of the same form. Mirrors
        TT-8's diffWidgets in api/_lib/drift.js: the same four keys with the
        same meanings, so a drift report reads the same whichever side
        computed it.

    Inputs:
        before (list[dict]): widgets as previously recorded
        after (list[dict]): widgets read from the form as it is now

    Outputs:
        report (dict): added, removed, relocated and retyped, each a sorted
            list of field names. A field that moved page is relocated, never
            an add plus a remove: its stored row is still correct.
    --------------------------------------------------------------------------
    """
    old = {w["name"]: w for w in (before or [])}
    new = {w["name"]: w for w in (after or [])}
    both = [n for n in new if n in old]

    return {
        "added": sorted(n for n in new if n not in old),
        "removed": sorted(n for n in old if n not in new),
        "relocated": sorted(
            n for n in both if int(new[n].get("page") or 0) != int(old[n].get("page") or 0)),
        "retyped": sorted(
            n for n in both if str(new[n].get("type")) != str(old[n].get("type"))),
    }
