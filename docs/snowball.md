# Snowball

`paperful snowball` starts from one DOI and asks OpenAlex for neighbours:
papers that work cites (`referenced_works`) and papers that cite it
(`filter=cites`). Dry-run lists the DOIs. `--apply` creates missing library
items in one collection. It does not download PDFs — `paperful run` does that.

Not a scheduled crawler. Not a second reading UI. A DOI-file backfill
(`ingest-dois`) is still later.

```sh
uv run paperful snowball 10.1038/nature12373
uv run paperful snowball 10.1038/nature12373 --depth 2 --max-nodes 40
uv run paperful snowball 10.1038/nature12373 --direction references
uv run paperful snowball 10.1038/nature12373 -C snowball/nature --apply
uv run paperful run -C snowball/nature
```

The same flags work as `docker compose run --rm paperful snowball …`.

## Caps

Depth 2 multiplies quickly. Two caps stop that:

| Flag | Default | Effect |
| --- | --- | --- |
| `--depth` | `1` (max 3) | Hops from the seed. The seed itself is depth 0 |
| `--max-per-hop` | `25` | References kept from each work, and citing works kept from each work |
| `--max-nodes` | `80` | Works stored in the plan, including the seed |
| `--direction` | `both` | `references`, `citations`, or `both` |

Citing works are the most-cited first (`cited_by_count`). References stay in
OpenAlex list order, then the hop cap drops the rest. A truncated plan says
so. Works with no DOI are counted and not expanded.

`[snowball]` in `config.toml` sets the same defaults. CLI flags win.

## Apply

`--apply` needs `-C PATH`. The path is created when it is missing (EndNote
stores it as the import Label). Items already in the library, matched by
normalised DOI anywhere — not only in that collection — are left alone.
Paperful does not move them.

New items are tagged `openalex-snowball`. `extra` records the OpenAlex id,
the seed DOI, the depth, and `references` or `citations`. The seed is included
when it is not already in the library. `--no-include-seed` skips it.

Dry-run still tries to read the library so rows can say `in_library`. If the
manager is down, every DOI is listed as `new` and the command does not exit 2.
`--apply` does exit 2 without write support.

## Disk

`state/runs/<stamp>-snowball.json` is a `paperful.run_report.v1` file. It
does not replace `last-run.json`. `summary.proposed` is the new-DOI count.
`summary.created` is set only after `--apply`.

## Not this command

- PDF fetch, attach, or Sci-Hub
- A repeating job or a citation graph UI
- Creating items from a DOI list that is not this neighbourhood (`ingest-dois`)
