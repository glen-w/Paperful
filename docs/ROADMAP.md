# Roadmap

Guidance for contributors, not a commitment calendar. Paperful’s jobs are
**library**, **find**, **completeness**, **mirror**, and **control**: one
disk mirror (`out/`, `state/`), adapters for citation managers, and fetch /
lint / attach / summarise as the core loop. **Zotero is the well-tested
adapter.** Mendeley and EndNote are in the tree and seeking testers. See
[architecture.md](architecture.md) and [why.md](why.md).

Surfaces like a Zotero plugin, Firefox extension, or web GUI are **not** the
product direction. Optional thin bridges (`paperful session login`) capture a local browser
profile; they do not rewrite the fetcher.

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
| Attachment **provenance stamp** (`oa:unpaywall` / `campus:ezproxy` / `grey:undocs` on notes or title prefix) | Trust inside Zotero | Shipped on the Zotero attachment note |
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
   object storage. Document `notes` (`view=all`) is read; paperful writes
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

- Resumable missing-PDF fetch, source routing, circuit breaker, EZProxy / Scholar
  session hygiene, attach reliability, `doctor` / `report`
- **Quiet mirror** — [quiet-mirror.md](quiet-mirror.md). **Shipped:** `snapshot`
  writes a per-item folder (`record.json`, optional PDF, notes) plus
  `out/_index.jsonl`, `out/_collections.json`, and `out/_history.json`.
  `[mirror].pdfs` is `additional` (default), `all`, or `none`. `restore --apply`
  creates missing items and does not overwrite fields already in Zotero. Dual
  `imported_file` store; house sync (Syncthing) stays outside paperful. Not a
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
Still later: Browser Use Cloud / BU2, batch `recover --from-last-run`, playbook
mining from agent traces, venue/date cleanup.

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
gates including `approve-each`, overlap ranking, and optional `[llm]` query
suggestions are in the tree. Contract: [snowball.md](snowball.md). Still
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
3. **Optional expansion. Shipped:** cited-by (`direction`), depth above 1
   under the same caps.
4. **Config. Shipped:** dedupe scope, type and venue filters, profile save.
5. **Last pass. Shipped:** `hybrid`, `approve-each`, overlap ranking,
   Crossref / Semantic Scholar fill, and `[llm]` suggestions on the queue.

Still outside this lane: every paper by every cited author; a snowball step
inside `paperful all`; cron; a review UI; systematic-review screening; a
citation-graph canvas; Sci-Hub or Google Scholar as snowball sources.

## Maybe later, not core

Workbench layers beyond the mirror contract. Worth keeping on the map; not
prerequisites for the fetch / lint / attach loop.

1. **Catalogue unification** — conflict journal; query-scoped virtual collections
   as run scopes. Mendeley and EndNote adapters exist and are seeking testers
   (above). Treating every manager as an equal is still later.
2. **Acquire beyond journal PDFs** — **shipped:** local session vault
   (`paperful session login`); **pluggable grey-lit PDF playbooks** in
   `direct`/`landing` with builtin packs (UNGA/undocs · BBNJ/DOALOS · ISA;
   plus FAO/OECD/IEA/WHO — extend via `[[grey_playbooks]]`). Still
   parked: SI/dataset/code siblings; watch/alert → propose items;
   **opt-in LibGen** for `book` / `bookSection` gap-fill (title or ISBN routing;
   unofficial scrapers only — spike
   [libgen-api](https://pypi.org/project/libgen-api/) /
   [libgenesis-api](https://pypi.org/project/libgenesis-api/) first; same
   opt-in + disclaimer bar as Sci-Hub; no third-party HTTP gateways).
3. **Identity / resolver graph** — work ↔ version ↔ preprint; scored patches with
   undo; citation ingest; manifestation-aware dedupe. Collection DOI / title+year
   trash is already `paperful dedupe`. Still later:
   `paperful ingest-dois --from-file dois.txt -C BBNJ --dry-run` then `--apply`
   (create items by DOI, tag `crossref-backfill`, hand off to `run` for PDFs).
   That backfill stays out of any scheduled bot inside Paperful.
   Growing a library from a keyword, a DOI bibliography, or an ORCID is the
   [Snowball](snowball.md) section above, not a line item inside this graph.
4. **File & attachment OS** — linked vs stored policy, rename, orphan GC,
   broken-link repair, PDF quality / wrong-paper triage (eat StorScan-class tools).
   The quiet mirror itself is core (above), not a later bet: dual bytes with
   Zotero `imported_file`; house transport stays outside paperful. Still not a
   second reading UI, and still not a linked-file cutover. PDF annotations and
   a full CSL dump are still later. A text layer for scans is `paperful ocr`.

## Maybe later

Larger product bets. Park until the ledger and core loop justify them.

5. **Reading & knowledge** — local full-text index; annotation sync;
   evidence packs; briefs grounded only in local PDFs
6. **Writing & export** — CSL / BibLaTeX / Quarto sync; living review / gap lists;
   git-friendly CSL-JSON dumps
7. **Agent surface** — MCP + CLI sharing one capability API; dry-run defaults;
   typed source/policy permissions; playbooks. **Shipped (CLI convenience,
   not a GUI):** named run configs and `paperful all` repeat a collection /
   year / type sequence (`profiles/*.toml`). Those are not grey-lit playbooks.
   **Shipped (opt-in):**
   [browser-use](https://github.com/browser-use/browser-use) as a *recovery*
   lane: last serial source on `run` after Scholar / EZProxy / htmlpdf fail
   (`[llm].enabled` + extra), and `paperful recover --item` for named keys.
   Never in `DEFAULT_SOURCES`, not “AI fetch everything.” Soft bot walls may improve with
   their Cloud stealth (not wired); hard CAPTCHAs stay human. Next: mine
   successful agent paths into grey playbooks so the deterministic fetcher
   stays primary.
8. **Collaboration without SaaS** — shared `state/` over syncthing/git; attach
   locks; optional headless fetch node. Aligns with the house
   [quiet mirror](quiet-mirror.md) stance: Syncthing (or similar) is transport;
   paperful stays a local CLI, not a sync product.
9. **Compliance & provenance** — 1.0 attach stamp is listed above. On disk,
   `record.json` plus `out/_history.json` are the chain-of-custody note for
   the library and the append-only ledgers. Still later: more jurisdictional
   presets, and PDF annotation export.

## Explicitly out of near-term scope

- Hosted multi-user service
- Replacing Zotero as a reading UI
- Shipping Sci-Hub or proxy abuse as defaults (opt-in + presets stay as today)
- Jeffersonian transcription / qualitative coding apps

## Related docs

- [architecture.md](architecture.md) — disk-first adapters and data flow
- [why.md](why.md) — library, find, completeness, mirror, control; what is true today
- [quiet-mirror.md](quiet-mirror.md) — `out/` as the copy you keep
- [releases.md](releases.md) — 0.x vs 1.0; known limits
- [comparison.md](comparison.md) — what paperful does and does not replace today
- [snowball.md](snowball.md) — library-building from a keyword, DOI, ORCID, or collection
- Site career / domain timeline plan (consumer of durable tags):
  `/Users/89298/Documents/website/glen-w.github.io/docs/dev/career-timeline-plan.md`
