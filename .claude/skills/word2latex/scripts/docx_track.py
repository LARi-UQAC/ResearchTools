"""
docx_track - apply tracked changes (w:ins / w:del) to an existing .docx from a JSON edit list.

Stage: reviewer-response support for manuscripts that stay in Word. The LaTeX path uses
latex-hygiene's tex_patch.py; this is its Word counterpart. Every edit is located by exact
text (matched across Word's fragmented runs), applied as a revision under one author, and
the output is read back: rejecting every revision must give the original text again (R9).

Usage:
    python docx_track.py paragraphs IN.docx [--json]
    python docx_track.py apply IN.docx EDITS.json -o OUT.docx --author NAME --date ISO
                                [--dry-run] [--json]

Exit codes: 0 every edit applied, 1 at least one edit failed (nothing is written),
2 refusal by design (bad arguments, unreadable edit file, output equal to input).
"""
from __future__ import annotations

import argparse
import copy
import json
import logging
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

logger = logging.getLogger(__name__)

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_NS = "http://www.w3.org/XML/1998/namespace"
DOC_PART = "word/document.xml"
WORD_XML_DECL = b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
OPS = {"replace", "delete", "insert_after", "insert_before", "insert_paragraphs_after"}
# Containers whose runs belong to the visible paragraph text; w:del content is not visible.
RUN_CONTAINERS = {"hyperlink", "smartTag", "ins", "fldSimple", "customXml", "sdtContent", "sdt"}
# Run children that carry no content, only a hint of Word's last layout; safe to split around.
RENDER_HINTS = {"lastRenderedPageBreak"}
# Run children that are content without a w:t: shown in the paragraph text so a find
# string must name them, and never split or deleted (see _split and _check_plain).
BREAK_TEXT = {"tab": "\t", "br": "\n", "cr": "\n"}
FIELD_DEPTH_XPATH = ("count(preceding::w:fldChar[@w:fldCharType='begin'])"
                     " - count(preceding::w:fldChar[@w:fldCharType='end'])")


def w(tag: str) -> str:
    """Purpose: qualified WordprocessingML tag name. Inputs: tag (str). Outputs: str."""
    return f"{{{W_NS}}}{tag}"


class EditError(Exception):
    """Raised when one edit cannot be applied safely; the message names the reason."""


@dataclass
class RunSpan:
    """One text run of a paragraph, with its offsets in the paragraph text."""

    run: etree._Element
    start: int
    end: int
    in_field: bool


@dataclass
class Report:
    """Machine-readable outcome of an apply run (R17)."""

    applied: list = field(default_factory=list)
    fails: list = field(default_factory=list)
    written: str | None = None
    verified: bool | None = None


def _run_text(run: etree._Element) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Visible text of one run: its w:t text, with a tab read as '\\t' and a line
        break as '\\n', so a match cannot silently span a tab or a break.

    Inputs:
        run (lxml element): a w:r element.

    Outputs:
        text (str): the run's text in child order, '' when the run holds none.
    --------------------------------------------------------------------------
    """
    parts = []
    for c in run:
        name = etree.QName(c).localname
        if name == "t":
            parts.append(c.text or "")
        elif name in BREAK_TEXT:
            parts.append(BREAK_TEXT[name])
    return "".join(parts)


def _plain_run(run: etree._Element) -> bool:
    """Purpose: True when a run holds only formatting, text and render hints. Inputs: run (w:r). Outputs: bool."""
    return all(etree.QName(c).localname in ("rPr", "t", *RENDER_HINTS) for c in run)


def paragraph_spans(p: etree._Element) -> list[RunSpan]:
    """
    --------------------------------------------------------------------------
    Purpose:
        List the visible runs of a paragraph with their text offsets, flagging runs
        that sit inside a field (code or result), since a field result is rewritten
        by Word or EndNote on update and must not be edited.

    Details:
        Runs inside w:del are skipped (not visible). Complex fields are tracked
        through w:fldChar begin/end; w:fldSimple content counts as in a field.
        The starting depth counts the fields opened and not yet closed before the
        paragraph, because an EndNote bibliography or a TOC field spans several
        paragraphs and its middle paragraphs hold no fldChar of their own.

    Inputs:
        p (lxml element): a w:p element.

    Outputs:
        spans (list[RunSpan]): runs in document order.
    --------------------------------------------------------------------------
    """
    spans: list[RunSpan] = []
    depth = max(0, int(p.xpath(FIELD_DEPTH_XPATH, namespaces={"w": W_NS})))
    pos = 0

    def walk(node: etree._Element, simple_field: bool) -> None:
        nonlocal depth, pos
        for child in node:
            name = etree.QName(child).localname
            if name == "r":
                for fc in child.findall(w("fldChar")):
                    kind = fc.get(w("fldCharType"))
                    if kind == "begin":
                        depth += 1
                text = _run_text(child)
                if text:
                    spans.append(RunSpan(child, pos, pos + len(text), depth > 0 or simple_field))
                    pos += len(text)
                for fc in child.findall(w("fldChar")):
                    if fc.get(w("fldCharType")) == "end":
                        depth = max(0, depth - 1)
            elif name in RUN_CONTAINERS:
                walk(child, simple_field or name == "fldSimple")

    walk(p, False)
    return spans


def paragraph_text(p: etree._Element) -> str:
    """Purpose: visible text of a paragraph. Inputs: p (w:p). Outputs: str."""
    return "".join(_run_text(s.run) for s in paragraph_spans(p))


def body_paragraphs(root: etree._Element) -> list[etree._Element]:
    """Purpose: every w:p of the body, tables included, in order. Inputs: root. Outputs: list."""
    body = root.find(w("body"))
    return [] if body is None else list(body.iter(w("p")))


def _find(root: etree._Element, text: str, occurrence: int | None) -> tuple[etree._Element, int]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Locate exactly one occurrence of `text` in the visible paragraph text.

    Inputs:
        root (lxml element): w:document root.
        text (str): exact text to find (may span several runs, never two paragraphs).
        occurrence (int | None): 1-based index when the text occurs several times.

    Outputs:
        (paragraph, offset): the paragraph holding the match and its start offset.

    Raises:
        EditError: text empty, not found, ambiguous without `occurrence`, or the
            requested occurrence does not exist.
    --------------------------------------------------------------------------
    """
    if not text:
        raise EditError("empty anchor")
    hits = []
    for p in body_paragraphs(root):
        ptext = paragraph_text(p)
        start = ptext.find(text)
        while start != -1:
            hits.append((p, start))
            start = ptext.find(text, start + 1)
    if not hits:
        raise EditError(f"not found: {text[:60]!r}")
    if occurrence is None:
        if len(hits) > 1:
            raise EditError(f"ambiguous ({len(hits)} matches): {text[:60]!r}; add 'occurrence'")
        return hits[0]
    if not 1 <= occurrence <= len(hits):
        raise EditError(f"occurrence {occurrence} of {len(hits)} does not exist: {text[:60]!r}")
    return hits[occurrence - 1]


def _set_text(run: etree._Element, text: str) -> None:
    """Purpose: give a run one w:t holding `text`, spaces preserved. Inputs: run, text. Outputs: None."""
    ts = run.findall(w("t"))
    for t in ts[1:]:
        run.remove(t)
    ts[0].text = text
    ts[0].set(f"{{{XML_NS}}}space", "preserve")


def _split(span: RunSpan, offset: int) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Split one run in two at an absolute paragraph offset, so a match boundary
        falls between runs.

    Inputs:
        span (RunSpan): the run containing the offset (start < offset < end).
        offset (int): absolute offset in the paragraph text.

    Outputs:
        None. Side effect: the run is shortened and a copy holding the rest is
        inserted right after it.

    Raises:
        EditError: the run holds something other than formatting and text (tab,
            break, drawing), where a split would move that content.
    --------------------------------------------------------------------------
    """
    run = span.run
    if not _plain_run(run):
        raise EditError("match boundary inside a run holding non-text content")
    text = _run_text(run)
    cut = offset - span.start
    right = copy.deepcopy(run)
    # A render hint marks where Word last broke the page; it belongs to the left part only.
    for hint in [c for c in right if etree.QName(c).localname in RENDER_HINTS]:
        right.remove(hint)
    _set_text(run, text[:cut])
    _set_text(right, text[cut:])
    run.addnext(right)


def _isolate(p: etree._Element, start: int, end: int) -> list[RunSpan]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Return the runs covering exactly [start, end) of the paragraph text,
        splitting runs at both ends as needed.

    Inputs:
        p (lxml element): paragraph. start, end (int): offsets, start <= end.

    Outputs:
        spans (list[RunSpan]): the covering runs (empty when start == end).
    --------------------------------------------------------------------------
    """
    for cut in (start, end):
        for s in paragraph_spans(p):
            if s.start < cut < s.end:
                _split(s, cut)
                break
    return [s for s in paragraph_spans(p) if s.start >= start and s.end <= end and s.end > s.start]


class Reviser:
    """Holds the revision author, date and the next free revision id of one document."""

    def __init__(self, root: etree._Element, author: str, date: str) -> None:
        """Purpose: prepare revision attributes. Inputs: root, author, date. Outputs: None."""
        self.author = author
        self.date = date
        ids = [int(v) for v in root.xpath("//@w:id", namespaces={"w": W_NS}) if str(v).lstrip("-").isdigit()]
        self.next_id = max(ids, default=0) + 1

    def attrs(self, el: etree._Element) -> etree._Element:
        """Purpose: stamp id, author, date on a revision element. Inputs: el. Outputs: el."""
        el.set(w("id"), str(self.next_id))
        el.set(w("author"), self.author)
        el.set(w("date"), self.date)
        self.next_id += 1
        return el

    def ins_run(self, text: str, template: etree._Element | None, highlight: str | None) -> etree._Element:
        """
        --------------------------------------------------------------------------
        Purpose:
            Build a w:ins holding one run of new text, formatted like `template`.

        Details:
            The template's highlight is dropped so new text is not confused with the
            author's own highlighted additions; `highlight` sets a new one.

        Inputs:
            text (str): inserted text. template (w:r | None): run whose rPr is copied.
            highlight (str | None): Word highlight colour name, e.g. "cyan".

        Outputs:
            ins (lxml element): the w:ins element.
        --------------------------------------------------------------------------
        """
        ins = self.attrs(etree.Element(w("ins")))
        run = etree.SubElement(ins, w("r"))
        rpr = None
        if template is not None and template.find(w("rPr")) is not None:
            rpr = copy.deepcopy(template.find(w("rPr")))
            for h in rpr.findall(w("highlight")):
                rpr.remove(h)
            run.append(rpr)
        if highlight:
            if rpr is None:
                rpr = etree.SubElement(run, w("rPr"))
            hl = etree.SubElement(rpr, w("highlight"))
            hl.set(w("val"), highlight)
        t = etree.SubElement(run, w("t"))
        t.text = text
        t.set(f"{{{XML_NS}}}space", "preserve")
        return ins

    def delete(self, spans: list[RunSpan]) -> etree._Element:
        """
        --------------------------------------------------------------------------
        Purpose:
            Wrap each covering run in its own w:del and turn its w:t into w:delText.

        Inputs:
            spans (list[RunSpan]): runs to delete, in order.

        Outputs:
            last (lxml element): the last w:del, after which an insertion goes.
        --------------------------------------------------------------------------
        """
        last = None
        for s in spans:
            run = s.run
            parent = run.getparent()
            d = self.attrs(etree.Element(w("del")))
            parent.replace(run, d)
            d.append(run)
            for t in run.findall(w("t")):
                t.tag = w("delText")
            last = d
        return last


def _check_not_field(spans: list[RunSpan]) -> None:
    """Purpose: refuse edits touching a field. Inputs: spans. Outputs: None. Raises: EditError when any span is in a field."""
    if any(s.in_field for s in spans):
        raise EditError("match touches a field (EndNote citation or cross-reference); choose another anchor")


def _check_plain(spans: list[RunSpan]) -> None:
    """Purpose: refuse deleting a run that holds a tab, break or drawing. Inputs: spans. Outputs: None. Raises: EditError."""
    if not all(_plain_run(s.run) for s in spans):
        raise EditError("match covers a run holding a tab, break or drawing; choose a narrower anchor")


STR_KEYS = ("find", "with", "anchor", "text", "highlight")


def _check_shape(e: object) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Refuse an edit whose shape is wrong before it touches the document, so a
        malformed edit file is reported as a failed edit and never as a traceback.

    Inputs:
        e (object): one entry of the edit list.

    Outputs:
        None.

    Raises:
        EditError: the edit is not an object, a text key is not a string,
            'paragraphs' is not a list of strings, or 'occurrence' is not an int.
    --------------------------------------------------------------------------
    """
    if not isinstance(e, dict):
        raise EditError(f"an edit must be an object, got {type(e).__name__}")
    for key in STR_KEYS:
        if key in e and e[key] is not None and not isinstance(e[key], str):
            raise EditError(f"key '{key}' must be a string")
    if "paragraphs" in e and not (isinstance(e["paragraphs"], list)
                                  and all(isinstance(x, str) for x in e["paragraphs"])):
        raise EditError("key 'paragraphs' must be a list of strings")
    occ = e.get("occurrence")
    if occ is not None and (isinstance(occ, bool) or not isinstance(occ, int)):
        raise EditError("key 'occurrence' must be an integer")


def apply_edit(root: etree._Element, rev: Reviser, e: dict) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Apply one edit as tracked revisions.

    Inputs:
        root (lxml element): w:document root, modified in place.
        rev (Reviser): author, date and id counter.
        e (dict): the edit; keys by op:
            replace: find, with   delete: find
            insert_after / insert_before: anchor, text
            insert_paragraphs_after: anchor, paragraphs (list[str])
            optional: occurrence (int), highlight (str)

    Outputs:
        None. Side effect: the document tree is revised.

    Raises:
        EditError: unknown op, missing key, or an anchor that cannot be applied.
    --------------------------------------------------------------------------
    """
    _check_shape(e)
    op = e.get("op")
    if op not in OPS:
        raise EditError(f"unknown op {op!r}")
    occ, hl = e.get("occurrence"), e.get("highlight")
    try:
        if op in ("replace", "delete"):
            p, start = _find(root, e["find"], occ)
            spans = _isolate(p, start, start + len(e["find"]))
            _check_not_field(spans)
            _check_plain(spans)
            template = spans[0].run
            last = rev.delete(spans)
            if op == "replace" and e["with"]:
                last.addnext(rev.ins_run(e["with"], template, hl))
        elif op in ("insert_after", "insert_before"):
            p, start = _find(root, e["anchor"], occ)
            at = start + len(e["anchor"]) if op == "insert_after" else start
            _isolate(p, at, at)
            spans = paragraph_spans(p)
            if op == "insert_after":
                ref = [s for s in spans if s.end == at][-1]
                _check_not_field([ref])
                ref.run.addnext(rev.ins_run(e["text"], ref.run, hl))
            else:
                ref = [s for s in spans if s.start == at][0]
                _check_not_field([ref])
                ref.run.addprevious(rev.ins_run(e["text"], ref.run, hl))
        else:
            p, _ = _find(root, e["anchor"], occ)
            spans = paragraph_spans(p)
            template = spans[0].run if spans else None
            anchor = p
            for text in e["paragraphs"]:
                newp = etree.Element(w("p"))
                ppr = p.find(w("pPr"))
                if ppr is not None:
                    ppr = copy.deepcopy(ppr)
                    for tag in ("sectPr", "pPrChange", "rPr"):
                        for x in ppr.findall(w(tag)):
                            ppr.remove(x)
                    newp.append(ppr)
                else:
                    ppr = etree.SubElement(newp, w("pPr"))
                mark = etree.SubElement(ppr, w("rPr"))
                mark.append(rev.attrs(etree.Element(w("ins"))))
                newp.append(rev.ins_run(text, template, hl))
                anchor.addnext(newp)
                anchor = newp
    except KeyError as k:
        raise EditError(f"op {op} needs key {k}") from None


def view_texts(root: etree._Element, accepted: bool) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Paragraph texts as Word shows them with all revisions accepted, or rejected.

    Details:
        Rejected view: w:ins text dropped, w:delText kept. Accepted view: the
        reverse. Empty paragraphs are omitted so an inserted paragraph that rejects
        to nothing does not shift the comparison.

    Inputs:
        root (lxml element): w:document root. accepted (bool): which view.

    Outputs:
        texts (list[str]): non-empty paragraph texts in order.
    --------------------------------------------------------------------------
    """
    out = []
    for p in body_paragraphs(root):
        parts = []
        for node in p.iter(w("t"), w("delText")):
            in_ins = any(a.tag == w("ins") for a in node.iterancestors())
            is_del = node.tag == w("delText")
            if accepted and not is_del:
                parts.append(node.text or "")
            elif not accepted and not in_ins:
                parts.append(node.text or "")
        text = "".join(parts)
        if text:
            out.append(text)
    return out


def verify(original: etree._Element, revised: etree._Element) -> bool:
    """
    Purpose: R9 read-back, rejecting every revision of both files must give the same text.
    Both sides use the rejected view, so revisions the input already carried (a co-author's
    earlier w:ins/w:del) cancel out instead of making every such file a mismatch.
    Inputs: original, revised (lxml roots). Outputs: bool.
    """
    return view_texts(original, accepted=False) == view_texts(revised, accepted=False)


def read_document(path: Path) -> etree._Element:
    """Purpose: parse word/document.xml of a .docx. Inputs: path. Outputs: root element."""
    with zipfile.ZipFile(path) as z:
        return etree.fromstring(z.read(DOC_PART))


def write_docx(src: Path, out: Path, root: etree._Element) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Write a copy of `src` whose document part is `root`; every other part is
        copied byte for byte.

    Inputs:
        src (Path): original .docx. out (Path): target. root (lxml element): new document.

    Outputs:
        None. Side effect: `out` is written through a temporary file then renamed.
    --------------------------------------------------------------------------
    """
    # Word's own declaration, double-quoted: some readers sniff it with a regex and fall
    # back to the system code page when lxml's single-quoted form is written instead.
    data = WORD_XML_DECL + etree.tostring(root, encoding="UTF-8")
    tmp = out.with_suffix(out.suffix + ".tmp")
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(tmp, "w") as zout:
        for item in zin.infolist():
            payload = data if item.filename == DOC_PART else zin.read(item.filename)
            zout.writestr(item, payload)
    tmp.replace(out)


def apply_file(src: Path, edits: list[dict], out: Path, author: str, date: str, dry_run: bool) -> Report:
    """
    --------------------------------------------------------------------------
    Purpose:
        Apply an edit list to a .docx, all or nothing, then verify the written file.

    Inputs:
        src, out (Path): input and output .docx. edits (list[dict]): see apply_edit.
        author, date (str): revision author and ISO date (injected, R19).
        dry_run (bool): apply in memory only, write nothing.

    Outputs:
        report (Report): applied ids, failures, written path, verification result.
        Side effect: `out` written only when every edit applied and not dry_run.
    --------------------------------------------------------------------------
    """
    report = Report()
    original = read_document(src)
    root = read_document(src)
    rev = Reviser(root, author, date)
    for i, e in enumerate(edits):
        eid = e.get("id", f"#{i + 1}") if isinstance(e, dict) else f"#{i + 1}"
        try:
            apply_edit(root, rev, e)
            report.applied.append(eid)
        except EditError as err:
            report.fails.append({"id": eid, "reason": str(err)})
    if report.fails or dry_run:
        return report
    write_docx(src, out, root)
    report.written = str(out)
    report.verified = verify(original, read_document(out))
    return report


def _load_edits(path: Path) -> list[dict]:
    """Purpose: read the edit list. Inputs: path. Outputs: list[dict]. Raises: ValueError when the file is not {"edits": [...]}."""
    data = json.loads(path.read_text(encoding="utf-8"))
    edits = data.get("edits") if isinstance(data, dict) else None
    if not isinstance(edits, list):
        raise ValueError(f"{path} must hold an object with an 'edits' list")
    return edits


def main(argv: list[str] | None = None) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        CLI entry point.

    Inputs:
        argv (list[str] | None): arguments, sys.argv when None.

    Outputs:
        code (int): 0 success, 1 an edit failed or verification failed, 2 refusal.
    --------------------------------------------------------------------------
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Apply tracked changes to a .docx.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("paragraphs", help="list visible paragraph texts with their index")
    pp.add_argument("docx", type=Path)
    pp.add_argument("--json", action="store_true")
    pa = sub.add_parser("apply", help="apply an edit list as tracked changes")
    pa.add_argument("docx", type=Path)
    pa.add_argument("edits", type=Path)
    pa.add_argument("-o", "--out", type=Path, required=True)
    pa.add_argument("--author", required=True)
    pa.add_argument("--date", required=True, help="ISO 8601, e.g. 2026-10-30T00:00:00Z")
    pa.add_argument("--dry-run", action="store_true")
    pa.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if not args.docx.is_file():
        print(f"REFUSED: {args.docx} not found", file=sys.stderr)
        return 2
    try:
        doc = read_document(args.docx)
    except (zipfile.BadZipFile, KeyError, etree.XMLSyntaxError, OSError) as err:
        print(f"REFUSED: {args.docx} is not a readable .docx: {err}", file=sys.stderr)
        return 2
    if args.cmd == "paragraphs":
        texts = [paragraph_text(p) for p in body_paragraphs(doc)]
        rows = [{"index": i + 1, "text": t} for i, t in enumerate(texts) if t]
        print(json.dumps(rows, ensure_ascii=False, indent=1) if args.json
              else "\n".join(f"[{r['index']}] {r['text']}" for r in rows))
        return 0
    if args.out.resolve() == args.docx.resolve():
        print("REFUSED: --out must differ from the input file", file=sys.stderr)
        return 2
    try:
        edits = _load_edits(args.edits)
    except (OSError, ValueError) as err:
        print(f"REFUSED: {err}", file=sys.stderr)
        return 2
    rep = apply_file(args.docx, edits, args.out, args.author, args.date, args.dry_run)
    if args.json:
        print(json.dumps(rep.__dict__, ensure_ascii=False, indent=1))
    else:
        print(f"applied {len(rep.applied)}/{len(edits)}" + (" (dry run)" if args.dry_run else ""))
        for f in rep.fails:
            print(f"FAILS: {f['id']}: {f['reason']}")
        if rep.written:
            print(f"written {rep.written}, read-back {'OK' if rep.verified else 'MISMATCH'}")
    if rep.fails or rep.verified is False:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
