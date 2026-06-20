r"""
16_completeness_audit.py
=======================

READ-ONLY completeness audit of the state-route tagging produced by the segment
method (script 14). It changes NOTHING (no reclassification, no map, no docx, no
new data files) — it only prints findings and writes outputs/completeness_audit.md.

Why: the road-to-road match can UNDER-tag genuine state routes (a centerline
segment that runs along a state route but fell below the 60% / name threshold was
left "City"). The earlier watchlist tested against the SAME state-route layer that
has the gap (circular), so this audit checks each known corridor explicitly.

Key signal — `ov_same_name`: the fraction of a centerline segment that lies within
10 m of a state route that SHARES its name key (PREDIR+NAME). This:
  - restricts to where the layer actually covers the corridor (partial corridors:
    the genuinely-city ends have ov_same_name = 0, so they are not flagged);
  - flags a segment that is geometrically ON a same-named state route but tagged
    City (a threshold under-tag, e.g. Jackson Ave);
  - excludes corner/parallel city streets (E Raines, N Bellevue) because no
    RAINES / N-BELLEVUE state route exists -> ov_same_name = 0.

Two-track output (per the decision):
  - THRESHOLD gaps (layer-covered, name-matched) -> folded into a corrected range.
  - LAYER-LEVEL gaps (roads the layer lacks: Sam Cooper, Bill Morris, north Bellevue)
    -> reported separately as a flagged uncertainty band, NOT folded into the range,
    and NOT name-tagged wholesale.

Run it with:
    .\.venv\Scripts\python.exe scripts\16_completeness_audit.py
"""

import re
import sys
from pathlib import Path

import pandas as pd
import geopandas as gpd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
OUT_MD = ROOT / "outputs" / "completeness_audit.md"

STREETS = RAW / "memphis_streets.geojson"
STATE_ROUTES = RAW / "state_routes.geojson"
NAMED_SEG = PROCESSED / "shelby_crashes_named_seg.csv"

CRS_M = "EPSG:32136"
CRS_GEO = "EPSG:4326"
BUF_WIDE, BUF_TIGHT = 10.0, 8.0
OV_CUTOFF, OV_OVERRIDE = 0.60, 0.85
UNDERTAG_OV = 0.20          # name-matched overlap >= this on a City segment = threshold under-tag
CITY, TDOT_SR = "City of Memphis", "TDOT state route"
INT_TDOT, INT_RAMP = "Interstate (TDOT)", "Interstate ramp"
FATAL = "Fatal"
JUNCTION_M = 10.0

# external truth -> the state-route NAME keys the layer actually stores for it
CORRIDORS = [
    ("Elvis Presley Blvd (US-51/SR-3)", ["ELVIS PRESLEY"]),
    ("Bellevue Blvd (US-51) [layer = S span only]", ["S BELLEVUE"]),
    ("Danny Thomas / Thomas (US-51)", ["N DANNY THOMAS", "S DANNY THOMAS", "THOMAS"]),
    ("Third St (US-61 / SR-14)", ["N THIRD", "S THIRD"]),
    ("E H Crump Blvd (US-61/70)", ["E E H CRUMP", "W E H CRUMP"]),
    ("Union Ave (US-64/70/79 / SR-23) [partial]", ["UNION"]),
    ("Summer Ave (SR-1 / US-64/70/79)", ["SUMMER"]),
    ("North Parkway (SR-1)", ["N PARKWAY"]),
    ("Poplar Ave (SR-57 / US-72) [partial]", ["POPLAR"]),
    ("Walnut Grove Rd (SR-23) [partial]", ["WALNUT GROVE"]),
    ("Lamar Ave (US-78 / SR-4)", ["LAMAR"]),
    ("Airways Blvd / East Parkway (SR-277)", ["AIRWAYS", "E PARKWAY"]),
]
# corridors the layer does NOT contain (or only under a mismatched name) -> layer-level band
LAYER_GAP_NAMES = ["SAM COOPER", "BILL MORRIS"]


def namekey(predir, name):
    p = "" if predir is None else str(predir).strip()
    n = "" if name is None else str(name).strip()
    p = "" if p.lower() == "nan" else p
    n = "" if n.lower() == "nan" else n
    return re.sub(r"\s+", " ", f"{p} {n}").strip().upper()


def pct(p, w):
    return round(100.0 * p / w, 1) if w else 0.0


def tag_all(st, sr):
    """Replicate script-14 Phase-1 ownership tagging -> Ownership per segment."""
    buf10 = sr.buffer(BUF_WIDE).union_all()
    buf8 = sr.buffer(BUF_TIGHT).union_all()
    cand_mask = st.intersects(buf10)
    cand = st[cand_mask].copy()
    cand["ov10"] = cand.geometry.intersection(buf10).length / cand.geometry.length
    cand["ov8"] = cand.geometry.intersection(buf8).length / cand.geometry.length
    sr_buf = gpd.GeoDataFrame({"k_sr": sr["key"]}, geometry=sr.buffer(BUF_WIDE), crs=CRS_M)
    j = gpd.sjoin(cand[["key", "geometry"]].reset_index(), sr_buf, predicate="intersects", how="inner")
    name_present = (j["key"] == j["k_sr"]).groupby(j["index"]).any()
    cand["name_present"] = cand.index.map(name_present).fillna(False)
    cand["tdot_match"] = ((cand["ov10"] >= OV_CUTOFF) & cand["name_present"]) | (cand["ov8"] >= OV_OVERRIDE)
    own = pd.Series(CITY, index=st.index)
    own.loc[cand.index[cand["tdot_match"]]] = TDOT_SR
    mt = st["MTFCC"].astype(str)
    own.loc[mt == "S1630"] = INT_RAMP
    own.loc[mt == "S1100"] = INT_TDOT
    return own.values


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    L = []
    def log(s=""):
        print(s); L.append(s)

    st = gpd.read_file(STREETS).to_crs(CRS_M)
    sr = gpd.read_file(STATE_ROUTES).to_crs(CRS_M)
    st["key"] = [namekey(p, n) for p, n in zip(st["PREDIR"], st["NAME"])]
    sr["key"] = [namekey(p, n) for p, n in zip(sr["PREDIR"], sr["NAME"])]
    st["seglen"] = st.geometry.length

    log("# State-route tagging — completeness audit (read-only)\n")
    log("*Nothing reclassified; no map/docx/data changes. Checks each known corridor "
        "against an external truth list, not the layer alone.*\n")

    print("tagging segments...")
    st["Ownership"] = tag_all(st, sr)

    # ---- ov_same_name for corridor-named segments ----
    print("computing ov_same_name...")
    sr_keys = set(sr["key"]) - {""}
    cl = st[st["key"].isin(sr_keys)].copy()
    cl["ov_same"] = 0.0
    for K in sorted(cl["key"].unique()):
        srK = sr[sr["key"] == K]
        if not len(srK):
            continue
        bufK = srK.buffer(BUF_WIDE).union_all()
        sub = cl[cl["key"] == K]
        cl.loc[sub.index, "ov_same"] = (sub.geometry.intersection(bufK).length / sub["seglen"]).values
    st["ov_same"] = 0.0
    st.loc[cl.index, "ov_same"] = cl["ov_same"].values

    # =====================================================================
    # TASK 1 — corridor completeness within the layer-covered span
    # =====================================================================
    log("## 1. Corridor completeness (within the span the layer covers each route)\n")
    log("| corridor | covered-span centerline (mi) | % tagged TDOT | under-tagged stretches |")
    log("|---|---|---|---|")
    flagged = []
    for label, keys in CORRIDORS:
        span = st[(st["key"].isin(keys)) & (st["ov_same"] > 0)]
        if not len(span):
            log(f"| {label} | 0.0 | n/a | (no covered span found) |")
            continue
        tot = span["seglen"].sum()
        tdot = span.loc[span["Ownership"] == TDOT_SR, "seglen"].sum()
        share = pct(tdot, tot)
        under = span[(span["Ownership"] == CITY) & (span["ov_same"] >= UNDERTAG_OV)]
        flag = " ⚠" if share < 90 else ""
        if share < 90:
            flagged.append(label)
        log(f"| {label}{flag} | {tot/1609.344:.2f} | {share}% | {len(under)} seg, "
            f"{under['seglen'].sum()/1609.344:.2f} mi |")
    log(f"\n*Flagged (<90% of covered span tagged): "
        f"{', '.join(flagged) if flagged else 'none'}.*")
    log("\n*SR-385 / Nonconnah is omitted from this table: the layer names it "
        "\"STATE ROUTE 385\" while the centerline calls it Nonconnah/Bill Morris, so "
        "name-key coverage is N/A; it is tagged via the geometric (≥85%) override "
        "instead, and Bill Morris Pkwy proper is a layer-level gap (below).*")

    # =====================================================================
    # TASK 2 — threshold under-tag segments (name-matched)
    # =====================================================================
    under = st[(st["Ownership"] == CITY) & (st["ov_same"] >= UNDERTAG_OV)].copy()
    under["name"] = [namekey(p, n) for p, n in zip(under["PREDIR"], under["NAME"])]
    log(f"\n## 2. Threshold under-tag segments — {len(under)} City segments that lie "
        f"≥{int(UNDERTAG_OV*100)}% along a SAME-NAMED state route\n")
    log("```")
    for K, g in under.groupby("name"):
        log(f"  {K:18s} {len(g):2d} seg  ({g['seglen'].sum()/1609.344:.2f} mi)  "
            f"ov_same {g['ov_same'].min():.2f}–{g['ov_same'].max():.2f}")
    log("```")

    # =====================================================================
    # TASK 3 — crash impact + watchlist re-judgement + layer-level band
    # =====================================================================
    n = pd.read_csv(NAMED_SEG)
    under_ids = set(st.loc[under.index, "OBJECTID"])
    on_under = n[(n["Jurisdiction"] == CITY) & (n["Seg_OBJECTID"].isin(under_ids))].copy()
    Tf = int((on_under["InjuryClass"] == FATAL).sum())
    log(f"\n## 3. Crash impact of the threshold under-tags\n")
    log(f"- City-labeled crashes sitting on an under-tagged state-route segment: "
        f"**{len(on_under)}** ({Tf} fatal, {len(on_under)-Tf} non-fatal).")
    log("```")
    for _, r in on_under.sort_values("Street_Name").iterrows():
        f = "FATAL" if r["InjuryClass"] == FATAL else "     "
        log(f"  {int(r['MstrRecNbrTxt'])} {f} {str(r['Street_Name'])[:20]:20s} "
            f"prev={r['Jurisdiction_prev']}  ({r['Latitude']:.5f},{r['Longitude']:.5f})")
    log("```")

    log("\n**Re-judged 3 watchlist crashes vs the external list:**\n")
    for mid, road in [(300968447, "E RAINES RD"), (300981287, "N BELLEVUE BLVD"), (300953626, "JACKSON AVE")]:
        verdict = ("**under-tag → should be TDOT** (on a same-named state route)"
                   if mid in {int(x) for x in on_under["MstrRecNbrTxt"]}
                   else "**City correct** (no same-named state route here; corner/parallel case)")
        log(f"- {mid} {road}: {verdict}")

    # layer-level gap band (separate; NOT folded into the range)
    nm = n["Street_Name"].astype(str).str.upper()
    band = n[(n["Jurisdiction"] == CITY) & nm.str.contains("|".join(LAYER_GAP_NAMES))]
    log(f"\n**Layer-level gap band (flagged, NOT in the range):** roads the state-route "
        f"layer does not contain, so their state-route extent can't be resolved from "
        f"project data. City crashes on these named streets: **{len(band)}** "
        f"({int((band['InjuryClass']==FATAL).sum())} fatal).")
    log("```")
    for k, v in band["Street_Name"].value_counts().items():
        log(f"  {k}: {v}")
    log("```")
    log("*(North Bellevue Blvd is treated as a Parkway-corner case, not here.)*")

    # =====================================================================
    # TASK 4 — corrected range (threshold fix in BOTH bounds; corner only in upper)
    # =====================================================================
    surface = n[n["Jurisdiction"].isin([CITY, TDOT_SR])]
    s_city = int((surface["Jurisdiction"] == CITY).sum())
    s_tdot = int((surface["Jurisdiction"] == TDOT_SR).sum())
    s_tot = len(surface)
    sf = surface[surface["InjuryClass"] == FATAL]
    sf_city = int((sf["Jurisdiction"] == CITY).sum())
    sf_tdot = int((sf["Jurisdiction"] == TDOT_SR).sum())
    sf_tot = len(sf)

    # corner crashes (script-15 editorial choice) — recomputed
    sr_base = set(sr["NAME"].dropna().astype(str).str.strip().str.upper()) - {""}
    moves = n[(n["Jurisdiction_prev"] == "TDOT") & (n["Jurisdiction"] == CITY)].copy()
    moves["sr_named"] = moves["Street_Name"].astype(str).str.upper().apply(
        lambda s: any(b in s for b in sr_base if len(b) > 3))
    cc = moves[~moves["sr_named"]]
    is_inter = cc["NonMotoristLocation"].astype(str).str.startswith("Intersection")
    corner = cc[is_inter & (cc["DistToStateRoute_m"] <= JUNCTION_M)]
    U, Uf = len(corner), int((corner["InjuryClass"] == FATAL).sum())

    T = len(on_under)               # threshold under-tag crashes (City -> TDOT, both bounds)
    log("\n## 4. Corrected surface City/TDOT split — final range\n")
    log(f"- Threshold under-tag fix (applies to BOTH bounds): move **{T}** City crashes "
        f"({Tf} fatal) to TDOT.")
    log(f"- Corner-credit (TDOT-favorable upper bound only): **{U}** corner crashes "
        f"({Uf} fatal).\n")

    def row(city, tdot, tot, label):
        return f"| {label} | {city} ({pct(city,tot)}%) | {tdot} ({pct(tdot,tot)}%) |"

    log("**ALL surface crashes (n=%d)**\n" % s_tot)
    log("| bound | City | TDOT |\n|---|---|---|")
    log(row(s_city - T, s_tdot + T, s_tot, "Lower (nearest-centerline + threshold fix)"))
    log(row(s_city - T - U, s_tdot + T + U, s_tot, "Upper (+ corner→state route)"))
    log("\n**FATAL surface crashes (n=%d)**\n" % sf_tot)
    log("| bound | City | TDOT |\n|---|---|---|")
    log(row(sf_city - Tf, sf_tdot + Tf, sf_tot, "Lower (nearest-centerline + threshold fix)"))
    log(row(sf_city - Tf - Uf, sf_tdot + Tf + Uf, sf_tot, "Upper (+ corner→state route)"))

    tdot_lo, tdot_hi = pct(s_tdot + T, s_tot), pct(s_tdot + T + U, s_tot)
    ftdot_lo, ftdot_hi = pct(sf_tdot + Tf, sf_tot), pct(sf_tdot + Tf + Uf, sf_tot)
    log(f"\n**Final corrected range:** surface TDOT **{tdot_lo}%–{tdot_hi}%** (all), "
        f"**{ftdot_lo}%–{ftdot_hi}%** (fatal); City **{pct(s_city-T-U,s_tot)}%–{pct(s_city-T,s_tot)}%** / "
        f"**{pct(sf_city-Tf-Uf,sf_tot)}%–{pct(sf_city-Tf,sf_tot)}%**. City keeps the majority under both "
        f"bounds. Interstate stays separate (23 / 10 fatal). Layer-level gaps "
        f"(Sam Cooper / Bill Morris, {len(band)} City crashes) are NOT in this range.")

    # terminal recap
    print("\n" + "=" * 64)
    print(f"threshold under-tag crashes: {T} ({Tf} fatal) | corner crashes: {U} ({Uf} fatal)")
    print(f"FINAL surface TDOT range: all {tdot_lo}%-{tdot_hi}% | fatal {ftdot_lo}%-{ftdot_hi}%")
    print(f"layer-level gap band (Sam Cooper/Bill Morris): {len(band)} City crashes (separate)")
    print("=" * 64)

    OUT_MD.parent.mkdir(exist_ok=True)
    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_MD}")
    print("Read-only: no classification/map/docx changes.")


if __name__ == "__main__":
    main()
