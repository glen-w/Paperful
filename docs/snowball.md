# Snowball

**Status:** keyword search, DOI / ORCID / collection seeds, refs and cited-by,
depth up to 5 under caps, gates `dry-run` / `approve-batch` / `auto`, and
`--fetch-pdfs` are implemented. Config honors `dedupe_scope`, `tag_prefix`,
`types`, `oa_only`, and venue include/exclude. `snowball profile save` writes
seeds and knobs only. `approve-each`, multi-seed overlap ranking, hybrid
profiles, and `[llm]` query refine are still later. Phases live in
[ROADMAP](ROADMAP.md#snowball).

Snowball grows a library outward from a keyword, a DOI, a person, or an
existing collection. It proposes works, then creates items under an explicit
gate. [`run`](commands.md) fills PDFs for items that already exist. With
`fetch_pdfs`, snowball calls that same `run` in the same process, limited to
the keys it just created, so one command can turn a keyword into a collection
with PDFs.

```text
paperful snowball search "area based management tools" --year-from 2018
paperful snowball doi 10.1038/s41586-021-03819-2 --depth 2 --direction both
paperful snowball orcid 0000-0002-9162-9618
paperful snowball collection "Inbox/Seeds" --direction refs
paperful snowball run --profile doi-refs-gated
paperful snowball apply <run-id> -C "Inbox/Snowball"
paperful snowball search "high seas EIA" --gate auto --fetch-pdfs -C "Inbox/Snowball"
```

`search`, `doi`, `orcid`, and `collection` are seeds under one verb. There is
no separate top-level `harvest`, `crawl`, or `discover`.

## Snowball and run

| Job | Command | What you are doing |
| --- | --- | --- |
| Build | `paperful snowball …` | Find works and, if the gate says so, create parents |
| Fill | `paperful run` | PDFs and attach for items already in the library |

A dry-run ends with “candidates ready”. A writing gate without `fetch_pdfs`
ends with “items created (metadata only)”. Downloaded and attached appear in
the summary only after `fetch_pdfs` has actually run `run`.

A snowball profile is a named job in `profiles/`. `paperful run` and
`paperful all` refuse it. Fetch profiles stay fetch profiles.

## Seeds

| Seed | What it collects | Default depth |
| --- | --- | --- |
| Keyword | OpenAlex title/abstract search | **0** — the hit list. Depth 1+ expands those hits and must be set explicitly. A global `depth = 1` does not expand every keyword hit |
| DOI | The work’s neighbours (`referenced_works` and/or works that cite it) | **1**, direction `refs` by default. Use `--direction cites` or `both` for cited-by |
| ORCID | That person’s works (ORCID public API, filled by OpenAlex author filter), then the same expander | **1** |
| Collection | DOIs already in the seed collection path, then the same expander | **1**. `-C` is the write target (defaults to the seed path) |

`expand = cited_authors` (every paper by every cited author) stays off. It
is a later, capped switch.

## Gates

The gate is a config value. The default for a new user is `dry-run`.

| Gate | Library writes | When |
| --- | --- | --- |
| `dry-run` | None | Always safe. `fetch_pdfs` is ignored |
| `approve-batch` | Only `keep = true` rows | `snowball apply <run-id>`. A second apply skips DOIs already created |
| `approve-each` | Each yes | Short lists. Not the path the docs teach first |
| `auto` | Every `status = new` row under the caps | A named profile, after you have dry-run that job once |

A writing gate requires a target collection and stops before the crawl if it
is missing. Paperful may create that collection path. It does not invent a
silent default collection. `auto` is not a scheduler.

Dedupe runs before create: normalized DOI against `dedupe_scope` (`library`
by default, or `collection`, or `none` logged loudly), then the existing
title+year fingerprint. Only `status = new` rows can become parents.

## One-shot PDFs

`fetch_pdfs` defaults to false. Set it on the command or in a profile when
the goal is a library, not a review file:

```text
paperful snowball search "BBNJ EIA" --gate auto --fetch-pdfs -C "Inbox/Snowball"
```

After create, snowball calls the existing `run` pipeline on those new item
keys. The rest of the library is out of scope. Sci-Hub and the other `run`
opt-ins stay as configured for `run`; snowball does not turn them on. If
attach fails, the parent remains, the report counts `attach_deferred`, and
the usual attach message is printed. The [quiet mirror](quiet-mirror.md) is
unchanged.

Example profile `keyword-library`: `gate = auto`, `fetch_pdfs = true`,
`target_collection` set. `keyword-scout` is the dry-run twin.
`doi-refs-gated` is approve-batch. `orcid-ego-auto` creates metadata only.

## Stop rules

| Knob | Default | Meaning |
| --- | --- | --- |
| `depth` | 0 for keyword, 1 for DOI / ORCID / collection | Hops from the seed. Soft ceiling 5; `max_candidates` and `per_hop_limit` still bind |
| `direction` | `refs` | `refs`, `cites`, or `both` |
| `max_candidates` | 200 | Stops after this many `new` + `exists` rows |
| `per_hop_limit` | 50 | Fan-out per seed work per hop, not a global pool |
| `year_from` / `year_to` | unset | Drop candidates outside the window |
| `types` | journal-article-shaped | OpenAlex / Zotero types |
| `oa_only` | false | Metadata filter only. It does not change the PDF chain |
| `min_seed_citations` | 0 | Skip cited-by expansion when the seed is below this count |
| `languages`, `venue_include`, `venue_exclude` | unset | Applied when the source has the field |

A seed that fails to resolve is `status = error`. Other seeds continue. The
process exits non-zero if any seed failed, using the existing exit ladder
(`2` for config / doctor).

## Candidate record

Each run writes `state/snowball/<run-id>/candidates.jsonl` and `summary.json`.
The summary counts requests, HTTP 429s, retries, and rows by status, backend,
and hop.

Schema `paperful.snowball.candidate.v1`:

| Field | Contents |
| --- | --- |
| `schema`, `run_id` | Version and run id |
| `seed` | `{type, value}` — keyword, doi, orcid, or openalex |
| `hop` | Integer. Search hits are 0. References of a seed are 1 |
| `direction` | `search`, `refs`, `cites`, or `author_work` |
| `ids` | Normalized doi, openalex, s2, pmid, orcid, when known |
| `biblio` | Title, year, authors, venue, type, optional OA url |
| `why` | Short reason, for example `ref of 10.xxxx/yyyy` |
| `status` | `new`, `exists`, `filtered`, or `error` |
| `exists_match` | When `exists`: `item_key` and `doi` or `title_year` |
| `provenance` | Backend, endpoint, `retrieved_at` |
| `gate` | The gate for this run |
| `score` | Optional rank. The summary states the formula |

The dry-run table shows title, year, DOI, why, in library, hop/direction,
and backend, with `new` rows first. Created items are tagged
`paperful-snowball` and `paperful-snowball:<backend>`. A child note holds the
seed, direction, hop, why, run id, and schema version. API keys and the
mailto address never go in that note.

## Config

Precedence matches [run profiles](config.md#run-configs-profiles): built-in
default, then `[snowball]` in `config.toml`, then `profiles/<name>.toml`,
then flags on the command.

```toml
[snowball]
enabled = false          # doctor and the CLI refuse snowball until true
depth = 1                # keyword runs still default to depth 0
direction = "refs"
max_candidates = 200
per_hop_limit = 50
gate = "dry-run"         # dry-run | approve-each | approve-batch | auto
target_collection = ""
dedupe_scope = "library" # library | collection | none
fetch_pdfs = false
tag_prefix = "paperful-snowball"
note_provenance = true
backends = ["openalex", "crossref", "semanticscholar", "orcid"]
```

`enabled = false` until you opt in, the same posture as `[llm]`. `doctor`
reports that flag, whether keys are present, and whether a backend answers.
A missing optional key warns. It does not abort the other backends.

`email` at the top of `config.toml` is the mailto for OpenAlex and Crossref.
`OPENALEX_API_KEY` and `SEMANTIC_SCHOLAR_API_KEY` come from the environment.
`snowball profile save` writes seeds and knobs only, after a successful
dry-run, or with `--force`. It refuses to store a key.

Backends resolve in order and emit each work once, keyed by DOI: OpenAlex
first, Crossref fills empty metadata fields, Semantic Scholar when a key is
set, ORCID for the person’s own work list. OpenAlex wins when it and Crossref
disagree on a field that both filled.

`snowball run --profile NAME` prints that profile’s one-line description
before any request.

## Where the crawl comes from

The personal site already does this hop for a people graph, not for Zotero:

| Site | Snowball |
| --- | --- |
| `processing/library/citations.py` | One-hop `referenced_works` and `filter=cites:` |
| `_data/openalex.yml` | `[snowball]` plus `profiles/*.toml` |
| `processing/library/s2_citations.py` | Optional Semantic Scholar fill, disk cache under `state/` |
| `processing/library/work_identity.py` | DOI, ORCID, and title normalization, aligned with `dedupe` |
| No Zotero writes | `create_parent` and `ensure_collection_path` |

Leave on the site: the people-graph JSON, the hard-coded ego slug, Jekyll
outputs, and `scholar_citations.py`.

## What to reuse elsewhere

OpenAlex is the graph (search, author, `referenced_works`, `cites:`). The
ORCID public API is the person’s own works; those lists are often incomplete,
so OpenAlex expands them. Semantic Scholar references and citations fill gaps
when a key is set. Crossref, already used to verify DOIs, fills metadata
gaps. It is not the forward-citation graph.

Adjacent tools, and the piece worth copying:

| Tool | Copy | Leave there |
| --- | --- | --- |
| [findpapers](https://github.com/jonatasgrosman/findpapers), [opencite](https://github.com/neuromechanist/opencite) | `direction`, `depth`, per-hop cap, dedupe before emit | The package, and any Scopus / Web of Science / IEEE requirement |
| [paperscraper](https://github.com/jannisborn/paperscraper) | — | DOI-list PDFs when you have no Zotero. See [comparison](comparison.md) |
| [litsearch](https://pypi.org/project/litsearch/), [lit-review-mcp](https://github.com/Bethww/lit-review-mcp), [CoLRev](https://colrev-environment.github.io/colrev/) | Flag ideas | The review project, the report, the screener |
| [Citation Gecko](https://github.com/CitationGecko/gecko-react) | Later: rank works cited by many seeds, or citing many seeds | The network UI |
| [zotero-snowball](https://github.com/socratic-irony/zotero-snowball), [Citegeist](https://github.com/phdemotions/zotero-citegeist) | — | In-Zotero one-hop dialogs |
| [pyalex](https://github.com/J535D165/pyalex) | — | A second HTTP client. Snowball extends the client paperful already uses for OpenAlex (mailto, sleep, backoff) |

ResearchRabbit, Litmaps, Connected Papers, Inciteful, Elicit, Consensus,
Scite, and Lens.org stay outside. A later “question → seed DOIs” assist can
sit behind `[llm]` as suggestions on the queue. Google Scholar stays the
existing PDF lane. It is not a snowball source. Screening a RIS file stays
with ASReview. Created items keep clean creators, DOI, and date so Better
BibTeX citekeys still make sense. Snowball does not depend on that plugin.

## Out of this lane

- A hosted discovery service, a force-directed graph, or a second OpenAlex browser
- Cron, or a snowball step inside `paperful all`
- A TUI or local web reviewer
- Sci-Hub or Scholar as ways to discover works
- Pulling every publication of every cited author, until an explicit capped switch exists

## Related docs

- [ROADMAP](ROADMAP.md#snowball) — phases
- [comparison](comparison.md) — paperscraper, findpapers, in-Zotero plugins
- [config](config.md#run-configs-profiles) — profile precedence this lane reuses
- [commands](commands.md) — `run`, which `fetch_pdfs` calls
