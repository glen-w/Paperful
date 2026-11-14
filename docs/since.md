# Since: what changed since the last run

`paperful since` compares a collection to its last saved `run` report and
lists what is different. It is always a dry run. It downloads no PDF,
attaches nothing, creates no parents, and writes no Zotero note. Zotero may
be closed; the read comes from the mirror.

```bash
uv run paperful since -C BBNJ
uv run paperful since -C BBNJ --since 2026-11-01   # compare to an older run
uv run paperful since -C BBNJ --limit 50           # probe at most 50 misses and 50 snapshots
uv run paperful since -C BBNJ --format json
```

## What it reports

| Section | Row | Produced by | Compared to |
| --- | --- | --- | --- |
| Holdings that changed meaning | Retraction, withdrawal, or expression of concern on a library item | The `screen` status lookup (Crossref and OpenAlex), report-only | The newest `screen` report |
| | Preprint that now has a version of record | `versions`, no merge | The newest `versions` pack |
| | URL or linked PDF that is now `hard_dead` or `paywall_html` | `urls check`, no rewrite | The newest `urls` report |
| | Snapshot-only PDF that an open-access lane can now replace | The metadata lanes of `run` | The stored snapshot |
| | Parent created by `keepup apply` that still has no PDF | The `keepup` applied ledger | The mirror |
| Misses that healed | An item the last `run` could not get, still without a PDF, that an open-access lane now names | The metadata lanes of `run` | The newest `run` report for the scope |

Every row names the verb that produced it and what it was compared to: the
run's witness id (first 12 characters of its config hash), or its date when
the report has no witness.

A healed miss is a row whose last `run` status was `not_found`, or whose miss
was `no_oa`, `paywalled`, or `fetch_failed`. Rows are ranked by cite count
(from the newest `refs gap` pack) times miss severity, the same score the
handoff list uses. `--limit` probes only the top of that ranking and the
pack says how many were skipped.

`since` does not fetch what it finds. Open Wanted, or run `paperful run` on
the collection.

## What it does not report

- **Nothing without a prior observation.** With no earlier `run` report for
  the scope, `since` exits 0, says healed misses were not compared, and
  still reports retractions.
- **Campus access.** Only the metadata lanes are probed: `unpaywall`,
  `openalex`, `arxiv`, `biorxiv`, `europepmc`, `semanticscholar`, `core`,
  `openaire`, and only those in your configured sources. EZProxy, HTML
  snapshot, browser, and Sci-Hub lanes are never called. A lane may read a
  publisher landing page to find the PDF link; it does not request the PDF.
- **URLs the last `urls check` never saw.** With no earlier `urls` report
  for the scope, URL health is skipped and the pack says so. A URL is
  re-probed only when the last report could open it.

## Cost

Each run re-checks retraction status for every DOI in scope, bypassing the
`screen` status cache, because that cache does not expire. It also looks up
a published version for each preprint, re-probes URLs the last `urls`
report could open, and makes one or more metadata requests per earlier miss
and per snapshot-only PDF. `--limit` caps the last two.

## Output

- `state/since/<stamp>-<scope>/since.json` (`paperful.since.v1`) and
  `since.md`. An empty pack is a successful run and prints "Nothing changed."
- `state/runs/<stamp>-since.json`, a command report that joins an open
  [pack](commands.md) trail. It does not replace `state/last-run.json`.

A holdings row is reported once. The next `since` reads the previous pack
and does not repeat it. A healed miss stays listed until a `run` fetches it.
