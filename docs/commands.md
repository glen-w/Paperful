# Commands

Snippets use `uv run`. Same commands work as
`docker compose run --rm paperful …` with the [optional Docker image](docker.md).
Headed `session login` is host-only either way.

```sh
# environment check (TTY guide for amber/red)
uv run paperful doctor
uv run paperful collections

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
uv run paperful session login ezproxy   # system Chrome/Edge when present; campus SSO
uv run paperful session login scholar    # same; --engine playwright to force Playwright
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
| `doctor` | Environment check (Zotero, paths, email, sessions, pdftotext, Playwright, grey-lit packs). Green / amber / red. TTY guide for remediations (`--guide` / `--no-guide`). |
| `run` | Find and download missing PDFs (`--dry-run`, `--preset eoi`, `--upgrade-linked`, `--try-all`, `--retry-failed`, `--sources`, `--scihub`, `--limit`). Never rewrites bibliographic fields. |
| `lint` | Read-only identifier / PDF-DOI / title-hygiene findings (`--json`, `--strict`, `--limit`). Codes: `missing_doi`, `suspect_doi`, `swappable_doi`, `pmid_no_doi`, `pdf_doi_mismatch`, `title_html`, `title_all_caps`, `title_filename`, `no_identifier` |
| `fix-metadata` | Propose patches on disk; `--apply` writes them to the library (`--overwrite` for title/date/venue). Whitelist: `doi`, `title`, `date`, `publicationTitle`. HTML title cleanup and verified PDF-DOI adoption included; ALL CAPS / filename are lint-only. |
| `collections` | Collection tree with “No PDF” counts |
| `report` | Manifest summary + latest run report (`--last-run`, `--json`, `--not-found`, `--status`) |
| `attach` | Attach already-downloaded PDFs into Zotero |
| `session` | Local browser vault: `login scholar|ezproxy` (`--engine auto|chrome|playwright`), `status`, `export` |
| `ezproxy` | Wrapper: headed login (or Netscape fallback) / `--no-open` probe |
| `scholar` | Wrapper: headed login (or Netscape fallback) / `--no-open` probe |
| `mirrors` | Ping configured Sci-Hub mirrors |
| `version` | Print the package version |

Collections can be given as a path (`BBNJ/not undermine`), a unique name, or
a key. Subcollections are always included. Items in several selected
collections are written once and hard-linked into the other folders.

## Doctor

`paperful doctor` prints one line per check.

| Colour | Meaning |
| --- | --- |
| **green** | Ready |
| **amber** | Degraded but you can continue (empty `email`, missing EZProxy/Scholar session, no `pdftotext`, Playwright/Chromium not ready, Zotero without write API) |
| **red** | Fatal if the check is `Zotero :23119`, `out_dir`, or `state_dir` |

Unpaywall needs a real `email`. Missing sessions: `paperful session login ezproxy` or `scholar` (system Chrome/Edge when present). Missing `pdftotext`: Poppler; `pypdf` is the fallback. Playwright is core; Chromium installs on first `session login`.

On a TTY (Compose sets `stdin_open` / `tty` for the optional image), amber/red
checks open an interactive **Guide**: each step prints what to do, waits for
Enter, then re-runs that check. Session logins still need a headed browser on
the host when you run inside Docker. Force or skip with `--guide` / `--no-guide`.
Inside Docker, `docker compose run --rm paperful` with no extra args is `doctor`.

## Dry-run

`paperful run … --dry-run` talks to Zotero only (no PDF fetches). The table’s
**Would-hit** column is the source lane for that item, in order. `--try-all`
(or `source_routing = false`) lists every configured source.

## Exits

| Code | When |
| --- | --- |
| 0 | Success (including empty dry-run) |
| 1 | User error (unknown collection, bad preset, `--strict` lint findings) |
| 2 | Environment: Zotero unreachable on `collections` / `run` / `attach`. Prints **Next steps** (start Zotero, enable local API, `paperful doctor`) |

## Run summary

After a real `run`, a **Run summary** table lists PDFs downloaded, attached,
deferred/skipped, sources checked, and typed errors. `paperful report` reprints
it. JSON: `paperful report --json` — field list in [architecture](architecture.md#run-report-v1).

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
- `state/metadata-patches.jsonl` — append-only audit log of proposed bibliographic
  patches from `fix-metadata` (dry-run and `--apply` both append here first).
  One patch per item key per invocation; inspect the file for review — it is not
  a selective re-apply queue.
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
