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
  watch` / `drain` against `[inbox].dir` (PDF DOI match; `inbox` defaults to
  whole-library scope so one drop folder serves every topic; unmatched →
  `unmatched/`). Distinct from snowball watch `inbox.jsonl`. CLI
  `--browser-agent` / `--no-browser-agent` overrides `[browser_agent].during_run`
  for one `run` / `all`.
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
  the circuit breaker never opens (429 is excluded for API `Retry-After` lanes;
  Scholar uses raw `httpx`, not `http_json`). Unlike EZProxy, there is no
  “session down — skip the rest of this pass” latch, so a burned Scholar session
  still gets **N** probe requests in one batch. **Fix before deprecation:**
  first 429 (or short streak) → skip Scholar for the remainder of the run
  (mirror `_mark_ezproxy_down`); optionally map Scholar 429/503 to block outcomes
  so the existing breaker can pause mid-batch. **Spreading load:** shuffling queue
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
  (skip or shorten the wait when the backend has no such behavior). Gated vs auto
  should match smart inbox; fail closed to `unmatched/` or a review queue when
  resolution is thin. Today’s default stays DOI attach only — no silent
  create-parent.
- **Smart inbox (optional, later).** Today `inbox` only attaches a PDF onto an
  existing missing-PDF parent by DOI (or FIFO in a handoff session). It does not
  choose a collection or create parents. Builds on **create-on-unmatched** above.
  A smarter drop-folder lane would
  **route** (and optionally ingest) each PDF toward the right collection using
  **deterministic** signals first — ongoing / recent snowball runs and watches
  (`state/snowball/…`, open packs, last `-C` / profile), DOI already in the
  library, filename / PDF metadata / first-page text fingerprints against
  collection titles and recent candidates — then an optional LLM ranker.
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
  Not a hosted service SKU; not Sci-Hub completeness metrics.
- **Quiet mirror** — [quiet-mirror.md](quiet-mirror.md). **Shipped:** `snapshot`
  writes a per-item folder (`record.json`, optional PDF, notes) plus
  `out/_index.jsonl`, `out/_collections.json`, and `out/_history.json`.
  `[mirror].pdfs` is `additional` (default), `all`, or `none`. `restore --apply`
  creates missing items and does not overwrite fields already in Zotero. Dual
  `imported_file` store; house sync (Syncthing) stays outside Paperful. Not a
  second reading UI. Not a linked-file cutover. Not a WebDAV client.
  **Housekeeping (after maintainer `out/` is clean):** flat
  `Author - Year - Title.pdf` (+ legacy `*.paperful.json`) is a pre-item-folder
  hangover. `doctor` ambers on mixed flat+folder trees and tells people to
  `snapshot`; `migrate_flat_*` / card absorb run on `snapshot` and on the next
  `run` that saves that file. Once the personal library has been migrated
  (`snapshot --library` or equivalent) and doctor is green on Mirror, **remove**
  that legacy path from code, tests, and docs (quiet-mirror / commands /
  CHANGELOG mentions) so future users are not steered into a whole-library
  snapshot for a layout they never had. Keep `snapshot` / `restore` themselves —
  only the flat→folder migration and the mixed-layout doctor amber go.
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
- CORE as an OA PDF source when `core_api_key` is set
- Library adapter seam (`LibraryBackend`). **Zotero is well tested.** Mendeley
  and EndNote are seeking testers (above).

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
agent *step* traces (beyond host/path wins); venue/date cleanup; CAPTCHA
posture below.

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
shipped. Still proposals on disk; never a silent library write.

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

**Status:** keyword, DOI, ORCID, and collection seeds, hybrid keyword-then-hop,
`direction` sides `refs` / `cites` / `both` / `keywords` / `similar` (and
combos), gates including `approve-each`, overlap ranking, and optional `[llm]`
query suggestions are in the tree. Contract: [snowball.md](snowball.md). Still
outside: `expand = cited_authors`.

Snowball grows a library outward from a keyword, one or more DOIs, an ORCID,
or DOIs already in a collection. It writes a candidate queue on disk, then
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
   parked: **inbox create-on-unmatched** (config; metadata resolve + optional
   wait for manager PDF metadata); **smart inbox** routing (Core above —
   snowball/recent-run context + PDF signals; LLM `off` | `when_thin` | `always`;
   model global + per-function; gated or auto);
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
3. **Identity / resolver graph** — work ↔ version ↔ preprint; scored patches with
   undo; citation ingest; manifestation-aware dedupe. Collection DOI / title+year
   trash is already `paperful dedupe`. Snowball only **skips** rows that match
   those fingerprints before create ([Snowball — dedupe during snowball](#dedupe-during-snowball--ongoing-prevention-not-merge-after));
   it does not trash or merge existing parents. Preprint ↔ version of record is
   `paperful versions`: the older parent keeps the published citation and PDF,
   and the preprint stays as a version (snowball may tag a candidate `version`
   without running that merge). Still later:
   `paperful ingest-dois --from-file dois.txt -C BBNJ --dry-run` then `--apply`
   (create items by DOI, tag `crossref-backfill`, hand off to `run` for PDFs).
   That backfill stays out of any scheduled bot inside Paperful.
   Growing a library from a keyword, a DOI bibliography, or an ORCID is the
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
   evidence packs; briefs grounded only in local PDFs. **Zotero-RAG (planned):**
   batch question → cited answer runs, corpus question generation, paper-level
   RQ extraction, and temporal RAG across the collection — see [Zotero-RAG
   integration](#zotero-rag-integration-later-question-centric-layer) under
   Optional LLM assist.
6. **Writing & export** — CSL / BibLaTeX / Quarto sync; living review / gap lists;
   git-friendly CSL-JSON dumps
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
   report (which hosts / win kinds paid off).
8. **Collaboration without SaaS** — shared `state/` over syncthing/git; attach
   locks; optional headless fetch node. Aligns with the house
   [quiet mirror](quiet-mirror.md) stance: Syncthing (or similar) is transport;
   Paperful stays a local CLI, not a sync product.
9. **Compliance & provenance** — 1.0 attach stamp is listed above. On disk,
   `record.json` plus `out/_history.json` are the chain-of-custody note for
   the library and the append-only ledgers. OA `license` / `oa_status` /
   `version` stamps (Core above) feed this lane; which fields are written stays
   config-driven. Still later: optional redistribution / license gate using those
   stamps, more jurisdictional presets, and PDF annotation export.

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
   - **PDFs for an existing collection** — two passes documented side by side:
     **quick** (default sources, `--dry-run` Would-hit, CORE / grey playbooks,
     EZProxy session hygiene, `run` banner);      **full** (`session login` / relogin for **EZProxy** (not Scholar-as-bot),
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
- [snowball.md](snowball.md) — library-building from a keyword, DOI, ORCID, or collection
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
