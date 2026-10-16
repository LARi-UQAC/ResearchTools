"""
wp_paths.py - the researcher data folder and path containment (R1, R24).

Stage: imported by every CLI module. All researcher data (XML, cihr.json,
config/) lives under an explicit --data-dir given outside the repository;
this module is the single place that resolves and contains those paths.
"""
from pathlib import Path

from wp_errors import WpRefusal


def repo_root():
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve the ResearchTools repository root from this file's own
        location (R1: no hardcoded path). Same arithmetic as narrative-cv's
        cv_common.repo_root: scripts(0) / wp-portfolio-sync(1) / skills(2) /
        .claude(3) / repository(4).

    Inputs:
        none

    Outputs:
        root (Path): the repository root. Inside a worktree this resolves to
            the worktree root, which is correct.
    --------------------------------------------------------------------------
    """
    return Path(__file__).resolve().parents[4]


def resolve_data_dir(raw, repo=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Validate and resolve the researcher's --data-dir argument.

    Inputs:
        raw (str or None): the raw --data-dir value as given on the CLI.
        repo (Path or None): the repository root to refuse containment
            against; defaults to repo_root().

    Outputs:
        data_dir (Path): the resolved absolute path.

    Raises:
        WpRefusal: raw is None or blank; the path does not exist; the path
            is not a directory; or the path resolves inside repo (the
            repository is public - spec D7).
    --------------------------------------------------------------------------
    """
    if raw is None or not raw.strip():
        raise WpRefusal("--data-dir is required")
    candidate = Path(raw)
    if not candidate.exists():
        raise WpRefusal("--data-dir does not exist: %s" % candidate)
    if not candidate.is_dir():
        raise WpRefusal("--data-dir is not a directory: %s" % candidate)
    resolved = candidate.resolve()
    repo_resolved = (repo if repo is not None else repo_root()).resolve()
    if resolved == repo_resolved or resolved.is_relative_to(repo_resolved):
        raise WpRefusal(
            "--data-dir must lie outside the repository (the repository is public): %s" % resolved
        )
    return resolved


def contained_path(data_dir, candidate):
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve a candidate path relative to data_dir and refuse it if it
        escapes data_dir (R24: resolve first, then compare, never a string
        comparison).

    Inputs:
        data_dir (Path): the resolved researcher data folder.
        candidate (str or Path): a relative or absolute path argument.

    Outputs:
        resolved (Path): the resolved path, guaranteed to be data_dir itself
            or to lie under it.

    Raises:
        WpRefusal: the resolved path is not data_dir and does not lie under
            it, naming both paths.
    --------------------------------------------------------------------------
    """
    data_dir = Path(data_dir).resolve()
    joined = Path(data_dir) / Path(candidate)
    resolved = joined.resolve()
    if resolved != data_dir and not resolved.is_relative_to(data_dir):
        raise WpRefusal(
            "path escapes the data folder: %s is not inside %s" % (resolved, data_dir)
        )
    return resolved
