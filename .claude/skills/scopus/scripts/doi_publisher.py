"""
doi_publisher.py - Derive the publisher of a reference from its DOI prefix.

The DOI prefix is assigned by the registration agency and does not negotiate.
Scopus `prism:publisher` does: MEASURED on a 25-reference chapter (2026-08-04),
the IJASS carries a Korean learned society while 10.1007 says Springer, Deskos
carries "Academic Press" which is an Elsevier imprint, and two entries have the
field empty. Every caller that needs to know who published a paper must read
the prefix, and keep the Scopus field only as informative context.

The table is ported from `VibeDesignBook/docs/tools/audit_editeurs.py` (21
prefixes, 14 test cases) rather than rewritten. One entry differs on purpose and
must NOT be "aligned" back: 10.1186 (BioMed Central) is out of list on the book
side and IN the approved list of ResearchTools, per the References section of
`.claude/CLAUDE.md`. The divergence is deliberate; changing it needs the
author's agreement.

This module derives an identity, never a verdict. Publisher approval stays with
the caller (`bib_audit.py`, the `bib-cleaner` agent), which owns the approved
list and the reporting rules.
"""

from __future__ import annotations

import re

# Prefix -> publisher. The first eleven are the approved list of the References
# section of `.claude/CLAUDE.md`; the rest are out of that list and NAMED on
# purpose, because a named publisher can be discussed while an unknown prefix
# stays silent.
DOI_PREFIX_PUBLISHERS: dict[str, str] = {
    "10.1109": "IEEE",
    "10.1007": "Springer",
    "10.1016": "Elsevier",
    "10.3390": "MDPI",
    "10.1088": "IOP",
    "10.1080": "Taylor & Francis",
    "10.1002": "Wiley",
    "10.1111": "Wiley",
    "10.1049": "IET",
    "10.1145": "ACM",
    "10.1017": "Cambridge",
    "10.1115": "ASME",
    "10.1186": "BioMed Central",
    "10.2514": "AIAA",
    "10.1177": "SAGE",
    "10.48550": "arXiv (preprint)",
    "10.7717": "PeerJ",
    "10.1137": "SIAM",
    "10.21105": "Open Journals (JOSS)",
    "10.1073": "PNAS",
    "10.1093": "Oxford University Press",
    "10.1680": "ICE Publishing",
}

_DOI_PREFIX = re.compile(r"\b(10\.\d{4,9})(?:/|$)")


def doi_prefix(doi: str | None) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Extract the registrant prefix of a DOI, tolerating the forms a
        bibliography actually carries: bare, `doi:`-tagged, or a full
        https://doi.org/ URL.

    Inputs:
        doi (str | None): the DOI in any of those forms, or an empty value.

    Outputs:
        prefix (str): e.g. "10.1109", or "" when no prefix can be read. An
            empty result is a measurement, not an error: a technical
            documentation reference legitimately has no DOI.
    --------------------------------------------------------------------------
    """
    if not doi:
        return ""
    found = _DOI_PREFIX.search(doi.strip())
    return found.group(1) if found else ""


def publisher_by_prefix(doi: str | None) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Name the publisher a DOI prefix designates. Complements, and where they
        disagree overrides, the `prism:publisher` field of Scopus.

    Inputs:
        doi (str | None): DOI in any accepted form, or an empty value.

    Outputs:
        publisher (str): the publisher name, or "" when the prefix is unknown
            or absent. "" means "not stated", never "not approved": an unknown
            prefix is reported as unknown so the caller can ask the author.
    --------------------------------------------------------------------------
    """
    return DOI_PREFIX_PUBLISHERS.get(doi_prefix(doi), "")


def annotate(record: dict) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Add the two derived fields to a record that already holds a `doi` key,
        in place, so the search / validate / cite modes all publish the same
        shape.

    Inputs:
        record (dict): a Scopus record carrying a `doi` key (possibly empty).

    Outputs:
        record (dict): the same object, with `doi_prefix` and
            `publisher_by_prefix` set (both possibly empty strings).
    --------------------------------------------------------------------------
    """
    doi = record.get("doi", "")
    record["doi_prefix"] = doi_prefix(doi)
    record["publisher_by_prefix"] = publisher_by_prefix(doi)
    return record
