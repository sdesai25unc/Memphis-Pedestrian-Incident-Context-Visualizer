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

In-Memphis crashes: **1403** (185 fatal) = surface **1366** + limited-access **37**.

**Surface City vs TDOT — point estimate (corner crashes as city) + range upper bound:**

| | City | TDOT |
|---|---|---|
| ALL — point (1366) | 1082 (79.2%) | 284 (20.8%) |
| ALL — upper (+64 corner) | 1018 (74.5%) | 348 (25.5%) |
| FATAL — point (171) | 121 (70.8%) | 50 (29.2%) |
| FATAL — upper (+5 corner) | 116 (67.8%) | 55 (32.2%) |

**Limited-access (TDOT)** — separate line: **37 crashes (14 fatal)** = Interstate 24 / ramp 9 / Sam Cooper 4.

**FINAL RANGE (lead with this):** surface **City 74.5%–79.2% / TDOT 20.8%–25.5%** (all crashes); **City 67.8%–70.8% / TDOT 29.2%–32.2%** (fatal). Plus limited-access 37 crashes (14 fatal), separate.

## Reconciliation

- surface 1366 + limited-access 37 = **1403** (expected 1403) ✓
- surface fatal 171 + limited-access fatal 14 = **185** (expected 185) ✓
- category changes vs seg-method (script 14): **1** City→TDOT (completeness force-rule), **4** City→limited-access (Sam Cooper). (Interstate-ramp crashes were only relabeled 'Interstate ramp (TDOT)' — same category, not a move.)
