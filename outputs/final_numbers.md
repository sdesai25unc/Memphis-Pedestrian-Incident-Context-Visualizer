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

In-Memphis crashes: **1455** (191 fatal) = surface **1417** + limited-access **38**.

**Surface City vs TDOT — point estimate (corner crashes as city) + range upper bound:**

| | City | TDOT |
|---|---|---|
| ALL — point (1417) | 1122 (79.2%) | 295 (20.8%) |
| ALL — upper (+64 corner) | 1058 (74.7%) | 359 (25.3%) |
| FATAL — point (177) | 124 (70.1%) | 53 (29.9%) |
| FATAL — upper (+5 corner) | 119 (67.2%) | 58 (32.8%) |

**Limited-access (TDOT)** — separate line: **38 crashes (14 fatal)** = Interstate 24 / ramp 9 / Sam Cooper 5.

**FINAL RANGE (lead with this):** surface **City 74.7%–79.2% / TDOT 20.8%–25.3%** (all crashes); **City 67.2%–70.1% / TDOT 29.9%–32.8%** (fatal). Plus limited-access 38 crashes (14 fatal), separate.

## Reconciliation

- surface 1417 + limited-access 38 = **1455** (expected 1455) ✓
- surface fatal 177 + limited-access fatal 14 = **191** (expected 191) ✓
- category changes vs seg-method (script 14): **1** City→TDOT (completeness force-rule), **5** City→limited-access (Sam Cooper). (Interstate-ramp crashes were only relabeled 'Interstate ramp (TDOT)' — same category, not a move.)
