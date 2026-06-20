# Memphis Pedestrian Safety — Novel Statistics & Findings

*Working reference · compiled June 1, 2026 · data window Jan 1, 2023 – May 26, 2026*

---

## How to use this document

This is two things at once:

1. **A reference** of every meaningful number the project has produced or relied on, with sources and exact definitions, so findings can be cited consistently and never drift.
2. **A compute-spec** for Claude Code. **Section A** holds verified findings (locked numbers — ours). **Section B** holds supporting/background stats (external sources — cite, don't claim as original). **Section C** lists high-value statistics we have *not* computed yet but that the data already in hand can support — each written precisely enough to paste straight into a Claude Code prompt. **Section D** lists statistics that require data we don't have yet.

A note on the word **"novel."** A statistic is *novel* if this project's own analysis produced it and no one has published it for Memphis before — the jurisdiction split, the deadliest-streets ranking, the road-character pattern. Those are in Section A. The national-ranking and crossing-spacing figures are real and useful but are *borrowed context*, not ours — they live in Section B and should always be attributed to their source.

**Two denominators that must not be conflated:**
- **1,294** = unique pedestrian/non-motorist *crashes* inside the City of Memphis, the basis for almost everything below.
- **184** = fatal pedestrian *person-rows* across all of Shelby County (a wider net). A few older percentages were computed against 184; those are flagged, and recomputing them on the in-Memphis fatal total (175) is the first item in Section C.

---

## Section A — Novel findings (original to this project · verified)

### A1. Scope
- **1,294** unique pedestrian & non-motorist crashes inside the City of Memphis, Jan 1, 2023 – May 26, 2026.
- **175** of those were fatal.
- Pedalcyclists were deliberately excluded (the project's focus is pedestrian infrastructure).

### A2. The jurisdictional split — *the headline finding*
- **City of Memphis–owned roads: 966 crashes (74.7%)**
- **TDOT (state route)–owned roads: 328 crashes (25.3%)**
- Fatal crashes: **City 123 (70.3%) · TDOT 52 (29.7%)**.
- *Phrasing:* "About three in four Memphis pedestrian crashes — and 70% of the deaths — happen on roads the City of Memphis itself owns and controls."

### A3. The reframe
- The project's original hypothesis was that TDOT controls the deadliest roads and is the primary accountability target. **The data contradicts that.** The City of Memphis is the primary actor with authority over the conditions where most pedestrians die.
- The honest two-part story: **the City owns the majority of deadly streets**, *and* **TDOT is over-represented relative to its small share of road miles** and concentrated on several of the worst individual corridors. Both halves are true; report both.

### A4. Deadliest streets — *first-ever Memphis ranking by street and owner*
- **529** distinct streets saw at least one crash.
- **By total crashes:** Poplar Ave (44, 8 fatal) · Union Ave (36, 8) · Lamar Ave (30, 6) · Winchester Rd (28, 5) · Park Ave (24, 4).
- **By fatalities:** Poplar Ave (8) · Union Ave (8) · S Third St (7) · Lamar Ave (6) · Winchester Rd (5).
- These are all recognizable high-volume arterials — a clean sanity signal that the ranking is real.

### A5. Road character of the deadliest streets — *the design-problem proof*
This is the empirical backbone of "design problem, not behavior problem," and is original to Memphis.
- The **top 25** deadliest streets average **5.4 lanes and a 41 mph speed limit**; **88% have four or more lanes** and **88% are posted 40 mph or higher**.
- **53% of all 175 fatalities** occurred on streets that are **both ≥40 mph and ≥4 lanes.** (62% on ≥40 mph; 63% on ≥4 lanes.)
- Fatalities skew toward fast roads *more* than crashes do: **48%** of all crashes are on ≥40 mph streets, but **62%** of *fatal* ones are — i.e., the fast roads aren't where most crashes happen, they're where crashes are most likely to kill.
- *Phrasing:* "The streets where Memphis pedestrians die are not random residential blocks. They are wide, fast arterials — over half the deaths are on roads with at least four lanes and a 40-mph-or-higher limit."

### A6. Concentration of deaths — *the "this is solvable" finding*
- **Roughly 26 streets account for about half of all 175 pedestrian deaths.**
- Of the 529 streets with any crash, **425 had zero fatalities** and **353 had only a single crash.**
- *Phrasing:* "Half of Memphis pedestrian deaths are concentrated on about two dozen corridors. This is not a problem spread evenly across the city — it is fixable street by street."

### A7. Lethality outliers — *short streets hidden by raw counts*
Some streets are unusually *lethal* even with few crashes (fatal share, among streets with ≥5 crashes):
- N Hollywood St — **4 of 8 fatal (50%)**
- Raleigh Millington Rd — 3 of 7 (43%) · Raleigh Lagrange Rd — 3 of 7 (43%)
- S Third St — 7 of 18 (39%)
- Note: pedestrian fatalities also appear on Interstate segments (I-240, I-40), a distinct and grim category worth separating out.
- *Caveat:* small denominators make these ratios noisy; treat as leads, not headline percentages. This is exactly what a per-mile rate (Section C) would formalize.

### A8. Road character by owner
Crash-weighted averages across all streets with crashes:
- **City-owned streets:** 460 streets, 978 crashes, 132 fatal — mean **3.4 lanes / 36.4 mph.**
- **TDOT state routes:** 69 streets, 316 crashes, 43 fatal — mean **5.0 lanes / 38.4 mph.**
- *Reading:* TDOT's roads really are wider and faster on average (supporting "over-represented per mile / more dangerous by design"), but the City still owns the larger share of both crashes and deaths.

### A9. Where people were when killed — *counters the "jaywalking" frame* ⚠ denominator
*(Computed on the 184 Shelby fatal person-rows — see Section C item 1 to recompute on the in-Memphis 175.)*
- **45%** killed at "Not Intersection – On Roadway, Not In Crosswalk" (the situation news coverage frames as the victim's fault).
- **22%** killed where the data **explicitly records no crosswalk was available** (40 of 184).
- **4%** killed **inside a marked crosswalk at an intersection** (8 of 184) — doing everything legally correct.

### A10. Robustness checks
- **Match quality (street join):** median crash sits **2.0 m** from its assigned street, mean 14.1 m; ~11% matched beyond 40 m (likely parking-lot or block-centroid geocodes), farthest 221 m. Assignments are reliable.
- **Jurisdiction join sensitivity:** the TDOT share is stable across 10–100 m thresholds. A TDOT-tagged crash sits on average **5.1 m** from its state route; a City-tagged crash is on average **1,066 m** from the nearest state route — a clean separation, so the classification is not fragile.

### A11. Year-by-year trend — *report with caveats*
| Year | All non-motorist crashes | Fatal pedestrian crashes |
|---|---|---|
| 2023 | 479 | 61 |
| 2024 | 437 | 53 |
| 2025 | 412 | 52 |
| 2026 (through May 26) | 139 | 18 |
- A modest decline is visible, but the window is short and the underlying road conditions haven't changed. Do **not** report this as a success; report it with caveats.

---

## Section B — Supporting / background stats (external sources · cite, not ours)

- **Memphis ranks #1 nationally** in pedestrian fatality rate — **5.14 per 100,000, ~3× the national average.** *(Smart Growth America, Dangerous by Design 2024.)*
- **343 Memphis pedestrian deaths, 2018–2022.** *(Smart Growth America 2024.)*
- The rate has **nearly tripled since 2009**, with ~65% of the last decade's deaths in the most recent five years. *(Smart Growth America 2024.)*
- A 2022 study found Memphis **driver yield rates at unmarked crossings in the single digits.**
- **FHWA recommends a safe crossing roughly every 300 ft.** Memphis arterials can run far longer — up to ~5,280 ft (≈17× the guideline); Summer Ave has ~3,000 ft gaps; N. Hollywood ~1 mile between signals.
- A **2022 TDOT-sponsored study** acknowledged the state was "disproportionately responsible" for pedestrian injury and death on its roads.
- The widely-quoted **"85% of pedestrian deaths on arterials"** figure traces to a personal-injury law firm (NST Law), not a primary source — directionally plausible but **superseded for Memphis by this project's own road-character analysis (A5).** Prefer A5.

### Legal corrections (factual, for countering victim-blaming coverage)
- In Tennessee, **every intersection is a legal crosswalk** (marked or not) unless explicitly prohibited.
- At a signalized intersection on a green light, **turning vehicles must yield** to a pedestrian crossing legally.
- Drivers must **"exercise due care"** regardless of where a pedestrian is — a duty often ignored in coverage.

---

## Section C — High-value statistics still to compute (data already in hand)

*Each is written so it can be lifted into a Claude Code prompt. Source files: `data/processed/shelby_crashes_named.csv` (per-crash, 1,294 in-Memphis) and `data/processed/deadliest_streets.csv` (per-street). Have Claude Code write the verified numbers into `data/processed/novel_statistics.md`.*

1. **Recompute the "where they were killed" breakdown on the in-Memphis fatal crashes (175), not the 184 Shelby person-rows.** Recreate A9's three percentages (jaywalking-framed, no-crosswalk-available, marked-crosswalk-at-intersection) from the `NonMotoristLocation` field on the 175 in-Memphis fatal crashes, so the denominator matches everything else. *Why: consistency and defensibility before publication.*

2. **Lighting-condition breakdown of fatal crashes.** From the crash data's lighting field, compute the share of fatal pedestrian crashes that occurred in dark / unlit conditions. *Why: street lighting is infrastructure the City controls — a dark-conditions majority is a powerful, novel, design-focused stat.*

3. **Time-of-day and day-of-week pattern of fatal crashes.** Distribution by hour and weekday/weekend. *Why: pairs with lighting to characterize when the danger concentrates.*

4. **Crash-level road character citywide (not just top 25).** Using each crash's own matched street speed/lanes (`Street_SPDLIMIT`, `Street_LANES`), report the % of all crashes and of fatal crashes on ≥40 mph, on ≥4 lanes, and on both — across the full 1,294, refining the street-level approximations in A5. *Why: a clean whole-sample version of the design-problem stat.*

5. **Crash rate per mile (and fatal rate per mile) by street.** Compute each street's length from the geometry in `memphis_streets.geojson`, then crashes-per-mile and fatalities-per-mile. Rank by rate. *Why: surfaces short, disproportionately deadly streets (N Hollywood, the Raleigh roads) that raw counts bury — potentially its own finding.*

6. **Formal per-street lethality ratio** (fatal ÷ total) with a minimum-crash floor (e.g. ≥5) to control noise, reported alongside the rate analysis above.

7. **Speed-limit distribution of fatal crashes.** Histogram of fatal crashes by posted limit (25/30/35/40/45+). *Why: shows the dose-response between speed and death directly.*

8. **Name-cleanup / dedup pass (do before publishing).** Resolve obvious artifacts: a generic "ALLEY" label appearing as a street (5 crashes), corridors split by inconsistent `TYPE` tags, and a decision on whether to merge or footnote directional splits (e.g. N/S Watkins). Keep North Parkway vs South Parkway **separate** — they are different streets. *Why: a journalist will hand-check the top of the ranking.*

9. **Interstate pedestrian fatalities as a separate category.** Pull the I-240 / I-40 crashes out of the arterial ranking and count/characterize them on their own. *Why: a categorically different (and especially lethal) situation that shouldn't dilute the arterial design story.*

---

## Section D — Future statistics (require data not yet collected)

- **Distance from each victim to the nearest safe crossing** — the eventual "killer stat." Needs the safe-crossing inventory (marked crosswalks, signals, HAWK/RRFB beacons) for the priority corridors.
- **Crossing-desert / gap analysis** — longest distance between safe crossings per corridor vs. the ~300 ft FHWA guideline. Needs the same inventory.
- **Equity / demographic overlay** — who bears the burden (income, race, vehicle access, transit dependence) by crash location. Needs census/ACS layers; ties to the Reconnecting Communities work.
- **Per-capita / exposure normalization** — deaths per resident or per walk-trip, for fair comparison across neighborhoods and against peer cities.

---

*End of document. Section A numbers are verified as of the data window above and will shift slightly as the rolling crash window advances; re-run the pipeline to refresh.*
