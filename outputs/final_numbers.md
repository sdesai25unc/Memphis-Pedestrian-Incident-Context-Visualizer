# Final locked numbers — canonical classifier (script 17)

*Surface = City vs TDOT state route only. Limited-access (Interstate + Interstate ramp + Sam Cooper) is a separate line. Range upper bound credits corner crashes (City at a state-route junction) to the state route. Read-only; no page/docx rebuild.*

## Rulebook — segments per rule

| rule | segments |
|---|---|
| interstate_mainline | 577 |
| interstate_ramp | 997 |
| limited_access_override | 64 |
| state_route_overlap | 1695 |
| force_state_route_completeness | 11 |
| force_state_route_manual | 0 |
| city_residual | 51797 |

*Force-state-route fired on 11 segments (AUSTIN PEAY HWY, COVINGTON PIKE, E G E PATTERSON AVE, JACKSON AVE, STATE ROUTE 385 E, US HIGHWAY 64, WALNUT GROVE CT, WALNUT GROVE RD). Threshold FORCE_OV=0.2, name-guarded.*

## Final crash split

In-Memphis crashes: **1347** (180 fatal) = surface **1312** + limited-access **35**.

**Surface City vs TDOT — point estimate (corner crashes as city) + range upper bound:**

| | City | TDOT |
|---|---|---|
| ALL — point (1312) | 1042 (79.4%) | 270 (20.6%) |
| ALL — upper (+61 corner) | 981 (74.8%) | 331 (25.2%) |
| FATAL — point (166) | 119 (71.7%) | 47 (28.3%) |
| FATAL — upper (+5 corner) | 114 (68.7%) | 52 (31.3%) |

**Limited-access (TDOT)** — separate line: **35 crashes (14 fatal)** = Interstate 23 / ramp 8 / Sam Cooper 4.

**FINAL RANGE (lead with this):** surface **City 74.8%–79.4% / TDOT 20.6%–25.2%** (all crashes); **City 68.7%–71.7% / TDOT 28.3%–31.3%** (fatal). Plus limited-access 35 crashes (14 fatal), separate.

## Reconciliation

- surface 1312 + limited-access 35 = **1347** (expected 1347) ✓
- surface fatal 166 + limited-access fatal 14 = **180** (expected 180) ✓
- category changes vs seg-method (script 14): **1** City→TDOT (completeness force-rule), **4** City→limited-access (Sam Cooper). (Interstate-ramp crashes were only relabeled 'Interstate ramp (TDOT)' — same category, not a move.)
