"""kit_manifest.py - the kit's own declaration of what it ships.

Every build step declares the relative paths it writes, and the union of those
declarations is the manifest verify-kit-install.ps1 compares the assembled tree
against. Declared against on-disk, never tree against tree: a leaked file (a
__pycache__ artefact, say) sits in the tree and not in the declaration, so the
difference names it, while a tree compared with itself would pass for ever. The
literal file count that preceded this had rotted three times - 31, then 50,
then 52 - and each rot was a gate printing two integers that named nothing.

The manifest lives BESIDE the assembled kit, never inside it, or it would be
one more undeclared file in the tree it describes.
"""

import pathlib

SEP = chr(92)


def manifest_path(out: pathlib.Path) -> pathlib.Path:
    """
    --------------------------------------------------------------------------
    Purpose:
        Where the declaration for an assembled kit is written.

    Inputs:
        out (pathlib.Path): the assembled kit directory

    Outputs:
        path (pathlib.Path): the manifest beside it
    --------------------------------------------------------------------------
    """
    # ".declared", not ".manifest": the published archive has a
    # "<name>.zip.manifest" beside it for its RECIPIENT, and two files differing
    # by one word with different consumers get read wrongly by whoever meets
    # them next. This one is the build's own declaration and nothing ships it.
    return out.parent / (out.name + ".declared")


def declare(out: pathlib.Path, rels) -> pathlib.Path:
    """
    --------------------------------------------------------------------------
    Purpose:
        Add relative paths to the kit's declaration, keeping what is already
        there. The four build steps run in sequence and each declares its own
        writes, so this reads the existing manifest rather than replacing it -
        build_kit.py writes it fresh, the three that follow add to it.

    Inputs:
        out (pathlib.Path): the assembled kit directory
        rels (iterable of str): kit-relative paths, either separator

    Outputs:
        path (pathlib.Path): the manifest that was written
    --------------------------------------------------------------------------
    """
    return _emit(out, set(_normalise(rels)) | _read(out))


def replace(out: pathlib.Path, rels) -> pathlib.Path:
    """
    --------------------------------------------------------------------------
    Purpose:
        Write the declaration from scratch, discarding any earlier one. Used by
        the FIRST build step only, which has just deleted and recreated the kit
        directory: a manifest left over from a previous build would otherwise
        declare files this one never wrote.

    Inputs:
        out (pathlib.Path): the assembled kit directory
        rels (iterable of str): kit-relative paths, either separator

    Outputs:
        path (pathlib.Path): the manifest that was written
    --------------------------------------------------------------------------
    """
    return _emit(out, set(_normalise(rels)))


def _normalise(rels):
    return [str(r).replace("/", SEP) for r in rels]


def _read(out: pathlib.Path) -> set:
    p = manifest_path(out)
    if not p.exists():
        return set()
    return {ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()}


def _emit(out: pathlib.Path, rels: set) -> pathlib.Path:
    p = manifest_path(out)
    p.write_text(chr(10).join(sorted(rels)) + chr(10), encoding="utf-8")
    return p
