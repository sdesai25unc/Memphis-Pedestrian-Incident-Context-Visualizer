# Novel Statistics — RUBRIC / TEMPLATE

**This file is the template (the instructions) for `novel_statistics.docx`.**
The `.docx` is the actual living document — the place the numbers are filled in,
added to, and updated. This `.md` defines *what must be in the docx*, *how each
figure is defined*, and *how it gets verified*. When the data refreshes or a new
statistic is computed, update the **docx**; update this rubric only when the
*structure or rules* change.

- **Source of numbers:** `scripts/07_compute_novel_stats.py` (reads
  `shelby_crashes_named.csv` + `deadliest_streets.csv`). Every Section A figure
  in the docx must be reproducible by that script. Re-run it to refresh, then
  update the docx.
- **Conversion helper:** `scripts/08_md_to_docx.py` can regenerate a docx *from a
  markdown file* if ever needed, but going forward the docx is edited directly so
  hand-edits aren't overwritten.

---

## Ground rules the docx must follow

**Two denominators that must never be conflated:**
- **1,294** = unique pedestrian/non-motorist *crashes* inside the City of Memphis. The basis for all of Section A.
- **175** = the fatal crashes among those 1,294.
- Do **not** use the wider **184** fatal *person-rows* (all of Shelby County) for in-Memphis percentages. If an older figure used 184, recompute on 175 and say so.

**What "novel" means — which section a stat belongs in:**
- **Section A** — original to this project AND verified from our data. Locked numbers. Ours to claim.
- **Section B** — external/background facts. Always attribute to the source; never present as our finding.
- **Section C** — high-value stats the data in hand can support but we haven't computed yet (backlog).
- **Section D** — stats that need data we don't have yet.

**Verification rule:** a number only enters Section A of the docx after it is
computed by `scripts/07_compute_novel_stats.py` (or an equally auditable script).
No hand-typed estimates in Section A.

---

## Section A — required contents (verified findings)

Each item below must appear in the docx, filled with current verified numbers
and a one-line plain-language framing. Definitions are fixed; only the numbers move.

- **A1. Scope** — count of in-Memphis crashes, fatal count, serious-injury count; note pedalcyclists excluded and the date window.
- **A2. Jurisdictional split (headline)** — City vs TDOT, as count + % for: all crashes, fatal crashes, and people-affected (sum of victims).
- **A3. The reframe** — the narrative that the City (not TDOT) owns most deadly roads, *and* TDOT is over-represented per road-mile. Both halves required; no numbers, but must stay consistent with A2/A8.
- **A4. Deadliest streets** — number of distinct streets with ≥1 crash; top 5 by total crashes and top 5 by fatalities (name, totals, fatal count).
- **A5. Road character of deadliest streets** — top-25 mean lanes & speed and % ≥4 lanes / % ≥40 mph; PLUS crash-level shares (all crashes and fatal) on ≥40 mph, ≥4 lanes, and both. *Definition:* crash-level uses each crash's own nearest-segment `Street_SPDLIMIT`/`Street_LANES`; 0-mph segments count as unknown (not ≥40).
- **A6. Concentration of deaths** — how many streets account for ~half of all fatalities; counts of streets with zero fatalities, with any fatality, and with a single crash.
- **A7. Lethality outliers** — fatal ÷ total for streets with ≥5 crashes (leads, not headline %, because denominators are small). Interstates listed separately; flag the "ALLEY" artifact.
- **A8. Road character by owner** — streets grouped by dominant jurisdiction: street count, crash count, fatal count, crash-weighted mean lanes & speed. Note why crash counts differ from A2 (grouping by dominant owner).
- **A9. Where victims were when killed** — on the in-Memphis fatal denominator (175): % "Not Intersection–On Roadway, Not In Crosswalk" (the victim-blamed case), % where no crosswalk was available, % in a marked crosswalk at an intersection.
- **A10. Robustness** — street-match distance quality (median/mean, % >40 m, max) and jurisdiction-join sensitivity (TDOT vs City mean distance to nearest state route; stability across 10–100 m).
- **A11. Year-by-year** — in-Memphis crashes and fatal crashes per year (2026 partial). Must sum to A1's totals. Report with caveats; do **not** call any decline a success.

## Section B — required contents (external context, cited)

Carry the national-ranking, historical-trend, crossing-spacing, yield-rate, and
TDOT-acknowledgement facts, each with its source. Include the Tennessee legal
corrections (every intersection a legal crosswalk; turning vehicles must yield;
"due care" duty). Mark the whole section clearly as external — not our analysis.

## Section C — backlog (compute next, then promote to Section A)

Keep the to-compute list current. Open items: lighting-condition breakdown of
fatal crashes; time-of-day / day-of-week pattern; expanded crash-level
road-character table; crash- and fatal-rate per mile by street; formal per-street
lethality ratio with a ≥5 floor; speed-limit distribution of fatal crashes;
name-cleanup/dedup pass before publishing; interstate fatalities as a separate
category. (A9 recomputed-on-175 is **done** and now lives in Section A.)

## Section D — future (needs new data)

Distance from each victim to nearest safe crossing; crossing-desert/gap analysis
vs. the ~300 ft FHWA guideline; equity/demographic overlay; per-capita/exposure
normalization. Each needs data not yet collected (crossing inventory, census).

---

*Rubric for `novel_statistics.docx`. Edit the docx to add/update content; edit
this file only when the required structure or definitions change.*
