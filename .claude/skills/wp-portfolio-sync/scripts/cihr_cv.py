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
from pathlib import Path

try:
    import defusedxml.ElementTree as ET
    from defusedxml.common import DefusedXmlException
except ImportError:  # degrades to stdlib: no entity-expansion guard, but never silent (R8)
    import xml.etree.ElementTree as ET

    DefusedXmlException = ()  # an empty except-tuple: nothing extra to catch without defusedxml
    print(
        "AVERTISSEMENT: defusedxml n'est pas installe - utilisation de xml.etree.ElementTree "
        "standard, sans protection contre les entites XML malveillantes ('pip install -r "
        "requirements.txt' dans scripts/ pour l'installer)",
        file=sys.stderr,
    )

from wp_common import atomic_write_text, configure_streams, error_report
from wp_errors import WpRefusal, exit_code_for
from wp_paths import contained_path, resolve_data_dir

ROOT_TAG = "generic-cv"

_LABELS_FILE = Path(__file__).resolve().parent / "cihr_labels.json"


def _load_labels(path=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Load the French/English label synonym table (R6, Q6) this module's
        section and field matchers read.

    Inputs:
        path (Path or None): override for the labels file; None reads
        cihr_labels.json beside this module.

    Outputs:
        labels (dict): the parsed document ("sections", "substrings",
        "evenements", "fields" keys).

    Raises:
        WpRefusal: the file is missing or is not a JSON object (R3).
    --------------------------------------------------------------------------
    """
    resolved = path if path is not None else _LABELS_FILE
    try:
        with open(resolved, "r", encoding="utf-8") as handle:
            doc = json.load(handle)
        if not isinstance(doc, dict):
            raise ValueError("cihr_labels.json must be a JSON object")
        return doc
    except (OSError, ValueError) as exc:
        raise WpRefusal("cihr_labels.json is missing or malformed: %s" % resolved) from exc


_LABELS = _load_labels()


def _section_names(key):
    return _LABELS["sections"][key]


def _is_events_label(label):
    lowered = label.lower()
    return any(all(part.lower() in lowered for part in parts) for parts in _LABELS["evenements"])


def _fget(d, field_key):
    for name in _LABELS["fields"][field_key]:
        value = d.get(name)
        if value:
            return value
    return ""


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


def _sections_of(root, section_key):
    names = _section_names(section_key)
    return [s for s in root if _tag(s) == "section" and s.get("label") in names]


def _parse_financement(root):
    out = []
    for s in _sections_of(root, "financement"):
        rec = _fields(s)
        sources, cochercheurs = [], []
        for sub in s:
            if _tag(sub) != "section":
                continue
            label = sub.get("label") or ""
            if label in _section_names("sources"):
                d = _fields(sub)
                sources.append(
                    {
                        "organisme": _fget(d, "organisme_financement"),
                        "programme": _fget(d, "nom_programme"),
                        "montant_total": _fget(d, "montant_total"),
                        "portion_recue": _fget(d, "portion_recue"),
                        "competitif": _fget(d, "competitif"),
                    }
                )
            elif label in _section_names("cochercheurs"):
                d = _fields(sub)
                if any(d.values()):
                    cochercheurs.append(
                        {"nom": _fget(d, "nom_chercheur") or _fget(d, "nom"), "role": _fget(d, "role")}
                    )
        out.append(
            {
                "titre": _fget(rec, "titre_financement"),
                "type": _fget(rec, "type_financement"),
                "statut": _fget(rec, "statut_financement"),
                "role": _fget(rec, "role"),
                "debut": _fget(rec, "debut_financement"),
                "fin": _fget(rec, "fin_financement"),
                "sources": sources,
                "cochercheurs": cochercheurs,
            }
        )
    return out


def _parse_implications(root):
    out = []
    for adh in _sections_of(root, "adhesions"):
        for x in adh:
            if _tag(x) != "section":
                continue
            label = x.get("label")
            is_comite = label in _section_names("membre_comite")
            is_organisme = label in _section_names("membre_organisme")
            if not is_comite and not is_organisme:
                continue
            d = _fields(x)
            out.append(
                {
                    "categorie": "comite" if is_comite else "organisme",
                    "nom": _fget(d, "nom_comite") or _fget(d, "nom_organisme"),
                    "role": _fget(d, "role"),
                    "organisation": _fget(d, "autre_organisation") or _fget(d, "organisation"),
                    "debut": _fget(d, "debut_adhesion"),
                    "fin": _fget(d, "fin_adhesion"),
                    "description": _fget(d, "description"),
                }
            )
    return out


def _parse_services(root):
    out = []
    for contrib in _sections_of(root, "contributions"):
        for sub in contrib:
            if _tag(sub) != "section":
                continue
            label = (sub.get("label") or "").lower()
            if any(term in label for term in _LABELS["substrings"]["medias"]):
                for x in sub:
                    if _tag(x) != "section":
                        continue
                    d = _fields(x)
                    out.append(
                        {
                            "type": "media",
                            "sujet": _fget(d, "sujet"),
                            "diffuseur": _fget(d, "emission") or _fget(d, "tribune"),
                            "chaine": _fget(d, "chaine"),
                            "date": _fget(d, "date_diffusion") or _fget(d, "date_publication"),
                        }
                    )
    for acts in _sections_of(root, "activites"):
        stack = [sub for sub in acts if _tag(sub) == "section"]
        seen = set()
        while stack:
            sub = stack.pop(0)
            if id(sub) in seen:
                continue
            seen.add(id(sub))
            label = sub.get("label") or ""
            if any(term in label.lower() for term in _LABELS["substrings"]["connaissances"]):
                d = _fields(sub)
                out.append(
                    {
                        "type": "entreprise",
                        "role": _fget(d, "role"),
                        "activite": _fget(d, "type_activite_connaissances"),
                        "organisation": _fget(d, "organisation_beneficiaire"),
                        "resultat": _fget(d, "resultat"),
                        "retombees": _fget(d, "retombees"),
                        "debut": _fget(d, "date_debut"),
                        "fin": _fget(d, "date_fin"),
                    }
                )
            if _is_events_label(label):
                d = _fields(sub)
                out.append(
                    {
                        "type": "evenement",
                        "role": _fget(d, "role"),
                        "nom": _fget(d, "nom_evenement"),
                        "debut": _fget(d, "debut_activite"),
                        "fin": _fget(d, "fin_activite"),
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
        if label in _section_names("distinctions_marques"):
            d = _fields(s)
            prix.append(
                {
                    "nom": _fget(d, "nom_reconnaissance"),
                    "organisation": _fget(d, "autre_organisation"),
                    "debut": _fget(d, "date_debut"),
                    "fin": _fget(d, "date_fin"),
                    "montant": _fget(d, "montant"),
                    "description": _fget(d, "description"),
                }
            )
        elif label in _section_names("distinctions_cles"):
            d = _fields(s)
            cles.append(
                {
                    "titre": _fget(d, "titre"),
                    "date": _fget(d, "date_contribution"),
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

    def _fail(line, message, code):
        print(line, file=sys.stderr)
        if args.json:
            print(json.dumps(error_report(message, code), ensure_ascii=False))
        return code

    try:
        data_dir = resolve_data_dir(args.data_dir)
        xml_path = contained_path(data_dir, args.xml)
        out_path = contained_path(data_dir, args.out)
    except WpRefusal as exc:
        return _fail("REFUS: %s" % exc, str(exc), exit_code_for(exc))

    try:
        root = ET.parse(str(xml_path)).getroot()
    except ET.ParseError as exc:
        return _fail("ERREUR: XML invalide: %s" % exc, str(exc), 1)
    except DefusedXmlException as exc:
        return _fail("ERREUR: XML refuse (protection contre les entites) : %s" % exc, str(exc), 1)
    except OSError as exc:
        return _fail("ERREUR: fichier illisible: %s" % exc, str(exc), 1)

    if _tag(root) != ROOT_TAG:
        message = "racine XML inattendue '%s' (attendu '%s')" % (_tag(root), ROOT_TAG)
        return _fail("ERREUR: %s" % message, message, 1)

    data = parse_cihr(root)
    if count_records(data) == 0:
        message = (
            "aucune section reconnue. Ce parseur ne reconnaît que les libellés "
            "français et anglais d'un export CV générique CIHR."
        )
        return _fail("ERREUR: %s" % message, message, 1)

    counts = {
        key: ({sub: len(sv) for sub, sv in value.items()} if isinstance(value, dict) else len(value))
        for key, value in data.items()
    }

    if args.dry_run:
        print("SIMULATION: would write %s" % out_path, file=sys.stderr)
    else:
        atomic_write_text(out_path, json.dumps(data, ensure_ascii=False, indent=1))

    for key, count in counts.items():
        print("  %-20s %s" % (key, count), file=sys.stderr)

    if args.json:
        print(json.dumps({"out": str(out_path), "dry_run": args.dry_run, "counts": counts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
