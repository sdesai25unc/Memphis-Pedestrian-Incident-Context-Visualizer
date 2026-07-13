r"""
27_build_locate_index.py
========================

FULL-NETWORK SEARCH DATA (for the /api/locate serverless endpoint + the in-page alias table).

The interactive page embeds search data only for the 529 crash-bearing corridors and the
25,533 through-road junction nodes. Any other named Memphis street exists on the basemap but
not to the search tool. Embedding the full network (41 MB rulebook) in the page is not viable,
and loading 41 MB per serverless cold start is not viable either — so this script preprocesses
the standard workaround: a COMPACT lookup structure that the Vercel function `api/locate.js`
bundles via `require()`:

  STREETS — every distinct named street in the canonical rulebook network (Memphis-scoped):
            display name, casual "base" form (no directional prefix / no suffix), WGS84 bbox
            (for map zoom), total length (m), dominant owner (by length, City/TDOT/Limited),
            and a crash count JOINED FROM THE SAME ATTRIBUTION the corridor cards use (0 for
            the ~16k streets outside the 529 — that 0 is honest and displayable).
  NODES   — the SAME citywide junction set script 25 built (true geometric intersection,
            grade-separated interstates/ramps excluded, divided carriageways merged), packed
            [display, lat, lon, crashes, deaths, sig] so the endpoint can answer intersection
            queries identically to the in-page index (plus typo/alias tolerance).
  ALIAS   — built from the DATA: the state-route layer's ALTNAME_1 groups streets that carry
            the same route designation (e.g. SR-3: ELVIS PRESLEY BLVD + N/S SECOND/THIRD ST +
            US HIGHWAY 51 ...). Query keys are generated per group ("sr 3", "state route 3",
            "route 3", "highway 3", "hwy 3", plus the literal ALTNAME_1 text and any member
            name of the form "US HIGHWAY n" -> "us 51"-style keys). No hand-invented pairs.

Excluded from STREETS: the generic catch-all names ALLEY / PRIVATE DR (hundreds of
disconnected segments citywide; meaningless as a search target — same exclusion Count-A uses).

Reads:  data/processed/road_ownership_rulebook.geojson
        data/processed/intersection_nodes_all.geojson
        data/processed/shelby_crashes_final.csv          (street crash counts, for honesty)
        data/raw/state_routes.geojson                    (ALTNAME_1 alias groups)
Writes: data/processed/locate_index.json                 (reference copy)
        outputs/interactive_map/api/locate_data.json     (bundled by api/locate.js)

Run AFTER script 25 (nodes) and BEFORE script 24 (which embeds the alias table in the page):
    .\.venv\Scripts\python.exe scripts\27_build_locate_index.py
"""

import json
import re
import sys
from pathlib import Path

import pandas as pd
import geopandas as gpd

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"
RULEBOOK = PROC / "road_ownership_rulebook.geojson"
NODES = PROC / "intersection_nodes_all.geojson"
FINAL = PROC / "shelby_crashes_final.csv"
ROUTES = ROOT / "data" / "raw" / "state_routes.geojson"
OUT_REF = PROC / "locate_index.json"
OUT_FN = ROOT / "outputs" / "interactive_map" / "api" / "locate_data.json"

GENERIC = {"ALLEY", "PRIVATE DR"}
CAT3 = {"City of Memphis": 0, "TDOT state route": 1}   # everything else (interstate/ramp/limited) -> 2

SUFFIX = {"AVE": "Avenue", "ST": "Street", "RD": "Road", "BLVD": "Boulevard",
          "DR": "Drive", "PKWY": "Parkway", "HWY": "Highway", "LN": "Lane",
          "CT": "Court", "PL": "Place", "CIR": "Circle", "PIKE": "Pike",
          "EXT": "Ext", "WAY": "Way", "COVE": "Cove", "TER": "Terrace"}

# words dropped when forming the casual "base" name. MUST stay in sync with the client
# BASE() in scripts/24_build_search.py and the server base() in api/locate.js.
SUFFIX_WORDS = {"avenue", "ave", "street", "st", "road", "rd", "boulevard", "blvd", "drive",
                "dr", "parkway", "pkwy", "highway", "hwy", "lane", "ln", "court", "ct",
                "place", "pl", "circle", "cir", "pike", "way", "cove", "cv", "terrace",
                "ter", "ext", "expressway", "expy"}
DIRS = {"n", "s", "e", "w", "north", "south", "east", "west"}


def titlecase_street(name):
    return " ".join(SUFFIX.get(w, w.capitalize() if not w.isdigit() else w)
                    for w in str(name).split())


def base_form(name):
    w = re.sub(r"[^a-z0-9 ]", " ", str(name).lower()).split()
    if len(w) > 1 and w[0] in DIRS:
        w = w[1:]
    if len(w) > 1 and w[-1] in SUFFIX_WORDS:
        w = w[:-1]
    return " ".join(w)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    # ---- STREETS: dissolve the rulebook per street name ----
    rb = gpd.read_file(RULEBOOK, columns=["Street_Name", "MTFCC", "Ownership"])
    rb = rb[rb["Street_Name"].notna() & (rb["Street_Name"].astype(str).str.strip() != "")]
    rb = rb[~rb["Street_Name"].isin(GENERIC)]
    rb_m = rb.to_crs("EPSG:32136")
    rb["len_m"] = rb_m.geometry.length
    rb["own3"] = rb["Ownership"].map(CAT3).fillna(2).astype(int)

    crash_counts = pd.read_csv(FINAL)["Street_Name"].value_counts().to_dict()

    streets = []
    for name, g in rb.groupby("Street_Name"):
        b = g.total_bounds  # minx, miny, maxx, maxy (WGS84)
        own = int(g.groupby("own3")["len_m"].sum().idxmax())
        streets.append([
            titlecase_street(name), base_form(name),
            round(float(b[1]), 5), round(float(b[0]), 5),
            round(float(b[3]), 5), round(float(b[2]), 5),
            int(round(g["len_m"].sum())), own,
            int(crash_counts.get(name, 0)),
        ])
    streets.sort(key=lambda s: s[0])

    # ---- NODES: repack script 25's citywide junction set ----
    nd = gpd.read_file(NODES)
    nodes = []
    for _, r in nd.to_crs("EPSG:4326").iterrows():
        sts = [titlecase_street(s.strip()) for s in str(r["streets"]).split(";") if s.strip()]
        c = r.geometry.centroid
        sig = "y" if bool(r["signalized"]) else ("n" if bool(r["on_covered"]) else "u")
        nodes.append([" & ".join(sts), round(float(c.y), 5), round(float(c.x), 5),
                      int(r["crashes"]), int(r["deaths"]), sig])

    # ---- ALIAS: state-route designation groups from ALTNAME_1 (data-derived only) ----
    routes = json.loads(ROUTES.read_text(encoding="utf-8"))
    groups = {}
    for ft in routes["features"]:
        p = ft["properties"]
        alt = str(p.get("ALTNAME_1") or "").strip()
        nm = " ".join(x for x in (str(p.get("PREDIR") or "").strip(),
                                  str(p.get("NAME") or "").strip(),
                                  str(p.get("TYPE") or "").strip()) if x)
        if alt and nm:
            groups.setdefault(alt, set()).add(titlecase_street(nm))
    alias = {}

    def add_key(k, members):
        k = re.sub(r"\s+", " ", k.lower().strip())
        if k:
            alias.setdefault(k, set()).update(members)

    for alt, members in groups.items():
        if alt.isdigit():
            for form in (f"sr {alt}", f"state route {alt}", f"route {alt}",
                         f"tn {alt}", f"highway {alt}", f"hwy {alt}"):
                add_key(form, members)
        else:
            add_key(alt, members)                      # e.g. "HIGHWAY 51", "NONCONNAH PKWY"
            add_key(base_form(alt), members)
        # members named like "US HIGHWAY 51" also key the group as "us 51" / "us highway 51"
        for m in members:
            mm = re.match(r"^(?:N |S |E |W )?Us Highway (\d+)$", m, re.I)
            if mm:
                n = mm.group(1)
                for form in (f"us {n}", f"us highway {n}", f"highway {n}", f"hwy {n}", f"us-{n}"):
                    add_key(form, members)
    alias = {k: sorted(v) for k, v in sorted(alias.items())}

    idx = {
        "meta": {"streets": len(streets), "nodes": len(nodes), "alias_keys": len(alias),
                 "source": "road_ownership_rulebook + intersection_nodes_all + state_routes",
                 "note": "streets crash counts use the same Street_Name attribution as the "
                         "corridor cards; 0 means no recorded pedestrian/non-motorist crash "
                         "was attributed to this street in the data window."},
        "streets": streets,
        "nodes": nodes,
        "alias": alias,
    }
    blob = json.dumps(idx, separators=(",", ":"), ensure_ascii=False)
    OUT_REF.write_text(blob, encoding="utf-8")
    OUT_FN.parent.mkdir(parents=True, exist_ok=True)
    OUT_FN.write_text(blob, encoding="utf-8")

    kb = len(blob.encode("utf-8")) / 1024
    print(f"locate index: {len(streets):,} streets | {len(nodes):,} nodes | "
          f"{len(alias)} alias keys | {kb:,.0f} KB")
    print(f"  -> {OUT_REF}")
    print(f"  -> {OUT_FN}  (bundled by api/locate.js via require)")
    # sanity: the known zero-crash residential street must be present with 0 crashes
    sp = next((s for s in streets if s[0] == "Slash Pine Cv"), None)
    print(f"  [check] Slash Pine Cv: {'FOUND, crashes=' + str(sp[8]) if sp else '*** MISSING ***'}")
    ep = alias.get("us 51", [])
    print(f"  [check] alias 'us 51' -> {ep[:4]}{' ...' if len(ep) > 4 else ''}")
    tot = sum(s[8] for s in streets)
    print(f"  [check] sum of street crash counts = {tot} (expect 1294 minus generic-name "
          f"crashes; generic excluded = {1294 - tot})")


if __name__ == "__main__":
    main()
