r"""
17_classifier.py
================

CANONICAL, REUSABLE jurisdiction classifier. Consolidates the settled methodology
(scripts 14 = segment ownership, 15 = corner cases, 16 = completeness) into one
rulebook-driven module that:
  A. tags every centerline segment with an Ownership by a documented, ordered
     rulebook (recording which rule fired) -> a stable artifact;
  B. classifies any crash set by inheriting the nearest rulebook segment's
     Ownership, with per-incident provenance + flags;
  C. recomputes and prints the FINAL locked numbers.

Spatial work in EPSG:32136. Writes NEW files only; never overwrites prior outputs.
Does NOT rebuild index.html or any docx (that is Pass 2).

------------------------------------------------------------------------------
THE RULEBOOK (applied in order; first match wins; the rule is recorded):
  1. MTFCC == S1100                         -> "Interstate (TDOT)"
  2. MTFCC == S1630 (ramps)                 -> "Interstate ramp (TDOT)"
  3. LIMITED-ACCESS OVERRIDE (name list)    -> "Limited-access (TDOT)"
        TDOT limited-access roads ABSENT from the state-route layer. Config:
        LIMITED_ACCESS_NAMES below. Seeded with Sam Cooper Blvd.
        CAVEAT: Sam Cooper's low-speed western boulevard end is technically a
        surface street, so the map tint slightly over-extends there (refine in
        Pass 2). Crash numbers are unaffected (all Sam Cooper crashes are on the
        expressway part).
  4. STATE-ROUTE OVERLAP (script-14 geometric rule)   -> "TDOT state route"
        >=60% of the segment within a 10 m buffer of a same-named state route,
        OR >=85% within an 8 m buffer (collinear override for differently-named
        routes like SR-385/Nonconnah).
  5. FORCE-STATE-ROUTE OVERRIDE (completeness fix)     -> "TDOT state route"
        (a) documented rule: a City segment whose length is >=20% collinear with
            a SAME-NAMED state route (ov_same_name >= FORCE_OV). Name-guarded, so
            it re-derives on a data refresh and never tags a cross/parallel street.
            Catches the genuine threshold slivers the completeness audit found
            (Jackson Ave + 10 others).
        (b) explicit FORCE_STATE_ROUTE list (OBJECTIDs/names), seeded empty, for
            future manual additions.
  6. else                                   -> "City of Memphis"

Run it with:
    .\.venv\Scripts\python.exe scripts\17_classifier.py
"""

import re
import sys
import json
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd

# ===========================================================================
# CONFIG — the two override lists + thresholds (visible & maintainable)
# ===========================================================================
LIMITED_ACCESS_NAMES = [
    # TDOT limited-access roads absent from state_routes.geojson. Tagged by name.
    "SAM COOPER",   # Sam Cooper Blvd — expressway; western ~25 mph end is technically surface (map caveat)
]
FORCE_STATE_ROUTE = {
    # Explicit manual force-state-route additions (OBJECTIDs or upper NAME tokens).
    # Seeded EMPTY: the FORCE_OV completeness rule already catches the audit's slivers.
    "objectids": [],
    "names": [],
}
FORCE_OV = 0.20        # City segment >= this fraction collinear w/ a same-named SR -> force TDOT
BUF_WIDE, BUF_TIGHT = 10.0, 8.0
OV_CUTOFF, OV_OVERRIDE = 0.60, 0.85
CORNER_M = 10.0        # City crash within this of a route, at an intersection = corner case

INT_TDOT = "Interstate (TDOT)"
INT_RAMP = "Interstate ramp (TDOT)"
LIM_ACC = "Limited-access (TDOT)"
TDOT_SR = "TDOT state route"
CITY = "City of Memphis"
LIMITED_SET = {INT_TDOT, INT_RAMP, LIM_ACC}
SURFACE_SET = {CITY, TDOT_SR}
FATAL = "Fatal"

CRS_M, CRS_GEO = "EPSG:32136", "EPSG:4326"
ROOT = Path(__file__).resolve().parent.parent
RAW, PROCESSED = ROOT / "data" / "raw", ROOT / "data" / "processed"
OUT_MAP = ROOT / "outputs" / "interactive_map"
STREETS, STATE_ROUTES = RAW / "memphis_streets.geojson", RAW / "state_routes.geojson"
NAMED_SEG = PROCESSED / "shelby_crashes_named_seg.csv"
RULEBOOK = PROCESSED / "road_ownership_rulebook.geojson"
FINAL_CSV = PROCESSED / "shelby_crashes_final.csv"
DISPLAY_GEOJSON = OUT_MAP / "ownership_segments_final.geojson"
FINAL_MD = ROOT / "outputs" / "final_numbers.md"


def namekey(predir, name):
    p = "" if predir is None else str(predir).strip()
    n = "" if name is None else str(name).strip()
    p = "" if p.lower() == "nan" else p
    n = "" if n.lower() == "nan" else n
    return re.sub(r"\s+", " ", f"{p} {n}").strip().upper()


def std_name(predir, name, type_, sufdir, label):
    def c(v):
        t = "" if v is None else str(v).strip()
        return "" if t.lower() == "nan" else t
    nm = c(name)
    if nm:
        return " ".join(" ".join(x for x in [c(predir), nm, c(type_), c(sufdir)] if x).split()).upper()
    return " ".join(c(label).split()).upper()


def pct(p, w):
    return round(100.0 * p / w, 1) if w else 0.0


# ===========================================================================
# PART A — build the rulebook
# ===========================================================================
def build_rulebook(sr):
    st = gpd.read_file(STREETS).to_crs(CRS_M)
    st["key"] = [namekey(p, n) for p, n in zip(st["PREDIR"], st["NAME"])]
    st["seglen"] = st.geometry.length
    nm_up = st["NAME"].astype(str).str.upper()
    mt = st["MTFCC"].astype(str)

    # --- geometric overlap with state routes (script-14 rule) ---
    buf10 = sr.buffer(BUF_WIDE).union_all()
    buf8 = sr.buffer(BUF_TIGHT).union_all()
    cand = st[st.intersects(buf10)].copy()
    cand["ov10"] = cand.geometry.intersection(buf10).length / cand["seglen"]
    cand["ov8"] = cand.geometry.intersection(buf8).length / cand["seglen"]
    sr_buf = gpd.GeoDataFrame({"k_sr": sr["key"]}, geometry=sr.buffer(BUF_WIDE), crs=CRS_M)
    j = gpd.sjoin(cand[["key", "geometry"]].reset_index(), sr_buf, predicate="intersects", how="inner")
    name_present = (j["key"] == j["k_sr"]).groupby(j["index"]).any()
    cand["name_present"] = cand.index.map(name_present).fillna(False)
    cand["tdot_match"] = ((cand["ov10"] >= OV_CUTOFF) & cand["name_present"]) | (cand["ov8"] >= OV_OVERRIDE)
    st["ov10"] = 0.0; st.loc[cand.index, "ov10"] = cand["ov10"].values
    st["tdot_match"] = False; st.loc[cand.index, "tdot_match"] = cand["tdot_match"].values

    # --- ov_same_name (overlap with a SAME-NAMED state route) for the force rule ---
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
    st["ov_same"] = 0.0; st.loc[cl.index, "ov_same"] = cl["ov_same"].values

    # --- ordered rules (first match wins) ---
    lim_name = nm_up.apply(lambda s: any(t in s for t in LIMITED_ACCESS_NAMES))
    force_manual = (st["OBJECTID"].isin(FORCE_STATE_ROUTE["objectids"]) |
                    st["key"].isin([k.upper() for k in FORCE_STATE_ROUTE["names"]]))
    force_complete = st["ov_same"] >= FORCE_OV
    conds = [mt == "S1100", mt == "S1630", lim_name, st["tdot_match"], force_manual, force_complete]
    owns = [INT_TDOT, INT_RAMP, LIM_ACC, TDOT_SR, TDOT_SR, TDOT_SR]
    rules = ["interstate_mainline", "interstate_ramp", "limited_access_override",
             "state_route_overlap", "force_state_route_manual", "force_state_route_completeness"]
    st["Ownership"] = np.select(conds, owns, default=CITY)
    st["Rule_Fired"] = np.select(conds, rules, default="city_residual")

    # --- human-readable basis per segment (crashes inherit this) ---
    st["Street_Name"] = [std_name(p, n, t, s, l) for p, n, t, s, l in
                         zip(st.PREDIR, st.NAME, st.TYPE, st.SUFDIR, st.LABEL)]
    def basis(r):
        rf = r["Rule_Fired"]
        if rf == "interstate_mainline":   return "interstate: MTFCC S1100"
        if rf == "interstate_ramp":       return "interstate ramp: MTFCC S1630"
        if rf == "limited_access_override": return f"limited-access override: {r['Street_Name'].title()}"
        if rf == "state_route_overlap":   return f"state route: {r['ov10']:.0%} overlap, name={r['key']}"
        if rf == "force_state_route_manual": return "force-state-route: manual override"
        if rf == "force_state_route_completeness": return f"force-state-route: {r['ov_same']:.0%} collinear w/ same-named SR ({r['key']})"
        return "city: no state-route overlap"
    st["Basis"] = st.apply(basis, axis=1)

    keep = ["OBJECTID", "NAME", "Street_Name", "MTFCC", "CITY_L", "ov10", "ov_same",
            "Ownership", "Rule_Fired", "Basis", "geometry"]
    return st[keep]


# ===========================================================================
# PART B — the reusable classifier
# ===========================================================================
def classify(crashes, rulebook, state_routes):
    """Classify a crash DataFrame (needs Latitude/Longitude) against the rulebook.
    `state_routes` is the state-route LAYER, used only for the corner-case distance
    (one representative line per road, matching the script-15 corner basis)."""
    # drop any pre-existing columns that would collide with what we produce
    produced = ["Seg_OBJECTID", "DistToSeg_m", "Ownership", "Rule_Fired", "Classification_Basis",
                "is_limited_access", "is_corner_case", "is_override", "index_right", "_d_route"]
    crashes = crashes.drop(columns=[c for c in produced if c in crashes.columns])
    pts = gpd.GeoDataFrame(
        crashes.copy(),
        geometry=gpd.points_from_xy(crashes["Longitude"], crashes["Latitude"]),
        crs=CRS_GEO).to_crs(CRS_M)

    seg = rulebook[["OBJECTID", "Ownership", "Rule_Fired", "Basis", "Street_Name", "geometry"]].rename(
        columns={"OBJECTID": "Seg_OBJECTID", "Street_Name": "Matched_Street"})
    nearest = gpd.sjoin_nearest(pts, seg, how="left", distance_col="DistToSeg_m")
    nearest = nearest[~nearest.index.duplicated(keep="first")]

    out = crashes.copy()
    out["Seg_OBJECTID"] = nearest["Seg_OBJECTID"].values
    out["DistToSeg_m"] = nearest["DistToSeg_m"].values
    out["Ownership"] = nearest["Ownership"].values
    out["Rule_Fired"] = nearest["Rule_Fired"].values
    out["Classification_Basis"] = nearest["Basis"].values
    out["Matched_Street"] = nearest["Matched_Street"].values

    # distance to the state-route LAYER (one line per road), for the corner-case flag
    routes = state_routes[["geometry"]]
    near_rt = gpd.sjoin_nearest(pts, routes, how="left", distance_col="_d_route")
    near_rt = near_rt[~near_rt.index.duplicated(keep="first")]
    d_route = near_rt["_d_route"].values

    loc = out["NonMotoristLocation"].astype(str).str.startswith("Intersection").values
    # corner case = city crash on a NON-state-route-named street, at an intersection,
    # within CORNER_M of a state route (matches the script-15 corner basis: genuine
    # city cross-streets at state-route corners, not city portions of named arterials)
    sr_tokens = {t for t in state_routes["NAME"].dropna().astype(str).str.strip().str.upper()
                 if len(t) > 3}
    matched_up = out["Matched_Street"].astype(str).str.upper()
    is_sr_named = matched_up.apply(lambda s: any(t in s for t in sr_tokens)).values
    out["is_limited_access"] = out["Ownership"].isin(LIMITED_SET).values
    out["is_override"] = out["Rule_Fired"].isin(
        {"limited_access_override", "force_state_route_manual", "force_state_route_completeness"}).values
    out["is_corner_case"] = ((out["Ownership"].values == CITY) & loc & (d_route <= CORNER_M)
                             & ~is_sr_named)
    return out


# ===========================================================================
# PART C — final numbers
# ===========================================================================
def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    print("PART A: building the rulebook...")
    OUT_MAP.mkdir(parents=True, exist_ok=True)
    sr = gpd.read_file(STATE_ROUTES).to_crs(CRS_M)
    sr["key"] = [namekey(p, n) for p, n in zip(sr["PREDIR"], sr["NAME"])]
    if RULEBOOK.exists():
        print("  loading cached rulebook (delete the file to force a rebuild)...")
        rb = gpd.read_file(RULEBOOK).to_crs(CRS_M)
    else:
        rb = build_rulebook(sr)
        rb.to_crs(CRS_GEO).to_file(RULEBOOK, driver="GeoJSON")
    rule_counts = rb["Rule_Fired"].value_counts()
    print(f"  rulebook: {len(rb)} segments -> {RULEBOOK.name}")

    # slim Memphis display layer (non-city only, simplified)
    disp = rb[(rb["Ownership"] != CITY) & (rb["CITY_L"].astype(str).str.upper() == "MEMPHIS")].copy()
    disp["geometry"] = disp.geometry.simplify(5, preserve_topology=True)
    disp[["Ownership", "Street_Name", "MTFCC", "Rule_Fired", "geometry"]].to_crs(CRS_GEO).to_file(
        DISPLAY_GEOJSON, driver="GeoJSON")

    print("PART B: classifying the 1,294 in-Memphis crashes...")
    crashes = pd.read_csv(NAMED_SEG)
    prev_seg = crashes["Jurisdiction"].copy()      # seg-method label (script 14) = audit trail
    crashes = crashes.drop(columns=[c for c in ["Jurisdiction", "Jurisdiction_prev",
                                                "Seg_OBJECTID", "DistToSeg_m"] if c in crashes.columns])
    fin = classify(crashes, rb, sr)
    fin["Jurisdiction_prev"] = prev_seg.values
    fin.to_csv(FINAL_CSV, index=False, encoding="utf-8")

    # --- reporting ---
    total, fatal = len(fin), int((fin["InjuryClass"] == FATAL).sum())
    surface = fin[fin["Ownership"].isin(SURFACE_SET)]
    limited = fin[fin["Ownership"].isin(LIMITED_SET)]
    s_tot = len(surface)
    s_city = int((surface["Ownership"] == CITY).sum())
    s_tdot = int((surface["Ownership"] == TDOT_SR).sum())
    sf = surface[surface["InjuryClass"] == FATAL]
    sf_tot = len(sf)
    sf_city = int((sf["Ownership"] == CITY).sum())
    sf_tdot = int((sf["Ownership"] == TDOT_SR).sum())
    lim_n = len(limited); lim_f = int((limited["InjuryClass"] == FATAL).sum())

    # corner cases (upper-bound move)
    U = int(fin["is_corner_case"].sum())
    Uf = int((fin["is_corner_case"] & (fin["InjuryClass"] == FATAL)).sum())

    L = ["# Final locked numbers — canonical classifier (script 17)\n",
         "*Surface = City vs TDOT state route only. Limited-access (Interstate + Interstate "
         "ramp + Sam Cooper) is a separate line. Range upper bound credits corner crashes "
         "(City at a state-route junction) to the state route. Read-only; no page/docx rebuild.*\n"]
    def log(s=""):
        print(s); L.append(s)

    log("## Rulebook — segments per rule\n")
    log("| rule | segments |\n|---|---|")
    for r in ["interstate_mainline", "interstate_ramp", "limited_access_override",
              "state_route_overlap", "force_state_route_completeness", "force_state_route_manual",
              "city_residual"]:
        log(f"| {r} | {int(rule_counts.get(r,0))} |")
    forced = rb[rb["Rule_Fired"].str.startswith("force_state_route")]
    forced_names = sorted(forced["Street_Name"].astype(str).unique())[:12]
    log(f"\n*Force-state-route fired on {len(forced)} segments "
        f"({', '.join(forced_names)}{'…' if len(forced)>12 else ''}). "
        f"Threshold FORCE_OV={FORCE_OV}, name-guarded.*")

    log("\n## Final crash split\n")
    log(f"In-Memphis crashes: **{total}** ({fatal} fatal) = surface **{s_tot}** + "
        f"limited-access **{lim_n}**.\n")
    log("**Surface City vs TDOT — point estimate (corner crashes as city) + range upper bound:**\n")
    log("| | City | TDOT |\n|---|---|---|")
    log(f"| ALL — point ({s_tot}) | {s_city} ({pct(s_city,s_tot)}%) | {s_tdot} ({pct(s_tdot,s_tot)}%) |")
    log(f"| ALL — upper (+{U} corner) | {s_city-U} ({pct(s_city-U,s_tot)}%) | {s_tdot+U} ({pct(s_tdot+U,s_tot)}%) |")
    log(f"| FATAL — point ({sf_tot}) | {sf_city} ({pct(sf_city,sf_tot)}%) | {sf_tdot} ({pct(sf_tdot,sf_tot)}%) |")
    log(f"| FATAL — upper (+{Uf} corner) | {sf_city-Uf} ({pct(sf_city-Uf,sf_tot)}%) | {sf_tdot+Uf} ({pct(sf_tdot+Uf,sf_tot)}%) |")

    log(f"\n**Limited-access (TDOT)** — separate line: **{lim_n} crashes ({lim_f} fatal)** "
        f"= Interstate {int((fin.Ownership==INT_TDOT).sum())} / ramp {int((fin.Ownership==INT_RAMP).sum())} / "
        f"Sam Cooper {int((fin.Ownership==LIM_ACC).sum())}.")

    log(f"\n**FINAL RANGE (lead with this):** surface **City {pct(s_city-U,s_tot)}%–{pct(s_city,s_tot)}% / "
        f"TDOT {pct(s_tdot,s_tot)}%–{pct(s_tdot+U,s_tot)}%** (all crashes); "
        f"**City {pct(sf_city-Uf,sf_tot)}%–{pct(sf_city,sf_tot)}% / TDOT {pct(sf_tdot,sf_tot)}%–{pct(sf_tdot+Uf,sf_tot)}%** "
        f"(fatal). Plus limited-access {lim_n} crashes ({lim_f} fatal), separate.")

    # reconciliation
    recon_all = s_tot + lim_n
    recon_fatal = sf_tot + lim_f
    log(f"\n## Reconciliation\n")
    log(f"- surface {s_tot} + limited-access {lim_n} = **{recon_all}** (expected {total}) "
        f"{'✓' if recon_all==total else '✗'}")
    log(f"- surface fatal {sf_tot} + limited-access fatal {lim_f} = **{recon_fatal}** "
        f"(expected {fatal}) {'✓' if recon_fatal==fatal else '✗'}")
    c2t = int(((fin["Jurisdiction_prev"] == CITY) & (fin["Ownership"] == TDOT_SR)).sum())
    c2l = int(((fin["Jurisdiction_prev"] == CITY) & (fin["Ownership"].isin(LIMITED_SET))).sum())
    log(f"- category changes vs seg-method (script 14): **{c2t}** City→TDOT (completeness force-rule), "
        f"**{c2l}** City→limited-access (Sam Cooper). (Interstate-ramp crashes were only relabeled "
        f"'Interstate ramp (TDOT)' — same category, not a move.)")

    FINAL_MD.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"\nWrote {RULEBOOK.name}, {FINAL_CSV.name}, {DISPLAY_GEOJSON.name}, {FINAL_MD.name}")
    print("STOP: no index.html / docx rebuild (Pass 2).")


if __name__ == "__main__":
    main()
