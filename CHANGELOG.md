# Changelog

All notable user-facing changes. Paperful is **0.x**: flags and report fields
may still move. **1.0** will lock `paperful.run_report.v1` and attach behaviour
(see [releases](docs/releases.md)).

## Unreleased

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
