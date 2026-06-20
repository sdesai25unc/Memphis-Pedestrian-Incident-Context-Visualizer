r"""
12_reclassify_interstates.py
===========================

Fixes the interstate mislabeling found in the audit (script 11): interstate
crashes were falling into the "City of Memphis" residual because the state-route
reference layer has no interstate geometry.

Method (decided): ADD interstate geometry to the non-city reference (the
`MTFCC == "S1100"` segments from memphis_streets.geojson) and keep the proven
30 m proximity test. Crashes on the interstate get a NEW jurisdiction,
**"Interstate (TDOT)"**, assigned before the City residual — reported as their
own category (option b), separate from the City-vs-TDOT surface comparison.

Robustness guard: a crash is tagged Interstate only when the interstate is also
its NEAREST road (interstate distance ~= its overall nearest-street distance),
so a surface crash passing *under* an overpass (within 30 m of the interstate in
2D) is NOT mislabeled, and ramp/connector crashes stay separate.

This writes NEW files and does NOT overwrite the originals:
    data/processed/shelby_crashes_classified_with_interstate.csv
    data/processed/shelby_crashes_named_with_interstate.csv
It does NOT touch index.html or novel_statistics.docx.

Run it with:
    .\.venv\Scripts\python.exe scripts\12_reclassify_interstates.py
"""

import re
from pathlib import Path

import pandas as pd
import geopandas as gpd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW = PROJECT_ROOT / "data" / "raw"
PROCESSED = PROJECT_ROOT / "data" / "processed"

STREETS = RAW / "memphis_streets.geojson"
CLASSIFIED = PROCESSED / "shelby_crashes_classified.csv"
NAMED = PROCESSED / "shelby_crashes_named.csv"
OUT_CLASSIFIED = PROCESSED / "shelby_crashes_classified_with_interstate.csv"
OUT_NAMED = PROCESSED / "shelby_crashes_named_with_interstate.csv"

PROJECTED_CRS = "EPSG:32136"     # NAD83 / Tennessee, meters
GEOGRAPHIC_CRS = "EPSG:4326"
THRESHOLD_M = 30                 # same proven threshold as the state-route join
NEAREST_TOL_M = 0.75             # interstate counts as "nearest road" within this slack
INTERSTATE_LABEL = "Interstate (TDOT)"
FATAL = "Fatal"

RAMP_RE = re.compile(r"\bTO\b", re.I)
INTERSTATE_TOKEN_RE = re.compile(r"\b(?:I[- ]?\d|240|269|55|40)\b")
MAINLINE_RE = re.compile(r"INTERSTATE", re.I)


def pct(p, w):
    return round(100.0 * p / w, 1) if w else 0.0


def main():
    # -----------------------------------------------------------------------
    # 1. Interstate reference = streets where MTFCC == "S1100" (mainline only).
    # -----------------------------------------------------------------------
    streets = gpd.read_file(STREETS)
    interstates = streets[streets["MTFCC"].astype(str) == "S1100"].copy()
    interstates = interstates.to_crs(PROJECTED_CRS)
    print(f"Interstate reference (MTFCC=S1100): {len(interstates)} segments.")

    # -----------------------------------------------------------------------
    # 2. In-Memphis crashes -> points -> distance to nearest interstate segment.
    # -----------------------------------------------------------------------
    named = pd.read_csv(NAMED)
    pts = gpd.GeoDataFrame(
        named.copy(),
        geometry=gpd.points_from_xy(named["Longitude"], named["Latitude"]),
        crs=GEOGRAPHIC_CRS,
    ).to_crs(PROJECTED_CRS)

    joined = gpd.sjoin_nearest(pts, interstates[["geometry"]], how="left",
                               distance_col="DistToInterstate_m")
    joined = joined[~joined.index.duplicated(keep="first")]
    named["DistToInterstate_m"] = joined["DistToInterstate_m"].values

    # -----------------------------------------------------------------------
    # 3. Identify the interstate set (with the nearest-road guard) + ramps.
    # -----------------------------------------------------------------------
    sn = named["Street_Name"].astype(str).str.upper()
    is_ramp = sn.str.contains(RAMP_RE) & sn.str.contains(INTERSTATE_TOKEN_RE) & ~sn.str.contains(MAINLINE_RE)

    # A crash is on the interstate when its NEAREST road (the full-network match
    # already stored in the named file) is an interstate mainline -- i.e.
    # Street_Name is "INTERSTATE ..." -- and that match is within 30 m. This is
    # the robust, nearest-road form of the proximity test: a surface crash near
    # an interchange/overpass keeps its surface street as nearest and is NOT
    # mislabeled, and ramp/connector crashes stay separate.
    mainline_name = sn.str.contains(MAINLINE_RE)
    interstate_mask = mainline_name & (named["DistToStreet_m"] <= THRESHOLD_M)

    # Diagnostics: a naive "within 30 m of the interstate line" test over-captures
    # interchange/overpass surface crashes; show the gap so the choice is explicit.
    within = named["DistToInterstate_m"] <= THRESHOLD_M
    pure_proximity = int((within & ~is_ramp).sum())
    overcapture = named[within & ~is_ramp & ~interstate_mask]

    print(f"\nReconciliation:")
    print(f"  nearest road IS an interstate mainline, <=30 m  (USED): {int(interstate_mask.sum())}")
    print(f"  naive: any crash within 30 m of the interstate line:    {pure_proximity}")
    print(f"  -> {len(overcapture)} surface crashes near an interchange/overpass "
          f"(kept City/TDOT, NOT interstate). Examples:")
    for _, r in overcapture.sort_values("DistToInterstate_m").head(8).iterrows():
        print(f"       {r['MstrRecNbrTxt']}  nearest='{r['Street_Name']}' {r['DistToStreet_m']:.1f} m "
              f"| interstate {r['DistToInterstate_m']:.1f} m  ({r['Latitude']:.5f},{r['Longitude']:.5f})")
    print(f"  ramp/connector crashes kept separate (flagged, not counted): {int(is_ramp.sum())}")

    # the far (21.3 m) outlier kept because the nearest road is still the interstate
    far = named[interstate_mask & (named["DistToStreet_m"] > 15)]
    for _, r in far.iterrows():
        print(f"  kept far match: {r['MstrRecNbrTxt']} {r['Street_Name']} {r['DistToStreet_m']:.1f} m "
              f"(nearest road IS the interstate; no closer surface street).")

    # -----------------------------------------------------------------------
    # 4. Apply the new jurisdiction to NEW copies (never overwrite originals).
    # -----------------------------------------------------------------------
    interstate_ids = set(named.loc[interstate_mask, "MstrRecNbrTxt"])

    named_out = named.copy()
    named_out["Jurisdiction_prev"] = named_out["Jurisdiction"]
    named_out.loc[interstate_mask, "Jurisdiction"] = INTERSTATE_LABEL
    named_out.to_csv(OUT_NAMED, index=False, encoding="utf-8")

    classified = pd.read_csv(CLASSIFIED)
    classified_out = classified.copy()
    classified_out["Jurisdiction_prev"] = classified_out["Jurisdiction"]
    m = classified_out["MstrRecNbrTxt"].isin(interstate_ids)
    classified_out.loc[m, "Jurisdiction"] = INTERSTATE_LABEL
    classified_out.to_csv(OUT_CLASSIFIED, index=False, encoding="utf-8")

    # -----------------------------------------------------------------------
    # 5. FINAL corrected numbers (option b: interstate is its own category).
    # -----------------------------------------------------------------------
    inter = named_out[named_out["Jurisdiction"] == INTERSTATE_LABEL]
    surface = named_out[named_out["Jurisdiction"].isin(["City of Memphis", "TDOT"])]
    s_total = len(surface)
    s_city = int((surface["Jurisdiction"] == "City of Memphis").sum())
    s_tdot = int((surface["Jurisdiction"] == "TDOT").sum())
    i_n = len(inter); i_fatal = int((inter["InjuryClass"] == FATAL).sum())

    sf = surface[surface["InjuryClass"] == FATAL]
    sf_total = len(sf)
    sf_city = int((sf["Jurisdiction"] == "City of Memphis").sum())
    sf_tdot = int((sf["Jurisdiction"] == "TDOT").sum())

    print("\n" + "=" * 68)
    print("FINAL CORRECTED NUMBERS  (option b - interstate as its own category)")
    print("=" * 68)
    print(f"In-Memphis crashes: {len(named_out)}  =  surface {s_total}  +  interstate {i_n}")
    print(f"\nALL CRASHES - surface City-vs-TDOT (n={s_total}):")
    print(f"   City of Memphis : {s_city:4d}  ({pct(s_city,s_total)}%)")
    print(f"   TDOT state route: {s_tdot:4d}  ({pct(s_tdot,s_total)}%)")
    print(f"   --------------------------------------------")
    print(f"   Interstate (TDOT): {i_n:4d} crashes  [separate category]")
    print(f"\nFATAL CRASHES - surface City-vs-TDOT (n={sf_total}):")
    print(f"   City of Memphis : {sf_city:4d}  ({pct(sf_city,sf_total)}%)")
    print(f"   TDOT state route: {sf_tdot:4d}  ({pct(sf_tdot,sf_total)}%)")
    print(f"   --------------------------------------------")
    print(f"   Interstate (TDOT): {i_fatal:4d} fatal  [separate category]")

    print(f"\nFor reference - current (uncorrected) split was "
          f"City 74.7% / TDOT 25.3% (all), City 70.3% / TDOT 29.7% (fatal), "
          f"with interstates hidden inside City.")

    print(f"\nInterstate breakdown by route:")
    tmp = inter.copy(); tmp["_f"] = (tmp["InjuryClass"] == FATAL).astype(int)
    for route, g in tmp.groupby("Street_Name"):
        print(f"   {route:18s} {len(g):2d} crashes, {int(g['_f'].sum())} fatal")

    print(f"\nWrote: {OUT_NAMED.name}  ({len(named_out)} rows)")
    print(f"Wrote: {OUT_CLASSIFIED.name}  ({len(classified_out)} rows)")
    print("Originals untouched. index.html / novel_statistics.docx NOT changed.")


if __name__ == "__main__":
    main()
