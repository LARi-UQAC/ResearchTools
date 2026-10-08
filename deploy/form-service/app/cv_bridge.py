"""
cv_bridge.py - The only module that imports the narrative-cv skill scripts.

Mirrors skill_bridge.py: the import surface lives in one file, so the route
is pure transport and the tests have exactly one seam to patch. Nothing here
compiles LaTeX (C2) or writes to disk (C3): the request body is rendered in
memory and returned, never persisted.
"""

import logging
import os
import sys
from typing import Any

logger = logging.getLogger(__name__)

# The narrative-cv skill scripts are plain modules in the repo, mounted into
# the image at /opt/narrative-cv/scripts. NARRATIVE_CV_SCRIPTS_DIR overrides
# the location for a local run straight from a checkout (same computation as
# skill_bridge.py's SKILL_SCRIPTS_DIR).
_DEFAULT_SCRIPTS = os.environ.get(
    "NARRATIVE_CV_SCRIPTS_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))),
        ".claude", "skills", "narrative-cv", "scripts"))
if _DEFAULT_SCRIPTS not in sys.path:
    sys.path.insert(0, _DEFAULT_SCRIPTS)

import cv_build  # noqa: E402
from cv_common import CvDataError  # noqa: E402

_TARGETS = ("latex", "text", "both")


def build_cv(model: dict, rows: list, reference_year: int, target: str = "both") -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Render a CV model plus consenting HQP rows into LaTeX and/or plain
        text. Stateless: nothing is written to disk and nothing is kept
        after the call returns (spec section 1, C2, C3).

    Inputs:
        model (dict): a cv_model.json document with inline prose only (no
            prose_file - C4, checked here before any rendering)
        rows (list): student rows per the closed HQP schema (C5); an empty
            list renders with no HQP block at all (C9)
        reference_year (int): the year the consent window ends
        target (str): "latex", "text" or "both"

    Outputs:
        result (dict): {"latex": str | None, "text": str | None,
            "hqp": {"recent": int, "archive": int}}

    Raises:
        CvDataError: target is not one of "latex"/"text"/"both", the model
            is not inline (assert_inline_model), or a row fails
            validate_hqp_rows (unknown key, bad date, missing consent - now
            mandatory for every row regardless of the window, C6 revised -
            ...)
    --------------------------------------------------------------------------
    """
    if target not in _TARGETS:
        raise CvDataError("target must be one of %s, got %r" % (_TARGETS, target))
    cv_build.assert_inline_model(model)

    hqp = {"rows": rows, "reference_year": reference_year} if rows else None

    result: dict[str, Any] = {"latex": None, "text": None}
    if target in ("latex", "both"):
        result["latex"] = cv_build.render_latex(model, hqp=hqp)
    if target in ("text", "both"):
        result["text"] = cv_build.render_text(model, hqp=hqp)

    if rows:
        types = cv_build.load_contribution_types()
        rules = cv_build.load_hqp_rules(types, model["portal_variant"])
        min_ref, max_ref = cv_build.reference_year_bounds(types)
        validated = cv_build.validate_hqp_rows(
            rows, reference_year, rules["window_years"], min_ref, max_ref)
        recent = sum(1 for row in validated if row["in_window"])
        archive = len(validated) - recent
    else:
        recent = archive = 0
    result["hqp"] = {"recent": recent, "archive": archive}
    return result
