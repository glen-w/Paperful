# Roadmap

Guidance for contributors, not a commitment calendar. Paperful stays a
**local CLI**: fetch missing PDFs, lint identifiers, propose metadata patches on
disk, write back through a library adapter. See [architecture.md](architecture.md).

Surfaces like a Zotero plugin, Firefox extension, or web GUI are **not** the
product direction. Optional thin bridges (`paperful session login`) capture a local browser
profile; they do not rewrite the fetcher.

Ambition beyond core is framed as a **local research library workbench** —
one catalogue, one disk ledger, one write-back bus — grown as optional modules
that speak the same adapter + `state/` protocol. Do not expand that surface
until the fetch / lint / attach loop is boringly reliable. **1.0 is that loop
plus the trust checklist below** — not a GUI or a second product.

(trust-10)=
## 0.1 → 1.0 (trust)

`0.1` is a first usable gap-filler. Do not call it **1.0** until these land.
Do **not** grow this list into a second product (no GUI, no auto Sci-Hub, no
“AI fetch everything”).

| Step | UX outcome | Status |
| --- | --- | --- |
| End-of-run **one-line** banner: `downloaded N · attached M · deferred K · not_found J` plus write-API yes/no | Trust after a run | Summary **table** ships; banner not locked |
| Attachment **provenance stamp** (`oa:unpaywall` / `campus:ezproxy` / `grey:undocs` on notes or title prefix) | Trust inside Zotero | Not shipped |
| `--dry-run` **Would-hit** column (sources in order) | Trust before network | Shipped |
| Exit **2** + next-steps when Zotero is down (`collections` / `run` / `attach`) | Fresh clone never dead-ends | Shipped |
| Slim README + [CHANGELOG](../CHANGELOG.md) known limits | Trust before install | Shipped |
| Lock `paperful.run_report.v1` | Trust for agents | Named schema; not frozen |

Nice-to-have (not 1.0 blockers): colour glossary next to `doctor` (documented);
collection picker hint on fuzzy `--collection` miss.

## Core (keep sharpening)

- Resumable missing-PDF fetch, source routing, circuit breaker, EZProxy / Scholar
  session hygiene, attach reliability, `doctor` / `report`
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
- Library adapter seam (`LibraryBackend`); Mendeley when someone needs it

## Optional LLM assist (local / LiteLLM)

**Status:** MVP shipped behind `[llm].enabled = false` — Ollama loopback default,
LiteLLM via `paperful[llm]`. Verbs: `recover` (browser agent, `paperful[browser-agent]`,
Py 3.11+), `fix-metadata` title proposals (`[fix_metadata].llm_title`), `lint`
`pdf_identity_mismatch` (`[lint].llm_pdf_match`), `summarize` → tagged child note.
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

**Non-goals for the MVP:** chat-over-library, auto-tagging everything, rewriting
abstracts, silent cloud defaults, applying patches without `--apply`.

**Later LLM verbs (only after title MVP):** venue/date cleanup from first page;
“is this PDF the right work?” mismatch check; grounded briefs — still proposals
on disk.

## Maybe later, not core

Workbench layers that would broaden paperful beyond fetch/lint. Worth keeping
on the map; not prerequisites for 1.x usefulness.

1. **Catalogue unification** — multi-manager adapters as equals; conflict journal;
   query-scoped virtual collections as run scopes
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
4. **File & attachment OS** — linked vs stored policy, rename, orphan GC,
   broken-link repair, PDF quality / wrong-paper triage (eat StorScan-class tools).
   **Near-term direction (not a product expand):** treat `out/` as a
   [quiet collection mirror](quiet-mirror.md) (dual bytes with Zotero
   `imported_file`); house transport (e.g. Syncthing) stays outside paperful.

## Maybe later

Larger product bets. Park until the ledger and core loop justify them.

5. **Reading & knowledge** — local full-text index / OCR; annotation sync;
   evidence packs; briefs grounded only in local PDFs
6. **Writing & export** — CSL / BibLaTeX / Quarto sync; living review / gap lists;
   git-friendly CSL-JSON dumps
7. **Agent surface** — MCP + CLI sharing one capability API; dry-run defaults;
   typed source/policy permissions; playbooks. **Shipped (opt-in):**
   [browser-use](https://github.com/browser-use/browser-use) as a *recovery*
   lane only (`paperful recover --item`), reusing the session vault — never a
   default source, not “AI fetch everything.” Soft bot walls may improve with
   their Cloud stealth (not wired); hard CAPTCHAs stay human. Next: mine
   successful agent paths into grey playbooks so the deterministic fetcher
   stays primary.
8. **Collaboration without SaaS** — shared `state/` over syncthing/git; attach
   locks; optional headless fetch node. Aligns with the house
   [quiet mirror](quiet-mirror.md) stance: Syncthing (or similar) is transport;
   paperful stays a local CLI, not a sync product.
9. **Compliance & provenance** — 1.0 attach stamp is listed above; later:
   per-PDF chain of custody, more jurisdictional presets, reproducible run records

## Explicitly out of near-term scope

- Hosted multi-user service
- Replacing Zotero as a reading UI
- Shipping Sci-Hub or proxy abuse as defaults (opt-in + presets stay as today)
- Jeffersonian transcription / qualitative coding apps

## Related docs

- [architecture.md](architecture.md) — disk-first adapters and data flow
- [quiet-mirror.md](quiet-mirror.md) — `out/` as quiet browsable mirror (direction)
- [releases.md](releases.md) — 0.x vs 1.0; known limits
- [comparison.md](comparison.md) — what paperful does and does not replace today
