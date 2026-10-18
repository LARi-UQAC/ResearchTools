"""
mkdocs_hooks.py - MkDocs build hook: links that leave docs/ are sent to GitHub.

MkDocs only knows the files inside docs_dir, so an inline link from a page to `../README.md` or to
a skill script is dead on the published site. This hook rewrites such a link, at build time and
only in the built page, to an absolute GitHub URL. The Markdown source keeps its relative links,
so GitHub, the editor preview and the tests that check that links resolve on disk are unchanged.

Rules, each proven in .claude/hooks/Test/test_mkdocs_links.py:

  * Only inline links `[text](target)` outside fenced and inline code are considered. A URL with a
    scheme, a bare `#anchor`, an absolute path and an image are left alone. A link may hold an
    image or inline code in its text. A fence may sit in a list item or a blockquote.
  * Stated limits: an indented code block (four spaces, no fence) is not detected, a title in single
    quotes or parentheses, a `)` inside a target, a reference-style definition and an HTML `href`
    are not rewritten, so such a link stays as MkDocs finds it and `--strict` reports it.
  * The target is resolved first, then must sit inside the repository root (R24). A target that
    does not exist is left alone so MkDocs still warns about a genuinely broken link.
  * A file MkDocs serves is left alone. A file that exists but is not served (outside docs_dir, or
    excluded) becomes `<repo_url>/blob/<ref>/<path>`, a directory becomes `/tree/`.
  * `ref` comes from `extra.docs_source_ref` of mkdocs.yml and `repo_url` from MkDocs itself, so no
    URL or branch is written here (R0). A missing value is a named HookConfigError (R3).

Wired through `hooks:` in mkdocs.yml. Standard library only.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable
from urllib.parse import quote, unquote

_FENCE = re.compile(r"^[ \t>]*(`{3,}|~{3,})")
_CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")
# The link text may hold an inline image, tried before a plain character so that the `!` of
# `![alt](src)` is never read as the start of the link.
_LINK = re.compile(
    r"(?<!!)\[(?P<text>(?:!\[[^\]\n]*\]\([^)\n]*\)|(?!!\[)[^\]\n])*)\]"
    r"\((?P<target>(?:<[^>\n]+>)|[^)\s]+)(?P<title>\s+\"[^\"\n]*\")?\)"
)
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_PATH_AND_SUFFIX = re.compile(r"^([^?#]*)(.*)$")


class HookConfigError(ValueError):
    """A MkDocs configuration value this hook needs is missing, with the key named."""


def _rewrite_target(
    raw: str,
    *,
    page_dir: Path,
    docs_dir: Path,
    root: Path,
    base_url: str,
    ref: str,
    is_served: Callable[[Path], bool],
) -> str | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Decide the replacement URL for one link target, or None to leave it alone.

    Inputs:
        raw (str): the target as written, without angle brackets.
        page_dir (Path): folder of the page holding the link.
        docs_dir (Path): the resolved docs_dir.
        root (Path): the resolved repository root.
        base_url (str): the repository URL without a trailing slash.
        ref (str): the branch or tag the links point at.
        is_served (Callable[[Path], bool]): True for a resolved path inside docs_dir that
            MkDocs serves.

    Outputs:
        url (str | None): the GitHub URL, fragment and query kept, or None.
    --------------------------------------------------------------------------
    """
    if not raw or raw.startswith(("#", "/")) or _SCHEME.match(raw):
        return None
    path_part, suffix = _PATH_AND_SUFFIX.match(raw).groups()
    rel = unquote(path_part)
    if not rel:
        return None
    resolved = (page_dir / rel).resolve()
    if not resolved.exists() or not resolved.is_relative_to(root):
        return None
    if resolved.is_relative_to(docs_dir) and is_served(resolved):
        return None
    kind = "tree" if resolved.is_dir() else "blob"
    repo_path = quote(resolved.relative_to(root).as_posix(), safe="/")
    if repo_path == ".":
        repo_path = ""
    url = f"{base_url}/{kind}/{ref}" + (f"/{repo_path}" if repo_path else "")
    return url + suffix


def _rewrite_line(line: str, found: list[str], **context) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Rewrite the link targets of one line outside fenced code.

    Details:
        Inline code spans are masked with NUL characters of the same length before the links are
        searched, so a link inside a span is never found while a link whose text holds code, such
        as [`SKILL.md`](../x.md), still is. Only the target is replaced, in the original line.

    Inputs:
        line (str): one line of the page, line ending included.
        found (list[str]): collects each rewritten raw target (side effect).
        **context: the keyword arguments of _rewrite_target.

    Outputs:
        line (str): the line with its eligible link targets rewritten.
    --------------------------------------------------------------------------
    """
    masked = _CODE_SPAN.sub(lambda span: "\x00" * len(span.group(0)), line)
    pieces, cursor = [], 0
    for match in _LINK.finditer(masked):
        start, end = match.span("target")
        target = line[start:end]
        raw = target[1:-1] if target.startswith("<") else target
        url = _rewrite_target(raw, **context)
        if url is None:
            continue
        found.append(raw)
        pieces.append(line[cursor:start])
        pieces.append(url)
        cursor = end
    pieces.append(line[cursor:])
    return "".join(pieces)


def rewrite_links(
    markdown: str,
    *,
    page_dir: Path,
    docs_dir: Path,
    repo_root: Path,
    base_url: str,
    ref: str,
    is_served: Callable[[Path], bool],
) -> tuple[str, list[str]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Send every inline link that leaves the served site to GitHub, leaving code regions,
        images, URLs, anchors, served files, missing files and paths outside the repository alone.

    Details:
        Pure: no file is written. Lines keep their own line endings. Rewriting twice changes
        nothing, since a rewritten target has a scheme.

    Inputs:
        markdown (str): the page source.
        page_dir (Path): folder of the page, the base of its relative links.
        docs_dir (Path): MkDocs's docs_dir.
        repo_root (Path): the repository root, the containment boundary (R24).
        base_url (str): the repository URL, for example MkDocs's repo_url.
        ref (str): branch or tag of the GitHub links.
        is_served (Callable[[Path], bool]): True for a resolved path inside docs_dir that
            MkDocs serves.

    Outputs:
        result (tuple[str, list[str]]): the new text and the raw targets that were rewritten.
    --------------------------------------------------------------------------
    """
    context = {
        "page_dir": page_dir,
        "docs_dir": docs_dir.resolve(),
        "root": repo_root.resolve(),
        "base_url": base_url.rstrip("/"),
        "ref": ref,
        "is_served": is_served,
    }
    found: list[str] = []
    out: list[str] = []
    fence: str | None = None
    for line in markdown.splitlines(keepends=True):
        opening = _FENCE.match(line.rstrip("\r\n"))
        if fence is not None:
            out.append(line)
            if (
                opening
                and opening.group(1)[0] == fence[0]
                and len(opening.group(1)) >= len(fence)
                and not line[opening.end():].strip()
            ):
                fence = None
            continue
        if opening:
            fence = opening.group(1)
            out.append(line)
            continue
        out.append(_rewrite_line(line, found, **context))
    return "".join(out), found


def _settings(config) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read and validate what the hook needs from the MkDocs configuration.

    Inputs:
        config: the MkDocs config object (item access, `get`, and `config_file_path`).

    Outputs:
        settings (dict): repo_root (Path), docs_dir (Path), base_url (str), ref (str).

    Raises:
        HookConfigError: repo_url, extra.docs_source_ref, docs_dir or the config file path is
        missing; the message names the key and mkdocs.yml.
    --------------------------------------------------------------------------
    """
    repo_url = config.get("repo_url")
    if not repo_url:
        raise HookConfigError("mkdocs.yml: 'repo_url' is missing, the hook cannot build GitHub links")
    extra = config.get("extra") or {}
    ref = extra.get("docs_source_ref")
    if not ref:
        raise HookConfigError(
            "mkdocs.yml: 'extra.docs_source_ref' is missing, the hook needs the branch the links point at"
        )
    docs_dir = config.get("docs_dir")
    config_file = getattr(config, "config_file_path", None)
    if not docs_dir or not config_file:
        raise HookConfigError("mkdocs.yml: 'docs_dir' or the config file path is missing")
    return {
        "repo_root": Path(config_file).resolve().parent,
        "docs_dir": Path(docs_dir).resolve(),
        "base_url": str(repo_url).rstrip("/"),
        "ref": str(ref),
    }


def on_config(config):
    """
    --------------------------------------------------------------------------
    Purpose:
        MkDocs event: fail the build early, with a named error, when the hook is mis-configured.

    Inputs:
        config: the MkDocs config object.

    Outputs:
        config: the same object, unchanged.

    Raises:
        HookConfigError: see _settings.
    --------------------------------------------------------------------------
    """
    _settings(config)
    return config


def on_page_markdown(markdown, page, config, files):
    """
    --------------------------------------------------------------------------
    Purpose:
        MkDocs event: rewrite the links of one page that leave the served site.

    Inputs:
        markdown (str): the page source.
        page: the MkDocs page, read for `file.abs_src_path`.
        config: the MkDocs config object.
        files: the MkDocs Files, asked through `get_file_from_path` which docs files are served.

    Outputs:
        markdown (str): the page source with eligible links pointing at GitHub.

    Raises:
        HookConfigError: see _settings.
    --------------------------------------------------------------------------
    """
    settings = _settings(config)
    docs_dir = settings["docs_dir"]

    def is_served(path: Path) -> bool:
        return files.get_file_from_path(path.relative_to(docs_dir).as_posix()) is not None

    text, _ = rewrite_links(
        markdown,
        page_dir=Path(page.file.abs_src_path).resolve().parent,
        docs_dir=docs_dir,
        repo_root=settings["repo_root"],
        base_url=settings["base_url"],
        ref=settings["ref"],
        is_served=is_served,
    )
    return text
