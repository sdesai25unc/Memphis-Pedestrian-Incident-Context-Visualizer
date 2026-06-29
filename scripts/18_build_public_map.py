r"""
18_build_public_map.py
=====================

PASS 2 — rebuild the public-facing interactive map + findings dashboard as ONE
clean, self-contained page, off the Pass-1 canonical classifier output. Replaces
the script-09/10 page (those are superseded).

Design goals (deliberately stripped of clutter so a pedestrian-crossing layer can
be added later):
  - default view = individual crash DOTS in THREE categories
    (City of Memphis / TDOT state route / Limited-access), fatal emphasized;
  - NO thick weighted corridor lines, NO fat numbered cluster bubbles;
  - subtle road-segment tint by ownership (slim layer only, never the 55k network);
  - light non-fatal clustering (fatal always individual), per-category toggles,
    a Fatal-only filter, and a default-OFF "Hotspots" intensity overlay;
  - simple user-facing popups (date, severity, location, road-owner) — no provenance.

Every number is computed from the data files (nothing hardcoded). Reconciles to
1,294 crashes / 175 fatal.

Inputs (Pass 1):
  data/processed/shelby_crashes_final.csv
  outputs/interactive_map/ownership_segments_final.geojson
  data/raw/memphis_boundary.geojson   (subtle context outline)
Outputs:
  outputs/interactive_map/index.html              (rebuilt)
  data/processed/novel_statistics.docx            (APPEND a dated Pass-2 section)

Run it with:
    .\.venv\Scripts\python.exe scripts\18_build_public_map.py
"""

import json
import sys
from pathlib import Path
from datetime import date

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"
OUT_MAP = ROOT / "outputs" / "interactive_map"
FINAL_CSV = PROCESSED / "shelby_crashes_final.csv"
SEG_GEOJSON = OUT_MAP / "ownership_segments_final.geojson"
BOUNDARY = ROOT / "data" / "raw" / "memphis_boundary.geojson"
INDEX_HTML = OUT_MAP / "index.html"
DOCX = PROCESSED / "novel_statistics.docx"

# palette
CITY_C, TDOT_C, LIM_C = "#1b9e8f", "#d6453d", "#3a3a44"
FATAL_STROKE = "#10242e"

CITY = "City of Memphis"
TDOT_SR = "TDOT state route"
LIMITED = {"Interstate (TDOT)", "Interstate ramp (TDOT)", "Limited-access (TDOT)"}
FATAL = "Fatal"


def pct(p, w):
    return round(100.0 * p / w, 1) if w else 0.0


def cat3(own):
    if own == CITY:
        return "City"
    if own == TDOT_SR:
        return "TDOT"
    return "Limited"


def compute_stats(f):
    N, NF = len(f), int((f.InjuryClass == FATAL).sum())
    fat = f[f.InjuryClass == FATAL]
    f = f.copy()
    f["cat3"] = f.Ownership.map(cat3)

    surf = f[f.Ownership.isin([CITY, TDOT_SR])]
    s_tot = len(surf)
    c_all = int((surf.Ownership == CITY).sum())
    t_all = int((surf.Ownership == TDOT_SR).sum())
    sf = surf[surf.InjuryClass == FATAL]
    sf_tot = len(sf)
    c_f = int((sf.Ownership == CITY).sum())
    t_f = int((sf.Ownership == TDOT_SR).sum())

    U = int(f.is_corner_case.sum())
    Uf = int((f.is_corner_case & (f.InjuryClass == FATAL)).sum())

    lim = f[f.is_limited_access]
    lim_n, lim_f = len(lim), int((lim.InjuryClass == FATAL).sum())
    int_n = int((f.Ownership == "Interstate (TDOT)").sum())
    ramp_n = int((f.Ownership == "Interstate ramp (TDOT)").sum())
    sam_n = int((f.Ownership == "Limited-access (TDOT)").sum())
    int_f = int(((f.Ownership == "Interstate (TDOT)") & (f.InjuryClass == FATAL)).sum())
    ramp_f = int(((f.Ownership == "Interstate ramp (TDOT)") & (f.InjuryClass == FATAL)).sum())
    sam_f = int(((f.Ownership == "Limited-access (TDOT)") & (f.InjuryClass == FATAL)).sum())

    # design (fatal)
    l4 = int((fat.Street_LANES >= 4).sum())
    s40 = int((fat.Street_SPDLIMIT >= 40).sum())
    both = int(((fat.Street_LANES >= 4) & (fat.Street_SPDLIMIT >= 40)).sum())

    # lighting (fatal)
    dark = int(fat.LightCondition.astype(str).str.startswith("Dark").sum())
    unlit = int(fat.LightCondition.astype(str).eq("Dark-Not Lighted").sum())

    # per-street concentration
    g = f.groupby("Street_Name").agg(
        total=("MstrRecNbrTxt", "size"),
        fatal=("InjuryClass", lambda s: int((s == FATAL).sum())),
        serious=("InjuryClass", lambda s: int((s == "Suspected Serious Injury").sum())),
    )
    by_fatal = g.sort_values(["fatal", "total"], ascending=False)
    cum = by_fatal["fatal"].cumsum()
    streets_half = int((cum < NF / 2).sum() + 1)
    n_streets = len(g)
    zero_fatal = int((g.fatal == 0).sum())

    # top 25 by total then fatal, with dominant category
    top = g.sort_values(["total", "fatal"], ascending=False).head(25)
    top25 = []
    for nm, r in top.iterrows():
        sub = f[f.Street_Name == nm]
        vc = sub.cat3.value_counts()
        dom = vc.index[0]
        dom_share = vc.iloc[0] / vc.sum()
        owner_lbl = {"City": "City of Memphis", "TDOT": "TDOT state route",
                     "Limited": "Limited-access"}[dom]
        spd = sub.Street_SPDLIMIT.mode()
        lanes = sub.Street_LANES.mode()
        top25.append({
            "name": nm, "total": int(r.total), "fatal": int(r.fatal),
            "serious": int(r.serious), "owner": owner_lbl,
            "mixed": bool(dom_share < 0.9),
            "spd": (None if spd.empty or pd.isna(spd.iloc[0]) else int(spd.iloc[0])),
            "lanes": (None if lanes.empty or pd.isna(lanes.iloc[0]) else int(lanes.iloc[0])),
        })

    # charts
    lane_counts = fat.Street_LANES.dropna().astype(int).value_counts().sort_index()
    years = sorted(int(y) for y in f.YearNmb.dropna().unique())
    # parse the collision-date field to real datetimes (it is US-format M/D/YYYY strings);
    # lexicographic string min/max would mis-rank these (e.g. "9/9/2025" > "5/26/2026").
    _cd = pd.to_datetime(f["CollisionDate"], errors="coerce")
    dmin, dmax = _cd.min().strftime("%Y-%m-%d"), _cd.max().strftime("%Y-%m-%d")

    return {
        "N": N, "NF": NF, "s_tot": s_tot, "sf_tot": sf_tot,
        "c_all": c_all, "t_all": t_all, "c_f": c_f, "t_f": t_f,
        "c_all_pct": pct(c_all, s_tot), "t_all_pct": pct(t_all, s_tot),
        "c_f_pct": pct(c_f, sf_tot), "t_f_pct": pct(t_f, sf_tot),
        "U": U, "Uf": Uf,
        "c_all_lo": pct(c_all - U, s_tot), "t_all_hi": pct(t_all + U, s_tot),
        "c_f_lo": pct(c_f - Uf, sf_tot), "t_f_hi": pct(t_f + Uf, sf_tot),
        "lim_n": lim_n, "lim_f": lim_f,
        "int_n": int_n, "ramp_n": ramp_n, "sam_n": sam_n,
        "int_f": int_f, "ramp_f": ramp_f, "sam_f": sam_f,
        "d_4ln": pct(l4, NF), "d_40": pct(s40, NF), "d_both": pct(both, NF), "d_both_n": both,
        "lit_dark": pct(dark, NF), "lit_unlit": pct(unlit, NF), "lit_unlit_n": unlit,
        "streets_half": streets_half, "n_streets": n_streets,
        "zero_fatal_pct": pct(zero_fatal, n_streets),
        "top25": top25,
        "chart_juris": {"all": [c_all, t_all, lim_n], "fatal": [c_f, t_f, lim_f]},
        "chart_lanes": {"labels": [int(k) for k in lane_counts.index],
                        "values": [int(v) for v in lane_counts.values]},
        "chart_year": {"labels": years,
                       "all": [int((f.YearNmb == y).sum()) for y in years],
                       "fatal": [int(((f.YearNmb == y) & (f.InjuryClass == FATAL)).sum()) for y in years]},
        "dmin": dmin, "dmax": dmax,
    }


def crash_array(f):
    """Compact per-crash array: [lat, lng, cat(0/1/2), fatal(0/1), date, sev, loc]."""
    catn = {"City": 0, "TDOT": 1, "Limited": 2}
    rows = []
    for _, r in f.iterrows():
        rows.append([
            round(float(r.Latitude), 6), round(float(r.Longitude), 6),
            catn[cat3(r.Ownership)], 1 if r.InjuryClass == FATAL else 0,
            str(r.CollisionDate)[:10], str(r.InjuryClass), str(r.NonMotoristLocation),
        ])
    return rows


def dashboard_html(s):
    """Build the findings dashboard markup with every number computed from data."""
    return f"""
<section id="stats"><div class="inner">
  <h2>Findings &mdash; who owns the deadly roads, and why people die on them</h2>
  <p class="sub">All figures are the {s['N']:,} pedestrian / non-motorist crashes inside the
     City of Memphis ({s['NF']} fatal), {s['dmin']} to {s['dmax']}. Recomputed from the data &mdash;
     nothing hand-entered.</p>

  <div class="hero">
    <div class="card city">
      <div class="big">{s['c_all_pct']}%</div>
      <div class="lab">of surface crashes are on <b>City of Memphis</b>&ndash;owned roads</div>
      <div class="rng">range {s['c_all_lo']}&ndash;{s['c_all_pct']}% &middot; TDOT {s['t_all_pct']}&ndash;{s['t_all_hi']}%</div>
    </div>
    <div class="card city">
      <div class="big">{s['c_f_pct']}%</div>
      <div class="lab">of pedestrian <b>deaths</b> are on City of Memphis roads</div>
      <div class="rng">range {s['c_f_lo']}&ndash;{s['c_f_pct']}% &middot; TDOT {s['t_f_pct']}&ndash;{s['t_f_hi']}%</div>
    </div>
    <div class="card tdot">
      <div class="big">{s['d_4ln']}%</div>
      <div class="lab">of deaths are on roads with <b>4+ lanes</b>; {s['d_40']}% on roads posted <b>40+ mph</b></div>
      <div class="rng">nearly half ({s['d_both']}%) are on roads that are <i>both</i></div>
    </div>
    <div class="card dark">
      <div class="big">{s['lit_dark']}%</div>
      <div class="lab">of pedestrian deaths happen <b>after dark</b></div>
      <div class="rng">{s['lit_unlit']}% on a <b>dark, unlit</b> road ({s['lit_unlit_n']} deaths)</div>
    </div>
    <div class="card city">
      <div class="big">{s['streets_half']} streets</div>
      <div class="lab">hold <b>half</b> of all pedestrian deaths (of {s['n_streets']} streets)</div>
      <div class="rng">{s['zero_fatal_pct']}% of streets saw no death at all</div>
    </div>
    <div class="card ltd">
      <div class="big">{s['lim_n']}</div>
      <div class="lab">crashes ({s['lim_f']} fatal) on <b>limited-access</b> roads &mdash; interstates, ramps, Sam Cooper</div>
      <div class="rng">counted separately, not in the City/TDOT surface split</div>
    </div>
  </div>

  <p class="reframe">Most Memphis pedestrian deaths are not random residential accidents. They cluster on
     <b>wide, fast, multi-lane arterials</b> &mdash; {s['d_4ln']}% on roads of four or more lanes and
     {s['d_40']}% on roads posted 40&nbsp;mph or higher. When a road is built to move cars quickly
     through many lanes, a person trying to cross has little chance. This is a <b>design problem, not a
     behavior problem</b>: who builds, owns, and lights these roads &mdash; the City and TDOT &mdash;
     decides whether crossing them is survivable.</p>

  <h3>Who owns the road</h3>
  <table class="juris">
    <tr><th>Category</th><th>All crashes</th><th>Deaths</th></tr>
    <tr><td><span class="sw" style="background:{CITY_C}"></span>City of Memphis (surface)</td>
        <td>{s['c_all']:,} ({s['c_all_pct']}%)</td><td>{s['c_f']} ({s['c_f_pct']}%)</td></tr>
    <tr><td><span class="sw" style="background:{TDOT_C}"></span>TDOT state route (surface)</td>
        <td>{s['t_all']:,} ({s['t_all_pct']}%)</td><td>{s['t_f']} ({s['t_f_pct']}%)</td></tr>
    <tr><td><span class="sw" style="background:{LIM_C}"></span>Limited-access (TDOT) &mdash; separate</td>
        <td>{s['lim_n']}</td><td>{s['lim_f']}</td></tr>
  </table>
  <p class="rangenote"><b>The range.</b> Of surface crashes, the City of Memphis owns
     <b>{s['c_all_lo']}&ndash;{s['c_all_pct']}%</b> (about {round(s['c_all_pct'])}% by the primary method) and
     TDOT state routes <b>{s['t_all_pct']}&ndash;{s['t_all_hi']}%</b>; among deaths, City
     <b>{s['c_f_lo']}&ndash;{s['c_f_pct']}%</b> and TDOT <b>{s['t_f_pct']}&ndash;{s['t_f_hi']}%</b>. The
     range&apos;s upper TDOT bound credits the {s['U']} crashes at a city corner with a state route to the
     state route instead of the city cross-street. <b>The City owns the majority of surface pedestrian
     crashes under either reading.</b> Limited-access roads (interstates, ramps, Sam&nbsp;Cooper) are a
     separate {s['lim_n']} crashes ({s['lim_f']} fatal).</p>

  <h3>Charts</h3>
  <div class="charts">
    <div class="chart-box"><h4>Who owns the road &mdash; all crashes vs. deaths</h4>
      <canvas id="cJuris" height="220"></canvas></div>
    <div class="chart-box"><h4>Deaths by number of lanes</h4>
      <canvas id="cLanes" height="220"></canvas></div>
    <div class="chart-box"><h4>Crashes by year</h4>
      <canvas id="cYear" height="220"></canvas></div>
  </div>

  <h3>The 25 deadliest corridors</h3>
  <p class="sub">Click a column to sort. Owner is the dominant road owner along the corridor.</p>
  <table class="deadliest" id="deadliest">
    <thead><tr>
      <th data-k="rank">#</th><th data-k="name">Street</th><th data-k="total">Crashes</th>
      <th data-k="serious">Serious Injury</th><th data-k="fatal">Deaths</th><th data-k="owner">Owner</th>
      <th data-k="spd">Speed</th><th data-k="lanes">Lanes</th>
    </tr></thead><tbody></tbody>
  </table>

  <div class="foot">
    <p><b>Method.</b> Tennessee SAFETY non-motorist crash records for Shelby County, {s['dmin']} to
       {s['dmax']}, deduplicated to one crash per report and filtered to inside the City of Memphis.
       Each crash is assigned to the road it happened on &mdash; City of Memphis, a TDOT state route,
       or a limited-access TDOT road &mdash; by matching it to the nearest road centerline (all distance
       math in EPSG:32136, Tennessee meters). Pedalcyclists are excluded. Every figure is recomputed
       from the data.</p>
    <p><b>Sources.</b> Crashes: Tennessee SAFETY MapServer (TDOT). Roads, state routes, city boundary,
       street centerline: City of Memphis Public Works GIS. National ranking: Smart Growth America,
       <i>Dangerous by Design 2024</i>. Sam&nbsp;Cooper Blvd&apos;s low-speed western end is technically a
       city surface street; its tint here reflects the TDOT expressway.</p>
  </div>
</div></section>
"""


def build_html(s, crashes, segments, boundary, crossings):
    dash = dashboard_html(s)
    stats_json = json.dumps({
        "juris": s["chart_juris"], "lanes": s["chart_lanes"], "year": s["chart_year"],
        "top25": s["top25"],
        "colors": {"city": CITY_C, "tdot": TDOT_C, "lim": LIM_C},
    })
    page = _TEMPLATE
    page = page.replace("/*__DASHBOARD__*/", dash)
    page = page.replace("__CITY_C__", CITY_C).replace("__TDOT_C__", TDOT_C)
    page = page.replace("__LIM_C__", LIM_C).replace("__FATAL_STROKE__", FATAL_STROKE)
    page = page.replace("__CRASHES__", json.dumps(crashes, separators=(",", ":")))
    page = page.replace("__SEGMENTS__", json.dumps(segments, separators=(",", ":")))
    page = page.replace("__BOUNDARY__", json.dumps(boundary, separators=(",", ":")))
    page = page.replace("__CROSSINGS__", json.dumps(crossings, separators=(",", ":")))
    page = page.replace("__STATS_JSON__", stats_json)
    return page


def append_docx(s):
    from docx import Document
    from docx.shared import Pt
    if not DOCX.exists():
        print(f"  (skip docx: {DOCX.name} not found)")
        return
    doc = Document(str(DOCX))
    if any(p.text.strip().startswith("Pass 2 — Final classification") for p in doc.paragraphs):
        print("  (docx already has the Pass-2 section; skipping append)")
        return
    doc.add_page_break()
    h = doc.add_heading(f"Pass 2 — Final classification & public map (rebuilt {date.today().isoformat()})", level=1)
    doc.add_paragraph(
        "The jurisdiction methodology is now canonical (rulebook-driven classifier, "
        "scripts/17_classifier.py). The public map + dashboard were rebuilt from it "
        "(scripts/18_build_public_map.py). Numbers below are computed from "
        "shelby_crashes_final.csv and reconcile to 1,294 crashes / 175 fatal.")

    doc.add_heading("Final surface City / TDOT split (range)", level=2)
    for line in [
        f"All surface crashes (n={s['s_tot']}): City {s['c_all_lo']}–{s['c_all_pct']}% "
        f"({s['c_all']:,} pt) / TDOT {s['t_all_pct']}–{s['t_all_hi']}% ({s['t_all']} pt).",
        f"Fatal surface crashes (n={s['sf_tot']}): City {s['c_f_lo']}–{s['c_f_pct']}% "
        f"({s['c_f']} pt) / TDOT {s['t_f_pct']}–{s['t_f_hi']}% ({s['t_f']} pt).",
        f"Point estimate = nearest-centerline (corner crashes counted as city). Upper TDOT "
        f"bound credits the {s['U']} state-route-corner crashes ({s['Uf']} fatal) to the state route.",
        f"Limited-access (TDOT), reported separately: {s['lim_n']} crashes ({s['lim_f']} fatal) "
        f"= interstate {s['int_n']} ({s['int_f']}), ramps {s['ramp_n']} ({s['ramp_f']}), "
        f"Sam Cooper {s['sam_n']} ({s['sam_f']}).",
        f"Reconciliation: surface {s['s_tot']} + limited-access {s['lim_n']} = {s['s_tot']+s['lim_n']} "
        f"(= 1,294); fatal {s['sf_tot']} + {s['lim_f']} = {s['sf_tot']+s['lim_f']} (= 175).",
    ]:
        doc.add_paragraph(line, style="List Bullet")

    doc.add_heading("Methodology decision-tree (internal)", level=2)
    for i, line in enumerate([
        "Interstate mainline (MTFCC S1100) → Limited-access (TDOT).",
        "Interstate ramp (MTFCC S1630) → Limited-access (TDOT).",
        "Limited-access override (documented name list; seeded with Sam Cooper Blvd) → Limited-access (TDOT).",
        "State-route geometric overlap (≥60% of the segment within 10 m of a same-named state route, "
        "or ≥85% within 8 m) → TDOT state route.",
        "Force-state-route completeness override (a City segment ≥20% collinear with a same-named "
        "state route; name-guarded) → TDOT state route.",
        "Otherwise → City of Memphis.",
    ], 1):
        doc.add_paragraph(f"Rule {i}: {line}", style="List Number")
    doc.add_paragraph(
        "Each crash inherits the ownership of its nearest rulebook segment (EPSG:32136). "
        "A corner case = a city crash on a non-state-route-named street, at an intersection, "
        "within 10 m of a state route (drives the range's upper bound only).")

    doc.add_heading("Per-incident provenance", level=2)
    doc.add_paragraph(
        "data/processed/shelby_crashes_final.csv carries, for every crash: Ownership, "
        "Classification_Basis (human-readable reason), Rule_Fired, matched Seg_OBJECTID, "
        "DistToSeg_m, flags is_limited_access / is_corner_case / is_override, and Jurisdiction_prev "
        "(the prior segment-method label) as an audit trail.")
    doc.save(str(DOCX))
    print(f"  appended Pass-2 section to {DOCX.name}")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    f = pd.read_csv(FINAL_CSV)
    for col in ["is_limited_access", "is_corner_case", "is_override"]:
        f[col] = f[col].astype(str).str.lower().isin(["true", "1", "yes"])
    s = compute_stats(f)
    crashes = crash_array(f)
    segments = json.loads(SEG_GEOJSON.read_text(encoding="utf-8"))
    boundary = json.loads(BOUNDARY.read_text(encoding="utf-8")) if BOUNDARY.exists() else {"type": "FeatureCollection", "features": []}
    cross_path = PROCESSED / "signalized_crossings_dedup.geojson"
    crossings = json.loads(cross_path.read_text(encoding="utf-8")) if cross_path.exists() else {"type": "FeatureCollection", "features": []}

    html = build_html(s, crashes, segments, boundary, crossings)
    INDEX_HTML.write_text(html, encoding="utf-8")
    print(f"Wrote {INDEX_HTML} ({len(html)/1e6:.2f} MB)")
    append_docx(s)

    # ---- report ----
    def row(label, allv, fatv):
        print(f"{label:<34}{allv:>18}{fatv:>14}")
    print("\n=== FINAL JURISDICTION TABLE (as rendered) ===")
    row("Category", "All crashes", "Deaths")
    row("City of Memphis (surface)", f"{s['c_all']:,} ({s['c_all_pct']}%)", f"{s['c_f']} ({s['c_f_pct']}%)")
    row("TDOT state route (surface)", f"{s['t_all']} ({s['t_all_pct']}%)", f"{s['t_f']} ({s['t_f_pct']}%)")
    row("Limited-access (TDOT) [separate]", str(s['lim_n']), str(s['lim_f']))
    print(f"\nRange: City {s['c_all_lo']}-{s['c_all_pct']}% / TDOT {s['t_all_pct']}-{s['t_all_hi']}% (all); "
          f"City {s['c_f_lo']}-{s['c_f_pct']}% / TDOT {s['t_f_pct']}-{s['t_f_hi']}% (fatal).")
    surf_recon = s['s_tot'] + s['lim_n']
    fat_recon = s['sf_tot'] + s['lim_f']
    print(f"\nRECONCILIATION: surface {s['s_tot']} + limited {s['lim_n']} = {surf_recon} "
          f"{'OK' if surf_recon == 1294 else 'FAIL'} (=1294); "
          f"fatal {s['sf_tot']} + {s['lim_f']} = {fat_recon} {'OK' if fat_recon == 175 else 'FAIL'} (=175)")

    print("\n=== CARD NUMBERS THAT DRIFTED (old page -> new) ===")
    drift = [
        ("City share, all crashes", "74.7%", f"{s['c_all_pct']}% (range {s['c_all_lo']}-{s['c_all_pct']}%)"),
        ("TDOT share, all crashes", "25.3%", f"{s['t_all_pct']}% (range {s['t_all_pct']}-{s['t_all_hi']}%)"),
        ("City share, fatal", "70.3%", f"{s['c_f_pct']}%"),
        ("TDOT share, fatal", "29.7%", f"{s['t_f_pct']}%"),
        ("Limited-access line", "(folded into City/TDOT)", f"{s['lim_n']} crashes / {s['lim_f']} fatal, separate"),
        ("Design: 4+ lanes & 40+ mph", "49.7% (hero)", f"{s['d_both']}% (reframed as 'nearly half', not a majority)"),
        ("Design: 4+ lanes / 40+ mph majorities", "62.9% / 60.0%", f"{s['d_4ln']}% / {s['d_40']}%"),
        ("Lighting after dark / unlit", "76.6% / 14.3%", f"{s['lit_dark']}% / {s['lit_unlit']}%"),
        ("Concentration", "26 streets / 80.3% none", f"{s['streets_half']} streets / {s['zero_fatal_pct']}% none"),
    ]
    for lbl, old, new in drift:
        flag = "" if old.split()[0] == new.split()[0] else "  <-- changed"
        print(f"  {lbl:<40} {old:<26} -> {new}{flag}")


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Memphis Pedestrian Crashes — by who owns the road</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
  :root { --city: __CITY_C__; --tdot: __TDOT_C__; --lim: __LIM_C__; }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; color: #1a1a1a; }
  #maphead { background: #14303f; color: #fff; padding: 14px 20px; }
  #maphead h1 { margin: 0; font-size: 20px; font-weight: 700; }
  #maphead p { margin: 4px 0 0; font-size: 13px; color: #b9ccd6; }
  #map { width: 100%; height: 72vh; min-height: 460px; background: #eef1f3; }
  .leaflet-control.panel { background: #fff; padding: 0; border-radius: 9px; box-shadow: 0 2px 10px rgba(0,0,0,.25); font-size: 13px; line-height: 1.5; width: 214px; overflow: hidden; }
  .panel .panel-hd { display: flex; align-items: center; justify-content: space-between; padding: 8px 11px; cursor: pointer; font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: .05em; color: #14303f; user-select: none; }
  .panel .panel-hd .panel-tog { color: #8aa; font-size: 10px; transition: transform .15s; }
  .panel.collapsed .panel-hd .panel-tog { transform: rotate(180deg); }
  .panel.collapsed .panel-body { display: none; }
  .panel .panel-body { padding: 0 11px 10px; }
  .panel h4 { margin: 7px 0 5px; font-size: 11px; text-transform: uppercase; letter-spacing: .05em; color: #54646c; }
  .panel label { display: block; cursor: pointer; }
  .panel .swatch { display: inline-block; width: 11px; height: 11px; border-radius: 50%; margin-right: 5px; vertical-align: middle; }
  .panel hr { border: none; border-top: 1px solid #e6eaec; margin: 8px 0; }
  .panel .lgd { font-size: 12px; line-height: 1.75; color: #33444c; }
  .panel .line { display: inline-block; width: 16px; height: 3px; margin-right: 6px; vertical-align: middle; }
  .panel .fatal-ex { display:inline-block; width:11px; height:11px; border-radius:50%; margin-right:6px; background:#fff; border:2px solid __FATAL_STROKE__; vertical-align:middle;}
  .leaflet-popup-content { font-size: 13px; line-height: 1.5; margin: 10px 12px; }
  .leaflet-popup-content b { color: #14303f; }
  /* ---- dashboard ---- */
  #stats { background: #f4f6f7; padding: 28px 20px 52px; }
  #stats .inner { max-width: 1120px; margin: 0 auto; }
  #stats h2 { font-size: 24px; color: #14303f; margin: 4px 0 4px; }
  #stats h3 { font-size: 18px; color: #14303f; margin: 36px 0 12px; border-bottom: 2px solid #dde4e7; padding-bottom: 6px; }
  #stats h4 { font-size: 14px; color: #14303f; margin: 0 0 8px; }
  #stats .sub { color: #4a5b63; margin: 0 0 18px; font-size: 13px; }
  .hero { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; }
  .card { background: #fff; border-radius: 8px; padding: 16px; box-shadow: 0 1px 4px rgba(0,0,0,.12); border-top: 4px solid #14303f; }
  .card.city { border-top-color: var(--city); }
  .card.tdot { border-top-color: var(--tdot); }
  .card.dark { border-top-color: #2b2b50; }
  .card.ltd  { border-top-color: var(--lim); }
  .card .big { font-size: 30px; font-weight: 700; color: #14303f; line-height: 1.1; }
  .card .lab { font-size: 13px; color: #33444c; margin-top: 6px; }
  .card .rng { font-size: 11px; color: #6a7a82; margin-top: 8px; }
  .reframe { background: #fff; border-left: 4px solid var(--tdot); padding: 14px 16px; border-radius: 6px;
             margin: 22px 0 0; font-size: 14px; line-height: 1.65; box-shadow: 0 1px 4px rgba(0,0,0,.1); }
  table.juris { border-collapse: collapse; width: 100%; max-width: 640px; background: #fff; font-size: 14px; box-shadow: 0 1px 4px rgba(0,0,0,.1); border-radius: 8px; overflow: hidden; }
  table.juris th { background: #14303f; color: #fff; text-align: left; padding: 9px 12px; }
  table.juris td { padding: 9px 12px; border-bottom: 1px solid #eef2f3; }
  .sw { display:inline-block; width:11px; height:11px; border-radius:50%; margin-right:7px; vertical-align: middle; }
  .rangenote { font-size: 13px; color: #33444c; line-height: 1.6; margin-top: 14px; max-width: 880px; }
  .charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 18px; }
  .chart-box { background: #fff; border-radius: 8px; padding: 14px 16px; box-shadow: 0 1px 4px rgba(0,0,0,.1); }
  table.deadliest { width: 100%; border-collapse: collapse; background: #fff; font-size: 13px; box-shadow: 0 1px 4px rgba(0,0,0,.1); border-radius: 8px; overflow: hidden; }
  table.deadliest th { background: #14303f; color: #fff; text-align: left; padding: 9px 10px; cursor: pointer; user-select: none; }
  table.deadliest th:hover { background: #1d4257; }
  table.deadliest td { padding: 8px 10px; border-bottom: 1px solid #eaeef0; }
  table.deadliest tr:nth-child(even) td { background: #f7f9fa; }
  .foot { margin-top: 30px; font-size: 12px; color: #5a6a72; line-height: 1.6; }
</style>
</head>
<body>
<div id="maphead">
  <h1>Memphis pedestrian crashes — by who owns the road</h1>
  <p>Every dot is a crash. Color shows the road owner. Deaths are emphasized. Drag, zoom, and toggle below.</p>
</div>
<div id="map"></div>
/*__DASHBOARD__*/

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.heat@0.2.0/dist/leaflet-heat.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>
var CRASHES = __CRASHES__;
var SEGMENTS = __SEGMENTS__;
var BOUNDARY = __BOUNDARY__;
var CROSSINGS = __CROSSINGS__;
var S = __STATS_JSON__;
var COL = [S.colors.city, S.colors.tdot, S.colors.lim];
var CATLBL = ["City of Memphis", "TDOT state route", "Limited-access (TDOT)"];

var map = L.map("map", { preferCanvas: true }).setView([35.135, -90.01], 11);
L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
  attribution: '&copy; OpenStreetMap &copy; CARTO', subdomains: "abcd", maxZoom: 19
}).addTo(map);

// boundary outline (context)
L.geoJSON(BOUNDARY, { style: { color: "#8a9aa2", weight: 1.5, fill: false, dashArray: "4 4", opacity: .7 } }).addTo(map);

// road ownership tint (slim layer only)
L.geoJSON(SEGMENTS, { style: function (ft) {
  var o = ft.properties.Ownership;
  if (o === "TDOT state route") return { color: COL[1], weight: 3, opacity: .45 };
  return { color: COL[2], weight: 3, opacity: .40 };  // interstate / ramp / limited-access
}}).addTo(map);

function popupHtml(c) {
  return "<b>" + c[4] + "</b><br>" + c[5] + "<br>" + c[6] +
         "<br><b>Road owner:</b> " + CATLBL[c[2]];
}

// per-category layers: every crash is an individual dot at all zooms (no clustering)
var nonfat = [], fatals = [], heatPts = [];
for (var k = 0; k < 3; k++) { nonfat[k] = L.layerGroup(); fatals[k] = L.layerGroup(); }
CRASHES.forEach(function (c) {
  var cat = c[2], ll = [c[0], c[1]];
  heatPts.push([c[0], c[1], c[3] ? 1.0 : 0.45]);
  if (c[3]) {  // fatal — emphasized
    L.circleMarker(ll, { radius: 6, color: "__FATAL_STROKE__", weight: 2,
      fillColor: COL[cat], fillOpacity: .92 }).bindPopup(popupHtml(c)).addTo(fatals[cat]);
  } else {     // non-fatal — individual dot, never grouped
    L.circleMarker(ll, { radius: 4, color: COL[cat], weight: 0.6,
      fillColor: COL[cat], fillOpacity: .6 }).bindPopup(popupHtml(c)).addTo(nonfat[cat]);
  }
});
var heat = L.heatLayer(heatPts, { radius: 18, blur: 16, maxZoom: 14, minOpacity: .25 });

// signalized pedestrian crossings (TDOT inventory) — DEFAULT OFF, distinct marker
var crossLayer = L.layerGroup();
(CROSSINGS.features || []).forEach(function (ft) {
  var g = ft.geometry.coordinates, p = ft.properties || {};
  L.circleMarker([g[1], g[0]], { radius: 4, color: "#1f3f8c", weight: 1.6,
    fillColor: "#7aa8e6", fillOpacity: .95 })
    .bindPopup("<b>Signalized pedestrian crossing</b><br>" + (p.dom_street || "") +
               "<br>Pedestrian walk signals + push buttons (TDOT ADA inventory)")
    .addTo(crossLayer);
});

// state + render
var st = { cat: [true, true, true], fatalOnly: false, hotspots: false, crossings: false };
function render() {
  for (var k = 0; k < 3; k++) {
    if (st.cat[k]) { map.addLayer(fatals[k]); } else { map.removeLayer(fatals[k]); }
    if (st.cat[k] && !st.fatalOnly) { map.addLayer(nonfat[k]); } else { map.removeLayer(nonfat[k]); }
  }
  if (st.hotspots) { map.addLayer(heat); } else { map.removeLayer(heat); }
  if (st.crossings) { map.addLayer(crossLayer); } else { map.removeLayer(crossLayer); }
}
render();

// combined layers + legend control (collapsible). Top-left so it never collides with the
// search panel (top-right). The three owner checkboxes double as the color legend, so the old
// standalone bottom-left legend is folded in here -- only the non-toggle symbols remain as a
// small Legend subsection.
var panel = L.control({ position: "topleft" });
panel.onAdd = function () {
  var d = L.DomUtil.create("div", "leaflet-control panel");
  d.innerHTML =
    '<div class="panel-hd"><span>Map layers</span><span class="panel-tog">&#9650;</span></div>' +
    '<div class="panel-body">' +
      '<h4>Road owner</h4>' +
      '<label><input type="checkbox" data-cat="0" checked><span class="swatch" style="background:' + COL[0] + '"></span>City of Memphis</label>' +
      '<label><input type="checkbox" data-cat="1" checked><span class="swatch" style="background:' + COL[1] + '"></span>TDOT state route</label>' +
      '<label><input type="checkbox" data-cat="2" checked><span class="swatch" style="background:' + COL[2] + '"></span>Limited-access</label>' +
      '<hr><label><input type="checkbox" id="fatalOnly"> Fatal crashes only</label>' +
      '<label><input type="checkbox" id="hotspots"> Hotspots (intensity)</label>' +
      '<label><input type="checkbox" id="crossings"> Signalized ped crossings (TDOT)</label>' +
      '<hr><h4>Legend</h4>' +
      '<div class="lgd"><span class="fatal-ex"></span>Fatal crash (emphasized)</div>' +
      '<div class="lgd"><span class="line" style="background:' + COL[1] + '"></span>state-route&nbsp;/&nbsp;' +
        '<span class="line" style="background:' + COL[2] + '"></span>limited-access road</div>' +
      '<div class="lgd"><span class="swatch" style="background:#7aa8e6;border:1.5px solid #1f3f8c"></span>Signalized pedestrian crossing</div>' +
    '</div>';
  L.DomEvent.disableClickPropagation(d);
  L.DomEvent.disableScrollPropagation(d);
  d.querySelector('.panel-hd').addEventListener('click', function () { d.classList.toggle('collapsed'); });
  d.querySelectorAll('input[data-cat]').forEach(function (cb) {
    cb.addEventListener("change", function () { st.cat[+cb.dataset.cat] = cb.checked; render(); });
  });
  d.querySelector("#fatalOnly").addEventListener("change", function (e) { st.fatalOnly = e.target.checked; render(); });
  d.querySelector("#hotspots").addEventListener("change", function (e) { st.hotspots = e.target.checked; render(); });
  d.querySelector("#crossings").addEventListener("change", function (e) { st.crossings = e.target.checked; render(); });
  return d;
};
panel.addTo(map);

// ---- charts ----
new Chart(document.getElementById("cJuris"), {
  type: "bar",
  data: { labels: ["City of Memphis", "TDOT state route", "Limited-access"],
    datasets: [
      { label: "All crashes", backgroundColor: ["#9cd6cd", "#eda9a3", "#a9a9b4"], data: S.juris.all },
      { label: "Deaths", backgroundColor: [COL[0], COL[1], COL[2]], data: S.juris.fatal } ] },
  options: { plugins: { legend: { position: "bottom" } }, scales: { y: { beginAtZero: true } } }
});
new Chart(document.getElementById("cLanes"), {
  type: "bar",
  data: { labels: S.lanes.labels.map(function (l) { return l + " ln"; }),
    datasets: [{ label: "Deaths", backgroundColor: COL[1], data: S.lanes.values }] },
  options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } }
});
new Chart(document.getElementById("cYear"), {
  type: "bar",
  data: { labels: S.year.labels,
    datasets: [
      { label: "All crashes", backgroundColor: "#9cb3bd", data: S.year.all },
      { label: "Deaths", backgroundColor: COL[1], data: S.year.fatal } ] },
  options: { plugins: { legend: { position: "bottom" } }, scales: { y: { beginAtZero: true } } }
});

// ---- deadliest table (sortable) ----
(function () {
  var rows = S.top25.map(function (r, i) { r.rank = i + 1; return r; });
  var tbody = document.querySelector("#deadliest tbody");
  var dir = {};
  function draw() {
    tbody.innerHTML = rows.map(function (r) {
      return "<tr><td>" + r.rank + "</td><td><b>" + r.name + "</b></td><td>" + r.total +
        "</td><td>" + r.serious + "</td><td>" + r.fatal + "</td><td>" + r.owner +
        (r.mixed ? " <span style='color:#8a99a0'>(mixed)</span>" : "") + "</td><td>" +
        (r.spd == null ? "&mdash;" : r.spd) + "</td><td>" + (r.lanes == null ? "&mdash;" : r.lanes) + "</td></tr>";
    }).join("");
  }
  draw();
  document.querySelectorAll("#deadliest th").forEach(function (th) {
    th.addEventListener("click", function () {
      var k = th.dataset.k; dir[k] = !dir[k];
      rows.sort(function (a, b) {
        var x = a[k], y = b[k];
        if (typeof x === "string") { return dir[k] ? x.localeCompare(y) : y.localeCompare(x); }
        return dir[k] ? x - y : y - x;
      });
      draw();
    });
  });
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()

