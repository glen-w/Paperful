---
orphan: true
---

# Watch: co-author network — Gjerde / BBNJ

**Date:** {{YYYY-MM-DD}}
**Result:** in progress | completed | blocked

## Plan

| Field | Value |
| --- | --- |
| ORCID | `0000-0001-9025-7632` |
| Phases | `bbnj` |
| Partition | `region` (or `none`) |
| Caps | `--max-works 200 --max-alters 80` |
| Artifacts | `state/network/<run-id>/` (gitignored) |

## Run

- Terminals: `<id>`
- cwd: repo root
- Started: {{LOCAL_START}}
- Finished: (when done)

```sh
PAPERFUL_E2E=1 uv run paperful network orcid 0000-0001-9025-7632 \
  --phases bbnj --partition region \
  --max-works 200 --max-alters 80
# GUI: Discover → People → Network (same ORCID)
```

Goal: graph.json + phase slices + ego metrics. OpenAlex budget spent is exit 2,
not an empty network.

## Result

- Run id:
- Nodes / edges:
- Advanced metrics (NetworkX): yes / degree-only
- Notes:
