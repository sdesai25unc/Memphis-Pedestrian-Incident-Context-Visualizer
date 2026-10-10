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

In-Memphis crashes: **1435** (190 fatal) = surface **1398** + limited-access **37**.

**Surface City vs TDOT — point estimate (corner crashes as city) + range upper bound:**

| | City | TDOT |
|---|---|---|
| ALL — point (1398) | 1109 (79.3%) | 289 (20.7%) |
| ALL — upper (+64 corner) | 1045 (74.7%) | 353 (25.3%) |
| FATAL — point (176) | 123 (69.9%) | 53 (30.1%) |
| FATAL — upper (+5 corner) | 118 (67.0%) | 58 (33.0%) |

**Limited-access (TDOT)** — separate line: **37 crashes (14 fatal)** = Interstate 24 / ramp 9 / Sam Cooper 4.

**FINAL RANGE (lead with this):** surface **City 74.7%–79.3% / TDOT 20.7%–25.3%** (all crashes); **City 67.0%–69.9% / TDOT 30.1%–33.0%** (fatal). Plus limited-access 37 crashes (14 fatal), separate.

## Reconciliation

- surface 1398 + limited-access 37 = **1435** (expected 1435) ✓
- surface fatal 176 + limited-access fatal 14 = **190** (expected 190) ✓
- category changes vs seg-method (script 14): **1** City→TDOT (completeness force-rule), **4** City→limited-access (Sam Cooper). (Interstate-ramp crashes were only relabeled 'Interstate ramp (TDOT)' — same category, not a move.)
