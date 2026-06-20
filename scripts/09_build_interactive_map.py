r"""
09_build_interactive_map.py
==========================

Builds the project's first INTERACTIVE web map (Leaflet.js) as a single,
self-contained HTML file that opens by DOUBLE-CLICKING - no web server needed.

Because browsers block fetch() of local files (file:// CORS), all the map data is
EMBEDDED directly into the HTML as JavaScript variables (the 1,294 crashes, the
top-25 deadliest corridors, the state routes, and the city boundary). Leaflet and
the markercluster plugin load from a CDN, so the page needs internet to open.

Layers:
  - Crashes: FATAL (always-visible, emphasized) + NON-FATAL (clustered).
  - Top-25 deadliest corridors (bold lines, weight scaled to crash count).
  - State routes (thin context lines) and the city boundary outline.
  - OpenStreetMap basemap.

It does NOT ship the 96 MB full street network to the browser - it only extracts
the 25 corridor geometries from it.

Run it with:
    .\.venv\Scripts\python.exe scripts\09_build_interactive_map.py
"""

import json
from pathlib import Path

import pandas as pd
import geopandas as gpd
from shapely.ops import unary_union


# ---------------------------------------------------------------------------
# SETTINGS
# ---------------------------------------------------------------------------
TOP_N_CORRIDORS = 25

COLOR_CITY = "#0e8f8f"     # teal  -> City of Memphis
COLOR_TDOT = "#d62728"     # red   -> TDOT state route
COLOR_STATE_ROUTE = "#8a8a8a"
COLOR_BOUNDARY = "#333333"

FATAL_VALUE = "Fatal"
SERIOUS_VALUE = "Suspected Serious Injury"

# Geometry simplification (degrees) just for a lean embedded file - visually
# identical at city zoom. ~0.0001 deg ~ 11 m.
SIMPLIFY_STATE_ROUTES = 0.00005
SIMPLIFY_BOUNDARY = 0.0002


# ---------------------------------------------------------------------------
# FILE PATHS
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCESSED = PROJECT_ROOT / "data" / "processed"
RAW = PROJECT_ROOT / "data" / "raw"
OUT_DIR = PROJECT_ROOT / "outputs" / "interactive_map"

NAMED_CSV = PROCESSED / "shelby_crashes_named.csv"
DEADLIEST_CSV = PROCESSED / "deadliest_streets.csv"
STREETS_GEOJSON = RAW / "memphis_streets.geojson"
STATE_ROUTES_GEOJSON = RAW / "state_routes.geojson"
BOUNDARY_GEOJSON = RAW / "memphis_boundary.geojson"

CORRIDORS_OUT = OUT_DIR / "deadliest_corridors.geojson"
HTML_OUT = OUT_DIR / "index.html"


# ---------------------------------------------------------------------------
# Standardized street name - SAME logic as script 06 (keep directional prefixes).
# ---------------------------------------------------------------------------
def clean_part(value):
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def build_street_name(predir, name, type_, sufdir, label):
    name_part = clean_part(name)
    if name_part:
        parts = [clean_part(predir), name_part, clean_part(type_), clean_part(sufdir)]
        return " ".join(" ".join(p for p in parts if p).split()).upper()
    return " ".join(clean_part(label).split()).upper()


def build_corridors():
    """Extract + merge the top-25 corridor geometries (clipped to Memphis)."""
    deadliest = pd.read_csv(DEADLIEST_CSV)
    top = deadliest.sort_values(
        ["Total_Crashes", "Fatal_Crashes"], ascending=False
    ).head(TOP_N_CORRIDORS).copy()
    top_names = set(top["Street_Name"])

    streets = gpd.read_file(STREETS_GEOJSON)
    streets["Street_Name"] = [
        build_street_name(p, n, t, s, l)
        for p, n, t, s, l in zip(streets["PREDIR"], streets["NAME"],
                                 streets["TYPE"], streets["SUFDIR"], streets["LABEL"])
    ]
    # Clip to the City of Memphis (drops suburban stretches of the same name).
    sub = streets[(streets["Street_Name"].isin(top_names)) &
                  (streets["CITY_L"] == "MEMPHIS")]

    # Merge each corridor's segments into one feature; attach ranking attributes.
    rows = []
    geoms = []
    info = top.set_index("Street_Name")
    for name in top["Street_Name"]:  # preserve ranked order
        seg = sub[sub["Street_Name"] == name]
        if len(seg) == 0:
            continue
        merged = unary_union(seg.geometry.values)
        r = info.loc[name]
        spd = r["SPDLIMIT"]
        rows.append({
            "Street_Name": name,
            "Dominant_Jurisdiction": r["Dominant_Jurisdiction"],
            "Mixed_Jurisdiction": bool(r["Mixed_Jurisdiction"]),
            "Total_Crashes": int(r["Total_Crashes"]),
            "Fatal_Crashes": int(r["Fatal_Crashes"]),
            "Serious_Injuries": int(r["Serious_Injuries"]),
            "SPDLIMIT": (None if pd.isna(spd) else int(spd)),
            "LANES": (None if pd.isna(r["LANES"]) else int(r["LANES"])),
        })
        geoms.append(merged)

    corridors = gpd.GeoDataFrame(rows, geometry=geoms, crs="EPSG:4326")
    return corridors


def build_crash_records():
    """Compact list of per-crash dicts for embedding, plus headline stats."""
    n = pd.read_csv(NAMED_CSV)
    # Defensive: drop any unusable coordinates (none expected).
    n = n[n["Latitude"].notna() & n["Longitude"].notna()].copy()

    records = []
    for _, r in n.iterrows():
        spd = r["Street_SPDLIMIT"]
        records.append({
            "lat": round(float(r["Latitude"]), 6),
            "lng": round(float(r["Longitude"]), 6),
            "sev": r["InjuryClass"],
            "date": r["CollisionDate"],
            "st": r["Street_Name"],
            "jur": "T" if r["Jurisdiction"] == "TDOT" else "C",
            "ln": None if pd.isna(r["Street_LANES"]) else int(r["Street_LANES"]),
            "sp": 0 if pd.isna(spd) else int(spd),
            "loc": ("" if pd.isna(r["NonMotoristLocation"]) else r["NonMotoristLocation"]),
            "f": 1 if r["InjuryClass"] == FATAL_VALUE else 0,
        })

    total = len(n)
    n_city = int((n["Jurisdiction"] == "City of Memphis").sum())
    n_tdot = int((n["Jurisdiction"] == "TDOT").sum())
    stats = {
        "total": total,
        "city": n_city, "tdot": n_tdot,
        "city_pct": round(100.0 * n_city / total, 1),
        "tdot_pct": round(100.0 * n_tdot / total, 1),
        "fatal": int((n["InjuryClass"] == FATAL_VALUE).sum()),
        "date_min": n["CollisionDate"].min(),
        "date_max": n["CollisionDate"].max(),
    }
    return records, stats


def simplified_geojson(path, tolerance):
    g = gpd.read_file(path)
    g["geometry"] = g.geometry.simplify(tolerance, preserve_topology=True)
    return json.loads(g.to_json())


# ---------------------------------------------------------------------------
# The HTML template. Data is injected via __PLACEHOLDER__ replacements (NOT
# .format) so the CSS/JS braces are left untouched.
# ---------------------------------------------------------------------------
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Memphis Pedestrian &amp; Non-Motorist Crashes by Road Ownership</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css" />
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css" />
<style>
  html, body { height: 100%; margin: 0; font-family: "Segoe UI", Roboto, Helvetica, Arial, sans-serif; color: #1a1a1a; }
  #header { position: absolute; top: 0; left: 0; right: 0; height: 64px; background: #14303f; color: #fff;
            padding: 8px 16px; box-sizing: border-box; z-index: 1000; box-shadow: 0 2px 6px rgba(0,0,0,.3); }
  #header h1 { margin: 0; font-size: 19px; font-weight: 600; }
  #header p  { margin: 2px 0 0; font-size: 12px; color: #b9d2dd; }
  #map { position: absolute; top: 64px; bottom: 0; left: 0; right: 0; }
  .box { background: rgba(255,255,255,.94); padding: 10px 12px; border-radius: 6px;
         box-shadow: 0 1px 5px rgba(0,0,0,.35); font-size: 12px; line-height: 1.5; }
  .info-box b { font-size: 13px; }
  .legend-row { display: flex; align-items: center; margin: 3px 0; }
  .legend-row span.sym { display: inline-block; width: 26px; text-align: center; margin-right: 8px; }
  .dot { display: inline-block; width: 12px; height: 12px; border-radius: 50%; }
  .dot-ring { width: 14px; height: 14px; border: 2px solid #111; box-sizing: border-box; }
  .line { display: inline-block; width: 22px; height: 0; vertical-align: middle; }
  .leaflet-popup-content { font-size: 12.5px; line-height: 1.5; }
  .leaflet-popup-content b { color: #14303f; }
  .legend h4, .info-box h4 { margin: 0 0 6px; font-size: 13px; }
</style>
</head>
<body>
<div id="header">
  <h1>Memphis Pedestrian &amp; Non-Motorist Crashes by Road Ownership</h1>
  <p>Who owns the roads where people are hurt and killed &mdash; City of Memphis vs. Tennessee DOT. Interactive prototype (v1).</p>
</div>
<div id="map"></div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>

<script>
/* ---- EMBEDDED DATA (no fetch; works on file://) ---- */
var CRASHES     = __CRASHES__;
var CORRIDORS   = __CORRIDORS__;
var STATE_ROUTES = __STATE_ROUTES__;
var BOUNDARY    = __BOUNDARY__;
var STATS       = __STATS__;
</script>

<script>
var COLOR_CITY = "__COLOR_CITY__";
var COLOR_TDOT = "__COLOR_TDOT__";
var COLOR_STATE_ROUTE = "__COLOR_STATE_ROUTE__";
var COLOR_BOUNDARY = "__COLOR_BOUNDARY__";

function jurColor(j) { return j === "T" ? COLOR_TDOT : COLOR_CITY; }
function jurName(j)  { return j === "T" ? "TDOT (state route)" : "City of Memphis"; }
function esc(s) { return (s == null ? "" : String(s)).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function roadChar(ln, sp) {
  var parts = [];
  if (ln != null) parts.push(ln + (ln === 1 ? " lane" : " lanes"));
  parts.push(sp && sp > 0 ? sp + " mph" : "speed n/a");
  return parts.join(", ");
}

var map = L.map("map", { zoomControl: true, preferCanvas: true }).setView([35.13, -89.97], 11);

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
}).addTo(map);

/* ---- City boundary (bottom) ---- */
var boundaryLayer = L.geoJSON(BOUNDARY, {
  style: { color: COLOR_BOUNDARY, weight: 1.6, fill: false, opacity: 0.9 }
}).addTo(map);

/* ---- State routes (thin context) ---- */
var stateRouteLayer = L.geoJSON(STATE_ROUTES, {
  style: { color: COLOR_STATE_ROUTE, weight: 1.1, opacity: 0.8 }
}).addTo(map);

/* ---- Deadliest corridors (bold, weight scaled to crash count) ---- */
var maxTotal = 1;
CORRIDORS.features.forEach(function (f) { maxTotal = Math.max(maxTotal, f.properties.Total_Crashes); });
function corridorWeight(t) { return 3.5 + (t / maxTotal) * 9; }

var corridorLayer = L.geoJSON(CORRIDORS, {
  style: function (f) {
    var p = f.properties;
    var col = (p.Dominant_Jurisdiction === "TDOT") ? COLOR_TDOT : COLOR_CITY;
    return { color: col, weight: corridorWeight(p.Total_Crashes), opacity: 0.9, lineCap: "round" };
  },
  onEachFeature: function (f, layer) {
    var p = f.properties;
    var owner = esc(p.Dominant_Jurisdiction);
    if (p.Mixed_Jurisdiction) owner += " <i>(ownership varies along this corridor)</i>";
    var html =
      "<b>" + esc(p.Street_Name) + "</b><br>" +
      "<b>Owner:</b> " + owner + "<br>" +
      "<b>Total crashes:</b> " + p.Total_Crashes +
        " &nbsp; <b>Fatal:</b> " + p.Fatal_Crashes +
        " &nbsp; <b>Serious:</b> " + p.Serious_Injuries + "<br>" +
      "<b>Road:</b> " + roadChar(p.LANES, p.SPDLIMIT);
    layer.bindPopup(html);
    layer.on("mouseover", function () { this.setStyle({ weight: corridorWeight(p.Total_Crashes) + 3 }); });
    layer.on("mouseout",  function () { this.setStyle({ weight: corridorWeight(p.Total_Crashes) }); });
  }
}).addTo(map);

/* ---- Crash markers ---- */
function crashPopup(c) {
  return "<b>" + esc(c.sev) + "</b><br>" +
         esc(c.date) + "<br>" +
         "<b>Street:</b> " + esc(c.st) + "<br>" +
         "<b>Owner:</b> " + jurName(c.jur) + "<br>" +
         "<b>Road:</b> " + roadChar(c.ln, c.sp) + "<br>" +
         "<b>Where:</b> " + esc(c.loc);
}

var fatalLayer = L.layerGroup();
var nonFatalCluster = L.markerClusterGroup({
  disableClusteringAtZoom: 17,
  spiderfyOnMaxZoom: false,
  chunkedLoading: true,
  maxClusterRadius: 45
});

CRASHES.forEach(function (c) {
  if (c.f === 1) {
    L.circleMarker([c.lat, c.lng], {
      radius: 7, color: "#111", weight: 2,
      fillColor: jurColor(c.jur), fillOpacity: 0.95
    }).bindPopup(crashPopup(c)).addTo(fatalLayer);
  } else {
    L.circleMarker([c.lat, c.lng], {
      radius: 4, stroke: false,
      fillColor: jurColor(c.jur), fillOpacity: 0.8
    }).bindPopup(crashPopup(c)).addTo(nonFatalCluster);
  }
});
nonFatalCluster.addTo(map);
fatalLayer.addTo(map);  // added last -> always on top

/* ---- Frame the map on the city ---- */
try { map.fitBounds(boundaryLayer.getBounds(), { padding: [10, 10] }); } catch (e) {}

/* ---- Scale bar ---- */
L.control.scale({ imperial: true, metric: true }).addTo(map);

/* ---- Layer control ---- */
L.control.layers(null, {
  "Fatal crashes": fatalLayer,
  "Non-fatal crashes (clustered)": nonFatalCluster,
  "Deadliest corridors (top 25)": corridorLayer,
  "State routes": stateRouteLayer,
  "City boundary": boundaryLayer
}, { collapsed: false, position: "topright" }).addTo(map);

/* ---- Info box ---- */
var info = L.control({ position: "topleft" });
info.onAdd = function () {
  var d = L.DomUtil.create("div", "box info-box");
  d.innerHTML =
    "<h4>In-Memphis crashes</h4>" +
    "<b>" + STATS.total.toLocaleString() + "</b> total &nbsp;&middot;&nbsp; <b>" + STATS.fatal + "</b> fatal<br>" +
    "City of Memphis: " + STATS.city.toLocaleString() + " (" + STATS.city_pct + "%)<br>" +
    "TDOT state route: " + STATS.tdot.toLocaleString() + " (" + STATS.tdot_pct + "%)<br>" +
    "<span style='color:#555'>" + STATS.date_min + " &ndash; " + STATS.date_max + "</span>";
  return d;
};
info.addTo(map);

/* ---- Legend ---- */
var legend = L.control({ position: "bottomright" });
legend.onAdd = function () {
  var d = L.DomUtil.create("div", "box legend");
  function dot(color, ring) {
    return "<span class='dot " + (ring ? "dot-ring" : "") + "' style='background:" + color + "'></span>";
  }
  function line(color, h) {
    return "<span class='line' style='border-top:" + h + "px solid " + color + "'></span>";
  }
  d.innerHTML =
    "<h4>Legend</h4>" +
    "<div class='legend-row'><span class='sym'>" + dot(COLOR_CITY) + "</span>City of Memphis crash</div>" +
    "<div class='legend-row'><span class='sym'>" + dot(COLOR_TDOT) + "</span>TDOT (state route) crash</div>" +
    "<div class='legend-row'><span class='sym'>" + dot("#999", true) + "</span>Fatal crash (larger, outlined)</div>" +
    "<div class='legend-row'><span class='sym'>" + line(COLOR_CITY, 5) + "</span>Deadliest corridor &ndash; City</div>" +
    "<div class='legend-row'><span class='sym'>" + line(COLOR_TDOT, 5) + "</span>Deadliest corridor &ndash; TDOT</div>" +
    "<div class='legend-row'><span class='sym'>" + line(COLOR_STATE_ROUTE, 2) + "</span>State route</div>" +
    "<div class='legend-row'><span class='sym'>" + line(COLOR_BOUNDARY, 2) + "</span>City boundary</div>";
  return d;
};
legend.addTo(map);
</script>
</body>
</html>
"""


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Building interactive map...")

    print("  Extracting top-25 corridor geometry (clipped to Memphis)...")
    corridors = build_corridors()
    corridors.to_file(CORRIDORS_OUT, driver="GeoJSON")
    print(f"    Saved {len(corridors)} corridors -> {CORRIDORS_OUT.name}")

    print("  Building crash records + stats...")
    crash_records, stats = build_crash_records()
    print(f"    {len(crash_records)} crashes ({stats['fatal']} fatal)")

    print("  Simplifying + loading context layers...")
    state_routes_gj = simplified_geojson(STATE_ROUTES_GEOJSON, SIMPLIFY_STATE_ROUTES)
    boundary_gj = simplified_geojson(BOUNDARY_GEOJSON, SIMPLIFY_BOUNDARY)
    corridors_gj = json.loads(corridors.to_json())

    print("  Writing HTML...")

    def embed(obj):
        # Compact JSON, hardened so an embedded string can never break out of the
        # <script> block (escape < and > as unicode).
        text = json.dumps(obj, separators=(",", ":"))
        return text.replace("<", "\\u003c").replace(">", "\\u003e")

    html = HTML_TEMPLATE
    replacements = {
        "__CRASHES__": embed(crash_records),
        "__CORRIDORS__": embed(corridors_gj),
        "__STATE_ROUTES__": embed(state_routes_gj),
        "__BOUNDARY__": embed(boundary_gj),
        "__STATS__": embed(stats),
        "__COLOR_CITY__": COLOR_CITY,
        "__COLOR_TDOT__": COLOR_TDOT,
        "__COLOR_STATE_ROUTE__": COLOR_STATE_ROUTE,
        "__COLOR_BOUNDARY__": COLOR_BOUNDARY,
    }
    for key, value in replacements.items():
        html = html.replace(key, value)
    HTML_OUT.write_text(html, encoding="utf-8")

    size_mb = HTML_OUT.stat().st_size / 1e6
    print()
    print("=" * 64)
    print(f"Saved map -> {HTML_OUT}")
    print(f"Saved corridors -> {CORRIDORS_OUT}")
    print(f"HTML size: {size_mb:.2f} MB")
    print("NOTE: open by double-clicking index.html. Needs internet for the")
    print("      Leaflet CDN scripts and the OpenStreetMap basemap tiles.")
    print("=" * 64)


if __name__ == "__main__":
    main()
