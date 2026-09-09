# scihub-dl

Fetch missing PDFs for Zotero items, save them to disk in a folder tree that mirrors your
collections, and attach them back into Zotero.

Sources are tried in order: **open access** first (Unpaywall, OpenAlex, arXiv, Semantic Scholar,
optional Google Scholar, the item's own URL), then your campus **EZProxy** (if configured), then
**Sci-Hub** mirrors. Sci-Hub coverage after ~2021 is thin; recent paywalled papers are best fetched
via EZProxy when your library has a subscription.

## Requirements

- Zotero running with the local API enabled:
  Settings → Advanced → "Allow other applications on this computer to communicate with Zotero".
- Zotero 10+ for attaching PDFs into the library (the local *write* API). On Zotero 7–9 the tool
  still downloads to disk; attach later with `scihub-dl attach` once upgraded.
- `uv` (Python 3.10+).
- Optional: a university/library account and EZProxy URL if you want publisher PDFs (ScienceDirect,
  Springer, Wiley, Taylor & Francis, …).

## Setup

```sh
cd /path/to/Paperful
uv sync
# edit config.toml: email, out_dir, and (optional) ezproxy_base — see below
uv run scihub-dl collections          # sanity check: tree with "No PDF" counts
uv run scihub-dl mirrors              # which Sci-Hub mirrors are up
```

If you use campus EZProxy, finish the [Campus EZProxy](#campus-ezproxy) section before a big run.

## Usage

```sh
# see what would be fetched, no downloads
uv run scihub-dl run --collection interesting --dry-run

# fetch to disk only
uv run scihub-dl run --collection interesting --no-attach

# fetch + attach (Zotero 10+ shows an authorisation dialog the first time; pick "Always Allow")
uv run scihub-dl run --collection "BBNJ/not undermine"

# several collections, or the whole library (resumable; Ctrl-C any time, rerun to continue)
uv run scihub-dl run -C BBNJ -C AO
uv run scihub-dl run --library

# attach previously downloaded PDFs
uv run scihub-dl attach

# what happened
uv run scihub-dl report
uv run scihub-dl report --not-found
uv run scihub-dl report --status error

# retry items marked not_found / no_identifier (e.g. after EZProxy login or Sci-Hub catches up)
uv run scihub-dl run --library --retry-failed
uv run scihub-dl run --collection BBNJ --retry-failed

# restrict / reorder sources for one run, or cap the number of items processed
uv run scihub-dl run -C hoops --sources unpaywall,openalex,ezproxy
uv run scihub-dl run --library --limit 50
```

Collections can be given as a path (`BBNJ/not undermine`), a unique name, or a key. Subcollections
are always included. Items in several selected collections are written once and hard-linked into
the other folders.

## Configuration (`config.toml`)

Looked up as `--config PATH`, then `./config.toml`, then the project folder's `config.toml`,
then `~/.config/scihub_dl/config.toml`. Relative paths resolve against the config file's folder.

| Key | Default | Meaning |
| --- | --- | --- |
| `email` | `""` | Sent as `mailto` to Unpaywall/OpenAlex/Crossref (required by Unpaywall) |
| `out_dir` / `state_dir` | `out` / `state` | PDF tree and manifest/key location |
| `sources` | OA → `scholar` → `direct` → `ezproxy` → `scihub` | Source order; `--sources` overrides per run |
| `ezproxy_base` | `""` (disabled) | Campus proxy prefix ending in `url=` — see [Campus EZProxy](#campus-ezproxy) |
| `ezproxy_cookies` | `state/ezproxy-cookies.txt` | Netscape cookies file after browser login |
| `scihub_mirrors` | built-in list | Hostnames tried in order |
| `delay_scihub_s` | `[3, 8]` | Random pause (seconds) before each Sci-Hub / EZProxy page fetch |
| `concurrency_oa` | `4` | Parallel workers for open-access sources (EZProxy and Sci-Hub are serial) |
| `min_pdf_bytes` | `10000` | Smaller downloads are rejected as error pages |
| `crossref_min_score` | `0.90` | Title-similarity threshold for accepting a Crossref DOI |
| `mirror_failures_before_skip` | `3` | Network failures before a Sci-Hub mirror is skipped for the run |
| `attach` | `true` | Attach into Zotero after download (`--no-attach` overrides) |
| `app_name` | `scihub-dl` | Name shown in Zotero's authorisation dialog |

Leave `ezproxy_base` empty (or remove `ezproxy` from `sources`) if you do not use a library proxy.
Remove `scholar` from `sources` if Google Scholar CAPTCHAs add noise. Remove `scihub` to disable
Sci-Hub entirely.

## Output

- `out/<collection path>/Author - Year - Title.pdf`
- `state/manifest.jsonl` — one line per item attempt; the latest line per item key wins. Statuses:
  `ok` (on disk), `attached` (on disk + in Zotero), `not_found`, `no_identifier`, `captcha`,
  `error`, `attach_failed`. `ok` / `attached` are never retried; `not_found` / `no_identifier` only
  with `--retry-failed`; the rest are retried on every run.
- `state/zotero-local-api-key.json` — the Zotero write key if you chose "Always Allow".
- `state/ezproxy-cookies.txt` — library session cookies (gitignored; never commit this file).

---

## Campus EZProxy

Publisher sites (Elsevier ScienceDirect, Springer Nature, Wiley, JSTOR, …) normally require a
subscription. If your university or research library offers **EZProxy** (or a similar “login?url=”
redirector), scihub-dl can download those PDFs **using your existing library entitlement**.

The tool never asks for or stores your institutional password. You log in once in a normal browser,
export session cookies to a local file, and scihub-dl reuses that session until it expires.

### 1. Find your library’s EZProxy base URL

Ask your library website for “EZProxy”, “off-campus access”, or “proxy bookmarklet”, or try the
pattern many OCLC sites use:

```text
https://<your-prefix>.idm.oclc.org/login?url=
```

Examples (illustrative only — use **your** institution’s URL):

| Institution (example) | Typical `ezproxy_base` |
| --- | --- |
| Sciences Po | `https://scpo.idm.oclc.org/login?url=` |
| Other OCLC EZProxy | `https://<prefix>.idm.oclc.org/login?url=` |

The value must be the prefix that, when a target URL is appended, starts login. A quick check in
the browser: open

```text
https://<your-prefix>.idm.oclc.org/login?url=https://www.sciencedirect.com/
```

You should land on your university’s single sign-on (CAS, Shibboleth, Microsoft, etc.). After
login you should reach ScienceDirect (or an error from the publisher if your library does not
subscribe — the login itself still proves the proxy URL is correct).

Some libraries use a hostname-rewriting proxy without `login?url=` (e.g. `www-sciencedirect-com.proxy.example.edu`). This tool expects the **`login?url=`** form. If your library only offers rewriting, ask them for the “start URL” / bookmarklet form, or leave EZProxy disabled.

### 2. Put the URL in `config.toml`

```toml
ezproxy_base = "https://YOUR-PREFIX.idm.oclc.org/login?url="
# optional — default is already state/ezproxy-cookies.txt under state_dir:
# ezproxy_cookies = "state/ezproxy-cookies.txt"

sources = [
  "unpaywall", "openalex", "arxiv", "semanticscholar", "scholar",
  "direct", "ezproxy", "scihub",
]
```

Keep `ezproxy` in `sources` **before** `scihub` so institutional access is preferred when both
could work.

### 3. Open the login page

```sh
uv run scihub-dl ezproxy
```

This prints your configured proxy and cookie path, and opens the login URL in your default browser
(`--no-open` skips the browser). Complete SSO until you can browse a proxied publisher page.

Stay logged in; do not clear cookies before exporting.

### 4. Export cookies (Netscape `cookies.txt`)

scihub-dl reads a **Netscape-format** cookie file (the same format curl uses). Export it from the
browser that just completed login.

#### Firefox

1. Install a cookie exporter from [addons.mozilla.org](https://addons.mozilla.org), for example
   **[cookies.txt](https://addons.mozilla.org/firefox/addon/cookies-txt/)**. Prefer extensions that
   keep data local (names often include “LOCALLY”).
2. Open a tab whose address bar contains your proxy host, e.g. `….idm.oclc.org` or a rewritten
   host like `www-sciencedirect-com.…idm.oclc.org`.
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
   (or another local-only Netscape exporter). Avoid older “cookies.txt” extensions that upload data
   to a remote server.
2. On a tab whose URL contains your `….idm.oclc.org` proxy host, open the extension.
3. Export **current site** (or include related proxy domains if the UI offers that).
4. Save as `state/ezproxy-cookies.txt` under your configured `state_dir` (same path as above).

#### Safari

Safari has no well-supported one-click Netscape exporter. Use Firefox or Chrome for the one-time
login + export step; you can keep using Safari for everyday browsing afterward.

#### What must be in the file

- Format: Netscape HTTP Cookie File (tab-separated lines; often starts with a `# Netscape…` comment).
- At least cookies for your EZProxy host (e.g. `….idm.oclc.org`). Including SSO cookies for your
  IdP domain (CAS / Shibboleth / Microsoft login host) can help some setups but is not always
  required.
- Permissions: `chmod 600` is recommended; the path is gitignored — **never commit it** and never
  paste it into chat or email.

### 5. Verify the session

```sh
uv run scihub-dl ezproxy --no-open
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

New runs pick up EZProxy automatically when `ezproxy` is in `sources` and the cookie file is valid:

```sh
uv run scihub-dl run --collection YOUR_COLLECTION
```

Items already marked `not_found` from an earlier run are **not** retried unless you ask:

```sh
uv run scihub-dl run --collection YOUR_COLLECTION --retry-failed
```

### 7. When the session expires

Library SSO cookies typically last hours to a few days. When EZProxy starts failing you will see
attempts like `ezproxy:error(ezproxy session expired…)` in `scihub-dl report`, and the run will
fall through to Sci-Hub / `not_found`.

Fix: repeat steps 3–5 (login → export → verify), then `--retry-failed` if needed.

### Alternatives and limits

- **Campus VPN**: if VPN alone gives you full publisher access without EZProxy, you can leave
  `ezproxy_base` empty and still use OA + Sci-Hub; VPN does not replace cookie export for this
  tool’s EZProxy source.
- **No subscription**: EZProxy cannot unlock journals your library does not license.
- **Google Scholar**: already in the default source list; often blocked by CAPTCHA for automated
  clients — remove `scholar` from `sources` if noisy.
- **arXiv**: already in the default list (by arXiv id, `10.48550/arxiv.…` DOI, or strict title match).

---

## How Sci-Hub is handled

Mirrors are tried in the configured order. A mirror that fails on the network
`mirror_failures_before_skip` times in a row is skipped for the rest of the run. Sci-Hub's robot
check (ALTCHA proof-of-work) is solved automatically; if it still cannot be passed the item is
marked `captcha` and retried next run. A definitive "not found" is final for the run since all
mirrors share one database.

## Tests

```sh
uv run pytest
```
