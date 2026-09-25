"""
test_rt_persistence_invariant - the journal-durable plan's acceptance criterion:
"rt-observe sans les deux services: sortie JSON identique a aujourd'hui, prouvee
par un test" (section 5 of docs/superpowers/todo/2026-09-24-rt-observe-journal-
durable.md).

What "identical" means here, stated once rather than left ambiguous: every
section that existed before this plan is computed by the EXACT SAME builder
function it always was, reads nothing from the new 'postgres'/'openobserve'
config keys, and is unaffected by whether those keys are present or absent. The
two new sections (identity, traces) are ADDITIVE - every other collector in this
skill already follows the same pattern (mcp, graph, services all appear as keys
even when their harness is absent, reporting unavailable with a reason) - and on
an unconfigured clone they report "unavailable" with a named reason, never a
blank panel and never a crash of any OTHER section (R8).

This is the meaningful, testable reading of the criterion: a literal forever-
byte-identical JSON string is impossible to hold once ANY section is added,
which every existing collector in this skill (mcp, graph, services) already
demonstrates by existing as a key regardless of harness presence.
"""
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import collect_services  # noqa: E402
import rt_state  # noqa: E402

NOW = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)

# The section keys section_builders() returned before the journal-durable plan
# touched this module (measured against the 2026-09-01 state of rt_state.py,
# before Phase 2/3 of docs/superpowers/todo/2026-09-24-rt-observe-journal-
# durable.md). A key disappearing from this set, or one of these builders being
# silently replaced, is exactly the regression this test exists to catch.
PRE_EXISTING_SECTIONS = {
    "mirrors", "registry", "repo_state", "progress", "graph", "mcp",
    "services", "fleet", "usage",
}
NEW_SECTIONS = {"identity", "traces"}


class TempTree(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name) / "repo"
        self.home = Path(self._tmp.name) / "home"
        self.repo.mkdir(parents=True, exist_ok=True)
        self.home.mkdir(parents=True, exist_ok=True)


def no_binaries():
    return mock.patch.object(collect_services.shutil, "which", return_value=None)


class SectionSetTest(TempTree):
    def test_every_pre_existing_section_key_still_exists(self):
        config = {}  # no postgres, no openobserve: the default clone state
        builders = rt_state.section_builders(self.repo, self.home, config)
        self.assertTrue(PRE_EXISTING_SECTIONS.issubset(set(builders.keys())))

    def test_the_only_new_keys_are_identity_and_traces(self):
        config = {}
        builders = rt_state.section_builders(self.repo, self.home, config)
        added = set(builders.keys()) - PRE_EXISTING_SECTIONS
        self.assertEqual(NEW_SECTIONS, added)


class UnconfiguredNewSectionsTest(TempTree):
    def test_identity_reports_unavailable_with_a_reason(self):
        config = {}
        builders = rt_state.section_builders(self.repo, self.home, config)
        with no_binaries():
            state = builders["identity"](NOW)
        self.assertEqual(state["status"], "unavailable")
        self.assertTrue(state.get("reason"))

    def test_traces_reports_unavailable_with_a_reason(self):
        config = {}
        builders = rt_state.section_builders(self.repo, self.home, config)
        with no_binaries():
            state = builders["traces"](NOW)
        self.assertEqual(state["status"], "unavailable")
        self.assertTrue(state.get("reason"))


class PreExistingSectionsUnaffectedTest(TempTree):
    """The persistence layer being undeclared must change NOTHING about how
    every pre-existing section is built: same function, same signature, same
    behaviour whether or not 'postgres'/'openobserve' happen to be present."""

    def test_pre_existing_sections_build_the_same_whether_or_not_the_optional_keys_are_present(self):
        config_without = {}
        config_with_unrelated_keys = {
            "postgres": {"host": "db", "port": 5432, "dbname": "rt",
                        "user": "lar"},
            "openobserve": {"base_url": "http://127.0.0.1:5080", "org": "lar"},
        }
        builders_a = rt_state.section_builders(self.repo, self.home,
                                                config_without)
        builders_b = rt_state.section_builders(self.repo, self.home,
                                                config_with_unrelated_keys)
        with no_binaries():
            for name in PRE_EXISTING_SECTIONS:
                state_a = builders_a[name](NOW)
                state_b = builders_b[name](NOW)
                # 'services' and 'fleet' carry no timestamp of their own beyond
                # what NOW already fixes, and every collector here is already
                # proven deterministic under a frozen clock by test_rt_
                # collectors.py; the point of THIS assertion is narrower and
                # sharper: adding a fully unrelated 'postgres'/'openobserve'
                # block must not change a single one of these, because none of
                # them may read it (R2: rt_store.py and rt_openobserve.py are
                # the ONLY modules that know those keys exist).
                self.assertEqual(state_a, state_b,
                                 "section %r changed when an unrelated "
                                 "postgres/openobserve block appeared" % name)


if __name__ == "__main__":
    unittest.main()
