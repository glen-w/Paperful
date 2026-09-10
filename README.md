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
big run. If you keep `scholar` in `sources`, optionally export cookies with
`paperful scholar` — see [Google Scholar cookies](#google-scholar-cookies).

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

# session cookies (optional)
uv run paperful ezproxy              # open campus proxy login
uv run paperful scholar               # open Google Scholar (solve CAPTCHA, then export cookies)
uv run paperful mirrors              # which Sci-Hub mirrors are up (Sci-Hub itself stays off)

# identifiers vs PDFs (read-only); metadata writes are a separate step
uv run paperful lint --library --json
uv run paperful lint -C BBNJ --strict             # exit 1 if any finding
uv run paperful fix-metadata --library            # dry-run → state/metadata-patches.jsonl
uv run paperful fix-metadata --library --apply    # write DOI/title/date/venue into Zotero 10+
uv run paperful fix-metadata --library --apply --overwrite   # also replace title/date/venue
```

| Command | Purpose |
| --- | --- |
| `doctor` | Environment check (Zotero, paths, email, cookies, pdftotext) |
| `run` | Find and download missing PDFs (`--dry-run`, `--preset eoi`, `--upgrade-linked`, `--try-all`, `--retry-failed`, `--sources`, `--scihub`, `--limit`). Never rewrites bibliographic fields. |
| `lint` | Read-only identifier / PDF-DOI findings (`--json`, `--strict`, `--limit`). Codes: `missing_doi`, `suspect_doi`, `swappable_doi`, `pmid_no_doi`, `pdf_doi_mismatch`, `no_identifier` |
| `fix-metadata` | Propose patches on disk; `--apply` writes them to the library (`--overwrite` for title/date/venue). Whitelist: `doi`, `title`, `date`, `publicationTitle` |
| `collections` | Collection tree with “No PDF” counts |
| `report` | Manifest summary + latest run report (`--last-run`, `--json`, `--not-found`, `--status`) |
| `attach` | Attach already-downloaded PDFs into Zotero |
| `ezproxy` | Open / verify campus EZProxy session |
| `scholar` | Open / verify Google Scholar cookies |
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
resolve PrepCom papers, many DOALOS/UN docs, or undocs without a DOI. Paperful
will try `direct` (item URL) and `htmlpdf` (web/news types) when routing
allows; otherwise the manifest records `no_identifier`. See
[docs/architecture.md](docs/architecture.md). Longer-horizon notes:
[docs/ROADMAP.md](docs/ROADMAP.md).

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
| `ezproxy_cookies` | `state/ezproxy-cookies.txt` | Netscape cookies file after browser login |
| `scholar_cookies` | `state/scholar-cookies.txt` | Google Scholar cookies after CAPTCHA — see [Google Scholar cookies](#google-scholar-cookies) |
| `scihub_mirrors` | built-in list | Hostnames tried in order |
| `delay_scihub_s` | `[3, 8]` | Random pause (seconds) before each Sci-Hub / EZProxy / htmlpdf page fetch |
| `concurrency_oa` | `4` | Parallel workers for open-access sources (EZProxy, htmlpdf, and Sci-Hub are serial) |
| `min_pdf_bytes` | `10000` | Smaller downloads are rejected as error pages |
| `crossref_min_score` | `0.90` | Title-similarity threshold for accepting a title→DOI match (Crossref, then OpenAlex, then Semantic Scholar) |
| `mirror_failures_before_skip` | `3` | Network failures before a Sci-Hub mirror is skipped for the run |
| `source_routing` | `true` | Skip sources that look inapplicable from item metadata; use `--try-all` to override per run |
| `circuit_breaker_threshold` | `3` | Block-like failures (CAPTCHA, rate limits) before a source is skipped for the rest of the run |
| `attach` | `true` | Attach into Zotero after download (`--no-attach` overrides) |
| `app_name` | `paperful` | Name shown in Zotero's authorisation dialog |
| `user_agent` | Chrome-like string | HTTP `User-Agent` for source and download requests |

Leave `ezproxy_base` empty (or remove `ezproxy` from `sources`) if you do not
use a library proxy. Remove `scholar` from `sources` if Google Scholar CAPTCHAs
add noise even with cookies. Sci-Hub is off until you add `"scihub"` to
`sources` or pass `--scihub` — see [Sci-Hub](#sci-hub). Set
`source_routing = false` (or pass `--try-all`) when Zotero fields are
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
- `state/zotero-local-api-key.json` — the Zotero write key if you chose
  "Always Allow".
- `state/ezproxy-cookies.txt` — library session cookies (gitignored; never
  commit this file).
- `state/scholar-cookies.txt` — Google Scholar session cookies (gitignored;
  never commit this file).

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
| `direct` | HTTP(S) URL that is not a resolver/aggregator/video host (doi.org, Scholar, Zotero, YouTube, X/Twitter, Consensus, …) |
| `ezproxy` | `ezproxy_base` plus a cookie file, **and** a DOI or a URL on a [known publisher host](#what-ezproxy-will-try) |
| `htmlpdf` | `webpage` / `blogPost` / `newspaperArticle` / `magazineArticle` / `forumPost` (or DOI-less `document`) with an HTTP(S) URL; needs optional Playwright — see [HTML→PDF](#htmlpdf-web-news-blogs) |

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
`forumPost` (and DOI-less `document`s with a URL) rarely have a native PDF.
After `direct` fails to find a PDF link on the page, the optional `htmlpdf`
source prints the page with headless Chromium and attaches the result.

```sh
uv sync --extra htmlpdf
uv run playwright install chromium
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
once in a normal browser, export session cookies to a local file, and paperful
reuses that session until it expires.

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

### 3. Open the login page

```sh
uv run paperful ezproxy
```

This prints your configured proxy and cookie path, and opens the login URL
in your default browser (`--no-open` skips the browser). Complete SSO until
you can browse a proxied publisher page.

Stay logged in; do not clear cookies before exporting.

### 4. Export cookies (Netscape `cookies.txt`)

paperful reads a **Netscape-format** cookie file (the same format curl uses).
Export it from the browser that just completed login.

#### Firefox

1. Install a cookie exporter from [addons.mozilla.org](https://addons.mozilla.org),
   for example **[cookies.txt](https://addons.mozilla.org/firefox/addon/cookies-txt/)**.
   Prefer extensions that keep data local (names often include “LOCALLY”).
2. Open a tab whose address bar contains your proxy host, e.g. `….idm.oclc.org`
   or a rewritten host like `www-sciencedirect-com.…idm.oclc.org`.
3. Click the extension icon → export cookies for **this site** / **current domain**.
4. Choose Netscape / cookies.txt format if asked.
5. Save or move the file to:

   ```text
   <state_dir>/ezproxy-cookies.txt
   ```

   With the default project layout that is:

   ```text
   state/ezproxy-cookies.txt
   ```

   (absolute example: `/path/to/Paperful/state/ezproxy-cookies.txt`)

If the extension downloads to your Desktop as `cookies.txt`:

```sh
mv ~/Desktop/cookies.txt /path/to/Paperful/state/ezproxy-cookies.txt
chmod 600 /path/to/Paperful/state/ezproxy-cookies.txt
```

#### Chrome / Edge / Brave / Chromium

1. Install **[Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)**
   (or another local-only Netscape exporter). Avoid older “cookies.txt”
   extensions that upload data to a remote server.
2. On a tab whose URL contains your `….idm.oclc.org` proxy host, open the
   extension.
3. Export **current site** (or include related proxy domains if the UI offers
   that).
4. Save as `state/ezproxy-cookies.txt` under your configured `state_dir` (same
   path as above).

#### Safari

Safari has no well-supported one-click Netscape exporter. Use Firefox or Chrome
for the one-time login + export step; you can keep using Safari for everyday
browsing afterward.

#### What must be in the file

- Format: Netscape HTTP Cookie File (tab-separated lines; often starts with a
  `# Netscape…` comment).
- At least cookies for your EZProxy host (e.g. `….idm.oclc.org`). Including
  SSO cookies for your IdP domain (CAS / Shibboleth / Microsoft login host)
  can help some setups but is not always required.
- Permissions: `chmod 600` is recommended; the path is gitignored — **never
  commit it** and never paste it into chat or email.

### 5. Verify the session

```sh
uv run paperful ezproxy --no-open
```

Success looks like:

```text
Session OK — ok (…)
```

If you see `Session not ready` / `session expired` / `cookie file missing`:

- Confirm the file path matches `ezproxy_cookies` / `state_dir`.
- Confirm you exported **after** a successful SSO login, from a **proxied** tab.
- Log in again in the browser, re-export, overwrite `ezproxy-cookies.txt`, retry.

### 6. Run (or retry) downloads

New runs pick up EZProxy automatically when `ezproxy` is in `sources` and the
cookie file is valid:

```sh
uv run paperful run --collection YOUR_COLLECTION
```

Items already marked `not_found` from an earlier run are **not** retried
unless you ask:

```sh
uv run paperful run --collection YOUR_COLLECTION --retry-failed
```

### 7. When the session expires

Library SSO cookies typically last hours to a few days. When EZProxy starts
failing you will see attempts like `ezproxy:error(ezproxy session expired…)` in
`paperful report`, and the run will fall through to Sci-Hub (if you opted in)
or `not_found`.

Fix: repeat steps 3–5 (login → export → verify), then `--retry-failed` if
needed.

### Alternatives and limits

- **Campus VPN**: if VPN alone gives you full publisher access without EZProxy,
  you can leave `ezproxy_base` empty and still use OA sources (and Sci-Hub
  only if you opt in); VPN does not replace cookie export for this tool’s
  EZProxy source.
- **No subscription**: EZProxy cannot unlock journals your library does not
  license.
- **Non-publisher URLs**: YouTube, Zotero, FAO, and similar pages are never
  proxied — see [What EZProxy will try](#what-ezproxy-will-try).
- **Google Scholar**: often blocked by CAPTCHA for automated clients — export
  browser cookies ([Google Scholar cookies](#google-scholar-cookies)) or
  remove `scholar` from `sources` if noisy.
- **arXiv**: already in the default list (by arXiv id, `10.48550/arxiv.…`
  DOI, or strict title match).
- **bioRxiv / medRxiv**: `10.1101/…` DOIs via the Cold Spring Harbor details
  API; PDF URL built from the latest version.
- **Europe PMC**: OA PDF links (including `?pdf=render`) for PubMed Central
  deposits, by DOI.

---

## Google Scholar cookies

Google Scholar treats scripted clients as bots. If you keep `scholar` in
`sources`, paperful can reuse a normal browser session the same way as EZProxy:
pass the CAPTCHA once, export cookies, and the next runs load that file. This
is **best-effort**. A cookie file that looks complete can still fail the probe,
because Google often keys the “not a robot” pass to the browser (TLS
fingerprint, not cookies alone). Scholar is optional — drop it from `sources`
if it is more noise than help.

Never commit `scholar-cookies.txt`, never paste it into chat or email, and do
not overwrite `ezproxy-cookies.txt` with a Google export (both extensions
default to `cookies.txt`).

### 1. Open Scholar and pass the CAPTCHA

```sh
uv run paperful scholar
```

This prints the cookie path and opens [scholar.google.com](https://scholar.google.com/)
(`--no-open` skips the browser). Stay in **the same browser profile**. Complete
any “unusual traffic” / CAPTCHA check until a **normal search-results page**
loads (result cards, not `google.com/sorry`). Stay logged into a Google
account if you use one. Do not clear cookies before exporting.

### 2. Export cookies (Netscape `cookies.txt`)

Use the same local-only extensions as
[Campus EZProxy](#4-export-cookies-netscape-cookiestxt) (Firefox **cookies.txt**,
Chrome **Get cookies.txt LOCALLY**). JSON / “EditThisCookie” dumps will not
parse.

1. Stay on the **scholar.google.com** tab that already shows results — not the
   sorry/CAPTCHA page.
2. Export **this site**, and include related Google cookies if the UI offers
   that. You need both `.google.com` (account cookies such as `SID` / `NID`)
   and `.scholar.google.com` (`GSP`).
3. Save to the path printed by `paperful scholar` (from `scholar_cookies`,
   else `<state_dir>/scholar-cookies.txt`). With the default layout that is:

   ```text
   state/scholar-cookies.txt
   ```

If the extension downloads to your Desktop as `cookies.txt`:

```sh
mv ~/Desktop/cookies.txt /path/to/Paperful/state/scholar-cookies.txt
chmod 600 /path/to/Paperful/state/scholar-cookies.txt
```

Use your real `state_dir` from `config.toml` (the `paperful scholar` output is
the source of truth). Safari has no reliable Netscape exporter; use Firefox or
Chrome for this step.

### 3. Verify

```sh
uv run paperful scholar --no-open
```

Success looks like:

```text
Session OK — ok (200)
```

`Loaded domains:` should mention `google.com` and usually `scholar.google.com`.

### 4. If you see `Session not ready`

Typical causes, in order:

| What you see | Likely cause | Fix |
| --- | --- | --- |
| `cookie file missing` / `No cookie file yet` | Export still on Desktop, or wrong `state_dir` | `mv` to the path the command prints; `chmod 600` |
| File exists but no `.google.com` cookies | Exported only the Scholar host, or JSON format | Re-export Netscape from the Scholar tab; include Google cookies |
| `blocked or CAPTCHA` / `HTTP 429` at `google.com/sorry` | Exported from the sorry page, or Google still fingerprinting the client | Solve CAPTCHA until **results** load, re-export **once**, wait before retrying |
| `unexpected response` | Page loaded but was not a results listing | Confirm the browser tab itself shows results, then re-export |
| Works in the browser, fails here anyway | CAPTCHA pass is tied to Chrome/Firefox, not the cookie jar | Wait, try one more export; or remove `scholar` from `sources` |

Do **not** run `paperful scholar --no-open` in a tight loop. Each failed probe
is more “unusual traffic” and makes the next attempt worse.

### 5. During a download run

When Scholar is blocked mid-run you will see `scholar blocked/captcha` in
`paperful report`. After `circuit_breaker_threshold` (default 3) block-like
failures, Scholar is skipped for the rest of that run so it does not hammer
Google. Refresh cookies (steps 1–3) is the real fix; then rerun. Items left
`captcha` / `error` are retried on the next run; `not_found` needs
`--retry-failed`.

Cookies typically last hours to a few days. Repeat steps 1–3 when they go
stale.

### Alternatives

- Remove `"scholar"` from `sources` if CAPTCHAs dominate. Open-access sources
  and EZProxy do not need a Google session (nor does Sci-Hub, if you have
  opted in).
- `user_agent` in `config.toml` can be set to match your browser, but it will
  not beat Google’s TLS fingerprint on its own.

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
