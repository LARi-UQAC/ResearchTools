"""
Offline tests for page_roles.py (Issue 122, plan 1 task 1, requirement R7).

Every text is fictitious (R34). PDFs are built inside a temporary folder with PyMuPDF.
No network, no model, no real report is opened (R21).
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import fitz

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import page_roles  # noqa: E402

DATA_FILE = SCRIPTS.parent / "assets" / "page_roles.json"


def _markers() -> dict:
    """
    Purpose:
        Load the shipped marker data file, as the caller of page_roles does.

    Inputs:
        None.

    Outputs:
        dict: the result of page_roles.load_markers on the shipped file.

    Raises:
        page_roles.PageRolesConfigError: when the shipped file is incomplete.
    """
    return page_roles.load_markers(DATA_FILE)


def _make_pdf(path: Path, pages: list) -> Path:
    """
    Purpose:
        Build a fictitious PDF with one text block and optional images per page.

    Inputs:
        path (Path): destination file.
        pages (list): each entry is a dict with "text" (str) and "images" (list of
            (x0, y0, x1, y1) rectangles, may be empty).

    Outputs:
        Path: the written file.

    Raises:
        RuntimeError: when PyMuPDF cannot save the file.
    """
    doc = fitz.open()
    for entry in pages:
        page = doc.new_page(width=300, height=400)
        page.insert_text((20, 40), entry["text"], fontsize=9)
        for x0, y0, x1, y1 in entry.get("images", []):
            pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 8), False)
            page.insert_image(fitz.Rect(x0, y0, x1, y1), pixmap=pix)
    doc.save(str(path))
    doc.close()
    return path


class TestPageRoles(unittest.TestCase):
    """Cover, signature table and version table are told apart from body text."""

    def setUp(self) -> None:
        """
        Purpose:
            Load the marker data once per test and keep the shipped file in use.

        Inputs:
            None.

        Outputs:
            None. Sets self.markers.

        Raises:
            page_roles.PageRolesConfigError: when the shipped file is incomplete.
        """
        self.markers = _markers()

    def test_cover_page_with_markers_and_few_words(self) -> None:
        """
        Purpose:
            A first page with markers, few words and a small logo is the cover.

        Inputs:
            None.

        Outputs:
            None. Asserts the role is "cover".

        Raises:
            AssertionError: when the cover is not recognised.
        """
        text = "Université Fictive\nRapport présenté à monsieur Exemple\nDépartement de génie"
        role = page_roles.classify_page(text, 0, 1, self.markers)
        self.assertEqual(role, "cover")

    def test_first_page_with_body_text_is_kept(self) -> None:
        """
        Purpose:
            A first page of real introduction (many words, no marker) is not excluded.

        Inputs:
            None.

        Outputs:
            None. Asserts the role is None.

        Raises:
            AssertionError: when the introduction is excluded.
        """
        body = " ".join(["The fictive sample was heated slowly while readings accumulated."] * 15)
        text = "1 Introduction\n" + body + " Rapport présenté in one clause only."
        role = page_roles.classify_page(text, 0, 1, self.markers)
        self.assertIsNone(role)

    def test_signature_marker_inside_long_text_is_kept(self) -> None:
        """
        Purpose:
            One word signature inside a long sentence of body text is not a signature table.

        Inputs:
            None.

        Outputs:
            None. Asserts the page on index 5 is kept.

        Raises:
            AssertionError: when the body page is excluded.
        """
        body = (
            "The signature of the sensor response was compared with the calibration curve, "
            "and each run was repeated three times before the averages were computed "
            "for the fictive table of results discussed in section four."
        )
        role = page_roles.classify_page(body, 5, 0, self.markers)
        self.assertIsNone(role)

    def test_version_table_on_a_middle_page(self) -> None:
        """
        Purpose:
            A middle page holding a version history table is excluded as version_table.

        Inputs:
            None.

        Outputs:
            None. Asserts the role is "version_table".

        Raises:
            AssertionError: when the version table is not recognised.
        """
        text = "Historique des révisions\nVersion 1.0  révision initiale\nVersion 1.1  correction"
        role = page_roles.classify_page(text, 6, 0, self.markers)
        self.assertEqual(role, "version_table")

    def test_signature_table_on_a_later_page(self) -> None:
        """
        Purpose:
            A page holding the approval block with signature markers is a signature table.

        Inputs:
            None.

        Outputs:
            None. Asserts the role is "signature_table".

        Raises:
            AssertionError: when the signature table is not recognised.
        """
        text = "Approuvé par\nSignature : ____\nDate d'approbation : fictive"
        role = page_roles.classify_page(text, 9, 0, self.markers)
        self.assertEqual(role, "signature_table")

    def test_markers_ignore_case_and_accents(self) -> None:
        """
        Purpose:
            Markers are found in upper case and with or without accents.

        Inputs:
            None.

        Outputs:
            None. Asserts the same role for the accented upper-case and the plain lower-case text.

        Raises:
            AssertionError: when accents or case change the verdict.
        """
        upper = "HISTORIQUE DES RÉVISIONS\nVERSION 2.0"
        plain = "historique des revisions\nversion 2.0"
        self.assertEqual(page_roles.classify_page(upper, 4, 0, self.markers), "version_table")
        self.assertEqual(page_roles.classify_page(plain, 4, 0, self.markers), "version_table")

    def test_short_report_no_error(self) -> None:
        """
        Purpose:
            A report with fewer pages than max_leading_pages gives no index error.

        Inputs:
            None.

        Outputs:
            None. Asserts a one-page report is excluded as cover only when it is a cover.

        Raises:
            AssertionError: when excluded_pages raises or misreports the single page.
        """
        pages = ["Université Fictive\nRapport présenté à monsieur Exemple\nDépartement de génie"]
        result = page_roles.excluded_pages(pages, [1], self.markers)
        self.assertEqual(result, [{"page": 1, "reason": "cover"}])
        empty = page_roles.excluded_pages([], [], self.markers)
        self.assertEqual(empty, [])

    def test_missing_key_is_named(self) -> None:
        """
        Purpose:
            A data file without max_cover_words is refused, and the error names the key and the file.

        Inputs:
            None.

        Outputs:
            None. Asserts the error message contains the key name and the file path.

        Raises:
            AssertionError: when the missing key is not reported by name.
        """
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "page_roles.json"
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            del data["max_cover_words"]
            bad.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(page_roles.PageRolesConfigError) as ctx:
                page_roles.load_markers(bad)
            message = str(ctx.exception)
            self.assertIn("max_cover_words", message)
            self.assertIn("page_roles.json", message)

    def test_small_images_count_on_a_built_pdf(self) -> None:
        """
        Purpose:
            small_image_counts counts only the image at most the ratio of the page area.

        Inputs:
            None.

        Outputs:
            None. Asserts one small image on page 1 and none on page 2 for a ratio of 0.1.

        Raises:
            AssertionError: when the count does not match the built PDF.
        """
        with tempfile.TemporaryDirectory() as tmp:
            pdf = _make_pdf(
                Path(tmp) / "fictive.pdf",
                [
                    {"text": "Page one", "images": [(20, 100, 220, 300), (250, 20, 270, 40)]},
                    {"text": "Page two", "images": []},
                ],
            )
            counts = page_roles.small_image_counts(pdf, 0.1)
        self.assertEqual(counts, [1, 0])

    def test_small_image_ratio_out_of_range_is_refused(self) -> None:
        """
        Purpose:
            A ratio outside ]0, 1] is refused before the PDF is opened.

        Inputs:
            None.

        Outputs:
            None. Asserts ValueError for 0 and for 1.5.

        Raises:
            AssertionError: when an invalid ratio is accepted.
        """
        with self.assertRaises(ValueError):
            page_roles.small_image_counts(DATA_FILE, 0)
        with self.assertRaises(ValueError):
            page_roles.small_image_counts(DATA_FILE, 1.5)

    def test_excluded_pages_lists_reasons_in_page_order(self) -> None:
        """
        Purpose:
            excluded_pages returns 1-based page numbers in order, with the reason of each.

        Inputs:
            None.

        Outputs:
            None. Asserts a cover on page 1 and a version table on page 3, with page 2 kept.

        Raises:
            AssertionError: when the list or its order is wrong.
        """
        pages = [
            "Université Fictive\nRapport présenté à monsieur Exemple\nDépartement de génie",
            " ".join(["A fictive paragraph of ordinary body text."] * 15),
            "Historique des révisions\nVersion 1.0  révision initiale",
        ]
        result = page_roles.excluded_pages(pages, [1, 0, 0], self.markers)
        self.assertEqual(
            result,
            [{"page": 1, "reason": "cover"}, {"page": 3, "reason": "version_table"}],
        )


    def test_long_body_page_with_version_words_is_kept(self) -> None:
        """
        Purpose:
            A body page of about 300 words that uses "version" and "history" is graded, not excluded.
            Signature and version markers apply only to a page within max_cover_words (Issue 122, defect 1).

        Inputs:
            None.

        Outputs:
            None. Asserts the page on index 6 is kept.

        Raises:
            AssertionError: when a long body page is excluded as a version table.
        """
        sentence = "The fictive sample was heated slowly while readings accumulated in the log."
        body = " ".join([sentence] * 14)
        body += " The version of the fictive model and its history were compared with the reference."
        body += " A second version and the history of its runs were examined by the team."
        self.assertGreater(len(body.split()), self.markers["max_cover_words"])
        role = page_roles.classify_page(body, 6, 0, self.markers)
        self.assertIsNone(role)

    def test_short_version_table_is_excluded(self) -> None:
        """
        Purpose:
            A short page with two version markers is still excluded as a version table (Issue 122, defect 1).

        Inputs:
            None.

        Outputs:
            None. Asserts the role is "version_table".

        Raises:
            AssertionError: when a short version table is kept.
        """
        text = "Version 1.0 first draft\nHistory of the changes to the fictive model"
        role = page_roles.classify_page(text, 6, 0, self.markers)
        self.assertEqual(role, "version_table")

    def test_plural_is_not_a_marker(self) -> None:
        """
        Purpose:
            "versions" is not the marker "version": a short page with "versions" alone is kept, and a short page
            with "versions" and "history" counts one marker only, so it is kept too (Issue 122, defect 1).

        Inputs:
            None.

        Outputs:
            None. Asserts both pages are kept.

        Raises:
            AssertionError: when a plural word is read as a marker.
        """
        alone = "Several versions of the fictive tool were compared in the lab."
        with_history = "Several versions of the fictive tool and its history were compared."
        self.assertIsNone(page_roles.classify_page(alone, 6, 0, self.markers))
        self.assertIsNone(page_roles.classify_page(with_history, 6, 0, self.markers))


if __name__ == "__main__":
    unittest.main()
