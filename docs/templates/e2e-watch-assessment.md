---
orphan: true
---

# Watch: E2E stack — {{TOPIC}} ({{EFFORT}})

**Date:** {{YYYY-MM-DD}}
**Result:** in progress | completed | blocked

## Plan

| Field | Value |
| --- | --- |
| Topic | `{{TOPIC}}` |
| Effort | `{{EFFORT}}` (`low` ~25 rows, `med` ~250, `high` 2-hop ~3k) |
| Collection | `e2e/{{TOPIC}}` (or `-C` override) |
| Years | `{{YEAR_FROM}}`–`{{YEAR_TO}}` (default: previous → current calendar year) |

## Run

- Terminals: `<id>` (first pass), `<id>` (resume if any)
- cwd: repo root
- Mode: start + watch
- Started watching: {{LOCAL_START}}
- Finished: (when done)

```sh
PAPERFUL_E2E=1 uv run python scripts/e2e_stack.py \
  --topic "{{TOPIC}}" \
  --effort {{EFFORT}} \
  {{YEAR_FLAGS}}
# resume example:
PAPERFUL_E2E=1 uv run python scripts/e2e_stack.py \
  --topic "{{TOPIC}}" --effort {{EFFORT}} \
  --from-phase <phase> --run-id <run-id>
```

Goal: watch until the harness exits. On failure or hang, fix, prove with a focused
test, then continue with `--from-phase` / `--run-id` (same topic and effort).

## Log

- Seeded assessment; starting live run.
- Run id: `<run-id>` from harness stdout / `state/e2e/<run-id>/`.
- (append phase milestones, incidents, fixes)

## Incidents

| Kind | Detail |
| --- | --- |
| Failure | |
| Hang | |
| Kill | |

## Fixes

1. (minimal code changes + pytest proof)

## Artifacts

- `state/e2e/<run-id>/report.json` / `REPORT.md`
- `state/e2e/<run-id>/reachout.csv`
- Zotero `-C e2e/{{TOPIC}}`
