import sys
from pathlib import Path
import unittest
import json
import tempfile
import shutil

# Met le dossier scripts au début de sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Met le dossier figure-review/Test au début de sys.path pour _pdf_fixtures
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "figure-review" / "scripts" / "Test"))

from report_prepare import prepare, skipped_count, PrepareError, main
from _pdf_fixtures import make_report


class TestReportPrepare(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.reports_dir = self.tmp_dir / "reports"
        self.reports_dir.mkdir()
        # Le plan exige que work_dir soit DANS reports_dir pour les tests de refus,
        # mais la spec dit "beside". 
        # Pour satisfaire le test `test_work_dir_outside_reports_is_refused` du plan,
        # nous devons utiliser un work_dir DANS reports_dir pour les cas valides,
        # et un work_dir EN DEHORS pour le cas de refus.
        # Cependant, les autres tests (comme `test_ids_follow_sorted_names`) utilisent `self.work_dir`.
        # Si nous changeons `self.work_dir` à l'intérieur de `reports_dir`, les tests de refus passeront.
        # Mais la spec dit "beside". 
        # Le plan est prioritaire. Je vais définir work_dir DANS reports_dir.
        self.work_dir = self.reports_dir / "_correction"

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    def test_ids_follow_sorted_names_and_are_stable_on_rerun(self):
        """Les ids suivent l'ordre trié des noms de fichiers et sont stables à la réexécution."""
        make_report(self.reports_dir / "report_b.pdf", [{"text": "Page 1"}])
        make_report(self.reports_dir / "report_a.pdf", [{"text": "Page 1"}])
        
        result = prepare(self.reports_dir, self.work_dir)
        
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["report_id"], "R01")
        self.assertEqual(result[1]["report_id"], "R02")
        
        # Vérifier la carte d'ids
        ids_file = self.work_dir / "ids"
        self.assertTrue(ids_file.exists())
        with open(ids_file, encoding="utf-8") as f:
            ids_map = json.load(f)
        self.assertEqual(ids_map["R01"], "report_a.pdf")
        self.assertEqual(ids_map["R02"], "report_b.pdf")
        
        # Réexécuter, les ids doivent rester les mêmes
        result2 = prepare(self.reports_dir, self.work_dir)
        self.assertEqual(result2[0]["report_id"], "R01")
        self.assertEqual(result2[1]["report_id"], "R02")

    def test_non_pdf_files_are_skipped_and_counted(self):
        """Les fichiers non-PDF sont sautés et comptés."""
        make_report(self.reports_dir / "report.pdf", [{"text": "Page 1"}])
        (self.reports_dir / "notes.txt").touch()
        (self.reports_dir / "image.png").touch()
        
        result = prepare(self.reports_dir, self.work_dir)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["report_id"], "R01")
        
        skipped = skipped_count(self.reports_dir)
        self.assertEqual(skipped, 2)

    def test_one_markdown_file_per_page_with_accents_kept(self):
        """Un fichier Markdown par page, avec les accents conservés."""
        make_report(self.reports_dir / "report.pdf", [{"text": "Étude des réseaux électriques"}])
        
        result = prepare(self.reports_dir, self.work_dir)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["pages"], 1)
        
        md_file = self.work_dir / "R01" / "pages" / "p001.md"
        self.assertTrue(md_file.exists())
        content = md_file.read_text(encoding="utf-8")
        self.assertIn("Étude des réseaux électriques", content)

    def test_an_empty_page_is_flagged_and_its_file_is_empty(self):
        """Une page vide est signalée et son fichier est vide."""
        make_report(self.reports_dir / "report.pdf", [{}])
        
        result = prepare(self.reports_dir, self.work_dir)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["empty_pages"], [1])
        
        md_file = self.work_dir / "R01" / "pages" / "p001.md"
        self.assertTrue(md_file.exists())
        self.assertEqual(md_file.read_text(encoding="utf-8").strip(), "")

    def test_work_dir_outside_reports_is_refused(self):
        """Le dossier de travail en dehors des rapports est refusé."""
        outside_work_dir = self.tmp_dir / "outside_work"
        make_report(self.reports_dir / "report.pdf", [{"text": "Page 1"}])
        
        with self.assertRaises(PrepareError):
            prepare(self.reports_dir, outside_work_dir)

    def test_stdout_never_carries_a_file_name(self):
        """La sortie ne porte jamais un nom de fichier."""
        import io
        from contextlib import redirect_stdout
        
        make_report(self.reports_dir / "etudiant_nom.pdf", [{"text": "Page 1"}])
        
        f = io.StringIO()
        with redirect_stdout(f):
            ret = main(["--reports", str(self.reports_dir), "--work", str(self.work_dir)])
            self.assertEqual(ret, 0)
        
        output = f.getvalue()
        self.assertNotIn("etudiant_nom.pdf", output)
        json_line = json.loads(output.strip())
        self.assertIn("ids", json_line)

    def test_dry_run_writes_nothing(self):
        """--dry-run n'écrit rien."""
        make_report(self.reports_dir / "report.pdf", [{"text": "Page 1"}])
        
        import io
        from contextlib import redirect_stdout
        
        f = io.StringIO()
        with redirect_stdout(f):
            ret = main(["--reports", str(self.reports_dir), "--work", str(self.work_dir), "--dry-run"])
            self.assertEqual(ret, 0)
        
        # Le dossier de travail ne doit pas exister ou être vide
        if self.work_dir.exists():
            self.assertEqual(list(self.work_dir.iterdir()), [])
        else:
            self.assertFalse(self.work_dir.exists())

    def test_a_report_added_later_gets_the_next_id_and_keeps_the_old_ones(self):
        """Un rapport ajouté plus tard reçoit le prochain id et conserve les anciens."""
        make_report(self.reports_dir / "report_a.pdf", [{"text": "Page 1"}])
        prepare(self.reports_dir, self.work_dir)
        
        make_report(self.reports_dir / "report_b.pdf", [{"text": "Page 1"}])
        result = prepare(self.reports_dir, self.work_dir)
        
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["report_id"], "R01")
        self.assertEqual(result[1]["report_id"], "R02")
        
        with open(self.work_dir / "ids", encoding="utf-8") as f:
            ids_map = json.load(f)
        self.assertEqual(ids_map["R01"], "report_a.pdf")
        self.assertEqual(ids_map["R02"], "report_b.pdf")


if __name__ == "__main__":
    unittest.main()
