# Developer guide

For people changing Paperful. Setup, tests, and pull requests are in
[CONTRIBUTING](https://github.com/glen-w/Paperful/blob/main/CONTRIBUTING.md).
The design reference is [architecture](architecture.md). This page is the
rules a change has to keep, and where things go.

## The rule: mirror first

Reference managers are flaky. Paperful copies the user's files and metadata
into its own mirror (`out/`, `state/`) and works from that copy. The manager
API is a narrow door with three uses:

1. **Refresh the mirror.** One listing of what changed.
2. **Write back when asked.** Attach, `--apply`, a note. Always explicit.
3. **Check the door.** `ping`, write support, authorize.

Anything else is a call Paperful should not make. Before adding a manager
call, ask which of the three it is. If it is none, read the mirror.

## What a command gets

`cli._connect(cfg)` is how a command opens the library. It returns a
`MirrorFirstBackend` ([`catalogue.py`](../paperful/catalogue.py)):

```text
_connect
  ├─ manager answers → run_sync (what changed) → MirrorFirstBackend(catalogue, live)
  ├─ manager down, mirror on disk → MirrorFirstBackend(catalogue, None)
  └─ manager down, no mirror → exit 2 with next steps
```

| Call on the backend | Served by |
| --- | --- |
| `collections`, `resolve_collection`, `subtree_keys`, `collection_counts` | `out/_collections.json` and the item folders |
| `items_in_scope`, `get_item`, `items_lacking_pdf` | `record.json` |
| `raw_item`, `children`, `find_child_note_keys`, `read_child_note` | `record.json` and `notes/` |
| `preview_merge` | `record.json` and `annotations.json` |
| `export_pdf` | the item folder; the manager only when the folder has no PDF |
| `apply_patch`, `attach`, `merge_into`, `trash_item`, `trash_note`, note and tag writers, `create_parent` | the manager, then that item is re-read into its folder. `trash_note` never marks the parent `_gone` |

With the manager down, the write calls raise `LibraryError` and
`supports_write()` is false. Check it before a batch and exit 2 with
`_no_write(backend)`.

Use `cli._live_backend(cfg)` only when comparing the manager with the mirror
is the command's job. Today that is `sync`, `snapshot`, `restore`, and
`attachments`.

## Rules for new code

- **A verb that only reads never needs the manager running.** Add it to
  `READ_VERBS` in `tests/test_mirror_first.py`; the test runs it with the
  manager closed.
- **A verb that writes goes through the backend it was given.** The
  write-through is in `MirroredBackend` ([`library.py`](../paperful/library.py)).
  A new write method on an adapter needs a matching method there, or the
  mirror goes stale until the next refresh.
- **Could not read is never "nothing there".** Adapter reads raise
  `LibraryReadError`. A missing key is `None`. Do not catch a read error and
  carry on with an empty list: skip the item, count it, and say so.
- **pyzotero and the raw client stay in `zot.py`, `library.py`, and
  `attach.py`.** A test enforces it. No `backend.zl` in command code.
- **Whole-library reads happen in `sync.py` and nowhere else.** If a feature
  seems to need a library listing, it needs `backend.items_in_scope(None)`,
  which is the mirror.
- **Nothing under `out/` is deleted.** An item that left is marked, or moved
  to `out/_trash/`. A folder the item no longer belongs in is folded into
  one it does (`mirror.fold_folder`).
- **Bytes from the manager go into the item folder,** not a side cache
  (`state/pdf-cache/` is only for `[mirror].pdfs = "none"`).
- **Sources never write `manifest` or `out/`.** The pipeline does.
- **`--apply` is explicit and dry-run is the default** on every verb that
  writes to the manager.

## Module map

| Module | Job | May import |
| --- | --- | --- |
| `zot.py` | Zotero client, `Item`, pure helpers | `resolve` |
| `attach.py` | Authorize and upload | `zot` |
| `library.py` | `LibraryBackend` protocol, `ZoteroBackend`, `MirroredBackend`, `ChangeSet` | `zot`, `attach` |
| `mendeley.py`, `endnote.py` | Other adapters (seeking testers) | `library` types |
| `store.py` | Manifest, filenames, record IO | `zot`, `attach` |
| `mirror.py` | Folders by key, records → `Item`, PDFs on disk, gone policy. Calls no manager | `store`, `zot` |
| `snapshot.py` | Write one item's folders from payloads (`write_item`); scoped full refresh | `mirror`, `library` |
| `sync.py` | The refresh: delta or full, version last | `snapshot`, `mirror`, `library` |
| `catalogue.py` | `MirrorCatalogue`, `MirrorFirstBackend`, `open_library` | `sync`, `mirror`, `library` |
| `scope.py` | Collection, year, type selection | `library` errors |
| `resolve/` (`ids.py`, `enrich.py`), `lint.py`, `acronyms.py`, `authors_report.py`, `metadata.py`, `dedupe.py`, `pdfid.py` | Identifier, hygiene, and corpus-frequency logic. Take a backend; never name a manager | the protocol |
| `config_tables.py` | Nested TOML sections applied onto `Config` | `config` parsers |
| `sources/` | One fetch lane each. Return bytes or a miss | `sources.base` |
| `pipeline.py` | Order the lanes, save, attach, write the manifest | most things |
| `pipeline_save.py` | Save a fetched PDF, write the manifest, attach when allowed | `store`, `pdfid` |
| `pipeline_phases.py` | OA parallel and serial fetch phases | `pipeline` helpers |
| `run_hooks.py` | EZProxy recovery, handoff, dry-run rows for `run` | `pipeline`, `handoff` |
| `gaps_cmd.py` | `gaps` body after the CLI parses flags | `handoff`, `run_hooks` |
| `run_cmd.py` | `run` body after the CLI parses flags | `pipeline`, `run_hooks` |
| `ask_cmd.py` | `ask` body after the CLI parses flags | `agent_ops`, rag |
| `completeness_cmd.py` | `dedupe`, `attachments`, `summarize`, `synthesize` after flags | `run_hooks` helpers via cli |
| `lint_cmd.py` | `lint` after flags | `lint` |
| `fix_metadata_cmd.py` | `fix-metadata` after flags | `metadata` |
| `ocr_cmd.py` | `ocr` after flags | `ocr` |
| `recover_cmd.py` | `recover` after flags | `pipeline`, `browser_agent` |
| `reachout_cmd.py` | `reachout` after flags | `reachout`, `handoff` |
| `notes_delete_cmd.py` | `notes delete` after flags | `notes` |
| `authors_cmd.py` | `authors` after flags | `authors_report` |
| `all_cmd.py` | `all` chain + step dispatch after flags | Typer wrappers via `cli` |
| `cli.py` | Flags, progress, exits. No logic of its own | everything |
| `agent_json.py` | `--format json` envelope (`paperful.agent.json.v1`) and exit 3 | none |
| `agent_ops.py` | Shared builders for CLI JSON and MCP (`gaps`, snowball dry-run / trends, `export`, refs-gap, ask) | `agent_json`, catalogue, rag, `export_build`, `pack_bib`, `snowball.trends` |
| `export_build.py` | Mirror-first interchange records for a scoped library export. Agent/MCP `export` calls this with notes off and no PDF directory. CLI `export` still builds the same overlay in `cli.py` (EndNote XML bundle and `--pdfs` live there) | `interop`, `store`, `mirror`, library protocol |
| `pack_bib.py` | BibTeX/RIS from snowball / authorwatch proposal JSONL on disk | `interop`, snowball |
| `notehtml.py` | First-line prefixes + `paperful.note.v1` comment | none |
| `notes.py` | Classify and trash Paperful-owned notes | `notehtml`, library protocol |
| `handoff_rank.py` | Missing-PDF sort: refs-gap cites × miss severity | `handoff` |
| `reachout.py` | Contact-only missing-PDF rows (metadata / Twenty emails, CSV). No fetch | `handoff`, `twenty` |
| `twenty.py` | Twenty People lookup (local cache) and `sync` (CRM create/enrich). User guide: [Twenty and SearXNG](snowball.md#twenty-and-searxng) | httpx |
| `mcp_server.py` | Optional stdio MCP: read-only gaps, snowball preview / trends, export, proposal_export, refs_gap, ask | `agent_ops` |
| `serve.py` | Localhost FastAPI: JSON capability API + mounts `ui` when the `serve` extra is installed | `agent_ops`, `ui` |
| `ui/` | Server-rendered workbench (Jinja). `app.py` mounts HTML + form POSTs; ordinary pages do not run `doctor` (System does). `jobs.py`, `wanted_jobs.py`, `repair_jobs.py`, `discover_jobs.py` call the same domain entrypoints as the CLI; review tokens under `state/gui/reviews/`; command ids under `state/gui/commands/` | CLI / MCP builders |
| `authorwatch.py` | People lists → OpenAlex new works; `gather_briefing` / `write_briefing` (inbox + recent works / co-authors); `apply` creates parents; `accept` / `delete` | OpenAlex client, `identity`, `snowball.ingest`, `authorwatch_suggest` |
| `authorwatch_suggest.py` | Corpus / cited / coauthor / mix suggestions → `suggestions.jsonl`; shared co-author accumulation for briefing | `authors_report`, OpenAlex, promoted packs |
| `authorwatch_social.py` | Parse operator-saved RG / LinkedIn / Academia HTML or CSV (no network) | stdlib HTML/CSV |
| `snowball/` | Crawl, hops, watch, thin briefing, frontier digest, `trends` (OpenAlex `group_by` year counts). Watch, digest, and trends do not create library items | OpenAlex; library protocol only on apply |

## The refresh

`run_sync` ([`sync.py`](../paperful/sync.py)):

1. `backend.changes(since)` — rows changed after the stored library version
   (all rows on a first or `--full` refresh), the keys now in the library,
   the trash, the collections. Zotero's local API leaves trashed items out
   of listings and has no `/deleted`; a removal is a key that stopped being
   listed.
2. Work out which parents are affected: changed themselves, a child changed,
   or a child key the index knew is gone.
3. Rewrite each one with `snapshot.write_item` (`exact=True`: the item's
   whole collection membership is known, so folders move and fold).
4. Mark or move parents that left (`mirror.retire`). Refused when more than
   half the mirror would go: that is a different library.
5. Write `out/_sync.json`. **Last.** If any item could not be read, the
   version does not move and the next refresh covers the same ground.
6. With `[mirror].pdfs = "all"`, copy PDFs (`copy_pdfs`). Whole library until
   it has completed once, then changed items only.

Every step can be repeated. A crash leaves valid records and an old version.

## Disk schemas

Tier policy (1.0-ready contract; package tag may still wait on workbench polish):

| Tier | Policy |
| --- | --- |
| **T0 Trust** | Required keys frozen in code (`*_KEYS`); rename/remove is a break; extras additive. Golden fixtures under `tests/fixtures/` |
| **T1 Agent packs** | Same for top-level keys used by scripts |
| **T2 Additive** | Schema string stable; keys may grow; no frozenset required |
| **T3 Cache** | Layout may change any release; rebuild with `rag ingest` |

| Schema | Location | Writer | Tier | Frozenset / golden |
| --- | --- | --- | --- | --- |
| `paperful.item.v1` | `out/.../record.json` | `store` / `snapshot` | T0 | `ITEM_RECORD_KEYS`; `tests/fixtures/item_v1/` |
| `paperful.run_report.v1` | `state/runs/*.json`, `state/last-run.json` | `runreport` | T0 | `RUN_REPORT_*_KEYS`; `tests/fixtures/run_report_v1/` |
| `paperful.agent.json.v1` | stdout `--format json` | `agent_json` | T0 | `REQUIRED_KEYS`; `tests/fixtures/agent_json*` |
| `paperful.note.v1` | HTML comment in child notes | `notehtml` | T0 | `NOTE_BLOCK_KEYS`; `tests/fixtures/note_v1/` |
| `paperful.refs_gap.pack.v1` | `state/refs-gaps/<stamp>/pack.json` | `refs_gap` | T1 | `REFS_GAP_PACK_KEYS`; `tests/fixtures/refs_gap_pack_v1/` |
| `paperful.inbox.proposal.v1` | `state/inbox/proposals/*.json` | `inbox_match` | T1 | `INBOX_PROPOSAL_KEYS`; `tests/fixtures/inbox_proposal_v1/` |
| `paperful.sync.v1` | `out/_sync.json` | `sync` | T2 | — |
| `paperful.annotations.v1` | `annotations.json` | `snapshot` | T2 | — |
| `paperful.collections.v1` | `out/_collections.json` | `store` | T2 | — |
| `paperful.history.v1` | item history sidecar | `store` | T2 | — |
| `paperful.standalone.v1` | standalone catalogue | `sync` | T2 | — |
| `paperful.pack.v1` | `state/packs/<id>.json` | `pack` | T2 | — |
| `paperful.dedupe_pack.v1` | `state/dedupe-packs/` | `dedupe` | T2 | — |
| `paperful.version_pack.v1` | `state/version-packs/` | `versions` | T2 | — |
| `paperful.ingest_dois.v1` | `state/ingest/<stamp>/` | `ingest_dois` | T2 | — |
| `paperful.collections_add.v1` | `state/collections-add/<stamp>/` | `collections_add` | T2 | — |
| `paperful.acronyms.v1` | `state/acronyms/<scope>.json` | `acronyms` | T2 | — |
| `paperful.authors_report.v1` | `state/reports/<slug>-authors.json` | `authors_report` | T2 | — |
| `paperful.author_pack.v1` | `state/author-packs/` | `snowball.authors` | T2 | — |
| `paperful.author_contact.v1` | `state/author-contacts/` | `twenty` | T2 | — |
| `paperful.author_request.v1` | reachout / request ledger | `author_request` | T2 | — |
| `paperful.authorwatch.v1` | `state/authorwatch/<name>/watch.json` | `authorwatch` | T2 | — |
| `paperful.authorwatch.person.v1` | `state/authorwatch/<name>/people.jsonl` | `authorwatch` | T2 | — |
| `paperful.authorwatch.suggestion.v1` | `state/authorwatch/<name>/suggestions.jsonl` | `authorwatch_suggest` | T2 | — |
| `paperful.snowball.candidate.v1` | `state/snowball/<run-id>/` | `snowball.candidate` | T2 | Additive through 1.x |
| `paperful.snowball.watch.v1` | snowball watch cursor | `snowball.watch` | T2 | — |
| `paperful.snowball.coauthors.v1` | co-author graph | `snowball.authors` | T2 | — |
| `paperful.htmlpdf.proposal.v1` | `state/htmlpdf/proposals/` | `sources.htmlpdf` | T2 | — |
| `paperful.synthesis.v1` | synthesize sidecar | `synthesize` | T2 | — |
| `paperful.ask_batch.v1` | `state/ask-batch/<stamp>/` | `rag.batch` | T2 | — |
| `paperful.rag.thread.v1` | `state/rag/threads/*.json` | `rag.thread` | T2 | — |
| `paperful.rag.questions.v1` | `state/rag/questions/` | `rag.questions` | T2 | — |
| `paperful.rq_answered.v1` | `state/rq-answered/` | `rag.answered` | T2 | — |
| `paperful.rag.text.v1` | extracted text cache | `rag.extract` | T3 | Rebuildable |
| `paperful.rag.index.v1` | LanceDB meta | `rag.index` | T3 | Not a promise |
| `paperful.e2e_stack.report.v1` | e2e stack reports | `e2e_nba` | T2 | Internal / CI |

**Consumers:** `recover --from-last-run`, GUI Activity, and `agent_ops` read `paperful.run_report.v1` (`state/last-run.json`). `restore` requires `paperful.item.v1`. Batch verbs and optional `paperful mcp` emit `paperful.agent.json.v1`.

The catalogue rebuilds an `Item` from a record. The test
`test_item_from_record_matches_the_live_listing` holds the two equal field
for field. A new `Item` field needs a home in the record and a case there.
Contract tests: `tests/test_schema_freeze.py`.

## Adding things

**A read verb.** `backend = _connect(cfg)`, `_load_scope(backend, …)`, do
the work, write a run report. Add it to `READ_VERBS`. Disk-only verbs such as
`authorwatch save` still belong there so a closed manager is not an accident.

**A write verb.** Same, dry-run by default. Before applying:
`if not backend.supports_write(): _exit_env(_no_write(backend), cfg)`.

**A source.** Subclass in `paperful/sources/`, register it, return a
`PageResult`. It gets a `Context`; it does not get the manifest or `out/`.

**An adapter method.** Ask first whether the mirror can serve it. If it is a
read, add it to `MirrorCatalogue`. If it is a write, add it to the adapter,
to `MirroredBackend` (refresh the item after), and to `MirrorFirstBackend`
(pass through, refuse offline).

**A manager.** Implement `LibraryBackend`. With a `changes(since)` method it
gets the mirror-first path for free. Zotero, Mendeley, and EndNote all
expose one. Without one, reads stay live.

## Tests

`uv run pytest` runs offline. `tests/conftest.py` refuses every request a
real Zotero client makes, so a Zotero running on your machine is never read
by a test.

| Fake | Use |
| --- | --- |
| `tests/test_sync.py::FakeZotero` | A library with versions, a trash, and call counts. For the refresh and the catalogue |
| `tests/conftest.py::FakeListing` | Mixin for a stub client that lists `Item` objects. For CLI tests |
| `tests/test_write_through.py::FakeLibrary` | A manager with write calls. For `MirroredBackend` |

Count requests when the point of a change is fewer of them: `FakeZotero.calls`.

### CI and local pitfalls

GitHub Actions (`.github/workflows/ci.yml`) runs `uv sync --group dev --extra
serve` and `uv run pytest` on Ubuntu. A second job builds the Compose image and
smokes `paperful doctor`; it can pass while pytest fails, so check the **test**
job when CI is red.

**CLI help assertions.** On CI, `CI` / `GITHUB_ACTIONS` is set and Typer/Rich
style option names with ANSI codes. A flag like `--apply` is often split across
escape sequences, so `assert "--apply" in result.stdout` fails even though help
is correct. Strip SGR codes with `tests.textutil.plain_text` before matching
tokens (see the comment in that module). For table layout, several CLI test
modules widen the shared `cli.console` (`width=250`) so Rich does not ellipsize
cells — follow `tests/test_cli.py` when adding help or table assertions.

**Dev sync and LanceDB.** `uv sync --group dev` pulls `lancedb` for index/RAG
tests. PyPI wheels cover Linux x86_64/arm64, Windows, and **macOS arm64**; there
is no wheel for every macOS x86_64 / OS combo. If sync fails with “no wheel for
the current platform”, use native **arm64** Python on Apple Silicon, run pytest
inside the Linux dev container / CI image, or temporarily sync without the dev
group only when you are not touching RAG tests.

**Pytest inside Compose.** The runtime image is for operators (`paperful …`), not
the full dev test suite. Reproduce CI with host `uv run pytest` or a
`python:3.12-slim` container plus `uv sync --group dev --extra serve`. Do not
expect host-only tests (for example default Zotero endpoint URLs) to pass when
`PAPERFUL_ZOTERO_HOST` is set for container → host networking.

**Docs CI.** Pushes that change `docs/` or `website/` also run strict Sphinx
(`DOCS_STRICT=1`) and may deploy Pages; new guide pages must be linked from
`docs/index.md` (`tests/test_sphinx_docs.py`).
