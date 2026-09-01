"""
Offline tests for the frozen qualification task set (qualification/tasks.json).

The task set is the oracle that decides which local model serves each role, so a wrong
expected value does not fail loudly - it silently mis-scores every candidate, forever, and
the mis-scoring looks exactly like a weak model. That is the defect class found on
2026-08-28, when a Markdown fence made every coder task fail for every model and the score
was read as a capability measurement for two weeks.

These tests therefore grade the GRADER. For every coder task, a reference implementation
written here is run through the real oracle built by model_resolver._build_coder_verify_command
and must pass every case. A case whose expectation is wrong fails here, before any model is
asked to satisfy it.

No network, no API key, no model load: the oracle is a local Python subprocess.
"""

import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SCRIPTS))

import model_resolver as mr  # noqa: E402
import ollama_bridge as ob  # noqa: E402

_TASKS_PATH = _SCRIPTS.parent / "qualification" / "tasks.json"

# Reference implementations, one per coder task entrypoint. Each is the contract as the
# task's own prompt states it - deliberately written from the prompt, not copied from the
# repository function it mirrors, so a divergence between prompt and cases shows up here.
_REFERENCES = {
    "norm_doi": '''
def norm_doi(doi):
    if not doi:
        return ""
    text = doi.strip()
    for prefix in ("https://doi.org/", "http://dx.doi.org/"):
        if text.lower().startswith(prefix):
            text = text[len(prefix):]
            break
    return text.lower()
''',
    "split_author_name": '''
def split_author_name(name):
    if "," in name:
        surname, _, rest = name.partition(",")
        rest = rest.strip()
        return (surname.strip(), rest[0] if rest else "")
    words = name.split()
    if len(words) >= 2:
        return (words[-1], words[0][0])
    return (name.strip(), "")
''',
    "doi_prefix": '''
import re

def doi_prefix(doi):
    if not doi:
        return ""
    match = re.search(r"10\\.\\d{4,9}(?=/|$)", doi)
    return match.group(0) if match else ""
''',
    "effective_window": '''
_STEPS = {"f16": 0, "q8_0": 1, "q4_0": 2}

def effective_window(num_ctx, kv_cache_type, exchange_rate):
    return num_ctx / (exchange_rate ** _STEPS.get(kv_cache_type, 0))
''',
    "admissible": '''
def admissible(residency_ratio, free_mib, clamped):
    return residency_ratio >= 0.999 and free_mib >= 300 and not clamped
''',
    "quartile": '''
def quartile(percentile):
    if percentile is None:
        return ""
    if percentile >= 75:
        return "Q1"
    if percentile >= 50:
        return "Q2"
    if percentile >= 25:
        return "Q3"
    return "Q4"
''',
    "normalize_issn": '''
def normalize_issn(raw):
    if not raw:
        return ""
    cleaned = raw.strip().replace("-", "").upper()
    if len(cleaned) != 8:
        return ""
    return cleaned[:4] + "-" + cleaned[4:]
''',
    "context_ladder": '''
def context_ladder(maximum):
    rungs = []
    value = 8192
    while value <= maximum:
        rungs.append(value)
        value *= 2
    return rungs
''',
    "jaccard": '''
def jaccard(a, b):
    left = set(a.lower().split())
    right = set(b.lower().split())
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)
''',
    "slugify": '''
import re

def slugify(title):
    if not title:
        return ""
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
''',
}


def _load_tasks():
    return json.loads(_TASKS_PATH.read_text(encoding="utf-8"))["tasks"]


class TestTheTaskSetHasEnoughResolution(unittest.TestCase):
    """
    Three tasks per role gave four possible scores, so candidates tied constantly and a
    VRAM measurement had to break ties about code quality it knows nothing about. Ten per
    role is the floor this file enforces.
    """

    def test_each_role_has_at_least_ten_tasks(self):
        counts = Counter(task["kind"] for task in _load_tasks())

        self.assertGreaterEqual(counts["coder"], 10, counts)
        self.assertGreaterEqual(counts["writer"], 10, counts)

    def test_every_task_id_is_unique(self):
        ids = [task["id"] for task in _load_tasks()]

        self.assertEqual(len(ids), len(set(ids)))

    def test_every_task_declares_a_known_kind_and_a_source(self):
        for task in _load_tasks():
            with self.subTest(task=task["id"]):
                self.assertIn(task["kind"], {"coder", "writer"})
                self.assertTrue(task.get("source_reference", "").strip())
                self.assertTrue(task.get("prompt", "").strip())


class TestEveryCoderTaskIsSatisfiable(unittest.TestCase):
    """
    The point of this file. A reference implementation of each contract must pass every
    case through the REAL oracle. A wrong expectation fails here rather than being read as
    a weak model later.
    """

    def test_a_reference_implementation_passes_every_case(self):
        coder_tasks = [t for t in _load_tasks() if t["kind"] == "coder"]
        self.assertTrue(coder_tasks)
        with tempfile.TemporaryDirectory(prefix="lari-taskcheck-") as tmp:
            for task in coder_tasks:
                entrypoint = task["entrypoint"]
                with self.subTest(task=task["id"]):
                    self.assertIn(entrypoint, _REFERENCES,
                                  f"no reference implementation for {entrypoint}")
                    module = Path(tmp) / f"{task['id']}.py"
                    module.write_text(_REFERENCES[entrypoint], encoding="utf-8")
                    passed, output = ob.run_verify(
                        mr._build_coder_verify_command(task), module)

                    self.assertTrue(passed, f"{task['id']}: {output}")

    def test_every_coder_task_carries_cases_and_an_entrypoint(self):
        for task in [t for t in _load_tasks() if t["kind"] == "coder"]:
            with self.subTest(task=task["id"]):
                self.assertTrue(task.get("entrypoint"))
                self.assertGreaterEqual(len(task.get("cases", [])), 3)
                for case in task["cases"]:
                    self.assertIn("args", case)
                    self.assertIn("expect", case)

    def test_a_deliberately_wrong_reference_is_caught(self):
        # Proves the check above can actually fail. Without this, a broken oracle that
        # passes everything would look like a green suite.
        task = [t for t in _load_tasks() if t["id"] == "coder-quartile"][0]
        with tempfile.TemporaryDirectory(prefix="lari-taskcheck-") as tmp:
            module = Path(tmp) / "wrong.py"
            module.write_text("def quartile(percentile):\n    return 'Q1'\n", encoding="utf-8")
            passed, _output = ob.run_verify(mr._build_coder_verify_command(task), module)

            self.assertFalse(passed)


class TestEveryWriterTaskIsGateable(unittest.TestCase):
    """
    A writer task has no oracle for whether prose is good, only mechanical gates. Those
    gates must at least be self-consistent: a length window that cannot hold the required
    sections is unsatisfiable, and a prompt that does not name a required heading asks the
    model to guess.
    """

    def test_the_length_window_is_ordered_and_can_hold_the_sections(self):
        for task in [t for t in _load_tasks() if t["kind"] == "writer"]:
            with self.subTest(task=task["id"]):
                low = task.get("min_length_chars", 0)
                high = task.get("max_length_chars", 10 ** 9)
                self.assertLess(low, high)
                headings = sum(len(s) + 4 for s in task.get("required_sections", []))
                self.assertGreater(high, headings)

    def test_every_required_section_is_named_in_the_prompt(self):
        for task in [t for t in _load_tasks() if t["kind"] == "writer"]:
            for section in task.get("required_sections", []):
                with self.subTest(task=task["id"], section=section):
                    self.assertIn(section, task["prompt"])

    def test_every_required_frontmatter_key_is_named_in_the_prompt(self):
        for task in [t for t in _load_tasks() if t["kind"] == "writer"]:
            for key in task.get("frontmatter_keys", []):
                with self.subTest(task=task["id"], key=key):
                    self.assertIn(key, task["prompt"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
