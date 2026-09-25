# Commands

Snippets below use `uv run` so they stay short. The operator install is
clone plus `docker compose build`, then
`docker compose run --rm paperful …` ([Docker](docker.md)). CI builds that
image and expects `doctor` to exit 2 without Zotero. There is no published
image and no PyPI package. Headed `session login` is host-only
(`uv run paperful session login …`). No campus access: `--preset oa`.
Campus EZProxy: `--preset eoi`. `paperful jobs` lists verbs by job.
The public grow verb is `snowball` (there is no `harvest` command).

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

uv run paperful ocr -C BBNJ                 # list image PDFs; does not write
uv run paperful ocr -C BBNJ --apply        # text layer on the out/ PDF
uv run paperful ocr --item ITEMKEY --apply --attach   # also upload beside the scan

# optional LLM verbs — off until [llm].enabled; setup in docs/llm.md
# recover also auto-fires at the end of `run` when Scholar / EZProxy / htmlpdf fail
uv run paperful recover --item ITEMKEY --dry-run     # browser agent: show start URL only
uv run paperful recover --item ITEMKEY               # needs Python 3.11+ and paperful[browser-agent]
uv run paperful summarize --item ITEMKEY             # disk HTML + tagged child note (default both)
uv run paperful summarize -C BBNJ --to disk          # HTML only; Zotero tree stays clean
uv run paperful summarize --item ITEMKEY --prompt prompts/mine.md --force
uv run paperful synthesize -C BBNJ --dry-run         # chunk plan from existing summary notes
uv run paperful synthesize -C BBNJ                   # report on disk and a note in the collection

# thicken the on-disk mirror (per-item folders). pdfs: additional | all | none
uv run paperful snapshot -C BBNJ --dry-run
uv run paperful snapshot -C BBNJ --pdfs all
uv run paperful restore -C BBNJ                 # dry-run unless --apply
uv run paperful restore -C BBNJ --year-from 2021 --year-to 2026 -T journalArticle
uv run paperful restore -C BBNJ --apply         # create missing items; never overwrite fields

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

# the same slice as one command, or saved beside config.toml
#   gaps → run --try-all --retry-failed --upgrade-linked → lint → fix-metadata --apply → summarize --apply
uv run paperful all -C BBNJ -T journalArticle --year-from 2021 --year-to 2026
uv run paperful all -C BBNJ -T journalArticle --year-from 2021 --year-to 2026 --dry-run
uv run paperful profile save bbnj-journal -C BBNJ -T journalArticle --year-from 2021 --year-to 2026 --try-all --apply
uv run paperful all --profile bbnj-journal
uv run paperful profile list
uv run paperful profile show bbnj-journal

# Sci-Hub is off unless you opt in (config `sources`, or this flag)
uv run paperful run --library --scihub

# session (optional)
uv run paperful session login ezproxy   # system Chrome/Edge when present; campus SSO
uv run paperful session login scholar    # same; --engine playwright to force Playwright
uv run paperful session login mendeley  # Elsevier OAuth (host-only localhost redirect)
uv run paperful session status
uv run paperful ezproxy --no-open       # probe the EZProxy session
uv run paperful scholar --no-open       # probe Scholar
uv run paperful mirrors                  # which Sci-Hub mirrors are up (Sci-Hub itself stays off)

# interchange (RIS / BibTeX / EndNote XML)
uv run paperful export library.ris --library
uv run paperful import other.bib                 # dry-run
uv run paperful import other.bib --apply

# identifiers vs PDFs (read-only); metadata writes are a separate step
uv run paperful lint --library --json
uv run paperful lint -C BBNJ --strict             # exit 1 if any finding
uv run paperful fix-metadata --library            # dry-run → state/metadata-patches.jsonl
uv run paperful fix-metadata --library --apply    # write DOI/title/date/venue into Zotero 10+
uv run paperful fix-metadata --library --apply --overwrite   # replaces title/date/venue you may have edited; dry-run first

# duplicates, then remaining PDF gaps (review the pack before --apply)
uv run paperful dedupe -C BBNJ --dry-run
uv run paperful dedupe -C BBNJ --apply          # high_doi only; add --apply-medium for title+year
uv run paperful gaps -C BBNJ

# one witness for a sequence (child reports still land in state/runs/)
uv run paperful pack open --label bbnj-journal-2021-2026
uv run paperful gaps -C BBNJ
uv run paperful pack close
uv run paperful pack show
```

| Command | Purpose |
| --- | --- |
| `doctor` | Environment check (Zotero / Mendeley / EndNote, paths, email, sessions, pdftotext, ocrmypdf, Playwright, grey-lit packs, LLM, browser-agent extra). Green / amber / red. TTY guide for remediations (`--guide` / `--no-guide`). `--json` prints `{name, status, code, detail}` and still exits 2 when a check is red (`zotero_down`, `zotero_api_off`, `zotero_bad_host`, `zotero_no_write`, `unpaywall_email`). Empty email is red only when `unpaywall` is in `sources`. LLM disabled stays green. Missing `ocrmypdf` is amber. |
| `run` | Fill PDFs for items already in the library. Default attaches on Zotero 10+ (`--dry-run` does not). `--preset oa` drops EZProxy; `--preset eoi` is OA + EZProxy (`--upgrade-linked`, `--try-all`, `--retry-failed`, `--sources`, `--scihub`, `--strict-pdf-doi`, `--year-from` / `--year-to`, `--type` / `-T`, `--limit`). When `[llm].enabled` and the browser-agent extra is installed, appends `browser_agent` after Scholar / EZProxy / htmlpdf. Never rewrites bibliographic fields. A PDF DOI that differs from the library item still attaches, with `warn:pdf_doi_mismatch` on the Zotero note. `--strict-pdf-doi` saves the file and does not attach; `paperful attach --allow-pdf-doi-mismatch` attaches those rows later. |
| `recover` | Opt-in **browser-agent** PDF recovery (`--item KEY` repeatable, `--dry-run`, `--no-attach`). Also auto-appended as the last `run` lane when `[llm].enabled` and other vault browser lanes (Scholar, EZProxy, htmlpdf) fail. Needs Python 3.11+, `paperful[browser-agent]`, and a session vault. Manual report: `state/runs/<stamp>-recover.json`. See [LLM](llm.md#a-recover-browser-agent-pdf-recovery). |
| `lint` | Read-only identifier / PDF-DOI / title-hygiene findings (`--json`, `--strict`, `--year-from` / `--year-to`, `--type` / `-T`, `--limit`). Codes: `missing_doi`, `suspect_doi`, `swappable_doi`, `pmid_no_doi`, `pdf_doi_mismatch`, `title_html`, `title_all_caps`, `title_filename`, `no_identifier`, plus `pdf_identity_mismatch` when `[lint].llm_pdf_match` is on. Writes `state/runs/<stamp>-lint.json` (also for `--json`, before a `--strict` exit 1). |
| `fix-metadata` | Propose patches on disk; `--apply` writes them to the library (`--overwrite` replaces title, date, or venue even when you edited them — dry-run first; `--year-from` / `--year-to`, `--type` / `-T`, `--limit`). Whitelist: `doi`, `title`, `date`, `publicationTitle`. HTML title cleanup, ALL CAPS → Title Case, and verified PDF-DOI adoption included; filename titles stay lint-only unless `[fix_metadata].llm_title` proposes a grounded title (`source = "llm_title"`). Dry-run and `--apply` both write `state/runs/<stamp>-fix-metadata.json` (`patches_applied` only after `--apply`). |
| `ocr` | Text layer for scanned PDFs (`ocrmypdf`). Dry-run unless `--apply`. Rewrites the PDF under `out/` (exports a manager-only file there first). `--attach` uploads that file as a new attachment and does not trash the scan. Languages: `[ocr].languages` (default `eng`). Not in the default `all` chain; add it with `--steps`. |
| `summarize` | Grounded LLM summary from the PDF already on disk (`--item` / `-C` / `--library`, `--year-from` / `--year-to`, `--type` / `-T`, `--limit`, `--prompt FILE`, `--force`, `--to disk, zotero, or both`). Default writes `state/summaries/<key>.html` and one child note tagged `[summarize].tag`. `--to disk` skips Zotero. `--apply` requires the note and conflicts with `--to disk`. Writes `state/runs/<stamp>-summarize.json`. See [LLM](llm.md#d-summarize-grounded-summary-note). |
| `synthesize` | Literature review from existing summary notes (`--item` / `-C` / `--library`, same year/type/`--limit` flags, `--prompt`, `--to`, `--dry-run`, `--force`, `--report-collection`). Writes `state/reports/<slug>.html` and, unless `--to disk`, a standalone note in each `-C` collection. See [LLM](llm.md#e-synthesize-summary-of-summaries). |
| `dedupe` | Duplicate pack on disk (`high_doi`, then `title+year`). `--apply` merges DOI extras onto the keeper, then trashes the emptied parent; title+year needs `--apply-medium`. Held when same-DOI titles diverge. Same year/type scope flags as `run`. See [dedupe](dedupe.md). |
| `gaps` | Counts: no stored PDF, linked PDF URL only, missing DOI. Read-only. Year/type scope flags apply. Next steps are `run` and `lint`. Writes `state/runs/<stamp>-gaps.json`. |
| `all` | `gaps` → `run --try-all --retry-failed --upgrade-linked` → `lint` → `fix-metadata --apply` → `summarize --apply`. Stops on the first failure. `--dry-run` skips `summarize` and does not apply metadata. `--profile` / `-f` load a saved run config. Opens a pack when none is open. See [Workflows](workflows.md). |
| `profile` | `list` / `show` / `save` — named run configs beside `config.toml` (`profiles/<name>.toml` or `[profiles.*]`). `show` prints the merge `all` would use. `save` does not edit `config.toml`. |
| `snowball` | Grow a library from a keyword, DOI, ORCID, or collection (`search`, `hybrid`, `doi`, `orcid`, `collection`, `apply`, `run --profile`, `profile save`). `hybrid` is keyword hits then one hop. `--direction keywords` expands OpenAlex keywords (`--keyword-limit` 1–5, `--keyword-hop-limit` a positive integer; `all` is refused). Seeds with no keywords are reported and skipped on that side. Dry-run unless a writing gate is set. `approve-each` is for short lists. `fetch_pdfs` is `off`, `fast`, or `full` on the new keys only. `run` and `all` refuse `kind = snowball` profiles. [How a hop is cut](snowball.md#how-a-hop-is-cut). |
| `pack` | `open` / `close` / `show` — group the run reports from one operator sequence into `state/packs/<id>.json` (`paperful.pack.v1`). `show` does not open the library. `PAPERFUL_PACK=off` keeps a command out of the open pack. |
| `collections` | Collection tree with “No PDF” counts |
| `report` | Manifest summary + latest run report (`--last-run`, `--json`, `--not-found`, `--status`) |
| `attach` | Attach already-downloaded PDFs into the configured manager |
| `snapshot` | Write a per-item restore folder under `out/` (`record.json`, optional PDF, notes) plus index, collection tree, and ledger pointers. `--pdfs additional\|all\|none`. `--dry-run` counts without writing. Year/type scope flags apply. |
| `restore` | Recreate missing library items from those folders. Dry-run unless `--apply`. `--apply` creates missing items, attaches a local PDF when the live item has none, and adds missing notes. Does not overwrite bibliographic fields. Year/type scope flags apply. |
| `import` | Load RIS, BibTeX, or EndNote XML into the configured manager. Dry-run unless `--apply`. |
| `export` | Write the scoped library to RIS, BibTeX, or EndNote XML (`--pdfs` copies files for XML). |
| `session` | Local browser vault: `login scholar\|ezproxy\|mendeley` (`--engine` is for the browser slots), `status`, `export` |
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

`--profile NAME` loads that slice from a run config so you do not repeat
`-C` / years / `-T` on every verb. `-f` / `--run-config FILE` overlays it.
Flags you pass still win. See [Workflows](workflows.md) and
[Configuration](config.md#run-configs-profiles).

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

Same flags on `run`, `lint`, `fix-metadata`, `dedupe`, `gaps`, `ocr`, `summarize`,
`synthesize`, `snapshot`, and `restore`.

## Doctor

`paperful doctor` prints one line per check.

| Colour | Meaning |
| --- | --- |
| **green** | Ready |
| **amber** | Degraded but you can continue (empty `email`, missing EZProxy/Scholar session, no `pdftotext`, no `ocrmypdf`, Playwright/Chromium not ready, Zotero without write API, LLM enabled but daemon/model/extra not ready, small model for the browser agent) |
| **red** | Fatal if the check is `Zotero :23119`, `Mendeley API`, `EndNote library`, `out_dir`, or `state_dir` |

Unpaywall needs a real `email`. Missing sessions: `paperful session login ezproxy` or `scholar` (system Chrome/Edge when present). Missing `pdftotext`: Poppler; `pypdf` is the fallback. Missing `ocrmypdf`: `brew install ocrmypdf tesseract-lang` or `apt install ocrmypdf tesseract-ocr-eng` (the Compose image ships English). Playwright is core; Chromium installs on first `session login`. An amber Write API means Zotero 7–9: fetch still works, but `attach`, `fix-metadata --apply`, and `dedupe --apply` do not.

On a TTY (Compose sets `stdin_open` / `tty` for the build-local image), amber/red
checks open an interactive **Guide**: each step prints what to do, waits for
Enter, then re-runs that check. Session logins still need a headed browser on
the host when you run inside Docker. Force or skip with `--guide` / `--no-guide`.
Inside Docker, `docker compose run --rm paperful` with no extra args is `doctor`.

## Dry-run

`paperful run … --dry-run` talks to Zotero only (no PDF fetches). The table’s
**Would-hit** column is the source lane for that item, in order. `--try-all`
(or `source_routing = false`) lists every configured source.

`paperful dedupe` is a dry-run unless you pass `--apply`: it writes
`state/dedupe-packs/` and does not merge. Do not pass `--dry-run` and
`--apply` together.

## Exits

| Code | When |
| --- | --- |
| 0 | Success (including empty dry-run) |
| 1 | User error (unknown collection, bad preset, unknown `--phase`, `--dry-run` together with `--apply`, `--year-from` > `--year-to`, unknown `--type`, `--strict` lint findings, unknown `--item` key, LLM not enabled/misconfigured for `recover` / `summarize` / `synthesize`, `recover` on Python < 3.11, note write refused, `--to disk` together with `--apply` or `--report-collection`, `synthesize` still over budget after 3 reduce passes, `pack open` while one is open, `pack close` when none is open, unknown `--pdfs`) |
| 2 | Environment: library unreachable on `collections`, `run`, `attach`, `lint`, `fix-metadata`, `dedupe`, `gaps`, `recover`, `summarize`, `synthesize`, `snapshot`, `restore`, `import --apply`, or `export`. Prints **Next steps** (Zotero local API, or Mendeley login, or EndNote `.enl`; then `paperful doctor`) |

## Run summary

After a real `run`, a **Run summary** table lists PDFs downloaded, attached,
deferred/skipped, sources checked, and typed errors. `paperful report` reprints
it. JSON: `paperful report --json` — field list in [architecture](architecture.md#run-report-v1).

## Output

- `out/<collection>/<Author - Year - Title -- KEY>/record.json` — restore
  record (`paperful.item.v1`). Identity, full creators, abstract, tags, Extra,
  type-specific fields, collection membership, attachment rows, fetch
  provenance, and note filenames. **0.x may add keys.** `run` writes this when
  it saves a PDF. `snapshot` writes one for every scoped item, including items
  with no PDF.
- `out/<collection>/<Author - Year - Title -- KEY>/<file>.pdf` — the PDF, when
  there is one. `run` always writes downloads here. `snapshot --pdfs all` also
  exports a PDF already stored in Zotero (`origin: zotero_export`). `additional`
  (the default) does not. `none` writes records and notes only and does not
  delete PDFs already on disk.
- `out/<collection>/…/notes/` — child-note HTML. A `state/summaries/<key>.html`
  file is copied as `paperful-summary.html`.
- `out/_index.jsonl` — one line per item key (`dirs`, `has_pdf`, `md5`).
- `out/_collections.json` — collection tree.
- `out/_history.json` — pointers at the append-only ledgers under `state/`
  (manifest, patches, dedupe, runs). Sessions, cookies, and the local API key
  are not copied.
- A flat `Author - Year - Title.pdf` plus `*.paperful.json` left from an older
  run is moved into the item folder on `snapshot` or the next `run` that saves
  that file. The legacy card is folded into `record.json`.
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
- `state/dedupe-applied.jsonl` — one line per parent merged by
  `dedupe --apply` (children and better fields land on the keeper first).
- `state/pdf-cache/` — PDFs exported from the manager so lint can read text
  on disk (`pdftotext`, then `pypdf`).
- `state/last-run.json` — latest auditable `run` or `recover` report (summary + per-item
  outcomes). Other commands do not replace it. Historical copies land in
  `state/runs/<timestamp>-<command>.json` (`run`, `recover`, `gaps`, `lint`,
  `fix-metadata` for dry-run and `--apply`, `summarize`, `synthesize`).
- `state/packs/<id>.json` — parent witness for one `pack open` … `pack close`
  sequence (`paperful.pack.v1`). Steps point at filenames under `state/runs/`.
  `state/packs/current` is the open id; `PAPERFUL_PACK=off` skips appending.
- `state/summaries/` — HTML summaries from `summarize` when dest includes disk.
- `state/reports/` — `synthesize` HTML report plus a JSON sidecar of source hashes.
- `state/sessions/` — Chromium profile (`chromium/`) plus `meta.json` (no
  passwords). Gitignored; `chmod 700`. Netscape dumps also land here and as
  `ezproxy-cookies.txt` / `scholar-cookies.txt` for httpx.
- `state/zotero-local-api-key.json` — the Zotero write key if you chose
  "Always Allow".
- `state/mendeley-oauth.json` — Mendeley access/refresh tokens after
  `session login mendeley` (mode `0600`).
- `state/endnote-import/<stamp>/` — staged XML+PDF bundle for EndNote
  File → Import. Paperful never edits the `.enl` database.
