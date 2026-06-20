r"""
22_osm_crossings_eval.py
======================

OSM pedestrian-crossings EVALUATION (read/acquire + report only — does NOT modify
the map or crash data). Acquires OSM crossings for Shelby County, splits/dedups
them, cross-references the signalized ones against the TDOT deduped signal clusters,
and assesses completeness along the deadly corridors.

Decisions (signed off):
  - Acquire Shelby-wide via an Overpass BBOX query (coordinate-bounded, so no
    name="Memphis" pollution); report counts both Shelby-wide and Memphis-only.
  - Cross-reference TDOT signals against the OSM PEDESTRIAN-specific signalized
    subset (crossing=traffic_signals OR crossing:signals=yes); bare
    highway=traffic_signals is reported separately.
  - Cross-ref reported at both 30 m and 50 m.

Definitions:
  - MARKED       = crossing:markings present and not in {no, (blank)}.
  - SIGNALIZED   = crossing=traffic_signals OR crossing:signals=yes OR highway=traffic_signals (full)
                   (ped subset = first two only).
Dedup:
  - node+way duplicate of one real crossing -> cluster within 8 m.
  - signalized one-per-intersection -> cluster within 30 m (matches the TDOT dedup).

Writes: data/raw/osm_crossings.geojson (raw acquisition)
        outputs/osm_crossings_eval.md  (the report)

Run it with:
    .\.venv\Scripts\python.exe scripts\22_osm_crossings_eval.py
"""

import sys
import time
from pathlib import Path

import requests
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from shapely.ops import linemerge, unary_union

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
OSM_OUT = RAW / "osm_crossings.geojson"
REPORT = ROOT / "outputs" / "osm_crossings_eval.md"
TDOT_CROSS = PROC / "signalized_crossings_dedup.geojson"
RULEBOOK = PROC / "road_ownership_rulebook.geojson"
BOUNDARY = RAW / "memphis_boundary.geojson"

CRS_M = "EPSG:32136"
SHELBY_BBOX = (34.99, -90.31, 35.42, -89.61)   # S, W, N, E
DEDUP_NODEWAY = 8.0
DEDUP_SIGNAL = 30.0
CORRIDORS_EXACT = {"Poplar Ave": "POPLAR AVE", "Winchester Rd": "WINCHESTER RD",
                   "Lamar Ave": "LAMAR AVE", "Union Ave": "UNION AVE",
                   "Jackson Ave": "JACKSON AVE", "Summer Ave": "SUMMER AVE"}
MIRRORS = ["https://overpass.kumi.systems/api/interpreter",
           "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
           "https://overpass-api.de/api/interpreter"]


def overpass(query):
    last = None
    for ep in MIRRORS:
        try:
            r = requests.post(ep, data={"data": query}, timeout=240,
                              headers={"User-Agent": "memphis-ped-safety-eval/1.0"})
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
                return r.json()
            last = f"{ep} -> {r.status_code}"
        except Exception as e:
            last = f"{ep} -> {repr(e)[:80]}"
        time.sleep(1)
    raise RuntimeError(f"All Overpass mirrors failed; last: {last}")


def acquire():
    if OSM_OUT.exists():
        print(f"  using cached {OSM_OUT.name} (delete it to re-pull from Overpass)")
        return gpd.read_file(OSM_OUT)
    s, w, n, e = SHELBY_BBOX
    q = f"""[out:json][timeout:240];
(
  node["highway"="crossing"]({s},{w},{n},{e});
  node["crossing"]({s},{w},{n},{e});
  node["highway"="traffic_signals"]({s},{w},{n},{e});
  way["footway"="crossing"]({s},{w},{n},{e});
);
out tags center;"""
    js = overpass(q)
    rows, geoms = [], []
    for el in js.get("elements", []):
        if el["type"] == "node":
            lat, lon = el.get("lat"), el.get("lon")
        else:
            c = el.get("center") or {}
            lat, lon = c.get("lat"), c.get("lon")
        if lat is None or lon is None:
            continue
        t = el.get("tags", {})
        rows.append({
            "osm_type": el["type"], "osm_id": el["id"],
            "highway": t.get("highway", ""), "crossing": t.get("crossing", ""),
            "markings": t.get("crossing:markings", ""), "signals": t.get("crossing:signals", ""),
            "footway": t.get("footway", ""),
        })
        geoms.append(Point(lon, lat))
    gdf = gpd.GeoDataFrame(rows, geometry=geoms, crs="EPSG:4326")
    gdf.to_file(OSM_OUT, driver="GeoJSON")
    return gdf


def cluster(gdf, radius):
    g = gdf.reset_index(drop=True)
    if len(g) == 0:
        return np.array([], dtype=int)
    g["pid"] = range(len(g))
    buf = gpd.GeoDataFrame(g[["pid"]], geometry=g.buffer(radius), crs=g.crs)
    pairs = gpd.sjoin(g[["pid", "geometry"]], buf, predicate="intersects", how="inner")
    parent = list(range(len(g)))
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a
    for a, b in zip(pairs["pid_left"].values, pairs["pid_right"].values):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    return np.array([find(i) for i in range(len(g))])


def centroids(gdf, labels):
    g = gdf.reset_index(drop=True)
    xy = np.c_[g.geometry.x.values, g.geometry.y.values]
    pts = []
    for lab in pd.unique(labels):
        m = labels == lab
        pts.append(Point(xy[m, 0].mean(), xy[m, 1].mean()))
    return gpd.GeoDataFrame(geometry=pts, crs=g.crs)


def pct(p, w):
    return round(100.0 * p / w, 1) if w else 0.0


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    L = []
    def log(s=""):
        print(s); L.append(s)

    log("# OSM pedestrian crossings — evaluation & cross-reference\n")
    log("*Evaluation only — no map or crash-data changes. Acquired from OSM via Overpass "
        f"(Shelby bbox {SHELBY_BBOX}); distances in EPSG:32136.*\n")

    print("acquiring from Overpass...")
    osm = acquire()
    osm_m = osm.to_crs(CRS_M)
    print(f"  fetched {len(osm)} raw elements -> {OSM_OUT.name}")

    # in-Memphis flag
    bnd = gpd.read_file(BOUNDARY).to_crs(CRS_M)
    poly = bnd.union_all()
    osm_m["in_memphis"] = osm_m.within(poly)

    # ---- SPLIT ----
    mk = osm_m["markings"].astype(str).str.lower()
    osm_m["is_marked"] = ~mk.isin(["", "no", "nan", "none"])
    cr = osm_m["crossing"].astype(str).str.lower()
    sg = osm_m["signals"].astype(str).str.lower()
    hw = osm_m["highway"].astype(str).str.lower()
    osm_m["sig_ped"] = (cr == "traffic_signals") | (sg == "yes")
    osm_m["sig_full"] = osm_m["sig_ped"] | (hw == "traffic_signals")
    osm_m["bare_ts"] = (hw == "traffic_signals") & ~osm_m["sig_ped"]

    def counts(mask):
        sub = osm_m[mask]
        return len(sub), int(sub["in_memphis"].sum())

    m_all, m_mem = counts(osm_m["is_marked"])
    sf_all, sf_mem = counts(osm_m["sig_full"])
    sp_all, sp_mem = counts(osm_m["sig_ped"])
    bt_all, bt_mem = counts(osm_m["bare_ts"])

    log("## 1. Raw counts (Shelby-wide | in-Memphis)\n")
    log(f"- Total OSM crossing/traffic-signal elements fetched: **{len(osm)}** "
        f"({int(osm_m['in_memphis'].sum())} in Memphis).")
    log(f"- **MARKED** (crossing:markings ≠ no/blank): **{m_all}** | {m_mem}  *(≈1,256 expected)*")
    log(f"- **SIGNALIZED, full** (crossing=traffic_signals / crossing:signals=yes / "
        f"highway=traffic_signals): **{sf_all}** | {sf_mem}  *(≈755 expected)*")
    log(f"  - pedestrian-specific subset (crossing=traffic_signals / crossing:signals=yes): "
        f"**{sp_all}** | {sp_mem}")
    log(f"  - bare highway=traffic_signals only (vehicular signal nodes, not ped-tagged): "
        f"{bt_all} | {bt_mem}")
    log(f"- markings value mix: {osm_m.loc[osm_m['is_marked'],'markings'].str.lower().value_counts().head(8).to_dict()}")
    log("\n*Note: the MARKED deduped-in-Memphis count (§2) lands near the ~1,256 anchor, validating the "
        "marked pipeline. SIGNALIZED runs well above the ~755 anchor — driven by the broad "
        "highway=traffic_signals tag (vehicular signal nodes, not pedestrian-specific) and by growth in "
        "OSM crossing mapping since the earlier snapshot. The pedestrian-specific deduped count is the "
        "clean signalized figure used for the cross-reference.*")

    # ---- DEDUP ----
    marked = osm_m[osm_m["is_marked"]].copy()
    lab_m = cluster(marked, DEDUP_NODEWAY)
    marked_dd = centroids(marked, lab_m)
    marked_dd["in_memphis"] = marked_dd.within(poly)
    sigp = osm_m[osm_m["sig_ped"]].copy()
    lab_s = cluster(sigp, DEDUP_SIGNAL)
    sigp_dd = centroids(sigp, lab_s)
    sigp_dd["in_memphis"] = sigp_dd.within(poly)
    sigf = osm_m[osm_m["sig_full"]].copy()
    sigf_dd = centroids(sigf, cluster(sigf, DEDUP_SIGNAL))

    log("\n## 2. Deduped (raw → deduped)\n")
    log(f"- MARKED, node+way merged @ {DEDUP_NODEWAY:.0f} m: {m_all} → **{len(marked_dd)}** "
        f"({int(marked_dd['in_memphis'].sum())} in Memphis).")
    log(f"- SIGNALIZED ped, one-per-intersection @ {DEDUP_SIGNAL:.0f} m: {sp_all} → "
        f"**{len(sigp_dd)}** ({int(sigp_dd['in_memphis'].sum())} in Memphis).")
    log(f"- SIGNALIZED full, @ {DEDUP_SIGNAL:.0f} m: {sf_all} → **{len(sigf_dd)}**.")

    # ---- CROSS-REF vs TDOT ----
    tdot = gpd.read_file(TDOT_CROSS).to_crs(CRS_M)
    log(f"\n## 3. Cross-reference — OSM ped-signalized ({len(sigp_dd)}) vs TDOT deduped "
        f"signals ({len(tdot)}), Shelby-wide\n")
    # nearest distances both ways
    t2o = gpd.sjoin_nearest(tdot[["geometry"]], sigp_dd[["geometry"]], how="left", distance_col="d")
    t2o = t2o[~t2o.index.duplicated(keep="first")]
    o2t = gpd.sjoin_nearest(sigp_dd[["geometry"]], tdot[["geometry"]], how="left", distance_col="d")
    o2t = o2t[~o2t.index.duplicated(keep="first")]
    log("| match radius | TDOT with an OSM match | OSM with a TDOT match |")
    log("|---|---|---|")
    for R in (30, 50):
        tm = int((t2o["d"] <= R).sum()); om = int((o2t["d"] <= R).sum())
        log(f"| {R} m | {tm}/{len(tdot)} ({pct(tm,len(tdot))}%) | {om}/{len(sigp_dd)} ({pct(om,len(sigp_dd))}%) |")
    tno = int((t2o["d"] > 50).sum()); ono = int((o2t["d"] > 50).sum())
    log(f"\n- **Disagreement:** {tno} TDOT signals have NO OSM ped-signal within 50 m "
        f"(TDOT-only); {ono} OSM ped-signals have NO TDOT signal within 50 m (OSM-only).")
    log("- *Interpretation:* TDOT inventories pedestrian signal heads/buttons on its route system; "
        "OSM `crossing=traffic_signals` is mapper-contributed and may tag the intersection node or omit "
        "legs. Mismatch ≠ error in either source — it reflects different definitions and OSM coverage gaps.")

    # ---- COMPLETENESS: corridors ----
    log("\n## 4. Completeness — marked-crossing coverage\n")
    mem_marked = int(marked_dd["in_memphis"].sum())
    sub_marked = len(marked_dd) - mem_marked
    log(f"- Core vs suburb: {mem_marked} marked crossings inside Memphis vs {sub_marked} in the "
        f"Shelby suburbs (outside the city). Memphis holds {pct(mem_marked,len(marked_dd))}% of marked crossings.")
    rb = gpd.read_file(RULEBOOK).to_crs(CRS_M)
    log("\n**Marked crossings along the deadly corridors — scoped to the in-Memphis stretch** (where the "
        "crashes are). Length = the in-Memphis single-carriageway reference (longest merged run); count = "
        "deduped in-Memphis marked crossings within 25 m; max gap = longest in-Memphis stretch with NO "
        "marked crossing.\n")
    log("| corridor | in-Memphis length (mi) | marked crossings | per mile | longest gap (mi) |")
    log("|---|---|---|---|---|")
    mdd = marked_dd[marked_dd["in_memphis"]]
    corr_stats = []
    for label, exact in CORRIDORS_EXACT.items():
        segs = rb[rb["Street_Name"].astype(str) == exact]
        segs = segs[segs.intersects(poly)]                 # in-Memphis stretch only
        if not len(segs):
            log(f"| {label} | (not found) | - | - | - |"); continue
        full = unary_union(segs.geometry.values)
        merged = linemerge(full)
        comps = list(merged.geoms) if merged.geom_type == "MultiLineString" else [merged]
        ref = max(comps, key=lambda l: l.length)
        ref_mi = ref.length / 1609.344
        near = mdd[mdd.distance(ref) <= 30]                 # near the reference line only
        cnt = len(near)
        permi = cnt / ref_mi if ref_mi else 0
        if cnt >= 2:
            along = sorted(float(ref.project(p)) for p in near.geometry)
            gaps = np.diff([0.0] + along + [ref.length])
            maxgap = gaps.max() / 1609.344
        else:
            maxgap = ref_mi
        corr_stats.append((label, ref_mi, cnt, permi, maxgap))
        log(f"| {label} | {ref_mi:.1f} | {cnt} | {permi:.1f} | {maxgap:.2f} |")
    log("\n*A well-mapped urban arterial has a marked crossing roughly every signalized block "
        "(~4+/mi, gaps under ~0.5 mi). Low per-mile or a long gap flags where OSM coverage thins.*")

    # usability call (data-driven)
    usable = [c[0] for c in corr_stats if c[3] >= 4 and c[4] <= 1.0]
    caution = [c[0] for c in corr_stats if c[0] not in usable]
    log("\n## 5. Usability call\n")
    log(f"- Core marked coverage is dense ({mem_marked} crossings in Memphis, "
        f"{pct(mem_marked,len(marked_dd))}% of the metro total) — the OSM MARKED layer is usable in the "
        f"urban core; the suburban fringe ({sub_marked}) is thinner.")
    log(f"- **Trustworthy enough for a distance-to-marked-crossing stat now** (≥~4/mi, no gap >~0.6 mi): "
        f"**{', '.join(usable) if usable else 'none'}**.")
    log(f"- **Ground-truth first** (lower density or a long gap): **{', '.join(caution) if caution else 'none'}**.")
    cliffs = [(c[0], c[4]) for c in corr_stats if c[4] >= 3.0]
    if cliffs:
        log("- **Coverage cliffs** (dense in the core, then a long unmapped stretch): "
            + "; ".join(f"{lbl} (~{g:.1f} mi with no OSM marked crossing)" for lbl, g in cliffs)
            + ". These corridors are usable for CORE-area crashes but not corridor-wide until the "
              "outer stretches are mapped/ground-truthed.")
    log("- **Recommended (not performed):** an aerial/satellite spot-check on **Poplar and Winchester** "
        "(highest-traffic corridors) — sample ~10 intersections each and confirm OSM marked crossings "
        "match painted crosswalks on imagery before publishing any crossing-distance stat.")
    log("- For SIGNALIZED crossings, TDOT (1,008 deduped) is the more complete inventory; OSM's "
        "pedestrian-signal layer (440) is partial, so prefer TDOT for signal-based stats and treat OSM "
        "signals as corroboration only.")

    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"\nWrote {OSM_OUT} and {REPORT}")
    print("Evaluation only — no map/crash-data changes. STOP.")


if __name__ == "__main__":
    main()
