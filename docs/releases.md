# Releases and stability

**1.3.1** is the current release (`pip install paperful` after this tag is published; optional extras
`[llm]`, `[rag]`, `[serve]`, `[browser-agent]`). **1.1.0** introduced PyPI and
trusted publishing. After install, run `playwright install chromium` once for
campus login and HTML PDF paths. The **operator** install tested in CI is still
clone plus `docker compose build` on your computer (see [Docker](docker.md)).

**1.0.0** is tagged. Required schemas are frozen in this tree.
Image packs: **light** (`[serve]` only; CI default
when unset) or **heavy** (`[serve]` `[llm]` `[rag]` `[browser-agent]`; set in
`.env.example`). See [Docker](docker.md#image-mode-light-vs-heavy).

Required keys on `paperful.run_report.v1` from `build_report()` are frozen
(removed or renamed required keys are a break; extra keys may still be added).
Required keys on `paperful.item.v1` from `empty_item_record()` are frozen the
same way.

**1.0** is CLI honesty plus the operator workbench. Screenshots and
walkthroughs are in the guide ([Walkthroughs](walkthroughs.md)). Discover + Wanted, people lists,
briefing/digest (optional collection note), Repair/Mirror Preview→Apply,
command ids, review tokens, and Activity run-status SSE (`GET /v1/runs/{id}/events`)
are in tree. **Interactive Ask** is on the default nav (`/ask`),
opt-in after `[rag]` + `[llm]`. Batch Ask is on that page when Advanced is on.
Advanced **Index** is ingest, search, and question extracts. **Briefs** runs
summarize/synthesize.
Item records and create-missing restore are locked; extra item keys may still
be added. Required `paperful.run_report.v1` keys and imported-file attach
(typed `attach_failed`, provenance note) are the contract. **1.1.1** shipped
Wanted stop-ship hygiene (Grab scope, Attach at zero, copy). Everything after
that is a buffet by area (Wanted excellence first, testers before new features).
**1.3.1** hardens local-trust boundaries (PDF fetch SSRF checks, review-token
sanitization, non-loopback `serve` gate, redacted witness digests; see
[SECURITY.md](../SECURITY.md)) and adds Mendeley/EndNote adapter contract tests
plus a field-assessment template for testers. **1.3.0** adds the optional
unsigned [Firefox add-on](firefox.md): save the open page or selected tabs into
`out/`. Local OpenAlex snapshot phases beyond
opt-in v1 and the alert loop stay later — see
[ROADMAP — Product split](ROADMAP.md#product-split-10-vs-post-10)
and [After 1.1.0](ROADMAP.md#after-110-buffet-by-area).

## Schema compatibility (1.0 contract)

Required-key frozensets and golden fixtures live in code / `tests/fixtures/`.
Full registry and tiers: [developer.md — Disk schemas](developer.md#disk-schemas).
Extra keys may still be added on frozen schemas.

| Schema | Policy | 1.0 |
| --- | --- | --- |
| `paperful.run_report.v1` | Required keys frozen (`RUN_REPORT_*_KEYS`); golden under `tests/fixtures/run_report_v1/` | Same |
| `paperful.item.v1` | Required keys frozen (`ITEM_RECORD_KEYS`); golden under `tests/fixtures/item_v1/` | Same |
| `paperful.agent.json.v1` | Required envelope keys frozen (`REQUIRED_KEYS`); nested `report` additive | Frozen envelope |
| `paperful.note.v1` | Required `block()` keys frozen (`NOTE_BLOCK_KEYS`) | Frozen |
| `paperful.refs_gap.pack.v1` | Top-level keys frozen (`REFS_GAP_PACK_KEYS`) | Frozen |
| `paperful.coverage.pack.v1` | Top-level keys frozen (`COVERAGE_PACK_KEYS`) | Frozen |
| `paperful.witness.v1` | Optional on run reports; additive (not in `RUN_REPORT_KEYS`) | Additive |
| `paperful.inbox.proposal.v1` | Top-level keys frozen (`INBOX_PROPOSAL_KEYS`) | Frozen |
| `paperful.snowball.candidate.v1` | Shipped and tested; additive keys allowed | Additive through 1.x |
| Snapshot / restore | Create-missing locked (DOI → key → title+year; no field overwrite; skip trashed/gone). Not a lossless round-trip | Same |
| Library index (`state/rag/`) | A rebuildable cache. Folder layout, ledger and table columns may change in any release; `rag ingest` rebuilds it | Not a promise |

Install claim tested in CI (`.github/workflows/ci.yml`, job `docker`): clone,
`docker compose build`, `doctor` exits 2 when Zotero is absent. That
clone-and-build path is the release.

A second manager is not owed as a finished feature and **does not gate 1.0**.
Mendeley and EndNote adapters are in the tree and **seeking testers**;
Zotero is the well-tested path. Pin a git tag or commit if you script against
JSON. See the
[changelog](https://github.com/glen-w/Paperful/blob/main/CHANGELOG.md) for
known limits. See [Why Paperful](why.md).

## Ladder

```text
doctor → collections → run --dry-run → run → report / report --json
```

`--dry-run` lists each item and a **Would-hit** column (sources that routing
would try, in order). It does not download. Narrow with `--collection` /
`--library`, plus optional `--year-from` / `--year-to` and `--type` / `-T`
([Commands — Scope filters](commands.md#scope-filters)).

When Zotero is down, `collections`, `run`, `attach`, `lint`, `fix-metadata`,
`dedupe`, `gaps`, `recover`, `summarize`, and `synthesize` exit **2** and print the same
next-steps ladder (`paperful doctor`, enable local API, copy
`config.example.toml`).

## Optional LLM

Off by default and additive: with `[llm].enabled = false` nothing in the PDF
loop changes. Known limits: `recover` needs Python 3.11+ and a 14B-class
local model to be useful; **light** images omit the LLM extras (use
**heavy** or host `uv sync --extra llm --extra browser-agent`);
identity/title verbs need a text layer (`paperful ocr` adds one to scans). `summarize` and
`synthesize` default to writing both a disk file and a Zotero note
(`--to disk` keeps the library tree clean). Config keys under `[llm]`,
`[browser_agent]`, `[summarize]`, `[synthesize]`, `[lint]`, and `[fix_metadata]`
are part of the 1.0 surface (additive extras allowed). See [LLM](llm.md).

## What 1.0 includes

| Outcome | Status |
| --- | --- |
| Trust inside Zotero (attachment provenance stamp) | Shipped on Zotero attachment notes. A readable parent line follows `[remarks].surface`. Manifest `source` stays the record |
| One-line end-of-run banner + write-API yes/no | Shipped (`downloaded · attached · deferred · not_found · write-api`) |
| Locked report JSON schema | Required `paperful.run_report.v1` keys frozen; additive keys still allowed |
| Locked item record + snapshot/restore | Required `paperful.item.v1` keys frozen; restore is create-missing (not identity round-trip) |
| Mendeley and EndNote adapters | Not a 1.0 blocker. In the tree; seeking testers; Zotero is the well-tested path |
| Workbench GUI (Discover, Wanted, Preview/Grab) | Shipped on `paperful serve` (Jinja workbench; Wanted first; Grab fetches to disk, Attach writes the library; Advanced Repair / Mirror / Index / Briefs; review tokens; `docker compose up` at `127.0.0.1:8765`) — [gui.md](gui.md) |
| Interactive Ask in GUI (cited chat-over-collection) | **Shipped** on the default nav (`/ask`; opt-in `[rag]` + `[llm]`; threads, batch when Advanced, custom prompts). Index is ingest/search/`rag questions`/`rag answered`. Briefs for summarize/synthesize |
| Fresh-clone doctor stays quiet without Scholar | Shipped: `scholar` opt-in like `scihub` |

## Known limits (1.0)

These stay true after the tag. They are not unfinished 1.0 work.

- Restore is create-missing, not a lossless round-trip.
- Mendeley and EndNote stay seeking testers; Zotero is the well-tested path.
- Provenance notes are Zotero-only.
- Open-access fill is DOI-scoped; Unpaywall often returns a landing page.
  Grey literature is configured playbooks only. Sci-Hub is opt-in and thin
  after ~2021.
- Report-only `attachments` reads children from the mirror (1.3.1); `--apply`
  still needs the manager.
- The RAG index (`state/rag/`) is a rebuildable cache, not a layout promise.
- TTY stays the shell for `session login`, `doctor --guide`, mid-run EZProxy,
  and Sci-Hub.

Full list: [CHANGELOG](../CHANGELOG.md) (1.0.0).
