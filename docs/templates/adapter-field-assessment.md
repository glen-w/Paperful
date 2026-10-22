---
orphan: true
---

# Adapter field assessment — {{MANAGER}} ({{LIBRARY_NAME}})

**Date:** {{YYYY-MM-DD}}
**Result:** in progress | passed | blocked

Use a **copy** of a small library (roughly 10–30 parents). Do not point EndNote at your only `.enl`. Do not commit OAuth secrets or client secrets.

**Pass bar:** every checklist row below is checked or has a filed incident with repro steps. One green CI run does **not** replace this report — adapters stay **seeking testers** until a real-library report exists.

## Plan

| Field | Value |
| --- | --- |
| Manager | `mendeley` or `endnote` |
| Paperful version | `uv run paperful --version` or git SHA |
| Host OS | |
| Manager version | Mendeley Reference Manager / EndNote 20–21 / 2025 |
| Config | path to throwaway `config.toml` (no secrets in git) |
| Library copy | path to test library |

## Vendor doc oracle

**Mendeley (Elsevier)** — [dev.mendeley.com](https://dev.mendeley.com/):

- [Authorization code](https://dev.mendeley.com/reference/topics/authorization_auth_code.html) — `scope=all`, redirect URI match, refresh rotation
- [Files](https://dev.mendeley.com/overview/core_resources.html) — raw `POST /files` + `Link: rel="document"`; `GET /files/{id}` → **303** signed URL; duplicate upload **400**
- [Documents change feed](https://dev.mendeley.com/methods/) — `modified_since` / `deleted_since` ISO 8601; trash `POST /documents/{id}/trash`

**EndNote (Clarivate)** — no public write API:

- [Import EndNote Generated XML](https://docs.endnote.com/docs/endnote/2025/v1/windows/en/content/appendices/opening_an_enx_lib_w_en8or9.htm) — File → Import → **EndNote Generated XML**; Duplicates policy; Text Translation **No Translation**
- [PDF folder beside `sdb`](https://support.clarivate.com/Endnote/s/article/EndNote-Transferring-References-from-Zotero-to-EndNote) — `Library.Data/PDF/` sibling of `sdb/`, not inside it

Paperful rules: [mendeley.md](../mendeley.md), [endnote.md](../endnote.md), [ROADMAP](../ROADMAP.md) § Mendeley and EndNote.

## Shared preflight

- [ ] `manager` set in config; `paperful doctor` green (or documented amber/red with next steps)
- [ ] `paperful collections` lists expected folder/group names
- [ ] `snapshot` (or a read verb) writes under `out/` without corrupting the manager catalogue

---

## Mendeley checklist (host OAuth — not inside Docker)

Run `paperful session login mendeley` on the **host** so `http://127.0.0.1:8765/callback` reaches the CLI. Mount the same `state/` into Docker after login if you use compose.

| # | Step | Expected | OK |
| --- | --- | --- | --- |
| M1 | Register app at [dev.mendeley.com/myapps.html](https://dev.mendeley.com/myapps.html); redirect `http://127.0.0.1:8765/callback`; scope `all` | App credentials in config or env only | |
| M2 | Failed auth: remove/expire token or bad secret → `paperful collections` | Exit **2** + next-steps ladder (app → config → login → doctor) | |
| M3 | `session login mendeley` | `state/mendeley-oauth.json` mode `0600` | |
| M4 | `doctor` | **Mendeley API** green | |
| M5 | Nested folder: `collections` + `items` in scope | UUID keys; folder paths match UI | |
| M6 | Mirror-first: second read after a small edit in Mendeley | `changes(since)` delta, not full-library re-list every time | |
| M7 | Missing PDF: `run --dry-run` then `run` / `attach` | PDF in Mendeley UI; file on disk under `out/` | |
| M8 | Notes: document `notes` visible; Paperful child note (`summarize` or manual) | Re-run updates **annotation**, not duplicate rows | |
| M9 | `dedupe --apply` | Refused with clear message | |
| M10 | `attachments --link --apply` | Refused (no linked-file mode) | |

**Commands (reference):**

```sh
uv run paperful session login mendeley
uv run paperful doctor
uv run paperful collections
uv run paperful run -C '<folder>' --dry-run
uv run paperful run -C '<folder>'
```

---

## EndNote checklist (Windows or macOS desktop for import)

| # | Step | Expected | OK |
| --- | --- | --- | --- |
| E1 | Copy `.enl` + `.Data`; `[endnote] library` → copy | `doctor` **EndNote library** green | |
| E2 | `collections` while EndNote **open** (locked DB) | Reads via temp copy (`-wal`/`-shm`/`-journal` if present) | |
| E3 | Type spot-check: Journal Article in UI | Paperful `journalArticle`, **not** Bill (`reference_type` 0 in DB, 17 in XML only) | |
| E4 | Online-search group (`TYPE;6`) if present | Skipped in Paperful collections | |
| E5 | `snapshot -C '<Group>' --pdfs all` | `out/` mirrors parents + PDFs | |
| E6 | Write path: `attach` or `fix-metadata --apply` | `state/endnote-import/<stamp>/` with `paperful.xml`, `PDF/`, `README.txt` | |
| E7 | EndNote: File → Import → File… → `paperful.xml` | Import Option **EndNote Generated XML**; Duplicates per your policy; **No Translation** | |
| E8 | PDFs | Attached or import `PDF/` folder per Clarivate; paths under `.Data/PDF/` beside `sdb/` | |
| E9 | Groups after import | Rebuilt manually from **Label** field (XML has no groups) | |
| E10 | `trash` / `dedupe --apply` / `attachments --apply` | Refused; live `.eni` not edited by Paperful | |

**Commands (reference):**

```sh
uv run paperful doctor
uv run paperful collections
uv run paperful snapshot -C '<Group>' --pdfs all
# after a write command, import the printed state/endnote-import/… folder in EndNote
```

---

## Log

- (timestamps, command lines, unexpected UI behaviour)

## Incidents

| ID | Manager | Summary | Repro | Severity |
| --- | --- | --- | --- | --- |
| | | | | |

## Artifacts

- Redacted `config.toml` excerpt (no secrets)
- `state/runs/` or run report paths
- Screenshots of Mendeley UI / EndNote import dialog (no secrets)
- Bundle path: `state/endnote-import/<stamp>/` (EndNote)

## CI contract tests (repo)

Before field work, confirm unit tests pass:

```sh
uv run pytest -q tests/test_mendeley.py tests/test_endnote.py tests/test_interop.py
```

These encode Elsevier/Clarivate contracts (Accept headers, 303 without Bearer, ISO `modified_since`, XML ref-type 17 vs DB type 0, import README wording). They do **not** replace rows M1–M10 / E1–E10 above.
