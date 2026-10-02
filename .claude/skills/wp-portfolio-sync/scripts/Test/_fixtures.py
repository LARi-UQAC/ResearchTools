"""
_fixtures.py - shared test fixtures for the wp-portfolio-sync skill.

Stage: imported by every test_*.py in this folder. Never discovered as a
suite itself (leading underscore), per run-offline-tests.ps1's discovery
rule.
"""
import sys
from pathlib import Path

# scripts/Test/_fixtures.py -> parents[1] is scripts/
SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def make_data_dir(root, files):
    """
    --------------------------------------------------------------------------
    Purpose:
        Build a fictitious researcher data folder for an offline test, never
        touching a real data folder or /tmp (R21).

    Inputs:
        root (Path): a tempfile.TemporaryDirectory() path or similar scratch
            root; the data folder is created at root/data.
        files (dict[str, str]): relative path -> UTF-8 text content. Parent
            directories are created as needed.

    Outputs:
        data_dir (Path): root/data, existing, with every file written.
    --------------------------------------------------------------------------
    """
    data_dir = Path(root) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    for relative, text in files.items():
        target = data_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return data_dir


class FakeResponse:
    """
    --------------------------------------------------------------------------
    Purpose:
        A fake requests.Response, for WpClient tests that never touch the
        network.

    Inputs:
        status_code (int): the HTTP status to report.
        json_data: the object .json() returns; None makes .json() raise
            ValueError, matching a response with no JSON body.
        text (str): the raw body, used for an error message's first 200 chars.

    Outputs:
        none (state object).
    --------------------------------------------------------------------------
    """

    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        if self._json_data is None:
            raise ValueError("no JSON body")
        return self._json_data


class _FakeCookieJar:
    """A fake requests.Session.cookies jar: records every .set() call."""

    def __init__(self):
        self.set_calls = []

    def set(self, name, value, domain="", path="/"):
        self.set_calls.append((name, value, domain, path))


class FakeSession:
    """
    --------------------------------------------------------------------------
    Purpose:
        A fake requests.Session for WpClient tests: consumes a fixed list of
        responses/exceptions in order, regardless of whether .get or .put
        reads next, and records every call for assertion.

    Inputs:
        outcomes (list): FakeResponse instances or exception instances,
            consumed in call order by whichever of .get/.put is invoked.

    Outputs:
        none (state object). `.calls` holds (method, url, params_or_json,
        timeout) tuples in call order.
    --------------------------------------------------------------------------
    """

    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls = []
        self.auth = None
        self.cookies = _FakeCookieJar()

    def _consume(self, method, url, params_or_json, timeout):
        self.calls.append((method, url, params_or_json, timeout))
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def get(self, url, params=None, timeout=None):
        return self._consume("GET", url, params, timeout)

    def put(self, url, json=None, timeout=None):
        return self._consume("PUT", url, json, timeout)


def settings(ref_year=2026, window=6, label="Six dernières années", excluded=()):
    """
    --------------------------------------------------------------------------
    Purpose:
        Build a fictitious RenderSettings for a render.py/verify_titles.py/
        push_wp.py test, with the same defaults the drafted code used
        (ref_year 2026, window 6), so a byte-identical-output test can
        still be written without repeating these numbers everywhere.

    Inputs:
        ref_year (int), window (int), label (str), excluded (iterable[str]):
            see render.RenderSettings.

    Outputs:
        settings (render.RenderSettings).
    --------------------------------------------------------------------------
    """
    import render

    return render.RenderSettings(ref_year=ref_year, window=window, recent_label=label, excluded_funding_statuses=tuple(excluded))


def grant(titre="Projet fictif A", debut="2024/1", fin="2026/1", statut="Obtenu", montant="100000", role="Chercheur principal"):
    """Build a fictitious financement record (parse_cihr shape)."""
    return {
        "titre": titre,
        "type": "Subvention",
        "statut": statut,
        "role": role,
        "debut": debut,
        "fin": fin,
        "sources": [
            {
                "organisme": "Organisme Fictif",
                "programme": "Programme Fictif",
                "montant_total": montant,
                "portion_recue": "",
                "competitif": "Oui",
            }
        ],
        "cochercheurs": [],
    }


def implication(nom="Comité Fictif Alpha", organisation="", categorie="comite", debut="2020/1", fin=""):
    """Build a fictitious implications record (parse_cihr shape)."""
    return {
        "categorie": categorie,
        "nom": nom,
        "role": "Membre",
        "organisation": organisation,
        "debut": debut,
        "fin": fin,
        "description": "",
    }


def media(sujet="Entrevue fictive https://example.org/a", diffuseur="Emission Fictive", date="2024/3"):
    """Build a fictitious media-type services_communaute record."""
    return {"type": "media", "sujet": sujet, "diffuseur": diffuseur, "chaine": "Chaîne Fictive", "date": date}


def entreprise(organisation="Entreprise Fictif Gamma", role="Responsable", debut="2023/1", fin="2023/6"):
    """Build a fictitious entreprise-type services_communaute record."""
    return {
        "type": "entreprise",
        "role": role,
        "activite": "Atelier",
        "organisation": organisation,
        "resultat": "Succès",
        "retombees": "Adoption",
        "debut": debut,
        "fin": fin,
    }


def evenement(nom="Évènement Fictif Delta", debut="2022/1", fin="2022/1"):
    """Build a fictitious evenement-type services_communaute record."""
    return {"type": "evenement", "role": "Organisateur", "nom": nom, "debut": debut, "fin": fin}


def prix(nom="Prix Fictif Epsilon", organisation="Organisation Fictive Zeta", fin="2024/1", montant=""):
    """Build a fictitious distinctions/prix record."""
    return {"nom": nom, "organisation": organisation, "debut": "2024/1", "fin": fin, "montant": montant, "description": ""}


def contribution_cle(titre="Contribution fictive clé", description="Description fictive"):
    """Build a fictitious distinctions/contributions_cles record."""
    return {"titre": titre, "date": "2020/1", "description": description}


def student(
    etudiant="Étudiant Fictif Un",
    type_diplome="Doctorat",
    statut="En cours",
    debut="2022/9",
    fin="",
    role="Directeur de recherche",
    titre_projet="Projet fictif",
    **extra,
):
    """Build a fictitious render_phq student record (Phase 2 shape, D3)."""
    rec = {
        "etudiant": etudiant,
        "type_diplome": type_diplome,
        "statut": statut,
        "debut": debut,
        "fin": fin,
        "role": role,
        "titre_projet": titre_projet,
    }
    rec.update(extra)
    return rec


_CIHR_NS = "http://www.cihr-irsc.gc.ca/generic-cv/1.0.0"


def _el(tag, label=None):
    import xml.etree.ElementTree as ET

    elem = ET.Element("{%s}%s" % (_CIHR_NS, tag))
    if label:
        elem.set("label", label)
    return elem


def _field(label, text):
    import xml.etree.ElementTree as ET

    f = _el("field", label)
    value = ET.SubElement(f, "{%s}value" % _CIHR_NS)
    value.set("type", "String")
    value.text = text
    return f


def write_cihr_xml(path, include_supervision=True):
    """
    --------------------------------------------------------------------------
    Purpose:
        Write a fictitious CIHR generic-cv XML export exercising every
        section cihr_cv.py reads, plus (optionally) a supervision section
        that cihr_cv.py must never read (D2: data minimisation proof).

    Inputs:
        path (Path): where to write the XML file.
        include_supervision (bool): whether to add an
            Activités > Activités de supervision record naming a fictitious
            student ("Étudiante Témoin Zeta").

    Outputs:
        none. Writes the file at path.
    --------------------------------------------------------------------------
    """
    import xml.etree.ElementTree as ET

    ET.register_namespace("", _CIHR_NS)
    root = _el("generic-cv")

    for titre, debut, fin, statut in [
        ("Projet fictif A", "2024/1", "2026/1", "Obtenu"),
        ("Projet fictif B", "2010/1", "2015/1", "Terminé"),
    ]:
        s = _el("section", "Historique du financement de la recherche")
        s.set("recordId", titre)
        s.append(_field("Titre du financement", titre))
        s.append(_field("Statut du financement", statut))
        s.append(_field("Début de financement", debut))
        s.append(_field("Fin de financement", fin))
        sources = _el("section", "Sources de financement")
        sources.append(_field("Organisme de financement", "Organisme Fictif"))
        sources.append(_field("Nom du programme", "Programme Fictif"))
        sources.append(_field("Montant total", "100000"))
        s.append(sources)
        root.append(s)

    adhesions = _el("section", "Adhésions")
    comite = _el("section", "Membre de comité")
    comite.append(_field("Nom du comité", "Comité Fictif Alpha"))
    comite.append(_field("Rôle", "Membre"))
    adhesions.append(comite)
    organisme = _el("section", "Membre d'autres organismes")
    organisme.append(_field("Nom de l'organisme", "Organisation Fictive Beta"))
    organisme.append(_field("Rôle", "Membre"))
    adhesions.append(organisme)
    root.append(adhesions)

    contributions = _el("section", "Contributions")
    medias = _el("section", "Présence dans les médias")
    item = _el("section")
    item.append(_field("Sujet", "Entrevue sur un sujet fictif https://example.org/a"))
    item.append(_field("Émission", "Emission Fictive"))
    item.append(_field("Chaîne", "Chaîne Fictive"))
    item.append(_field("Date de la première diffusion", "2024/3"))
    medias.append(item)
    contributions.append(medias)
    root.append(contributions)

    activites = _el("section", "Activités")
    wrapper = _el("section", "Activités diverses")
    connaissances = _el("section", "Transfert de connaissances et de la technologie")
    connaissances.append(_field("Rôle", "Responsable"))
    connaissances.append(
        _field(
            "Type d'activité d'application des connaissances et de la technologie",
            "Atelier fictif",
        )
    )
    connaissances.append(
        _field(
            "Groupe, organisation ou entreprise bénéficiant des services",
            "Entreprise Fictif Gamma",
        )
    )
    connaissances.append(_field("Date de début", "2023/1"))
    connaissances.append(_field("Date de fin", "2023/6"))
    wrapper.append(connaissances)
    activites.append(wrapper)

    evenement = _el("section", "Gestion d'évènements")
    evenement.append(_field("Rôle", "Organisateur"))
    evenement.append(_field("Nom de l'événement", "Évènement Fictif Delta"))
    evenement.append(_field("Date de début de l'activité", "2022/1"))
    activites.append(evenement)

    if include_supervision:
        supervision = _el("section", "Activités de supervision")
        record = _el("section")
        record.append(_field("Etudiant", "Étudiante Témoin Zeta"))
        record.append(_field("Type de diplôme ou statut postdoctoral", "Maîtrise"))
        record.append(_field("Statut de l'étudiant", "En cours"))
        supervision.append(record)
        activites.append(supervision)

    root.append(activites)

    prix = _el("section", "Marques de reconnaissance")
    prix.append(_field("Nom de la reconnaissance", "Prix Fictif Epsilon"))
    prix.append(_field("Autre organisation", "Organisation Fictive Zeta"))
    prix.append(_field("Date de début", "2021/1"))
    root.append(prix)

    cle = _el("section", "Contributions les plus importantes")
    cle.append(_field("Titre", "Contribution fictive clé"))
    cle.append(_field("Date du contribution", "2020/1"))
    root.append(cle)

    tree = ET.ElementTree(root)
    tree.write(str(path), encoding="utf-8", xml_declaration=True)
