# Metrics: citation counts for items you hold

`paperful metrics` looks up how often papers **already in the library** are
cited, stores the numbers on disk, and shows them on Library. It does not
grow the collection. `--apply` writes or updates one tagged child note per
item so Zotero shows the count on the item pane. It does not write Extra or
parent tags.

OpenAlex is first. Crossref `is-referenced-by-count` is the fallback when
OpenAlex has no work or no count. Google Scholar is not a source. Semantic
Scholar and alphaXiv likes are reserved config names and ignored until
wired.

## CLI

```bash
uv run paperful metrics refresh -C BBNJ
uv run paperful metrics refresh -C BBNJ --apply
uv run paperful metrics refresh -C BBNJ --offline --apply
uv run paperful metrics refresh -C BBNJ --dry-run --limit 50
uv run paperful metrics refresh -C BBNJ --stale-days 7
uv run paperful metrics refresh -C BBNJ --format json
uv run paperful metrics show KEY
```

`refresh` needs `-C` or `--library` (same scope flags as `lint`: year, type,
`--limit`). It writes `state/metrics/cache.json` unless `--dry-run`. It
always writes a pack under `state/metrics/runs/<stamp>/pack.json` and a
`state/runs/` command report. `--offline` (or `PAPERFUL_OFFLINE=1`) never
contacts APIs; it only reads the cache. `--apply` creates or updates a child
note tagged `[metrics].note_tag` (default `paperful-metrics`). Re-runs update
that note instead of adding another. `--dry-run` and `--apply` conflict.
Unresolved and error rows get no note.

`show KEY` prints the cached row. Exit 1 if that key is missing. No network.

Identity: a DOI if the item has one; otherwise `10.48550/arxiv.{id}` from an
arXiv id. Title-and-year search is not used (too many false matches). Rows
without either id are `unresolved`.

`--stale-days` skips cache rows fetched that recently (default
`[metrics].stale_days` = 30). `0` always fetches.

`--format json` is `paperful.agent.json.v1`. MCP `metrics_show` is cache-only;
refresh stays CLI and Library so agents do not spend the OpenAlex budget.

## Workbench

Library, with a collection chip: a **Citations** column, sort by clicking
the header, and **Refresh citations**. Tick **Write notes in Zotero** on that
form to pass `--apply` (child notes, not Extra). MCP `metrics_show` stays
cache-only.

## Disk

| Path | Role |
| --- | --- |
| `state/metrics/cache.json` | `item_key` → latest counts (`paperful.metrics.cache.v1`) |
| `state/metrics/runs/<stamp>/pack.json` | One refresh (`paperful.metrics.pack.v1`) |

Per-item rows are `paperful.metrics.v1`: `cited_by_count`, `source`
(`openalex` / `crossref` / `unresolved` / `error`), `fetched_at`, optional
`likes` (unused in v1).

## Config

```toml
[metrics]
stale_days = 30
sources = ["openalex", "crossref"]
note_tag = "paperful-metrics"
```

`config check` warns if `sources` lists `google_scholar` or a reserved name
(`semantic_scholar`, `alphaxiv`).

## Later: Extra

A future Extra line such as `Citations (OpenAlex): 12` would let Zotero itself
sort on the field. That is still not implemented; the child note is the
in-Zotero surface. Cron refresh is `metrics refresh` on a timer you own; there
is no built-in scheduler.

See [commands](commands.md), [config](config.md).
