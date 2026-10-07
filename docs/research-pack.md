# Research pack playbook

Narrative spine for a named `-C` topic build. Each verb stays honest: dry-run
first, `--apply` writes, PDFs come from `run` / handoff / inbox, not from
ingest. This is not `paperful all` and not a grey-lit playbook.

Seed greys and seed papers live in the collection before you start. After the
ledger is honest, optional `snowball watch` or `authorwatch` (including
`suggest -C` → `accept`), then the frontier digest (thin `briefing` is still
there), then `summarize` / `ask`.

## Sequence

```sh
# 1. Cited in PDFs, not in the library. Always dry-run.
# Writes state/refs-gaps/<stamp>-<scope>/ (paperful.refs_gap.pack.v1).
# Exit 0 with a pack; 1 unknown collection / bad flags; 2 no manager and no mirror.
docker compose run --rm paperful refs gap -C COLLECTION
# read state/refs-gaps/*/pack.md and dois.txt

# 2. Classify DOIs against the library fingerprint. Still dry-run.
# Exit 0 even when some rows are exists / unresolved / held.
docker compose run --rm paperful ingest-dois --from-pack state/refs-gaps/<stamp> -C COLLECTION

# 3. Create metadata parents. Provenance tags: --tag, [ingest].default_tags, from-<stem>.
docker compose run --rm paperful ingest-dois \
  --from-file state/refs-gaps/<stamp>/dois.txt \
  -C COLLECTION --apply --tag TOPIC

# 4. PDFs for items already in -C (including the new parents).
docker compose run --rm paperful run -C COLLECTION --dry-run
docker compose run --rm paperful run -C COLLECTION
# remaining misses: system browser, then drop PDFs into [inbox].dir
docker compose run --rm paperful gaps -C COLLECTION --list-missing --handoff walk
docker compose run --rm paperful inbox drain
# optional: ask authors instead of fetching remaining misses
docker compose run --rm paperful reachout -C COLLECTION --to reachout.csv

# 5. Hygiene after creates and attaches.
docker compose run --rm paperful dedupe -C COLLECTION
docker compose run --rm paperful dedupe -C COLLECTION --apply

# 6. Optional frontier (no scheduler; no silent creates).
docker compose run --rm paperful snowball watch run NAME --digest
docker compose run --rm paperful snowball watch digest NAME
docker compose run --rm paperful snowball digest --run-id <run-id>
```

Contributors: the same verbs with `uv run paperful …`.

## What to read on disk

| Path | Schema / role |
| --- | --- |
| `state/refs-gaps/<stamp>/pack.json` | `paperful.refs_gap.pack.v1` — cited, missing, `ingest-dois` vs skip |
| `state/refs-gaps/<stamp>/dois.txt` | Missing DOIs for ingest |
| `state/runs/<stamp>-ingest-dois.json` | Created / exists / unresolved / held |
| `state/last-run.json` | `paperful.run_report.v1` after `run` |
| `state/snowball/<run-id>/digest.md` | Frontier digest for that queue |
| `state/snowball/watches/<name>/digest.md` | Frontier digest for that watch |
| `state/snowball/<run-id>/briefing.md` | Thin queue export |
| `state/snowball/watches/<name>/briefing.md` | Thin watch inbox export |
| `state/reports/<scope>-authors.json` | `paperful.authors_report.v1` from `authors --apply` |
| `state/author-packs/<slug>.proposed.toml` | Field pack until `snowball packs promote` |

`summarize` and `ask` wait until `dedupe` and attach are boring. Harvest
collection acronyms (`paperful acronyms -C COLLECTION --apply`) before a
large `fix-metadata` recase if titles are ALL CAPS with corpus tokens
(BBNJ, FAO, OECD). For frequent creators and institutional authors in the
same slice, `paperful authors -C COLLECTION --apply` writes
`state/reports/<scope>-authors.json` and a proposed field author pack; then
`snowball packs promote` before relying on `author_site`. Optional CRM
lookup is [Twenty and SearXNG](snowball.md#twenty-and-searxng).

## Exits (same table as commands)

| Code | When |
| --- | --- |
| 0 | Success, including an empty dry-run or a classify with held rows |
| 1 | User error (unknown collection, missing `--from-file`, `--apply` without `-C` on a briefing or digest note) |
| 2 | Manager unreachable on a write, or no mirror yet on a read that needs the library |
| 3 | Partial batch (`inbox drain` mixed attach/errors; `run` mixed attach) |

## Out of this playbook

- Silent parent create from inbox (default stays DOI attach)
- Newsletter / Scholar-alert ingest
- Firefox extension
- `coverage` (briefing note vs collection) — later sibling of `refs gap`
