# Author watch lists

A named list of **people you already follow**, turned into new papers on this
machine. Distinct from [snowball watch](snowball.md#watch) (a keyword / DOI /
ORCID **crawl** that can hop) and from [`inbox watch`](commands.md) (a PDF drop
folder). Paperful does not schedule runs; call `authorwatch run` yourself
(launchd / cron if you want).

**Does not live-scrape** ResearchGate, LinkedIn, or Academia.edu. Save the follows
page as HTML or export CSV, then `import --file …`. Corpus-grounded
`suggest` ranks people already in your `-C` collection (not cloud recommendations).

## Success loop

```text
paperful authorwatch save ocean-people
paperful authorwatch add ocean-people --orcid 0000-0002-1825-0097
# or seed from the collection:
paperful authorwatch suggest ocean-people -C ocean/BBNJ --method mix --limit 15
paperful authorwatch accept ocean-people --id sug_…   # optional --seed-from YYYY-MM-DD
paperful authorwatch run ocean-people --backfill-from 2025-01-01
paperful authorwatch apply ocean-people -C Watch/Ocean --apply
paperful run -C Watch/Ocean
```

`--orcid` is the high-value path (OpenAlex may fill the display name). An
OpenAlex author id alone is also `ok` and pollable. `--name` alone stays
**unresolved** until `resolve` finds a unique OpenAlex author (ORCID **or**
OpenAlex author id). `--affiliation` is an optional host hint (for example
`stanford.edu`). Ambiguous names are **held** — `show` lists candidate iDs;
`add --orcid` to confirm. Name-only rows are never polled.

Discover (People) mirrors this: suggest method + limit, checkboxes + optional
seed date, member edit/remove, list delete, and saved social HTML/CSV upload.
See [gui.md](gui.md).

`doctor` ambers when a list has people and **zero** `ok` members. It does not
probe social sites.

`apply` does **not** need `[snowball] enabled`. It creates metadata parents
tagged `paperful-authorwatch` and `from-<list-name>`. PDFs stay `paperful run`.
Dry-run is the default; `--apply` needs a live write API (exit **2** when the
manager is closed). Mixed create failures exit **3**.

A poll `run` (after baseline, or with `--backfill-from`) talks to OpenAlex.
When the daily budget is spent it exits **2** with next steps (`OPENALEX_API_KEY`,
retry `authorwatch run`) — not a traceback. Cursor baseline still proposes 0
without polling.

## Run semantics

The first `authorwatch run` without `--backfill-from` records a **cursor
baseline** and proposes **0**. It does not download each author’s full oeuvre
(that would burn the OpenAlex allowance) and **does not open the library**.
Later runs, and any run with `--backfill-from`, ask OpenAlex for works and
fingerprint `exists` against the library.

Later runs use OpenAlex **index** time (`from_created_date`). That is not
publication date: an old paper newly indexed can appear; a paper published
yesterday but indexed last month will not.

`--backfill-from YYYY-MM-DD` uses **publication** date so the first useful day
can propose “their 2025 papers.” Works already in the library (`exists`) stay
out of the inbox. Caps: `--max-authors` (default 50) and `--per-author-limit`
(default 200).

No hop: this is **their papers**, not cited-by / references. For that, use
`paperful snowball orcid`.

## Suggest people from a collection

```text
paperful authorwatch suggest ocean-people -C ocean/BBNJ --method mix --limit 15
paperful authorwatch accept ocean-people --id sug_abcd1234 --seed-from 2025-01-01
```

Methods: `corpus` (frequency in `-C`), `most_cited` (OpenAlex `cited_by_count`
after resolving names), `coauthor` (shared works with list members or promoted
author pack), `mix` (blend corpus + cited). `suggest` **opens the library** for
`-C` (unlike a cursor-only `run`). Pending rows live in `suggestions.jsonl`
(`pollable` when ORCID or OpenAlex id is set). Accept moves checked ids onto
`people.jsonl` (`--id` repeatable, or `--all-pending`; `--dismiss-rest` marks
the rest dismissed). Optional `--seed-from` runs a backfill poll after accept.
Repeat `suggest` to append more candidates (skips people already on the list or
still pending). Spent OpenAlex budget exits **2** (same next steps as `run`).

## Import follows

```text
paperful authorwatch import ocean-people --file follows.csv --source csv
paperful authorwatch import ocean-people --file saved-rg.html --source rg
paperful authorwatch import ocean-people --file orcids.txt --source orcid
paperful authorwatch remove ocean-people --orcid 0000-0002-1825-0097
paperful authorwatch delete ocean-people --yes
```

CSV header: `name`, `orcid`, optional `affiliation`. JSON is a list of objects
or `{ "people": [...] }`.

`import --source rg|linkedin|academia` **without** `--file` exits 2 with the
export recipe. With `--file`, parses operator-saved HTML/CSV only.

## Ledger

`state/authorwatch/<name>/` (under `state/`, backup-excluded with the rest of
that tree):

| File | Role |
| --- | --- |
| `watch.json` | `paperful.authorwatch.v1` — `baseline_at`, `last_run_at` |
| `people.jsonl` | `paperful.authorwatch.person.v1` |
| `seen.json` | Identities already proposed or backfilled |
| `inbox.jsonl` | Proposed works |
| `applied.json` | Identities already created in the library |
| `suggestions.jsonl` | `paperful.authorwatch.suggestion.v1` — pending/accepted/dismissed |
| `briefing.md` | `authorwatch briefing` (markdown only; not a substitute for `apply`) |

## Local dogfood (operator)

Validate on a test collection without committing `state/` or pack edits. Example:
`suggest bbnj-test-voices -C ocean/BBNJ --method mix`; accept a few; optional
`--seed-from`; confirm OpenAlex budget exit **2** is actionable. See
[bbnj-author-lanes.md](bbnj-author-lanes.md) Phase 3.

## Versus snowball

| Job | Command |
| --- | --- |
| People I follow → new papers | `authorwatch` |
| One-shot oeuvre + hops | `snowball orcid` |
| Saved crawl profile, new hits | `snowball watch` |
| PDF drop folder | `inbox watch` |
