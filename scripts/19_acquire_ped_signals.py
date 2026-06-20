r"""
19_acquire_ped_signals.py
========================

Phase 3a / Phase 1 — DATA ACQUISITION + inspection (no dedup, no coverage yet).

Downloads the TDOT ADA Asset Data "Pedestrian Signal" layer (and, once, the
"Crosswalks" layer to confirm the interstate-only pattern) for Shelby County, and
prints the structure we need to ground the Phase-1 thresholds:
  - feature-type breakdown (signal heads vs push buttons),
  - route-name coverage,
  - nearest-neighbour distance distribution (how tightly heads/buttons cluster at
    one intersection — informs the dedup radius),
  - crosswalks route/feature breakdown (interstate-only check).

Source: ArcGIS Feature Service resolved from geodata.tn.gov Hub item
69511fa73a584e2bb37acfa85b177fa5 -> ADA_Asset_Data/FeatureServer
  layer 1 = Pedestrian Signal, layer 2 = Crosswalks.

Writes (data/raw, raw downloads — never hand-edit):
  data/raw/ped_signals.geojson        (Shelby pedestrian-signal points, EPSG:4326)
  data/raw/crosswalks_shelby.geojson  (Shelby crosswalks, EPSG:4326)

Run it with:
    .\.venv\Scripts\python.exe scripts\19_acquire_ped_signals.py
"""

import sys
import time
from pathlib import Path

import requests
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
BASE = "https://services2.arcgis.com/nf3p7v7Zy4fTOh6M/arcgis/rest/services/ADA_Asset_Data/FeatureServer"
PED_LAYER, XWALK_LAYER = 1, 2
COUNTY = "SHELBY"
SHELBY_BBOX = (-90.31, 34.99, -89.61, 35.42)   # lon_min, lat_min, lon_max, lat_max
PAGE = 2000
CRS_M = "EPSG:32136"

PED_OUT = RAW / "ped_signals.geojson"
XWALK_OUT = RAW / "crosswalks_shelby.geojson"


def _count(layer, where):
    r = requests.get(f"{BASE}/{layer}/query",
                     params={"where": where, "returnCountOnly": "true", "f": "json"}, timeout=60)
    r.raise_for_status()
    return r.json().get("count", 0)


def fetch_layer(layer, label):
    """Pull all Shelby features of a layer as a GeoDataFrame (EPSG:4326)."""
    where = f"COUNTY_NAME='{COUNTY}'"
    n = _count(layer, where)
    use_bbox = n == 0
    if use_bbox:
        print(f"  [{label}] COUNTY_NAME='{COUNTY}' returned 0 — falling back to Shelby bbox.")
    feats = []
    offset = 0
    while True:
        params = {
            "where": where if not use_bbox else "1=1",
            "outFields": "*", "returnGeometry": "true", "outSR": "4326",
            "resultRecordCount": PAGE, "resultOffset": offset,
            "orderByFields": "OBJECTID", "f": "json",
        }
        if use_bbox:
            params.update({
                "geometry": ",".join(map(str, SHELBY_BBOX)),
                "geometryType": "esriGeometryEnvelope", "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
            })
        r = requests.get(f"{BASE}/{layer}/query", params=params, timeout=120)
        r.raise_for_status()
        js = r.json()
        if "error" in js:
            raise RuntimeError(f"API error: {js['error']}")
        batch = js.get("features", [])
        if not batch:
            break
        feats.extend(batch)
        print(f"  [{label}] fetched {len(feats)} ...")
        if len(batch) < PAGE:
            break
        offset += PAGE
        time.sleep(0.4)

    rows, geoms = [], []
    for ft in feats:
        g = ft.get("geometry") or {}
        x, y = g.get("x"), g.get("y")
        a = ft["attributes"]
        if x is None or y is None:          # fall back to the lat/long fields
            x, y = a.get("LONGITUDE_DD"), a.get("LATITUDE_DD")
        if x is None or y is None:
            continue
        rows.append(a)
        geoms.append(Point(x, y))
    gdf = gpd.GeoDataFrame(rows, geometry=geoms, crs="EPSG:4326")
    return gdf


def vc(gdf, col, top=20):
    if col not in gdf.columns:
        return f"(no {col})"
    return gdf[col].value_counts(dropna=False).head(top).to_dict()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    RAW.mkdir(parents=True, exist_ok=True)

    # ---- Pedestrian Signal ----
    print("=== Pedestrian Signal (layer 1) ===")
    ped = fetch_layer(PED_LAYER, "ped")
    ped.to_file(PED_OUT, driver="GeoJSON")
    print(f"  saved {len(ped)} points -> {PED_OUT.name}")
    print(f"  COUNTY_NAME: {vc(ped, 'COUNTY_NAME')}")
    print(f"  FEATURE_DESCRIPTION: {vc(ped, 'FEATURE_DESCRIPTION')}")
    print(f"  FEATURE_TYPE: {vc(ped, 'FEATURE_TYPE')}")
    print(f"  FEATURE_CHARACTER_CODE: {vc(ped, 'FEATURE_CHARACTER_CODE')}")
    print(f"  LOCATION_DESCRIPTION: {vc(ped, 'LOCATION_DESCRIPTION', 12)}")
    print(f"  distinct ROUTE_NAME: {ped['ROUTE_NAME'].nunique() if 'ROUTE_NAME' in ped else 'n/a'}; "
          f"top: {vc(ped, 'ROUTE_NAME', 12)}")

    # nearest-neighbour distance distribution (informs dedup radius)
    pm = ped.to_crs(CRS_M)
    coords = list(zip(pm.geometry.x, pm.geometry.y))
    try:
        from scipy.spatial import cKDTree
        tree = cKDTree(coords)
        d, _ = tree.query(coords, k=2)       # k=2: nearest other point
        nn = pd.Series(d[:, 1])
        print("\n  nearest-neighbour distance (m) among signal points:")
        for q in [0.10, 0.25, 0.50, 0.75, 0.90, 0.95]:
            print(f"    p{int(q*100):02d} = {nn.quantile(q):6.1f}")
        print(f"    within 5 m: {(nn<=5).mean()*100:.0f}%  | <=15 m: {(nn<=15).mean()*100:.0f}%  "
              f"| <=25 m: {(nn<=25).mean()*100:.0f}%  | <=40 m: {(nn<=40).mean()*100:.0f}%")
    except Exception as e:
        print(f"  (nearest-neighbour calc skipped: {e})")

    # ---- Crosswalks (confirm interstate-only) ----
    print("\n=== Crosswalks (layer 2) — interstate-only confirmation ===")
    xw = fetch_layer(XWALK_LAYER, "xwalk")
    xw.to_file(XWALK_OUT, driver="GeoJSON")
    print(f"  saved {len(xw)} features -> {XWALK_OUT.name}")
    print(f"  ROUTE_NAME: {vc(xw, 'ROUTE_NAME', 25)}")
    print(f"  FEATURE_DESCRIPTION: {vc(xw, 'FEATURE_DESCRIPTION')}")

    print("\nDONE (acquisition only — no dedup/coverage yet; that comes after threshold sign-off).")


if __name__ == "__main__":
    main()
