"""
generate_letter.py - recommendation-letter skill.

Two-track LaTeX letter generator. Standard library plus PyYAML, which reads the
signatory out of the active domain profile (letter_identity.py); the profile is
YAML because that is where every other domain-specific value already lives.
Authored track (scholarship,
academic_position, industry_position, appreciation): the caller supplies
body_tex, the script wraps it in the shared scaffold. Form track (acceptance,
dispense): the script assembles a fixed French template from config fields.

Quality patterns (see references/quality-patterns.md): direct opening verdict,
quantified claims, named funding sources, the professor's own experience,
future collaboration, availability. Style hygiene: no invisible characters,
no em dash, straight quotes only (AI-usage target < 20%).

Usage:
    python generate_letter.py --config CONFIG [--output out/] [--no-compile] [--strict]
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import unicodedata

import letter_identity
import letter_templates as tpl

PLACEHOLDER = "[À COMPLÉTER]"

_AUTHORED = ("scholarship", "academic_position", "industry_position", "appreciation")

_DOCTORAL_TITLES = ("Dr.", "Dr", "Pr.", "Pr", "Pre.", "Dre.", "Prof.")

_LATEX_ESCAPES = [
    ("&", r"\&"), ("%", r"\%"), ("#", r"\#"), ("_", r"\_"),
    ("$", r"\$"), ("{", r"\{"), ("}", r"\}"),
    ("~", r"\textasciitilde{}"), ("^", r"\textasciicircum{}"),
]

MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
             "août", "septembre", "octobre", "novembre", "décembre"]
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December"]

_ZERO_WIDTH = ("​", "‌", "‍")
_SMART_QUOTES = ("“", "”", "‘", "’")


# --- config / CLI ---------------------------------------------------------

def load_config(path):
    """Read a JSON config file. Raises ValueError on a parse error."""
    with open(path, "r", encoding="utf-8") as fh:
        try:
            return json.load(fh)
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid JSON config: %s" % exc)


def surname_slug(candidate_name):
    """Last whitespace token, ASCII-folded, lowercased. '' if empty."""
    if not candidate_name:
        return ""
    token = candidate_name.strip().split()[-1]
    folded = unicodedata.normalize("NFKD", token)
    folded = folded.encode("ascii", "ignore").decode("ascii")
    return folded.lower()


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Generate a letter (LaTeX/PDF) signed by the active profile.")
    p.add_argument("--config", required=True, help="Path to the JSON config.")
    p.add_argument("--output", default="out", help="Output directory (default: out).")
    p.add_argument("--no-compile", action="store_true", help="Emit .tex only.")
    p.add_argument("--strict", action="store_true",
                   help="Fail (exit 3) on any style-hygiene violation.")
    return p.parse_args(argv)


# --- escaping / dates -----------------------------------------------------

def escape_latex(value):
    """Escape LaTeX specials in a plain-text scalar. Accents pass through."""
    if value is None:
        return ""
    out = str(value)
    for src, dst in _LATEX_ESCAPES:
        out = out.replace(src, dst)
    return out


def _split_iso(iso):
    """('2026','03','27') -> (2026, 3, 27) or None on any failure."""
    try:
        y, m, d = iso.split("-")
        return int(y), int(m), int(d)
    except (ValueError, AttributeError):
        return None


def format_date(iso, language):
    parts = _split_iso(iso)
    if parts is None:
        return PLACEHOLDER
    y, m, d = parts
    if language == "fr":
        return "Le %d %s %d" % (d, MONTHS_FR[m - 1], y)
    return "%s %d, %d" % (MONTHS_EN[m - 1], d, y)


def format_date_dispense(iso):
    parts = _split_iso(iso)
    if parts is None:
        return PLACEHOLDER
    y, m, d = parts
    return "le %d %s %d" % (d, MONTHS_FR[m - 1], y)


# --- candidate reference --------------------------------------------------

def derive_candidate_reference(config):
    """Canonical way to name the candidate, per status + gender + language."""
    name = config.get("candidate_name", "") or PLACEHOLDER
    status = config.get("candidate_status", "applicant")
    title = config.get("candidate_title", "")
    program = config.get("candidate_program", "") or PLACEHOLDER
    fem = config.get("candidate_gender", "M") == "F"
    lang = config.get("language", "fr")
    if status == "graduated":
        if lang == "fr":
            article = "la" if fem else "le"
            return ("%s %s %s" % (article, title, name)).strip()
        return ("%s %s" % (title, name)).strip()
    if status == "current_student":
        if lang == "fr":
            word = "étudiante" if fem else "étudiant"
            return "%s, %s au %s" % (name, word, program)
        return "%s, a student in the %s" % (name, program)
    # applicant
    if lang == "fr":
        noun = "la candidate" if fem else "le candidat"
        return "%s (%s)" % (noun, name)
    return "the candidate %s" % name


def status_title_warnings(config):
    warns = []
    status = config.get("candidate_status", "applicant")
    title = (config.get("candidate_title", "") or "").strip()
    if status == "graduated" and title not in _DOCTORAL_TITLES:
        warns.append("status is 'graduated' but candidate_title '%s' is not a "
                     "doctoral title" % title)
    if status in ("applicant", "current_student") and title in (
            "Dr.", "Dr", "Dre.", "Pr.", "Pr"):
        warns.append("status is '%s' but candidate_title is a doctoral title "
                     "'%s'" % (status, title))
    return warns


# --- style-hygiene linter -------------------------------------------------

def style_hygiene_violations(text):
    """Return a list of style-hygiene problems (empty if clean).

    Enforces the .claude/CLAUDE.md 'Style hygiene' list on generated prose:
    invisible chars, ellipsis char, em/en dash, unicode tags, smart quotes,
    and stray markdown bold/heading marks.
    """
    text = text or ""
    found = []
    if any(z in text for z in _ZERO_WIDTH):
        found.append("zero-width character (U+200B/C/D)")
    if "…" in text:
        found.append("ellipsis character (U+2026) - use ...")
    if "—" in text or "–" in text:
        found.append("em/en dash - use a hyphen or parentheses")
    if any(0xE0000 <= ord(c) <= 0xE007F for c in text):
        found.append("unicode tag character (U+E0000-E007F)")
    if any(q in text for q in _SMART_QUOTES):
        found.append("smart quote - use straight quotes")
    if "**" in text or re.search(r"(?m)^\s*#", text):
        found.append("stray markdown (** or leading #)")
    return found


# --- placeholders ---------------------------------------------------------

def apply_gender(text, gender):
    """Replace %%GENDER_*%% / %%SALUTATION%% placeholders. Applied last."""
    idx = 1 if gender == "F" else 0
    out = text
    for key, pair in tpl.GENDER_MAP.items():
        out = out.replace("%%%%%s%%%%" % key, pair[idx])
    return out


def fill_scalars(text, mapping):
    """Replace %%KEY%% with escape_latex(value) for each key in mapping."""
    out = text
    for key, value in mapping.items():
        out = out.replace("%%%%%s%%%%" % key, escape_latex(value))
    return out


# --- funding paragraph ----------------------------------------------------

def _supervisor_funding(config):
    model = config.get("funding_model", "") or ""
    amount = str(config.get("funding_amount", "") or "")
    parts = []
    if "mitacs_bso" in model:
        parts.append("L'étudiant%%GENDER_E%% a obtenu la bourse d'études "
                     "supérieures de MITACS (BSO), qui couvre 15 000\\$ sur un an.")
    if "befm" in model:
        parts.append("Une bourse d'exemption des frais majorés (BEFM) de "
                     "12 000\\$/an est également accordée.")
    if "mitacs_acceleration" in model:
        parts.append("Chaque unité de stage MITACS Accélération octroie une "
                     "bourse de 12 500\\$, sous réserve de l'acceptation des "
                     "partenaires industriels et de la disponibilité des fonds.")
    if "mitacs_gra" in model:
        parts.append("L'étudiant%%GENDER_E%% bénéficie du programme MITACS "
                     "Globalink Research Award.")
    if "internal" in model:
        parts.append("L'étudiant%%GENDER_E%% pourra aussi agir comme "
                     "assistant%%GENDER_E%% de recherche (environ 2500\\$/an) et "
                     "auxiliaire d'enseignement (environ 2500\\$/an) au sein du "
                     "%%LAB_ACRONYM%%.")
    if amount and not parts:
        parts.append("Le montant de la bourse est de %s\\$/an, conditionnel à la "
                     "performance dans les activités de recherche."
                     % escape_latex(amount))
    return parts


def _candidate_funding(config):
    model = config.get("funding_model", "") or ""
    details = config.get("funding_source_details", "") or ""
    parts = []
    if "self_funded" in model:
        parts.append("L'étudiant%%GENDER_E%% assure son propre financement "
                     "(ressources personnelles ou familiales).")
    if "scholarship" in model:
        base = ("L'étudiant%%GENDER_E%% assure son propre financement au moyen "
                "d'une bourse externe")
        base += (" (%s)." % escape_latex(details)) if details else "."
        parts.append(base)
        details = ""  # consumed
    if details:
        parts.append(escape_latex(details))
    return parts


def build_funding_paragraph(config):
    provider = config.get("funding_provider", "")
    parts = []
    if provider in ("supervisor", "combination"):
        parts += _supervisor_funding(config)
    if provider in ("candidate", "combination"):
        parts += _candidate_funding(config)
    extra = config.get("funding_source_details", "") or ""
    if provider == "supervisor" and extra and escape_latex(extra) not in " ".join(parts):
        parts.append(escape_latex(extra))
    if not parts:
        return "[À COMPLÉTER : détails du financement]"
    return " ".join(parts)


# --- authored-track assembly ----------------------------------------------

def count_words(body_tex):
    """Count words in body prose. Strips LaTeX commands and braces first."""
    text = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", " ", body_tex or "")
    text = text.replace("{", " ").replace("}", " ")
    text = re.sub(r"[~^_&%$\\]", " ", text)
    return len([w for w in text.split() if w])


def _babel(language):
    return "french" if language == "fr" else "english"


# --- signatory blocks, rendered from the active profile -------------------
# The values come from author.letter and are LaTeX-ready by contract, so they
# are inserted verbatim and never passed through escape_latex(): escaping a
# field that already reads \href{...} would print the macro instead of running
# it. Candidate-supplied text keeps going through fill_scalars as before.

def _stacked(lines):
    """Join LaTeX lines with a line break after every entry but the last."""
    return "\\\\\n".join(lines)


def render_letterhead(identity, lang):
    """The letterhead scaffold with this profile's address block in it."""
    key = "letterhead_fr" if lang == "fr" else "letterhead_en"
    return tpl.LETTERHEAD.replace("%%LETTERHEAD_LINES%%",
                                  _stacked(identity[key]))


def render_signature(identity, lang):
    """The closing scaffold with this profile's name and credential lines."""
    scaffold = tpl.SIGNATURE_FR if lang == "fr" else tpl.SIGNATURE_EN
    name = identity["signature_name_fr" if lang == "fr" else "signature_name_en"]
    lines = identity["signature_lines_fr" if lang == "fr" else "signature_lines_en"]
    text = scaffold.replace("%%SIGNATURE_NAME%%", name)
    return text.replace("%%SIGNATURE_LINES%%",
                        _stacked(["{\\small %s}" % line for line in lines]))


def assemble_authored(config, identity=None):
    """Full .tex for scholarship/academic_position/industry_position/appreciation."""
    identity = identity if identity is not None else letter_identity.load_identity()
    lang = config.get("language", "fr")
    preamble = tpl.PREAMBLE.replace("%%BABEL_LANGUAGE%%", _babel(lang))
    letterhead = render_letterhead(identity, lang)
    signature = render_signature(identity, lang)
    date = format_date(config.get("date", ""), lang)
    salutation = ("Madame, Monsieur," if lang == "fr"
                  else "Dear Members of the Committee,")
    ref = config.get("reference_number", "") or ""
    ref_line = ("\\hfill %s\n\n" % escape_latex(ref)) if ref else ""
    subject_word = "Objet~:" if lang == "fr" else "Subject:"
    regarding = "Lettre concernant" if lang == "fr" else "Regarding"
    subject = "\\textbf{%s %s %s}\n\n" % (
        subject_word, regarding,
        escape_latex(config.get("target", "") or PLACEHOLDER))
    body = config.get("body_tex", "") or (
        "[À COMPLÉTER : corps de la lettre]" if lang == "fr"
        else "[TO COMPLETE: body]")
    return "".join([preamble, letterhead, ref_line, date, "\n\n", subject,
                    salutation, "\n\n", body, "\n\n", signature])


# --- acceptance form ------------------------------------------------------

def _clean_spaces(text):
    """Collapse the blank runs left by omitted conditional sentences."""
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text


def _acceptance_conditionals(config):
    model = config.get("funding_model", "") or ""
    collab = config.get("lab_collaborators", "") or ""
    collab_sentence = ("%%GENDER_IL%% travaillera avec " + escape_latex(collab) + "."
                       if collab else "")
    if "mitacs_acceleration" in model:
        partner = config.get("partner_company", "") or ""
        clause = ("avec le partenaire industriel " + escape_latex(partner)
                  if partner else "")
        mitacs_sentence = ("%%GENDER_IL%% aura l'opportunité de réaliser un ou "
                           "plusieurs stages MITACS Accélération " + clause + ".")
        mitacs_sentence = mitacs_sentence.replace("Accélération .", "Accélération.")
    elif "mitacs_gra" in model:
        mitacs_sentence = ("%%GENDER_IL%% bénéficie du programme MITACS "
                           "Globalink Research Award.")
    else:
        mitacs_sentence = ""
    tools = config.get("tools_technologies", "") or ""
    end = config.get("project_end_date", "") or ""
    if tools:
        details = ("%%GENDER_IL%% sera responsable de la conception sous "
                   + escape_latex(tools) + ".")
        if end:
            details += (" Ce projet s'étendra jusqu'à la fin du mois de "
                        + escape_latex(end) + ".")
        project_details = details
    else:
        project_details = ""
    prereq = config.get("prerequisites", "") or ""
    if prereq:
        prereq_par = ("Notez que l'acceptation est assortie d'une propédeutique "
                      "(condition) : la réussite de " + escape_latex(prereq) + ". "
                      "L'étudiant%%GENDER_E%% pourra bénéficier d'une bourse à "
                      "condition de réussir ces cours.")
    else:
        prereq_par = ""
    return {
        "LAB_COLLABORATORS_SENTENCE": collab_sentence,
        "MITACS_OPPORTUNITY_SENTENCE": mitacs_sentence,
        "PROJECT_DETAILS_PARAGRAPH": project_details,
        "FUNDING_PARAGRAPH": build_funding_paragraph(config),
        "PREREQUISITES_PARAGRAPH": prereq_par,
        "DEGREE_DESCRIPTION": tpl.DEGREE_DESCRIPTION.get(
            config.get("degree_level", ""), "[À COMPLÉTER : niveau d'études]"),
    }


def build_acceptance(config, identity=None):
    identity = identity if identity is not None else letter_identity.load_identity()
    gender = config.get("candidate_gender", "M")
    text = tpl.TEMPLATE_ACCEPTANCE_FR.replace("%%LETTERHEAD_FR%%",
                                              render_letterhead(identity, "fr"))
    text = tpl.PREAMBLE.replace("%%BABEL_LANGUAGE%%", "french") + text
    text = text.replace("%%SIGNATURE_FR%%", render_signature(identity, "fr"))
    text = text.replace("%%DATE%%", format_date(config.get("date", ""), "fr"))
    # raw (LaTeX-safe) conditional blocks - user free text inside is escaped
    for key, value in _acceptance_conditionals(config).items():
        text = text.replace("%%%%%s%%%%" % key, value)
    # scalar (escaped) fields
    text = fill_scalars(text, {
        "CANDIDATE_NAME": config.get("candidate_name", "") or PLACEHOLDER,
        "PROJECT_DESCRIPTION": config.get("project_description", "") or PLACEHOLDER,
    })
    # After the conditional blocks, not before: the funding paragraph is built in
    # this module and names the laboratory too, so it has to be inserted first
    # for its own placeholder to be seen. Same ordering reason as apply_gender.
    text = text.replace("%%LAB_ACRONYM%%", identity["lab_acronym"])
    text = apply_gender(text, gender)
    return _clean_spaces(text)


# --- dispense form --------------------------------------------------------

def stay_days(start, end):
    """Day span between two YYYY/MM/DD dates, or None on a parse error."""
    fmt = "%Y/%m/%d"
    try:
        d0 = datetime.datetime.strptime(start, fmt)
        d1 = datetime.datetime.strptime(end, fmt)
    except (ValueError, TypeError):
        return None
    return (d1 - d0).days


def build_dispense(config, identity=None):
    identity = identity if identity is not None else letter_identity.load_identity()
    warns = []
    gender = config.get("candidate_gender", "M")
    text = tpl.TEMPLATE_DISPENSE_FR
    text = text.replace("%%SIGNATURE_NAME%%", identity["signature_name_fr"])
    text = text.replace("%%DISPENSE_LINES%%", _stacked(
        ["{\\small %s}" % line for line in identity["dispense_lines_fr"]]))
    text = text.replace("%%RESPONSIBLE_NAME%%", identity["responsible_name"])
    text = text.replace("%%DATE%%", format_date_dispense(config.get("date", "")))
    immigration = tpl.IMMIGRATION_PARAGRAPH_STANDARD
    days = stay_days(config.get("stay_start", ""), config.get("stay_end", ""))
    if days is not None and days > 120:
        warns.append("Stay duration is %d days, exceeds the 120-day work-permit "
                     "exemption; subject line still says MOINS DE 120 JOURS - verify."
                     % days)
        immigration = immigration + tpl.IMMIGRATION_EXTRA_CLAUSE
    conditional = ""
    if str(config.get("conditional_scholarship", "")).lower() == "true":
        name = config.get("conditional_scholarship_name", "") or PLACEHOLDER
        conditional = tpl.CONDITIONAL_SENTENCE.replace(
            "%%CONDITIONAL_SCHOLARSHIP_NAME%%", escape_latex(name))
    text = text.replace("%%CONDITIONAL_PARAGRAPH%%", conditional)
    text = text.replace("%%IMMIGRATION_PARAGRAPH%%", immigration)
    text = fill_scalars(text, {
        "CANDIDATE_ADDRESS": config.get("candidate_address", "") or PLACEHOLDER,
        "STAY_START": config.get("stay_start", "") or PLACEHOLDER,
        "STAY_END": config.get("stay_end", "") or PLACEHOLDER,
        "REMUNERATION": config.get("remuneration", "") or PLACEHOLDER,
        "WEEKLY_HOURS": str(config.get("weekly_hours", "") or "40"),
        "HOME_INSTITUTION": config.get("home_institution", "") or PLACEHOLDER,
        "TASKS_DESCRIPTION": config.get("tasks_description", "") or PLACEHOLDER,
    })
    name_upper = (config.get("candidate_name", "") or PLACEHOLDER).upper()
    text = text.replace("%%CANDIDATE_NAME_UPPER%%", escape_latex(name_upper))
    text = apply_gender(text, gender)
    return text, warns


# --- dispatch / warnings / output -----------------------------------------

def collect_warnings(config, body_or_none):
    warns = list(status_title_warnings(config))
    probe = body_or_none if body_or_none is not None else ""
    if PLACEHOLDER in probe or "[TO COMPLETE]" in probe:
        warns.append("placeholder %s present - manual editing needed" % PLACEHOLDER)
    if body_or_none:
        for v in style_hygiene_violations(body_or_none):
            warns.append("style hygiene: " + v)
        limit = str(config.get("limit", ""))
        if "word" in limit:
            digits = "".join(ch for ch in limit if ch.isdigit())
            n = count_words(body_or_none)
            if digits and n > int(digits):
                warns.append("body is %d words, limit is %s" % (n, limit))
    return warns


def generate(config, identity=None):
    """Return a list of {letter_type, tex, warnings, words} dicts."""
    # Resolved once here rather than in each builder: an invitation pair emits
    # two letters and both must be signed by the same person.
    identity = identity if identity is not None else letter_identity.load_identity()
    ltype = config.get("letter_type", "")
    pair = config.get("invitation_pair", "")
    results = []
    if ltype in _AUTHORED:
        tex = assemble_authored(config, identity)
        body = config.get("body_tex", "")
        results.append({"letter_type": ltype, "tex": tex,
                        "warnings": collect_warnings(config, body),
                        "words": count_words(body)})
        return results
    if pair == "both":
        make_acc, make_dis = True, True
    elif pair == "acceptance_only":
        make_acc, make_dis = True, False
    elif pair == "dispense_only":
        make_acc, make_dis = False, True
    else:
        make_acc = ltype == "acceptance"
        make_dis = ltype == "dispense"
    if make_acc:
        tex = build_acceptance(config, identity)
        results.append({"letter_type": "acceptance", "tex": tex,
                        "warnings": collect_warnings(config, None), "words": 0})
    if make_dis:
        tex, w = build_dispense(config, identity)
        results.append({"letter_type": "dispense", "tex": tex,
                        "warnings": collect_warnings(config, None) + w, "words": 0})
    return results


def write_outputs(results, config, output_dir, compile_pdf, strict):
    os.makedirs(output_dir, exist_ok=True)
    surname = surname_slug(config.get("candidate_name", "")) or "candidate"
    exit_code = 0
    for res in results:
        stem = "letter_%s_%s" % (surname, res["letter_type"])
        tex_path = os.path.join(output_dir, stem + ".tex")
        with open(tex_path, "w", encoding="utf-8") as fh:
            fh.write(res["tex"])
        print("Wrote %s (%d words)" % (tex_path, res["words"]))
        for w in res["warnings"]:
            print("WARNING: " + w, file=sys.stderr)
        hygiene = style_hygiene_violations(res["tex"])
        if hygiene and strict:
            for h in hygiene:
                print("STRICT style hygiene: " + h, file=sys.stderr)
            exit_code = 3
        if compile_pdf:
            compile_latex(tex_path, output_dir)
    return exit_code


# --- compilation ----------------------------------------------------------

def count_pdf_pages(pdf_path):
    """Approximate page count: /Type /Page minus /Type /Pages occurrences."""
    with open(pdf_path, "rb") as fh:
        content = fh.read()
    return content.count(b"/Type /Page") - content.count(b"/Type /Pages")


def compile_latex(tex_path, output_dir):
    """Compile .tex to .pdf via pdflatex (two passes). False if unavailable."""
    cmd = ["pdflatex", "-interaction=nonstopmode",
           "-output-directory", output_dir, tex_path]
    try:
        for _ in range(2):
            subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        print("INFO: pdflatex unavailable or timed out (%s); .tex only." % exc,
              file=sys.stderr)
        return False
    pdf_path = tex_path[:-4] + ".pdf" if tex_path.endswith(".tex") else tex_path + ".pdf"
    if os.path.exists(pdf_path):
        if tex_path.endswith(".tex"):
            for ext in (".aux", ".log", ".out"):
                aux = tex_path[:-4] + ext
                if os.path.exists(aux):
                    os.remove(aux)
        print("Compiled %s (%d page(s))" % (pdf_path, count_pdf_pages(pdf_path)))
        return True
    return False


def main(argv=None):
    args = parse_args(argv)
    try:
        config = load_config(args.config)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    # A profile with no signatory is a refusal by design, not a crash: exit 2
    # says the run was declined and names the key and the file (R12).
    try:
        results = generate(config)
    except letter_identity.IdentityError as exc:
        print("No letter identity: %s" % exc, file=sys.stderr)
        return 2
    return write_outputs(results, config, args.output,
                         compile_pdf=not args.no_compile, strict=args.strict)


if __name__ == "__main__":
    sys.exit(main())