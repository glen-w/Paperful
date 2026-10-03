# Browser agent: local models (Ollama + browser-use)

Paperful’s `browser_agent` lane and `paperful recover` drive
[browser-use](https://github.com/browser-use/browser-use) against your **session
vault** Chromium profile. The model must emit **tool-shaped actions** (click by
element index, wait, navigate) — not chat about downloading.

**There is no official browser-use benchmark for local Ollama tags.** The guidance
below is evidence-weighted from browser-use docs, GitHub issues, and community
reports (2025–2026), folded for Paperful’s honesty rules and shipped wiring.
See [ROADMAP § browser-use](ROADMAP.md#browser-use-integration-models-docs-config).

## How Paperful uses browser-use (not vanilla quickstart)

| Topic | Paperful behaviour |
| --- | --- |
| LLM | `[browser_agent].model` if set, else `[llm].model`; Ollama → `ChatOllama`, LiteLLM → `ChatLiteLLM` |
| Vision | **`use_vision=False`** by default — text/DOM index path only. Text-only Ollama models error if vision is on. |
| Browser | System **Chrome** (`channel="chrome"`), same profile as `session login`; uBlock + cookie extensions on |
| Success | Valid PDF on disk (`min_pdf_bytes`, stable size) — **not** agent `done` alone |
| Task | Stay on DOI/landing; no search engines; no purchase; stop on CAPTCHA / paywall / 403 |
| Caps | `[browser_agent].max_steps`, `max_wall_s`; agent stopped early when PDF lands |

Operator setup: [LLM § recover](llm.md#a-recover--browser-agent-pdf-recovery), [sessions](sessions.md), [config § browser_agent](config.md#llm-optional-local-first).

## Recommended Ollama tags (by VRAM band)

Use **`ollama pull`** tags that support **tool calling** (`ollama show <tag>` — avoid
HTTP 400 “does not support tools”). Prefer **non-thinking** instruct tags for
recover; thinking models can burn step/wall time.

| VRAM (rough) | Good defaults | Notes |
| --- | --- | --- |
| **24 GB+** | `qwen2.5vl:32b` (hard UI + vision), `qwen3:32b` / `qwen3:30b`, `qwen2.5:32b` | Best local band for publisher cookie → PDF clicks. VL needs Paperful vision support (today: text-only). |
| **12–16 GB** | `qwen3:14b`, `qwen2.5:14b` | **Documented floor** for recover; more retries, tight prompts. Match `use_vision=False`. |
| **~8 GB** | Prototype only: `llama3.1:8b`, `qwen2.5vl:7b` | Official docs’ Ollama example is `llama3.1:8b` — connects, often fails soft walls. |

Paperful **`doctor`** ambers agent models whose **name** looks under **~10B**
(e.g. `7b` in the tag). **`llm.md`** recommends **14B+** for browsing. Treat
14B as the serious minimum; 32B-class for batch recover on messy publisher UIs.

### Ranked starting points (PDF / publisher UI)

1. **`qwen2.5vl:32b`** — vision + layout; best when controls are icon-only or missing from the a11y tree *(needs `use_vision=True` when Paperful exposes it)*.
2. **`qwen3:32b`** / **`qwen3:30b`** — strong tool/agent loops (Ollama tool docs use Qwen3).
3. **`qwen2.5:32b`** — proven text JSON / multi-step UI in community reports.
4. **`mistral-small:24b`** — function-calling specialist; fits mid VRAM.
5. **`qwen3:14b`** / **`qwen2.5:14b`** — minimum serious band.
6. **`qwen2.5vl:7b`** — small vision option.
7. **`llama3.1:8b`** — docs plumbing example only; not a production PDF agent.

Upstream warns that **non–`qwen-vl-max` Qwen** can emit **flat action JSON**
(e.g. `{"navigate": "url"}` instead of nested objects). browser-use docs suggest
**concrete nested examples** in the system prompt if parsing fails.

### Avoid as primary recover models

- Sub-**7B** chat tags, embedding models, legacy **`qwen:`** (pre-2.5) without tools.
- Many **Gemma3** builds → Ollama **400** (no tools template) in community reports.
- **DeepSeek-R1** / heavy reasoning tags — thinking noise, slow steps, fragile tools API.
- **Small coder-only** tags — JSON sometimes works; browsing/UI loops are weaker than general agent models (validate on *your* publishers before relying on a coder tag).
- Hosted-only names (**`qwen-vl-max`**, Browser Use Cloud **`bu-*`**) — not `ollama pull`.

## Context, temperature, and Ollama tuning

browser-use sends **large DOM snapshots** each step. Ollama may default to a
**small context window** on consumer GPUs (community reports cite ~4k under 24 GiB).
Agent workloads often want **16k–32k+**; **64k** when VRAM allows. Paperful does
**not** yet pass `num_ctx` into `ChatOllama` — raise context in **`Modelfile`**
/ Ollama env or track [ROADMAP](ROADMAP.md#browser-use-integration-models-docs-config)
for a config knob.

Community configs often use **`temperature=0`** for action selection. browser-use
maintainers note that **smaller local models struggle with tool-calling**
([discussion #4261](https://github.com/browser-use/browser-use/discussions/4261)).

## Acceptance test (one page, your rights)

Before trusting a tag for a collection run:

1. Pick one article URL you **already** may access (OA or campus session in the vault).
2. `paperful recover --item <KEY> --dry-run` then run without dry-run.
3. **Pass** = PDF under `out/` with sane bytes — not a polite `done` in logs.
4. **Fail** = invents a new host, opens a search engine, or claims success with no file
   ([Playwright download caveat](https://stackoverflow.com/questions/79384448/issue-with-downloading-file-via-browser-use)).

Paperful already enforces disk verification and aborts on search/support URLs;
models that only succeed by hallucinating PDF URLs should be demoted regardless of size.

## Deterministic paths beat the agent

Use HTTP / vault Playwright lanes first. Reserve `browser_agent` for **soft UI**
(cookie banner → “Download PDF”) when metadata lanes and vault retry already failed.
See [architecture § sources](architecture.md) and [workflows](workflows.md).

## LiteLLM / remote

With `provider = "litellm"`, page text may leave the machine (orange disclaimer).
Use for recovery only with `allow_remote` understood. Reject `ollama/…` ids on the
LiteLLM path — use `provider = "ollama"` instead. See [llm.md](llm.md).

### Jev (post-v1)

[Jev](https://openrouter.ai/docs/guides/community/jev) (typesafe/jev-1.13, available on
OpenRouter) is optimized for browser automation and notably **faster** than local Ollama
models for PDF recovery tasks. Trade-off: cloud model (costs per API call, page content
leaves the machine) vs local inference (free, slower per step). Worth spiking post-v1 when
browser recovery is stable and operators want to batch-recover large citation gaps on mesopelagic-scale
collections.

## References

- browser-use: [supported models](https://docs.browser-use.com/open-source/supported-models), [tools](https://docs.browser-use.com/open-source/customize/tools/available.md), [agent params](https://docs.browser-use.com/open-source/customize/agent/all-parameters.md)
- Ollama: [tool calling](https://docs.ollama.com/capabilities/tool-calling)
- Issues: [#442](https://github.com/browser-use/browser-use/issues/442), [#486](https://github.com/browser-use/browser-use/issues/486), [#814](https://github.com/browser-use/browser-use/issues/814)
- Internal research note (2026-09-29): distilled into this page; full multi-lane draft kept under `assessments/2026-09-29-ollama-browser-use-pdf-download-models.md`.
