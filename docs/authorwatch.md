# Author watch lists

A named list of **people you already follow**, turned into new papers on this
machine. Distinct from [snowball watch](snowball.md#watch) (a keyword / DOI /
ORCID **crawl** that can hop) and from [`inbox watch`](commands.md) (a PDF drop
folder). Paperful does not schedule runs; call `authorwatch run` yourself
(launchd / cron if you want).

**Does not scrape** ResearchGate, LinkedIn, or Academia.edu. Export a CSV if
that is where the names live.

## Success loop

```text
paperful authorwatch save ocean-people
paperful authorwatch add ocean-people --orcid 0000-0002-1825-0097
paperful authorwatch run ocean-people --backfill-from 2025-01-01
paperful authorwatch apply ocean-people -C Watch/Ocean --apply
paperful run -C Watch/Ocean
```

`--orcid` is the high-value path. `--name` alone stays **unresolved** until
`resolve` finds a unique OpenAlex author (ORCID or OpenAlex id). Ambiguous
names are **held** — `show` lists candidate iDs; add `--orcid` to confirm.
Name-only rows are never polled.

`apply` does **not** need `[snowball] enabled`. It creates metadata parents
only. PDFs stay `paperful run`.

## Run semantics

The first `authorwatch run` without `--backfill-from` records a **cursor
baseline** and proposes **0**. It does not download each author’s full oeuvre
(that would burn the OpenAlex allowance). Later runs ask OpenAlex for works
**indexed** after that cursor (`from_created_date`). That is not publication
date: an old paper newly indexed can appear; a paper published yesterday but
indexed last month will not.

`--backfill-from YYYY-MM-DD` uses **publication** date so the first useful day
can propose “their 2025 papers.” Works already in the library (`exists`) stay
out of the inbox. Caps: `--max-authors` (default 50) and `--per-author-limit`
(default 200).

`from_created_date` is OpenAlex index time. `--backfill-from` is publication
date.

No hop: this is **their papers**, not cited-by / references. For that, use
`paperful snowball orcid`.

## Import follows

```text
paperful authorwatch import ocean-people --file follows.csv --source csv
paperful authorwatch import ocean-people --file orcids.txt --source orcid
```

CSV header: `name`, `orcid`, optional `affiliation`. JSON is a list of objects
or `{ "people": [...] }`.

`import --source rg|linkedin|academia` **without** `--file` exits 2 with the
export recipe. HTML scrape is later and opt-in; it is not a `run` source.

## Ledger

`state/authorwatch/<name>/`:

| File | Role |
| --- | --- |
| `watch.json` | `paperful.authorwatch.v1` — `baseline_at`, `last_run_at` |
| `people.jsonl` | `paperful.authorwatch.person.v1` |
| `seen.json` | Identities already proposed or backfilled |
| `inbox.jsonl` | Proposed works |
| `applied.json` | Identities already created in the library |
| `briefing.md` | `authorwatch briefing` |

## Versus snowball

| Job | Command |
| --- | --- |
| People I follow → new papers | `authorwatch` |
| One-shot oeuvre + hops | `snowball orcid` |
| Saved crawl profile, new hits | `snowball watch` |
| PDF drop folder | `inbox watch` |
