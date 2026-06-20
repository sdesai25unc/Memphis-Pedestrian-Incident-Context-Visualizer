r"""
05_download_streets.py
=====================

Downloads the FULL Memphis-area street network (street centerline) so we can
later attach a street name to every crash and draw clickable streets on a map.

Which layer (decided after browsing the city's GIS server):
  Service: Basemaps/Common_Services_PROD/MapServer, Layer 17 = "Streets".
  This is the city's full centerline layer (~86k segments region-wide). It has a
  ready-made full-name field (LABEL) plus the same component name fields as the
  state-routes layer we already use (PREDIR / NAME / TYPE / SUFDIR / SUBNAME /
  ALTNAME_1), and CITY_L / COUNTY_L for filtering.

  Candidates considered and REJECTED:
    - PW_Support_Layers/17 "Street State Routes" (1,652) - already downloaded; a
      state-route SUBSET, not the full network.
    - PW_Support_Layers/6 "Major Roads" (1,658) and /7 "Major Highways" (122) -
      subsets only.
    - Common_Services/16 "Major Roads" (5,098) - subset only.
    - PW_Support_Layers/8 "Road Centerline" (88,023) - also a full network, but
      cruder name fields (STRTDIR/STRTNAME/STRTDES, no prebuilt label) and an
      opaque MUNIC code that can't isolate Memphis. "Streets" was preferred.

Scope: Shelby County only (COUNTY_L='SHELBY', ~55k segments) - all of Memphis
plus a margin around the city limits, without the far-flung TN/MS/AR towns the
region-wide layer also contains.

What this script does:
  1. Asks the API how many Shelby-County street segments exist.
  2. Skips downloading if we already have that exact number saved.
  3. Pages through the layer (2,000 at a time) and saves each raw JSON page.
  4. Converts the ArcGIS line shapes to a GeoDataFrame, reprojects to lat/long,
     keeps ALL attributes, and saves data/raw/memphis_streets.geojson.
  5. Prints a summary (count, name fields, sample names, source CRS, choice).

Run it with:
    .\.venv\Scripts\python.exe scripts\05_download_streets.py
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
import sys
import time
import json
from pathlib import Path

import requests
import geopandas as gpd
from shapely.geometry import shape
from arcgis2geojson import arcgis2geojson


# ---------------------------------------------------------------------------
# SETTINGS
# ---------------------------------------------------------------------------

# Basemaps/Common_Services_PROD MapServer, Layer 17 = "Streets" (full centerline).
STREETS_API_URL = (
    "https://maps.memphistn.gov/mapping/rest/services/"
    "Basemaps/Common_Services_PROD/MapServer/17/query"
)

# Keep all of Shelby County (covers Memphis + a margin around the city limits).
WHERE_CLAUSE = "COUNTY_L='SHELBY'"

PAGE_SIZE = 2000
DELAY_BETWEEN_REQUESTS = 0.5

# The layer's shapes come back in Tennessee State Plane, US Feet (ArcGIS WKID
# 102736 = EPSG:2274). We read in that system and convert to lat/long on save.
SOURCE_CRS = "EPSG:2274"
OUTPUT_CRS = "EPSG:4326"

# The street-name fields we care about (for the summary). LABEL is the ready-made
# full display name; the rest are the components, matching the state-routes layer.
NAME_FIELDS = ["LABEL", "PREDIR", "NAME", "TYPE", "SUFDIR", "SUBNAME", "ALTNAME_1"]


# ---------------------------------------------------------------------------
# FILE PATHS
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
STREETS_GEOJSON_PATH = RAW_DIR / "memphis_streets.geojson"


# ---------------------------------------------------------------------------
# Ask the API how many matching segments exist right now.
# ---------------------------------------------------------------------------
def get_current_api_count():
    params = {"where": WHERE_CLAUSE, "returnCountOnly": "true", "f": "json"}
    response = requests.get(STREETS_API_URL, params=params, timeout=60)
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        raise RuntimeError(f"API returned an error on the count request: {data['error']}")
    return data["count"]


# ---------------------------------------------------------------------------
# Count how many segments we already have saved across page files.
# ---------------------------------------------------------------------------
def count_records_in_existing_pages():
    existing_pages = sorted(RAW_DIR.glob("memphis_streets_page_*.json"))
    total = 0
    for page_file in existing_pages:
        with open(page_file, "r", encoding="utf-8") as f:
            total += len(json.load(f).get("features", []))
    return total, existing_pages


# ---------------------------------------------------------------------------
# Download every page and save each as raw JSON.
# ---------------------------------------------------------------------------
def download_all_pages(expected_count):
    for old_file in RAW_DIR.glob("memphis_streets_page_*.json"):
        old_file.unlink()

    offset = 0
    page_number = 1
    total_downloaded = 0

    while True:
        params = {
            "where": WHERE_CLAUSE,
            "outFields": "*",
            "returnGeometry": "true",
            "f": "json",
            "resultRecordCount": PAGE_SIZE,
            "resultOffset": offset,
            "orderByFields": "OBJECTID ASC",
        }

        print(f"  Downloading page {page_number} (records starting at {offset})...")

        try:
            response = requests.get(STREETS_API_URL, params=params, timeout=120)
            response.raise_for_status()
            page_data = response.json()
        except Exception as problem:
            print()
            print("!!! DOWNLOAD STOPPED - a page failed to download.")
            print(f"!!! Failed on page {page_number}, record offset {offset}.")
            print(f"!!! Reason: {problem}")
            print("!!! The pages downloaded so far have been KEPT in data/raw/.")
            sys.exit(1)

        if "error" in page_data:
            print()
            print("!!! DOWNLOAD STOPPED - the API reported an error.")
            print(f"!!! Failed on page {page_number}, record offset {offset}.")
            print(f"!!! API error: {page_data['error']}")
            print("!!! The pages downloaded so far have been KEPT in data/raw/.")
            sys.exit(1)

        features = page_data.get("features", [])
        if not features:
            print("  Got an empty page - no more records. Done downloading.")
            break

        page_path = RAW_DIR / f"memphis_streets_page_{page_number:03d}.json"
        with open(page_path, "w", encoding="utf-8") as f:
            json.dump(page_data, f)
        print(f"  Saved {len(features)} records -> {page_path.name}")

        total_downloaded += len(features)

        if not page_data.get("exceededTransferLimit", False):
            print("  API says there are no more pages. Done downloading.")
            break

        offset += PAGE_SIZE
        page_number += 1
        time.sleep(DELAY_BETWEEN_REQUESTS)

    print(f"  Total segments downloaded: {total_downloaded} (API expected {expected_count}).")
    return total_downloaded


# ---------------------------------------------------------------------------
# Turn one ArcGIS feature's shape into a shapely geometry (or None).
# ---------------------------------------------------------------------------
def arcgis_feature_to_geometry(feature):
    arcgis_geometry = feature.get("geometry")
    if not arcgis_geometry:
        return None
    if not arcgis_geometry.get("paths") and not arcgis_geometry.get("rings"):
        return None
    geometry = shape(arcgis2geojson(arcgis_geometry))
    return None if geometry.is_empty else geometry


# ---------------------------------------------------------------------------
# Read all saved pages, keep ALL attributes, build a GeoDataFrame in lat/long.
# ---------------------------------------------------------------------------
def build_streets_geodataframe():
    page_files = sorted(RAW_DIR.glob("memphis_streets_page_*.json"))
    if not page_files:
        raise RuntimeError("No street page files found to read. Try downloading again.")

    rows = []
    geometries = []
    skipped_no_geometry = 0

    for page_file in page_files:
        with open(page_file, "r", encoding="utf-8") as f:
            page_data = json.load(f)
        for feature in page_data.get("features", []):
            geometry = arcgis_feature_to_geometry(feature)
            if geometry is None:
                skipped_no_geometry += 1
                continue
            # Keep ALL attributes - don't drop fields we're unsure about.
            rows.append(feature.get("attributes", {}))
            geometries.append(geometry)

    streets = gpd.GeoDataFrame(rows, geometry=geometries, crs=SOURCE_CRS)
    streets = streets.to_crs(OUTPUT_CRS)
    return streets, skipped_no_geometry


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    print("Memphis Pedestrian Safety - full street network download")
    print("-" * 70)
    print("Layer: Basemaps/Common_Services_PROD/MapServer/17 'Streets'")
    print(f"Scope: {WHERE_CLAUSE}")
    print("-" * 70)

    print("Checking the live segment count from the API...")
    api_count = get_current_api_count()
    print(f"  API currently has {api_count} street segments in scope.")

    existing_count, existing_pages = count_records_in_existing_pages()
    if existing_pages and existing_count == api_count:
        print(f"  We already have {existing_count} segments saved that match the "
              f"live count - skipping download and just reprocessing.")
    else:
        if existing_pages:
            print(f"  We have {existing_count} saved segments but the API now has "
                  f"{api_count} - re-downloading fresh.")
        else:
            print("  No saved street data found - downloading fresh.")
        print("Downloading...")
        download_all_pages(api_count)

    print("Converting street shapes and saving GeoJSON (keeping all attributes)...")
    streets, skipped_no_geometry = build_streets_geodataframe()
    streets.to_file(STREETS_GEOJSON_PATH, driver="GeoJSON")
    print(f"  Saved -> {STREETS_GEOJSON_PATH.name}")

    # --- SUMMARY -----------------------------------------------------------
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Chosen layer:        Common_Services_PROD/MapServer/17 'Streets'")
    print(f"Scope filter:        {WHERE_CLAUSE}")
    print(f"Source CRS:          {SOURCE_CRS} (saved reprojected to {OUTPUT_CRS})")
    print(f"Total segments:      {len(streets)}")
    print(f"Skipped (no geom):   {skipped_no_geometry}")
    print(f"Attributes kept:     {len(streets.columns) - 1} fields + geometry")

    present_name_fields = [c for c in NAME_FIELDS if c in streets.columns]
    print(f"Name field(s) used:  {present_name_fields}")
    print(f"  Primary display name field: LABEL")

    print()
    print("8-10 sample street names (LABEL):")
    sample = (streets["LABEL"].dropna().astype(str).str.strip())
    sample = sample[sample != ""].drop_duplicates().head(10).tolist()
    for nm in sample:
        print(f"  - {nm}")

    print()
    print("Candidates considered & REJECTED:")
    print("  - PW_Support_Layers/17 'Street State Routes' (1,652) - already have; subset")
    print("  - PW_Support_Layers/6 'Major Roads' (1,658) / 7 'Major Highways' (122) - subsets")
    print("  - Common_Services/16 'Major Roads' (5,098) - subset")
    print("  - PW_Support_Layers/8 'Road Centerline' (88,023) - full, but cruder names")
    print("=" * 70)


if __name__ == "__main__":
    main()
