# Source routing and circuit breaker

With `source_routing = true` (the default), each item is sent only to sources
that look applicable from its metadata. The per-item log line `trying: …`
lists that lane, not the full `sources` list.

| Source | Tried when |
| --- | --- |
| `unpaywall` | DOI and `email` are set |
| `openalex` / `europepmc` / `openaire` | DOI |
| `scihub` | DOI, and either undated or year ≤ 2021 (Sci-Hub largely stopped ingesting after ~2021; see [Sci-Hub](scihub.md#coverage-cutoff-2021)) |
| `arxiv` | arXiv id, `10.48550/arxiv.…` DOI, or a scholarly item type with a long title |
| `biorxiv` | `10.1101/…` DOI (including from a bioRxiv/medRxiv URL) |
| `semanticscholar` | DOI or arXiv id |
| `core` | DOI and `core_api_key` |
| `scholar` | DOI, or title at least 20 characters (**opt-in** — not in default `sources`) |
| `direct` | HTTP(S) URL that is not a resolver/aggregator/video host after playbook rewrite/synthesize, **or** Extra/title match from a `synthesize` playbook (e.g. UN symbol → undocs) |
| `ezproxy` | `ezproxy_base` plus a session (vault or cookie file), **and** a DOI or a URL on a [known publisher host](ezproxy.md#what-ezproxy-will-try) |
| `htmlpdf` | `webpage` / `blogPost` / `newspaperArticle` / `magazineArticle` / `forumPost` (or DOI-less `document` / `report`) with an HTTP(S) URL; needs Playwright Chromium — see [HTML→PDF](#htmlpdf-web-news-blogs) |

Indexes can **find** a publisher PDF URL that then **403s** on httpx (bronze/hybrid Elsevier is the usual case). With a session profile, that GET is retried in Chromium and wrapped in EZProxy when configured; the same publisher host is not downloaded again by the next OA source.

Before sources run, **identifier preparation** verifies an existing library DOI
against Crossref/OpenAlex (title similarity ≥ `crossref_min_score` → `ok`).
A library DOI below `doi_suspect_score` is `suspect` and can be **swapped in
memory** when a title match scores ≥ `crossref_min_score`; the original stays
in the manifest as `library_doi`. API failure or a mid-range match is `unknown`
and **does not swap**. Missing DOIs are filled from URL/meta, PubMed ID
converter (PMID in Extra), then Crossref / OpenAlex / Semantic Scholar
(skipped for web/blog/forum types). `run` never writes bibliographic fields —
use `paperful lint` then `paperful fix-metadata --apply`.

`--try-all` (or `source_routing = false`) tries every configured source regardless
of those filters. Use that when library records have missing or wrong
identifiers. EZProxy still refuses YouTube, Zotero, FAO, and other
non-publisher URLs: wrapping them in the campus proxy cannot produce a
subscription PDF.

When `run` is scoped with `-T` / `--type`, sources that can never apply to those
item types are dropped from the run list entirely (e.g. `htmlpdf` on a
`journalArticle`-only scope), including under `--try-all`. Likewise, when
`--year-from` is after Sci-Hub's ~2021 coverage, `scihub` is dropped from the
run list even if you opted in.

Independently, a **circuit breaker** pauses a source after `circuit_breaker_threshold`
(default 3) CAPTCHA or block-like errors (`blocked`, `captcha`, `sorry`). A 429
does not open it; the HTTP client already waits on `Retry-After`. After the
pause (25 items) one later item is tried. A clean result closes the circuit;
another block pauses it again. A Scholar CAPTCHA is a miss for that source;
the item continues through the rest of its lane. Only an unsolved Sci-Hub
robot check records the item as `captcha`. `--try-all` does not disable the
breaker.

Items every applicable source misses are `not_found` with reason `closed`
(skipped next run unless `--retry-failed`). Items that missed a lane because
the circuit was paused, or because the EZProxy session expired, are
`retryable` and are picked up on the next `run` without that flag. An expired
campus session stops further EZProxy calls for the rest of that run.

## HTML→PDF (web, news, blogs)

Items typed as `webpage`, `blogPost`, `newspaperArticle`, `magazineArticle`, or
`forumPost` (and DOI-less `document` / `report` items with a URL) rarely have a
native PDF. After `direct` fails to find a PDF link on the page, the `htmlpdf`
source prints the page with Chromium. If you have run `paperful session login`,
it reuses that profile (so a campus login can apply); otherwise it launches a
fresh headless browser. Playwright is a core dependency; Chromium installs on
the first `session login` (or: `uv run playwright install chromium`).

```sh
# ensure "htmlpdf" is in config sources (it is in the default list)
uv run paperful run --collection interesting --retry-failed
```

Soft paywall pages are treated as not found.
