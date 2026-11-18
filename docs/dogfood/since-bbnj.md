---
dogfood_gate: active
started: 2026-11-14
collections: [BBNJ, Hoops]
target_weeks: 4
target_verdicts: 8
---

# `since` dogfood — BBNJ and Hoops

Four-week habit check for [`paperful since`](../since.md) on **two** real collections.
**16 Nov 2026:** full `paperful run` watch started for BBNJ (in progress), then Hoops —
to establish run witnesses for healed-miss comparisons.

Record each weekly `since` after the library may have moved (optional mid-week `run` only
when you refill). **Operator schedule:** Nightshift [`paperful-since`](../../../nightshift/jobs/paperful-since/)
(Friday 23:45) runs `paperful since` on `ocean/BBNJ` and `hoops` and writes packs only —
you still open each pack and fill **Verdict**.

**Loop (each collection, each week):** `paperful since -C <name>` → open
`state/since/<stamp>/since.md` → fill a row in the matching table.

**Verdicts:** `actionable` (you acted or queued work), `dismissed` (read and
closed), `noise` (no signal). Leave verdict empty until the pack is opened.

**Exit:** four non-empty verdicts **per collection** → set `dogfood_gate: complete` in
the front matter and append **Decision**. If three or more packs on a collection are
noise, narrow the diff before a workbench block (see [ROADMAP](../ROADMAP.md#after-17-habit)).

## BBNJ

| Week | Date | Stamp (`state/since/…`) | Witness | Holdings rows | Healed rows | Verdict | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | | | | | | | | `run -C BBNJ` watch 2026-11-16 establishes witness |
| 2 | | | | | | | |
| 3 | | | | | | | |
| 4 | | | | | | | |

## Hoops

| Week | Date | Stamp (`state/since/…`) | Witness | Holdings rows | Healed rows | Verdict | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | | | | | | | | `run -C Hoops` after BBNJ run completes |
| 2 | | | | | | | |
| 3 | | | | | | | |
| 4 | | | | | | | |

## Decision

*(After week 4 on both collections: workbench Since block go / no-go, or CLI-only stop.)*