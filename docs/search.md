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

## Discover Web

Discover → **Web** (default visible; hide with `[ui].web_search = "off"` in
Settings). Same Preview → apply honesty as Topic / People. Copy on the tab:
PDFs still need Wanted.

## Example (Gjerde / BBNJ)

```text
paperful search Gjerde IUCN BBNJ \
  --hosts iucn.org,dosi-project.org,undocs.org,highseasalliance.org,iisd.org \
  --max 20
```

Then `--apply -C "ocean/BBNJ"` (or the collection chip on Discover → Web) and
`paperful run` / Wanted for PDFs. See [BBNJ author lanes](bbnj-author-lanes.md).
