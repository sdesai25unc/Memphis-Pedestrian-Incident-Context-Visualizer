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

In-Memphis crashes: **1294** (175 fatal) = surface **1259** + limited-access **35**.

**Surface City vs TDOT — point estimate (corner crashes as city) + range upper bound:**

| | City | TDOT |
|---|---|---|
| ALL — point (1259) | 1003 (79.7%) | 256 (20.3%) |
| ALL — upper (+58 corner) | 945 (75.1%) | 314 (24.9%) |
| FATAL — point (161) | 116 (72.0%) | 45 (28.0%) |
| FATAL — upper (+5 corner) | 111 (68.9%) | 50 (31.1%) |

**Limited-access (TDOT)** — separate line: **35 crashes (14 fatal)** = Interstate 23 / ramp 8 / Sam Cooper 4.

**FINAL RANGE (lead with this):** surface **City 75.1%–79.7% / TDOT 20.3%–24.9%** (all crashes); **City 68.9%–72.0% / TDOT 28.0%–31.1%** (fatal). Plus limited-access 35 crashes (14 fatal), separate.

## Reconciliation

- surface 1259 + limited-access 35 = **1294** (expected 1294) ✓
- surface fatal 161 + limited-access fatal 14 = **175** (expected 175) ✓
- category changes vs seg-method (script 14): **1** City→TDOT (completeness force-rule), **4** City→limited-access (Sam Cooper). (Interstate-ramp crashes were only relabeled 'Interstate ramp (TDOT)' — same category, not a move.)
