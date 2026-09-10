# Campus EZProxy

Publisher sites (Elsevier ScienceDirect, Springer Nature, Wiley, JSTOR, …)
normally require a subscription. If your university or research library
offers **EZProxy** (or a similar “login?url=” redirector), paperful can
download those PDFs **using your existing library entitlement**.

## What EZProxy will try

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
once in a headed browser (`paperful session login ezproxy` prefers system
Chrome/Edge so campus SSO works); `run` reuses that vault and exported cookies
until the campus session expires.

## 1. Find your library’s EZProxy base URL

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

## 2. Put the URL in `config.toml`

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

## 3. Log in (session vault)

```sh
uv run paperful session login ezproxy
```

Playwright is already a core dependency (`uv sync`). Chromium downloads on the
first login if needed. Login prefers your system Chrome/Edge (Google and campus
SSO often reject a Playwright-launched window). `paperful ezproxy` does the
same. Complete campus SSO in the window that opens, then press Enter in the
terminal. Cookies are written under `state/sessions/` (and compat
`state/ezproxy-cookies.txt`). Never commit that directory.

## 4. Verify the session

```sh
uv run paperful ezproxy --no-open
```

Success looks like `Session OK`. If not, run `session login ezproxy` again.

## 5. Run (or retry) downloads

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

## 6. When the session expires

Library SSO typically lasts hours to a few days. When EZProxy starts failing
you will see `ezproxy:error(ezproxy session expired…)` in `paperful report`.
Fix: `paperful session login ezproxy`, then `--retry-failed` if needed.

## Advanced: Netscape cookies.txt

If headed login is unavailable, `paperful ezproxy` can still use a Netscape
`cookies.txt` at `ezproxy_cookies` (Firefox **cookies.txt**, Chrome **Get
cookies.txt LOCALLY** — local-only exporters). `chmod 600`. Never commit or
paste the file.

## Alternatives and limits

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
