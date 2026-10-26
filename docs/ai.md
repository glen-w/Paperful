# AI for notes and Ask: what is feasible

Paperful’s PDF loop (`run` / `attach` / `lint` / `fix-metadata` / `dedupe`)
never needs a model. Optional AI covers grounded notes (`summarize`), a
collection review (`synthesize`), Ask / RAG, title and identity helpers, the
browser agent, and suggested `critique --llm` comments. Heuristic AI-prose
tells and the optional Binoculars extra on `critique` are **not** authorship
proof. This page is the **feasibility and scale** guide: what works on
ordinary academic hardware, what is a “try it” experiment, and what a large
library actually costs in time or hosted tokens.

Command reference and install steps live in [LLM setup](llm.md). Ask / index
details are in [Ask your library](rag.md). Recover model bands are in
[Browser agent models](browser-agent-models.md).

## Two paths

| Path | When to use | What leaves the machine |
| --- | --- | --- |
| **Local (Ollama)** — default | Your computer can run the tags you need | Nothing (loopback) |
| **Hosted (LiteLLM)** — opt-in | You prefer an API, or local VRAM is too small for the job | Metadata + PDF text excerpts you send to the model |

Install local with Ollama only. For hosted APIs, install `paperful[llm]` and
set `provider = "litellm"`. Keys stay in the environment, never in
`config.toml`. Commands print a yellow notice when text leaves the machine.

```toml
# Local
[llm]
enabled = true
provider = "ollama"
model = "qwen2.5:7b"

# Or hosted (example: OpenRouter — see below)
# provider = "litellm"
# model = "openrouter/openai/gpt-4.1-mini"
# api_base = "https://openrouter.ai/api/v1"
```

## Try it out vs library scale

These are different jobs. A model that feels fine on one paper can be
unusable for a 1,500-PDF collection overnight.

| Job | Scale | Feasible on typical academic hardware? | Notes |
| --- | --- | --- | --- |
| One summary | `--item KEY` | Yes (local 7B–12B, or any solid hosted chat model) | Acceptance test: four sections, no invented numbers |
| Small slice | `-C … --limit 5` or one year / one type | Yes locally if a 7B tag fits; or cheap hosted | Use `--order newest` when the model is slow |
| Whole collection summarize | ~10²–10³ PDFs | Local: only with patience or strong silicon; hosted: budget tokens + rate limits | Resume-safe; already-done items skip |
| `synthesize` over ~10³ summaries | One review from notes already written | Local: can take hours and many map-reduce chunks; hosted: far fewer tokens than summarizing every PDF again | Run `synthesize --dry-run` for the chunk plan first |
| Browser agent (`recover`) | Per stubborn landing | Needs ~14B+ local or a capable hosted tool-calling model | Not a free-tier hobby lane |
| Ask / RAG | After `rag ingest` | Embeddings dominate first ingest; chat is per question | Local `nomic-embed-text` or hosted `embed_provider = "litellm"` |

**Try it out** means: one item, five papers, or a free hosted model while you
watch for timeouts and bad grounding. **Library scale** means: hundreds or
thousands of PDFs, overnight or multi-night runs, resumable batches, and a
model you trust enough not to babysit every note.

### What a ~1.5k collection actually looks like

Operator dogfood on a large ocean / BBNJ-style collection (thousands of
mirror PDFs, on the order of **~1–1.5k summaries in scope** for a review):

- **`summarize` is the expensive step.** Default grounding sends up to
  `[summarize].max_context_chars` (24,000) of PDF text per paper. On a
  high-end Apple Silicon machine running a large local Qwen tag, night
  windows of several hours typically finish on the order of **~100–300 new
  notes per night**, not the whole library in one sitting. Multiple
  overnight runs (and resume after skips / identity refusals / missing text)
  are normal. That hardware is **not** average laptop RAM/VRAM.
- **`synthesize` is cheaper than re-summarizing, but not instant.** It reads
  existing summary notes only (PDFs are not opened again). Notes are packed
  under `[synthesize].max_context_chars`; overflow uses map-reduce. A corpus
  of ~1,500 summaries can produce **dozens of first-level chunks** (e.g.
  `level 1 chunk 44/71` in a live run). Each chunk is one completion; then
  Paperful combines them (up to three reduce passes).
- **Average academic hardware** (8–16 GB unified / VRAM, shared with Zotero
  and browser tabs) is a good fit for **try-it** and **small slices**, not
  for finishing 1.5k grounded summaries in a weekend with a large local
  model. Prefer a smaller local tag (`qwen2.5:7b`), a narrower `-C` / year
  filter, or a **hosted** mid-tier model with a spend cap.

`paperful summarize` skips items already summarized **for the current
model**, so interrupted overnight runs are safe to resume. Changing the
model id rewrites the audit trail.

## Local models: pick by job, not by hype

| Hardware (rough) | Sensible local tags | Realistic use |
| --- | --- | --- |
| **8 GB** | `qwen2.5:7b`, `llama3.1:8b` | Try-it summaries; small `--limit`; Ask after a modest index |
| **12–16 GB** | 7B–14B instruct | Summaries and synthesize on **slices**; recover is tight |
| **24 GB+ / large unified memory** | 14B–32B, dogfood large Qwen tags | Multi-night library summarize; synthesize over large note sets |

Browser agent floors and avoid-lists: [browser-agent-models.md](browser-agent-models.md).
Doctor ambers undersized recover tags by name.

## Hosted models via LiteLLM

LiteLLM is the in-process adapter (`paperful[llm]`). Paperful does **not**
require you to run a separate LiteLLM proxy. Point `api_base` at any
OpenAI-compatible endpoint when you need one (OpenRouter, a campus proxy,
OpenAI, Anthropic via LiteLLM’s provider ids).

```sh
uv sync --extra llm
# or: PAPERFUL_IMAGE_MODE=heavy docker compose build
```

Keys are provider-specific environment variables (see
[LiteLLM providers](https://docs.litellm.ai/docs/providers)). Examples:

```sh
export OPENAI_API_KEY=…           # model = "openai/gpt-4.1-mini"
export ANTHROPIC_API_KEY=…        # model = "anthropic/claude-…"
export OPENROUTER_API_KEY=…       # model = "openrouter/…"
```

Rules that always apply:

- Model ids use LiteLLM’s `provider/model` form. **`ollama/…` is rejected** on
  the LiteLLM path — use `provider = "ollama"` for local tags.
- `api_base` must be `http` or `https` when set.
- Title / abstract / PDF excerpts leave the machine; for `recover`, page text
  can too.

Full verb docs: [llm.md § LiteLLM](llm.md#litellm-paid--openai-compatible-apis).

### OpenRouter setup

[OpenRouter](https://openrouter.ai/) aggregates many providers behind one
OpenAI-compatible API. Useful when you want one key and easy model swaps.

1. Create an account and an API key at
   [openrouter.ai/keys](https://openrouter.ai/keys).
2. Install the LiteLLM extra (`uv sync --extra llm` or **heavy** Docker).
3. Configure Paperful:

```toml
[llm]
enabled = true
provider = "litellm"
model = "openrouter/openai/gpt-4.1-mini"   # pin a concrete id; avoid random routers for batches
api_base = "https://openrouter.ai/api/v1"
timeout_s = 180                            # hosted + long prompts; raise if you see timeouts
```

```sh
export OPENROUTER_API_KEY=sk-or-…
uv run paperful doctor                     # LLM row should be green (import + config)
uv run paperful summarize --item ABCD1234  # one-paper acceptance test
```

Optional for RAG embeddings on the same key:

```toml
[rag]
enabled = true
embed_provider = "litellm"
embed_model = "openrouter/openai/text-embedding-3-small"
# embed_api_base empty → reuses [llm].api_base
```

Pin a **fixed** model id for library-scale runs. The
[`openrouter/free`](https://openrouter.ai/openrouter/free) router picks a free
model per request — fine for curiosity, poor for consistent note quality
across a collection. Browse current free and paid models at
[openrouter.ai/models](https://openrouter.ai/models) and the
[free models collection](https://openrouter.ai/collections/free-models).

### Free OpenRouter lanes

Free `:free` endpoints can run a **try-it** `summarize --item` when they are
up and rate limits allow. They are a weak default for library scale:

- Daily / burst rate limits and empty responses are common.
- Serving is often heavily quantized; grounding quality varies day to day.
- A random free router makes provenance and quality inconsistent.
- `recover` (tool calling, multi-step) is usually a poor free-tier fit.

Treat free lanes as experiments. For hundreds of papers, prefer a **paid
mid-tier** chat model with a spending limit in the OpenRouter dashboard, or
local Ollama.

## Cost order of magnitude (hosted)

Paperful cannot quote a fixed dollar price: providers change rates, your PDF
text length varies, and retries / identity failures change call counts. Use
this **order-of-magnitude** sketch, then check the provider’s pricing page
before a large run.

**Rough tokens per grounded summary** (defaults):

- Input: up to ~24k characters of PDF text ≈ **~6k–10k tokens**, plus prompt
  and metadata.
- Output: under ~600 words ≈ **~0.5k–1.5k tokens**.
- Ballpark: **~8k–12k tokens per successful summary**.

**For ~1,500 papers** (one call each, no retries): on the order of
**~12–20 million tokens** total.

| Hosted tier (illustrative) | Ballpark for ~1.5k summaries | Role |
| --- | --- | --- |
| Mid-tier / “mini” chat APIs | Often **tens of USD**, sometimes low double digits | Practical remote path for library summarize |
| Strong general / frontier chat | **Higher by several×** — can reach low hundreds USD | Only if you need that quality bar |
| OpenRouter `:free` | **$0** listed, but rate limits and flaky uptime | Try-it only |
| Embeddings for a large `rag ingest` | Usually **much cheaper per token** than chat, but first ingest is many passages | Budget separately from summarize |

**`synthesize` over ~1.5k notes** is typically **one to two orders of
magnitude cheaper** than summarizing those PDFs: you send packed summary
HTML in dozens of chunk completions (plus reduce passes), not 1.5k full PDF
excerpts. Still check `synthesize --dry-run` for the chunk count before you
pay for a long wall-clock run.

How to estimate for *your* library:

1. `paperful summarize -C … --limit 5` on a hosted model; note provider usage
   / cost for those five.
2. Multiply by the number of **not-yet-summarized** items (`summarize` skips
   current-model footers).
3. Add headroom for failures, `--force` regenerations, and identity retries.
4. Set a spend cap on OpenRouter (or your provider) before an overnight batch.
5. For synthesize: `synthesize --dry-run` → chunk count × similar per-call cost.

Pricing pages to re-check (numbers change):

- [OpenRouter models / pricing](https://openrouter.ai/models)
- [OpenAI API pricing](https://openai.com/api/pricing/)
- [Anthropic pricing](https://www.anthropic.com/pricing)
- [LiteLLM providers](https://docs.litellm.ai/docs/providers)

## Practical recipes

**Laptop try-it (local)**

```sh
ollama pull qwen2.5:7b
# [llm] enabled, provider = "ollama", model = "qwen2.5:7b"
uv run paperful summarize --item ABCD1234
uv run paperful synthesize -C "My Collection" --year-from 2024   # narrow scope
```

**Small hosted batch (OpenRouter mid-tier)**

```sh
uv sync --extra llm
export OPENROUTER_API_KEY=…
# config: provider = litellm, model + api_base as above
uv run paperful summarize -C "My Collection" --year-from 2024 --limit 20 --order newest
```

**Library-scale summarize (local, multi-night)**

- Keep one model id for the whole campaign.
- Prefer `--order newest` or year slices so useful notes land first.
- Let night / cron windows stop cleanly; re-run to resume skips.
- Fix `could not extract PDF text` with OCR before expecting a summary.
- Do not expect a large Qwen tag on high-end silicon to finish 1.5k papers in
  one evening — plan for **multiple overnight runs**.

**Library-scale synthesize**

```sh
uv run paperful synthesize -C "My Collection" --dry-run   # sources + chunk plan
uv run paperful synthesize -C "My Collection"             # map-reduce over notes
```

Narrow with `-T`, `--year-from` / `--year-to`, or a smaller collection if the
chunk plan is huge and wall time matters.

## Privacy and grounding (unchanged)

- Prompts only see item metadata plus text from PDFs already on disk
  (`out/` or `state/pdf-cache/`).
- Disk write first; Zotero notes are optional (`--to disk|zotero|both`).
- Remote footers are stamped `remote LLM` so you can tell egress notes apart.
- Terms: [TERMS](TERMS.md).

## See also

| Doc | Role |
| --- | --- |
| [llm.md](llm.md) | Install, config keys, verb behaviour, troubleshooting |
| [rag.md](rag.md) | Index, Ask, embedding providers |
| [browser-agent-models.md](browser-agent-models.md) | Recover / Ollama VRAM bands |
| [example-setups.md](example-setups.md#notes-a-collection-review-and-ask) | Workbench setup 4 |
| [config.md](config.md#llm-optional-local-first) | Full key tables |
| [docker.md](docker.md#image-mode-light-vs-heavy) | light vs heavy (LiteLLM + RAG) |
