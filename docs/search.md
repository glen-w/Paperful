# Web grey search

Discover grey literature (IUCN, undocs, PrepCom, author PDFs) from a query.
This is **not** a Google or Scholar HTML scraper. Paperful calls a
[SearXNG](https://docs.searxng.org/) JSON API you configure
(`[searxng].base_url` or `SEARXNG_BASE_URL`). It is **not** a `paperful run`
source: apply creates metadata parents; PDFs still come from Wanted /
`paperful run` so grey playbooks stay in charge of the fetch.

Distinct from [snowball search](snowball.md) (OpenAlex keywords) and from grey
**playbooks** (URL already on the item → PDF). Search finds URLs; playbooks
fetch.

## CLI

```text
paperful search Gjerde "high seas" OR BBNJ \
  --hosts iucn.org,dosi-project.org,undocs.org,highseasalliance.org,iisd.org \
  --max 30 --format json
paperful search Gjerde IUCN --apply -C "Gjerde tribute/grey"
paperful search --run-id <id>
paperful search --list
paperful search watch save iucn --query "Gjerde IUCN" --hosts iucn.org --interval-days 7
paperful search watch run iucn          # first time: baseline, inbox empty
paperful search watch run iucn --force  # skip the interval wait
paperful search watch apply iucn -C "Gjerde tribute/grey"          # dry-run
paperful search watch apply iucn -C "Gjerde tribute/grey" --apply  # metadata parents
paperful search watch show iucn
paperful search watch list
```

`--filetype pdf` (default) appends `filetype:pdf` to the query. Pass
`--filetype none` to skip. `--hosts` is an allowlist and is also injected as
`site:` ORs. Dry-run prints a table (`new` / `exists` / `blocked`). `--apply -C`
creates `report` parents (URL + Extra provenance `web:searxng` or
`grey:<playbook>`). `--out-dir` writes the `paperful.search.v1` pack only; it
does not imply `--apply`.

Exit **2** when SearXNG is unset (`paperful doctor` shows the same amber row).

## Ranking

Blocked hosts (Scholar, ResearchGate, Wikipedia, doi.org, …) and large
publisher platforms are dropped. Remaining hits prefer `.pdf` / playbook
rewrites, then HTML landings on known grey hosts. Optional HEAD/GET probe
(`--no-probe` to skip) distinguishes PDF from HTML. Empty SearXNG / HTTP 429
is a **partial** run, not a crash.

## Store

`state/search/<run-id>/` (`paperful.search.v1`; gitignored with `state/`):

| File | Contents |
| --- | --- |
| `meta.json` | Query, filetype, hosts, engine host (not a secret-bearing URL), caps |
| `hits.jsonl` | Ranked rows (`url`, `title`, `score`, `host`, `playbook`, `kind`) |
| `candidates.jsonl` | Post-filter / probe |
| `summary.json` | hits, kept, exists, blocked, new |

Cache JSON lives under `state/search/cache/` (not the critique SearXNG folder).

## Watch

`paperful search watch` is a pull-only URL poll. First `run` baselines every
hit into `seen.json` and writes nothing to the inbox. Later runs propose
unseen URLs (not DOIs — grey reports often have none). `--interval-days`
(default 7, `0` = every run) uses the same due-date helper as
[`keepup`](keepup.md); Paperful **does not** schedule watches — cron
`search watch run`. `--force` ignores the interval. `watch apply -C` is
dry-run unless `--apply` (metadata parents only; PDFs stay Wanted /
`paperful run`). Distinct from [`snowball watch`](snowball.md#watch)
(OpenAlex works) and [`authorwatch`](authorwatch.md) (people).

Ledger under `state/search/watches/<name>/` (`paperful.search.watch.v1`):

| File | Role |
| --- | --- |
| `watch.json` | Query, hosts, filetype, `interval_days`, `baseline_at`, `last_run_at` |
| `seen.json` | URL identities already recorded |
| `inbox.jsonl` | Append-only proposed hits |
| `applied.json` | URLs already created by `watch apply --apply` |

## Discover Web

Discover → **Web** (default visible; hide with `[ui].web_search = "off"` in
Settings). Same Preview → apply honesty as Topic / People. Copy on the tab:
PDFs still need Wanted. The tab can **Save watch** / **Run** a saved grey
watch (inbox on disk). Apply from the CLI.

## Example (Gjerde / BBNJ)

```text
paperful search Gjerde IUCN BBNJ \
  --hosts iucn.org,dosi-project.org,undocs.org,highseasalliance.org,iisd.org \
  --max 20
```

Then `--apply -C "ocean/BBNJ"` (or the collection chip on Discover → Web) and
`paperful run` / Wanted for PDFs. See [BBNJ author lanes](bbnj-author-lanes.md).
