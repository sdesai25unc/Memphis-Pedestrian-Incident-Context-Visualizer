r"""
28_auto_refresh.py
==================

SCHEDULED DATA REFRESH with safety gates — the engine behind the GitHub Action
(.github/workflows/data-refresh.yml), also runnable by hand. It can NOT publish
anything itself: it only updates files in the working tree and reports a status;
committing/pushing is the workflow's (or the human's) separate decision.

MODES
  --mode auto          incremental daily; FULL on the 1st of the month (the default)
  --mode incremental   cheap change probe first (CollisionDate >= last-max minus a
                       30-day overlap, per HANDOFF §5); if nothing changed, exits
                       cleanly with status=nochange. If anything changed, falls
                       through to a full re-pull: at this source's size the whole
                       window is ONE API page (~1.5k person-rows), so re-pulling
                       beats a partial merge — same result, zero merge-drift risk.
  --mode full          unconditional re-pull of the entire window + full rebuild.
                       REQUIRED monthly: the 2026-07 refresh proved the source
                       DELETES records (fatal 301011588 removed upstream) and
                       backfills old dates — both invisible to date-floored pulls.
  --dry-run            identical behavior, but the workflow will not commit.

SAFETY GATES (any failure -> status=aborted, exit 2, nothing published)
  1. Pull plausibility: API count request must succeed; upstream count must be
     >= MIN_PULL_RATIO of the current local person-rows; downloaded rows must
     match the count the API declared.
  2. Pipeline integrity: every rebuild step must exit 0.
  3. Internal reconciliation (computed, never hardcoded): surface + limited-access
     partitions the in-Memphis total (crashes AND fatals); the embedded search
     index and the locate index must both sum back to the same total.
  4. Sanity bounds vs the previous snapshot: new_total >= old_total - DELETION_ALLOWANCE;
     new_total <= old_total + NEW_RECORD_CEILING; new max CollisionDate >= old.
  5. No-change short-circuit: if the pull yields zero added/removed/changed crash
     records, restore the two pull files and exit with status=nochange — no
     rebuild, no commit, no deploy.

OUTPUTS (for the workflow)
  $GITHUB_OUTPUT   status=updated|nochange|aborted, commit_msg=..., reason=...
  $GITHUB_STEP_SUMMARY (when set) + stdout: a human-readable run report.
  Exit codes: 0 = updated or nochange (see status), 2 = aborted.

Run it locally:
    .\.venv\Scripts\python.exe scripts\28_auto_refresh.py --mode incremental --dry-run
"""

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
PERSONS_CSV = RAW / "shelby_crashes_all_persons.csv"
DEDUP_CSV = PROC / "shelby_crashes_dedup.csv"
FINAL_CSV = PROC / "shelby_crashes_final.csv"
SEARCH_IDX = PROC / "search_index.json"
LOCATE_IDX = PROC / "locate_index.json"
SIDEWALKS = PROC / "memphis_sidewalks_32136.geojson"
STREETS = RAW / "memphis_streets.geojson"

OVERLAP_DAYS = 30          # incremental probe floor = last max CollisionDate minus this
MIN_PULL_RATIO = 0.90      # gate 1: upstream count must be >= this share of local rows
DELETION_ALLOWANCE = 5     # gate 4: tolerated upstream removals per refresh (observed: 1)
NEW_RECORD_CEILING = 75    # gate 4: max plausible growth per refresh (observed: ~1/day;
                           # 75 covers >2 months of backlog — anything above smells wrong)

# the routine rebuild chain (HANDOFF §2), fail-fast in order
PIPELINE = ["03_spatial_join.py", "06_join_streets.py", "14_segment_jurisdiction.py",
            "17_classifier.py", "21_signal_intersections.py", "23_union_poc.py",
            "18_build_public_map.py", "25_rebuild_junctions.py",
            "27_build_locate_index.py", "24_build_search.py"]

LOG = []


def say(msg=""):
    print(msg, flush=True)
    LOG.append(msg)


def gh_output(**kv):
    p = os.environ.get("GITHUB_OUTPUT")
    if p:
        with open(p, "a", encoding="utf-8") as f:
            for k, v in kv.items():
                f.write(f"{k}={v}\n")


def finish_summary():
    p = os.environ.get("GITHUB_STEP_SUMMARY")
    if p:
        with open(p, "a", encoding="utf-8") as f:
            f.write("```\n" + "\n".join(LOG) + "\n```\n")


def abort(reason, detail=""):
    say(f"\n*** ABORT: {reason}")
    if detail:
        say(detail)
    say("Nothing will be committed; the live site is untouched.")
    gh_output(status="aborted", reason=reason)
    finish_summary()
    sys.exit(2)


def load_script01():
    spec = importlib.util.spec_from_file_location(
        "dl01", ROOT / "scripts" / "01_download_crashes.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)          # runs constants + defs only (main() is guarded)
    return m


def crash_signature(df):
    """Per-crash comparison signature to detect modified records between snapshots."""
    return {
        int(r.MstrRecNbrTxt): (
            str(r.CollisionDate), str(r.InjuryClass),
            round(float(r.Latitude), 5) if pd.notna(r.Latitude) else None,
            round(float(r.Longitude), 5) if pd.notna(r.Longitude) else None,
            int(r.VictimsInCrash) if pd.notna(r.VictimsInCrash) else None,
        ) for r in df.itertuples()
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["auto", "incremental", "full"], default="auto")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    mode = args.mode
    if mode == "auto":
        mode = "full" if date.today().day == 1 else "incremental"
    say(f"=== StreetStat auto-refresh | mode={mode}{' (dry-run)' if args.dry_run else ''} "
        f"| {date.today().isoformat()} ===")

    # ---- required inputs the pipeline cannot degrade without ----
    if not SIDEWALKS.exists():
        abort("sidewalk inventory missing",
              f"{SIDEWALKS} is required — without it the build silently loses the sidewalk "
              "layer. It is committed to the repository; restore it from git.")
    if not STREETS.exists():
        abort("street network missing",
              f"{STREETS} is required (regenerate with scripts/05_download_streets.py).")

    # ---- previous snapshot (the baseline every gate compares against) ----
    old_final = pd.read_csv(FINAL_CSV)
    old_total, old_fatal = len(old_final), int((old_final.InjuryClass == "Fatal").sum())
    old_dmax = pd.to_datetime(old_final.CollisionDate).max()
    old_dedup = pd.read_csv(DEDUP_CSV)
    old_sig = crash_signature(old_dedup)
    say(f"current snapshot: {old_total} in-Memphis crashes / {old_fatal} fatal, "
        f"through {old_dmax.date()} | Shelby dedup {len(old_dedup)}")

    m01 = load_script01()

    # ---- gate 1a: the count probe itself must succeed ----
    try:
        api_count = m01.get_current_api_count()
    except Exception as e:
        abort("API count request failed", str(e))
    local_persons = pd.read_csv(PERSONS_CSV)
    say(f"upstream person-rows: {api_count} | local person-rows: {len(local_persons)}")

    # ---- gate 1b: implausibly small upstream answer ----
    if api_count < MIN_PULL_RATIO * len(local_persons):
        abort("implausibly few upstream rows",
              f"upstream {api_count} < {MIN_PULL_RATIO:.0%} of local {len(local_persons)} — "
              "refusing to treat a broken/misbehaving source as a mass deletion.")

    # ---- incremental: cheap date-floored change probe (30-day overlap, HANDOFF §5) ----
    if mode == "incremental":
        floor = (pd.to_datetime(old_dedup.CollisionDate).max()
                 - timedelta(days=OVERLAP_DAYS)).date()
        say(f"incremental probe: CollisionDate >= {floor} (overlap {OVERLAP_DAYS} d)")
        feats, offset = [], 0
        while True:
            r = requests.get(m01.API_URL, params={
                "where": m01.WHERE_CLAUSE + f" AND CollisionDate >= DATE '{floor}'",
                "outFields": "MstrRecNbrTxt,CollisionDate,InjuryClass",
                "returnGeometry": "false", "f": "json",
                # this server 400s on resultOffset/resultRecordCount WITHOUT orderByFields
                "orderByFields": "MstrRecNbrTxt",
                "resultOffset": offset, "resultRecordCount": 2000}, timeout=60)
            r.raise_for_status()
            data = r.json()
            if "error" in data:
                abort("probe query failed", str(data["error"]))
            feats += data.get("features", [])
            if not data.get("exceededTransferLimit"):
                break
            offset += 2000
        probe_ids = {int(f["attributes"]["MstrRecNbrTxt"]) for f in feats}
        lp = local_persons.copy()
        lp["_d"] = pd.to_datetime(lp.CollisionDate)
        local_window_ids = set(lp.loc[lp._d >= pd.Timestamp(floor), "MstrRecNbrTxt"].astype(int))
        new_ids = probe_ids - local_window_ids
        gone_ids = local_window_ids - probe_ids
        say(f"probe: {len(feats)} upstream person-rows in window | "
            f"new ids {len(new_ids)} | vanished-in-window ids {len(gone_ids)}")
        if not new_ids and not gone_ids and len(feats) == len(lp[lp._d >= pd.Timestamp(floor)]):
            say("\nno changes detected in the overlap window — exiting cleanly (gate 5).")
            gh_output(status="nochange", reason="probe found no changes")
            finish_summary()
            return

    # ---- full pull (both modes reach here once change is detected/forced) ----
    say("\nfull pull (unconditional download — count-equality caching is bypassed on purpose:")
    say("an add+remove pair can leave the count unchanged while the content differs)")
    try:
        m01.download_all_pages(api_count)
        person_df = m01.load_pages_into_dataframe()
    except Exception as e:
        abort("download failed", str(e))
    if len(person_df) != api_count:
        abort("row-count mismatch",
              f"downloaded {len(person_df)} person-rows but the API declared {api_count}")
    m01.save_person_rows_csv(person_df)
    new_dedup = m01.make_dedup_crash_csv(person_df)

    # ---- gate 5: real change detection on the deduplicated crash set ----
    new_sig = crash_signature(new_dedup)
    added = sorted(set(new_sig) - set(old_sig))
    removed = sorted(set(old_sig) - set(new_sig))
    modified = sorted(k for k in set(new_sig) & set(old_sig) if new_sig[k] != old_sig[k])
    say(f"\nchange set (Shelby dedup): +{len(added)} added, -{len(removed)} removed, "
        f"~{len(modified)} modified")
    if removed:
        rm = old_dedup[old_dedup.MstrRecNbrTxt.isin(removed)]
        for r in rm.itertuples():
            say(f"  removed upstream: {r.MstrRecNbrTxt} {r.CollisionDate} {r.InjuryClass}")
    if not added and not removed and not modified:
        say("content identical after full pull — restoring pull files, no rebuild (gate 5).")
        subprocess.run(["git", "-C", str(ROOT), "checkout", "--",
                        str(PERSONS_CSV.relative_to(ROOT)), str(DEDUP_CSV.relative_to(ROOT))],
                       check=False)
        gh_output(status="nochange", reason="full pull returned identical content")
        finish_summary()
        return

    # ---- gate 2: the rebuild pipeline, fail-fast ----
    say("\nrebuilding (routine chain):")
    for script in PIPELINE:
        say(f"  -> {script}")
        p = subprocess.run([sys.executable, str(ROOT / "scripts" / script)],
                           capture_output=True, text=True, cwd=str(ROOT))
        if p.returncode != 0:
            abort(f"pipeline step failed: {script}",
                  (p.stdout or "")[-1500:] + "\n" + (p.stderr or "")[-1500:])

    # ---- gate 3: internal reconciliation, computed from the fresh outputs ----
    final = pd.read_csv(FINAL_CSV)
    total, fatal = len(final), int((final.InjuryClass == "Fatal").sum())
    lim = final.is_limited_access.astype(str).str.lower().isin(["true", "1", "yes"])
    surface, limited = int((~lim).sum()), int(lim.sum())
    if surface + limited != total:
        abort("reconciliation failed", f"surface {surface} + limited {limited} != total {total}")
    idx_sum = sum(c["total"] for c in json.loads(SEARCH_IDX.read_text(encoding="utf-8"))["corridors"])
    if idx_sum != total:
        abort("reconciliation failed", f"search index sums to {idx_sum}, expected {total}")
    loc = json.loads(LOCATE_IDX.read_text(encoding="utf-8"))
    loc_sum = sum(s[8] for s in loc["streets"])
    if not (0 <= total - loc_sum <= 25):     # small remainder = crashes on excluded generic names
        abort("reconciliation failed",
              f"locate index street counts sum to {loc_sum}, expected ~{total} "
              f"(generic-name remainder {total - loc_sum} outside 0–25)")

    # ---- gate 4: sanity bounds vs the previous snapshot ----
    new_dmax = pd.to_datetime(final.CollisionDate).max()
    if total < old_total - DELETION_ALLOWANCE:
        abort("sanity bounds", f"new total {total} < old {old_total} - {DELETION_ALLOWANCE} — "
              "mass shrinkage; refusing to publish")
    if total > old_total + NEW_RECORD_CEILING:
        abort("sanity bounds", f"new total {total} > old {old_total} + {NEW_RECORD_CEILING} — "
              "implausible growth; refusing to publish")
    if new_dmax < old_dmax:
        abort("sanity bounds", f"new max CollisionDate {new_dmax.date()} < old {old_dmax.date()}")

    # ---- success report ----
    g = final.groupby("Street_Name").agg(t=("MstrRecNbrTxt", "size"),
                                         f=("InjuryClass", lambda s: int((s == "Fatal").sum())))
    say("\n=== REFRESH RESULT ===")
    say(f"totals:   {old_total}/{old_fatal}  ->  {total}/{fatal}")
    say(f"window:   through {old_dmax.date()}  ->  {new_dmax.date()}")
    for nm in ["POPLAR AVE", "UNION AVE", "LAMAR AVE", "WINCHESTER RD"]:
        if nm in g.index:
            say(f"  {nm:<15} {g.loc[nm].t}/{g.loc[nm].f}")
    say(f"changes:  +{len(added)} new, -{len(removed)} removed, ~{len(modified)} modified (Shelby dedup)")
    say("all gates passed. " + ("DRY RUN — the workflow will not commit."
                                if args.dry_run else "ready to commit."))
    msg = (f"auto: data refresh through {new_dmax.date()} — "
           f"{len(added)} new, {len(removed)} removed"
           + (f", {len(modified)} modified" if modified else ""))
    gh_output(status="updated", commit_msg=msg,
              reason=f"{len(added)} new / {len(removed)} removed / {len(modified)} modified")
    say(f'commit message: "{msg}"')
    finish_summary()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    main()
