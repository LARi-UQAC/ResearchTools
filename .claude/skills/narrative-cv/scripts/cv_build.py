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

HQP_ROW_KEYS = ("name", "cycle", "start", "end", "consent_cv", "current_position", "current_employer")
HQP_REQUIRED_KEYS = ("name", "cycle", "start", "end", "consent_cv")
_HQP_DATE_RE = re.compile(r"^\d{4}(-\d{2})?$")
_HQP_CONSENT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


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


def load_hqp_rules(types):
    """
    --------------------------------------------------------------------------
    Purpose:
        Return the HQP window length and bilingual labels from a loaded
        contribution_types.json document.

    Inputs:
        types (dict): the parsed contribution_types.json document

    Outputs:
        rules (dict): {"window_years": int, "labels": dict} (labels carries
            both "fr" and "en", each with recent_heading/archive_heading/
            ongoing/none)

    Raises:
        CvDataError: `types["hqp"]` or one of its keys is missing, or
            window_years is not an int >= 1
    --------------------------------------------------------------------------
    """
    try:
        hqp = types["hqp"]
        window_years = hqp["window_years"]
        labels = hqp["labels"]
    except KeyError as exc:
        raise CvDataError("contribution_types.json is missing key %s (expected under 'hqp')" % exc)
    if not isinstance(window_years, int) or isinstance(window_years, bool) or window_years < 1:
        raise CvDataError("hqp.window_years must be an int >= 1, got %r" % (window_years,))
    return {"window_years": window_years, "labels": labels}


def assert_inline_model(model):
    """
    --------------------------------------------------------------------------
    Purpose:
        Refuse a cv_model.json whose sections reference a `prose_file` on
        disk, since a request received over the network must never pick a
        file on the server (R24, C4).

    Details:
        Dict-shape checks only: no filesystem call is made, so the refusal
        happens identically whether or not the named file exists. The
        message names the offending section key, never the prose_file
        value, so a path traversal attempt is never echoed back.

    Inputs:
        model: the candidate cv_model.json document

    Outputs:
        None

    Raises:
        CvDataError: `model` is not a dict, `model["sections"]` is not a
            dict, or any section carries a `prose_file` key
    --------------------------------------------------------------------------
    """
    if not isinstance(model, dict):
        raise CvDataError("model must be an object, got %s" % type(model).__name__)
    sections = model.get("sections")
    if not isinstance(sections, dict):
        raise CvDataError("model.sections must be an object")
    for key, section in sections.items():
        if isinstance(section, dict) and "prose_file" in section:
            raise CvDataError(
                "section %s carries a prose_file key; an inline model must not "
                "reference a file on disk" % key)


def validate_hqp_rows(rows, reference_year, window_years):
    """
    --------------------------------------------------------------------------
    Purpose:
        Validate student rows against the closed HQP schema and tag each with
        whether it falls inside the consent-required window.

    Details:
        Every error names the row's index only, never a field value, so a
        malformed row never puts a student's name in a log or an error
        response (C3). Rows are returned as deep copies: the caller's own
        dicts are never mutated.

    Inputs:
        rows (list): candidate row dicts
        reference_year (int): the year the window ends
        window_years (int): the window length (from load_hqp_rules)

    Outputs:
        validated (list[dict]): deep copies of `rows`, each with an added
            boolean `in_window`

    Raises:
        CvDataError: `rows` is not a list, `reference_year` is not an int, a
            row is not a dict, carries an unknown or missing key, a field is
            malformed, or an in-window row has no consent_cv
    --------------------------------------------------------------------------
    """
    if not isinstance(reference_year, int) or isinstance(reference_year, bool):
        raise CvDataError("reference_year must be an int, got %r" % (reference_year,))
    if not isinstance(rows, list):
        raise CvDataError("hqp rows must be a list, got %s" % type(rows).__name__)

    validated = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise CvDataError("row %d is not an object" % index)
        unknown = sorted(set(row) - set(HQP_ROW_KEYS))
        if unknown:
            raise CvDataError("row %d has unknown key(s): %s" % (index, ", ".join(unknown)))
        missing = [key for key in HQP_REQUIRED_KEYS if key not in row]
        if missing:
            raise CvDataError("row %d is missing key(s): %s" % (index, ", ".join(missing)))
        if not isinstance(row["name"], str) or not row["name"].strip():
            raise CvDataError("row %d: name must be a non-empty string" % index)
        if not isinstance(row["cycle"], str) or not row["cycle"].strip():
            raise CvDataError("row %d: cycle must be a non-empty string" % index)
        start = row["start"]
        if not isinstance(start, str) or not _HQP_DATE_RE.match(start):
            raise CvDataError("row %d: start must match YYYY or YYYY-MM" % index)
        end = row["end"]
        if end is not None and (not isinstance(end, str) or not _HQP_DATE_RE.match(end)):
            raise CvDataError("row %d: end must be null or match YYYY or YYYY-MM" % index)
        consent = row["consent_cv"]
        if consent is not None and (not isinstance(consent, str) or not _HQP_CONSENT_RE.match(consent)):
            raise CvDataError("row %d: consent_cv must be null or an ISO YYYY-MM-DD date" % index)
        in_window = end is None or int(end[:4]) >= reference_year - window_years + 1
        if in_window and consent is None:
            raise CvDataError("row %d requires consent_cv (inside the consent window)" % index)
        copy = dict(row)
        copy["in_window"] = in_window
        validated.append(copy)
    return validated


def _hqp_date_value(datestr):
    """Return an orderable int for a 'YYYY' or 'YYYY-MM' string, most recent = largest."""
    year = int(datestr[:4])
    month = int(datestr[5:7]) if len(datestr) > 4 else 1
    return year * 12 + month


def _hqp_sort_key(row):
    """Ongoing (end is None) first, then most recent end, then most recent start, then name."""
    end = row["end"]
    end_rank = 0 if end is None else 1
    end_val = 0 if end is None else -_hqp_date_value(end)
    start_val = -_hqp_date_value(row["start"])
    return (end_rank, end_val, start_val, row["name"])


def _hqp_end_label(row, heading_labels):
    return heading_labels["ongoing"] if row["end"] is None else row["end"]


def _hqp_position_suffix(row, escape):
    """Return the ' — position, employer' suffix, or '' when no position is given."""
    position = row.get("current_position")
    if not position:
        return ""
    detail = escape(position)
    employer = row.get("current_employer")
    if employer:
        detail += ", %s" % escape(employer)
    return " \u2014 %s" % detail


def _hqp_block_latex(heading, rows, heading_labels):
    parts = ["\\section*{%s}\n" % escape_latex(heading)]
    if not rows:
        parts.append("%s\n\n" % escape_latex(heading_labels["none"]))
        return "".join(parts)
    parts.append("\\begin{itemize}\n")
    for row in rows:
        parts.append(
            "\\item \\textbf{%s} (%s, %s \u2013 %s)%s\n"
            % (
                escape_latex(row["name"]), escape_latex(row["cycle"]), escape_latex(row["start"]),
                escape_latex(_hqp_end_label(row, heading_labels)),
                _hqp_position_suffix(row, escape_latex),
            )
        )
    parts.append("\\end{itemize}\n\n")
    return "".join(parts)


def _hqp_block_text(heading, rows, heading_labels):
    lines = [heading, "=" * len(heading)]
    if not rows:
        lines.append(heading_labels["none"])
    else:
        for row in rows:
            lines.append(
                "- %s (%s, %s \u2013 %s)%s"
                % (
                    row["name"], row["cycle"], row["start"], _hqp_end_label(row, heading_labels),
                    _hqp_position_suffix(row, lambda text: text),
                )
            )
    lines.append("")
    return "\n".join(lines)


def render_hqp(rows_validated, language, labels, target):
    """
    --------------------------------------------------------------------------
    Purpose:
        Render validated HQP rows into the two-list (recent/archive) block
        described in spec section 4, for either the LaTeX or text renderer.

    Inputs:
        rows_validated (list[dict]): output of validate_hqp_rows()
        language (str): "fr" or "en"
        labels (dict): the bilingual labels dict (load_hqp_rules()["labels"])
        target (str): "latex" or "text"

    Outputs:
        block (str): the rendered recent list followed by the archive list

    Raises:
        CvDataError: target is neither "latex" nor "text"
    --------------------------------------------------------------------------
    """
    if target not in ("latex", "text"):
        raise CvDataError("render_hqp target must be 'latex' or 'text', got %r" % (target,))
    heading_labels = labels[language]
    recent = sorted((row for row in rows_validated if row["in_window"]), key=_hqp_sort_key)
    archive = sorted((row for row in rows_validated if not row["in_window"]), key=_hqp_sort_key)
    block = _hqp_block_latex if target == "latex" else _hqp_block_text
    return (
        block(heading_labels["recent_heading"], recent, heading_labels)
        + block(heading_labels["archive_heading"], archive, heading_labels)
    )


def _hqp_block(model, types, hqp, target):
    """Build the HQP block for `render_latex`/`render_text`, or raise per C8."""
    section3 = (model.get("sections") or {}).get("3") or {}
    if not section3.get("hqp_list"):
        raise CvDataError(
            "hqp rows were provided but section 3 does not declare hqp_list: true (C8)")
    rules = load_hqp_rules(types)
    language = model.get("language", "fr")
    rows_validated = validate_hqp_rows(hqp.get("rows", []), hqp.get("reference_year"), rules["window_years"])
    return render_hqp(rows_validated, language, rules["labels"], target)


def inline_model(path):
    """
    --------------------------------------------------------------------------
    Purpose:
        Load a cv_model.json and strip every section's `prose_file` key,
        producing a model ready to upload to ThesisTracker's /cv/build (which
        refuses prose_file - C4, C9).

    Inputs:
        path (str or Path): the cv_model.json file

    Outputs:
        model (dict): load_model(path), with every prose_file key removed;
            the result passes assert_inline_model

    Raises:
        CvDataError: same as load_model() (a prose_file missing, or
            resolving outside the model's folder)
    --------------------------------------------------------------------------
    """
    model = load_model(path)
    for section in model.get("sections", {}).values():
        if isinstance(section, dict):
            section.pop("prose_file", None)
    return model


def render_latex(model, types_path=None, hqp=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Render `model` to a complete, compilable LaTeX source satisfying the
        chosen portal variant's font/margin/header/footer rules.

    Inputs:
        model (dict): a cv_model.json document (see module docstring)
        types_path (str, Path or None): contribution_types.json override
        hqp (dict or None): {"rows": list, "reference_year": int} of
            consenting-student rows to render into section 3 (spec section
            4); None leaves the output byte-identical to before this
            parameter existed (C9)

    Outputs:
        source (str): the LaTeX document

    Raises:
        CvDataError: `hqp` is given but section 3 does not declare
            hqp_list: true (C8), or a row fails validate_hqp_rows()
    --------------------------------------------------------------------------
    """
    types = load_contribution_types(types_path)
    if model["portal_variant"] not in types["portal_variants"]:
        raise CvDataError("unknown portal_variant %r" % model["portal_variant"])
    hqp_block = _hqp_block(model, types, hqp, "latex") if hqp is not None else None

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
    if hqp_block is not None:
        parts.append(hqp_block)
    parts.append("\\end{document}\n")
    return "".join(parts)


def render_text(model, types_path=None, hqp=None):
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
    hqp_block = _hqp_block(model, types, hqp, "text") if hqp is not None else None
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
    text = "\n".join(lines)
    if hqp_block is not None:
        text = text + "\n" + hqp_block
    return text


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

    p_inline = sub.add_parser("inline")
    p_inline.add_argument("--model", required=True)
    p_inline.add_argument("--out", required=True)

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
        elif args.command == "inline":
            model_path, out_path = Path(args.model), Path(args.out)
            if model_path.resolve() == out_path.resolve():
                print(json.dumps({"status": "error", "message": "--out must not equal --model"}),
                      file=sys.stderr)
                return 2
            model = inline_model(args.model)
            offending = sorted(
                key for key, section in model.get("sections", {}).items()
                if isinstance(section, dict) and {"hqp", "hqp_rows", "rows"} & set(section))
            if offending:
                print(json.dumps({
                    "status": "error",
                    "message": "section(s) %s carry a student-row key; student rows never "
                               "come from a file" % ", ".join(offending)}), file=sys.stderr)
                return 2
            out_path.write_text(json.dumps(model, ensure_ascii=False, indent=1), encoding="utf-8")
            print(json.dumps({"status": "written", "file": str(out_path)}, ensure_ascii=False))
    except CvDataError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
