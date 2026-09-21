# Changelog

All notable user-facing changes. Paperful is **0.x**: flags and report fields
may still move. **1.0** will lock `paperful.run_report.v1`, `paperful.item.v1`,
and attach behaviour (see [releases](docs/releases.md)).

## Unreleased

When `[llm].enabled` and `paperful[browser-agent]` are on, `run` appends the
`browser_agent` lane after Scholar / EZProxy / htmlpdf and fires it only if
one of those vault lanes was tried and failed. Playwright releases the
session profile before browser-use starts. `paperful recover --item` still
targets named keys. `[browser_agent].during_run = false` turns the auto-lane
off. `browser_agent` stays out of `DEFAULT_SOURCES`.

`paperful all` runs the usual operator chain in one process: `gaps`, then
`run --try-all --retry-failed --upgrade-linked`, `lint`, `fix-metadata
--apply`, and `summarize --apply`. It stops on the first failure. Named run
configs (`paperful profile save`, `[profiles.*]`, `profiles/<name>.toml`
beside `config.toml`) store that SCOPE and those flags. `--profile` also
works on the individual verbs. This is not a grey-lit playbook and not a
pack. See [Workflows](docs/workflows.md).

Public pitch is a local library sidecar: disk ledger first, Zotero as the
live catalogue. **Zotero is the well-tested adapter.** Mendeley and EndNote
are in the tree and seeking testers — not the supported path. See
[Why paperful](docs/why.md), [Mendeley](docs/mendeley.md), and
[EndNote](docs/endnote.md). `paperful import` / `export` move RIS, BibTeX,
and EndNote XML. Mendeley PDF download follows the 303 to object storage
without the API token. EndNote reads SQLite `reference_type` (not XML
numbers) and group membership from `groups.spec` / `members`. The comparison
pages now include
`snapshot` / `restore`, grey-literature playbooks, and opt-in `summarize` /
`synthesize`, and they point scan OCR and chat agents at zotero-agent and
zotero-mcp.

`paperful pack open` / `close` / `show` groups one operator sequence into
`state/packs/<id>.json` (`paperful.pack.v1`). `gaps`, `lint`, `summarize`, and
`fix-metadata` (including dry-run) now write `state/runs/<stamp>-<command>.json`
and leave `state/last-run.json` to `run` and `recover`. `PAPERFUL_PACK=off`
keeps a command out of the open pack.

`synthesize` writes a literature review from existing `summarize` notes
(`state/reports/<slug>.html` and, by default, a standalone note in the
collection). `summarize` and `synthesize` take `--to disk|zotero|both`
(default `both`); `--to disk` leaves the Zotero tree clean. `--apply` on
`summarize` still requires a note and conflicts with `--to disk`. Ollama
calls from those two verbs set `num_ctx` from the prompt, capped by
`[llm].max_num_ctx`.

Browser session Playwright work runs on a dedicated thread so parallel OA
downloads no longer trip ``Cannot switch to a different thread`` (which left
Scholar/EZProxy as immediate ``browser (error)`` misses).

`--year-from` / `--year-to` and `--type` / `-T` restrict collection-scoped
commands (`run`, `lint`, `fix-metadata`, `dedupe`, `gaps`, `summarize`,
`synthesize`, `snapshot`, `restore`) by publication year and Zotero item type. `summarize --apply` creates child notes
without pyzotero's `item_template()` (the Zotero local API has no `/items/new`).
`fix-metadata` recases ALL CAPS scholarly titles to Title Case; filename
titles stay lint-only.

Sci-Hub skips items dated after 2021 (and drops from the run when
`--year-from` is past that coverage year), matching thin post-2021 ingest.

`paperful snapshot` writes a per-item restore folder under `out/`
(`record.json`, optional PDF, notes) plus an index, collection tree, and
ledger pointers. `[mirror].pdfs` is `additional` (default), `all`, or `none`.
`paperful restore` is a dry run until `--apply`, and `--apply` only creates
what is missing. A flat PDF plus legacy `*.paperful.json` card is moved into
the item folder.

## 0.5.0 — 2026-09-21

Optional local-first LLM is off by default (Ollama on loopback; LiteLLM via
`paperful[llm]`). `fix-metadata` can propose grounded titles; `lint` can flag
PDF identity mismatches; `summarize` writes `state/summaries/` and `--apply`
updates a tagged Zotero child note. `recover` is a separate browser-agent
lane (`paperful[browser-agent]`, Python 3.11+), not part of `run`. `out/` is
documented as a quiet collection-shaped PDF mirror; house sync stays outside
paperful.

`paperful dedupe` writes a collection-scoped duplicate pack (normalised DOI,
then title+year) and trashes only on `--apply`. Same-DOI groups with divergent
titles are held. Title+year groups need `--apply-medium`. `paperful gaps`
counts missing PDFs, linked-URL-only items, and missing DOIs. Crossref
year-backfill ingest and CRM contact scans stay outside this tool.

Publisher PDF URLs that Unpaywall / OpenAlex / Semantic Scholar “find” often
403 on a cookie-only GET (Elsevier ScienceDirect especially). `run` now
retries those through the session Chromium profile, wrapping the URL in
EZProxy when `ezproxy_base` is set. A publisher host that already 403’d is
not tried again by the next OA source. EZProxy landing pages use the same
profile when it exists.

## 0.3.0 — 2026-09-10

Usual path is `uv`. Docker Compose is an optional one-shot image (Python +
Poppler + Chromium); Zotero and headed `session login` stay on the host. Bare
`docker compose run --rm paperful` is `doctor`.

`paperful doctor` walks amber/red remediations on a TTY (`--guide` /
`--no-guide`). Playwright is a core dependency; Chromium installs on first
`session login`. Login prefers system Chrome/Edge (CDP) so Google SSO works;
`--engine playwright` is the fallback.

## 0.2.0 — 2026-09-10

Docker Compose is the preferred operator deploy: one-shot CLI image talks to
host Zotero (`PAPERFUL_ZOTERO_HOST` / Host-header fix for
`host.docker.internal`), durable data outside the repo. Optional
`grey_playbooks_dir` loads extra pack TOML files (merged after builtin, before
inline). See [Docker](docs/docker.md).

## 0.1.0 — 2026-09-10

First usable local Zotero gap-filler: `doctor` → `collections` → `run --dry-run`
→ `run` → `report`.

### Known limits (not 1.0 yet)

- End-of-run **summary table** exists; a one-line banner
  (`downloaded N · attached M · deferred K · not_found J` plus write-API yes/no)
  is not locked yet.
- Attachments are **not** stamped with source provenance
  (`oa:unpaywall` / `campus:ezproxy` / `grey:undocs`) in Zotero notes.
- `paperful.run_report.v1` is the current JSON shape; treat extra keys as
  additive until 1.0.
- Collection resolve failures print the spec; they do not yet suggest closest
  paths.

### Honest defaults

- Sci-Hub is opt-in and off by default.
- Zotero 7–9: download to disk only; attach needs Zotero 10+.
- `--preset eoi`: open access + campus EZProxy (no Scholar, no Sci-Hub).
