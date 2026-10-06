# E2E all-in: NBA (reference dogfood)

First shipped dogfood for the generic [E2E stack](e2e-stack.md): topic `NBA`,
effort `low`, collection `e2e/NBA`. For any other topic or tier, use
`scripts/e2e_stack.py` or `/e2e-watch`.

This is **not** in default CI. Sci-Hub stays off. Paperful never sends mail.

## Honesty

| Rule | Detail |
| --- | --- |
| Opt-in | `PAPERFUL_E2E=1` or `scripts/e2e_stack.py --force` |
| Isolated writes | Only `-C e2e/NBA` (created on first snowball `--gate auto`) |
| Soft-skip | Twenty, SearXNG, headed tabs, Scholar/EZProxy when not ready |
| No Sci-Hub | Not in the harness; see [scihub](scihub.md) if you opt in yourself |
| Watch | Every live run is babysat; see [Babysitting](#babysitting-a-live-run) |

## Preconditions

1. Zotero 10+ local write API; `paperful doctor` (exit 0 or 1).
2. Real Unpaywall `email` in `config.toml`.
3. Prefer `OPENALEX_API_KEY` (shared no-key pool is easy to exhaust).
4. For summarize + browser-agent: `[llm].enabled`,  
   `uv sync --extra llm --extra browser-agent` (Python ≥ 3.11), Ollama up.
5. Optional: `[twenty].enabled` + `TWENTY_API_KEY` + `base_url`;  
   `[searxng].base_url` or `SEARXNG_BASE_URL` (JSON API).
6. Optional headed tabs: `PAPERFUL_E2E_TABS=1`.

## Profiles

| File | Kind | Role |
| --- | --- | --- |
| [`profiles/e2e-nba-search.toml`](../profiles/e2e-nba-search.toml) | snowball | Same caps as harness (`gate = auto`, `fetch_pdfs = full`) |
| [`profiles/e2e-nba-run.toml`](../profiles/e2e-nba-run.toml) | run | `all --profile e2e-nba-run` slice on `e2e/NBA` |

## One command

```sh
make e2e-nba
# or:
PAPERFUL_E2E=1 uv run python scripts/e2e_stack.py --topic NBA --effort low
```

Resume after a failed phase (keep the same `--topic` and `--effort`):

```sh
PAPERFUL_E2E=1 uv run python scripts/e2e_stack.py --topic NBA --effort low \
  --from-phase run_fetch --run-id <id>
```

Machine witness: `state/e2e/<run-id>/report.json` and `REPORT.md` (older runs may
be under `state/e2e-nba/`).

## Phases

| # | Phase | What runs | Required |
| --- | --- | --- | --- |
| 0 | `doctor` | `paperful doctor --no-guide` | yes (exit 2 fails) |
| 1 | `snowball_search` | `snowball search NBA … --gate auto --fetch-pdfs full -C e2e/NBA` (optional `--dry-run-search` prelude) | yes |
| 2 | `snowball_orcid` | ORCIDs from `candidates.jsonl` → `snowball orcid … --author-site-preflight` | yes if ≥1 ORCID, else skip |
| 3 | `run_fetch` | `run -C e2e/NBA --try-all --retry-failed --upgrade-linked --browser-agent` | yes |
| 4 | `hygiene` | `all … --steps lint,fix-metadata,summarize --apply` | yes (summarize soft if LLM off) |
| 5 | `authors_pack` | `authors --apply` → `snowball packs promote e2e-nba` → dry-run | soft |
| 6 | `twenty` | `twenty lookup/sync --apply --limit 5` | soft |
| 7 | `reachout` | `reachout -C e2e/NBA --lookup --to …/reachout.csv` | yes (CSV may have 0 data rows) |
| 8 | `handoff_tabs` | `gaps --list-missing --handoff list` (or `tabs` if `PAPERFUL_E2E_TABS=1`) | yes |
| 9 | `report` | `report.json` + `REPORT.md` | yes |

### Lane matrix (fetch)

Default sources from config (`unpaywall` … `htmlpdf`), then late
`author_site` (when a pack/contact exists), optional Scholar (session),
`browser_agent` when LLM + extra are ready. **No Sci-Hub.**

SearXNG is only used inside snowball `--author-site-preflight`, not as a
`run` source. Twenty feeds listings/emails; it never sends mail.

## Pass signals

- ≥1 snowball candidate for `NBA` in 2025–2026
- Parents under `e2e/NBA` after gate auto
- After fetch: at least one attach **or** explicit miss rows (not a silent empty run)
- `reachout.csv` exists
- `report.json` has `"ok": true` for required phases
- Soft-skips logged when Twenty / SearX / tabs / LLM are off

## Babysitting a live run

Do not fire-and-forget. Use Cursor `/watch` (or the same discipline by hand):

1. Use `/e2e-watch` or copy [`templates/e2e-watch-assessment.md`](templates/e2e-watch-assessment.md)
   into `assessments/YYYY-MM-DD-e2e-<topic>-watch.md` (gitignored).
2. Record command, terminal path, start time.
3. Poll the terminal. Progress (new phase lines) is not a hang.
4. Hang quiet window: **10 minutes** (longer for one browser-agent item or a
   long summarize batch).
5. On failure: diagnose → backup once before first code edit → minimal fix →
   focused test (`uv run pytest -q tests/test_e2e_nba.py` or narrower) →
   resume with `--from-phase` / `--run-id`.
6. On hang: kill only that PID; then the failure path.
7. Finalize the assessment: `completed` or `blocked`, duration, `git diff --stat`.

Harness log: `state/e2e/<run-id>/watch.log`.  
Assessment file: human/agent narrative. Keep both.

## Hermetic tests

```sh
uv run pytest -q tests/test_e2e_nba.py
```

Live marker (skipped unless env set):

```sh
PAPERFUL_E2E=1 uv run pytest -q tests/test_e2e_nba.py -m e2e_live
```

## Manual copy-paste (without the harness)

```sh
SCOPE=(-C e2e/NBA --year-from 2025 --year-to 2026)

uv run paperful snowball search NBA --year-from 2025 --year-to 2026 \
  --max-candidates 12 --depth 1 --gate dry-run

uv run paperful snowball search NBA --year-from 2025 --year-to 2026 \
  --max-candidates 12 --depth 1 --gate auto --fetch-pdfs full -C e2e/NBA

# then ORCID seeds from state/snowball/<run>/candidates.jsonl author_records
uv run paperful run "${SCOPE[@]}" --try-all --retry-failed --upgrade-linked --browser-agent
uv run paperful all "${SCOPE[@]}" --steps lint,fix-metadata,summarize --apply
uv run paperful reachout -C e2e/NBA --lookup --to reachout-nba.csv
uv run paperful gaps -C e2e/NBA --list-missing --handoff list
```

## Cleanup

Review `e2e/NBA` in Zotero. Trash or keep. Author pack `e2e-nba` under
`state/author-packs/` can stay for reruns. Do not point production BBNJ
profiles at this collection.

## Related

- [Workflows](workflows.md) deep pass and reachout
- [Snowball](snowball.md) / [Twenty and SearXNG](snowball.md#twenty-and-searxng)
- [BBNJ author lanes](bbnj-author-lanes.md) (separate dogfood, `ocean/BBNJ-test`)
- [LLM](llm.md) / [browser-agent models](browser-agent-models.md)
