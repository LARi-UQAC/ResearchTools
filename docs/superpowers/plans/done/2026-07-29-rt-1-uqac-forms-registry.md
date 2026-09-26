# RT-1: UQAC Form Registry and Drift Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the `uqac-forms` skill scaffold with a declarative registry of UQAC PDF forms, a validated downloader, a SHA-256 baseline, and a drift check that refuses to let downstream tooling run against a form UQAC has silently replaced.

> ## SCOPE CHANGE, 2026-07-29 - read before anything else
>
> Two decisions changed after this plan was written, and `NEW_ARCHITECTURE.md` on `main`
> is the authority on both. **Read its sections 1, 3 and 10 before starting.**
>
> **The repository boundary moved.** ResearchTools cannot track a form and cannot know the information that fills one: it is skills, agents and commands for a thesis, a paper, a review or a report, and only ThesisTracker writes the database. The form catalogue, the workflow rules, the field maps, the profile store and the drift check therefore live in **ThesisTracker**, edited in the UI by an `owner` or the `direction`. The ResearchTools service is reduced to **stateless PDF mechanics**: hand it a PDF and a set of values, it hands back a PDF. It is a function, not a system, and holds no data.
>
> > **What this means for RT-1.** The `registry/forms.yaml` catalogue, the SHA-256
> baseline, the drift check and the stale-map gate all move to **TT-8**, where they
> become rows in the ThesisTracker database and a `fetch` in Node. What remains here is
> the part only Python can do:
>
> - the `uqac-forms` skill scaffold and its `SKILL.md`,
> - the **validated PDF-ingest contract**: `%PDF` magic bytes, the size cap, https
>   only, capped redirects, atomic write. TT-8 reuses the same contract in Node, so
>   keep it documented as a contract and not only as code,
> - the offline test suite and the repo wiring (README, `Architecture.md`, the routing
>   row, `install.ps1`).
>
> Do **not** build `registry/forms.yaml`, `registry/baseline.json`, `require_fresh_map`
> or the `check` subcommand. Tasks 1, 3 and 4 below are superseded; Task 2 (the
> validated downloader) and Task 5 (the wiring) stand, with the registry references in
> Task 5 rewritten to describe a stateless service.
>
> Everything below that this block does not contradict still stands. Where the plan and
> `NEW_ARCHITECTURE.md` disagree, the architecture document wins, and your first commit
> should be the correction to this plan.


**Architecture:** A new skill folder `.claude/skills/uqac-forms/` holds a human-curated `registry/forms.yaml` (one entry per official form), a generated `registry/baseline.json` (per-form SHA-256 fingerprint), and per-form field maps under `registry/maps/<form_id>.json` (populated later by RT-2). `form_registry.py` downloads each form over HTTPS with the same validation contract as the `scopus` skill's `download_pdf.py` (PDF magic bytes, size cap, manual redirect handling, atomic write), records the fingerprint, and on a later mismatch marks the form's field map `stale` so the filler refuses to run. The field-level diff is injected as a callable so RT-1 stays offline-testable and RT-2 wires the real differ in without touching this file.

**Tech Stack:** Python 3.13, `requests` (HTTP), `PyYAML` (registry parsing), standard library `hashlib` / `json` / `argparse` / `logging`. No PDF library in this unit: RT-1 is byte fidelity only, field-level knowledge starts at RT-2.

## CORRECTION, 2026-08-31 - what this unit actually builds

The scope-change block above says Task 2 stands. Taken literally that is not
possible: Task 2 consumes `FormSpec` and `load_registry` from Task 1, and Task 1
is superseded. The registry is the thing that moved to TT-8, so the downloader
cannot keep a registry-shaped interface. This block replaces the File Structure
and the published-interface table, and restates Task 2's signature. Where an
older section below disagrees with this one, this one wins.

**The module is renamed.** `form_registry.py` becomes `pdf_ingest.py`. Nothing in
this unit loads a registry any more, and a module named for a registry it does
not contain would mislead every later unit that imports it.

**The downloader takes a URL, not a form.** A `FormSpec` carried `form_id`,
`office` and `source`, which are database columns in ThesisTracker now. The
caller names the destination path, so this unit chooses no filenames and keeps no
index of what it has fetched. Stateless PDF mechanics, per section 1.

### Corrected file structure

**New files**

- `.claude/skills/uqac-forms/SKILL.md`
- `.claude/skills/uqac-forms/scripts/pdf_ingest.py`
- `.claude/skills/uqac-forms/scripts/requirements.txt`
- `.claude/skills/uqac-forms/scripts/Test/test_pdf_ingest.py`
- `.claude/commands/uqacform.md`

**Not built here** (all moved to TT-8, where they are database rows and a `fetch`
in Node): `registry/forms.yaml`, `registry/baseline.json`, `registry/maps/`, the
PDF cache directory, and every function that reads or writes them.

**Modified files** are unchanged from the list below, minus the `.gitignore` row:
with no cache directory there is nothing to ignore.

### Corrected interfaces published by RT-1

Consumed from `.claude/skills/uqac-forms/scripts/pdf_ingest.py`:

| Name | Signature | Consumed by |
|---|---|---|
| `fetch_pdf` | `fetch_pdf(url: str, dest: str, *, max_bytes: int = MAX_PDF_BYTES, max_redirects: int = MAX_REDIRECTS, timeout_s: float = REQUEST_TIMEOUT_S) -> str \| None` | RT-2, RT-3 |
| `sha256_file` | `sha256_file(path: str) -> str` | RT-2, RT-5 |
| `sha256_bytes` | `sha256_bytes(data: bytes) -> str` | RT-5 |
| `MAX_PDF_BYTES`, `MAX_REDIRECTS`, `REQUEST_TIMEOUT_S`, `CHUNK_BYTES` | module constants | RT-2, RT-3, RT-5 |

The nine other names in the old table - `FormSpec`, `load_registry`,
`cache_path`, `map_path`, `map_status`, `mark_map_stale`, `require_fresh_map`,
`check_drift`, `StaleMapError` - are not published by this unit. RT-2, RT-3 and
RT-5 receive a path and a value dictionary from their caller instead.

### The ingest contract, stated once for two languages

TT-8 already implements this contract in Node (`api/_lib/drift.js`,
`api/_lib/routes/catalogue.js`). Two implementations of one contract only stay
honest if the contract is written down with numbers, so:

| Rule | Value | Why it is not optional |
|---|---|---|
| Scheme | `https` only, **re-checked on every redirect hop** | Checking only the URL the caller typed is not a scheme check. A source that answers 302 to `http://` defeats it entirely. |
| Redirects | at most `MAX_REDIRECTS` = 5, followed manually | An automatic follower cannot re-check the scheme between hops. |
| Size | `MAX_PDF_BYTES` = 25 MiB, enforced **during** the stream | A cap applied after the body is in memory cannot prevent the allocation it exists to prevent. |
| Magic bytes | first four bytes are `%PDF` | UQAC answers HTTP 200 with an HTML access page when a form moves. Status alone never proves a PDF. |
| Timeout | `REQUEST_TIMEOUT_S` = 30 | Without one, a source that accepts and then stalls holds the caller open indefinitely. |
| Write | atomic: `*.part` then `os.replace` | A partial file that looks like a cached form is worse than no file. |

**Known divergence, recorded rather than silently fixed here.** As shipped, the
Node side does not satisfy rows 1, 3 and 5: it passes `redirect: 'follow'` and
checks the scheme once, it calls `arrayBuffer()` before comparing to the cap, and
it sets no timeout. That is a ThesisTracker defect, not an RT-1 one, and it is
listed in the Open items below so the fix is traceable to the contract that
found it rather than arriving as an unexplained patch.

---

## Global Constraints

- Definition files (agents, skills, commands) are **English-only**. French appears only in emitted deliverable strings and the repo-root `CLAUDE.md`.
- Style hygiene in any produced text: no em dash, no double or triple dash, straight quotes only, no zero-width or Unicode-tag characters, no single-character ellipsis, no leftover `*` or `#`.
- Python naming: classes `PascalCase`, functions and module variables `snake_case`, private `_snake_case`, constants `UPPER_SNAKE_CASE`. Type hints in every signature (PEP 8 / PEP 484).
- Docstrings use the repo's extended format: a `Purpose: / Inputs: / Outputs:` block between dashed rules (see `.claude/rules/code-style.md`).
- Logging: `logging.getLogger(__name__)` per module, messages prefixed with a context tag, here `[UQAC-FORMS]`.
- Dependencies are pinned **exactly** in the skill's own `requirements.txt`, then audited: `pip-audit -r .claude/skills/uqac-forms/requirements.txt --strict`.
- Offline tests only: no network, no API key, no model load. Tests live in `scripts/Test/` and patch `requests.get`.
- HTTPS only, capped redirects, size cap, magic-byte validation on every download. Never follow a redirect to a non-https scheme.
- All fixtures are synthetic. No real profile, certificate, or key is ever committed.
- A skill has **no per-tool mirror**, so the routing row in `.claude/CLAUDE.md` is the only thing that makes it discoverable outside Claude Code. Follow `docs/authoring-and-mirrors.md` sections 7 and 10.

---

## File Structure

**New files**

- `.claude/skills/uqac-forms/SKILL.md` - skill definition: workflow, prerequisites, outputs, the unverified-signature disclosure.
- `.claude/skills/uqac-forms/registry/forms.yaml` - human-curated list of registered UQAC forms. Never generated.
- `.claude/skills/uqac-forms/scripts/form_registry.py` - registry loader, validated downloader, baseline, drift check.
- `.claude/skills/uqac-forms/scripts/requirements.txt` - exact pins for this skill.
- `.claude/skills/uqac-forms/scripts/Test/test_form_registry.py` - offline unit tests (`requests.get` patched).
- `.claude/commands/uqacform.md` - thin `/uqacform` wrapper pointing at the skill.

**Generated at runtime, not committed with content**

- `.claude/skills/uqac-forms/registry/baseline.json` - `{form_id: {sha256, bytes, url, captured_at}}`.
- `.claude/skills/uqac-forms/registry/maps/<form_id>.json` - field map; RT-1 only reads and flips its `status`.
- The PDF cache directory (default `out/uqac-forms/cache/`) is gitignored.

**Modified files**

- `.claude/CLAUDE.md` - Tooling routing row (critical: sole discoverability path).
- `README.md` - skill count in three places, skills-table row, `### uqac-forms` subsection, Prerequisites rows, File-Locations tree, command count and `/uqacform` row, TODO item 3 decision note.
- `Architecture.md` - Layer 1 mermaid `SK` subgraph node, `CMD` node with a direct command-to-skill edge, inventory counts.
- `.claude/rules/workflows.md` - flow row.
- `.claude/rules/testing.md` - new offline test command in the script-surface list.
- `.gitignore` - ignore the PDF cache directory.

---

## Task 1: Registry loader (SUPERSEDED - moved to TT-8)

**Files:**

- Create: `.claude/skills/uqac-forms/registry/forms.yaml`
- Create: `.claude/skills/uqac-forms/scripts/form_registry.py`
- Create: `.claude/skills/uqac-forms/scripts/requirements.txt`
- Test: `.claude/skills/uqac-forms/scripts/Test/test_form_registry.py`

**Interfaces:**

- Consumes: nothing (first unit).
- Produces:
  - `class FormSpec` with attributes `form_id: str`, `title: str`, `url: str`, `office: str`, `source: str`, `description: str`.
  - `load_registry(path: str) -> dict[str, FormSpec]` keyed by `form_id`.
  - `REGISTRY_PATH: str`, `BASELINE_PATH: str`, `MAPS_DIR: str` module constants resolving relative to the script file.

- [ ] **Step 1: Write the failing test**

Create `.claude/skills/uqac-forms/scripts/Test/test_form_registry.py`:

```python
"""
test_form_registry.py - Offline unit tests for form_registry.py.

No network, no API key: every HTTP call is patched. Run with the project Python:
    python .claude/skills/uqac-forms/scripts/Test/test_form_registry.py
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import form_registry  # noqa: E402


SAMPLE_YAML = """
forms:
  - id: mth-inscription-sujet
    title: "Formulaire d'inscription du sujet de recherche"
    url: "https://www.uqac.ca/de-docs/mth-formulaires/1-formulaire-inscription-sujet.pdf"
    office: decanat
    source: "https://www.uqac.ca/decanat/mth-formulaires/"
    description: "Registers the research subject with the Decanat des etudes."
  - id: srf-rapport-depenses
    title: "Rapport de depenses"
    url: "https://www.uqac.ca/srf-docs/formulaires/rapport_depenses.pdf"
    office: srf
    source: "https://www.uqac.ca/srf/formulaires/"
    description: "Expense claim filed with the Service des ressources financieres."
"""


class TestLoadRegistry(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "forms.yaml")
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(SAMPLE_YAML)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_loads_every_entry_keyed_by_id(self) -> None:
        registry = form_registry.load_registry(self.path)
        self.assertEqual(set(registry), {"mth-inscription-sujet", "srf-rapport-depenses"})

    def test_spec_carries_the_declared_fields(self) -> None:
        spec = form_registry.load_registry(self.path)["srf-rapport-depenses"]
        self.assertEqual(spec.office, "srf")
        self.assertTrue(spec.url.startswith("https://"))
        self.assertEqual(spec.title, "Rapport de depenses")

    def test_rejects_a_non_https_url(self) -> None:
        bad = os.path.join(self.tmp.name, "bad.yaml")
        with open(bad, "w", encoding="utf-8") as handle:
            handle.write(SAMPLE_YAML.replace("https://www.uqac.ca/srf-docs", "http://www.uqac.ca/srf-docs"))
        with self.assertRaises(ValueError):
            form_registry.load_registry(bad)

    def test_rejects_a_duplicate_id(self) -> None:
        dupe = os.path.join(self.tmp.name, "dupe.yaml")
        with open(dupe, "w", encoding="utf-8") as handle:
            handle.write(SAMPLE_YAML + SAMPLE_YAML.split("forms:")[1])
        with self.assertRaises(ValueError):
            form_registry.load_registry(dupe)


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python .claude/skills/uqac-forms/scripts/Test/test_form_registry.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'form_registry'`.

- [ ] **Step 3: Write the requirements file**

Create `.claude/skills/uqac-forms/scripts/requirements.txt`:

```
# Dependencies for the uqac-forms skill scripts.
#
# form_registry.py : requests (validated HTTPS download), PyYAML (registry parsing)
# field_map.py     : pypdf (RT-2, AcroForm widget enumeration)
# fill_form.py     : pypdf (RT-3)
# sign_form.py     : pyhanko (RT-4, PAdES incremental-update signature)
#
# pypdf is BSD-3 and pyhanko is MIT: this skill must stay AGPL-free because it
# ships inside a deployable container (PyMuPDF, used by extract-statistic, is
# AGPL-3.0 and stays isolated in that skill).
#
# Audit before use:
#   pip-audit -r .claude/skills/uqac-forms/requirements.txt --strict

requests==2.34.2
PyYAML==6.0.3
```

- [ ] **Step 4: Write the minimal implementation**

Create `.claude/skills/uqac-forms/scripts/form_registry.py`:

```python
"""
form_registry.py - Registry, fingerprint, and drift detection for the official
UQAC PDF forms the uqac-forms skill fills and signs.

UQAC can add, modify, or withdraw a form at any time, always at the same URL.
This script is the guard against that: it records a SHA-256 fingerprint per
registered form and, on a later mismatch, marks the form's field map stale so
the filler refuses to produce an official-looking document from a map that no
longer describes the file.

Usage:
  python form_registry.py list
  python form_registry.py fetch    <form_id | --all> [--cache-dir DIR]
  python form_registry.py baseline <form_id | --all> [--cache-dir DIR]
  python form_registry.py check    <form_id | --all> [--cache-dir DIR]
  python form_registry.py status
"""

import argparse
import datetime
import hashlib
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

import requests
import yaml

logger = logging.getLogger(__name__)

_HERE = os.path.dirname(os.path.abspath(__file__))
_SKILL_ROOT = os.path.dirname(_HERE)

REGISTRY_PATH = os.path.join(_SKILL_ROOT, "registry", "forms.yaml")
BASELINE_PATH = os.path.join(_SKILL_ROOT, "registry", "baseline.json")
MAPS_DIR = os.path.join(_SKILL_ROOT, "registry", "maps")
DEFAULT_CACHE_DIR = os.path.join("out", "uqac-forms", "cache")

PDF_MAGIC = b"%PDF"
MAX_PDF_BYTES = 25 * 1024 * 1024  # 25 MB cap: an administrative form is far smaller
MAX_REDIRECTS = 5
CHUNK_BYTES = 8192
REQUEST_TIMEOUT_S = 60


@dataclass(frozen=True)
class FormSpec:
    """One registered UQAC form, exactly as declared in registry/forms.yaml."""

    form_id: str
    title: str
    url: str
    office: str
    source: str
    description: str


def load_registry(path: str = REGISTRY_PATH) -> dict[str, FormSpec]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Parse the human-curated form registry into FormSpec objects, rejecting
        a malformed entry at load time rather than at download time.

    Inputs:
        path (str): path to registry/forms.yaml

    Outputs:
        registry (dict[str, FormSpec]): specs keyed by form id

    Raises:
        FileNotFoundError if the registry is missing.
        ValueError on a missing field, a duplicate id, or a non-https url.
    --------------------------------------------------------------------------
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"registry not found: {path}")
    with open(path, encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    entries = raw.get("forms") or []
    registry: dict[str, FormSpec] = {}
    for entry in entries:
        form_id = str(entry.get("id") or "").strip()
        url = str(entry.get("url") or "").strip()
        if not form_id:
            raise ValueError("registry entry with no id")
        if form_id in registry:
            raise ValueError(f"duplicate form id in registry: {form_id}")
        # https only at the registry boundary, so no later code path can be
        # handed a downgraded scheme.
        if urlparse(url).scheme != "https":
            raise ValueError(f"form {form_id}: url must be https, got {url!r}")
        registry[form_id] = FormSpec(
            form_id=form_id,
            title=str(entry.get("title") or "").strip(),
            url=url,
            office=str(entry.get("office") or "").strip(),
            source=str(entry.get("source") or "").strip(),
            description=str(entry.get("description") or "").strip(),
        )
    if not registry:
        raise ValueError(f"registry has no forms: {path}")
    return registry
```

- [ ] **Step 5: Write the registry data file**

Create `.claude/skills/uqac-forms/registry/forms.yaml`. The five entries below were probed on 2026-07-29: all carry `/AcroForm` and no XFA, so filling is deterministic and no OCR is involved.

```yaml
# Registered UQAC forms. Human-curated: never generated, never rewritten by a
# script. The fingerprint of each file lives in the generated baseline.json;
# the field map of each file lives in maps/<id>.json.
#
# Sources:
#   Decanat des etudes, thesis forms      https://www.uqac.ca/decanat/mth-formulaires/
#   Service des ressources financieres    https://www.uqac.ca/srf/formulaires/
#   Departement des sciences appliquees   https://www.uqac.ca/dsa/documents/
forms:
  - id: mth-inscription-sujet
    title: "Formulaire d'inscription du sujet de recherche"
    url: "https://www.uqac.ca/de-docs/mth-formulaires/1-formulaire-inscription-sujet.pdf"
    office: decanat
    source: "https://www.uqac.ca/decanat/mth-formulaires/"
    description: "Registers the research subject and the supervision team."

  - id: mth-plan-travail
    title: "Plan de travail"
    url: "https://www.uqac.ca/de-docs/mth-formulaires/1-plan-travail.pdf"
    office: decanat
    source: "https://www.uqac.ca/decanat/mth-formulaires/"
    description: "Work plan filed alongside the research subject."

  - id: mth-autorisation-depot
    title: "Autorisation de depot pour evaluation"
    url: "https://www.uqac.ca/de-docs/mth-formulaires/2-autorisation-depot-evaluation.pdf"
    office: decanat
    source: "https://www.uqac.ca/decanat/mth-formulaires/"
    description: "Supervisor authorization to deposit the thesis for evaluation."

  - id: srf-rapport-depenses
    title: "Rapport de depenses"
    url: "https://www.uqac.ca/srf-docs/formulaires/rapport_depenses.pdf"
    office: srf
    source: "https://www.uqac.ca/srf/formulaires/"
    description: "Expense claim after a mission or a conference."

  - id: srf-demande-avance-voyage
    title: "Demande d'avance de voyage"
    url: "https://www.uqac.ca/srf-docs/formulaires/demande_avance_voyage.pdf"
    office: srf
    source: "https://www.uqac.ca/srf/formulaires/"
    description: "Travel advance request filed before a mission."
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python .claude/skills/uqac-forms/scripts/Test/test_form_registry.py`
Expected: PASS, 4 tests.

- [ ] **Step 7: Commit**

```bash
git add .claude/skills/uqac-forms/registry/forms.yaml \
        .claude/skills/uqac-forms/scripts/form_registry.py \
        .claude/skills/uqac-forms/scripts/requirements.txt \
        .claude/skills/uqac-forms/scripts/Test/test_form_registry.py
git commit -m "feat(uqac-forms): registry loader with https and duplicate-id validation"
```

---

## Task 2: Validated downloader (CORRECTED - see the correction block above)

**Files:**

- Modify: `.claude/skills/uqac-forms/scripts/form_registry.py`
- Test: `.claude/skills/uqac-forms/scripts/Test/test_form_registry.py`

**Interfaces:**

- Consumes: `FormSpec`, `load_registry` from Task 1.
- Produces:
  - `sha256_file(path: str) -> str`
  - `cache_path(spec: FormSpec, cache_dir: str) -> str` returning `<cache_dir>/<form_id>.pdf`
  - `fetch_form(spec: FormSpec, cache_dir: str, force: bool = False) -> str | None` returning the cached path on success, `None` on failure.

- [ ] **Step 1: Write the failing test**

Append to `.claude/skills/uqac-forms/scripts/Test/test_form_registry.py`, above the `if __name__` block:

```python
class _FakeResponse:
    """Minimal stand-in for a streamed requests.Response."""

    def __init__(self, body: bytes, status: int = 200, headers: dict | None = None) -> None:
        self._body = body
        self.status_code = status
        self.headers = headers or {"Content-Type": "application/pdf"}

    def iter_content(self, chunk_size: int):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i:i + chunk_size]

    def close(self) -> None:
        pass


class TestFetchForm(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = os.path.join(self.tmp.name, "cache")
        self.spec = form_registry.FormSpec(
            form_id="srf-rapport-depenses",
            title="Rapport de depenses",
            url="https://www.uqac.ca/srf-docs/formulaires/rapport_depenses.pdf",
            office="srf",
            source="https://www.uqac.ca/srf/formulaires/",
            description="",
        )
        self._real_get = form_registry.requests.get

    def tearDown(self) -> None:
        form_registry.requests.get = self._real_get
        self.tmp.cleanup()

    def test_writes_a_real_pdf(self) -> None:
        form_registry.requests.get = lambda *a, **k: _FakeResponse(b"%PDF-1.7\nbody\n%%EOF")
        path = form_registry.fetch_form(self.spec, self.cache)
        self.assertTrue(path and os.path.isfile(path))
        with open(path, "rb") as handle:
            self.assertTrue(handle.read(4) == b"%PDF")

    def test_rejects_an_html_access_page_served_with_http_200(self) -> None:
        form_registry.requests.get = lambda *a, **k: _FakeResponse(
            b"<html><body>Acces refuse</body></html>", headers={"Content-Type": "text/html"})
        self.assertIsNone(form_registry.fetch_form(self.spec, self.cache))
        self.assertFalse(os.path.exists(form_registry.cache_path(self.spec, self.cache)))

    def test_leaves_no_partial_file_when_the_cap_is_exceeded(self) -> None:
        oversized = b"%PDF-1.7" + b"x" * (form_registry.MAX_PDF_BYTES + 10)
        form_registry.requests.get = lambda *a, **k: _FakeResponse(oversized)
        self.assertIsNone(form_registry.fetch_form(self.spec, self.cache))
        self.assertFalse(os.path.exists(form_registry.cache_path(self.spec, self.cache)))
        self.assertFalse(os.path.exists(form_registry.cache_path(self.spec, self.cache) + ".part"))

    def test_refuses_a_redirect_to_a_non_https_scheme(self) -> None:
        def redirect_to_http(*args, **kwargs):
            return _FakeResponse(b"", status=302, headers={"Location": "http://www.uqac.ca/f.pdf"})
        form_registry.requests.get = redirect_to_http
        self.assertIsNone(form_registry.fetch_form(self.spec, self.cache))

    def test_skips_the_network_when_the_file_is_already_cached(self) -> None:
        os.makedirs(self.cache, exist_ok=True)
        with open(form_registry.cache_path(self.spec, self.cache), "wb") as handle:
            handle.write(b"%PDF-1.7\ncached\n%%EOF")

        def explode(*args, **kwargs):
            raise AssertionError("fetch_form hit the network despite a cache hit")
        form_registry.requests.get = explode
        self.assertEqual(
            form_registry.fetch_form(self.spec, self.cache),
            form_registry.cache_path(self.spec, self.cache),
        )

    def test_sha256_is_stable(self) -> None:
        path = os.path.join(self.tmp.name, "x.pdf")
        with open(path, "wb") as handle:
            handle.write(b"%PDF-1.7\n")
        self.assertEqual(form_registry.sha256_file(path), form_registry.sha256_file(path))
        self.assertEqual(len(form_registry.sha256_file(path)), 64)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python .claude/skills/uqac-forms/scripts/Test/test_form_registry.py`
Expected: FAIL with `AttributeError: module 'form_registry' has no attribute 'fetch_form'`.

- [ ] **Step 3: Write the minimal implementation**

Append to `.claude/skills/uqac-forms/scripts/form_registry.py`:

```python
def sha256_file(path: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Hash a file with SHA-256, streamed, so a large PDF is never fully
        resident in memory.

    Inputs:
        path (str): file to hash

    Outputs:
        digest (str): lowercase hexadecimal digest, 64 characters
    --------------------------------------------------------------------------
    """
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cache_path(spec: FormSpec, cache_dir: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the cache location of a registered form. The name comes from the
        registry id, never from the remote URL, so a hostile Location header
        cannot steer the write outside the cache directory.

    Inputs:
        spec (FormSpec): the registered form
        cache_dir (str): cache directory

    Outputs:
        path (str): <cache_dir>/<form_id>.pdf
    --------------------------------------------------------------------------
    """
    return os.path.join(cache_dir, f"{spec.form_id}.pdf")


def _write_validated(response: Any, dest: str) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Stream an HTTP response body to `dest` only if it is a real PDF. The
        first bytes must be the %PDF magic number, which rejects the HTML access
        or error pages UQAC serves with HTTP 200, and the body must stay under
        the size cap. The write is atomic: a temporary *.part file is renamed
        into place only after a complete, validated download.

        Lifted from .claude/skills/scopus/scripts/download_pdf.py so both
        skills validate a downloaded PDF the same way.

    Inputs:
        response (requests.Response): a streamed 200 response
        dest (str): final destination path

    Outputs:
        ok (bool): True when a valid PDF was written, False otherwise (no
        partial file is ever left behind).
    --------------------------------------------------------------------------
    """
    content_type = response.headers.get("Content-Type", "").lower()
    chunks = response.iter_content(CHUNK_BYTES)
    first = next(chunks, b"") or b""
    if not first.startswith(PDF_MAGIC):
        logger.warning("[UQAC-FORMS] not a PDF (magic mismatch, content-type=%s) - discarded",
                       content_type)
        return False

    tmp = f"{dest}.part"
    size = 0
    try:
        with open(tmp, "wb") as handle:
            size += len(first)
            handle.write(first)
            for chunk in chunks:
                if not chunk:
                    continue
                size += len(chunk)
                if size > MAX_PDF_BYTES:
                    logger.warning("[UQAC-FORMS] exceeds %d-byte cap - discarded", MAX_PDF_BYTES)
                    handle.close()
                    os.remove(tmp)
                    return False
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, dest)
        return True
    except OSError as exc:
        logger.warning("[UQAC-FORMS] write failed for %s: %s", dest, exc)
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        return False


def fetch_form(spec: FormSpec, cache_dir: str = DEFAULT_CACHE_DIR,
               force: bool = False) -> str | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Download one registered form into the cache. HTTPS only, with manual
        redirect handling so every hop is re-checked for the https scheme, then
        magic-byte and size validation before the file is kept. A cached file is
        returned untouched unless `force` is set, so repeated runs cost nothing.

    Inputs:
        spec (FormSpec): the registered form
        cache_dir (str): cache directory (created if absent)
        force (bool): re-download even when the file is already cached

    Outputs:
        path (str | None): cached path on success, None on any failure
    --------------------------------------------------------------------------
    """
    dest = cache_path(spec, cache_dir)
    if os.path.isfile(dest) and not force:
        logger.info("[UQAC-FORMS] cache hit for %s", spec.form_id)
        return dest
    os.makedirs(cache_dir, exist_ok=True)

    current = spec.url
    for _ in range(MAX_REDIRECTS + 1):
        if urlparse(current).scheme != "https":
            logger.warning("[UQAC-FORMS] refusing non-https URL: %s", current)
            return None
        try:
            response = requests.get(
                current, stream=True, timeout=REQUEST_TIMEOUT_S, allow_redirects=False)
        except requests.RequestException as exc:
            logger.error("[UQAC-FORMS] network error for %s: %s", spec.form_id, exc)
            return None

        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("Location", "")
            response.close()
            if not location:
                logger.warning("[UQAC-FORMS] redirect with no Location for %s", spec.form_id)
                return None
            current = urljoin(current, location)
            continue
        if response.status_code != 200:
            logger.error("[UQAC-FORMS] HTTP %s for %s", response.status_code, spec.form_id)
            response.close()
            return None
        try:
            return dest if _write_validated(response, dest) else None
        finally:
            response.close()

    logger.warning("[UQAC-FORMS] too many redirects for %s", spec.form_id)
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python .claude/skills/uqac-forms/scripts/Test/test_form_registry.py`
Expected: PASS, 10 tests.

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/uqac-forms/scripts/form_registry.py \
        .claude/skills/uqac-forms/scripts/Test/test_form_registry.py
git commit -m "feat(uqac-forms): https-only validated form downloader with atomic write"
```

---

## Task 3: Baseline fingerprint (SUPERSEDED - moved to TT-8)

**Files:**

- Modify: `.claude/skills/uqac-forms/scripts/form_registry.py`
- Test: `.claude/skills/uqac-forms/scripts/Test/test_form_registry.py`
- Modify: `.gitignore`

**Interfaces:**

- Consumes: `fetch_form`, `sha256_file`, `cache_path` from Task 2.
- Produces:
  - `load_baseline(path: str = BASELINE_PATH) -> dict[str, dict[str, Any]]` (empty dict when absent).
  - `save_baseline(data: dict[str, dict[str, Any]], path: str = BASELINE_PATH) -> None`.
  - `record_baseline(spec: FormSpec, cache_dir: str, baseline: dict) -> dict[str, Any]` returning the entry `{sha256, bytes, url, captured_at}` and mutating `baseline` in place.

- [ ] **Step 1: Write the failing test**

Append to `.claude/skills/uqac-forms/scripts/Test/test_form_registry.py`, above the `if __name__` block:

```python
class TestBaseline(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = os.path.join(self.tmp.name, "cache")
        self.baseline_path = os.path.join(self.tmp.name, "baseline.json")
        self.spec = form_registry.FormSpec(
            form_id="mth-plan-travail", title="Plan de travail",
            url="https://www.uqac.ca/de-docs/mth-formulaires/1-plan-travail.pdf",
            office="decanat", source="https://www.uqac.ca/decanat/mth-formulaires/",
            description="")
        self._real_get = form_registry.requests.get
        form_registry.requests.get = lambda *a, **k: _FakeResponse(b"%PDF-1.7\nv1\n%%EOF")

    def tearDown(self) -> None:
        form_registry.requests.get = self._real_get
        self.tmp.cleanup()

    def test_missing_baseline_file_loads_as_empty(self) -> None:
        self.assertEqual(form_registry.load_baseline(self.baseline_path), {})

    def test_record_then_load_round_trips(self) -> None:
        baseline: dict = {}
        entry = form_registry.record_baseline(self.spec, self.cache, baseline)
        self.assertEqual(len(entry["sha256"]), 64)
        self.assertEqual(entry["bytes"], len(b"%PDF-1.7\nv1\n%%EOF"))
        self.assertEqual(entry["url"], self.spec.url)
        form_registry.save_baseline(baseline, self.baseline_path)
        self.assertEqual(
            form_registry.load_baseline(self.baseline_path)["mth-plan-travail"]["sha256"],
            entry["sha256"],
        )

    def test_recording_twice_refreshes_the_entry_in_place(self) -> None:
        baseline: dict = {}
        form_registry.record_baseline(self.spec, self.cache, baseline)
        form_registry.record_baseline(self.spec, self.cache, baseline)
        self.assertEqual(len(baseline), 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python .claude/skills/uqac-forms/scripts/Test/test_form_registry.py`
Expected: FAIL with `AttributeError: module 'form_registry' has no attribute 'load_baseline'`.

- [ ] **Step 3: Write the minimal implementation**

Append to `.claude/skills/uqac-forms/scripts/form_registry.py`:

```python
def load_baseline(path: str = BASELINE_PATH) -> dict[str, dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the recorded fingerprints. A missing file is not an error: it is
        the state before any baseline has been captured.

    Inputs:
        path (str): path to registry/baseline.json

    Outputs:
        baseline (dict): {form_id: {sha256, bytes, url, captured_at}}
    --------------------------------------------------------------------------
    """
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        return json.load(handle) or {}


def save_baseline(data: dict[str, dict[str, Any]], path: str = BASELINE_PATH) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Persist the fingerprints, sorted by form id so a diff of this file
        stays readable in review.

    Inputs:
        data (dict): baseline mapping
        path (str): destination path (parent directory created if absent)

    Outputs:
        none
    --------------------------------------------------------------------------
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")


def record_baseline(spec: FormSpec, cache_dir: str,
                    baseline: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Download one form (forced, so a stale cache entry can never be recorded
        as the current truth) and store its fingerprint in the baseline mapping.

    Inputs:
        spec (FormSpec): the registered form
        cache_dir (str): cache directory
        baseline (dict): mapping mutated in place

    Outputs:
        entry (dict): {sha256, bytes, url, captured_at}

    Raises:
        RuntimeError when the download fails, so a silent gap is impossible.
    --------------------------------------------------------------------------
    """
    path = fetch_form(spec, cache_dir, force=True)
    if path is None:
        raise RuntimeError(f"could not download {spec.form_id} from {spec.url}")
    entry = {
        "sha256": sha256_file(path),
        "bytes": os.path.getsize(path),
        "url": spec.url,
        "captured_at": datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0).isoformat(),
    }
    baseline[spec.form_id] = entry
    return entry
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python .claude/skills/uqac-forms/scripts/Test/test_form_registry.py`
Expected: PASS, 13 tests.

- [ ] **Step 5: Ignore the PDF cache**

Append to `.gitignore`:

```
# uqac-forms: downloaded official PDFs are cached, never committed
out/uqac-forms/cache/
```

- [ ] **Step 6: Commit**

```bash
git add .claude/skills/uqac-forms/scripts/form_registry.py \
        .claude/skills/uqac-forms/scripts/Test/test_form_registry.py .gitignore
git commit -m "feat(uqac-forms): SHA-256 baseline capture and persistence"
```

---

## Task 4: Drift check and stale-map marking (SUPERSEDED - moved to TT-8)

**Files:**

- Modify: `.claude/skills/uqac-forms/scripts/form_registry.py`
- Test: `.claude/skills/uqac-forms/scripts/Test/test_form_registry.py`

**Interfaces:**

- Consumes: `record_baseline`, `load_baseline`, `fetch_form`, `sha256_file` from Task 3.
- Produces (all consumed by RT-2 and RT-3):
  - `class StaleMapError(RuntimeError)`.
  - `map_path(form_id: str, maps_dir: str = MAPS_DIR) -> str` returning `<maps_dir>/<form_id>.json`.
  - `map_status(form_id: str, maps_dir: str = MAPS_DIR) -> str` returning `"missing"`, `"ok"`, or `"stale"`.
  - `mark_map_stale(form_id: str, reason: str, maps_dir: str = MAPS_DIR) -> bool` setting `status="stale"` and `stale_reason=reason` on the map file; returns False when no map exists.
  - `require_fresh_map(form_id: str, maps_dir: str = MAPS_DIR) -> None` raising `StaleMapError` unless the status is `"ok"`.
  - `check_drift(spec, baseline, cache_dir, differ=None, maps_dir=MAPS_DIR) -> dict[str, Any]` returning `{form_id, changed: bool, old_sha, new_sha, field_diff}`. `differ` is `Callable[[str, str], dict] | None`, called as `differ(form_id, downloaded_pdf_path)` only when the hash changed; RT-2 passes `field_map.diff_against_map`.
  - The field-map file contract every unit shares: a JSON object with `form_id: str`, `status: "ok" | "stale"`, `fields: list[dict]`, and optional `stale_reason: str`. RT-2 populates `fields`.

- [ ] **Step 1: Write the failing test**

Append to `.claude/skills/uqac-forms/scripts/Test/test_form_registry.py`, above the `if __name__` block:

```python
class TestDrift(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = os.path.join(self.tmp.name, "cache")
        self.maps = os.path.join(self.tmp.name, "maps")
        os.makedirs(self.maps, exist_ok=True)
        self.spec = form_registry.FormSpec(
            form_id="mth-inscription-sujet", title="Inscription du sujet",
            url="https://www.uqac.ca/de-docs/mth-formulaires/1-formulaire-inscription-sujet.pdf",
            office="decanat", source="https://www.uqac.ca/decanat/mth-formulaires/",
            description="")
        self._real_get = form_registry.requests.get
        self._serve(b"%PDF-1.7\nversion-one\n%%EOF")
        with open(form_registry.map_path(self.spec.form_id, self.maps), "w", encoding="utf-8") as h:
            json.dump({"form_id": self.spec.form_id, "status": "ok", "fields": []}, h)

    def tearDown(self) -> None:
        form_registry.requests.get = self._real_get
        self.tmp.cleanup()

    def _serve(self, body: bytes) -> None:
        form_registry.requests.get = lambda *a, **k: _FakeResponse(body)

    def test_no_drift_when_the_bytes_are_unchanged(self) -> None:
        baseline: dict = {}
        form_registry.record_baseline(self.spec, self.cache, baseline)
        result = form_registry.check_drift(self.spec, baseline, self.cache, maps_dir=self.maps)
        self.assertFalse(result["changed"])
        self.assertEqual(result["old_sha"], result["new_sha"])
        self.assertEqual(form_registry.map_status(self.spec.form_id, self.maps), "ok")

    def test_drift_marks_the_map_stale(self) -> None:
        baseline: dict = {}
        form_registry.record_baseline(self.spec, self.cache, baseline)
        self._serve(b"%PDF-1.7\nversion-TWO-uqac-changed-it\n%%EOF")
        result = form_registry.check_drift(self.spec, baseline, self.cache, maps_dir=self.maps)
        self.assertTrue(result["changed"])
        self.assertNotEqual(result["old_sha"], result["new_sha"])
        self.assertEqual(form_registry.map_status(self.spec.form_id, self.maps), "stale")

    def test_the_injected_differ_runs_only_on_drift(self) -> None:
        calls: list = []

        def differ(form_id: str, pdf_path: str) -> dict:
            calls.append(form_id)
            return {"added": ["Text99"], "removed": [], "relocated": []}

        baseline: dict = {}
        form_registry.record_baseline(self.spec, self.cache, baseline)
        form_registry.check_drift(self.spec, baseline, self.cache, differ=differ, maps_dir=self.maps)
        self.assertEqual(calls, [])
        self._serve(b"%PDF-1.7\nversion-TWO\n%%EOF")
        result = form_registry.check_drift(self.spec, baseline, self.cache,
                                           differ=differ, maps_dir=self.maps)
        self.assertEqual(calls, [self.spec.form_id])
        self.assertEqual(result["field_diff"], {"added": ["Text99"], "removed": [], "relocated": []})

    def test_an_unknown_form_is_reported_as_new_not_as_drift(self) -> None:
        result = form_registry.check_drift(self.spec, {}, self.cache, maps_dir=self.maps)
        self.assertFalse(result["changed"])
        self.assertIsNone(result["old_sha"])

    def test_require_fresh_map_raises_on_a_stale_map(self) -> None:
        form_registry.mark_map_stale(self.spec.form_id, "sha256 changed", self.maps)
        with self.assertRaises(form_registry.StaleMapError):
            form_registry.require_fresh_map(self.spec.form_id, self.maps)

    def test_require_fresh_map_raises_on_a_missing_map(self) -> None:
        with self.assertRaises(form_registry.StaleMapError):
            form_registry.require_fresh_map("no-such-form", self.maps)

    def test_require_fresh_map_passes_on_a_fresh_map(self) -> None:
        form_registry.require_fresh_map(self.spec.form_id, self.maps)  # must not raise
```

Add `import json` to the test file imports if it is not already there.

- [ ] **Step 2: Run test to verify it fails**

Run: `python .claude/skills/uqac-forms/scripts/Test/test_form_registry.py`
Expected: FAIL with `AttributeError: module 'form_registry' has no attribute 'map_path'`.

- [ ] **Step 3: Write the minimal implementation**

Append to `.claude/skills/uqac-forms/scripts/form_registry.py`:

```python
class StaleMapError(RuntimeError):
    """Raised when a field map is missing or no longer describes its PDF."""


def map_path(form_id: str, maps_dir: str = MAPS_DIR) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Locate the field-map file of one form.

    Inputs:
        form_id (str): registry id
        maps_dir (str): directory holding the field maps

    Outputs:
        path (str): <maps_dir>/<form_id>.json
    --------------------------------------------------------------------------
    """
    return os.path.join(maps_dir, f"{form_id}.json")


def map_status(form_id: str, maps_dir: str = MAPS_DIR) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Report whether a form has a usable field map.

    Inputs:
        form_id (str): registry id
        maps_dir (str): directory holding the field maps

    Outputs:
        status (str): "missing", "stale", or "ok"
    --------------------------------------------------------------------------
    """
    path = map_path(form_id, maps_dir)
    if not os.path.isfile(path):
        return "missing"
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return "stale"
    return "ok" if data.get("status") == "ok" else "stale"


def mark_map_stale(form_id: str, reason: str, maps_dir: str = MAPS_DIR) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Flip a field map to stale and record why, so a human re-reviews the map
        before any further filling. Silent drift producing a wrong-looking
        official form is the failure mode this guards against.

    Inputs:
        form_id (str): registry id
        reason (str): human-readable cause, stored as stale_reason
        maps_dir (str): directory holding the field maps

    Outputs:
        marked (bool): True when a map existed and was updated
    --------------------------------------------------------------------------
    """
    path = map_path(form_id, maps_dir)
    if not os.path.isfile(path):
        logger.warning("[UQAC-FORMS] no field map to mark stale for %s", form_id)
        return False
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    data["status"] = "stale"
    data["stale_reason"] = reason
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    logger.error("[UQAC-FORMS] field map for %s marked stale: %s", form_id, reason)
    return True


def require_fresh_map(form_id: str, maps_dir: str = MAPS_DIR) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Gate every downstream operation (filling, signing, serving) on a field
        map that still describes its PDF.

    Inputs:
        form_id (str): registry id
        maps_dir (str): directory holding the field maps

    Outputs:
        none

    Raises:
        StaleMapError naming the form when the map is missing or stale.
    --------------------------------------------------------------------------
    """
    status = map_status(form_id, maps_dir)
    if status == "ok":
        return
    if status == "missing":
        raise StaleMapError(
            f"{form_id}: no field map. Run field_map.py dump {form_id} and complete the targets.")
    raise StaleMapError(
        f"{form_id}: field map is stale (the official PDF changed). "
        f"Re-run field_map.py dump {form_id}, re-review the targets, then set status back to ok.")


def check_drift(spec: FormSpec, baseline: dict[str, dict[str, Any]],
                cache_dir: str = DEFAULT_CACHE_DIR,
                differ: Callable[[str, str], dict] | None = None,
                maps_dir: str = MAPS_DIR) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Re-download one registered form and compare its SHA-256 with the
        recorded baseline. On a mismatch the field map is marked stale and, when
        a differ is supplied, the field set is re-dumped and diffed so the report
        names the added, removed, and relocated fields.

        `differ` is injected rather than imported so this module stays free of a
        PDF dependency and its tests stay offline. RT-2 passes
        field_map.diff_against_map.

    Inputs:
        spec (FormSpec): the registered form
        baseline (dict): recorded fingerprints, mutated in place with the new one
        cache_dir (str): cache directory
        differ (callable | None): differ(form_id, pdf_path) -> dict
        maps_dir (str): directory holding the field maps

    Outputs:
        result (dict): {form_id, changed, old_sha, new_sha, field_diff}

    Raises:
        RuntimeError when the form cannot be downloaded.
    --------------------------------------------------------------------------
    """
    old = (baseline.get(spec.form_id) or {}).get("sha256")
    path = fetch_form(spec, cache_dir, force=True)
    if path is None:
        raise RuntimeError(f"could not download {spec.form_id} from {spec.url}")
    new = sha256_file(path)

    result: dict[str, Any] = {
        "form_id": spec.form_id, "changed": False,
        "old_sha": old, "new_sha": new, "field_diff": None,
    }
    if old is None:
        # First sight of this form: record it, do not call it drift.
        logger.info("[UQAC-FORMS] %s has no baseline yet - recording", spec.form_id)
        record_baseline(spec, cache_dir, baseline)
        return result
    if old == new:
        return result

    result["changed"] = True
    if differ is not None:
        result["field_diff"] = differ(spec.form_id, path)
    mark_map_stale(spec.form_id, f"sha256 changed from {old[:12]} to {new[:12]}", maps_dir)
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python .claude/skills/uqac-forms/scripts/Test/test_form_registry.py`
Expected: PASS, 20 tests.

- [ ] **Step 5: Add the command-line interface**

Append to `.claude/skills/uqac-forms/scripts/form_registry.py`:

```python
def _selected(registry: dict[str, FormSpec], form_id: str | None,
              every: bool) -> list[FormSpec]:
    """Resolve the command-line selection to a list of specs (fail fast)."""
    if every:
        return list(registry.values())
    if not form_id:
        raise SystemExit("give a form id or --all")
    if form_id not in registry:
        raise SystemExit(f"unknown form id: {form_id} (try: form_registry.py list)")
    return [registry[form_id]]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="UQAC form registry, baseline, and drift check")
    sub = parser.add_subparsers(dest="mode", required=True)

    sub.add_parser("list", help="print the registered forms as JSON")
    sub.add_parser("status", help="print baseline and field-map status per form")

    for name, helptext in (("fetch", "download into the cache"),
                           ("baseline", "download and record the SHA-256 baseline"),
                           ("check", "re-download and report drift")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("form_id", nargs="?", default=None)
        p.add_argument("--all", action="store_true", help="apply to every registered form")
        p.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR)

    args = parser.parse_args()
    registry = load_registry()

    if args.mode == "list":
        print(json.dumps([vars(s) for s in registry.values()], indent=2, ensure_ascii=False))
        return

    if args.mode == "status":
        baseline = load_baseline()
        rows = [{
            "form_id": s.form_id,
            "baseline": "recorded" if s.form_id in baseline else "absent",
            "map": map_status(s.form_id),
        } for s in registry.values()]
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return

    specs = _selected(registry, args.form_id, args.all)

    if args.mode == "fetch":
        results = [{"form_id": s.form_id, "path": fetch_form(s, args.cache_dir)} for s in specs]
        print(json.dumps(results, indent=2, ensure_ascii=False))
        raise SystemExit(0 if all(r["path"] for r in results) else 1)

    baseline = load_baseline()
    if args.mode == "baseline":
        entries = {s.form_id: record_baseline(s, args.cache_dir, baseline) for s in specs}
        save_baseline(baseline)
        print(json.dumps(entries, indent=2, ensure_ascii=False))
        return

    drifted = [check_drift(s, baseline, args.cache_dir) for s in specs]
    save_baseline(baseline)
    print(json.dumps(drifted, indent=2, ensure_ascii=False))
    # Non-zero exit so a scheduled check fails loudly and can open an issue.
    raise SystemExit(1 if any(d["changed"] for d in drifted) else 0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Verify the interface end to end against the real forms**

Run (needs network):

```powershell
python .claude/skills/uqac-forms/scripts/form_registry.py list
python .claude/skills/uqac-forms/scripts/form_registry.py baseline --all
python .claude/skills/uqac-forms/scripts/form_registry.py check --all
```

Expected: `list` prints five forms; `baseline --all` writes `registry/baseline.json` with five 64-character digests; `check --all` prints `"changed": false` for all five and exits 0.

- [ ] **Step 7: Commit**

```bash
git add .claude/skills/uqac-forms/scripts/form_registry.py \
        .claude/skills/uqac-forms/scripts/Test/test_form_registry.py \
        .claude/skills/uqac-forms/registry/baseline.json
git commit -m "feat(uqac-forms): drift check, stale-map gate, and CLI"
```

---

## Task 5: SKILL.md, command wrapper, and repo wiring

**Files:**

- Create: `.claude/skills/uqac-forms/SKILL.md`
- Create: `.claude/commands/uqacform.md`
- Modify: `.claude/CLAUDE.md`, `README.md`, `Architecture.md`, `.claude/rules/workflows.md`, `.claude/rules/testing.md`

**Interfaces:**

- Consumes: the full `form_registry.py` CLI from Task 4.
- Produces: the `uqac-forms` skill, discoverable through the `.claude/CLAUDE.md` routing row and the `/uqacform` command.

- [ ] **Step 1: Write SKILL.md**

Create `.claude/skills/uqac-forms/SKILL.md`:

```markdown
---
name: uqac-forms
description: >
  Fill and cryptographically sign the official UQAC PDF forms (Decanat des
  etudes thesis forms, Service des ressources financieres travel and expense
  forms) from a structured profile. Keeps a registry of registered forms with a
  SHA-256 fingerprint per file and refuses to fill a form whose field map went
  stale after UQAC replaced the PDF. Trigger on: /uqacform, fill a UQAC form,
  formulaire UQAC, inscription du sujet, plan de travail, autorisation de depot,
  rapport de depenses, demande d'avance de voyage, sign a UQAC form, form drift
  check.
allowed-tools: [Read, Write, Edit, Bash, AskUserQuestion, Glob]
---

# uqac-forms - official UQAC form filling and signing

Registry-driven filling of the official UQAC PDF forms. All output goes to `out/`.

The registry is the guard: UQAC replaces a form at the same URL without notice,
so every registered form carries a SHA-256 fingerprint and every field map
carries a status. A map whose PDF changed is marked `stale`, and the filler
refuses to run against a stale map rather than emitting a wrong-looking official
document.

## Scope in this unit (RT-1)

Registry, download, baseline, and drift check. Field mapping (RT-2), filling
(RT-3), signing (RT-4), and the HTTP service (RT-5) land in the following units.

## Prerequisites

- `pip install -r .claude/skills/uqac-forms/scripts/requirements.txt`
- Network access to `www.uqac.ca` for the download and drift commands. Every
  other command is offline.

## Workflow

1. Inspect the registry:
   `python .claude/skills/uqac-forms/scripts/form_registry.py list`
2. Capture or refresh the fingerprints (first run, and after an approved form
   change): `python .claude/skills/uqac-forms/scripts/form_registry.py baseline --all`
3. Check for drift (weekly, or before any filling session):
   `python .claude/skills/uqac-forms/scripts/form_registry.py check --all`
   Exit code 1 means at least one form changed. The affected field maps are now
   `stale` and must be re-dumped and re-reviewed before use.
4. Report the status of every form:
   `python .claude/skills/uqac-forms/scripts/form_registry.py status`

## Adding a form

Add an entry to `registry/forms.yaml` with an `id`, `title`, https `url`,
`office`, `source`, and `description`, then run `baseline <id>`. Registry entries
are human-curated and never generated.

## Outputs

- `registry/baseline.json` - one fingerprint per form.
- `registry/maps/<form_id>.json` - field map, status `ok` or `stale`.
- `out/uqac-forms/cache/<form_id>.pdf` - the downloaded official PDF (gitignored).

## Unverified

Whether the Decanat des etudes and the Service des ressources financieres accept
a PAdES cryptographic signature is **not confirmed**. The signer (RT-4) is
pluggable with a self-signed development default so implementation proceeds; the
production certificate decision (UQAC PKI, or Notarius / ConsignO) is open and
someone must ask both offices.
```

- [ ] **Step 2: Write the command wrapper**

Create `.claude/commands/uqacform.md`:

```markdown
# Fill and check an official UQAC form

Thin wrapper over the `uqac-forms` skill. Read `.claude/skills/uqac-forms/SKILL.md`
and follow its workflow. The registry is the guard: a form whose PDF changed at
the same URL leaves its field map `stale`, and nothing may be filled from a stale
map until a human re-reviews it.

Procedure:

1. Resolve the intent from `$ARGUMENTS`: a form id (for example
   `srf-rapport-depenses`), the word `check` for a drift pass over every
   registered form, or `list` for the registry.
2. Run the matching command:
   ```
   python ".claude/skills/uqac-forms/scripts/form_registry.py" list
   python ".claude/skills/uqac-forms/scripts/form_registry.py" check --all
   python ".claude/skills/uqac-forms/scripts/form_registry.py" status
   ```
3. If `check` exits 1, name every drifted form, show its old and new SHA-256
   prefix, and state plainly that its field map is now stale and must be
   re-dumped and re-reviewed before any filling.

Report at the end: the forms inspected, the drift verdict per form, and the field
map status per form.

Respond in French unless the active file is in English.

$ARGUMENTS
```

- [ ] **Step 3: Add the routing row (critical, sole discoverability path)**

In `.claude/CLAUDE.md`, in the "Tooling - when to reach for what" table, add this row directly after the `geolocalisation` row:

```markdown
| Fill and sign an official UQAC form (Decanat thesis forms, SRF travel and expense forms) from a profile; keep a fingerprinted registry that refuses a form whose PDF UQAC silently replaced | `uqac-forms` skill | `/uqacform` |
```

- [ ] **Step 4: Update README.md**

Five edits:

1. Line 48: `The repo ships **11 skills**, **16 agents**, and **21 commands**.` becomes `The repo ships **12 skills**, **16 agents**, and **22 commands**.`
2. Line 269: `Skills bundle scripts and references the agents reuse. Eleven ship in this repo.` becomes `Skills bundle scripts and references the agents reuse. Twelve ship in this repo.`
3. In the skills table, after the `recommendation-letter` row, add:

```markdown
| `uqac-forms` | Fill and sign the official UQAC PDF forms from a structured profile. A human-curated registry carries one SHA-256 fingerprint per form; a drift check re-downloads each form, marks the field map `stale` when the bytes changed, and the filler refuses to run against a stale map. | `/uqacform`, `.claude/skills/uqac-forms/SKILL.md` |
```

4. After the `### recommendation-letter` subsection, add:

```markdown
### `uqac-forms` - official UQAC form filling and signing

Registry-driven filling of the official UQAC forms (Decanat des etudes thesis
forms, Service des ressources financieres travel and expense forms). Every
registered form carries a SHA-256 fingerprint, because UQAC replaces a form at
the same URL without notice; a drift check marks the affected field map `stale`
and the filler refuses to produce an official-looking document from it.

- `.claude/skills/uqac-forms/SKILL.md`
- `.claude/skills/uqac-forms/registry/forms.yaml` - human-curated form list
- `.claude/skills/uqac-forms/scripts/form_registry.py` - download, baseline, drift check
- `.claude/skills/uqac-forms/scripts/Test/test_form_registry.py` - offline unit tests
```

5. In the Prerequisites table, after the `pdflatex` row, add:

```markdown
| `pip install -r .claude/skills/uqac-forms/scripts/requirements.txt` | `uqac-forms` skill: `requests` and `PyYAML` for the registry and drift check (`pypdf` and `pyhanko` join at RT-2 and RT-4) |
```

6. In the Commands table, after the `/recommendation-letter` row, add:

```markdown
| `/uqacform` | Inspect the UQAC form registry, capture the SHA-256 baseline, or run the drift check that marks a changed form's field map stale. | Optional - form id, `check`, or `list` |
```

7. In the File-Locations tree: change `├── commands\ (21 commands)` to `(22 commands)`, add `├── uqacform.md` next to `└── recommendation-letter.md` (and fix the `└──`), change `└── skills\ (11 skills)` to `(12 skills)`, and append after the `recommendation-letter` skill entry (moving its `└──` up):

```
        └── uqac-forms\SKILL.md              (+ scripts\form_registry.py,
                           Test\test_form_registry.py; registry\forms.yaml)
```

8. Update TODO item 3 to record the decision:

```markdown
3- Thesis-Tracker: full UI/UX with user login, database, to fill paperworks, forms, track paper submission process, manage mindmap to create new paper ideas, end of 2026. **Decided 2026-07-29:** ThesisTracker stays the system of record (Plane rejected, its Community edition cannot express the per-row ownership ThesisTracker already tests); mindmaps stay on markmap (Graphify rejected, it is a code-first tool); n8n is deferred to Phase 3 behind explicit entry criteria; the form engine is this repo's `uqac-forms` skill plus a containerized Python service, converging on institutional Docker rather than Vercel.
```

- [ ] **Step 5: Update Architecture.md**

Two edits to the Layer 1 mermaid graph:

1. In `subgraph CMD`, after `c10["/litupdate"]`, add:

```
    c11["/uqacform"]
```

2. In `subgraph SK`, after `s9`, add:

```
    s10["uqac-forms<br/>form_registry.py"]
```

3. In the edge list, next to the existing `c8 --> s8` direct command-to-skill edge (the `geolocalisation` precedent), add:

```
  c11 --> s10
```

4. In the prose that follows the diagram, extend the sentence naming `geolocalisation` as the skill a command drives directly, so it reads that `geolocalisation` and `uqac-forms` are the two such skills, and note that `uqac-forms` consumes none of the shared academic skills; it reuses only the validation contract of the `scopus` skill's `download_pdf.py`.

- [ ] **Step 6: Update the rules files**

In `.claude/rules/workflows.md`, in the "Research and writing flows" table, after the `/recommendation-letter` row, add:

```markdown
| Fill or drift-check an official UQAC form | `/uqacform` | `uqac-forms` skill | Registry status, SHA-256 baseline, drift verdict; filled and signed PDF once RT-3/RT-4 land |
```

In `.claude/rules/testing.md`, in the offline test list, add:

```powershell
python .claude/skills/uqac-forms/scripts/Test/test_form_registry.py   # registry parse, validated download, baseline, drift + stale gate
```

and add `uqac-forms` to the ResearchTools script-surface paragraph: `form_registry.py` (registry, validated download, SHA-256 baseline, drift check marking a field map stale; offline tests patch `requests.get`).

- [ ] **Step 7: Audit the dependencies**

Run:

```powershell
pip-audit -r .claude/skills/uqac-forms/scripts/requirements.txt --strict
```

Expected: no vulnerabilities. If a CVE is reported, bump to the fixed version, cite the `CVE-YYYY-NNNNN` identifier in a comment above the pin, and re-run.

- [ ] **Step 8: Regenerate the mirrors**

Run:

```powershell
.\install.ps1 -Profile engineering
```

Then verify the wiring:

```bash
rtk grep -n "uqac-forms\|uqacform" .claude/CLAUDE.md README.md Architecture.md \
  .github/copilot-instructions.md .github/prompts/ .claude/rules/
```

Expected: the routing row, the README entries, the Architecture nodes, the workflows row, and a generated `.github/prompts/uqacform.prompt.md`.

- [ ] **Step 9: Run the full offline suite (no regression)**

```powershell
python .claude/skills/uqac-forms/scripts/Test/test_form_registry.py
python .claude/skills/scopus/scripts/Test/test_download_pdf.py
python .claude/skills/scopus/scripts/Test/test_browser_fetch.py
python .claude/skills/scopus/scripts/Test/test_bib_batch.py
python .claude/skills/scopus/scripts/Test/test_litreview_update.py
python .claude/skills/extract-statistic/scripts/Test/test_section_scan.py
```

Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add .claude README.md Architecture.md .github .opencode .continue
git commit -m "feat(uqac-forms): SKILL.md, /uqacform command, and full repo wiring"
```

---

## Interfaces published by RT-1

Every later unit consumes these from `.claude/skills/uqac-forms/scripts/form_registry.py`:

| Name | Signature | Consumed by |
|---|---|---|
| `FormSpec` | `FormSpec(form_id, title, url, office, source, description)` | RT-2, RT-3, RT-5 |
| `load_registry` | `load_registry(path: str = REGISTRY_PATH) -> dict[str, FormSpec]` | RT-2, RT-3, RT-5 |
| `fetch_form` | `fetch_form(spec: FormSpec, cache_dir: str, force: bool = False) -> str \| None` | RT-2, RT-3 |
| `cache_path` | `cache_path(spec: FormSpec, cache_dir: str) -> str` | RT-2, RT-3 |
| `sha256_file` | `sha256_file(path: str) -> str` | RT-2, RT-5 |
| `map_path` | `map_path(form_id: str, maps_dir: str = MAPS_DIR) -> str` | RT-2, RT-3 |
| `map_status` | `map_status(form_id: str, maps_dir: str = MAPS_DIR) -> str` | RT-2, RT-5 |
| `mark_map_stale` | `mark_map_stale(form_id: str, reason: str, maps_dir: str = MAPS_DIR) -> bool` | RT-2 |
| `require_fresh_map` | `require_fresh_map(form_id: str, maps_dir: str = MAPS_DIR) -> None`, raises `StaleMapError` | RT-3, RT-4, RT-5 |
| `check_drift` | `check_drift(spec, baseline, cache_dir, differ=None, maps_dir=MAPS_DIR) -> dict` | RT-2 (supplies `differ`) |
| `StaleMapError` | `class StaleMapError(RuntimeError)` | RT-3, RT-5 |
| `DEFAULT_CACHE_DIR`, `MAPS_DIR`, `BASELINE_PATH`, `REGISTRY_PATH` | module constants | RT-2, RT-3, RT-5 |

Field-map file contract, honoured by every unit: a JSON object with `form_id: str`, `status: "ok" | "stale"`, `fields: list[dict]`, and optional `stale_reason: str`.

---

## Acceptance

```powershell
python .claude/skills/uqac-forms/scripts/Test/test_form_registry.py
python .claude/skills/uqac-forms/scripts/form_registry.py check --all   # network; expects no drift, exit 0
pip-audit -r .claude/skills/uqac-forms/scripts/requirements.txt --strict
.\install.ps1 -Profile engineering
```

Plus the five existing offline suites listed in `.claude/rules/testing.md`, which must stay green.

---

## Task 6: Documentation and the pull request

Run this after the acceptance block above passes. It is the last task of the unit,
and it is what makes the work reviewable by someone who was not here.

**Files:**

- Modify: `README.md`
- Modify: `Architecture.md`
- Modify: `NEW_ARCHITECTURE.md`

**Interfaces:**

- Consumes: the finished implementation of every task above.
- Produces: the inventories a reader needs, and one pull request per unit so nothing
  reaches `main` unreviewed.

- [ ] **Step 1: Update `README.md`**

Task 5 already covers the whole README change for this unit: the skill count in
three places, the skills-table row, the `### uqac-forms` subsection, the
Prerequisites rows, the File-Locations tree entry, the command count, the
`/uqacform` row, and the TODO item 3 decision note.

Here, only verify it: re-read the six edits of Task 5 Step 4 and confirm each
landed. Do not duplicate them.

```bash
rtk grep -c "12 skills\|22 commands\|uqac-forms\|uqacform" README.md
```

Expected: a non-zero count for each. A zero means Task 5 Step 4 was skipped.

- [ ] **Step 2: Update `Architecture.md`**

Task 5 Step 5 already covers it: the `s10` node in the `SK` subgraph, the `c11`
node in `CMD`, the direct `c11 --> s10` command-to-skill edge, the inventory
counts, and the prose naming `uqac-forms` as the second skill a command drives
directly.

Here, only verify: render the Layer 1 mermaid graph and confirm the new nodes and
the edge appear, and that the counts match the README.

- [ ] **Step 3: Update `NEW_ARCHITECTURE.md`**

`NEW_ARCHITECTURE.md` is committed identically to `main` in both ResearchTools and
ThesisTracker. Edit only what this unit owns, and keep the wording identical in both
checkouts so the two copies never drift.

1. In the section 9 unit table, append ` Delivered <YYYY-MM-DD>.` to the **RT-1** row's
   deliverable cell.
2. Section 6 (the drift guard state diagram) describes what this unit implements. Read it
   against the delivered `form_registry.py` and correct the diagram if the states or the
   transitions differ. The diagram is the contract RT-2 and RT-3 rely on.
3. The file opens with `**Status: planned, not implemented.**` That line stops being true
   the moment any unit lands. Replace it with
   `**Status: in progress. <n> of 14 units delivered.**` and keep the count correct.

The change must land in both repositories. After committing it here, copy the same file
into the other checkout and open a second, documentation-only pull request there, or fold
it into that repository's next unit pull request. Verify the two copies match:

```bash
git -C "<path to ResearchTools>" show main:NEW_ARCHITECTURE.md | sha256sum
git -C "<path to ThesisTracker>" show main:NEW_ARCHITECTURE.md | sha256sum
```

Expected: the two digests are equal.

- [ ] **Step 4: Verify every relative link resolves**

```bash
grep -ohE "\]\([^)#][^)]*\)" README.md Architecture.md NEW_ARCHITECTURE.md \
  | sed 's/.*](//; s/)$//' | grep -v "^http" | sort -u \
  | while read -r f; do [ -e "$f" ] || echo "BROKEN: $f"; done
```

Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add README.md Architecture.md NEW_ARCHITECTURE.md
git commit -m "docs(uqac-forms): record RT-1 in the inventories"
```

- [ ] **Step 6: Open the pull request**

`gh` is **not installed** on this machine, and `GITHUB_TOKEN` carries `read:user` only,
so neither the CLI nor that token can open a pull request. Do not try to install `gh`.
The OAuth token in the Windows Credential Manager has `repo` scope and is sufficient.
Retrieve it per command: never write it to a file, never echo it, never commit it.

```bash
git push -u origin feat/uqac-forms-registry

TOK=$(printf "protocol=https\nhost=github.com\n\n" | git credential fill | sed -n 's/^password=//p')
curl -s -X POST https://api.github.com/repos/LARi-UQAC/ResearchTools/pulls \
  -H "Authorization: Bearer $TOK" \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  --data-binary @pr-body.json
```

Write `pr-body.json` to the scratchpad first, never into the repository:

```json
{
  "title": "[RT-1] uqac-forms skill: registry and drift detection",
  "head": "feat/uqac-forms-registry",
  "base": "main",
  "body": "Closes #4\n\n<what the unit delivers, in three or four lines>\n\n**Depends on.** nothing. This is the first unit of the ResearchTools chain.\n\n**Acceptance run.** <paste the commands from the acceptance block and their real result, not a summary>\n\n**Reviewer must check by hand.** <the manual verification steps of this plan, or 'none'>"
}
```

If a permission classifier blocks the command that reads the token, open the pull request
in the browser instead and paste the same title and body:

```
https://github.com/LARi-UQAC/ResearchTools/compare/main...feat/uqac-forms-registry?expand=1
```

Then delete `pr-body.json` from the scratchpad.

**Do not merge your own pull request.** Merging to `main` is the human gate. RT-2 is blocked behind this unit; say so in the body.

- [ ] **Step 7: Report**

State the pull request URL, the acceptance commands you ran with their real output, and
anything you could not verify. A test you did not run is not a test that passed.
