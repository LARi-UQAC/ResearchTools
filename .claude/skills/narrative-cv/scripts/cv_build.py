"""
cv_build.py - render ONE cv_model.json into LaTeX and/or plain text, build the
mandatory filename, and check the compiled page count against the FRQ cap.

Stage: the last step of the narrative-cv pipeline. Mirrors paper2talk's
talk_model.py pattern - one JSON model, several renderers - so the LaTeX
(old-FRQnet-portal / tri-agency PDF upload) and plain-text (new-FRQnet-portal
paste-in) outputs can never drift apart: both come from the same sections.

cv_model.json shape:
    {
      "language": "fr" | "en",
      "portal_variant": "frq_old_portal" | "frq_new_portal" | "tri_agency",
      "candidate_name": "Martin Otis",
      "document_title": "CV descriptif",
      "frq_id": "XXXYY1234",                 # required only for frq_old_portal
      "sections": {
        "1": {"title": "...", "prose": "..."},
        "2": {"title": "...", "items": [
                {"description": "...", "role": "...", "date": "2024",
                 "clienteles": ["milieu_academique"]}, ...]},
        "3": {"title": "...", "prose": "..."}
      }
    }
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cv_common import CvDataError, build_frq_filename, load_contribution_types  # noqa: E402

_LATEX_SPECIAL = {
    "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
    "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}


def escape_latex(text):
    """Escape the LaTeX special characters in `text` (never applied to raw markup callers build themselves)."""
    return "".join(_LATEX_SPECIAL.get(ch, ch) for ch in text or "")


def _preamble(model, types):
    variant = types["portal_variants"][model["portal_variant"]]
    font_pkg = {
        "Times New Roman": r"\usepackage{mathptmx}",
        "Arial": r"\usepackage{helvet}\renewcommand{\familydefault}{\sfdefault}",
    }.get(variant.get("font"), r"\usepackage{mathptmx}")
    margin = variant.get("margins_cm", 2)
    return (
        "\\documentclass[12pt]{article}\n"
        "\\usepackage[T1]{fontenc}\n"
        "\\usepackage[utf8]{inputenc}\n"
        f"\\usepackage[margin={margin}cm]{{geometry}}\n"
        f"{font_pkg}\n"
        "\\usepackage{fancyhdr}\n"
        "\\usepackage{enumitem}\n"
        "\\pagestyle{fancy}\n"
        "\\fancyhf{}\n"
        f"\\lhead{{{escape_latex(model['candidate_name'])}}}\n"
        f"\\rfoot{{{escape_latex(model['document_title'])}}}\n"
        "\\lfoot{\\thepage}\n"
        "\\setlength{\\parindent}{0pt}\n"
        "\\setlength{\\parskip}{0.5em}\n"
    )


def render_latex(model, types_path=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Render `model` to a complete, compilable LaTeX source satisfying the
        chosen portal variant's font/margin/header/footer rules.

    Inputs:
        model (dict): a cv_model.json document (see module docstring)
        types_path (str, Path or None): contribution_types.json override

    Outputs:
        source (str): the LaTeX document
    --------------------------------------------------------------------------
    """
    types = load_contribution_types(types_path)
    if model["portal_variant"] not in types["portal_variants"]:
        raise CvDataError("unknown portal_variant %r" % model["portal_variant"])

    clientele_labels = {c["id"]: c["label_fr"] for c in types["clienteles"]}

    parts = [_preamble(model, types), "\\begin{document}\n"]
    for key in ("1", "2", "3"):
        section = model["sections"].get(key)
        if not section:
            continue
        parts.append("\\section*{%s}\n" % escape_latex(section["title"]))
        if "items" in section:
            if not section["items"]:
                parts.append("s.o.\n\n")
                continue
            parts.append("\\begin{enumerate}[leftmargin=*]\n")
            for item in section["items"]:
                clienteles = ", ".join(clientele_labels.get(c, c) for c in item.get("clienteles", []))
                parts.append(
                    "\\item \\textbf{%s} (%s) -- %s. Clientèle : %s.\n"
                    % (
                        escape_latex(item.get("date", "")),
                        escape_latex(item.get("role", "")),
                        escape_latex(item.get("description", "")),
                        escape_latex(clienteles),
                    )
                )
            parts.append("\\end{enumerate}\n\n")
        else:
            parts.append(section.get("prose", "") + "\n\n")
    parts.append("\\end{document}\n")
    return "".join(parts)


def render_text(model, types_path=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Render `model` to a plain-text/Markdown companion, for the new-FRQnet
        portal's direct paste-in (that channel takes no file upload at all).

    Inputs / Outputs:
        Same as render_latex(), returning plain text instead of LaTeX.
    --------------------------------------------------------------------------
    """
    types = load_contribution_types(types_path)
    clientele_labels = {c["id"]: c["label_fr"] for c in types["clienteles"]}

    lines = []
    for key in ("1", "2", "3"):
        section = model["sections"].get(key)
        if not section:
            continue
        lines.append(section["title"])
        lines.append("=" * len(section["title"]))
        if "items" in section:
            if not section["items"]:
                lines.append("s.o.")
            for i, item in enumerate(section["items"], start=1):
                clienteles = ", ".join(clientele_labels.get(c, c) for c in item.get("clienteles", []))
                lines.append(
                    "%d. [%s] %s -- %s (Clientèle : %s)"
                    % (i, item.get("date", ""), item.get("role", ""), item.get("description", ""), clienteles)
                )
        else:
            lines.append(section.get("prose", ""))
        lines.append("")
    return "\n".join(lines)


def count_pdf_pages(pdf_path):
    """
    --------------------------------------------------------------------------
    Purpose:
        Count the pages of a compiled PDF, for the page-budget check.

    Inputs:
        pdf_path (str or Path): the compiled CV PDF

    Outputs:
        pages (int)

    Raises:
        CvDataError: pypdf is not installed, or the file cannot be read
    --------------------------------------------------------------------------
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise CvDataError("pypdf is required for page counting (pip install pypdf): %s" % exc)
    try:
        return len(PdfReader(str(pdf_path)).pages)
    except Exception as exc:  # pragma: no cover - pypdf raises several distinct types
        raise CvDataError("could not read PDF %s: %s" % (pdf_path, exc))


def check_page_budget(pdf_path, language, types_path=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Compare a compiled CV's page count against the FRQ/tri-agency cap
        (6 pages French, 5 pages English).

    Inputs:
        pdf_path (str or Path): the compiled CV PDF
        language (str): "fr" or "en"
        types_path (str, Path or None): contribution_types.json override

    Outputs:
        report (dict): {"pages", "max_pages", "over_budget" (bool)}
    --------------------------------------------------------------------------
    """
    types = load_contribution_types(types_path)
    max_pages = types["page_budget"][language]
    pages = count_pdf_pages(pdf_path)
    return {"pages": pages, "max_pages": max_pages, "over_budget": pages > max_pages}


def compile_latex(tex_path, outdir=None, runner=subprocess.run):
    """
    --------------------------------------------------------------------------
    Purpose:
        Run pdflatex twice (cross-references settle on the second pass) over
        `tex_path`, matching the rest of this repo's LaTeX build convention.

    Inputs:
        tex_path (str or Path): the .tex source to compile
        outdir (str, Path or None): output directory (defaults to the source's
            own directory, per the repo's out/ convention when the caller
            passes one)
        runner (callable): injected for tests (R19); defaults to
            subprocess.run

    Outputs:
        result (dict): {"returncode", "pdf_path"}
    --------------------------------------------------------------------------
    """
    tex_path = Path(tex_path)
    outdir = Path(outdir) if outdir else tex_path.parent
    cmd = ["pdflatex", "-interaction=nonstopmode", "-output-directory", str(outdir), str(tex_path)]
    result = None
    for _ in range(2):
        result = runner(cmd, capture_output=True, text=True, timeout=120)
    return {"returncode": result.returncode if result else 1, "pdf_path": str(outdir / (tex_path.stem + ".pdf"))}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_render = sub.add_parser("render")
    p_render.add_argument("--model", required=True)
    p_render.add_argument("--target", choices=["latex", "text", "both"], default="both")
    p_render.add_argument("--out", required=True, help="output path without extension")
    p_render.add_argument("--types")

    p_filename = sub.add_parser("filename")
    p_filename.add_argument("--surname", required=True)
    p_filename.add_argument("--frq-id", required=True)
    p_filename.add_argument("--title", required=True)

    p_pages = sub.add_parser("check-pages")
    p_pages.add_argument("--pdf", required=True)
    p_pages.add_argument("--language", required=True, choices=["fr", "en"])
    p_pages.add_argument("--types")

    args = parser.parse_args()

    try:
        if args.command == "render":
            with open(args.model, "r", encoding="utf-8") as handle:
                model = json.load(handle)
            out = Path(args.out)
            written = []
            if args.target in ("latex", "both"):
                tex_path = out.with_suffix(".tex")
                tex_path.write_text(render_latex(model, args.types), encoding="utf-8")
                written.append(str(tex_path))
            if args.target in ("text", "both"):
                txt_path = out.with_suffix(".txt")
                txt_path.write_text(render_text(model, args.types), encoding="utf-8")
                written.append(str(txt_path))
            print(json.dumps({"status": "written", "files": written}))
        elif args.command == "filename":
            print(json.dumps({"filename": build_frq_filename(args.surname, args.frq_id, args.title)}))
        elif args.command == "check-pages":
            print(json.dumps(check_page_budget(args.pdf, args.language, args.types)))
    except CvDataError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
