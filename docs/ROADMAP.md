# Roadmap

Guidance for contributors, not a commitment calendar. Paperful’s jobs are
**library**, **find**, **completeness**, **mirror**, and **control**: one
disk mirror (`out/`, `state/`), adapters for citation managers, and fetch /
lint / attach / summarise as the core loop. **Zotero is the well-tested
adapter.** Mendeley and EndNote are in the tree and seeking testers. See
[architecture.md](architecture.md) and [why.md](why.md).

Surfaces like a Zotero plugin, Firefox extension, or web GUI are **not** the
1.0 product direction. Optional thin bridges (`paperful session login`, and a
parked Firefox extension below) capture a local browser profile or shell CLI
verbs; they do not rewrite the fetcher.

**1.0** is that loop, the trust checklist below, and a locked item record
(`paperful.item.v1` plus `snapshot` / `restore`), proven on **Zotero**. Mendeley
and EndNote adapters are not 1.0 until testers have exercised them. Not a GUI,
not a full-text reading index, not a WebDAV client, and not “AI fetch everything.”
`paperful ocr` is the optional text layer for scans.

(trust-10)=
## 0.1 → 1.0 (trust + mirror contract)

`0.1` is a first usable helper for a reference library. Do not call it **1.0**
until these land. Do **not** grow this list into a second product (no GUI, no
auto Sci-Hub, no “AI fetch everything”).

| Step | UX outcome | Status |
| --- | --- | --- |
| End-of-run **one-line** banner: `downloaded N · attached M · deferred K · not_found J` plus write-API yes/no | Trust after a run | Shipped (table still follows the line) |
| Attachment **provenance stamp** (`oa:unpaywall` / `campus:ezproxy` / `grey:undocs` on notes or title prefix) | Trust inside Zotero | Shipped on the Zotero attachment note. A readable parent line follows `[remarks].surface` |
| `--dry-run` **Would-hit** column (sources in order) | Trust before network | Shipped |
| Exit **2** + next-steps when Zotero is down (`collections` / `run` / `attach`) | Fresh clone never dead-ends | Shipped |
| Slim README + [CHANGELOG](../CHANGELOG.md) known limits | Trust before install | Shipped |
| Lock `paperful.run_report.v1` | Trust for agents | Required keys frozen; extra keys may be added. Not tagged 1.0 |
| Lock `paperful.item.v1` and `snapshot` / `restore` (additive keys only after 1.0) | Trust for the disk ledger | Named schema; 0.x may add keys. Behaviour shipped |
| Strip legacy flat-PDF migrate + mixed-layout doctor amber | Day-0 mirror never steers people into a whole-library layout cleanup | **Shipped (0.1 → 1.0)** |
| **Mendeley and EndNote adapters** | The ledger survives a manager change | In the tree. **Seeking testers.** Zotero stays the well-tested path. See below |

Nice-to-have (not 1.0 blockers): colour glossary next to `doctor` (documented);
collection picker hint on fuzzy `--collection` miss.

### Mendeley and EndNote (seeking testers)

The code is in the tree. It has not been proven on real libraries the way
Zotero has. Do not document either adapter as supported until testers say so.

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
  watch` / `drain` against `[inbox].dir` (today: PDF **DOI-only** attach to
  missing-PDF parents; `inbox` defaults to whole-library scope so one drop
  folder serves every topic; anything else → `unmatched/` immediately). Operator
  pain: Zotero **Retrieve Metadata** often recognizes the same PDFs Paperful
  quarantined — inbox does not call the manager recognizer or wait before
  quarantine ([match ladder](#inbox-match-ladder) below). Distinct from snowball
  watch `inbox.jsonl`. **Later (handoff):**
  rank `--handoff list` by in-corpus cite count (from [refs gap](#bibliography-gap-scan-later-not-gaps))
  × miss severity so limited browser time hits high-value PDFs first. CLI
  `--browser-agent` / `--no-browser-agent` overrides `[browser_agent].during_run`
  for one `run` / `all`. **Later (author-site + RG):** personal-site PDF discovery
  via opt-in web search ([Acquire §2](#maybe-later-not-core)); ResearchGate
  request-from-author only behind config when vault/handoff already has an RG
  session ([same section](#maybe-later-not-core)).
- **Academic HTML→PDF snapshot (optional, later).** `htmlpdf` today applies only
  to web/news types (and DOI-less `document` / `report`); journal articles skip
  with `not a web/news item` even when `run` already reached the publisher HTML
  reader (OA, EZProxy, `direct`, or vault retry) but no lane returned a native
  PDF. **Direction:** opt-in fallback after scripted lanes exhaust — Playwright
  print-to-PDF of the article URL the operator would otherwise open in handoff.
  Provenance must read as a **page snapshot**, not publisher PDF or licensed OA;
  reuse session vault, paywall hints, and `min_pdf_bytes`; off by default on
  DOI journal items so completeness runs do not silently attach HTML prints.
- **Google Scholar — out of core `run`, handoff + API research (next).** Today
  `scholar` is an opt-in serial source that replays cookies from the session
  vault (same Chromium profile family as EZProxy). In practice it rarely stays
  healthy: sessions expire, fingerprint drift, and Google serves `/sorry/` CAPTCHA
  (`doctor --probe` ambers are common). **Direction:** remove automated Scholar
  from the reliable fetch loop (not from the repo overnight — deprecate in docs
  and presets first, then drop the `run` source once handoff covers the workflow).
  **Replace with end-of-run handoff:** after OA, EZProxy, grey playbooks, and
  optional `browser_agent`, open remaining misses via `--handoff list|tabs|walk|watch`
  so the operator uses their **usual working browser** (logged-in Google, campus
  extensions, saved passwords) — not isolated vault Chromium — to find PDFs and
  save into `[inbox].dir` → `inbox drain`. Scholar URLs belong in that tab list,
  not as a bot lane mid-batch. Same posture as the parked Firefox extension
  **PDFs from open tabs** (tab cookies, confirm checklist, paced download).
  **Research before any new automated Scholar lane:** spike third-party Scholar
  APIs and metadata-only discovery (e.g. [SerpApi Google Scholar
  API](https://serpapi.com/google-scholar-api) — structured results, pagination,
  `cites` / `cluster`; paid key, quota, and ToS vs local scrape). Evaluate for
  **link discovery and bibliographic fill**, not bulk download or a silent cloud
  default; must fit opt-in config, circuit breaker, and the OA honesty miss enum.
  **SerpApi already exercised elsewhere:** [Google Maps via
  SerpApi](https://serpapi.com/google-maps-api) worked well in recent work —
  borrow that repo’s client patterns, env key / quota handling, and test
  credentials when spiking Scholar (or other SerpApi engines) so Paperful does
  not invent a second third-party API stack.
  OpenAlex / Semantic Scholar / Crossref remain the programmatic defaults; Scholar
  stays out of snowball backends. CAPTCHA solve services stay out of scope (see
  CAPTCHA section).
  **Near-term run behaviour (while `scholar` is still on `run`):** the serial
  Scholar phase queues every OA miss and then hits Google once per item (~
  `delay_scihub_s` apart). HTTP **429** is recorded as `error`, not `captcha`, so
  the circuit breaker still ignores it (429 is excluded for API `Retry-After`
  lanes). **Shipped (latch):** the first Scholar 429, 503, or CAPTCHA /
  `/sorry/` page skips Scholar for the rest of the run, across batches; queued
  items get `scholar:skipped(blocked)` and end `retryable`. **Spreading load:** shuffling queue
  order alone does not help much; what helps is fewer requests after a clear block
  and/or spacing attempts across the whole run (shared rate limiter, per-item
  Scholar only after long jitter, or interleaving with other work) instead of one
  end-of-batch burst after parallel OA.
- **Inbox create-on-unmatched (config, later).** Optional `[inbox]` mode so
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
  Tag parents `inbox-created` for later `dedupe` / `refs gap`. Optional
  multi-root `[inbox].dir` list with provenance `inbox:<dirname>`. End-of-drain
  one-liner + JSON (attached / created_gated / unmatched), same honesty as
  `run`. Today’s default stays DOI attach only — no silent create-parent.
(inbox-match-ladder)=
- **Inbox match ladder (before `unmatched/`, config, later).** Optional stages
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
- **Smart inbox (optional, later).** Today `inbox` only attaches a PDF onto an
  existing missing-PDF parent by DOI (or FIFO in a handoff session). It does not
  choose a collection or create parents. Builds on **create-on-unmatched** and the
  **match ladder** above (ladder = *which parent* among missing-PDF rows; smart
  inbox = *which collection* when creating or routing).
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
- **OA honesty / miss taxonomy (next).** Project internal miss status to a frozen
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
- **Linked-URL health (later).** `doctor` and/or `paperful urls check -C …` —
  short-budget HEAD/GET on metadata URLs; findings `ok | redirect | soft_404 |
  hard_dead | paywall_html` (no rewrite unless `--apply` from a known mirror list).
  Feeds handoff for linked-only greys; pairs with grey playbook packs.
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
  `title_filename`). Filename titles stay findings-only. De-allcaps today only keeps
  two-letter tokens (UN, EU); longer corpus acronyms (BBNJ, FAO, OECD, …) still
  get Title-Cased. **Next:** collection-scoped NER / acronym harvest — scan titles,
  abstracts, and venues once, write a durable allowlist under `state/`, and feed it
  into `title_to_title_case` so known all-caps entities stay uppercase on recase.
  Deterministic first (freq + shape heuristics); optional LLM NER only as a later
  assist behind the existing `[llm]` gate.
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
- CORE as an OA PDF source when `core_api_key` is set
- Library adapter seam (`LibraryBackend`). **Zotero is well tested.** Mendeley
  and EndNote are seeking testers (above).

### Near-term research-ops

**Status:** next — thicken and ship verbs already named on this page; not a second
product. Same bars: dry-run default, explicit `--apply`, fail closed, no silent
library writes. See [Documentation (thicken) — research pack](#documentation-thicken)
for the end-to-end operator story.

| Priority | Item | Status |
| --- | --- | --- |
| 1 | [`paperful refs gap`](#bibliography-gap-scan-later-not-gaps) — cited-in-PDF, not-in-library pack | Next |
| 2 | [Inbox match ladder](#inbox-match-ladder) (defer quarantine, title/OCR, optional `llm_when_thin`) + [create-on-unmatched](#core-keep-sharpening) (gated proposals) | Next |
| 3 | `paperful ingest-dois` — DOI list → `-C`, `--dry-run` / `--apply`, `--tag` | Parked (Identity §3) |
| 4 | Provenance tags on create (`--tag`, `[snowball]` / `[ingest]` default_tags, `from-<seed-slug>`) | Next (with 1–3) |
| 5 | Grey playbook example packs (think-tanks, RFMOs, institute report hosts) via `[[grey_playbooks]]` | Ongoing |
| 6 | Linked-URL health (Core above) | Later |
| 7 | Non-DOI grey fingerprint (`norm(title)|year|registrant_host`; ISBN/report # when present) in snowball / dedupe / inbox ladder + inbox-create | Later |
| 8 | `paperful collections add --keys-file` — membership batch, dry-run / apply | Parked (Agent §7) |
| 9 | Acronym allowlist harvest (Core `fix-metadata` next) | Next |
| 10 | [Frontier digest](#frontier-digest-later-watch--external-ingest); thin [snowball briefing](#frontier-digest-later-watch--external-ingest) export before full digest | Later |
| 11 | Scholar 429 latch (Core Scholar) | Shipped |
| 12 | Authors/orgs frequency report from `-C` (`state/reports/…`; seed **field author packs**) | Later |
| 13 | Handoff list ranking (Core handoff) | Later |
| 14 | Opt-in academic HTML→PDF snapshot (Core `htmlpdf`) | Later |
| 15 | Agent JSON + documented exit codes on batch verbs; MCP after those are stable | Next / Later |
| 16 | Author-site PDF (registry + packs + co-author crawl; **snowball co-author preflight** / `grey:author_site`) | Later |
| 17 | ResearchGate request-from-author (logged-in vault; config off by default) | Later / explore |
| 18 | Twenty CRM — author lookup (website → registry; email for mail merge / PDF request; channel policy vs RG) | Later / explore |
| 19 | Typed note provenance (`paperful.note.v1`) + scannable **first-line** prefixes on all Paperful note writers | Next |
| 20 | `paperful notes delete` (or equivalent) — scoped filters: type, model, `--except-model`, tags; dry-run / `--apply` | Later |
| 21 | [Author watch lists](#author-watch-lists-later-people-you-follow--their-papers) — ORCID resolve + list `run`; optional import from RG / LinkedIn / Academia follows | Later |

**Spike acceptance (one week, eng):** `refs gap` dry-run pack with zero manager
writes; `ingest-dois` idempotent apply + `held` on ambiguous resolve; `collections
add --keys-file` dry-run with per-key `not-found`; miss enum + license stamps on
OA success path; gated inbox proposal → apply/reject without silent create;
inbox drain dry-run on a fixture pack where DOI-less PDFs attach via title
fingerprint (deterministic) and one `when_thin` LLM case logs confidence without
auto-attach when below bar.
Golden CI fixtures for `paperful.run_report.v1`, `paperful.refs_gap.pack.v1`, and
`paperful.inbox.proposal.v1` when those land.

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
← `state/fetch-wins.jsonl` (below). Still later: **second-model fallback** on
`browser_agent` / `recover` (one retry with
`[browser_agent].fallback_model` — prefer a larger local tag or LiteLLM when
`allow_remote` — before `not_found` / `captcha`; not a cascade); Browser Use
Cloud / BU2; batch `recover --from-last-run`; mining richer playbooks from
agent *step* traces (beyond host/path wins); venue/date cleanup; **vault /
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
`done` alone). **`run`** auto-appends the lane after Scholar / EZProxy / htmlpdf
when `[llm].enabled`, `[browser_agent].during_run`, and the extra are on;
**`paperful recover --item`** runs the same runner in isolation. Docker image
**excludes** browser-use (host-only: vault login + Chrome).

#### Documentation map (keep in sync)

| Doc | Role |
| --- | --- |
| [llm.md](llm.md) | Install extras, `[llm]` / `[browser_agent]` keys, `recover` behaviour, troubleshooting table |
| [browser-agent-models.md](browser-agent-models.md) | **Local Ollama tag guidance** for PDF UI loops (VRAM bands, avoid list, acceptance test) |
| [config.md](config.md#llm-optional-local-first) | Key table: `during_run`, `max_steps`, `max_wall_s`, `model` override |
| [architecture.md](architecture.md) | Serial source ordering, Playwright handoff before agent, CAPTCHA → skip lane for run |
| [sessions.md](sessions.md) | Vault profile shared with recover; no concurrent vault users |
| [commands.md](commands.md) | `--browser-agent` / `--no-browser-agent` on `run` / `all` |
| [docker.md](docker.md) | Explicit non-shipment of browser-use in container |
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
during_run = true                # false → recover --item only unless --browser-agent
max_steps = 20                   # stop early when PDF lands
max_wall_s = 300
```

| Knob | Policy |
| --- | --- |
| **`[browser_agent].model`** | Always treat as **separate** from `[llm].model`. Browsing wants **tool-capable 14B+**; other verbs stay on 7B–12B. |
| **`doctor`** | Name-pattern amber under **~10B**; message points at **14b+ class** tag. |
| **`use_vision`** | Hard-coded **False** until config + VL tag path is designed (avoid Ollama 400 on text models). |
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
| **`[browser_agent].fallback_model`** | Roadmapped one retry (larger local or LiteLLM) before final `not_found` — **not shipped**. |
| **`use_vision` + VL tag** | Opt-in `[browser_agent].use_vision` + model hint for **`qwen2.5vl:*`** when DOM index fails. |
| **`num_ctx` / temperature** | Pass through to `ChatOllama` or document Modelfile recipe; agent DOM dumps need **16k–32k+**. |
| **Schema hardening** | Nested JSON examples in `extend_system_message`; log parse failures to run report. |
| **Batch recover** | `recover --from-last-run` — still later. |
| **Playbooks from wins** | `state/fetch-wins.jsonl` + `playbooks promote` today; **step-trace** mining still later. |
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

**Non-goals for the MVP:** chat-over-library, blank-slate auto-tagging of the
whole library, rewriting abstracts, silent cloud defaults, applying patches
without `--apply`. Staged tagging (below) is **later**, not part of the title /
PDF-identity MVP.

**Later LLM verbs:** venue/date cleanup from the first page. Title proposals,
the PDF identity check, and grounded briefs (`summarize` / `synthesize`) are
shipped. Still proposals on disk; never a silent library write. **Note cleanup**
(selective delete by model / type, dedupe remarks, etc.) and shared
`paperful.note.v1` + first-line prefixes — [Core note hygiene](#core-keep-sharpening).

### Zotero-RAG integration (later; question-centric layer)

**Status:** roadmap only — deepen the optional **zotero-rag** bridge (corpus
index + grounded answers) without making chat the default product surface.
CLI first (batch Q&A); **built-in chat with collection** in the 2.0 GUI
**Ask** mode follows once cited answers are stable — see [GUI](#gui). Reuse the
house LLM pattern: global `[llm]` + per-verb overrides (same spirit as
`[summarize].model`, `[browser_agent].model`, smart inbox per-function gates).

**Direction:**

1. **Batch Q&A with citations** — ingest a file or stdin of questions (one per
   line or structured batch); run each against the indexed collection; write
   answers with **citations** to items/chunks on disk (`state/` report JSON +
   optional Zotero child notes). Resume-safe skips when question hash + index
   version unchanged. Not a silent library write without `--apply` where notes
   are involved.
2. **Question generation from summaries** — optional LLM pass over existing
   `summarize` outputs (and/or `synthesize` sections) to propose **unanswered**
   or **open** research questions for the corpus; land in a reviewable queue
   before batch RAG (same patch / dry-run honesty as other LLM verbs).
3. **Prompt variants and `--focus`** — keep today’s summary-oriented default;
   add alternate bundled prompts (e.g. **questions-only** brief, gap list,
   methods comparison) and a `--focus` (or profile field) that selects prompt
   template + retrieval knobs without hand-editing files every time. Custom
   `--prompt FILE` stays the escape hatch.
4. **Extract questions posed by papers** — two lanes, composable:
   **deterministic** (section headings, “we ask whether”, numbered RQs in
   abstract/introduction via rules + optional first-page text) and **LLM**
   (grounded in local PDF excerpt / summary note; reject ungrounded). Store
   extracted RQs on disk keyed by `item_key` with provenance (`rule` vs
   `llm`).
5. **Corpus-wide RAG on those questions** — take questions from extraction,
   from summary generation, or from an operator file; query the **whole**
   collection (or `-C` / year / type scope) to see whether other papers
   **already answered** or **later addressed** the same question. Filters
   (e.g. `--year-from` / `--year-to`, “only items after the asking paper”) are
   first-class so temporal stories (“did 2020 papers already answer this 2015
   RQ?”) are explicit in the report, not implicit in model memory.
6. **Config** — global defaults under `[zotero_rag]` (or shared with the
   zotero-rag project’s config file when co-installed); **per-task** overrides
   on the CLI and in `profiles/*.toml` (batch path, focus, scope, generation
   gates, citation format). `doctor` should amber when the index is stale vs
   `snapshot` / PDF set.

**Non-goals for this lane:** replacing Zotero’s reader; cloud-default RAG;
answers without citations; auto-mutating parent metadata from Q&A output;
scheduling nightly “ask everything” jobs without an explicit operator command.

**Consumer fit:** extends **Reading & knowledge** (below) and complements
`summarize` / `synthesize` — summaries stay the human-readable layer; RAG stays
the evidence-linked Q&A layer.

### Bibliography gap scan (later; not `gaps`)

**Status:** roadmap — pieces exist; a collection-scoped **verb** does not.

| Today | Roadmap gap scan |
| --- | --- |
| **`paperful gaps`** (shipped) | **Bibliography gap scan** (planned) |
| Items **already in scope** missing a stored PDF, linked-only URL, or DOI | Works **cited inside** your collection’s PDFs (or seed items) that are **not** in the library fingerprint |
| Drives `run` / handoff | Drives review pack → optional `ingest-dois` / snowball seed / gated create |

**Already in the tree (reuse, do not reinvent):** snowball bibliography parsing
(`paperful/snowball/bibliography.py` — landing HTML, open-PDF reference
sections, `parse_bibliography_entries`); OpenAlex reference lists cached under
`state/cites/` for in-collection overlap remarks; Europe PMC / remote ref
recovery on hops. None of that is yet “scan every PDF in `-C` and emit
**missing-from-library** rows” as one operator-facing command.

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

### Briefing ↔ collection coverage (later; sibling of `refs gap`)

**Status:** roadmap — `refs gap` is “cited inside collection PDFs but not owned.”
This answers “named in my briefing / starred note / DOI list but not in `-C`.”

**Direction:** `paperful coverage --from-note <key|path> -C … --dry-run` (or
`--from-file` markdown / export). Same fingerprint family as `refs gap`; pack
under `state/coverage/<stamp>/` with `in_collection` / `missing` / `ambiguous`;
findings only → `ingest-dois` / snowball. Optional grey-vs-peer hint from
provenance tags. Share pack columns with `paperful.refs_gap.pack.v1` where
possible.

### Frontier digest (later; watch + external ingest)

**Status:** roadmap — snowball **watch** is shipped (baseline, `inbox.jsonl`,
dry-run, no PDFs); a **digest** is the human-readable rollup on top.

**Digest (Paperful):** after `snowball watch run` (or on demand), emit a short
report: new vs `exists` vs deferred, overlap hints, suggested `-C`, links to
queue paths — file under `state/` or stdout; still **no** built-in scheduler
(launchd / cron calls `watch run` + digest; document launchd/systemd examples
only). Complements watch inbox review.

**Thin v0 before full digest:** `paperful snowball briefing --run-id …` /
`snowball watch briefing <name>` → markdown export of the dry-run or watch queue
(no silent creates; optional child note `paperful:frontier-briefing`). Surface
grey-vs-peer / OA stamp hints in briefing and coverage tables where provenance
exists (`grey:…`, `oa:…`, seed tags).

**Newsletter / alert ingest (rollup bridge):** optional plug-in or HTTP client
to sibling **[rollup](Documents/rollup)**-style ingest architecture — pull
candidate papers from the operator’s **newsletters and alerts**, first source
**Google Scholar** email/alert feeds (opt-in; same honesty bar as Scholar in
handoff, not a silent `run` source). Normalise to DOI/title rows → Paperful
snowball queue or bibliography-gap / ingest path. Rollup owns fetch/parse of
mail sources; Paperful owns library fingerprint, gates, and ledger. Spike
shared message shapes before hard-wiring repos.

(author-watch-lists-later-people-you-follow--their-papers)=
### Author watch lists (later; people you follow → their papers)

**Status:** roadmap — distinct from collection-scoped [`snowball watch`](snowball.md#watch)
(keyword / DOI / ORCID **seed** profiles and hop expansion). Here the seed is a
**named author list** the operator curates: people they already care about on
social or academic networks, turned into a **local** watch for **new research
outputs**, not career posts.

**Direction:**

- **Lists on disk** — `paperful authorwatch list save|add|remove|show` (names
  TBD) maintains people under `state/authorwatch/<name>/` (display name, ORCID
  when known, optional affiliation host / disambiguation notes). Resolve missing
  ORCID via OpenAlex / Crossref author search; **held** on ambiguity (same bar as
  snowball ORCID fill).
- **Watch run** — `paperful authorwatch run` polls bibliographic APIs (OpenAlex
  first; snapshot store when configured) for works **newer than baseline** per
  list member; baseline + `seen` ledger mirrors `snowball watch`. Proposals land
  in `inbox.jsonl` and/or a normal snowball-style queue — dry-run default, library
  fingerprint (`exists`), optional gate to `-C` + provenance tags. PDFs only via
  the usual `run` / handoff loop after explicit create. Paperful does not
  schedule; launchd / cron like `watch run` + optional [frontier digest](#frontier-digest-later-watch--external-ingest).
- **Import from existing follow lists (opt-in, explore)** — seed or refresh the
  list from sources the operator already maintains: ResearchGate “following”,
  LinkedIn researcher lists, Academia.edu follows, institutional directory
  pages, CSV/JSON export when available. Prefer read-only APIs; where only HTML
  exists, headed handoff or session vault with explicit config, rate limits, and
  ToS / AUP disclaimer — **not** a silent default scrape bot. Normalise rows to
  name + ORCID (or held) before watch starts; dedupe against the list and the
  library fingerprint.

**Pitch (ship when the lane is real):** Get what really matters from the people
you already follow — **their research**. Social follow graphs surface jobs,
posts, and noise; authorwatch turns that graph into a frontier of **new papers**
from those names, in one place — **your machine** (`state/`, optional `-C`, same
mirror and honesty contract as snowball).

**Non-goals:** replacing RSS or social timelines; auto-friending or messaging on
RG; cloud “who to follow” recommendations; treating LinkedIn/Academia HTML scrape
as a core `run` source without opt-in.

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

### Run witness (later; trust thicken)

**Status:** roadmap — extend existing run artifacts, not a new product surface.

**Shipped slices:** `state/runs/<stamp>-*.json`, `state/last-run.json`, pack
open/close under `state/packs/`, frozen `paperful.run_report.v1` (0.1 → 1.0
checklist). **Direction:** every material batch (`run`, `summarize`, `synthesize`,
snowball execute, `ingest-dois`, `refs gap`, `inbox drain`, future RAG) appends a
**witness** block: config file
hash (or normalised effective config), active `profiles/*.toml` name, scope
(`-C`, year/type), source list and presets, `[llm]` model ids per verb, PDF /
index versions when relevant, Paperful version. Packs reference witness ids so
“what produced this literature review?” is answerable without git. Additive keys
only on `run_report` until 1.0 tag; document in [architecture](architecture.md).

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
4. **Config. Shipped:** `dedupe_scope`, type and venue filters, profile save
   (`snowball profile save --dedupe-scope` persists it; `[snowball]` and
   `profiles/*.toml` override at run time — not a separate CLI flag on
   `search` / `doi` / `run` yet).
5. **Last pass. Shipped:** `hybrid`, `approve-each`, overlap ranking,
   Crossref / Semantic Scholar fill, and `[llm]` suggestions on the queue.
6. **Watch. Shipped:** `snowball watch save` / `run` / `show` re-runs a saved
   profile, baselines the frontier on the first run, and proposes only unseen
   arrivals into `state/snowball/watches/<name>/inbox.jsonl` plus a normal
   run queue. Always dry-run / no PDFs. Paperful does not schedule it; your
   own launchd or cron may call `watch run`. See [snowball.md](snowball.md#watch).
7. **Co-author site preflight (later).** Before or alongside hop expansion,
   derive a co-author graph from the seed + candidate author lists, discover
   personal / institutional / static-site home pages for high-centrality names,
   and write them into [field author packs](#maybe-later-not-core) for the
   profile scope so the following `run` / `fetch_pdfs` pass tries those grey
   lanes first. Rationale: GitHub Pages, Weebly, and university pages are
   usually easier to fetch than major publisher paywalls. Opt-in profile knob;
   not a substitute for OpenAlex caps or gates.

### Dedupe during snowball — ongoing prevention, not merge-after

Snowball never runs `paperful dedupe` inside the crawl. **Ongoing** here means
duplicate work is collapsed and library hits are applied **while the queue is
built and before any parent is created**, not a one-shot merge at the end.
Stragglers still use the same hygiene loop as any other ingest:
`dedupe --dry-run` → read `state/dedupe-packs/` → `dedupe --apply` on the
target collection. There is no `--dedupe-after` flag and no snowball step inside
`paperful all` today.

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
  `_dedupe` into the on-disk queue; it does not repeat the library fingerprint
  on the merged file unless you run `apply` or a fresh execute path that
  re-executes `_mark_exists`. **`resume` on a finished queue** (no
  `deferred.json`) re-marks `exists` on the full library before create/PDF
  continue.
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
`profiles/*.toml`. CLI `--dedupe-scope` exists on profile save, not yet on every
`search` / `doi` / `run` invocation (parked below).

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
  fresh `_mark_exists` (resume-after-budget merge is the weak spot: new rows are
  not re-fingerprinted on disk until apply or a full re-run).
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

- **Re-fingerprint on queue merge** — after OpenAlex `resume` adds rows, run
  `_mark_exists` on the merged `candidates.jsonl` before optional `auto` create on
  `added` (today `added` can create without a fresh library pass).
- **`--dedupe-scope` on every subcommand** — override profile per invocation.
- **Align `snowball apply` with saved `dedupe_scope`** — or document “apply always
  library” as intentional (safer for delayed gates).
- **In-run create index** — while `create_new` runs, feed new keys/DOIs back into
  the fingerprint so a single `auto` batch cannot create the same DOI twice if
  the queue had duplicates reintroduced by hand.
- **Optional post-create sweep** — profile knob: `dedupe` classify (and optionally
  `--apply`) on target `-C` after `auto` / `apply`.
- **Seed-file / stdin for long DOI or ORCID lists** — `snowball doi` and
  `snowball orcid` already take several positionals (and profile `--doi` /
  `--orcid` repeats). Optional `--seeds-file` / stdin so operators are not
  shell-pasting long lists.
- **Manifestation-aware identity** — work ↔ preprint ↔ VoR graph (**Identity /
  resolver graph**, Maybe later §3); snowball keeps skip-only semantics.
- **Co-author graph + author-site discovery preflight** — phase 7 above;
  feeds author-site registry before PDF fill on new snowball items.
- **Keyword wildcards / stem expansion** — OpenAlex `search=` strips `*`, `?`,
  and `~` (no true wildcard). Operators who want `polic*` (policy, policies,
  political, …) need Paperful to expand the stem client-side into an OR group
  before composing the boolean query (same path as multi-keyword AND/`--or`).
  Scope: `search` / `hybrid` seeds (and later `--cites-query` if useful). Cap
  expansion length so the `search=` URL stays under OpenAlex’s ~4 KB limit;
  document that a bare `polic*` today is not a wildcard.

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
- **Next (2B):** `works_citing` plus text search (`cites-query`) from the
  snapshot (likely an inverted cites index or careful scan strategy).
- **Later (2C):** keyword / ORCID / `search` parity; `local_duckdb` and `http`
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
   plus FAO/OECD/IEA/WHO — extend via `[[grey_playbooks]]`). Still
   parked: **inbox match ladder** (defer quarantine; OCR-for-match on sparse
   scans; deterministic title/fingerprint attach; optional grounded LLM when
   thin — reuse `llm_pdf_match` posture); **inbox create-on-unmatched** (config;
   metadata resolve + optional wait for manager PDF metadata after attach);
   **smart inbox** routing (Core above — snowball/recent-run context + ladder
   signals; LLM `off` | `when_thin` | `always`; model global + per-function;
   gated or auto);
   SI/dataset/code siblings;
   **opt-in LibGen** for `book` / `bookSection` gap-fill (title or ISBN routing;
   unofficial scrapers only — spike
   [libgen-api](https://pypi.org/project/libgen-api/) /
   [libgenesis-api](https://pypi.org/project/libgenesis-api/) first; same
   opt-in + disclaimer bar as Sci-Hub; no third-party HTTP gateways);
   **opt-in SearXNG** for author / personal-site / institutional-repo PDFs that
   Unpaywall / OpenAIRE / CORE never indexed — thin client against a local
   instance (`SEARXNG_BASE_URL`), not a public meta-search. Reuse the fetch +
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
   ([authors/orgs frequency report](#near-term-research-ops) row 12) plus manual
   curation — not an auto cloud graph. Same honesty: grey only, no OA mislabel.
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
   **Snowball preflight (co-author graph → author sites).** Optional early phase
   when `snowball` runs (dry-run or before `fetch_pdfs`): build a **co-author
   graph** from seeds, queue rows, and OpenAlex author ids; rank nodes by
   frequency in the frontier. For top authors, run bounded discovery (name +
   affiliation + `filetype:pdf` / “personal page” heuristics) to find faculty,
   GitHub Pages, Weebly, and similar **simple** hosts — then seed the
   author-site registry and field pack for that profile’s `-C`. **Why before
   bulk `run`:** those endpoints are more often static HTML or direct PDF links
   and less often publisher Cloudflare / bot walls, so they pay off as **priority
   grey sources** when the same names appear on items snowball is about to
   create. Cap queries; no auto-promote without operator or a fetch win; same
   `grey:author_site` stamps. Complements post-hoc co-author site crawl on misses.
   **ResearchGate “request from author” (explore; config-gated).** When the
   publication page has no PDF but shows **Request full-text PDF** (logged-in RG
   account), optional automation: session vault or headed handoff opens the page;
   if `[researchgate].request_from_author` (name TBD) is enabled, click the request
   button and record `deferred:author_request` on the item — no silent download,
   same honesty as handoff. Default off; requires explicit opt-in, RG ToS / rate
   limits, and operator awareness that fulfillment is async (email from authors).
   **Twenty CRM integration (later; opt-in).** When `[twenty]` (or env) points at
   the operator’s [Twenty](https://twenty.com) workspace, resolve item `creator`
   names against **People** (and linked **Companies** for affiliation disambiguation):
   pull **website** into the author-site registry when the CRM row has one; cache
   **work email** on disk (`state/author-contacts/` or keyed fields on registry
   rows) for later **mail merge** or polite PDF-request drafts — never send mail
   from Paperful without an explicit verb and template (`paperful request draft`
   TBD). Twenty is a first-class CRM the operator already curates, so it can beat
   web search for contact data on people you have met or filed. **RG vs email:**
   both channels can annoy the same author if mis-timed; treat as a **policy**
   knob, not one hardcoded path — e.g. `request_channels = rg | email | both |
   rg_then_email_after_days` with per-author “already requested” ledger on the
   item (`deferred:author_request` records channel + date). Email may cut through
   inbox noise when RG requests are ignored; RG may be faster when the author is
   active there — operator chooses. No CRM write-back unless `--apply` on an
   explicit sync verb; read-only search by default. Fits MCP/agent surface when
   Twenty tools are available on the workstation.
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
   without running that merge).    **Next (research-ops):** `paperful ingest-dois --from-file dois.txt -C BBNJ
   --dry-run` then `--apply` (resolve Crossref/OpenAlex; skip `exists` under
   dedupe scope; report created / exists / unresolved / **held** on ambiguous
   title mismatch; repeatable `--tag` / profile `[ingest].default_tags`; hand off
   to `run` for PDFs). `paperful collections add --keys-file keys.txt -C …`
   — membership-only batch (dry-run / apply; added / already-in / not-found).
   Complements `ingest-dois` (create parents) vs add (file existing keys). No
   scheduled bot inside Paperful. **Grey identity:** fingerprint
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
   digest](#frontier-digest-later-watch--external-ingest) (watch rollup + optional
   rollup newsletter bridge, Scholar alerts first); [author watch
   lists](#author-watch-lists-later-people-you-follow--their-papers) (ORCID-backed
   people lists + optional import from RG / LinkedIn / Academia follows). **[Run
   witness](#run-witness-later-trust-thicken)** ties batches to config/model/index
   for reproducibility.
6. **Writing & export** — CSL / BibLaTeX / Quarto sync; living review / gap lists;
   git-friendly CSL-JSON dumps; [briefing ↔ collection coverage](#briefing--collection-coverage-later-sibling-of-refs-gap)
   (thin slice of parked “gap lists,” collection-scoped only)
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
   for between-item or mid-run rotation vs stable profile UA. **Next:** stable `--format json`
   (or machine channel beside the human banner) on batch verbs (`run`, `refs gap`,
   `ingest-dois`, `inbox drain`, `collections add`); one documented exit-code
   table (`0` ok, `2` manager down, partial batch, …). **MCP** wraps the same
   verbs after JSON + exits are boring — not a prerequisite for research-ops.
   **Later:** optional **Twenty** workspace lookup for author website / email
   ([Acquire §2](#maybe-later-not-core) CRM row) via MCP or a thin API client —
   read-only by default; request-channel policy stays config, not agent-default.
8. **Collaboration without SaaS** — shared `state/` over syncthing/git; attach
   locks; optional headless fetch node. Aligns with the house
   [quiet mirror](quiet-mirror.md) stance: Syncthing (or similar) is transport;
   Paperful stays a local CLI, not a sync product.
9. **Compliance & provenance** — 1.0 attach stamp is listed above. On disk,
   `record.json` plus `out/_history.json` are the chain-of-custody note for
   the library and the append-only ledgers. OA `license` / `oa_status` /
   `version` stamps (Core above) feed this lane; which fields are written stays
   config-driven. **[Run witness](#run-witness-later-trust-thicken)** (Optional
   LLM section) extends run reports and packs with config/model scope. Still
   later: optional redistribution / license gate using those stamps, more
   jurisdictional presets, and PDF annotation export (annotation **mirror** is
   read-sync into `out/`, not export-only).

## Explicitly out of near-term scope

- Hosted multi-user service
- Replacing Zotero as a reading UI
- Shipping Sci-Hub or proxy abuse as defaults (opt-in + presets stay as today)
- Jeffersonian transcription / qualitative coding apps

## Optional thin bridge — Firefox extension (parked)

**Status:** design-only; **not** a 1.0 deliverable and **not** a replacement
for the Zotero Connector. Same Control posture as the CLI (dry-run default,
explicit Apply, fail closed if Paperful is unreachable). Feasibility +
contracts researched 2026-09-29 (local notes; substance locked below).

Three explicit toolbar actions (no single “grab everything”):

| Action | Maps to | Priority |
| --- | --- | --- |
| **Snowball this DOI** — detect DOI on the current page → `paperful snowball doi` | CLI already writes `paperful.snowball.candidate.v1`; dry-run → optional Apply + `-C` | **P0** |
| **Ingest to quiet mirror** — current page → `out/` (`paperful.item.v1`) → Zotero upsert via LibraryBackend | Needs a Paperful-owned create-parent ingest verb; today’s `inbox` attaches only | **P1** |
| **PDFs from open tabs** — enumerate tabs, confirm checklist, download with tab cookies into `[inbox].dir`, then `inbox drain` | Campus entitlement strength; refuse pirate hosts; park unattended mass download | **P1** spike |

**v0 transport (room lock):** Extension → **`nativeMessaging`** host → shells
`paperful` CLI (dry-run JSON → confirm → write). No new daemon and no invented
localhost Capability API for these three actions. Thin `paperful serve` /
Capability API later only if doctor/status needs a sticky probe (GUI 2.0 still
targets HTTP — [gui.md](gui.md)). **Wrong:** extension → Zotero `:23119`
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
the depth of the CLI. Not a 1.0 blocker; raises trust before install and after
the first confusing run.

Ship in layers:

0. **Research pack playbook** (narrative spine for `-C` topic builds):
   seed greys + seed papers → `refs gap` → `ingest-dois --dry-run` → `--apply`
   with provenance tags → `run` / handoff / inbox for PDFs → `dedupe` hygiene →
   optional `snowball watch` + [briefing export](#frontier-digest-later-watch--external-ingest)
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

Keep new pages linked from README and [commands.md](commands.md); avoid a
second doc tree that drifts from the CLI.

## Related docs

- [architecture.md](architecture.md) — disk-first adapters and data flow
- [why.md](why.md) — library, find, completeness, mirror, control; what is true today
- [quiet-mirror.md](quiet-mirror.md) — `out/` as the copy you keep
- [releases.md](releases.md) — 0.x vs 1.0; known limits
- [comparison.md](comparison.md) — what Paperful does and does not replace today
- [snowball.md](snowball.md) — library-building from a keyword, multi-DOI / multi-ORCID, or collection
- Site career / domain timeline plan (consumer of durable tags):
  `/Users/89298/Documents/website/glen-w.github.io/docs/dev/career-timeline-plan.md`
- Firefox extension (parked thin bridge) — section above; not a separate doc yet

## GUI

Parked **2.0 vision** only — not a 1.0 deliverable. Web-native workbench
sketch (open / Docker / SaaS): [gui.md](gui.md). The Firefox extension above
is a thinner optional bridge; it does not wait on the full GUI Capability API.

**Built-in chat with collection (2.0, opt-in):** a scoped **Ask** mode in the
workbench — conversational Q&A over the current collection (and the same
year / type / profile filters as other modes), with **citations** back to
items and PDF chunks via the zotero-rag index. Not the default landing
experience and not a replacement for Zotero’s reader; requires
`[llm].enabled` and an up-to-date corpus index (`snapshot` / PDF set). The
Capability API exposes the same verbs as CLI batch Q&A ([Zotero-RAG
integration](#zotero-rag-integration-later-question-centric-layer)): turn
history, `--focus` / prompt presets, optional “promote this thread to batch
report on disk,” and explicit scope chrome so SaaS / shared workspaces never
imply library-wide answers without a visible filter. GUI ships **after** CLI
batch ingest and cited answers are stable.
