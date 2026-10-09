# Roadmap

Guidance for contributors, not a commitment calendar. Paperful’s jobs are
**library**, **find**, **completeness**, **mirror**, and **control**: one
disk mirror (`out/`, `state/`), adapters for citation managers, and fetch /
lint / attach / summarise as the core loop. **Zotero is the well-tested
adapter.** Mendeley and EndNote are in the tree and seeking testers. See
[architecture.md](architecture.md) and [why.md](why.md).

Optional thin bridges (`paperful session login`) capture a local browser profile;
they do not rewrite the fetcher. A **Zotero plugin** is not the 1.0 bet.
**Firefox extension**, **local OpenAlex snapshot** (beyond today’s opt-in v1),
and **newsletter / alert ingest** are **post-1.0** — see [Product split](#product-split-10-vs-post-10).

**1.0** is the trust checklist below, a locked item record (`paperful.item.v1`
plus `snapshot` / `restore`), proven on **Zotero**, and the **workbench**
([GUI](#gui)): Discover + Wanted on the default nav, Preview/Grab
with review tokens, full CLI surface behind **Advanced**. **Interactive Ask** is
opt-in under Index (`[rag]` + `[llm]`), not the home page
([Zotero-RAG integration](#zotero-rag-integration-later-question-centric-layer)).
**Mendeley and EndNote do not gate 1.0** — they stay in the tree with honest
docs (“seeking testers”; Zotero well-tested). Do not market them as supported
until real-library reports say so.
Still not a full-text reading index, not a WebDAV client, and not “AI fetch
everything.” `paperful ocr` is the optional text layer for scans.

(product-split-10-vs-post-10)=
## Product split: 1.0 vs post-1.0

Contributor decisions (not a calendar). **1.0** is CLI honesty plus the
operator workbench; **post-1.0** items stay on the map for power users and
integrations.

| **1.0** | **Post-1.0** |
| --- | --- |
| Trust checklist, locked `paperful.run_report.v1` / `paperful.item.v1`, snapshot contract | **Local OpenAlex parquet store** — phases 2B/2C (`works_citing`, full search parity, `local_duckdb` / `http`). Live OpenAlex API is enough for most installs; v1 `ssh_duckdb` remains opt-in for institutions |
| **GUI workbench** — Discover + Wanted simple loop (topic + people); command ids; review tokens; Advanced Repair / Mirror / Index / Briefs and the non-TTY CLI verbs | **Firefox extension** — native messaging → CLI ([section below](#optional-thin-bridge--firefox-extension-post-10)) |
| **Ask in GUI (Index)** — scoped chat with citations when `[rag]` + `[llm]` on | **Newsletter / alert ingest** — rollup bridge, Scholar alerts first ([Frontier digest](#frontier-digest-later-watch--external-ingest)) |
| Zotero-proven fetch/mirror path; honest adapter docs (Mendeley / EndNote seeking testers) | SaaS tenancy polish; promoting other managers to “supported” after field reports; remote-manager parity beyond what 1.0 open/Docker needs |

(trust-10)=
## 0.1 → 1.0 (trust + mirror contract)

`0.1` is a first usable helper for a reference library. Do not call it **1.0**
until these land. Do **not** grow this list into a second product (no auto
Sci-Hub, no “AI fetch everything”).

| Step | UX outcome | Status |
| --- | --- | --- |
| End-of-run **one-line** banner: `downloaded N · attached M · deferred K · not_found J` plus write-API yes/no | Trust after a run | Shipped (table still follows the line) |
| Attachment **provenance stamp** (`oa:unpaywall` / `campus:ezproxy` / `grey:undocs` on notes or title prefix) | Trust inside Zotero | Shipped on the Zotero attachment note. A readable parent line follows `[remarks].surface` |
| `--dry-run` **Would-hit** column (sources in order) | Trust before network | Shipped |
| Exit **2** + next-steps when Zotero is down (`collections` / `run` / `attach`) | Fresh clone never dead-ends | Shipped |
| Slim README + [CHANGELOG](../CHANGELOG.md) known limits | Trust before install | Shipped |
| Lock `paperful.run_report.v1` | Trust for agents | **Shipped** — required keys frozen (`RUN_REPORT_*_KEYS` incl. miss rollups); golden fixtures; extra keys may be added. Package tag may still wait on workbench polish |
| Lock `paperful.item.v1` and `snapshot` / `restore` (additive keys only after 1.0) | Trust for the disk ledger | **Shipped** — required keys frozen; restore is create-missing (not lossless round-trip) |
| Strip legacy flat-PDF migrate + mixed-layout doctor amber | Day-0 mirror never steers people into a whole-library layout cleanup | **Shipped (0.1 → 1.0)** |
| **Mendeley and EndNote adapters** (not a 1.0 blocker) | The ledger survives a manager change | In the tree. **Seeking testers.** Zotero stays the well-tested path. See below |
| **Workbench GUI** | Discover, Wanted, Preview/Grab; Advanced Repair / Mirror / Discover grow / Wanted recover | Landed — [GUI](#gui); `paperful serve` + `paperful/ui/`; `docker compose up` publishes `127.0.0.1:8765`. TTY and Sci-Hub stay CLI. Not tagged 1.0 |
| **Interactive Ask (GUI)** | Index page when `[rag]` + `[llm]` enabled | **Shipped** — Index Ask + batch (scope, custom prompts, force); `rag questions` / `rag answered`; ingest/search; Briefs for summarize/synthesize |

Nice-to-have (not 1.0 blockers): colour glossary next to `doctor` (documented);
collection picker hint on fuzzy `--collection` miss.

### Mendeley and EndNote (seeking testers)

The code is in the tree. It has not been proven on real libraries the way
Zotero has. **1.0 does not wait on tester sign-off** — ship with clear limits
in README, [why.md](why.md), [mendeley.md](mendeley.md), and [endnote.md](endnote.md).
Do not call either adapter **supported** until field reports justify it.

1. **Mendeley** — `MendeleyBackend` talks to `api.mendeley.com` (no official
   SDK). OAuth via `paperful session login mendeley`. `supports_write` is true
   in code. File download must **not** forward the Bearer token on the 303 to
   object storage. Document `notes` (`view=all`) is read; Paperful writes
   still use annotations. Needs a real library: list, fetch a missing PDF,
   attach, notes, and a failed auth that prints the next-steps ladder.
2. **EndNote** — `EndNoteBackend` reads `<Library>.Data/sdb/sdb.eni` (a copy
   if EndNote holds the lock, including `-journal`). Writes never touch that
   database: they stage `state/endnote-import/<stamp>/` for File → Import.
   Trash is refused. SQLite `reference_type` is **not** the XML number
   (journal is 0 in the DB, 17 in XML). Groups come from `groups.spec` +
   `members`, not a join table. Testers should confirm a round trip: read a
   small library, `snapshot`, import the bundle, and check that types and
   groups (stored only as a Label in XML) match what they expect.
3. **Still later:** multi-manager-as-equals (conflict journal, virtual
   collections). A tester report is not that.

## Core (keep sharpening)

- Resumable missing-PDF fetch, source routing, circuit breaker, EZProxy session
  hygiene, attach reliability, `doctor` / `report`. **Google Scholar posture**
  (below): stop treating vault Scholar replay as core; human browser at handoff
  instead. **Shipped (find
  recovery):** soft-blocked OA URLs (empty httpx body) retry in the vault
  browser (SSO / PDF link / download control), then optional `browser_agent`;
  items stay `retryable` / `soft block` rather than hard `not_found`. Dead vault
  landings (`login` / `captcha` / `no download control`) silence that final host
  for the rest of the run; transport timeouts use a short connect budget and do
  not permanently block a publisher on a single blip. Manual
  handoff: `run` / `gaps --handoff list|tabs|walk|watch` and `paperful inbox
  watch` / `drain` against `[inbox].dir` (default: PDF **DOI-only** attach to
  missing-PDF parents, whole-library scope; `[inbox].match` / `[inbox].create`
  opt in to the [match ladder](#inbox-match-ladder) and gated create). Distinct from snowball
  watch `inbox.jsonl`. **Later (handoff):**
  rank `--handoff list` by in-corpus cite count (from [refs gap](#bibliography-gap-scan-later-not-gaps))
  × miss severity so limited browser time hits high-value PDFs first. CLI
  `--browser-agent` / `--no-browser-agent` overrides `[browser_agent].during_run`
  for one `run` / `all`. **Later (author-site + RG):** personal-site PDF discovery
  via opt-in web search ([Acquire §2](#maybe-later-not-core)); ResearchGate
  request-from-author is **handoff-only** (existing RG URL → system browser;
  you click Request full-text; ToS) behind `[request].channels` ([same section](#maybe-later-not-core)).
- **Academic HTML→PDF snapshot (shipped, opt-in).** Web/news (and DOI-less
  `document` / `report`) still print when the page is the article. Journal and
  other DOI items stay off unless `[htmlpdf].academic` is `gated` or `auto`
  (`--htmlpdf` for one run). The print runs after scripted lanes and
  `browser_agent`. Landing pages are refused: paywall, login, cookie wall,
  access-options, short pages, and any page that still offers a native PDF.
  `gated` writes `state/htmlpdf/proposals/` (`paperful htmlpdf proposals
  list|apply|reject`). `auto` attaches only after those checks. The stamp is
  `snapshot:htmlpdf` (weaker than a publisher PDF). `gaps` counts
  `snapshot_only`. `run --upgrade-snapshot` retries native lanes and replaces
  the print unless `--keep-snapshot`. A snapshot is miss-surface `snapshot`,
  not `import_ok`.
- **Google Scholar — late tail + handoff (shipped).** `scholar` stays **opt-in**
  (not in `DEFAULT_SOURCES`; first-run CAPTCHA ambers if it were). **Policy**
  (`[fetch].order = "policy"`, default) pulls it out of the reliable loop:
  OA, campus, grey, then a **late** Scholar try. When `browser_agent` is on
  this run, `[scholar].when = "auto"` **interleaves**: one Scholar query, then
  the agent only if that miss remains — the agent wall clock is the backoff
  (no extra `delay_scihub_s` after an agent call). Agent off: one late Scholar
  phase with the existing latch. `[scholar].when = "phase"` keeps a Scholar
  burst then the agent; `"interleave"` always pairs. `[fetch].order = "list"`
  honors the `sources` array (field-specific escape). **Handoff:**
  `[handoff].scholar` (default on) adds a Scholar results URL to miss rows and
  opens it in the **system** browser when there is no direct PDF URL.
  **SerpApi** (`[serpapi].enabled` + env `SERPAPI_API_KEY`) is a paid link-discovery
  lane after local tail steps, never a silent cloud default; stamp `web:serpapi`.
  `[serpapi].max_calls` (default 20, `0` unlimited) and `--serpapi-max` cap
  paid searches this run. `doctor` ambers when enabled without a key (no paid probe).
  OpenAlex / Semantic Scholar / Crossref remain the programmatic defaults; Scholar stays
  out of snowball backends. CAPTCHA solve services stay out of scope.
  **Latch (unchanged):** the first Scholar 429, 503, or CAPTCHA / `/sorry/`
  page skips Scholar for the rest of the run; queued items get
  `scholar:skipped(blocked)` and still reach `browser_agent`. SerpApi quota
  uses its own latch and does not trip Scholar.
- **Inbox create-on-unmatched (config, shipped).** Optional `[inbox]` mode so
  `watch` / `drain` still ingests when no missing-PDF parent matches: create a
  parent in a configured collection (or a routed target once smart inbox exists),
  attach the PDF, and fill bibliographic fields from Paperful’s identifier
  pipelines (DOI from PDF → Crossref / OpenAlex / Semantic Scholar; title /
  first-page fallbacks when DOI is missing). **Reference-manager metadata
  window:** configurable settle or poll after attach so Zotero and other backends
  that retrieve metadata from PDFs can run before Paperful writes or merges fields
  (skip or shorten the wait when the backend has no such behavior).   Config modes: `attach_only` (today) | `create_gated` | `create_auto` (high bar).
  Gated vs auto should match smart inbox; fail closed to `unmatched/` or
  `review/` when resolution is thin. **Gated UX:** write
  `state/inbox/proposals/<id>.json` (`paperful.inbox.proposal.v1`);
  `paperful inbox proposals list|apply|reject` — never silent parent create.
  Tag parents `inbox-created` and `inbox:<dirname>` for later `dedupe` / `refs gap`. Optional
  multi-root `[inbox].dir` list is still later. End-of-drain
  one-liner + JSON (attached / created_gated / unmatched), same honesty as
  `run`. Today’s default stays DOI attach only — no silent create-parent.
(inbox-match-ladder)=
- **Inbox match ladder (before `unmatched/`, config, shipped).** Optional stages
  run **in order** after a stable PDF lands in `[inbox].dir`, each toggled in
  config, before `move_unmatched`. Goal: attach (or propose attach) using the
  same missing-PDF index as today without requiring the operator to rescue files
  from `unmatched/` when metadata lives in the PDF but not in the first two
  pages of extractable text.
  1. **DOI (shipped)** — `doi_from_pdf` (pdftotext / pypdf, ~two pages) →
     normalized DOI → unique missing-PDF parent in scope. Fast path; keep default.
  2. **Hold / defer quarantine** — `[inbox].quarantine_after_s` (or
     `hold_before_unmatched`): poll the same path until timeout so another
     process can act (e.g. operator drag into Zotero, or a manager watched folder
     on a *different* path — Paperful does not drive Zotero’s GUI recognizer;
     document sidecar patterns). Re-run the ladder on the file before quarantine.
  3. **Richer text extraction** — when the text layer is empty or sparse, optional
     transient OCR for matching only (`[inbox].ocr_for_match`: cache under
     `state/pdf-cache/` or temp; do not rewrite the drop file unless the operator
     later runs `paperful ocr --apply` on the attached item). Reuse `ocrmypdf` /
     `[ocr].languages` where `doctor` is green.
  4. **Deterministic title / fingerprint attach** — derive candidate title (PDF
     `/Title`, first-page heuristics, filename stem when not junk), year when
     visible, optional registrant host from embedded links; normalize like dedupe
     title hygiene. Match missing-PDF rows in scope by
     `norm(title)+year` (same ambiguity rules as dedupe `medium_title_year`:
     hold groups with divergent titles; never attach on a tie). Shares the
     **non-DOI grey fingerprint** work (`norm(title)|year|registrant_host`; ISBN /
     report # when present — near-term table row 7). Crossref / OpenAlex title
     search only as an opt-in, rate-limited **resolve** step when local library
     match is thin (same honesty as `fix-metadata`, not silent parent create).
  5. **LLM match (`when_thin`)** — only when stages 1–4 fail or scores sit below
     a bar: grounded prompt with PDF excerpt + short list of candidate missing-PDF
     items (metadata block pattern from `lint` / `[lint].llm_pdf_match` and
     `fix-metadata` `llm_title`). Config: `[inbox].llm_match` `off` | `when_thin` |
     `always`, `[inbox].llm_match_min_confidence`, per-function
     `[inbox].model` / `[inbox].provider`. **Gated attach** by default (proposal
     row in `paperful.inbox.proposal.v1`); auto attach only above a high bar and
     single clear candidate. Fail closed to `unmatched/` or `review/`.
  **Config sketch:** `[inbox].match` preset `doi_only` (today) | `doi+title` |
  `doi+title+ocr` | `full` (title + OCR + `llm_when_thin`), or explicit stage
  list. Run report / `state/runs/*-inbox.json` should record `how`:
  `doi` | `fifo` | `title_fingerprint` | `title_resolve` | `ocr` | `llm` |
  `manager_metadata` | `none`. **Not in scope:** guessing parents outside the
  missing-PDF index without create-on-unmatched; bulk OCR of the whole library
  inside `watch`.
- **Smart inbox (optional, later).** Create-on-unmatched and the match ladder
  can attach or propose a parent; they still do not choose a collection.
  A smarter drop-folder lane would
  **route** (and optionally ingest) each PDF toward the right collection using
  **deterministic** signals first — ongoing / recent snowball runs and watches
  (`state/snowball/…`, open packs, last `-C` / profile), DOI already in the
  library, filename / PDF metadata / first-page text (and ladder OCR/title
  fingerprints) against collection titles and recent candidates — then an
  optional LLM ranker.
  **LLM use** is configurable per this lane: `off` | `when_thin` (only when
  deterministic signals conflict or score below a bar) | `always`. **Model**
  follows the house pattern: global `[llm].provider` + `[llm].model` (and the
  LiteLLM `provider/model` id form), overridable **per function** (e.g.
  `[inbox].model` / `[inbox].provider`, same idea as `[browser_agent].model`
  today; other verbs keep their own overrides). Apply modes: **gated** (propose
  collection ± create-parent → human confirm / edit) or **auto** (apply when
  confidence clears a config bar). Fail closed to today’s `unmatched/` (or a
  review queue) — never silent misfile. Builds on the Firefox-bridge
  create-parent ingest gap; keep DOI attach as the fast path when a miss already
  exists.
- **OA honesty / miss taxonomy (shipped).** Project internal miss status to a frozen
  surface enum for dry-run, `gaps`, and the run report:
  `no_doi | paywalled | no_oa | fetch_failed | license_blocked | import_ok`
  (one code → one plain string; keep rich detail on `attempts[]`). Stamp
  Unpaywall / OpenAlex `license` / `oa_status` / `version` onto candidates and
  `record.json` so bronze vs licensed OA is auditable and a future license gate
  can emit `license_blocked` without writing bytes. **Configurable:** the
  operator chooses which of those fields get stamped (and later which feed a
  gate); defaults should be honest but not surprise a local library with
  redistribution policy. Prefer licensed `url_for_pdf` / green repository copies
  over bronze-only publisher landings when both exist. Follow-ons: DOI→candidate
  URL cache (TTL) to cut repeat API traffic; Crossref `link[]` PDF harvest as
  campus-entitled API-first (never claimed as free OA without entitlement).
  Not a hosted service SKU; not Sci-Hub completeness metrics. **Ship with** the
  next research-ops verbs ([Near-term research-ops](#near-term-research-ops)), not
  after: surface the same codes on `run --dry-run`, `gaps`, and `--handoff list`
  (plain-string column + optional `oa_status` / `license` when stamped); map rich
  `attempts[]` outcomes via `miss_detail` until Core fully switches. Without
  stamps when Unpaywall/OpenAlex supplied them → do not claim `import_ok`.
- **Linked-URL health (shipped).** `paperful urls check -C …` —
  short-budget HEAD/GET on metadata URLs and linked-PDF URLs; findings `ok | redirect | soft_404 |
  hard_dead | paywall_html`. `--apply` rewrites a URL only when a grey playbook
  already knows the PDF target. Report-only by default.
- **Quiet mirror** — [quiet-mirror.md](quiet-mirror.md). **Shipped:** `snapshot`
  writes a per-item folder (`record.json`, optional PDF, notes) plus
  `out/_index.jsonl`, `out/_collections.json`, and `out/_history.json`.
  `[mirror].pdfs` is `additional` (default), `all`, or `none`. `restore --apply`
  creates missing items and does not overwrite fields already in Zotero. Dual
  `imported_file` store; house sync (Syncthing) stays outside Paperful. Not a
  second reading UI. Not a linked-file cutover. Not a WebDAV client.
- Deterministic `lint` / `fix-metadata` (Crossref / OpenAlex / Semantic Scholar /
  PubMed, PDF-text DOI via pdftotext then pypdf) with explicit `--apply`.
  **Shipped:** verified PDF-DOI → patch; date precision guard; HTML title cleanup;
  ALL CAPS → Title Case; title hygiene findings (`title_html` / `title_all_caps` /
  `title_filename`). Filename titles stay findings-only.   De-allcaps today only keeps
  two-letter tokens (UN, EU); longer corpus acronyms (BBNJ, FAO, OECD, …) stay
  uppercase when they appear in `state/acronyms/` (`paperful acronyms -C … --apply`,
  frequency + shape; optional `extra` list). Deterministic first; optional LLM NER
  only as a later assist behind the existing `[llm]` gate.
- Collection-scoped duplicate packs: `paperful dedupe` (DOI, then title+year).
  Trash is explicit `--apply`; title+year needs `--apply-medium`. See
  [dedupe](dedupe.md).
- **Note hygiene — selective deletion + typed provenance (later).** Paperful
  writes many child and collection notes (`summarize`, `synthesize`, `[remarks]`
  found / duplicate / linked, dedupe spare-parent lines, attachment readable
  lines, future RAG / briefing exports). Re-runs often update in place via
  tags, but operators still need **bulk delete** with honest filters — e.g. only
  summaries from a particular model, all summaries **except** one model,
  dedupe-remark notes only, notes before a date stamp, or everything under `-C`
  matching selected `paperful-*` kinds. **Direction:** a scoped verb
  (`paperful notes …`, name TBD) with `--dry-run` default and `--apply` to
  trash matched notes only (never parent items). Filters should include
  `note_type` / kind, LLM **model** (from structured metadata, not regex on
  footer text), tag, date, collection scope, and paired exclusions
  (`--except-model`, `--except-type`, …). **Infrastructure:** do not infer
  intent by searching note bodies — each Paperful-owned note should carry a
  stable **`paperful.note.v1`** block (type, model, verb, run id, prompt sha
  when relevant) in machine-readable form (HTML comment or agreed prefix),
  mirrored on `snapshot` under `notes/`; Zotero tags stay the update lookup
  key but are not enough when tags were renamed or two verbs overlap.
  **First line (Zotero UX):** the item pane shows the note’s **first line**
  before open — every writer should lead with a fixed, scannable prefix per
  type (e.g. `Summary (qwen2.5:7b): …`, `Duplicate: …`, `Attach: oa:unpaywall
  …`) so provenance and intent are obvious at a glance; retrofit existing verbs
  when deletion ships. Complements `dedupe` (merge parents, not note purge)
  and quiet-mirror `notes/` (audit on disk before `--apply`). Mendeley / EndNote
  parity after the Zotero path is boring.
- **CORE as an OA PDF source (shipped).** In `DEFAULT_SOURCES`; skipped until
  `core_api_key` is set. Stamp `oa:core`. `doctor` reports whether the key is set
  (green either way — optional lane).
- Library adapter seam (`LibraryBackend`). **Zotero is well tested.** Mendeley
  and EndNote are seeking testers (above).

### Mirror-first reads

**Status:** shipped. The rule is in
[architecture](architecture.md#mirror-first) and the
[developer guide](developer.md). Measurements before the change:
`assessments/2026-10-01-mirror-first-zotero-api.md` (local, not published).

Commands refresh `out/` from what changed in the library, read the mirror,
and write through it. Read verbs run with Zotero closed. A first refresh of
a 22,700-item library takes about a minute; a refresh with nothing changed
is six requests.

Still open:

- **`attachments`** still reads each item's children from the manager. It
  no longer downloads files to test for them.

Closed in this pass:

- **Mendeley and EndNote** implement `changes(since)` (Mendeley via
  `modified_since` / `deleted_since`; EndNote via `sdb.eni` mtime). Their
  reads take the mirror-first path when the feed is present. Still seeking
  testers.
- **Non-PDF attachments** copy into the item folder when `[mirror].pdfs =
  "all"`. Standalone notes and attachments land under `out/_notes/` and
  `out/_attachments/`.
- **Freshness on screen** includes last-refresh written/gone counts from
  `_sync.json`.
- **`paperful cache clean`** removes absorbed or stale files under
  `state/pdf-cache/` (dry-run unless `--apply`).

Not in scope: reading `zotero.sqlite` or `storage/` directly, and any sync
daemon.

(near-term-research-ops)=
### Near-term research-ops

**Status:** rows 1–24 shipped (literature-discovery complement waves 1–3 in rows 22–24). Same bars:
dry-run default, explicit `--apply`, fail closed, no silent library writes. See
[Documentation (thicken) — research pack](#documentation-thicken)
for the end-to-end operator story.

| Priority | Item | Status |
| --- | --- | --- |
| 1 | [`paperful refs gap`](#bibliography-gap-scan-later-not-gaps) — cited-in-PDF, not-in-library pack | Shipped |
| 2 | [Inbox match ladder](#inbox-match-ladder) (defer quarantine, title/OCR, optional `llm_when_thin`) + [create-on-unmatched](#core-keep-sharpening) (gated proposals) | Shipped (`create_auto`: unique DOI, or unique ISBN / report / title+year+host) |
| 3 | `paperful ingest-dois` — DOI list → `-C`, `--dry-run` / `--apply`, `--tag` | Shipped |
| 4 | Provenance tags on create (`--tag`, `[snowball]` / `[ingest]` default_tags, `from-<seed-slug>`) | Shipped |
| 4b | OA honesty miss enum + license/OA stamps on `run --dry-run`, `gaps`, handoff list, run report | Shipped |
| 5 | Grey playbook example packs (think-tanks, RFMOs, institute report hosts) via `[[grey_playbooks]]` | Shipped — ocean builtin (`rfmo-docs`, `iucn-dosi`, `thinktank-ocean`) plus `paperful/data/grey_playbooks_examples/` (IEA/IRENA, OECD/WHO/UNEP/UNDP) |
| 6 | Linked-URL health (Core above) | Shipped (`paperful urls check`; `--apply` only via a known playbook rewrite) |
| 7 | Non-DOI grey fingerprint (`norm(title)|year|registrant_host`; ISBN/report # when present) in snowball / dedupe / inbox ladder + inbox-create | Shipped (ISBN/report like DOI; title\|year\|host is review-tier; host mismatch is not `exists`) |
| 8 | `paperful collections add --keys-file` — membership batch, dry-run / apply | Shipped |
| 9 | Acronym allowlist harvest (Core `fix-metadata`) | Shipped (`paperful acronyms`; Title Case consumes `state/acronyms/`) |
| 10 | [Frontier digest](#frontier-digest-later-watch--external-ingest); thin [snowball briefing](#frontier-digest-later-watch--external-ingest) export before full digest | Shipped (`snowball digest`, `watch digest`, `watch run --digest`); newsletter ingest later |
| 11 | Scholar late tail + latch + opt-in SerpApi | Shipped (`[fetch].order` policy; interleave with `browser_agent`; `[handoff].scholar`; `[serpapi].enabled` / `max_calls`) |
| 12 | Authors/orgs frequency report from `-C` (`state/reports/…`; seed **field author packs**) | Shipped (`paperful authors`; `--apply` writes report + proposed pack) |
| 13 | Handoff list ranking (Core handoff) | Shipped (cite count × miss severity) |
| 14 | Opt-in academic HTML→PDF snapshot (Core `htmlpdf`) | Shipped (`[htmlpdf].academic` off\|gated\|auto; snapshot tier; `--upgrade-snapshot`) |
| 15 | Agent JSON + documented exit codes on batch verbs; MCP after those are stable | **Shipped** — `paperful.agent.json.v1` + exits 0/1/2/3 on batch verbs; optional `paperful mcp` (expanded in row 22) |
| 16 | Author-site PDF (registry + packs + co-author crawl; **snowball co-author preflight** / `grey:author_site`) | Shipped (opt-in; promote packs; SearXNG local-only) |
| 17 | ResearchGate request-from-author (**handoff-only**; config off by default; you click) | Shipped (`[request].channels`; `state/author-requests.jsonl`; `paperful reachout --handoff tabs`) |
| 18 | Twenty CRM — lookup cache plus `twenty sync` (create/enrich, Paperful note, late `author_site` before Scholar, opt-in listing write-back) | Shipped (`paperful twenty lookup` / `twenty sync`; `[twenty].enabled`; `--twenty-writeback`) |
| 19 | Typed note provenance (`paperful.note.v1`) + scannable **first-line** prefixes on all Paperful note writers | Shipped (summarize / synthesize / remarks / snowball / briefing) |
| 20 | `paperful notes delete` (or equivalent) — scoped filters: type, model, `--except-model`, tags; dry-run / `--apply` | Shipped (`--type`, `--model` / `--except-model`, `--all` + confirm / `--yes`) |
| 21 | [Author watch lists](#author-watch-lists-later-people-you-follow--their-papers) — ORCID / OpenAlex resolve + `run` / `apply`; file import of follows; corpus suggestions | **Shipped** — `paperful authorwatch` (+ suggest/accept/delete); saved social HTML/CSV import; Discover list management |
| 22 | [Literature-discovery complement](#literature-discovery-complement-waves) — **Wave 1:** read-only MCP (`gaps`, snowball dry-run / keyword preview, collection `export`) + BibTeX/RIS for snowball / `authorwatch` proposal packs | **Shipped** — `paperful mcp` tools + `export-proposals`; CLI snowball `--format json` loads `summary.json` on dry-run |
| 23 | Same — **Wave 2:** OpenAlex publication trend report for a query or saved snowball seed (`snowball trends`) | **Shipped** |
| 24 | Same — **Wave 3:** thicker `authorwatch` briefing (co-authors + recent works via OpenAlex) | **Shipped** |

(literature-discovery-complement-waves)=
### Literature-discovery complement (waves)

**Context:** Hosted literature MCP (e.g. [Valency MCP Bond](comparison-reference.md#valency-mcp-bond-and-hub))
covers corpus-scale semantic search, citation graph, and keyword trends. Paperful
does not replicate that index; these waves tighten the **local** loop and agent
surface so Bond-class tools pair cleanly with snowball, mirror, and `ask`.

Same bars as [near-term research-ops](#near-term-research-ops): dry-run default,
explicit `--apply` for anything that touches the manager, fail closed, one JSON
envelope for CLI and MCP.

| Wave | Scope | Acceptance |
| --- | --- | --- |
| **1** | **Agent MCP + proposal export** — Extend optional `paperful mcp` with read-only tools that call the same builders as CLI `--format json`: `gaps`; snowball crawl dry-run / keyword preview (no gate that writes parents); collection `export` (BibTeX/RIS). Emit BibTeX or RIS from on-disk snowball / `authorwatch` proposal packs (DOIs already resolved in the pack). | **Shipped** — `export-proposals` + MCP tools; docs in [commands](commands.md#agent-channel-format-json-and-mcp), [snowball](snowball.md#bibtex--ris-from-the-queue), [authorwatch](authorwatch.md#ledger). |
| **2** | **Publication trends** — Count works by publication year for an OpenAlex query or a saved snowball profile seed; reuse `OpenAlexClient` and budget posture as snowball. | **Shipped** — `snowball trends`, MCP `snowball_trends`; dry-run table + `--format json`; no library writes. |
| **3** | **Author briefing thicken** — `authorwatch show` / list briefing adds co-author network and recent works from OpenAlex (same resolution paths as `resolve` / `suggest`). | **Shipped** — `authorwatch briefing` + compact `show`; `--format json`; no new polling scheduler. |

**Non-goals for these waves:** hosting a global full-text index; Valency Hub–style
publishing; replacing Bond for “ask the whole literature” chat.

**Spike acceptance (one week, eng):** `refs gap` dry-run pack with zero manager
writes; `ingest-dois` idempotent apply + `held` on ambiguous resolve; `collections
add --keys-file` dry-run with per-key `not-found`; miss enum + license stamps on
OA success path; gated inbox proposal → apply/reject without silent create;
inbox drain dry-run on a fixture pack where DOI-less PDFs attach via title
fingerprint (deterministic) and one `when_thin` LLM case logs confidence without
auto-attach when below bar.
Golden CI fixtures for `paperful.run_report.v1`, `paperful.refs_gap.pack.v1`, and
`paperful.inbox.proposal.v1` — **shipped** (`tests/fixtures/` + `tests/test_schema_freeze.py`).

## Optional LLM assist (local / LiteLLM)

**Status:** MVP shipped behind `[llm].enabled = false` — Ollama loopback default,
LiteLLM via `paperful[llm]`. Verbs: `recover` (browser agent on `run` after
other vault lanes fail, plus `paperful recover --item`; `paperful[browser-agent]`,
Py 3.11+), `fix-metadata` title proposals (`[fix_metadata].llm_title`), `lint`
`pdf_identity_mismatch` (`[lint].llm_pdf_match`), `summarize` → tagged child note,
`synthesize` → literature review from those notes (`state/reports/` and, by
default, a collection note). Image PDFs need `paperful ocr --apply` first.
See [architecture § LLM layer](architecture.md#llm-layer-optional-local-first).
URL recipes from vault/agent wins are already `playbooks propose` / `promote`
← `state/fetch-wins.jsonl` (below), including agent step traces when the
agent lands a PDF. **Shipped:** `[browser_agent].fallback_model` (one retry),
`use_vision`, `recover --from-last-run`. Still later: Browser Use Cloud / BU2;
venue/date cleanup; **vault /
agent Chromium extensions** when the profile can load them safely (small
operator allowlist — e.g. cookie-consent dismiss, PDF/link helpers — so models
spend fewer steps on CMP noise and missed download controls; spike Playwright +
unpacked vs store extensions and whether extension UI confuses DOM/vision
agents); model and doc posture below; CAPTCHA posture in the next subsection.

(browser-use-integration-models-docs-config)=
### browser-use integration (models, docs, config)

**Status:** Shipped as optional **`paperful[browser-agent]`** (browser-use **0.13.x**,
Python **≥3.11**). Wired in `paperful/browser_agent.py`: **`ChatOllama`** or
**`ChatLiteLLM`**, session-vault **Chrome**, **`use_vision=False`**, PDF success
only when bytes pass **`min_pdf_bytes`** and size stabilizes (never trust agent
`done` alone). **`run`** auto-appends the lane when `[llm].enabled`,
`[browser_agent].during_run`, and the extra are on (policy order: one Scholar
try immediately before the agent when Scholar is opted in);
**`paperful recover --item`** runs the same runner in isolation. **heavy**
Compose images ship browser-use; **light** (CI default) does not. Headed
vault login still stays on the host (shared `state/`).

#### Documentation map (keep in sync)

| Doc | Role |
| --- | --- |
| [llm.md](llm.md) | Install extras, `[llm]` / `[browser_agent]` keys, `recover` behaviour, troubleshooting table |
| [browser-agent-models.md](browser-agent-models.md) | **Local Ollama tag guidance** for PDF UI loops (VRAM bands, avoid list, acceptance test) |
| [config.md](config.md#llm-optional-local-first) | Key table: `model`, `fallback_model`, `use_vision`, `during_run`, caps |
| [architecture.md](architecture.md) | Serial source ordering, Playwright handoff before agent, CAPTCHA → skip lane for run |
| [sessions.md](sessions.md) | Vault profile shared with recover; no concurrent vault users |
| [commands.md](commands.md) | `recover --from-last-run`, `--browser-agent` / `--no-browser-agent` on `run` / `all` |
| [docker.md](docker.md#image-mode-light-vs-heavy) | light vs heavy packs (`browser-use` in heavy) |
| `assessments/2026-09-29-ollama-browser-use-pdf-download-models.md` | Full research note (Infra rank + honesty/engineering cuts); **user-facing summary lives in `browser-agent-models.md`** |

When changing agent defaults, task text, or doctor floors, update **`llm.md`**
and **`browser-agent-models.md`** together so operators see one story.

#### Config contract (today)

```toml
[llm]
enabled = true
provider = "ollama"              # ollama | litellm
model = "qwen2.5:7b"             # summarize / synthesize / lint / fix-metadata
base_url = "http://127.0.0.1:11434"
allow_remote = false
timeout_s = 120

[browser_agent]
# model = "qwen3:14b"            # override for browsing only; omit → [llm].model
# fallback_model = "qwen3:30b"   # one retry before final not_found (not on captcha)
# use_vision = false             # true only with VL tags (qwen2.5vl, etc.)
during_run = true                # false → recover --item only unless --browser-agent
max_steps = 20                   # stop early when PDF lands
max_wall_s = 300
```

| Knob | Policy |
| --- | --- |
| **`[browser_agent].model`** | Always treat as **separate** from `[llm].model`. Browsing wants **tool-capable 14B+**; other verbs stay on 7B–12B. |
| **`doctor`** | Name-pattern amber under **~10B**; message points at **14b+ class** tag. |
| **`use_vision`** | Default **false**; set true only with a VL-capable `[browser_agent].model`. |
| **Vault** | Same **`user_data_dir`** as `session login`; extensions (uBlock, cookie banner) reduce step waste. |
| **Honesty** | Task + `_RECOVER_SYSTEM_EXT` forbid search engines, purchase, pirate hosts; hard CAPTCHA → **`captcha`** and lane silence for the run. |

Example operator split (dogfood): **`qwen3.8:latest`** for notes, **`qwen3-coder:30b`**
for recover on ~20 GB — coder MoE is **not** in the community top rank for UI;
validate on real publisher pages and prefer **`qwen3:30b`** / **`qwen2.5:14b+`**
if recover loops or mis-clicks.

#### Model selection (evidence, not a Paperful benchmark)

browser-use publishes **no official local-model quality table**; hosted
**ChatBrowserUse** / cloud VL scores do not transfer to Ollama quants. Consolidated
guidance (see [browser-agent-models.md](browser-agent-models.md)):

- **Floor:** community and GitHub threads cluster around **≥14B** for multi-step
  click loops; sub-7B tags parse-fail or time out.
- **24 GB+ band:** **`qwen2.5vl:32b`**, **`qwen3:32b`/`30b`**, **`qwen2.5:32b`**
  — best anecdotal reliability for publisher PDF flows.
- **12–16 GB:** **`qwen3:14b`** / **`qwen2.5:14b`** with raised Ollama context.
- **Avoid:** models without Ollama **tools** template (400), legacy **`qwen:`**,
  fragile **Gemma3** / **R1** loops, embedding models.
- **Qwen schema drift:** nested action objects; mitigations upstream = prompt
  examples — Paperful should extend system message if parse errors spike.

**Scoreboard for docs and dogfood:** schema-valid actions + **file on disk** +
no invented URL — not parameter count or model marketing copy.

#### Gaps vs upstream browser-use (roadmap)

| Item | Notes |
| --- | --- |
| **`[browser_agent].fallback_model`** | **Shipped:** one retry before final `not_found` (not on captcha). |
| **`use_vision` + VL tag** | **Shipped:** opt-in `[browser_agent].use_vision`; preflight/doctor check tag shape. |
| **`num_ctx` / temperature** | Pass through to `ChatOllama` or document Modelfile recipe; agent DOM dumps need **16k–32k+**. |
| **Schema hardening** | Nested JSON examples in `extend_system_message`; log parse failures to run report. |
| **Batch recover** | **Shipped:** `recover --from-last-run` + `--from-last-run-mode`. |
| **Playbooks from wins** | **Shipped:** agent successes write promotable `click:` / `rewrite` wins + optional `steps` in `fetch-wins.jsonl`. |
| **Browser Use Cloud / BU2** | Stealth / CAPTCHA — explicit non-default; no bypass product. |
| **Controlled bakeoff** | No Paperful CI fixture for “Springer cookie → PDF” per model; optional **`assessments/`** protocol later. |

#### When *not* to run the agent (product rule)

Deterministic lanes first: Unpaywall, OA APIs, httpx download, vault Playwright
(SSO / `citation_pdf_url` / download control). **`browser_agent`** only after
those miss on a URL the vault **already** may load. Handoff (`--handoff`,
`inbox watch`) remains the honest path for Scholar, CAPTCHA, and entitlement
the vault cannot hold.

### CAPTCHA / soft bot walls (open; do not ship a bypass product)

Hard CAPTCHAs end as `captcha` today; vault landings that look like
`login` / `captcha` / `no download control` already silence that host for the
rest of the run. Soft bot walls may improve with Browser Use Cloud stealth
(not wired). **No** Cloudflare-bypass product feature; Sci-Hub ALTCHA stays
on the opt-in Sci-Hub lane only.

Open questions before wiring anything else:

1. **Third-party solve APIs** (2Captcha, CapSolver, …) — paid, keys leave the
   machine, publisher ToS / campus AUP risk. Only consider behind explicit
   opt-in + disclaimer, never as a default, never for pirate hosts. Prefer
   human-in-the-loop over a solve service.
2. **Human-once, quiet-for-run?** If vault / browser-use keeps the **same
   persistent Chromium profile** (cookie jar, User-Agent, outbound IP), a
   human challenge solve that issues site clearance (e.g. Cloudflare
   `cf_clearance`) can quiet *subsequent* challenges on that zone for the
   cookie lifetime (often tens of minutes), as long as later traffic stays in
   that profile. Opening a tab in a *different* browser (system Firefox vs
   vault Chromium) does **not** transfer clearance. Spike worth trying: on
   `captcha`, pause like EZProxy re-login — open headed vault on that URL,
   wait for the operator to pass the challenge, resume the same host for the
   rest of the run — instead of (or before) permanent host silence. Measure
   how often clearance actually sticks across publishers.
3. **User-Agent switcher (between items or mid-run)?** httpx uses one
   `[fetch].user_agent`; vault / `browser_agent` reuse the profile string.
   **Explore:** rotate or override UA per host, per serial source phase, or
   after a soft block — vs keeping UA stable for the life of the cookie jar
   (mixed fingerprint often triggers harder walls). Same question for switching
   only on scripted httpx while leaving vault UA alone. Measure against host
   silence, 403/soft-block rates, and campus/Google posture; opt-in config only,
   not a default anti-bot product.

**MVP:** when a title looks wonky (ALL CAPS, truncated, HTML junk, filename-as-title,
mojibake), propose a cleaned title using **abstract and/or first-page PDF text**
as grounding. Output lands in the existing patch pipeline
(`state/metadata-patches.jsonl`); human review + `fix-metadata --apply` remain
mandatory. Never mutate the library from a model call alone.

Sketch:

```text
lint / heuristics flag bad title
  → extract abstract (item) + first-page text (pdfid / out/ cache)
  → opt-in LLM propose {title} JSON
  → validate (non-empty, length bounds, not equal to garbage patterns)
  → Patch(source="llm_title", …) beside deterministic patches
```

### Patterns to copy (do not invent a third stack)

Prefer **rollup’s** CLI-shaped LiteLLM/Ollama split; borrow **transcriptx**
enablement / grounding / review rules for “suggestions only.”

Sibling checkouts (not in this repo): `Documents/rollup`, `Documents/transcriptx`.

| Pattern | Draw on | Paperful takeaway |
|---------|---------|-------------------|
| Optional extra, no silent cloud default | rollup `pyproject.toml` (`[llm]` extra), `LlmExtraMissingError` | `paperful[llm]`; LLM off unless config/flag |
| Provider protocol + Ollama vs LiteLLM clients | `rollup/src/rollup/llm_client.py` | Thin `LLMClient` + `CompletionRequest`; local Ollama default path |
| Reject `ollama/…` via LiteLLM; no Ollama-only knobs on LiteLLM | `rollup/src/rollup/provider_options.py` | Same guards if both providers ship |
| Plan-time validation before network | `rollup/src/rollup/llm_validate.py` | Fail in `doctor` / before batch, not mid-run |
| Doctor import/config checks (no paid probe) | `rollup/src/rollup/doctor.py` (`_check_litellm_config`) | Amber/red when `llm_provider=litellm` without extra or model |
| Keys from env only; `api_base` validated | rollup `validate_llm_api_base`, `docs/CONFIG.md` | Document remote = title/abstract/PDF excerpt leave the machine |
| Pluggable client + Null stub | `transcriptx/src/transcriptx/core/llm/llm_client.py` | Fix code never imports provider SDKs directly |
| Suggestions grounded + human apply | `transcriptx/docs/runtime/corrections-llm.md` | Ground in abstract/first page; reject ungrounded titles; continue on failure |
| Opt-in module flag separate from global LLM | transcriptx `analysis.corrections.llm.enabled` | e.g. `llm.enabled` + `fix_metadata.llm_title = true` |
| Multi-provider stance (sidecar vs in-process) | `transcriptx/docs/ROADMAP.md` theme N | Start in-process LiteLLM like rollup; revisit sidecar only if weight hurts |

Config sketch (names TBD):

```toml
[llm]
enabled = false
provider = "ollama"          # ollama | litellm
model = "qwen2.5:7b"
base_url = "http://127.0.0.1:11434"
# api_base = ""              # LiteLLM / OpenAI-compatible
# allow_remote = false

[fix_metadata]
llm_title = false            # MVP gate; requires [llm].enabled
```

**Non-goals for the MVP:** blank-slate auto-tagging of the whole library,
rewriting abstracts, silent cloud defaults, applying patches without `--apply`.
Staged tagging (below) is **later**, not part of the title / PDF-identity MVP.
Chat-over-library in the **GUI** is a **1.0 goal** (see
[Zotero-RAG integration](#zotero-rag-integration-later-question-centric-layer));
terminal `ask` / `--thread` remain the CLI path.

**Later LLM verbs:** venue/date cleanup from the first page. Title proposals,
the PDF identity check, and grounded briefs (`summarize` / `synthesize`) are
shipped. Still proposals on disk; never a silent library write. **Note cleanup**
(selective delete by model / type, dedupe remarks, etc.) and shared
`paperful.note.v1` + first-line prefixes — [Core note hygiene](#core-keep-sharpening).

### Zotero-RAG integration (later; question-centric layer)

**Status:** CLI question-centric layer shipped — see [rag.md](rag.md). The index
is built in Paperful from the on-disk mirror (no separate zotero-rag install, no
reference manager calls): `paperful rag ingest | search | status | questions |
answered` and `paperful ask` (one cited answer, TTY/`--thread` follow-ups, or
`--from-file` batch). Opt-in under `[rag]`; `auto_ingest` is off by default.

**Interactive Ask in the GUI is shipped** — see [GUI](#gui) and [Product
split](#product-split-10-vs-post-10). Terminal multi-turn and the Index page
share `ask --thread`: follow-ups are rewritten for retrieval and stored under
`state/rag/threads/` with visible scope (collection chip, optional years) and
citations. Index exposes batch scope (`--item`, years, types), custom prompts
(inline, upload, path, saved under `state/prompts/`), and `rag questions` /
`rag answered` when Advanced is on.

Reuse the house LLM pattern: global `[llm]` + per-verb overrides (same spirit
as `[summarize].model`, `[browser_agent].model`, `[rag].model`).

**Direction:**

1. **Batch Q&A with citations** — **Shipped:** `ask --from-file` →
   `state/ask-batch/` (`paperful.ask_batch.v1`); resume via question hash +
   focus + index tip; optional Zotero collection note with `--apply` + `-C`.
2. **Question generation from summaries** — optional LLM pass over existing
   `summarize` outputs (and/or `synthesize` sections) to propose **unanswered**
   or **open** research questions for the corpus; land in a reviewable queue
   before batch RAG (same patch / dry-run honesty as other LLM verbs). Still
   roadmap (deferred; batch/`rag answered` already accept operator files).
3. **Prompt variants and `--focus`** — **Shipped:** `--focus`
   default|questions|gaps|methods|answered; `[rag].focus`; `--prompt FILE`;
   profile `focus` field.
4. **Extract questions posed by papers** — **Shipped:** `rag questions`
   (deterministic rules + optional `--llm` / `[rag].extract_questions_llm`) →
   `state/rag/questions/<key>.json` with provenance `rule`|`llm`.
5. **Corpus-wide RAG on those questions** — **Shipped:** `rag answered`
   `--from-file` / `--from-extract`, `--after-item`, year filters →
   `state/rq-answered/` (`paperful.rq_answered.v1`).
6. **Config** — **Shipped:** `[rag]` focus/prompt/dest/extract_questions_llm;
   profile `focus` + existing SCOPE. `doctor` ambers when the index is missing,
   the embedding model is unavailable, or the index is behind the mirror.

**Non-goals for this lane:** replacing Zotero’s reader; cloud-default RAG;
answers without citations; auto-mutating parent metadata from Q&A output;
scheduling nightly “ask everything” jobs without an explicit operator command.

**Consumer fit:** extends **Reading & knowledge** (below) and complements
`summarize` / `synthesize` — summaries stay the human-readable layer; RAG stays
the evidence-linked Q&A layer.

(bibliography-gap-scan-later-not-gaps)=
### Bibliography gap scan (shipped; not `gaps`)

**Status:** shipped — `paperful refs gap` writes `state/refs-gaps/` (`paperful.refs_gap.pack.v1`). Always dry-run.

| Today | Bibliography gap scan |
| --- | --- |
| **`paperful gaps`** (shipped) | **`paperful refs gap`** (shipped) |
| Items **already in scope** missing a stored PDF, linked-only URL, or DOI | Works **cited inside** your collection’s PDFs (or seed items) that are **not** in the library fingerprint |
| Drives `run` / handoff | Drives review pack → optional `ingest-dois` / snowball seed / gated create |

**Already in the tree:** snowball bibliography parsing
(`paperful/snowball/bibliography.py` — landing HTML, open-PDF reference
sections, `parse_bibliography_entries`); OpenAlex reference lists cached under
`state/cites/` for in-collection overlap remarks; Europe PMC / remote ref
recovery on hops. `refs gap` walks collection PDFs (mirror-first) and emits
**missing-from-library** rows as one operator-facing command.

**Direction:** `paperful refs gap` — inputs `-C`, seed item keys, and/or seed PDF
paths; always dry-run (never auto-create). Match: same fingerprint family as
`dedupe` / snowball (`DOI` → title+year; extend with [non-DOI grey
identity](#near-term-research-ops) when present). Output: stdout table +
`state/refs-gaps/<stamp>/` pack (`paperful.refs_gap.pack.v1`), reusing
`snowball.candidate` columns where they fit. Pack rows include at least
`cited_by_count_in_scope`, `oa_hint`, `already_exists`, `suggested_action`
(`ingest-dois` | `snowball doi` | skip). Gate: hand off to
`ingest-dois --dry-run` then `--apply`; optional rank for handoff. OCR /
text-layer required for scan-only PDFs (`ocr` first); clear finding, not crash.
Not a silent snowball auto-run. Treat as a **near-term research-ops epic** ([stack
above](#near-term-research-ops)).

### Briefing ↔ collection coverage (shipped; sibling of `refs gap`)

**Status:** shipped — `paperful coverage --from-note <key|path> -C …` or
`--from-file`. Always dry-run. Pack under `state/coverage/<stamp>/`
(`paperful.coverage.pack.v1`) with `in_collection` / `missing` / `ambiguous`;
`dois.txt` → `ingest-dois --from-file` / `--from-pack`. Same fingerprint family
as `refs gap`. Optional `provenance_hint` when tags are available.

### Frontier digest (later; watch + external ingest)

**Status:** digest shipped. Newsletter / alert ingest stays later. Snowball
**watch** stays dry-run and does not download PDFs. There is still **no**
built-in scheduler.

**Digest (Paperful):** `paperful snowball digest --run-id`,
`snowball watch digest`, or `snowball watch run --digest` writes
`digest.md` (run dir, or `state/snowball/watches/<name>/`). The report is
new vs `exists` vs version vs deferred, overlap hints on the top new rows
(`score`, `why`, hop, `overlap`), a suggested `-C` from the profile or
`[snowball].target_collection`, and paths for the queue, `apply`, and
`resume`. `--apply -C` files a collection note tagged
`paperful:frontier-briefing`. After `watch run` the queue file holds only
new proposals; `already seen` is the overlap with the prior frontier.
launchd / systemd / cron examples are in [snowball.md](snowball.md#watch).

**Thin briefing (still shipped):** `paperful snowball briefing --run-id …` /
`snowball watch briefing <name>` → markdown export of the dry-run or watch queue
(no silent creates; optional collection note `paperful:frontier-briefing` with
`--apply -C`). Surface
grey-vs-peer / OA stamp hints in briefing tables where provenance
exists (`grey:…`, `oa:…`).

**Newsletter / alert ingest (rollup bridge; post-1.0):** optional plug-in or HTTP client
to sibling **[rollup](Documents/rollup)**-style ingest architecture — pull
candidate papers from the operator’s **newsletters and alerts**, first source
**Google Scholar** email/alert feeds (opt-in; same honesty bar as Scholar in
handoff, not a silent `run` source). Normalise to DOI/title rows → Paperful
snowball queue or bibliography-gap / ingest path. Rollup owns fetch/parse of
mail sources; Paperful owns library fingerprint, gates, and ledger. Spike
shared message shapes before hard-wiring repos.

(author-watch-lists-later-people-you-follow--their-papers)=
### Author watch lists (in tree; people you follow → their papers)

**Status:** shipped — `paperful authorwatch`. Distinct from collection-scoped [`snowball watch`](snowball.md#watch)
(keyword / DOI / ORCID **seed** profiles and hop expansion). Here the seed is a
**named author list** the operator curates: people they already care about,
turned into a **local** watch for **new research outputs**, not career posts.
Live social scraping is out of scope; saved HTML/CSV exports import with `--file`.

**Direction:**

- **Lists on disk** — `paperful authorwatch save|add|remove|show|delete` maintains people under `state/authorwatch/<name>/` (display name, ORCID
  when known, optional affiliation host). `resolve` fills missing ORCID / OpenAlex ids; **held** on ambiguity.
- **Suggestions** — `paperful authorwatch suggest -C … --method corpus|most_cited|coauthor|mix` ranks people from the collection (and OpenAlex where needed). `authorwatch accept --id …` (optional `--seed-from`) moves checked rows onto the list; ledger `suggestions.jsonl`.
- **Watch run** — `paperful authorwatch run` sets a cursor baseline (no full-oeuvre fetch) then polls OpenAlex for works indexed after that cursor. `--backfill-from` proposes by **publication** date. `exists` stays out of the inbox. `authorwatch apply -C` creates parents (independent of `[snowball] enabled`). PDFs via `paperful run`. Paperful does not schedule.
- **Import** — CSV/JSON/ORCID files; `import --source rg|linkedin|academia --file saved.html` parses operator-saved exports. Without `--file`, prints the export recipe.

**Pitch:** Get what really matters from the people you already follow —
**their research**. Social follow graphs surface jobs, posts, and noise;
authorwatch turns that graph into a frontier of **new papers** from those
names, in one place — **your machine** (`state/`, optional `-C`, same
mirror and honesty contract as snowball).

**Non-goals:** replacing RSS or social timelines; auto-friending or messaging on
RG; cloud “who to follow” recommendations; live authenticated scraping of social
follow pages; treating social HTML as a `run` PDF source.

### Structured section extract (MVP; later)

**Status:** roadmap — narrower than full `summarize`; structured fields for
downstream RAG, synthesis, and gap scan context.

**MVP fields (per item, on disk):** `abstract`, `conclusion`, `methodology`,
`research_questions` (plus optional raw section map). **Stage 1 — deterministic:**
split PDF text (and manager abstract when present) on a maintained **heading
synonym list** — e.g. Abstract, Introduction, Background, Methods / Materials
and methods, Results, Discussion, Conclusion(s), Summary, Research questions,
Limitations, References / Bibliography (locale and publisher variants in
`state/section-headings.toml` or shipped defaults). Boundaries from line-start
heuristics + known IMRaD patterns; fail partial sections to findings, not
garbage writes. **Stage 2 — LLM inference** only when `[llm].enabled` and a
dedicated gate (e.g. `[extract_sections].llm`): fill missing MVP fields from
the bounded excerpt; reject outputs that do not quote-ground in the supplied
spans. Writes `state/sections/<key>.json` (and optional mirror into
`record.json` on snapshot); **no** silent Zotero parent mutation. Overlaps
Zotero-RAG RQ extraction (deterministic + LLM) — share heading list and
provenance enums where possible.

### Annotation mirror (later)

**Status:** roadmap — Zotero stays reader of record; the quiet mirror gains
**your** highlights and notes for RAG / evidence packs.

Read item annotations (and tagged notes where distinguishable) through
`LibraryBackend` on `snapshot` or a dedicated `paperful annotations mirror`
verb; store beside `record.json` under `out/` (hashes + page anchors). Read-only
sync into Paperful — never replace Zotero’s annotation UI. Consumers: cited
answers prefer operator highlights; future evidence-pack export. Group libraries
and adapter parity (Mendeley/EndNote) are explicit non-goals until tested.

### Run witness (shipped; trust thicken)

**Status:** shipped — optional `witness` (`paperful.witness.v1`) on every
`paperful.run_report.v1` written via `write_run_report` / `write_command_report`.
Includes config SHA-256, Paperful version, profile name when bound, scope,
fetch sources/preset, `[llm]` / RAG index tip, mirror `_sync.json` refresh.
Not part of `RUN_REPORT_KEYS` (additive). Open packs record `witness_id`
(first 12 of `config_sha256`) on each step. `refs gap` and `coverage` write
command reports so they join the pack trail.

### Auto-tagging library items (later; not 1.0)

**Status:** roadmap only — do not implement until the fetch / lint / attach loop
and 1.0 trust checklist are solid. Suggestions-only + human `--apply`, same
patch posture as `fix-metadata`.

Goal: durable domain / topic tags on items (Zotero tags and/or fields that
survive into `record.json`), so catalogues stay filterable and downstream
surfaces can use them. One consumer already named: a **domain-engagement
timeline** on the public site (`glen-w.github.io`) — distinct from that site’s
career timeline (type/role over years). Site plan:
`/Users/89298/Documents/website/glen-w.github.io/docs/dev/career-timeline-plan.md`
(section *Later: domain engagement timeline*).

Staged approach (ship in order; each stage can stop without the next):

1. **Built-in keywords** — harvest BibTeX `keywords`, existing Zotero tags, and
   any collection/label hints already on the item. Normalise casing/slugs into
   a reviewable patch set; no model calls. Write only on explicit `--apply`.
2. **Extraction from abstract / title** — rules, frequency heuristics, and/or
   light NLP keyword harvest grounded in local title + abstract (and optional
   first-page text). Prefer deterministic allowlists under `state/` (same spirit
   as the collection-scoped acronym harvest under Core `lint` / `fix-metadata`).
   Still findings → patches → human apply.
3. **LLM pass** — optional enrichment / normalisation behind `[llm].enabled`
   (and a dedicated gate, e.g. `fix_metadata.llm_tags`). Ground proposals in
   title/abstract/PDF excerpt; reject ungrounded tags; never silent library
   writes. Reuse the existing LiteLLM/Ollama client patterns above.

**Non-goals for this lane:** chat-over-library tagging UI; replacing Zotero’s
tag UI; publishing tags straight to the website without a review path; treating
LLM tags as source of truth without stage 1–2 anchors.

## Snowball

**Status:** keyword, multi-DOI / multi-ORCID, and collection seeds, hybrid keyword-then-hop,
`direction` sides `refs` / `cites` / `both` / `keywords` / `similar` (and
combos), gates including `approve-each`, overlap ranking, and optional `[llm]`
query suggestions are in the tree. Contract: [snowball.md](snowball.md). Still
outside: `expand = cited_authors`.

Snowball grows a library outward from a keyword, one or more DOIs, one or more
ORCIDs, or DOIs already in a collection. It writes a candidate queue on disk, then
creates items only under an explicit gate. `run` still fills PDFs. With
`fetch_pdfs`, snowball calls that same `run` in-process on the keys it just
created, so one command can go from a keyword to a collection with PDFs. The
stranger default is a dry-run: candidates only, no library writes, no
downloads.

The mechanic to port is the personal-site citation crawl
(`glen-w.github.io` `processing/library/citations.py`): a fixed one-hop
OpenAlex expansion (`referenced_works` out, `filter=cites:` in), polite
client, caps. Paperful needs a work list for the library. The site’s people
graph, hard-coded ego slug, and Scholar scrape stay on the site.

Phases, in order. Each can stop without the next.

1. **Dry-run. Shipped.** `snowball doi` / `search` write
   `paperful.snowball.candidate.v1` under `state/snowball/<run-id>/`.
2. **Writing gates and the one-shot library. Shipped:** `--gate auto` and
   `fetch_pdfs`, plus `approve-batch` / `snowball apply`, ORCID works (plus
   OpenAlex author fill), and collection DOI seeds.
3. **Optional expansion. Shipped:** `direction` including cited-by, OpenAlex
   keyword hops, and `similar` (one ranked hop: shared references, then
   Semantic Scholar recommendations; combinable e.g. `refs+similar`), plus
   depth above 1 under the same caps. A finished queue with no `deferred.json`
   resumes into create / PDF fetch without searching OpenAlex again.
4. **Config. Shipped:** `dedupe_scope`, type and venue filters, profile save,
   and CLI `--dedupe-scope` on crawl / `run` / `resume` / `apply` / `watch run`
   (`apply` still defaults to the full library).
5. **Last pass. Shipped:** `hybrid`, `approve-each`, overlap ranking,
   Crossref / Semantic Scholar fill, and `[llm]` suggestions on the queue.
6. **Watch. Shipped:** `snowball watch save` / `run` / `show` re-runs a saved
   profile, baselines the frontier on the first run, and proposes only unseen
   arrivals into `state/snowball/watches/<name>/inbox.jsonl` plus a normal
   run queue. Always dry-run / no PDFs. `watch digest` / `watch run --digest`
   writes the frontier rollup. Paperful does not schedule it; your
   own launchd or cron may call `watch run --digest`. See [snowball.md](snowball.md#watch).
7. **Co-author site preflight (opt-in). Shipped:** Before or alongside hop
   expansion, derive a co-author graph from the seed + candidate author lists,
   discover personal / institutional / static-site home pages for
   high-centrality names (ORCID researcher URLs, then an optional CRM listing,
   then SearXNG), and write them into
   [field author packs](#maybe-later-not-core) for the profile scope so the
   following `run` / `fetch_pdfs` pass can try the `author_site` grey lane.
   Proposed packs only until `snowball packs promote`. Opt-in profile knob;
   not a substitute for OpenAlex caps or gates.

### Dedupe during snowball — ongoing prevention, not merge-after

Snowball never runs `paperful dedupe` inside the crawl. **Ongoing** here means
duplicate work is collapsed and library hits are applied **while the queue is
built and before any parent is created**, not a one-shot merge at the end.
Stragglers still use the same hygiene loop as any other ingest:
`dedupe --dry-run` → read `state/dedupe-packs/` → `dedupe --apply` on the
target collection. Optional `--dedupe-after` / `[snowball].dedupe_after`
(`off` | `classify` | `apply`) can run that pack after create. There is
still no snowball step inside `paperful all` today.

Treat snowball dedupe and `paperful dedupe` as complementary:

| Layer | When | What it does | What it does *not* do |
| --- | --- | --- | --- |
| **In-run identity** | Every hop and on OpenAlex resume merge | One `candidates.jsonl` row per work (`doi:` or `openalex:` identity). Duplicate paths merge `seed_keys`, ref/keyword overlap, and scores. | Read Zotero; trash or merge parents |
| **Library fingerprint** | Once per crawl finish (and again on `apply` / saved-queue resume) | Normalized DOI, then title+year (same family as [dedupe](dedupe.md)); optional preprint ↔ published via `link_versions` → row `version` (tag only, no `versions` merge). `create_new` skips `exists` / `version`. | Re-scan the library on every reference hop; title+year `held_divergent_title` logic |
| **Hygiene `dedupe`** | Operator schedule (between batches or after a messy week) | Classify DOI groups and title+year packs; `--apply` merges extras onto a keeper. | Run automatically at snowball exit |

#### Timeline through one run

```text
seeds → hops (OpenAlex / filters)
  → crawl _dedupe (work identity, all hops so far)
  → fill / overlap / truncate
  → read library per dedupe_scope → _mark_exists on every row
  → write queue (dry-run / approve-batch) OR create_new (writing gates)
```

- **Dry-run and `approve-batch`** still perform the library fingerprint before
  `candidates.jsonl` is written, so the table’s “in library” column is the same
  signal `auto` would use later. Editing `keep=true` on an `exists` row does not
  create a parent; `create_new` skips it.
- **`snowball apply`** reloads the queue, re-runs `_mark_exists` against the
  **full library** (not the profile’s `dedupe_scope`), then creates only rows
  still `status = new`. A second apply skips DOIs already written from that
  queue. If you imported parents elsewhere between dry-run and apply, they show
  up as `exists` on apply — that is the main “ongoing” safety net for delayed
  gates.
- **`snowball resume`** after an OpenAlex budget pause merges new neighbours with
  `_dedupe` into the on-disk queue and re-runs the library fingerprint before
  optional `auto` create. **`resume` on a finished queue** (no
  `deferred.json`) re-marks `exists` (full library unless `--dedupe-scope`)
  before create/PDF continue.
- **`snowball watch`** is a second ongoing filter: baseline stores every work
  identity from the first profile run in `state/snowball/watches/<name>/seen.json`.
  Later runs still use the profile’s `dedupe_scope` during the crawl, but only
  rows that are `status = new`, not already in `seen`, and (on non-baseline runs)
  unseen since baseline land in `inbox.jsonl`. Library `exists` rows never become
  watch proposals even if the watch ledger has not seen that DOI yet.

#### `dedupe_scope` (config and profiles)

| Value | Fingerprint against | Typical use |
| --- | --- | --- |
| `library` (default) | All parents the backend can list | New topic collection; avoid duplicating anything you already own |
| `collection` | Parents under target `-C` only | Deliberately re-fetch metadata for works already filed elsewhere; **same DOI outside `-C` can still be created** |
| `none` | Skipped (yellow log) | Scout-only queues; `auto` / `approve-each` still refuse create if the library cannot be opened |

Persist with `snowball profile save --dedupe-scope …` or `[snowball].dedupe_scope` /
`profiles/*.toml`. CLI `--dedupe-scope` overrides per invocation on crawl
commands, `run`, `resume`, and `watch run`. `apply` stays full-library unless
that flag is passed on apply.

Indexed lookup (when the backend exposes `items_in_scope`) also maps arXiv IDs and
`preprint DOI:` lines in Extra into the DOI index, aligned with dedupe’s DOI
normalisation. The Zotero fast path uses `find_top_item_key` (DOI-first; title
fallback without the full title+year index).

#### Operator loop (large corpus + watch)

Recommended rhythm when snowball is actively growing a collection — same spirit
as the **Large corpus from scratch** worked example under [Documentation
(thicken)](#documentation-thicken):

1. **Pre-flight** — `dedupe -C <target> --dry-run` on the slice (or `--library`
   if the topic bleeds across collections). Fix obvious DOI collisions before
   the crawl so `exists` counts are trustworthy.
2. **Scout** — profile with `gate = dry-run`, `dedupe_scope = library`, realistic
   `max_candidates` / hop caps. Read `state/snowball/<run-id>/candidates.jsonl`
   (`exists_match` → `item_key`, `doi`, or `title_year`).
3. **Write** — `approve-batch` + `snowball apply`, or `gate = auto` on a named
   profile after one dry-run. Expect `skipped_exists` in the run report.
4. **Post-batch hygiene** — after `fetch_pdfs` / `run` stragglers, `dedupe` again
   on `-C` (title+year stragglers often appear here, not in snowball).
5. **Frontier** — `snowball watch save` / `watch run` on the same profile;
   review `inbox.jsonl`, then apply or manual import; watch does not download
   PDFs.

`paperful all` does not insert dedupe or snowball; chain explicitly (see
[workflows.md](workflows.md) fill recipes).

#### Why duplicate parents can still appear

- **`collection` scope** — fingerprint misses the same DOI in another collection.
- **`none` or unread library** — queue rows stay `new` until a later apply with
  a readable backend.
- **Stale queue** — manual edits, or apply long after dry-run without re-apply’s
  fresh `_mark_exists`. Resume-after-budget merge re-fingerprints before
  `auto` create; delayed apply still defaults to the full library.
- **Title+year blind spots** — missing year, `(untitled)`, HTML/title drift:
  snowball may create a second parent; `dedupe` may **hold** divergent titles on
  the same DOI instead of merging.
- **Parallel snowball or manual ingest** — two creates for one DOI before either
  run’s fingerprint; second wins only if apply re-check runs.
- **`version` vs merge** — preprint and version-of-record stay two parents unless
  you run `paperful versions` / `dedupe --apply`; snowball only marks `version`.
- **Same bytes, two parents** — [`attachments`](commands.md) / `dedupe`, not
  snowball.

#### Parked (snowball lane — thicker “ongoing”)

- **Align `snowball apply` with saved `dedupe_scope`** — apply still defaults
  to full-library fingerprint; `--dedupe-scope` on apply is the override.
- **In-run create index** — while `create_new` runs, feed new keys/DOIs back into
  the fingerprint so a single `auto` batch cannot create the same DOI twice if
  the queue had duplicates reintroduced by hand.
- **Manifestation-aware identity** — work ↔ preprint ↔ VoR graph (**Identity /
  resolver graph**, Maybe later §3); snowball keeps skip-only semantics.

Still outside this lane: every paper by every cited author; a snowball step
inside `paperful all`; a built-in scheduler; a review UI; systematic-review screening; a
citation-graph canvas; Sci-Hub or Google Scholar as snowball sources.

**OpenAlex snapshot store (opt-in).** Most installs use the live API only.
Institutions (or a personal homeserver) may host an [OpenAlex parquet
snapshot](https://help.openalex.org/access/snapshot/) and point
`[openalex_store]` at it. Architecture: a `WorksStore` transport behind
`OpenAlexClient` — not an entry in `snowball_backends`.

- **v1 (shipped):** `ssh_duckdb` — DuckDB runs on the data host; Paperful SSHs
  SQL and gets small JSON rows. Covers `work_by_doi` / `works_by_dois` /
  `works_by_ids` with API fallback for misses. Docs:
  [config Advanced](config.md#openalex-api-limits-and-snapshot-store),
  [snowball Advanced](snowball.md#advanced).
- **Post-1.0 (2B):** `works_citing` plus text search (`cites-query`) from the
  snapshot (likely an inverted cites index or careful scan strategy). Not required
  for 1.0 — the public API is generous for typical snowball / ingest loads.
- **Post-1.0 (2C):** keyword / ORCID / `search` parity; `local_duckdb` and `http`
  backends for campus hosting without SSH.

## Maybe later, not core

Workbench layers beyond the mirror contract. Worth keeping on the map; not
prerequisites for the fetch / lint / attach loop.

1. **Catalogue unification** — conflict journal; query-scoped virtual collections
   as run scopes. Mendeley and EndNote adapters exist and are seeking testers
   (above). Treating every manager as an equal is still later.
2. **Acquire beyond journal PDFs** — **shipped:** local session vault
   (`paperful session login`); soft-blocked OA → vault retry (Core above);
   manual handoff / PDF inbox (`--handoff`, `inbox watch` / `drain`);
   **pluggable grey-lit PDF playbooks** in
   `direct`/`landing` with builtin packs (UNGA/undocs · BBNJ/DOALOS · ISA;
   plus FAO, RFMO, IUCN/DOSI, IDDRI/Pew). IEA/IRENA and OECD/WHO/UNEP/UNDP
   are optional files in `paperful/data/grey_playbooks_examples/` — extend
   via `grey_playbooks_dir` or `[[grey_playbooks]]`. **Shipped:**
   **inbox match ladder** and **inbox create-on-unmatched** (config; unique-DOI
   `create_auto`; gated proposals). Still parked: **smart inbox** routing (Core
   above — snowball/recent-run context + ladder
   signals; LLM `off` | `when_thin` | `always`; model global + per-function;
   gated or auto);
   SI/dataset/code siblings;
   **opt-in LibGen** for `book` / `bookSection` gap-fill (title or ISBN routing;
   unofficial scrapers only — spike
   [libgen-api](https://pypi.org/project/libgen-api/) /
   [libgenesis-api](https://pypi.org/project/libgenesis-api/) first; same
   opt-in + disclaimer bar as Sci-Hub; no third-party HTTP gateways);
   **opt-in SearXNG** for author / personal-site / institutional-repo PDFs that
   Unpaywall / OpenAIRE / CORE never indexed. **Shipped** as author-site
   remainder search against `[searxng].base_url` (your instance, or a public
   one that serves JSON — [Twenty and SearXNG](snowball.md#twenty-and-searxng)).
   Not a default `run` source. Reuse the fetch +
   engine-rotation + disk-cache pattern from folk directory
   `ingest/scrape_searxng.py`; do not port the county×event grid. Query by
   title/author/`filetype:pdf` (or DOI), hand URLs to the existing download +
   PDF-identity checks.
   Same bar as legacy opt-in `scholar` on `run`: never in `DEFAULT_SOURCES`,
   circuit-breaker / sleep so fill runs do not burn the instance, CAPTCHA/empty
   engines are misses not hard fails. Wins when the PDF lives only on a personal
   page; complements handoff tabs rather than vault Scholar replay.
   **Field example (mesopelagic run, 2026-09):** Mendenhall 2024 missed every
   scripted lane; a web search surfaced a **direct PDF** on the author’s personal
   site at **result ~3** — not in Unpaywall-style indexes. The download URL’s host
   or path often carries the author surname (cheap **deterministic** match against
   `creator` / `lastName` before any LLM). Spike: rank SearXNG (or SerpApi web)
   hits with that host/token rule + `filetype:pdf` / `.pdf` suffix, then existing
   PDF-identity checks; log provenance as `grey:author_site` (or similar), not OA.
   **Author-site registry (grey; learned over time).** Successful personal-site
   fetches should accumulate a **local** map of “how to get this author’s PDFs” —
   not a hosted service. Keys: OpenAlex / ORCID author id when the item has one;
   else normalized name fingerprint (`last|first_initial` + optional affiliation
   host). Values: `base_host`, optional listing URL or path pattern, last-good
   direct-PDF URL or slug rule, `verified_at`, attach stamp `grey:author_site`.
   Feed from `state/fetch-wins.jsonl`, inbox/handoff saves, and operator
   `playbooks propose` / `promote` (same gated `learned.toml` posture as host
   grey packs — author-scoped rows, default propose-not-auto). On later misses,
   consult the registry **before** burning a web-search quota; treat hits as grey
   `direct`/`landing` playbooks, not OA. `doctor` ambers on stale entries; no
   silent promotion of third-party mirrors into the registry.
   **Field author packs (priority when names match).** Group registry entries into
   **packs** tied to keywords, topics, or `-C` / snowball profile scope (e.g.
   `ocean/mesopelagic` → authors seen often in that collection or seeded from a
   research pack). When a miss’s `creator` list intersects a pack active for the
   current run scope, **boost** that author’s site playbook and web-search rank
   (try known `base_host` before generic SearXNG). Packs are operator-owned files
   under `state/author-packs/` (or profile refs), mergeable from corpus stats
   ([authors/orgs frequency report](#near-term-research-ops) row 12 —
   `paperful authors -C … --apply`) plus manual curation — not an auto cloud
   graph. Same honesty: grey only, no OA mislabel.
   **Co-author expansion on personal sites.** Learn **frequent co-author** edges
   from in-library items (creator lists) and from bibliography / OpenAlex ref
   overlap; link co-authors to the same pack when they repeatedly co-publish in
   scope. When author **A** has a verified publications page, a miss on a paper
   where **B** (or C…) is on the item but only **A** is in the registry can still
   try **A’s site** — scan listing HTML/PDF links for title/DOI match to the
   target work (deterministic string match first). One site fetch may attach PDFs
   for several names on the author line; stamp which name triggered the lane.
   Co-author hints are suggestions until a win promotes them into the registry;
   disambiguate common surnames with ORCID / affiliation host when available.
   **Snowball preflight (co-author graph → author sites). Shipped**
   (opt-in; [snowball.md](snowball.md) / snowball phase 7): when `snowball`
   runs (dry-run or before `fetch_pdfs`), build a **co-author graph** from
   seeds, queue rows, and OpenAlex author ids; rank nodes by frequency in the
   frontier. For top authors, run bounded discovery (ORCID researcher URLs,
   optional CRM listing, then SearXNG remainder) to find faculty, GitHub Pages,
   Weebly, and similar **simple** hosts — then write a **proposed** field pack
   for that profile’s `-C`. Promote with `snowball packs promote` before
   `grey:author_site` fetch. Caps on authors/queries; no auto-promote. Complements
   post-hoc co-author site crawl on misses (still later, above).
   **ResearchGate “request from author” (config-gated, handoff-only).** When the
   item already has a `researchgate.net/publication` URL and `[request].channels`
   includes `rg`, `--handoff tabs` / `walk` on `gaps` / `run` / `paperful reachout`
   opens that page in the **system**
   browser. **You** click Request full-text. Paperful never automates the click
   (RG ToS / rate limits) and never searches ResearchGate for a URL. Fulfillment
   is async (email from authors). Ledger: `state/author-requests.jsonl`.
   `reachout` is the contact-only verb (no grab modalities; CSV of emails).
   **Twenty CRM (opt-in, shipped).** Lookup, sync, late `author_site`, and
   listing write-back are [Twenty and SearXNG](snowball.md#twenty-and-searxng).
   Paperful does not send mail. **RG vs email:**
   both channels can annoy the same author if mis-timed; treat as a **policy**
   knob, not one hardcoded path — e.g. `request_channels = rg | email | both |
   rg_then_email_after_days` with per-item “already requested” ledger
   (`handoff_opened` records channel + date). Email may cut through
   inbox noise when RG requests are ignored; RG may be faster when the author is
   active there — operator chooses. CRM writes stay on `twenty sync --apply`
   and `--twenty-writeback`; lookup stays read-only.
   **Marketing copy (later — ship only when the lanes above exist).** Draft
   positioning for site / README / comparison once learned grey playbooks,
   author-site registry, field packs, and co-author site crawl are real (local
   disk, not cloud training):

   > Paperful improves over time: it learns where the grey literature lives in
   > your field, remembers easy-to-access sources from your previous runs, and
   > keeps a list of authors with personal sites — and their co-author network —
   > so it can fetch co-authored papers from pages you already trust.

   Honesty bar: “learns” = your machine’s `state/` + promoted playbooks, not a
   shared model; grey and campus paths stay stamped; no implication of paywall
   bypass or universal completeness.
3. **Identity / resolver graph** — work ↔ version ↔ preprint; scored patches with
   undo; citation ingest; manifestation-aware dedupe. Collection DOI / title+year
   trash is already `paperful dedupe`. Snowball only **skips** rows that match
   those fingerprints before create ([Snowball — dedupe during snowball](#dedupe-during-snowball--ongoing-prevention-not-merge-after));
   it does not trash or merge existing parents. Preprint ↔ version of record is
   `paperful versions`: the older parent keeps the published citation and PDF,
   and the preprint stays as a version (snowball may tag a candidate `version`
   without running that merge).    **Shipped (research-ops):** `paperful ingest-dois --from-file dois.txt -C BBNJ
   --dry-run` then `--apply` (resolve Crossref/OpenAlex; skip `exists` under
   dedupe scope; report created / exists / unresolved / **held** on ambiguous
   title mismatch; repeatable `--tag` / `[ingest].default_tags`; hand off
   to `run` for PDFs). **Shipped:** `paperful collections add --keys-file keys.txt
   -C …` — membership-only batch (dry-run / apply; added / already-in /
   not-found). Complements `ingest-dois` (create parents) vs add (file existing
   keys). No scheduled bot inside Paperful. **Grey identity:** fingerprint
   `norm(title)|year|registrant_host` (plus ISBN/report number when present) for
   snowball / dedupe / inbox-create when DOI is absent.
   Growing a library from a keyword, one or more DOI bibliographies, or one or
   more ORCIDs is the
   [Snowball](snowball.md) section above, not a line item inside this graph.
4. **File & attachment OS** — **shipped (Zotero):** `paperful attachments`
   reports ghosts, broken links, same-file duplicates, and filename drift.
   `--fix-broken`, `--merge-files`, `--rename`, and `--link` write only with
   `--apply`, and only from files already under `out/`. `--link` is the
   stored-to-linked cutover and is refused for group libraries. The quiet
   mirror stays a dual `imported_file` store unless you pass `--link`. Still
   parked: full wrong-paper triage, orphan GC of unreferenced
   `storage/` files, author folders, and tablet send/get. **Shipped (slice):**
   one-page density gate — sparse stubs soft-reject and keep searching; denser
   one-pagers hold for `attach --allow-short-pdf`. PDF annotations and
   a full CSL dump are still later. A text layer for scans is `paperful ocr`.

## Maybe later

Larger product bets. Park until the ledger and core loop justify them.

5. **Reading & knowledge** — local full-text index; annotation sync;
   evidence packs; briefs grounded only in local PDFs. **Planned (see Optional
   LLM + subsections above):** [Zotero-RAG
   integration](#zotero-rag-integration-later-question-centric-layer);
   [bibliography gap scan](#bibliography-gap-scan-later-not-gaps) (cited-but-not-owned,
   distinct from shipped `gaps`); [structured section
   extract](#structured-section-extract-mvp-later); [annotation
   mirror](#annotation-mirror-later); [frontier
   digest](#frontier-digest-later-watch--external-ingest) (watch rollup shipped;
   optional rollup newsletter bridge, Scholar alerts first, still later); [author watch
   lists](#author-watch-lists-later-people-you-follow--their-papers) (shipped;
   saved social HTML/CSV import; live scrape still out). **[Run
   witness](#run-witness-later-trust-thicken)** ties batches to config/model/index
   for reproducibility.
6. **Writing & export** — CSL / BibLaTeX / Quarto sync; living review / gap lists;
   git-friendly CSL-JSON dumps; [briefing ↔ collection coverage](#briefing--collection-coverage-shipped-sibling-of-refs-gap)
   (shipped thin slice of parked “gap lists,” collection-scoped only)
7. **Agent surface** — MCP + CLI sharing one capability API; dry-run defaults;
   typed source/policy permissions; playbooks. **Shipped (CLI convenience,
   not a GUI):** named run configs and `paperful all` repeat a collection /
   year / type sequence (`profiles/*.toml`). Those are not grey-lit playbooks.
   **Shipped (opt-in):**
   [browser-use](https://github.com/browser-use/browser-use) as a *recovery*
   lane: last serial source on `run` after EZProxy / htmlpdf fail (today still
   after opt-in `scholar` until that source leaves core)
   (`[llm].enabled` + extra), and `paperful recover --item` for named keys.
   Never in `DEFAULT_SOURCES`, not “AI fetch everything.” Soft bot walls may improve with
   their Cloud stealth (not wired); hard CAPTCHAs stay human (see CAPTCHA
   open questions under Optional LLM). Vault fetch follows
   meta PDF links and SSO hops without an LLM. Successful vault and agent fetches
   log to `state/fetch-wins.jsonl`. `paperful playbooks propose` / `promote`
   install user-owned recipes in `grey_playbooks_dir/learned.toml` (default
   `gated`; `auto` is opt-in and can promote flukes). Learned packs are not
   shipped in the wheel. Still later: second-model fallback on agent failure
   (LLM section); playbook health / expiry; win analytics rolled into the run
   report (which hosts / win kinds paid off); **allowlisted extensions** on the
   vault profile for agent ergonomics (see Optional LLM — extensions bullet);
   **user-agent switcher** spike (CAPTCHA open question #3 under Optional LLM)
   for between-item or mid-run rotation vs stable profile UA. **Shipped:** `--format json`
   (`paperful.agent.json.v1`) on batch verbs (`run`, `refs gap`,
   `ingest-dois`, `inbox drain`, `ask`, snowball crawl/apply, …); documented exit-code
   table (`0` ok, `1` user, `2` manager down, `3` partial write batch). **MCP** is a thin
   optional stdio wrap of `refs_gap` + `ask` over the same envelope — not a second API
   and not a prerequisite for research-ops. **Literature-discovery complement shipped**
   (waves 1–3): read-only MCP for `gaps`, snowball preview, `snowball_trends`,
   `export`, `proposal_export`, plus `export-proposals`, `snowball trends`, and
   thickened `authorwatch briefing` — [Literature-discovery complement](#literature-discovery-complement-waves). Writes stay
   CLI `--apply`. `collections add` is CLI-only (not an MCP tool).
   **Shipped:** Twenty sync, lookup, and `--twenty-writeback` —
   [Twenty and SearXNG](snowball.md#twenty-and-searxng).
   Request-channel policy stays config (`[request].channels`), not agent-default.
   Contact surface without fetch is `paperful reachout` (CSV + optional RG tabs).
8. **Collaboration without SaaS** — shared `state/` over syncthing/git; attach
   locks; optional headless fetch node. Aligns with the house
   [quiet mirror](quiet-mirror.md) stance: Syncthing (or similar) is transport;
   Paperful stays a local CLI, not a sync product.
9. **Compliance & provenance** — 1.0 attach stamp is listed above. On disk,
   `record.json` plus `out/_history.json` are the chain-of-custody note for
   the library and the append-only ledgers. OA `license` / `oa_status` /
   `version` stamps (Core above) feed this lane; which fields are written stays
   config-driven. **[Run witness](#run-witness-shipped-trust-thicken)** extends
   run reports and packs with config/model scope. Still later: optional
   redistribution / license gate using those stamps, more jurisdictional
   presets, and PDF annotation export (annotation **mirror** is read-sync into
   `out/`, not export-only).

## Explicitly out of near-term scope

- Hosted multi-user service
- Replacing Zotero as a reading UI
- Shipping Sci-Hub or proxy abuse as defaults (opt-in + presets stay as today)
- Jeffersonian transcription / qualitative coding apps

## Optional thin bridge — Firefox extension (post-1.0)

**Status:** design-only; **post-1.0** ([Product split](#product-split-10-vs-post-10)) — **not** a replacement
for the Zotero Connector. Same Control posture as the CLI (dry-run default,
explicit Apply, fail closed if Paperful is unreachable). Feasibility +
contracts researched 2026-09-29 (local notes; substance locked below).

Three explicit toolbar actions (no single “grab everything”):

| Action | Maps to | Priority |
| --- | --- | --- |
| **Snowball this DOI** — detect DOI on the current page → `paperful snowball doi` | CLI already writes `paperful.snowball.candidate.v1`; dry-run → optional Apply + `-C` | **P0** |
| **Ingest to quiet mirror** — current page → `out/` (`paperful.item.v1`) → Zotero upsert via LibraryBackend | `ingest-dois` / inbox create exist on the CLI; extension still needs a thin ingest action | **P1** |
| **PDFs from open tabs** — enumerate tabs, confirm checklist, download with tab cookies into `[inbox].dir`, then `inbox drain` | Campus entitlement strength; refuse pirate hosts; park unattended mass download | **P1** spike |

**v0 transport (room lock):** Extension → **`nativeMessaging`** host → shells
`paperful` CLI (dry-run JSON → confirm → write). No new daemon and no invented
localhost Capability API for these three actions. Thin `paperful serve` /
Capability API for the 1.0 workbench targets HTTP — [gui.md](gui.md). The
extension may reuse the same API later via native messaging. **Wrong:** extension → Zotero `:23119`
directly (skips quiet mirror + provenance; do not replace Connector for
cite-save).

**Contracts (names):** NM message shapes `snowball.doi`, `ingest`,
`tabs.pdfs.plan` / confirm with the same dry-run + miss-enum honesty as the
CLI. DOI detect: Unpaywall-style meta list first (`citation_doi`,
`dc.identifier.doi`, …), then doi.org links, then bounded regex — not a full
Zotero translator VM. Provenance: `paperful web:extension` (or `campus:…`
when the URL matches a configured proxy host). Hard-refuse Sci-Hub / LibGen /
known pirate hosts on the tab-PDF job.

**P0 spike:** content-script DOI → native host → `paperful snowball doi …`
`--dry-run` → popup shows `run_id` + new/exists counts.

**Blockers / gaps:** `[snowball].enabled` opt-in; ingest create-parent verb
missing; mass-download ToS / campus AUP (confirm count, concurrency cap);
AMO friction (sideload fine for personal spike); do not collide with Zotero
23119.

**Inspo (steal patterns, not product identity):**
[zotero-connectors](https://github.com/zotero/zotero-connectors) (inject /
background / localhost maturity),
[unpaywall-extension](https://github.com/ourresearch/unpaywall-extension)
(DOI meta + legal OA posture),
[JabRef browser extension](https://docs.jabref.org/collect/jabref-browser-extension)
(local-manager pairing; JabRef’s HTTP direction informs later Capability API),
DownThemAll / Pull Tabs for paced tab-download UX only.

## Documentation (thicken)

**Status:** roadmap — reference docs exist; playbooks and media do not yet match
the depth of the CLI. Raises trust before install; **GUI 1.0** should ship with
worked examples and screenshots for the main workbench modes (see [GUI](#gui)).

Ship in layers:

0. **Research pack playbook** — [research-pack.md](research-pack.md) (narrative spine for `-C` topic builds):
   seed greys + seed papers → `refs gap` → `ingest-dois --dry-run` → `--apply`
   with provenance tags → `run` / handoff / inbox for PDFs → `dedupe` hygiene →
   optional `snowball watch` + [frontier digest](#frontier-digest-later-watch--external-ingest)
   → `summarize` / RAG only after the ledger is honest.
1. **Example commands and templates** — copy-paste invocations plus
   `profiles/*.toml` and config snippets for recurring flows: `-C` / collection
   scoping, `--dry-run` → `--apply`, `paperful all`, snowball profiles and
   gates, `[inbox].dir` handoff, `session login` (Zotero / Mendeley / campus
   vault), and `[llm]` gates spelled as one-liners with expected exit codes.
2. **Worked examples** (narrative walkthroughs: starting state → command
   sequence → banners / `state/` paths → Zotero outcome):
   - **Messy folder / uneven library** — weak metadata, broken or ghost PDF
     attachments, same bytes on two parents, title+year stragglers: `doctor` →
     `lint` / `fix-metadata` → `attachments` → `dedupe` → `run`, always
     dry-run and read packs on disk before `--apply`.
   - **Large corpus from scratch** — snowball from **keyword** plus seed
     **DOI**s (profile save, `direction` / `hybrid`, `dedupe_scope`, gates,
     optional `fetch_pdfs`, then `run` for stragglers; optional `watch` for
     frontier inbox) with a realistic cap / approve story.
   - **Research pack** — follow layer **0** above on a named `-C` (refs gap pack
     on disk, ingest tags, handoff walk, watch inbox).
   - **PDFs for an existing collection** — two passes documented side by side:
     **quick** (default sources, `--dry-run` Would-hit, CORE / grey playbooks,
     EZProxy session hygiene, `run` banner); **full** (`session login` / relogin for **EZProxy** (not Scholar-as-bot),
     vault retry on soft-blocked OA, optional `[browser_agent]` on
     `run` or `recover --item`, `--handoff list|tabs|walk|watch` including
     Scholar in the **system browser**, PDF download into `[inbox].dir` and
     `inbox drain` / `watch`).
3. **Screenshots and video guides** — annotated screenshots for dry-run tables,
   `doctor` colour lines, attachment provenance in Zotero, snowball queue rows,
   and handoff inbox layout; short screen recordings aligned with the three
   worked examples above (hygiene, snowball, fetch quick vs full).
4. **Developer guide** — [developer.md](developer.md). **Shipped:** the
   mirror-first rule, what a command's backend serves from disk, rules for
   new code, the module map, the refresh, disk schemas, and how to add a
   verb, a source, or an adapter method. Keep it current when a rule or a
   module boundary changes.

Keep new pages linked from README and [commands.md](commands.md); avoid a
second doc tree that drifts from the CLI.

## Related docs

- [architecture.md](architecture.md) — disk-first adapters, the mirror-first rule, and data flow
- [why.md](why.md) — library, find, completeness, mirror, control; what is true today
- [quiet-mirror.md](quiet-mirror.md) — `out/` as the copy you keep
- [releases.md](releases.md) — 0.x vs 1.0; known limits
- [comparison.md](comparison.md) — what Paperful does and does not replace today
- [snowball.md](snowball.md) — library-building from a keyword, multi-DOI / multi-ORCID, or collection
- [bbnj-author-lanes.md](bbnj-author-lanes.md) — dogfood `author_site` + `authorwatch` on `ocean/BBNJ` / `ocean/BBNJ-test`
- Site career / domain timeline plan (consumer of durable tags):
  `/Users/89298/Documents/website/glen-w.github.io/docs/dev/career-timeline-plan.md`
- Firefox extension (post-1.0 thin bridge) — section above; not a separate doc yet

## GUI

**1.0 deliverable** — workbench (open / Docker first): [gui.md](gui.md).
**Landed:** `paperful.item.v1` lock, `paperful serve` HTTP + server-rendered UI
under `paperful/ui/` — default nav **Wanted** (also `GET /`) then **Discover**,
Preview → Grab (fetch to `out/` only) → Attach (explicit library write), with
review tokens and command ids under `state/gui/commands/`; Activity run-status
SSE on `GET /v1/runs/{id}/events`. Empty Wanted shows a
coach line when there is no collection or the library is down. Discover covers topic
queues (keep/skip, briefing, digest, profile run, resume, watches), people
lists (create/add/resolve/run/import/suggest/accept, inbox apply), and Advanced grow tools
(refs gap, ingest-dois, authors, packs promote). Queue/watch briefing and
digest can file a collection note (`paperful:frontier-briefing`). **Advanced**
(cookie) reveals Repair, Mirror, Index, Briefs, Settings and extra form fields
without enabling opt-in sources. Repair/Mirror Preview is dry-run; Apply uses
the same entrypoints as the CLI. TTY (`session login`, `doctor --guide`,
mid-run EZProxy), `collections add`, `approve-each`, and Sci-Hub stay CLI.
**Not tagged 1.0.** Polish left is tagging and screenshots.

The CLI stays the source of truth; the GUI marshals the same verbs with dry-run
default and explicit Apply. Not a second fetch stack or Zotero’s reader.
**Firefox extension** is post-1.0.

**Ask (Index, opt-in):** **Shipped** — scoped chat with citations when `[llm]` and
`[rag]` are on and the index has rows. Collection chip is the scope; threads live
under `state/rag/threads/` (same as `ask --thread`). Index also runs `rag ingest`,
`rag search`, batch Ask (item/year/type/top-k/force, custom prompts),
`rag questions`, and `rag answered`. **Briefs** (Advanced) runs `summarize` and
`synthesize`. CLI `ask` remains for scripts, TTY multi-turn, and run profiles.
See [Zotero-RAG integration](#zotero-rag-integration-later-question-centric-layer).
