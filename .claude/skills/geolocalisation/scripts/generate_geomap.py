"""
generate_geomap.py - Stage 3 of the geolocalisation skill.

Read a reviewed study_locations.csv and render the corpus as geographic
artifacts: KML (Google My Maps), GeoJSON (QGIS/Leaflet), a static world-map PNG
for the review figure, an interactive HTML map, and a per-country count table.

The Natural Earth basemap is drawn from raw GeoJSON with matplotlib, so the
skill needs no geopandas/GDAL. Rows with no lat/lon are unmappable (global-scope
papers) and are reported but not plotted.

Dependencies: matplotlib (PNG). Optional: folium (HTML).
Usage:
  python generate_geomap.py --csv study_locations.csv --out DIR
        [--formats csv,kml,geojson,png,html] [--title "..."]
        [--min-confidence none|low|medium|high] [--no-labels]
"""
import argparse
import csv
import html
import json
import logging
import os
import sys
import urllib.request
from collections import Counter

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(SKILL_DIR, "data")
BASEMAP = os.path.join(DATA_DIR, "world_countries.geojson")
BASEMAP_URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
               "master/geojson/ne_110m_admin_0_countries.geojson")

CONF_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3, "manual": 3, "override": 3}


def ensure_basemap() -> None:
    """Cache the Natural Earth basemap locally on first use; TLS verified."""
    if os.path.exists(BASEMAP):
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    req = urllib.request.Request(BASEMAP_URL, headers={"User-Agent": "python-urllib"})
    data = urllib.request.urlopen(req, timeout=60).read()
    with open(BASEMAP, "wb") as fh:
        fh.write(data)


def load_rows(csv_path: str) -> list[dict]:
    """Read study_locations.csv into a list of dicts (string values)."""
    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        return [dict(r) for r in csv.DictReader(fh)]


def mappable(rows: list[dict], min_conf: str = "none") -> list[dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Keep rows that carry numeric coordinates and meet a confidence floor.

    Inputs:
        rows (list[dict]): parsed study_locations.csv rows.
        min_conf (str): lowest confidence kept (none|low|medium|high).

    Outputs:
        kept (list[dict]): rows with float lat/lon added and confidence >= floor.
    --------------------------------------------------------------------------
    """
    floor = CONF_RANK.get(min_conf, 0)
    kept = []
    for r in rows:
        try:
            r["_lat"], r["_lon"] = float(r["lat"]), float(r["lon"])
        except (ValueError, KeyError, TypeError):
            continue
        if CONF_RANK.get((r.get("confidence") or "none").lower(), 0) >= floor:
            kept.append(r)
    return kept


def _xesc(s: str) -> str:
    """Minimal XML escaping for KML text nodes."""
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def write_kml(rows: list[dict], out: str) -> None:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
             '<name>Localisation des etudes du corpus</name>']
    for r in rows:
        ev = r.get("evidence", "")
        desc = (f"{r.get('citekey', '')} | theme {r.get('theme', '')} | "
                f"{r.get('ville', '')}, {r.get('pays', '')} | conf {r.get('confidence', '')}")
        if ev:
            desc += f" | evidence ({r.get('evidence_field', '')}): {ev}"
        lines.append(
            f"<Placemark><name>{_xesc(r.get('etude', ''))} ({_xesc(r.get('ville', ''))})</name>"
            f"<description>{_xesc(desc)}</description>"
            f"<Point><coordinates>{r['_lon']},{r['_lat']},0</coordinates></Point></Placemark>")
    lines.append("</Document></kml>")
    path = os.path.join(out, "study_locations.kml")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    logger.info("[OUT] %s", path)


def write_geojson(rows: list[dict], out: str) -> None:
    features = [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [r["_lon"], r["_lat"]]},
        "properties": {k: r.get(k, "") for k in
                       ("citekey", "etude", "ville", "pays", "theme",
                        "confidence", "source", "matched",
                        "evidence_field", "evidence", "provenance")},
    } for r in rows]
    path = os.path.join(out, "study_locations.geojson")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": features}, fh,
                  ensure_ascii=False, indent=1)
    logger.info("[OUT] %s", path)


def write_country_counts(rows: list[dict], out: str) -> Counter:
    """Per-country study count (mappable rows), sorted descending."""
    counts = Counter(r.get("pays", "") or "(unknown)" for r in rows)
    path = os.path.join(out, "country_counts.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["pays", "n_etudes"])
        for country, n in counts.most_common():
            w.writerow([country, n])
    logger.info("[OUT] %s", path)
    return counts


def _iter_rings(geometry: dict):
    """Yield each exterior ring of a Polygon / MultiPolygon geometry."""
    gtype = geometry.get("type")
    if gtype == "Polygon":
        yield geometry["coordinates"][0]
    elif gtype == "MultiPolygon":
        for poly in geometry["coordinates"]:
            yield poly[0]


def write_png(rows: list[dict], out: str, title: str, labels: bool) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Draw a world map (Natural Earth basemap from raw GeoJSON) with the study
        points coloured by per-country study count, as the review figure.

    Inputs:
        rows (list[dict]): mappable rows with _lat/_lon floats.
        out (str): output directory.
        title (str): optional figure title ("" for none).
        labels (bool): annotate distinct city names when True.
    --------------------------------------------------------------------------
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon as MplPolygon
    from matplotlib.collections import PatchCollection
    from matplotlib.colors import Normalize

    ensure_basemap()
    with open(BASEMAP, encoding="utf-8") as fh:
        world = json.load(fh)

    patches = []
    for feat in world.get("features", []):
        for ring in _iter_rings(feat.get("geometry", {})):
            patches.append(MplPolygon(ring, closed=True))

    fig, ax = plt.subplots(figsize=(11, 5.6))
    ax.add_collection(PatchCollection(patches, facecolor="#eef0f2",
                                      edgecolor="white", linewidth=0.4))

    country_count = Counter(r.get("pays", "") for r in rows)
    counts = [country_count[r.get("pays", "")] for r in rows]
    lons = [r["_lon"] for r in rows]
    lats = [r["_lat"] for r in rows]
    vmax = max(counts) if counts else 1
    norm = Normalize(vmin=1, vmax=vmax)
    sc = ax.scatter(lons, lats, c=counts, cmap=plt.cm.YlOrRd, norm=norm,
                    s=[45 + 32 * c for c in counts], edgecolor="#333333",
                    linewidth=0.5, zorder=5, alpha=0.95)

    if labels:
        seen = set()
        for r in rows:
            ville = (r.get("ville") or "").split(" (")[0]
            if ville and ville not in seen:
                seen.add(ville)
                ax.annotate(ville, (r["_lon"], r["_lat"]), xytext=(3, 3),
                            textcoords="offset points", fontsize=6.5, color="#222222")

    ax.set_xlim(-179, 179)
    ax.set_ylim(-58, 84)
    ax.set_axis_off()
    if title:
        ax.set_title(title, fontsize=11)
    cbar = fig.colorbar(sc, ax=ax, fraction=0.022, pad=0.01,
                        ticks=range(1, vmax + 1))
    cbar.set_label("Nombre d'études par pays", fontsize=8)
    cbar.ax.tick_params(labelsize=7)
    plt.tight_layout(pad=0.2)
    path = os.path.join(out, "study_locations_map.png")
    plt.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    logger.info("[OUT] %s", path)


def write_html(rows: list[dict], out: str, title: str) -> bool:
    """Interactive folium map; returns False (with a note) if folium is absent."""
    try:
        import folium
    except ImportError:
        logger.warning("[HTML] folium not installed; skipping the interactive map "
                       "(pip install folium).")
        return False
    fmap = folium.Map(location=[20, 10], zoom_start=2, tiles="cartodbpositron")
    for r in rows:
        ev, ev_field = r.get("evidence", ""), r.get("evidence_field", "")
        prov = r.get("provenance", "")
        popup = (f"<b>{html.escape(r.get('etude', ''))}</b><br>{html.escape(r.get('citekey', ''))}<br>"
                 f"{html.escape(r.get('ville', ''))}, {html.escape(r.get('pays', ''))}<br>"
                 f"theme {html.escape(r.get('theme', ''))} | conf {html.escape(r.get('confidence', ''))}")
        if ev:
            popup += (f"<hr><i>read from {html.escape(ev_field)}:</i><br>"
                      f"“{html.escape(ev)}”")
        if prov:
            popup += f"<br><small>audit: {html.escape(prov)}</small>"
        folium.CircleMarker([r["_lat"], r["_lon"]], radius=5, color="#b30000",
                            fill=True, fill_opacity=0.8,
                            popup=folium.Popup(popup, max_width=260)).add_to(fmap)
    if title:
        folium.map.Marker([84, -179], icon=folium.DivIcon(
            html=f'<div style="font-size:14px;font-weight:bold">{title}</div>')).add_to(fmap)
    path = os.path.join(out, "study_locations_map.html")
    fmap.save(path)
    logger.info("[OUT] %s", path)
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description="Render study-location artifacts from a reviewed CSV.")
    ap.add_argument("--csv", required=True, help="reviewed study_locations.csv")
    ap.add_argument("--out", default=".", help="output directory")
    ap.add_argument("--formats", default="csv,kml,geojson,png,html",
                    help="comma list of csv,kml,geojson,png,html (default: all)")
    ap.add_argument("--title", default="", help="figure title (PNG/HTML)")
    ap.add_argument("--min-confidence", default="none",
                    choices=["none", "low", "medium", "high"],
                    help="drop points below this confidence from the PNG/HTML map")
    ap.add_argument("--no-labels", action="store_true", help="omit city labels on the PNG")
    args = ap.parse_args()

    if not os.path.exists(args.csv):
        logger.error("[CSV] file not found: %s", args.csv)
        sys.exit(1)
    os.makedirs(args.out, exist_ok=True)
    formats = {f.strip().lower() for f in args.formats.split(",") if f.strip()}

    rows = load_rows(args.csv)
    # Data exports (KML/GeoJSON) carry every mappable row; visual maps (PNG/HTML)
    # honour the confidence floor.
    data_rows = mappable(rows, "none")
    map_rows = mappable(rows, args.min_confidence)
    unmapped = len(rows) - len(data_rows)
    logger.info("[LOAD] %d rows | %d mappable | %d unmapped (no coords)",
                len(rows), len(data_rows), unmapped)

    if "kml" in formats:
        write_kml(data_rows, args.out)
    if "geojson" in formats:
        write_geojson(data_rows, args.out)
    counts = write_country_counts(data_rows, args.out)
    if "png" in formats:
        write_png(map_rows, args.out, args.title, not args.no_labels)
    if "html" in formats:
        write_html(map_rows, args.out, args.title)

    top = ", ".join(f"{c}={n}" for c, n in counts.most_common(5))
    logger.info("[SUMMARY] %d countries | top: %s", len(counts), top)
    if unmapped:
        logger.info("[NOTE] %d unmapped rows (global scope or unreviewed) are in the "
                    "CSV but not on the map.", unmapped)


if __name__ == "__main__":
    main()
