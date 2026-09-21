# Dedupe

`paperful dedupe` finds duplicate parent items in a collection (or the whole
library) and writes a review pack on disk. It does not trash anything unless
you pass `--apply`. It does not delete files under `out/`.

Monday literature ingest stays outside Paperful. After that ingest, the local
hygiene loop is:

```sh
uv run paperful dedupe -C BBNJ --dry-run
# read state/dedupe-packs/*.md
uv run paperful dedupe -C BBNJ --apply
uv run paperful gaps -C BBNJ
uv run paperful run -C BBNJ

# optional: same year / item-type filters as run
uv run paperful dedupe -C BBNJ --year-from 2023 --year-to 2026 -T journalArticle
uv run paperful gaps -C BBNJ -T journalArticle,report
```

`-C` accepts a path, a unique name, or a collection key (`2DBKZRPC`).
Subcollections are included. `--library` is the whole library.
`--year-from` / `--year-to` and `--type` / `-T` match [Commands — Scope
filters](commands.md#scope-filters).

## Phases

Default `--phase all` classifies both. `--apply` always does `high_doi` before
`medium_title_year`.

**high_doi.** Parents that share a normalised DOI (casefold, strip
`https://doi.org/`). One keep, the rest are trash candidates.

Keep rank, highest first:

1. stored / imported PDF
2. linked PDF URL only
3. richer metadata (a real title, then a date or year, then more creators)
4. older `dateAdded`, then item key

If any pair of titles in the group scores below 0.60 after HTML-unescape and
punctuation stripping, the group is **held** (`held_divergent_title`). Nothing
in that group is trashed. Review it by hand — the same DOI string is attached
to different works.

**medium_title_year.** Items that were not already in a multi-item DOI group.
Same normalised title and the same year. Blank titles, the `(untitled)`
placeholder, and missing years are skipped. These groups are marked
`needs_review`. `--apply` skips them unless you also pass `--apply-medium`.

## Flags

| Flag | Effect |
| --- | --- |
| `--dry-run` | Write the pack only. This is the default. Do not combine with `--apply`. |
| `--apply` | Trash `high_doi` extras. Needs Zotero 10+ (same gate as attach). |
| `--apply-medium` | Also trash title+year extras. |
| `--phase` | `high_doi`, `medium_title_year`, or `all`. |
| `--limit` / `-n` | Only the first N items in scope. |
| `--year-from` / `--year-to` | Inclusive publication-year range; undated items excluded. |
| `--type` / `-T` | Only these Zotero item types (repeatable or comma-separated). |
| `--json` | Pack paths and counts on stdout (`dedupe`), or the four gap counts (`gaps`). |

Pack JSON is `paperful.dedupe_pack.v1`. Both commands exit 2 if Zotero is
unreachable. `--apply` also needs the Zotero 10+ write API; without it, the
pack is still written and the command exits 2. `paperful doctor` stays amber
on the Write API check when trash, attach, and `fix-metadata --apply` cannot
run.

## Disk

- `state/dedupe-packs/<timestamp>-<scope>.json` — groups, keep, trash, reason, scores
- `state/dedupe-packs/<timestamp>-<scope>.md` — the same pack for reading
- `state/dedupe-applied.jsonl` — one line per trashed key, only after `--apply`

## Gaps

`paperful gaps -C BBNJ` (`--library`, `--year-from` / `--year-to`, `--type` / `-T`, `--json`) counts items with no stored PDF, a linked PDF URL only,
or no DOI. It does not fetch or edit. Use `run` for PDFs and `lint` for
identifiers.

## Not this command

Adding new items from a Crossref year query (`ingest-dois`) is later. So are
summary notes, moving items between collections, and Sci-Hub.
