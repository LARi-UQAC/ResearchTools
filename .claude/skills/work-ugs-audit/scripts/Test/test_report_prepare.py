"""
Offline tests of report_prepare.py. The reports are fictitious PDFs built in a temporary folder.
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS.parent.parent / "figure-review" / "scripts" / "Test"))

import fitz  # noqa: E402
import report_prepare  # noqa: E402
import ugs_tables  # noqa: E402
import ugs_config  # noqa: E402
from report_prepare import PrepareError, main, prepare, skipped_count  # noqa: E402
from text_quality import OcrUnavailable  # noqa: E402
from _pdf_fixtures import make_report  # noqa: E402

ARGUMENTS = ("--reports", "--work")

# Fictitious texts (R34). The cover holds the cover markers, the signature page the signature markers.
COVER_TEXT = "Université du Québec Rapport présenté Département d'informatique"
BODY_TEXT = "Le réseau est une structure dans laquelle les noeuds sont reliés entre eux."
SIGNATURE_TEXT = "Signature Approuvé Approbation"
TABLE_BODY_TEXT = "Le tableau présente les résultats obtenus."
# The real OCR call, captured before setUpModule replaces it for the existing tests.
REAL_OCR_PAGE = getattr(report_prepare, "_run_ocr_page", None)


def _no_ocr(pdf, page_number, tesseract_language, dpi=None):
    """Fail when the OCR runs: a sound page must never be sent to it."""
    raise AssertionError("OCR must not run for this page")


def _snapshot(root):
    """Return the bytes of every file under a folder, keyed by relative path."""
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def setUpModule():
    """
    Purpose: Replace the OCR preflight and the OCR call for the existing tests, which build no Tesseract
        installation. The new tests inject their own hooks and the optional real-OCR test calls the real call.
    Inputs: None.
    Outputs: None. Patches are started and stopped in tearDownModule.
    """
    global _PATCHES
    _PATCHES = [
        patch.object(report_prepare, "_run_preflight", lambda languages: None, create=True),
        patch.object(report_prepare, "_run_ocr_page", _no_ocr, create=True),
    ]
    for patcher in _PATCHES:
        patcher.start()


def tearDownModule():
    """Stop the patches started by setUpModule."""
    for patcher in _PATCHES:
        patcher.stop()


class ReportPrepareTests(unittest.TestCase):
    """Ids, pages, refusals and what is printed."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.reports = self.tmp / "reports"
        self.reports.mkdir()
        self.work = self.reports / "_correction"

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_main(self, *extra):
        """Run main with the two folders and return (exit code, stdout)."""
        out = io.StringIO()
        with redirect_stdout(out):
            code = main([ARGUMENTS[0], str(self.reports), ARGUMENTS[1], str(self.work), *extra])
        return code, out.getvalue()

    def test_ids_follow_sorted_names_and_are_stable_on_rerun(self):
        make_report(self.reports / "report_b.pdf", [{"text": "Page 1"}])
        make_report(self.reports / "report_a.pdf", [{"text": "Page 1"}])
        first = prepare(self.reports, self.work)
        self.assertEqual([item["report_id"] for item in first], ["R01", "R02"])
        ids = json.loads((self.work / "ids.json").read_text(encoding="utf-8"))
        self.assertEqual(ids, {"R01": "report_a.pdf", "R02": "report_b.pdf"})
        second = prepare(self.reports, self.work)
        self.assertEqual([item["report_id"] for item in second], ["R01", "R02"])

    def test_a_report_added_later_gets_the_next_id_and_keeps_the_old_ones(self):
        make_report(self.reports / "report_b.pdf", [{"text": "Page 1"}])
        prepare(self.reports, self.work)
        make_report(self.reports / "report_a.pdf", [{"text": "Page 1"}])
        result = prepare(self.reports, self.work)
        by_id = {item["report_id"] for item in result}
        self.assertEqual(by_id, {"R01", "R02"})
        ids = json.loads((self.work / "ids.json").read_text(encoding="utf-8"))
        self.assertEqual(ids["R01"], "report_b.pdf")
        self.assertEqual(ids["R02"], "report_a.pdf")

    def test_non_pdf_files_are_skipped_and_counted(self):
        make_report(self.reports / "report.pdf", [{"text": "Page 1"}])
        (self.reports / "notes.txt").touch()
        (self.reports / "image.png").touch()
        result = prepare(self.reports, self.work)
        self.assertEqual(len(result), 1)
        self.assertEqual(skipped_count(self.reports), 2)

    def test_one_markdown_file_per_page_with_accents_kept(self):
        make_report(self.reports / "report.pdf", [{"text": "Étude des réseaux électriques"}])
        result = prepare(self.reports, self.work)
        self.assertEqual(result[0]["pages"], 1)
        page = self.work / "R01" / "pages" / "p001.md"
        self.assertIn("Étude des réseaux électriques", page.read_text(encoding="utf-8"))

    def test_an_empty_page_is_flagged_and_its_file_is_empty(self):
        make_report(self.reports / "report.pdf", [{"text": "Le réseau des noeuds"}, {}])
        with patch.object(report_prepare, "_run_ocr_page", lambda *args, **kwargs: ""):
            result = prepare(self.reports, self.work)
        self.assertEqual(result[0]["empty_pages"], [2])
        self.assertEqual((self.work / "R01" / "pages" / "p002.md").read_text(encoding="utf-8").strip(), "")

    def test_a_work_folder_directly_inside_the_reports_folder_is_accepted_and_is_not_a_report(self):
        make_report(self.reports / "report.pdf", [{"text": "Page 1"}])
        inside = self.reports / "_correction"
        first = prepare(self.reports, inside)
        second = prepare(self.reports, inside)
        self.assertEqual([r["report_id"] for r in first], ["R01"])
        self.assertEqual([r["report_id"] for r in second], ["R01"])

    def test_a_work_folder_deeper_than_one_level_is_refused(self):
        make_report(self.reports / "report.pdf", [{"text": "Page 1"}])
        with self.assertRaises(PrepareError):
            prepare(self.reports, self.reports / "a" / "_correction")

    def test_the_reports_folder_itself_is_refused_as_work_folder(self):
        make_report(self.reports / "report.pdf", [{"text": "Page 1"}])
        with self.assertRaises(PrepareError):
            prepare(self.reports, self.reports)
        self.assertEqual([path.name for path in self.reports.iterdir()], ["report.pdf"])

    def test_a_work_folder_beside_the_reports_folder_is_now_refused(self):
        make_report(self.reports / "report.pdf", [{"text": "Page 1"}])
        with self.assertRaises(PrepareError):
            prepare(self.reports, self.tmp / "other" / "_correction")
        with self.assertRaises(PrepareError):
            prepare(self.reports, self.reports.parent / "_correction")

    def test_an_unreadable_id_map_is_refused_without_naming_a_file(self):
        make_report(self.reports / "report.pdf", [{"text": "Page 1"}])
        self.work.mkdir()
        (self.work / "ids.json").write_text("not json", encoding="utf-8")
        with self.assertRaises(PrepareError) as raised:
            prepare(self.reports, self.work)
        self.assertNotIn("ids.json", str(raised.exception))

    def test_a_missing_configuration_key_is_named(self):
        make_report(self.reports / "report.pdf", [{"text": "Page 1"}])
        with patch("report_prepare.ugs_config.load", return_value={}):
            with self.assertRaises(PrepareError) as raised:
                prepare(self.reports, self.work)
        self.assertIn("reports.id_prefix", str(raised.exception))

    def test_stdout_never_carries_a_file_name(self):
        make_report(self.reports / "invented_student_name.pdf", [{"text": "Page 1"}])
        code, output = self.run_main()
        self.assertEqual(code, 0)
        self.assertNotIn("invented_student_name", output)
        self.assertEqual(json.loads(output)["ids"], ["R01"])

    def test_dry_run_writes_nothing(self):
        make_report(self.reports / "report.pdf", [{"text": "Page 1"}])
        code, output = self.run_main("--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output), {"reports": 1, "skipped": 0})
        self.assertFalse(self.work.exists())

    def test_a_missing_reports_folder_exits_2(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main([ARGUMENTS[0], str(self.tmp / "absent"), ARGUMENTS[1], str(self.work)])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out.getvalue())["status"], "refused")

    def test_a_refusal_prints_no_file_name_or_path(self):
        make_report(self.reports / "secret_report.pdf", [{"text": "Page 1"}])
        error = PrepareError(f"failed on {self.reports}/secret_report.pdf")
        with patch.object(report_prepare, "prepare", side_effect=error):
            code, output = self.run_main()
        self.assertEqual(code, 2)
        self.assertNotIn("secret_report", output)
        self.assertNotIn(str(self.reports), output)

    def test_an_unexpected_failure_prints_the_type_and_no_path(self):
        make_report(self.reports / "report.pdf", [{"text": "Page 1"}])
        error = FileNotFoundError(f"No such file: '{self.reports}/report.pdf'")
        with patch.object(report_prepare, "prepare", side_effect=error):
            code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output)["error_type"], "FileNotFoundError")
        self.assertNotIn(str(self.reports), output)


def _hooks(preflight=None, ocr_page=None, find_elements=None):
    """
    Purpose: Build the injected hooks of a preparation run; each argument defaults to the offline behaviour.
    Inputs:
        preflight (callable | None): OCR preflight over the list of Tesseract codes; None accepts every language.
        ocr_page (callable | None): OCR of one page; None fails when called.
        find_elements (callable | None): element finder; None runs the real extraction.
    Outputs:
        PrepHooks: the hooks to pass to prepare.
    Raises:
        None.
    """
    return report_prepare.PrepHooks(
        preflight=preflight or (lambda languages: None),
        ocr_page=ocr_page or _no_ocr,
        find_elements=find_elements or report_prepare._run_find_elements,
    )


def test_module_starts_without_a_byte_order_mark():
    """Review round 1 M2 (Issue 126): report_prepare.py carries no stray BOM before its first line."""
    head = (SCRIPTS / "report_prepare.py").read_bytes()[:3]
    assert head != b"\xef\xbb\xbf", "report_prepare.py starts with a byte-order mark"


class PreparationTests(unittest.TestCase):
    """Language, excluded pages, text repair, elements, table text and rerun of the preparation (R5 to R7, R10)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.reports = self.tmp / "reports"
        self.reports.mkdir()
        self.work = self.reports / "_correction"
        self.pdf = self.reports / "report.pdf"
        make_report(self.pdf, [{"text": COVER_TEXT}, {"text": BODY_TEXT}, {"text": SIGNATURE_TEXT}])

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def report_file(self, *parts):
        """Return a file of the first report in the work folder."""
        return self.work.joinpath("R01", *parts)

    def test_meta_file_has_language_excluded_pages_and_quality(self):
        prepare(self.reports, self.work, hooks=_hooks())
        meta = json.loads(self.report_file("report_meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["language"], "fr")
        self.assertEqual(meta["excluded_pages"], [{"page": 1, "reason": "cover"},
                                                  {"page": 3, "reason": "signature_table"}])
        self.assertEqual([entry["page"] for entry in meta["text_quality"]], [1, 2, 3])
        for entry in meta["text_quality"]:
            self.assertIn("replacement_chars", entry)
            self.assertIn("ocr", entry)

    def test_excluded_page_is_replaced_by_a_marker_and_its_text_is_kept_aside(self):
        prepare(self.reports, self.work, hooks=_hooks())
        self.assertEqual(self.report_file("pages", "p001.md").read_text(encoding="utf-8").strip(),
                         "[page excluded: cover]")
        self.assertEqual(self.report_file("pages", "p003.md").read_text(encoding="utf-8").strip(),
                         "[page excluded: signature_table]")
        self.assertIn("Université", self.report_file("excluded", "p001.md").read_text(encoding="utf-8"))
        self.assertIn("Le réseau", self.report_file("pages", "p002.md").read_text(encoding="utf-8"))
        self.assertFalse(self.report_file("excluded", "p002.md").exists())

    def test_front_roles_written_to_meta(self):
        """Issue 126 plan 10 F1: the front-matter pages are recorded in report_meta.json (fictitious list page)."""
        list_text = "Liste des figures\nFigure 1 Schema du montage ........ 4\nFigure 2 Courbe mesuree ........ 6\nFigure 3 Bloc ........ 8"
        make_report(self.pdf, [{"text": COVER_TEXT}, {"text": list_text}, {"text": BODY_TEXT}])
        prepare(self.reports, self.work, hooks=_hooks())
        meta = json.loads(self.report_file("report_meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["front_roles"]["list_of_figures"], [2])
        self.assertEqual(meta["front_roles"]["body_start"], 3)
    def test_front_pages_are_skipped_by_extraction(self):
        """Issue 126 plan 16 N3: a list page is not sent to the element finder as content (fictitious report)."""
        list_text = "Liste des figures\nFigure 1 Schema ........ 4\nFigure 2 Courbe ........ 6\nFigure 3 Bloc ........ 8"
        make_report(self.pdf, [{"text": COVER_TEXT}, {"text": list_text}, {"text": BODY_TEXT}])
        seen = {}

        def finder(pdf, figures_dir, skip_pages, overrides=None):
            seen["skip"] = list(skip_pages)
            return []

        prepare(self.reports, self.work, hooks=_hooks(find_elements=finder))
        self.assertEqual(seen["skip"], [1, 2])

    def test_cover_logo_gives_no_element(self):
        """Issue 126 plan 16 N3: a finder that would take the cover logo writes no element, the cover being skipped."""
        make_report(self.pdf, [{"text": COVER_TEXT}, {"text": BODY_TEXT}])

        def finder(pdf, figures_dir, skip_pages, overrides=None):
            if 1 in skip_pages:
                return []
            return [{"element_id": "F01", "element_type": "figure", "page": 1, "file": "F01.png"}]

        prepare(self.reports, self.work, hooks=_hooks(find_elements=finder))
        self.assertEqual(json.loads(self.report_file("elements.json").read_text(encoding="utf-8")), [])

    def _two_figures_declared(self):
        """Give the fictitious report a list of figures declaring two figures (plan 12 Task 3)."""
        list_text = "Liste des figures\nFigure 1 Schema ........ 4\nFigure 2 Courbe ........ 6"
        make_report(self.pdf, [{"text": COVER_TEXT}, {"text": list_text}, {"text": BODY_TEXT}])

    def test_preparation_records_attempts_and_status(self):
        """Plan 12 Task 3: the first attempt gives three figures, the re-run gives the two declared ones."""
        self._two_figures_declared()
        calls = []

        def finder(pdf, figures_dir, skip_pages, overrides=None):
            calls.append(overrides)
            count = 2 if overrides else 3
            figures_dir.mkdir(parents=True, exist_ok=True)
            records = []
            for number in range(1, count + 1):
                (figures_dir / f"F{number:02d}.png").write_bytes(b"png")
                records.append({"element_id": f"F{number:02d}", "element_type": "figure", "page": 2,
                                "file": f"F{number:02d}.png",
                                "title": {"text": f"Figure {number}: Schema"}})
            return records

        prepare(self.reports, self.work, hooks=_hooks(find_elements=finder))
        meta = json.loads(self.report_file("report_meta.json").read_text(encoding="utf-8"))
        self.assertEqual([attempt["extracted"] for attempt in meta["figure_attempts"]], [3, 2])
        self.assertEqual([attempt["status"] for attempt in meta["figure_attempts"]], ["mismatch", "ok"])
        self.assertEqual(meta["figure_count_status"], "ok")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], None)

    def test_rejected_attempt_leaves_no_file(self):
        """Plan 12 Task 3: the files of a rejected attempt never reach the figures folder."""
        self._two_figures_declared()

        def finder(pdf, figures_dir, skip_pages, overrides=None):
            count = 2 if overrides else 3
            figures_dir.mkdir(parents=True, exist_ok=True)
            records = []
            for number in range(1, count + 1):
                (figures_dir / f"F{number:02d}.png").write_bytes(b"png")
                records.append({"element_id": f"F{number:02d}", "element_type": "figure", "page": 2,
                                "file": f"F{number:02d}.png",
                                "title": {"text": f"Figure {number}: Schema"}})
            return records

        prepare(self.reports, self.work, hooks=_hooks(find_elements=finder))
        figures = sorted(path.name for path in self.report_file("figures").glob("*.png"))
        self.assertEqual(figures, ["F01.png", "F02.png"])
        self.assertFalse(self.report_file(".attempts").exists())

    def _untitled_region_finder(self):
        """Finder giving one untitled figure record that its folder holds as a PNG (plan 11 Task 2)."""
        def finder(pdf, figures_dir, skip_pages, overrides=None):
            figures_dir.mkdir(parents=True, exist_ok=True)
            (figures_dir / "F-u01.png").write_bytes(b"png")
            return [{"element_id": "F-u01", "element_type": "figure", "page": 2, "file": "F-u01.png",
                     "rect": [100, 300, 400, 500], "title": None, "drawing_area_ratio": 1.0}]
        return finder

    @staticmethod
    def _grid_words(rows, cols):
        """Fictitious OCR word boxes laid out as a grid (plan 11 Task 2)."""
        return [(100 + c * 100, 300 + r * 15, 140 + c * 100, 310 + r * 15, f"w{r}{c}", 0, 0, 0)
                for r in range(rows) for c in range(cols)]

    def _prepare_with_ocr(self, words_hook):
        """Prepare the fictitious report with an untitled region and the given word-box OCR hook."""
        hooks = report_prepare.PrepHooks(preflight=lambda languages: None, ocr_page=_no_ocr,
                                         find_elements=self._untitled_region_finder(), ocr_words=words_hook)
        prepare(self.reports, self.work, hooks=hooks)

    def test_untitled_grid_region_becomes_table_image(self):
        """Plan 11 Task 2: an untitled region whose OCR rebuilds a 3 by 3 grid is a table_image T-u01."""
        self._prepare_with_ocr(lambda pdf, page, rect, lang: self._grid_words(3, 3))
        elements = json.loads(self.report_file("elements.json").read_text(encoding="utf-8"))
        self.assertEqual([(e["element_type"], e["element_id"], e["file"]) for e in elements],
                         [("table_image", "T-i01", "T-i01.png")])
        self.assertTrue(self.report_file("figures", "T-i01.png").exists())
        self.assertFalse(self.report_file("figures", "F-u01.png").exists())

    def test_renamed_table_image_never_collides_with_a_ruled_table_id(self):
        """Review I1: an untitled ruled table T-u01 and an untitled figure turned table image keep distinct ids."""
        def finder(pdf, figures_dir, skip_pages, overrides=None):
            figures_dir.mkdir(parents=True, exist_ok=True)
            (figures_dir / "F-u01.png").write_bytes(b"png")
            return [{"element_id": "T-u01", "element_type": "table", "page": 1, "file": None,
                     "rect": [60, 60, 500, 200], "title": None, "markdown": "| a |"},
                    {"element_id": "F-u01", "element_type": "figure", "page": 2, "file": "F-u01.png",
                     "rect": [100, 300, 400, 500], "title": None, "drawing_area_ratio": 1.0}]

        hooks = report_prepare.PrepHooks(preflight=lambda languages: None, ocr_page=_no_ocr,
                                         find_elements=finder, ocr_words=lambda pdf, page, rect, lang: self._grid_words(3, 3))
        prepare(self.reports, self.work, hooks=hooks)
        elements = json.loads(self.report_file("elements.json").read_text(encoding="utf-8"))
        ids = [e["element_id"] for e in elements]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("T-u01", ids)
        files = [e["file"] for e in elements if e.get("file")]
        self.assertEqual(len(files), len(set(files)))

    def test_ocr_failure_keeps_figure_with_reason(self):
        """Plan 11 Task 2: when OCR cannot run, the untitled region stays a figure with a fixed status."""
        def failing(pdf, page, rect, lang):
            raise PrepareError("tesseract_missing")

        self._prepare_with_ocr(failing)
        elements = json.loads(self.report_file("elements.json").read_text(encoding="utf-8"))
        self.assertEqual(elements[0]["element_type"], "figure")
        self.assertEqual(elements[0]["status"], "untitled_ocr_unavailable")

    def test_ocr_called_once_per_region(self):
        """Plan 11 Task 2: the classification and the table reading share one OCR call per region."""
        calls = []

        def counting(pdf, page, rect, lang):
            calls.append((page, tuple(rect)))
            return self._grid_words(3, 3)

        self._prepare_with_ocr(counting)
        self.assertEqual(len(calls), 1)

    def test_count_status_written_to_meta(self):
        """Issue 126 plan 6 E2: a declared figure with no extracted figure is a mismatch in report_meta.json."""
        list_text = "Liste des figures\nFigure 1. Schema ........ 4\nFigure 2. Courbe ........ 6\nFigure 3. Bloc ........ 8"
        make_report(self.pdf, [{"text": COVER_TEXT}, {"text": list_text}, {"text": BODY_TEXT}])
        prepare(self.reports, self.work, hooks=_hooks())
        meta = json.loads(self.report_file("report_meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["figure_count_status"], "mismatch")
        self.assertEqual(meta["extracted_figures"], 0)
        self.assertEqual(meta["missing_figure_numbers"], ["1", "2", "3"])
        self.assertEqual(meta["table_count_status"], "not_found")

    def test_declared_counts_written_to_meta(self):
        """Issue 126 plan 5 E1: the printed figure count of the list is written to report_meta.json (fictitious)."""
        list_text = "Liste des figures\nFigure 1. Schema ........ 4\nFigure 2. Courbe ........ 6\nFigure 3. Bloc ........ 8"
        make_report(self.pdf, [{"text": COVER_TEXT}, {"text": list_text}, {"text": BODY_TEXT}])
        prepare(self.reports, self.work, hooks=_hooks())
        meta = json.loads(self.report_file("report_meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["declared_figures"], 3)
        self.assertEqual(meta["declared_figure_numbers"], ["1", "2", "3"])
        self.assertIsNone(meta["declared_tables"])

    def test_elements_file_written(self):
        prepare(self.reports, self.work, hooks=_hooks())
        elements = json.loads(self.report_file("elements.json").read_text(encoding="utf-8"))
        self.assertIsInstance(elements, list)
        self.assertEqual(elements, [])

    def test_table_markdown_added_to_the_page_text(self):
        table = {"element_id": "T01", "element_type": "table", "page": 2,
                 "rect": [50.0, 300.0, 500.0, 400.0], "file": "T01.png", "title": None, "legend": "",
                 "notes": [], "caption": None, "drawing_area_ratio": None,
                 "markdown": "| Nom | Valeur |\n|---|---|\n| Alpha | 12 |"}
        make_report(self.pdf, [{"text": COVER_TEXT}, {"text": TABLE_BODY_TEXT}, {"text": SIGNATURE_TEXT}])
        prepare(self.reports, self.work, hooks=_hooks(find_elements=lambda pdf, out, skip, overrides=None: [table]))
        text = self.report_file("pages", "p002.md").read_text(encoding="utf-8")
        # The fixture report is French (meta language fr), so its heading is the French one (D3).
        self.assertIn("## Tableau T01 (détecté)", text)
        self.assertIn("| Alpha | 12 |", text)
        self.assertIn("Le tableau", text)

    def _table_image_record(self):
        """
        Purpose: Build one fictitious table_image element record (plan 8), as extract_elements returns it.
        Inputs:
            None.
        Outputs:
            dict - the record, on page 2, with its title above.
        Raises:
            None.
        """
        return {"element_id": "T01", "element_type": "table_image", "page": 2,
                "rect": [50.0, 300.0, 500.0, 400.0], "file": "T01.png",
                "title": {"text": "Tableau 1 : Mesures", "position": "above", "alignment": "center"},
                "legend": "", "notes": [], "caption": "Tableau 1 : Mesures", "source": "raster",
                "pixel_size": [100, 80]}

    def test_titled_table_image_reaches_page_markdown(self):
        """Issue 126 plan 8 E3: the OCR words of a table drawn as an image become rows of the page text (fictitious)."""
        words = [(60.0, 310.0, 90.0, 320.0, "Mesure", 0, 0, 0), (200.0, 310.0, 240.0, 320.0, "Valeur", 0, 0, 1),
                 (60.0, 330.0, 90.0, 340.0, "Masse", 0, 0, 2), (200.0, 330.0, 220.0, 340.0, "12.5", 0, 0, 3)]
        make_report(self.pdf, [{"text": COVER_TEXT}, {"text": TABLE_BODY_TEXT}, {"text": SIGNATURE_TEXT}])
        hooks = report_prepare.PrepHooks(preflight=lambda languages: None, ocr_page=_no_ocr,
                                         find_elements=lambda pdf, out, skip, overrides=None: [self._table_image_record()],
                                         ocr_words=lambda pdf, page, rect, language: words)
        prepare(self.reports, self.work, hooks=hooks)
        text = self.report_file("pages", "p002.md").read_text(encoding="utf-8")
        self.assertIn("## Tableau T01 (détecté)", text)
        self.assertIn("| Mesure | Valeur |", text)
        self.assertIn("| Masse | 12.5 |", text)
        record = json.loads(self.report_file("elements.json").read_text(encoding="utf-8"))[0]
        self.assertEqual(record["element_type"], "table_image")
        self.assertIn("markdown", record)

    def test_empty_table_image_is_unreadable_and_not_a_figure(self):
        """Issue 126 plan 8 E3: a table drawn as an image with no OCR word is unreadable, never an empty table."""
        make_report(self.pdf, [{"text": COVER_TEXT}, {"text": TABLE_BODY_TEXT}, {"text": SIGNATURE_TEXT}])
        hooks = report_prepare.PrepHooks(preflight=lambda languages: None, ocr_page=_no_ocr,
                                         find_elements=lambda pdf, out, skip, overrides=None: [self._table_image_record()],
                                         ocr_words=lambda pdf, page, rect, language: [])
        prepare(self.reports, self.work, hooks=hooks)
        record = json.loads(self.report_file("elements.json").read_text(encoding="utf-8"))[0]
        self.assertEqual(record["element_type"], "table_image")
        self.assertEqual(record["status"], "table_image_unreadable")
        self.assertEqual(record["status_reason"], "0 rows found, 2 needed")
        self.assertNotIn("markdown", record)
        self.assertNotIn("| --- |", self.report_file("pages", "p002.md").read_text(encoding="utf-8"))

    def test_two_table_images_on_one_page_cost_one_ocr(self):
        """Review M3 (series C): the OCR of a page is cached for one preparation; a second region reuses it."""
        calls = []

        def reader(pdf, page_number, language, dpi):
            calls.append(page_number)
            return [(10.0, 10.0, 20.0, 20.0, "Mesure", 0, 0, 0)]

        hook = report_prepare._make_ocr_words_hook(300, page_reader=reader)
        hook(self.pdf, 1, [0.0, 0.0, 100.0, 100.0], "fra")
        hook(self.pdf, 1, [0.0, 0.0, 100.0, 100.0], "fra")
        self.assertEqual(calls, [1])
        hook(self.pdf, 2, [0.0, 0.0, 100.0, 100.0], "fra")
        self.assertEqual(calls, [1, 2])

    def test_only_words_inside_the_element_rect_are_returned(self):
        """Review M4 (series C): a stub textpage gives words inside and outside a sub-rect; only the inside ones return."""

        class StubPage:
            def __init__(self):
                self.textpages = 0

            def get_textpage_ocr(self, language, dpi, full):
                self.textpages += 1
                return "stub-textpage"

            def get_text(self, kind, textpage=None):
                assert kind == "words" and textpage == "stub-textpage"
                return [(110.0, 110.0, 130.0, 120.0, "dedans", 0, 0, 0),
                        (10.0, 10.0, 30.0, 20.0, "dehors", 0, 0, 1),
                        (190.0, 110.0, 230.0, 120.0, "bord", 0, 0, 2)]

        stub = StubPage()
        hook = report_prepare._make_ocr_words_hook(
            300, page_reader=lambda pdf, number, language, dpi: report_prepare._page_words(stub, language, dpi))
        words = hook(self.pdf, 1, [100.0, 100.0, 150.0, 150.0], "fra")
        self.assertEqual([word[4] for word in words], ["dedans"])
        self.assertEqual(stub.textpages, 1)

    def test_ocr_error_gives_a_category_and_never_the_path(self):
        """Security correction (series C, M3): the PrepareError holds a fixed category and the type name, never the
        error text, which can carry the PDF path (fictitious path here)."""
        leaking = FileNotFoundError("C:/Etudiants/Fictif Dupont/rapport.pdf introuvable")
        with patch.object(report_prepare.fitz, "open", side_effect=leaking):
            with self.assertRaises(PrepareError) as ctx:
                report_prepare._ocr_page_words(self.pdf, 1, "fra", 300)
        text = str(ctx.exception)
        self.assertIn("tesseract_missing", text)
        self.assertIn("FileNotFoundError", text)
        self.assertNotIn("Dupont", text)
        self.assertNotIn("Etudiants", text)

    def test_unlisted_ocr_error_is_ocr_failed(self):
        """Security correction (series C, M3): an exception type with no category is reported as ocr_failed."""
        with patch.object(report_prepare.fitz, "open", side_effect=RuntimeError("secret detail")):
            with self.assertRaises(PrepareError) as ctx:
                report_prepare._ocr_page_words(self.pdf, 1, "fra", 300)
        self.assertIn("ocr_failed", str(ctx.exception))
        self.assertNotIn("secret detail", str(ctx.exception))

    def test_table_image_without_an_ocr_hook_is_a_named_refusal(self):
        """Issue 126 plan 8 E3: a table_image with no OCR hook given is refused by name, never guessed."""
        make_report(self.pdf, [{"text": COVER_TEXT}, {"text": TABLE_BODY_TEXT}, {"text": SIGNATURE_TEXT}])
        with self.assertRaises(PrepareError) as ctx:
            prepare(self.reports, self.work, hooks=_hooks(find_elements=lambda pdf, out, skip, overrides=None: [self._table_image_record()]))
        self.assertIn("OCR", str(ctx.exception))

    @unittest.skipUnless(os.environ.get("TESSDATA_PREFIX"), "needs TESSDATA_PREFIX (Tesseract) to run real OCR")
    def test_real_ocr_reads_the_words_of_a_table_image(self):
        """Issue 126 plan 8 E3: real OCR of a fictitious picture of two words (skips without TESSDATA_PREFIX)."""
        source = fitz.open()
        page = source.new_page(width=400, height=120)
        page.insert_text((20, 70), "Mesure", fontsize=28)
        pix = page.get_pixmap(dpi=200)
        probe = self.tmp / "table_image_probe.pdf"
        doc = fitz.open()
        picture_page = doc.new_page(width=400, height=120)
        picture_page.insert_image(picture_page.rect, pixmap=pix)
        doc.save(str(probe))
        doc.close()
        source.close()
        words = report_prepare._ocr_page_words(probe, 1, "eng", 300)
        self.assertTrue(any("Mesure" in str(word[4]) for word in words))

    def test_missing_min_anchor_key_writes_no_elements_file(self):
        cfg = self.work.parent / "ugs_config_no_anchor.json"
        cfg.write_text(json.dumps({"other.key": {"value": 1, "provenance": "fictitious"}}), encoding="utf-8")
        make_report(self.pdf, [{"text": COVER_TEXT}, {"text": TABLE_BODY_TEXT}, {"text": SIGNATURE_TEXT}])
        with patch.object(ugs_tables, "DEFAULT_CONFIG_PATH", cfg):
            with self.assertRaises(PrepareError) as ctx:
                prepare(self.reports, self.work, hooks=_hooks())
        self.assertIn("tables.min_anchor_chars", str(ctx.exception))
        self.assertFalse(list(self.work.rglob("elements.json")))

    def test_missing_table_text_language_writes_no_elements_file(self):
        """F2: a language with no table text refuses the report before any write of its elements."""
        cfg = self.work.parent / "table_text_en_only.json"
        cfg.write_text(json.dumps({"en": {"heading": {"value": "## Table {element_id} (detected)", "provenance": "t"},
                                          "page_line": {"value": "Page {page}", "provenance": "t"}}}), encoding="utf-8")
        make_report(self.pdf, [{"text": COVER_TEXT}, {"text": TABLE_BODY_TEXT}, {"text": SIGNATURE_TEXT}])
        with patch.object(ugs_tables, "TABLE_TEXT_PATH", cfg):
            with self.assertRaises(PrepareError) as ctx:
                prepare(self.reports, self.work, hooks=_hooks())
        self.assertIn("'fr'", str(ctx.exception))
        self.assertFalse(list(self.work.rglob("elements.json")))

    def test_tables_dropped_is_read_from_the_extraction_file(self):
        """F0: the count of tables dropped by the extraction is surfaced in report_meta.json, 0 when none."""
        report_dir = self.work / "R01"
        report_dir.mkdir(parents=True)
        self.assertEqual(report_prepare._tables_dropped(report_dir), 0)
        (report_dir / report_prepare.TABLE_STATS_FILE).write_text(json.dumps({"tables_dropped": 2}), encoding="utf-8")
        self.assertEqual(report_prepare._tables_dropped(report_dir), 2)

    def test_second_run_changes_nothing(self):
        prepare(self.reports, self.work, hooks=_hooks())
        first_files = _snapshot(self.work)
        first_ids = json.loads((self.work / "ids.json").read_text(encoding="utf-8"))
        prepare(self.reports, self.work, hooks=_hooks())
        self.assertEqual(_snapshot(self.work), first_files)
        self.assertEqual(json.loads((self.work / "ids.json").read_text(encoding="utf-8")), first_ids)

    def test_preflight_failure_stops_before_any_write(self):
        def refuse(languages):
            raise OcrUnavailable("Tesseract language data missing: fra.traineddata not found")

        with self.assertRaises(report_prepare.OcrPreflightError) as raised:
            prepare(self.reports, self.work, hooks=_hooks(preflight=refuse))
        self.assertIn("fra.traineddata", str(raised.exception))
        self.assertFalse(self.work.exists())
        self.assertEqual([path.name for path in self.reports.iterdir()], ["report.pdf"])

    def test_preflight_checks_every_language_code_of_the_map_once(self):
        seen = []
        prepare(self.reports, self.work, hooks=_hooks(preflight=lambda languages: seen.append(list(languages))))
        self.assertEqual(len(seen), 1)
        self.assertEqual(sorted(set(seen[0])), ["eng", "fra"])

    def test_a_damaged_page_is_repaired_by_ocr_in_the_detected_language(self):
        texts = [COVER_TEXT, "Le re���seau est �", SIGNATURE_TEXT]
        calls = []

        def ocr(pdf, page_number, tesseract_language):
            calls.append((page_number, tesseract_language))
            return "Le réseau est fiable ﬁn"

        with patch.object(report_prepare, "_extract_page_text", return_value=texts):
            prepare(self.reports, self.work, hooks=_hooks(ocr_page=ocr))
        self.assertEqual(calls, [(2, "fra")])
        self.assertEqual(self.report_file("pages", "p002.md").read_text(encoding="utf-8"), "Le réseau est fiable fin")
        meta = json.loads(self.report_file("report_meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["text_quality"][1]["replacement_chars"], 4)
        self.assertTrue(meta["text_quality"][1]["ocr"])
        self.assertFalse(meta["text_quality"][0]["ocr"])

    def test_a_page_without_any_text_is_sent_to_ocr_and_flagged_when_still_empty(self):
        texts = [COVER_TEXT, "", SIGNATURE_TEXT]
        calls = []

        def ocr(pdf, page_number, tesseract_language):
            calls.append(page_number)
            return ""

        with patch.object(report_prepare, "_extract_page_text", return_value=texts):
            prepare(self.reports, self.work, hooks=_hooks(ocr_page=ocr))
        self.assertEqual(calls, [2])
        meta = json.loads(self.report_file("report_meta.json").read_text(encoding="utf-8"))
        self.assertTrue(meta["text_quality"][1]["empty"])
        self.assertTrue(meta["text_quality"][1]["ocr"])

    def test_unreadable_pages_are_listed_in_meta(self):
        texts = [COVER_TEXT, "", SIGNATURE_TEXT]
        with patch.object(report_prepare, "_extract_page_text", return_value=texts):
            prepare(self.reports, self.work, hooks=_hooks(ocr_page=lambda pdf, number, language: ""))
        meta = json.loads(self.report_file("report_meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["unreadable_pages"], [2])
        self.assertTrue(all(isinstance(number, int) for number in meta["unreadable_pages"]))

    def test_undecidable_language_refuses_the_report_with_a_named_reason(self):
        self.pdf.unlink()
        make_report(self.reports / "undecidable.pdf", [{"text": "Page 1"}])
        make_report(self.reports / "french.pdf", [{"text": COVER_TEXT}, {"text": BODY_TEXT}])
        result = prepare(self.reports, self.work, hooks=_hooks())
        by_id = {item["report_id"]: item for item in result}
        # Sorted names: french.pdf is R01 and undecidable.pdf is R02.
        self.assertIn("language", by_id["R02"]["refused"])
        self.assertIn("R02", by_id["R02"]["refused"])
        self.assertFalse((self.work / "R02" / "pages").exists())
        self.assertNotIn("refused", by_id["R01"])
        self.assertTrue((self.work / "R01" / "pages" / "p002.md").exists())

    def test_library_messages_never_reach_stdout(self):
        def chatty(languages):
            fitz.message("OCR on page 1 (library progress line)")

        out = io.StringIO()
        with redirect_stdout(out):
            prepare(self.reports, self.work, hooks=_hooks(preflight=chatty))
        self.assertNotIn("library progress line", out.getvalue())

    def test_a_missing_preparation_key_is_named(self):
        config = ugs_config.load(ugs_config.default_path())
        del config["text.ocr_dpi"]
        with patch("report_prepare.ugs_config.load", return_value=config):
            with self.assertRaises(PrepareError) as raised:
                prepare(self.reports, self.work, hooks=_hooks())
        self.assertIn("text.ocr_dpi", str(raised.exception))

    def test_an_ocr_refusal_names_the_missing_part_and_prints_no_path(self):
        def refuse(languages):
            raise OcrUnavailable("Tesseract language data missing: fra.traineddata not found")

        out = io.StringIO()
        with patch.object(report_prepare, "_default_hooks", return_value=_hooks(preflight=refuse)):
            with redirect_stdout(out):
                code = main([ARGUMENTS[0], str(self.reports), ARGUMENTS[1], str(self.work)])
        self.assertEqual(code, 2)
        self.assertIn("fra.traineddata", json.loads(out.getvalue())["reason"])
        self.assertNotIn(str(self.reports), out.getvalue())

    @unittest.skipUnless(os.environ.get("TESSDATA_PREFIX"), "TESSDATA_PREFIX is not set: the real OCR is not run")
    def test_real_ocr_reads_a_rendered_probe_word(self):
        source = fitz.open()
        page = source.new_page(width=400, height=200)
        page.insert_text((20, 120), "Test", fontsize=48)
        probe = self.tmp / "probe.pdf"
        source.save(str(probe))
        source.close()
        text = REAL_OCR_PAGE(probe, 1, "eng", 300)
        self.assertIn("test", text.lower())


if __name__ == "__main__":
    unittest.main()
