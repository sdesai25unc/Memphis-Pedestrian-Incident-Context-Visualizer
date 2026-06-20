r"""
02_download_roads.py
====================

PHASE 3 (part 1) of the Memphis Pedestrian Safety project.

What this script does, in plain English:
  1. Downloads two map layers published by City of Memphis Public Works:
       - Layer 17 = STATE ROUTES (the TDOT-owned roads inside Memphis), as
         individual line segments.
       - Layer 15 = the CITY OF MEMPHIS BOUNDARY (one big shape that outlines
         the city limits).
  2. For the state routes, it first asks the API how many segments exist, and
     skips the download if we already have that exact number saved.
  3. It saves every raw API response untouched as JSON in data/raw/.
  4. It converts the map shapes (which arrive in a Tennessee-specific coordinate
     system measured in feet) into standard latitude/longitude, and writes two
     clean files the next script can read:
       - data/raw/state_routes.geojson    (the road lines)
       - data/raw/memphis_boundary.geojson (the city outline)
  5. It prints a short summary so we can confirm everything loaded correctly.

It does NOT do any distance math or classification - that is script 03.

Run it with:
    .\.venv\Scripts\python.exe scripts\02_download_roads.py
"""

# ---------------------------------------------------------------------------
# Imports: toolkits Python loads so we can use their features.
# ---------------------------------------------------------------------------
import sys                          # lets us stop the program with a clear message
import time                         # lets us pause politely between API requests
import json                         # reads/writes JSON files (the API's format)
from pathlib import Path            # a clean, modern way to handle file paths

import requests                     # downloads data from the web (the API)
import geopandas as gpd             # tables that also understand map shapes
from shapely.geometry import shape  # turns GeoJSON shapes into real geometry objects
from shapely import union_all       # merges many shapes into one combined shape
from arcgis2geojson import arcgis2geojson  # converts ArcGIS shapes -> GeoJSON shapes


# ---------------------------------------------------------------------------
# SETTINGS - everything you might want to change lives here at the top.
# ---------------------------------------------------------------------------

# City of Memphis Public Works "PW_Support_Layers" map service.
# Layer 17 = State Routes (TDOT roads).  Layer 15 = City of Memphis Boundary.
ROADS_API_URL = (
    "https://maps.memphistn.gov/mapping/rest/services/"
    "PublicWorks/PW_Support_Layers/MapServer/17/query"
)
BOUNDARY_API_URL = (
    "https://maps.memphistn.gov/mapping/rest/services/"
    "PublicWorks/PW_Support_Layers/MapServer/15/query"
)

# This layer is already pre-filtered to state routes, so we take everything.
WHERE_CLAUSE = "1=1"

# The API returns at most 2000 records per request, so we page through them.
PAGE_SIZE = 2000

# A short, polite pause (seconds) between page requests.
DELAY_BETWEEN_REQUESTS = 0.5

# The road columns we keep (the layer has many more; these are what we use).
ROAD_FIELDS_WE_KEEP = [
    "NAME",             # street name (e.g. "JACKSON")
    "TYPE",             # street type (e.g. "AVE")
    "PREDIR",           # direction prefix (e.g. "N")
    "SUBNAME",          # alternate / sub name
    "ALTNAME_1",        # state route number (e.g. "3" means SR-3)
    "F_System",         # functional class (Principal Arterial, Freeway, etc.)
    "SPDLIMIT",         # speed limit
    "LANES",            # number of lanes
    "Council_District", # Memphis city council district
    "State_Route",      # always "Yes" on this layer
    "Segment_ID",       # the segment's own id
    "OBJECTID",         # the layer's internal row id
]

# The state-route layer's shapes come back in Tennessee State Plane, US Feet.
# (ArcGIS calls it WKID 102736; the standard EPSG code for the same thing is
# 2274.) We read the shapes in this system, then convert to lat/long below.
SOURCE_CRS = "EPSG:2274"

# The clean, standard coordinate system we save everything in (plain lat/long),
# so the crash data (also lat/long) lines up with these roads.
OUTPUT_CRS = "EPSG:4326"


# ---------------------------------------------------------------------------
# FILE PATHS - figured out relative to this script.
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"

ROADS_GEOJSON_PATH = RAW_DIR / "state_routes.geojson"
BOUNDARY_JSON_PATH = RAW_DIR / "memphis_boundary.json"
BOUNDARY_GEOJSON_PATH = RAW_DIR / "memphis_boundary.geojson"


# ===========================================================================
# PART 1: THE STATE ROUTES LAYER
# ===========================================================================

# ---------------------------------------------------------------------------
# Ask the API how many state-route segments exist right now.
# ---------------------------------------------------------------------------
def get_current_api_count():
    """Return the live count of state-route segments from the API."""
    params = {
        "where": WHERE_CLAUSE,
        "returnCountOnly": "true",   # ask ONLY for the count, not the data
        "f": "json",
    }
    response = requests.get(ROADS_API_URL, params=params, timeout=60)
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        raise RuntimeError(f"API returned an error on the count request: {data['error']}")
    return data["count"]


# ---------------------------------------------------------------------------
# Count how many segments we already have saved across page files on disk.
# ---------------------------------------------------------------------------
def count_records_in_existing_pages():
    """Total the records stored in any state_routes_page_*.json already saved."""
    existing_pages = sorted(RAW_DIR.glob("state_routes_page_*.json"))
    total = 0
    for page_file in existing_pages:
        with open(page_file, "r", encoding="utf-8") as f:
            page_data = json.load(f)
        total += len(page_data.get("features", []))
    return total, existing_pages


# ---------------------------------------------------------------------------
# Download every page of the state-routes layer and save each as raw JSON.
# ---------------------------------------------------------------------------
def download_all_pages(expected_count):
    """
    Page through the roads API and save each response to data/raw/.
    If a request fails, STOP, say which page failed, and keep what we have.
    """
    # Start clean: remove any old page files so we don't mix old + new data.
    for old_file in RAW_DIR.glob("state_routes_page_*.json"):
        old_file.unlink()

    offset = 0
    page_number = 1
    total_downloaded = 0

    while True:
        params = {
            "where": WHERE_CLAUSE,
            "outFields": "*",                # return all available columns
            "returnGeometry": "true",        # include the road shapes
            "f": "json",
            "resultRecordCount": PAGE_SIZE,
            "resultOffset": offset,
            "orderByFields": "OBJECTID ASC", # consistent ordering across pages
        }

        print(f"  Downloading page {page_number} (records starting at {offset})...")

        try:
            response = requests.get(ROADS_API_URL, params=params, timeout=120)
            response.raise_for_status()
            page_data = response.json()
        except Exception as problem:
            print()
            print("!!! DOWNLOAD STOPPED - a page failed to download.")
            print(f"!!! Failed on page {page_number}, record offset {offset}.")
            print(f"!!! Reason: {problem}")
            print("!!! The pages downloaded so far have been KEPT in data/raw/.")
            print("!!! Please tell me how you'd like to proceed (retry, wait, etc.).")
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

        page_path = RAW_DIR / f"state_routes_page_{page_number:03d}.json"
        with open(page_path, "w", encoding="utf-8") as f:
            json.dump(page_data, f)
        print(f"  Saved {len(features)} records -> {page_path.name}")

        total_downloaded += len(features)

        # The API sets this flag to True when there are still more pages to get.
        more_pages_exist = page_data.get("exceededTransferLimit", False)
        if not more_pages_exist:
            print("  API says there are no more pages. Done downloading.")
            break

        offset += PAGE_SIZE
        page_number += 1
        time.sleep(DELAY_BETWEEN_REQUESTS)

    print(f"  Total segments downloaded: {total_downloaded} (API expected {expected_count}).")
    return total_downloaded


# ---------------------------------------------------------------------------
# Small helper: turn one ArcGIS feature's shape into a real geometry object.
# Returns None if the feature has no usable shape.
# ---------------------------------------------------------------------------
def arcgis_feature_to_geometry(feature):
    """Convert an ArcGIS feature's geometry to a shapely geometry (or None)."""
    arcgis_geometry = feature.get("geometry")
    if not arcgis_geometry:
        return None
    # A line needs "paths"; a polygon needs "rings". If neither has content,
    # there's nothing to draw, so we skip it.
    if not arcgis_geometry.get("paths") and not arcgis_geometry.get("rings"):
        return None
    geojson_geometry = arcgis2geojson(arcgis_geometry)
    geometry = shape(geojson_geometry)
    if geometry.is_empty:
        return None
    return geometry


# ---------------------------------------------------------------------------
# Read all saved road pages, convert shapes, and build a clean GeoDataFrame.
# ---------------------------------------------------------------------------
def build_roads_geodataframe():
    """Read saved state-route pages into one GeoDataFrame in lat/long."""
    page_files = sorted(RAW_DIR.glob("state_routes_page_*.json"))
    if not page_files:
        raise RuntimeError("No road page files found to read. Try downloading again.")

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
            attributes = feature.get("attributes", {})
            # Keep only the columns we care about (missing ones become None).
            row = {field: attributes.get(field) for field in ROAD_FIELDS_WE_KEEP}
            rows.append(row)
            geometries.append(geometry)

    # Build the GeoDataFrame in the source system (TN State Plane, feet)...
    roads = gpd.GeoDataFrame(rows, geometry=geometries, crs=SOURCE_CRS)
    # ...then convert to plain lat/long so it matches the crash data.
    roads = roads.to_crs(OUTPUT_CRS)
    return roads, skipped_no_geometry


# ===========================================================================
# PART 2: THE CITY OF MEMPHIS BOUNDARY LAYER
# ===========================================================================

# ---------------------------------------------------------------------------
# Download the boundary layer (a single area shape) and save it raw.
# ---------------------------------------------------------------------------
def download_boundary():
    """Fetch the Memphis boundary layer and save the raw response (light cache)."""
    if BOUNDARY_JSON_PATH.exists():
        print(f"  Boundary already saved at {BOUNDARY_JSON_PATH.name} - reusing it.")
        return

    params = {
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": "true",
        "f": "json",
    }
    print("  Downloading the City of Memphis boundary (layer 15)...")
    response = requests.get(BOUNDARY_API_URL, params=params, timeout=120)
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        raise RuntimeError(f"Boundary API returned an error: {data['error']}")

    with open(BOUNDARY_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f)
    print(f"  Saved raw boundary -> {BOUNDARY_JSON_PATH.name}")


# ---------------------------------------------------------------------------
# Convert the boundary into ONE combined shape and save it as GeoJSON.
# ---------------------------------------------------------------------------
def build_boundary_geodataframe():
    """Merge the boundary feature(s) into a single shape in lat/long."""
    with open(BOUNDARY_JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    features = data.get("features", [])
    geometries = []
    for feature in features:
        geometry = arcgis_feature_to_geometry(feature)
        if geometry is not None:
            geometries.append(geometry)

    if not geometries:
        raise RuntimeError("The boundary layer returned no usable shape.")

    # Merge everything into one shape (handles the city being one big outline,
    # possibly with separate pieces).
    combined = union_all(geometries)

    boundary = gpd.GeoDataFrame(
        {"name": ["City of Memphis"]},
        geometry=[combined],
        crs=SOURCE_CRS,
    )
    boundary = boundary.to_crs(OUTPUT_CRS)
    return boundary


# ===========================================================================
# MAIN
# ===========================================================================
def main():
    print("Memphis Pedestrian Safety - road + boundary download (Phase 3, part 1)")
    print("-" * 70)

    # --- STATE ROUTES ------------------------------------------------------
    print("STATE ROUTES (layer 17)")
    print("Checking the live segment count from the API...")
    api_count = get_current_api_count()
    print(f"  API currently has {api_count} state-route segments.")

    existing_count, existing_pages = count_records_in_existing_pages()
    if existing_pages and existing_count == api_count:
        print(f"  We already have {existing_count} segments saved that match the "
              f"live count - skipping download and just reprocessing.")
    else:
        if existing_pages:
            print(f"  We have {existing_count} saved segments but the API now has "
                  f"{api_count} - re-downloading fresh.")
        else:
            print("  No saved road data found - downloading fresh.")
        print("Downloading...")
        download_all_pages(api_count)

    print("Converting road shapes and saving GeoJSON...")
    roads, skipped_no_geometry = build_roads_geodataframe()
    roads.to_file(ROADS_GEOJSON_PATH, driver="GeoJSON")
    print(f"  Saved -> {ROADS_GEOJSON_PATH.name}")

    # --- BOUNDARY ----------------------------------------------------------
    print()
    print("CITY OF MEMPHIS BOUNDARY (layer 15)")
    download_boundary()
    print("Converting boundary shape and saving GeoJSON...")
    boundary = build_boundary_geodataframe()
    boundary.to_file(BOUNDARY_GEOJSON_PATH, driver="GeoJSON")
    print(f"  Saved -> {BOUNDARY_GEOJSON_PATH.name}")

    # --- SUMMARY -----------------------------------------------------------
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)

    print(f"State-route segments loaded:        {len(roads)}")
    print(f"Segments skipped (no geometry):     {skipped_no_geometry}")
    all_valid = roads.geometry.notna().all() and (~roads.geometry.is_empty).all()
    print(f"Every loaded segment has geometry:  {bool(all_valid)}")

    print()
    print("Sample of 5 state-route names:")
    sample = roads["NAME"].dropna().head(5).tolist()
    for name in sample:
        print(f"  - {name}")

    print()
    boundary_geom = boundary.geometry.iloc[0]
    boundary_valid = (boundary_geom is not None) and (not boundary_geom.is_empty)
    print(f"Memphis boundary loaded:            {bool(boundary_valid)}")
    print(f"Boundary shape type:                {boundary_geom.geom_type}")
    print("=" * 70)


if __name__ == "__main__":
    main()
