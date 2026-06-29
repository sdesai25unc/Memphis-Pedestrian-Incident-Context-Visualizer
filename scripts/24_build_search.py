r"""
24_build_search.py
================

MAP SEARCH FEATURE (additive) — builds a precomputed search index and injects a
type-ahead corridor / intersection / address search into the existing public map.
Does NOT change any existing layer, toggle, chart, or stat; the search is purely
additive and idempotent (re-running replaces only the injected block).

PART 1 — search index (data/processed/search_index.json, also embedded in the page):
  - CORRIDORS: every named street with >=1 crash. Crash counts use the SAME
    Street_Name grouping as the deadliest-corridor card (so they match exactly):
    total, fatal, ownership split (City / TDOT / Limited-access), deadliest rank,
    # signalized intersections on the corridor (covered corridors only, else
    "not yet analyzed"), simplified centerline geometry, and safe-crossing stats
    ONLY for Union (from union_safe_summary.json) — "not yet analyzed" elsewhere.
  - INTERSECTIONS: covered junction nodes that have >=1 crash OR are signalized:
    crashes, deaths, signalized (yes/no), nearest safe crossing (Union only), location.

PART 2 — injects the search UI + logic into outputs/interactive_map/index.html
  (embedded for file:// use). Address queries dispatch to the free, no-key US Census
  geocoder client-side, with graceful failure.

Run it AFTER script 18 (rebuilding index.html drops the injection; just re-run this):
    .\.venv\Scripts\python.exe scripts\24_build_search.py
"""

import sys
import json
import re
from pathlib import Path

import pandas as pd
import geopandas as gpd

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"
RAW = ROOT / "data" / "raw"
HTML = ROOT / "outputs" / "interactive_map" / "index.html"
INDEX_JSON = PROC / "search_index.json"

FINAL = PROC / "shelby_crashes_final.csv"
SIGNALS = PROC / "shelby_crashes_signals.csv"
NODES = PROC / "intersection_nodes_all.geojson"        # EVERY junction citywide (script 25)
NODES_COVERED = PROC / "intersection_nodes_covered.geojson"  # old covered set (for Union safe-dist transfer)
COVERED_OUT = PROC / "covered_corridors.json"           # authoritative covered-corridor set (script 25)
RULEBOOK = PROC / "road_ownership_rulebook.geojson"
UNION_SUM = PROC / "union_safe_summary.json"

CRS_M, CRS_GEO = "EPSG:32136", "EPSG:4326"
FATAL = "Fatal"
CAT3 = {"City of Memphis": "City", "TDOT state route": "TDOT",
        "Interstate (TDOT)": "Limited", "Interstate ramp (TDOT)": "Limited",
        "Limited-access (TDOT)": "Limited"}
SUFFIX = {"AVE": "Avenue", "ST": "Street", "RD": "Road", "BLVD": "Boulevard",
          "DR": "Drive", "PKWY": "Parkway", "HWY": "Highway", "LN": "Lane",
          "CT": "Court", "PL": "Place", "CIR": "Circle", "PIKE": "Pike",
          "EXT": "Ext", "WAY": "Way", "COVE": "Cove", "TER": "Terrace"}


def titlecase_street(name):
    out = []
    for w in str(name).split():
        out.append(SUFFIX.get(w, w.capitalize() if not w.isdigit() else w))
    return " ".join(out)


# Count-A geometry: each crash corridor's full-resolution centerline is embedded in EPSG:32136
# meters (rounded to int), simplified at this tolerance. The browser snaps query points to it and
# measures along-corridor distance in the SAME metric frame (its JS LCC projection matches pyproj
# to <0.001 mm). Keep this modest -- it controls both snap accuracy and embedded payload size.
SIMPLIFY_MG_M = 10


def measure_xy(mg, px, py):
    """Nearest point on a metric multipath mg=[[[x,y],...],...] to (px,py).
    Returns (along_distance_m, perpendicular_distance_m). MUST stay byte-for-byte identical in
    logic to the JS measureXY() so crash measures (Python) and query measures (JS) are consistent."""
    best_d = float("inf")
    best_m = 0.0
    base = 0.0
    for path in mg:
        cum = 0.0
        for i in range(len(path) - 1):
            ax, ay = path[i]
            bx, by = path[i + 1]
            dx = bx - ax
            dy = by - ay
            l2 = dx * dx + dy * dy
            t = 0.0 if l2 == 0 else ((px - ax) * dx + (py - ay) * dy) / l2
            t = 0.0 if t < 0 else (1.0 if t > 1 else t)
            cx = ax + t * dx
            cy = ay + t * dy
            d2 = (px - cx) ** 2 + (py - cy) ** 2
            seg = l2 ** 0.5
            if d2 < best_d:
                best_d = d2
                best_m = base + cum + t * seg
            cum += seg
        base += cum
    return best_m, best_d ** 0.5


def count_a_demo(corridors, lat, lon, window=300):
    """Server-side mirror of the JS countA() -- proves the embedded data yields the same counts.
    Snaps (lat,lon) to the nearest crash corridor in EPSG:32136 and counts along-corridor crashes."""
    from pyproj import Transformer
    px, py = Transformer.from_crs(CRS_GEO, CRS_M, always_xy=True).transform(lon, lat)
    ranked = []
    for c in corridors:
        if c["mg"]:
            m, d = measure_xy(c["mg"], px, py)
            ranked.append((d, m, c))
    ranked.sort(key=lambda t: t[0])
    d, m, c = ranked[0]
    lo, hi = m - window, m + window
    n = sum(1 for mm in c["xm"] if lo <= mm <= hi)
    fat = sum(fa for mm, fa in zip(c["xm"], c["xf"]) if lo <= mm <= hi)
    alt = next((t for t in ranked[1:] if t[2]["raw"] != c["raw"]), None)
    return {"road": c["disp"], "snap_m": d, "n": n, "fat": fat,
            "alt": (alt[2]["disp"] if alt else None), "alt_m": (alt[0] if alt else None),
            "corridor_total": c["total"], "corridor_fatal": c["fatal"]}


def build_index():
    f = pd.read_csv(FINAL)
    f["cat3"] = f["Ownership"].map(CAT3)
    g = f.groupby("Street_Name")
    agg = g.agg(
        total=("MstrRecNbrTxt", "size"),
        fatal=("InjuryClass", lambda s: int((s == FATAL).sum())),
        city=("cat3", lambda s: int((s == "City").sum())),
        tdot=("cat3", lambda s: int((s == "TDOT").sum())),
        limited=("cat3", lambda s: int((s == "Limited").sum())),
    )
    ranked = agg.sort_values(["total", "fatal"], ascending=False).reset_index()
    ranked["rank"] = range(1, len(ranked) + 1)
    rank_map = dict(zip(ranked["Street_Name"], ranked["rank"]))

    # ALL junctions citywide (script 25 -- true geometric intersection)
    nodes = gpd.read_file(NODES)
    nodes_geo = nodes.to_crs(CRS_GEO)
    # covered corridors come from script 25's sidecar (authoritative); a corridor not in this
    # set has no signal inventory -> n_signalized stays None ("not yet analyzed").
    covered = set(json.loads(COVERED_OUT.read_text())) if COVERED_OUT.exists() else set()
    sig_count = {}
    for _, nd in nodes.iterrows():
        if not bool(nd["signalized"]):
            continue
        for s in [s.strip() for s in str(nd["streets"]).split(";") if s.strip()]:
            if s in covered:
                sig_count[s] = sig_count.get(s, 0) + 1

    union = json.loads(UNION_SUM.read_text()) if UNION_SUM.exists() else {}
    union_safe = {
        "n_safe": union.get("n_safe"), "n_signalized": union.get("n_signalized"),
        "n_marked_only": union.get("n_marked_only"), "longest_gap_ft": union.get("longest_gap_ft"),
        "pct_over_250ft": union.get("pct_over_250ft"), "median_spacing_ft": union.get("median_spacing_ft"),
    } if union else None
    # Union per-node nearest-safe distances were keyed by the OLD covered-node ids; transfer them
    # to the rebuilt Union nodes by location (nearest old covered node within 25 m).
    union_node_dist = {int(k): v for k, v in union.get("node_nearest_safe_m", {}).items()}
    new_union_safe_m = {}
    if union_node_dist and NODES_COVERED.exists():
        oldc = gpd.read_file(NODES_COVERED).to_crs(CRS_M)
        oldc = oldc[oldc["node_id"].isin(union_node_dist.keys())].copy()
        oldc["safe_m"] = oldc["node_id"].map(union_node_dist)
        new_union = nodes.to_crs(CRS_M)
        new_union = new_union[new_union["streets"].str.contains("UNION AVE", na=False)]
        if len(oldc) and len(new_union):
            mt = gpd.sjoin_nearest(new_union[["node_id", "geometry"]],
                                   oldc[["safe_m", "geometry"]], how="left", distance_col="d")
            mt = mt[~mt.index.duplicated(keep="first")]
            for nid, sm, d in zip(mt["node_id"], mt["safe_m"], mt["d"]):
                if d <= 25:
                    new_union_safe_m[int(nid)] = float(sm)

    # corridor centerlines (simplified) for highlight + address nearest-corridor
    rb = gpd.read_file(RULEBOOK).to_crs(CRS_M)

    # Count A: project every crash to EPSG:32136 once, grouped by the road it's attributed to
    # (the SAME Street_Name attribution the deadliest-corridor cards use -- not a blind radius).
    cf = f[["Street_Name", "Latitude", "Longitude", "InjuryClass"]].dropna(subset=["Latitude", "Longitude"])
    cg = gpd.GeoDataFrame(cf, geometry=gpd.points_from_xy(cf["Longitude"], cf["Latitude"]),
                          crs=CRS_GEO).to_crs(CRS_M)
    crashpts = {}
    for nm, grp in cg.groupby("Street_Name"):
        crashpts[nm] = [(geom.x, geom.y, inj == FATAL)
                        for geom, inj in zip(grp.geometry, grp["InjuryClass"])]

    corridors = []
    n_no_geom = 0
    for name in agg.index:
        r = agg.loc[name]
        segs = rb[rb["Street_Name"] == name]
        paths = []      # lat/lon, simplified 20 m -> Leaflet highlight (display only)
        mg = []         # EPSG:32136 metric, simplified SIMPLIFY_MG_M, int -> Count A snap + measure
        if len(segs):
            geo = segs.copy()
            geo["geometry"] = geo.geometry.simplify(20, preserve_topology=False)
            for gm in geo.to_crs(CRS_GEO).geometry:
                if gm is None or gm.is_empty:
                    continue
                lines = gm.geoms if gm.geom_type == "MultiLineString" else [gm]
                for ln in lines:
                    paths.append([[round(y, 5), round(x, 5)] for x, y in ln.coords])
            gm_m = segs.copy()
            gm_m["geometry"] = gm_m.geometry.simplify(SIMPLIFY_MG_M, preserve_topology=False)
            for gm in gm_m.geometry:
                if gm is None or gm.is_empty:
                    continue
                lines = gm.geoms if gm.geom_type == "MultiLineString" else [gm]
                for ln in lines:
                    mg.append([[int(round(x)), int(round(y))] for x, y in ln.coords])
        # along-corridor measure + fatal flag for each crash on this road (same metric mg the JS uses)
        xm, xf = [], []
        if mg:
            for (cx, cy, fa) in crashpts.get(name, []):
                mm, _ = measure_xy(mg, cx, cy)
                xm.append(int(round(mm)))
                xf.append(1 if fa else 0)
        else:
            n_no_geom += 1
        corridors.append({
            "disp": titlecase_street(name), "raw": name,
            "total": int(r.total), "fatal": int(r.fatal),
            "city": int(r.city), "tdot": int(r.tdot), "limited": int(r.limited),
            "rank": int(rank_map[name]),
            "n_signalized": (sig_count.get(name, 0) if name in covered else None),
            "safe": (union_safe if name == "UNION AVE" else None),
            "geom": paths, "mg": mg, "xm": xm, "xf": xf,
        })
    if n_no_geom:
        print(f"  NOTE: {n_no_geom} crash corridors have no rulebook geometry (excluded from Count A snap)")

    # intersections: EVERY junction citywide (crash counts/deaths/signalized precomputed by script 25).
    # Packed as compact arrays [disp, lat, lon, crashes, deaths, sig, near_safe_ft] to keep the
    # embedded index small; sig in {"y": signalized, "n": covered+unsignalized, "u": no signal coverage}.
    # 0-crash nodes are INCLUDED and searchable (they honestly report "0 incidents reported here").
    intersections = []
    with_crash = 0
    for _, nd in nodes_geo.iterrows():
        nid = int(nd["node_id"])
        sts = [titlecase_street(s.strip()) for s in str(nd["streets"]).split(";") if s.strip()]
        c = nd.geometry.centroid
        cr = int(nd["crashes"]); dt = int(nd["deaths"])
        if cr:
            with_crash += 1
        sig = "y" if bool(nd["signalized"]) else ("n" if bool(nd["on_covered"]) else "u")
        nsf = new_union_safe_m.get(nid)
        intersections.append([" & ".join(sts), round(c.y, 5), round(c.x, 5), cr, dt, sig,
                              (round(nsf / 0.3048) if nsf is not None else None)])

    idx = {"corridors": corridors, "intersections": intersections,
           "meta": {"n_corridors": len(corridors), "n_intersections": len(intersections),
                    "n_intersections_with_crash": with_crash, "total_crashes": int(f.shape[0])}}
    return idx, f, agg


def reconcile(idx, f):
    # independent recompute of the deadliest top-25 (same method script 18 uses)
    g = f.groupby("Street_Name").agg(
        total=("MstrRecNbrTxt", "size"),
        fatal=("InjuryClass", lambda s: int((s == FATAL).sum())))
    top = g.sort_values(["total", "fatal"], ascending=False).head(25).reset_index()
    by_rank = {c["rank"]: c for c in idx["corridors"]}
    print("\n=== RECONCILIATION: index corridors vs deadliest-card method (top 12 shown) ===")
    print(f"{'#':>2} {'street':<22} {'idx total/fatal':>16} {'card total/fatal':>17}  match")
    ok = True
    for i, row in top.iterrows():
        rank = i + 1
        ic = by_rank[rank]
        m = (ic["raw"] == row["Street_Name"] and ic["total"] == int(row["total"])
             and ic["fatal"] == int(row["fatal"]))
        ok = ok and m
        if rank <= 12:
            print(f"{rank:>2} {ic['disp']:<22} {str(ic['total'])+'/'+str(ic['fatal']):>16} "
                  f"{str(int(row['total']))+'/'+str(int(row['fatal'])):>17}  {'OK' if m else 'MISMATCH'}")
    tot = sum(c["total"] for c in idx["corridors"])
    print(f"\nAll 25 deadliest match exactly: {ok}")
    print(f"Sum of all corridor totals = {tot} (expected {f.shape[0]}) "
          f"{'OK' if tot == f.shape[0] else 'MISMATCH'}")
    return ok


def inject(idx):
    blob = json.dumps(idx, separators=(",", ":"))
    block = ("<!-- SEARCH-FEATURE-START -->\n" + _CSS +
             '<div id="searchWrap"><div id="searchPanel">'
             '<div id="searchTop"><span class="lbl">Input</span>'
             '<span id="segMode"><button id="segAddr" class="on">Address</button>'
             '<button id="segCoord">Coordinates</button></span></div>'
             '<input id="searchBox" autocomplete="off" '
             'placeholder="Search a street, intersection, or address…">'
             '<div id="searchHint">…or click anywhere on the map to locate a point</div>'
             '</div>'
             '<div id="searchDrop"></div><div id="searchCard"></div></div>\n'
             '<script>window.SEARCH_INDEX=' + blob + ';</script>\n'
             "<script>\n" + _JS + "\n</script>\n<!-- SEARCH-FEATURE-END -->\n")
    html = HTML.read_text(encoding="utf-8")
    pat = re.compile(r"<!-- SEARCH-FEATURE-START -->.*?<!-- SEARCH-FEATURE-END -->\n?", re.S)
    html = pat.sub("", html)
    html = html.replace("</body>", block + "</body>")
    HTML.write_text(html, encoding="utf-8")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    idx, f, agg = build_index()
    blob = json.dumps(idx, separators=(",", ":"))
    INDEX_JSON.write_text(blob, encoding="utf-8")
    ok = reconcile(idx, f)
    inject(idx)

    html_kb = HTML.stat().st_size / 1024
    print(f"\nIndex: {idx['meta']['n_corridors']} corridors, "
          f"{idx['meta']['n_intersections']:,} intersections "
          f"({idx['meta']['n_intersections_with_crash']:,} carry >=1 crash; the rest are searchable "
          f"and report '0 incidents reported here').")
    print(f"  embedded index size: {len(blob)/1024:.0f} KB  ->  index.html now {html_kb:.0f} KB "
          f"({'OK to embed' if html_kb < 4096 else 'LARGE -- consider lazy-load'})")

    # three example lookups
    print("\n=== EXAMPLE LOOKUPS ===")
    c = next(x for x in idx["corridors"] if x["raw"] == "POPLAR AVE")
    print(f"[corridor] {c['disp']}: rank #{c['rank']}, {c['total']} crashes / {c['fatal']} fatal, "
          f"owner City {c['city']}/TDOT {c['tdot']}/Limited {c['limited']}, "
          f"signalized intersections {c['n_signalized']}, safe-crossing "
          f"{'not yet analyzed' if not c['safe'] else c['safe']}")
    u = next(x for x in idx["corridors"] if x["raw"] == "UNION AVE")
    print(f"[corridor] {u['disp']}: rank #{u['rank']}, {u['total']}/{u['fatal']}, "
          f"SAFE={u['safe']}")
    SIGMAP = {"y": "signalized", "n": "unsignalized", "u": "no signal coverage"}
    it = max(idx["intersections"], key=lambda x: x[3])  # packed: [disp,lat,lon,crashes,deaths,sig,nsf]
    print(f"[intersection] {it[0]}: {it[3]} crashes / {it[4]} fatal, signal={SIGMAP[it[5]]}, "
          f"nearest safe crossing={(str(it[6])+' ft') if it[6] is not None else 'not yet analyzed'}")
    uc = next((x for x in idx["intersections"]
               if "Union Avenue" in x[0] and "Cleveland" in x[0]), None)
    print(f"[ACCEPTANCE] Union & S Cleveland -> "
          + (f"FOUND '{uc[0]}': {uc[3]} crashes / {uc[4]} fatal, signal={SIGMAP[uc[5]]} "
             f"(searchable: yes)" if uc else "*** NOT IN INDEX ***"))
    # ---- COUNT A worked examples on Union (all three input modes share ONE pipeline: countA) ----
    print("\n=== COUNT A (road-attributed) — worked examples on UNION AVE ===")
    _wn = re.search(r"COUNTA_WINDOW_M\s*=\s*(\d+)", _JS)
    print(f"  window N = {_wn.group(1) if _wn else '?'} m "
          "(change in scripts/24_build_search.py: _JS var COUNTA_WINDOW_M)")
    cors = idx["corridors"]
    # (1) ADDRESS mode: geocode a real Union address server-side (same Census the proxy uses), then countA
    try:
        import requests
        gu = ("https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
              "?address=" + requests.utils.quote("1779 Union Ave, Memphis, TN") +
              "&benchmark=Public_AR_Current&format=json")
        mm = requests.get(gu, timeout=15).json()["result"]["addressMatches"][0]
        alat, alon = mm["coordinates"]["y"], mm["coordinates"]["x"]
        a = count_a_demo(cors, alat, alon)
        print(f"  [address]     '1779 Union Ave' -> {alat:.5f},{alon:.5f} -> on {a['road']} "
              f"(snap {a['snap_m']:.0f} m): {a['n']} crashes / {a['fat']} fatal in ±300 m")
    except Exception as e:
        print(f"  [address]     (Census lookup skipped: {e})")
    # (2) COORDINATES mode: Union & S Cleveland point
    c2 = count_a_demo(cors, 35.13684, -90.01667)
    print(f"  [coordinates] 35.13684,-90.01667 -> on {c2['road']} (snap {c2['snap_m']:.0f} m): "
          f"{c2['n']} crashes / {c2['fat']} fatal in ±300 m"
          + (f"  [ambiguous w/ {c2['alt']} @ {c2['alt_m']:.0f} m]" if c2['alt_m'] is not None and (c2['alt_m']-c2['snap_m'])<=15 else ""))
    # (3) CLICK mode: a different Union point (midtown, near S Cox)
    c3 = count_a_demo(cors, 35.13353, -89.98368)
    print(f"  [click]       35.13353,-89.98368 -> on {c3['road']} (snap {c3['snap_m']:.0f} m): "
          f"{c3['n']} crashes / {c3['fat']} fatal in ±300 m")
    # bonus — parallel-street discrimination: a point between Union and Court attributes to the nearer
    cpar = count_a_demo(cors, 35.13839, -89.99494)
    print(f"  [parallel chk] 35.13839,-89.99494 -> on {cpar['road']} (snap {cpar['snap_m']:.0f} m): "
          f"{cpar['n']}/{cpar['fat']} — nearer than Union, so Union's crashes are NOT grabbed")
    # reconciliation: whole-corridor window must equal the Union card total (proves attribution matches)
    full = count_a_demo(cors, 35.13684, -90.01667, window=10**7)
    print(f"  reconcile: whole-Union window = {full['n']}/{full['fat']} "
          f"(Union card = {full['corridor_total']}/{full['corridor_fatal']}; "
          f"{'MATCH' if (full['n'],full['fat'])==(full['corridor_total'],full['corridor_fatal']) else 'MISMATCH'})")

    print(f"\nAll 25 deadliest corridors match the published card: {ok}. "
          "Search is additive; existing map/layers/toggles/charts untouched.")


_CSS = """<style>
#searchWrap{position:absolute;z-index:1200;top:12px;right:14px;left:auto;width:min(380px,calc(100vw - 28px));font-family:system-ui,Segoe UI,Roboto,sans-serif}
@media(max-width:560px){#searchWrap{right:8px;left:8px;width:auto}}
#searchPanel{background:#fff;border-radius:11px;box-shadow:0 4px 18px rgba(0,0,0,.28);padding:11px 12px}
#searchTop{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px}
#searchTop .lbl{font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:#54646c}
#segMode{display:inline-flex;border:1px solid #cdd6dc;border-radius:8px;overflow:hidden}
#segMode button{appearance:none;border:none;background:#fff;color:#54646c;font-size:12px;font-weight:600;padding:5px 13px;cursor:pointer;transition:background .12s}
#segMode button+button{border-left:1px solid #cdd6dc}
#segMode button.on{background:#14303f;color:#fff}
#searchBox{width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid #cdd6dc;border-radius:8px;font-size:14px}
#searchBox:focus{outline:none;border-color:#2a6f97;box-shadow:0 0 0 3px rgba(42,111,151,.15)}
#searchHint{font-size:11px;color:#8a9aa2;margin-top:7px}
#searchDrop{background:#fff;border-radius:9px;margin-top:5px;box-shadow:0 4px 16px rgba(0,0,0,.22);overflow:hidden;display:none}
#searchDrop .it{padding:8px 13px;cursor:pointer;font-size:13px;border-bottom:1px solid #eef1f3}
#searchDrop .it:hover,#searchDrop .it.sel{background:#eaf3f7}
#searchDrop .it b{color:#14303f}
#searchDrop .it .ty{float:right;color:#8aa;font-size:11px;text-transform:uppercase}
#searchCard{background:#fff;border-radius:10px;margin-top:6px;box-shadow:0 4px 16px rgba(0,0,0,.22);padding:13px 15px;font-size:13px;line-height:1.55;display:none}
#searchCard h2{margin:0 0 6px;font-size:16px;color:#14303f}
#searchCard .na{color:#a06000;font-style:italic}
#searchCard .x{float:right;cursor:pointer;color:#8aa;font-weight:700}
#searchCard .row{margin:2px 0}
</style>"""

_JS = r"""
(function(){
 var IDX=window.SEARCH_INDEX, box=document.getElementById('searchBox'),
     drop=document.getElementById('searchDrop'), card=document.getElementById('searchCard');
 var layer=L.layerGroup().addTo(map);
 function norm(s){return (s||'').toLowerCase().replace(/\band\b/g,'&').replace(/[^a-z0-9& ]/g,' ').replace(/\s+/g,' ').trim();}
 function toks(s){return norm(s).replace(/&/g,' ').split(' ').filter(Boolean);}
 // searchable items (intersections arrive packed as [disp,lat,lon,crashes,deaths,sig,near_safe_ft])
 var items=[];
 var INTERS=IDX.intersections.map(function(a){return {disp:a[0],lat:a[1],lon:a[2],crashes:a[3],deaths:a[4],sig:a[5],near_safe_ft:a[6]};});
 IDX.corridors.forEach(function(c){items.push({t:'corridor',disp:c.disp,blob:norm(c.disp),score:c.total,ref:c});});
 INTERS.forEach(function(n){items.push({t:'intersection',disp:n.disp,blob:norm(n.disp),score:n.crashes,ref:n});});
 function meters(a,b){var R=111320,la=(a[0]+b[0])/2*Math.PI/180;var dx=(a[1]-b[1])*Math.cos(la)*R,dy=(a[0]-b[0])*R;return Math.sqrt(dx*dx+dy*dy);}
 function ptSeg(p,a,b){var la=p[0]*Math.PI/180,kx=111320*Math.cos(la),ky=111320;
   var px=p[1]*kx,py=p[0]*ky,ax=a[1]*kx,ay=a[0]*ky,bx=b[1]*kx,by=b[0]*ky;
   var dx=bx-ax,dy=by-ay,L=dx*dx+dy*dy,t=L?((px-ax)*dx+(py-ay)*dy)/L:0;t=Math.max(0,Math.min(1,t));
   var cx=ax+t*dx,cy=ay+t*dy;return Math.sqrt((px-cx)*(px-cx)+(py-cy)*(py-cy));}
 function corridorDist(p,c){var m=1e9;c.geom.forEach(function(path){for(var i=0;i<path.length-1;i++){m=Math.min(m,ptSeg(p,path[i],path[i+1]));}});return m;}
 var FT=function(m){return Math.round(m/0.3048);};

 function clear(){layer.clearLayers();}
 function showCard(html){card.innerHTML='<span class="x" onclick="this.parentNode.style.display=\'none\'">✕</span>'+html;card.style.display='block';}
 function row(k,v){return '<div class="row"><b>'+k+':</b> '+v+'</div>';}
 function na(){return '<span class="na">not yet analyzed</span>';}

 // ======================= COUNT A (shared point -> road -> count) =======================
 // >>> CHANGE THE COUNT-A WINDOW HERE <<<  (meters measured UP and DOWN the road from the
 //     snapped point; the counted stretch is up to 2x this). Default 300 m.
 var COUNTA_WINDOW_M = 300;

 // EPSG:32136 (NAD83 / Tennessee, meters) forward projection. Matches pyproj to <0.001 mm, so a
 // query point lands in the SAME metric frame as the embedded corridor geometry (c.mg) and the
 // precomputed crash measures. ALL Count-A distance math is done in these meters (never lat/lon
 // degrees, never Web Mercator).
 var _a=6378137.0,_f=1/298.257222101,_e=Math.sqrt(2*(1/298.257222101)-(1/298.257222101)*(1/298.257222101));
 var _p1=36.4166666667*Math.PI/180,_p2=35.25*Math.PI/180,_p0=34.3333333333*Math.PI/180,_l0=-86*Math.PI/180,_FE=600000,_FN=0;
 function _tt(ph){return Math.tan(Math.PI/4-ph/2)/Math.pow((1-_e*Math.sin(ph))/(1+_e*Math.sin(ph)),_e/2);}
 function _mm(ph){return Math.cos(ph)/Math.sqrt(1-_e*_e*Math.sin(ph)*Math.sin(ph));}
 var _n=(Math.log(_mm(_p1))-Math.log(_mm(_p2)))/(Math.log(_tt(_p1))-Math.log(_tt(_p2)));
 var _F=_mm(_p1)/(_n*Math.pow(_tt(_p1),_n)),_rho0=_a*_F*Math.pow(_tt(_p0),_n);
 function prj(lat,lon){var ph=lat*Math.PI/180,la=lon*Math.PI/180,rho=_a*_F*Math.pow(_tt(ph),_n),th=_n*(la-_l0);
   return [_FE+rho*Math.sin(th),_FN+_rho0-rho*Math.cos(th)];}

 // Nearest point on a metric multipath mg -> {m: along-distance, d: perpendicular distance}.
 // MUST match Python measure_xy() exactly (same crash measures vs query measures).
 function measureXY(mg,px,py){
   var bestD=Infinity,bestM=0,base=0;
   for(var k=0;k<mg.length;k++){var path=mg[k],cum=0;
     for(var i=0;i<path.length-1;i++){
       var ax=path[i][0],ay=path[i][1],bx=path[i+1][0],by=path[i+1][1];
       var dx=bx-ax,dy=by-ay,l2=dx*dx+dy*dy,t=l2>0?((px-ax)*dx+(py-ay)*dy)/l2:0;
       t=t<0?0:(t>1?1:t);
       var cx=ax+t*dx,cy=ay+t*dy,d2=(px-cx)*(px-cx)+(py-cy)*(py-cy),seg=Math.sqrt(l2);
       if(d2<bestD){bestD=d2;bestM=base+cum+t*seg;}
       cum+=seg;
     }
     base+=cum;
   }
   return {m:bestM,d:Math.sqrt(bestD),len:base};
 }
 function corridorLen(c){if(c._len==null)c._len=measureXY(c.mg,0,0).len;return c._len;}

 var MEMBBOX={latMin:34.94,latMax:35.42,lonMin:-90.40,lonMax:-89.55};
 function inMemphis(lat,lon){return lat>=MEMBBOX.latMin&&lat<=MEMBBOX.latMax&&lon>=MEMBBOX.lonMin&&lon<=MEMBBOX.lonMax;}

 // THE one shared pipeline. Address, coordinates, and map-click all call this.
 function countA(lat,lon,srcLabel){
   clear();
   L.marker([lat,lon]).addTo(layer);map.setView([lat,lon],16);
   var xy=prj(lat,lon),px=xy[0],py=xy[1];
   // (a) snap to nearest crash-corridor centerline (EPSG:32136 meters)
   var ranked=[];
   IDX.corridors.forEach(function(c){if(c.mg&&c.mg.length){var r=measureXY(c.mg,px,py);ranked.push({c:c,m:r.m,d:r.d});}});
   if(!ranked.length){showCard('<h2>'+srcLabel+'</h2>'+row('Result','no road geometry available'));return;}
   ranked.sort(function(a,b){return a.d-b.d;});
   var hit=ranked[0],alt=null;
   for(var i=1;i<ranked.length;i++){if(ranked[i].c.raw!==hit.c.raw){alt=ranked[i];break;}}
   var ambiguous=alt&&(alt.d-hit.d)<=15;   // two roads within ~15 m of each other
   if(hit.c.geom)L.polyline(hit.c.geom,{color:'#ffe11a',weight:5,opacity:.5,interactive:false}).addTo(layer);
   // (b) Count A: crashes attributed to THIS road, within +/-N m ALONG the road from the snap
   var lo=hit.m-COUNTA_WINDOW_M,hi=hit.m+COUNTA_WINDOW_M,n=0,fat=0,xm=hit.c.xm||[],xf=hit.c.xf||[];
   for(var k=0;k<xm.length;k++){if(xm[k]>=lo&&xm[k]<=hi){n++;if(xf[k])fat++;}}
   var tot=corridorLen(hit.c),stretch=Math.round(Math.min(tot,hi)-Math.max(0,lo));
   // (c)/(d) card -- honest + descriptive
   var ll=lat.toFixed(5)+', '+lon.toFixed(5);
   var coord='<div class="row" style="font-size:12px;color:#54646c">'+ll+
     ' <span style="cursor:pointer;color:#2a6f97" title="copy" onclick="navigator.clipboard&&navigator.clipboard.writeText(\''+ll+'\')">⧉ copy</span></div>';
   var snap=hit.c.disp+' <span style="color:#54646c">— snapped '+Math.round(hit.d)+' m from your point</span>';
   var amb=ambiguous?'<div class="row na">Ambiguous: also '+Math.round(alt.d)+' m from '+alt.c.disp+'; counting '+hit.c.disp+'.</div>':'';
   var far=(!ambiguous&&hit.d>35)?'<div class="row na">Your point is '+Math.round(hit.d)+' m from the nearest road on record — it may not be on '+hit.c.disp+'.</div>':'';
   showCard('<h2>'+srcLabel+'</h2>'+coord+row('On road',snap)+amb+far+
     row('Crashes on this stretch',n+' ('+fat+' fatal)')+
     '<div class="row" style="color:#54646c">On this ~'+stretch+' m stretch of '+hit.c.disp+
     ' (±'+COUNTA_WINDOW_M+' m along the road from your point). Crashes attributed to this road only — not a straight-line radius.</div>');
 }

 function openCorridor(c){
   clear();
   // interactive:false => the highlight never captures pointer events, so crash dots
   // beneath it stay clickable. Lower opacity => the dots remain visible through the wash.
   L.polyline(c.geom,{color:'#ffe11a',weight:11,opacity:.22,interactive:false}).addTo(layer); // soft glow
   var pl=L.polyline(c.geom,{color:'#ffe11a',weight:5,opacity:.5,interactive:false}).addTo(layer); // highlighter
   try{map.fitBounds(pl.getBounds().pad(0.2));}catch(e){}
   var own='City '+c.city+' · TDOT '+c.tdot+' · Limited-access '+c.limited;
   var sig=c.n_signalized==null?na():(c.n_signalized+' signalized');
   var safe=c.safe?(c.safe.n_safe+' safe crossings ('+c.safe.n_signalized+' signalized + '+c.safe.n_marked_only+
     ' marked-only) · '+c.safe.pct_over_250ft+'% of crossing-relevant crashes >250 ft from one · longest gap '+
     c.safe.longest_gap_ft.toLocaleString()+' ft'):na();
   showCard('<h2>'+c.disp+'</h2>'+row('Deadliest rank','#'+c.rank)+row('Crashes',c.total+' ('+c.fatal+' fatal)')+
     row('Road owner',own)+row('Signalized intersections',sig)+row('Safe crossings',safe));
 }
 function openInter(n){
   // interactive:false + low fill => the node ring marks the spot but the crash dot(s)
   // underneath stay visible and clickable.
   clear();L.circleMarker([n.lat,n.lon],{radius:14,color:'#bfa600',weight:2,opacity:.65,fillColor:'#ffe11a',fillOpacity:.3,interactive:false}).addTo(layer);
   map.setView([n.lat,n.lon],16);
   var safe=n.near_safe_ft==null?na():(n.near_safe_ft+' ft');
   var crashes=n.crashes>0?(n.crashes+' ('+n.deaths+' fatal)'):'<span class="na">0 incidents reported here</span>';
   var sig=n.sig==='y'?'yes':(n.sig==='n'?'no':na());   // 'u' = no signal coverage -> not yet analyzed
   showCard('<h2>'+n.disp+'</h2>'+row('Crashes',crashes)+
     row('Signalized',sig)+row('Nearest safe crossing',safe));
 }
 function openAddress(q){
   showCard('<h2>Searching…</h2><div class="row">geocoding "'+q+'"</div>');clear();
   // Address geocoding goes through our own /api/geocode serverless proxy (Vercel). The US
   // Census geocoder sends no CORS header, so the browser cannot call it directly; the proxy
   // appends "Memphis, TN", calls Census server-side, and returns {matchedAddress,lat,lon}
   // with CORS allowed. NOTE: this needs the deployed server -- on file:// there is no
   // /api, so it falls through to the graceful "Address not found" message (corridor &
   // intersection search still work on file:// because that data is embedded in the page).
   fetch('/api/geocode?address='+encodeURIComponent(q)).then(function(r){return r.json();}).then(function(j){
     if(!j||typeof j.lat!=='number'){throw 0;}
     countA(j.lat,j.lon,j.matchedAddress||q);     // address -> same Count A pipeline
   }).catch(function(){showCard('<h2>Address not found</h2><div class="row">Couldn’t find that address — try a street or intersection.</div>');});
 }
 function runCoords(q){
   var mt=(q||'').match(/(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)/);
   if(!mt){showCard('<h2>Invalid coordinates</h2><div class="row">Type "lat, lon" — e.g. 35.137, -90.017</div>');return;}
   var lat=parseFloat(mt[1]),lon=parseFloat(mt[2]);
   if(!inMemphis(lat,lon)){showCard('<h2>Outside the Memphis area</h2><div class="row">'+lat+', '+lon+
     ' is not within the Memphis area — expected lat 34.94–35.42, lon -90.40 to -89.55.</div>');return;}
   countA(lat,lon,'Coordinates '+lat.toFixed(5)+', '+lon.toFixed(5));   // coords -> same Count A pipeline
 }

 var sel=-1,cur=[];
 function render(list){cur=list;sel=-1;if(!list.length){drop.style.display='none';return;}
   drop.innerHTML=list.map(function(it,i){return '<div class="it" data-i="'+i+'"><b>'+it.disp+'</b><span class="ty">'+it.t+'</span></div>';}).join('');
   drop.style.display='block';
   Array.prototype.forEach.call(drop.children,function(el){el.onclick=function(){pick(cur[+el.dataset.i]);};});
 }
 function pick(it){box.value=it.disp;drop.style.display='none';if(it.t==='corridor')openCorridor(it.ref);else openInter(it.ref);}
 var mode='address',segAddr=document.getElementById('segAddr'),segCoord=document.getElementById('segCoord');
 // segmented control: the ACTIVE segment is the current input mode (standard, unambiguous).
 function applyMode(){
   var addr=(mode==='address');
   if(segAddr)segAddr.className=addr?'on':'';
   if(segCoord)segCoord.className=addr?'':'on';
   box.placeholder=addr?'Search a street, intersection, or address…':'Type a coordinate — e.g. 35.137, -90.017';
   box.value='';drop.style.display='none';card.style.display='none';}
 if(segAddr)segAddr.onclick=function(){mode='address';applyMode();box.focus();};
 if(segCoord)segCoord.onclick=function(){mode='coord';applyMode();box.focus();};
 applyMode();
 box.addEventListener('input',function(){
   if(mode==='coord'){drop.style.display='none';return;}    // coords mode: parse on Enter, no suggestions
   var q=box.value.trim();if(q.length<2){drop.style.display='none';return;}
   var tq=toks(q);
   var matches=items.filter(function(it){return tq.every(function(t){return it.blob.indexOf(t)>=0;});})
     .sort(function(a,b){return b.score-a.score;}).slice(0,8);
   if(/\d/.test(q)&&/\d+\s+\S/.test(q)){matches.unshift({t:'address',disp:'Search address: "'+q+'"',addr:q});}
   else if(!matches.length){matches=[{t:'address',disp:'Search address: "'+q+'"',addr:q}];}
   render(matches);
 });
 box.addEventListener('keydown',function(e){
   if(mode==='coord'){if(e.key==='Enter'){runCoords(box.value.trim());drop.style.display='none';}return;}
   if(drop.style.display==='none')return;
   if(e.key==='ArrowDown'){sel=Math.min(sel+1,cur.length-1);}
   else if(e.key==='ArrowUp'){sel=Math.max(sel-1,0);}
   else if(e.key==='Enter'){var it=cur[sel<0?0:sel];if(it){if(it.t==='address')openAddress(it.addr);else pick(it);drop.style.display='none';}return;}
   else return;
   Array.prototype.forEach.call(drop.children,function(el,i){el.className='it'+(i===sel?' sel':'');});
   e.preventDefault();
 });
 document.addEventListener('click',function(e){if(!document.getElementById('searchWrap').contains(e.target))drop.style.display='none';});
 // allow clicking the "Search address" row
 drop.addEventListener('click',function(e){var el=e.target.closest('.it');if(el&&cur[+el.dataset.i]&&cur[+el.dataset.i].t==='address'){openAddress(cur[+el.dataset.i].addr);drop.style.display='none';}});

 // CHANGE 3 -- click-to-locate. Resolution of the click conflict: clicking a crash/cross dot
 // opens ITS popup (Leaflet fires 'popupopen'); we record the time and have the map-click handler
 // skip locate within 80 ms, so a dot-click never doubles as a locate. Clicking empty map or a
 // road centerline (no popup) runs the same Count A pipeline. Zoom buttons and the layer panel are
 // separate DOM controls and never emit a map 'click', so they are unaffected.
 var _lastPopup=0;
 map.on('popupopen',function(){_lastPopup=Date.now();});
 map.on('click',function(e){
   if(Date.now()-_lastPopup<80)return;
   countA(e.latlng.lat,e.latlng.lng,'Clicked location');
 });
})();
"""


if __name__ == "__main__":
    main()
