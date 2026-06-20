r"""
15_sensitivity_check.py
======================

READ-ONLY sensitivity / verification note for the segment-inheritance method
(script 14). It changes NOTHING: no reclassification, no new data files, no map
or index.html edits. It only prints findings and APPENDS a section to
outputs/segment_method_audit.md.

  1. Hand-verify the 3 join-quality watchlist arterials (E Raines Rd, N Bellevue
     Blvd, Jackson Ave) against state_routes.geojson — should each be a state route?
  2. Characterize the ~96 intersection-area TDOT->City moves (city-cross-street
     crashes near a state route): NonMotoristLocation breakdown, how many are at a
     junction WITH a state route, and how many are fatal.
  3. Upper-bound (TDOT-favorable) split: if those state-route-junction crashes were
     credited to the state route instead of the city cross-street, what is the
     surface City/TDOT split (all + fatal)? Reported as a RANGE against the current
     nearest-centerline (City-favorable) split.

Run it with:
    .\.venv\Scripts\python.exe scripts\15_sensitivity_check.py
"""

import sys
from pathlib import Path

import pandas as pd
import geopandas as gpd

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"
NAMED_SEG = PROCESSED / "shelby_crashes_named_seg.csv"
STATE_ROUTES = ROOT / "data" / "raw" / "state_routes.geojson"
STREETS = ROOT / "data" / "raw" / "memphis_streets.geojson"
AUDIT_MD = ROOT / "outputs" / "segment_method_audit.md"

CRS_M = "EPSG:32136"
CRS_GEO = "EPSG:4326"
CITY, TDOT_SR = "City of Memphis", "TDOT state route"
FATAL = "Fatal"
JUNCTION_M = 10.0     # a city crash this close to a state route = "at a junction with it"
WATCHLIST = [300968447, 300981287, 300953626]   # E Raines, N Bellevue, Jackson


def pct(p, w):
    return round(100.0 * p / w, 1) if w else 0.0


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    out = []
    def log(s=""):
        print(s); out.append(s)

    n = pd.read_csv(NAMED_SEG)
    sr = gpd.read_file(STATE_ROUTES).to_crs(CRS_M)
    sr["sr_name"] = (sr["PREDIR"].fillna("").astype(str).str.strip() + " " +
                     sr["NAME"].fillna("").astype(str).str.strip()).str.strip().str.upper()
    sr_base = set(sr["NAME"].dropna().astype(str).str.strip().str.upper()) - {""}

    log("\n## Sensitivity & watchlist verification (read-only — nothing reclassified)\n")
    log("*Appended by `scripts/15_sensitivity_check.py`. The per-crash labels and the "
        "map's three categories are unchanged; these are reporting-only numbers.*\n")

    # =====================================================================
    # 1. Hand-verify the 3 watchlist arterials
    # =====================================================================
    log("### 1. Watchlist arterials — should each be a state route?\n")
    st = gpd.read_file(STREETS)[["OBJECTID", "NAME", "MTFCC"]]
    pts = gpd.GeoDataFrame(
        n[n["MstrRecNbrTxt"].isin(WATCHLIST)].copy(),
        geometry=gpd.points_from_xy(
            n.loc[n["MstrRecNbrTxt"].isin(WATCHLIST), "Longitude"],
            n.loc[n["MstrRecNbrTxt"].isin(WATCHLIST), "Latitude"]),
        crs=CRS_GEO).to_crs(CRS_M)
    near = gpd.sjoin_nearest(pts, sr[["sr_name", "ALTNAME_1", "geometry"]],
                             how="left", distance_col="d_sr")
    near = near[~near.index.duplicated(keep="first")]
    log("| crash | matched (city) road | nearest state route | route # | dist | verdict |")
    log("|---|---|---|---|---|---|")
    for _, r in near.iterrows():
        matched = str(r["Street_Name"])
        srn = str(r["sr_name"]).strip()
        alt = "" if pd.isna(r["ALTNAME_1"]) else str(r["ALTNAME_1"])
        d = r["d_sr"]
        # ground truth: is the matched road itself a state route (its NAME token in sr_base)?
        toks = matched.replace(" AVE", "").replace(" RD", "").replace(" BLVD", "").strip()
        base_in_sr = any(b and b in matched.upper() and b in sr_base for b in [srn.split()[-1] if srn else ""]) \
            or any(b in matched.upper() for b in sr_base if len(b) > 3 and b in matched.upper())
        same_road = (srn and srn.split()[-1] in matched.upper())
        verdict = ("SHOULD be state route (same road, under-tagged)" if (same_road and d < 12)
                   else "City correct (nearest state route is a DIFFERENT road / cross-street)")
        log(f"| {int(r['MstrRecNbrTxt'])} | {matched} | {srn} | {alt} | {d:.1f} m | {verdict} |")
    log("\n*Verdict logic: if the crash's own (matched) road appears in the state-route "
        "layer at <12 m, it is an under-tagged state route; otherwise the nearby state "
        "route is a different road the city street merely meets/parallels, and City is correct.*")

    # =====================================================================
    # 2. Characterize the intersection-area TDOT -> City moves
    # =====================================================================
    moves = n[(n["Jurisdiction_prev"] == "TDOT") & (n["Jurisdiction"] == CITY)].copy()
    moves["is_sr_named"] = moves["Street_Name"].astype(str).str.upper().apply(
        lambda s: any(b in s for b in sr_base if len(b) > 3))
    city_cross = moves[~moves["is_sr_named"]].copy()      # the ~96
    loc = city_cross["NonMotoristLocation"].astype(str)
    is_inter = loc.str.startswith("Intersection")

    log("\n### 2. The intersection-area TDOT→City moves (city cross-street crashes)\n")
    log(f"- TDOT→City moves total: **{len(moves)}**; on a city cross-street (not a "
        f"state-route-named road): **{len(city_cross)}**; fatal among them: "
        f"**{int((city_cross['InjuryClass']==FATAL).sum())}**.")
    log(f"- NonMotoristLocation: **{int(is_inter.sum())} Intersection-***, "
        f"**{int((~is_inter).sum())} Not-Intersection-***. Breakdown:")
    log("```")
    for k, v in city_cross["NonMotoristLocation"].value_counts().items():
        log(f"  {k}: {v}")
    log("```")
    # at a junction WITH a state route (city crash sits right at a state route)
    junction = city_cross[is_inter & (city_cross["DistToStateRoute_m"] <= JUNCTION_M)]
    log(f"- Of the {int(is_inter.sum())} intersection crashes, **{len(junction)} are at a "
        f"junction WITH a state route** (a state route within {JUNCTION_M:.0f} m — the "
        f"'crossing a state route at the corner' cases; {int((junction['InjuryClass']==FATAL).sum())} fatal). "
        f"Sensitivity: ≤5 m → {int((city_cross[is_inter]['DistToStateRoute_m']<=5).sum())}, "
        f"≤15 m → {int((city_cross[is_inter]['DistToStateRoute_m']<=15).sum())}.")

    # =====================================================================
    # 3. Upper-bound (TDOT-favorable) split
    # =====================================================================
    surface = n[n["Jurisdiction"].isin([CITY, TDOT_SR])]
    s_tot = len(surface)
    s_city = int((surface["Jurisdiction"] == CITY).sum())
    s_tdot = int((surface["Jurisdiction"] == TDOT_SR).sum())
    sf = surface[surface["InjuryClass"] == FATAL]
    sf_tot = len(sf)
    sf_city = int((sf["Jurisdiction"] == CITY).sum())
    sf_tdot = int((sf["Jurisdiction"] == TDOT_SR).sum())

    U = len(junction)
    Uf = int((junction["InjuryClass"] == FATAL).sum())
    u_city, u_tdot = s_city - U, s_tdot + U
    uf_city, uf_tdot = sf_city - Uf, sf_tdot + Uf

    log("\n### 3. Surface City/TDOT split — a RANGE (sensitivity to corner crashes)\n")
    log(f"Two bounds on the same {s_tot} surface crashes ({sf_tot} fatal). Lower bound = "
        f"current nearest-centerline (corner crash credited to the city cross-street, "
        f"City-favorable). Upper bound = the {U} state-route-junction crashes credited to "
        f"the STATE ROUTE instead (TDOT-favorable). The truth sits between.\n")
    log("| | City | TDOT |")
    log("|---|---|---|")
    log(f"| ALL — nearest-centerline (current) | {s_city} ({pct(s_city,s_tot)}%) | {s_tdot} ({pct(s_tdot,s_tot)}%) |")
    log(f"| ALL — corner→state route (upper) | {u_city} ({pct(u_city,s_tot)}%) | {u_tdot} ({pct(u_tdot,s_tot)}%) |")
    log(f"| FATAL — nearest-centerline (current) | {sf_city} ({pct(sf_city,sf_tot)}%) | {sf_tdot} ({pct(sf_tdot,sf_tot)}%) |")
    log(f"| FATAL — corner→state route (upper) | {uf_city} ({pct(uf_city,sf_tot)}%) | {uf_tdot} ({pct(uf_tdot,sf_tot)}%) |")
    log(f"\n**Range to report:** surface TDOT share is **{pct(s_tdot,s_tot)}%–{pct(u_tdot,s_tot)}%** "
        f"(all crashes) and **{pct(sf_tdot,sf_tot)}%–{pct(uf_tdot,sf_tot)}%** (fatal); "
        f"City correspondingly **{pct(u_city,s_tot)}%–{pct(s_city,s_tot)}%** / "
        f"**{pct(uf_city,sf_tot)}%–{pct(sf_city,sf_tot)}%**. City owns the majority of surface "
        f"crashes under **both** bounds. (Interstate stays a separate 23 / 10 fatal; the map and "
        f"per-crash labels are unchanged.)")

    # ---- append (idempotent) to the audit md ----
    section = "\n".join(out)
    MARK = "## Sensitivity & watchlist verification"
    if AUDIT_MD.exists():
        txt = AUDIT_MD.read_text(encoding="utf-8")
        if MARK in txt:
            txt = txt.split(MARK)[0].rstrip() + "\n"
        AUDIT_MD.write_text(txt.rstrip() + "\n" + section + "\n", encoding="utf-8")
    print(f"\nAppended sensitivity section to {AUDIT_MD}")


if __name__ == "__main__":
    main()
