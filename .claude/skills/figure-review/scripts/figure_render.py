"""
figure_render.py - turn a figure a model cannot see into one it can, when the caller asks for it.

A model reads PNG and JPEG. Every other source (TikZ, draw.io, SVG, EPS, PDF, GIF, BMP, TIFF, WebP) is
rendered by the tool that fits its format, then cut to the model's size by figure_image.fit_for_model.
A tool that is absent, a compile that fails and a timeout are reported as `not_run` with the reason and
the tool, never as a broken picture, and no other tool is substituted (R8). The source figure is never
modified, and every file written stays inside the output folder given by the caller (R24).

Command line: figure_render.py --tex FILE --out DIR [--render] [--json]. Without --render it only lists
the sources and their kinds and calls no tool.
EXIT CODES (R12): 0 done, 2 refusal (missing document, missing configuration key).
"""
import argparse
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import fitz

import figure_checks
import figure_image
import figure_tex

NATIVE_KINDS = ("png", "jpg")
RASTER_KINDS = ("gif", "bmp", "tiff", "webp")
DEFAULT_CRITERIA = Path(__file__).resolve().parent.parent / "assets" / "figure_criteria.json"
FIG_EXPORT = Path(__file__).resolve().parents[2] / "paper2talk" / "scripts" / "fig_export.py"
SETTING_KEYS = ("max_long_edge", "photo_colors", "jpeg_quality", "render_dpi", "render_timeout_s", "drawio_scale")
EXIT_REFUSAL = 2


class RenderError(ValueError):
    """Raised when a rendering request would write outside the output folder."""


def native(kind: str) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Say whether a model reads this source kind as it is.

    Inputs:
        kind (str): a source kind of figure_tex

    Outputs:
        native (bool): True for png and jpg.
    --------------------------------------------------------------------------
    """
    return kind in NATIVE_KINDS


def standalone_text(code: str, preamble: Optional[str]) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Wrap a TikZ picture in a `standalone` document that carries the paper's own preamble, so a macro
        or a library the picture uses is defined.

    Inputs:
        code (str): the tikzpicture
        preamble (str | None): the paper's preamble without its \\documentclass; None loads tikz only

    Outputs:
        text (str): a complete LaTeX document.
    --------------------------------------------------------------------------
    """
    head = preamble if preamble and preamble.strip() else r"\usepackage{tikz}"
    return "\\documentclass[border=2pt]{standalone}\n" + head + "\n\\begin{document}\n" + code + "\n\\end{document}\n"


def _result(status: str, file: Optional[str] = None, fmt: Optional[str] = None, tokens: Optional[int] = None,
            reason: Optional[str] = None, tool: Optional[str] = None, **extra: Any) -> Dict[str, Any]:
    out = {"status": status, "file": file, "format": fmt, "estimated_tokens": tokens, "reason": reason, "tool": tool}
    out.update(extra)
    return out


def _not_run(reason: str, tool: Optional[str] = None) -> Dict[str, Any]:
    return _result("not_run", reason=reason, tool=tool)


def _stem(source: Dict[str, Any], out_dir: Path) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Choose the output name and refuse one that would leave the output folder (R24: the path is
        resolved first, compared after, and refused, never clamped).

    Inputs:
        source (dict): the source; an optional `name` sets the file stem
        out_dir (Path): the output folder

    Outputs:
        stem (str): a plain file stem.

    Raises:
        RenderError: the stem holds a separator or resolves outside out_dir.
    --------------------------------------------------------------------------
    """
    name = source.get("name")
    if not name:
        name = Path(str(source["path_or_code"])).stem if source["kind"] not in ("tikz",) else "tikz"
    if Path(name).name != name or name in ("", ".", ".."):
        raise RenderError("output name leaves the output folder")
    if (out_dir / (name + ".png")).resolve().parent != out_dir.resolve():
        raise RenderError("output name leaves the output folder")
    return name


def _finish(png: Path, stem: str, out_dir: Path, fmt_args: Dict[str, int], tool: Optional[str], **extra: Any) -> Dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Cut an image to the model's size and write it into the output folder under `stem`.

    Inputs:
        png (Path): the image to fit, any readable bitmap
        stem (str): output file stem
        out_dir (Path): the output folder
        fmt_args (dict): max_long_edge, photo_colors, jpeg_quality
        tool (str | None): the tool that produced the image, for the report

    Outputs:
        result (dict): status rendered, or not_run when the image cannot be read.
    --------------------------------------------------------------------------
    """
    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / (stem + png.suffix)
        shutil.copyfile(png, staged)
        try:
            fit = figure_image.fit_for_model(staged, out_dir, **fmt_args)
        except figure_image.ImageError as exc:
            return _not_run("unreadable image: %s" % exc, tool)
    return _result("rendered", str((out_dir.resolve() / fit["file"])), fit["format"], fit["estimated_tokens"],
                   extra.pop("reason", None), tool, **extra)


def _pymupdf_to_png(path: Path, png: Path, dpi: int, raster: bool) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Rasterise page 1 of a PDF or an SVG, or re-encode a bitmap, as a PNG without transparency.

    Inputs:
        path (Path): the source file
        png (Path): the PNG to write
        dpi (int): rendering resolution of a page
        raster (bool): True for a bitmap file, False for a page document

    Outputs:
        None. Writes `png`.

    Raises:
        Exception: whatever PyMuPDF raises on a file it cannot read; the caller reports it.
    --------------------------------------------------------------------------
    """
    if raster:
        pix = fitz.Pixmap(str(path))
        if pix.colorspace is not None and pix.colorspace.n > 3:
            pix = fitz.Pixmap(fitz.csRGB, pix)
        if pix.alpha:
            pix = fitz.Pixmap(pix, 0)
    else:
        with fitz.open(str(path)) as doc:
            pix = doc[0].get_pixmap(dpi=dpi, alpha=False)
    pix.save(str(png))


def _load_export() -> Optional[Callable[..., bool]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Import the draw.io export of paper2talk (imported, not copied, R18).

    Inputs:
        None

    Outputs:
        export (callable | None): fig_export.export, or None when the file is not there.
    --------------------------------------------------------------------------
    """
    if not FIG_EXPORT.is_file():
        return None
    spec = importlib.util.spec_from_file_location("fig_export_for_figure_render", FIG_EXPORT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.export


def _first_error(output: str) -> Optional[str]:
    for line in (output or "").splitlines():
        if line.startswith("!"):
            return line.strip()
    return None


def render(source: Dict[str, Any], out_dir: Path, preamble: Optional[str], *,
           which: Optional[Callable] = None, run: Optional[Callable] = None, export: Optional[Callable] = None,
           timeout: float, max_long_edge: int, dpi: int, photo_colors: int, jpeg_quality: int,
           drawio_scale: int) -> Dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Give a model something it can look at for one figure source.

    Details:
        png and jpg are native: used as they are when within max_long_edge, else cut. TikZ goes through
        pdflatex in a standalone document with the paper's preamble, draw.io through fig_export (only one
        image is exported; the page count of the file is reported), SVG and PDF through PyMuPDF, EPS
        through epstopdf then PyMuPDF, GIF, BMP, TIFF and WebP through PyMuPDF. Every rendered result goes
        through figure_image.fit_for_model. Nothing is substituted when a tool is absent (R8).

    Inputs:
        source (dict): `kind`, `path_or_code` (a file path, or the code for tikz) and optional `name`
        out_dir (Path): where the result is written, created when needed
        preamble (str | None): the paper's preamble for a TikZ picture
        which, run, export (callable | None): shutil.which, subprocess.run and fig_export.export, injected
            by the tests; None resolves the real one at call time
        timeout (float): seconds allowed to one external tool
        max_long_edge, photo_colors, jpeg_quality (int): the image-fitting limits
        dpi (int): rendering resolution of a page document
        drawio_scale (int): scale of the draw.io export

    Outputs:
        result (dict): `status` (rendered, native, not_run), `file`, `format`, `estimated_tokens`, `reason`,
        `tool`, and `pages` for draw.io.

    Raises:
        RenderError: the output name would leave out_dir.
    --------------------------------------------------------------------------
    """
    which = which or shutil.which
    run = run or subprocess.run
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = _stem(source, out_dir)
    fit = {"max_long_edge": max_long_edge, "photo_colors": photo_colors, "jpeg_quality": jpeg_quality}
    kind, value = source["kind"], source["path_or_code"]
    if kind == "tikz":
        return _render_tikz(value, stem, out_dir, preamble, which, run, timeout, dpi, fit)
    if kind == "unknown":
        return _not_run("unknown source kind: %s" % value)
    path = Path(value)
    if not path.is_file():
        return _not_run("file not found: %s" % path.name)
    if kind in NATIVE_KINDS:
        return _native(path, kind, stem, out_dir, fit)
    if kind == "drawio":
        return _render_drawio(path, stem, out_dir, export, timeout, drawio_scale, fit)
    if kind == "eps":
        return _render_eps(path, stem, out_dir, which, run, timeout, dpi, fit)
    if kind in ("svg", "pdf") or kind in RASTER_KINDS:
        with tempfile.TemporaryDirectory() as tmp:
            png = Path(tmp) / "page.png"
            try:
                _pymupdf_to_png(path, png, dpi, kind in RASTER_KINDS)
            except Exception as exc:  # noqa: BLE001 - PyMuPDF raises several types on a bad file
                return _not_run("cannot read the %s file: %s" % (kind, exc), "pymupdf")
            return _finish(png, stem, out_dir, fit, "pymupdf")
    return _not_run("no renderer for source kind: %s" % kind)


def _native(path: Path, kind: str, stem: str, out_dir: Path, fit: Dict[str, int]) -> Dict[str, Any]:
    try:
        pix = fitz.Pixmap(str(path))
    except Exception as exc:  # noqa: BLE001
        return _not_run("cannot read the image: %s" % exc)
    if max(pix.width, pix.height) <= fit["max_long_edge"]:
        return _result("native", str(path), "jpeg" if kind == "jpg" else "png",
                       figure_image.estimated_tokens(pix.width, pix.height))
    cut = _finish(path, stem, out_dir, fit, None)
    cut["status"] = "native" if cut["status"] == "rendered" else cut["status"]
    return cut


def _render_tikz(code: str, stem: str, out_dir: Path, preamble: Optional[str], which: Callable, run: Callable,
                 timeout: float, dpi: int, fit: Dict[str, int]) -> Dict[str, Any]:
    exe = which("pdflatex")
    if not exe:
        return _not_run("pdflatex was not found on this machine", "pdflatex")
    with tempfile.TemporaryDirectory() as tmp:
        tex = Path(tmp) / "figure.tex"
        tex.write_text(standalone_text(code, preamble), encoding="utf-8")
        argv = [exe, "-interaction=nonstopmode", "-halt-on-error", "-output-directory", tmp, str(tex)]
        try:
            done = run(argv, capture_output=True, text=True, errors="replace", timeout=timeout, cwd=tmp)
        except subprocess.TimeoutExpired:
            return _not_run("pdflatex timeout after %s s" % timeout, "pdflatex")
        pdf = Path(tmp) / "figure.pdf"
        if done.returncode != 0 or not pdf.is_file():
            why = _first_error(done.stdout) or ("exit code %s" % done.returncode if done.returncode else "no PDF written")
            return _not_run("pdflatex failed: %s" % why, "pdflatex")
        png = Path(tmp) / "figure.png"
        try:
            _pymupdf_to_png(pdf, png, dpi, False)
        except Exception as exc:  # noqa: BLE001
            return _not_run("cannot rasterise the compiled figure: %s" % exc, "pdflatex")
        return _finish(png, stem, out_dir, fit, "pdflatex")


def _render_drawio(path: Path, stem: str, out_dir: Path, export: Optional[Callable], timeout: float, scale: int,
                   fit: Dict[str, int]) -> Dict[str, Any]:
    export = export or _load_export()
    if export is None:
        return _not_run("the draw.io export of paper2talk was not found", "draw.io")
    pages = len(re.findall(r"<diagram[\s>/]", path.read_text(encoding="utf-8", errors="replace")))
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "drawio.png"
        try:
            written = export(str(path), str(png), scale=scale, timeout=timeout)
        except RuntimeError as exc:
            return _not_run(str(exc), "draw.io")
        if not written or not png.is_file():
            return _not_run("draw.io wrote no image", "draw.io")
        note = "%d pages in the file, one exported" % pages if pages > 1 else None
        return _finish(png, stem, out_dir, fit, "draw.io", pages=pages, reason=note)


def _render_eps(path: Path, stem: str, out_dir: Path, which: Callable, run: Callable, timeout: float, dpi: int,
                fit: Dict[str, int]) -> Dict[str, Any]:
    exe = which("epstopdf")
    if not exe:
        return _not_run("epstopdf was not found on this machine", "epstopdf")
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "eps.pdf"
        try:
            done = run([exe, "--outfile=" + str(pdf), str(path)], capture_output=True, text=True, errors="replace",
                       timeout=timeout)
        except subprocess.TimeoutExpired:
            return _not_run("epstopdf timeout after %s s" % timeout, "epstopdf")
        if done.returncode != 0 or not pdf.is_file():
            return _not_run("epstopdf failed: exit code %s" % done.returncode, "epstopdf")
        png = Path(tmp) / "eps.png"
        try:
            _pymupdf_to_png(pdf, png, dpi, False)
        except Exception as exc:  # noqa: BLE001
            return _not_run("cannot rasterise the converted figure: %s" % exc, "epstopdf")
        return _finish(png, stem, out_dir, fit, "epstopdf")


def preamble_of(tex_text: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Take the paper's preamble: what lies before \\begin{document}, without the \\documentclass line
        and without comments.

    Inputs:
        tex_text (str): the LaTeX source

    Outputs:
        preamble (str): possibly empty.
    --------------------------------------------------------------------------
    """
    head = figure_tex.strip_comments(tex_text).split("\\begin{document}", 1)[0]
    return re.sub(r"\\documentclass\s*(\[[^\]]*\])?\s*\{[^}]*\}", "", head).strip()


def _settings(criteria_path: Path) -> Dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the rendering settings from the criteria file's `extraction` block.

    Inputs:
        criteria_path (Path): figure_criteria.json

    Outputs:
        settings (dict): the six values of SETTING_KEYS.

    Raises:
        CriteriaError: the file or one key is missing; the message names the key and the file.
    --------------------------------------------------------------------------
    """
    doc = figure_checks.load_criteria(criteria_path)
    block = doc.get("extraction", {})
    values = {}
    for key in SETTING_KEYS:
        if key not in block or "value" not in block[key]:
            raise figure_checks.CriteriaError("missing extraction.%s in %s" % (key, criteria_path.name))
        values[key] = block[key]["value"]
    return values


def main(argv: Optional[List[str]] = None) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        List the figure sources of a LaTeX document and, with --render, render each one.

    Inputs:
        argv (list[str] | None): --tex FILE, --out DIR, --render, --json, --criteria FILE

    Outputs:
        code (int): 0 done; 2 when the document or a configuration key is missing. The report goes to
        stdout, as JSON with --json.
    --------------------------------------------------------------------------
    """
    parser = argparse.ArgumentParser(description="List and optionally render the figures of a LaTeX document")
    parser.add_argument("--tex", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--criteria", default=str(DEFAULT_CRITERIA))
    args = parser.parse_args(argv)
    tex = Path(args.tex)
    if not tex.is_file():
        sys.stderr.write("figure_render: the .tex file was not found\n")
        return EXIT_REFUSAL
    try:
        settings = _settings(Path(args.criteria)) if args.render else {}
    except figure_checks.CriteriaError as exc:
        sys.stderr.write("figure_render: %s\n" % exc)
        return EXIT_REFUSAL
    text = tex.read_text(encoding="utf-8", errors="replace")
    base, out_dir = tex.parent, Path(args.out)
    preamble = preamble_of(text)
    report = []
    for fi, fig in enumerate(figure_tex.figures(text, base), start=1):
        entries = []
        for si, src in enumerate(fig["sources"], start=1):
            entry = {"kind": src["kind"], "origin": src["origin"]}
            if src["kind"] == "tikz" and src["origin"] != "file":
                entry["code_chars"] = len(src["path_or_code"])
            else:
                entry["path"] = src["path_or_code"]
            if args.render:
                stem = re.sub(r"[^A-Za-z0-9_-]", "_", fig["label"] or "figure%d" % fi) + "_%d" % si
                job = {"kind": src["kind"], "path_or_code": src["path_or_code"], "name": stem}
                if src["kind"] != "tikz":
                    located = figure_tex.inside_folder(base, src["path_or_code"]) if src["kind"] != "unknown" else None
                    if src["kind"] != "unknown" and located is None:
                        entry["render"] = _not_run("the source is outside the document folder")
                        entries.append(entry)
                        continue
                    job["path_or_code"] = str(located) if located is not None else src["path_or_code"]
                entry["render"] = render(job, out_dir, preamble, which=None, run=None, export=None,
                                         timeout=settings["render_timeout_s"], max_long_edge=settings["max_long_edge"],
                                         dpi=settings["render_dpi"], photo_colors=settings["photo_colors"],
                                         jpeg_quality=settings["jpeg_quality"], drawio_scale=settings["drawio_scale"])
            entries.append(entry)
        report.append({"label": fig["label"], "caption": fig["caption"], "line": fig["line"], "sources": entries})
    if args.json:
        print(json.dumps({"figures": report}, ensure_ascii=False, indent=2))
    else:
        for fig in report:
            print("%s (line %d): %d source(s)" % (fig["label"] or "no label", fig["line"], len(fig["sources"])))
            for src in fig["sources"]:
                rendered = src.get("render")
                print("  %s %s%s" % (src["kind"], src.get("path", "inline"),
                                     " -> %s" % (rendered["file"] or rendered["reason"]) if rendered else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
