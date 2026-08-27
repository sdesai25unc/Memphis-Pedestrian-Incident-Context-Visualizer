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

In-Memphis crashes: **1381** (184 fatal) = surface **1344** + limited-access **37**.

**Surface City vs TDOT — point estimate (corner crashes as city) + range upper bound:**

| | City | TDOT |
|---|---|---|
| ALL — point (1344) | 1068 (79.5%) | 276 (20.5%) |
| ALL — upper (+63 corner) | 1005 (74.8%) | 339 (25.2%) |
| FATAL — point (170) | 121 (71.2%) | 49 (28.8%) |
| FATAL — upper (+5 corner) | 116 (68.2%) | 54 (31.8%) |

**Limited-access (TDOT)** — separate line: **37 crashes (14 fatal)** = Interstate 24 / ramp 9 / Sam Cooper 4.

**FINAL RANGE (lead with this):** surface **City 74.8%–79.5% / TDOT 20.5%–25.2%** (all crashes); **City 68.2%–71.2% / TDOT 28.8%–31.8%** (fatal). Plus limited-access 37 crashes (14 fatal), separate.

## Reconciliation

- surface 1344 + limited-access 37 = **1381** (expected 1381) ✓
- surface fatal 170 + limited-access fatal 14 = **184** (expected 184) ✓
- category changes vs seg-method (script 14): **1** City→TDOT (completeness force-rule), **4** City→limited-access (Sam Cooper). (Interstate-ramp crashes were only relabeled 'Interstate ramp (TDOT)' — same category, not a move.)
