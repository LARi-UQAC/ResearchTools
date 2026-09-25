"""
cv_common.py - shared constants and small helpers for the narrative-cv skill.

Stage: used by every other module in this skill (cv_inventory, cv_select,
cv_build). Holds nothing that reaches the network and nothing that writes a
file, so it can be imported freely by offline tests.
"""
import json
import re
import unicodedata
from pathlib import Path

# The active-profile selector lives in .claude/CLAUDE.md (profiles/README.md).
# Same two-pattern resolution as recommendation-letter's letter_identity.py;
# not shared as a cross-skill import because each skill's identity need is a
# different sub-block of the profile (R18: a script lives beside its caller).
_MACHINE_LINE = re.compile(r"^\s*active_profile:\s*(\S+)\s*$", re.MULTILINE)
_PROSE_LINE = re.compile(r"^\s*Profil actif\s*:\s*(\S+)\s*$", re.MULTILINE)

REQUIRED_AUTHOR_KEYS = ("name", "email", "institution", "department")

# normes_presentation.pdf (FRQ, 2025-09-23): "Le nom du document ne doit
# contenir aucun espace ni aucun des caractères suivants" - this is the
# closed set, not a generic "keep alphanumeric" guess (R14).
_FILENAME_FORBIDDEN = set("()~!@%^&*={}[];:'\",/<>?\\|")
_FILENAME_MAX_CHARS = 50


class CvDataError(Exception):
    """Raised when configuration, a profile, or the inventory is malformed."""


def repo_root():
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve the ResearchTools repository root from this file's own
        location (R1: no hardcoded path).

    Inputs:
        none

    Outputs:
        root (Path): <repo>, four levels above .claude/skills/<skill>/scripts/
    --------------------------------------------------------------------------
    """
    return Path(__file__).resolve().parents[4]


def load_contribution_types(path=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Load the closed set of section titles, clientele tags, category ids,
        page budgets, and portal/font variants (R6: data, not code).

    Inputs:
        path (str, Path or None): explicit contribution_types.json path, used
            by tests to inject a fixture; defaults to the file beside this
            module.

    Outputs:
        data (dict): the parsed JSON document.

    Raises:
        CvDataError: the file is absent or is not valid JSON.
    --------------------------------------------------------------------------
    """
    target = Path(path) if path else Path(__file__).resolve().parent / "contribution_types.json"
    if not target.is_file():
        raise CvDataError("contribution_types.json not found: %s" % target)
    try:
        with open(target, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise CvDataError("contribution_types.json is not valid JSON: %s (%s)" % (target, exc))


def active_profile_name(root=None):
    """Read the active domain profile's name from .claude/CLAUDE.md."""
    root = Path(root) if root else repo_root()
    selector = root / ".claude" / "CLAUDE.md"
    if not selector.is_file():
        raise CvDataError(
            "active-profile selector not found: %s (expected an "
            "'active_profile: <name>' line)" % selector)
    text = selector.read_text(encoding="utf-8")
    for pattern in (_MACHINE_LINE, _PROSE_LINE):
        found = pattern.search(text)
        if found:
            return found.group(1)
    raise CvDataError(
        "no 'active_profile:' line in %s; install.ps1 -Profile <name> writes it"
        % selector)


def load_author_identity(path=None, root=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Return the plain `author` block (name/email/institution/department)
        of the active profile, used for the CV header and the filename's
        surname. Deliberately no fallback (R8): a profile with no usable
        identity stops the run rather than borrowing another profile's name.

    Inputs:
        path (str, Path or None): explicit profile YAML, for test fixtures
        root (Path or None): repository root, used only when path is None

    Outputs:
        author (dict): mapping with at least REQUIRED_AUTHOR_KEYS present

    Raises:
        CvDataError: profile missing, not a mapping, or missing a required key
    --------------------------------------------------------------------------
    """
    import yaml  # deferred: keeps this module importable without PyYAML installed

    target = Path(path) if path else (repo_root() if root is None else Path(root)) / "profiles" / (
        "%s.yaml" % active_profile_name(root))
    if not target.is_file():
        raise CvDataError("profile not found: %s" % target)

    with open(target, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise CvDataError("profile is not a YAML mapping: %s" % target)

    author = data.get("author")
    if not isinstance(author, dict):
        raise CvDataError("no 'author:' block in %s" % target)

    missing = [key for key in REQUIRED_AUTHOR_KEYS if not author.get(key)]
    if missing:
        raise CvDataError("author block is missing %s in %s" % (", ".join(missing), target))

    return author


def load_cv_project_dir(path=None, root=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Return the external project directory where this profile's CV
        inventory and drafts live (never inside ResearchTools - R7). The path
        is profile data, the same tier as `author.letter` (R1: no hardcoded
        path in repository code), with the same no-fallback refusal.

    Inputs:
        path (str, Path or None): explicit profile YAML, for test fixtures
        root (Path or None): repository root, used only when path is None

    Outputs:
        project_dir (Path): the configured directory (existence not checked
            here - callers create it on first write)

    Raises:
        CvDataError: profile missing, not a mapping, or no 'cv.project_dir' key
    --------------------------------------------------------------------------
    """
    import yaml  # deferred, see load_author_identity()

    target = Path(path) if path else (repo_root() if root is None else Path(root)) / "profiles" / (
        "%s.yaml" % active_profile_name(root))
    if not target.is_file():
        raise CvDataError("profile not found: %s" % target)

    with open(target, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise CvDataError("profile is not a YAML mapping: %s" % target)

    cv_block = data.get("cv")
    if not isinstance(cv_block, dict) or not cv_block.get("project_dir"):
        raise CvDataError(
            "no 'cv.project_dir' in %s. That key names the external folder "
            "this profile's CV inventory and drafts live in; it is not "
            "inherited from another profile, and it is never guessed." % target)

    return Path(cv_block["project_dir"])


def strip_accents(text):
    """Return `text` with combining diacritics removed (NFKD decomposition)."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def build_frq_filename(surname, frq_id, doc_title):
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the mandatory old-FRQnet-portal attachment filename:
        NOM_XXXXX1234_Titre.pdf, per normes_presentation.pdf.

    Details:
        The FRQ id is validated as 5 letters + 4 digits (its own documented
        shape, e.g. XXXYY1234) rather than accepted as an opaque string, so a
        pasted-in typo is caught here instead of surfacing as a portal
        rejection. Accents are stripped, forbidden characters and spaces are
        removed, and the result is truncated to the 50-character cap - but a
        truncation that would cut the filename to fewer than 5 characters of
        title is refused rather than silently producing a useless name.

    Inputs:
        surname (str): family name, without accent required (accents are
            stripped either way)
        frq_id (str): the 5-letter/4-digit FRQ identification number
        doc_title (str): a short document title/keyword, e.g. "CVdescriptif"

    Outputs:
        filename (str): "<NOM>_<XXXXX1234>_<Titre>.pdf", at most 50 characters

    Raises:
        CvDataError: frq_id does not match the 5-letter/4-digit shape, or the
            50-character cap leaves no room for a usable title
    --------------------------------------------------------------------------
    """
    if not re.fullmatch(r"[A-Za-z]{5}\d{4}", frq_id):
        raise CvDataError(
            "frq_id %r does not match the FRQ shape (5 letters + 4 digits, e.g. XXXYY1234)"
            % frq_id)

    def clean(fragment):
        fragment = strip_accents(fragment)
        fragment = "".join(ch for ch in fragment if ch not in _FILENAME_FORBIDDEN)
        fragment = fragment.replace(" ", "")
        return fragment

    nom = clean(surname).upper()
    titre = clean(doc_title)
    base = "%s_%s_%s" % (nom, frq_id, titre)
    filename = base + ".pdf"

    if len(filename) > _FILENAME_MAX_CHARS:
        overflow = len(filename) - _FILENAME_MAX_CHARS
        if len(titre) - overflow < 5:
            raise CvDataError(
                "filename %r exceeds the %d-character cap and truncating the title "
                "would leave fewer than 5 usable characters; shorten doc_title"
                % (filename, _FILENAME_MAX_CHARS))
        titre = titre[: len(titre) - overflow]
        filename = "%s_%s_%s.pdf" % (nom, frq_id, titre)

    return filename
