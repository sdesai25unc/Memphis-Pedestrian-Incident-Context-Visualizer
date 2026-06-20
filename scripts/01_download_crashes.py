r"""
01_download_crashes.py
=======================

PHASE 1 + 2 of the Memphis Pedestrian Safety project.

What this script does, in plain English:
  1. Asks the TDOT crash API how many Shelby County non-motorist records exist
     right now (excluding pedalcyclists).
  2. If we already downloaded that exact number, it skips downloading and just
     re-processes the files we have. Otherwise it downloads fresh.
  3. Downloads the data in "pages" (the API returns at most 2000 at a time) and
     saves each page as an untouched JSON file in data/raw/.
  4. Combines all pages into one "person-row" CSV (one row per person involved).
  5. Builds a "deduplicated" CSV (one row per crash), keeping the worst injury
     and counting how many people were in each crash.
  6. Prints a summary, then shows the first 5 rows of the deduplicated file.

It does NOT do any maps, charts, or spatial analysis. That comes later.

Run it with:
    .\.venv\Scripts\python.exe scripts\01_download_crashes.py
"""

# ---------------------------------------------------------------------------
# Imports: these are toolkits Python loads so we can use their features.
# ---------------------------------------------------------------------------
import sys                      # lets us stop the program with a clear message
import time                     # lets us pause politely between API requests
import json                     # reads/writes JSON files (the API's format)
from pathlib import Path        # a clean, modern way to handle file paths

import requests                 # downloads data from the web (the API)
import pandas as pd             # organizes data into tables and writes CSVs


# ---------------------------------------------------------------------------
# SETTINGS - everything you might want to change lives here at the top.
# ---------------------------------------------------------------------------

# The TDOT SAFETY MapServer, Layer 8 = Non-Motorist Crashes. No login needed.
API_URL = (
    "https://tnmap.tn.gov/arcgis/rest/services/"
    "SAFETY/MapForDashboards/MapServer/8/query"
)

# Which records we want: Shelby County, every non-motorist EXCEPT pedalcyclists.
# (That keeps "Pedestrian" and "Other Non-Motorist".)
WHERE_CLAUSE = "County='Shelby' AND PersonType<>'Pedalcyclists'"

# The API returns at most 2000 records per request, so we page through them.
PAGE_SIZE = 2000

# A short, polite pause (in seconds) between page requests so we don't hammer
# the state's server.
DELAY_BETWEEN_REQUESTS = 0.5

# The columns we care about (the API has many more, but these are the ones the
# project uses). If a column is missing in the data it is simply skipped.
FIELDS_WE_KEEP = [
    "MstrRecNbrTxt",      # crash report number (the SAME crash repeats per person)
    "CollisionDate",      # date of crash (comes as Unix milliseconds; we convert it)
    "CollisionDteTime",   # date + time of crash (also Unix milliseconds)
    "YearNmb",            # year
    "Month",              # month
    "DayOfWeek",          # day of week
    "Hour",               # hour of day
    "Latitude",           # latitude (for later mapping)
    "Longitude",          # longitude (for later mapping)
    "InjuryClass",        # severity for this person (Fatal, etc.)
    "PersonType",         # Pedestrian / Other Non-Motorist
    "NonMotoristLocation",   # where the person was (crosswalk, roadway, etc.)
    "RelationToJunction",    # Intersection / Non-Junction
    "LightCondition",     # daylight, dark, etc.
    "MannerOfCollision",  # how the collision happened
    "FirstHarmfulEvent",  # first damaging event in the crash
]

# Injury severity ranked from WORST (top) to LEAST SEVERE (bottom).
# These are the EXACT text values that appear in the data.
# Anything not in this list (e.g. "Unknown" or blank) is treated as the least
# severe, so it can never hide a real injury when we pick a crash's worst.
SEVERITY_WORST_TO_LEAST = [
    "Fatal",
    "Suspected Serious Injury",
    "Suspected Minor Injury",
    "Possible Injury",
    "No Injury",
]

# ---------------------------------------------------------------------------
# FILE PATHS - figured out relative to this script, so it works no matter what
# folder you run it from.
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent  # the "Memphis Data Project" folder
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

PERSON_CSV_PATH = RAW_DIR / "shelby_crashes_all_persons.csv"
DEDUP_CSV_PATH = PROCESSED_DIR / "shelby_crashes_dedup.csv"


# ---------------------------------------------------------------------------
# STEP A: Ask the API how many records exist right now.
# ---------------------------------------------------------------------------
def get_current_api_count():
    """Return the live count of matching records from the API."""
    params = {
        "where": WHERE_CLAUSE,
        "returnCountOnly": "true",   # ask ONLY for the count, not the data
        "f": "json",                 # return the answer as JSON
    }
    response = requests.get(API_URL, params=params, timeout=60)
    response.raise_for_status()      # raise an error if the web request failed
    data = response.json()

    # ArcGIS reports problems inside the JSON with an "error" key.
    if "error" in data:
        raise RuntimeError(f"API returned an error on the count request: {data['error']}")

    return data["count"]


# ---------------------------------------------------------------------------
# STEP B: Look at any pages we already downloaded and total their records.
# ---------------------------------------------------------------------------
def count_records_in_existing_pages():
    """Count how many records are stored across page files already on disk."""
    existing_pages = sorted(RAW_DIR.glob("shelby_crashes_page_*.json"))
    total = 0
    for page_file in existing_pages:
        with open(page_file, "r", encoding="utf-8") as f:
            page_data = json.load(f)
        total += len(page_data.get("features", []))
    return total, existing_pages


# ---------------------------------------------------------------------------
# STEP C: Download every page and save each one as a raw JSON file.
# ---------------------------------------------------------------------------
def download_all_pages(expected_count):
    """
    Page through the API and save each response to data/raw/.
    If a request fails, STOP, say which page failed, and ask the user.
    """
    # Start clean: remove any old page files so we don't mix old + new data.
    for old_file in RAW_DIR.glob("shelby_crashes_page_*.json"):
        old_file.unlink()

    offset = 0          # which record number to start each page at (0, 2000, ...)
    page_number = 1     # used to name the files: page_001, page_002, ...
    total_downloaded = 0

    while True:
        params = {
            "where": WHERE_CLAUSE,
            "outFields": "*",            # return all available columns
            "returnGeometry": "true",    # include map coordinates (needed later)
            "outSR": "4326",             # coordinates as normal latitude/longitude
            "f": "json",
            "resultRecordCount": PAGE_SIZE,
            "resultOffset": offset,
            "orderByFields": "ESRI_OID ASC",  # consistent ordering across pages
        }

        print(f"  Downloading page {page_number} (records starting at {offset})...")

        # --- Make the request, and stop clearly if anything goes wrong. ---
        try:
            response = requests.get(API_URL, params=params, timeout=120)
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

        # ArcGIS can also report an error inside a "successful" response.
        if "error" in page_data:
            print()
            print("!!! DOWNLOAD STOPPED - the API reported an error.")
            print(f"!!! Failed on page {page_number}, record offset {offset}.")
            print(f"!!! API error: {page_data['error']}")
            print("!!! The pages downloaded so far have been KEPT in data/raw/.")
            sys.exit(1)

        features = page_data.get("features", [])

        # If a page comes back empty, there is nothing more to fetch.
        if not features:
            print("  Got an empty page - no more records. Done downloading.")
            break

        # Save this page exactly as received (never modified later).
        page_path = RAW_DIR / f"shelby_crashes_page_{page_number:03d}.json"
        with open(page_path, "w", encoding="utf-8") as f:
            json.dump(page_data, f)
        print(f"  Saved {len(features)} records -> {page_path.name}")

        total_downloaded += len(features)

        # The API sets this flag to True when there are still more pages to get.
        more_pages_exist = page_data.get("exceededTransferLimit", False)
        if not more_pages_exist:
            print("  API says there are no more pages. Done downloading.")
            break

        # Otherwise, move to the next page.
        offset += PAGE_SIZE
        page_number += 1
        time.sleep(DELAY_BETWEEN_REQUESTS)  # be polite to the server

    print(f"  Total records downloaded: {total_downloaded} (API expected {expected_count}).")
    return total_downloaded


# ---------------------------------------------------------------------------
# STEP D: Read every saved page into one pandas table (DataFrame).
# ---------------------------------------------------------------------------
def load_pages_into_dataframe():
    """Read all saved JSON pages and return one combined table of person-rows."""
    page_files = sorted(RAW_DIR.glob("shelby_crashes_page_*.json"))
    if not page_files:
        raise RuntimeError("No page files found to read. Try downloading again.")

    all_rows = []
    for page_file in page_files:
        with open(page_file, "r", encoding="utf-8") as f:
            page_data = json.load(f)
        # Each "feature" has an "attributes" dictionary = one person-row.
        for feature in page_data.get("features", []):
            all_rows.append(feature["attributes"])

    df = pd.DataFrame(all_rows)

    # Keep only the columns we care about (and only ones that actually exist).
    columns_present = [c for c in FIELDS_WE_KEEP if c in df.columns]
    df = df[columns_present].copy()

    # Convert the date columns from Unix milliseconds to readable text.
    # We read them as UTC and keep the calendar date as-is (no timezone shifting),
    # which is the correct handling for these ArcGIS date fields.
    if "CollisionDate" in df.columns:
        df["CollisionDate"] = (
            pd.to_datetime(df["CollisionDate"], unit="ms", utc=True)
            .dt.strftime("%Y-%m-%d")
        )
    if "CollisionDteTime" in df.columns:
        df["CollisionDteTime"] = (
            pd.to_datetime(df["CollisionDteTime"], unit="ms", utc=True)
            .dt.strftime("%Y-%m-%d %H:%M:%S")
        )

    return df


# ---------------------------------------------------------------------------
# STEP E: Save the person-row CSV (one row per person involved).
# ---------------------------------------------------------------------------
def save_person_rows_csv(df):
    """Write the primary 'one row per person' CSV."""
    df.to_csv(PERSON_CSV_PATH, index=False, encoding="utf-8")
    print(f"  Saved person-row file: {PERSON_CSV_PATH.name} ({len(df)} rows)")


# ---------------------------------------------------------------------------
# Small helper: turn an InjuryClass text value into a rank number.
# Lower number = worse injury. Unknown/blank become the least severe.
# ---------------------------------------------------------------------------
def severity_rank(injury_value):
    if injury_value in SEVERITY_WORST_TO_LEAST:
        return SEVERITY_WORST_TO_LEAST.index(injury_value)
    # Treat "No Apparent Injury" the same as "No Injury", just in case.
    if injury_value == "No Apparent Injury":
        return SEVERITY_WORST_TO_LEAST.index("No Injury")
    # Anything else (Unknown, blank, missing) ranks below everything real.
    return len(SEVERITY_WORST_TO_LEAST)


def rank_back_to_label(rank):
    """Turn a rank number back into its InjuryClass text."""
    if rank < len(SEVERITY_WORST_TO_LEAST):
        return SEVERITY_WORST_TO_LEAST[rank]
    return "Unknown"


# ---------------------------------------------------------------------------
# STEP F: Build the deduplicated CSV (one row per crash).
# ---------------------------------------------------------------------------
def make_dedup_crash_csv(df):
    """
    Collapse person-rows into one row per crash (by report number).
    Keep the worst injury seen, count the victims, and take other fields from
    the first person-row of each crash.
    """
    # Add a temporary rank column so we can find the worst injury per crash.
    df = df.copy()
    df["_severity_rank"] = df["InjuryClass"].apply(severity_rank)

    # Warn (for transparency) if any injury values weren't in our known list.
    known_values = set(SEVERITY_WORST_TO_LEAST) | {"No Apparent Injury"}
    unknown_values = sorted(set(df["InjuryClass"].dropna()) - known_values)
    if unknown_values:
        print(f"  NOTE: these InjuryClass values are ranked as least-severe: {unknown_values}")

    # One row per crash = the FIRST person-row for each report number.
    # sort=False / keep='first' preserves the API's ESRI_OID ordering.
    dedup = df.drop_duplicates(subset="MstrRecNbrTxt", keep="first").copy()

    # For each crash, find the worst (lowest) rank and how many people involved.
    grouped = df.groupby("MstrRecNbrTxt", sort=False)
    worst_rank_per_crash = grouped["_severity_rank"].min()
    victims_per_crash = grouped.size()

    # Apply the worst injury back onto the deduplicated rows.
    dedup["InjuryClass"] = (
        dedup["MstrRecNbrTxt"].map(worst_rank_per_crash).apply(rank_back_to_label)
    )
    # Add the new VictimsInCrash column.
    dedup["VictimsInCrash"] = dedup["MstrRecNbrTxt"].map(victims_per_crash)

    # Drop the temporary helper column before saving.
    dedup = dedup.drop(columns="_severity_rank")

    dedup.to_csv(DEDUP_CSV_PATH, index=False, encoding="utf-8")
    print(f"  Saved deduplicated file: {DEDUP_CSV_PATH.name} ({len(dedup)} rows)")
    return dedup


# ---------------------------------------------------------------------------
# STEP G: Print a clear summary of what we have.
# ---------------------------------------------------------------------------
def print_summary(person_df, dedup_df):
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)

    print(f"Total person-rows pulled:      {len(person_df)}")
    print(f"Total unique crashes (dedup):  {len(dedup_df)}")

    # Date range (the text dates sort correctly as YYYY-MM-DD).
    dates = person_df["CollisionDate"].dropna()
    if len(dates) > 0:
        print(f"Date range:                    {dates.min()}  to  {dates.max()}")

    print()
    print("Crashes by year (YearNmb), across person-rows:")
    print(person_df["YearNmb"].value_counts().sort_index().to_string())

    print()
    print("Injury severity (InjuryClass), across person-rows:")
    print(person_df["InjuryClass"].value_counts().to_string())

    print()
    print("Person type (Pedestrian vs Other Non-Motorist):")
    print(person_df["PersonType"].value_counts().to_string())

    fatal_crashes = dedup_df[dedup_df["InjuryClass"] == "Fatal"]
    print()
    print(f"Fatal crashes (after dedup, worst injury = Fatal): {len(fatal_crashes)}")

    print()
    print("NonMotoristLocation - ALL person-rows (most common first):")
    print(person_df["NonMotoristLocation"].value_counts(dropna=False).to_string())

    print()
    print("NonMotoristLocation - FATAL crashes only (most common first):")
    # Find the report numbers of fatal crashes, then look at their person-rows.
    fatal_report_numbers = set(fatal_crashes["MstrRecNbrTxt"])
    fatal_person_rows = person_df[person_df["MstrRecNbrTxt"].isin(fatal_report_numbers)]
    print(fatal_person_rows["NonMotoristLocation"].value_counts(dropna=False).to_string())

    print()
    print("First 5 rows of the deduplicated crash file:")
    print("-" * 70)
    # Show all columns so nothing is hidden.
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(dedup_df.head(5).to_string())
    print("=" * 70)


# ---------------------------------------------------------------------------
# MAIN: ties all the steps together, including the "do we need to download?" logic.
# ---------------------------------------------------------------------------
def main():
    print("Memphis Pedestrian Safety - crash data download (Phase 1+2)")
    print("-" * 70)

    # 1. Ask the API how many records exist right now.
    print("Checking the live record count from the API...")
    api_count = get_current_api_count()
    print(f"  API currently has {api_count} matching records "
          f"(Shelby County, excluding pedalcyclists).")

    # 2. Decide whether to download fresh or reuse what we already have.
    existing_count, existing_pages = count_records_in_existing_pages()
    if existing_pages and existing_count == api_count:
        print(f"  We already have {existing_count} records saved that match the "
              f"live count - skipping download and just reprocessing.")
    else:
        if existing_pages:
            print(f"  We have {existing_count} saved records but the API now has "
                  f"{api_count} - re-downloading fresh.")
        else:
            print("  No saved data found - downloading fresh.")
        print("Downloading...")
        download_all_pages(api_count)

    # 3. Read the saved pages into one table.
    print("Reading saved pages into a table...")
    person_df = load_pages_into_dataframe()

    # 4. Save the two CSV files.
    print("Writing CSV files...")
    save_person_rows_csv(person_df)
    dedup_df = make_dedup_crash_csv(person_df)

    # 5. Print the summary and stop. (No analysis beyond this - that's later.)
    print_summary(person_df, dedup_df)


# This makes the script run main() when you execute the file.
if __name__ == "__main__":
    main()
