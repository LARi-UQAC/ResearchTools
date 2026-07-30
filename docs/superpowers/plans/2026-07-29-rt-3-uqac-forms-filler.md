# RT-3: UQAC Form Filler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn a profile plus a reviewed field map into a filled official UQAC PDF, with appearances requested, non-signature fields locked, the signature field left intact for RT-4, and a hard refusal to run against a stale map.

> ## SCOPE CHANGE, 2026-07-29 - read before anything else
>
> Two decisions changed after this plan was written, and `NEW_ARCHITECTURE.md` on `main`
> is the authority on both. **Read its sections 1, 3 and 10 before starting.**
>
> **The repository boundary moved.** ResearchTools cannot track a form and cannot know the information that fills one: it is skills, agents and commands for a thesis, a paper, a review or a report, and only ThesisTracker writes the database. The form catalogue, the workflow rules, the field maps, the profile store and the drift check therefore live in **ThesisTracker**, edited in the UI by an `owner` or the `direction`. The ResearchTools service is reduced to **stateless PDF mechanics**: hand it a PDF and a set of values, it hands back a PDF. It is a function, not a system, and holds no data.
>
> > **What this means for RT-3.** The filler becomes **stateless**. Its signature is
> `fill(pdf_bytes, values, flatten_fields=None) -> bytes`, where `values` maps a
> byte-exact PDF field name to a string that ThesisTracker already resolved.
>
> - Keep: the write itself, `NeedAppearances`, the per-widget checkbox on-state handling,
>   the ordering rule (fill, appearances, lock, sign last), and the honest statement that
>   `pypdf` has no appearance-burning flatten.
> - Drop: `load_profile`, `resolve_values`, the field map, the profile vocabulary and
>   `require_fresh_map`. TT-9 resolves the values and TT-10 decides which fields a step
>   may write; this function is handed the result.
> - `flatten_fields` becomes a **list of field names to lock**, not a boolean, because
>   only the fields of completed steps are locked while later steps still have to write.
>   That is a real behavioural change and its own test.
>
> Task 1 is superseded, Task 2 stands with the selective-locking change, Task 3 becomes
> the stateless entry point with no stale gate.
>
> Everything below that this block does not contradict still stands. Where the plan and
> `NEW_ARCHITECTURE.md` disagree, the architecture document wins, and your first commit
> should be the correction to this plan.


**Architecture:** `fill_form.py` loads the reviewed map (RT-2), resolves every bound target against a profile document, and writes the values back with `pypdf`. Text and choice widgets take a string; checkbox and radio widgets take the widget's own on-state read from the map, never an assumed `/Yes`. After filling, `NeedAppearances` is set so a viewer regenerates the visible text, then every non-signature widget is locked read-only. Signature widgets are deliberately untouched: flattening destroys them, and RT-4 signs last as an incremental update. The whole path is gated on `form_registry.require_fresh_map`, so a form UQAC silently replaced can never be filled.

**Tech Stack:** Python 3.13, `pypdf` (BSD-3), `PyYAML`, standard library. No PyMuPDF (AGPL-3.0).

## Global Constraints

- Definition files (agents, skills, commands) are **English-only**.
- Style hygiene in any produced text: no em dash, no double or triple dash, straight quotes only, no zero-width or Unicode-tag characters, no single-character ellipsis, no leftover `*` or `#`.
- Python naming: classes `PascalCase`, functions and module variables `snake_case`, private `_snake_case`, constants `UPPER_SNAKE_CASE`. Type hints in every signature.
- Docstrings use the repo's extended `Purpose: / Inputs: / Outputs:` block format.
- Logging: `logging.getLogger(__name__)`, messages prefixed `[UQAC-FORMS]`. **Never log a field value**: a profile carries a permanent code, an address, and a bank payee. Log field names and counts only.
- **Field names are opaque byte-exact keys.** Never normalize, lowercase, or strip accents.
- **Order is fill, appearances, flatten non-signature fields, sign LAST as an incremental update.** Flattening destroys signature fields, so this file never touches a `/Sig` widget and never signs.
- **Set `NeedAppearances` after filling**, and assert it in tests: AcroForm values do not render without appearance streams.
- All fixtures synthetic. The sample profile is invented data and is committed as such; no real profile, certificate, or key is ever committed.
- LaTeX output goes to `out/`; so does every generated PDF here.
- Offline tests only: PDFs are built in the test with `pypdf`, never downloaded.

**Depends on:** RT-2 (`feat/uqac-forms-field-map`), which depends on RT-1.

---

## File Structure

**New files**

- `.claude/skills/uqac-forms/scripts/fill_form.py` - profile plus map to filled PDF.
- `.claude/skills/uqac-forms/samples/profile.sample.json` - synthetic profile covering every vocabulary namespace.
- `.claude/skills/uqac-forms/scripts/Test/test_fill_form.py` - offline unit tests.

**Modified files**

- `.claude/skills/uqac-forms/SKILL.md` - the fill workflow and the ordering rule.
- `.claude/rules/testing.md` - the new offline test command.

---

## Interfaces consumed

From RT-1 `form_registry.py`:

- `load_registry(path: str = REGISTRY_PATH) -> dict[str, FormSpec]`
- `fetch_form(spec: FormSpec, cache_dir: str, force: bool = False) -> str | None`
- `require_fresh_map(form_id: str, maps_dir: str = MAPS_DIR) -> None`, raises `StaleMapError`
- `StaleMapError`, `DEFAULT_CACHE_DIR`, `MAPS_DIR`

From RT-2 `field_map.py`:

- `load_map(form_id: str, maps_dir: str = MAPS_DIR) -> dict`
- `resolve_target(profile: dict, target: str) -> Any`
- `validate_map(form_id, pdf_path, maps_dir, schema_path) -> list[str]`
- `TODO_TARGET`, `UNMAPPED_TARGET`
- Map entry shape: `{"name", "name_hex", "type", "page", "rect", "on_states", "readonly", "target"}`

---

## Task 1: Value resolution from a profile

**Files:**

- Create: `.claude/skills/uqac-forms/scripts/fill_form.py`
- Create: `.claude/skills/uqac-forms/samples/profile.sample.json`
- Test: `.claude/skills/uqac-forms/scripts/Test/test_fill_form.py`

**Interfaces:**

- Consumes: `load_map`, `resolve_target`, `TODO_TARGET`, `UNMAPPED_TARGET` from RT-2.
- Produces:
  - `load_profile(path: str) -> dict[str, Any]` (JSON, UTF-8).
  - `resolve_values(document: dict, profile: dict) -> tuple[dict[str, Any], list[str]]` returning `(values_by_field_name, skipped_field_names)`. A checkbox resolves to its on-state string when the profile value is truthy or equals an offered on-state, and is skipped when falsy.

- [ ] **Step 1: Write the failing test**

Create `.claude/skills/uqac-forms/scripts/Test/test_fill_form.py`:

```python
"""
test_fill_form.py - Offline unit tests for fill_form.py.

No network and no committed PDF fixture: each test builds its own AcroForm PDF
with pypdf. All profile data is invented. Run with the project Python:
    python .claude/skills/uqac-forms/scripts/Test/test_fill_form.py
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fill_form  # noqa: E402
import field_map  # noqa: E402

from pypdf import PdfReader, PdfWriter  # noqa: E402
from pypdf.generic import (  # noqa: E402
    ArrayObject, DictionaryObject, FloatObject, NameObject, TextStringObject,
)


def _widget(name: str, field_type: str, rect: tuple[float, float, float, float],
            on_states: list[str] | None = None) -> DictionaryObject:
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


def make_form_pdf(path: str, widgets: list[DictionaryObject]) -> str:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    annots = ArrayObject()
    for widget in widgets:
        annots.append(writer._add_object(widget))
    page[NameObject("/Annots")] = annots
    with open(path, "wb") as handle:
        writer.write(handle)
    return path


PROFILE = {
    "student": {"nom": "Tremblay", "prenom": "Camille",
                "code_permanent": "TREM99010199", "courriel": "ctremblay@etu.uqac.ca"},
    "professor": {"nom": "Otis", "prenom": "Martin"},
    "project": {"titre": "Diagnostic de pannes par apprentissage profond"},
    "trip": {"destination": "Montreal, Canada", "mode_transport": "Avion",
             "montant_demande": "1250.00"},
}


class TestResolveValues(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.maps = os.path.join(self.tmp.name, "maps")
        os.makedirs(self.maps, exist_ok=True)
        self.pdf = make_form_pdf(
            os.path.join(self.tmp.name, "form.pdf"),
            [_widget("Nom", "/Tx", (10, 700, 200, 720)),
             _widget("no_matricule", "/Tx", (10, 670, 200, 690)),
             _widget("champ_interne", "/Tx", (10, 640, 200, 660)),
             _widget("mode_transport", "/Btn", (10, 610, 30, 630), on_states=["Avion"])],
        )
        self.document = self._map()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _map(self) -> dict:
        doc = field_map.build_scaffold("srf-demande-avance-voyage", self.pdf)
        targets = {"Nom": "student.nom", "no_matricule": "student.code_permanent",
                   "champ_interne": field_map.UNMAPPED_TARGET,
                   "mode_transport": "trip.mode_transport"}
        for field in doc["fields"]:
            field["target"] = targets[field["name"]]
        doc["status"] = "ok"
        field_map.write_map(doc, self.maps)
        return doc

    def test_one_vocabulary_key_fills_the_form_specific_name(self) -> None:
        values, _ = fill_form.resolve_values(self.document, PROFILE)
        # student.code_permanent is written once and lands in no_matricule here.
        self.assertEqual(values["no_matricule"], "TREM99010199")
        self.assertEqual(values["Nom"], "Tremblay")

    def test_an_unmapped_field_is_skipped_not_filled(self) -> None:
        values, skipped = fill_form.resolve_values(self.document, PROFILE)
        self.assertNotIn("champ_interne", values)
        self.assertIn("champ_interne", skipped)

    def test_a_checkbox_resolves_to_its_own_on_state(self) -> None:
        values, _ = fill_form.resolve_values(self.document, PROFILE)
        self.assertEqual(values["mode_transport"], "Avion")

    def test_a_checkbox_whose_profile_value_is_falsy_is_skipped(self) -> None:
        profile = {**PROFILE, "trip": {**PROFILE["trip"], "mode_transport": ""}}
        values, skipped = fill_form.resolve_values(self.document, profile)
        self.assertNotIn("mode_transport", values)
        self.assertIn("mode_transport", skipped)

    def test_a_checkbox_bound_to_a_state_the_widget_does_not_offer_raises(self) -> None:
        profile = {**PROFILE, "trip": {**PROFILE["trip"], "mode_transport": "Fusee"}}
        with self.assertRaises(ValueError) as ctx:
            fill_form.resolve_values(self.document, profile)
        self.assertIn("Fusee", str(ctx.exception))

    def test_a_missing_profile_key_is_skipped_not_filled_with_none(self) -> None:
        values, skipped = fill_form.resolve_values(self.document, {"student": {"nom": "Tremblay"}})
        self.assertNotIn("no_matricule", values)
        self.assertIn("no_matricule", skipped)

    def test_a_numeric_profile_value_becomes_a_string(self) -> None:
        doc = dict(self.document)
        doc["fields"] = [dict(f) for f in self.document["fields"]]
        doc["fields"][0]["target"] = "trip.montant_demande"
        values, _ = fill_form.resolve_values(doc, {**PROFILE, "trip": {"montant_demande": 1250}})
        self.assertEqual(values["Nom"], "1250")

    def test_the_shipped_sample_profile_loads_and_covers_every_namespace(self) -> None:
        here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(fill_form.__file__))))
        sample = os.path.join(here, "uqac-forms", "samples", "profile.sample.json")
        sample = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(fill_form.__file__))),
                              "samples", "profile.sample.json")
        profile = fill_form.load_profile(sample)
        self.assertEqual(set(profile), {"student", "professor", "project", "trip"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python .claude/skills/uqac-forms/scripts/Test/test_fill_form.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'fill_form'`.

- [ ] **Step 3: Write the sample profile**

Create `.claude/skills/uqac-forms/samples/profile.sample.json`. Every value is invented; nothing here belongs to a real person.

```json
{
  "student": {
    "nom": "Tremblay",
    "prenom": "Camille",
    "code_permanent": "TREM99010199",
    "courriel": "camille.tremblay1@etu.uqac.ca",
    "telephone": "418-555-0142",
    "programme": "3459 Doctorat en ingenierie",
    "cycle": "3",
    "adresse": "555 boulevard de l'Universite, Chicoutimi (Quebec) G7H 2B1",
    "date_admission": "2025-09-02"
  },
  "professor": {
    "nom": "Exemple",
    "prenom": "Alex",
    "departement": "Departement des sciences appliquees",
    "courriel": "alex.exemple@uqac.ca",
    "codirecteur_nom": "",
    "codirecteur_prenom": ""
  },
  "project": {
    "titre": "Diagnostic de pannes industrielles par apprentissage profond",
    "resume": "Detection et classification de pannes sur une chaine de production instrumentee.",
    "laboratoire": "LAR.i",
    "date_debut": "2025-09-02",
    "date_depot_prevue": "2029-08-31",
    "organisme_subvention": "MITACS",
    "numero_dossier": "IT00000"
  },
  "trip": {
    "destination": "Montreal, Canada",
    "motif": "Presentation d'un article de conference",
    "date_depart": "2026-10-12",
    "date_retour": "2026-10-15",
    "montant_demande": "1250.00",
    "mode_transport": "Avion",
    "code_budgetaire": "00000-00000",
    "cheque_payable_a": "Camille Tremblay"
  }
}
```

- [ ] **Step 4: Write the minimal implementation**

Create `.claude/skills/uqac-forms/scripts/fill_form.py`:

```python
"""
fill_form.py - Fill a registered UQAC form from a profile and its reviewed
field map.

Order is fill, appearances, flatten non-signature fields, sign LAST. Signing is
RT-4's job and is an incremental update: flattening destroys signature fields,
so nothing here touches a /Sig widget.

Nothing in this module logs a field value. A profile carries a permanent code,
a postal address, and a cheque payee, so only field names and counts are logged.

Usage:
  python fill_form.py <form_id> --profile <profile.json> [--out out/<name>.pdf]
                      [--cache-dir DIR] [--maps-dir DIR] [--no-flatten]
"""

import argparse
import json
import logging
import os
from typing import Any

from pypdf import PdfReader, PdfWriter
from pypdf.generic import BooleanObject, DictionaryObject, NameObject, NumberObject

import field_map
import form_registry

logger = logging.getLogger(__name__)

READONLY_FLAG = 1  # /Ff bit 1: the field is not editable in a viewer


def load_profile(path: str) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read a profile document. A profile is plain JSON keyed by the vocabulary
        namespaces declared in registry/schema.yaml.

    Inputs:
        path (str): path to the profile JSON

    Outputs:
        profile (dict): the parsed profile

    Raises:
        FileNotFoundError when the profile is missing.
    --------------------------------------------------------------------------
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"profile not found: {path}")
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def resolve_values(document: dict[str, Any],
                   profile: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Turn a reviewed field map plus a profile into the values to write,
        keyed by the form's own byte-exact field names.

        A text or choice widget takes the profile value as a string. A checkbox
        or radio widget takes one of its own on-states: the profile value is
        matched against the states the map recorded from /AP /N, so nothing
        assumes /Yes. A field the profile does not feed is skipped rather than
        written empty, which keeps an untouched official field untouched.

    Inputs:
        document (dict): a reviewed field map (status ok)
        profile (dict): the profile document

    Outputs:
        result (tuple): (values, skipped) where values maps field name to the
        string to write and skipped lists the field names left untouched

    Raises:
        ValueError when a checkbox is bound to a state the widget does not
        offer, since writing it would silently produce an unticked box.
    --------------------------------------------------------------------------
    """
    values: dict[str, Any] = {}
    skipped: list[str] = []

    for field in document.get("fields", []):
        name = field["name"]
        target = field.get("target", field_map.TODO_TARGET)
        if target in (field_map.TODO_TARGET, field_map.UNMAPPED_TARGET):
            skipped.append(name)
            continue
        if field.get("type") == "signature":
            skipped.append(name)  # signature fields are RT-4's, never filled here
            continue

        raw = field_map.resolve_target(profile, target)
        if raw is None or raw == "":
            skipped.append(name)
            continue

        if field.get("type") in ("checkbox", "radio"):
            states = list(field.get("on_states") or [])
            wanted = str(raw)
            if wanted in states:
                values[name] = wanted
                continue
            if raw is True and len(states) == 1:
                values[name] = states[0]
                continue
            if raw is False:
                skipped.append(name)
                continue
            raise ValueError(
                f"field {name!r} is bound to on-state {wanted!r}, but the widget "
                f"only offers {states}")
            continue

        values[name] = str(raw)

    logger.info("[UQAC-FORMS] resolved %d value(s), skipped %d field(s)",
                len(values), len(skipped))
    return values, skipped
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python .claude/skills/uqac-forms/scripts/Test/test_fill_form.py`
Expected: PASS, 8 tests.

- [ ] **Step 6: Commit**

```bash
git add .claude/skills/uqac-forms/scripts/fill_form.py \
        .claude/skills/uqac-forms/samples/profile.sample.json \
        .claude/skills/uqac-forms/scripts/Test/test_fill_form.py
git commit -m "feat(uqac-forms): profile-to-field value resolution with per-widget on-states"
```

---

## Task 2: Write the values, request appearances, lock the fields

**Files:**

- Modify: `.claude/skills/uqac-forms/scripts/fill_form.py`
- Test: `.claude/skills/uqac-forms/scripts/Test/test_fill_form.py`

**Interfaces:**

- Consumes: `resolve_values` from Task 1.
- Produces:
  - `set_need_appearances(writer: PdfWriter) -> None`.
  - `write_values(writer: PdfWriter, values: dict[str, Any]) -> int` returning the number of widgets written.
  - `lock_non_signature_fields(writer: PdfWriter) -> int` returning the number of widgets locked. Signature widgets are never locked and never removed.

**Honest limitation, stated once and carried into `SKILL.md`:** `pypdf` has no appearance-burning flatten. "Flatten" here means locking every non-signature widget read-only while its value and appearance stream stay in the file, which is what an administrative reviewer needs and what leaves the signature field usable for the RT-4 incremental update. A true burn-in flatten would destroy the signature field and is therefore out of scope for the signing path.

- [ ] **Step 1: Write the failing test**

Append to `.claude/skills/uqac-forms/scripts/Test/test_fill_form.py`, above the `if __name__` block:

```python
class TestWriteAndLock(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.pdf = make_form_pdf(
            os.path.join(self.tmp.name, "form.pdf"),
            [_widget("Nom", "/Tx", (10, 700, 200, 720)),
             _widget("mode_transport", "/Btn", (10, 610, 30, 630), on_states=["Avion"]),
             _widget("Signature_directeur", "/Sig", (300, 100, 500, 160))],
        )
        self.out = os.path.join(self.tmp.name, "filled.pdf")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write(self, values: dict, lock: bool = True) -> str:
        writer = PdfWriter(clone_from=self.pdf)
        fill_form.write_values(writer, values)
        fill_form.set_need_appearances(writer)
        if lock:
            fill_form.lock_non_signature_fields(writer)
        with open(self.out, "wb") as handle:
            writer.write(handle)
        return self.out

    def test_a_text_value_round_trips_through_the_written_file(self) -> None:
        reader = PdfReader(self._write({"Nom": "Tremblay"}))
        self.assertEqual(reader.get_fields()["Nom"].get("/V"), "Tremblay")

    def test_need_appearances_is_set_so_a_viewer_renders_the_values(self) -> None:
        reader = PdfReader(self._write({"Nom": "Tremblay"}))
        acro = reader.trailer["/Root"]["/AcroForm"]
        self.assertTrue(bool(acro.get("/NeedAppearances")))

    def test_a_checkbox_gets_both_v_and_as_set_to_its_on_state(self) -> None:
        path = self._write({"mode_transport": "Avion"})
        reader = PdfReader(path)
        annot = [a.get_object() for a in reader.pages[0]["/Annots"]
                 if str(a.get_object().get("/T")) == "mode_transport"][0]
        self.assertEqual(str(annot["/V"]), "/Avion")
        self.assertEqual(str(annot["/AS"]), "/Avion")

    def test_locking_sets_readonly_on_a_text_widget(self) -> None:
        reader = PdfReader(self._write({"Nom": "Tremblay"}))
        annot = [a.get_object() for a in reader.pages[0]["/Annots"]
                 if str(a.get_object().get("/T")) == "Nom"][0]
        self.assertTrue(int(annot.get("/Ff", 0)) & fill_form.READONLY_FLAG)

    def test_locking_never_touches_a_signature_widget(self) -> None:
        reader = PdfReader(self._write({"Nom": "Tremblay"}))
        annots = [a.get_object() for a in reader.pages[0]["/Annots"]]
        sig = [a for a in annots if str(a.get("/T")) == "Signature_directeur"]
        self.assertEqual(len(sig), 1, "the signature field must survive flattening")
        self.assertFalse(int(sig[0].get("/Ff", 0)) & fill_form.READONLY_FLAG)

    def test_the_signature_field_survives_so_rt4_can_sign_last(self) -> None:
        reader = PdfReader(self._write({"Nom": "Tremblay"}))
        kinds = {str(a.get_object().get("/FT")) for a in reader.pages[0]["/Annots"]}
        self.assertIn("/Sig", kinds)

    def test_write_values_reports_how_many_widgets_it_touched(self) -> None:
        writer = PdfWriter(clone_from=self.pdf)
        self.assertEqual(fill_form.write_values(writer, {"Nom": "X", "mode_transport": "Avion"}), 2)

    def test_a_value_for_an_unknown_field_name_is_reported_not_silently_dropped(self) -> None:
        writer = PdfWriter(clone_from=self.pdf)
        with self.assertRaises(KeyError):
            fill_form.write_values(writer, {"champ_qui_nexiste_pas": "X"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python .claude/skills/uqac-forms/scripts/Test/test_fill_form.py`
Expected: FAIL with `AttributeError: module 'fill_form' has no attribute 'write_values'`.

- [ ] **Step 3: Write the minimal implementation**

Append to `.claude/skills/uqac-forms/scripts/fill_form.py`:

```python
def _widget_annots(writer: PdfWriter) -> list[Any]:
    """Every /Widget annotation of the document, in page then annotation order."""
    out: list[Any] = []
    for page in writer.pages:
        annots = page.get("/Annots")
        if not annots:
            continue
        for ref in annots:
            annot = ref.get_object()
            if str(annot.get("/Subtype") or "") == "/Widget":
                out.append(annot)
    return out


def _annot_name(annot: Any) -> str | None:
    """The widget's own /T, walking /Parent for an inherited name."""
    parts: list[str] = []
    node: Any = annot
    seen = 0
    while node is not None and seen < 32:
        title = node.get("/T")
        if title is not None:
            parts.append(str(title.get_object() if hasattr(title, "get_object") else title))
        parent = node.get("/Parent")
        node = parent.get_object() if parent is not None else None
        seen += 1
    return ".".join(reversed(parts)) if parts else None


def _annot_kind(annot: Any) -> str:
    """The widget's field type code (/Tx, /Btn, /Ch, /Sig), inherited if needed."""
    node: Any = annot
    seen = 0
    while node is not None and seen < 32:
        field_type = node.get("/FT")
        if field_type is not None:
            return str(field_type)
        parent = node.get("/Parent")
        node = parent.get_object() if parent is not None else None
        seen += 1
    return ""


def write_values(writer: PdfWriter, values: dict[str, Any]) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Write the resolved values into the widgets, matching on the byte-exact
        field name. A button gets both /V and /AS set to its on-state, because a
        viewer draws the appearance named by /AS; a text or choice widget gets
        /V.

    Inputs:
        writer (PdfWriter): a writer cloned from the official PDF
        values (dict): field name to value, as returned by resolve_values

    Outputs:
        written (int): number of widgets written

    Raises:
        KeyError naming every value whose field is absent from the document, so
        a map that drifted out of sync fails loudly instead of half-filling.
    --------------------------------------------------------------------------
    """
    by_name: dict[str, list[Any]] = {}
    for annot in _widget_annots(writer):
        name = _annot_name(annot)
        if name is not None:
            by_name.setdefault(name, []).append(annot)

    missing = sorted(set(values) - set(by_name))
    if missing:
        raise KeyError(f"no such field(s) in the PDF: {missing}")

    written = 0
    for name, value in values.items():
        for annot in by_name[name]:
            if _annot_kind(annot) == "/Btn":
                # A viewer draws the appearance named by /AS, so both are set.
                state = NameObject(f"/{value}")
                annot[NameObject("/V")] = state
                annot[NameObject("/AS")] = state
            else:
                annot[NameObject("/V")] = TextStringObject(str(value))
            written += 1
    logger.info("[UQAC-FORMS] wrote %d widget(s)", written)
    return written


def set_need_appearances(writer: PdfWriter) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Ask the viewer to regenerate the appearance streams of the form fields.
        An AcroForm value written into /V does not render on its own, so this
        flag is what makes a filled form visibly filled.

    Inputs:
        writer (PdfWriter): the writer being assembled

    Outputs:
        none
    --------------------------------------------------------------------------
    """
    root = writer._root_object  # noqa: SLF001 (pypdf idiom for the catalog)
    acro = root.get("/AcroForm")
    if acro is None:
        acro = DictionaryObject()
        root[NameObject("/AcroForm")] = writer._add_object(acro)  # noqa: SLF001
        acro = root["/AcroForm"].get_object()
    acro[NameObject("/NeedAppearances")] = BooleanObject(True)


def lock_non_signature_fields(writer: PdfWriter) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Lock every filled widget so a reviewer cannot edit the submitted values,
        while leaving signature widgets untouched.

        pypdf offers no appearance-burning flatten, and a true burn-in would
        destroy the signature field the RT-4 incremental-update signature needs.
        Locking read-only is therefore the flatten step of this pipeline: values
        and appearance streams stay, editability goes.

    Inputs:
        writer (PdfWriter): the writer being assembled

    Outputs:
        locked (int): number of widgets locked
    --------------------------------------------------------------------------
    """
    locked = 0
    for annot in _widget_annots(writer):
        if _annot_kind(annot) == "/Sig":
            continue  # never lock or remove a signature field
        flags = int(annot.get("/Ff", 0))
        annot[NameObject("/Ff")] = NumberObject(flags | READONLY_FLAG)
        locked += 1
    logger.info("[UQAC-FORMS] locked %d non-signature widget(s)", locked)
    return locked
```

- [ ] **Step 4: Simplify `write_values` (remove the placeholder churn)**

The text branch above was written the long way to keep the diff explicit. Replace the whole `else` branch body with the two clean lines, and move the import to the module header:

At the top of the file, extend the pypdf import to:

```python
from pypdf.generic import (
    BooleanObject, DictionaryObject, NameObject, NumberObject, TextStringObject,
)
```

and replace the `else:` branch of the loop with:

```python
            else:
                annot[NameObject("/V")] = TextStringObject(str(value))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python .claude/skills/uqac-forms/scripts/Test/test_fill_form.py`
Expected: PASS, 16 tests.

- [ ] **Step 6: Commit**

```bash
git add .claude/skills/uqac-forms/scripts/fill_form.py \
        .claude/skills/uqac-forms/scripts/Test/test_fill_form.py
git commit -m "feat(uqac-forms): write values, request appearances, lock non-signature fields"
```

---

## Task 3: The fill pipeline, gated on a fresh map

**Files:**

- Modify: `.claude/skills/uqac-forms/scripts/fill_form.py`
- Test: `.claude/skills/uqac-forms/scripts/Test/test_fill_form.py`

**Interfaces:**

- Consumes: everything above; `require_fresh_map`, `StaleMapError`, `load_registry`, `fetch_form` from RT-1; `load_map` from RT-2.
- Produces:
  - `fill(form_id: str, profile: dict, out_path: str, cache_dir: str = DEFAULT_CACHE_DIR, maps_dir: str = MAPS_DIR, flatten: bool = True, pdf_path: str | None = None) -> dict[str, Any]` returning `{"form_id", "out", "filled": int, "skipped": list[str], "flattened": int}`. `pdf_path` overrides the cached download and exists so tests stay offline.

- [ ] **Step 1: Write the failing test**

Append to `.claude/skills/uqac-forms/scripts/Test/test_fill_form.py`, above the `if __name__` block:

```python
class TestFillPipeline(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.maps = os.path.join(self.tmp.name, "maps")
        os.makedirs(self.maps, exist_ok=True)
        self.pdf = make_form_pdf(
            os.path.join(self.tmp.name, "form.pdf"),
            [_widget("Nom", "/Tx", (10, 700, 200, 720)),
             _widget("no_matricule", "/Tx", (10, 670, 200, 690)),
             _widget("Signature_directeur", "/Sig", (300, 100, 500, 160))],
        )
        self.out = os.path.join(self.tmp.name, "out", "filled.pdf")
        doc = field_map.build_scaffold("mth-inscription-sujet", self.pdf)
        for field in doc["fields"]:
            field["target"] = {"Nom": "student.nom",
                               "no_matricule": "student.code_permanent",
                               "Signature_directeur": field_map.UNMAPPED_TARGET}[field["name"]]
        doc["status"] = "ok"
        field_map.write_map(doc, self.maps)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_fill_writes_the_output_and_reports_counts(self) -> None:
        result = fill_form.fill("mth-inscription-sujet", PROFILE, self.out,
                                maps_dir=self.maps, pdf_path=self.pdf)
        self.assertTrue(os.path.isfile(self.out))
        self.assertEqual(result["filled"], 2)
        self.assertIn("Signature_directeur", result["skipped"])
        self.assertEqual(result["flattened"], 2)

    def test_fill_creates_the_output_directory(self) -> None:
        fill_form.fill("mth-inscription-sujet", PROFILE, self.out,
                       maps_dir=self.maps, pdf_path=self.pdf)
        self.assertTrue(os.path.isdir(os.path.dirname(self.out)))

    def test_fill_refuses_a_stale_map_and_names_the_form(self) -> None:
        form_registry.mark_map_stale("mth-inscription-sujet", "sha256 changed", self.maps)
        with self.assertRaises(form_registry.StaleMapError) as ctx:
            fill_form.fill("mth-inscription-sujet", PROFILE, self.out,
                           maps_dir=self.maps, pdf_path=self.pdf)
        self.assertIn("mth-inscription-sujet", str(ctx.exception))
        self.assertFalse(os.path.exists(self.out))

    def test_fill_refuses_a_missing_map(self) -> None:
        with self.assertRaises(form_registry.StaleMapError):
            fill_form.fill("srf-rapport-depenses", PROFILE, self.out,
                           maps_dir=self.maps, pdf_path=self.pdf)

    def test_no_flatten_leaves_the_fields_editable(self) -> None:
        fill_form.fill("mth-inscription-sujet", PROFILE, self.out,
                       maps_dir=self.maps, pdf_path=self.pdf, flatten=False)
        reader = PdfReader(self.out)
        annot = [a.get_object() for a in reader.pages[0]["/Annots"]
                 if str(a.get_object().get("/T")) == "Nom"][0]
        self.assertFalse(int(annot.get("/Ff", 0)) & fill_form.READONLY_FLAG)

    def test_no_field_value_is_ever_logged(self) -> None:
        with self.assertLogs(fill_form.logger, level="INFO") as captured:
            fill_form.fill("mth-inscription-sujet", PROFILE, self.out,
                           maps_dir=self.maps, pdf_path=self.pdf)
        joined = "\n".join(captured.output)
        self.assertNotIn("TREM99010199", joined)
        self.assertNotIn("Tremblay", joined)
```

Add `import form_registry  # noqa: E402` to the test imports.

- [ ] **Step 2: Run test to verify it fails**

Run: `python .claude/skills/uqac-forms/scripts/Test/test_fill_form.py`
Expected: FAIL with `AttributeError: module 'fill_form' has no attribute 'fill'`.

- [ ] **Step 3: Write the minimal implementation**

Append to `.claude/skills/uqac-forms/scripts/fill_form.py`:

```python
def fill(form_id: str, profile: dict[str, Any], out_path: str,
         cache_dir: str = form_registry.DEFAULT_CACHE_DIR,
         maps_dir: str = form_registry.MAPS_DIR,
         flatten: bool = True, pdf_path: str | None = None) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run the whole fill pipeline for one form, in the only order that works:
        refuse a stale map, resolve the values, write them, request appearances,
        lock every non-signature field, and write the output. Signing is RT-4's
        job and happens after this, as an incremental update.

    Inputs:
        form_id (str): registry id
        profile (dict): the profile document
        out_path (str): destination PDF (its directory is created)
        cache_dir (str): cache directory for the official PDF
        maps_dir (str): directory holding the field maps
        flatten (bool): lock non-signature fields (default True)
        pdf_path (str | None): use this PDF instead of the cached download; the
            offline tests pass their own generated file here

    Outputs:
        result (dict): {form_id, out, filled, skipped, flattened}

    Raises:
        StaleMapError when the field map is missing or stale.
        RuntimeError when the official PDF cannot be obtained.
    --------------------------------------------------------------------------
    """
    # Gate first: never produce an official-looking document from a map that no
    # longer describes the file UQAC serves.
    form_registry.require_fresh_map(form_id, maps_dir)

    source = pdf_path
    if source is None:
        registry = form_registry.load_registry()
        if form_id not in registry:
            raise RuntimeError(f"unknown form id: {form_id}")
        source = form_registry.fetch_form(registry[form_id], cache_dir)
        if source is None:
            raise RuntimeError(f"could not obtain the official PDF for {form_id}")

    document = field_map.load_map(form_id, maps_dir)
    values, skipped = resolve_values(document, profile)

    writer = PdfWriter(clone_from=source)
    written = write_values(writer, values)
    set_need_appearances(writer)
    flattened = lock_non_signature_fields(writer) if flatten else 0

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as handle:
        writer.write(handle)

    logger.info("[UQAC-FORMS] %s: filled %d, skipped %d, locked %d -> %s",
                form_id, written, len(skipped), flattened, out_path)
    return {"form_id": form_id, "out": out_path, "filled": written,
            "skipped": skipped, "flattened": flattened}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python .claude/skills/uqac-forms/scripts/Test/test_fill_form.py`
Expected: PASS, 22 tests.

- [ ] **Step 5: Add the command-line interface**

Append to `.claude/skills/uqac-forms/scripts/fill_form.py`:

```python
def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Fill a registered UQAC form from a profile")
    parser.add_argument("form_id")
    parser.add_argument("--profile", required=True, help="path to the profile JSON")
    parser.add_argument("--out", default=None, help="output PDF (default out/<form_id>_rempli.pdf)")
    parser.add_argument("--cache-dir", default=form_registry.DEFAULT_CACHE_DIR)
    parser.add_argument("--maps-dir", default=form_registry.MAPS_DIR)
    parser.add_argument("--no-flatten", action="store_true",
                        help="leave the fields editable (draft review)")
    args = parser.parse_args()

    out = args.out or os.path.join("out", f"{args.form_id}_rempli.pdf")
    try:
        result = fill(args.form_id, load_profile(args.profile), out,
                      cache_dir=args.cache_dir, maps_dir=args.maps_dir,
                      flatten=not args.no_flatten)
    except form_registry.StaleMapError as exc:
        raise SystemExit(f"refusing to fill: {exc}")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Verify against a real form**

Run (needs network on first run, then the cache serves):

```powershell
python .claude/skills/uqac-forms/scripts/fill_form.py srf-demande-avance-voyage `
  --profile .claude/skills/uqac-forms/samples/profile.sample.json `
  --out out/srf-demande-avance-voyage_rempli.pdf
```

Then open `out/srf-demande-avance-voyage_rempli.pdf` and confirm by eye: the values are visible (not only present in the file), the checkboxes that should be ticked are ticked, no field shows a stray `None`, and the signature area is still an empty signature field.

- [ ] **Step 7: Update SKILL.md**

Add to `.claude/skills/uqac-forms/SKILL.md`:

````markdown
## Filling

```
python .claude/skills/uqac-forms/scripts/fill_form.py <form_id> --profile <profile.json> [--out out/<name>.pdf] [--no-flatten]
```

The order is fixed and not negotiable: fill, request appearances, lock the
non-signature fields, then sign last as an incremental update. Flattening
destroys signature fields, so the filler never touches a `/Sig` widget and never
signs.

`pypdf` has no appearance-burning flatten. "Flatten" here means every
non-signature widget is locked read-only with its value and appearance stream
intact, which is what an administrative reviewer needs and what keeps the
signature field usable.

A stale or missing field map is refused by name: nothing is written, because a
wrong-looking official form is worse than no form. `--no-flatten` produces an
editable draft for review.

The sample profile at `samples/profile.sample.json` is entirely synthetic. A real
profile is never committed.
````

- [ ] **Step 8: Update `.claude/rules/testing.md`**

Add to the offline test list:

```powershell
python .claude/skills/uqac-forms/scripts/Test/test_fill_form.py   # value resolution, write, appearances, lock, stale-map refusal
```

- [ ] **Step 9: Run the full offline suite**

```powershell
python .claude/skills/uqac-forms/scripts/Test/test_fill_form.py
python .claude/skills/uqac-forms/scripts/Test/test_field_map.py
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
git add .claude/skills/uqac-forms .claude/rules/testing.md
git commit -m "feat(uqac-forms): fill pipeline gated on a fresh field map, with CLI"
```

---

## Interfaces published by RT-3

| Name | Signature | Consumed by |
|---|---|---|
| `load_profile` | `load_profile(path: str) -> dict[str, Any]` | RT-5, TT-3 (through the service) |
| `resolve_values` | `resolve_values(document: dict, profile: dict) -> tuple[dict, list[str]]` | RT-5 |
| `write_values` | `write_values(writer: PdfWriter, values: dict) -> int` | RT-4 (not expected to call it, listed for completeness) |
| `set_need_appearances` | `set_need_appearances(writer: PdfWriter) -> None` | RT-4 |
| `lock_non_signature_fields` | `lock_non_signature_fields(writer: PdfWriter) -> int` | RT-4 |
| `fill` | `fill(form_id, profile, out_path, cache_dir=DEFAULT_CACHE_DIR, maps_dir=MAPS_DIR, flatten=True, pdf_path=None) -> dict` | RT-5 `POST /forms/{form_id}/fill` |
| `READONLY_FLAG` | `int = 1` | RT-4 |

`fill` result shape: `{"form_id": str, "out": str, "filled": int, "skipped": list[str], "flattened": int}`.

---

## Acceptance

```powershell
python .claude/skills/uqac-forms/scripts/Test/test_fill_form.py
python .claude/skills/uqac-forms/scripts/fill_form.py srf-demande-avance-voyage --profile .claude/skills/uqac-forms/samples/profile.sample.json
pip-audit -r .claude/skills/uqac-forms/scripts/requirements.txt --strict
```

Plus the RT-1 and RT-2 suites and the five existing offline suites in `.claude/rules/testing.md`, which must stay green.

---

## Task 4: Documentation and the pull request

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

In the `### uqac-forms` subsection, add:

```markdown
- `.claude/skills/uqac-forms/scripts/fill_form.py` - profile plus map to a filled PDF
- `.claude/skills/uqac-forms/samples/profile.sample.json` - synthetic sample profile
```

Add two sentences a reader must not have to discover by reading code. First, the
order is fixed: fill, request appearances, lock the non-signature fields, sign
last as an incremental update, because flattening destroys signature fields.
Second, `pypdf` has no appearance-burning flatten, so "flatten" here means every
non-signature widget is locked read-only with its value and appearance stream
intact. State the limitation plainly rather than letting a reader assume a burn-in.

In the File-Locations tree, extend the `uqac-forms` entry with `fill_form.py`,
`Test\test_fill_form.py`, and `samples\profile.sample.json`.

- [ ] **Step 2: Update `Architecture.md`**

Extend the `s10` node label to name the three scripts:

```
    s10["uqac-forms<br/>form_registry.py . field_map.py . fill_form.py"]
```

In the Notes, add one bullet stating the ordering rule and the stale-map gate: the
filler refuses by name rather than emitting an official-looking document from a map
that no longer describes the file UQAC serves.

- [ ] **Step 3: Update `NEW_ARCHITECTURE.md`**

`NEW_ARCHITECTURE.md` is committed identically to `main` in both ResearchTools and
ThesisTracker. Edit only what this unit owns, and keep the wording identical in both
checkouts so the two copies never drift.

1. In the section 9 unit table, append ` Delivered <YYYY-MM-DD>.` to the **RT-3** row's
   deliverable cell.
2. Section 5.1 (the fill sequence diagram) describes what this unit implements, including
   the stale-map 409 branch. Read it against the delivered `fill_form.py` and correct any
   step that differs. Section 7 (the form lifecycle) is TT-2's to verify, not this unit's.
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
git commit -m "docs(uqac-forms): record RT-3 in the inventories"
```

- [ ] **Step 6: Open the pull request**

`gh` is **not installed** on this machine, and `GITHUB_TOKEN` carries `read:user` only,
so neither the CLI nor that token can open a pull request. Do not try to install `gh`.
The OAuth token in the Windows Credential Manager has `repo` scope and is sufficient.
Retrieve it per command: never write it to a file, never echo it, never commit it.

```bash
git push -u origin feat/uqac-forms-filler

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
  "title": "[RT-3] uqac-forms: form filler",
  "head": "feat/uqac-forms-filler",
  "base": "main",
  "body": "Closes #6\n\n<what the unit delivers, in three or four lines>\n\n**Depends on.** RT-2 (`feat/uqac-forms-field-map`), which depends on RT-1.\n\n**Acceptance run.** <paste the commands from the acceptance block and their real result, not a summary>\n\n**Reviewer must check by hand.** <the manual verification steps of this plan, or 'none'>"
}
```

If a permission classifier blocks the command that reads the token, open the pull request
in the browser instead and paste the same title and body:

```
https://github.com/LARi-UQAC/ResearchTools/compare/main...feat/uqac-forms-filler?expand=1
```

Then delete `pr-body.json` from the scratchpad.

**Do not merge your own pull request.** Merging to `main` is the human gate. RT-4 is blocked behind this unit; say so in the body.

- [ ] **Step 7: Report**

State the pull request URL, the acceptance commands you ran with their real output, and
anything you could not verify. A test you did not run is not a test that passed.
