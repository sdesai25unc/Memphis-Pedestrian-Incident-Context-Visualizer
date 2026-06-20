r"""
20_dedup_crossings.py
====================

Phase 3a / Phase 1 (final step) — DEDUP the raw TDOT pedestrian-signal heads +
push buttons into one "signalized pedestrian crossing" point per physical
intersection, and size the signal-covered corridor scope for Phase 2.

CONFIRMED THRESHOLDS (signed off 2026-06-16):
  - signal dedup radius          = 30 m  (single-linkage; one cluster per intersection)
  - covered-corridor definition  = a street carrying >= MIN_SIGNALS_PER_CORRIDOR
                                    inventoried signals is "signal-covered",
                                    regardless of City/TDOT ownership. (Phase 2
                                    will mark intersections off every covered
                                    corridor as 'no_signal_coverage' — absence of
                                    data is NOT 'no'.)
(Phase-2 thresholds, for reference: crash->node 30 m, signal->node 30 m,
 intersections = junctions of 2+ named through-roads on covered corridors.)

Reads:  data/raw/ped_signals.geojson, data/processed/road_ownership_rulebook.geojson
Writes: data/processed/signalized_crossings_dedup.geojson  (one point per crossing)
        data/processed/signal_covered_corridors.csv         (the covered-corridor list)

Run it with:
    .\.venv\Scripts\python.exe scripts\20_dedup_crossings.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
PED = RAW / "ped_signals.geojson"
RULEBOOK = PROC / "road_ownership_rulebook.geojson"
CROSSINGS_OUT = PROC / "signalized_crossings_dedup.geojson"
CORRIDORS_OUT = PROC / "signal_covered_corridors.csv"

CRS_M = "EPSG:32136"
DEDUP_RADIUS = 30.0
MIN_SIGNALS_PER_CORRIDOR = 4

CITY = "City of Memphis"
TDOT = "TDOT state route"
LIM = {"Interstate (TDOT)", "Interstate ramp (TDOT)", "Limited-access (TDOT)"}
HEAD = "Pedestrian Signal"
BUTTON = "Push Button"


def cat3(o):
    return "City" if o == CITY else (TDOT if o == TDOT else "Limited-access")


def cluster_single_linkage(gdf, radius):
    """Union-find single-linkage clustering: connect points within `radius`."""
    g = gdf.reset_index(drop=True)
    g["pid"] = range(len(g))
    buf = gpd.GeoDataFrame(g[["pid"]].copy(), geometry=g.buffer(radius), crs=g.crs)
    pairs = gpd.sjoin(g[["pid", "geometry"]], buf, predicate="intersects", how="inner")
    parent = list(range(len(g)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for a, b in zip(pairs["pid_left"].values, pairs["pid_right"].values):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    return np.array([find(i) for i in range(len(g))])


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ped = gpd.read_file(PED).to_crs(CRS_M).reset_index(drop=True)
    print(f"raw signal points: {len(ped)} "
          f"({int((ped.FEATURE_DESCRIPTION == HEAD).sum())} heads + "
          f"{int((ped.FEATURE_DESCRIPTION == BUTTON).sum())} buttons)")

    # attach nearest rulebook segment (ownership + street) to each signal
    print("loading rulebook + snapping signals...")
    rb = gpd.read_file(RULEBOOK).to_crs(CRS_M)
    snap = gpd.sjoin_nearest(ped[["FEATURE_DESCRIPTION", "ROUTE_NAME", "geometry"]],
                             rb[["Ownership", "Street_Name", "geometry"]],
                             how="left", distance_col="dseg")
    snap = snap[~snap.index.duplicated(keep="first")]
    ped["Ownership"] = snap["Ownership"].values
    ped["Street_Name"] = snap["Street_Name"].values

    # ---- DEDUP: single-linkage @ 30 m ----
    lab = cluster_single_linkage(ped, DEDUP_RADIUS)
    ped["cluster"] = lab
    xy = np.c_[ped.geometry.x.values, ped.geometry.y.values]
    recs = []
    for cl, idx in pd.Series(range(len(ped))).groupby(lab).groups.items():
        idx = list(idx)
        sub = ped.iloc[idx]
        cx, cy = xy[idx, 0].mean(), xy[idx, 1].mean()
        routes = sorted(set(sub.ROUTE_NAME.dropna().astype(str)))
        dom_route = sub.ROUTE_NAME.mode().iloc[0] if not sub.ROUTE_NAME.mode().empty else ""
        dom_street = sub.Street_Name.mode().iloc[0] if not sub.Street_Name.mode().empty else ""
        recs.append({
            "crossing_id": int(cl),
            "n_signals": len(sub),
            "n_heads": int((sub.FEATURE_DESCRIPTION == HEAD).sum()),
            "n_buttons": int((sub.FEATURE_DESCRIPTION == BUTTON).sum()),
            "dom_route": dom_route,
            "n_routes": len(routes),
            "dom_street": dom_street,
            "x": cx, "y": cy,
        })
    cross = gpd.GeoDataFrame(recs, geometry=gpd.points_from_xy([r["x"] for r in recs],
                                                               [r["y"] for r in recs]), crs=CRS_M)
    cross = cross.drop(columns=["x", "y"])
    cross = cross.sort_values("crossing_id").reset_index(drop=True)
    cross["crossing_id"] = range(1, len(cross) + 1)
    cross.to_crs("EPSG:4326").to_file(CROSSINGS_OUT, driver="GeoJSON")
    print(f"\nDEDUP: {len(ped)} signal points -> {len(cross)} signalized crossings "
          f"(radius {DEDUP_RADIUS:.0f} m) -> {CROSSINGS_OUT.name}")
    print(f"  crossings with a head: {(cross.n_heads > 0).sum()}; "
          f"median signals/crossing: {int(cross.n_signals.median())}")

    # ---- COVERED-CORRIDOR scope (streets with >= MIN signals) ----
    by_street = ped.groupby("Street_Name").agg(
        signals=("FEATURE_DESCRIPTION", "size"),
        own=("Ownership", lambda s: cat3(s.mode().iloc[0]) if not s.mode().empty else "")
    ).sort_values("signals", ascending=False)
    covered = by_street[by_street["signals"] >= MIN_SIGNALS_PER_CORRIDOR].copy()
    covered.to_csv(CORRIDORS_OUT)
    print(f"\nCOVERED CORRIDORS (>= {MIN_SIGNALS_PER_CORRIDOR} signals on the street): "
          f"{len(covered)} streets -> {CORRIDORS_OUT.name}")
    print(f"  signals on covered corridors: {int(covered['signals'].sum())} of {len(ped)} "
          f"({covered['signals'].sum()/len(ped)*100:.1f}%)")
    print(f"  by our ownership of the corridor: {covered['own'].value_counts().to_dict()}")
    print("  top covered corridors (street | signals | our-owner):")
    for nm, r in covered.head(20).iterrows():
        print(f"    {str(nm)[:26]:26s} {int(r['signals']):4d}  {r['own']}")
    print(f"  streets dropped as below-threshold (<{MIN_SIGNALS_PER_CORRIDOR} signals): "
          f"{len(by_street) - len(covered)} streets, "
          f"{int(by_street['signals'].sum() - covered['signals'].sum())} signals")

    print("\nPhase 1 complete. STOP — awaiting go-ahead for Phase 2 "
          "(intersection nodes, crash attributes, map, stats).")


if __name__ == "__main__":
    main()
