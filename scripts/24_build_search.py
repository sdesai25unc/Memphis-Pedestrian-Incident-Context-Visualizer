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
    # `sww` (added 2026-07-12) mirrors `sw` with the matched inventory line's WIDTH in feet
    # (0 = not recorded), so the clickable sidewalk layer can show width where available.
    for rec in corridors:
        rec["sw"] = [[0] * max(0, len(comp) - 1) for comp in rec["mg"]]
        rec["sww"] = [[0] * max(0, len(comp) - 1) for comp in rec["mg"]]
    if SIDEWALKS.exists():
        sw_gdf = gpd.read_file(SIDEWALKS).to_crs(CRS_M)
        widths = (pd.to_numeric(sw_gdf["WIDTH"], errors="coerce")
                  if "WIDTH" in sw_gdf.columns else None)
        tree = STRtree(sw_gdf.geometry.values)
        mids, loc = [], []
        for corridor_i, rec in enumerate(corridors):
            for comp_i, comp in enumerate(rec["mg"]):
                for si in range(len(comp) - 1):
                    mids.append(Point((comp[si][0] + comp[si + 1][0]) / 2.0,
                                      (comp[si][1] + comp[si + 1][1]) / 2.0))
                    loc.append((corridor_i, comp_i, si))
        n_with = n_w = 0
        if mids:
            indices, dists = tree.query_nearest(mids, all_matches=False, return_distance=True)
            for k in range(len(dists)):
                if dists[k] <= SIDEWALK_T:
                    ci, cj, si = loc[indices[0][k]]
                    corridors[ci]["sw"][cj][si] = 1
                    n_with += 1
                    if widths is not None:
                        w = widths.iloc[int(indices[1][k])]
                        if pd.notna(w) and w > 0:
                            corridors[ci]["sww"][cj][si] = int(w)
                            n_w += 1
        _swpct = round(100.0 * n_with / len(mids), 1) if mids else 0.0
        print(f"  sidewalks: {len(sw_gdf):,} city lines | {n_with:,}/{len(mids):,} road sub-segments "
              f"have a sidewalk within {SIDEWALK_T:.0f} m ({_swpct}%) | width recorded on {n_w:,}")
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

    # state-route alias table (data-derived, built by script 27) — embedded so the in-page
    # matcher resolves "sr 23" / "us 51"-style queries without a network round-trip
    locate_path = PROC / "locate_index.json"
    alias = (json.loads(locate_path.read_text(encoding="utf-8")).get("alias", {})
             if locate_path.exists() else {})

    idx = {"corridors": corridors, "intersections": intersections, "alias": alias,
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
             '<div id="searchHint">Streets, intersections &amp; addresses — for a full location '
             'report, use <a href="#/investigate">Investigate</a></div>'
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
/* StreetStat design tokens (defined by the base page, script 18); fallbacks keep this
   self-sufficient if the injection ever runs against an older template. */
#searchWrap{position:absolute;z-index:1200;top:14px;left:14px;width:min(360px,calc(100vw - 28px));font-family:var(--sans,system-ui)}
@media(max-width:560px){#searchWrap{left:10px;width:min(300px,calc(100vw - 232px))}}
#searchPanel{background:var(--surface,#fff);border:1px solid var(--border,#e4e4e7);border-radius:14px;box-shadow:var(--shadow-md,0 4px 18px rgba(0,0,0,.18));padding:11px 12px}
#searchTop{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px}
#searchTop .lbl{font-family:var(--mono,monospace);font-size:10.5px;font-weight:500;letter-spacing:.09em;text-transform:uppercase;color:var(--muted,#71717a)}
#segMode{display:inline-flex;background:#f4f4f5;border:1px solid var(--border,#e4e4e7);border-radius:8px;padding:2px;gap:2px}
#segMode button{appearance:none;border:none;background:transparent;border-radius:6px;color:var(--muted,#71717a);font-family:inherit;font-size:12px;font-weight:600;padding:4px 12px;cursor:pointer;transition:background .12s,color .12s}
#segMode button.on{background:var(--surface,#fff);color:var(--ink,#18181b);box-shadow:0 1px 2px rgba(24,24,27,.08)}
#searchBox{width:100%;box-sizing:border-box;padding:9px 12px;border:1px solid var(--border-strong,#d4d4d8);border-radius:9px;font-family:inherit;font-size:14px;color:var(--ink,#18181b);background:var(--surface,#fff)}
#searchBox:focus{outline:none;border-color:var(--accent,#4f46e5);box-shadow:0 0 0 3px var(--accent-soft,#eef2ff)}
#searchHint{font-size:11px;color:var(--muted,#8a9aa2);margin-top:7px}
#searchDrop{background:var(--surface,#fff);border:1px solid var(--border,#e4e4e7);border-radius:10px;margin-top:6px;box-shadow:var(--shadow-lg,0 4px 16px rgba(0,0,0,.18));overflow:hidden;display:none}
#searchDrop .it{padding:8px 13px;cursor:pointer;font-size:13px;border-bottom:1px solid var(--border,#eef1f3)}
#searchDrop .it:last-child{border-bottom:none}
#searchDrop .it:hover,#searchDrop .it.sel{background:var(--accent-soft,#eef2ff)}
#searchDrop .it b{color:var(--ink,#18181b)}
#searchDrop .it .ty{float:right;color:var(--faint,#a1a1aa);font-family:var(--mono,monospace);font-size:10px;text-transform:uppercase;letter-spacing:.05em}
#searchDrop .it.deadrow{color:var(--faint,#a1a1aa);font-style:italic;cursor:default}
#searchDrop .it.deadrow:hover{background:var(--surface,#fff)}
#searchCard{background:var(--surface,#fff);border:1px solid var(--border,#e4e4e7);border-radius:12px;margin-top:6px;box-shadow:var(--shadow-lg,0 4px 16px rgba(0,0,0,.18));padding:13px 15px;font-size:13px;line-height:1.55;display:none;max-height:calc(100vh - 240px);overflow-y:auto}
#searchCard h2{margin:0 0 6px;font-size:15.5px;letter-spacing:-.01em;color:var(--ink,#18181b)}
#searchCard .x{float:right;cursor:pointer;color:var(--faint,#a1a1aa);font-weight:700}
#searchCard .x:hover{color:var(--ink,#18181b)}
#searchCard .cstats{margin-top:7px;border-top:1px solid var(--border,#eef1f3);padding-top:6px}
#searchCard #twLink{color:var(--accent-ink,#4338ca);text-decoration:none;margin-left:4px;cursor:pointer;font-weight:600}
#searchCard .row,#invCard .row{margin:2.5px 0}
#searchCard .row b,#invCard .row b{color:var(--ink-2,#3f3f46)}
#searchCard .na,#invCard .na{color:#a06000;font-style:italic}
#searchCard table.tw,#invCard table.tw{width:100%;border-collapse:collapse;margin:8px 0 3px}
#searchCard table.tw th,#invCard table.tw th{text-align:left;font-family:var(--mono,monospace);font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted,#71717a);font-weight:500;border-bottom:1px solid var(--border-strong,#d9e0e4);padding:3px 6px}
#searchCard table.tw td,#invCard table.tw td{font-size:12px;padding:3.5px 6px;border-bottom:1px solid var(--border,#f0f3f5)}
#searchCard table.tw .n,#invCard table.tw .n{text-align:right;font-family:var(--mono,monospace);font-variant-numeric:tabular-nums;width:78px}
#searchCard .twnote,#invCard .twnote{font-size:10.5px;color:var(--faint,#9aa7ad);font-style:italic;margin-top:3px}
#searchCard .twcov,#invCard .twcov{font-size:11px;color:var(--muted,#54646c);margin-top:2px}
#searchCard .disclaim,#invCard .disclaim{font-size:10.5px;color:var(--faint,#9aa7ad);line-height:1.45;margin-top:8px;border-top:1px solid var(--border,#eef1f3);padding-top:6px}
/* Investigate facts card */
.inv-card{background:var(--surface,#fff);border:1px solid var(--border,#e4e4e7);border-radius:12px;box-shadow:var(--shadow-sm,0 1px 2px rgba(24,24,27,.06));padding:14px 16px;font-size:13.5px;line-height:1.6}
.inv-card h3{margin:0 0 2px;font-size:16px;letter-spacing:-.01em;color:var(--ink,#18181b)}
.inv-coords{font-family:var(--mono,monospace);font-size:11.5px;color:var(--muted,#71717a);margin-bottom:9px}
</style>"""

_JS = r"""
(function(){
 var IDX=window.SEARCH_INDEX, box=document.getElementById('searchBox'),
     drop=document.getElementById('searchDrop'), card=document.getElementById('searchCard');
 var layer=L.layerGroup().addTo(map);      // explore-view highlights (search / click cards)
 var invLayer=L.layerGroup().addTo(map);   // investigate-view microscope layers
 // StreetStat shell (script 18): dock the search panel inside the Explore map slot so it
 // travels with that view. If the shell is absent (older template), it stays where it is.
 (function(){var w=document.getElementById('searchWrap'),s=document.getElementById('mapSlotExplore');
  if(w&&s)s.appendChild(w);})();
 function norm(s){return (s||'').toLowerCase().replace(/\band\b/g,'&').replace(/[^a-z0-9& ]/g,' ').replace(/\s+/g,' ').trim();}
 function toks(s){return norm(s).replace(/&/g,' ').split(' ').filter(Boolean);}
 // searchable items (intersections arrive packed as [disp,lat,lon,crashes,deaths,sig,near_safe_ft])
 var items=[];
 var INTERS=IDX.intersections.map(function(a){return {disp:a[0],lat:a[1],lon:a[2],crashes:a[3],deaths:a[4],sig:a[5],near_safe_ft:a[6]};});
 IDX.corridors.forEach(function(c){items.push({t:'corridor',disp:c.disp,blob:norm(c.disp),score:c.total,ref:c});});
 INTERS.forEach(function(n){items.push({t:'intersection',disp:n.disp,blob:norm(n.disp),score:n.crashes,ref:n});});

 // ================= FORGIVING MATCHING (casual queries; mirrors api/locate.js) =================
 // suffix-blind, directional-blind, and/&/@, alias-aware, typo-tolerant. Keep the word lists in
 // sync with api/locate.js and scripts/27_build_locate_index.py.
 var SUFW={avenue:1,ave:1,street:1,st:1,road:1,rd:1,boulevard:1,blvd:1,drive:1,dr:1,parkway:1,pkwy:1,
   highway:1,hwy:1,lane:1,ln:1,court:1,ct:1,place:1,pl:1,circle:1,cir:1,pike:1,way:1,cove:1,cv:1,
   terrace:1,ter:1,ext:1,expressway:1,expy:1};
 var DIRW={n:'n',s:'s',e:'e',w:'w',north:'n',south:'s',east:'e',west:'w'};
 function baseOf(s){
   var w=(s||'').toLowerCase().replace(/[^a-z0-9 ]/g,' ').replace(/\s+/g,' ').trim().split(' ').filter(Boolean);
   var dir=null;
   if(w.length>1&&DIRW[w[0]]!=null){dir=DIRW[w[0]];w=w.slice(1);}
   if(w.length>1&&SUFW[w[w.length-1]])w=w.slice(0,-1);
   return {b:w.join(' '),dir:dir};
 }
 function lev(a,b,max){
   if(Math.abs(a.length-b.length)>max)return max+1;
   var prev=[],i,j;for(j=0;j<=b.length;j++)prev[j]=j;
   for(i=1;i<=a.length;i++){var cur=[i],rowMin=i;
     for(j=1;j<=b.length;j++){cur[j]=Math.min(prev[j]+1,cur[j-1]+1,prev[j-1]+(a[i-1]===b[j-1]?0:1));if(cur[j]<rowMin)rowMin=cur[j];}
     if(rowMin>max)return max+1;prev=cur;}
   return prev[b.length];
 }
 var ALIAS=IDX.alias||{};
 var corrByBase={};IDX.corridors.forEach(function(c){var b=baseOf(c.disp).b;(corrByBase[b]=corrByBase[b]||[]).push(c);});
 var nodePartsArr=INTERS.map(function(n){return n.disp.split(' & ').map(function(p){return baseOf(p).b;});});
 var nodeByBase={};nodePartsArr.forEach(function(parts,i){parts.forEach(function(b){(nodeByBase[b]=nodeByBase[b]||[]).push(i);});});
 var VOCAB=Object.keys(nodeByBase);Object.keys(corrByBase).forEach(function(b){if(!nodeByBase[b])VOCAB.push(b);});
 // one query part -> {bases:{base:quality}, dir}: exact/alias 4, prefix 3, fuzzy 2, contains 1.
 // Fuzzy runs only when the cheap tiers found nothing (keystroke performance); api/locate is the
 // authority for hard typos anyway.
 function matchPart(raw){
   var bo=baseOf(raw),part=bo.b,out={},n=0;
   if(!part)return {bases:out,dir:bo.dir};
   var key=(raw||'').toLowerCase().replace(/\s+/g,' ').trim();
   var members=ALIAS[key]||ALIAS[part];
   if(members){members.forEach(function(m){out[baseOf(m).b]=4;n++;});}
   if(corrByBase[part]||nodeByBase[part]){out[part]=4;n++;}
   var pre=0,sub=0,i;
   for(i=0;i<VOCAB.length;i++){var v=VOCAB[i];
     if(v===part)continue;
     if(v.indexOf(part)===0){if(pre<40&&!(out[v]>=3)){out[v]=3;pre++;n++;}}
     else if(part.length>=5&&sub<40&&v.indexOf(part)>=0){if(out[v]==null){out[v]=1;sub++;n++;}}
   }
   if(!n&&part.length>=4){
     var tol=part.length<6?1:2,best=tol+1,fz=[];
     for(i=0;i<VOCAB.length;i++){var d=lev(part,VOCAB[i],tol);
       if(d<best){best=d;fz=[VOCAB[i]];}else if(d===best&&d<=tol)fz.push(VOCAB[i]);}
     if(best<=tol)fz.slice(0,25).forEach(function(v){if(!(out[v]>=2))out[v]=2;});
   }
   return {bases:out,dir:bo.dir};
 }
 function dirBoost(disp,base,dir){   // +0.5 when the display's directional prefix matches the query's
   if(!dir)return 0;
   var hit=disp.toLowerCase().split(' & ').some(function(p){var w=p.trim().split(' ');
     return DIRW[w[0]]===dir&&baseOf(p).b===base;});
   return hit?0.5:0;
 }
 function forgivingMatches(q){
   var parts=q.split(/\s*(?:\band\b|&|@)\s*/i).map(function(s){return s.trim();}).filter(Boolean);
   var out=[];
   if(parts.length>=2){
     var sets=parts.map(matchPart),ok=sets.every(function(s){var k;for(k in s.bases)return true;return false;});
     if(!ok)return out;
     var pool={},b0;for(b0 in sets[0].bases)(nodeByBase[b0]||[]).forEach(function(i){pool[i]=1;});
     var cand=[];
     Object.keys(pool).forEach(function(i){
       i=+i;var np=nodePartsArr[i],used={},qsum=0,good=true;
       for(var pi=0;pi<sets.length;pi++){
         var found=-1,fq=0;
         for(var k=0;k<np.length;k++){var qq=sets[pi].bases[np[k]];
           if(!used[k]&&qq!=null){qq+=dirBoost(INTERS[i].disp,np[k],sets[pi].dir);
             if(qq>fq){fq=qq;found=k;}}}
         if(found<0){good=false;break;}
         used[found]=1;qsum+=fq;
       }
       if(good)cand.push({t:'intersection',disp:INTERS[i].disp,score:INTERS[i].crashes,ref:INTERS[i],q:qsum});
     });
     cand.sort(function(a,b){return (b.q-a.q)||(b.score-a.score);});
     // ambiguity: dirless query resolving to multiple directional peers -> flag, never auto-pick
     var dirless=sets.some(function(s){return !s.dir;});
     if(dirless&&cand.length>1&&cand[0].q===cand[1].q){cand[0].amb=true;cand[1].amb=true;}
     return cand.slice(0,8);
   }
   var m=matchPart(q),cand2=[],b;
   for(b in m.bases){(corrByBase[b]||[]).forEach(function(c){
     cand2.push({t:'corridor',disp:c.disp,score:c.total,ref:c,q:m.bases[b]+dirBoost(c.disp,b,m.dir)});});}
   cand2.sort(function(a,b2){return (b2.q-a.q)||(b2.score-a.score);});
   if(cand2.length>1&&!m.dir&&cand2[0].q===cand2[1].q&&baseOf(cand2[0].disp).b===baseOf(cand2[1].disp).b){
     cand2[0].amb=true;cand2[1].amb=true;}
   return cand2.slice(0,8);
 }

 // ---- /api/locate fallback: the full street network, server-side (deployed site only) ----
 var locateTimer=null,locateCtl=null,locateSeq=0;
 function ownerLabelNum(o){return o===0?'City of Memphis':o===1?'TDOT / State':'Limited-access (TDOT)';}
 function fmtFullDate(d){if(!d)return '?';var p=d.split('-'),M=['January','February','March','April','May','June','July','August','September','October','November','December'];return M[(+p[1])-1]+' '+(+p[2])+', '+p[0];}
 function scheduleLocate(q,wantsInt){
   if(locateTimer)clearTimeout(locateTimer);
   var seq=++locateSeq;
   locateTimer=setTimeout(function(){
     if(locateCtl&&locateCtl.abort)try{locateCtl.abort();}catch(e){}
     locateCtl=('AbortController' in window)?new AbortController():null;
     fetch('/api/locate?q='+encodeURIComponent(q),{signal:locateCtl?locateCtl.signal:undefined})
       .then(function(r){return r.json();})
       .then(function(j){
         if(seq!==locateSeq||box.value.trim()!==q)return;   // stale response
         var add=[];
         ((j&&j.candidates)||[]).forEach(function(c){
           if(c.kind==='street'){
             // a street that IS a crash corridor should open its full corridor card instead
             var cor=IDX.corridors.filter(function(x){return x.disp===c.name;})[0];
             if(cor){add.push({t:'corridor',disp:cor.disp,score:cor.total,ref:cor});return;}
             add.push({t:'street · network',disp:c.name,score:0,ref:c,net:1});
           }else{
             add.push({t:'intersection · network',disp:c.name,score:c.crashes,
               ref:{disp:c.name,lat:c.lat,lon:c.lon,crashes:c.crashes,deaths:c.deaths,sig:c.sig,near_safe_ft:null},net:1});
           }
         });
         if(!add.length){appendRows([{t:'no result',disp:'No matching street or intersection in the Memphis network',dead:1}]);return;}
         appendRows(add);
       })
       .catch(function(){
         if(seq!==locateSeq)return;
         // street intent: only a corridor/network-street row counts as "resolved" — an
         // intersection containing the name is real info but the street itself still
         // needs the online endpoint, so say so honestly
         var resolved=cur.some(function(it){return it.net||it.t==='corridor'||(wantsInt&&it.t==='intersection');});
         if(!resolved)appendRows([{t:'offline',disp:'Full-network street search needs the online version',dead:1}]);
       });
   },350);
 }
 // honest minimal card for a street outside the analyzed crash-corridor set (Part 4)
 function openNetworkStreet(c){
   clear();
   var bnds=L.latLngBounds([[c.bbox[0],c.bbox[1]],[c.bbox[2],c.bbox[3]]]);
   L.rectangle(bnds,{color:'#4f46e5',weight:2,dashArray:'6 5',fill:false,interactive:false}).addTo(layer);
   try{map.fitBounds(bnds.pad(0.5),{maxZoom:17});}catch(e){}
   var range=fmtFullDate(IDX.meta.dmin)+' – '+fmtFullDate(IDX.meta.dmax);
   var mi=(c.length_m/1609.344);
   showCard('<h2>'+c.name+'</h2>'+
     '<div class="row" style="color:var(--muted,#71717a)">Found on the full Memphis street network</div>'+
     row('Pedestrian incidents','<b>'+c.crashes+' recorded here</b> ('+range+')')+
     row('Road owner',ownerLabelNum(c.owner)+' <span style="color:var(--muted,#71717a)">(dominant along the street, from the ownership rulebook)</span>')+
     row('Street length',(mi<0.1?Math.round(c.length_m)+' m':mi.toFixed(1)+' mi'))+
     row('Sidewalk (city inventory)','<span class="na">not analyzed for this street</span> — sidewalk flags are computed along roads with ≥1 recorded crash')+
     row('±'+COUNTA_WINDOW_M+' m stretch analysis','<span class="na">not available</span> — this street is outside the crash-corridor set')+
     row('Signalized crossings',na()));
 }
 function appendRows(add){
   var have={};cur.forEach(function(it){have[it.t+'|'+it.disp]=1;});
   var merged=cur.slice();
   add.forEach(function(it){if(!have[it.t+'|'+it.disp]){merged.push(it);have[it.t+'|'+it.disp]=1;}});
   render(merged.slice(0,12));
 }

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
   var allLbl='All data ('+fmtMon(dmin)+' – '+fmtMon(dmax)+')';
   var W=[[allLbl,null],['Last 12 months',12],['Last 6 months',6],['Last 3 months',3],['Last 1 month',1]];
   var body=W.map(function(w){
     var inc=0,dth=0,co=(w[1]==null?null:cut(w[1]));
     for(var i=0;i<xd.length;i++){
       var ok=(w[1]==null);
       if(!ok&&xd[i]){ok=(new Date(xd[i]+'T00:00:00'))>=co;}
       if(ok){inc++;if(xf[i])dth++;}
     }
     return '<tr><td>'+w[0]+'</td><td class="n">'+inc+'</td><td class="n">'+dth+'</td></tr>';
   }).join('');
   return '<div class="cstats"><div class="row"><b>'+allLbl+':</b> '+total+' incidents · '+deaths+
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
 // a short perpendicular cross-bar marking one end of the +/-window (clamped within the component).
 // grp: layer group to draw into (default = explore highlight layer); acc: collects the bar
 // endpoints so the Investigate view can zoom to the exact ±window stretch.
 function drawWindowTick(line,target,color,grp,acc){
   var H=22,t=tickAt(line,target);if(!t)return;
   var a=iprj(t.x+t.perp[0]*H,t.y+t.perp[1]*H),b=iprj(t.x-t.perp[0]*H,t.y-t.perp[1]*H);
   L.polyline([a,b],{color:color,weight:4,opacity:.95,interactive:false}).addTo(grp||layer);
   if(acc){acc.push(a);acc.push(b);}
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
 function drawFrontier(c,res,ci,m,grp,acc){
   var g=res.g,dist=res.dist,W=COUNTA_WINDOW_M,drawn=0;
   res.comps.forEach(function(cj){var line=c.mg[cj],Lj=g.len[cj];
     if(cj===ci){
       if(m-W>=0){drawWindowTick(line,m-W,'#e8590c',grp,acc);drawn++;}
       if(m+W<=Lj){drawWindowTick(line,m+W,'#e8590c',grp,acc);drawn++;}
     }else{
       var dS=dist[g.en[cj][0]],dE=dist[g.en[cj][1]];
       if(dS!=null&&dS<=W){var x=W-dS;if(x>0&&x<Lj){drawWindowTick(line,x,'#e8590c',grp,acc);drawn++;}}
       if(dE!=null&&dE<=W){var x2=Lj-(W-dE);if(x2>0&&x2<Lj){drawWindowTick(line,x2,'#e8590c',grp,acc);drawn++;}}
     }});
   return drawn;
 }

 // (a) snap to the nearest crash-corridor COMPONENT (EPSG:32136 m). Skip generic names (Change 2).
 // Shared by BOTH renderers (Explore's compact card and Investigate's microscope), so a given
 // point always resolves to the identical road/component/measure.
 function snapBest(lat,lon){
   var xy=prj(lat,lon),px=xy[0],py=xy[1],ranked=[];
   IDX.corridors.forEach(function(c){if(c.g)return;(c.mg||[]).forEach(function(line,ci){
     var r=measureLine(line,px,py);ranked.push({c:c,ci:ci,m:r.m,d:r.d,si:r.si});});});
   ranked.sort(function(a,b){return a.d-b.d;});
   return ranked;
 }

 // THE one shared pipeline. Explore's address and coordinate searches both call this.
 function countA(lat,lon,srcLabel){
   clear();
   L.marker([lat,lon]).addTo(layer);map.setView([lat,lon],16);
   var ranked=snapBest(lat,lon);
   if(!ranked.length){showCard('<h2>'+srcLabel+'</h2>'+row('Result','no road geometry available'));return;}
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
     c.safe.longest_gap_ft.toLocaleString()+' ft <span class="na">(proof of concept — preliminary, pending ground-truthing)</span>'):na();
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
   drop.innerHTML=list.map(function(it,i){return '<div class="it'+(it.dead?' deadrow':'')+'" data-i="'+i+'"><b>'+it.disp+'</b>'+
     (it.amb?'<span class="ty">choose one</span>':'<span class="ty">'+it.t+'</span>')+'</div>';}).join('');
   drop.style.display='block';
   Array.prototype.forEach.call(drop.children,function(el){el.onclick=function(){pick(cur[+el.dataset.i]);};});
 }
 // NOTE: 'address' rows must route to openAddress here — the old code let pick() fall through to
 // openInter(undefined) (a swallowed TypeError) and relied on a second delegated click listener.
 function pick(it){if(!it||it.dead)return;box.value=it.disp;drop.style.display='none';
   if(it.t==='address'){openAddress(it.addr);}
   else if(it.t==='corridor'){openCorridor(it.ref);}
   else if(it.t==='street · network'){openNetworkStreet(it.ref);}
   else{openInter(it.ref);}}
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
   // fast path (unchanged): every token a substring of the item's display
   var matches=items.filter(function(it){return tq.every(function(t){return it.blob.indexOf(t)>=0;});})
     .sort(function(a,b){return b.score-a.score;}).slice(0,8);
   var isAddr=/\d/.test(q)&&/\d+\s+\S/.test(q);
   // forgiving pass: suffix/directional-blind, alias-aware, typo-tolerant. Exact-quality
   // forgiving hits (incl. alias groups) lead; then the fast-path rows; then weaker fuzzies.
   if(!isAddr){
     var fg=forgivingMatches(q),strong=[],weak=[];
     fg.forEach(function(it){(it.q>=4?strong:weak).push(it);});
     var merged=[],have={};
     strong.concat(matches).concat(weak).forEach(function(it){
       var k=it.t+'|'+it.disp;
       if(!have[k]&&merged.length<12){have[k]=1;merged.push(it);}});
     matches=merged;
   }
   if(isAddr){matches.unshift({t:'address',disp:'Search address: "'+q+'"',addr:q});}
   else if(!matches.length){matches=[{t:'address',disp:'Search address: "'+q+'"',addr:q}];}
   render(matches);
   // full-network fallback (/api/locate) when the in-page index cannot resolve the query type.
   // Street intent: only an EXACT-quality corridor match suppresses the network lookup — a
   // prefix/fuzzy corridor hit (e.g. "kings" -> Kings Trail Cv) must not hide the ~16k
   // non-corridor streets (Kings Court etc.).
   if(!isAddr){
     var wantsInt=/(\band\b|&|@)/i.test(q);
     var hasInt=matches.some(function(it){return it.t==='intersection';});
     var exactCorr=matches.some(function(it){return it.t==='corridor'&&(it.q>=4||baseOf(it.disp).b===baseOf(q).b);});
     if((wantsInt&&!hasInt)||(!wantsInt&&!exactCorr))scheduleLocate(q,wantsInt);
   }
 });
 box.addEventListener('keydown',function(e){
   if(mode==='coord'){if(e.key==='Enter'){runCoords(box.value.trim());drop.style.display='none';}return;}
   if(drop.style.display==='none')return;
   if(e.key==='ArrowDown'){sel=Math.min(sel+1,cur.length-1);}
   else if(e.key==='ArrowUp'){sel=Math.max(sel-1,0);}
   else if(e.key==='Enter'){var it=cur[sel<0?0:sel];
     if(it&&it.dead)return;
     if(sel<0&&it&&it.amb){e.preventDefault();return;}   // ambiguous (e.g. N vs S) -> keep the list, never silent-pick
     if(it){if(it.t==='address')openAddress(it.addr);else pick(it);drop.style.display='none';}return;}
   else return;
   Array.prototype.forEach.call(drop.children,function(el,i){el.className='it'+(i===sel?' sel':'');});
   e.preventDefault();
 });
 document.addEventListener('click',function(e){if(!document.getElementById('searchWrap').contains(e.target))drop.style.display='none';});
 // (the old delegated "Search address" click listener is gone — pick() handles address rows directly,
 //  which also removes the double-dispatch where both listeners fired on one click)

 // Click-to-locate was REMOVED (2026-07-12): empty-map clicks no longer run Count A, so the
 // popup-timing conflict handler it required is gone too. Map clicks now belong to FEATURES only
 // (crash dots / signals / sidewalk segments — each carries its own popup); a full location
 // report is reached through the Investigate tab (address or coordinates).

 // ---- Sidewalk-inventory lens layer. Colors the crash-corridor roads by the city sidewalk flags
 // (c.sw) with inventory widths (c.sww). CLICKABLE (2026-07-12): each segment pops its honest
 // status + street name + width where recorded. The lines draw on the SHARED canvas — a separate
 // lower pane would never receive DOM clicks under the overlay canvas — and the lens system's
 // raise() ordering keeps crash dots and signals ABOVE them in click priority.
 var SW_PRESENT='#2a6f97', SW_NONE='#d98324';   // blue = present; amber = none-found (distinct from owner teal/crimson)
 function swPopup(disp,v,w){
   return '<b>'+disp+'</b><br>'+
     (v?'Sidewalk in city inventory':'None found in city inventory (absence may reflect incomplete records)')+
     ((v&&w)?'<br>Inventory width: '+w+' ft':'')+
     '<br><span style="font-size:11px;color:#71717a">City of Memphis sidewalk inventory · matched within 20 m of the road centerline</span>';
 }
 var swLayer=null;
 function buildSwLayer(){
   if(swLayer)return swLayer;
   swLayer=L.layerGroup();
   IDX.corridors.forEach(function(c){
     if(c.g)return; var ll=llOf(c);
     (c.mg||[]).forEach(function(line,ci){
       var flags=(c.sw&&c.sw[ci])||[],wids=(c.sww&&c.sww[ci])||[],pts=ll[ci],i=0;
       while(i<flags.length){
         var v=flags[i],w=wids[i]||0,j=i;
         while(j<flags.length&&flags[j]===v&&(wids[j]||0)===w)j++;   // merge same-status, same-width runs
         L.polyline(pts.slice(i,j+1),{color:v?SW_PRESENT:SW_NONE,weight:3,opacity:.8})
           .bindPopup(swPopup(c.disp,v,w)).addTo(swLayer);
         i=j;}
     });
   });
   return swLayer;
 }
 // Register the sidewalk layer as the "Sidewalks" lens in the StreetStat shell (script 18 owns
 // the one-lens-at-a-time control + legend). Fallback for an older template without the shell:
 // no-op (the layer is still reachable through the Investigate microscope).
 if(window.__registerLens){window.__registerLens('sidewalk',buildSwLayer);}

 // ======================= INVESTIGATE — the location microscope (StreetStat) =======================
 // A dedicated view built on the SAME pipeline as Explore's compact card (snapBest + netCount), so
 // both render identical numbers for the same point. This is the ONE view where layers combine
 // (ownership + sidewalk status + window bars + intersection marker) — it works because it is
 // scoped to a single location at street-level zoom. Reached by address/coordinates input only.
 function nearestNode(lat,lon){
   var ni=null,nd=1e9;
   INTERS.forEach(function(n){var d=distM(lat,lon,n.lat,n.lon);if(d<nd){nd=d;ni=n;}});
   return {n:ni,d:nd};
 }
 // whole-road time table, always expanded (same window math as statsTable -> identical numbers)
 function invTimeTable(c){
   var xd=c.xd||[],xf=c.xf||[];
   var dmax=IDX.meta.dmax,dmin=IDX.meta.dmin;
   function cut(m){var d=new Date(dmax+'T00:00:00');d.setMonth(d.getMonth()-m);return d;}
   var W=[['All data ('+fmtMon(dmin)+' – '+fmtMon(dmax)+')',null],['Last 12 months',12],['Last 6 months',6],['Last 3 months',3],['Last 1 month',1]];
   var body=W.map(function(w){
     var inc=0,dth=0,co=(w[1]==null?null:cut(w[1]));
     for(var i=0;i<xd.length;i++){
       var ok=(w[1]==null);
       if(!ok&&xd[i]){ok=(new Date(xd[i]+'T00:00:00'))>=co;}
       if(ok){inc++;if(xf[i])dth++;}
     }
     return '<tr><td>'+w[0]+'</td><td class="n">'+inc+'</td><td class="n">'+dth+'</td></tr>';
   }).join('');
   return '<table class="tw"><thead><tr><th>Whole road</th><th class="n">Incidents</th><th class="n">Deaths</th></tr></thead>'+
     '<tbody>'+body+'</tbody></table>'+
     '<div class="twnote">Recent windows may undercount — official crash data is finalized with a reporting lag.</div>'+
     '<div class="twcov">Data coverage: '+fmtMon(dmin)+' – '+fmtMon(dmax)+'</div>';
 }
 var invCardEl=document.getElementById('invCard'),invErrEl=document.getElementById('invErr');
 function invSetErr(msg){if(invErrEl){invErrEl.textContent=msg;invErrEl.style.display='block';}}
 function invClearErr(){if(invErrEl)invErrEl.style.display='none';}
 function investigate(lat,lon,label){
   if(!invCardEl){countA(lat,lon,label);return;}   // shell absent -> fall back to the compact card
   invClearErr();clear();invLayer.clearLayers();
   var ranked=snapBest(lat,lon);
   if(!ranked.length){invCardEl.innerHTML='<div class="inv-card">No road geometry available.</div>';return;}
   var hit=ranked[0],alt=null,i;
   for(i=1;i<ranked.length;i++){if(ranked[i].c.raw!==hit.c.raw){alt=ranked[i];break;}}
   var c=hit.c,res=netCount(c,hit.ci,hit.m),W=COUNTA_WINDOW_M;
   // --- microscope layers: owner underlay (glow) + sidewalk-status overlay, whole corridor ---
   var ll=llOf(c);
   (c.mg||[]).forEach(function(line,ci){
     var owns=(c.co&&c.co[ci])||[],pts=ll[ci],a=0,b;
     while(a<owns.length){var oc=owns[a];b=a;while(b<owns.length&&owns[b]===oc)b++;
       L.polyline(pts.slice(a,b+1),{color:OWNCOL[oc],weight:11,opacity:.30,interactive:false}).addTo(invLayer);a=b;}
     var flags=(c.sw&&c.sw[ci])||[];a=0;
     while(a<flags.length){var v=flags[a];b=a;while(b<flags.length&&flags[b]===v)b++;
       L.polyline(pts.slice(a,b+1),{color:v?SW_PRESENT:SW_NONE,weight:3.5,opacity:.95,interactive:false,
         dashArray:v?null:'7 5'}).addTo(invLayer);a=b;}
   });
   var acc=[];drawFrontier(c,res,hit.ci,hit.m,invLayer,acc);
   L.marker([lat,lon]).addTo(invLayer);
   var nn=nearestNode(lat,lon);
   if(nn.n)L.circleMarker([nn.n.lat,nn.n.lon],{radius:11,color:'#4f46e5',weight:2,opacity:.85,
     fillColor:'#4f46e5',fillOpacity:.07,interactive:false}).addTo(invLayer);
   // hard zoom to the ±window stretch (fallback: plain street-level view of the point)
   try{
     var bb=L.latLngBounds([[lat,lon]]);acc.forEach(function(p){bb.extend(p);});
     if(nn.n&&nn.d<=400)bb.extend([nn.n.lat,nn.n.lon]);
     map.fitBounds(bb.pad(0.3),{maxZoom:17});
   }catch(e){map.setView([lat,lon],16);}
   // --- facts card (all deterministic; same fields the CountA facts API exposes) ---
   var powner=(c.co&&c.co[hit.ci]&&c.co[hit.ci][hit.si]!=null)?c.co[hit.ci][hit.si]:null;
   var varies=allOwners(c).length>1;
   var xd=c.xd||[],xf=c.xf||[],tot=xd.length,dth=0;
   for(i=0;i<xf.length;i++)if(xf[i])dth++;
   var ncl=Math.max.apply(null,c.cl)+1,clusterLen=0;
   res.comps.forEach(function(cj){clusterLen+=res.g.len[cj];});
   var ambiguous=alt&&(alt.d-hit.d)<=15;
   var ll2=lat.toFixed(5)+', '+lon.toFixed(5);
   var secNote='';
   if(ncl>1){
     secNote='<div class="row" style="color:var(--muted,#71717a)">This point is on a ~'+Math.round(clusterLen)+
       ' m section of '+c.disp+' — '+
       (c.rg?('one of '+ncl+' disconnected pieces (separated by real gaps — rail, etc.)')
            :('one of '+ncl+' sections (small centreline gaps)'))+
       '; the ±'+W+' m window stays on it.</div>';
   }
   var sigTxt=nn.n?(nn.n.sig==='y'?'signalized':(nn.n.sig==='n'?'not signalized':'signal status not yet analyzed')):'';
   invCardEl.innerHTML='<div class="inv-card"><h3>'+label+'</h3>'+
     '<div class="inv-coords">'+ll2+' <span style="cursor:pointer;color:var(--accent-ink,#4338ca)" title="copy" '+
       'onclick="navigator.clipboard&&navigator.clipboard.writeText(\''+ll2+'\')">⧉ copy</span></div>'+
     row('Road',c.disp+' <span style="color:var(--muted,#71717a)">— snapped '+Math.round(hit.d)+' m from your point</span>')+
     row('Owner',(powner==null?'unknown':ownerLabel(powner))+
       (varies?' <span style="color:var(--muted,#71717a)">(ownership varies along the corridor — see the map coloring)</span>':''))+
     row('Sidewalk (city inventory)',swStatus(swAt(c,hit.ci,hit.si)))+
     (ambiguous?'<div class="row na">Ambiguous: also '+Math.round(alt.d)+' m from '+alt.c.disp+'; counting '+c.disp+'.</div>':'')+
     ((!ambiguous&&hit.d>35)?'<div class="row na">Your point is '+Math.round(hit.d)+' m from the nearest road on record — it may not be on '+c.disp+'.</div>':'')+
     row('Crashes within ±'+W+' m',res.n+' ('+res.fat+' fatal)')+
     row('Whole road',tot+' incidents · '+dth+' deaths <span style="color:var(--muted,#71717a)">('+fmtMon(IDX.meta.dmin)+' – '+fmtMon(IDX.meta.dmax)+')</span>')+
     row('Nearest mapped intersection',nn.n?(nn.n.disp+' <span style="color:var(--muted,#71717a)">— '+Math.round(nn.d)+' m away · '+sigTxt+' · '+
       (nn.n.crashes>0?(nn.n.crashes+' crashes ('+nn.n.deaths+' fatal)'):'0 incidents reported')+'</span>'):na())+
     row('Nearest safe crossing',(nn.n&&nn.n.near_safe_ft!=null)?(nn.n.near_safe_ft+' ft (from the nearest mapped intersection)'):na())+
     secNote+
     '<div class="row" style="color:var(--muted,#71717a)">The two orange bars on the map mark ±'+W+' m along the road from your point '+
       '(crashes attributed to this road only, by network distance — not a straight-line radius). '+
       'Corridor coloring: outer glow = road owner; inner line = sidewalk status (solid blue = in city inventory, '+
       'dashed amber = none found; absence may reflect incomplete records). The thin ring marks the nearest mapped intersection.</div>'+
     invTimeTable(c)+DISCLAIMER+'</div>';
 }
 // Investigate input wiring (address / coordinates segmented control + Enter + button)
 var invMode='address',iA=document.getElementById('invSegAddr'),iC=document.getElementById('invSegCoord'),
     iIn=document.getElementById('invInput'),iGo=document.getElementById('invGo');
 function invApplyMode(){
   if(!iA)return;
   iA.className=(invMode==='address')?'on':'';
   iC.className=(invMode==='address')?'':'on';
   iIn.placeholder=(invMode==='address')?'e.g. 1779 Union Ave':'e.g. 35.137, -90.017';
 }
 function invRun(){
   if(!iIn)return;
   var q=iIn.value.trim();
   invClearErr();
   if(!q){invSetErr('Enter a location.');return;}
   if(invMode==='coord'){
     var mt=q.match(/(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)/);
     if(!mt){invSetErr('Type "lat, lon" — e.g. 35.137, -90.017');return;}
     var lat=parseFloat(mt[1]),lon=parseFloat(mt[2]);
     if(!inMemphis(lat,lon)){invSetErr(lat+', '+lon+' is outside the Memphis area — expected lat 34.94–35.42, lon -90.40 to -89.55.');return;}
     investigate(lat,lon,'Coordinates '+lat.toFixed(5)+', '+lon.toFixed(5));
     return;
   }
   iGo.disabled=true;iGo.textContent='Locating…';
   fetch('/api/geocode?address='+encodeURIComponent(q)).then(function(r){return r.json();}).then(function(j){
     iGo.disabled=false;iGo.textContent='Look up';
     if(!j||typeof j.lat!=='number'){throw 0;}
     investigate(j.lat,j.lon,j.matchedAddress||q);
   }).catch(function(){
     iGo.disabled=false;iGo.textContent='Look up';
     invSetErr('Couldn’t find that address. Address lookup needs the deployed geocoder (/api/geocode) — on a local file, use Coordinates mode instead.');
   });
 }
 if(iA){
   iA.onclick=function(){invMode='address';invApplyMode();iIn.focus();};
   iC.onclick=function(){invMode='coord';invApplyMode();iIn.focus();};
   iGo.onclick=invRun;
   iIn.addEventListener('keydown',function(e){if(e.key==='Enter')invRun();});
   invApplyMode();
 }
 // keep each view's overlays scoped: microscope layers only in Investigate; search highlights only elsewhere
 window.__onRoute=function(v){
   if(v==='investigate'){clear();}
   else{invLayer.clearLayers();}
 };
 window.__investigate=investigate;   // exposed for the shell / tests

 // ---- Deterministic fact API. Gathers the SAME facts a Count-A lookup computes -- snap, owner,
 // +/-window count, time windows, nearest intersection, nearest safe crossing -- as a plain
 // object. The Investigate view and the test harnesses build on it. Code-only; no judgment. ----
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
 window.CountA={facts:gatherFacts};   // deterministic facts API (Investigate + tests build on it)
})();
"""


if __name__ == "__main__":
    main()
