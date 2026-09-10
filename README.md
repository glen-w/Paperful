<h1 align="center">
  <img src="docs/logo.png" alt="paperful" width="280">
</h1>

<p align="center">
  <strong>Fill the gaps in your Zotero library.</strong><br>
  Fetch the PDFs your items are missing. Keep them in a folder tree that
  mirrors your collections. Attach them back into Zotero.
</p>

Open access first (Unpaywall, OpenAlex, arXiv, bioRxiv/medRxiv, Europe PMC,
Semantic Scholar, CORE, optional Google Scholar, the item's own URL). Campus
**EZProxy** when you have a subscription. **Sci-Hub is opt-in and off by
default** — it occupies a legal grey zone in some jurisdictions; see
[Sci-Hub](#sci-hub).

By default each item only hits sources that match its metadata (DOI, arXiv
id, URL, …); `--try-all` disables that. Sci-Hub coverage after ~2021 is thin;
recent paywalled papers are best fetched via EZProxy when your library has a
subscription.

Work happens **on disk** (`out/`, `state/`). Zotero is a library adapter:
read the catalogue in, write PDFs and metadata patches back. Mendeley is
reserved in config for a later adapter. Not sure if this is the right
tool? [How paperful compares](docs/comparison.md).

## Quick start

**You need**

- Zotero running, with the local API enabled:
  Settings → Advanced → *Allow other applications on this computer to communicate with Zotero*.
- Zotero 10+ to attach PDFs into the library. On Zotero 7–9 the tool still
  downloads to disk; attach later with `paperful attach` once upgraded.
- [`uv`](https://docs.astral.sh/uv/) (Python 3.10+).
- Optional: a university/library account and EZProxy URL for publisher PDFs
  (ScienceDirect, Springer, Wiley, Taylor & Francis, …).
- Optional: a browser session for Google Scholar (`paperful scholar`) if you
  keep `scholar` enabled.
- Optional: [Poppler](https://poppler.freedesktop.org/) `pdftotext` on `PATH`
  for PDF-text DOI extraction (`pypdf` is the fallback; `doctor` ambers if
  Poppler is missing).

```sh
git clone https://github.com/glen-w/Paperful.git
cd Paperful
uv sync
cp config.example.toml config.toml   # then set email, out_dir, optional ezproxy_base
uv run paperful doctor               # Zotero, paths, cookies — green / amber / red
uv run paperful collections          # sanity check: tree with "No PDF" counts
```

Then pick a collection and go:

```sh
uv run paperful run --collection interesting --dry-run   # see what would be fetched
uv run paperful run --collection interesting                   # fetch + attach
```

If you use campus EZProxy, finish [Campus EZProxy](#campus-ezproxy) before a
big run. If you keep `scholar` in `sources`, log in once with
`paperful session login scholar` — see [Browser sessions](#browser-sessions-scholar-ezproxy-publishers).

---

The rest of this README is reference: commands, configuration, output,
source routing, EZProxy, Scholar, and Sci-Hub.

## Commands

```sh
# fetch to disk only
uv run paperful run --collection interesting --no-attach

# several collections, or the whole library (resumable; Ctrl-C any time, rerun to continue)
uv run paperful run -C BBNJ -C AO
uv run paperful run --library

# attach previously downloaded PDFs
uv run paperful attach

# what happened
uv run paperful report
uv run paperful report --last-run      # latest run summary only
uv run paperful report --json          # agent-friendly (manifest + last run)
uv run paperful report --not-found
uv run paperful report --status error

# policy-sensitive runs (OA + campus EZProxy; no Scholar / Sci-Hub)
uv run paperful run -C BBNJ --preset eoi --dry-run

# items with only a linked PDF URL in Zotero are skipped by default
uv run paperful run --library --upgrade-linked

# retry items marked not_found / no_identifier (e.g. after EZProxy login)
uv run paperful run --library --retry-failed
uv run paperful run --collection BBNJ --retry-failed
uv run paperful run --collection BBNJ --try-all   # ignore source_routing when metadata is unreliable

# restrict / reorder sources for one run, or cap the number of items processed
uv run paperful run -C hoops --sources unpaywall,openalex,ezproxy
uv run paperful run --library --limit 50

# Sci-Hub is off unless you opt in (config `sources`, or this flag)
uv run paperful run --library --scihub

# session (optional)
uv run paperful session login ezproxy   # headed Chromium, campus SSO
uv run paperful session login scholar    # same profile; solve Scholar CAPTCHA here
uv run paperful session status
uv run paperful ezproxy --no-open       # probe the EZProxy session
uv run paperful scholar --no-open       # probe Scholar
uv run paperful mirrors                  # which Sci-Hub mirrors are up (Sci-Hub itself stays off)

# identifiers vs PDFs (read-only); metadata writes are a separate step
uv run paperful lint --library --json
uv run paperful lint -C BBNJ --strict             # exit 1 if any finding
uv run paperful fix-metadata --library            # dry-run → state/metadata-patches.jsonl
uv run paperful fix-metadata --library --apply    # write DOI/title/date/venue into Zotero 10+
uv run paperful fix-metadata --library --apply --overwrite   # also replace title/date/venue
```

| Command | Purpose |
| --- | --- |
| `doctor` | Environment check (Zotero, paths, email, sessions, pdftotext) |
| `run` | Find and download missing PDFs (`--dry-run`, `--preset eoi`, `--upgrade-linked`, `--try-all`, `--retry-failed`, `--sources`, `--scihub`, `--limit`). Never rewrites bibliographic fields. |
| `lint` | Read-only identifier / PDF-DOI findings (`--json`, `--strict`, `--limit`). Codes: `missing_doi`, `suspect_doi`, `swappable_doi`, `pmid_no_doi`, `pdf_doi_mismatch`, `no_identifier` |
| `fix-metadata` | Propose patches on disk; `--apply` writes them to the library (`--overwrite` for title/date/venue). Whitelist: `doi`, `title`, `date`, `publicationTitle` |
| `collections` | Collection tree with “No PDF” counts |
| `report` | Manifest summary + latest run report (`--last-run`, `--json`, `--not-found`, `--status`) |
| `attach` | Attach already-downloaded PDFs into Zotero |
| `session` | Local Chromium vault: `login scholar|ezproxy`, `status`, `export` |
| `ezproxy` | Wrapper: headed login (or Netscape fallback) / `--no-open` probe |
| `scholar` | Wrapper: headed login (or Netscape fallback) / `--no-open` probe |
| `mirrors` | Ping configured Sci-Hub mirrors |
| `version` | Print the package version |

Collections can be given as a path (`BBNJ/not undermine`), a unique name, or
a key. Subcollections are always included. Items in several selected
collections are written once and hard-linked into the other folders.

## Configuration (`config.toml`)

Copy `config.example.toml` to `config.toml` and edit locally; the example file
is tracked in git, personal config is not.

Looked up as `--config PATH`, then `./config.toml`, then the project folder's
`config.toml`, then `~/.config/paperful/config.toml`. Relative paths resolve
against the config file's folder.

**Grey literature and no-DOI items** — Unpaywall and most DOI sources cannot
resolve PrepCom papers, many DOALOS/UN docs, or undocs without a DOI. `direct`
rewrites undocs/daccess URLs (and UN symbols in Extra/title) to a PDF link;
then `htmlpdf` can print DOI-less `document` / `report` pages. Otherwise the
manifest records `no_identifier`. See [docs/architecture.md](docs/architecture.md).

| Key | Default | Meaning |
| --- | --- | --- |
| `email` | `""` | Sent as `mailto` to Unpaywall/OpenAlex/Crossref and as `email` to NCBI ID Converter (required by Unpaywall) |
| `manager` | `zotero` | Library adapter. `mendeley` is reserved (not implemented yet) |
| `out_dir` / `state_dir` | `out` / `state` | PDF tree; manifest, patches, PDF cache, run reports, and write key |
| `sources` | `unpaywall` → `openalex` → `arxiv` → `biorxiv` → `europepmc` → `semanticscholar` → `core` → `scholar` → `direct` → `ezproxy` → `htmlpdf` | Source order; `--sources` overrides per run. `scihub` is **not** included unless you opt in. `core` is skipped until `core_api_key` is set |
| `verify_doi` | `true` | Check library DOIs against Crossref/OpenAlex before fetching; may swap DOI **in memory** for that run. `false` leaves an existing DOI as `doi_verified=unknown` and does not swap |
| `doi_suspect_score` | `0.70` | Title similarity below this marks a library DOI as suspect (eligible for in-memory swap). API failure is `unknown` and **keeps** the original DOI |
| `core_api_key` | `""` | CORE API bearer token; empty skips the `core` source |
| `ezproxy_base` | `""` (disabled) | Campus proxy prefix ending in `url=` — see [Campus EZProxy](#campus-ezproxy) |
| `ezproxy_cookies` | `state/ezproxy-cookies.txt` | Compat Netscape dump after `session login ezproxy` |
| `scholar_cookies` | `state/scholar-cookies.txt` | Compat Netscape dump after `session login scholar` |
| `scihub_mirrors` | built-in list | Hostnames tried in order |
| `delay_scihub_s` | `[3, 8]` | Random pause (seconds) before each Sci-Hub / EZProxy / htmlpdf page fetch |
| `concurrency_oa` | `4` | Parallel workers for open-access sources (Scholar, EZProxy, htmlpdf, and Sci-Hub are serial) |
| `min_pdf_bytes` | `10000` | Smaller downloads are rejected as error pages |
| `crossref_min_score` | `0.90` | Title-similarity threshold for accepting a title→DOI match (Crossref, then OpenAlex, then Semantic Scholar) |
| `mirror_failures_before_skip` | `3` | Network failures before a Sci-Hub mirror is skipped for the run |
| `source_routing` | `true` | Skip sources that look inapplicable from item metadata; use `--try-all` to override per run |
| `circuit_breaker_threshold` | `3` | Block-like failures (CAPTCHA, rate limits) before a source is skipped for the rest of the run |
| `attach` | `true` | Attach into Zotero after download (`--no-attach` overrides) |
| `app_name` | `paperful` | Name shown in Zotero's authorisation dialog |
| `user_agent` | Chrome-like string | HTTP `User-Agent` for source and download requests |

Leave `ezproxy_base` empty (or remove `ezproxy` from `sources`) if you do not
use a library proxy. Remove `scholar` from `sources` if Google Scholar
CAPTCHAs add noise even after `session login scholar`. Sci-Hub is off until
you add `"scihub"` to `sources` or pass `--scihub` — see [Sci-Hub](#sci-hub).
Set `source_routing = false` (or pass `--try-all`) when Zotero fields are
untrustworthy and you want every configured source tried anyway.

## Output

- `out/<collection path>/Author - Year - Title.pdf`
- `state/manifest.jsonl` — one line per item attempt; the latest line per item
  key wins. Statuses: `ok` (on disk), `attached` (on disk + in Zotero),
  `not_found`, `no_identifier`, `captcha`, `error`, `attach_failed`. `ok` /
  `attached` are never retried; `not_found` / `no_identifier` only with
  `--retry-failed`; the rest are retried on every run. Extra fields:
  `library_doi` (DOI as stored in the manager), `doi` (DOI used for this
  attempt), `doi_verified` (`ok` / `suspect` / `swapped` / `unknown` /
  `missing`), `pdf_doi` (extracted from the file on disk after a successful
  download).
- `state/metadata-patches.jsonl` — proposed bibliographic patches from
  `fix-metadata` (dry-run and `--apply` both append here first).
- `state/pdf-cache/` — PDFs exported from the manager so lint can read text
  on disk (`pdftotext`, then `pypdf`).
- `state/last-run.json` — latest auditable `run` report (summary + per-item
  outcomes). Historical copies land in `state/runs/<timestamp>-<command>.json`
  (`run`, or `fix-metadata` after `--apply`). `fix-metadata --apply` does
  not overwrite `last-run.json`.
- `state/sessions/` — Chromium profile (`chromium/`) plus `meta.json` (no
  passwords). Gitignored; `chmod 700`. Netscape dumps also land here and as
  `ezproxy-cookies.txt` / `scholar-cookies.txt` for httpx.
- `state/zotero-local-api-key.json` — the Zotero write key if you chose
  "Always Allow".

---

## Source routing and circuit breaker

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
| `direct` | HTTP(S) URL that is not a resolver/aggregator/video host, **or** a UN document symbol in Extra/title (undocs / daccess) |
| `ezproxy` | `ezproxy_base` plus a session (vault or cookie file), **and** a DOI or a URL on a [known publisher host](#what-ezproxy-will-try) |
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

---

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

---

## Campus EZProxy

Publisher sites (Elsevier ScienceDirect, Springer Nature, Wiley, JSTOR, …)
normally require a subscription. If your university or research library
offers **EZProxy** (or a similar “login?url=” redirector), paperful can
download those PDFs **using your existing library entitlement**.

### What EZProxy will try

The campus proxy is only used where a library stanza can actually return a PDF:

| Item has… | EZProxy? |
| --- | --- |
| A DOI | **Yes** — target is `https://doi.org/{doi}` (the usual path). The Zotero URL is ignored, so a webinar URL next to a real DOI is fine. |
| A URL on a known publisher host, and no DOI | **Yes** — the URL is wrapped in `ezproxy_base`. Subdomains match (`link.springer.com` counts as Springer). |
| Only a YouTube / `youtu.be` / Vimeo / X / Facebook / Zotero / Scholar link | **No** |
| Only an NGO, UN, or government page (FAO, High Seas Alliance, G77, …) | **No** — public sites are not in EZProxy databases. `direct` may still try them if the URL looks like a PDF. |

Known publisher hosts (suffix match) include ScienceDirect / Elsevier, Springer
Nature, Wiley, JSTOR, Taylor & Francis, Sage, Oxford, Cambridge, IEEE, ACM,
*Science*, Cell, Lancet, NEJM, BMJ, PNAS, Annual Reviews, IOP, APS, RSC, ACS,
AIP, Frontiers, MDPI, PLOS, Hindawi, De Gruyter, Brill, Emerald, SSRN, Ingenta,
ProQuest, EBSCO, OECD / UN iLibrary, Project MUSE, HeinOnline, Westlaw,
LexisNexis, Cairn, Érudit, OpenEdition, Persée, Dalloz, JAMA, World Scientific,
MIT Press Direct, Chicago journals, Cochrane, Ovid, and BioOne.

The canonical list is `_EZPROXY_PUBLISHER_HOSTS` in `paperful/routing.py`.
`--try-all` does not wrap YouTube or other non-publisher URLs.

The tool never asks for or stores your institutional password. You log in
once in headed Chromium (`paperful session login ezproxy`); `run` reuses that
vault and exported cookies until the campus session expires.

### 1. Find your library’s EZProxy base URL

Ask your library website for “EZProxy”, “off-campus access”, or “proxy
bookmarklet”, or try the pattern many OCLC sites use:

```text
https://<your-prefix>.idm.oclc.org/login?url=
```

Examples (illustrative only — use **your** institution’s URL):

| Institution (example) | Typical `ezproxy_base` |
| --- | --- |
| Sciences Po | `https://scpo.idm.oclc.org/login?url=` |
| Other OCLC EZProxy | `https://<prefix>.idm.oclc.org/login?url=` |

The value must be the prefix that, when a target URL is appended, starts
login. A quick check in the browser: open

```text
https://<your-prefix>.idm.oclc.org/login?url=https://www.sciencedirect.com/
```

You should land on your university’s single sign-on (CAS, Shibboleth,
Microsoft, etc.). After login you should reach ScienceDirect (or an error from
the publisher if your library does not subscribe — the login itself still
proves the proxy URL is correct).

Some libraries use a hostname-rewriting proxy without `login?url=` (e.g.
`www-sciencedirect-com.proxy.example.edu`). This tool expects the
**`login?url=`** form. If your library only offers rewriting, ask them for the
“start URL” / bookmarklet form, or leave EZProxy disabled.

### 2. Put the URL in `config.toml`

```toml
ezproxy_base = "https://YOUR-PREFIX.idm.oclc.org/login?url="
# optional — default is already state/ezproxy-cookies.txt under state_dir:
# ezproxy_cookies = "state/ezproxy-cookies.txt"

sources = [
  "unpaywall", "openalex", "arxiv", "biorxiv", "europepmc", "semanticscholar",
  "core", "scholar", "direct", "ezproxy", "htmlpdf",
]
```

If you later opt in to Sci-Hub, keep `ezproxy` **before** `"scihub"` so
institutional access is preferred when both could work.

### 3. Log in (session vault)

```sh
uv sync --extra htmlpdf
uv run playwright install chromium   # or: playwright install chrome
uv run paperful session login ezproxy
```

`paperful ezproxy` does the same when Playwright is installed. Complete campus
SSO in the window that opens, then press Enter in the terminal. Cookies are
written under `state/sessions/` (and compat `state/ezproxy-cookies.txt`).
Never commit that directory.

### 4. Verify the session

```sh
uv run paperful ezproxy --no-open
```

Success looks like `Session OK`. If not, run `session login ezproxy` again.

### 5. Run (or retry) downloads

New runs pick up EZProxy when `ezproxy` is in `sources` and the session is
valid:

```sh
uv run paperful run --collection YOUR_COLLECTION
```

Items already marked `not_found` from an earlier run are **not** retried
unless you ask:

```sh
uv run paperful run --collection YOUR_COLLECTION --retry-failed
```

### 6. When the session expires

Library SSO typically lasts hours to a few days. When EZProxy starts failing
you will see `ezproxy:error(ezproxy session expired…)` in `paperful report`.
Fix: `paperful session login ezproxy`, then `--retry-failed` if needed.

### Advanced: Netscape cookies.txt

If you cannot install Playwright, `paperful ezproxy` opens the system browser
and you can still drop a Netscape `cookies.txt` at `ezproxy_cookies` (Firefox
**cookies.txt**, Chrome **Get cookies.txt LOCALLY** — local-only exporters).
`chmod 600`. Never commit or paste the file.

### Alternatives and limits

- **Campus VPN**: if VPN alone gives you full publisher access without EZProxy,
  you can leave `ezproxy_base` empty and still use OA sources (and Sci-Hub
  only if you opt in); VPN does not replace a session for this tool’s EZProxy
  source.
- **No subscription**: EZProxy cannot unlock journals your library does not
  license.
- **Non-publisher URLs**: YouTube, Zotero, FAO, and similar pages are never
  proxied — see [What EZProxy will try](#what-ezproxy-will-try). Public UN /
  process PDFs go through `direct` (URL rewrites) then `htmlpdf`.
- **Google Scholar**: solve CAPTCHA in `paperful session login scholar` (same
  Chromium profile used during `run`). Cookie-only export is often not enough.
- **arXiv**: already in the default list (by arXiv id, `10.48550/arxiv.…`
  DOI, or strict title match).
- **bioRxiv / medRxiv**: `10.1101/…` DOIs via the Cold Spring Harbor details
  API; PDF URL built from the latest version.
- **Europe PMC**: OA PDF links (including `?pdf=render`) for PubMed Central
  deposits, by DOI.

---

## Browser sessions (Scholar, EZProxy, publishers)

One local vault: `state/sessions/`. Requires `paperful[htmlpdf]`.

```sh
uv run paperful session login scholar
uv run paperful session login ezproxy
uv run paperful session status
uv run paperful session status --probe  # optional Scholar / EZProxy session_ok
uv run paperful session export          # refresh Netscape dumps for httpx
```

Scholar fetches during `run` use this Chromium profile when it exists (Google
often keys CAPTCHA to the browser, not cookies). htmlpdf uses the same profile
so a publisher login can apply. EZProxy PDF downloads stay on httpx using the
exported cookies.

Never commit `state/sessions/` or cookie files; never paste them into chat.

### If you see `Session not ready` (Scholar)

| What you see | Likely cause | Fix |
| --- | --- | --- |
| `No session yet` / cookie file missing | No login / export | `paperful session login scholar` |
| `blocked or CAPTCHA` | Solved CAPTCHA in a different browser | Login in the paperful Chromium window |
| Works in Chrome, fails here | Fingerprint mismatch | `session login scholar`; or drop `scholar` from `sources` |

Do **not** probe Scholar in a tight loop.

When Scholar is blocked mid-run you will see `scholar blocked/captcha`. After
`circuit_breaker_threshold` (default 3) it is skipped for the rest of that
run. Items left `captcha` / `error` are retried on the next run; `not_found`
needs `--retry-failed`.

---

## Sci-Hub

Sci-Hub occupies a **legal grey zone in some jurisdictions**. paperful does
not enable it unless you opt in. You are responsible for complying with the
laws that apply to you. The authors and distributors of this tool do not
encourage copyright infringement.

Opt in either way (Sci-Hub is then tried last, after open-access sources and
EZProxy):

- add `"scihub"` at the end of `sources` in `config.toml`, or
- pass `--scihub` on a single `run`.

A yellow disclaimer is printed whenever Sci-Hub is in the source list for
that run. `paperful mirrors` pings configured hostnames even when Sci-Hub is
off; it does not turn the source on.

When enabled, mirrors are tried in the configured order. A mirror that fails
on the network `mirror_failures_before_skip` times in a row is skipped for the
rest of the run. Sci-Hub's robot check (ALTCHA proof-of-work) is solved
automatically; if it still cannot be passed the item is marked `captcha` and
retried next run. Repeated CAPTCHAs also trip the run-wide
[circuit breaker](#source-routing-and-circuit-breaker) for `scihub`. A
definitive "not found" is final for the run since all mirrors share one
database. Coverage after ~2021 is thin.

## Tests

```sh
uv run pytest
```

## License

[MIT](LICENSE)

---

<p align="center">
  <a href="https://ko-fi.com/C0C1XK8G" target="_blank" rel="noopener noreferrer"><img height="36" style="border:0;height:36px" src="https://storage.ko-fi.com/cdn/kofi6.png?v=6" alt="Buy Me a Coffee at ko-fi.com" /></a>
</p>
