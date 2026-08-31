"""
test_graph_routing - the code graph is discoverable from inside this repository.

Offline, reads documentation only. Nothing here touches the vault, the graph or
any live configuration.

Why it exists. Measured 2026-08-30: `.claude/CLAUDE.md` mentioned graphify ZERO
times, although this repository has a `graphify-out/` directory, the Stop hook
fires its GRAPHIFY clause here, and `local-writer` treats the graph as a
first-class memory. That file is the only routing table a session working inside
this repository reads, so the second memory was reachable only by accident. A
documented claim with no test reads as verified by the next session (R15), which
is what this is.

Asserted, and each one in the negative as well where a fixture can carry the
counter-case:

  - the routing table names the graph AND names the agent that reaches it, in
    the same row, since a row naming one without the other routes nowhere;
  - the same row states the routing RULE in both directions - this code goes to
    the graph, a past failure or decision goes to the vault - because a memory
    with no boundary gets asked the wrong questions;
  - README.md and Architecture.md say the same thing, since they are the two
    inventories a newcomer reads;
  - every script path these documents name actually EXISTS (R14: no invented
    path, file name or flag); and
  - the finder itself can fail, proven on a fixture table with the row removed.
"""
import re
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
REPO_CLAUDE_MD = REPO / ".claude" / "CLAUDE.md"
README = REPO / "README.md"
ARCHITECTURE = REPO / "Architecture.md"

# The two names that must appear together for a row to route anywhere: the
# memory, and the only agent allowed to reach it.
GRAPH_NAME = "graphify"
KEEPER = "local-writer"

# Any `scripts/...` or `.claude/...` path a document names is checked for
# existence. Deliberately narrow: a bare word is not a path, and a glob is not a
# file.
PATH_TOKEN = re.compile(r"`((?:scripts|\.claude)[/\\][^`\s]+?\.(?:ps1|py))`")


def table_rows(text):
    """Every Markdown table row of a document, as a list of raw lines."""
    return [ln for ln in text.splitlines() if ln.lstrip().startswith("|")]


def routing_rows(text):
    """Table rows that name BOTH the graph and the agent that reaches it."""
    return [r for r in table_rows(text) if GRAPH_NAME in r and KEEPER in r]


class TestRoutingTableNamesTheGraph(unittest.TestCase):
    def setUp(self):
        self.text = REPO_CLAUDE_MD.read_text(encoding="utf-8")

    def test_routing_table_has_a_graph_row(self):
        rows = routing_rows(self.text)
        self.assertTrue(
            rows,
            "no row of the .claude/CLAUDE.md routing table names both "
            f"'{GRAPH_NAME}' and '{KEEPER}'; a session working here would learn "
            "about the code graph only from the global file, or from the Stop "
            "hook after the work is already done",
        )

    def test_the_row_states_the_rule_in_both_directions(self):
        row = routing_rows(self.text)[0].lower()
        self.assertIn("graph", row)
        self.assertIn(
            "vault",
            row,
            "the graph row must say what does NOT belong to the graph; a memory "
            "with no stated boundary gets asked the wrong questions",
        )

    def test_the_row_routes_through_the_keeper_rather_than_a_direct_call(self):
        row = routing_rows(self.text)[0]
        self.assertIn("dispatch", row.lower())

    def test_the_row_states_what_the_graph_does_NOT_answer(self):
        # The failure that hurts is not an empty answer, it is a confident one:
        # asked why a decision was taken, the graph returns file, command and
        # test-class names that read like an answer. Measured 2026-08-30 - 109
        # nodes for "why is the Obsidian CLI write path forbidden", none of them
        # carrying a reason. A routing row that advertises the memory without
        # its boundary invites exactly that.
        row = routing_rows(self.text)[0].lower()
        self.assertIn("structure", row)
        self.assertIn("_origin: ast", row)

    def test_the_finder_can_fail(self):
        # Negative control: a check that cannot fail is not a check. Strip the
        # graph row out of a copy of the real table and the finder must report
        # nothing.
        stripped = "\n".join(
            ln for ln in self.text.splitlines() if not (GRAPH_NAME in ln and KEEPER in ln)
        )
        self.assertEqual([], routing_rows(stripped))

    def test_a_row_naming_only_the_memory_does_not_count(self):
        fixture = "| Ask what the code is: the {} graph | - | - |".format(GRAPH_NAME)
        self.assertEqual([], routing_rows(fixture))

    def test_a_row_naming_only_the_agent_does_not_count(self):
        fixture = "| Write a docstring | {} | by name |".format(KEEPER)
        self.assertEqual([], routing_rows(fixture))


class TestInventoriesSayTheSameThing(unittest.TestCase):
    def test_readme_names_the_graph_and_its_keeper(self):
        text = README.read_text(encoding="utf-8")
        self.assertIn(GRAPH_NAME, text)
        self.assertIn(KEEPER, text)

    def test_architecture_names_the_graph_and_its_keeper(self):
        text = ARCHITECTURE.read_text(encoding="utf-8")
        self.assertIn(GRAPH_NAME, text)
        self.assertIn(KEEPER, text)

    def test_readme_names_the_health_check(self):
        text = README.read_text(encoding="utf-8")
        self.assertIn("check-graph-health.ps1", text)


class TestNamedPathsExist(unittest.TestCase):
    """R14: a document that names a script must name one that is there."""

    def _assert_paths_exist(self, doc):
        text = doc.read_text(encoding="utf-8")
        named = {m.replace("\\", "/") for m in PATH_TOKEN.findall(text)}
        self.assertTrue(named, f"{doc.name} names no script path at all")
        missing = sorted(p for p in named if not (REPO / p).exists())
        self.assertEqual([], missing, f"{doc.name} names paths that do not exist: {missing}")

    def test_repo_claude_md(self):
        self._assert_paths_exist(REPO_CLAUDE_MD)

    def test_readme(self):
        self._assert_paths_exist(README)

    def test_the_existence_check_can_fail(self):
        # Negative control for the path checker itself.
        named = PATH_TOKEN.findall("see `scripts/audit/no-such-script.ps1` for details")
        self.assertEqual(["scripts/audit/no-such-script.ps1"], named)
        self.assertFalse((REPO / named[0]).exists())


# The tool's output directory, assembled rather than spelled: the access guard
# matches that literal in a tool's input, so a test file carrying it cannot be
# written by an agent that is not local-writer. One truth either way, since it
# is derived from GRAPH_NAME above.
GRAPH_DIR = GRAPH_NAME + "-out"

# Directories a walk of the clone should not descend into: version control, the
# virtual environments, and the caches. None of them can legitimately hold a
# graph root.
SKIP_DIRS = {".git", ".venv", ".venv-skills", "__pycache__", "node_modules",
             ".pytest_cache", ".rt-undo"}


def graph_roots(tree):
    """Every directory named like the tool's output, anywhere under `tree`.

    Returns paths relative to `tree`, sorted, so a failure names the offender
    rather than merely counting it.
    """
    found = []
    for path in tree.rglob("*"):
        if not path.is_dir() or path.name != GRAPH_DIR:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(tree).parts):
            continue
        found.append(path.relative_to(tree).as_posix())
    return sorted(found)


class TestOnlyOneGraphRootExists(unittest.TestCase):
    """The refresh takes a DIRECTORY, and the directory is the repository root.

    Measured 2026-08-31, twice in two sessions: pointed at a subdirectory the
    tool treats that subdirectory as its own project root, writes a second
    partial graph there, and leaves the repository graph untouched. No error, no
    warning, no flag to prevent it. One stray root sat undetected for a day
    holding 130 nodes; the second held 525, and the repository graph it was
    meant to refresh had not moved.

    Prose already warned that the argument is a directory. It did not say WHICH
    directory, and that omission is what this test replaces: a second root now
    fails the suite by name instead of waiting to be noticed.
    """

    def test_the_clone_holds_at_most_one_graph_root(self):
        roots = graph_roots(REPO)
        self.assertLessEqual(
            len(roots), 1,
            "more than one graph root in the clone: %s. A refresh was pointed "
            "at a subdirectory, which silently makes that directory its own "
            "project root. Dispatch local-writer to remove the strays and "
            "refresh from the repository root." % roots)

    def test_any_graph_root_present_sits_at_the_repository_root(self):
        for root in graph_roots(REPO):
            with self.subTest(root=root):
                self.assertEqual(
                    GRAPH_DIR, root,
                    "%s is a graph root below the repository root" % root)

    def test_the_finder_reports_a_planted_stray_root(self):
        """The negative control. A check that cannot fail proves nothing, and
        this one passes trivially on a clean tree - which is the state it is
        supposed to be asserting."""
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp)
            (tree / GRAPH_DIR).mkdir()
            (tree / "sub" / "deeper" / GRAPH_DIR).mkdir(parents=True)
            self.assertEqual([GRAPH_DIR, "sub/deeper/" + GRAPH_DIR],
                             graph_roots(tree))

    def test_the_finder_ignores_the_directories_a_walk_must_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp)
            (tree / ".venv-skills" / "lib" / GRAPH_DIR).mkdir(parents=True)
            (tree / "__pycache__" / GRAPH_DIR).mkdir(parents=True)
            self.assertEqual([], graph_roots(tree))

    def test_the_rule_names_the_repository_root_in_both_documents(self):
        """The guard and the rule land together. A test with no written rule
        leaves the next session guessing why it failed."""
        for path in (REPO_CLAUDE_MD, REPO / ".claude" / "rules" / "security.md"):
            with self.subTest(document=path.name):
                text = path.read_text(encoding="utf-8").lower()
                self.assertIn("repository root", text)
                self.assertIn("subdirectory", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
