"""
letter_identity.py - who signs the letter, read from the active domain profile.

Stage: input resolution, before any template is assembled. The signatory of a
letter is true of exactly one person, so it is profile data and not repository
code (R7). This module is the only thing in the skill that knows where that data
lives; letter_templates.py holds LaTeX scaffolding with placeholders, and
generate_letter.py fills them from what is returned here.

There is deliberately NO fallback (R8). If the active profile carries no letter
identity, the run stops and names the key and the file. The alternative would be
to fall back to another profile, which means signing someone's letter with
someone else's name, credentials and laboratory - a wrong answer that looks
exactly like a right one.
"""
import re
from pathlib import Path

import yaml

# The active-profile selector lives in .claude/CLAUDE.md, which is the single
# authoritative location (profiles/README.md). Machine-readable line first, the
# French prose line as the documented second spelling.
_MACHINE_LINE = re.compile(r"^\s*active_profile:\s*(\S+)\s*$", re.MULTILINE)
_PROSE_LINE = re.compile(r"^\s*Profil actif\s*:\s*(\S+)\s*$", re.MULTILINE)

# Every key generate_letter.py reads. Checked up front so a missing one is one
# named error before anything is written, not a KeyError halfway through a .tex.
REQUIRED_KEYS = (
    "letterhead_fr",
    "letterhead_en",
    "signature_name_fr",
    "signature_name_en",
    "signature_lines_fr",
    "signature_lines_en",
    "dispense_lines_fr",
    "responsible_name",
    "lab_acronym",
)


class IdentityError(Exception):
    """Raised when the active profile carries no usable letter identity."""


def repo_root():
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve the repository root from this module's own location, which is
        configuration-free by R1.

    Inputs:
        none

    Outputs:
        root (Path): <repo>, four levels above .claude/skills/<skill>/scripts/
    --------------------------------------------------------------------------
    """
    return Path(__file__).resolve().parents[4]


def active_profile_name(root=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the active domain profile's name from .claude/CLAUDE.md.

    Inputs:
        root (Path or None): repository root; resolved from this file when None

    Outputs:
        name (str): the profile slug, e.g. "engineering"
    --------------------------------------------------------------------------
    """
    root = Path(root) if root else repo_root()
    selector = root / ".claude" / "CLAUDE.md"
    if not selector.is_file():
        raise IdentityError(
            "active-profile selector not found: %s (expected an "
            "'active_profile: <name>' line)" % selector)
    text = selector.read_text(encoding="utf-8")
    for pattern in (_MACHINE_LINE, _PROSE_LINE):
        found = pattern.search(text)
        if found:
            return found.group(1)
    raise IdentityError(
        "no 'active_profile:' line in %s; install.ps1 -Profile <name> writes it"
        % selector)


def profile_path(root=None, name=None):
    """Absolute path of the active profile's YAML file."""
    root = Path(root) if root else repo_root()
    name = name or active_profile_name(root)
    return root / "profiles" / ("%s.yaml" % name)


def load_identity(path=None, root=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Return the letter identity of the active profile (or of an explicit
        profile file, which is how the tests inject a fixture).

    Inputs:
        path (str, Path or None): a profile YAML to read instead of the active one
        root (Path or None): repository root, used only when path is None

    Outputs:
        identity (dict): the author.letter mapping, every REQUIRED_KEYS present
    --------------------------------------------------------------------------
    """
    target = Path(path) if path else profile_path(root)
    if not target.is_file():
        raise IdentityError("profile not found: %s" % target)

    # safe_load, never load: a profile is a data file and must not be able to
    # construct Python objects (security.md, "General input handling").
    with open(target, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise IdentityError("profile is not a YAML mapping: %s" % target)

    author = data.get("author")
    if not isinstance(author, dict):
        raise IdentityError("no 'author:' block in %s" % target)

    identity = author.get("letter")
    if not isinstance(identity, dict):
        raise IdentityError(
            "no 'author.letter:' block in %s. That block carries who signs the "
            "letter (letterhead, signature name, credentials, laboratory). "
            "Add it to this profile; it is not inherited from another one, "
            "because signing a letter with another profile's identity is a "
            "wrong answer that reads as a right one." % target)

    missing = [key for key in REQUIRED_KEYS if not identity.get(key)]
    if missing:
        raise IdentityError(
            "author.letter is missing %s in %s"
            % (", ".join(missing), target))

    return identity
