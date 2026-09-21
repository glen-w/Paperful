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

# optional LLM verbs — off until [llm].enabled; setup in docs/llm.md
uv run paperful recover --item ITEMKEY --dry-run     # browser agent: show start URL only
uv run paperful recover --item ITEMKEY               # needs Python 3.11+ and paperful[browser-agent]
uv run paperful summarize --item ITEMKEY             # → state/summaries/ITEMKEY.html (no Zotero write)
uv run paperful summarize -C BBNJ --limit 5 --apply  # create/update tagged child notes
uv run paperful summarize --item ITEMKEY --prompt prompts/mine.md --force

# restrict / reorder sources for one run, or cap the number of items processed
uv run paperful run -C hoops --sources unpaywall,openalex,ezproxy
uv run paperful run --library --limit 50

# year range (inclusive; undated items excluded) — e.g. full run on BBNJ 2023–2026
uv run paperful run -C BBNJ --year-from 2023 --year-to 2026
uv run paperful run -C BBNJ --year-from 2023 --year-to 2026 --dry-run
uv run paperful gaps -C BBNJ --year-from 2023 --year-to 2026

# restrict to Zotero item types (repeatable / comma-separated; friendly names ok)
uv run paperful run -C BBNJ -T journalArticle --year-from 2023 --year-to 2026
uv run paperful run -C BBNJ -T "Journal Article" -T report
uv run paperful lint -C BBNJ --type journalArticle,preprint

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

# duplicates, then remaining PDF gaps (review the pack before --apply)
uv run paperful dedupe -C BBNJ --dry-run
uv run paperful dedupe -C BBNJ --apply          # high_doi only; add --apply-medium for title+year
uv run paperful gaps -C BBNJ
```

| Command | Purpose |
| --- | --- |
| `doctor` | Environment check (Zotero, paths, email, sessions, pdftotext, Playwright, grey-lit packs, LLM, browser-agent extra). Green / amber / red. TTY guide for remediations (`--guide` / `--no-guide`). |
| `run` | Find and download missing PDFs (`--dry-run`, `--preset eoi`, `--upgrade-linked`, `--try-all`, `--retry-failed`, `--sources`, `--scihub`, `--year-from` / `--year-to`, `--type` / `-T`, `--limit`). Never rewrites bibliographic fields. |
| `recover` | Opt-in **browser-agent** PDF recovery for named items (`--item KEY` repeatable, `--dry-run`, `--no-attach`). Only the `browser_agent` source; never part of `run`. Needs `[llm].enabled`, Python 3.11+, `paperful[browser-agent]`, and a session vault. Report: `state/runs/<stamp>-recover.json`. See [LLM](llm.md#a-recover-browser-agent-pdf-recovery). |
| `lint` | Read-only identifier / PDF-DOI / title-hygiene findings (`--json`, `--strict`, `--year-from` / `--year-to`, `--type` / `-T`, `--limit`). Codes: `missing_doi`, `suspect_doi`, `swappable_doi`, `pmid_no_doi`, `pdf_doi_mismatch`, `title_html`, `title_all_caps`, `title_filename`, `no_identifier`, plus `pdf_identity_mismatch` when `[lint].llm_pdf_match` is on |
| `fix-metadata` | Propose patches on disk; `--apply` writes them to the library (`--overwrite` for title/date/venue; `--year-from` / `--year-to`, `--type` / `-T`, `--limit`). Whitelist: `doi`, `title`, `date`, `publicationTitle`. HTML title cleanup, ALL CAPS → Title Case, and verified PDF-DOI adoption included; filename titles stay lint-only unless `[fix_metadata].llm_title` proposes a grounded title (`source = "llm_title"`). |
| `summarize` | Grounded LLM summary from the PDF already on disk (`--item` / `-C` / `--library`, `--year-from` / `--year-to`, `--type` / `-T`, `--limit`, `--prompt FILE`, `--force`). Always writes `state/summaries/<key>.html`; `--apply` creates or updates one child note tagged `[summarize].tag`. See [LLM](llm.md#d-summarize-grounded-summary-note). |
| `dedupe` | Duplicate pack on disk (`high_doi`, then `title+year`). `--apply` trashes DOI extras only; title+year needs `--apply-medium`. Held when same-DOI titles diverge. Same year/type scope flags as `run`. See [dedupe](dedupe.md). |
| `gaps` | Counts: no stored PDF, linked PDF URL only, missing DOI. Read-only. Year/type scope flags apply. Next steps are `run` and `lint`. |
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

## Scope filters

After collection / `--library` selection, these optional filters shrink the
item list further (applied before `--limit`). They appear in the Scope line
(e.g. `BBNJ, years 2023–2026, types journalArticle`).

| Flag | Effect |
| --- | --- |
| `--year-from YEAR` | Keep items dated this year or later (inclusive). |
| `--year-to YEAR` | Keep items dated this year or earlier (inclusive). |
| `--type` / `-T TYPE` | Keep only these Zotero item types (repeatable or comma-separated). |

**Year.** Open ends are fine (`--year-from 2023` alone). Items with no
parsed publication year are excluded whenever either bound is set.
`--year-from` must be ≤ `--year-to`.

**Type.** Accepts Zotero camelCase ids (`journalArticle`), spaced labels
(`Journal Article`), and hyphen/underscore forms (`journal-article`). Case
insensitive. Unknown tokens exit 1. Common scholarly types:

`journalArticle`, `preprint`, `conferencePaper`, `report`, `book`,
`bookSection`, `thesis`, `manuscript`, `document`, `webpage`,
`newspaperArticle`, `magazineArticle`, `blogPost`, `dataset`, `standard`,
`patent`, `presentation`, …

Attachments, notes, and annotations are never in scope (Zotero skips them
already). Full list: Zotero’s item-types reference; paperful rejects anything
not in that set.

```sh
uv run paperful run -C BBNJ --year-from 2023 --year-to 2026 -T journalArticle
uv run paperful gaps -C BBNJ -T "Journal Article" -T report
uv run paperful lint -C BBNJ --type journalArticle,preprint --strict
```

Same flags on `run`, `lint`, `fix-metadata`, `dedupe`, `gaps`, and
`summarize`.

## Doctor

`paperful doctor` prints one line per check.

| Colour | Meaning |
| --- | --- |
| **green** | Ready |
| **amber** | Degraded but you can continue (empty `email`, missing EZProxy/Scholar session, no `pdftotext`, Playwright/Chromium not ready, Zotero without write API, LLM enabled but daemon/model/extra not ready, small model for the browser agent) |
| **red** | Fatal if the check is `Zotero :23119`, `out_dir`, or `state_dir` |

Unpaywall needs a real `email`. Missing sessions: `paperful session login ezproxy` or `scholar` (system Chrome/Edge when present). Missing `pdftotext`: Poppler; `pypdf` is the fallback. Playwright is core; Chromium installs on first `session login`. An amber Write API means Zotero 7–9: fetch still works, but `attach`, `fix-metadata --apply`, and `dedupe --apply` do not.

On a TTY (Compose sets `stdin_open` / `tty` for the optional image), amber/red
checks open an interactive **Guide**: each step prints what to do, waits for
Enter, then re-runs that check. Session logins still need a headed browser on
the host when you run inside Docker. Force or skip with `--guide` / `--no-guide`.
Inside Docker, `docker compose run --rm paperful` with no extra args is `doctor`.

## Dry-run

`paperful run … --dry-run` talks to Zotero only (no PDF fetches). The table’s
**Would-hit** column is the source lane for that item, in order. `--try-all`
(or `source_routing = false`) lists every configured source.

`paperful dedupe` is a dry-run unless you pass `--apply`: it writes
`state/dedupe-packs/` and does not trash. Do not pass `--dry-run` and
`--apply` together.

## Exits

| Code | When |
| --- | --- |
| 0 | Success (including empty dry-run) |
| 1 | User error (unknown collection, bad preset, unknown `--phase`, `--dry-run` together with `--apply`, `--year-from` > `--year-to`, unknown `--type`, `--strict` lint findings, unknown `--item` key, LLM not enabled/misconfigured for `recover` / `summarize`, `recover` on Python < 3.11, note write refused) |
| 2 | Environment: Zotero unreachable on `collections`, `run`, `attach`, `lint`, `fix-metadata`, `dedupe`, `gaps`, `recover`, or `summarize`. Prints **Next steps** (start Zotero, enable local API, `paperful doctor`) |

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
- `state/dedupe-packs/` — `dedupe` review packs (`.json` and `.md`). Not applied
  until `--apply`.
- `state/dedupe-applied.jsonl` — one line per item moved to trash by
  `dedupe --apply`.
- `state/pdf-cache/` — PDFs exported from the manager so lint can read text
  on disk (`pdftotext`, then `pypdf`).
- `state/last-run.json` — latest auditable `run` report (summary + per-item
  outcomes). Historical copies land in `state/runs/<timestamp>-<command>.json`
  (`run`, or `fix-metadata` after `--apply`). `fix-metadata --apply` does
  not overwrite `last-run.json`.
- `state/summaries/` — HTML summaries from `summarize` before optional `--apply`
  to Zotero.
- `state/sessions/` — Chromium profile (`chromium/`) plus `meta.json` (no
  passwords). Gitignored; `chmod 700`. Netscape dumps also land here and as
  `ezproxy-cookies.txt` / `scholar-cookies.txt` for httpx.
- `state/zotero-local-api-key.json` — the Zotero write key if you chose
  "Always Allow".
