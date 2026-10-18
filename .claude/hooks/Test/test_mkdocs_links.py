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

import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
