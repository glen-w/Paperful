# Source routing and circuit breaker

With `source_routing = true` (the default), each item is sent only to sources
that look applicable from its metadata. The per-item log line `trying: …`
lists that lane, not the full `sources` list.

| Source | Tried when |
| --- | --- |
| `unpaywall` | DOI and `email` are set |
| `openalex` / `europepmc` / `scihub` | DOI |
| `arxiv` | arXiv id, `10.48550/arxiv.…` DOI, or a scholarly item type with a long title |
| `biorxiv` | `10.1101/…` DOI (including from a bioRxiv/medRxiv URL) |
| `semanticscholar` | DOI or arXiv id |
| `core` | DOI and `core_api_key` |
| `scholar` | DOI, or title at least 20 characters |
| `direct` | HTTP(S) URL that is not a resolver/aggregator/video host after playbook rewrite/synthesize, **or** Extra/title match from a `synthesize` playbook (e.g. UN symbol → undocs) |
| `ezproxy` | `ezproxy_base` plus a session (vault or cookie file), **and** a DOI or a URL on a [known publisher host](ezproxy.md#what-ezproxy-will-try) |
| `htmlpdf` | `webpage` / `blogPost` / `newspaperArticle` / `magazineArticle` / `forumPost` (or DOI-less `document` / `report`) with an HTTP(S) URL; needs optional Playwright — see [HTML→PDF](#htmlpdf-web-news-blogs) |

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

Independently, a **circuit breaker** skips a source for the rest of the run
after `circuit_breaker_threshold` (default 3) CAPTCHA or block-like errors
(`blocked`, `captcha`, `429`, `rate limit`, `sorry`). A Scholar CAPTCHA is a
miss for that source; the item continues through the rest of its lane. Only
an unsolved Sci-Hub robot check records the item as `captcha`. `--try-all`
does not disable the breaker.

## HTML→PDF (web, news, blogs)

Items typed as `webpage`, `blogPost`, `newspaperArticle`, `magazineArticle`, or
`forumPost` (and DOI-less `document` / `report` items with a URL) rarely have a
native PDF. After `direct` fails to find a PDF link on the page, the optional
`htmlpdf` source prints the page with Chromium. If you have run
`paperful session login`, it reuses that profile (so a campus login can apply);
otherwise it launches a fresh headless browser.

```sh
uv sync --extra htmlpdf
uv run playwright install chromium   # or: playwright install chrome
# ensure "htmlpdf" is in config sources (it is in the default list)
uv run paperful run --collection interesting --retry-failed
```

Without the extra, `htmlpdf` is skipped with a note to install
`paperful[htmlpdf]`. Soft paywall pages are treated as not found.
