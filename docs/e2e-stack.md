# E2E stack (topic + effort)

Opt-in **all-in** end-to-end against a throwaway Zotero collection `e2e/<topic>`.
You choose the **keyword seed** and an **effort** tier; every tier runs the same
phase stack (snowball → ORCID → fetch → hygiene → authors → Twenty → reachout →
handoff).

This is **not** in default CI. Sci-Hub stays off. Paperful never sends mail.

## Effort tiers

| Effort | Snowball | Typical new queue rows | Wall time (rough) |
| --- | --- | --- | --- |
| `low` | depth 1, cap 25 | ~25 | tens of minutes |
| `med` | depth 1, cap 250 | low hundreds | 1–3 h |
| `high` | depth 2, cap 3000 | up to ~3k | many hours |

Years default to **previous calendar year → current year**. Override with
`--year-from` / `--year-to`.

## Honesty

| Rule | Detail |
| --- | --- |
| Opt-in | `PAPERFUL_E2E=1` or `scripts/e2e_stack.py --force` |
| Isolated writes | Only `-C e2e/<topic>` (created on first snowball `--gate auto`) |
| Soft-skip | Twenty, SearXNG, headed tabs, Scholar/EZProxy when not ready |
| No Sci-Hub | Not in the harness; see [scihub](scihub.md) if you opt in yourself |
| PDFs | Snowball `--gate auto` and ORCID hop use `--fetch-pdfs full`; `run_fetch` uses `--try-all` (+ browser-agent when ready). Optional `--dry-run-search` prelude does not fetch |
| Watch | Every live run is babysat; see [Babysitting](#babysitting-a-live-run) |

## Preconditions

Same as the NBA dogfood run: Zotero 10+ write API, Unpaywall email, prefer
`OPENALEX_API_KEY`, optional LLM + browser-agent extras, optional Twenty /
SearXNG, optional `PAPERFUL_E2E_TABS=1`.

## One command

```sh
# Examples
PAPERFUL_E2E=1 uv run python scripts/e2e_stack.py --topic "NBA" --effort low
PAPERFUL_E2E=1 uv run python scripts/e2e_stack.py --topic "BBNJ" --effort high \
  --year-from 2020 --year-to 2026

# Topic labels the collection; --query can be a richer OpenAlex seed
PAPERFUL_E2E=1 uv run python scripts/e2e_stack.py --topic eco-surveys --effort med \
  --year-from 2020 --year-to 2026 \
  --query '(survey AND ("climate policy" OR "climate policies")) OR (survey AND degrowth AND (policy OR policies)) OR (survey AND ("ecosocial policy" OR "ecosocial policies" OR "eco-social policy" OR "eco-social policies"))'

# Legacy alias (NBA + low effort)
make e2e-nba
```

Child `paperful` phases stream stdout/stderr live (`PYTHONUNBUFFERED=1`). With
`--format json`, snowball and `run` keep human progress on stderr under
`PAPERFUL_E2E=1` so the harness CLI stays readable.

Resume after a failed phase:

```sh
PAPERFUL_E2E=1 uv run python scripts/e2e_stack.py --topic NBA --effort low \
  --from-phase run_fetch --run-id <id>
```

Machine witness: `state/e2e/<run-id>/report.json` and `REPORT.md` (legacy runs
may still live under `state/e2e-nba/<run-id>/`).

## Phases

Same ordered stack as [E2E NBA](e2e-nba.md#phases) (doctor through report). Caps
and collection come from the resolved plan (`topic`, `effort`, years).

## Babysitting a live run

Use Cursor **`/e2e-watch`** (or copy
[`docs/templates/e2e-watch-assessment.md`](templates/e2e-watch-assessment.md)
into gitignored `assessments/`):

1. Fill topic, effort, command, terminal path, start time.
2. Poll until the harness exits (progress = new phase lines in `watch.log`).
3. Hang quiet window: **10 minutes** (longer for `high` or browser-agent).
4. On failure: backup → minimal fix → `uv run pytest -q tests/test_e2e_nba.py` →
   resume with `--from-phase` / `--run-id` (same `--topic` / `--effort` as the run).
5. Finalize assessment: `completed` or `blocked`, duration, `git diff --stat`.

Harness log: `state/e2e/<run-id>/watch.log`. While a phase runs, tail
`state/e2e/<run-id>/<phase>.stderr.txt` (e.g. `snowball_search.stderr.txt`).
Snowball also writes under `state/snowball/<run-id>/` (`candidates.jsonl`,
`summary.json`) — list newest with `ls -lt state/snowball | head`.

## Hermetic tests

```sh
uv run pytest -q tests/test_e2e_nba.py
```

## Related

- [E2E NBA](e2e-nba.md) — first dogfood (`NBA`, effort `low`)
- [Workflows](workflows.md)
