# State-route tagging — completeness audit (read-only)

*Nothing reclassified; no map/docx/data changes. Checks each known corridor against an external truth list, not the layer alone.*

## 1. Corridor completeness (within the span the layer covers each route)

| corridor | covered-span centerline (mi) | % tagged TDOT | under-tagged stretches |
|---|---|---|---|
| Elvis Presley Blvd (US-51/SR-3) | 7.98 | 100.0% | 0 seg, 0.00 mi |
| Bellevue Blvd (US-51) [layer = S span only] | 1.91 | 100.0% | 0 seg, 0.00 mi |
| Danny Thomas / Thomas (US-51) | 9.23 | 100.0% | 0 seg, 0.00 mi |
| Third St (US-61 / SR-14) | 11.32 | 100.0% | 0 seg, 0.00 mi |
| E H Crump Blvd (US-61/70) | 2.74 | 100.0% | 0 seg, 0.00 mi |
| Union Ave (US-64/70/79 / SR-23) [partial] | 4.41 | 99.2% | 0 seg, 0.00 mi |
| Summer Ave (SR-1 / US-64/70/79) | 8.94 | 100.0% | 0 seg, 0.00 mi |
| North Parkway (SR-1) | 6.29 | 100.0% | 0 seg, 0.00 mi |
| Poplar Ave (SR-57 / US-72) [partial] | 9.92 | 98.0% | 0 seg, 0.00 mi |
| Walnut Grove Rd (SR-23) [partial] | 6.68 | 97.4% | 2 seg, 0.10 mi |
| Lamar Ave (US-78 / SR-4) | 17.54 | 99.0% | 0 seg, 0.00 mi |
| Airways Blvd / East Parkway (SR-277) | 4.53 | 98.7% | 0 seg, 0.00 mi |

*Flagged (<90% of covered span tagged): none.*

*SR-385 / Nonconnah is omitted from this table: the layer names it "STATE ROUTE 385" while the centerline calls it Nonconnah/Bill Morris, so name-key coverage is N/A; it is tagged via the geometric (≥85%) override instead, and Bill Morris Pkwy proper is a layer-level gap (below).*

## 2. Threshold under-tag segments — 11 City segments that lie ≥20% along a SAME-NAMED state route

```
  AUSTIN PEAY         1 seg  (0.04 mi)  ov_same 0.31–0.31
  COVINGTON           2 seg  (0.03 mi)  ov_same 0.26–0.26
  E G E PATTERSON     1 seg  (0.02 mi)  ov_same 0.21–0.21
  JACKSON             3 seg  (0.15 mi)  ov_same 0.31–0.39
  STATE ROUTE 385     1 seg  (0.03 mi)  ov_same 0.25–0.25
  US HIGHWAY 64       1 seg  (0.17 mi)  ov_same 0.23–0.23
  WALNUT GROVE        2 seg  (0.10 mi)  ov_same 0.20–0.50
```

## 3. Crash impact of the threshold under-tags

- City-labeled crashes sitting on an under-tagged state-route segment: **1** (1 fatal, 0 non-fatal).
```
  300953626 FATAL JACKSON AVE          prev=TDOT  (35.17769,-89.93764)
```

**Re-judged 3 watchlist crashes vs the external list:**

- 300968447 E RAINES RD: **City correct** (no same-named state route here; corner/parallel case)
- 300981287 N BELLEVUE BLVD: **City correct** (no same-named state route here; corner/parallel case)
- 300953626 JACKSON AVE: **under-tag → should be TDOT** (on a same-named state route)

**Layer-level gap band (flagged, NOT in the range):** roads the state-route layer does not contain, so their state-route extent can't be resolved from project data. City crashes on these named streets: **4** (2 fatal).
```
  SAM COOPER BLVD: 3
  SAM COOPER BLVD W: 1
```
*(North Bellevue Blvd is treated as a Parkway-corner case, not here.)*

## 4. Corrected surface City/TDOT split — final range

- Threshold under-tag fix (applies to BOTH bounds): move **1** City crashes (1 fatal) to TDOT.
- Corner-credit (TDOT-favorable upper bound only): **58** corner crashes (5 fatal).

**ALL surface crashes (n=1263)**

| bound | City | TDOT |
|---|---|---|
| Lower (nearest-centerline + threshold fix) | 1007 (79.7%) | 256 (20.3%) |
| Upper (+ corner→state route) | 949 (75.1%) | 314 (24.9%) |

**FATAL surface crashes (n=163)**

| bound | City | TDOT |
|---|---|---|
| Lower (nearest-centerline + threshold fix) | 118 (72.4%) | 45 (27.6%) |
| Upper (+ corner→state route) | 113 (69.3%) | 50 (30.7%) |

**Final corrected range:** surface TDOT **20.3%–24.9%** (all), **27.6%–30.7%** (fatal); City **75.1%–79.7%** / **69.3%–72.4%**. City keeps the majority under both bounds. Interstate stays separate (23 / 10 fatal). Layer-level gaps (Sam Cooper / Bill Morris, 4 City crashes) are NOT in this range.
