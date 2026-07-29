# RT-2: UQAC Form Field Map and Profile Vocabulary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn each registered UQAC PDF into a reviewable field map: dump every AcroForm widget with its type, page, and checkbox on-states, let a human bind each widget to one key of a shared profile vocabulary, and validate that the binding still holds.

**Architecture:** `field_map.py` reads the cached PDF with `pypdf`, walks the page annotations rather than the flat field dictionary so page numbers, rectangles, and per-widget appearance streams are available, and writes `registry/maps/<form_id>.json` in the contract RT-1 published (`form_id`, `status`, `fields`, optional `stale_reason`). Every entry carries `target: "TODO"` until a human completes it. One profile vocabulary (`registry/schema.yaml`, namespaces `student`, `professor`, `project`, `trip`) is written once and reused by every form, so `student.code_permanent` lands in `code permanent` on a Decanat form and `no_matricule` on an SRF form. `diff_against_map` is exported and injected into RT-1's `check_drift`, closing the drift loop with a field-level report.

**Tech Stack:** Python 3.13, `pypdf` (BSD-3), `PyYAML`, standard library. No PyMuPDF: it is AGPL-3.0 and this skill ships inside a deployable container.

## Global Constraints

- Definition files (agents, skills, commands) are **English-only**. French appears only in emitted deliverable strings and the repo-root `CLAUDE.md`.
- Style hygiene in any produced text: no em dash, no double or triple dash, straight quotes only, no zero-width or Unicode-tag characters, no single-character ellipsis, no leftover `*` or `#`.
- Python naming: classes `PascalCase`, functions and module variables `snake_case`, private `_snake_case`, constants `UPPER_SNAKE_CASE`. Type hints in every signature.
- Docstrings use the repo's extended `Purpose: / Inputs: / Outputs:` block format.
- Logging: `logging.getLogger(__name__)`, messages prefixed `[UQAC-FORMS]`.
- **Field names are opaque byte-exact keys. Never normalize, lowercase, strip accents, or trim them.** They are not clean UTF-8: the probed forms carry `Nom`, a mojibake `Prenom`, `code permanent` (Decanat) against `Code permanent` (plan de travail) against `no_matricule` (SRF), plus generic `Text1`, `Text24`, and `TachesAEffectuerRow1`.
- **Checkbox on-states are read from each widget's `/AP /N` dictionary, never assumed to be `/Yes`.** The SRF forms use per-checkbox export values.
- The generated map is a **human-reviewed draft**: it carries a confidence-equivalent (`target: "TODO"` until bound) and per-field provenance (page, rect, type, on-states), and a human decision always wins. This is the same contract as the `geolocalisation` skill.
- Dependencies pinned exactly in `.claude/skills/uqac-forms/scripts/requirements.txt`, then `pip-audit -r ... --strict`.
- Offline tests only. Test PDFs are generated in the test itself with `pypdf`, never downloaded and never committed.
- All fixtures synthetic. No real profile is ever committed.

**Depends on:** RT-1 (`feat/uqac-forms-registry`). Branch from RT-1's branch or rebase onto it once it lands.

---

## File Structure

**New files**

- `.claude/skills/uqac-forms/scripts/field_map.py` - widget dump, map scaffold, validation, diff.
- `.claude/skills/uqac-forms/registry/schema.yaml` - the profile vocabulary (human-curated).
- `.claude/skills/uqac-forms/scripts/Test/test_field_map.py` - offline unit tests.

**Modified files**

- `.claude/skills/uqac-forms/scripts/requirements.txt` - add the `pypdf` pin.
- `.claude/skills/uqac-forms/scripts/form_registry.py` - wire `field_map.diff_against_map` as the default differ in the `check` CLI path only (the `check_drift` signature does not change).
- `.claude/skills/uqac-forms/SKILL.md` - document the dump / review / validate workflow.
- `.claude/rules/testing.md` - add the new offline test command.

---

## Interfaces consumed from RT-1

From `.claude/skills/uqac-forms/scripts/form_registry.py`:

- `FormSpec(form_id, title, url, office, source, description)`
- `load_registry(path: str = REGISTRY_PATH) -> dict[str, FormSpec]`
- `fetch_form(spec: FormSpec, cache_dir: str, force: bool = False) -> str | None`
- `cache_path(spec: FormSpec, cache_dir: str) -> str`
- `map_path(form_id: str, maps_dir: str = MAPS_DIR) -> str`
- `map_status(form_id: str, maps_dir: str = MAPS_DIR) -> str`
- `mark_map_stale(form_id: str, reason: str, maps_dir: str = MAPS_DIR) -> bool`
- `DEFAULT_CACHE_DIR`, `MAPS_DIR` module constants
- Field-map file contract: JSON object with `form_id: str`, `status: "ok" | "stale"`, `fields: list[dict]`, optional `stale_reason: str`.

---

## Task 1: Widget dump

**Files:**

- Create: `.claude/skills/uqac-forms/scripts/field_map.py`
- Modify: `.claude/skills/uqac-forms/scripts/requirements.txt`
- Test: `.claude/skills/uqac-forms/scripts/Test/test_field_map.py`

**Interfaces:**

- Consumes: nothing from RT-1 in this task (pure PDF reading).
- Produces:
  - `dump_widgets(pdf_path: str) -> list[dict[str, Any]]`, one entry per widget:
    `{"name": str, "name_hex": str, "type": str, "page": int, "rect": [float, float, float, float], "on_states": list[str], "readonly": bool}`.
    `type` is one of `"text"`, `"checkbox"`, `"radio"`, `"choice"`, `"signature"`, `"unknown"`. `page` is 1-based. `on_states` is empty for anything but a checkbox or radio.

- [ ] **Step 1: Write the failing test**

Create `.claude/skills/uqac-forms/scripts/Test/test_field_map.py`:

```python
"""
test_field_map.py - Offline unit tests for field_map.py.

No network and no committed fixture: each test builds its own AcroForm PDF in a
temporary directory with pypdf, so the suite runs anywhere pypdf is installed.
Run with the project Python:
    python .claude/skills/uqac-forms/scripts/Test/test_field_map.py
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import field_map  # noqa: E402

from pypdf import PdfWriter  # noqa: E402
from pypdf.generic import (  # noqa: E402
    ArrayObject, DictionaryObject, FloatObject, NameObject, TextStringObject,
)


def _widget(name: str, field_type: str, rect: tuple[float, float, float, float],
            on_states: list[str] | None = None) -> DictionaryObject:
    """Build one AcroForm widget annotation, on-states declared in /AP /N."""
    annot = DictionaryObject()
    annot.update({
        NameObject("/Type"): NameObject("/Annot"),
        NameObject("/Subtype"): NameObject("/Widget"),
        NameObject("/FT"): NameObject(field_type),
        NameObject("/T"): TextStringObject(name),
        NameObject("/Rect"): ArrayObject([FloatObject(v) for v in rect]),
    })
    if on_states is not None:
        normal = DictionaryObject()
        for state in on_states + ["Off"]:
            normal[NameObject(f"/{state}")] = DictionaryObject()
        appearance = DictionaryObject()
        appearance[NameObject("/N")] = normal
        annot[NameObject("/AP")] = appearance
    return annot


def make_form_pdf(path: str, widgets_per_page: list[list[DictionaryObject]]) -> str:
    """Write a multi-page AcroForm PDF carrying the given widgets."""
    writer = PdfWriter()
    for page_widgets in widgets_per_page:
        page = writer.add_blank_page(width=612, height=792)
        annots = ArrayObject()
        for widget in page_widgets:
            annots.append(writer._add_object(widget))
        page[NameObject("/Annots")] = annots
    writer.set_need_appearances_writer(True)
    with open(path, "wb") as handle:
        writer.write(handle)
    return path


class TestDumpWidgets(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.pdf = make_form_pdf(
            os.path.join(self.tmp.name, "form.pdf"),
            [
                [_widget("Nom", "/Tx", (10, 700, 200, 720)),
                 _widget("code permanent", "/Tx", (10, 670, 200, 690))],
                [_widget("Cheque_Payable_a", "/Tx", (10, 640, 200, 660)),
                 _widget("mode_transport", "/Btn", (10, 610, 30, 630), on_states=["Avion"])],
            ],
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_every_widget_is_returned(self) -> None:
        names = [w["name"] for w in field_map.dump_widgets(self.pdf)]
        self.assertEqual(names, ["Nom", "code permanent", "Cheque_Payable_a", "mode_transport"])

    def test_page_numbers_are_one_based(self) -> None:
        by_name = {w["name"]: w for w in field_map.dump_widgets(self.pdf)}
        self.assertEqual(by_name["Nom"]["page"], 1)
        self.assertEqual(by_name["Cheque_Payable_a"]["page"], 2)

    def test_field_names_are_never_normalized(self) -> None:
        names = [w["name"] for w in field_map.dump_widgets(self.pdf)]
        # "code permanent" keeps its space and its lowercase c; nothing is slugified.
        self.assertIn("code permanent", names)
        self.assertNotIn("code_permanent", names)
        self.assertNotIn("Code permanent", names)

    def test_name_hex_records_the_exact_bytes(self) -> None:
        by_name = {w["name"]: w for w in field_map.dump_widgets(self.pdf)}
        self.assertEqual(bytes.fromhex(by_name["Nom"]["name_hex"]).decode("utf-8"), "Nom")

    def test_checkbox_on_states_come_from_ap_n_and_exclude_off(self) -> None:
        by_name = {w["name"]: w for w in field_map.dump_widgets(self.pdf)}
        self.assertEqual(by_name["mode_transport"]["type"], "checkbox")
        self.assertEqual(by_name["mode_transport"]["on_states"], ["Avion"])

    def test_a_text_widget_has_no_on_states(self) -> None:
        by_name = {w["name"]: w for w in field_map.dump_widgets(self.pdf)}
        self.assertEqual(by_name["Nom"]["type"], "text")
        self.assertEqual(by_name["Nom"]["on_states"], [])

    def test_rect_is_preserved_for_relocation_detection(self) -> None:
        by_name = {w["name"]: w for w in field_map.dump_widgets(self.pdf)}
        self.assertEqual(by_name["Nom"]["rect"], [10.0, 700.0, 200.0, 720.0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python .claude/skills/uqac-forms/scripts/Test/test_field_map.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'field_map'`.

- [ ] **Step 3: Add the pypdf pin**

In `.claude/skills/uqac-forms/scripts/requirements.txt`, add under the existing pins:

```
pypdf==6.14.2
```

Then install and audit:

```powershell
pip install -r .claude/skills/uqac-forms/scripts/requirements.txt
pip-audit -r .claude/skills/uqac-forms/scripts/requirements.txt --strict
```

- [ ] **Step 4: Write the minimal implementation**

Create `.claude/skills/uqac-forms/scripts/field_map.py`:

```python
"""
field_map.py - Dump, bind, and validate the AcroForm field map of a registered
UQAC form.

A field map is the human-reviewed contract between one PDF's opaque widget names
and the shared profile vocabulary. It is generated as a scaffold with every
target set to TODO, completed once by a human, then validated on every run.

Field names are treated as opaque byte-exact keys: the probed UQAC forms carry
accented, space-bearing, and generic names that are not clean UTF-8, so nothing
here normalizes, lowercases, or trims them. Checkbox on-states are read from each
widget's /AP /N dictionary, never assumed to be /Yes, because the SRF forms use
per-checkbox export values.

Usage:
  python field_map.py dump     <form_id> [--cache-dir DIR] [--maps-dir DIR]
  python field_map.py validate <form_id> [--cache-dir DIR] [--maps-dir DIR]
  python field_map.py diff     <form_id> [--cache-dir DIR] [--maps-dir DIR]
  python field_map.py schema
"""

import argparse
import json
import logging
import os
from typing import Any

import yaml
from pypdf import PdfReader
from pypdf.generic import IndirectObject

import form_registry

logger = logging.getLogger(__name__)

_HERE = os.path.dirname(os.path.abspath(__file__))
_SKILL_ROOT = os.path.dirname(_HERE)
SCHEMA_PATH = os.path.join(_SKILL_ROOT, "registry", "schema.yaml")

# AcroForm field-type codes, mapped to the vocabulary the map file uses.
_FIELD_TYPES = {"/Tx": "text", "/Btn": "button", "/Ch": "choice", "/Sig": "signature"}


def _resolve(value: Any) -> Any:
    """Follow an indirect reference once, so callers always see a real object."""
    return value.get_object() if isinstance(value, IndirectObject) else value


def _qualified_name(annot: Any) -> str | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the fully qualified field name of a widget, walking /Parent so a
        widget that inherits its name from a parent field is reported under the
        same key the AcroForm dictionary uses.

    Inputs:
        annot (DictionaryObject): a /Widget annotation

    Outputs:
        name (str | None): dotted qualified name, or None when the widget and
        all of its parents are unnamed
    --------------------------------------------------------------------------
    """
    parts: list[str] = []
    node: Any = annot
    seen = 0
    while node is not None and seen < 32:  # cycle guard on a malformed file
        title = _resolve(node.get("/T"))
        if title is not None:
            parts.append(str(title))
        node = _resolve(node.get("/Parent"))
        seen += 1
    if not parts:
        return None
    return ".".join(reversed(parts))


def _name_hex(annot: Any) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Record the exact bytes of the widget's own /T entry, so a later reader
        can prove the key was never re-encoded on the way through this tool.

    Inputs:
        annot (DictionaryObject): a /Widget annotation

    Outputs:
        digest (str): hexadecimal encoding of the raw name bytes, "" when unnamed
    --------------------------------------------------------------------------
    """
    title = _resolve(annot.get("/T"))
    if title is None:
        return ""
    raw = getattr(title, "original_bytes", None)
    if raw is None:
        raw = str(title).encode("utf-8")
    return raw.hex()


def _on_states(annot: Any) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read a button widget's export values from its normal appearance
        dictionary (/AP /N). The on-state is whatever key is not /Off, and it is
        per-widget: the SRF forms do not use /Yes.

    Inputs:
        annot (DictionaryObject): a /Widget annotation

    Outputs:
        states (list[str]): on-state names without the leading slash, sorted
        for a stable map file; empty when the widget has no appearance states
    --------------------------------------------------------------------------
    """
    appearance = _resolve(annot.get("/AP"))
    if not appearance:
        return []
    normal = _resolve(appearance.get("/N"))
    if not hasattr(normal, "keys"):
        return []
    return sorted(str(k).lstrip("/") for k in normal.keys() if str(k) != "/Off")


def _widget_type(annot: Any, states: list[str]) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Classify a widget for the map file. /Btn splits into checkbox and radio
        on the /Ff radio flag (bit 16), because the two are filled differently.

    Inputs:
        annot (DictionaryObject): a /Widget annotation
        states (list[str]): its on-states, already extracted

    Outputs:
        kind (str): text | checkbox | radio | choice | signature | unknown
    --------------------------------------------------------------------------
    """
    node: Any = annot
    seen = 0
    field_type = None
    while node is not None and seen < 32:
        field_type = _resolve(node.get("/FT"))
        if field_type is not None:
            break
        node = _resolve(node.get("/Parent"))
        seen += 1
    kind = _FIELD_TYPES.get(str(field_type or ""), "unknown")
    if kind != "button":
        return kind
    flags = int(_resolve(annot.get("/Ff")) or 0)
    return "radio" if flags & (1 << 15) else "checkbox"


def dump_widgets(pdf_path: str) -> list[dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Enumerate every AcroForm widget of a PDF in page order, with the
        provenance a human needs to bind it: name, exact name bytes, type, page,
        rectangle, and on-states.

        Page annotations are walked rather than PdfReader.get_fields(), because
        the flat field dictionary loses the page number and the per-widget
        appearance streams the checkbox on-states live in.

    Inputs:
        pdf_path (str): path to a local PDF

    Outputs:
        widgets (list[dict]): {name, name_hex, type, page, rect, on_states,
        readonly}, in page then annotation order
    --------------------------------------------------------------------------
    """
    reader = PdfReader(pdf_path)
    widgets: list[dict[str, Any]] = []
    for page_index, page in enumerate(reader.pages, start=1):
        annots = _resolve(page.get("/Annots")) or []
        for ref in annots:
            annot = _resolve(ref)
            if str(_resolve(annot.get("/Subtype")) or "") != "/Widget":
                continue
            name = _qualified_name(annot)
            if name is None:
                continue
            states = _on_states(annot)
            rect = [float(v) for v in (_resolve(annot.get("/Rect")) or [0, 0, 0, 0])]
            flags = int(_resolve(annot.get("/Ff")) or 0)
            widgets.append({
                "name": name,
                "name_hex": _name_hex(annot),
                "type": _widget_type(annot, states),
                "page": page_index,
                "rect": rect,
                "on_states": states,
                "readonly": bool(flags & 1),
            })
    logger.info("[UQAC-FORMS] dumped %d widgets from %s", len(widgets), os.path.basename(pdf_path))
    return widgets
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python .claude/skills/uqac-forms/scripts/Test/test_field_map.py`
Expected: PASS, 7 tests.

- [ ] **Step 6: Commit**

```bash
git add .claude/skills/uqac-forms/scripts/field_map.py \
        .claude/skills/uqac-forms/scripts/requirements.txt \
        .claude/skills/uqac-forms/scripts/Test/test_field_map.py
git commit -m "feat(uqac-forms): AcroForm widget dump with byte-exact names and /AP /N on-states"
```

---

## Task 2: Profile vocabulary

**Files:**

- Create: `.claude/skills/uqac-forms/registry/schema.yaml`
- Modify: `.claude/skills/uqac-forms/scripts/field_map.py`
- Test: `.claude/skills/uqac-forms/scripts/Test/test_field_map.py`

**Interfaces:**

- Consumes: nothing.
- Produces:
  - `load_schema(path: str = SCHEMA_PATH) -> dict[str, dict[str, str]]`, namespace to key to description.
  - `schema_keys(schema: dict) -> set[str]`, the flat set of dotted keys such as `student.code_permanent`.
  - `resolve_target(profile: dict[str, Any], target: str) -> Any`, dotted lookup returning `None` when absent. **RT-3 consumes this to fill a form.**

- [ ] **Step 1: Write the failing test**

Append to `.claude/skills/uqac-forms/scripts/Test/test_field_map.py`, above the `if __name__` block:

```python
class TestSchema(unittest.TestCase):
    def test_the_shipped_schema_declares_the_four_namespaces(self) -> None:
        schema = field_map.load_schema()
        self.assertEqual(set(schema), {"student", "professor", "project", "trip"})

    def test_one_vocabulary_key_feeds_forms_that_name_it_differently(self) -> None:
        keys = field_map.schema_keys(field_map.load_schema())
        # Written once as student.code_permanent, it lands in "code permanent"
        # on the Decanat form and "no_matricule" on the SRF form.
        self.assertIn("student.code_permanent", keys)
        self.assertIn("student.nom", keys)
        self.assertIn("professor.nom", keys)
        self.assertIn("trip.destination", keys)

    def test_resolve_target_walks_the_dotted_path(self) -> None:
        profile = {"student": {"nom": "Tremblay", "code_permanent": "TREM12345678"}}
        self.assertEqual(field_map.resolve_target(profile, "student.nom"), "Tremblay")
        self.assertEqual(
            field_map.resolve_target(profile, "student.code_permanent"), "TREM12345678")

    def test_resolve_target_returns_none_for_an_absent_key(self) -> None:
        self.assertIsNone(field_map.resolve_target({"student": {}}, "student.nom"))
        self.assertIsNone(field_map.resolve_target({}, "trip.destination"))
        self.assertIsNone(field_map.resolve_target({"student": "flat"}, "student.nom"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python .claude/skills/uqac-forms/scripts/Test/test_field_map.py`
Expected: FAIL with `AttributeError: module 'field_map' has no attribute 'load_schema'`.

- [ ] **Step 3: Write the vocabulary**

Create `.claude/skills/uqac-forms/registry/schema.yaml`:

```yaml
# The profile vocabulary. One key is written once and lands in whatever the
# individual form happens to call it: student.code_permanent fills "code permanent"
# on the Decanat form, "Code permanent" on the plan de travail, and "no_matricule"
# on the SRF forms. Human-curated: never generated.
#
# Adding a key here is cheap; renaming one breaks every map that binds it, so
# prefer adding over renaming.
student:
  nom: "Family name as it appears on the UQAC record."
  prenom: "Given name."
  code_permanent: "UQAC permanent code, also the SRF matricule."
  courriel: "Institutional email address."
  telephone: "Contact telephone number."
  programme: "Program code and title, for example 3459 Doctorat en ingenierie."
  cycle: "2 for a master's, 3 for a doctorate."
  adresse: "Mailing address, one line."
  date_admission: "Admission date, ISO 8601 (YYYY-MM-DD)."

professor:
  nom: "Family name of the research director."
  prenom: "Given name of the research director."
  departement: "Department, for example Departement des sciences appliquees."
  courriel: "Institutional email address."
  codirecteur_nom: "Family name of the co-director, empty when there is none."
  codirecteur_prenom: "Given name of the co-director, empty when there is none."

project:
  titre: "Research subject title, as registered."
  resume: "Short description of the research subject."
  laboratoire: "Host laboratory, for example LAR.i."
  date_debut: "Start date, ISO 8601."
  date_depot_prevue: "Expected deposit date, ISO 8601."
  organisme_subvention: "Funding organism, for example MITACS, CRSNG, FRQNT."
  numero_dossier: "Grant or file number, for example IT43550."

trip:
  destination: "City and country of the mission."
  motif: "Purpose of the mission, for example conference presentation."
  date_depart: "Departure date, ISO 8601."
  date_retour: "Return date, ISO 8601."
  montant_demande: "Requested amount, in Canadian dollars, as a decimal string."
  mode_transport: "Transport mode, matching the form's own on-state vocabulary."
  code_budgetaire: "Budget code the expense is charged to."
  cheque_payable_a: "Payee name for the reimbursement cheque."
```

- [ ] **Step 4: Write the minimal implementation**

Append to `.claude/skills/uqac-forms/scripts/field_map.py`:

```python
def load_schema(path: str = SCHEMA_PATH) -> dict[str, dict[str, str]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Load the shared profile vocabulary: the namespaces and keys a field map
        may bind a widget to.

    Inputs:
        path (str): path to registry/schema.yaml

    Outputs:
        schema (dict): {namespace: {key: description}}

    Raises:
        FileNotFoundError when the schema is missing.
    --------------------------------------------------------------------------
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"profile schema not found: {path}")
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def schema_keys(schema: dict[str, dict[str, str]]) -> set[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Flatten the vocabulary to the dotted keys a map file may reference.

    Inputs:
        schema (dict): as returned by load_schema

    Outputs:
        keys (set[str]): for example {"student.nom", "trip.destination"}
    --------------------------------------------------------------------------
    """
    return {f"{ns}.{key}" for ns, keys in schema.items() for key in (keys or {})}


def resolve_target(profile: dict[str, Any], target: str) -> Any:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read one dotted vocabulary key out of a profile. A missing namespace,
        a missing key, or a non-mapping namespace all resolve to None so the
        caller reports an unfilled field rather than raising mid-fill.

    Inputs:
        profile (dict): the profile document
        target (str): dotted key, for example "student.code_permanent"

    Outputs:
        value (Any): the bound value, or None when the path does not resolve
    --------------------------------------------------------------------------
    """
    node: Any = profile
    for part in target.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
        if node is None:
            return None
    return node
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python .claude/skills/uqac-forms/scripts/Test/test_field_map.py`
Expected: PASS, 11 tests.

- [ ] **Step 6: Commit**

```bash
git add .claude/skills/uqac-forms/registry/schema.yaml \
        .claude/skills/uqac-forms/scripts/field_map.py \
        .claude/skills/uqac-forms/scripts/Test/test_field_map.py
git commit -m "feat(uqac-forms): shared profile vocabulary and dotted target resolution"
```

---

## Task 3: Map scaffold and validation

**Files:**

- Modify: `.claude/skills/uqac-forms/scripts/field_map.py`
- Test: `.claude/skills/uqac-forms/scripts/Test/test_field_map.py`

**Interfaces:**

- Consumes: `dump_widgets`, `load_schema`, `schema_keys` from Tasks 1 and 2; `map_path`, `MAPS_DIR` from RT-1.
- Produces:
  - `TODO_TARGET: str = "TODO"` module constant.
  - `build_scaffold(form_id: str, pdf_path: str) -> dict[str, Any]` returning the map document (`status` is `"stale"` until a human completes the targets and flips it).
  - `write_map(document: dict, maps_dir: str = MAPS_DIR) -> str` returning the written path.
  - `load_map(form_id: str, maps_dir: str = MAPS_DIR) -> dict[str, Any]`.
  - `validate_map(form_id: str, pdf_path: str, maps_dir: str = MAPS_DIR, schema_path: str = SCHEMA_PATH) -> list[str]` returning an empty list when the map is usable, otherwise one actionable message per problem.

- [ ] **Step 1: Write the failing test**

Append to `.claude/skills/uqac-forms/scripts/Test/test_field_map.py`, above the `if __name__` block:

```python
class TestScaffoldAndValidate(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.maps = os.path.join(self.tmp.name, "maps")
        os.makedirs(self.maps, exist_ok=True)
        self.pdf = make_form_pdf(
            os.path.join(self.tmp.name, "form.pdf"),
            [[_widget("Nom", "/Tx", (10, 700, 200, 720)),
              _widget("code permanent", "/Tx", (10, 670, 200, 690)),
              _widget("mode_transport", "/Btn", (10, 640, 30, 660), on_states=["Avion"])]],
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _bound_map(self) -> dict:
        doc = field_map.build_scaffold("srf-demande-avance-voyage", self.pdf)
        targets = {"Nom": "student.nom", "code permanent": "student.code_permanent",
                   "mode_transport": "trip.mode_transport"}
        for field in doc["fields"]:
            field["target"] = targets[field["name"]]
        doc["status"] = "ok"
        return doc

    def test_scaffold_marks_every_target_todo(self) -> None:
        doc = field_map.build_scaffold("srf-demande-avance-voyage", self.pdf)
        self.assertEqual({f["target"] for f in doc["fields"]}, {field_map.TODO_TARGET})

    def test_scaffold_is_not_usable_until_a_human_flips_it(self) -> None:
        doc = field_map.build_scaffold("srf-demande-avance-voyage", self.pdf)
        self.assertEqual(doc["status"], "stale")

    def test_scaffold_records_the_pdf_fingerprint_and_widget_count(self) -> None:
        doc = field_map.build_scaffold("srf-demande-avance-voyage", self.pdf)
        self.assertEqual(doc["widget_count"], 3)
        self.assertEqual(len(doc["source_sha256"]), 64)

    def test_write_then_load_round_trips(self) -> None:
        path = field_map.write_map(self._bound_map(), self.maps)
        self.assertTrue(os.path.isfile(path))
        loaded = field_map.load_map("srf-demande-avance-voyage", self.maps)
        self.assertEqual(len(loaded["fields"]), 3)

    def test_a_complete_map_validates_clean(self) -> None:
        field_map.write_map(self._bound_map(), self.maps)
        self.assertEqual(
            field_map.validate_map("srf-demande-avance-voyage", self.pdf, self.maps), [])

    def test_an_unbound_target_is_reported(self) -> None:
        doc = self._bound_map()
        doc["fields"][0]["target"] = field_map.TODO_TARGET
        field_map.write_map(doc, self.maps)
        errors = field_map.validate_map("srf-demande-avance-voyage", self.pdf, self.maps)
        self.assertEqual(len(errors), 1)
        self.assertIn("Nom", errors[0])

    def test_a_target_outside_the_vocabulary_is_reported(self) -> None:
        doc = self._bound_map()
        doc["fields"][0]["target"] = "student.invented_key"
        field_map.write_map(doc, self.maps)
        errors = field_map.validate_map("srf-demande-avance-voyage", self.pdf, self.maps)
        self.assertTrue(any("student.invented_key" in e for e in errors))

    def test_a_mapped_field_that_left_the_pdf_is_reported(self) -> None:
        doc = self._bound_map()
        doc["fields"].append({"name": "champ_disparu", "name_hex": "", "type": "text",
                              "page": 1, "rect": [0, 0, 0, 0], "on_states": [],
                              "readonly": False, "target": "student.courriel"})
        field_map.write_map(doc, self.maps)
        errors = field_map.validate_map("srf-demande-avance-voyage", self.pdf, self.maps)
        self.assertTrue(any("champ_disparu" in e for e in errors))

    def test_a_new_pdf_field_missing_from_the_map_is_reported(self) -> None:
        doc = self._bound_map()
        doc["fields"] = [f for f in doc["fields"] if f["name"] != "mode_transport"]
        field_map.write_map(doc, self.maps)
        errors = field_map.validate_map("srf-demande-avance-voyage", self.pdf, self.maps)
        self.assertTrue(any("mode_transport" in e for e in errors))

    def test_a_checkbox_bound_to_an_unknown_on_state_is_reported(self) -> None:
        doc = self._bound_map()
        for field in doc["fields"]:
            if field["name"] == "mode_transport":
                field["on_states"] = ["Train"]
        field_map.write_map(doc, self.maps)
        errors = field_map.validate_map("srf-demande-avance-voyage", self.pdf, self.maps)
        self.assertTrue(any("on-state" in e for e in errors))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python .claude/skills/uqac-forms/scripts/Test/test_field_map.py`
Expected: FAIL with `AttributeError: module 'field_map' has no attribute 'build_scaffold'`.

- [ ] **Step 3: Write the minimal implementation**

Append to `.claude/skills/uqac-forms/scripts/field_map.py`:

```python
TODO_TARGET = "TODO"


def build_scaffold(form_id: str, pdf_path: str) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Produce the reviewable draft map of one form: every widget listed with
        its provenance and target set to TODO. The document is born `stale`, so
        nothing can be filled from it until a human completes the targets and
        flips the status to ok.

    Inputs:
        form_id (str): registry id
        pdf_path (str): the cached official PDF

    Outputs:
        document (dict): {form_id, status, source_sha256, widget_count, fields}
    --------------------------------------------------------------------------
    """
    widgets = dump_widgets(pdf_path)
    return {
        "form_id": form_id,
        "status": "stale",
        "stale_reason": "scaffold: every target is TODO and needs a human review",
        "source_sha256": form_registry.sha256_file(pdf_path),
        "widget_count": len(widgets),
        "fields": [{**w, "target": TODO_TARGET} for w in widgets],
    }


def write_map(document: dict[str, Any], maps_dir: str = form_registry.MAPS_DIR) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Persist a field map. Field order is preserved (page then annotation
        order) so a diff of this file reads like the form itself.

    Inputs:
        document (dict): a map document
        maps_dir (str): directory holding the field maps

    Outputs:
        path (str): the written path
    --------------------------------------------------------------------------
    """
    os.makedirs(maps_dir, exist_ok=True)
    path = form_registry.map_path(document["form_id"], maps_dir)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    logger.info("[UQAC-FORMS] wrote field map %s", path)
    return path


def load_map(form_id: str, maps_dir: str = form_registry.MAPS_DIR) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read one field map.

    Inputs:
        form_id (str): registry id
        maps_dir (str): directory holding the field maps

    Outputs:
        document (dict): the map document

    Raises:
        FileNotFoundError when no map exists for this form.
    --------------------------------------------------------------------------
    """
    path = form_registry.map_path(form_id, maps_dir)
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"no field map for {form_id}: run field_map.py dump {form_id}")
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def validate_map(form_id: str, pdf_path: str,
                 maps_dir: str = form_registry.MAPS_DIR,
                 schema_path: str = SCHEMA_PATH) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Check that a completed map still describes its PDF and still speaks the
        shared vocabulary: every mapped field exists in the file, every field in
        the file is mapped, every target is bound and known, and every declared
        checkbox on-state is one the widget actually offers.

    Inputs:
        form_id (str): registry id
        pdf_path (str): the cached official PDF
        maps_dir (str): directory holding the field maps
        schema_path (str): path to the profile vocabulary

    Outputs:
        errors (list[str]): empty when the map is usable, otherwise one
        actionable message per problem
    --------------------------------------------------------------------------
    """
    document = load_map(form_id, maps_dir)
    live = {w["name"]: w for w in dump_widgets(pdf_path)}
    known = schema_keys(load_schema(schema_path))
    errors: list[str] = []

    mapped: set[str] = set()
    for field in document.get("fields", []):
        name = field.get("name", "")
        mapped.add(name)
        target = field.get("target", TODO_TARGET)
        if name not in live:
            errors.append(
                f"{form_id}: mapped field {name!r} is no longer in the PDF - "
                f"re-run dump and re-review")
            continue
        if target == TODO_TARGET:
            errors.append(f"{form_id}: field {name!r} is still unbound (target is TODO)")
            continue
        if target not in known:
            errors.append(
                f"{form_id}: field {name!r} binds {target!r}, which is not in "
                f"registry/schema.yaml")
        declared = set(field.get("on_states") or [])
        actual = set(live[name]["on_states"])
        unknown = declared - actual
        if unknown:
            errors.append(
                f"{form_id}: field {name!r} declares on-state(s) "
                f"{sorted(unknown)} the widget does not offer {sorted(actual)}")

    for name in live:
        if name not in mapped:
            errors.append(
                f"{form_id}: PDF field {name!r} has no entry in the map - "
                f"re-run dump and bind it")
    return errors
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python .claude/skills/uqac-forms/scripts/Test/test_field_map.py`
Expected: PASS, 21 tests.

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/uqac-forms/scripts/field_map.py \
        .claude/skills/uqac-forms/scripts/Test/test_field_map.py
git commit -m "feat(uqac-forms): map scaffold, persistence, and validation"
```

---

## Task 4: Field diff wired into the drift check

**Files:**

- Modify: `.claude/skills/uqac-forms/scripts/field_map.py`
- Modify: `.claude/skills/uqac-forms/scripts/form_registry.py`
- Test: `.claude/skills/uqac-forms/scripts/Test/test_field_map.py`

**Interfaces:**

- Consumes: `dump_widgets`, `load_map` from Tasks 1 and 3; `check_drift`, `load_registry`, `load_baseline`, `save_baseline`, `DEFAULT_CACHE_DIR` from RT-1.
- Produces:
  - `diff_against_map(form_id: str, pdf_path: str, maps_dir: str = MAPS_DIR) -> dict[str, list[str]]` returning `{"added": [...], "removed": [...], "relocated": [...]}`. This is exactly the `differ(form_id, pdf_path) -> dict` callable RT-1's `check_drift` accepts.
  - The `form_registry.py check` CLI path passes `field_map.diff_against_map` as its differ, so a drifted form reports the field-level change and not only a hash mismatch.

- [ ] **Step 1: Write the failing test**

Append to `.claude/skills/uqac-forms/scripts/Test/test_field_map.py`, above the `if __name__` block:

```python
class TestDiffAgainstMap(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.maps = os.path.join(self.tmp.name, "maps")
        os.makedirs(self.maps, exist_ok=True)
        self.v1 = make_form_pdf(
            os.path.join(self.tmp.name, "v1.pdf"),
            [[_widget("Nom", "/Tx", (10, 700, 200, 720)),
              _widget("Prenom", "/Tx", (10, 670, 200, 690))]],
        )
        doc = field_map.build_scaffold("mth-inscription-sujet", self.v1)
        for field in doc["fields"]:
            field["target"] = "student.nom" if field["name"] == "Nom" else "student.prenom"
        doc["status"] = "ok"
        field_map.write_map(doc, self.maps)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_identical_pdf_reports_no_change(self) -> None:
        diff = field_map.diff_against_map("mth-inscription-sujet", self.v1, self.maps)
        self.assertEqual(diff, {"added": [], "removed": [], "relocated": []})

    def test_an_added_field_is_named(self) -> None:
        v2 = make_form_pdf(
            os.path.join(self.tmp.name, "v2.pdf"),
            [[_widget("Nom", "/Tx", (10, 700, 200, 720)),
              _widget("Prenom", "/Tx", (10, 670, 200, 690)),
              _widget("Courriel", "/Tx", (10, 640, 200, 660))]],
        )
        diff = field_map.diff_against_map("mth-inscription-sujet", v2, self.maps)
        self.assertEqual(diff["added"], ["Courriel"])
        self.assertEqual(diff["removed"], [])

    def test_a_removed_field_is_named(self) -> None:
        v2 = make_form_pdf(
            os.path.join(self.tmp.name, "v2.pdf"),
            [[_widget("Nom", "/Tx", (10, 700, 200, 720))]],
        )
        diff = field_map.diff_against_map("mth-inscription-sujet", v2, self.maps)
        self.assertEqual(diff["removed"], ["Prenom"])
        self.assertEqual(diff["added"], [])

    def test_a_moved_field_is_reported_as_relocated_not_as_add_plus_remove(self) -> None:
        v2 = make_form_pdf(
            os.path.join(self.tmp.name, "v2.pdf"),
            [[_widget("Nom", "/Tx", (10, 700, 200, 720))],
             [_widget("Prenom", "/Tx", (10, 500, 200, 520))]],
        )
        diff = field_map.diff_against_map("mth-inscription-sujet", v2, self.maps)
        self.assertEqual(diff["added"], [])
        self.assertEqual(diff["removed"], [])
        self.assertEqual(diff["relocated"], ["Prenom"])

    def test_a_missing_map_reports_every_field_as_added(self) -> None:
        diff = field_map.diff_against_map("no-such-form", self.v1, self.maps)
        self.assertEqual(diff["added"], ["Nom", "Prenom"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python .claude/skills/uqac-forms/scripts/Test/test_field_map.py`
Expected: FAIL with `AttributeError: module 'field_map' has no attribute 'diff_against_map'`.

- [ ] **Step 3: Write the minimal implementation**

Append to `.claude/skills/uqac-forms/scripts/field_map.py`:

```python
def diff_against_map(form_id: str, pdf_path: str,
                     maps_dir: str = form_registry.MAPS_DIR) -> dict[str, list[str]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Report what changed between a stored field map and a freshly downloaded
        PDF: fields added, fields removed, and fields that survived under the
        same name but moved to another page or rectangle.

        This is the differ RT-1's form_registry.check_drift accepts, so a drifted
        form is reported at field level and not only as a hash mismatch. A form
        with no stored map yet reports every field as added.

    Inputs:
        form_id (str): registry id
        pdf_path (str): the freshly downloaded PDF
        maps_dir (str): directory holding the field maps

    Outputs:
        diff (dict): {"added": [...], "removed": [...], "relocated": [...]},
        each list sorted for a stable report
    --------------------------------------------------------------------------
    """
    live = {w["name"]: w for w in dump_widgets(pdf_path)}
    try:
        stored = {f["name"]: f for f in load_map(form_id, maps_dir).get("fields", [])}
    except FileNotFoundError:
        return {"added": sorted(live), "removed": [], "relocated": []}

    added = sorted(set(live) - set(stored))
    removed = sorted(set(stored) - set(live))
    relocated = sorted(
        name for name in set(live) & set(stored)
        if live[name]["page"] != stored[name].get("page")
        or [round(v, 2) for v in live[name]["rect"]]
        != [round(float(v), 2) for v in (stored[name].get("rect") or [0, 0, 0, 0])]
    )
    if added or removed or relocated:
        logger.warning("[UQAC-FORMS] %s field diff: +%d -%d moved %d",
                       form_id, len(added), len(removed), len(relocated))
    return {"added": added, "removed": removed, "relocated": relocated}
```

- [ ] **Step 4: Wire the differ into the drift-check CLI**

In `.claude/skills/uqac-forms/scripts/form_registry.py`, inside `main()`, replace the `check` branch line

```python
    drifted = [check_drift(s, baseline, args.cache_dir) for s in specs]
```

with:

```python
    # Imported lazily so form_registry keeps no import-time PDF dependency and
    # its own offline suite stays free of pypdf.
    try:
        import field_map
        differ = field_map.diff_against_map
    except ImportError:  # pypdf absent: hash-level drift reporting still works
        logger.warning("[UQAC-FORMS] field_map unavailable - reporting hash drift only")
        differ = None
    drifted = [check_drift(s, baseline, args.cache_dir, differ=differ) for s in specs]
```

- [ ] **Step 5: Run both suites to verify they pass**

```powershell
python .claude/skills/uqac-forms/scripts/Test/test_field_map.py
python .claude/skills/uqac-forms/scripts/Test/test_form_registry.py
```

Expected: 26 tests pass in `test_field_map.py`, 20 in `test_form_registry.py`.

- [ ] **Step 6: Commit**

```bash
git add .claude/skills/uqac-forms/scripts/field_map.py \
        .claude/skills/uqac-forms/scripts/form_registry.py \
        .claude/skills/uqac-forms/scripts/Test/test_field_map.py
git commit -m "feat(uqac-forms): field-level drift diff wired into the registry check"
```

---

## Task 5: Command-line interface and the real maps

**Files:**

- Modify: `.claude/skills/uqac-forms/scripts/field_map.py`
- Modify: `.claude/skills/uqac-forms/SKILL.md`
- Modify: `.claude/rules/testing.md`
- Create (generated then hand-completed): `.claude/skills/uqac-forms/registry/maps/<form_id>.json` for the five registered forms.

**Interfaces:**

- Consumes: everything above, plus `load_registry`, `fetch_form`, `DEFAULT_CACHE_DIR` from RT-1.
- Produces: the `dump`, `validate`, `diff`, and `schema` subcommands, and five reviewed field maps with `status: "ok"`.

- [ ] **Step 1: Write the CLI**

Append to `.claude/skills/uqac-forms/scripts/field_map.py`:

```python
def _pdf_for(form_id: str, cache_dir: str) -> str:
    """Resolve the cached PDF of a registered form, downloading it when absent."""
    registry = form_registry.load_registry()
    if form_id not in registry:
        raise SystemExit(f"unknown form id: {form_id} (try: form_registry.py list)")
    path = form_registry.fetch_form(registry[form_id], cache_dir)
    if path is None:
        raise SystemExit(f"could not download {form_id}")
    return path


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="UQAC form field map: dump, validate, diff")
    sub = parser.add_subparsers(dest="mode", required=True)

    sub.add_parser("schema", help="print the profile vocabulary")
    for name, helptext in (("dump", "write a scaffold map with every target TODO"),
                           ("validate", "check a completed map against the PDF and the schema"),
                           ("diff", "report added, removed, and relocated fields")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("form_id")
        p.add_argument("--cache-dir", default=form_registry.DEFAULT_CACHE_DIR)
        p.add_argument("--maps-dir", default=form_registry.MAPS_DIR)

    args = parser.parse_args()

    if args.mode == "schema":
        print(json.dumps(load_schema(), indent=2, ensure_ascii=False))
        return

    pdf = _pdf_for(args.form_id, args.cache_dir)

    if args.mode == "dump":
        path = write_map(build_scaffold(args.form_id, pdf), args.maps_dir)
        print(json.dumps({"form_id": args.form_id, "map": path,
                          "next": "complete every target, then set status to ok"},
                         indent=2, ensure_ascii=False))
        return

    if args.mode == "diff":
        print(json.dumps(diff_against_map(args.form_id, pdf, args.maps_dir),
                         indent=2, ensure_ascii=False))
        return

    errors = validate_map(args.form_id, pdf, args.maps_dir)
    print(json.dumps({"form_id": args.form_id, "errors": errors}, indent=2, ensure_ascii=False))
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Generate the five scaffolds**

Run (needs network on first run, then the cache serves):

```powershell
python .claude/skills/uqac-forms/scripts/field_map.py dump mth-inscription-sujet
python .claude/skills/uqac-forms/scripts/field_map.py dump mth-plan-travail
python .claude/skills/uqac-forms/scripts/field_map.py dump mth-autorisation-depot
python .claude/skills/uqac-forms/scripts/field_map.py dump srf-rapport-depenses
python .claude/skills/uqac-forms/scripts/field_map.py dump srf-demande-avance-voyage
```

Expected widget counts, from the 2026-07-29 probe: `mth-inscription-sujet` 56 over 2 pages, `mth-plan-travail` 92 over 2 pages, `srf-rapport-depenses` 111 over 1 page, `srf-demande-avance-voyage` 63 over 1 page. A materially different count means the form already drifted: stop and re-check the registry URL before binding anything.

- [ ] **Step 3: Complete the targets by hand (human review, mandatory)**

For each `registry/maps/<form_id>.json`:

1. Bind every field whose value comes from the profile to its dotted key, for example `"name": "code permanent"` to `"target": "student.code_permanent"` and `"name": "no_matricule"` to the same `student.code_permanent`.
2. Leave a field the profile does not feed bound to the literal `"UNMAPPED"`, and add the same string to the vocabulary check by adding it to the map entry only, never to `schema.yaml`. Then extend `validate_map` acceptance by treating `"UNMAPPED"` as a deliberate human decision: add `UNMAPPED_TARGET = "UNMAPPED"` next to `TODO_TARGET` and skip both the vocabulary check and the unbound check for it, while still reporting a field that vanished from the PDF.
3. Set `"status": "ok"` and delete the `stale_reason` key.

- [ ] **Step 4: Validate all five**

```powershell
python .claude/skills/uqac-forms/scripts/field_map.py validate mth-inscription-sujet
python .claude/skills/uqac-forms/scripts/field_map.py validate mth-plan-travail
python .claude/skills/uqac-forms/scripts/field_map.py validate mth-autorisation-depot
python .claude/skills/uqac-forms/scripts/field_map.py validate srf-rapport-depenses
python .claude/skills/uqac-forms/scripts/field_map.py validate srf-demande-avance-voyage
```

Expected: `"errors": []` and exit 0 for each.

- [ ] **Step 5: Update SKILL.md**

In `.claude/skills/uqac-forms/SKILL.md`, replace the "Scope in this unit (RT-1)" section with:

```markdown
## Field maps

A field map binds one form's opaque widget names to the shared profile
vocabulary in `registry/schema.yaml`. Names are byte-exact keys and are never
normalized; checkbox on-states are read from each widget's `/AP /N` dictionary
and are per-widget, so nothing assumes `/Yes`.

1. Scaffold: `python .claude/skills/uqac-forms/scripts/field_map.py dump <form_id>`
   writes `registry/maps/<form_id>.json` with every `target` set to `TODO` and
   `status` set to `stale`.
2. Human review (mandatory): complete each `target` with a dotted vocabulary key,
   mark a field the profile does not feed as `UNMAPPED`, then set `status` to `ok`.
3. Validate: `python .claude/skills/uqac-forms/scripts/field_map.py validate <form_id>`
   reports every unbound target, unknown key, vanished field, unmapped new field,
   and impossible checkbox on-state. Exit 1 means the map is not usable.
4. Inspect the vocabulary: `python .claude/skills/uqac-forms/scripts/field_map.py schema`.

When `form_registry.py check` detects drift it calls this diff, so the report
names the added, removed, and relocated fields before it marks the map stale.
```

- [ ] **Step 6: Update `.claude/rules/testing.md`**

Add to the offline test list:

```powershell
python .claude/skills/uqac-forms/scripts/Test/test_field_map.py   # widget dump, vocabulary, scaffold, validation, field diff
```

and extend the `uqac-forms` script-surface sentence with `field_map.py` (widget dump with byte-exact names and `/AP /N` on-states, scaffold, validation, drift diff; tests build their own AcroForm PDFs with `pypdf`, no network).

- [ ] **Step 7: Run the full offline suite**

```powershell
python .claude/skills/uqac-forms/scripts/Test/test_field_map.py
python .claude/skills/uqac-forms/scripts/Test/test_form_registry.py
python .claude/skills/scopus/scripts/Test/test_download_pdf.py
python .claude/skills/scopus/scripts/Test/test_browser_fetch.py
python .claude/skills/scopus/scripts/Test/test_bib_batch.py
python .claude/skills/scopus/scripts/Test/test_litreview_update.py
python .claude/skills/extract-statistic/scripts/Test/test_section_scan.py
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add .claude/skills/uqac-forms .claude/rules/testing.md
git commit -m "feat(uqac-forms): field-map CLI and five reviewed maps"
```

---

## Interfaces published by RT-2

| Name | Signature | Consumed by |
|---|---|---|
| `dump_widgets` | `dump_widgets(pdf_path: str) -> list[dict]` | RT-3, RT-5 |
| `load_schema` | `load_schema(path: str = SCHEMA_PATH) -> dict[str, dict[str, str]]` | RT-3, RT-5 |
| `schema_keys` | `schema_keys(schema: dict) -> set[str]` | RT-3 |
| `resolve_target` | `resolve_target(profile: dict, target: str) -> Any` | RT-3 |
| `build_scaffold` | `build_scaffold(form_id: str, pdf_path: str) -> dict` | RT-5 |
| `write_map` | `write_map(document: dict, maps_dir: str = MAPS_DIR) -> str` | RT-5 |
| `load_map` | `load_map(form_id: str, maps_dir: str = MAPS_DIR) -> dict` | RT-3, RT-4, RT-5 |
| `validate_map` | `validate_map(form_id, pdf_path, maps_dir, schema_path) -> list[str]` | RT-3, RT-5 |
| `diff_against_map` | `diff_against_map(form_id: str, pdf_path: str, maps_dir: str) -> dict[str, list[str]]` | RT-1 `check_drift` differ |
| `TODO_TARGET`, `UNMAPPED_TARGET`, `SCHEMA_PATH` | module constants | RT-3, RT-5 |

Map entry shape every unit relies on: `{"name": str, "name_hex": str, "type": "text"|"checkbox"|"radio"|"choice"|"signature"|"unknown", "page": int, "rect": [float, float, float, float], "on_states": list[str], "readonly": bool, "target": str}`.

---

## Acceptance

```powershell
python .claude/skills/uqac-forms/scripts/Test/test_field_map.py
python .claude/skills/uqac-forms/scripts/Test/test_form_registry.py
python .claude/skills/uqac-forms/scripts/field_map.py validate srf-rapport-depenses   # network on first run
pip-audit -r .claude/skills/uqac-forms/scripts/requirements.txt --strict
```

Plus the five existing offline suites in `.claude/rules/testing.md`, which must stay green.
