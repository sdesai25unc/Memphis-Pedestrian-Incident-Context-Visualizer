r"""
03_spatial_join.py
==================

PHASE 4 of the Memphis Pedestrian Safety project.

What this script does, in plain English:
  1. Loads the deduplicated crash file (one row per crash) from Phase 2.
  2. Throws out crashes whose location is missing or impossible (e.g. blank,
     (0,0), or outside Shelby County) - but KEEPS them in the final file,
     flagged, so the row counts still add up.
  3. Filters the remaining crashes to those that fall INSIDE the City of
     Memphis boundary. (The road layer only covers the city, so a suburban
     crash has no city road near it and must not be counted as "City.")
  4. For each in-Memphis crash, finds the nearest state route and measures the
     distance in METERS. If that distance is 30 m or less, the crash is on a
     TDOT road; otherwise it's a City of Memphis road.
  5. Writes data/processed/shelby_crashes_classified.csv with new columns.
  6. Prints a clear three-part summary (Shelby total / Memphis-only headline /
     suburban context) plus a sensitivity table and top-route rankings.

It does NOT make maps or charts - that is Phase 5.

Run it with:
    .\.venv\Scripts\python.exe scripts\03_spatial_join.py
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
from pathlib import Path

import pandas as pd
import geopandas as gpd


# ---------------------------------------------------------------------------
# SETTINGS - the knobs you might want to change live here at the top.
# ---------------------------------------------------------------------------

# A crash is classified as on a TDOT state route if the nearest state-route
# segment is within this many METERS. This is THE key threshold of the study.
DISTANCE_THRESHOLD_M = 30

# Extra thresholds we ALSO report (diagnostic only) so we can see whether the
# TDOT share is stable or fragile around 30 m. The official answer stays 30 m.
SENSITIVITY_THRESHOLDS_M = [10, 20, 30, 50, 100]

# The projected coordinate system used for all distance math, in METERS.
# EPSG:32136 = NAD83 / Tennessee. It is purpose-built for Tennessee and has
# almost no distance distortion here. (We deliberately do NOT use Web Mercator
# / EPSG:3857: at Memphis's latitude it stretches distances by ~22%, which
# would quietly corrupt a tight 30 m threshold.)
PROJECTED_CRS = "EPSG:32136"

# Plain lat/long, the system the input files are stored in.
GEOGRAPHIC_CRS = "EPSG:4326"

# A generous bounding box around Shelby County. Any crash whose lat/long falls
# outside this box (or is blank, or is (0,0)) is treated as a bad location.
LAT_MIN, LAT_MAX = 34.99, 35.42
LON_MIN, LON_MAX = -90.31, -89.61


# ---------------------------------------------------------------------------
# FILE PATHS
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

CRASH_CSV_PATH = PROCESSED_DIR / "shelby_crashes_dedup.csv"
ROADS_GEOJSON_PATH = RAW_DIR / "state_routes.geojson"
BOUNDARY_GEOJSON_PATH = RAW_DIR / "memphis_boundary.geojson"
CLASSIFIED_CSV_PATH = PROCESSED_DIR / "shelby_crashes_classified.csv"

# The new columns we add to every crash row, in the order they should appear.
NEW_COLUMNS = [
    "InMemphis",
    "Jurisdiction",
    "StateRoute_NAME",
    "StateRoute_F_System",
    "StateRoute_SPDLIMIT",
    "StateRoute_LANES",
    "StateRoute_ALTNAME_1",
    "StateRoute_Council_District",
    "DistToStateRoute_m",
]


# ---------------------------------------------------------------------------
# Build a clean, consistent display name for a state-route segment.
#   PREDIR + NAME + TYPE, single-spaced, uppercased, trimmed -> "N WATKINS ST"
#   If NAME is blank, fall back to the SR number -> "SR-3".
#   If both are blank, use "(unnamed segment)".
# Using the SAME rule everywhere keeps grouping from splitting on whitespace.
# ---------------------------------------------------------------------------
def build_route_name(predir, name, type_, altname):
    def clean(value):
        if value is None:
            return ""
        text = str(value).strip()
        # pandas reads blank cells as the float "nan"; treat that as empty.
        if text.lower() == "nan":
            return ""
        return text

    name_part = clean(name)
    if name_part:
        parts = [clean(predir), name_part, clean(type_)]
        composite = " ".join(p for p in parts if p)
        # Collapse any double spaces and uppercase for consistent grouping.
        return " ".join(composite.split()).upper()

    altname_part = clean(altname)
    if altname_part:
        return f"SR-{altname_part}"

    return "(unnamed segment)"


# ---------------------------------------------------------------------------
# Decide whether a single lat/long pair is usable.
# ---------------------------------------------------------------------------
def is_good_location(lat, lon):
    if pd.isna(lat) or pd.isna(lon):
        return False
    if lat == 0 and lon == 0:
        return False
    if not (LAT_MIN <= lat <= LAT_MAX):
        return False
    if not (LON_MIN <= lon <= LON_MAX):
        return False
    return True


# ---------------------------------------------------------------------------
# A small helper for "count and percent" lines.
# ---------------------------------------------------------------------------
def pct(part, whole):
    return (100.0 * part / whole) if whole else 0.0


def main():
    print("Memphis Pedestrian Safety - spatial join / classification (Phase 4)")
    print("-" * 70)

    # -----------------------------------------------------------------------
    # 1. Load the crashes (one row per crash).
    # -----------------------------------------------------------------------
    crashes = pd.read_csv(CRASH_CSV_PATH)
    original_columns = list(crashes.columns)
    total_input = len(crashes)
    print(f"Loaded {total_input} crashes from {CRASH_CSV_PATH.name}.")

    # -----------------------------------------------------------------------
    # 2. Flag crashes with bad / missing locations.
    # -----------------------------------------------------------------------
    crashes["_good_geo"] = [
        is_good_location(lat, lon)
        for lat, lon in zip(crashes["Latitude"], crashes["Longitude"])
    ]
    bad_geo_count = int((~crashes["_good_geo"]).sum())
    print(f"  Crashes with bad/missing location (excluded from analysis): {bad_geo_count}")

    # Prepare the new columns up front so every row has them (blank by default).
    for column in NEW_COLUMNS:
        crashes[column] = pd.NA
    # Bad-geo rows can never be "in Memphis" - they have no usable point.
    crashes["InMemphis"] = False
    crashes.loc[~crashes["_good_geo"], "Jurisdiction"] = "Excluded-BadGeo"

    # -----------------------------------------------------------------------
    # 3. Build map points for the good-location crashes only.
    # -----------------------------------------------------------------------
    good = crashes[crashes["_good_geo"]].copy()
    good_points = gpd.GeoDataFrame(
        good,
        geometry=gpd.points_from_xy(good["Longitude"], good["Latitude"]),
        crs=GEOGRAPHIC_CRS,
    ).to_crs(PROJECTED_CRS)

    # -----------------------------------------------------------------------
    # 4. Filter to crashes inside the City of Memphis boundary.
    # -----------------------------------------------------------------------
    boundary = gpd.read_file(BOUNDARY_GEOJSON_PATH).to_crs(PROJECTED_CRS)
    boundary_shape = boundary.geometry.iloc[0]

    in_memphis_mask = good_points.geometry.within(boundary_shape)
    # Record InMemphis back on the master table (by row index).
    crashes.loc[good_points.index[in_memphis_mask], "InMemphis"] = True
    crashes.loc[good_points.index[~in_memphis_mask], "InMemphis"] = False

    in_memphis_count = int(in_memphis_mask.sum())
    outside_count = int((~in_memphis_mask).sum())
    good_count = len(good_points)
    print(f"  Good-location crashes: {good_count}")
    print(f"    Inside City of Memphis:  {in_memphis_count} "
          f"({pct(in_memphis_count, good_count):.1f}% of good-location)")
    print(f"    Outside (suburban Shelby): {outside_count} "
          f"({pct(outside_count, good_count):.1f}% of good-location)")

    # Crashes outside Memphis are suburban; mark them now.
    crashes.loc[good_points.index[~in_memphis_mask], "Jurisdiction"] = "Suburban-Shelby"

    # -----------------------------------------------------------------------
    # 5. Load the state routes and build a clean display name for each.
    # -----------------------------------------------------------------------
    roads = gpd.read_file(ROADS_GEOJSON_PATH).to_crs(PROJECTED_CRS)
    roads["StateRoute_NAME"] = [
        build_route_name(predir, name, type_, altname)
        for predir, name, type_, altname in zip(
            roads["PREDIR"], roads["NAME"], roads["TYPE"], roads["ALTNAME_1"]
        )
    ]

    # -----------------------------------------------------------------------
    # 6. For each in-Memphis crash, find the nearest state route + distance.
    #    We do NOT cap the distance here, so City-of-Memphis crashes still get
    #    a real distance (needed for the sanity check + sensitivity table).
    # -----------------------------------------------------------------------
    memphis_points = good_points[in_memphis_mask].copy()
    # Drop the placeholder result columns we pre-added to every crash row, so
    # they don't collide with the road columns / distance column during the join.
    memphis_points = memphis_points.drop(
        columns=[c for c in NEW_COLUMNS if c in memphis_points.columns]
    )

    road_columns = [
        "StateRoute_NAME", "F_System", "SPDLIMIT", "LANES",
        "ALTNAME_1", "Council_District", "geometry",
    ]
    joined = gpd.sjoin_nearest(
        memphis_points,
        roads[road_columns],
        how="left",
        distance_col="DistToStateRoute_m",
    )
    # If a crash is exactly tied between two segments, sjoin_nearest lists both.
    # Keep the first deterministically so we have one row per crash.
    joined = joined[~joined.index.duplicated(keep="first")]

    # -----------------------------------------------------------------------
    # 7. Write the matched values back onto the master crash table.
    # -----------------------------------------------------------------------
    for crash_index, match in joined.iterrows():
        distance = match["DistToStateRoute_m"]
        crashes.at[crash_index, "DistToStateRoute_m"] = distance
        if distance <= DISTANCE_THRESHOLD_M:
            crashes.at[crash_index, "Jurisdiction"] = "TDOT"
            crashes.at[crash_index, "StateRoute_NAME"] = match["StateRoute_NAME"]
            crashes.at[crash_index, "StateRoute_F_System"] = match["F_System"]
            crashes.at[crash_index, "StateRoute_SPDLIMIT"] = match["SPDLIMIT"]
            crashes.at[crash_index, "StateRoute_LANES"] = match["LANES"]
            crashes.at[crash_index, "StateRoute_ALTNAME_1"] = match["ALTNAME_1"]
            crashes.at[crash_index, "StateRoute_Council_District"] = match["Council_District"]
        else:
            crashes.at[crash_index, "Jurisdiction"] = "City of Memphis"

    # -----------------------------------------------------------------------
    # 8. Save the classified file (original columns first, new columns after).
    # -----------------------------------------------------------------------
    crashes = crashes.drop(columns="_good_geo")
    output = crashes[original_columns + NEW_COLUMNS]
    output.to_csv(CLASSIFIED_CSV_PATH, index=False, encoding="utf-8")
    print(f"\nSaved classified file: {CLASSIFIED_CSV_PATH.name} ({len(output)} rows)")

    # =======================================================================
    # 9. SUMMARY
    # =======================================================================
    is_fatal = output["InjuryClass"] == "Fatal"

    print()
    print("=" * 70)
    print("SECTION (a) - SHELBY COUNTY TOTALS")
    print("=" * 70)
    print("(These figures are at the CRASH level - one row per crash.)")
    print(f"  Total crashes:                 {total_input}")
    print(f"  Fatal crashes:                 {int(is_fatal.sum())}")
    print(f"  People affected (sum Victims): {int(output['VictimsInCrash'].sum())}")
    print(f"  Good-location crashes:         {good_count}")
    print(f"  Excluded (bad/missing geo):    {bad_geo_count}")

    # --- Memphis-only subset -----------------------------------------------
    memphis = output[output["InMemphis"] == True]  # noqa: E712
    memphis_total = len(memphis)
    tdot = memphis[memphis["Jurisdiction"] == "TDOT"]
    city = memphis[memphis["Jurisdiction"] == "City of Memphis"]

    print()
    print("=" * 70)
    print("SECTION (b) - MEMPHIS-ONLY SUBSET  *** HEADLINE FINDING ***")
    print("=" * 70)
    print(f"  Crashes inside the City of Memphis: {memphis_total}")
    print()
    print("  Who owns the road? (all in-Memphis crashes)")
    print(f"    TDOT (state route): {len(tdot):5d}  ({pct(len(tdot), memphis_total):5.1f}%)")
    print(f"    City of Memphis:    {len(city):5d}  ({pct(len(city), memphis_total):5.1f}%)")

    m_fatal = memphis[memphis["InjuryClass"] == "Fatal"]
    mf_total = len(m_fatal)
    mf_tdot = int((m_fatal["Jurisdiction"] == "TDOT").sum())
    mf_city = int((m_fatal["Jurisdiction"] == "City of Memphis").sum())
    print()
    print(f"  FATAL crashes only (in Memphis): {mf_total}")
    print(f"    TDOT (state route): {mf_tdot:5d}  ({pct(mf_tdot, mf_total):5.1f}%)")
    print(f"    City of Memphis:    {mf_city:5d}  ({pct(mf_city, mf_total):5.1f}%)")

    people_total = memphis["VictimsInCrash"].sum()
    people_tdot = tdot["VictimsInCrash"].sum()
    people_city = city["VictimsInCrash"].sum()
    print()
    print(f"  People affected (sum of VictimsInCrash, in Memphis): {int(people_total)}")
    print(f"    TDOT (state route): {int(people_tdot):5d}  ({pct(people_tdot, people_total):5.1f}%)")
    print(f"    City of Memphis:    {int(people_city):5d}  ({pct(people_city, people_total):5.1f}%)")

    # Average distance per group - sanity check on the 30 m threshold.
    dist = pd.to_numeric(memphis["DistToStateRoute_m"], errors="coerce")
    tdot_dist = dist[memphis["Jurisdiction"] == "TDOT"]
    city_dist = dist[memphis["Jurisdiction"] == "City of Memphis"]
    print()
    print("  Sanity check - average distance to nearest state route:")
    print(f"    TDOT group:            {tdot_dist.mean():7.1f} m  (should be well under 30)")
    print(f"    City of Memphis group: {city_dist.mean():7.1f} m  (should be well over 30)")

    # Sensitivity table - is the TDOT share stable around 30 m?
    print()
    print("  Sensitivity table (diagnostic only; official threshold = 30 m):")
    print("    threshold   TDOT crashes   TDOT share")
    for t in SENSITIVITY_THRESHOLDS_M:
        n_tdot = int((dist <= t).sum())
        marker = "  <-- official" if t == DISTANCE_THRESHOLD_M else ""
        print(f"    {t:5d} m      {n_tdot:6d}        {pct(n_tdot, memphis_total):5.1f}%{marker}")

    # Top routes - need fatal info per crash, so work off the Memphis subset.
    tdot_named = tdot.copy()
    tdot_named["_fatal"] = (tdot_named["InjuryClass"] == "Fatal").astype(int)
    by_route = tdot_named.groupby("StateRoute_NAME").agg(
        crashes=("StateRoute_NAME", "size"),
        fatal=("_fatal", "sum"),
    )

    print()
    print("  Top 10 state routes by TOTAL crashes (fatal count alongside):")
    top_total = by_route.sort_values(["crashes", "fatal"], ascending=False).head(10)
    print(f"    {'route':30s} {'crashes':>8s} {'fatal':>6s}")
    for route_name, row in top_total.iterrows():
        print(f"    {str(route_name)[:30]:30s} {int(row['crashes']):8d} {int(row['fatal']):6d}")

    print()
    print("  Top 10 state routes by FATAL crashes:")
    top_fatal = by_route[by_route["fatal"] > 0].sort_values(
        ["fatal", "crashes"], ascending=False
    ).head(10)
    if len(top_fatal) == 0:
        print("    (no fatal crashes matched to a state route)")
    else:
        print(f"    {'route':30s} {'fatal':>6s} {'crashes':>8s}")
        for route_name, row in top_fatal.iterrows():
            print(f"    {str(route_name)[:30]:30s} {int(row['fatal']):6d} {int(row['crashes']):8d}")

    print()
    print(f"  Unclassified in-Memphis crashes (rejected by 30 m -> City): {len(city)}")

    # --- Suburban context --------------------------------------------------
    suburban = output[output["Jurisdiction"] == "Suburban-Shelby"]
    sub_fatal = int((suburban["InjuryClass"] == "Fatal").sum())
    print()
    print("=" * 70)
    print("SECTION (c) - SUBURBAN (in Shelby County, outside City of Memphis)")
    print("=" * 70)
    print(f"  Suburban crashes:          {len(suburban)}  "
          f"({pct(len(suburban), total_input):.1f}% of all Shelby crashes)")
    print(f"  Suburban fatal crashes:    {sub_fatal}")
    print(f"  Suburban people affected:  {int(suburban['VictimsInCrash'].sum())}")

    # --- Reconciliation ----------------------------------------------------
    counts = output["Jurisdiction"].value_counts(dropna=False)
    print()
    print("  Reconciliation (every crash lands in exactly one bucket):")
    for label, n in counts.items():
        print(f"    {str(label):18s} {int(n):6d}")
    print(f"    {'TOTAL':18s} {int(counts.sum()):6d}  (input was {total_input})")

    # --- First 10 rows -----------------------------------------------------
    print()
    print("First 10 rows of the classified file:")
    print("-" * 70)
    preview_cols = [
        "MstrRecNbrTxt", "CollisionDate", "InjuryClass", "VictimsInCrash",
        "InMemphis", "Jurisdiction", "StateRoute_NAME", "DistToStateRoute_m",
    ]
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(output[preview_cols].head(10).to_string())
    print("=" * 70)


if __name__ == "__main__":
    main()
