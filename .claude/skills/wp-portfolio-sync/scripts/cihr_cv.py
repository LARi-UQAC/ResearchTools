"""
cihr_cv.py - parse a CIHR / Canadian Common CV generic-cv XML export into a
structured JSON document.

Stage: reads the researcher's final CCV export once (D1). There is no
supervision parser and no "supervision" key (D2): student data never leaves
the XML through this module, by construction rather than by filtering.
"""
import argparse
import json
import sys

try:
    import defusedxml.ElementTree as ET
except ImportError:  # pragma: no cover - degrades to stdlib, same file either parses or doesn't
    import xml.etree.ElementTree as ET

from wp_common import configure_streams
from wp_errors import WpRefusal, exit_code_for
from wp_paths import contained_path, resolve_data_dir

ROOT_TAG = "generic-cv"


def _tag(elem):
    return elem.tag.rsplit("}", 1)[-1]


def _fval(field):
    for child in field:
        tag = _tag(child)
        if tag in ("value", "lov"):
            return (child.text or "").strip()
        if tag == "refTable":
            return ", ".join(
                linked.get("value")
                for linked in child.iter()
                if _tag(linked) == "linkedWith" and linked.get("value")
            )
    return ""


def _fields(section):
    return {f.get("label"): _fval(f) for f in section if _tag(f) == "field"}


def _sections_of(root, label):
    return [s for s in root if _tag(s) == "section" and s.get("label") == label]


def _parse_financement(root):
    out = []
    for s in _sections_of(root, "Historique du financement de la recherche"):
        rec = _fields(s)
        sources, cochercheurs = [], []
        for sub in s:
            if _tag(sub) != "section":
                continue
            if sub.get("label") == "Sources de financement":
                d = _fields(sub)
                sources.append(
                    {
                        "organisme": d.get("Organisme de financement", ""),
                        "programme": d.get("Nom du programme", ""),
                        "montant_total": d.get("Montant total", ""),
                        "portion_recue": d.get("Portion de financement reçu", ""),
                        "competitif": d.get("Est-ce que le financement est compétitif?", ""),
                    }
                )
            elif sub.get("label") == "Autres chercheurs":
                d = _fields(sub)
                if any(d.values()):
                    cochercheurs.append(
                        {"nom": d.get("Nom du chercheur") or d.get("Nom", ""), "role": d.get("Rôle", "")}
                    )
        out.append(
            {
                "titre": rec.get("Titre du financement", ""),
                "type": rec.get("Type de financement", ""),
                "statut": rec.get("Statut du financement", ""),
                "role": rec.get("Rôle", ""),
                "debut": rec.get("Début de financement", ""),
                "fin": rec.get("Fin de financement", ""),
                "sources": sources,
                "cochercheurs": cochercheurs,
            }
        )
    return out


def _parse_implications(root):
    out = []
    for adh in _sections_of(root, "Adhésions"):
        for x in adh:
            if _tag(x) != "section":
                continue
            label = x.get("label")
            if label not in ("Membre de comité", "Membre d'autres organismes"):
                continue
            d = _fields(x)
            out.append(
                {
                    "categorie": "comite" if label == "Membre de comité" else "organisme",
                    "nom": d.get("Nom du comité") or d.get("Nom de l'organisme", ""),
                    "role": d.get("Rôle", ""),
                    "organisation": d.get("Autre organisation") or d.get("Organisation", ""),
                    "debut": d.get("Date de début de l'adhésion", ""),
                    "fin": d.get("Date de fin de l'adhésion", ""),
                    "description": d.get("Description", ""),
                }
            )
    return out


def _parse_services(root):
    out = []
    for contrib in _sections_of(root, "Contributions"):
        for sub in contrib:
            if _tag(sub) != "section":
                continue
            if "médias" in (sub.get("label") or ""):
                for x in sub:
                    if _tag(x) != "section":
                        continue
                    d = _fields(x)
                    out.append(
                        {
                            "type": "media",
                            "sujet": d.get("Sujet", ""),
                            "diffuseur": d.get("Émission") or d.get("Tribune", ""),
                            "chaine": d.get("Chaîne", ""),
                            "date": d.get("Date de la première diffusion") or d.get("Date de publication", ""),
                        }
                    )
    for acts in _sections_of(root, "Activités"):
        stack = [sub for sub in acts if _tag(sub) == "section"]
        seen = set()
        while stack:
            sub = stack.pop(0)
            if id(sub) in seen:
                continue
            seen.add(id(sub))
            label = sub.get("label") or ""
            if "connaissances" in label:
                d = _fields(sub)
                out.append(
                    {
                        "type": "entreprise",
                        "role": d.get("Rôle", ""),
                        "activite": d.get(
                            "Type d'activité d'application des connaissances et de la technologie", ""
                        ),
                        "organisation": d.get(
                            "Groupe, organisation ou entreprise bénéficiant des services", ""
                        ),
                        "resultat": d.get("Résultat", ""),
                        "retombees": d.get("Preuve de l'adoption ou des retombées", ""),
                        "debut": d.get("Date de début", ""),
                        "fin": d.get("Date de fin", ""),
                    }
                )
            if "Gestion d" in label and "vènements" in label:
                d = _fields(sub)
                out.append(
                    {
                        "type": "evenement",
                        "role": d.get("Rôle", ""),
                        "nom": d.get("Nom de l'événement", ""),
                        "debut": d.get("Date de début de l'activité", ""),
                        "fin": d.get("Date de fin de l'activité", ""),
                    }
                )
            stack.extend(ch for ch in sub if _tag(ch) == "section")
    return out


def _parse_distinctions(root):
    prix, cles = [], []
    for s in root:
        if _tag(s) != "section":
            continue
        label = (s.get("label") or "").strip()
        if label == "Marques de reconnaissance":
            d = _fields(s)
            prix.append(
                {
                    "nom": d.get("Nom de la reconnaissance", ""),
                    "organisation": d.get("Autre organisation", ""),
                    "debut": d.get("Date de début", ""),
                    "fin": d.get("Date de fin", ""),
                    "montant": d.get("Montant", ""),
                    "description": d.get("Description", ""),
                }
            )
        elif label == "Contributions les plus importantes":
            d = _fields(s)
            cles.append(
                {
                    "titre": d.get("Titre", ""),
                    "date": d.get("Date du contribution", ""),
                    "description": d.get("Description/Valeur/Impact", ""),
                }
            )
    return {"prix": prix, "contributions_cles": cles}


def parse_cihr(root):
    """
    --------------------------------------------------------------------------
    Purpose:
        Parse a CIHR generic-cv XML root into the four record sections this
        skill publishes. There is no supervision parser and no
        "supervision" key: student data is never extracted here (D2).

    Inputs:
        root (xml.etree.ElementTree.Element): the namespaced generic-cv root.

    Outputs:
        data (dict): exactly the keys "financement", "implications",
        "services_communaute" and "distinctions" (the last a dict with
        "prix" and "contributions_cles" lists).
    --------------------------------------------------------------------------
    """
    return {
        "financement": _parse_financement(root),
        "implications": _parse_implications(root),
        "services_communaute": _parse_services(root),
        "distinctions": _parse_distinctions(root),
    }


def count_records(data):
    """
    --------------------------------------------------------------------------
    Purpose:
        Count every record parse_cihr produced, across all four keys,
        counting both distinctions sub-lists.

    Inputs:
        data (dict): the document returned by parse_cihr.

    Outputs:
        total (int): the sum of every record across all sections.
    --------------------------------------------------------------------------
    """
    total = 0
    for value in data.values():
        if isinstance(value, dict):
            total += sum(len(v) for v in value.values())
        else:
            total += len(value)
    return total


def main(argv=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        CLI entry point: parse a CIHR XML export and write it as JSON under
        the researcher's data folder.

    Inputs:
        argv (list[str] or None): CLI arguments; None reads sys.argv.

    Outputs:
        exit_code (int): 0 on success, 1 on a parse/content failure, 2 on a
        refusal by design (spec section 6).
    --------------------------------------------------------------------------
    """
    configure_streams()
    parser = argparse.ArgumentParser(description="Parse a CIHR generic-cv XML export into JSON.")
    parser.add_argument("xml")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--out", default="cihr.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        data_dir = resolve_data_dir(args.data_dir)
        xml_path = contained_path(data_dir, args.xml)
        out_path = contained_path(data_dir, args.out)
    except WpRefusal as exc:
        print("REFUS: %s" % exc, file=sys.stderr)
        return exit_code_for(exc)

    try:
        root = ET.parse(str(xml_path)).getroot()
    except ET.ParseError as exc:
        print("ERREUR: XML invalide: %s" % exc, file=sys.stderr)
        return 1
    except OSError as exc:
        print("ERREUR: fichier illisible: %s" % exc, file=sys.stderr)
        return 1

    if _tag(root) != ROOT_TAG:
        print(
            "ERREUR: racine XML inattendue '%s' (attendu '%s')" % (_tag(root), ROOT_TAG),
            file=sys.stderr,
        )
        return 1

    data = parse_cihr(root)
    if count_records(data) == 0:
        print(
            "ERREUR: aucune section reconnue. Ce parseur ne reconnaît que les libellés "
            "français d'un export CV générique CIHR.",
            file=sys.stderr,
        )
        return 1

    counts = {
        key: ({sub: len(sv) for sub, sv in value.items()} if isinstance(value, dict) else len(value))
        for key, value in data.items()
    }

    if args.dry_run:
        print("SIMULATION: would write %s" % out_path, file=sys.stderr)
    else:
        with open(out_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=1)

    for key, count in counts.items():
        print("  %-20s %s" % (key, count), file=sys.stderr)

    if args.json:
        print(json.dumps({"out": str(out_path), "dry_run": args.dry_run, "counts": counts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
