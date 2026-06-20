# Jurisdiction Audit — interstates mislabeled "City of Memphis"

*Read-only diagnosis · 2026-06-10 · no files were reclassified.*

## 1. `state_routes.geojson` — route types present, interstate check

- Rows: **1652** · CRS EPSG:4326 · all `State_Route == "Yes"`.
- `F_System` (functional class) distribution:

| F_System | count |
|---|---|
| Principal Arterial | 1123 |
| Minor Arterial | 361 |
| None | 102 |
| Freeway and Expressway | 32 |
| Major Collector | 25 |
| Interstate | 9 |

- `F_System == "Interstate"`: **9** rows — but these are spurious: their names are ['PARKWAY', 'POPLAR AVE', 'THIRD ST']. They are arterial segments, **not interstate mainline**.
- Features actually named "INTERSTATE" / I-#: **0**.
- `ALTNAME_1` route numbers are state-route numbers (3, 14, 1, 4, 57, 175, 385…); no interstate route numbers (40/55/240/269) appear.

[Task 1] state_routes.geojson contains NO interstate mainline geometry (0 features named Interstate; the 9 F_System='Interstate' rows are mislabeled arterials).

## 2. `memphis_streets.geojson` — fields + authoritative class field

- Rows: **55141** · 63 fields.
- All field names: `OBJECTID, OIRID, SEGID, L_F_ADD, L_T_ADD, R_F_ADD, R_T_ADD, ADDR_TYPE, PREDIR, PRETYPE, NAME, TYPE, SUFDIR, POSTMOD, LABEL, VANITY, SUBNAME, NAMETYPE, CFCC, ESN_L, ESN_R, ZIP_L, ZIP_R, CITY_L, CITY_R, COUNTY_L, COUNTY_R, STATE_L, STATE_R, SPDLIMIT, ONEWAY, LANES, T_ELEV, F_ELEV, TFCOST, FTCOST, EDITOR, GEOMOD, GEOSRCE, GEODATE, ATTMOD, ATTSRCE, ATTDATE, STATUS, ALTNAME_1, ALTNAME_2, ALTNAME_3, ALTNAME_4, ALTNAME_5, ALTNAME_6, ALTNAME_7, ALTNAME_8, TRACKING_OIRID1, TRACKING_OIRID2, TRACKING_OIRID3, TRACKING_OIRID4, BRDG_HGHT_PSTD, BRDG_HGHT_MSRD, HONORARY_NAME, CAD_NAME, MTFCC, Shape.STLength()`

**Candidate CLASS / route-type / jurisdiction fields:**

- **CFCC** — Census Feature Class Code (A1x = primary/limited-access). Distinct values (top 10):
  ```
  A41: 38742
  A61: 5398
  A31: 4954
  A74: 1317
  A63: 964
  A21: 945
  A15: 887
  A73: 789
  A35: 498
  A25: 381
  ```
- **MTFCC** — MAF/TIGER class (S1100 = primary/Interstate, S1200 = secondary hwy, S1400 = local). Distinct values (top 10):
  ```
  S1400: 46973
  S1200: 3852
  S1730: 1147
  S1630: 997
  S1740: 705
  S1735: 591
  S1100: 577
  S1110: 241
  S1640: 31
  S1820: 22
  ```
- **NAMETYPE** — name-type code. Distinct values (top 10):
  ```
  8: 55141
  ```
- `CITY_L` / `COUNTY_L` exist but encode *place name*, not road **ownership**. There is **no explicit OWNER / JURIS field** in the layer.

**Interstate geometry IS present in the streets layer:**
- Segments named "Interstate …": **577**.
- `MTFCC == "S1100"`: **577** — matches the named interstates (577 overlap). So **`MTFCC == "S1100"` is a clean, authoritative interstate key.**
- Sample S1100 names: ['Interstate 240 West', 'Interstate 240 East', 'Interstate 40 East', 'Interstate 55 North', 'Interstate 55 South', 'Interstate 240 North', 'Interstate 40 West', 'Interstate 240 South']
[Task 2] Authoritative class field found: streets `MTFCC` (S1100=interstate, 577 segs). `CFCC` is the legacy equivalent. No ownership field exists.

## 3. Interstate crashes in `shelby_crashes_named.csv`

In-Memphis crashes total: **1294**. Mainline-interstate crashes (Street_Name contains "INTERSTATE"): **23** (all posted [65.0] mph — cross-check speed≥55 holds).

| Route (named) | crashes | fatal | current: City | current: TDOT | speeds |
|---|---|---|---|---|---|
| INTERSTATE 240 E | 5 | 2 | 4 | 1 | 65 |
| INTERSTATE 240 S | 1 | 1 | 1 | 0 | 65 |
| INTERSTATE 240 W | 8 | 2 | 6 | 2 | 65 |
| INTERSTATE 40 E | 3 | 2 | 3 | 0 | 65 |
| INTERSTATE 40 W | 5 | 2 | 5 | 0 | 65 |
| INTERSTATE 55 N | 1 | 1 | 1 | 0 | 65 |

**Totals:** 23 interstate crashes, 10 fatal · currently **20 mislabeled "City of Memphis"**, 3 already TDOT.

`NonMotoristLocation` on interstates:
```
  Not Intersection-On Roadway Crosswalk not Available: 9
  Not Intersection-On Roadway Not In Crosswalk: 3
  Not Intersection-Adjacent to Roadway: 3
  Intersection-On Roadway not in Crosswalk: 2
  Not Intersection-Other Not On Roadway: 1
  Intersection-On Roadway Crosswalk Not Available: 1
  Not Intersection-Outside Traffic: 1
  Intersection-Not on Roadway: 1
  Not Intersection-Unknown: 1
  Unknown: 1
```

**Interstate ramp / connector crashes (flagged, NOT in the interstate count):** 4
```
  "40 W TO DANNY THOMAS BLVD"  juris=TDOT  spd=25.0  dist=2.0m  (35.15181,-90.04047)
  "240 E TO 385 E"  juris=City of Memphis  spd=45.0  dist=1.0m  (35.08359,-89.88082)
  "40 S TO 240 E"  juris=City of Memphis  spd=45.0  dist=72.5m  (35.15432,-89.88554)
  "MILLBRANCH RD OR NONCONNAH BLVD TO 240 E"  juris=City of Memphis  spd=45.0  dist=0.1m  (35.07429,-90.00193)
```

**Context — freeway-grade state routes (already TDOT, for comparison):**
- SR-385 / Nonconnah: 7 crashes · jurisdiction {'TDOT': 4, 'City of Memphis': 3}
- Sam Cooper Blvd: 4 crashes · jurisdiction {'City of Memphis': 3, 'TDOT': 1}

## 4. Snap sanity check (distance to matched street)

- Distance to matched interstate centerline: min 0.02 m, median 0.27 m, max 21.28 m.
- **1 crash(es) matched >15 m away** (possible overpass/frontage snap — eyeball):
```
  300928926  INTERSTATE 240 E  21.3m  (35.14372,-89.87304)
```
[Task 4] interstate snap distances: median 0.27 m, max 21.28 m (1 over 15 m).

## 5. Headline City/TDOT split — before vs after

**Current (in-Memphis, n=1294):** City 966 (74.7%) · TDOT 328 (25.3%). Fatal (n=175): City 123 (70.3%) · TDOT 52 (29.7%).

**Option (a) — interstates reclassified as TDOT** (move 20 City→TDOT; 3 already TDOT):
- All crashes (n=1294): City **946 (73.1%)** · TDOT **348 (26.9%)**  _(was City 74.7% / TDOT 25.3%)_
- Fatal (n=175): City **114 (65.1%)** · TDOT **61 (34.9%)**  _(was City 70.3% / TDOT 29.7%)_

**Option (b) — interstates moved to a separate "Interstate / limited-access (TDOT)" category** (removed from the City-vs-TDOT *surface* comparison; n_interstate=23):
- Surface crashes (n=1271): City **946 (74.4%)** · TDOT **325 (25.6%)**  + Interstate bucket 23.
- Surface fatal (n=165): City **114 (69.1%)** · TDOT **51 (30.9%)**  + Interstate fatal 10.

[Task 5] Splits:
  Current   : City 74.7% / TDOT 25.3%  | fatal City 70.3% / TDOT 29.7%
  (a) I->TDOT: City 73.1% / TDOT 26.9%  | fatal City 65.1% / TDOT 34.9%
  (b) I separate: City 74.4% / TDOT 25.6% of 1271 surface | + 23 interstate (10 fatal)

## 6. Recommendation

**Recommended: add interstate geometry to the non-city reference and re-run proximity
(option ii), sourcing the interstate mainline from the streets layer where
`MTFCC == "S1100"` (577 segments, an exact match to the
"Interstate …" names).**

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
  crash within ~30 m of it as a new **"Interstate (TDOT)"** jurisdiction *before* the
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

