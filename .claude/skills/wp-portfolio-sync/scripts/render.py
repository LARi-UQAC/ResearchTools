"""
render.py - HTML rendering of portfolio sections from cihr.json.

Stage: imported by verify_titles.py, preview.py and push_wp.py. Every
renderer returns (recent_html, history_html) under the N-year rule driven
by RenderSettings (D10: no hardcoded ref_year/window), never writes to its
caller's data, and reads no network. render_entry is the only function
that touches the researcher's config/ folder, always through
wp_paths.contained_path (R24).
"""
import copy
import html
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from wp_common import fmt_amount, fmt_ym, norm_ws, parse_year, split_recent_history, md_to_html
from wp_errors import WpRefusal, WpSyncError
from wp_paths import contained_path

PHASE1_RENDERERS = ("financement", "implications", "services", "distinctions")

_URL_RE = re.compile(r"https?://\S+")

# Which optional degree gives no printed title on its own; the caller's own
# titre_professionnel record field covers the rest (D3: no OIQ membership file).
_TITRE_DIPLOME = {
    "Doctorat": "Ph.D.",
    "Postdoctorat": "Ph.D.",
    "Maîtrise avec mémoire": "M. Ing.",
    "Maîtrise sans mémoire": "M. Ing.",
}

_PHQ_REQUIRED_KEYS = ("etudiant", "type_diplome", "statut", "debut", "fin", "role", "titre_projet")


@dataclass(frozen=True)
class RenderSettings:
    """The mapping.yaml values every renderer needs (D10: no defaults)."""

    ref_year: int
    window: int
    recent_label: str
    excluded_funding_statuses: tuple


def load_render_settings(mapping, source):
    """
    --------------------------------------------------------------------------
    Purpose:
        Read ref_year, recent_window, recent_label and
        excluded_funding_statuses out of a loaded mapping.yaml document.

    Inputs:
        mapping (dict): the parsed mapping.yaml.
        source (str): the file name reported in a refusal.

    Outputs:
        settings (RenderSettings): the validated values.

    Raises:
        WpRefusal: a key is missing, or has the wrong type/shape, naming the
        key and source.
    --------------------------------------------------------------------------
    """
    if "ref_year" not in mapping or not isinstance(mapping["ref_year"], int) or isinstance(mapping["ref_year"], bool):
        raise WpRefusal("mapping key 'ref_year' must be an int (from %s)" % source)
    if (
        "recent_window" not in mapping
        or not isinstance(mapping["recent_window"], int)
        or isinstance(mapping["recent_window"], bool)
        or mapping["recent_window"] < 1
    ):
        raise WpRefusal("mapping key 'recent_window' must be an int >= 1 (from %s)" % source)
    if "recent_label" not in mapping or not isinstance(mapping["recent_label"], str) or not mapping["recent_label"].strip():
        raise WpRefusal("mapping key 'recent_label' must be a non-empty string (from %s)" % source)
    if "excluded_funding_statuses" not in mapping or not isinstance(mapping["excluded_funding_statuses"], list) or not all(
        isinstance(x, str) for x in mapping["excluded_funding_statuses"]
    ):
        raise WpRefusal("mapping key 'excluded_funding_statuses' must be a list of strings (from %s)" % source)
    return RenderSettings(
        ref_year=mapping["ref_year"],
        window=mapping["recent_window"],
        recent_label=mapping["recent_label"],
        excluded_funding_statuses=tuple(mapping["excluded_funding_statuses"]),
    )


def window_caption(settings):
    """
    --------------------------------------------------------------------------
    Purpose:
        Format the recent-window caption shown above a cumul paragraph.

    Inputs:
        settings (RenderSettings): the loaded settings.

    Outputs:
        caption (str): "<recent_label> (<first year>–<ref_year>)", with
        an en dash (U+2013), the window computed from settings.
    --------------------------------------------------------------------------
    """
    return "%s (%d–%d)" % (settings.recent_label, settings.ref_year - settings.window + 1, settings.ref_year)


def media_display_title(sujet):
    """
    --------------------------------------------------------------------------
    Purpose:
        Compute a media item's display title: the subject with every URL
        removed, so it can be shown and approved independently of its link.

    Inputs:
        sujet (str): the raw media subject field.

    Outputs:
        title (str): the subject, URL-free, whitespace-normalised, with
        trailing " ,;:" stripped.
    --------------------------------------------------------------------------
    """
    return norm_ws(_URL_RE.sub("", sujet or "")).rstrip(" ,;:")


def item_title(section, item, subkey=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Compute the display title of one record, used by exclusions
        filtering and by the anti-fabrication gate.

    Inputs:
        section (str): one of "financement", "implications",
        "services_communaute" or "distinctions" (the data's own key names).
        item (dict): the record.
        subkey (str or None): "prix" or "contributions_cles", distinctions only.

    Outputs:
        title (str): the normalised title, possibly "".

    Raises:
        WpSyncError: section is none of the four known names.
    --------------------------------------------------------------------------
    """
    if section == "financement":
        return norm_ws(item.get("titre"))
    if section == "implications":
        return norm_ws(item.get("nom")) or norm_ws(item.get("organisation"))
    if section == "services_communaute":
        kind = item.get("type")
        if kind == "media":
            return media_display_title(item.get("sujet"))
        if kind == "entreprise":
            return norm_ws(item.get("organisation"))
        if kind == "evenement":
            return norm_ws(item.get("nom"))
        return ""
    if section == "distinctions":
        if subkey == "contributions_cles":
            return norm_ws(item.get("titre"))
        return norm_ws(item.get("nom"))
    raise WpSyncError("item_title: unknown section %r" % section)


def _extract_links(text):
    urls = _URL_RE.findall(text or "")
    return list(dict.fromkeys(u.rstrip(".,;)") for u in urls))


def _linkify(text):
    stripped = _URL_RE.sub("", text or "")
    stripped = " ".join(stripped.split()).rstrip(" ,;:")
    out = html.escape(stripped)
    for url in _extract_links(text):
        out += ' <a href="%s">lien</a>' % html.escape(url)
    return out


def _clean(s):
    return " ".join((s or "").split())


def _h(heading, body):
    return "<h4>%s</h4>\n%s" % (html.escape(heading), body) if body else ""


def _norm_title(t):
    return " ".join((t or "").split())


def _montant_total(g):
    if not g.get("sources"):
        return 0.0
    try:
        return float(str(g["sources"][0].get("montant_total", "") or "0").replace(" ", "").replace(",", "."))
    except (ValueError, TypeError):
        return 0.0


def _fmt_grant(g, contributions):
    src = g["sources"][0] if g["sources"] else {}
    titre = _clean(g["titre"])
    debut = fmt_ym(g["debut"])
    fin = fmt_ym(g["fin"]) if g["fin"] else "en cours"
    montant = fmt_amount(src.get("montant_total", ""))
    portion = src.get("portion_recue", "")
    try:
        show_portion = float(str(portion).replace(" ", "")) > 1
    except (ValueError, TypeError):
        show_portion = False
    if show_portion and portion != src.get("montant_total"):
        montant += " (portion : %s)" % fmt_amount(portion)
    competitif = "Compétitif" if src.get("competitif") == "Oui" else "Non compétitif"
    statut = g["statut"]
    statut_txt = " · Statut : %s" % html.escape(statut) if statut else ""
    org = html.escape(_clean(src.get("organisme", "")))
    prog = html.escape(_clean(src.get("programme", "")))
    qui = " — ".join(p for p in (org, prog) if p)
    lignes = [
        "<strong>%s</strong>" % html.escape(titre),
        "%s(%s – %s, %s)" % ((qui + " ") if qui else "", debut, fin, montant),
        "%s · Rôle : %s%s" % (competitif, html.escape(g["role"]), statut_txt),
    ]
    if g["cochercheurs"]:
        names = ", ".join(
            html.escape(c["nom"]) + (" (%s)" % html.escape(c["role"]) if c["role"] else "")
            for c in g["cochercheurs"]
        )
        lignes.append("Autres chercheurs : %s" % names)
    txt = (contributions.get(_norm_title(g["titre"])) or "").strip()
    if txt:
        lignes.append("<em>Contribution :</em> %s" % html.escape(txt))
    return "<p>" + "<br>\n".join(l for l in lignes if l.strip(" —")) + "</p>"


def _cumul_financement(items, recent, settings):
    total = sum(_montant_total(g) for g in items)
    total6 = sum(_montant_total(g) for g in recent)
    return (
        "<p><strong>Cumul :</strong> %d subventions au total — montant total : %s."
        "<br><strong>%s :</strong> %d subventions — montant total : %s.</p>"
        % (len(items), fmt_amount(total), window_caption(settings), len(recent), fmt_amount(total6))
    )


def render_financement(items, settings, contributions=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Render the funding section: a cumul paragraph followed by one
        paragraph per grant, split between recent and history by settings.

    Inputs:
        items (list[dict]): financement records (not mutated).
        settings (RenderSettings): drives the window and its caption (D10).
        contributions (dict or None): title -> editorial text, opt-in only.

    Outputs:
        (recent_html, history_html) (tuple[str, str]).
    --------------------------------------------------------------------------
    """
    contributions = contributions or {}
    ordered = sorted(items, key=lambda g: parse_year(g["debut"]) or 0, reverse=True)
    recent, history = split_recent_history(ordered, "fin", settings.ref_year, settings.window)
    cumul = _cumul_financement(ordered, recent, settings)
    recent_html = cumul + "\n" + "\n".join(_fmt_grant(g, contributions) for g in recent)
    history_html = "\n".join(_fmt_grant(g, contributions) for g in history)
    return recent_html, history_html


# --------------------------------------------------------------------- PHQ


def _direction(record, owner_name):
    role = record.get("role", "")
    if role == "Codirecteur de recherche":
        base = "%s (codirecteur)" % owner_name
    elif role == "Conseiller universitaire":
        base = "%s (conseiller)" % owner_name
    else:
        base = owner_name
    if record.get("codirecteur"):
        base += " (codirection : %s)" % record["codirecteur"]
    return base


def _phq_table(rows, owner_name):
    if not rows:
        return ""
    trs = []
    for s in rows:
        fin = fmt_ym(s["fin"]) if s["fin"] else "en cours"
        periode = "%s – %s" % (fmt_ym(s["debut"]), fin)
        num = s.get("_numero", "–")
        nom = "<strong>%s</strong>" % html.escape(s["etudiant"])
        if s.get("_titre"):
            nom += ", %s" % s["_titre"]
        trs.append(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (num, nom, html.escape(_clean(s["titre_projet"])), html.escape(_direction(s, owner_name)), html.escape(periode))
        )
    return (
        "<table><thead><tr><th>N<sup>o</sup></th><th>Étudiant</th><th>Titre du projet</th>"
        "<th>Direction</th><th>Période</th></tr></thead><tbody>" + "".join(trs) + "</tbody></table>"
    )


def _debut_key(s):
    match = re.match(r"\s*(\d{4})[/-](\d{1,2})", s.get("debut") or "")
    if match:
        return (int(match.group(1)), int(match.group(2)))
    return (9999, 99)


def _phq_cat(t):
    if t == "Doctorat":
        return "doctorat"
    if t in ("Maîtrise avec mémoire", "Maîtrise sans mémoire"):
        return "maitrise"
    if t in ("Baccalauréat", "Baccalauréat spécialisé", "Équivalent du baccalauréat"):
        return "premier_cycle"
    if t == "Postdoctorat":
        return "postdoc"
    return "autre"


def _phq_alumni(termines, owner_name):
    ordered = sorted(termines, key=lambda s: s.get("_numero", 0))
    sup = [s for s in ordered if _phq_cat(s["type_diplome"]) in ("doctorat", "maitrise")]
    prem = [s for s in ordered if _phq_cat(s["type_diplome"]) == "premier_cycle"]
    autres = [s for s in ordered if _phq_cat(s["type_diplome"]) not in ("doctorat", "maitrise", "premier_cycle")]
    out = _h("Alumni (cycles supérieurs)", _phq_table(sup, owner_name))
    out += _h("Alumni (1er cycle)", _phq_table(prem, owner_name))
    if autres:
        out += _h("Alumni (autres)", _phq_table(autres, owner_name))
    return out


def render_phq(students, settings, owner_name):
    """
    --------------------------------------------------------------------------
    Purpose:
        Render the PHQ supervision tables (Phase 2, D3). A pure function:
        records in, HTML out, wired to nothing in Phase 1.

    Inputs:
        students (list[dict]): required keys etudiant, type_diplome,
        statut, debut, fin, role, titre_projet; optional titre_professionnel
        (used only when the degree gives no title) and codirecteur.
        settings (RenderSettings): drives the six-year window and caption.
        owner_name (str): the supervisor's name, shown in the Direction column.

    Outputs:
        (recent_html, history_html, notes) (tuple[str, str, list[str]]).

    Raises:
        WpSyncError: a record is missing a required key, naming the key
        and the record's index.
    --------------------------------------------------------------------------
    """
    working = copy.deepcopy(students)
    for index, record in enumerate(working):
        for key in _PHQ_REQUIRED_KEYS:
            if key not in record:
                raise WpSyncError("render_phq: record %d is missing required key %r" % (index, key))

    working = [s for s in working if (s.get("etudiant") or "").strip()]
    for i, s in enumerate(sorted(working, key=lambda x: (_debut_key(x), x.get("etudiant", ""))), 1):
        s["_numero"] = i
        titre = _TITRE_DIPLOME.get((s.get("type_diplome") or "").strip(), "")
        s["_titre"] = titre or s.get("titre_professionnel", "")

    en_cours = [s for s in working if s["statut"] == "En cours"]
    termines = [s for s in working if s["statut"] in ("Terminé", "Tout sauf diplôme")]
    ignores = [s for s in working if s["statut"] not in ("En cours", "Terminé", "Tout sauf diplôme")]
    ter_recents, ter_anciens = split_recent_history(termines, "fin", settings.ref_year, settings.window)

    cats = {}
    for s in en_cours:
        cats.setdefault(_phq_cat(s["type_diplome"]), []).append(s)
    for v in cats.values():
        v.sort(key=lambda s: parse_year(s["debut"]) or 0, reverse=True)

    labels = {
        "doctorat": "Candidats au doctorat",
        "maitrise": "Candidats à la maîtrise",
        "premier_cycle": "Assistants de recherche (1er cycle)",
        "postdoc": "Postdoctorants",
        "autre": "Autres",
    }
    order = ["doctorat", "maitrise", "premier_cycle", "postdoc", "autre"]
    blocks = [_h(labels[c], _phq_table(cats[c], owner_name)) for c in order if cats.get(c)]
    blocks.append(_h("Diplômés récents", _phq_alumni(ter_recents, owner_name)))

    def _counts(group):
        n_doc = sum(1 for s in group if s["type_diplome"] == "Doctorat")
        n_mai = sum(1 for s in group if "Maîtrise" in s["type_diplome"])
        n_bac = sum(1 for s in group if "baccalauréat" in s["type_diplome"].lower())
        n_post = sum(1 for s in group if s["type_diplome"] == "Postdoctorat")
        n_aut = len(group) - n_doc - n_mai - n_bac - n_post
        return n_doc, n_mai, n_bac, n_post, n_aut

    n_doc, n_mai, n_bac, n_post, n_aut = _counts(working)
    cumul = (
        "<p><strong>Cumul :</strong> %d supervisions au total — %d doctorats, %d maîtrises, "
        "%d au premier cycle, %d postdoctorats" % (len(working), n_doc, n_mai, n_bac, n_post)
        + (", %d associés de recherche" % n_aut if n_aut else "")
    )

    six = [
        s
        for s in working
        if s["statut"] == "En cours"
        or (
            s["statut"] in ("Terminé", "Tout sauf diplôme")
            and (parse_year(s.get("fin") or "") or 9999) >= settings.ref_year - settings.window + 1
        )
    ]
    s_doc, s_mai, s_bac, s_post, s_aut = _counts(six)
    cumul += "<br><strong>%s :</strong> %d supervisions — %d doctorats, %d maîtrises, %d au premier cycle, %d postdoctorats" % (
        window_caption(settings),
        len(six),
        s_doc,
        s_mai,
        s_bac,
        s_post,
    )
    if s_aut == 1:
        cumul += ", 1 associé de recherche"
    elif s_aut > 1:
        cumul += ", %d associés de recherche" % s_aut

    e_doc, e_mai, e_bac, e_post, e_aut = _counts(en_cours)
    parts = []
    if e_doc:
        parts.append("%d doctorant%s" % (e_doc, "s" if e_doc > 1 else ""))
    if e_mai:
        parts.append("%d à la maîtrise" % e_mai)
    if e_bac:
        parts.append("%d au premier cycle" % e_bac)
    if e_post:
        parts.append("%d postdoctorant%s" % (e_post, "s" if e_post > 1 else ""))
    if e_aut:
        parts.append("%d associé(s) de recherche" % e_aut)
    cumul += "<br><strong>Actuellement en supervision :</strong> %d%s.</p>" % (
        len(en_cours),
        (" (%s)" % ", ".join(parts)) if parts else "",
    )
    recent_html = cumul + "\n" + "\n".join(b for b in blocks if b)

    hist = _phq_alumni(ter_anciens, owner_name)
    notes = []
    if ignores:
        notes.append(
            "dossiers exclus des tableaux (statut « Interrompu ») : "
            + ", ".join(s["etudiant"] for s in ignores)
        )
    return recent_html, hist, notes


# ------------------------------------------------------------- Implications


def _fmt_impl(i):
    nom = html.escape(_clean(i["nom"]) or _clean(i["organisation"]))
    role = html.escape(i["role"])
    org = _clean(i["organisation"])
    org = re.sub(r"^(Canada,\s*)?(Québec,\s*)?(Milieu universitaire,\s*)?", "", org).strip()
    org = html.escape(org)
    debut = fmt_ym(i["debut"])
    fin = fmt_ym(i["fin"]) if i["fin"] else "en cours"
    if debut and debut == fin:
        dates = " (%s)" % debut
    elif debut:
        dates = " (%s – %s)" % (debut, fin)
    else:
        dates = " (%s)" % fin
    head = "<strong>%s</strong> — %s" % (nom, role)
    if org and org not in nom:
        head += ", %s" % org
    head += dates
    desc = _clean(i["description"])
    if desc:
        head += "<br>%s" % html.escape(desc)
    return "<li>%s</li>" % head


def render_implications(items, settings):
    """
    --------------------------------------------------------------------------
    Purpose:
        Render memberships (committees and organisations), split by the
        N-year window.

    Inputs:
        items (list[dict]): implications records (not mutated).
        settings (RenderSettings): drives the window.

    Outputs:
        (recent_html, history_html) (tuple[str, str]).
    --------------------------------------------------------------------------
    """
    recent, history = split_recent_history(items, "fin", settings.ref_year, settings.window)

    def _sec(lst):
        comites = [i for i in lst if i["categorie"] == "comite"]
        orgs = [i for i in lst if i["categorie"] == "organisme"]
        out = _h("Comités", "<ul>" + "".join(_fmt_impl(i) for i in comites) + "</ul>" if comites else "")
        out += _h("Organismes", "<ul>" + "".join(_fmt_impl(i) for i in orgs) + "</ul>" if orgs else "")
        return out

    return _sec(recent), _sec(history)


# ------------------------------------------------------- Services communauté


def _fmt_media(m):
    title = media_display_title(m["sujet"])
    links = "".join(' <a href="%s">lien</a>' % html.escape(u) for u in _extract_links(m["sujet"]))
    dif = _linkify(m["diffuseur"])
    chaine = html.escape(_clean(m["chaine"]))
    date = fmt_ym(m["date"])
    txt = "<strong>%s</strong>%s — %s" % (html.escape(title), links, dif)
    if chaine:
        txt += ", %s" % chaine
    if date:
        txt += " (%s)" % date
    return "<li>%s</li>" % txt


def render_services(items, settings):
    """
    --------------------------------------------------------------------------
    Purpose:
        Render community services (media, start-up outreach, events), media
        sorted by broadcast date and the rest by the N-year window. The
        media link sits after </strong>, never inside it (D12).

    Inputs:
        items (list[dict]): services_communaute records (not mutated).
        settings (RenderSettings): drives the window.

    Outputs:
        (recent_html, history_html) (tuple[str, str]).
    --------------------------------------------------------------------------
    """
    medias = [x for x in items if x["type"] == "media"]
    autres = [x for x in items if x["type"] != "media"]
    med_recent, med_hist = split_recent_history(medias, "date", settings.ref_year, settings.window)
    aut_recent, aut_hist = split_recent_history(autres, "fin", settings.ref_year, settings.window)
    med_recent = sorted(med_recent, key=lambda x: parse_year(x.get("date") or "") or 0, reverse=True)
    med_hist = sorted(med_hist, key=lambda x: parse_year(x.get("date") or "") or 0, reverse=True)

    def _sec(meds, others):
        out = ""
        if meds:
            out += _h("Médias", "<ul>" + "".join(_fmt_media(m) for m in meds) + "</ul>")
        ents = [x for x in others if x["type"] == "entreprise"]
        evts = [x for x in others if x["type"] == "evenement"]
        if ents:
            out += _h(
                "Entreprise en démarrage",
                "".join(
                    "<p><strong>%s</strong> — %s (%s – %s)<br>%s<br><em>Retombées :</em> %s</p>"
                    % (
                        html.escape(_clean(e["organisation"])),
                        html.escape(e["role"]),
                        fmt_ym(e["debut"]),
                        fmt_ym(e["fin"]),
                        html.escape(_clean(e["resultat"])),
                        html.escape(_clean(e["retombees"])),
                    )
                    for e in ents
                ),
            )
        if evts:
            out += _h(
                "Évènements",
                "<ul>"
                + "".join(
                    "<li><strong>%s</strong> — %s (%s – %s)</li>"
                    % (html.escape(_clean(v["nom"])), html.escape(v["role"]), fmt_ym(v["debut"]), fmt_ym(v["fin"]))
                    for v in evts
                )
                + "</ul>",
            )
        return out

    return _sec(med_recent, aut_recent), _sec(med_hist, aut_hist)


# ---------------------------------------------------------------- Distinctions


def _fmt_prix(p):
    nom = _clean(p["nom"])
    org = _clean(p["organisation"])
    debut = fmt_ym(p["debut"])
    fin = fmt_ym(p["fin"]) if p["fin"] else ""
    dates = " (%s)" % " – ".join(x for x in (debut, fin) if x) if (debut or fin) else ""
    montant = fmt_amount(p["montant"]) if p["montant"] not in ("", "0") else ""
    head = "<strong>%s</strong>" % html.escape(nom)
    if org:
        head += " — %s" % html.escape(org)
    head += dates
    if montant:
        head += ", %s" % montant
    desc = _clean(p["description"])
    if desc:
        head += "<br>%s" % html.escape(desc)
    return "<li>%s</li>" % head


def render_distinctions(section_data, subkey, settings):
    """
    --------------------------------------------------------------------------
    Purpose:
        Render awards (subkey "prix", dated, split by the N-year window) or
        key contributions (subkey "contributions_cles", undated, one block).

    Inputs:
        section_data (dict): {"prix": [...], "contributions_cles": [...]}.
        subkey (str): "prix" or "contributions_cles".
        settings (RenderSettings): drives the window (prix only).

    Outputs:
        (recent_html, history_html) (tuple[str, str]).
    --------------------------------------------------------------------------
    """
    items = section_data.get(subkey, []) if isinstance(section_data, dict) else []
    if subkey == "prix":
        recent, history = split_recent_history(items, "fin", settings.ref_year, settings.window)
        recent = sorted(recent, key=lambda p: parse_year(p["fin"]) or 0, reverse=True)
        history = sorted(history, key=lambda p: parse_year(p["fin"]) or 0, reverse=True)
        recent_html = _h("Distinctions", "<ul>" + "".join(_fmt_prix(p) for p in recent) + "</ul>") if recent else ""
        history_html = _h("Distinctions", "<ul>" + "".join(_fmt_prix(p) for p in history) + "</ul>") if history else ""
        return recent_html, history_html
    blocks = []
    for c in items:
        titre = _clean(c["titre"])
        desc = _clean(c["description"])
        t = "<strong>%s</strong><br>" % html.escape(titre) if titre else ""
        blocks.append("<p>%s%s</p>" % (t, html.escape(desc)))
    return (_h("Contributions marquantes", "\n".join(blocks)) if blocks else "", "")


def _load_yaml_list_or_dict(data_dir, relative):
    try:
        resolved = contained_path(data_dir, relative)
    except WpRefusal:
        raise
    if not resolved.is_file():
        return None
    with open(resolved, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def render_entry(entry, data, data_dir, settings):
    """
    --------------------------------------------------------------------------
    Purpose:
        Dispatch one mapping.yaml entry to its renderer, applying extras,
        exclusions, the funding-status filter and the editorial opt-in
        first. The only function here that reads config/ (always through
        contained_path, R24).

    Inputs:
        entry (dict): one mapping.yaml entry (cv_path, renderer, and the
        split-mode keys of spec section 5).
        data (dict): the parsed cihr.json document.
        data_dir (Path): the resolved researcher data folder.
        settings (RenderSettings): passed through to the chosen renderer.

    Outputs:
        (recent_html, history_html, notes) (tuple[str, str, list[str]]).

    Raises:
        WpSyncError: entry["cv_path"] is absent from data.
        WpRefusal: renderer is "phq" (D2) or outside PHASE1_RENDERERS; or
        history_static escapes the data folder.
    --------------------------------------------------------------------------
    """
    cv_path = entry["cv_path"]
    if cv_path not in data:
        raise WpSyncError("cv_path %r absent from data (keys: %s)" % (cv_path, list(data.keys())))

    renderer = entry.get("renderer")
    if renderer == "phq":
        raise WpRefusal(
            "renderer 'phq' is refused: supervision is published from ThesisTracker, never from the CV XML (D2)"
        )
    if renderer not in PHASE1_RENDERERS:
        raise WpRefusal("unknown renderer %r (expected one of %s)" % (renderer, PHASE1_RENDERERS))

    notes = []
    subkey = entry.get("subkey")
    if cv_path == "distinctions":
        items = copy.deepcopy(data[cv_path].get(subkey, []))
    else:
        items = copy.deepcopy(data[cv_path])

    extra_file = {
        "implications": "config/implications_extra.yaml",
        "services": "config/services_extra.yaml",
    }.get(renderer)
    if renderer == "distinctions" and subkey == "prix":
        extra_file = "config/distinctions_extra.yaml"
    if extra_file:
        extra_items = _load_yaml_list_or_dict(data_dir, extra_file) or []
        if extra_items:
            items = list(items) + list(extra_items)
            notes.append("%d dossier(s) ajouté(s) (%s)" % (len(extra_items), extra_file))

    exclusions_doc = _load_yaml_list_or_dict(data_dir, "config/exclusions.yaml") or {}
    excluded_titles = {norm_ws(t) for t in (exclusions_doc.get(cv_path) or [])}
    if excluded_titles:
        before = len(items)
        items = [i for i in items if item_title(cv_path, i, subkey) not in excluded_titles]
        if len(items) < before:
            notes.append("%d dossier(s) exclu(s) (config/exclusions.yaml)" % (before - len(items)))

    if renderer == "financement":
        before = len(items)
        items = [i for i in items if norm_ws(i.get("statut")) not in settings.excluded_funding_statuses]
        if len(items) < before:
            notes.append("%d dossier(s) exclu(s) par statut (excluded_funding_statuses)" % (before - len(items)))

        contributions = {}
        if entry.get("editorial_texts") is True:
            raw = _load_yaml_list_or_dict(data_dir, "config/contributions.yaml")
            if raw is not None:
                contributions = {_norm_title(k): v for k, v in (raw.get("contributions", {}) or {}).items()}
            else:
                notes.append("editorial_texts: true mais config/contributions.yaml absent")
        recent, history = render_financement(items, settings, contributions)
        if entry.get("editorial_texts") is True:
            missing = [
                _norm_title(g["titre"])[:60]
                for g in items
                if not (contributions.get(_norm_title(g["titre"])) or "").strip()
            ]
            if missing:
                notes.append("%d projets sans texte de contribution : %s" % (len(missing), missing))
    elif renderer == "implications":
        recent, history = render_implications(items, settings)
    elif renderer == "services":
        recent, history = render_services(items, settings)
    else:  # distinctions
        recent, history = render_distinctions({subkey: items}, subkey, settings)

    history_static = entry.get("history_static")
    if history_static:
        resolved = contained_path(data_dir, history_static)
        if resolved.is_file():
            static_html = md_to_html(resolved.read_text(encoding="utf-8"))
            history = (history + "\n" + static_html).strip() if history else static_html
        else:
            notes.append("fichier historique introuvable : %s" % history_static)

    return recent, history, notes
