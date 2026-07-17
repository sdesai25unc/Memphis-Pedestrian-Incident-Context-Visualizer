# CLAUDE.md — Memphis Pedestrian Safety Project

Project instructions for Claude Code. These are read automatically at the start of every session.

## What this project is

Turn public crash data into a Memphis-specific breakdown of pedestrian / non-motorist crashes by **who owns the road** (City of Memphis vs. TDOT), plus an interactive map and a statistics resource that help journalists frame these deaths as a systemic *design* problem, not victim error. Full project history, file inventory, and current status live in the README — load it for context:

@README.md

## Environment (Windows)

- Project root: `C:\Users\dchir\Downloads\Memphis Data Project`
- Always use the project virtual environment. Run scripts with the venv Python, **never** bare `python`:
  `.\.venv\Scripts\python.exe scripts\<script>.py`
- Install packages into the venv: `.\.venv\Scripts\python.exe -m pip install <pkg>` (or `py -m pip install <pkg>`).

## How we work (the most important rule)

- **Before writing any code, inspect the actual data files (real column names, real values) and ask clarifying questions until you are 95% certain of what's wanted. Do not guess at columns, values, or file contents.** This has been the rule for every phase and it works — keep following it.
- Scripts are numbered and run in order (`01_…`, `02_…`, …). New work takes the next unused number.
- After a script runs successfully, update `README.md`: append a section for the new script (what it does, inputs, outputs, how to run). **Keep all existing README content — append, never overwrite.**

## File rules (do not break these)

- `data/raw/` — raw API downloads. **Never hand-edit.**
- `data/processed/novel_statistics.md` — a **fixed rubric/template** (definitions, denominator rules, how each figure is verified). **Never edit it.**
- `data/processed/novel_statistics.docx` — the **living statistics document**. New verified numbers are **appended** here, never overwritten.
- Never overwrite `shelby_crashes_classified.csv` or `shelby_crashes_named.csv` — write new outputs to new filenames.
- `outputs/interactive_map/index.html` — the v1 interactive map. When adding to this page (e.g. a stats section), **append below the existing map and keep the map fully intact** — do not remove or break it.

## Methodology constants (do not silently change)

- Distance math uses **EPSG:32136** (NAD83 / Tennessee, meters). **Never** Web Mercator (EPSG:3857) — it stretches distances ~22% at Memphis's latitude and would corrupt the numbers.
- State-route vs. City classification threshold: **30 m**.
- Headline percentages are computed on **in-Memphis crashes only** (`Jurisdiction` = "TDOT" or "City of Memphis"); Suburban-Shelby and Excluded-BadGeo are excluded.
- Standardized street names **keep directional prefixes** (North Parkway ≠ South Parkway). Do not merge them.
- Pedalcyclists are excluded from the dataset by design.
- **Compute every statistic from the data files — never hardcode a number into an output.**

## Sanity-check anchors (current data window)

A correct run should reconcile to these. If it doesn't, stop and report before continuing.

- 1,339 in-Memphis crashes; 179 fatal. (Data window Jan 1, 2023 – Jul 14, 2026; refreshed 2026-07-15 by the first automated CI run.)
- Jurisdiction split ≈ 79.5% City / 20.5% TDOT (surface crashes); ≈ 71.5% / 28.5% (fatal). Limited-access separate: 35 (14 fatal).
- `deadliest_streets.csv` ranks 546 streets; the crash counts sum back to 1,339.
- Top corridors: Poplar 47/9 · Union 37/8 · Lamar 33/7 · Winchester 28/5.

(These shift slowly as the state's rolling ~3-year crash window advances — re-verify rather than assume.)
