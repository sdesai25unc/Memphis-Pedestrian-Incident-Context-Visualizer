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
from shapely import STRtree
from shapely.geometry import Point
from shapely.ops import linemerge

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
# Owner code per road segment, indexing the map's COL=[city,tdot,lim] color array (reused, no new colors).
CAT_CODE = {"City": 0, "TDOT": 1, "Limited": 2}


def owner_code(ownership):
    return CAT_CODE.get(CAT3.get(str(ownership)), 0)


# City of Memphis sidewalk inventory (reprojected to EPSG:32136). We flag, per road sub-segment,
# whether a sidewalk line runs within SIDEWALK_T metres of it. 20 m is the diagnosed "knee": sidewalks
# sit ~7 m (median) to ~12 m (p90) off the centerline, so 20 m catches near- AND far-side adjacent
# sidewalks while staying well under the ~60 m block spacing (no parallel-street false positives).
SIDEWALKS = PROC / "memphis_sidewalks_32136.geojson"
SIDEWALK_T = 20.0

# Generic catch-all street names excluded ONLY from the nearest-corridor snap (Change 2). They are
# real attributions for crashes (counts unchanged) but worthless as a "nearest road" because they are
# hundreds of disconnected segments citywide. Derived from the data: the only such names among the 529
# crash corridors are "ALLEY" and "PRIVATE DR".
GENERIC_NAMES = {"ALLEY", "PRIVATE DR"}
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


def lines_of(geom):
    if geom is None or geom.is_empty:
        return []
    return list(geom.geoms) if geom.geom_type == "MultiLineString" else [geom]


def measure_line(line, px, py):
    """Nearest point on ONE spatially-ordered component line=[[x,y],...] to (px,py).
    Returns (along_distance_m, perpendicular_distance_m, nearest_subsegment_index, total_length_m).
    MUST stay identical in logic to the JS measureLine() (query vs crash measures must match)."""
    best_d = float("inf")
    best_m = 0.0
    best_si = 0
    cum = 0.0
    for i in range(len(line) - 1):
        ax, ay = line[i]
        bx, by = line[i + 1]
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
            best_m = cum + t * seg
            best_si = i
        cum += seg
    return best_m, best_d ** 0.5, best_si, cum


TOUCH_M = 1.0    # components whose endpoints touch within this are ONE road (branch stubs merged)
GAP_M = 15.0     # inter-cluster gap beyond this is a genuine "disconnected" break (Vance rail, etc.)


def _clen(line):
    return sum(((line[i + 1][0] - line[i][0]) ** 2 + (line[i + 1][1] - line[i][1]) ** 2) ** 0.5
               for i in range(len(line) - 1))


def cluster_components(mg):
    """Union-find components into CLUSTERS by endpoint-touch <= TOUCH_M (Fix 1). Returns
    (cl: cluster id per component, real_gap: 1 if any inter-cluster gap > GAP_M else 0)."""
    n = len(mg)
    ends = [(m[0], m[-1]) for m in mg]
    par = list(range(n))

    def find(i):
        while par[i] != i:
            par[i] = par[par[i]]; i = par[i]
        return i

    def dist(a, b):
        return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5

    for i in range(n):
        for j in range(i + 1, n):
            if min(dist(ends[i][a], ends[j][b]) for a in (0, 1) for b in (0, 1)) <= TOUCH_M:
                par[find(i)] = find(j)
    roots = {}
    cl = [0] * n
    for i in range(n):
        r = find(i)
        cl[i] = roots.setdefault(r, len(roots))
    # real gap: min endpoint distance between DIFFERENT clusters
    real_gap = 0
    if len(roots) > 1:
        best = float("inf")
        for i in range(n):
            for j in range(i + 1, n):
                if cl[i] != cl[j]:
                    best = min(best, min(dist(ends[i][a], ends[j][b]) for a in (0, 1) for b in (0, 1)))
        real_gap = 1 if best > GAP_M else 0
    return cl, real_gap


def _net_dist(mg, cl, ci, m):
    """Dijkstra network distances from a click on component ci at measure m, over its cluster.
    Returns (dist_by_node, en, length, comps) mirroring the JS. Node ids match endpoints <= TOUCH_M."""
    import heapq
    comps = [i for i in range(len(mg)) if cl[i] == cl[ci]]
    nodes = []

    def node_id(pt):
        for k, (nx, ny) in enumerate(nodes):
            if ((nx - pt[0]) ** 2 + (ny - pt[1]) ** 2) ** 0.5 <= TOUCH_M:
                return k
        nodes.append(pt); return len(nodes) - 1

    en, length, adj = {}, {}, {}
    for cj in comps:
        a, b = node_id(mg[cj][0]), node_id(mg[cj][-1])
        en[cj] = (a, b); length[cj] = _clen(mg[cj])
        adj.setdefault(a, []).append((b, length[cj]))
        adj.setdefault(b, []).append((a, length[cj]))
    a0, b0 = en[ci]
    dist = {a0: m, b0: length[ci] - m}
    pq = [(dist[a0], a0), (dist[b0], b0)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist.get(u, float("inf")):
            continue
        for v, w in adj.get(u, []):
            if d + w < dist.get(v, float("inf")):
                dist[v] = d + w
                heapq.heappush(pq, (d + w, v))
    return dist, en, length, comps


def net_count(c, ci, m, window):
    """Crashes on ci's CLUSTER within `window` NETWORK metres of the click (Fix 1: folds stubs in)."""
    cl = c["cl"]
    dist, en, length, comps = _net_dist(c["mg"], cl, ci, m)
    n = fat = 0
    for k in range(len(c["xm"])):
        cj = c["xc"][k]
        if cl[cj] != cl[ci]:
            continue
        mj = c["xm"][k]
        if cj == ci:
            nd = abs(mj - m)
        else:
            a, b = en[cj]
            nd = min(dist.get(a, 1e18) + mj, dist.get(b, 1e18) + (length[cj] - mj))
        if nd <= window:
            n += 1
            fat += c["xf"][k]
    return n, fat, comps


def count_a_demo(corridors, lat, lon, window=300):
    """Server-side mirror of the JS countA() -- proves the embedded data yields the same counts.
    Snaps (lat,lon) to the nearest crash-corridor COMPONENT in EPSG:32136 and counts crashes on
    that connected component within +/-window metres (Option A: no cross-gap leakage)."""
    from pyproj import Transformer
    px, py = Transformer.from_crs(CRS_GEO, CRS_M, always_xy=True).transform(lon, lat)
    ranked = []
    for c in corridors:
        if c.get("g"):                       # skip generic catch-all names in the snap (Change 2)
            continue
        for ci, line in enumerate(c["mg"]):
            mm, dd, si, _ = measure_line(line, px, py)
            ranked.append((dd, mm, c, ci, si))
    ranked.sort(key=lambda t: t[0])
    d, m, c, ci, si = ranked[0]
    n, fat, _ = net_count(c, ci, m, window)      # network distance over the connected cluster (Fix 1)
    alt = next((t for t in ranked[1:] if t[2]["raw"] != c["raw"]), None)
    owners = sorted({o for row in (c.get("co") or []) for o in row})
    lbl = {0: "City of Memphis", 1: "TDOT / State", 2: "Limited-access (TDOT)"}
    pt_owner = c["co"][ci][si] if c.get("co") and ci < len(c["co"]) and si < len(c["co"][ci]) else None
    ncl = (max(c["cl"]) + 1) if c.get("cl") else 1
    clen_here = sum(_clen(c["mg"][i]) for i in range(len(c["mg"])) if c["cl"][i] == c["cl"][ci])
    return {"road": c["disp"], "snap_m": d, "n": n, "fat": fat, "comp": ci, "ncomp": len(c["mg"]),
            "ncl": ncl, "cluster_len": round(clen_here),
            "alt": (alt[2]["disp"] if alt else None), "alt_m": (alt[0] if alt else None),
            "corridor_total": c["total"], "corridor_fatal": c["fatal"],
            "pt_owner": (lbl.get(pt_owner) if pt_owner is not None else None),
            "varies": len(owners) > 1}


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
    cf = f[["Street_Name", "Latitude", "Longitude", "InjuryClass", "CollisionDate"]].dropna(
        subset=["Latitude", "Longitude"]).copy()
    # CollisionDate is M/D/YYYY in the source -> normalize to ISO 'YYYY-MM-DD' for clean JS parsing
    cf["_iso"] = pd.to_datetime(cf["CollisionDate"], errors="coerce").dt.strftime("%Y-%m-%d")
    cg = gpd.GeoDataFrame(cf, geometry=gpd.points_from_xy(cf["Longitude"], cf["Latitude"]),
                          crs=CRS_GEO).to_crs(CRS_M)
    crashpts = {}
    for nm, grp in cg.groupby("Street_Name"):
        crashpts[nm] = [(geom.x, geom.y, inj == FATAL, (iso if isinstance(iso, str) else None))
                        for geom, inj, iso in zip(grp.geometry, grp["InjuryClass"], grp["_iso"])]

    # dataset date coverage (Change 4) -- windows are measured from dmax, NOT today (reporting-lag honesty)
    dser = pd.to_datetime(f["CollisionDate"], errors="coerce").dropna()
    DMIN = dser.min().strftime("%Y-%m-%d")
    DMAX = dser.max().strftime("%Y-%m-%d")

    # Option A: stitch each corridor's rulebook segments into spatially-ordered CONNECTED COMPONENTS
    # (shapely linemerge). mg = list of components (each a single ordered metric polyline). A point
    # snaps to ONE component and the window/count/bars are confined to it -> true along-road semantics,
    # no cross-gap leakage. A road broken by a rail yard etc. becomes separate components by design.
    corridors = []
    n_no_geom = 0
    comp_hist = {}      # name -> #components, for reporting
    for name in agg.index:
        r = agg.loc[name]
        segs = rb[rb["Street_Name"] == name]
        mg = []         # list of components; each = [[x,y],...] EPSG:32136 metric int, spatial order
        co = []         # per component: owner code per sub-segment (City-vs-State view + point owner)
        orig_lines, orig_oc = [], []
        for gm, own in zip(segs.geometry, segs["Ownership"]):
            for ln in lines_of(gm):
                orig_lines.append(ln)
                orig_oc.append(owner_code(own))
        if orig_lines:
            comps = lines_of(linemerge(orig_lines))
            tree = STRtree(orig_lines)               # recover owner along each merged component
            for comp in comps:
                cs = list(comp.simplify(SIMPLIFY_MG_M, preserve_topology=False).coords)
                if len(cs) < 2:
                    continue
                mg.append([[int(round(x)), int(round(y))] for x, y in cs])
                row = []
                for i in range(len(cs) - 1):
                    mx = (cs[i][0] + cs[i + 1][0]) / 2.0
                    my = (cs[i][1] + cs[i + 1][1]) / 2.0
                    row.append(orig_oc[int(tree.nearest(Point(mx, my)))])
                co.append(row)
        comp_hist[name] = len(mg)
        # each crash -> nearest COMPONENT + along-measure within that component
        xc, xm, xf, xd = [], [], [], []
        if mg:
            for (cx, cy, fa, dt) in crashpts.get(name, []):
                bi, bd, bm = 0, float("inf"), 0.0
                for ci, line in enumerate(mg):
                    mm, dd, _, _ = measure_line(line, cx, cy)
                    if dd < bd:
                        bd, bi, bm = dd, ci, mm
                xc.append(bi)
                xm.append(int(round(bm)))
                xf.append(1 if fa else 0)
                xd.append(dt)
        else:
            n_no_geom += 1
        cl, real_gap = cluster_components(mg) if mg else ([], 0)
        rec = {
            "disp": titlecase_street(name), "raw": name,
            "total": int(r.total), "fatal": int(r.fatal),
            "city": int(r.city), "tdot": int(r.tdot), "limited": int(r.limited),
            "rank": int(rank_map[name]),
            "n_signalized": (sig_count.get(name, 0) if name in covered else None),
            "safe": (union_safe if name == "UNION AVE" else None),
            "mg": mg, "co": co, "cl": cl, "rg": real_gap, "xc": xc, "xm": xm, "xf": xf, "xd": xd,
        }
        if name in GENERIC_NAMES:
            rec["g"] = 1     # excluded from the nearest-corridor snap (Change 2)
        corridors.append(rec)
    if n_no_geom:
        print(f"  NOTE: {n_no_geom} crash corridors have no rulebook geometry (excluded from Count A snap)")
    print("  components: " + ", ".join(f"{k.title()}={comp_hist.get(k, 0)}"
          for k in ["CENTRAL AVE", "UNION AVE", "POPLAR AVE", "VANCE AVE"]))

    # ---- City sidewalk presence per road sub-segment (deterministic; parallel to `co`) ----
    # For each mg sub-segment midpoint, is a city-inventory sidewalk within SIDEWALK_T metres?
    for rec in corridors:
        rec["sw"] = [[0] * max(0, len(comp) - 1) for comp in rec["mg"]]
    if SIDEWALKS.exists():
        sw_gdf = gpd.read_file(SIDEWALKS).to_crs(CRS_M)
        tree = STRtree(sw_gdf.geometry.values)
        mids, loc = [], []
        for corridor_i, rec in enumerate(corridors):
            for comp_i, comp in enumerate(rec["mg"]):
                for si in range(len(comp) - 1):
                    mids.append(Point((comp[si][0] + comp[si + 1][0]) / 2.0,
                                      (comp[si][1] + comp[si + 1][1]) / 2.0))
                    loc.append((corridor_i, comp_i, si))
        n_with = 0
        if mids:
            indices, dists = tree.query_nearest(mids, all_matches=False, return_distance=True)
            for k in range(len(dists)):
                if dists[k] <= SIDEWALK_T:
                    ci, cj, si = loc[indices[0][k]]
                    corridors[ci]["sw"][cj][si] = 1
                    n_with += 1
        _swpct = round(100.0 * n_with / len(mids), 1) if mids else 0.0
        print(f"  sidewalks: {len(sw_gdf):,} city lines | {n_with:,}/{len(mids):,} road sub-segments "
              f"have a sidewalk within {SIDEWALK_T:.0f} m ({_swpct}%)")
    else:
        print(f"  sidewalks: {SIDEWALKS.name} not found -> sidewalk status will read 'no data' "
              f"(run the unzip/convert step first)")

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
                    "n_intersections_with_crash": with_crash, "total_crashes": int(f.shape[0]),
                    "dmin": DMIN, "dmax": DMAX}}
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
              f"(snap {a['snap_m']:.0f} m) | Owner: {a['pt_owner']} | {a['n']} crashes / {a['fat']} fatal in ±300 m")
    except Exception as e:
        print(f"  [address]     (Census lookup skipped: {e})")
    # (2) COORDINATES mode: Union & S Cleveland point
    c2 = count_a_demo(cors, 35.13684, -90.01667)
    print(f"  [coordinates] 35.13684,-90.01667 -> on {c2['road']} (snap {c2['snap_m']:.0f} m) | "
          f"Owner: {c2['pt_owner']} | {c2['n']} crashes / {c2['fat']} fatal in ±300 m"
          + (f"  [ambiguous w/ {c2['alt']} @ {c2['alt_m']:.0f} m]" if c2['alt_m'] is not None and (c2['alt_m']-c2['snap_m'])<=15 else ""))
    # (3) CLICK mode: a different Union point (midtown, near S Cox)
    c3 = count_a_demo(cors, 35.13353, -89.98368)
    print(f"  [click]       35.13353,-89.98368 -> on {c3['road']} (snap {c3['snap_m']:.0f} m) | "
          f"Owner: {c3['pt_owner']} | {c3['n']} crashes / {c3['fat']} fatal in ±300 m")
    print(f"  (each snaps to ONE component of its corridor; e.g. click -> component {c3['comp']+1}/{c3['ncomp']})")
    # (CHANGE 1) owner card -- (a) single-owner point and (b) a varies-by-segment corridor (Poplar)
    pop = next((c for c in cors if c["raw"] == "POPLAR AVE"), None)
    if pop:
        pset = sorted({o for row in (pop.get("co") or []) for o in row})
        lbl = {0: "City", 1: "TDOT/State", 2: "Limited"}
        print(f"  [owner: point]   single point above -> Owner: {c3['pt_owner']} (one sub-segment, one owner)")
        print(f"  [owner: corridor] Poplar Avenue -> road ownership = "
              f"{'varies by segment' if len(pset) > 1 else lbl.get(pset[0])} "
              f"(segments: {', '.join(lbl.get(o) for o in pset)}) -> 'See City vs State segments'")
    cpar = count_a_demo(cors, 35.13839, -89.99494)
    print(f"  [parallel chk] 35.13839,-89.99494 -> on {cpar['road']} (snap {cpar['snap_m']:.0f} m): "
          f"{cpar['n']}/{cpar['fat']} — nearer than Union, so Union's crashes are NOT grabbed")
    # reconciliation: whole-corridor total (sum of ALL crashes on the road, every component) = card
    print(f"  reconcile: whole-Union (all components) = {len(u['xd'])}/{sum(u['xf'])} "
          f"(Union card = {u['total']}/{u['fatal']}; "
          f"{'MATCH' if (len(u['xd']), sum(u['xf'])) == (u['total'], u['fatal']) else 'MISMATCH'})")

    # ---- FIX 1 (branch-stub merge) + divergence re-check (must stay 0 for Union/Poplar) ----
    import math as _math
    from pyproj import Transformer as _TF
    _Tinv = _TF.from_crs(CRS_M, CRS_GEO, always_xy=True)

    def _pt_at(line, target):
        cum = 0.0
        for i in range(len(line) - 1):
            ax, ay = line[i]; bx, by = line[i + 1]; seg = _math.hypot(bx - ax, by - ay)
            if cum + seg >= target or i == len(line) - 2:
                tt = max(0.0, min(1.0, 0.0 if seg == 0 else (target - cum) / seg))
                return (ax + tt * (bx - ax), ay + tt * (by - ay))
            cum += seg
        return tuple(line[-1])

    def _divcheck(c):
        pos = [_pt_at(c["mg"][c["xc"][k]], c["xm"][k]) for k in range(len(c["xm"]))]
        cl = c["cl"]; samples = diverge = 0; max_crash = 0.0
        for ci, line in enumerate(c["mg"]):
            tot = _clen(line); s = 60.0
            while s < tot:
                click = _pt_at(line, s)
                wc, _, _ = net_count(c, ci, s, 300)     # NETWORK window over the cluster (Fix 1)
                sc = 0
                for k in range(len(c["xm"])):
                    if cl[c["xc"][k]] == cl[ci] and _math.dist(click, pos[k]) <= 300:
                        sc += 1; max_crash = max(max_crash, _math.dist(click, pos[k]))
                samples += 1
                if wc != sc:
                    diverge += 1
                s += 120.0
        return samples, diverge, max_crash

    # corridor-wide Fix-1 summary
    branch = []
    parked_total = 0
    for c in cors:
        if not c["mg"] or c.get("g"):
            continue
        cl = c["cl"]; ncl = max(cl) + 1
        clusters = {}
        for i, g in enumerate(cl):
            clusters.setdefault(g, []).append(i)
        merged = [g for g in clusters.values() if len(g) >= 2]
        if merged:
            parked = 0
            for g in merged:
                primary = max(g, key=lambda i: _clen(c["mg"][i]))
                parked += sum(c["xc"].count(i) for i in g if i != primary)
            parked_total += parked
            branch.append((c["raw"], len(c["mg"]), ncl, parked))
    print("\n=== FIX 1 (branch-stub merge) — corridor-wide ===")
    print(f"  corridors with same-name branch stubs merged into one road: {len(branch)} "
          f"| crashes folded from a stub back into main-line clicks: {parked_total}")
    for raw, nc, ncl, pk in sorted(branch, key=lambda t: -t[3])[:6]:
        print(f"    {raw:<22} {nc} components -> {ncl} cluster(s), folded-in crashes = {pk}")

    print("\n=== divergence re-check (network window vs straight-line-on-cluster; must be ~0) ===")
    for nm in ["UNION AVE", "POPLAR AVE", "S PARKWAY E"]:
        cc = next(x for x in cors if x["raw"] == nm)
        sm, dv, mc = _divcheck(cc)
        print(f"  {cc['disp']}: {len(cc['mg'])} comps -> {max(cc['cl'])+1} clusters | sampled {sm} | "
              f"divergence {dv}/{sm} | max counted-crash straight-line {mc:.0f} m")
    print("  (before ALL fixes: Union diverged 30/64, Poplar 63/272; Option A took them to 0; Fix 1 keeps 0)")

    # Airways (branch -> ONE road) and Vance (real gaps -> stays split)
    def _mid_latlon(c):
        line = max(c["mg"], key=_clen); p = _pt_at(line, _clen(line) / 2)
        lon, lat = _Tinv.transform(p[0], p[1]); return lat, lon
    print("\n=== Airways (branch merge) vs Vance (real gaps) ===")
    air = next(x for x in cors if x["raw"] == "AIRWAYS BLVD")
    alat, alon = _mid_latlon(air)
    ar = count_a_demo(cors, alat, alon)
    print(f"  Airways mid-boulevard: {ar['ncomp']} components -> {ar['ncl']} cluster(s) "
          f"(=> {'NO disconnected-pieces note' if ar['ncl'] == 1 else 'STILL SPLIT'}); "
          f"±300 count on the connected road = {ar['n']}/{ar['fat']}; cluster length {ar['cluster_len']} m")
    van = next(x for x in cors if x["raw"] == "VANCE AVE")
    print(f"  Vance Ave: {len(van['mg'])} components -> {max(van['cl'])+1} clusters, real_gap flag={van['rg']} "
          f"(=> stays split; each click scoped to its section, wording shows section length)")

    # ---- CHANGE 4: data coverage + per-corridor date-window table (Union, collapsed + expanded) ----
    import pandas as _pd
    meta = idx["meta"]
    print(f"\n=== DATA COVERAGE (Change 4) ===")
    print(f"  CollisionDate min..max = {meta['dmin']} .. {meta['dmax']}  "
          f"(windows are measured from {meta['dmax']}, NOT today)")
    u = next(c for c in idx["corridors"] if c["raw"] == "UNION AVE")
    xd, xf = u["xd"], u["xf"]
    dmax = _pd.Timestamp(meta["dmax"])
    print(f"  Union Ave time breakdown:")
    print(f"    [collapsed] Since data start: {len(xd)} incidents · {sum(xf)} deaths  "
          f"(deadliest card = {u['total']}/{u['fatal']}; "
          f"{'RECONCILES' if (len(xd), sum(xf)) == (u['total'], u['fatal']) else 'MISMATCH'})")
    for label, months in [("Last 12 months", 12), ("Last 6 months", 6), ("Last 3 months", 3), ("Last 1 month", 1)]:
        cut = dmax - _pd.DateOffset(months=months)
        inc = sum(1 for d in xd if d and _pd.Timestamp(d) >= cut)
        dth = sum(xf[i] for i, d in enumerate(xd) if d and _pd.Timestamp(d) >= cut)
        print(f"    [expanded] {label:<16} {inc:>3} incidents · {dth} deaths  (since {cut.date()})")

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
#searchCard .cstats{margin-top:7px;border-top:1px solid #eef1f3;padding-top:6px}
#searchCard #twLink{color:#2a6f97;text-decoration:none;margin-left:4px;cursor:pointer;font-weight:600}
#searchCard table.tw{width:100%;border-collapse:collapse;margin:6px 0 3px}
#searchCard table.tw th{text-align:left;font-size:11px;color:#54646c;font-weight:700;border-bottom:1px solid #d9e0e4;padding:3px 6px}
#searchCard table.tw td{font-size:12px;padding:3px 6px;border-bottom:1px solid #f0f3f5}
#searchCard table.tw .n{text-align:right;font-variant-numeric:tabular-nums;width:78px}
#searchCard .twnote{font-size:10.5px;color:#9aa7ad;font-style:italic;margin-top:3px}
#searchCard .twcov{font-size:11px;color:#54646c;margin-top:2px}
#searchCard .disclaim{font-size:10.5px;color:#9aa7ad;line-height:1.45;margin-top:8px;border-top:1px solid #eef1f3;padding-top:6px}
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

 function clear(){layer.clearLayers();}
 function showCard(html){card.innerHTML='<span class="x" onclick="this.parentNode.style.display=\'none\'">✕</span>'+html;card.style.display='block';}
 function row(k,v){return '<div class="row"><b>'+k+':</b> '+v+'</div>';}
 function na(){return '<span class="na">not yet analyzed</span>';}

 // Change 1 -- always-visible attribution disclaimer on the result card (text only, no logic change).
 var DISCLAIMER='<div class="disclaim">Incidents are matched to roads by the nearest point to the true '+
   'road centerline. Near intersections, a point may attribute to a cross street rather than the main '+
   'road. Points on roads with no recorded pedestrian crashes snap to the nearest road that has them — '+
   'check the listed road name and snap distance on each result.</div>';

 // Change 4 -- collapsible, date-windowed per-corridor stats table (whole road; reconciles to the
 // deadliest card). Windows are measured from the DATA'S most recent date (IDX.meta.dmax), not today.
 var MON=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
 function fmtMon(d){if(!d)return '?';var p=d.split('-');return MON[(+p[1])-1]+' '+p[0];}
 function statsTable(c){
   var xd=c.xd||[],xf=c.xf||[],total=xd.length,deaths=0,j;
   for(j=0;j<xf.length;j++)if(xf[j])deaths++;
   var dmax=IDX.meta.dmax,dmin=IDX.meta.dmin;
   function cut(m){var d=new Date(dmax+'T00:00:00');d.setMonth(d.getMonth()-m);return d;}
   var W=[['Since data start',null],['Last 12 months',12],['Last 6 months',6],['Last 3 months',3],['Last 1 month',1]];
   var body=W.map(function(w){
     var inc=0,dth=0,co=(w[1]==null?null:cut(w[1]));
     for(var i=0;i<xd.length;i++){
       var ok=(w[1]==null);
       if(!ok&&xd[i]){ok=(new Date(xd[i]+'T00:00:00'))>=co;}
       if(ok){inc++;if(xf[i])dth++;}
     }
     return '<tr><td>'+w[0]+'</td><td class="n">'+inc+'</td><td class="n">'+dth+'</td></tr>';
   }).join('');
   return '<div class="cstats"><div class="row"><b>Since data start:</b> '+total+' incidents · '+deaths+
     ' deaths <a id="twLink" onclick="return __toggleTW()">▸ Show time breakdown</a></div>'+
     '<div id="tw" style="display:none">'+
       '<table class="tw"><thead><tr><th>Window</th><th class="n">Incidents</th><th class="n">Deaths</th></tr></thead>'+
       '<tbody>'+body+'</tbody></table>'+
       '<div class="twnote">Recent windows may undercount — official crash data is finalized with a reporting lag.</div>'+
       '<div class="twcov">Data coverage: '+fmtMon(dmin)+' – '+fmtMon(dmax)+'</div>'+
     '</div></div>';
 }
 window.__toggleTW=function(){
   var tw=document.getElementById('tw'),a=document.getElementById('twLink');if(!tw)return false;
   var open=tw.style.display==='none';tw.style.display=open?'block':'none';
   if(a)a.innerHTML=open?'▾ Hide time breakdown':'▸ Show time breakdown';return false;};

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

 // Nearest point on ONE spatially-ordered component -> {m: along-dist, d: perpendicular, si, len}.
 // MUST match Python measure_line() exactly (query measures vs crash measures must agree).
 function measureLine(line,px,py){
   var bestD=Infinity,bestM=0,bestSi=0,cum=0;
   for(var i=0;i<line.length-1;i++){
     var ax=line[i][0],ay=line[i][1],bx=line[i+1][0],by=line[i+1][1];
     var dx=bx-ax,dy=by-ay,l2=dx*dx+dy*dy,t=l2>0?((px-ax)*dx+(py-ay)*dy)/l2:0;
     t=t<0?0:(t>1?1:t);
     var cx=ax+t*dx,cy=ay+t*dy,d2=(px-cx)*(px-cx)+(py-cy)*(py-cy),seg=Math.sqrt(l2);
     if(d2<bestD){bestD=d2;bestM=cum+t*seg;bestSi=i;}
     cum+=seg;
   }
   return {m:bestM,d:Math.sqrt(bestD),si:bestSi,len:cum};
 }
 function compLen(line){var c=0;for(var i=0;i<line.length-1;i++)c+=Math.hypot(line[i+1][0]-line[i][0],line[i+1][1]-line[i][1]);return c;}
 // metric components -> lat/lon polylines (inverse EPSG:32136), cached per corridor for highlights.
 function llOf(c){if(!c._ll){c._ll=(c.mg||[]).map(function(line){return line.map(function(p){return iprj(p[0],p[1]);});});}return c._ll;}

 var MEMBBOX={latMin:34.94,latMax:35.42,lonMin:-90.40,lonMax:-89.55};
 function inMemphis(lat,lon){return lat>=MEMBBOX.latMin&&lat<=MEMBBOX.latMax&&lon>=MEMBBOX.lonMin&&lon<=MEMBBOX.lonMax;}

 // Inverse EPSG:32136 (metres -> lat/lon). Lets us place the +/-window markers at an exact
 // along-corridor distance computed in metres, then draw them on the lat/lon map.
 function iprj(x,y){
   var E=x-_FE,N=y-_FN,rho=Math.sqrt(E*E+(_rho0-N)*(_rho0-N));if(_n<0)rho=-rho;
   var theta=Math.atan2(E,_rho0-N),lon=theta/_n+_l0,t=Math.pow(rho/(_a*_F),1/_n),phi=Math.PI/2-2*Math.atan(t);
   for(var i=0;i<8;i++){var es=_e*Math.sin(phi);phi=Math.PI/2-2*Math.atan(t*Math.pow((1-es)/(1+es),_e/2));}
   return [phi*180/Math.PI,lon*180/Math.PI];
 }
 // metric point + road-perpendicular unit vector at along-distance target on ONE component line
 function tickAt(line,target){
   var cum=0;
   for(var i=0;i<line.length-1;i++){
     var ax=line[i][0],ay=line[i][1],bx=line[i+1][0],by=line[i+1][1],seg=Math.hypot(bx-ax,by-ay);
     if(cum+seg>=target||i===line.length-2){
       var tt=seg>0?(target-cum)/seg:0;tt=tt<0?0:(tt>1?1:tt);
       var ux=seg>0?(bx-ax)/seg:1,uy=seg>0?(by-ay)/seg:0;
       return {x:ax+tt*(bx-ax),y:ay+tt*(by-ay),perp:[-uy,ux]};
     }
     cum+=seg;
   }
   return null;
 }
 // a short perpendicular cross-bar marking one end of the +/-window (clamped within the component)
 function drawWindowTick(line,target,color){
   var H=22,t=tickAt(line,target);if(!t)return;
   var a=iprj(t.x+t.perp[0]*H,t.y+t.perp[1]*H),b=iprj(t.x-t.perp[0]*H,t.y-t.perp[1]*H);
   L.polyline([a,b],{color:color,weight:4,opacity:.95,interactive:false}).addTo(layer);
 }

 // ----- road ownership (Change 1). Reuse the map's City/TDOT/Limited colors -- no new green/red. -----
 var OWNCOL=(typeof COL!=='undefined'&&COL)?COL:['#1b9e8f','#d6453d','#3a3a44'];
 function ownerLabel(code){return code===0?'City of Memphis':code===1?'TDOT / State':code===2?'Limited-access (TDOT)':'unknown';}
 function allOwners(c){var s={};(c.co||[]).forEach(function(row){row.forEach(function(o){s[o]=1;});});return Object.keys(s).map(Number);}
 // City sidewalk inventory: is a sidewalk line within SIDEWALK_T m of this road sub-segment?
 function swAt(c,ci,si){return !!(c.sw&&c.sw[ci]&&c.sw[ci][si]);}
 function swStatus(p){return p?'Sidewalk present in city inventory':'No sidewalk found in city inventory (absence may reflect incomplete records)';}
 function fitTo(ll){try{var b=L.latLngBounds([]);ll.forEach(function(p){p.forEach(function(q){b.extend(q);});});if(b.isValid())map.fitBounds(b.pad(0.2));}catch(e){}}
 var ownTarget=null;   // corridor whose City/State breakdown the "See ... segments" link reveals
 function highlightOwnership(c){
   clear();var nL=0,ll=llOf(c);
   (c.mg||[]).forEach(function(line,ci){
     var owns=(c.co&&c.co[ci])||[],pts=ll[ci],i=0;
     while(i<owns.length){var oc=owns[i],j=i;while(j<owns.length&&owns[j]===oc)j++;  // merge same-owner runs
       if(oc===2)nL++;
       L.polyline(pts.slice(i,j+1),{color:OWNCOL[oc],weight:6,opacity:.6,interactive:false}).addTo(layer); // teal=City, crimson=TDOT
       i=j;}
   });
   fitTo(ll);
   function sw(col){return '<span style="display:inline-block;width:11px;height:11px;border-radius:50%;background:'+col+';margin-right:6px;vertical-align:middle"></span>';}
   showCard('<h2>'+c.disp+' — road ownership</h2>'+
     '<div class="row">'+sw(OWNCOL[0])+'City of Memphis segments</div>'+
     '<div class="row">'+sw(OWNCOL[1])+'TDOT / State segments</div>'+
     (nL?'<div class="row">'+sw(OWNCOL[2])+'Limited-access (TDOT) segments</div>':'')+
     '<div class="row" style="color:#54646c">Same colours as the crash dots — '+c.disp+' only.</div>');
 }
 window.__segBreak=function(){if(ownTarget)highlightOwnership(ownTarget);return false;};

 // ---- Fix 1: connected-cluster network distance (branch stubs count as ONE road) ----
 function clusterOf(c,ci){var g=c.cl[ci],out=[];for(var i=0;i<c.cl.length;i++)if(c.cl[i]===g)out.push(i);return out;}
 function clusterGraph(c,comps){
   var nodes=[],en={},len={},adj={};
   function nid(p){for(var k=0;k<nodes.length;k++){var q=nodes[k];if(Math.hypot(q[0]-p[0],q[1]-p[1])<=1.5)return k;}nodes.push(p);return nodes.length-1;}
   comps.forEach(function(cj){var line=c.mg[cj],a=nid(line[0]),b=nid(line[line.length-1]);
     en[cj]=[a,b];len[cj]=compLen(line);
     (adj[a]=adj[a]||[]).push([b,len[cj]]);(adj[b]=adj[b]||[]).push([a,len[cj]]);});
   return {en:en,adj:adj,len:len};
 }
 function netDist(g,ci,m){var a=g.en[ci][0],b=g.en[ci][1],dist={};dist[a]=m;dist[b]=g.len[ci]-m;
   var pq=[[dist[a],a],[dist[b],b]];
   while(pq.length){var mi=0;for(var i=1;i<pq.length;i++)if(pq[i][0]<pq[mi][0])mi=i;
     var top=pq.splice(mi,1)[0],d=top[0],u=top[1];if(d>dist[u])continue;
     var nb=g.adj[u]||[];for(var j=0;j<nb.length;j++){var v=nb[j][0],w=nb[j][1],nd=d+w;
       if(dist[v]==null||nd<dist[v]){dist[v]=nd;pq.push([nd,v]);}}}
   return dist;
 }
 // crashes on ci's cluster within +/-COUNTA_WINDOW_M NETWORK metres; returns count + graph for bars
 function netCount(c,ci,m){
   var comps=clusterOf(c,ci),g=clusterGraph(c,comps),dist=netDist(g,ci,m),W=COUNTA_WINDOW_M;
   var n=0,fat=0,cl=c.cl,xc=c.xc,xm=c.xm,xf=c.xf;
   for(var k=0;k<xm.length;k++){if(cl[xc[k]]!==cl[ci])continue;
     var cj=xc[k],mj=xm[k],nd;
     if(cj===ci)nd=Math.abs(mj-m);
     else{var a=g.en[cj][0],b=g.en[cj][1];nd=Math.min((dist[a]==null?1e18:dist[a])+mj,(dist[b]==null?1e18:dist[b])+(g.len[cj]-mj));}
     if(nd<=W){n++;if(xf[k])fat++;}}
   return {n:n,fat:fat,comps:comps,g:g,dist:dist};
 }
 // draw the +/-window frontier bars over the cluster; returns how many were drawn (>=2 => not clamped)
 function drawFrontier(c,res,ci,m){
   var g=res.g,dist=res.dist,W=COUNTA_WINDOW_M,drawn=0;
   res.comps.forEach(function(cj){var line=c.mg[cj],Lj=g.len[cj];
     if(cj===ci){
       if(m-W>=0){drawWindowTick(line,m-W,'#e8590c');drawn++;}
       if(m+W<=Lj){drawWindowTick(line,m+W,'#e8590c');drawn++;}
     }else{
       var dS=dist[g.en[cj][0]],dE=dist[g.en[cj][1]];
       if(dS!=null&&dS<=W){var x=W-dS;if(x>0&&x<Lj){drawWindowTick(line,x,'#e8590c');drawn++;}}
       if(dE!=null&&dE<=W){var x2=Lj-(W-dE);if(x2>0&&x2<Lj){drawWindowTick(line,x2,'#e8590c');drawn++;}}
     }});
   return drawn;
 }

 // THE one shared pipeline. Address, coordinates, and map-click all call this.
 function countA(lat,lon,srcLabel){
   clear();
   L.marker([lat,lon]).addTo(layer);map.setView([lat,lon],16);
   var xy=prj(lat,lon),px=xy[0],py=xy[1];
   // (a) snap to the nearest crash-corridor COMPONENT (EPSG:32136 m). Skip generic names (Change 2).
   var ranked=[];
   IDX.corridors.forEach(function(c){if(c.g)return;(c.mg||[]).forEach(function(line,ci){
     var r=measureLine(line,px,py);ranked.push({c:c,ci:ci,m:r.m,d:r.d,si:r.si});});});
   if(!ranked.length){showCard('<h2>'+srcLabel+'</h2>'+row('Result','no road geometry available'));return;}
   ranked.sort(function(a,b){return a.d-b.d;});
   var hit=ranked[0],alt=null;
   for(var i=1;i<ranked.length;i++){if(ranked[i].c.raw!==hit.c.raw){alt=ranked[i];break;}}
   var ambiguous=alt&&(alt.d-hit.d)<=15;
   // highlight ALL components of the corridor as clean, spatially-ordered lines (Option A: no zigzag)
   var ll=llOf(hit.c);ll.forEach(function(p){
     L.polyline(p,{color:'#ffe11a',weight:11,opacity:.20,interactive:false}).addTo(layer);
     L.polyline(p,{color:'#ffe11a',weight:5,opacity:.5,interactive:false}).addTo(layer);});
   // (b) Count A over the CONNECTED CLUSTER by NETWORK distance (Fix 1: branch stubs fold in; no leakage)
   var res=netCount(hit.c,hit.ci,hit.m),n=res.n,fat=res.fat;
   var barsDrawn=drawFrontier(hit.c,res,hit.ci,hit.m);
   var clamped=barsDrawn<2;
   var clusterLen=0;res.comps.forEach(function(cj){clusterLen+=res.g.len[cj];});
   var ncl=Math.max.apply(null,hit.c.cl)+1;
   // (CHANGE 1) point owner = owner of the sub-segment it snapped to
   ownTarget=hit.c;
   var powner=(hit.c.co&&hit.c.co[hit.ci]&&hit.c.co[hit.ci][hit.si]!=null)?hit.c.co[hit.ci][hit.si]:null;
   var varies=allOwners(hit.c).length>1;
   var ownRow=row('Owner',(powner==null?'unknown':ownerLabel(powner)))+
     (varies?'<div class="row"><a href="#" onclick="return __segBreak()">See full corridor City vs State breakdown</a></div>':'');
   var ll2=lat.toFixed(5)+', '+lon.toFixed(5);
   var coord='<div class="row" style="font-size:12px;color:#54646c">'+ll2+
     ' <span style="cursor:pointer;color:#2a6f97" title="copy" onclick="navigator.clipboard&&navigator.clipboard.writeText(\''+ll2+'\')">⧉ copy</span></div>';
   var snap=hit.c.disp+' <span style="color:#54646c">— snapped '+Math.round(hit.d)+' m from your point</span>';
   var amb=ambiguous?'<div class="row na">Ambiguous: also '+Math.round(alt.d)+' m from '+alt.c.disp+'; counting '+hit.c.disp+'.</div>':'';
   var far=(!ambiguous&&hit.d>35)?'<div class="row na">Your point is '+Math.round(hit.d)+' m from the nearest road on record — it may not be on '+hit.c.disp+'.</div>':'';
   // wording: real-gap sections vs a continuous road; only clamped windows get the section note (Fix 2)
   var body='The two orange bars mark ±'+COUNTA_WINDOW_M+' m along the road from your point. '+
            'Crashes attributed to this road only, by network distance — not a straight-line radius.';
   if(ncl>1){
     var word=hit.c.rg?('one of '+ncl+' disconnected pieces (separated by real gaps — rail, etc.)')
                      :('one of '+ncl+' sections (small centreline gaps)');
     body='This is a ~'+Math.round(clusterLen)+' m section of '+hit.c.disp+' — '+word+
          (clamped?', so the ±'+COUNTA_WINDOW_M+' m window is clamped to it. ':'. ')+body;
   }
   showCard('<h2>'+srcLabel+'</h2>'+coord+row('On road',snap)+ownRow+
     row('Sidewalk (city inventory)',swStatus(swAt(hit.c,hit.ci,hit.si)))+amb+far+
     row('Crashes within ±'+COUNTA_WINDOW_M+' m',n+' ('+fat+' fatal)')+
     '<div class="row" style="color:#54646c">'+body+'</div>'+
     statsTable(hit.c)+DISCLAIMER);    // whole-road time breakdown (Change 4) + disclaimer (Change 1)
 }

 function openCorridor(c){
   clear();
   // draw each spatially-ordered component as a clean connected line (Option A fixes the old zigzag);
   // interactive:false keeps crash dots underneath clickable.
   var ll=llOf(c);ll.forEach(function(p){
     L.polyline(p,{color:'#ffe11a',weight:11,opacity:.22,interactive:false}).addTo(layer); // soft glow
     L.polyline(p,{color:'#ffe11a',weight:5,opacity:.5,interactive:false}).addTo(layer);}); // highlighter
   fitTo(ll);
   var own='City '+c.city+' · TDOT '+c.tdot+' · Limited-access '+c.limited;
   var owners=allOwners(c);ownTarget=c;
   var roadOwn=owners.length>1?'varies by segment — <a href="#" onclick="return __segBreak()">See City vs State segments</a>'
                              :ownerLabel(owners.length?owners[0]:0);
   var sig=c.n_signalized==null?na():(c.n_signalized+' signalized');
   var safe=c.safe?(c.safe.n_safe+' safe crossings ('+c.safe.n_signalized+' signalized + '+c.safe.n_marked_only+
     ' marked-only) · '+c.safe.pct_over_250ft+'% of crossing-relevant crashes >250 ft from one · longest gap '+
     c.safe.longest_gap_ft.toLocaleString()+' ft'):na();
   showCard('<h2>'+c.disp+'</h2>'+row('Deadliest rank','#'+c.rank)+row('Crashes',c.total+' ('+c.fatal+' fatal)')+
     row('Road',roadOwn)+row('Crashes by owner',own)+row('Signalized intersections',sig)+row('Safe crossings',safe)+
     statsTable(c));    // whole-corridor time breakdown (Change 4)
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

 // ---- TASK 1: Sidewalk-inventory toggle. Colors the crash-corridor roads by the city sidewalk
 // flags already built (c.sw, per sub-segment) -- present vs none-found. Off by default; a separate
 // pane keeps the lines BELOW crash dots and interactive:false so dots/clicks/search are unaffected.
 var SW_PRESENT='#2a6f97', SW_NONE='#d98324';   // blue = present; amber = none-found (distinct from owner teal/crimson)
 if(map.createPane&&!map.getPane('swPane')){map.createPane('swPane');map.getPane('swPane').style.zIndex=350;}
 var swLayer=null;
 function buildSwLayer(){
   if(swLayer)return swLayer;
   swLayer=L.layerGroup();
   IDX.corridors.forEach(function(c){
     if(c.g)return; var ll=llOf(c);
     (c.mg||[]).forEach(function(line,ci){
       var flags=(c.sw&&c.sw[ci])||[],pts=ll[ci],i=0;
       while(i<flags.length){var v=flags[i],j=i;while(j<flags.length&&flags[j]===v)j++;   // merge same-status runs
         L.polyline(pts.slice(i,j+1),{pane:'swPane',color:v?SW_PRESENT:SW_NONE,weight:3,opacity:.8,interactive:false}).addTo(swLayer);
         i=j;}
     });
   });
   return swLayer;
 }
 (function addSwToggle(){
   var body=document.querySelector('.leaflet-control.panel .panel-body');
   if(!body)return;   // panel not present -> skip quietly (no interference)
   function ln(col){return '<span class="line" style="background:'+col+'"></span>';}
   var wrap=document.createElement('div');
   wrap.innerHTML='<hr><label><input type="checkbox" id="swToggle"> Sidewalk (city inventory)</label>'+
     '<div id="swLegend" style="display:none;font-size:12px;line-height:1.75;color:#33444c;margin-top:2px">'+
       '<div>'+ln(SW_PRESENT)+'Sidewalk in city inventory</div>'+
       '<div>'+ln(SW_NONE)+'None found in city inventory</div></div>';
   body.appendChild(wrap);
   var cb=document.getElementById('swToggle'),leg=document.getElementById('swLegend');
   cb.addEventListener('change',function(){
     if(cb.checked){buildSwLayer().addTo(map);leg.style.display='block';}
     else{if(swLayer)map.removeLayer(swLayer);leg.style.display='none';}
   });
 })();

 // ---- Deterministic fact API (reused by the "Report a New Incident" demo tab). Gathers the SAME
 // facts a map click computes -- snap, owner, +/-window count, time windows, nearest intersection,
 // nearest safe crossing -- as a plain object. Code-only; no phrasing, no judgment. ----
 function statsWindows(c){
   var xd=c.xd||[],xf=c.xf||[],total=xd.length,deaths=0,i;
   for(i=0;i<xf.length;i++)if(xf[i])deaths++;
   var dmax=IDX.meta.dmax;
   function cut(m){var d=new Date(dmax+'T00:00:00');d.setMonth(d.getMonth()-m);return d;}
   function win(months){var inc=0,dth=0,co=(months==null?null:cut(months));
     for(var i=0;i<xd.length;i++){var ok=(months==null);if(!ok&&xd[i])ok=(new Date(xd[i]+'T00:00:00'))>=co;if(ok){inc++;if(xf[i])dth++;}}
     return {incidents:inc,deaths:dth};}
   return {coverage_start:IDX.meta.dmin,coverage_end:dmax,total_incidents:total,total_deaths:deaths,
     since_data_start:win(null),last_12_months:win(12),last_6_months:win(6),last_3_months:win(3),last_1_month:win(1)};
 }
 function distM(la1,lo1,la2,lo2){var R=111320,la=(la1+la2)/2*Math.PI/180;var dx=(lo1-lo2)*Math.cos(la)*R,dy=(la1-la2)*R;return Math.sqrt(dx*dx+dy*dy);}
 function gatherFacts(lat,lon){
   var xy=prj(lat,lon),px=xy[0],py=xy[1],best=null;
   IDX.corridors.forEach(function(c){if(c.g)return;(c.mg||[]).forEach(function(line,ci){var r=measureLine(line,px,py);if(!best||r.d<best.d)best={c:c,ci:ci,m:r.m,d:r.d,si:r.si};});});
   if(!best)return null;
   var c=best.c,res=netCount(c,best.ci,best.m);
   var oc=(c.co&&c.co[best.ci]&&c.co[best.ci][best.si]!=null)?c.co[best.ci][best.si]:null;
   var clusterLen=0;res.comps.forEach(function(cj){clusterLen+=res.g.len[cj];});
   var S=statsWindows(c);
   var ni=null,nd=1e9;INTERS.forEach(function(n){var d=distM(lat,lon,n.lat,n.lon);if(d<nd){nd=d;ni=n;}});
   var atInt=(ni&&nd<=35);
   return {
     location:{lat:+(+lat).toFixed(5),lon:+(+lon).toFixed(5)},
     road:{name:c.disp,owner:(oc==null?'unknown':ownerLabel(oc)),snap_distance_m:Math.round(best.d),owner_varies:allOwners(c).length>1},
     sidewalk:{present:swAt(c,best.ci,best.si),status:swStatus(swAt(c,best.ci,best.si))},
     stretch:{window_m:COUNTA_WINDOW_M,crashes:res.n,fatal:res.fat,connected_length_m:Math.round(clusterLen),pieces:(Math.max.apply(null,c.cl)+1),road_split_by_gaps:!!c.rg},
     time_window:{coverage_start:S.coverage_start,coverage_end:S.coverage_end,total_incidents:S.total_incidents,total_deaths:S.total_deaths,
       since_data_start:S.since_data_start,last_12_months:S.last_12_months,last_6_months:S.last_6_months,last_3_months:S.last_3_months,last_1_month:S.last_1_month},
     nearest_intersection:atInt?{name:ni.disp,distance_m:Math.round(nd),crashes:ni.crashes,deaths:ni.deaths,signalized:(ni.sig==='y')}:null,
     nearest_safe_crossing_ft:(atInt&&ni.near_safe_ft!=null)?ni.near_safe_ft:null
   };
 }
 window.CountA={facts:gatherFacts};   // demo-tab entry point (deterministic; no AI here)
})();
"""


if __name__ == "__main__":
    main()
