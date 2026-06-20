r"""
14_segment_jurisdiction.py
=========================

MAJOR METHODOLOGY CHANGE: classify crashes City vs TDOT by SEGMENT INHERITANCE
instead of crash-point distance to a state-route line.

Idea: tag every centerline segment with an OWNER (Phase 1), then let each crash
inherit the owner of the segment it sits on (Phase 2). This removes road-width
sensitivity (wide roads like Poplar), represents ownership block-by-block, and
folds in interstates (absent from the state-route layer).

All spatial work in EPSG:32136 (meters). Writes NEW files only; never overwrites
the existing classified / named / deadliest CSVs. Does NOT rebuild index.html or
novel_statistics.docx. Supersedes the interstate-only fix in script 12.

Phase 1 parameters (confirmed):
  - Interstate: MTFCC == "S1100" -> "Interstate (TDOT)"; S1630 -> "Interstate ramp".
  - State route: a centerline segment is "TDOT state route" if >=60% of its length
    lies within a 10 m buffer of a state-route line AND a same-named state route is
    nearby (name key = PREDIR+NAME), OR it is essentially collinear (>=85% of its
    length within an 8 m buffer of any state route) which overrides a name mismatch
    (catches SR-385/Nonconnah, US-64, etc.). Precedence: Interstate > ramp > state
    route > City.

Run it with:
    .\.venv\Scripts\python.exe scripts\14_segment_jurisdiction.py
"""

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW = PROJECT_ROOT / "data" / "raw"
PROCESSED = PROJECT_ROOT / "data" / "processed"
OUT_MAP = PROJECT_ROOT / "outputs" / "interactive_map"
AUDIT_MD = PROJECT_ROOT / "outputs" / "segment_method_audit.md"

STREETS = RAW / "memphis_streets.geojson"
STATE_ROUTES = RAW / "state_routes.geojson"
NAMED = PROCESSED / "shelby_crashes_named.csv"
CLASSIFIED = PROCESSED / "shelby_crashes_classified.csv"

OUT_CLASSIFIED = PROCESSED / "shelby_crashes_classified_seg.csv"
OUT_NAMED = PROCESSED / "shelby_crashes_named_seg.csv"
OUT_DEADLIEST = PROCESSED / "deadliest_streets_seg.csv"
OUT_OWNERSHIP = OUT_MAP / "ownership_segments.geojson"

CRS_M = "EPSG:32136"
CRS_GEO = "EPSG:4326"
BUF_WIDE = 10.0       # m, primary buffer
BUF_TIGHT = 8.0       # m, tight buffer for the name-override (near-total overlap)
OV_CUTOFF = 0.60      # >=60% within wide buffer + name => state route
OV_OVERRIDE = 0.85    # >=85% within tight buffer => state route even if name differs
OV_AMBIG_LO = 0.30
FATAL = "Fatal"

INT_TDOT = "Interstate (TDOT)"
INT_RAMP = "Interstate ramp"
TDOT_SR = "TDOT state route"
CITY = "City of Memphis"
SURFACE = [CITY, TDOT_SR]


def namekey(predir, name):
    p = "" if predir is None else str(predir).strip()
    n = "" if name is None else str(name).strip()
    if p.lower() == "nan":
        p = ""
    if n.lower() == "nan":
        n = ""
    return re.sub(r"\s+", " ", f"{p} {n}").strip().upper()


def std_street_name(predir, name, type_, sufdir, label):
    def c(v):
        if v is None:
            return ""
        t = str(v).strip()
        return "" if t.lower() == "nan" else t
    nm = c(name)
    if nm:
        return " ".join(" ".join(x for x in [c(predir), nm, c(type_), c(sufdir)] if x).split()).upper()
    return " ".join(c(label).split()).upper()


def modal_nonzero(s):
    v = pd.to_numeric(s, errors="coerce").dropna()
    v = v[v != 0]
    return (v.mode().iloc[0] if len(v.mode()) else pd.NA) if len(v) else pd.NA


# ===========================================================================
# PHASE 1 — tag every centerline segment with an Owner
# ===========================================================================
def phase1_tag_segments(log):
    st = gpd.read_file(STREETS).to_crs(CRS_M)
    sr = gpd.read_file(STATE_ROUTES).to_crs(CRS_M)
    st["seglen"] = st.geometry.length
    st["k"] = [namekey(p, n) for p, n in zip(st["PREDIR"], st["NAME"])]
    sr["k"] = [namekey(p, n) for p, n in zip(sr["PREDIR"], sr["NAME"])]

    # Buffers (union for fast overlap; per-segment buffer for the name join).
    buf10_union = sr.buffer(BUF_WIDE).union_all()
    buf8_union = sr.buffer(BUF_TIGHT).union_all()

    # Candidate centerline segments = those touching the wide state-route corridor.
    cand_mask = st.intersects(buf10_union)
    cand = st[cand_mask].copy()
    log(f"  candidate centerline segments near state routes: {len(cand)} of {len(st)}")
    cand["ov10"] = cand.geometry.intersection(buf10_union).length / cand["seglen"]
    cand["ov8"] = cand.geometry.intersection(buf8_union).length / cand["seglen"]

    # Name agreement: a SAME-named state route lies within the wide buffer.
    sr_buf = gpd.GeoDataFrame({"k_sr": sr["k"]}, geometry=sr.buffer(BUF_WIDE), crs=CRS_M)
    j = gpd.sjoin(cand[["k", "geometry"]].reset_index(), sr_buf, predicate="intersects", how="inner")
    j["match"] = j["k"] == j["k_sr"]
    name_present = j.groupby("index")["match"].any()
    cand["name_present"] = cand.index.map(name_present).fillna(False)

    cand["tdot_match"] = ((cand["ov10"] >= OV_CUTOFF) & cand["name_present"]) | (cand["ov8"] >= OV_OVERRIDE)
    cand["ambiguous"] = (
        ((cand["ov10"] >= OV_AMBIG_LO) & (cand["ov10"] < OV_CUTOFF)) |
        ((cand["ov10"] >= OV_CUTOFF) & (~cand["name_present"]) & (cand["ov8"] < OV_OVERRIDE))
    )

    # Assign Ownership with precedence: Interstate > ramp > state route > City.
    own = pd.Series(CITY, index=st.index)
    own.loc[cand.index[cand["tdot_match"]]] = TDOT_SR
    mtfcc = st["MTFCC"].astype(str)
    own.loc[mtfcc == "S1630"] = INT_RAMP
    own.loc[mtfcc == "S1100"] = INT_TDOT
    st["Ownership"] = own.values
    # carry overlap diagnostics back for reporting
    st["ov10"] = np.nan; st.loc[cand.index, "ov10"] = cand["ov10"].values
    st["name_present"] = False; st.loc[cand.index, "name_present"] = cand["name_present"].values
    st["ambiguous"] = False; st.loc[cand.index, "ambiguous"] = cand["ambiguous"].values

    # ---- validation report ----
    log("\n## Phase 1 — segment ownership tagging\n")
    miles = st.groupby("Ownership").apply(lambda g: g.geometry.length.sum() / 1609.344, include_groups=False)
    counts = st["Ownership"].value_counts()
    log("| Ownership | segments | miles |\n|---|---|---|")
    for o in [INT_TDOT, INT_RAMP, TDOT_SR, CITY]:
        log(f"| {o} | {int(counts.get(o,0))} | {miles.get(o,0):.1f} |")
    raw_mi = sr.geometry.length.sum() / 1609.344
    log(f"\n- Raw `state_routes.geojson` mileage: **{raw_mi:.1f} mi**; tagged "
        f"\"{TDOT_SR}\" centerline mileage: **{miles.get(TDOT_SR,0):.1f} mi** "
        f"(centerline can differ from the single state-route line where a divided "
        f"road has two carriageways or alignments differ).")

    # overlap distribution among candidates
    bins = [0, .1, .3, .6, .85, 1.01]
    hist = pd.cut(cand["ov10"], bins, right=False).value_counts().sort_index()
    log("\n- Overlap-fraction (ov10) distribution among candidates:")
    log("```")
    for iv, c in hist.items():
        log(f"  {iv}: {c}")
    log("```")

    # spot checks
    log("\n- Spot checks (Ownership mix by name key):")
    for nm in ["POPLAR", "LAMAR", "SUMMER", "UNION", "WINCHESTER", "GETWELL", "AIRWAYS"]:
        sub = st[st["k"].str.contains(rf"\b{nm}\b", na=False)]
        if len(sub):
            mix = sub["Ownership"].value_counts().to_dict()
            log(f"    {nm:11s}: {mix}")
    inter = st[st["NAME"].astype(str).str.upper().str.contains("INTERSTATE", na=False)]
    log(f"    INTERSTATE : {inter['Ownership'].value_counts().to_dict()}")

    # ambiguous segments to eyeball
    amb = st[st["ambiguous"]]
    log(f"\n- Ambiguous segments to review (30–60% overlap, or >=60% with name "
        f"mismatch & <85% tight overlap): **{len(amb)}**")
    show = amb.assign(name=[std_street_name(p, n, t, s, l) for p, n, t, s, l in
                            zip(amb.PREDIR, amb.NAME, amb.TYPE, amb.SUFDIR, amb.LABEL)])
    log("```")
    for _, r in show.sort_values("ov10", ascending=False).head(20).iterrows():
        log(f"  {r['name'][:26]:26s} ov10={r['ov10']:.2f} name_match={r['name_present']} MTFCC={r['MTFCC']}")
    log("```")

    return st


# ===========================================================================
# PHASE 2 — reclassify crashes by inherited segment ownership
# ===========================================================================
def phase2_reclassify(st, log):
    named = pd.read_csv(NAMED)
    pts = gpd.GeoDataFrame(
        named.copy(),
        geometry=gpd.points_from_xy(named["Longitude"], named["Latitude"]),
        crs=CRS_GEO,
    ).to_crs(CRS_M)

    seg = st[["OBJECTID", "Ownership", "geometry"]].rename(columns={"OBJECTID": "Seg_OBJECTID"})
    joined = gpd.sjoin_nearest(pts, seg, how="left", distance_col="DistToSeg_m")
    joined = joined[~joined.index.duplicated(keep="first")]

    named_seg = named.copy()
    named_seg["Jurisdiction_prev"] = named_seg["Jurisdiction"]
    named_seg["Seg_OBJECTID"] = joined["Seg_OBJECTID"].values
    named_seg["DistToSeg_m"] = joined["DistToSeg_m"].values
    named_seg["Jurisdiction"] = joined["Ownership"].values
    named_seg.to_csv(OUT_NAMED, index=False, encoding="utf-8")

    # propagate to the classified file (in-Memphis rows only; keep the rest)
    new_juris = dict(zip(named_seg["MstrRecNbrTxt"], named_seg["Jurisdiction"]))
    classified = pd.read_csv(CLASSIFIED)
    classified_seg = classified.copy()
    classified_seg["Jurisdiction_prev"] = classified_seg["Jurisdiction"]
    classified_seg["Jurisdiction"] = [
        new_juris.get(mid, j) for mid, j in zip(classified_seg["MstrRecNbrTxt"], classified_seg["Jurisdiction"])
    ]
    classified_seg.to_csv(OUT_CLASSIFIED, index=False, encoding="utf-8")

    # regenerate deadliest ranking from the new labels
    m = named_seg.copy()
    m["_fatal"] = (m["InjuryClass"] == FATAL).astype(int)
    m["_serious"] = (m["InjuryClass"] == "Suspected Serious Injury").astype(int)

    def summarize(g):
        total = len(g)
        jc = g["Jurisdiction"].value_counts()
        dom = jc.idxmax()
        return pd.Series({
            "Total_Crashes": total,
            "Fatal_Crashes": int(g["_fatal"].sum()),
            "Serious_Injuries": int(g["_serious"].sum()),
            "Dominant_Jurisdiction": dom,
            "Mixed_Jurisdiction": bool(jc.max() / total < 0.90),
            "SPDLIMIT": modal_nonzero(g["Street_SPDLIMIT"]),
            "LANES": modal_nonzero(g["Street_LANES"]),
        })

    ranking = (m.groupby("Street_Name", sort=False).apply(summarize, include_groups=False)
               .reset_index().sort_values(["Total_Crashes", "Fatal_Crashes"], ascending=False))
    ranking.to_csv(OUT_DEADLIEST, index=False, encoding="utf-8")
    log(f"\nWrote {OUT_NAMED.name}, {OUT_CLASSIFIED.name}, {OUT_DEADLIEST.name} "
        f"({len(ranking)} streets).")
    return named_seg


# ===========================================================================
# PHASE 3 — old vs new comparison
# ===========================================================================
def phase3_compare(named_seg, st, log):
    n = named_seg
    total = len(n)
    fatal = n[n["InjuryClass"] == FATAL]

    def count2(df, col, city_lbl, tdot_lbl):
        return int((df[col] == city_lbl).sum()), int((df[col] == tdot_lbl).sum())

    def pct(p, w):
        return round(100.0 * p / w, 1) if w else 0.0

    # OLD distance-method split (labels are "City of Memphis" / "TDOT")
    o_city, o_tdot = count2(n, "Jurisdiction_prev", CITY, "TDOT")
    of_city, of_tdot = count2(fatal, "Jurisdiction_prev", CITY, "TDOT")

    # NEW segment split, option (b): surface only + separate interstate
    surface = n[n["Jurisdiction"].isin(SURFACE)]
    inter = n[n["Jurisdiction"] == INT_TDOT]
    ramp = n[n["Jurisdiction"] == INT_RAMP]
    s_total = len(surface)
    s_city, s_tdot = count2(surface, "Jurisdiction", CITY, TDOT_SR)
    sf = surface[surface["InjuryClass"] == FATAL]
    sf_city, sf_tdot = count2(sf, "Jurisdiction", CITY, TDOT_SR)

    log("\n## Phase 3 — old (distance) vs new (segment) split\n")
    log("**ALL crashes**\n")
    log("| method | City | TDOT | Interstate | Interstate ramp |\n|---|---|---|---|---|")
    log(f"| OLD distance (n={total}) | {o_city} ({pct(o_city,total)}%) | {o_tdot} ({pct(o_tdot,total)}%) | (in City) | (in City) |")
    log(f"| NEW segment, surface (n={s_total}) | {s_city} ({pct(s_city,s_total)}%) | {s_tdot} ({pct(s_tdot,s_total)}%) | {len(inter)} sep. | {len(ramp)} sep. |")
    log("\n**FATAL crashes**\n")
    log("| method | City | TDOT | Interstate | Interstate ramp |\n|---|---|---|---|---|")
    log(f"| OLD distance (n={len(fatal)}) | {of_city} ({pct(of_city,len(fatal))}%) | {of_tdot} ({pct(of_tdot,len(fatal))}%) | (in City) | (in City) |")
    log(f"| NEW segment, surface (n={len(sf)}) | {sf_city} ({pct(sf_city,len(sf))}%) | {sf_tdot} ({pct(sf_tdot,len(sf))}%) | "
        f"{int((inter['InjuryClass']==FATAL).sum())} sep. | {int((ramp['InjuryClass']==FATAL).sum())} sep. |")

    # who changed label
    chg = n[n["Jurisdiction"] != n["Jurisdiction_prev"]]
    log(f"\n**Crashes that changed label: {len(chg)} of {total}** (reconciles: "
        f"sum still {total}; fatal {len(fatal)}).")
    log("\n```")
    ct = chg.groupby(["Jurisdiction_prev", "Jurisdiction"]).size().sort_values(ascending=False)
    for (a, b), c in ct.items():
        log(f"  {a:18s} -> {b:18s} : {c}")
    log("```")

    # per-street old vs new for wide arterials
    log("\n**Wide-arterial old-vs-new** (crash counts by jurisdiction):\n")
    log("| street | OLD City/TDOT | NEW City/TDOT/Int/Ramp |\n|---|---|---|")
    for nm in ["POPLAR", "LAMAR", "SUMMER", "UNION", "JACKSON", "PARK", "GETWELL", "WINCHESTER", "AIRWAYS"]:
        sub = n[n["Street_Name"].astype(str).str.contains(rf"\b{nm}\b", na=False)]
        if not len(sub):
            continue
        oc, ot = count2(sub, "Jurisdiction_prev", CITY, "TDOT")
        nc = int((sub["Jurisdiction"] == CITY).sum()); nt = int((sub["Jurisdiction"] == TDOT_SR).sum())
        ni = int((sub["Jurisdiction"] == INT_TDOT).sum()); nr = int((sub["Jurisdiction"] == INT_RAMP).sum())
        log(f"| {nm} | {oc}/{ot} | {nc}/{nt}/{ni}/{nr} |")

    # JOIN-QUALITY WATCHLIST: TDOT->City crashes whose matched centerline segment
    # actually overlaps a state route (>=30%) but was NOT tagged state route -- the
    # genuine under-tagging suspects (divided carriageway alignment or name-key gap).
    segattr = st[["OBJECTID", "ov10", "Ownership"]].rename(
        columns={"OBJECTID": "Seg_OBJECTID", "Ownership": "Seg_Own"})
    merged = n.merge(segattr, on="Seg_OBJECTID", how="left")
    watch = merged[(merged["Jurisdiction_prev"] == "TDOT") & (merged["Jurisdiction"] == CITY) &
                   (merged["ov10"].fillna(0) >= 0.30)]
    log(f"\n**Join-quality watchlist** — {len(watch)} of the {int(((n.Jurisdiction_prev=='TDOT')&(n.Jurisdiction==CITY)).sum())} "
        f"TDOT→City crashes sit on a segment that overlaps a state route ≥30% yet was "
        f"tagged City (possible under-tagged carriageway / name gap — eyeball these; the "
        f"rest are genuine city cross-streets near intersections):")
    log("```")
    for _, r in watch.sort_values("ov10", ascending=False).iterrows():
        log(f"  {r['MstrRecNbrTxt']} {str(r['Street_Name'])[:20]:20s} ov10={r['ov10']:.2f} "
            f"oldDistToSR={r['DistToStateRoute_m']:.1f}m  ({r['Latitude']:.5f},{r['Longitude']:.5f})")
    log("```")

    # reframe check
    log(f"\n**Reframe check:** new surface split City {pct(s_city,s_total)}% vs "
        f"TDOT {pct(s_tdot,s_total)}% — City {'still owns the majority' if s_city>s_tdot else 'NO LONGER owns the majority'} "
        f"of surface crashes; fatal surface City {pct(sf_city,len(sf))}% vs TDOT {pct(sf_tdot,len(sf))}%.")

    # terminal summary
    print("\n" + "=" * 64)
    print("OLD vs NEW (segment method), option (b)")
    print("=" * 64)
    print(f"ALL  : OLD City {pct(o_city,total)}% / TDOT {pct(o_tdot,total)}%   ->   "
          f"NEW surface City {pct(s_city,s_total)}% / TDOT {pct(s_tdot,s_total)}%  + Interstate {len(inter)} (ramp {len(ramp)})")
    print(f"FATAL: OLD City {pct(of_city,len(fatal))}% / TDOT {pct(of_tdot,len(fatal))}%   ->   "
          f"NEW surface City {pct(sf_city,len(sf))}% / TDOT {pct(sf_tdot,len(sf))}%  + Interstate "
          f"{int((inter['InjuryClass']==FATAL).sum())} (ramp {int((ramp['InjuryClass']==FATAL).sum())})")
    print(f"Crashes relabeled: {len(chg)} of {total}")


# ===========================================================================
# PHASE 4 — export the display layer (Memphis-only state route + interstate)
# ===========================================================================
def phase4_export(st, log):
    keep = st[st["Ownership"].isin([INT_TDOT, INT_RAMP, TDOT_SR]) &
              (st["CITY_L"].astype(str).str.upper() == "MEMPHIS")].copy()
    keep["Street_Name"] = [std_street_name(p, n, t, s, l) for p, n, t, s, l in
                           zip(keep.PREDIR, keep.NAME, keep.TYPE, keep.SUFDIR, keep.LABEL)]
    out = keep[["Ownership", "Street_Name", "MTFCC", "geometry"]].copy()
    out["geometry"] = out.geometry.simplify(5, preserve_topology=True)
    out = out.to_crs(CRS_GEO)
    OUT_MAP.mkdir(parents=True, exist_ok=True)
    out.to_file(OUT_OWNERSHIP, driver="GeoJSON")
    size_mb = OUT_OWNERSHIP.stat().st_size / 1e6
    log(f"\n## Phase 4 — display layer\n\nWrote `{OUT_OWNERSHIP.name}`: {len(out)} Memphis "
        f"state-route/interstate segments ({size_mb:.2f} MB, simplified, EPSG:4326).")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    lines = ["# Segment-inheritance jurisdiction method — audit",
             "\n*Read/compute only · all spatial math in EPSG:32136 · new files; originals untouched.*"]
    def log(s=""):
        print(s); lines.append(s)

    print("PHASE 1: tagging centerline segments...")
    st = phase1_tag_segments(log)
    print("\nPHASE 2: reclassifying crashes by inherited ownership...")
    named_seg = phase2_reclassify(st, log)
    print("\nPHASE 3: comparing old vs new...")
    phase3_compare(named_seg, st, log)
    print("\nPHASE 4: exporting display layer...")
    phase4_export(st, log)

    AUDIT_MD.parent.mkdir(exist_ok=True)
    AUDIT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote {AUDIT_MD}")
    print("STOP: index.html and novel_statistics.docx were NOT changed.")


if __name__ == "__main__":
    main()
