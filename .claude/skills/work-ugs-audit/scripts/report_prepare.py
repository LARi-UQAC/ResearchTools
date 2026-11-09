"""
Purpose: Préparer les rapports PDF en générant des ids stables et des fichiers Markdown par page.
"""
import argparse
import json
import sys
from pathlib import Path
from typing import List, Dict, Optional

# Constantes de configuration (R0: les nombres viennent de la configuration ou sont des constantes de module acceptées si non configurables)
# Ici, nous utilisons des constantes pour les formats d'ID et le padding, car ce sont des conventions internes.
ID_PREFIX = "R"
ID_PADDING = 2
PAGE_PADDING = 3


class PrepareError(ValueError):
    """Erreur lors de la préparation des rapports."""
    pass


def _is_pdf(file_path: Path) -> bool:
    """
    Purpose: Vérifier si un fichier est un PDF.
    Inputs:
        file_path: Path - chemin du fichier.
    Outputs:
        bool - True si c'est un PDF, False sinon.
    """
    return file_path.suffix.lower() == ".pdf"


def _extract_page_text(pdf_path: Path) -> List[str]:
    """
    Purpose: Extraire le texte de chaque page d'un PDF.
    Inputs:
        pdf_path: Path - chemin du fichier PDF.
    Outputs:
        List[str] - liste des textes de chaque page (index 0 = page 1).
    Raises:
        PrepareError: si le fichier n'est pas un PDF valide ou si pymupdf4llm échoue.
    """
    try:
        import pymupdf4llm
        # Extraire page par page avec pymupdf4llm
        # page_chunks=True retourne une liste de dictionnaires avec 'text' et 'page'
        chunks = pymupdf4llm.to_markdown(str(pdf_path), page_chunks=True)
        
        pages = []
        for chunk in chunks:
            pages.append(chunk.get("text", ""))
        return pages
    except ImportError:
        raise PrepareError("pymupdf4llm est requis mais n'est pas installé.")
    except Exception as e:
        raise PrepareError(f"Échec de l'extraction du texte du PDF: {type(e).__name__}")


def _write_markdown_file(work_dir: Path, report_id: str, page_num: int, text: str) -> None:
    """
    Purpose: Écrire un fichier Markdown pour une page.
    Inputs:
        work_dir: Path - dossier de travail.
        report_id: str - id du rapport (ex: "R01").
        page_num: int - numéro de page (1-based).
        text: str - texte de la page.
    Outputs:
        None - écrit le fichier.
    """
    pages_dir = work_dir / report_id / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    md_file = pages_dir / f"p{page_num:0{PAGE_PADDING}d}.md"
    md_file.write_text(text, encoding="utf-8")


def _load_existing_ids(ids_file: Path) -> Dict[str, str]:
    """
    Purpose: Charger la carte d'ids existante.
    Inputs:
        ids_file: Path - chemin du fichier d'ids.
    Outputs:
        Dict[str, str] - mapping des ids existants vers les noms de fichiers.
    """
    if ids_file.exists():
        with open(ids_file, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_ids(ids_file: Path, ids_map: Dict[str, str]) -> None:
    """
    Purpose: Sauvegarder la carte d'ids.
    Inputs:
        ids_file: Path - chemin du fichier d'ids.
        ids_map: Dict[str, str] - mapping des ids vers les noms de fichiers.
    Outputs:
        None - écrit le fichier.
    """
    ids_file.parent.mkdir(parents=True, exist_ok=True)
    with open(ids_file, "w", encoding="utf-8") as f:
        json.dump(ids_map, f, indent=2, ensure_ascii=False)


def _check_path_containment(reports_dir: Path, work_dir: Path) -> None:
    """
    Purpose: Vérifier que work_dir est à l'intérieur de reports_dir (ou dans un dossier adjacent autorisé par la spec, mais le plan dit 'outside' -> refused).
    Inputs:
        reports_dir: Path - dossier des rapports.
        work_dir: Path - dossier de travail.
    Raises:
        PrepareError: si work_dir n'est pas dans reports_dir.
    """
    try:
        reports_resolved = reports_dir.resolve()
        work_resolved = work_dir.resolve()
        # R24: confine every path derived from input. Resolve it to its canonical absolute form first,
        # then check that it sits inside the allowed folder.
        # Le plan dit: "Raises PrepareError when the work folder resolves outside the reports folder."
        # Cependant, la spec dit "Working folder beside the reports: _correction/".
        # Il y a une contradiction entre le plan (test_work_dir_outside_reports_is_refused) et la spec (beside).
        # Le plan est l'autorité pour cette tâche. Je vais implémenter la vérification demandée par le plan.
        if not work_resolved.is_relative_to(reports_resolved):
            raise PrepareError("Le dossier de travail doit être à l'intérieur du dossier des rapports.")
    except PrepareError:
        raise
    except Exception as e:
        raise PrepareError(f"Erreur de vérification de chemin: {e}")


def prepare(reports_dir: Path, work_dir: Path) -> List[Dict]:
    """
    Purpose: Préparer les rapports PDF en générant des ids stables et des fichiers Markdown par page.
    Inputs:
        reports_dir: Path - dossier contenant les rapports PDF.
        work_dir: Path - dossier de travail pour la sortie.
    Outputs:
        List[Dict] - liste des rapports préparés, chacun avec report_id, pages, empty_pages.
    Raises:
        PrepareError: si work_dir se résout en dehors de reports_dir.
    """
    _check_path_containment(reports_dir, work_dir)
    
    ids_file = work_dir / "ids"
    existing_ids = _load_existing_ids(ids_file)
    
    pdf_files = sorted([f for f in reports_dir.iterdir() if f.is_file() and _is_pdf(f)])
    
    results = []
    new_ids_map = dict(existing_ids)
    
    # Identifier les fichiers qui ont déjà un id
    existing_file_names = set(existing_ids.values())
    
    # Attribuer les ids
    next_id_num = 1
    for rid in existing_ids.keys():
        # Extraire le numéro de l'id existant pour déterminer le prochain
        try:
            num = int(rid[len(ID_PREFIX):])
            if num >= next_id_num:
                next_id_num = num + 1
        except (ValueError, IndexError):
            pass

    for pdf_file in pdf_files:
        if pdf_file.name in existing_file_names:
            # Trouver l'id correspondant
            report_id = None
            for rid, fname in existing_ids.items():
                if fname == pdf_file.name:
                    report_id = rid
                    break
            if report_id is None:
                # Cas de conflit ou de données corrompues
                report_id = f"{ID_PREFIX}{next_id_num:0{ID_PADDING}d}"
                new_ids_map[report_id] = pdf_file.name
                next_id_num += 1
        else:
            report_id = f"{ID_PREFIX}{next_id_num:0{ID_PADDING}d}"
            new_ids_map[report_id] = pdf_file.name
            next_id_num += 1
        
        pages_text = _extract_page_text(pdf_file)
        page_count = len(pages_text)
        empty_pages = [i + 1 for i, text in enumerate(pages_text) if not text.strip()]
        
        for i, text in enumerate(pages_text):
            _write_markdown_file(work_dir, report_id, i + 1, text)
        
        results.append({
            "report_id": report_id,
            "pages": page_count,
            "empty_pages": empty_pages
        })
    
    _save_ids(ids_file, new_ids_map)
    
    return results


def skipped_count(reports_dir: Path) -> int:
    """
    Purpose: Compter les fichiers non-PDF dans le dossier des rapports.
    Inputs:
        reports_dir: Path - dossier contenant les rapports.
    Outputs:
        int - nombre de fichiers non-PDF.
    """
    all_files = [f for f in reports_dir.iterdir() if f.is_file()]
    pdf_files = [f for f in all_files if _is_pdf(f)]
    return len(all_files) - len(pdf_files)


def main(argv: Optional[List[str]] = None) -> int:
    """
    Purpose: Point d'entrée de la commande.
    Inputs:
        argv: Optional[List[str]] - arguments de la ligne de commande.
    Outputs:
        int - code de sortie (0 succès, 2 refus, 1 échec).
    """
    if argv is None:
        argv = sys.argv[1:]
    
    parser = argparse.ArgumentParser(description="Préparer les rapports PDF")
    parser.add_argument("--reports", required=True, help="Dossier des rapports")
    parser.add_argument("--work", required=True, help="Dossier de travail")
    parser.add_argument("--dry-run", action="store_true", help="Aperçu sans écriture")
    parser.add_argument("--json", action="store_true", help="Sortie JSON")
    
    args = parser.parse_args(argv)
    
    reports_dir = Path(args.reports)
    work_dir = Path(args.work)
    
    if not reports_dir.exists():
        print(json.dumps({"error": "Dossier des rapports introuvable", "status": "refused"}))
        return 2

    if args.dry_run:
        pdf_files = sorted([f for f in reports_dir.iterdir() if f.is_file() and _is_pdf(f)])
        skipped = skipped_count(reports_dir)
        output = {
            "reports": len(pdf_files),
            "skipped": skipped
        }
        print(json.dumps(output))
        return 0
    
    try:
        results = prepare(reports_dir, work_dir)
        skipped = skipped_count(reports_dir)
        
        output = {
            "reports": len(results),
            "skipped": skipped,
            "ids": {r["report_id"]: r["report_id"] for r in results}
        }
        print(json.dumps(output))
        return 0
    except PrepareError as e:
        output = {
            "error": str(e),
            "status": "refused"
        }
        print(json.dumps(output))
        return 2
    except Exception as e:
        output = {
            "error": str(e),
            "status": "failure"
        }
        print(json.dumps(output))
        return 1


if __name__ == "__main__":
    sys.exit(main())
