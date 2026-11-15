"""
figure_tex.py - the figures of a LaTeX document, read from the text alone.

It finds each `figure` environment with its label, caption and the sources it draws (TikZ, draw.io, SVG,
EPS, PDF and bitmaps), counts the `\\ref`, `\\autoref` and `\\cref` calls, and runs the three criteria that
need no image: the label form, the citation before the figure, and a hard-coded figure number out of order.
Rendering is figure_render.py's job. Nothing here runs a tool or writes a file.
"""
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from figure_checks import CriteriaError

KIND_BY_EXTENSION = {
    "png": "png", "jpg": "jpg", "jpeg": "jpg", "gif": "gif", "bmp": "bmp", "tif": "tiff", "tiff": "tiff",
    "webp": "webp", "pdf": "pdf", "eps": "eps", "svg": "svg", "drawio": "drawio", "tikz": "tikz", "pgf": "tikz",
}
# Extensions tried, in this order, for an \includegraphics path written without one.
GUESS_EXTENSIONS = ("pdf", "png", "jpg", "jpeg", "eps", "svg", "gif", "bmp", "tif", "tiff", "webp")
INPUT_EXTENSIONS = ("tikz", "tex", "pgf")
LABEL_FORM = re.compile(r"^fig:[a-z0-9]+-[a-z0-9]+-[a-z0-9]+$")
HARD_NUMBER = re.compile(r"^\s*(?:Figure|Fig\.?)\s*(\d+)", re.I)
TEXT_CRITERIA = ("figure_label_form", "called_before_appearing", "numbered_in_sequence")

_FIGURE = re.compile(r"\\begin\{figure\*?\}(\[[^\]]*\])?(.*?)\\end\{figure\*?\}", re.S)
_SUBFIGURE = re.compile(r"\\begin\{subfigure\}.*?\\end\{subfigure\}", re.S)
_SOURCE = re.compile(
    r"(?P<tikz>\\begin\{tikzpicture\}.*?\\end\{tikzpicture\})"
    r"|\\includegraphics\s*(?:\[[^\]]*\])?\s*\{(?P<graphic>[^}]*)\}"
    r"|\\includesvg\s*(?:\[[^\]]*\])?\s*\{(?P<svg>[^}]*)\}"
    r"|\\input\s*\{(?P<input>[^}]*)\}", re.S)
_REF = re.compile(r"\\(?:ref|autoref|cref|Cref|vref)\*?\s*\{([^}]*)\}")
_LABEL = re.compile(r"\\label\s*\{([^}]*)\}")


def strip_comments(text: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Blank every LaTeX comment, keeping each offset and line number unchanged.

    Inputs:
        text (str): the document

    Outputs:
        text (str): the same text with `%` to the end of the line replaced by spaces.
    --------------------------------------------------------------------------
    """
    return re.sub(r"(?<!\\)%[^\n]*", lambda m: " " * len(m.group(0)), text)


def _argument(text: str, start: int) -> Optional[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the brace-balanced argument that opens at `start`.

    Inputs:
        text (str): the text
        start (int): index of the opening brace

    Outputs:
        content (str | None): what lies between the braces, or None when it never closes.
    --------------------------------------------------------------------------
    """
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{" and text[index - 1:index] != "\\":
            depth += 1
        elif text[index] == "}" and text[index - 1:index] != "\\":
            depth -= 1
            if depth == 0:
                return text[start + 1:index]
    return None


def _caption(body: str) -> Optional[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the text of the first `\\caption` of a figure body.

    Inputs:
        body (str): the body of a figure, subfigures already blanked

    Outputs:
        caption (str | None): the caption with runs of spaces folded, or None when there is none.
    --------------------------------------------------------------------------
    """
    found = re.search(r"\\caption\s*(?:\[[^\]]*\])?\s*\{", body)
    if not found:
        return None
    content = _argument(body, found.end() - 1)
    return None if content is None else re.sub(r"\s+", " ", content).strip()


def _extension(path: str) -> str:
    return path.rsplit(".", 1)[1].lower() if "." in Path(path).name else ""


def inside_folder(base_dir: Optional[Path], relative: str) -> Optional[Path]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve a path written in the document and keep it only when it stays in the document's folder
        (R24: resolve first, compare after, refuse rather than clamp).

    Inputs:
        base_dir (Path | None): the folder of the .tex file
        relative (str): the path as written

    Outputs:
        path (Path | None): the resolved path, or None when there is no folder or the path leaves it.
    --------------------------------------------------------------------------
    """
    if base_dir is None or not relative.strip():
        return None
    root = base_dir.resolve()
    target = (root / relative.strip()).resolve()
    return target if target == root or root in target.parents else None


def _graphic_source(raw: str, base_dir: Optional[Path]) -> Dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Classify an `\\includegraphics` path. A draw.io file beside the exported image wins, since the
        export is only the picture of the source the author really edited.

    Inputs:
        raw (str): the path as written
        base_dir (Path | None): the folder of the .tex file, or None to skip every file lookup

    Outputs:
        source (dict): `kind`, `path_or_code`, `origin` ("file").
    --------------------------------------------------------------------------
    """
    raw = raw.strip()
    stem = raw.rsplit(".", 1)[0] if _extension(raw) else raw
    drawio = stem + ".drawio"
    found = inside_folder(base_dir, drawio)
    if found is not None and found.is_file():
        return {"kind": "drawio", "path_or_code": drawio, "origin": "file"}
    extension = _extension(raw)
    if extension in KIND_BY_EXTENSION:
        return {"kind": KIND_BY_EXTENSION[extension], "path_or_code": raw, "origin": "file"}
    for guess in GUESS_EXTENSIONS:
        found = inside_folder(base_dir, raw + "." + guess)
        if found is not None and found.is_file():
            return {"kind": KIND_BY_EXTENSION[guess], "path_or_code": raw + "." + guess, "origin": "file"}
    return {"kind": "unknown", "path_or_code": raw, "origin": "file"}


def _input_source(name: str, base_dir: Optional[Path]) -> Dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Follow an `\\input` of a TikZ file. A file that is missing, leaves the document's folder or is
        not a TikZ source is `unknown`, never read.

    Inputs:
        name (str): the name as written
        base_dir (Path | None): the folder of the .tex file

    Outputs:
        source (dict): `kind` tikz with the file's code, or `unknown`; `path` names the file.
    --------------------------------------------------------------------------
    """
    name = name.strip()
    written = name if _extension(name) else name + ".tex"
    target = inside_folder(base_dir, written)
    if target is None or not target.is_file() or _extension(written) not in INPUT_EXTENSIONS:
        return {"kind": "unknown", "path_or_code": name, "origin": "input"}
    code = target.read_text(encoding="utf-8", errors="replace")
    return {"kind": "tikz", "path_or_code": code, "origin": "input", "path": written}


def figures(tex_text: str, base_dir: Optional[Path]) -> List[Dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        List the figure environments of a document with what each one draws.

    Inputs:
        tex_text (str): the LaTeX source
        base_dir (Path | None): the folder of the .tex file; with None no file is looked up or read

    Outputs:
        figures (list[dict]): in document order, each with `label` (outside the subfigures), `caption`,
        `position` (the `[htbp]` letters), `offset` and `line` of `\\begin{figure}`, and `sources`, the
        flat list of `{kind, path_or_code, origin}` over every subfigure. `kind` is tikz, drawio, svg,
        eps, pdf, png, jpg, gif, bmp, tiff, webp or unknown. Commented figures are ignored.
    --------------------------------------------------------------------------
    """
    text = strip_comments(tex_text)
    result = []
    for match in _FIGURE.finditer(text):
        body = match.group(2)
        outer = _SUBFIGURE.sub(lambda m: " " * len(m.group(0)), body)
        label = _LABEL.search(outer)
        sources = []
        for found in _SOURCE.finditer(body):
            if found.group("tikz") is not None:
                sources.append({"kind": "tikz", "path_or_code": found.group("tikz"), "origin": "inline"})
            elif found.group("graphic") is not None:
                sources.append(_graphic_source(found.group("graphic"), base_dir))
            elif found.group("svg") is not None:
                name = found.group("svg").strip()
                sources.append({"kind": "svg", "path_or_code": name if _extension(name) else name + ".svg",
                                "origin": "file"})
            else:
                sources.append(_input_source(found.group("input"), base_dir))
        result.append({
            "label": label.group(1).strip() if label else None,
            "caption": _caption(outer),
            "position": match.group(1)[1:-1] if match.group(1) else None,
            "offset": match.start(),
            "line": text.count("\n", 0, match.start()) + 1,
            "sources": sources,
        })
    return result


def references(tex_text: str) -> Dict[str, List[int]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Count the cross-references of a document, per label.

    Inputs:
        tex_text (str): the LaTeX source

    Outputs:
        refs (dict[str, list[int]]): label -> offsets of every `\\ref`, `\\autoref`, `\\cref`, `\\Cref`
        or `\\vref` naming it (a comma list names several labels). Comments are ignored.
    --------------------------------------------------------------------------
    """
    refs: Dict[str, List[int]] = {}
    for match in _REF.finditer(strip_comments(tex_text)):
        for label in match.group(1).split(","):
            if label.strip():
                refs.setdefault(label.strip(), []).append(match.start())
    return refs


def text_checks(tex_text: str, criteria_doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run the three criteria that need only the text: the label form `fig:three-words`, the figure
        cited before it appears, and a hard-coded figure number out of order (LaTeX numbers by itself,
        so an automatic number is not applicable).

    Inputs:
        tex_text (str): the LaTeX source
        criteria_doc (dict): the loaded criteria document; it must define the three ids

    Outputs:
        records (list[dict]): one per figure with `label`, `caption`, `line` and `criteria`, a mapping of
        criterion id to `{verdict, reason}` where the verdict is pass, fail, not_run or not_applicable,
        the shape figure_checks.check returns.

    Raises:
        CriteriaError: the criteria document lacks one of the three ids.
    --------------------------------------------------------------------------
    """
    known = {criterion.get("id") for criterion in criteria_doc.get("criteria", [])}
    missing = [name for name in TEXT_CRITERIA if name not in known]
    if missing:
        raise CriteriaError("criteria document lacks: " + ", ".join(missing))
    text = strip_comments(tex_text)
    refs = references(text)
    records = []
    for index, fig in enumerate(figures(text, None)):
        label, verdicts = fig["label"], {}
        if label is None:
            verdicts["figure_label_form"] = {"verdict": "fail", "reason": "the figure has no label"}
            verdicts["called_before_appearing"] = {"verdict": "not_run", "reason": "no label to look up"}
        else:
            ok = bool(LABEL_FORM.match(label))
            verdicts["figure_label_form"] = {
                "verdict": "pass" if ok else "fail",
                "reason": f"label {label} " + ("has the form fig:three-words" if ok else "is not fig:three-words")}
            calls = refs.get(label)
            if not calls:
                verdicts["called_before_appearing"] = {"verdict": "fail", "reason": "the figure is never cited"}
            elif min(calls) < fig["offset"]:
                verdicts["called_before_appearing"] = {
                    "verdict": "pass", "reason": f"first cited on line {text.count(chr(10), 0, min(calls)) + 1}"}
            else:
                verdicts["called_before_appearing"] = {
                    "verdict": "fail",
                    "reason": f"first cited on line {text.count(chr(10), 0, min(calls)) + 1}, "
                              f"after the figure on line {fig['line']}"}
        number = HARD_NUMBER.match(fig["caption"] or "")
        if number is None:
            verdicts["numbered_in_sequence"] = {"verdict": "not_applicable", "reason": "numbered by LaTeX"}
        else:
            ok = int(number.group(1)) == index + 1
            verdicts["numbered_in_sequence"] = {
                "verdict": "pass" if ok else "fail",
                "reason": f"caption says {number.group(1)}, the figure is number {index + 1}"}
        records.append({"label": label, "caption": fig["caption"], "line": fig["line"], "criteria": verdicts})
    return records
