# Changelog

All notable user-facing changes. Paperful is **0.x** and is not tagged 1.0.
Required `paperful.run_report.v1` keys are frozen; extra report keys may still
be added. Required `paperful.item.v1` keys are frozen the same way (additive
extras allowed). This tree is not tagged 1.0. See [releases](docs/releases.md).

## Unreleased

### Added

- **Docs / site:** GUI-first landing and README (local workbench, not
  “CLI sidecar”). Playwright screenshots of Wanted, Discover, Repair,
  Index, and Index Ask (a live `ocean/BBNJ` thread with a cited answer) on
  [paperful.app](https://paperful.app/) and in the guide.
  Walkthroughs: [first fill](docs/first-fill.md),
  [grow the library](docs/grow-library.md),
  [tidy a collection](docs/tidy-library.md). Recapture:
  `scripts/docs/capture_workbench.py`.
- **`paperful coverage`:** briefing / note / file DOI lists vs `-C` membership
  (`in_collection` / `missing` / `ambiguous`). Always dry-run; pack under
  `state/coverage/` (`paperful.coverage.pack.v1`). `ingest-dois --from-pack`
  accepts coverage packs. Sibling of `refs gap`.
- **Run witness:** optional `witness` (`paperful.witness.v1`) on every
  `paperful.run_report.v1` — config SHA-256, Paperful version, profile, scope,
  fetch sources, LLM/RAG tip. Pack steps record `witness_id`. Not part of the
  required `RUN_REPORT_KEYS` freeze. `refs gap`, `coverage`, and `snowball apply`
  write command reports so they join the pack trail.
- **CORE doctor check:** green either way — reports whether `core_api_key` is
  set (optional OA lane already in `DEFAULT_SOURCES`).
- **GUI run SSE:** `GET /v1/runs/{id}/events` pushes command status until
  `done`/`failed`; workbench Activity uses `EventSource` with JSON poll fallback.
  See [gui.md](docs/gui.md#run-status-sse).
- **Literature-discovery Wave 1 (roadmap row 22):** `paperful mcp` adds read-only
  `gaps`, `snowball_search`, `export`, and `proposal_export` (same
  `paperful.agent.json.v1` builders as CLI). `paperful export-proposals` writes
  BibTeX/RIS from `state/snowball/<run>/candidates.jsonl`, watch/authorwatch
  `inbox.jsonl`, or a pack directory. Snowball `--format json` on dry-run loads
  `summary.json` when the in-memory summary is empty.
- **OpenAlex study design filters:** snowball `--study-design` / `[snowball].study_designs`
  (`rct`, `meta-analysis`, `systematic-review`, …) pushes
  `filter=study_designs.id:…` into OpenAlex search, citing, keyword, and author
  queries, and keeps a client-side guard on candidates. See
  [OpenAlex blog](https://blog.openalex.org/filter-openalex-for-rcts-meta-analyses-and-systematic-reviews/)
  and [snowball stop rules](docs/snowball.md#stop-rules).
- **`paperful authorwatch suggest` / `accept` / `delete`:** corpus-grounded people
  suggestions (`--method corpus|most_cited|coauthor|mix`, `-C`, `--limit`);
  `accept --id` (+ optional `--seed-from` backfill run). Social
  `import --source rg|linkedin|academia --file` parses saved HTML/CSV (no live
  scrape). Discover: suggestion checkboxes, member edit, delete list. Ledger:
  `suggestions.jsonl`. Roadmap row 21 shipped. See [authorwatch.md](docs/authorwatch.md).
- **Docker light/heavy packs:** `PAPERFUL_IMAGE_MODE=light` (default; `[serve]`
  only, CI) or `heavy` (`[serve]` `[llm]` `[rag]` `[browser-agent]`). Set in
  `.env` for a full local image; `make docker-build-heavy`. See [docker](docs/docker.md).
- **GUI CLI parity (Wanted / Repair / Mirror / Discover):** Repair and Mirror
  Preview run dry-run then Apply invokes the same domain entrypoints as the CLI
  (`lint`, `fix-metadata`, `dedupe`, `versions`, `attachments`, `ocr`, `sync`,
  `snapshot`, `restore`, `cache clean`). Wanted Advanced: attach, recover,
  handoff, inbox drain, reachout, Grab year/type/retry/browser-agent flags.
  Discover Advanced: crawl knobs (including Twenty writeback), profile save,
  refs gap, ingest-dois, authors, packs promote; queue/watch briefing and
  digest can file a collection note (`paperful:frontier-briefing`). Route
  table: [gui.md](docs/gui.md).
- **GUI thickening:** Index runs `rag ingest`, `rag search`, batch Ask, and collection
  `synthesize`; Advanced **Briefs** runs collection `summarize` / `synthesize`.
  Per-item summarize in Wanted/Library drawers (`/item/{key}/summary`, `/wanted/summarize`).
  Discover: snowball kinds (search/hybrid/doi/orcid/collection), keep/skip, profile run,
  resume, queue briefing/digest, watch via `save_watch` (profile required);
  authorwatch list create/add/remove/resolve/run/import/suggest/accept/delete +
  people briefing; Preview apply before snowball/inbox apply. Route table:
  [gui.md](docs/gui.md).
- **Repair / Mirror (Advanced):** Preview runs real library cores and writes review
  tokens under `state/gui/previews/`; Apply consumes the token (409 when the preview
  file changed). Covers `lint` (read-only), `fix-metadata`, `dedupe`, `versions`,
  `attachments`, `ocr`, plus `sync`, `snapshot`, `restore`, and `cache clean`.
- **Index RAG/ask CLI parity:** Ask and batch Ask take item keys, types, years, top-k,
  and custom system prompts (inline → upload → path → `state/prompts/` → `[rag].prompt`
  / focus). Batch adds force and questions file upload. Index also runs
  `rag questions` and `rag answered` (`state/rq-answered/`, `pack.md`). See
  [rag.md](docs/rag.md#workbench-advanced-index) and [gui.md](docs/gui.md).

### Changed

- **Docs screenshots:** workbench stills show forms in use (selected Wanted
  rows, Discover query, Index search + Ask), not empty landing pages.
  Recapture: `scripts/docs/capture_workbench.py`.
- **Wanted row ticks:** Preview / Grab / Attach labels switch to “selected”
  when table checkboxes are ticked (they sit outside `#wanted-form` and
  point at it with the `form` attribute).
- **Workbench chrome:** product box mark + Nunito wordmark top-left; cream paper,
  Fraunces / Nunito / Source Sans 3, and accent buttons match the public site.
- **Library collections:** nested `<details>` groups by path (AO → Mini meta
  studies → Coffee); item counts no longer render as a dict `.items` method.
  Parent rows no longer treat the disclosure marker as a grid cell, so names,
  item counts, and missing-PDF counts line up with the column headers.
- **Compose `up` → GUI:** `docker compose up` serves the workbench at
  http://127.0.0.1:8765 (assumes setup done). CLI one-shots stay
  `docker compose run --rm paperful <cmd>`. `compose.gui.yaml` is a no-op shim.
- **Docker doctor guide:** default `doctor` inside Compose no longer waits for
  Enter. It prints fix steps once; opt in with
  `docker compose run --rm paperful doctor --guide`.
- **Schema freeze prep for 1.0:** `RUN_REPORT_SUMMARY_KEYS` now includes always-emitted
  rollups (`retryable`, `browser_misses`, `not_downloaded`, `paywall_prices`,
  `agent_after_playwright`). Frozen top-level keys for `refs_gap.pack.v1`,
  `inbox.proposal.v1`, and `note.v1`. Golden fixtures under `tests/fixtures/` and
  `tests/test_schema_freeze.py`. Registry + tiers in [developer.md](docs/developer.md);
  releases revisit rows resolved. Package not tagged 1.0 yet.
- **Docs:** command reference covers `urls`, `htmlpdf`, `cache`, and `jobs`.
  Workbench pages, the public install snippet, and `paperful serve --help`
  match Grab (disk only) → Attach (library write), `docker compose up` (no
  `gui` profile), and loopback-only `PAPERFUL_OLLAMA_HOST` rewrites.
  See [gui.md](docs/gui.md) and [commands.md](docs/commands.md).
- **Roadmap / 1.0 scope:** 1.0 now includes the workbench GUI (illuminate and
  run CLI workflows) and interactive Ask (chat-over-collection RAG in the GUI).
  Post-1.0: local OpenAlex snapshot phases 2B/2C, Firefox extension,
  newsletter/alert ingest (rollup bridge). See [ROADMAP](docs/ROADMAP.md#product-split-10-vs-post-10).
- **Roadmap / adapters:** Mendeley and EndNote no longer gate 1.0; docs stay
  honest (seeking testers; Zotero well-tested).
- BBNJ author-site / authorwatch dogfood plan: [bbnj-author-lanes](docs/bbnj-author-lanes.md)
  (`-C ocean/BBNJ`, test sibling `ocean/BBNJ-test`). Workflows pack slug is
  `ocean-bbnj`, not `bbnj`.
- `authorwatch run` maps a spent OpenAlex daily budget to exit 2 with a retry
  line (no traceback).
- **Workbench health chip:** ordinary HTML pages no longer run full `doctor`
  (was 15–30s and felt like an endless load). The chip stays amber until
  **System** refreshes it; `/system` still runs doctor. See [gui.md](docs/gui.md).

### Added

- **Index Ask:** Advanced Index page runs cited, threaded `ask` when `[rag]` and
  `[llm]` are on and the index has rows. Collection chip is the scope; turns
  persist under `state/rag/threads/` (`paperful.rag.thread.v1`). `rag ingest`,
  `rag search`, and batch Ask (`state/ask-batch/`) are on Index; synthesize on
  Index; per-item summarize in drawers. Advanced **Briefs** runs collection
  `summarize` / `synthesize`. See [gui.md](docs/gui.md).
- **GUI P0:** required `paperful.item.v1` keys frozen (additive extras survive
  snapshot); restore is create-missing (DOI → key → title+year; skip gone /
  foreign schema; one folder per key). `paperful serve` is a localhost HTTP
  skeleton (`uv sync --extra serve`) over the same builders as `--format json`
  / MCP. No SPA, no `--apply` over HTTP. See [gui.md](docs/gui.md).
- Opt-in all-in E2E for keyword `NBA` (2025–2026) on throwaway `-C e2e/NBA`:
  `make e2e-nba` / `scripts/e2e_nba.py`, profiles `e2e-nba-search` /
  `e2e-nba-run`, hermetic `tests/test_e2e_nba.py`, marker `e2e_live`
  (`PAPERFUL_E2E=1`). Playbook: [e2e-nba](docs/e2e-nba.md).
- Browser agent: `[browser_agent].fallback_model` (one retry before final
  `not_found`, not on captcha), documented `use_vision` with preflight/doctor
  checks, `recover --from-last-run` / `--from-last-run-mode` / `--limit`, and
  promotable fetch-wins from agent step traces (`steps` in `fetch-wins.jsonl`).
- Mirror-first gaps: Mendeley and EndNote `changes(since)` (Mendeley
  `modified_since` / `deleted_since`; EndNote `sdb.eni` mtime) so both take
  the mirror path; offline freshness lines include last-refresh written/gone
  counts; non-PDF stored attachments copy when `pdfs=all`; standalone notes /
  attachments under `out/_notes/` and `out/_attachments/`; `paperful cache
  clean` (dry-run unless `--apply`) for absorbed or stale `state/pdf-cache/`
  files. `attachments` still reads live children (still open on the roadmap).
- CLI question-centric RAG: `ask --from-file` batch packs
  (`state/ask-batch/`, `paperful.ask_batch.v1`, resume-safe); `--focus`
  presets (`default|questions|gaps|methods|answered`) and `--prompt FILE`;
  `rag questions` (rules + optional `--llm`) → `state/rag/questions/`;
  `rag answered` (`--from-file` / `--from-extract`, `--after-item`) →
  `state/rq-answered/` (`paperful.rq_answered.v1`). Config:
  `[rag].focus` / `prompt` / `dest` / `extract_questions_llm`; profile `focus`.
- `paperful snowball digest --run-id` and `snowball watch digest` write a
  frontier rollup (`digest.md`): new / exists / version / deferred, overlap
  detail on the top new rows, a suggested `-C`, and queue / apply / resume
  paths. `snowball watch run --digest` writes the watch file after a
  successful run. Still no scheduler and no silent creates; `--apply -C`
  files the same `paperful:frontier-briefing` note as thin briefing.
  launchd / systemd / cron examples are in [snowball.md](docs/snowball.md#watch).
- `paperful authors -C …`: authors/orgs frequency from scope (`--min-count`,
  `--max-authors`, `--format json`). Dry-run prints tables. `--apply` writes
  `state/reports/<scope>-authors.json` (`paperful.authors_report.v1`) and seeds
  `state/author-packs/<slug>.proposed.toml` (top people; preserves listing URLs).
  Corporate `name`-only creators are orgs (report-only). Then `twenty lookup` /
  `snowball packs promote`.
- `paperful collections add --keys-file` — file existing library item keys into
  `-C` (membership only; dry-run unless `--apply`; added / already-in /
  not-found). `--format json`. Summary under `state/collections-add/`. Bare
  `collections` / `collections list` still print the tree. Not an MCP tool.
- `paperful reachout -C …`: contact-only list of missing PDFs. Never fetches.
  CSV (`--to`) with emails from item metadata, then Twenty contacts when
  `[twenty].enabled` (`--lookup` for a live People search). `--non-oa-only`
  keeps paywalled / no_oa / license_blocked. `--handoff tabs` opens existing
  ResearchGate publication URLs so **you** click Request. Does not send mail.
- `paperful authorwatch`: ORCID/OpenAlex people lists, cursor `run` (optional
  `--backfill-from`), `apply -C` (no `[snowball] enabled`). First `run` without
  `--backfill-from` does not open the library. `--apply` needs write API.
  CSV/JSON/ORCID import; social `--source` without `--file` prints the export
  recipe (no scrape). Ledger: `state/authorwatch/<name>/`. See
  [authorwatch.md](docs/authorwatch.md).
- `paperful ask --format json` (`paperful.agent.json.v1`; implies `--no-stream`).
  Snowball `search` / `hybrid` / `doi` / `orcid` / `collection` / `run` /
  `resume` share the envelope with `snowball apply`. `--format json` writes one
  object on stdout (progress on stderr). `paperful mcp` stays optional stdio
  sugar for `refs_gap` and `ask` over the same builders.
- Opt-in ResearchGate request **handoff**: `[request].channels = "rg"` opens an
  existing `researchgate.net/publication` URL in the system browser so **you**
  click Request full-text. Paperful never automates the click (RG ToS) and does
  not search ResearchGate. Ledger: `state/author-requests.jsonl`. `--request-rg`
  / `--re-request` on `gaps` / `run --handoff`.
- `paperful twenty sync -C …` creates or enriches Twenty People from library
  authors (`--apply`; dry-run default). Fills blank homepage/email and appends
  extras. Keywords include `paperful` plus the collection slug, and a note
  titled Paperful records the action. `lookup` stays CRM-read-only.
  `author_site` runs after open-access and campus lanes and before Scholar,
  using a promoted pack, `state/author-contacts/`, then a capped People
  website lookup. `--twenty-writeback` on `run` or snowball preflight appends
  a SearXNG personal page onto a unique Person and does not create one.
  No mail. Guide: [Twenty and SearXNG](docs/snowball.md#twenty-and-searxng).
- `paperful playbooks probe --corpus FILE` fetches each grey-playbook target
  and passes only when the first candidate is a real PDF (at least
  `--min-bytes`, default 10KB). `--save` writes a replay snapshot. The public
  corpus is `tests/fixtures/grey/corpus.toml`. PDF-shaped links rank ahead of
  section paths such as `/meetings/` or `/iris/`.
- Scholar late tail: `[fetch].order = "policy"` (default) runs opted-in Google
  Scholar after campus/grey, interleaved with `browser_agent` when that lane is
  on (`[scholar].when = auto|phase|interleave`). `[handoff].scholar` adds a
  Scholar results URL for misses. Opt-in `[serpapi].enabled` plus env
  `SERPAPI_API_KEY` is a paid Scholar **link-discovery** lane after local
  routes (`[serpapi].max_calls`, default 20, `0` unlimited; `--serpapi-max`
  per run). See [SerpApi](docs/serpapi.md).

### Changed

- The builtin ocean grey pack adds `rfmo-docs`, `iucn-dosi`, and
  `thinktank-ocean`, and no longer includes IEA, IRENA, OECD, or WHO.
  Those four, plus UNEP and UNDP, ship as optional copies in
  `paperful/data/grey_playbooks_examples/`. Point `grey_playbooks_dir` at
  that folder, or copy the files into your own packs directory. The ocean
  builtin stays on by default and is not in that folder.

### Added

- Snowball `--dedupe-scope` on crawl/run/resume/apply/watch; `--seeds-file`
  (DOI/ORCID lists); trailing `*` keyword stem expansion; `--dedupe-after
  classify|apply`; opt-in `--author-site-preflight` (co-author graph + proposed
  `state/author-packs/`) and `snowball packs promote`. `author_site` grey lane
  stamps `grey:author_site` (not a default `run` source). Resume re-fingerprints
  merged OpenAlex rows before auto-create.
- `--format json` (`paperful.agent.json.v1`) on the remaining batch verbs
  (`gaps`, `lint`, `fix-metadata`, `dedupe`, `snowball apply`, `summarize`,
  `synthesize`, `restore`, `import`, `recover`, `ocr`, `all`, inbox
  proposals, `notes delete`). Mixed `--apply` batches exit **3**. Legacy
  `--json` on `lint` / `gaps` / `dedupe` is unchanged unless `--format json`
  is also passed.
- `paperful notes delete`: dry-run then `--apply` trash of Paperful-owned
  notes only (`--type`, `--model` / `--except-model`, `--all` with TTY
  confirm or `--yes`). Never parent items.
- `doctor` ambers when the RAG index is behind the mirror.

- `paperful acronyms` harvests collection-scoped all-caps tokens into
  `state/acronyms/` (`paperful.acronyms.v1`). `fix-metadata` and parent create
  keep those tokens uppercase when recasing ALL CAPS titles.
- `paperful snowball briefing --run-id` and `snowball watch briefing` write
  markdown from a saved queue or watch inbox. No silent creates; `--apply -C`
  files a collection note tagged `paperful:frontier-briefing`.
- Research-pack playbook: [docs/research-pack.md](docs/research-pack.md).
- `--format json` (`paperful.agent.json.v1`) and exit **3** (partial batch) on
  `run`, `refs gap`, `ingest-dois`, and `inbox drain`. `paperful mcp` is a thin
  stdio server for dry-run `refs_gap` and read-only `ask`.
- Paperful notes lead with scannable prefixes (`Summary (model):`, `Attach:`,
  `Duplicate:`, `Linked:`) plus a `paperful.note.v1` HTML comment.
- Handoff lists rank by in-corpus cite count from the newest refs-gap pack ×
  miss-surface severity, then openable URLs.
- `paperful ask --thread` stores turns under `state/rag/threads/` and retrieves
  on a rewritten follow-up query. Prompted `ask` always threads.

- Frozen miss-surface enum (`no_doi`, `paywalled`, `no_oa`, `fetch_failed`,
  `license_blocked`, `import_ok`) on `run --dry-run`, `gaps --list-missing`,
  handoff exports, and `paperful.run_report.v1` items. Unpaywall / OpenAlex
  stamp `license`, `oa_status`, and `version` on candidates, manifest rows, and
  `record.json` (`fetch.oa`). Config: `[oa_honesty].stamp_fields` and
  `license_block`.

`paperful refs gap` scans collection PDFs for cited works that are not in the library and writes `state/refs-gaps/` (`paperful.refs_gap.pack.v1`). `paperful ingest-dois --from-file` (or `--from-pack`) creates metadata parents in `-C` only with `--apply`; dry-run reports exists / unresolved / held. Inbox can use a match ladder (`[inbox].match`) and gated or high-bar auto create-on-unmatched (`inbox proposals list|apply|reject`). Default inbox behaviour stays DOI attach only. Created parents take `--tag`, `[snowball]` / `[ingest].default_tags`, `from-<seed-slug>` (snowball seed or ingest file stem), `inbox-created`, and `inbox:<dirname>`.

Pipeline tests that stub EZProxy now set a campus prefix, so the preflight that drops an unconfigured `ezproxy` source no longer skips those runs.

Docs: Wave D honesty. Compose-first stranger path names CI job `docker`
(doctor without Zotero = exit 2). README leads with trust-the-disk
(`gaps` → `attachments` → `run`/`out/` before summarize/Ask). CLI-first today;
operator console parked post-1.0. Paperful **attach** vs TranscriptX **admit**
in [docs/TERMS.md](docs/TERMS.md). `--link` documented as advanced surgery only.
LLM labelling (LiteLLM experimental banners / paid-provider CI) was skipped
this wave.

New: ask your library. `paperful rag ingest` builds a search index from the
PDFs and abstracts in the mirror, and `paperful ask "question"` answers from it,
streaming the answer and listing the papers and pages it cited. `ask` with no
question prompts for several; each is answered on its own. `paperful rag search`
shows the matching passages without a chat model, and `paperful rag status`
compares the index with the mirror. All of it is off until `[rag].enabled =
true`, needs `paperful[rag]` (LanceDB), and reads `out/` only: it never calls
the reference manager. Embeddings default to `nomic-embed-text` on Ollama
(`bge-m3` for multilingual libraries, or LiteLLM); each embedding model keeps
its own index under `state/rag/`. Ingest is incremental and resumable. Scans
are OCR'd before indexing and PDFs with a text layer are not; note that
`[rag].ocr = "auto"` rewrites scanned PDFs under `out/` without an `--apply`
flag (`ocr = "off"` or `--no-ocr` turns that off). `[rag].auto_ingest = true`
indexes new PDFs after `run`, `attach`, `inbox`, `snapshot`, `ocr --apply` and
`snowball`; it is off by default. `[rag].parser = "docling"` is available with
`paperful[rag-docling]`. `doctor` gains RAG rows. See `docs/rag.md`.

**Mirror first.** Commands now work from the copy under `out/` and use the
reference manager only to refresh that copy and to write back when asked.

- Each command first asks Zotero what changed since the last refresh and
  rewrites only those item folders. With nothing changed that is six
  requests. Before, every command listed the library through the API, and
  scoping one collection read every attachment in the library first.
- `paperful sync` does that refresh on its own. `--full` reads the whole
  library, `--dry-run` counts and writes nothing. The first refresh reads
  the library once (about a minute for 22,000 items).
- With Zotero closed, `collections`, `gaps`, `lint`, `export`, `ocr`,
  dry-runs, and `run` (without attach) carry on from the mirror and say how
  old it is. `--offline` (or `PAPERFUL_OFFLINE=1`) never contacts Zotero.
  `sync`, `snapshot`, `restore`, `attachments`, `attach`, and any `--apply`
  still need it and exit 2.
- A write to Zotero (`attach`, `fix-metadata --apply`, `dedupe --apply`,
  `versions --apply`, summary and remark notes, snowball and `import`
  creates) now updates that item's folder in the same step. Before, the
  mirror was stale until the next `snapshot`.
- **Behaviour change:** `[mirror].pdfs` defaults to `all`. `paperful sync`
  copies every PDF Zotero holds into its item folder, once; expect the
  mirror to grow by about the size of your Zotero storage. `lazy` copies a
  PDF the first time a command needs it (`additional` is the old name and
  still loads). `none` keeps them out. Files already in `state/pdf-cache/`
  are moved in rather than copied again.
- An item trashed, merged, or deleted in Zotero keeps its folder and is
  marked in its record; commands leave it out. `[mirror].gone = "trash"`
  moves the folder under `out/_trash/` instead. Nothing under `out/` is
  deleted. `sync` refuses to mark more than half the mirror as gone (a
  different library) without `--accept-gone`.
- A retitled item's folder is renamed instead of a second one appearing. An
  item that changes collection takes its folder with it.
- Annotations are copied to `annotations.json` beside the record.
- A Zotero read that fails is now an error, not an empty answer. `snapshot`
  and `sync` skip the item, keep what is on disk, and say how many could not
  be read. Before, a stalled API could replace a full record with an empty
  one, and a failed note lookup could post a duplicate note.
- `attachments` no longer downloads each file to see whether it is there.
- New config: `[mirror].refresh` (`auto` / `manual`), `[mirror].gone`
  (`mark` / `trash`). `doctor` shows when the mirror was last refreshed.

Every command that walks the library now says what it is doing. `lint`,
`fix-metadata`, `attachments`, `versions`, `snapshot`, `restore`, `import`,
`export`, `ocr`, `summarize` and `synthesize` show the same live progress bar as
`run` and `snowball`: items done, the item in hand, elapsed time and ETA. `lint`
also shows the running finding count. Loading the library scope shows a spinner
in those commands and in `run`, `gaps`, `collections` and `inbox`. With `--json`
the bar goes to stderr and only on a terminal, so stdout stays JSON. Ctrl-C
during `lint` keeps the findings so far: it prints them, writes the run report
with `flags.interrupted`, and exits 130.

`snowball resume` after an OpenAlex budget stop during a keyword search now
keeps the original `max_candidates` (including `all`) instead of capping the
search at `per_hop_limit`.

Snowball reference recovery from publisher landing pages keeps references with
no DOI when the page lists references as `<li>` items, so they reach the title
match instead of being merged into one entry and dropped.

`run` stops asking Google Scholar after the first clear block. An HTTP 429,
503, or CAPTCHA / `/sorry/` page skips Scholar for the rest of the run instead
of one request per queued item; those items are left `retryable` for the next
run.

Removed the legacy flat-PDF migration. A flat `Author - Year - Title.pdf` and
its `*.paperful.json` card are no longer moved into an item folder by `snapshot`
or `run`, and `doctor` no longer ambers on mixed flat + folder trees. The
`snapshot` summary drops its `migrations` count.

`snowball orcid` accepts several ORCID iDs in one crawl (shared caps / gate /
`-C`), matching multi-DOI positionals. Profile save takes repeatable `--orcid`
and writes `orcids = [...]`; legacy singular `orcid` still loads.

Creating library parents (snowball ingest, restore, import) Title-Cases ALL
CAPS scholarly titles before write, using the same rules as `fix-metadata`.
DOI work titles adopted by `fix-metadata` get the same pass so Crossref/
OpenAlex ALL CAPS does not land in Zotero.

Mid-run EZProxy re-login pauses the Rich fetch progress bar so the Y/n prompt
(and headed-login Enter confirm) stay visible instead of being overwritten.

`doctor --probe` no longer prints Playwright `TargetClosedError` / "Task was
destroyed" noise: Chromium readiness is checked via `playwright install
--dry-run` instead of starting a throwaway sync driver before the live probes.

`session login` CDP attach uses Playwright `no_defaults` so cookie export
works against system Chrome that rejects `Browser.setDownloadBehavior`
("Browser context management is not supported"). Requires Playwright ≥1.60.

`run` releases the vault Chromium before headed EZProxy re-login so system
Chrome can open the shared profile (preflight `session_ok` otherwise held the
SingletonLock and the login window never appeared).

`doctor --probe` hits Scholar / EZProxy `session_ok` (vault Chromium when
available) and ambers when cookie files exist but campus CAS or a captcha
still blocks. Default `doctor` stays file-presence only. The same vault-faithful
probe runs before batch 1 of `run` when `ezproxy` is in sources.

One-page PDFs are gated by text density (`gate_short_pdfs`, default on). Sparse
stubs (few words — ethics/consent forms) soft-reject so later sources can still
run. Denser one-pagers (letters, short comments) save to `out/` with reason
`short_pdf` and wait for `paperful attach --allow-short-pdf`. Tune with
`short_pdf_min_words` (default 200).

Vault PDF fetch follows SSO interstitials, playbook rewrites, citation PDF
links, View PDF controls, and viewer iframes before giving up. Successes append
`state/fetch-wins.jsonl` (no query string). `paperful playbooks propose` /
`promote` write user-owned `learned.toml` under `grey_playbooks_dir`.
`[playbooks].promote` defaults to `gated`; `auto` waits for `auto_min_hits`
(default 2) and can still promote a fluke. `run --promote` overrides one run.
Learned files stay in `state/` and `packs/` (gitignored, including Docker
`PAPERFUL_DATA`).

Configurable PDF drop folder (`[inbox].dir`) for manual downloads after soft
blocks. `--handoff watch` opens tabs then polls the folder; `paperful inbox
watch` / `drain` are a long-running sidecar and one-shot drain. Files match by
PDF DOI (FIFO of openable misses during a handoff session). `inbox watch` /
`drain` default to the whole library so one drop folder serves every topic;
`-C` is an optional narrow. Unmatched PDFs move to `unmatched/`. Reports:
`state/runs/<stamp>-inbox.json`.

`run` and `all` accept `--browser-agent` / `--no-browser-agent` to override
`[browser_agent].during_run` for one invocation (default stays on when
`llm.enabled`).

A `javascript:void(0)` (or other non-http) PDF link is a failed download for that item. It no longer aborts `run` when the HTTP client has cookies.

The run summary counts items that did not yield a PDF by reason — captcha, cloudflare, paywall, and a plain not-found — one reason per item. When the browser agent reads a publisher price on an unsaved article, that price is logged on the item and the summary totals it (`€79.90 for 2 articles`).

Long PDF runs pause a blocked source instead of dropping it for the rest of the process, and a 429 does not open that circuit. When EZProxy is configured, `run` probes the vault before batch 1. An expired campus session skips further proxy wraps; on a TTY, `run` offers re-login at the next batch boundary and again after the fetch (`ezproxy_relogin`) for items left `retryable` / `session expired`. A miss from every source stays `not_found` with reason `closed`. Europe PMC tries the PMC render URL when a PMCID is present. OpenAIRE is a DOI source for repository copies. A preprint that misses open access is tried once against its published DOI, without changing the library DOI.

`snowball --direction similar` adds one ranked hop: works that share the seed's references, then Semantic Scholar recommendations. A saved queue with no `deferred.json` resumes into create and PDF fetch without searching OpenAlex again.

A depth-0 snowball search stays on the hit list. Citation backends fill empty
fields on those hits and do not import their references. A reference title is
the structured article title, never the raw citation. A blank or citation-shaped
title is filled from the OpenAlex work before the year filter; if that still
is not a work title, the row is not created. `fix-metadata` replaces a blank,
`(untitled)`, or citation-shaped title from the DOI without `--overwrite`,
and does not replace that DOI from the bad title. A DOI with a unicode hyphen,
a doubled hyphen, a `/figures/`, `/tables/`, or `/metrics` suffix, or a Wiley
SICI missing a colon, is looked up as the bare DOI. Snowball still refuses to
store a reference list entry as the title: author-year lines such as
``Xiao B, Wu H, Wei Y (2018) Simple baselines…`` stay blank until the work
record supplies the article title.

`paperful attachments` compares PDF attachments to `out/` and writes a report.
It does not change Zotero unless you also pass `--fix-broken`, `--merge-files`,
`--rename`, or `--link` with `--apply`. Repairs use a file already in the
mirror. `--link` points a personal library at that file and is refused for
groups. Tablet send/get stays outside this command.

A readable line sits on the parent item beside the PDF provenance stamp.
`[remarks].surface` is `note` (default), `tag`, or `off`. Attach writes
"Free copy from Unpaywall." (and a DOI-mismatch sentence when that applies).
`dedupe --apply` writes "Same paper as Smith 2019, which already has the
PDF." on the spare copy before the merge. Snowball, when it creates an item,
can write "Cited by N papers in this collection." from OpenAlex reference
lists cached under `state/cites/`, plus a seed-overlap sentence when at
least two seeds from that run point at the work.

`paperful ocr` adds an OCRmyPDF text layer to scanned PDFs under `out/`
(`--apply`; dry-run lists them). `--attach` uploads that file beside the
scan. It is an optional `all` step, not in the default chain. Summarize,
lint PDF-DOI, and synthesize then read the text that was already there.

First run copies
`config.minimal.toml`. `--preset oa` drops EZProxy. Empty `email` with
Unpaywall in `sources` is a red `doctor` row (`unpaywall_email`, exit 2).
`paperful jobs` lists verbs by job. `run` fills items already in the library;
`snowball` grows it. A quota on the run summary says the PDF is in `out/`
and to run `attach` after freeing Storage.

Public pitch is the five jobs — library, find, completeness, mirror, control —
rather than a Zotero sidecar. The catalogue stays an adapter: Zotero is well
tested; Mendeley and EndNote are seeking testers. See [Why Paperful](docs/why.md).

Snowball wave 5: `hybrid` (keyword hits, then one hop), `approve-each` for short
lists, overlap ranking, Crossref and Semantic Scholar metadata fill, and
`languages`, `min_seed_citations`, `note_provenance`, and `backends`. Optional
`--refine` writes query suggestions and does not create items.

Snowball wave 3: ORCID and collection seeds, `--direction cites|both`, depth
above 1 (soft ceiling 5) under the existing caps, `approve-batch` queues with
`keep` plus `paperful snowball apply <run-id>`, and profiles for `orcid` /
`collection` modes.

`recover` / `browser_agent` stop the browser-use agent as soon as a valid PDF
is on disk (size stable across two polls), instead of burning the remaining
step budget after a successful click. The recover task tells the agent to quit
immediately on access blocks (403 / "Request blocked" / paywall) and never open
search engines or support/help pages; Paperful also force-stops if the page URL
becomes Google/Bing/DuckDuckGo or a support/contact path, so ignored
instructions cannot burn the wall budget.

Importing browser-use no longer prints pyzotero's per-request log
(`INFO [httpx2] HTTP Request: GET http://localhost:23119/...`). Those lines
were appearing while the library was listed and over the fetch progress bar.

## 0.9.0 — 2026-09-22

Google Scholar is opt-in: dropped from `DEFAULT_SOURCES` and
`config.example.toml` so a fresh `doctor` stays green without a Scholar
session. Add `"scholar"` to `sources` (and usually `session login scholar`)
when you want that lane. `doctor --guide` remediation for a red Zotero row
now matches the exit-ladder diagnosis codes (`zotero_down` /
`zotero_api_off` / `zotero_bad_host`, including the Host vs
`PAPERFUL_ZOTERO_HOST` tip). Sphinx Start here lists Docker and Zotero
setup before Commands.

`recover` / browser-use launch with system Chrome (`channel="chrome"`) so the
agent matches `session login`. Default browser-use extensions stay on (popup /
cookie helpers); empty cached ``.crx`` files are dropped so a failed download
is retried instead of breaking extraction.

Shared 1.0 leftovers that remain after the item/restore lock: workbench GUI
P1–P3b (read-only review through Ask in the browser). Snapshot/restore is
create-missing, not a lossless identity round-trip.

## 0.8.0 — 2026-09-22

Zotero PDF attachments carry a provenance note (`paperful oa:unpaywall`,
`campus:ezproxy`, `grey:<playbook>`, `pirate:scihub`, …). A PDF DOI that
differs from the library item adds `warn:pdf_doi_mismatch` and still attaches.
`run --strict-pdf-doi` saves that file and skips attach;
`attach --allow-pdf-doi-mismatch` attaches it later.

`run` prints `downloaded N · attached M · deferred K · not_found J · write-api yes|no`
before the summary table. `summary.write_api` is part of the required
`paperful.run_report.v1` key set (extra keys may still be added). This is not
a 1.0 tag.

`doctor --json` prints check codes. Next steps branch on Zotero down, API off,
a bad Host header, and Zotero 7–9. Quota and auth failures print one operator
line. The operator install card is `docker compose build` (build-local only;
no PyPI, no `docker pull`). `uv` is the contributor path.

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
[Why Paperful](docs/why.md), [Mendeley](docs/mendeley.md), and
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
Paperful.

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

- `paperful.item.v1` and snapshot/restore keys may still move. Mendeley and
  EndNote are seeking testers. This tree is not tagged 1.0.
- Open-access fill is DOI-scoped. Unpaywall often returns a landing page with
  no PDF. Grey literature is the configured playbooks only, not a universal
  harvester. Sci-Hub is opt-in and thin after ~2021. A full Zotero file quota
  can leave the PDF only in `out/`.
- A mismatched PDF DOI still attaches unless `--strict-pdf-doi` is set. The
  note then includes `warn:pdf_doi_mismatch`.
- Required `paperful.run_report.v1` keys are frozen; extra keys may still be
  added.
- Collection resolve failures print the spec; they do not yet suggest closest
  paths.
- Provenance notes are Zotero-only.

### Honest defaults

- Sci-Hub is opt-in and off by default.
- Zotero 7–9: download to disk only; attach needs Zotero 10+.
- `--preset eoi`: open access + campus EZProxy (no Scholar, no Sci-Hub).
