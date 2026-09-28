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

Section-2 item fields are plain text, escaped on render, with two exceptions
the funder's citation rules require: `**Name**` renders in bold (candidate and
co-researchers), and an `http(s)://` URL (a DOI) renders as a clickable
`\\url{}`. A single `*` after a supervised person's name is kept as typed.
Sections 1 and 3 `prose` are raw LaTeX, written by the caller, either inline
or as `"prose_file": "section1.tex"`, a file beside the model that
load_model() reads (no backslash doubling, no assembly script).
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cv_common import CvDataError, build_frq_filename, load_contribution_types  # noqa: E402

_LATEX_SPECIAL = {
    "\\": r"\textbackslash{}",
    "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
    "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_URL_RE = re.compile(r"https?://\S+")
# Punctuation that ends a sentence right after a URL belongs to the sentence, not the link.
_URL_TRAILING = ".,;:)"
_BABEL_LANGUAGE = {"fr": "french", "en": "english"}


def escape_latex(text):
    """Escape the LaTeX special characters in `text` (never applied to raw markup callers build themselves)."""
    return "".join(_LATEX_SPECIAL.get(ch, ch) for ch in text or "")


def inline_latex(text):
    """
    --------------------------------------------------------------------------
    Purpose:
        Render one plain-text item field to LaTeX: everything escaped, except
        `**bold**` markup (to `\\textbf{}`) and URLs (to a clickable `\\url{}`).

    Details:
        URLs are cut out BEFORE escaping, since `\\url{}` must receive the raw
        characters, and trailing sentence punctuation is handed back to the
        text. Bold markup is converted AFTER escaping, which is safe because
        escape_latex never touches `*`. An unbalanced `**` stays literal.

    Inputs:
        text (str or None): the item field as typed by the caller

    Outputs:
        latex (str): the LaTeX-safe rendering
    --------------------------------------------------------------------------
    """
    parts, cursor = [], 0
    text = text or ""
    for match in _URL_RE.finditer(text):
        url = match.group(0).rstrip(_URL_TRAILING)
        parts.append(_BOLD_RE.sub(r"\\textbf{\1}", escape_latex(text[cursor:match.start()])))
        parts.append("\\url{%s}" % url.replace("%", r"\%").replace("#", r"\#"))
        cursor = match.start() + len(url)
    parts.append(_BOLD_RE.sub(r"\\textbf{\1}", escape_latex(text[cursor:])))
    return "".join(parts)


def plain_text(text):
    """Strip the `**bold**` markup for the plain-text companion, where bold cannot be carried."""
    return _BOLD_RE.sub(r"\1", text or "")


def _item_labels(types, language):
    """Return the (role, period, clientele) labels for `language`, naming the missing key (R3)."""
    try:
        labels = types["item_labels"]
        return tuple(labels[key][language] for key in ("role", "period", "clientele"))
    except KeyError as exc:
        raise CvDataError("contribution_types.json: item_labels is missing key %s for language %r" % (exc, language))


def _item_references(item):
    """Return an item's optional `references` list, refusing anything but a list of strings (R3)."""
    refs = item.get("references", [])
    if not isinstance(refs, list) or not all(isinstance(r, str) for r in refs):
        raise CvDataError("section-2 item 'references' must be a list of strings, got %r" % (refs,))
    return refs


def citation_warnings(model, types_path=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Flag bolded names in section-2 references that the chosen portal
        variant's citation rules do not allow.

    Details:
        The FRQ bolds the candidate and the co-researchers. The tri-agency CV
        bolds only a lead author who is not listed first, so any bold there is
        reported for the author to confirm: a bolded third author reads as
        the lead author to a reviewer. A warning, not a refusal, because the
        alphabetical-authorship case is legitimate and cannot be detected.

    Inputs:
        model (dict): a cv_model.json document
        types_path (str, Path or None): contribution_types.json override

    Outputs:
        warnings (list[str]): one message per offending bolded name
    --------------------------------------------------------------------------
    """
    types = load_contribution_types(types_path)
    rules = types["portal_variants"][model["portal_variant"]].get("citation_rules", {})
    if rules.get("bold_candidate_and_coresearchers", True):
        return []
    warnings = []
    for n, item in enumerate(model["sections"].get("2", {}).get("items", []), start=1):
        for ref in _item_references(item):
            for name in _BOLD_RE.findall(ref):
                warnings.append(
                    "item %d: bold '%s' in a %s reference; this variant bolds only a lead author "
                    "not listed first" % (n, name, model["portal_variant"]))
    return warnings


def _clientele_labels(types, language):
    field = "label_en" if language == "en" else "label_fr"
    return {c["id"]: c.get(field, c["label_fr"]) for c in types["clienteles"]}


def _preamble(model, types):
    variant = types["portal_variants"][model["portal_variant"]]
    font_pkg = {
        "Times New Roman": r"\usepackage{mathptmx}",
        "Arial": r"\usepackage{helvet}\renewcommand{\familydefault}{\sfdefault}",
    }.get(variant.get("font"), r"\usepackage{mathptmx}")
    margin = variant.get("margins_cm", 2)
    language = model.get("language", "fr")
    babel = "\\usepackage[%s]{babel}\n" % _BABEL_LANGUAGE.get(language, "french")
    if language != "en":
        # babel-french turns itemize labels into long dashes, which the style rules forbid.
        babel += "\\frenchsetup{StandardLists=true}\n"
    if variant.get("running_header", True):
        header = (
            f"\\lhead{{{escape_latex(model['candidate_name'])}}}\n"
            f"\\rfoot{{{escape_latex(model['document_title'])}}}\n"
            "\\lfoot{\\thepage}\n"
        )
    else:
        header = "\\cfoot{\\thepage}\n"
    return (
        "\\documentclass[12pt,letterpaper]{article}\n"
        "\\usepackage[T1]{fontenc}\n"
        "\\usepackage[utf8]{inputenc}\n"
        f"{babel}"
        f"\\usepackage[margin={margin}cm]{{geometry}}\n"
        f"{font_pkg}\n"
        "\\usepackage{fancyhdr}\n"
        "\\usepackage{enumitem}\n"
        "\\usepackage[hidelinks]{hyperref}\n"
        "\\urlstyle{same}\n"
        "\\pagestyle{fancy}\n"
        "\\fancyhf{}\n"
        "\\renewcommand{\\headrulewidth}{0pt}\n"
        f"{header}"
        "\\setlength{\\parindent}{0pt}\n"
        "\\setlength{\\parskip}{0.5em}\n"
    )


def _front_matter(model, types):
    """Print the variant's own document heading and name line, when its template carries them."""
    variant = types["portal_variants"][model["portal_variant"]]
    language = model.get("language", "fr")
    heading = variant.get("document_heading", {}).get(language)
    if not heading:
        return ""
    name_label = variant.get("name_label", {}).get(language, "")
    return "{\\Large\\bfseries %s\\par}\n\\section*{%s : %s}\n" % (
        escape_latex(heading), escape_latex(name_label), escape_latex(model["candidate_name"]))


def load_model(path):
    """
    --------------------------------------------------------------------------
    Purpose:
        Read a cv_model.json and resolve each section's optional `prose_file`
        (a .tex file holding that section's raw LaTeX prose) into `prose`.

    Details:
        Raw LaTeX inside a JSON string doubles every backslash, so long prose
        is kept in its own file beside the model. The path is resolved first,
        then required to sit inside the model's folder (R24): a prose_file is
        input, and `..` must not reach an arbitrary file on disk.

    Inputs:
        path (str or Path): the cv_model.json file

    Outputs:
        model (dict): the model with every prose_file replaced by its text

    Raises:
        CvDataError: a prose_file is missing, or resolves outside the model's
            folder
    --------------------------------------------------------------------------
    """
    path = Path(path).resolve()
    with open(path, "r", encoding="utf-8") as handle:
        model = json.load(handle)
    root = path.parent
    for key, section in model.get("sections", {}).items():
        name = section.get("prose_file") if isinstance(section, dict) else None
        if not name:
            continue
        target = (root / name).resolve()
        if root != target and root not in target.parents:
            raise CvDataError("section %s prose_file %r resolves outside %s" % (key, name, root))
        if not target.is_file():
            raise CvDataError("section %s prose_file %r not found in %s" % (key, name, root))
        section["prose"] = target.read_text(encoding="utf-8")
    return model


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

    language = model.get("language", "fr")
    clientele_labels = _clientele_labels(types, language)
    role_label, period_label, clientele_label = _item_labels(types, language)

    parts = [_preamble(model, types), "\\begin{document}\n", _front_matter(model, types)]
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
                refs = "".join("%s\\newline\n" % inline_latex(ref) for ref in _item_references(item))
                parts.append(
                    "\\item %s%s\\newline\n\\textit{%s :} %s. \\textit{%s :} %s. \\textit{%s :} %s.\n"
                    % (
                        refs,
                        inline_latex(item.get("description", "")),
                        escape_latex(role_label), inline_latex(item.get("role", "")),
                        escape_latex(period_label), escape_latex(item.get("date", "")),
                        escape_latex(clientele_label), escape_latex(clienteles),
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
    language = model.get("language", "fr")
    clientele_labels = _clientele_labels(types, language)
    role_label, period_label, clientele_label = _item_labels(types, language)

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
                entry = [plain_text(ref) for ref in _item_references(item)]
                entry.append(plain_text(item.get("description", "")))
                lines.append("%d. %s" % (i, entry[0]))
                lines.extend("   %s" % line for line in entry[1:])
                lines.append(
                    "   %s : %s. %s : %s. %s : %s."
                    % (role_label, plain_text(item.get("role", "")), period_label,
                       item.get("date", ""), clientele_label, clienteles)
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
            model = load_model(args.model)
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
            print(json.dumps({"status": "written", "files": written,
                              "warnings": citation_warnings(model, args.types)}, ensure_ascii=False))
        elif args.command == "filename":
            print(json.dumps({"filename": build_frq_filename(args.surname, args.frq_id, args.title)}))
        elif args.command == "check-pages":
            print(json.dumps(check_page_budget(args.pdf, args.language, args.types)))
    except CvDataError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
