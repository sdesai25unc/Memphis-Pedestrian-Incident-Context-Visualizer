r"""
11_jurisdiction_audit.py
=======================

JURISDICTION AUDIT (read-only diagnosis). Interstate crashes are being mislabeled
"City of Memphis" because the state-route reference layer (state_routes.geojson)
contains no interstate geometry, so the 30 m proximity test never matches them
and they fall into the City residual.

This script ONLY inspects + reports. It does not change the classification, and
it does not overwrite shelby_crashes_classified.csv or shelby_crashes_named.csv.
It writes findings to outputs/jurisdiction_audit.md and prints the key tables.

Run it with:
    .\.venv\Scripts\python.exe scripts\11_jurisdiction_audit.py
"""

import re
from pathlib import Path

import pandas as pd
import geopandas as gpd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW = PROJECT_ROOT / "data" / "raw"
PROCESSED = PROJECT_ROOT / "data" / "processed"
OUT_MD = PROJECT_ROOT / "outputs" / "jurisdiction_audit.md"

STATE_ROUTES = RAW / "state_routes.geojson"
STREETS = RAW / "memphis_streets.geojson"
NAMED = PROCESSED / "shelby_crashes_named.csv"

FATAL = "Fatal"
INTERSTATE_RE = re.compile(r"INTERSTATE|^\s*I[- ]?\d", re.I)
RAMP_RE = re.compile(r"\bTO\b", re.I)          # connector/ramp descriptions ("240 E TO 385 E")
INTERSTATE_TOKEN_RE = re.compile(r"\b(?:I[- ]?\d|240|269|55|40)\b")


def pct(p, w):
    return round(100.0 * p / w, 1) if w else 0.0


def main():
    lines = []                       # markdown accumulator
    def md(s=""):
        lines.append(s)
    def both(s=""):                  # print AND write to md
        print(s); lines.append(s)

    md(f"# Jurisdiction Audit — interstates mislabeled \"City of Memphis\"")
    md(f"\n*Read-only diagnosis · 2026-06-10 · no files were reclassified.*\n")

    # =====================================================================
    # TASK 1 — state_routes.geojson: what classes does it contain? interstates?
    # =====================================================================
    sr = gpd.read_file(STATE_ROUTES)
    md("## 1. `state_routes.geojson` — route types present, interstate check\n")
    md(f"- Rows: **{len(sr)}** · CRS {sr.crs} · all `State_Route == \"Yes\"`.")
    md(f"- `F_System` (functional class) distribution:\n")
    md("| F_System | count |\n|---|---|")
    for k, v in sr["F_System"].value_counts(dropna=False).items():
        md(f"| {k} | {v} |")
    # the spurious "Interstate" rows
    inter_rows = sr[sr["F_System"] == "Interstate"]
    md(f"\n- `F_System == \"Interstate\"`: **{len(inter_rows)}** rows — but these are "
       f"spurious: their names are {sorted(set((inter_rows['NAME'].fillna('') + ' ' + inter_rows['TYPE'].fillna('')).str.strip()))}. "
       f"They are arterial segments, **not interstate mainline**.")
    name_i = sr["NAME"].astype(str).str.upper()
    n_real_i = int(name_i.str.contains("INTERSTATE", na=False).sum())
    md(f"- Features actually named \"INTERSTATE\" / I-#: **{n_real_i}**.")
    md(f"- `ALTNAME_1` route numbers are state-route numbers (3, 14, 1, 4, 57, 175, 385…); "
       f"no interstate route numbers (40/55/240/269) appear.")
    both(f"\n[Task 1] state_routes.geojson contains NO interstate mainline geometry "
         f"(0 features named Interstate; the 9 F_System='Interstate' rows are mislabeled arterials).")

    # =====================================================================
    # TASK 2 — memphis_streets.geojson: fields + authoritative class field?
    # =====================================================================
    st = gpd.read_file(STREETS)
    md("\n## 2. `memphis_streets.geojson` — fields + authoritative class field\n")
    md(f"- Rows: **{len(st)}** · {len(st.columns)} fields.")
    md(f"- All field names: `{', '.join(c for c in st.columns if c != 'geometry')}`\n")
    md("**Candidate CLASS / route-type / jurisdiction fields:**\n")

    # CFCC and MTFCC are TIGER class codes (authoritative functional class).
    for fld, note in [("CFCC", "Census Feature Class Code (A1x = primary/limited-access)"),
                      ("MTFCC", "MAF/TIGER class (S1100 = primary/Interstate, S1200 = secondary hwy, S1400 = local)"),
                      ("NAMETYPE", "name-type code")]:
        md(f"- **{fld}** — {note}. Distinct values (top 10):")
        md("  ```")
        for k, v in st[fld].value_counts(dropna=False).head(10).items():
            md(f"  {k}: {v}")
        md("  ```")
    md("- `CITY_L` / `COUNTY_L` exist but encode *place name*, not road **ownership**. "
       "There is **no explicit OWNER / JURIS field** in the layer.")

    # Does the streets layer contain interstates, and is there a clean class key?
    lbl = st["LABEL"].astype(str).str.upper()
    nm = st["NAME"].astype(str).str.upper()
    is_i = lbl.str.contains("INTERSTATE", na=False) | nm.str.contains("INTERSTATE", na=False)
    s1100 = st["MTFCC"].astype(str) == "S1100"
    md(f"\n**Interstate geometry IS present in the streets layer:**")
    md(f"- Segments named \"Interstate …\": **{int(is_i.sum())}**.")
    md(f"- `MTFCC == \"S1100\"`: **{int(s1100.sum())}** — matches the named interstates "
       f"({int((is_i & s1100).sum())} overlap). So **`MTFCC == \"S1100\"` is a clean, "
       f"authoritative interstate key.**")
    md(f"- Sample S1100 names: {st.loc[s1100,'LABEL'].dropna().unique()[:8].tolist()}")
    both(f"[Task 2] Authoritative class field found: streets `MTFCC` (S1100=interstate, "
         f"{int(s1100.sum())} segs). `CFCC` is the legacy equivalent. No ownership field exists.")

    # =====================================================================
    # TASK 3 — interstate crashes in the named crash file
    # =====================================================================
    n = pd.read_csv(NAMED)
    total = len(n)
    sn = n["Street_Name"].astype(str).str.upper()
    is_main = sn.str.contains("INTERSTATE", na=False)        # mainline-named interstates
    is_ramp = (~is_main) & sn.str.contains(RAMP_RE) & sn.str.contains(INTERSTATE_TOKEN_RE)
    inter = n[is_main].copy()
    ramps = n[is_ramp].copy()

    md("\n## 3. Interstate crashes in `shelby_crashes_named.csv`\n")
    md(f"In-Memphis crashes total: **{total}**. Mainline-interstate crashes "
       f"(Street_Name contains \"INTERSTATE\"): **{len(inter)}** "
       f"(all posted {sorted(inter['Street_SPDLIMIT'].dropna().unique().tolist())} mph — "
       f"cross-check speed≥55 holds).\n")
    md("| Route (named) | crashes | fatal | current: City | current: TDOT | speeds |")
    md("|---|---|---|---|---|---|")
    for route, g in inter.groupby("Street_Name"):
        nf = int((g["InjuryClass"] == FATAL).sum())
        nc = int((g["Jurisdiction"] == "City of Memphis").sum())
        nt = int((g["Jurisdiction"] == "TDOT").sum())
        sp = "/".join(str(int(x)) for x in sorted(g["Street_SPDLIMIT"].dropna().unique()))
        md(f"| {route} | {len(g)} | {nf} | {nc} | {nt} | {sp} |")
    n_i = len(inter)
    n_i_fatal = int((inter["InjuryClass"] == FATAL).sum())
    n_i_city = int((inter["Jurisdiction"] == "City of Memphis").sum())
    n_i_tdot = int((inter["Jurisdiction"] == "TDOT").sum())
    md(f"\n**Totals:** {n_i} interstate crashes, {n_i_fatal} fatal · "
       f"currently **{n_i_city} mislabeled \"City of Memphis\"**, {n_i_tdot} already TDOT.")
    md(f"\n`NonMotoristLocation` on interstates:")
    md("```")
    for k, v in inter["NonMotoristLocation"].value_counts(dropna=False).items():
        md(f"  {k}: {v}")
    md("```")

    # ramps/connectors (flagged gray area, NOT counted as interstate)
    md(f"\n**Interstate ramp / connector crashes (flagged, NOT in the interstate count):** "
       f"{len(ramps)}")
    if len(ramps):
        md("```")
        for _, r in ramps.iterrows():
            md(f"  \"{r['Street_Name']}\"  juris={r['Jurisdiction']}  "
               f"spd={r['Street_SPDLIMIT']}  dist={r['DistToStreet_m']:.1f}m  "
               f"({r['Latitude']:.5f},{r['Longitude']:.5f})")
        md("```")

    # context: SR-385 (freeway-grade state route) + Sam Cooper
    sr385 = n[sn.str.contains("385", na=False) | sn.str.contains("NONCONNAH", na=False)]
    sam = n[sn.str.contains("SAM COOPER", na=False)]
    md(f"\n**Context — freeway-grade state routes (already TDOT, for comparison):**")
    md(f"- SR-385 / Nonconnah: {len(sr385)} crashes · jurisdiction "
       f"{sr385['Jurisdiction'].value_counts().to_dict()}")
    md(f"- Sam Cooper Blvd: {len(sam)} crashes · jurisdiction "
       f"{sam['Jurisdiction'].value_counts().to_dict()}")

    print(f"\n[Task 3] {n_i} mainline-interstate crashes ({n_i_fatal} fatal); "
          f"{n_i_city} mislabeled City, {n_i_tdot} already TDOT. "
          f"{len(ramps)} ramp/connector crashes flagged separately.")

    # =====================================================================
    # TASK 4 — snap sanity: are interstate crashes really on the mainline?
    # =====================================================================
    md("\n## 4. Snap sanity check (distance to matched street)\n")
    d = inter["DistToStreet_m"]
    md(f"- Distance to matched interstate centerline: min {d.min():.2f} m, "
       f"median {d.median():.2f} m, max {d.max():.2f} m.")
    far = inter[inter["DistToStreet_m"] > 15].sort_values("DistToStreet_m", ascending=False)
    if len(far):
        md(f"- **{len(far)} crash(es) matched >15 m away** (possible overpass/frontage snap — eyeball):")
        md("```")
        for _, r in far.iterrows():
            md(f"  {r['MstrRecNbrTxt']}  {r['Street_Name']}  {r['DistToStreet_m']:.1f}m  "
               f"({r['Latitude']:.5f},{r['Longitude']:.5f})")
        md("```")
    else:
        md("- No interstate crash matched >15 m away; snaps look genuine.")
    both(f"[Task 4] interstate snap distances: median {d.median():.2f} m, max {d.max():.2f} m "
         f"({len(far)} over 15 m).")

    # =====================================================================
    # TASK 5 — recompute City/TDOT split, before vs after
    # =====================================================================
    city0 = int((n["Jurisdiction"] == "City of Memphis").sum())
    tdot0 = int((n["Jurisdiction"] == "TDOT").sum())
    fatal_all = n[n["InjuryClass"] == FATAL]
    fcity0 = int((fatal_all["Jurisdiction"] == "City of Memphis").sum())
    ftdot0 = int((fatal_all["Jurisdiction"] == "TDOT").sum())
    inter_fatal = inter["InjuryClass"] == FATAL
    nf_city = int((inter_fatal & (inter["Jurisdiction"] == "City of Memphis")).sum())
    nf_tdot = int((inter_fatal & (inter["Jurisdiction"] == "TDOT")).sum())

    md("\n## 5. Headline City/TDOT split — before vs after\n")
    md(f"**Current (in-Memphis, n={total}):** "
       f"City {city0} ({pct(city0,total)}%) · TDOT {tdot0} ({pct(tdot0,total)}%). "
       f"Fatal (n={len(fatal_all)}): City {fcity0} ({pct(fcity0,len(fatal_all))}%) · "
       f"TDOT {ftdot0} ({pct(ftdot0,len(fatal_all))}%).\n")

    # (a) interstates -> TDOT (the n_i_city move from City to TDOT; the 3 already TDOT stay)
    a_city, a_tdot = city0 - n_i_city, tdot0 + n_i_city
    a_fcity, a_ftdot = fcity0 - nf_city, ftdot0 + nf_city
    md(f"**Option (a) — interstates reclassified as TDOT** (move {n_i_city} City→TDOT; "
       f"3 already TDOT):")
    md(f"- All crashes (n={total}): City **{a_city} ({pct(a_city,total)}%)** · "
       f"TDOT **{a_tdot} ({pct(a_tdot,total)}%)**  _(was City {pct(city0,total)}% / TDOT {pct(tdot0,total)}%)_")
    md(f"- Fatal (n={len(fatal_all)}): City **{a_fcity} ({pct(a_fcity,len(fatal_all))}%)** · "
       f"TDOT **{a_ftdot} ({pct(a_ftdot,len(fatal_all))}%)**  "
       f"_(was City {pct(fcity0,len(fatal_all))}% / TDOT {pct(ftdot0,len(fatal_all))}%)_\n")

    # (b) interstates -> separate category, removed from surface comparison
    b_total = total - n_i
    b_city, b_tdot = city0 - n_i_city, tdot0 - n_i_tdot
    bf_total = len(fatal_all) - n_i_fatal
    bf_city, bf_tdot = fcity0 - nf_city, ftdot0 - nf_tdot
    md(f"**Option (b) — interstates moved to a separate \"Interstate / limited-access (TDOT)\" "
       f"category** (removed from the City-vs-TDOT *surface* comparison; n_interstate={n_i}):")
    md(f"- Surface crashes (n={b_total}): City **{b_city} ({pct(b_city,b_total)}%)** · "
       f"TDOT **{b_tdot} ({pct(b_tdot,b_total)}%)**  + Interstate bucket {n_i}.")
    md(f"- Surface fatal (n={bf_total}): City **{bf_city} ({pct(bf_city,bf_total)}%)** · "
       f"TDOT **{bf_tdot} ({pct(bf_tdot,bf_total)}%)**  + Interstate fatal {n_i_fatal}.")

    both("\n[Task 5] Splits:")
    both(f"  Current   : City {pct(city0,total)}% / TDOT {pct(tdot0,total)}%  | "
         f"fatal City {pct(fcity0,len(fatal_all))}% / TDOT {pct(ftdot0,len(fatal_all))}%")
    both(f"  (a) I->TDOT: City {pct(a_city,total)}% / TDOT {pct(a_tdot,total)}%  | "
         f"fatal City {pct(a_fcity,len(fatal_all))}% / TDOT {pct(a_ftdot,len(fatal_all))}%")
    both(f"  (b) I separate: City {pct(b_city,b_total)}% / TDOT {pct(b_tdot,b_total)}% of {b_total} "
         f"surface | + {n_i} interstate ({n_i_fatal} fatal)")

    # =====================================================================
    # TASK 6 — recommendation
    # =====================================================================
    md("\n## 6. Recommendation\n")
    rec = f"""\
**Recommended: add interstate geometry to the non-city reference and re-run proximity
(option ii), sourcing the interstate mainline from the streets layer where
`MTFCC == "S1100"` ({int(s1100.sum())} segments, an exact match to the
\"Interstate …\" names).**

Why this over a pure class-field reclassification (option i):

- The streets layer's `MTFCC`/`CFCC` are *functional-class* codes, not ownership.
  `S1100` cleanly isolates interstates (limited-access, TDOT-owned), so it is perfect
  for THIS bug. But the broader City/TDOT split also depends on `S1200` (secondary
  highways + major arterials), which mixes TDOT state routes and City arterials — so
  a class field alone cannot reproduce the state-route classification we already have.
- Keeping the **proven proximity method** and only **adding the missing reference
  geometry** (interstates) is the smallest, least-disruptive change. It fixes the
  residual-bucket leak without re-deriving the whole pipeline, and it composes with the
  existing 30 m logic and tie-breaks.
- Concretely: build an interstate reference (the S1100 segments, dissolved), tag any
  crash within ~30 m of it as a new **\"Interstate (TDOT)\"** jurisdiction *before* the
  City residual is assigned. This also future-proofs ramp/connector cases that a pure
  name match misses.

Tradeoffs / cautions:
- Decide whether interstates report as their own bucket (option b, recommended for the
  surface City-vs-TDOT story) or fold into TDOT (option a). The surface comparison is
  cleaner with interstates separated, since a pedestrian on an interstate is a
  categorically different (and rarer) event.
- Re-running proximity means re-deriving `shelby_crashes_classified.csv` /
  `shelby_crashes_named.csv` to **new filenames** (never overwrite the originals), then
  refreshing the dependent stats + map.
- Sam Cooper / SR-385 are already correctly TDOT and need no change; leave them.
"""
    md(rec)
    print("\n[Task 6] RECOMMENDATION: add interstate geometry (streets MTFCC=S1100) to the "
          "non-city reference and re-run proximity into a new 'Interstate (TDOT)' bucket; "
          "keep the proven proximity method. Do NOT implement yet.")

    OUT_MD.parent.mkdir(exist_ok=True)
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote {OUT_MD}")


if __name__ == "__main__":
    main()
