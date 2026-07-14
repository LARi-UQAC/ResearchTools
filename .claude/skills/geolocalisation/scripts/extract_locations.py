"""
extract_locations.py - Stage 1 of the geolocalisation skill.

Parse a corpus .bib, resolve each paper's study / case-study location from its
Scopus abstract + title + keywords against an offline Natural Earth gazetteer,
and write a reviewable draft table (study_locations.csv) with a confidence and a
matched-terms column. A manual override CSV always wins.

The location is INFERRED from text and is never certain; see
../references/geocoding-protocol.md for the confidence rubric and failure modes.
Stage 2 is a mandatory human review; Stage 3 is generate_geomap.py.

Dependencies: standard library only (urllib, json, csv, re, subprocess).
Usage:
  python extract_locations.py --bib corpus.bib --out DIR [--override curated.csv]
                              [--no-scopus] [--insttoken TOKEN]
"""
import argparse
import csv
import json
import logging
import os
import re
import subprocess
import sys
import urllib.request

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(SKILL_DIR, "data")
SCOPUS_API = os.path.join(SKILL_DIR, "..", "scopus", "scripts", "scopus_api.py")

# The full-text fallback reuses the scopus skill's download_pdf.py (any-format
# retrieval). Import is best-effort: if requests is missing it self-exits, so we
# also swallow SystemExit and disable the fallback rather than crash this script.
sys.path.insert(0, os.path.dirname(SCOPUS_API))
try:
    import download_pdf as dl
except (ImportError, SystemExit):
    dl = None

BASEMAP = os.path.join(DATA_DIR, "world_countries.geojson")
BASEMAP_URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
               "master/geojson/ne_110m_admin_0_countries.geojson")
CITIES = os.path.join(DATA_DIR, "ne_10m_populated_places.geojson")
CITIES_URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
              "master/geojson/ne_10m_populated_places.geojson")

CSV_HEADER = ["citekey", "etude", "ville", "pays", "lat", "lon",
              "theme", "confidence", "source", "matched",
              "evidence_field", "evidence", "provenance"]

CONF_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3, "manual": 3, "override": 3}

# Aliases fold common spellings / abbreviations onto the Natural Earth admin-0
# country name so the matcher recognises them in an abstract.
COUNTRY_ALIASES = {
    "us": "United States of America", "usa": "United States of America",
    "u s a": "United States of America", "united states": "United States of America",
    "america": "United States of America", "uk": "United Kingdom",
    "u k": "United Kingdom", "britain": "United Kingdom",
    "great britain": "United Kingdom", "england": "United Kingdom",
    "korea": "South Korea", "south korea": "South Korea",
    "republic of korea": "South Korea", "north korea": "North Korea",
    "iran": "Iran", "russia": "Russia", "czech republic": "Czechia",
    "uae": "United Arab Emirates", "ivory coast": "Ivory Coast",
    "turkey": "Turkey", "the netherlands": "Netherlands",
}

# City-name spellings absent from the Natural Earth gazetteer or spelled in
# French in the corpus. Maps an alias to the canonical NE city name.
CITY_ALIASES = {
    "pekin": "Beijing", "chiraz": "Shiraz", "geneve": "Geneva",
    "athenes": "Athens", "bruxelles": "Brussels", "seoul": "Seoul",
    "lisbonne": "Lisbon", "moscou": "Moscow", "montreal": "Montreal",
    "kaboul": "Kabul",
}

# Gazetteer city names that are also common English words / ML-paper jargon and
# would otherwise fire on the title or abstract of a methods paper. These small
# towns are dropped from the gazetteer entirely; a real study in one of them is
# recovered through the override CSV.
CITY_STOPWORDS = {
    "progress", "same", "lead", "superior", "split", "mobile", "reading",
    "guide", "turbo", "best", "general", "union", "central", "commerce",
    "industry", "independence", "enterprise", "liberty", "surprise", "results",
    "model", "data", "figure", "table", "benchmark", "vision", "language",
}

# Characters that end a sentence; a capitalised word right after one may be
# capitalised only by position, not because it is a proper noun.
_SENT_BOUNDARY = set(".!?\n\r;:")


# --------------------------------------------------------------------------
# Bib parsing
# --------------------------------------------------------------------------
def _first_author_label(authors_raw: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Turn a BibTeX author field into a short study label matching the
        corpus style: "Surname" (1 author), "S1 & S2" (2), "S1 et al." (3+).

    Inputs:
        authors_raw (str): the raw BibTeX author field ("Cai, X. and Li, Y.").

    Outputs:
        label (str): the short human label, or "" if no author is present.
    --------------------------------------------------------------------------
    """
    if not authors_raw:
        return ""
    parts = [p.strip() for p in re.split(r"\s+and\s+", authors_raw) if p.strip()]

    def surname(person: str) -> str:
        # "Surname, Given" -> Surname; else last whitespace token.
        return (person.split(",")[0] if "," in person else person.split()[-1]).strip()

    names = [surname(p) for p in parts]
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} & {names[1]}"
    return f"{names[0]} et al."


def parse_bib(path: str) -> list[dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Extract one record per BibTeX entry: citekey, first-author label, DOI,
        and the THEME tag from the trailing "% [... THEME: Tx ...]" comment.

    Inputs:
        path (str): path to the corpus .bib file.

    Outputs:
        records (list[dict]): dicts with keys citekey, etude, doi, theme.
    --------------------------------------------------------------------------
    """
    with open(path, encoding="utf-8") as fh:
        text = fh.read()

    entries = list(re.finditer(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", text))
    records = []
    for i, m in enumerate(entries):
        citekey = m.group(2).strip()
        block_start = m.end()
        next_start = entries[i + 1].start() if i + 1 < len(entries) else len(text)
        block = text[block_start:next_start]

        author_m = re.search(r"author\s*=\s*[{\"]([^}\"]*)[}\"]", block, re.I | re.S)
        doi_m = re.search(r"doi\s*=\s*[{\"]([^}\"]*)[}\"]", block, re.I | re.S)
        theme_m = re.search(r"THEME:\s*(T\d)", block, re.I)

        records.append({
            "citekey": citekey,
            "etude": _first_author_label(author_m.group(1).strip() if author_m else ""),
            "doi": doi_m.group(1).strip() if doi_m else "",
            "theme": theme_m.group(1).upper() if theme_m else "",
        })
    logger.info("[BIB] parsed %d entries (%d with DOI)",
                len(records), sum(1 for r in records if r["doi"]))
    return records


# --------------------------------------------------------------------------
# Offline gazetteer
# --------------------------------------------------------------------------
def _ensure_data(path: str, url: str) -> None:
    """Cache a Natural Earth file locally on first use; TLS verified."""
    if os.path.exists(path):
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    logger.info("[DATA] downloading %s", os.path.basename(path))
    req = urllib.request.Request(url, headers={"User-Agent": "python-urllib"})
    data = urllib.request.urlopen(req, timeout=60).read()
    with open(path, "wb") as fh:
        fh.write(data)


def _polygon_centroid(geometry: dict) -> tuple[float, float] | None:
    """Rough centroid (mean of the largest ring's vertices) for a country marker."""
    coords = []
    gtype = geometry.get("type")
    if gtype == "Polygon":
        rings = [geometry["coordinates"][0]]
    elif gtype == "MultiPolygon":
        rings = [poly[0] for poly in geometry["coordinates"]]
    else:
        return None
    biggest = max(rings, key=len)
    for lon, lat in biggest:
        coords.append((lon, lat))
    if not coords:
        return None
    return (sum(c[1] for c in coords) / len(coords),
            sum(c[0] for c in coords) / len(coords))


def build_gazetteer(min_pop: int = 50000) -> tuple[dict, dict, dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Load the offline country + city gazetteers used to match place names.

    Inputs:
        min_pop (int): drop cities below this population (a precision floor that
            removes small towns whose names collide with common words).

    Outputs:
        country_names (dict): lowercased country name/alias -> canonical name.
        country_centroid (dict): canonical name -> (lat, lon).
        city_index (dict): lowercased city name -> (canonical, lat, lon, country),
            keeping the most populous entry per name.
    --------------------------------------------------------------------------
    """
    _ensure_data(BASEMAP, BASEMAP_URL)
    _ensure_data(CITIES, CITIES_URL)

    with open(BASEMAP, encoding="utf-8") as fh:
        world = json.load(fh)
    country_names, country_centroid = {}, {}
    for feat in world.get("features", []):
        props = feat.get("properties", {})
        name = props.get("NAME") or props.get("ADMIN") or props.get("name") or ""
        if not name:
            continue
        country_names[name.lower()] = name
        cen = _polygon_centroid(feat.get("geometry", {}))
        if cen:
            country_centroid[name] = cen
    for alias, canonical in COUNTRY_ALIASES.items():
        # Only wire an alias whose canonical name exists in the basemap.
        if canonical in country_centroid:
            country_names[alias] = canonical

    with open(CITIES, encoding="utf-8") as fh:
        cities = json.load(fh)
    city_index: dict[str, tuple] = {}
    city_pop: dict[str, float] = {}
    for feat in cities.get("features", []):
        props = feat.get("properties", {})
        cname = props.get("NAME") or props.get("name") or ""
        key = cname.lower()
        if not cname or len(cname) < 4 or key in CITY_STOPWORDS:
            continue
        geom = feat.get("geometry", {})
        if geom.get("type") != "Point":
            continue
        lon, lat = geom["coordinates"][0], geom["coordinates"][1]
        country = props.get("ADM0NAME") or props.get("SOV0NAME") or ""
        pop = float(props.get("POP_MAX") or props.get("POP_MIN") or 0)
        if pop < min_pop:
            continue
        if key not in city_index or pop > city_pop.get(key, -1):
            city_index[key] = (cname, lat, lon, country, pop)
            city_pop[key] = pop
    logger.info("[GAZ] %d countries, %d cities", len(country_centroid), len(city_index))
    return country_names, country_centroid, city_index


# --------------------------------------------------------------------------
# Place-name matching
# --------------------------------------------------------------------------
def _proper_ngrams(text: str, n: int = 3) -> set[str]:
    """
    Lowercased 1..n-word phrases whose every word is capitalised in the original
    text and whose first word is not sentence-initial. Capitalisation is the
    signal that separates a place ("Mobile", "Reading", "Split") from the common
    word that shares its spelling ("mobile", "reading", "split"); the
    sentence-start guard drops words capitalised only by position.
    """
    tokens = []
    for m in re.finditer(r"[A-Za-zÀ-ÿ]+", text):
        w = m.group(0)
        j = m.start() - 1
        while j >= 0 and text[j] in " \t\"'([":
            j -= 1
        sent_start = j < 0 or text[j] in _SENT_BOUNDARY
        tokens.append((w, w[:1].isupper(), sent_start))
    grams = set()
    for size in range(1, n + 1):
        for i in range(len(tokens) - size + 1):
            span = tokens[i:i + size]
            if all(t[1] for t in span) and not span[0][2]:
                grams.add(" ".join(t[0].lower() for t in span))
    return grams


def match_location(text: str, gaz: tuple) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Infer the most likely study location from a paper's search text and
        score the confidence per ../references/geocoding-protocol.md (section 3).

    Inputs:
        text (str): title + abstract + keywords of one paper.
        gaz (tuple): (country_names, country_centroid, city_index) gazetteer.

    Outputs:
        result (dict): ville, pays, lat, lon, confidence, matched. Empty strings
            and confidence "none" when no place term fires.
    --------------------------------------------------------------------------
    """
    country_names, country_centroid, city_index = gaz
    empty = {"ville": "", "pays": "", "lat": "", "lon": "",
             "confidence": "none", "matched": ""}
    if not text.strip():
        return empty

    # Fold French / abbreviated aliases onto their canonical gazetteer spelling.
    grams = _proper_ngrams(text)
    grams |= {CITY_ALIASES[g].lower() for g in grams if g in CITY_ALIASES}

    countries_hit = []
    for g in grams:
        canonical = country_names.get(g)
        if canonical and canonical in country_centroid and canonical not in countries_hit:
            countries_hit.append(canonical)

    cities_hit = [city_index[g] for g in grams if g in city_index]
    # De-duplicate by name, then rank by population descending. The population
    # sort is what makes the choice deterministic (grams is an unordered set) and
    # sensible (Kitchener 256k wins over the smaller same-named Waterloo).
    seen, cities = set(), []
    for c in cities_hit:
        if c[0] not in seen:
            seen.add(c[0])
            cities.append(c)
    cities.sort(key=lambda c: c[4], reverse=True)

    if cities:
        # Prefer the largest city whose parent country is also named in the text.
        confirmed = [c for c in cities if c[3] in countries_hit]
        if confirmed:
            cname, lat, lon, ctry = confirmed[0][:4]
            return {"ville": cname, "pays": ctry, "lat": lat, "lon": lon,
                    "confidence": "high", "matched": f"{cname}+{ctry}"}
        if len(cities) == 1 and len(countries_hit) <= 1:
            cname, lat, lon, ctry = cities[0][:4]
            # A single city whose country conflicts with a different named country.
            conflict = countries_hit and ctry not in countries_hit
            return {"ville": cname, "pays": ctry, "lat": lat, "lon": lon,
                    "confidence": "low" if conflict else "medium", "matched": cname}
        # Several unconfirmed cities: take the most populous, flag ambiguous.
        cname, lat, lon, ctry = cities[0][:4]
        return {"ville": cname, "pays": ctry, "lat": lat, "lon": lon,
                "confidence": "low", "matched": "|".join(c[0] for c in cities[:4])}

    if countries_hit:
        if len(countries_hit) == 1:
            ctry = countries_hit[0]
            lat, lon = country_centroid[ctry]
            return {"ville": "", "pays": ctry, "lat": lat, "lon": lon,
                    "confidence": "medium", "matched": ctry}
        # Multiple countries, no city: pick most-mentioned (name as a stable
        # tiebreak so the choice is deterministic), flag low.
        ranked = sorted(countries_hit, key=lambda c: (-text.lower().count(c.lower()), c))
        ctry = ranked[0]
        lat, lon = country_centroid[ctry]
        return {"ville": "", "pays": ctry, "lat": lat, "lon": lon,
                "confidence": "low", "matched": "|".join(ranked[:4])}

    return empty


# --------------------------------------------------------------------------
# Evidence / provenance
# --------------------------------------------------------------------------
# Phrases that tend to introduce the empirical site; scanned first in full text
# so the study location wins over the many place names in affiliations and the
# reference list.
CUE_WORDS = (
    "case study", "study area", "study region", "study site", "study sites",
    "located in", "situated in", "conducted in", "carried out in", "field site",
    "test site", "we study", "our study", "in this study", "case of",
    "region of", "city of", "province of", "municipality of", "district of",
    "collected in", "selected in", "buildings in", "test area", "study covers",
    "field campaign", "sample of", "we select", "we survey", "were collected",
    "were selected", "focus area",
)
_STUDY_CUE_RE = re.compile("|".join(re.escape(w) for w in CUE_WORDS), re.I)

# Markers of an author-affiliation / header / footer line. A sentence carrying
# one of these names an institution's city, NOT the study site, so it is
# rejected before matching - the single biggest source of full-text error.
AFFIL_MARKERS = (
    "department", "universit", "institute", "school of", "faculty",
    "laborator", "college", "academy", "@", "e-mail", "email", "editors",
    "affiliation", "corresponding author", "received", "accepted", "©",
    "copyright", "press", "proceedings", "conference on", "ministry",
    "co., ltd", "gmbh", " inc.", "orcid",
)


def _is_affiliation(sentence: str) -> bool:
    """True when a sentence looks like an affiliation/header line (city != site)."""
    low = sentence.lower()
    return any(m in low for m in AFFIL_MARKERS)


def _sentences(text: str) -> list[str]:
    """Split text into sentence-like segments on ., !, ? and newlines."""
    return [p.strip() for p in re.split(r"(?<=[.!?])\s+|\n+", text) if p.strip()]


def _evidence_terms(ville: str, pays: str, matched: str) -> list[str]:
    """Place strings to search for in the source, including reverse aliases so
    the original spelling (Chiraz for Shiraz, USA for United States) is found."""
    terms = {t for t in (ville, pays) if t}
    terms |= {t.strip() for t in re.split(r"[+|]", matched or "") if t.strip()}
    for alias, canon in CITY_ALIASES.items():
        if canon == ville:
            terms.add(alias)
    for alias, canon in COUNTRY_ALIASES.items():
        if canon == pays:
            terms.add(alias)
    return sorted(terms, key=len, reverse=True)


def find_evidence(search_terms: list[str],
                  fields: list[tuple[str, str]]) -> tuple[str, str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Locate the winning place name in the source so the extraction is
        auditable: return the field it came from and the verbatim sentence
        that contains it.

    Inputs:
        search_terms (list[str]): place strings to look for, longest first.
        fields (list[tuple]): (field_name, field_text) in priority order,
            e.g. [("title", ...), ("abstract", ...), ("keywords", ...)].

    Outputs:
        (field, snippet): the field the term was found in and the verbatim
        sentence (the whole field when short). ("", "") if not found verbatim.
    --------------------------------------------------------------------------
    """
    for field_name, field_text in fields:
        if not field_text:
            continue
        low = field_text.lower()
        for term in search_terms:
            if term.lower() not in low:
                continue
            snippet = field_text.strip()
            if len(snippet) > 300:
                for sent in _sentences(field_text):
                    if term.lower() in sent.lower():
                        snippet = sent
                        break
            snippet = re.sub(r"\s+", " ", snippet).strip()
            if len(snippet) > 400:
                snippet = snippet[:397] + "..."
            return field_name, snippet
    return "", ""


def write_provenance(out_dir: str, row: dict, doi: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Write a per-paper audit note recording the resolved location, where in
        the article it was read, and the verbatim evidence snippet.

    Inputs:
        out_dir (str): the run output directory.
        row (dict): the resolved row (citekey, ville, pays, lat, lon, ...).
        doi (str): the paper DOI.

    Outputs:
        rel_path (str): the provenance file path relative to out_dir, stored in
        the CSV so the map can link to it.
    --------------------------------------------------------------------------
    """
    prov_dir = os.path.join(out_dir, "provenance")
    os.makedirs(prov_dir, exist_ok=True)
    fname = re.sub(r"[^\w.-]", "_", row["citekey"]) + ".md"
    path = os.path.join(prov_dir, fname)
    loc = ", ".join(p for p in (row.get("ville", ""), row.get("pays", "")) if p) or "(none)"
    lines = [
        f"# {row['citekey']} — {row.get('etude', '')}",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Location | {loc} |",
        f"| Coordinates | {row.get('lat', '')}, {row.get('lon', '')} |",
        f"| Confidence | {row.get('confidence', '')} |",
        f"| Theme | {row.get('theme', '')} |",
        f"| Read from | {row.get('evidence_field', '')} |",
        f"| Matched term | {row.get('matched', '')} |",
        f"| Extraction | {row.get('source', '')} |",
        f"| DOI | {doi} |",
        "",
        "## Evidence (verbatim from the article)",
        "",
        f"> {row.get('evidence', '') or '(no verbatim snippet located)'}",
        "",
    ]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return os.path.relpath(path, out_dir).replace("\\", "/")


# --------------------------------------------------------------------------
# Full-text fallback (download_pdf.py -> PyMuPDF / HTML -> scan)
# --------------------------------------------------------------------------
def _pdf_text(path: str) -> str:
    """Extract text from a PDF with PyMuPDF (fitz); '' if unavailable or unreadable."""
    try:
        import fitz
    except ImportError:
        logger.warning("[FULLTEXT] PyMuPDF (fitz) not installed; cannot read PDFs.")
        return ""
    try:
        with fitz.open(path) as doc:
            return "\n".join(page.get_text() for page in doc)
    except Exception as exc:  # defensive: a bad PDF must not stop the run
        logger.warning("[FULLTEXT] PDF read failed %s: %s", os.path.basename(path), exc)
        return ""


def _read_fulltext(path: str, fmt: str) -> str:
    """Read a downloaded artifact (pdf via PyMuPDF, html tag-stripped, md raw)."""
    if fmt == "pdf":
        return _pdf_text(path)
    with open(path, encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    if fmt == "html":
        raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
        raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return raw


def _focus_body(text: str) -> str:
    """Drop the reference list (a dense source of unrelated city names) and cap length."""
    cut = None
    for m in re.finditer(r"(?im)^\s*(references|bibliography|r[ée]f[ée]rences)\s*$", text):
        cut = m.start()
    if cut:
        text = text[:cut]
    return text[:60000]


def match_fulltext(body: str, gaz: tuple) -> tuple[dict, str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Match a study SITE from full text. Only study-cue sentences that are not
        affiliation/header lines are scanned; the reference list is removed
        first. There is deliberately NO whole-body fallback: the body is dense
        with author-affiliation and dataset cities that are not study sites, so
        scanning it maps authors, not studies.

    Inputs:
        body (str): the extracted full-text of one paper.
        gaz (tuple): the gazetteer (country_names, country_centroid, city_index).

    Outputs:
        (location, evidence_text): the matched location dict and the exact
        cue sentences it was drawn from ("" when no usable sentence exists).
    --------------------------------------------------------------------------
    """
    candidates = [s for s in _sentences(_focus_body(body))
                  if _STUDY_CUE_RE.search(s) and not _is_affiliation(s)]
    if not candidates:
        return match_location("", gaz), ""
    text = " ".join(candidates)
    return match_location(text, gaz), text


def fetch_fulltext(entry: dict, refs_dir: str, api_key: str | None,
                   insttoken: str | None, email: str | None,
                   allow_html: bool) -> tuple[str, str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Download a paper's full text via the scopus skill's download_pdf.py and
        return its extracted body text.

    Inputs:
        entry (dict): {citekey, doi, author, year, title}.
        refs_dir (str): directory where full-text files are stored/cached.
        api_key, insttoken, email: passed through to download_pdf.
        allow_html (bool): permit the HTML/landing tiers.

    Outputs:
        (body, source_format): extracted text and the artifact format, or
        ("", "") when nothing usable was retrieved.
    --------------------------------------------------------------------------
    """
    if dl is None:
        return "", ""
    os.makedirs(refs_dir, exist_ok=True)
    try:
        res = dl.download_one(entry, refs_dir, api_key, insttoken,
                              email=email, allow_html=allow_html)
    except (SystemExit, Exception) as exc:  # never let a fetch abort the corpus run
        logger.warning("[FULLTEXT] fetch failed %s: %s", entry.get("citekey"), exc)
        return "", ""
    if res.get("status") in ("failed", "no-doi") or not res.get("file"):
        return "", ""
    path = os.path.join(refs_dir, res["file"])
    if not os.path.exists(path):
        return "", ""
    return _read_fulltext(path, res.get("format") or ""), res.get("format") or ""


# --------------------------------------------------------------------------
# Scopus text retrieval (per DOI, cached)
# --------------------------------------------------------------------------
def fetch_scopus_text(doi: str, cache_dir: str, insttoken: str | None) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Return {title, abstract, keywords, authors} for a DOI via the sibling
        scopus skill, cached on disk so re-runs are offline and free.

    Inputs:
        doi (str): the paper DOI.
        cache_dir (str): directory for per-DOI JSON cache files.
        insttoken (str | None): optional Scopus institution token.

    Outputs:
        record (dict): the scopus_api "cite" JSON, or {} when unresolved.
    --------------------------------------------------------------------------
    """
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, re.sub(r"[^\w.-]", "_", doi) + ".json")
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as fh:
            return json.load(fh)

    cmd = [sys.executable, SCOPUS_API, "cite", doi]
    if insttoken:
        cmd += ["--insttoken", insttoken]
    # Force the child into UTF-8 mode: on Windows its stdout defaults to cp1252,
    # and Scopus titles carry smart quotes (byte 0x92) that break a UTF-8 decode.
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        # A rate-limit or access wall must halt the run, not be mistaken for
        # a paper with no location.
        if "429" in err:
            logger.error("[SCOPUS] rate limited (429). Wait 60 s and re-run; "
                         "cached DOIs will be skipped.")
            sys.exit(1)
        if "403" in err:
            logger.error("[SCOPUS] access denied (403). Connect to the UQAC VPN "
                         "or pass --insttoken.")
            sys.exit(1)
        logger.warning("[SCOPUS] unresolved %s: %s", doi, err[:120])
        record = {}
    else:
        try:
            record = json.loads(proc.stdout)
        except (json.JSONDecodeError, TypeError):
            record = {}
    with open(cache_path, "w", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False)
    return record


# --------------------------------------------------------------------------
# Override merge + output
# --------------------------------------------------------------------------
def load_override(path: str) -> dict:
    """Read the curated override CSV into {citekey: row}; manual rows win."""
    rows = {}
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            key = (row.get("citekey") or "").strip()
            if key:
                rows[key] = {k: (v or "").strip() for k, v in row.items()}
    logger.info("[OVERRIDE] %d curated rows loaded", len(rows))
    return rows


def apply_override(base: dict, override: dict, bib: dict) -> dict:
    """Overlay a curated row onto an auto row; fill etude/theme from the bib."""
    merged = dict(base)
    for field in ("ville", "pays", "lat", "lon", "etude", "theme",
                  "confidence", "source", "matched"):
        if override.get(field, "") != "":
            merged[field] = override[field]
    if not merged.get("etude"):
        merged["etude"] = bib.get("etude", "")
    if not merged.get("theme"):
        merged["theme"] = bib.get("theme", "")
    merged["confidence"] = override.get("confidence") or "manual"
    merged["source"] = override.get("source") or "override"
    return merged


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract study locations from a corpus .bib.")
    ap.add_argument("--bib", required=True, help="corpus .bib path")
    ap.add_argument("--out", default=".", help="output directory")
    ap.add_argument("--override", default=None, help="curated override CSV (wins by citekey)")
    ap.add_argument("--no-scopus", action="store_true",
                    help="skip Scopus; emit an empty-location template for manual entry")
    ap.add_argument("--insttoken", default=None, help="Scopus institution token")
    ap.add_argument("--min-city-pop", type=int, default=50000,
                    help="drop gazetteer cities below this population (precision floor)")
    ap.add_argument("--full-text", action="store_true",
                    help="for none/low abstract results, download the PDF via "
                         "download_pdf.py and scan the full text for the study site")
    ap.add_argument("--refs-dir", default=None,
                    help="where full-text files are stored/cached (default <out>/refs)")
    ap.add_argument("--email", default=None,
                    help="Unpaywall contact email for the full-text open-access tier")
    ap.add_argument("--no-html", action="store_true",
                    help="full-text: restrict retrieval to PDF only (skip HTML tiers)")
    args = ap.parse_args()

    if not os.path.exists(args.bib):
        logger.error("[BIB] file not found: %s", args.bib)
        sys.exit(1)
    os.makedirs(args.out, exist_ok=True)
    # Clear stale provenance notes so a shorter run never leaves dead evidence
    # from a previous, longer one behind.
    prov_dir = os.path.join(args.out, "provenance")
    if os.path.isdir(prov_dir):
        for f in os.listdir(prov_dir):
            if f.endswith(".md"):
                os.remove(os.path.join(prov_dir, f))

    records = parse_bib(args.bib)
    override = load_override(args.override) if args.override else {}
    gaz = None if args.no_scopus else build_gazetteer(args.min_city_pop)
    cache_dir = os.path.join(args.out, ".scopus_cache")
    refs_dir = args.refs_dir or os.path.join(args.out, "refs")
    api_key = dl._scopus_key_optional() if (args.full_text and dl) else None
    email = args.email or (dl._unpaywall_email_optional() if (args.full_text and dl) else None)
    if args.full_text and dl is None:
        logger.warning("[FULLTEXT] download_pdf.py not importable; --full-text disabled.")

    rows, tally = [], {"high": 0, "medium": 0, "low": 0, "none": 0, "override": 0}
    ft_used = 0
    for rec in records:
        base = {"citekey": rec["citekey"], "etude": rec["etude"], "theme": rec["theme"],
                "ville": "", "pays": "", "lat": "", "lon": "",
                "confidence": "none", "source": "", "matched": "",
                "evidence_field": "", "evidence": "", "provenance": ""}
        if rec["citekey"] in override:
            merged = apply_override(base, override[rec["citekey"]], rec)
            merged["evidence_field"] = "override"
            merged["evidence"] = override[rec["citekey"]].get("evidence") or "(user-supplied override)"
            tally["override"] += 1
        elif args.no_scopus or not rec["doi"]:
            merged = {**base, "source": "template"}
            tally["none"] += 1
        else:
            sc = fetch_scopus_text(rec["doi"], cache_dir, args.insttoken)
            fields = [("title", sc.get("title", "")),
                      ("abstract", sc.get("abstract", "")),
                      ("keywords", "; ".join(sc.get("keywords", []) or []))]
            loc = match_location(" ".join(t for _, t in fields), gaz)
            source, evidence_fields = "scopus-abstract", fields
            # Full-text fallback: only for weak abstract results (none/low), only
            # when it beats the abstract, so strong abstract hits are never lost.
            if args.full_text and dl and CONF_RANK.get(loc["confidence"], 0) < 2:
                entry = {"citekey": rec["citekey"], "doi": rec["doi"],
                         "author": rec["etude"].split()[0], "year": "",
                         "title": sc.get("title", "")}
                body, _ = fetch_fulltext(entry, refs_dir, api_key, args.insttoken,
                                         email, not args.no_html)
                if body:
                    ftloc, ftev = match_fulltext(body, gaz)
                    # Adopt full text only when it strictly wins AND either the
                    # abstract found nothing or the full-text hit is high (a
                    # cue sentence naming city + country). This stops a bare-city
                    # full-text guess from displacing a correct low abstract answer.
                    ft_conf, abs_conf = ftloc["confidence"], loc["confidence"]
                    strictly_better = CONF_RANK.get(ft_conf, 0) > CONF_RANK.get(abs_conf, 0)
                    if strictly_better and (abs_conf == "none" or ft_conf == "high"):
                        loc, source, evidence_fields = ftloc, "full-text", [("full-text", ftev)]
                        ft_used += 1
            efield, esnip = find_evidence(
                _evidence_terms(loc.get("ville", ""), loc.get("pays", ""), loc.get("matched", "")),
                evidence_fields)
            merged = {**base, **loc, "source": source,
                      "evidence_field": efield, "evidence": esnip}
            tally[loc["confidence"]] += 1
        # An audit note for every row that resolved coordinates.
        if merged.get("lat") != "":
            merged["provenance"] = write_provenance(args.out, merged, rec["doi"])
        rows.append(merged)

    out_csv = os.path.join(args.out, "study_locations.csv")
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_HEADER)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in CSV_HEADER})

    logger.info("[OUT] %s", out_csv)
    logger.info("[OUT] %s/provenance/*.md (one audit note per located paper)", args.out)
    logger.info("[SUMMARY] %d rows | high=%d medium=%d low=%d none=%d override=%d%s",
                len(rows), tally["high"], tally["medium"], tally["low"],
                tally["none"], tally["override"],
                f" | full-text upgraded {ft_used}" if args.full_text else "")
    logger.info("[NEXT] review low/none rows (Stage 2), then run generate_geomap.py")


if __name__ == "__main__":
    main()
