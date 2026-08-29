#!/usr/bin/env python3
"""
daemon_taxonomy.py - where a note may go, and what each shelf is for.

Split out of daemon_states.py when that file passed the 4096-token ceiling, and
along a real seam rather than an arbitrary one: everything here answers "which
folders exist and what belongs in them", while daemon_states next door answers
"what happens to this event". Nothing in this module calls a model.

The folder ENUM is built from the vault at run time, so a technology folder
created tomorrow needs no code change. The one-line description of each folder
is DATA, in technology-folders.json beside daemon-config.json (R6), because a
per-folder gloss is a taxonomy that will be edited far more often than the code
that reads it.

Both halves are needed and they fail differently. Without the enum the model
could name any string. Without the glosses it sees bare names, and a bare name
invites surface association: measured 2026-08-28 on the first live drill, three
notes went into Docker, a two-note folder, one of them about an outbox lock.
"""
import json
from pathlib import Path

RESOURCES = "30_Ressources"
PROJECTS = "10_Projets"
PROJECT_NATURES = ("Articles", "Subventions", "Livres", "Logiciels")

# Retired catch-all: still on disk, never offered as a destination.
EXCLUDED_FOLDERS = {"Logiciel"}

FOLDER_GLOSSES = Path(__file__).resolve().parents[1] / "technology-folders.json"


def technology_folders(vault) -> list:
    """The enum the classification is constrained to, built at run time from the
    folders that actually exist. Sorted for a deterministic prompt."""
    root = Path(vault) / RESOURCES
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir()
                  if p.is_dir() and p.name not in EXCLUDED_FOLDERS)


def folder_glosses(path=None) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Load the one-line description of each technology folder, so the model
        is told what a shelf is FOR rather than only what it is called.

        An absent or unreadable file returns {}, which offers every folder by
        name exactly as before. That is a degradation of a hint, not of a
        result - R8 forbids substituting a weaker RESOURCE, and the enum the
        answer is constrained to comes from the vault either way.

    Inputs:
        path (Path | None): the data file, defaulting to the skill's own

    Outputs:
        glosses (dict): folder name -> one-line description
    --------------------------------------------------------------------------
    """
    try:
        loaded = json.loads(Path(path or FOLDER_GLOSSES).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    glosses = loaded.get("folders")
    return glosses if isinstance(glosses, dict) else {}


def folder_menu(folders: list, glosses: dict) -> str:
    """One line per folder, with its gloss when there is one. The caller sorts
    the folders, so the prompt stays deterministic."""
    lines = []
    for name in folders:
        gloss = glosses.get(name)
        lines.append(f"- {name}: {gloss}" if gloss else f"- {name}")
    return "\n".join(lines)
