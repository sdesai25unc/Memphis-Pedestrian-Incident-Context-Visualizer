# Crash data source — fetchable endpoint (verification, read-only)

This documents where the pedestrian/non-motorist crash data comes from and how to
pull it, so a future scheduled job could fetch only **new** records. **Nothing here
is wired up to auto-update yet** — this is a verification + reference note only.

_Last verified: 2026-06-28 (live, no login, no API key)._

## The endpoint

TDOT **SAFETY MapServer → MapForDashboards → Layer 8 ("Non-Motorist Crashes")**, an
ArcGIS REST query endpoint. Used by `scripts/01_download_crashes.py`.

```
https://tnmap.tn.gov/arcgis/rest/services/SAFETY/MapForDashboards/MapServer/8/query
```

It is a standard ArcGIS REST `/query` endpoint: you pass URL parameters (`where`,
`outFields`, `f=json`, paging params) and it returns JSON.

## What the project asks for

- **`where`**: `County='Shelby' AND PersonType<>'Pedalcyclists'`
  (Shelby County, every non-motorist **except** pedalcyclists — i.e. pedestrians +
  "Other Non-Motorist"; pedalcyclists are excluded by project design).
- **`outFields=*`**, **`returnGeometry=true`**, **`outSR=4326`** (lat/lon).
- Returns **one feature per person involved** ("person-rows"); script 01 then
  dedupes to one row per crash (`MstrRecNbrTxt`), keeping the worst injury and a
  victim count.

## What it returns

JSON with a `features` array; each feature has an `attributes` object (the columns)
and `geometry` (point lat/lon). Relevant fields include `MstrRecNbrTxt` (crash id),
`CollisionDate`, `CollisionDteTime`, `InjuryClass` (severity, `Fatal` = death),
`PersonType`, `NonMotoristLocation`, `Latitude`/`Longitude`, plus light/manner fields.

Dates arrive as **Unix epoch milliseconds** and are converted to `YYYY-MM-DD` in
script 01.

## Live verification (2026-06-28)

| Query | Result |
|---|---|
| `returnCountOnly=true` (full where clause) | **1,499** person-rows |
| same + `AND CollisionDate >= DATE '2026-01-01'` | **172** person-rows |
| layer metadata `supportsPagination` | **true** |
| date-typed fields (`esriFieldTypeDate`) | **`CollisionDate`, `CollisionDteTime`** |

(The headline analysis runs on the **deduplicated, in-Memphis** subset — 1,294
crashes / 175 fatal *at this 2026-06-28 verification; the totals advance with the
rolling window (see CLAUDE.md's current anchors)* — a different, smaller denominator
than the raw person-row count above. The 1,499 is the raw upstream person-row count
on that date, expected to drift as the state's rolling ~3-year window advances.)

## Date filtering — YES, supported

Both date fields are real ArcGIS date types, so the `where` clause can bound by date.
Two equivalent forms work:

```
# date literal (what we tested)
... AND CollisionDate >= DATE '2026-01-01'

# timestamp literal (if you need time-of-day precision)
... AND CollisionDteTime >= TIMESTAMP '2026-06-01 00:00:00'
```

**Count-only probe (cheap, no data transfer)** — paste into a browser or `curl`:

```
https://tnmap.tn.gov/arcgis/rest/services/SAFETY/MapForDashboards/MapServer/8/query
  ?where=County%3D'Shelby'%20AND%20PersonType%3C%3E'Pedalcyclists'%20AND%20CollisionDate%20%3E%3D%20DATE%20'2026-01-01'
  &returnCountOnly=true
  &f=json
```

## How a future incremental pull would work (NOT built yet)

A scheduled job could fetch only new records by adding a date floor to the existing
`where` clause — e.g. `AND CollisionDate >= DATE '<last_pull_date>'` — page through
with `resultOffset`/`resultRecordCount=2000` (pagination is supported), and append
to the deduplicated CSV. The current `scripts/01_download_crashes.py` already does
full paged pulls with a cache-by-count check; adding a date floor + an "append only
new `MstrRecNbrTxt`" step is the only change needed. **Left for later by request.**
