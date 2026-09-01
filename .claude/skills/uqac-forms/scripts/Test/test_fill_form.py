"""
test_fill_form.py - Offline unit tests for fill_form.py.

No network and no committed fixture: each test builds its own AcroForm PDF with
pypdf, fills it, and reads the result back with field_map.dump_widgets, so the
assertions are made against the document a viewer would open rather than against
the writer's in-memory objects.

The refusal tests matter most. A filler that silently drops a value produces a
form that looks complete and is not, which is the failure this whole skill
exists to prevent.

Run with the project Python:
    python .claude/skills/uqac-forms/scripts/Test/test_fill_form.py
"""

import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fill_form  # noqa: E402
import field_map  # noqa: E402

from pypdf import PdfReader, PdfWriter  # noqa: E402
from pypdf.generic import (  # noqa: E402
    ArrayObject, DictionaryObject, FloatObject, NameObject, NumberObject,
    TextStringObject,
)

RADIO_FLAG = 1 << 15


def _widget(name: str, field_type: str,
            rect: tuple = (10, 700, 200, 720),
            on_states: list | None = None,
            flags: int = 0) -> DictionaryObject:
    annot = DictionaryObject()
    annot.update({
        NameObject("/Type"): NameObject("/Annot"),
        NameObject("/Subtype"): NameObject("/Widget"),
        NameObject("/FT"): NameObject(field_type),
        NameObject("/T"): TextStringObject(name),
        NameObject("/Rect"): ArrayObject([FloatObject(v) for v in rect]),
    })
    if flags:
        annot[NameObject("/Ff")] = NumberObject(flags)
    if on_states is not None:
        normal = DictionaryObject()
        for state in on_states + ["Off"]:
            normal[NameObject(f"/{state}")] = DictionaryObject()
        appearance = DictionaryObject()
        appearance[NameObject("/N")] = normal
        annot[NameObject("/AP")] = appearance
    return annot


def form_bytes(widgets: list) -> bytes:
    """An AcroForm PDF carrying the given widgets on one page, as bytes."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    annots = ArrayObject()
    refs = []
    for widget in widgets:
        ref = writer._add_object(widget)
        refs.append(ref)
        annots.append(ref)
    page[NameObject("/Annots")] = annots
    # A real form declares its fields in the AcroForm dictionary, so the filler
    # is exercised against the structure it will actually meet.
    writer._root_object[NameObject("/AcroForm")] = DictionaryObject({
        NameObject("/Fields"): ArrayObject(refs),
    })
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def annots_of(pdf: bytes) -> dict:
    """Read the filled document back the way a viewer would."""
    reader = PdfReader(io.BytesIO(pdf))
    out = {}
    for page in reader.pages:
        for ref in page.get("/Annots") or []:
            annot = ref.get_object()
            name = annot.get("/T")
            if name is not None:
                out[str(name)] = annot
    return out


SIMPLE = [
    _widget("Nom", "/Tx"),
    _widget("code permanent", "/Tx", (10, 670, 200, 690)),
    _widget("accepte", "/Btn", (10, 640, 30, 660), on_states=["Oui"]),
    _widget("signature_etudiant", "/Sig", (10, 600, 200, 630)),
]


class TestWritesValues(unittest.TestCase):

    def test_a_text_value_is_written(self) -> None:
        out = fill_form.fill(form_bytes(SIMPLE), {"Nom": "Umuhoza"})
        self.assertEqual(str(annots_of(out)["Nom"]["/V"]), "Umuhoza")

    def test_the_result_is_a_pdf(self) -> None:
        out = fill_form.fill(form_bytes(SIMPLE), {"Nom": "Umuhoza"})
        self.assertTrue(out.startswith(b"%PDF"))

    def test_a_name_with_a_space_is_used_verbatim(self) -> None:
        # The key is the PDF's own name. Tidying it here means failing to find
        # the field it belongs to.
        out = fill_form.fill(form_bytes(SIMPLE), {"code permanent": "UMUJ12345678"})
        self.assertEqual(str(annots_of(out)["code permanent"]["/V"]), "UMUJ12345678")

    def test_fields_not_named_are_left_alone(self) -> None:
        out = fill_form.fill(form_bytes(SIMPLE), {"Nom": "Umuhoza"})
        self.assertIsNone(annots_of(out)["code permanent"].get("/V"))

    def test_the_count_of_written_widgets_is_returned_by_write_values(self) -> None:
        writer = PdfWriter(clone_from=io.BytesIO(form_bytes(SIMPLE)))
        written = fill_form.write_values(writer, {"Nom": "a", "code permanent": "b"})
        self.assertEqual(written, 2)

    def test_an_empty_value_dictionary_returns_the_document_unharmed(self) -> None:
        out = fill_form.fill(form_bytes(SIMPLE), {})
        self.assertEqual(sorted(annots_of(out)), sorted(annots_of(form_bytes(SIMPLE))))


class TestCheckboxOnStates(unittest.TestCase):
    """The same failure RT-2's on_states prevents, one stage later."""

    def test_a_checkbox_is_set_to_its_own_on_state(self) -> None:
        out = fill_form.fill(form_bytes(SIMPLE), {"accepte": "Oui"})
        annot = annots_of(out)["accepte"]
        self.assertEqual(str(annot["/V"]), "/Oui")

    def test_the_appearance_state_is_set_too(self) -> None:
        # A viewer draws the appearance named by /AS. Setting /V alone leaves
        # the box looking unchecked whatever the value says.
        out = fill_form.fill(form_bytes(SIMPLE), {"accepte": "Oui"})
        self.assertEqual(str(annots_of(out)["accepte"]["/AS"]), "/Oui")

    def test_a_leading_slash_in_the_value_is_accepted(self) -> None:
        out = fill_form.fill(form_bytes(SIMPLE), {"accepte": "/Oui"})
        self.assertEqual(str(annots_of(out)["accepte"]["/AS"]), "/Oui")

    def test_a_value_that_is_not_an_on_state_is_refused(self) -> None:
        # Writing /Yes to a box whose on-state is /Oui leaves it unchecked on a
        # document that then looks complete.
        with self.assertRaises(fill_form.FillError) as caught:
            fill_form.fill(form_bytes(SIMPLE), {"accepte": "Yes"})
        self.assertIn("Oui", str(caught.exception))

    def test_a_checkbox_can_be_cleared_with_off(self) -> None:
        out = fill_form.fill(form_bytes(SIMPLE), {"accepte": "Off"})
        self.assertEqual(str(annots_of(out)["accepte"]["/AS"]), "/Off")

    def test_a_radio_takes_any_of_its_own_states(self) -> None:
        widgets = [_widget("transport", "/Btn", on_states=["Avion", "Train"],
                           flags=RADIO_FLAG)]
        out = fill_form.fill(form_bytes(widgets), {"transport": "Train"})
        self.assertEqual(str(annots_of(out)["transport"]["/AS"]), "/Train")


class TestRefusals(unittest.TestCase):

    def test_a_value_for_a_field_the_pdf_does_not_have_is_refused(self) -> None:
        # The caller believes it filled something. A blank where the value
        # should be is worse than an obvious failure.
        with self.assertRaises(fill_form.FillError) as caught:
            fill_form.fill(form_bytes(SIMPLE), {"champ_inexistant": "x"})
        self.assertIn("champ_inexistant", str(caught.exception))

    def test_the_refusal_names_every_missing_field_not_just_the_first(self) -> None:
        with self.assertRaises(fill_form.FillError) as caught:
            fill_form.fill(form_bytes(SIMPLE), {"absent_a": "1", "absent_b": "2"})
        message = str(caught.exception)
        self.assertIn("absent_a", message)
        self.assertIn("absent_b", message)

    def test_nothing_is_returned_when_a_value_is_refused(self) -> None:
        with self.assertRaises(fill_form.FillError):
            fill_form.fill(form_bytes(SIMPLE), {"Nom": "ok", "absent": "x"})

    def test_a_body_that_is_not_a_pdf_is_refused(self) -> None:
        with self.assertRaises(Exception):
            fill_form.fill(b"<html>not a pdf</html>", {"Nom": "x"})


class TestNeedAppearances(unittest.TestCase):
    """AcroForm values do not render without appearance streams."""

    def test_need_appearances_is_set(self) -> None:
        out = fill_form.fill(form_bytes(SIMPLE), {"Nom": "Umuhoza"})
        acro = PdfReader(io.BytesIO(out)).trailer["/Root"]["/AcroForm"]
        self.assertTrue(bool(acro.get("/NeedAppearances")))

    def test_it_is_set_even_when_nothing_was_written(self) -> None:
        out = fill_form.fill(form_bytes(SIMPLE), {})
        acro = PdfReader(io.BytesIO(out)).trailer["/Root"]["/AcroForm"]
        self.assertTrue(bool(acro.get("/NeedAppearances")))


class TestSelectiveLocking(unittest.TestCase):
    """A UQAC form is filled by several people in turn."""

    def locked(self, pdf: bytes, name: str) -> bool:
        flags = int(annots_of(pdf)[name].get("/Ff", 0))
        return bool(flags & fill_form.READONLY_FLAG)

    def test_only_the_named_fields_are_locked(self) -> None:
        out = fill_form.fill(form_bytes(SIMPLE), {"Nom": "Umuhoza"},
                             flatten_fields=["Nom"])
        self.assertTrue(self.locked(out, "Nom"))
        self.assertFalse(self.locked(out, "code permanent"),
                         "a later step must still be able to write this")

    def test_none_locks_nothing(self) -> None:
        out = fill_form.fill(form_bytes(SIMPLE), {"Nom": "Umuhoza"})
        self.assertFalse(self.locked(out, "Nom"))

    def test_a_signature_field_is_never_locked_even_when_named(self) -> None:
        # Locking one destroys the field a later signer needs.
        out = fill_form.fill(form_bytes(SIMPLE), {},
                             flatten_fields=["signature_etudiant"])
        self.assertFalse(self.locked(out, "signature_etudiant"))

    def test_the_signature_field_survives_locking_of_everything_else(self) -> None:
        out = fill_form.fill(form_bytes(SIMPLE), {},
                             flatten_fields=["Nom", "code permanent", "accepte",
                                             "signature_etudiant"])
        self.assertIn("signature_etudiant", annots_of(out))

    def test_locking_reports_how_many_widgets_it_locked(self) -> None:
        writer = PdfWriter(clone_from=io.BytesIO(form_bytes(SIMPLE)))
        # The signature is named but never counted, because it is never locked.
        n = fill_form.lock_fields(writer, ["Nom", "signature_etudiant"])
        self.assertEqual(n, 1)

    def test_locking_a_field_that_does_not_exist_is_refused(self) -> None:
        with self.assertRaises(fill_form.FillError):
            fill_form.fill(form_bytes(SIMPLE), {}, flatten_fields=["absent"])


class TestTheResultIsReadableByTheRestOfTheSkill(unittest.TestCase):
    """RT-2 reads what RT-3 writes, so the two must agree on the document."""

    def test_dump_widgets_still_sees_every_field_after_filling(self) -> None:
        before = field_map.dump_widgets(form_bytes(SIMPLE))
        after = field_map.dump_widgets(
            fill_form.fill(form_bytes(SIMPLE), {"Nom": "Umuhoza"},
                           flatten_fields=["Nom"]))
        self.assertEqual([w["name"] for w in before], [w["name"] for w in after])

    def test_filling_is_not_reported_as_drift(self) -> None:
        # Filling a form must not look like UQAC replacing it.
        before = field_map.dump_widgets(form_bytes(SIMPLE))
        after = field_map.dump_widgets(
            fill_form.fill(form_bytes(SIMPLE), {"Nom": "Umuhoza", "accepte": "Oui"}))
        self.assertEqual(
            field_map.diff_widgets(before, after),
            {"added": [], "removed": [], "relocated": [], "retyped": [],
             "restated": []})

    def test_a_locked_field_is_reported_readonly_by_dump_widgets(self) -> None:
        after = field_map.dump_widgets(
            fill_form.fill(form_bytes(SIMPLE), {"Nom": "x"}, flatten_fields=["Nom"]))
        by_name = {w["name"]: w for w in after}
        self.assertTrue(by_name["Nom"]["readonly"])
        self.assertFalse(by_name["code permanent"]["readonly"])


class TestFillingTwiceInSequence(unittest.TestCase):
    """The multi-step case: a student fills, then a professor does."""

    def test_a_second_pass_adds_values_without_disturbing_the_first(self) -> None:
        step1 = fill_form.fill(form_bytes(SIMPLE), {"Nom": "Umuhoza"},
                               flatten_fields=["Nom"])
        step2 = fill_form.fill(step1, {"code permanent": "UMUJ12345678"})
        annots = annots_of(step2)
        self.assertEqual(str(annots["Nom"]["/V"]), "Umuhoza")
        self.assertEqual(str(annots["code permanent"]["/V"]), "UMUJ12345678")

    def test_a_field_locked_in_the_first_pass_stays_locked(self) -> None:
        step1 = fill_form.fill(form_bytes(SIMPLE), {"Nom": "Umuhoza"},
                               flatten_fields=["Nom"])
        step2 = fill_form.fill(step1, {"code permanent": "x"})
        flags = int(annots_of(step2)["Nom"].get("/Ff", 0))
        self.assertTrue(flags & fill_form.READONLY_FLAG)


class TestSignLast(unittest.TestCase):
    """Filling rewrites the file, so filling after signing voids the signature."""

    def signed_form(self) -> bytes:
        sig = _widget("signature_etudiant", "/Sig", (10, 600, 200, 630))
        sig[NameObject("/V")] = TextStringObject("a signature blob")
        return form_bytes([_widget("Nom", "/Tx"), sig])

    def test_filling_an_already_signed_document_is_refused(self) -> None:
        with self.assertRaises(fill_form.FillError) as caught:
            fill_form.fill(self.signed_form(), {"Nom": "Umuhoza"})
        self.assertIn("already signed", str(caught.exception))

    def test_the_refusal_names_the_signature_field(self) -> None:
        with self.assertRaises(fill_form.FillError) as caught:
            fill_form.fill(self.signed_form(), {"Nom": "x"})
        self.assertIn("signature_etudiant", str(caught.exception))

    def test_an_unsigned_signature_field_does_not_block_filling(self) -> None:
        # The field exists on every UQAC form from the start. Only a signature
        # that has actually been applied blocks a later fill.
        out = fill_form.fill(form_bytes(SIMPLE), {"Nom": "Umuhoza"})
        self.assertEqual(str(annots_of(out)["Nom"]["/V"]), "Umuhoza")

    def test_the_output_is_a_rewrite_not_an_incremental_update(self) -> None:
        # The fact that makes the refusal above necessary. If this ever becomes
        # an incremental update, the refusal can be relaxed, so it is asserted
        # rather than assumed.
        original = form_bytes(SIMPLE)
        out = fill_form.fill(original, {"Nom": "x"})
        self.assertNotEqual(out[:len(original)], original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
