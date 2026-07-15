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

In-Memphis crashes: **1339** (179 fatal) = surface **1304** + limited-access **35**.

**Surface City vs TDOT — point estimate (corner crashes as city) + range upper bound:**

| | City | TDOT |
|---|---|---|
| ALL — point (1304) | 1037 (79.5%) | 267 (20.5%) |
| ALL — upper (+60 corner) | 977 (74.9%) | 327 (25.1%) |
| FATAL — point (165) | 118 (71.5%) | 47 (28.5%) |
| FATAL — upper (+5 corner) | 113 (68.5%) | 52 (31.5%) |

**Limited-access (TDOT)** — separate line: **35 crashes (14 fatal)** = Interstate 23 / ramp 8 / Sam Cooper 4.

**FINAL RANGE (lead with this):** surface **City 74.9%–79.5% / TDOT 20.5%–25.1%** (all crashes); **City 68.5%–71.5% / TDOT 28.5%–31.5%** (fatal). Plus limited-access 35 crashes (14 fatal), separate.

## Reconciliation

- surface 1304 + limited-access 35 = **1339** (expected 1339) ✓
- surface fatal 165 + limited-access fatal 14 = **179** (expected 179) ✓
- category changes vs seg-method (script 14): **1** City→TDOT (completeness force-rule), **4** City→limited-access (Sam Cooper). (Interstate-ramp crashes were only relabeled 'Interstate ramp (TDOT)' — same category, not a move.)
