"""
Offline suite for scripts/docs/mkdocs_hooks.py (the MkDocs build hook that sends links leaving
docs/ to GitHub) and for the MkDocs wiring that uses it. Standard library only.

Measured 2026-10-17 on main 0989909: `mkdocs build` printed 73 warnings, one per inline link from
a page under docs/ to a file outside docs_dir, so those links were dead (404) on the published
site. Every fixture here is fictitious (R34) and built in a temporary directory (R21).

Proves: the rewrite rules, the refusals (a target outside the repository, a missing target, code
regions, images), idempotence, the named configuration errors, and the hook's wiring through the
MkDocs event signature. Does not prove: the live site, which only `mkdocs gh-deploy` publishes.
"""

import fnmatch
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote

# Timeouts in seconds. Chosen 2026-10-17: the full strict build was measured at 1.4 s and a git
# listing of this repository at well under a second, so these are generous ceilings, not tuned.
BUILD_TIMEOUT_S = 300
GIT_TIMEOUT_S = 60

REPO = Path(__file__).resolve().parents[3]
HOOK_PATH = REPO / "scripts" / "docs" / "mkdocs_hooks.py"
BASE = "https://example.org/acme/tools"
REF = "main"


def load_hooks():
    """
    --------------------------------------------------------------------------
    Purpose:
        Import the hook module by file path, since scripts/docs is not a package.

    Inputs:
        None

    Outputs:
        module: the loaded mkdocs_hooks module.

    Raises:
        FileNotFoundError: the hook file does not exist (the red state of this suite).
    --------------------------------------------------------------------------
    """
    spec = importlib.util.spec_from_file_location("mkdocs_hooks", HOOK_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeConfig(dict):
    """A MkDocs config stand-in: item access plus the config_file_path attribute."""


class FakeFile:
    """A MkDocs File stand-in carrying only the absolute source path."""

    def __init__(self, abs_src_path: Path):
        self.abs_src_path = str(abs_src_path)


class FakePage:
    """A MkDocs Page stand-in."""

    def __init__(self, abs_src_path: Path):
        self.file = FakeFile(abs_src_path)


class FakeFiles:
    """A MkDocs Files stand-in answering get_file_from_path for a set of served paths."""

    def __init__(self, served: set):
        self.served = served

    def get_file_from_path(self, path: str):
        return object() if path in self.served else None


class Fixture(unittest.TestCase):
    """A temporary repository: README, rules, a folder with a space, docs, a hidden page."""

    def setUp(self):
        self.hooks = load_hooks()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.root = self.tmp / "repo"
        self.docs = self.root / "docs"
        files = {
            "README.md": "readme",
            ".claude/rules/a.md": "rule",
            ".claude/dir with space/f.md": "spaced",
            "docs/page.md": "page",
            "docs/sub/b.md": "b",
            "docs/hidden/x.md": "hidden",
            "img.png": "png",
        }
        for rel, body in files.items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "secret.md").write_text("secret", encoding="utf-8")

    def served(self, path: Path) -> bool:
        """The fixture's served set: docs/ except the hidden folder."""
        rel = path.resolve().relative_to(self.docs.resolve())
        return rel.parts[0] != "hidden"

    def run_rewrite(self, text: str, page: str = "page.md"):
        """Run rewrite_links for a page of the fixture docs."""
        return self.hooks.rewrite_links(
            text,
            page_dir=(self.docs / page).parent,
            docs_dir=self.docs,
            repo_root=self.root,
            base_url=BASE,
            ref=REF,
            is_served=self.served,
        )


class RewriteRules(Fixture):
    def test_out_of_docs_file_becomes_blob_url(self):
        out, done = self.run_rewrite("See [R](../README.md) now.")
        self.assertEqual(out, f"See [R]({BASE}/blob/{REF}/README.md) now.")
        self.assertEqual(done, ["../README.md"])

    def test_directory_becomes_tree_url(self):
        out, _ = self.run_rewrite("[d](../.claude/rules/)")
        self.assertEqual(out, f"[d]({BASE}/tree/{REF}/.claude/rules)")

    def test_fragment_and_title_kept(self):
        out, _ = self.run_rewrite('[R](../README.md#install "The readme")')
        self.assertEqual(out, f'[R]({BASE}/blob/{REF}/README.md#install "The readme")')

    def test_space_is_percent_encoded(self):
        expected = f"[f]({BASE}/blob/{REF}/.claude/dir%20with%20space/f.md)"
        angle, _ = self.run_rewrite("[f](<../.claude/dir with space/f.md>)")
        encoded, _ = self.run_rewrite("[f](../.claude/dir%20with%20space/f.md)")
        self.assertEqual(angle, expected)
        self.assertEqual(encoded, expected)

    def test_served_docs_page_untouched(self):
        text = "[b](sub/b.md#x) and [p](page.md)"
        out, done = self.run_rewrite(text)
        self.assertEqual(out, text)
        self.assertEqual(done, [])

    def test_excluded_docs_file_rewritten(self):
        out, _ = self.run_rewrite("[x](hidden/x.md)")
        self.assertEqual(out, f"[x]({BASE}/blob/{REF}/docs/hidden/x.md)")

    def test_missing_target_untouched(self):
        text = "[m](../nope.md)"
        out, done = self.run_rewrite(text)
        self.assertEqual(out, text)
        self.assertEqual(done, [])

    def test_target_outside_root_untouched(self):
        text = "[s](../../outside/secret.md)"
        out, done = self.run_rewrite(text)
        self.assertEqual(out, text)
        self.assertEqual(done, [])

    @unittest.skipUnless(os.name == "nt", "a directory junction is a Windows construct")
    def test_junction_escaping_the_root_untouched(self):
        link = self.docs / "link"
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(self.tmp / "outside")],
            check=True, capture_output=True, timeout=30,
        )
        # rmdir removes the junction only, never its target (R37).
        self.addCleanup(os.rmdir, link)
        text = "[j](link/secret.md)"
        out, done = self.run_rewrite(text)
        self.assertEqual(out, text)
        self.assertEqual(done, [])

    def test_url_anchor_image_absolute_untouched(self):
        text = (
            "[w](https://x.org/a) [a](#top) ![i](../README.md) "
            "[m](mailto:a@b.example) [abs](/README.md)"
        )
        out, done = self.run_rewrite(text)
        self.assertEqual(out, text)
        self.assertEqual(done, [])

    def test_fenced_and_inline_code_untouched(self):
        text = (
            "Intro [R](../README.md)\n\n"
            "```md\n[R](../README.md)\n```\n\n"
            "and `[R](../README.md)` inline.\n"
        )
        out, done = self.run_rewrite(text)
        self.assertEqual(done, ["../README.md"])
        self.assertIn(f"Intro [R]({BASE}/blob/{REF}/README.md)", out)
        self.assertIn("```md\n[R](../README.md)\n```", out)
        self.assertIn("`[R](../README.md)` inline", out)

    def test_link_text_holding_inline_code_is_rewritten(self):
        out, done = self.run_rewrite("See [`README.md`](../README.md) and [a `b` c](hidden/x.md).")
        self.assertEqual(
            out,
            f"See [`README.md`]({BASE}/blob/{REF}/README.md) and "
            f"[a `b` c]({BASE}/blob/{REF}/docs/hidden/x.md).",
        )
        self.assertEqual(done, ["../README.md", "hidden/x.md"])

    def test_link_inside_a_code_span_next_to_a_real_link(self):
        out, done = self.run_rewrite("`[R](../README.md)` then [R](../README.md)")
        self.assertEqual(out, f"`[R](../README.md)` then [R]({BASE}/blob/{REF}/README.md)")
        self.assertEqual(done, ["../README.md"])

    def test_image_inside_link_text_is_left_alone_and_the_link_is_rewritten(self):
        out, done = self.run_rewrite("[![badge](../img.png)](../README.md)")
        self.assertEqual(out, f"[![badge](../img.png)]({BASE}/blob/{REF}/README.md)")
        self.assertEqual(done, ["../README.md"])

    def test_fence_inside_a_list_item_or_a_blockquote_is_code(self):
        listed = "1. step\n    ```md\n    [x](../README.md)\n    ```\n"
        quoted = "> ```md\n> [x](../README.md)\n> ```\n"
        for text in (listed, quoted):
            out, done = self.run_rewrite(text)
            self.assertEqual(out, text)
            self.assertEqual(done, [])

    def test_text_after_a_closed_indented_fence_is_still_rewritten(self):
        text = "1. step\n    ```md\n    [x](../README.md)\n    ```\n\n[R](../README.md)\n"
        out, done = self.run_rewrite(text)
        self.assertEqual(done, ["../README.md"])
        self.assertTrue(out.endswith(f"[R]({BASE}/blob/{REF}/README.md)\n"))

    def test_inline_triple_backtick_line_does_not_open_a_fence(self):
        text = "```code``` see [R](../README.md)\n\n[S](../README.md)\n"
        out, done = self.run_rewrite(text)
        self.assertEqual(done, ["../README.md", "../README.md"])
        self.assertEqual(out.count(f"{BASE}/blob/{REF}/README.md"), 2)

    def test_second_pass_changes_nothing(self):
        once, _ = self.run_rewrite("[R](../README.md) [x](hidden/x.md)")
        twice, done = self.run_rewrite(once)
        self.assertEqual(twice, once)
        self.assertEqual(done, [])


class ConfigAndWiring(Fixture):
    def config(self, **overrides) -> FakeConfig:
        """A valid fake MkDocs config for the fixture, with keys overridden or removed."""
        cfg = FakeConfig(
            repo_url=BASE,
            docs_dir=str(self.docs),
            extra={"docs_source_ref": REF},
        )
        cfg.config_file_path = str(self.root / "mkdocs.yml")
        for key, value in overrides.items():
            cfg[key] = value
        return cfg

    def test_on_config_names_missing_repo_url(self):
        with self.assertRaises(self.hooks.HookConfigError) as ctx:
            self.hooks.on_config(self.config(repo_url=None))
        self.assertIn("repo_url", str(ctx.exception))

    def test_on_config_names_missing_ref(self):
        with self.assertRaises(self.hooks.HookConfigError) as ctx:
            self.hooks.on_config(self.config(extra={}))
        self.assertIn("docs_source_ref", str(ctx.exception))
        self.assertIn("mkdocs.yml", str(ctx.exception))

    def test_on_config_returns_a_valid_config_unchanged(self):
        cfg = self.config()
        self.assertIs(self.hooks.on_config(cfg), cfg)

    def test_on_page_markdown_wires_files_lookup(self):
        files = FakeFiles({"page.md", "sub/b.md"})
        text = "[R](../README.md) [b](sub/b.md) [x](hidden/x.md)"
        out = self.hooks.on_page_markdown(
            text, FakePage(self.docs / "page.md"), self.config(), files
        )
        self.assertEqual(
            out,
            f"[R]({BASE}/blob/{REF}/README.md) [b](sub/b.md) "
            f"[x]({BASE}/blob/{REF}/docs/hidden/x.md)",
        )


def read_yml() -> str:
    """The text of the repository's mkdocs.yml (it carries !!python tags, so no safe_load)."""
    return (REPO / "mkdocs.yml").read_text(encoding="utf-8")


def untracked_by_git(root: Path, rels: list) -> list:
    """
    --------------------------------------------------------------------------
    Purpose:
        Name the repository-relative paths that git does not track. A rewritten link to an
        untracked file would be a 404 on GitHub while the file still exists on the build machine.

    Inputs:
        root (Path): the repository root.
        rels (list): repository-relative POSIX paths, files or directories.

    Outputs:
        missing (list): the paths with no tracked file at or under them.
    --------------------------------------------------------------------------
    """
    done = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=GIT_TIMEOUT_S, check=True,
    )
    tracked = [name for name in done.stdout.split("\0") if name]
    return [
        rel for rel in rels
        if not any(name == rel or name.startswith(rel.rstrip("/") + "/") for name in tracked)
    ]


def exclude_patterns(text: str) -> list:
    """The exclude_docs patterns of mkdocs.yml, one per indented line."""
    patterns = []
    for ln in text.split("exclude_docs: |\n", 1)[1].splitlines():
        if ln.strip() and ln[:1] not in (" ", "\t"):
            break  # the next top-level key ends the block scalar
        if ln.strip():
            patterns.append(ln.strip())
    return patterns


def strip_code(text: str) -> str:
    """Remove fenced blocks and inline code spans, for an independent link scan."""
    text = re.sub(r"^(```|~~~).*?^\1[^\n]*$", "", text, flags=re.S | re.M)
    return re.sub(r"`[^`\n]*`", "", text)


class MkdocsWiring(unittest.TestCase):
    def test_exclude_patterns_stop_at_the_next_top_level_key(self):
        text = "exclude_docs: |\n  superpowers/**\n  drafts/*.md\n\nplugins:\n  - search\n"
        self.assertEqual(exclude_patterns(text), ["superpowers/**", "drafts/*.md"])

    def test_mkdocs_yml_declares_hook_ref_and_validation(self):
        text = read_yml()
        self.assertRegex(text, r"(?m)^hooks:\s*\n\s+-\s+scripts/docs/mkdocs_hooks\.py\s*$")
        self.assertRegex(text, r"(?m)^\s+docs_source_ref:\s*main\b")
        self.assertRegex(text, r"(?ms)^validation:.*?^\s+not_found:\s*warn\b")
        self.assertRegex(text, r"(?ms)^validation:.*?^\s+anchors:\s*warn\b")
        self.assertIn("pymdownx.slugs.slugify", text)

    def test_no_served_page_keeps_a_relative_link_leaving_docs(self):
        hooks = load_hooks()
        text = read_yml()
        docs = REPO / "docs"
        patterns = exclude_patterns(text)
        served = {
            p.relative_to(docs).as_posix()
            for p in docs.rglob("*")
            if p.is_file() and not any(
                fnmatch.fnmatch(p.relative_to(docs).as_posix(), pat) for pat in patterns
            )
        }

        def is_served(path: Path) -> bool:
            return path.is_file() and path.relative_to(docs.resolve()).as_posix() in served

        repo_url = re.search(r"(?m)^repo_url:\s*(\S+)", text).group(1)
        ref = re.search(r"(?m)^\s+docs_source_ref:\s*(\S+)", text)
        self.assertIsNotNone(ref, "extra.docs_source_ref is missing from mkdocs.yml")
        offenders = []
        rewritten = set()
        for page in sorted(name for name in served if name.endswith(".md")):
            source = docs / page
            out, done = hooks.rewrite_links(
                source.read_text(encoding="utf-8"),
                page_dir=source.parent,
                docs_dir=docs,
                repo_root=REPO,
                base_url=repo_url,
                ref=ref.group(1),
                is_served=is_served,
            )
            for raw in done:
                resolved = (source.parent / unquote(re.split(r"[?#]", raw)[0])).resolve()
                rewritten.add(resolved.relative_to(REPO.resolve()).as_posix())
            for target in re.findall(
                r"!?\[[^\]\n]*\]\(([^)\s<>]+)(?:\s+\"[^\"\n]*\")?\)", strip_code(out)
            ):
                if target.startswith(("#", "/")) or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target):
                    continue
                path = (source.parent / unquote(re.split(r"[?#]", target)[0])).resolve()
                if not is_served(path):
                    offenders.append(f"{page} -> {target}")
        self.assertEqual(offenders, [], "links that would stay dead on the built site")
        self.assertGreater(len(rewritten), 0, "the corpus rewrote nothing, so this proves nothing")
        self.assertEqual(
            untracked_by_git(REPO, sorted(rewritten)), [],
            "rewritten links to files git does not track, a 404 on GitHub",
        )

    def test_untracked_finder_reports_an_untracked_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True, timeout=GIT_TIMEOUT_S)
            (root / "kept.md").write_text("k", encoding="utf-8")
            (root / "dir").mkdir()
            (root / "dir" / "inner.md").write_text("i", encoding="utf-8")
            (root / "loose.md").write_text("l", encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(root), "add", "kept.md", "dir/inner.md"],
                check=True, timeout=GIT_TIMEOUT_S,
            )
            self.assertEqual(untracked_by_git(root, ["kept.md", "dir", "loose.md"]), ["loose.md"])

    @unittest.skipUnless(
        importlib.util.find_spec("mkdocs") and importlib.util.find_spec("material"),
        "mkdocs and mkdocs-material are not installed in this interpreter",
    )
    def test_strict_build_exits_zero(self):
        with tempfile.TemporaryDirectory() as out:
            done = subprocess.run(
                [sys.executable, "-m", "mkdocs", "build", "--strict",
                 "-f", str(REPO / "mkdocs.yml"), "-d", out],
                capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=REPO,
                timeout=BUILD_TIMEOUT_S,
            )
        self.assertEqual(done.returncode, 0, (done.stdout + done.stderr)[-2000:])


if __name__ == "__main__":
    unittest.main()
