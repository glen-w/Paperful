# Releases and stability

**0.x** (including tagged `v0.9`) is a first usable release. The operator
install is clone plus `docker compose build`. The image is build-local only.
There is no `docker pull` and no `pip install paperful`. Image packs:
**light** (`[serve]` only; CI default when unset) or **heavy**
(`[serve]` `[llm]` `[rag]` `[browser-agent]`; set in `.env.example`). See
[Docker](docker.md#image-mode-light-vs-heavy).

Required keys on `paperful.run_report.v1` from `build_report()` are frozen
(removed or renamed required keys are a break; extra keys may still be added).
Required keys on `paperful.item.v1` from `empty_item_record()` are frozen the
same way. This tree is not tagged 1.0.

**1.0** (not tagged) still owes polish on the **workbench** on
`paperful serve` (screenshots, SSE, a 1.0 tag). Discover + Wanted, people lists,
briefing/digest (optional collection note), Repair/Mirror Preview→Apply,
command ids, and review tokens are in tree. **Interactive Ask** is on **Index**,
opt-in after `[rag]` + `[llm]`; Advanced **Briefs** runs summarize/synthesize.
Item records and create-missing restore are locked; extra item keys may still
be added. Required `paperful.run_report.v1` keys and imported-file attach
(typed `attach_failed`, provenance note) are already the contract. **Post-1.0:**
local OpenAlex snapshot phases beyond opt-in v1, Firefox extension,
newsletter/alert ingest — see
[ROADMAP — Product split](ROADMAP.md#product-split-10-vs-post-10).

## Schema compatibility (1.0-ready contract; package not tagged yet)

Required-key frozensets and golden fixtures live in code / `tests/fixtures/`.
Full registry and tiers: [developer.md — Disk schemas](developer.md#disk-schemas).
Extra keys may still be added on frozen schemas. The package tag may wait on
workbench polish.

| Schema | Policy | 1.0 |
| --- | --- | --- |
| `paperful.run_report.v1` | Required keys frozen (`RUN_REPORT_*_KEYS`); golden under `tests/fixtures/run_report_v1/` | Same |
| `paperful.item.v1` | Required keys frozen (`ITEM_RECORD_KEYS`); golden under `tests/fixtures/item_v1/` | Same |
| `paperful.agent.json.v1` | Required envelope keys frozen (`REQUIRED_KEYS`); nested `report` additive | Frozen envelope |
| `paperful.note.v1` | Required `block()` keys frozen (`NOTE_BLOCK_KEYS`) | Frozen |
| `paperful.refs_gap.pack.v1` | Top-level keys frozen (`REFS_GAP_PACK_KEYS`) | Frozen |
| `paperful.inbox.proposal.v1` | Top-level keys frozen (`INBOX_PROPOSAL_KEYS`) | Frozen |
| `paperful.snowball.candidate.v1` | Shipped and tested; additive keys allowed | Additive through 1.x |
| Snapshot / restore | Create-missing locked (DOI → key → title+year; no field overwrite; skip trashed/gone). Not a lossless round-trip | Same |
| Library index (`state/rag/`) | A rebuildable cache. Folder layout, ledger and table columns may change in any release; `rag ingest` rebuilds it | Not a promise |

Install claim tested in CI (`.github/workflows/ci.yml`, job `docker`): clone,
`docker compose build`, `doctor` exits 2 when Zotero is absent. That is the
release. There is no wheel and no GHCR image.

A second manager is not owed as a finished feature and **does not gate the 1.0
tag**. Mendeley and EndNote adapters are in the tree and **seeking testers**;
Zotero is the well-tested path. Until 1.0, pin a git tag or commit if you script
against JSON. See the
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

## Optional LLM at 0.5

Off by default and additive: with `[llm].enabled = false` nothing in the PDF
loop changes. Known limits: `recover` needs Python 3.11+ and a 14B-class
local model to be useful; **light** images omit the LLM extras (use
**heavy** or host `uv sync --extra llm --extra browser-agent`);
identity/title verbs need a text layer (`paperful ocr` adds one to scans). `summarize` and
`synthesize` default to writing both a disk file and a Zotero note
(`--to disk` keeps the library tree clean). Config keys under `[llm]`,
`[browser_agent]`, `[summarize]`, `[synthesize]`, `[lint]`, `[fix_metadata]` may still move
before 1.0. See [LLM](llm.md).

## What 1.0 still owes operators

| Outcome | Status at 0.9 |
| --- | --- |
| Trust inside Zotero (attachment provenance stamp) | Shipped on Zotero attachment notes. A readable parent line follows `[remarks].surface`. Manifest `source` stays the record |
| One-line end-of-run banner + write-API yes/no | Shipped (`downloaded · attached · deferred · not_found · write-api`) |
| Locked report JSON schema | Required `paperful.run_report.v1` keys frozen; additive keys still allowed. Not tagged 1.0 |
| Locked item record + snapshot/restore | Required `paperful.item.v1` keys frozen; restore is create-missing (not identity round-trip) |
| Mendeley and EndNote adapters | Not a 1.0 blocker. In the tree; seeking testers; Zotero is the well-tested path |
| Workbench GUI (Discover, Wanted, Preview/Grab) | Landed on `paperful serve` (Jinja workbench; Advanced Repair / Mirror / Discover grow / Wanted recover; review tokens; Compose `gui` profile) — [gui.md](gui.md). Not tagged 1.0 |
| Interactive Ask in GUI (cited chat-over-collection) | **Shipped** on Index (opt-in `[rag]` + `[llm]`; threads, batch, custom prompts, `rag questions` / `rag answered`); Briefs for summarize/synthesize |
| Fresh-clone doctor stays quiet without Scholar | Shipped (0.9): `scholar` opt-in like `scihub` |