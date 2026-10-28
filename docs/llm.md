# Optional LLM: setup and verbs

Everything here is **off by default**. Paperful’s PDF loop (`run` / `attach` /
`lint` / `fix-metadata` / `dedupe`) never needs a model. Turn the LLM on only
for the LLM-backed verbs below, and only after `paperful doctor` shows the
`LLM` row green. `extract-sections` (optional GROBID then optional LLM),
`rag questions`, `critique`, and style-only `rewrite` run
deterministic rules without a model; their `--llm` lanes (and
critique `--lane` / `--advanced`, rewrite areas other than style) need `[llm].enabled`.

**Feasibility first.** Trying one summary is not the same job as summarizing
or synthesizing ~1.5k PDFs. Hardware bands, overnight local runs, OpenRouter /
LiteLLM setup, free-tier caveats, and order-of-magnitude hosted cost:
[AI for notes and Ask](ai.md).

**Two ways to run a model:** use **Ollama** on your computer when your RAM/VRAM
can support the tags you need (default `provider = "ollama"`). Or install
`paperful[llm]` and set **`provider = "litellm"`** to call a hosted API
(OpenAI, Anthropic, or another LiteLLM provider) without running weights
locally. RAG embeddings follow the same split (`[rag].embed_provider`).

Design rules (see [architecture § LLM layer](architecture.md#llm-layer-optional-local-first)):

- **Local first.** Default provider is [Ollama](https://ollama.com) on
  `127.0.0.1:11434`. Nothing leaves the machine unless you opt into a remote
  endpoint, and then every command prints a yellow egress notice.
- **Disk first, apply second.** Each verb writes under `state/` before any
  Zotero write; Zotero writes go through the same library adapter as `attach`.
- **Grounded.** Prompts only see item metadata plus text extracted from a PDF
  already on disk (`out/` or `state/pdf-cache/`). Nothing is fetched from the
  web for a model call.
- **No silent defaults.** API keys live in the environment, never in
  `config.toml`; `browser_agent` is never in the default source list. `run`
  appends it only when `[llm].enabled` and the extra is installed.

## 1. Install

### Ollama (default, local)

```sh
# macOS
brew install ollama && ollama serve          # or the Ollama.app menu-bar daemon
# Linux
curl -fsSL https://ollama.com/install.sh | sh

ollama pull qwen2.5:7b        # title / identity / summaries
ollama pull qwen2.5:14b       # recommended floor for `recover` (browsing agent)
# See browser-agent-models.md for VRAM bands, ranked tags, and avoid list.
```

No Python extra is needed for Ollama: Paperful talks HTTP to the daemon.

| Verb | Works well with | Notes |
| --- | --- | --- |
| `fix-metadata` titles, `lint` identity, `summarize`, `synthesize`, `extract-sections --llm`, `rag questions --llm`, `critique --lane` / `--llm` / `--advanced`, `rewrite` (non-style), `ask` | 7B–12B instruct models (`qwen2.5:7b`, `gemma3:12b`, `llama3.1:8b`) | JSON-capable instruct tags; thinking models are fine but slower. `summarize` and `synthesize` set Ollama `num_ctx` from the prompt, capped by `[llm].max_num_ctx`. `critique` comments are suggested-lane only. `--lane marg` is many more completions per paper (aspect groups plus refine; default experiments/clarity/impact); `--lane adversary` is one validity red-team turn; `--lane claims` is claim extract plus an optional downgrade turn; `--lane verify` is one or two turns per segment plus refine; `--lane context` adds summary / historian / scout / Q&A turns. `rewrite` is one JSON call per enabled area that still has findings after glossary/Vale swaps; an optional `[[rewrite.specialists]]` model may be an [XtraGPT](https://huggingface.co/collections/Xtra-Computing/xtragpt) Ollama tag (ICLR/ReviseQA-shaped — do not assume it fits ocean/policy drafts). `ask` default is **simple** (one completion); **advanced** adds about `evidence_k` summary calls — [rag.md](rag.md#ask-modes) |
| `recover` | 14B+ (`qwen2.5:14b`, `qwen3:14b`, larger); 32B / VL on 24 GB+ | Small models loop on cookie banners and publisher menus; `doctor` warns under ~10B by tag name. Full guidance: [browser-agent-models.md](browser-agent-models.md) |

### LiteLLM (paid / OpenAI-compatible APIs)

```sh
uv sync --extra llm            # installs litellm
export OPENAI_API_KEY=...      # or ANTHROPIC_API_KEY, OPENROUTER_API_KEY, etc.
```

```toml
[llm]
enabled = true
provider = "litellm"
model = "openai/gpt-4.1-mini"          # LiteLLM model id (provider/model)
# api_base = "https://openrouter.ai/api/v1"   # e.g. OpenRouter; optional otherwise
```

Rules: `ollama/…` model ids are rejected on the LiteLLM path (use
`provider = "ollama"` instead); `api_base` must be `http(s)`. With LiteLLM,
title/abstract/PDF excerpts (and, for `recover`, page text) leave your machine.
OpenRouter walkthrough, free-tier limits, and cost sketch:
[AI for notes and Ask](ai.md#openrouter-setup).

### Browser agent (`recover` / last `run` lane)

```sh
uv sync --extra browser-agent  # browser-use + ollama client; needs Python >= 3.11
uv run paperful session login scholar   # the agent reuses this Chromium profile
# or: PAPERFUL_IMAGE_MODE=heavy docker compose build
```

Paperful core supports Python 3.10; the extra is marked
`python_version >= "3.11"` so `uv sync` on 3.10 simply skips it and `recover`
exits 1 with a hint. If your `.python-version` is 3.10, run
`uv python pin 3.12 && uv sync --extra browser-agent`. The **heavy** Compose
image already includes this extra (headed login still on the host).

## 2. Configure

```toml
[llm]
enabled = true
provider = "ollama"                 # ollama | litellm
model = "qwen2.5:7b"
base_url = "http://127.0.0.1:11434"
allow_remote = false                # true only for a non-loopback Ollama host
timeout_s = 120
# max_num_ctx = 32768              # cap for the Ollama context window on summarize / synthesize

[fix_metadata]
llm_title = false                   # verb B: grounded title proposals

[lint]
llm_pdf_match = false               # verb C: pdf_identity_mismatch finding
llm_pdf_match_min_confidence = 0.6

[critique]                          # verb C2: suggested comments only
llm = false
# lanes = []                       # reviewers, marg, adversary, claims, verify, context, context-web (see critique.md)
# advanced = false                 # shim → marg when lanes is empty
# vale = false                     # house-style pass; needs vale on PATH (not an LLM)
# glossary = true                  # fuzzy house expansions from state/glossary/
# [[critique.reviewers]]            # omit the table for one builtin JSON reviewer
# id = "reviewer-2"
# prompt = "prompts/critique-reviewer-2.md"

[rewrite]                           # verb C2.5: apply a critique pack
areas = ["style"]                   # style-only glossary/Vale swaps need no model
# outputs = ["edits", "tracked"]   # also odt, pdf
# comments = "off"
# [[rewrite.specialists]]
# id = "style"
# model = ""                        # empty → [llm].model; may be an XtraGPT tag
# prompt = "default"                # or prompts/rewrite-style.md

[summarize]                         # verb D
prompt_template = "default"         # or a path, e.g. "prompts/summary.md"
max_context_chars = 24000
tag = "paperful-summary"
# dest = "both"                    # disk | zotero | both
# order = "library"                # library | newest | oldest
# style = "plain"                  # plain | ste (ASD-STE100 constraints)
# ste_violation_policy = "warn"    # warn | fail (when style = ste)
# ste_word_list_path = ""          # optional approved-word list (one word/line)

[synthesize]                        # verb E
prompt_template = "default"
max_context_chars = 24000
tag = "paperful-report"
# dest = "both"                    # disk | zotero | both
# timeout_s = 300                  # default is max([llm].timeout_s, 300)

[browser_agent]                     # last run lane + recover --item
max_steps = 20
max_wall_s = 300
# during_run = true                 # false keeps recover as --item only
#                                     # also: --no-browser-agent on one run
# model = "qwen2.5:14b"             # override [llm].model for browsing only
# fallback_model = "qwen3:30b"      # one retry before final not_found (not on captcha)
# use_vision = false                # true needs a VL tag; see browser-agent-models.md
```

Full key table: [Configuration § LLM](config.md#llm-optional-local-first).
Ollama tag ranking and acceptance tests: [browser-agent-models.md](browser-agent-models.md).
`fallback_model`, `use_vision`, and `recover --from-last-run` are documented in [config.md](config.md#llm-optional-local-first). Remaining gap: `num_ctx` pass-through — [ROADMAP § browser-use](ROADMAP.md#browser-use-integration-models-docs-config).

## 3. Check

```sh
uv run paperful doctor
```

| Row | Green | Amber |
| --- | --- | --- |
| `LLM` | daemon reachable and model tag present (Ollama), or `paperful[llm]` importable (LiteLLM) | disabled is also green; amber = unreachable, model not pulled, extra missing, non-loopback URL without `allow_remote`, `ollama/…` id on LiteLLM |
| `browser-agent extra` | `browser-use` importable and agent model ≥ 10B by name | extra missing (`uv sync --extra browser-agent`), or model tag looks small |

`doctor` never sends a paid completion: Ollama is probed via `/api/tags`,
LiteLLM by import only. The TTY guide prints the fix for each amber row.

## 4. Verbs

### A. `recover` — browser-agent PDF recovery

Model choice (Ollama tags, VRAM bands, acceptance test):
[browser-agent-models.md](browser-agent-models.md).

On `run`, when `[llm].enabled` and `paperful[browser-agent]` are available,
Paperful appends `browser_agent` as a late serial lane. Policy order tries
Scholar once immediately before the agent (the agent wall clock spaces Scholar
requests). When opt-in [Camofox](camofox.md) is also on, order is Scholar →
`camofox` → `browser_agent` (separate phases; a Scholar or Camofox hit skips
later lanes). The agent
fires only if one of those vault lanes was tried and failed (not merely
skipped as inapplicable). Playwright releases the session profile first.
`[browser_agent].during_run = false` turns that auto-lane off for every run.
`--no-browser-agent` skips it for one `run` (or `all`); `--browser-agent`
forces it on even when `during_run` is false. Sci-Hub, when
opted in, stays after recover.

`paperful recover --item` still targets named keys without waiting for other
lanes:

```sh
uv run paperful recover --item ABCD1234 --dry-run   # shows the start URL only
uv run paperful recover --item ABCD1234             # runs the agent, attaches on success
uv run paperful recover --item K1 --item K2 --no-attach
uv run paperful recover --from-last-run              # default mode: browser_agent_miss
uv run paperful recover --from-last-run --from-last-run-mode missing -n 5
```

- Start URL is `https://doi.org/<DOI>` when the item has a DOI, else its URL.
- One item at a time, on the session vault profile. Never in `DEFAULT_SOURCES`.
- Hard CAPTCHAs are not solved. Local Chrome does not solve publisher
  Cloudflare or Turnstile; that solver is a Browser Use Cloud feature, and
  this install does not use it. When the page is a robot check, a Cloudflare
  verification, or a publisher bot wall, Paperful stops that attempt, marks
  it `captcha`, and skips `browser_agent` for the rest of the process. Later
  items stay `retryable`. A paywall stops that item only. Sci-Hub's ALTCHA
  check is separate and still completed when it can be. Timeouts / no
  download → `not_found`.
- **Mileage varies** for both `browser_agent` and opt-in [Camofox](camofox.md):
  bulk recover often sees long strings of timeouts, Cloudflare / soft bot
  walls, DOI pages with no PDF control, and empty downloads. Expect frequent
  misses; keep these lanes off when you want a fast, predictable pass over
  HTTP / vault sources only. Model and acceptance detail:
  [browser-agent-models.md](browser-agent-models.md).
- Access blocks (403 / "Request blocked" / paywall with no free PDF) are
  instructed as immediate stop — the agent must not open search engines or
  support/help pages. If it navigates to Google/Bing/etc. or a support/contact
  path anyway, Paperful force-stops that attempt.
- As soon as a valid PDF lands in the recover download folder (size stable
  across two polls), Paperful calls `agent.stop()` so the step budget does not
  keep running after the click already succeeded.
- Success lands like any other source: PDF under `out/`, manifest line with
  `source = "browser_agent"`, attach through the normal path. A dedicated
  `recover` writes `state/runs/<stamp>-recover.json`; auto-recover on `run`
  is counted in that run’s report (`command = "run"`).
- Prints an orange disclaimer: you are responsible for publisher terms; remote
  LLMs may receive page content; a local LLM does not send page content off
  your computer.

Do not run two commands concurrently against the same vault: both would open
the same Chromium profile.

### B. Grounded title proposals (`fix-metadata`)

With `[fix_metadata].llm_title = true`, items flagged `title_all_caps`,
`title_html`, or `title_filename` get a proposed clean title grounded in the
abstract and first two PDF pages. ALL CAPS titles already get a deterministic
Title Case patch without the LLM; the model can still override when enabled.
Proposals that share no content words with the grounding are dropped. They land
in `state/metadata-patches.jsonl` with `source = "llm_title"` and are written
only on `fix-metadata --apply`.

### C. PDF identity check (`lint`)

With `[lint].llm_pdf_match = true`, `lint` asks the model whether the first
two pages match the record (title, author surnames, year, DOI). A `false`, or a
`true` below `llm_pdf_match_min_confidence`, becomes the finding
`pdf_identity_mismatch` (detail carries the model’s reason and confidence).
Nothing is deleted or re-attached; you decide. Model or extraction failure is
silent (no finding).

### C2. `critique --lane` — suggested review lanes only

```sh
uv run paperful critique --file ./draft.pdf --lane reviewers
uv run paperful critique --file ./draft.pdf --llm --reviewer reviewer-2
uv run paperful critique --file ./draft.pdf --llm --reviewer reviewer-5
uv run paperful critique --file ./draft.pdf --lane marg
uv run paperful critique --file ./draft.pdf --lane adversary
uv run paperful critique --file ./draft.pdf --lane claims
uv run paperful critique --file ./draft.pdf --lane verify
uv run paperful critique --file ./draft.pdf --lane reviewers --lane marg --grobid
uv run paperful critique --file ./draft.pdf --lane context
uv run paperful critique --item ABCD1234 --llm --force
```

Additive. The default pack is checkers, metrics, and heuristic AI-tells with
no model. `--lane reviewers` (or `--llm` / `[critique].llm`) asks for a
contribution summary, up to eight comments tied to a finding code or a quoted
span, and author questions. `--lane marg` (or `--advanced`) adds a MARG-S-style
multi-agent pass. `--lane adversary` adds a structured validity red-team.
`--lane claims` builds an intra-doc claim ledger (support in this extract only).
`--lane verify` is a local section-swarm stress-test (not Deep Review; local
models will not match hosted proof recall). `--lane context` adds a
ScholarPeer-inspired local historian /
scout / Q&A pass; `--lane context-web` may query OpenAlex / SearXNG (egress
notice; skipped offline). Lanes run together. `--grobid` /
`[grobid].enabled` changes MARG-S / claims / verify PDF chunks. Every row is
`lane=suggested`. Ungrounded spans are dropped. No overall score. Identity
mismatch refuses review lanes unless `--force`. Optional
`[[critique.reviewers]]` run one call each (per-id model and prompt) and do
not replace `marg`, `adversary`, `claims`, `verify`, or `context`. A Markdown prompt file becomes a **Reviewer**
note** in `pack.md`; the builtin prompt still returns JSON comments. Optional
`--vale` house-style lint is a separate **checked** pass (no model). See
[critique.md](critique.md).

### C2.5. `rewrite` — apply a critique pack

```sh
uv run paperful rewrite --file ./draft.docx
uv run paperful rewrite --pack state/critiques/file-draft/20261027T... --area cites --comments substantive
uv run paperful rewrite --pack PATH --output edits --dry-run
```

Pack required. Never re-runs critique. Default area is **style** (glossary
`suggested` and obvious Vale swaps are deterministic and run with `[llm]`
off). Other areas (`cites`, `structure`, `comments`) need a model for
findings without a deterministic replacement. Body edits must not invent
numbers or cite keys. Retracted / withdrawn / EoC cites become comments,
never deletes. Optional `[[rewrite.specialists]]` can point a specialist at
an XtraGPT Ollama tag; ICLR/ReviseQA criteria are ML-shaped. Optional
`[rewrite].openxml_audit` (`uv sync --extra openxml`) validates
`tracked.docx` / `.pptx` / `.odt` with a Microsoft Open XML SDK port
(ODF adapter for `.odt`). `--output odt` / `--output pdf` write those
formats from any source. See
[rewrite.md](rewrite.md).

### D. `summarize` — grounded summary note

```sh
uv run paperful summarize --item ABCD1234                 # disk HTML + tagged child note
uv run paperful summarize -C BBNJ --to disk               # HTML only; Zotero tree stays clean
uv run paperful summarize -C BBNJ --year-from 2023 -T journalArticle --limit 5
uv run paperful summarize -C BBNJ --order newest          # recent publications first
uv run paperful summarize --item ABCD1234 --prompt prompts/one-liner.md
```

- Full PDF text is extracted (`pdftotext`, then `pypdf`) and reduced to
  `max_context_chars` as head + detected headings + tail.
- The builtin prompt asks for Objective / Methods / Key findings /
  Limitations in simple HTML. Local models often answer in Markdown anyway;
  Paperful converts headings, bullets, bold, and code fences so the Zotero
  note renders cleanly.
- Every summary ends with a provenance footer:
  `paperful · <model> · <UTC date> · prompt <sha8>` (prefixed `remote LLM`
  when the provider is not loopback).
- `--to disk|zotero|both` (default `both`, or `[summarize].dest`) chooses the
  write. `disk` is `state/summaries/<key>.html`. `zotero` is one child note
  tagged `[summarize].tag`. Without `--force`, items that already have the
  requested outputs **for the current model** (and prompt sha, when local)
  are skipped — safe to resume after an interrupt. A different model is a
  different audit trail and is rewritten. A partial pair (disk HTML without
  the note, or the reverse) is finished from a matching other side without
  calling the model again. `--force` regenerates even when the footer matches.
  `--to disk` leaves the Zotero tree clean. `--apply` still means “this run
  must write the note” and exits 1 together with `--to disk`.
- `--order newest|oldest|library` (default `[summarize].order`, or `library`)
  sets queue order **before** `--limit`. Use `newest` when the model is slow
  and recent papers matter first. Undated items stay at the end under
  `newest` / `oldest`. Item type stays a filter (`-T`), not an order key.
- Ollama receives `num_ctx` sized from the prompt (about 3 characters per
  token, plus reply headroom, rounded up, capped by `[llm].max_num_ctx`).
  The model tag has to actually support that window. If Ollama logs a
  truncation warning, lower `max_context_chars` or raise `max_num_ctx`.
- If `[lint].llm_pdf_match` is on and the item is flagged, `summarize` refuses
  it; pass `--force` to override.
- `[summarize].style = ste` appends ASD-STE100 Simplified Technical English
  constraints to the prompt (≤25 words/sentence, ≤6 sentences/paragraph,
  prefer active voice, approved vocabulary with domain terms allowed). The
  prompt SHA changes, so existing plain summaries are regenerated. After the
  model replies, a heuristic check runs: `ste_violation_policy = warn` (default)
  keeps the summary and warns; `fail` marks the item failed. Optional
  `ste_word_list_path` enables vocabulary checks against an approved list.

### E. `synthesize` — summary of summaries

```sh
uv run paperful synthesize -C BBNJ --year-from 2021 --year-to 2026 -T journalArticle
uv run paperful synthesize -C BBNJ --dry-run          # counts and chunk plan, no model call
uv run paperful synthesize -C BBNJ --to disk          # state/reports/ only
uv run paperful synthesize --library --to zotero --report-collection BBNJ
uv run paperful synthesize -C BBNJ --force            # ignore the up-to-date sidecar
```

- Reads summary notes already produced by `summarize`. A file under
  `state/summaries/<key>.html` wins; otherwise the tagged child note is read.
  PDFs are not opened again. Items with neither are listed under **Not
  included** and are not sent to the model.
- Notes are packed under `[synthesize].max_context_chars`. One chunk is one
  completion. Several chunks are synthesised in batches, then combined.
  If that still overflows, Paperful reduces again, at most three times, then
  exits 1 and asks you to narrow the scope or raise the budget.
- When there is more than one first-level chunk, Paperful completes the first
  three (or fewer), forecasts whether three reduce passes can fit the budget,
  and may run one extra reduce on that sample. If the forecast still leaves
  more than one chunk, it exits 1 before the rest of the chunks run.
- The builtin prompt asks for Corpus / Themes / Points of agreement /
  Disagreements and tensions / Gaps and open questions / Suggested reading
  order, citing only `[Surname Year]`. `--prompt FILE` overrides it; its SHA
  is stamped in the footer.
- After the model text, Paperful appends a **Sources** list (key, DOI, and
  the source note’s model and date), the **Not included** list, and any
  `[Surname Year]` token that matches no source.
- Disk output is `state/reports/<slug>.html` plus a `<slug>.json` sidecar
  (`paperful.synthesis.v1`) of source hashes. A later run with the same
  hashes and the same destination skips the model; `--force` regenerates.
- Zotero output is one standalone note in each collection you named with
  `-C` (or in `--report-collection`), tagged `paperful-report` and
  `paperful-report:<slug>`. Re-runs update that note. `--library` or
  `--item` with no collection cannot file a note: pass `--report-collection`
  or `--to disk`.
- A run report lands at `state/runs/<stamp>-synthesize.json` and does not
  replace `state/last-run.json`.

Custom prompt file example (`prompts/one-liner.md`):

```text
Write one paragraph (max 120 words) stating the research question, the
approach, and the single most important finding. Plain HTML <p> only.
Use only the metadata and document text provided.
```

The file’s SHA-256 is stamped in the footer so you can tell which prompt
produced which note.

### F. `extract-sections` — structured IMRaD JSON (optional LLM)

```sh
uv run paperful extract-sections -C BBNJ
uv run paperful extract-sections -C BBNJ --llm    # fill missing MVP fields only
uv run paperful extract-sections --library --dry-run
```

- **Rules always run** without `[llm].enabled`. Heading split uses the shared
  synonym list (see `[extract_sections]` and `state/section-headings.toml`).
- **`--llm`** (or `[extract_sections].llm`) asks the model for missing
  `abstract`, `methodology`, `conclusion`, or `research_questions` only.
  Outputs must ground in the excerpt or they are dropped.
- Writes `state/sections/<key>.json` (`paperful.sections.v1`). Reuses
  `state/rag/text/` when present; otherwise parses the mirror PDF. No Zotero
  writes. Distinct from `summarize` (HTML prose) and `rag questions` (RQ queue
  for `rag answered`). See [rag.md](rag.md#structured-sections-mirror-only).

## 5. Docker

**light** images omit `litellm` and `browser-use`. **heavy**
(`PAPERFUL_IMAGE_MODE=heavy`) installs both, so the `browser_agent` lane can
run in the container (headed `session login` still needs the host vault).
B/C/D work inside the container against a host Ollama.

**Keep loopback in config** so the same `config.toml` works for host
`uv run` and Compose:

```toml
[llm]
enabled = true
base_url = "http://127.0.0.1:11434"   # rewritten inside the container
```

Inside Docker, Paperful rewrites a loopback `[llm].base_url` to
`host.docker.internal` (Compose sets `PAPERFUL_OLLAMA_HOST` and `extra_hosts`,
same pattern as Zotero). A remote hostname stays as configured and still needs
`allow_remote = true`. The Docker bridge is treated as local — you do **not**
need `allow_remote = true` for it.

**Docker Desktop (macOS/Windows):** leave Ollama on its default loopback bind
(`127.0.0.1:11434`). Compose reaches it via `host.docker.internal` the same way
it reaches Zotero. Do **not** force `OLLAMA_HOST=0.0.0.0` on Desktop — that can
break the gateway path.

**Linux Docker Engine:** bind the host daemon so `host-gateway` can connect:

```sh
OLLAMA_HOST=0.0.0.0 ollama serve
```

Optional overrides: set `PAPERFUL_OLLAMA_HOST` in `.env`, or pin an explicit
URL with `allow_remote = true`:

```toml
base_url = "http://host.docker.internal:11434"
allow_remote = true
```

`docker compose run --rm paperful doctor` shows the `LLM` row. See
[Docker](docker.md).

## 6. Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `llm.enabled is false in config.toml` | Set `[llm].enabled = true` |
| `Ollama unreachable` / `Connection refused` in Compose | Config still pointing at container loopback without this Paperful rewrite, or Ollama not running on the host. Keep `[llm].base_url = "http://127.0.0.1:11434"`; rebuild/restart Compose. On **Linux Engine** only: `OLLAMA_HOST=0.0.0.0 ollama serve` |
| `model 'x' not in Ollama tags` | `ollama pull x`; tags must match (e.g. `qwen2.5:7b`, not `qwen2.5`) |
| `Ollama URL host … is not local` | Set `allow_remote = true` knowingly (egress notice will print) |
| `LiteLLM not installed` | `uv sync --extra llm`, or rebuild with `PAPERFUL_IMAGE_MODE=heavy` |
| `model 'ollama/…' must use llm.provider = "ollama"` | Switch provider or model id |
| `recover requires Python 3.11+` | `uv python pin 3.12 && uv sync --extra browser-agent` |
| `browser-use is not installed` | `uv sync --extra browser-agent`, or rebuild with `PAPERFUL_IMAGE_MODE=heavy` |
| `session vault not ready` | `paperful session login scholar` (headed, on the host) |
| `recover` ends `not_found` quickly | Model too small or wrong class for UI tools; try 14B+ via `[browser_agent].model`, or a one-shot `[browser_agent].fallback_model` — [browser-agent-models.md](browser-agent-models.md) |
| `recover` never starts during `run` | Extra missing, `[llm].enabled` false, `[browser_agent].during_run = false`, or `--no-browser-agent` |
| `use_vision is true but model … does not look vision-capable` | Use a VL tag (`qwen2.5vl:…`) or set `use_vision = false` |
| `fallback_model must differ` / remote fallback blocked | Set a different tag than `model`; for `provider/model` ids on Ollama provider set `llm.allow_remote = true` |
| `--from-last-run` finds no keys | Last report had no `browser_agent` miss (try `--from-last-run-mode missing`) or run `paperful run` first |
| Multimodal / 400 from Ollama on recover | `use_vision` on with a text-only tag — fix tag or turn vision off |
| Summary note shows raw `##` | Update Paperful (0.5+ converts Markdown); re-run `summarize` |
| `could not extract PDF text` | Scanned PDF. Run `paperful ocr -C …` then `--apply`, and summarize again |
| Report seems to ignore half the notes | Ollama truncated the prompt. Lower `[synthesize].max_context_chars` or raise `[llm].max_num_ctx`, and confirm the model supports that window |
| **Not included** list is long | Those items have no summary yet. Run `summarize` for them, then `synthesize` again |

## Related docs

- [ai.md](ai.md) — feasibility: try-it vs ~1.5k library, LiteLLM / OpenRouter,
  cost order of magnitude
- [rag.md](rag.md): `paperful ask` and the library index. `ask` uses the chat
  model configured here (`[rag].model` overrides it; advanced summaries use
  `[rag].summary_model` when set). Embeddings are under `[rag]`. Two modes:
  `simple` (default) and `advanced` (`--ask-mode` / `[rag].ask_mode`).
- [config.md](config.md#llm-optional-local-first) — key reference
- [commands.md](commands.md) — `recover` / `summarize` / `synthesize` / `extract-sections` / `rewrite` flags and exit codes
- [rewrite.md](rewrite.md) — apply a critique pack (style-only without a model)
- [architecture.md](architecture.md#llm-layer-optional-local-first) — layer, gates, note write path
- [camofox.md](camofox.md) — opt-in scripted Camoufox lane before `browser_agent`
- [sessions.md](sessions.md) — vault profile ownership during `recover`
- [ROADMAP.md](ROADMAP.md#optional-llm-assist-local-litellm) — what is later (Cloud/BU2, `num_ctx` pass-through)
