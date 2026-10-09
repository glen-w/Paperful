# Source routing and circuit breaker

Free copies first, then campus, then only the sources that match the record.
The walkthrough is [How it works](how-it-works.md). This page is the routing
table and what happens when a site blocks.

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
| `core` | DOI and `core_api_key` (in default `sources`; skipped until the key is set. `doctor` reports whether it is set — green either way). Register at [core.ac.uk/services/api](https://core.ac.uk/services/api) |
| `scholar` | DOI, or title at least 20 characters (**opt-in** — not in default `sources`). Policy order runs it late, paired with `browser_agent` when that lane is on |
| `serpapi` | Same query as Scholar. **Opt-in:** `[serpapi].enabled` and env `SERPAPI_API_KEY`. Policy order after local Scholar / agent. Cap with `[serpapi].max_calls` / `--serpapi-max`. See [SerpApi](serpapi.md) |
| `direct` | HTTP(S) URL that is not a resolver/aggregator/video host after playbook rewrite/synthesize, **or** Extra/title match from a `synthesize` playbook (e.g. UN symbol → undocs) |
| `ezproxy` | `ezproxy_base` plus a session (vault or cookie file), **and** a DOI or a URL on a [known publisher host](ezproxy.md#what-ezproxy-will-try) |
| `htmlpdf` | `webpage` / `blogPost` / `newspaperArticle` / `magazineArticle` / `forumPost` (or DOI-less `document` / `report`) with an HTTP(S) URL; needs Playwright Chromium — see [HTML→PDF](#htmlpdf-web-news-blogs) |

Indexes can **find** a publisher PDF URL that then **403s** on httpx (bronze/hybrid Elsevier is the usual case). With a session profile, that GET is retried in Chromium: SSO hops, citation PDF links, and download controls are followed before the miss. Wins can become local playbooks (`paperful playbooks`); see [sessions](sessions.md). The same publisher host is not downloaded again by the next OA source.

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
campus session skips further EZProxy wraps; on a TTY, `run` offers re-login at
the next batch boundary and again after the fetch (`ezproxy_relogin`, default
on) so you can log in and retry only those items. That login browser is closed
before the report, and before `--handoff` opens tabs in your normal browser.
`--no-ezproxy-relogin` skips the pauses.

When an OA or `direct` lane **finds** a PDF URL but httpx gets an empty or
non-PDF body (soft bot-gate — common on some publisher `downloadpdf` links),
Paperful retries that URL in the vault browser even if the host is not on the
usual campus allowlist, enables `browser_agent` as a fallback, and records
`retryable` / `soft block` until recover has had a real try. If that still
fails, use the manual handoff loop:

```sh
uv run paperful gaps -C Inbox/Fitzpatrick --list-missing
uv run paperful gaps -C Inbox/Fitzpatrick --list-missing --handoff tabs
uv run paperful gaps -C Inbox/Fitzpatrick --list-missing --handoff watch
uv run paperful gaps -C Inbox/Fitzpatrick --list-missing --handoff walk
uv run paperful attach --item L7ISVTKE --file ~/Downloads/paper.pdf
uv run paperful inbox watch                    # long-running sidecar (whole library)
uv run paperful inbox drain                    # one-shot
uv run paperful inbox watch -C Inbox/Fitzpatrick  # optional narrow
```

`--handoff list` (default) only prints/exports. `tabs` opens each
`openable_url` in your default browser (confirms when more than 20). Opt-in
`[request].channels = "rg"` also opens **existing** ResearchGate publication
URLs (`author_request` hint) so you can click Request full-text yourself —
Paperful never automates that click (RG ToS) and never searches ResearchGate.
For contact-only (no Unpaywall, proxy, or Sci-Hub), use
`paperful reachout -C … --to reachout.csv` instead of `gaps`/`run`. That verb
never fetches; `--handoff tabs` opens RG URLs only. Emails come from the item,
then an optional contact cache
([Twenty and SearXNG](snowball.md#twenty-and-searxng)). Paperful does not send mail.
`watch`
opens those tabs, then polls `[inbox].dir` until Ctrl+C or idle timeout:
match by DOI extracted from the PDF, else FIFO against the openable-miss
queue from this handoff. `walk` opens one URL at a time, waits for you to
download into `[gaps].downloads_dir` (default `~/Downloads`), then ingests
via the same path as `attach --item --file`. Sparse one-page PDFs (few words)
are rejected there so an ethics stub does not attach by accident; denser
one-pagers (letters) attach because you already chose the file. Automated
`run` holds denser one-pagers for `attach --allow-short-pdf` — see
[research-ops](research-ops.md#wrong-work-pdfs).

Set `[inbox].dir` (for example `~/Documents/paperful_inbox`) and point the
browser download folder there (or Save As into it). `inbox watch` / `drain`
default to the **whole library** so one drop folder can serve every topic;
pass `-C` only to narrow the DOI index. Unmatched PDFs move to
`<inbox>/unmatched/`. This folder is **not** snowball’s
`state/snowball/watches/*/inbox.jsonl`. When `[inbox].watch_after_handoff` is
true (default) and `dir` is set, `--handoff tabs` also enters the watch loop
after opening tabs. Optional `[inbox].match` (title / OCR / LLM) and
`[inbox].create` (`create_gated` / unique-DOI `create_auto`) are in
[config](config.md) and [commands](commands.md). Config: `[gaps].handoff`, `[gaps].downloads_dir`,
`[inbox].*`. After a snowball `--fetch-pdfs` pass, the same handoff is
`gaps -C <collection> --list-missing --handoff …` (or `run --handoff` on a
retry of soft-blocked keys).

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

Journal and other DOI items stay off this lane unless `[htmlpdf].academic` is
`gated` or `auto` (`--htmlpdf` on one `run`). `gated` writes proposals under
`state/htmlpdf/proposals/`. Review them with `paperful htmlpdf proposals list`,
then `apply` or `reject`. `auto` attaches a snapshot-tier PDF only after the
landing checks in [config](config.md). The stamp is `snapshot:htmlpdf`.
