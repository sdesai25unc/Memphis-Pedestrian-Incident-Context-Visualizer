r"""
07_compute_novel_stats.py
========================

Computes and PRINTS every "novel statistic" the project relies on, straight from
the verified data files, so the numbers in data/processed/novel_statistics.md
can be locked, audited, and refreshed whenever the rolling crash window advances.

This script only READS data and prints numbers - it writes no files. Re-run it to
re-verify the figures in novel_statistics.md.

Inputs:
  data/processed/shelby_crashes_named.csv   (1,294 in-Memphis crashes, per-crash)
  data/processed/deadliest_streets.csv      (529 streets, per-street)

Run it with:
    .\.venv\Scripts\python.exe scripts\07_compute_novel_stats.py
"""

from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCESSED = PROJECT_ROOT / "data" / "processed"

FATAL = "Fatal"
SERIOUS = "Suspected Serious Injury"


def pct(part, whole):
    return 100.0 * part / whole if whole else 0.0


def main():
    n = pd.read_csv(PROCESSED / "shelby_crashes_named.csv")
    s = pd.read_csv(PROCESSED / "deadliest_streets.csv")

    fatal = n[n["InjuryClass"] == FATAL]
    N = len(n)
    NF = len(fatal)

    print("=" * 72)
    print("A1 / A2  SCOPE + JURISDICTIONAL SPLIT")
    print("=" * 72)
    n_serious = int((n["InjuryClass"] == SERIOUS).sum())
    print(f"In-Memphis crashes: {N}   Fatal: {NF}   Serious: {n_serious}")
    for j in ["City of Memphis", "TDOT"]:
        c = (n["Jurisdiction"] == j).sum()
        cf = ((n["Jurisdiction"] == j) & (n["InjuryClass"] == FATAL)).sum()
        ppl = n.loc[n["Jurisdiction"] == j, "VictimsInCrash"].sum()
        print(f"  {j:18s} crashes {c:4d} ({pct(c,N):4.1f}%) | fatal {cf:3d} ({pct(cf,NF):4.1f}%) | people {int(ppl)} ({pct(ppl, n['VictimsInCrash'].sum()):4.1f}%)")

    print("\n" + "=" * 72)
    print("A4  DEADLIEST STREETS")
    print("=" * 72)
    print(f"Distinct streets with >=1 crash: {len(s)}")
    print("Top 5 by total crashes:")
    for _, r in s.sort_values(["Total_Crashes", "Fatal_Crashes"], ascending=False).head(5).iterrows():
        print(f"  {r.Street_Name:20s} {int(r.Total_Crashes):3d} crashes, {int(r.Fatal_Crashes)} fatal")
    print("Top 5 by fatal crashes:")
    for _, r in s.sort_values(["Fatal_Crashes", "Total_Crashes"], ascending=False).head(5).iterrows():
        print(f"  {r.Street_Name:20s} {int(r.Fatal_Crashes)} fatal, {int(r.Total_Crashes)} crashes")

    print("\n" + "=" * 72)
    print("A5  ROAD CHARACTER  (top-25 streets, and crash-level)")
    print("=" * 72)
    top25 = s.sort_values(["Total_Crashes", "Fatal_Crashes"], ascending=False).head(25)
    print(f"Top-25 mean lanes: {top25['LANES'].mean():.1f} | mean speed: {top25['SPDLIMIT'].mean():.1f}")
    print(f"Top-25 with >=4 lanes: {pct((top25['LANES']>=4).sum(), len(top25)):.0f}% | "
          f">=40 mph: {pct((top25['SPDLIMIT']>=40).sum(), len(top25)):.0f}%")
    # crash-level, using each crash's matched street speed/lanes (0 speed = unknown)
    for label, sub in [("ALL crashes", n), ("FATAL crashes", fatal)]:
        tot = len(sub)
        f40 = (sub["Street_SPDLIMIT"] >= 40).sum()
        l4 = (sub["Street_LANES"] >= 4).sum()
        both = ((sub["Street_SPDLIMIT"] >= 40) & (sub["Street_LANES"] >= 4)).sum()
        print(f"  {label:14s} (n={tot}):  >=40mph {pct(f40,tot):4.1f}% | "
              f">=4 lanes {pct(l4,tot):4.1f}% | both {pct(both,tot):4.1f}%")

    print("\n" + "=" * 72)
    print("A6  CONCENTRATION OF DEATHS")
    print("=" * 72)
    by_fatal = s.sort_values(["Fatal_Crashes", "Total_Crashes"], ascending=False)
    cum = by_fatal["Fatal_Crashes"].cumsum()
    n_streets_half = int((cum < NF / 2).sum() + 1)  # streets needed to reach half
    print(f"Streets to reach half ({NF/2:.0f}) of all {NF} deaths: {n_streets_half}")
    print(f"Streets with ZERO fatalities: {(s['Fatal_Crashes']==0).sum()} of {len(s)}")
    print(f"Streets with exactly ONE crash total: {(s['Total_Crashes']==1).sum()}")
    print(f"Streets with >=1 fatality: {(s['Fatal_Crashes']>=1).sum()}")

    print("\n" + "=" * 72)
    print("A7  LETHALITY OUTLIERS  (streets with >=5 crashes, by fatal share)")
    print("=" * 72)
    busy = s[s["Total_Crashes"] >= 5].copy()
    busy["fatal_share"] = busy["Fatal_Crashes"] / busy["Total_Crashes"]
    for _, r in busy.sort_values(["fatal_share", "Fatal_Crashes"], ascending=False).head(6).iterrows():
        print(f"  {r.Street_Name:24s} {int(r.Fatal_Crashes)}/{int(r.Total_Crashes)} = {r.fatal_share*100:.0f}%")

    print("\n" + "=" * 72)
    print("A8  ROAD CHARACTER BY OWNER  (streets grouped by Dominant_Jurisdiction)")
    print("=" * 72)
    owner = n.merge(s[["Street_Name", "Dominant_Jurisdiction"]], on="Street_Name", how="left")
    for j in ["City of Memphis", "TDOT"]:
        streets_j = s[s["Dominant_Jurisdiction"] == j]
        crashes_j = owner[owner["Dominant_Jurisdiction"] == j]
        spd = crashes_j.loc[crashes_j["Street_SPDLIMIT"] > 0, "Street_SPDLIMIT"]
        print(f"  {j:18s}: {len(streets_j):3d} streets | {len(crashes_j):4d} crashes | "
              f"{(crashes_j['InjuryClass']==FATAL).sum():3d} fatal | "
              f"mean {crashes_j['Street_LANES'].mean():.1f} lanes / {spd.mean():.1f} mph")

    print("\n" + "=" * 72)
    print(f"A9  WHERE PEOPLE WERE WHEN KILLED  (recomputed on in-Memphis fatal = {NF})")
    print("=" * 72)
    loc = fatal["NonMotoristLocation"]
    jay = (loc == "Not Intersection-On Roadway Not In Crosswalk").sum()
    no_cw = loc.isin(["Not Intersection-On Roadway Crosswalk not Available",
                      "Intersection-On Roadway Crosswalk Not Available"]).sum()
    marked = (loc == "Intersection-In Crosswalk").sum()
    print(f"  'Not Intersection-On Roadway Not In Crosswalk' (jaywalking-framed): {jay} ({pct(jay,NF):.1f}%)")
    print(f"  Crosswalk NOT AVAILABLE (intersection + non-intersection):          {no_cw} ({pct(no_cw,NF):.1f}%)")
    print(f"  Killed IN a marked crosswalk at an intersection:                    {marked} ({pct(marked,NF):.1f}%)")

    print("\n" + "=" * 72)
    print("A10  ROBUSTNESS  (street-join distance quality)")
    print("=" * 72)
    d = pd.to_numeric(n["DistToStreet_m"], errors="coerce")
    print(f"  median {d.median():.1f} m | mean {d.mean():.1f} m | "
          f">40 m: {(d>40).sum()} ({pct((d>40).sum(),N):.1f}%) | max {d.max():.0f} m")

    print("\n" + "=" * 72)
    print("A11  YEAR-BY-YEAR  (in-Memphis crashes; 2026 partial through data window)")
    print("=" * 72)
    by_year = n.groupby("YearNmb").agg(
        crashes=("YearNmb", "size"),
        fatal=("InjuryClass", lambda c: (c == FATAL).sum()),
    )
    for yr, r in by_year.iterrows():
        print(f"  {int(yr)}: {int(r.crashes):4d} crashes | {int(r.fatal):3d} fatal")

    print("\nDate window:", n["CollisionDate"].min(), "to", n["CollisionDate"].max())


if __name__ == "__main__":
    main()
