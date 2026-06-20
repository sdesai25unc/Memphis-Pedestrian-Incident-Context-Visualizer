r"""
06_join_streets.py
=================

Matches every in-Memphis crash to its nearest street and produces the project's
first "deadliest streets" ranking.

What this script does, in plain English:
  1. Takes only the IN-MEMPHIS crashes (Jurisdiction "TDOT" or "City of Memphis").
  2. Builds map points from their latitude/longitude. Any crash with a bad
     coordinate is set aside (reported, not crashed on).
  3. Reprojects the crash points AND the street lines to EPSG:32136
     (Tennessee, in METERS) so distances are true meters.
  4. For each crash, finds the nearest street segment and attaches that street's
     standardized name, the distance, and SPDLIMIT / LANES / ONEWAY / CITY_L /
     COUNTY_L.
  5. Writes a per-crash file (shelby_crashes_named.csv).
  6. Groups by street to build a deadliest-streets ranking
     (deadliest_streets.csv) and prints review tables to the terminal.

It does NOT overwrite shelby_crashes_classified.csv.

Run it with:
    .\.venv\Scripts\python.exe scripts\06_join_streets.py
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
from pathlib import Path

import pandas as pd
import geopandas as gpd


# ---------------------------------------------------------------------------
# SETTINGS
# ---------------------------------------------------------------------------

# Only these crashes are in the City of Memphis and get a street match.
IN_MEMPHIS_JURISDICTIONS = ["TDOT", "City of Memphis"]

# The exact InjuryClass text values we count.
FATAL_VALUE = "Fatal"
SERIOUS_VALUE = "Suspected Serious Injury"

# Distance math must be in true meters -> Tennessee state plane (NOT Web Mercator).
GEOGRAPHIC_CRS = "EPSG:4326"
PROJECTED_CRS = "EPSG:32136"   # NAD83 / Tennessee, meters

# Crashes matched farther than this (meters) are flagged as possibly weak matches.
FAR_MATCH_M = 40

# A street is "MIXED" jurisdiction if no single jurisdiction is at least this share.
DOMINANT_SHARE = 0.90

# A generous Shelby County bounding box for spotting impossible coordinates.
LAT_MIN, LAT_MAX = 34.9, 35.5
LON_MIN, LON_MAX = -90.4, -89.5


# ---------------------------------------------------------------------------
# FILE PATHS
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
RAW_DIR = PROJECT_ROOT / "data" / "raw"

CRASH_CSV_PATH = PROCESSED_DIR / "shelby_crashes_classified.csv"
STREETS_GEOJSON_PATH = RAW_DIR / "memphis_streets.geojson"
NAMED_CSV_PATH = PROCESSED_DIR / "shelby_crashes_named.csv"
DEADLIEST_CSV_PATH = PROCESSED_DIR / "deadliest_streets.csv"

# New per-crash columns added by this script.
NEW_COLUMNS = [
    "Street_Name", "DistToStreet_m", "Street_SPDLIMIT", "Street_LANES",
    "Street_ONEWAY", "Street_CITY_L", "Street_COUNTY_L",
]


# ---------------------------------------------------------------------------
# Build the standardized street name from a segment's component fields.
#   PREDIR + NAME + TYPE + SUFDIR  (only the parts present), single-spaced,
#   uppercased, trimmed, double-spaces collapsed.  e.g. "N WATKINS ST".
#   If NAME is blank, fall back to LABEL (uppercased).
#   Directionals are KEPT (NORTH PARKWAY vs SOUTH PARKWAY stay separate).
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
        joined = " ".join(p for p in parts if p)
        return " ".join(joined.split()).upper()   # collapse doubles + uppercase
    # NAME blank -> fall back to the prebuilt LABEL.
    return " ".join(clean_part(label).split()).upper()


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
# Most common non-zero value in a series (deterministic). Used for the per-street
# speed limit (0 = unknown, so excluded) and lane count.
# ---------------------------------------------------------------------------
def modal_nonzero(series):
    vals = pd.to_numeric(series, errors="coerce").dropna()
    vals = vals[vals != 0]
    if len(vals) == 0:
        return pd.NA
    modes = vals.mode()          # sorted; pick the first for a stable tie-break
    return modes.iloc[0] if len(modes) else pd.NA


def main():
    print("Memphis Pedestrian Safety - nearest-street join + deadliest ranking")
    print("-" * 70)

    # -----------------------------------------------------------------------
    # 1. Load crashes, keep only in-Memphis ones.
    # -----------------------------------------------------------------------
    crashes = pd.read_csv(CRASH_CSV_PATH)
    original_columns = list(crashes.columns)
    in_memphis = crashes[crashes["Jurisdiction"].isin(IN_MEMPHIS_JURISDICTIONS)].copy()
    n_in_memphis = len(in_memphis)
    print(f"In-Memphis crashes (TDOT + City of Memphis): {n_in_memphis}")

    # 1b. Separate out any with bad coordinates (reported, not dropped).
    good_mask = [is_good_location(lat, lon)
                 for lat, lon in zip(in_memphis["Latitude"], in_memphis["Longitude"])]
    good = in_memphis[good_mask].copy()
    bad = in_memphis[[not g for g in good_mask]].copy()
    n_bad = len(bad)
    print(f"  Set aside for invalid coordinates: {n_bad}")

    # -----------------------------------------------------------------------
    # 2. Load streets, build the standardized name, reproject to meters.
    # -----------------------------------------------------------------------
    streets = gpd.read_file(STREETS_GEOJSON_PATH)
    streets["Street_Name"] = [
        build_street_name(p, n, t, s, l)
        for p, n, t, s, l in zip(streets["PREDIR"], streets["NAME"],
                                 streets["TYPE"], streets["SUFDIR"], streets["LABEL"])
    ]
    # Keep just what we need, renamed to the Street_* output columns.
    streets_small = streets[[
        "Street_Name", "SPDLIMIT", "LANES", "ONEWAY", "CITY_L", "COUNTY_L", "geometry",
    ]].rename(columns={
        "SPDLIMIT": "Street_SPDLIMIT", "LANES": "Street_LANES", "ONEWAY": "Street_ONEWAY",
        "CITY_L": "Street_CITY_L", "COUNTY_L": "Street_COUNTY_L",
    }).to_crs(PROJECTED_CRS)

    # -----------------------------------------------------------------------
    # 3. Build crash points (meters) and find the nearest street for each.
    # -----------------------------------------------------------------------
    crash_points = gpd.GeoDataFrame(
        good,
        geometry=gpd.points_from_xy(good["Longitude"], good["Latitude"]),
        crs=GEOGRAPHIC_CRS,
    ).to_crs(PROJECTED_CRS)

    joined = gpd.sjoin_nearest(
        crash_points, streets_small, how="left", distance_col="DistToStreet_m",
    )
    # If a crash is exactly tied between two segments, keep the first match.
    joined = joined[~joined.index.duplicated(keep="first")]

    # -----------------------------------------------------------------------
    # 4. Write the per-crash named file (all in-Memphis crashes; bad-geo rows
    #    kept with blank street fields so the file reconciles to one row each).
    # -----------------------------------------------------------------------
    joined_df = pd.DataFrame(joined.drop(columns="geometry"))
    if n_bad > 0:
        # Keep bad-coordinate crashes in the file with blank street fields.
        for col in NEW_COLUMNS:
            bad[col] = pd.NA
        named = pd.concat([joined_df, bad], ignore_index=True)
    else:
        named = joined_df
    named = named[original_columns + NEW_COLUMNS]
    named.to_csv(NAMED_CSV_PATH, index=False, encoding="utf-8")
    print(f"\nSaved per-crash file: {NAMED_CSV_PATH.name} ({len(named)} rows)")

    # The matched crashes (those that actually got a street) drive the ranking.
    matched = joined_df.copy()

    # -----------------------------------------------------------------------
    # 5. Build the deadliest-streets ranking.
    # -----------------------------------------------------------------------
    matched["_is_fatal"] = (matched["InjuryClass"] == FATAL_VALUE).astype(int)
    matched["_is_serious"] = (matched["InjuryClass"] == SERIOUS_VALUE).astype(int)

    def summarize_street(group):
        total = len(group)
        juris_counts = group["Jurisdiction"].value_counts()
        dominant = juris_counts.idxmax()
        dominant_share = juris_counts.max() / total
        return pd.Series({
            "Total_Crashes": total,
            "Fatal_Crashes": int(group["_is_fatal"].sum()),
            "Serious_Injuries": int(group["_is_serious"].sum()),
            "Dominant_Jurisdiction": dominant,
            "Mixed_Jurisdiction": bool(dominant_share < DOMINANT_SHARE),
            "SPDLIMIT": modal_nonzero(group["Street_SPDLIMIT"]),
            "LANES": modal_nonzero(group["Street_LANES"]),
        })

    ranking = (matched.groupby("Street_Name", sort=False)
               .apply(summarize_street, include_groups=False)
               .reset_index())
    ranking = ranking.sort_values(
        ["Total_Crashes", "Fatal_Crashes"], ascending=False
    ).reset_index(drop=True)
    ranking.to_csv(DEADLIEST_CSV_PATH, index=False, encoding="utf-8")
    print(f"Saved deadliest-streets ranking: {DEADLIEST_CSV_PATH.name} "
          f"({len(ranking)} streets)")

    # -----------------------------------------------------------------------
    # 6. Terminal review tables.
    # -----------------------------------------------------------------------
    def show(df, cols):
        with pd.option_context("display.max_rows", None, "display.width", 200):
            print(df[cols].to_string(index=False))

    rank_cols = ["Street_Name", "Total_Crashes", "Fatal_Crashes",
                 "Dominant_Jurisdiction", "Mixed_Jurisdiction", "SPDLIMIT", "LANES"]

    print()
    print("=" * 70)
    print("TOP 25 STREETS BY TOTAL CRASHES")
    print("=" * 70)
    show(ranking.head(25), rank_cols)

    print()
    print("=" * 70)
    print("TOP 25 STREETS BY FATAL CRASHES")
    print("=" * 70)
    top_fatal = ranking.sort_values(
        ["Fatal_Crashes", "Total_Crashes"], ascending=False
    ).head(25)
    show(top_fatal, rank_cols)

    # -----------------------------------------------------------------------
    # 7. Distance quality check.
    # -----------------------------------------------------------------------
    dist = pd.to_numeric(matched["DistToStreet_m"], errors="coerce")
    far = matched[dist > FAR_MATCH_M]
    print()
    print("=" * 70)
    print("DISTANCE QUALITY CHECK (crash -> nearest street, meters)")
    print("=" * 70)
    print(f"  Mean distance:   {dist.mean():.1f} m")
    print(f"  Median distance: {dist.median():.1f} m")
    print(f"  Crashes matched > {FAR_MATCH_M} m away: {len(far)}")
    if len(far) > 0:
        print(f"\n  Farthest few matches (sanity-check these):")
        sample = far.sort_values("DistToStreet_m", ascending=False).head(8)
        show(sample, ["MstrRecNbrTxt", "Street_Name", "DistToStreet_m",
                      "Latitude", "Longitude"])

    # -----------------------------------------------------------------------
    # 8. Reconciliation.
    # -----------------------------------------------------------------------
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  In-Memphis crashes processed:    {n_in_memphis}")
    print(f"  Matched to a street:             {len(matched)}")
    print(f"  Set aside (bad coordinates):     {n_bad}")
    print(f"  Distinct streets in ranking:     {len(ranking)}")
    print("=" * 70)


if __name__ == "__main__":
    main()
