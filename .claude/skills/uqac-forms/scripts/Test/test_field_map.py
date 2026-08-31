"""
test_field_map.py - Offline unit tests for field_map.py.

No network and no committed fixture: each test builds its own AcroForm PDF in a
temporary directory with pypdf, so the suite runs anywhere pypdf is installed.

Two groups matter more than the rest. The name tests exist because TT-8 stores
what dump_widgets returns and RT-3 fills by exactly that key, so a name this
code tidies is a field nobody can ever fill again. The diff tests exist because
TT-8 ships the same function in Node, and the two must report the same thing.

Run with the project Python:
    python .claude/skills/uqac-forms/scripts/Test/test_field_map.py
"""

import copy
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import field_map  # noqa: E402

from pypdf import PdfWriter  # noqa: E402
from pypdf.generic import (  # noqa: E402
    ArrayObject, DictionaryObject, FloatObject, NameObject, NumberObject,
    TextStringObject,
)

RADIO_FLAG = 1 << 15
READONLY_FLAG = 1


def _widget(name: str, field_type: str,
            rect: tuple[float, float, float, float] = (10, 700, 200, 720),
            on_states: list[str] | None = None,
            flags: int = 0) -> DictionaryObject:
    """Build one AcroForm widget annotation, on-states declared in /AP /N."""
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


def make_form_pdf(path: str, widgets_per_page: list) -> str:
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


class _PdfTestCase(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def build(self, widgets_per_page: list, name: str = "form.pdf") -> str:
        return make_form_pdf(os.path.join(self.tmp.name, name), widgets_per_page)


class TestDumpWidgets(_PdfTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.pdf = self.build([
            [_widget("Nom", "/Tx"),
             _widget("code permanent", "/Tx", (10, 670, 200, 690))],
            [_widget("Cheque_Payable_a", "/Tx", (10, 640, 200, 660)),
             _widget("mode_transport", "/Btn", (10, 610, 30, 630),
                     on_states=["Avion"])],
        ])

    def test_every_widget_is_returned_in_document_order(self) -> None:
        names = [w["name"] for w in field_map.dump_widgets(self.pdf)]
        self.assertEqual(
            names, ["Nom", "code permanent", "Cheque_Payable_a", "mode_transport"])

    def test_page_numbers_are_one_based(self) -> None:
        by_name = {w["name"]: w for w in field_map.dump_widgets(self.pdf)}
        self.assertEqual(by_name["Nom"]["page"], 1)
        self.assertEqual(by_name["Cheque_Payable_a"]["page"], 2)

    def test_the_rect_is_four_numbers(self) -> None:
        by_name = {w["name"]: w for w in field_map.dump_widgets(self.pdf)}
        self.assertEqual(by_name["Nom"]["rect"], [10.0, 700.0, 200.0, 720.0])

    def test_every_widget_carries_the_full_key_set(self) -> None:
        expected = {"name", "name_hex", "type", "page", "rect", "on_states", "readonly"}
        for widget in field_map.dump_widgets(self.pdf):
            self.assertEqual(set(widget), expected)

    def test_a_pdf_with_no_widgets_returns_an_empty_list(self) -> None:
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        blank = os.path.join(self.tmp.name, "blank.pdf")
        with open(blank, "wb") as handle:
            writer.write(handle)
        self.assertEqual(field_map.dump_widgets(blank), [])


class TestNamesAreByteExact(_PdfTestCase):
    """A name this code tidies is a field that can never be filled again."""

    def test_names_are_never_normalized(self) -> None:
        pdf = self.build([[_widget("code permanent", "/Tx")]])
        names = [w["name"] for w in field_map.dump_widgets(pdf)]
        self.assertIn("code permanent", names)
        self.assertNotIn("code_permanent", names)
        self.assertNotIn("Code permanent", names)

    def test_a_trailing_space_survives(self) -> None:
        # Real UQAC forms carry these. Stripping one silently renames the field.
        pdf = self.build([[_widget("Nom ", "/Tx")]])
        self.assertEqual(field_map.dump_widgets(pdf)[0]["name"], "Nom ")

    def test_accents_survive(self) -> None:
        pdf = self.build([[_widget("Prenom_et_nom_du_directeur_de_recherche", "/Tx"),
                           _widget("Date_de_depot_prevue", "/Tx", (10, 670, 200, 690)),
                           _widget("Numero_d_etudiant", "/Tx", (10, 640, 200, 660))]])
        names = [w["name"] for w in field_map.dump_widgets(pdf)]
        self.assertEqual(len(names), 3)

    def test_two_names_differing_only_by_case_stay_distinct(self) -> None:
        pdf = self.build([[_widget("Signature", "/Tx"),
                           _widget("signature", "/Tx", (10, 670, 200, 690))]])
        names = [w["name"] for w in field_map.dump_widgets(pdf)]
        self.assertEqual(sorted(names), ["Signature", "signature"])

    def test_name_hex_records_the_exact_bytes(self) -> None:
        pdf = self.build([[_widget("Nom ", "/Tx")]])
        widget = field_map.dump_widgets(pdf)[0]
        self.assertEqual(
            bytes.fromhex(widget["name_hex"]).decode("utf-8"), "Nom ")

    def test_name_hex_distinguishes_names_that_print_alike(self) -> None:
        # The whole point: "Nom" and "Nom " look identical in a report.
        pdf = self.build([[_widget("Nom", "/Tx"),
                           _widget("Nom ", "/Tx", (10, 670, 200, 690))]])
        hexes = {w["name_hex"] for w in field_map.dump_widgets(pdf)}
        self.assertEqual(len(hexes), 2)


class TestOnStates(_PdfTestCase):
    """Writing /Yes to a box whose on-state is /Oui leaves it silently unchecked."""

    def test_a_checkbox_reports_its_own_on_state(self) -> None:
        pdf = self.build([[_widget("accepte", "/Btn", on_states=["Oui"])]])
        self.assertEqual(field_map.dump_widgets(pdf)[0]["on_states"], ["Oui"])

    def test_off_is_never_reported_as_an_on_state(self) -> None:
        pdf = self.build([[_widget("accepte", "/Btn", on_states=["Oui"])]])
        self.assertNotIn("Off", field_map.dump_widgets(pdf)[0]["on_states"])

    def test_a_radio_group_reports_every_choice(self) -> None:
        pdf = self.build([[_widget("transport", "/Btn",
                                   on_states=["Avion", "Train", "Voiture"],
                                   flags=RADIO_FLAG)]])
        self.assertEqual(sorted(field_map.dump_widgets(pdf)[0]["on_states"]),
                         ["Avion", "Train", "Voiture"])

    def test_a_text_field_has_no_on_states(self) -> None:
        pdf = self.build([[_widget("Nom", "/Tx")]])
        self.assertEqual(field_map.dump_widgets(pdf)[0]["on_states"], [])

    def test_a_button_without_an_appearance_dictionary_is_not_a_crash(self) -> None:
        pdf = self.build([[_widget("accepte", "/Btn")]])
        self.assertEqual(field_map.dump_widgets(pdf)[0]["on_states"], [])

    def test_a_text_field_with_an_appearance_stream_reports_no_on_states(self) -> None:
        # Regression, found on the real inscription-sujet form and on nothing
        # synthetic. A text field's /AP /N is a single appearance STREAM, not a
        # dictionary of states, so reading its keys invented six on-states
        # (BBox, FormType, Matrix, Resources, Subtype, Type) on 25 of 56 fields.
        # Only a button has on-states, whatever /AP happens to contain.
        annot = _widget("Courriel", "/Tx")
        stream_like = DictionaryObject()
        for key in ("/BBox", "/FormType", "/Matrix", "/Resources", "/Subtype", "/Type"):
            stream_like[NameObject(key)] = DictionaryObject()
        appearance = DictionaryObject()
        appearance[NameObject("/N")] = stream_like
        annot[NameObject("/AP")] = appearance

        pdf = self.build([[annot]])
        widget = field_map.dump_widgets(pdf)[0]
        self.assertEqual(widget["type"], "text")
        self.assertEqual(widget["on_states"], [])


class TestTypes(_PdfTestCase):

    def test_each_acroform_type_maps_to_the_vocabulary(self) -> None:
        pdf = self.build([[
            _widget("txt", "/Tx"),
            _widget("box", "/Btn", (10, 670, 30, 690), on_states=["Oui"]),
            _widget("radio", "/Btn", (10, 640, 30, 660),
                    on_states=["A", "B"], flags=RADIO_FLAG),
            _widget("choice", "/Ch", (10, 610, 200, 630)),
            _widget("sig", "/Sig", (10, 580, 200, 600)),
        ]])
        by_name = {w["name"]: w["type"] for w in field_map.dump_widgets(pdf)}
        self.assertEqual(by_name, {"txt": "text", "box": "checkbox",
                                   "radio": "radio", "choice": "choice",
                                   "sig": "signature"})

    def test_an_unrecognized_type_is_unknown_rather_than_a_crash(self) -> None:
        pdf = self.build([[_widget("odd", "/Zz")]])
        self.assertEqual(field_map.dump_widgets(pdf)[0]["type"], "unknown")

    def test_readonly_is_reported(self) -> None:
        pdf = self.build([[_widget("locked", "/Tx", flags=READONLY_FLAG),
                           _widget("open", "/Tx", (10, 670, 200, 690))]])
        by_name = {w["name"]: w["readonly"] for w in field_map.dump_widgets(pdf)}
        self.assertTrue(by_name["locked"])
        self.assertFalse(by_name["open"])


class TestAcceptsBytes(_PdfTestCase):
    """TT-8 holds the PDF as bytea and RT-5 is handed a body, not a filename."""

    def test_bytes_and_a_path_give_the_same_answer(self) -> None:
        pdf = self.build([[_widget("Nom", "/Tx"),
                           _widget("box", "/Btn", (10, 670, 30, 690),
                                   on_states=["Oui"])]])
        with open(pdf, "rb") as handle:
            from_bytes = field_map.dump_widgets(handle.read())
        self.assertEqual(from_bytes, field_map.dump_widgets(pdf))


class TestDiffWidgets(unittest.TestCase):
    """The four keys TT-8's diffWidgets returns, with the same meanings."""

    @staticmethod
    def w(name: str, type_: str = "text", page: int = 1) -> dict:
        return {"name": name, "name_hex": name.encode().hex(), "type": type_,
                "page": page, "rect": [0, 0, 1, 1], "on_states": [], "readonly": False}

    def test_an_unchanged_form_reports_nothing(self) -> None:
        before = [self.w("Nom"), self.w("Date")]
        self.assertEqual(
            field_map.diff_widgets(before, list(before)),
            {"added": [], "removed": [], "relocated": [], "retyped": [],
             "restated": []})

    def test_added_and_removed(self) -> None:
        result = field_map.diff_widgets([self.w("Nom")], [self.w("Date")])
        self.assertEqual(result["added"], ["Date"])
        self.assertEqual(result["removed"], ["Nom"])

    def test_a_moved_field_is_relocated_not_an_add_plus_a_remove(self) -> None:
        # Its stored row is still correct; only the page changed.
        result = field_map.diff_widgets(
            [self.w("Nom", page=1)], [self.w("Nom", page=2)])
        self.assertEqual(result["relocated"], ["Nom"])
        self.assertEqual(result["added"], [])
        self.assertEqual(result["removed"], [])

    def test_a_changed_type_is_retyped(self) -> None:
        result = field_map.diff_widgets(
            [self.w("accepte", "text")], [self.w("accepte", "checkbox")])
        self.assertEqual(result["retyped"], ["accepte"])
        self.assertEqual(result["added"], [])

    def test_a_field_can_be_both_relocated_and_retyped(self) -> None:
        result = field_map.diff_widgets(
            [self.w("x", "text", 1)], [self.w("x", "checkbox", 2)])
        self.assertEqual(result["relocated"], ["x"])
        self.assertEqual(result["retyped"], ["x"])

    def test_every_list_is_sorted(self) -> None:
        result = field_map.diff_widgets(
            [], [self.w("z"), self.w("a"), self.w("m")])
        self.assertEqual(result["added"], ["a", "m", "z"])

    def test_empty_inputs_are_handled(self) -> None:
        self.assertEqual(
            field_map.diff_widgets([], []),
            {"added": [], "removed": [], "relocated": [], "retyped": [],
             "restated": []})

    def test_names_differing_only_by_a_trailing_space_are_two_fields(self) -> None:
        result = field_map.diff_widgets([self.w("Nom")], [self.w("Nom ")])
        self.assertEqual(result["added"], ["Nom "])
        self.assertEqual(result["removed"], ["Nom"])


    def test_a_renamed_on_state_is_restated(self) -> None:
        # Without this, /Oui becoming /Yes changes no name, page or type, so the
        # drift check passes it and every later fill leaves the box unchecked.
        before = [{**self.w("accepte", "checkbox"), "on_states": ["Oui"]}]
        after = [{**self.w("accepte", "checkbox"), "on_states": ["Yes"]}]
        result = field_map.diff_widgets(before, after)
        self.assertEqual(result["restated"], ["accepte"])
        self.assertEqual(result["added"], [])
        self.assertEqual(result["removed"], [])

    def test_an_unchanged_on_state_is_not_restated(self) -> None:
        before = [{**self.w("accepte", "checkbox"), "on_states": ["Oui"]}]
        self.assertEqual(
            field_map.diff_widgets(before, copy.deepcopy(before))["restated"], [])

    def test_on_state_order_is_not_a_rename(self) -> None:
        before = [{**self.w("t", "radio"), "on_states": ["Avion", "Train"]}]
        after = [{**self.w("t", "radio"), "on_states": ["Train", "Avion"]}]
        self.assertEqual(field_map.diff_widgets(before, after)["restated"], [])

    def test_the_stored_text_column_compares_equal_to_the_widget_list(self) -> None:
        # TT-8 stores on_states as a text column; RT-2 returns a list. The same
        # states in either shape must not read as a rename.
        before = [{**self.w("t", "radio"), "on_states": "Avion, Train"}]
        after = [{**self.w("t", "radio"), "on_states": ["Train", "Avion"]}]
        self.assertEqual(field_map.diff_widgets(before, after)["restated"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
