"""
fill_form.py - write values into a UQAC AcroForm PDF and hand back the bytes.

Stage: filling. It is given a PDF, a dictionary of already-resolved values, and
optionally the names of fields to lock. It returns a new PDF. It holds nothing,
looks nothing up, and does not know which form it has: TT-9 resolves the values
and TT-10 decides which fields a step may write.

The order inside fill() is not an implementation detail:

    1. write the values
    2. set NeedAppearances
    3. lock the fields of the step that just completed
    4. sign, in RT-4, as an incremental update

Signing last is what makes a signature verifiable. An incremental update appends
to the file, so every earlier signature survives; anything that rewrites the
whole document after a signature invalidates it.

Two failures this module refuses rather than produces:

  A value for a field the PDF does not have. The caller believes it filled
  something, and a form with a blank where the value should be is worse than one
  that obviously failed.

  A checkbox value that is not one of that widget's own on-states. Writing /Yes
  to a box whose on-state is /Oui leaves it unchecked on a document that then
  looks complete. This is the failure RT-2's on_states exists to prevent, one
  stage later, which is why the on-state is read from the widget rather than
  assumed.

Honest limitation: pypdf has no appearance-burning flatten. Locking a field
read-only is what "flatten" means here. The values are fixed and a viewer will
not edit them, but they remain form fields rather than page content. A caller
who needs a true burn-in needs a different tool.
"""

import io
import logging
from typing import Any

from pypdf import PdfWriter
from pypdf.generic import (
    BooleanObject, DictionaryObject, IndirectObject, NameObject, NumberObject,
    TextStringObject,
)

logger = logging.getLogger(__name__)

# /Ff bit 1: the field is not editable in a viewer.
READONLY_FLAG: int = 1

# Field types that hold a name rather than a string, and are therefore checked
# against the widget's own appearance states.
_BUTTON: str = "/Btn"
_SIGNATURE: str = "/Sig"
_OFF_STATE: str = "Off"


class FillError(RuntimeError):
    """A value could not be written, and no document is produced."""


def _resolve(value: Any) -> Any:
    return value.get_object() if isinstance(value, IndirectObject) else value


def _inherited(annot: Any, key: str) -> Any:
    """Read an attribute a widget may inherit from a parent field."""
    node = annot
    seen = 0
    while node is not None and seen < 32:
        if key in node:
            return _resolve(node[key])
        node = _resolve(node.get("/Parent"))
        seen += 1
    return None


def _widgets_by_name(writer: PdfWriter) -> dict[str, list]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Index every named widget annotation in the document. A name can carry
        more than one widget, as a radio group does, so each maps to a list.

    Inputs:
        writer (PdfWriter): the document being built

    Outputs:
        index (dict[str, list]): field name to its widget annotations
    --------------------------------------------------------------------------
    """
    index: dict[str, list] = {}
    for page in writer.pages:
        for ref in _resolve(page.get("/Annots")) or []:
            annot = _resolve(ref)
            if not hasattr(annot, "get") or str(annot.get("/Subtype")) != "/Widget":
                continue
            name = _inherited(annot, "/T")
            if name is None:
                continue
            index.setdefault(str(name), []).append(annot)
    return index


def _on_states(annot: Any) -> list[str]:
    """Read the states a button accepts from its /AP /N dictionary."""
    appearance = _resolve(annot.get("/AP"))
    if not appearance:
        return []
    normal = _resolve(appearance.get("/N"))
    if not hasattr(normal, "keys"):
        return []
    return [str(k).lstrip("/") for k in normal.keys() if str(k).lstrip("/") != _OFF_STATE]


def write_values(writer: PdfWriter, values: dict[str, str]) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Write each value to the widget or widgets carrying its field name. A
        button gets both /V and /AS set to its on-state, because a viewer draws
        the appearance named by /AS: setting /V alone leaves the box looking
        unchecked whatever the value says.

    Inputs:
        writer (PdfWriter): the document being built
        values (dict[str, str]): byte-exact field name to value

    Outputs:
        written (int): number of widgets written

    Raises:
        FillError: a name is absent from the document, or a button value is not
            one of that widget's own on-states. Every offending name is
            reported, not only the first.
    --------------------------------------------------------------------------
    """
    index = _widgets_by_name(writer)

    missing = sorted(n for n in values if n not in index)
    if missing:
        raise FillError(
            "no such field in this PDF: " + ", ".join(repr(n) for n in missing)
            + ". The names must be exactly as the form spells them.")

    written = 0
    problems: list[str] = []
    for name, raw in values.items():
        for annot in index[name]:
            kind = str(_inherited(annot, "/FT") or "")
            if kind == _BUTTON:
                wanted = str(raw).lstrip("/")
                allowed = _on_states(annot)
                if wanted != _OFF_STATE and wanted not in allowed:
                    problems.append(
                        f"{name!r} was given {wanted!r}, but this widget accepts "
                        f"{allowed or ['(none declared)']}")
                    continue
                state = NameObject(f"/{wanted}")
                annot[NameObject("/V")] = state
                # A viewer draws the appearance named by /AS, so both are set.
                annot[NameObject("/AS")] = state
            else:
                annot[NameObject("/V")] = TextStringObject(str(raw))
            written += 1

    if problems:
        raise FillError(
            "a checkbox value is not one of the widget's own on-states, which "
            "would leave it unchecked on a form that looks complete: "
            + "; ".join(problems))
    return written


def set_need_appearances(writer: PdfWriter) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Ask the viewer to build appearance streams for the form fields. Without
        it an AcroForm value is present in the file and invisible on screen,
        which is the most convincing way to produce an empty-looking form that
        the data says is filled.

    Inputs:
        writer (PdfWriter): the document being built

    Outputs:
        None
    --------------------------------------------------------------------------
    """
    root = writer._root_object
    if "/AcroForm" not in root:
        root[NameObject("/AcroForm")] = DictionaryObject()
    acro = _resolve(root["/AcroForm"])
    acro[NameObject("/NeedAppearances")] = BooleanObject(True)


def lock_fields(writer: PdfWriter, names: list[str]) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Mark the named fields read-only, which is what "flatten" means in this
        pipeline. Only the fields of the step that just completed are locked: a
        UQAC form is filled by several people in turn, and locking everything
        after the first step would leave the professor and the Direction with
        nothing they can write.

    Inputs:
        writer (PdfWriter): the document being built
        names (list[str]): field names to lock

    Outputs:
        locked (int): number of widgets locked

    Raises:
        FillError: a named field is absent from the document.

    Note:
        A signature widget is never locked, even when named. Locking one
        destroys the field a later signer needs, and a caller naming it is more
        likely mistaken than instructing.
    --------------------------------------------------------------------------
    """
    if not names:
        return 0

    index = _widgets_by_name(writer)
    missing = sorted(n for n in names if n not in index)
    if missing:
        raise FillError(
            "cannot lock a field this PDF does not have: "
            + ", ".join(repr(n) for n in missing))

    locked = 0
    for name in names:
        for annot in index[name]:
            if str(_inherited(annot, "/FT") or "") == _SIGNATURE:
                logger.info("[UQAC-FORMS] not locking signature field %r", name)
                continue
            flags = int(_inherited(annot, "/Ff") or 0)
            annot[NameObject("/Ff")] = NumberObject(flags | READONLY_FLAG)
            locked += 1
    return locked


def _refuse_if_already_signed(writer: PdfWriter) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Refuse to fill a document that already carries a signature, because
        writing one produces a full rewrite rather than an incremental update,
        and a rewrite invalidates every signature already in the file.

    Inputs:
        writer (PdfWriter): the document being built

    Outputs:
        None

    Raises:
        FillError: a signature field already holds a value.

    Note:
        This is the "sign last" rule of the pipeline, enforced rather than
        documented. Without it the failure is silent and expensive: an official
        document goes out carrying a signature that no longer verifies, and
        nobody discovers it until someone checks.
    --------------------------------------------------------------------------
    """
    signed = []
    for annots in _widgets_by_name(writer).items():
        name, widgets = annots
        for annot in widgets:
            if (str(_inherited(annot, "/FT") or "") == _SIGNATURE
                    and annot.get("/V") is not None):
                signed.append(name)
                break
    if signed:
        raise FillError(
            "this document is already signed by "
            + ", ".join(repr(n) for n in sorted(signed))
            + ". Filling rewrites the file, which would invalidate that "
            "signature. Fill every step first and sign last.")


def fill(pdf_bytes: bytes, values: dict[str, str],
         flatten_fields: list[str] | None = None) -> bytes:
    """
    --------------------------------------------------------------------------
    Purpose:
        Fill a form and return the resulting PDF. Stateless: nothing is read
        from disk, nothing is written to it, and the same input always gives
        the same output.

    Inputs:
        pdf_bytes (bytes): the form to fill
        values (dict[str, str]): byte-exact field name to already-resolved
            value, as TT-9 produced it
        flatten_fields (list[str] | None): fields to lock, normally those of
            the step that just completed. None locks nothing.

    Outputs:
        filled (bytes): the new PDF

    Raises:
        FillError: any value or lock names a field the document does not have,
            or a button value is not one of its own on-states. Nothing is
            returned in that case: a form that looks filled and is not would be
            worse than an obvious failure.
    --------------------------------------------------------------------------
    """
    writer = PdfWriter(clone_from=io.BytesIO(pdf_bytes))
    _refuse_if_already_signed(writer)

    # The order below is the contract. Locking before writing would refuse the
    # values of the very step being completed.
    write_values(writer, values or {})
    set_need_appearances(writer)
    lock_fields(writer, flatten_fields or [])

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
