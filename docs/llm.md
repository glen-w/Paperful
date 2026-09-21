# Optional LLM: setup and verbs

Everything here is **off by default**. Paperful’s PDF loop (`run` / `attach` /
`lint` / `fix-metadata` / `dedupe`) never needs a model. Turn the LLM on only
for the four verbs below, and only after `paperful doctor` shows the `LLM` row
green.

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
  `config.toml`; `browser_agent` is never in the default source list.

## 1. Install

### Ollama (default, local)

```sh
# macOS
brew install ollama && ollama serve          # or the Ollama.app menu-bar daemon
# Linux
curl -fsSL https://ollama.com/install.sh | sh

ollama pull qwen2.5:7b        # title / identity / summaries
ollama pull qwen2.5:14b       # recommended floor for `recover` (browsing agent)
```

No Python extra is needed for Ollama: paperful talks HTTP to the daemon.

| Verb | Works well with | Notes |
| --- | --- | --- |
| `fix-metadata` titles, `lint` identity, `summarize` | 7B–12B instruct models (`qwen2.5:7b`, `gemma3:12b`, `llama3.1:8b`) | JSON-capable instruct tags; thinking models are fine but slower |
| `recover` | 14B+ (`qwen2.5:14b`, `qwen3:14b`, larger) | Small models loop on cookie banners and publisher menus; `doctor` warns under ~10B by tag name |

### LiteLLM (paid / OpenAI-compatible APIs)

```sh
uv sync --extra llm            # installs litellm
export OPENAI_API_KEY=...      # or ANTHROPIC_API_KEY, etc. — provider-specific env var
```

```toml
[llm]
enabled = true
provider = "litellm"
model = "openai/gpt-4.1-mini"          # LiteLLM model id (provider/model)
# api_base = "https://my-proxy.example/v1"   # optional OpenAI-compatible base
```

Rules: `ollama/…` model ids are rejected on the LiteLLM path (use
`provider = "ollama"` instead); `api_base` must be `http(s)`. With LiteLLM,
title/abstract/PDF excerpts (and, for `recover`, page text) leave your machine.

### Browser agent (`recover` only)

```sh
uv sync --extra browser-agent  # browser-use + ollama client; needs Python >= 3.11
uv run paperful session login scholar   # the agent reuses this Chromium profile
```

Paperful core supports Python 3.10; the extra is marked
`python_version >= "3.11"` so `uv sync` on 3.10 simply skips it and `recover`
exits 1 with a hint. If your `.python-version` is 3.10, run
`uv python pin 3.12 && uv sync --extra browser-agent`.

## 2. Configure

```toml
[llm]
enabled = true
provider = "ollama"                 # ollama | litellm
model = "qwen2.5:7b"
base_url = "http://127.0.0.1:11434"
allow_remote = false                # true only for a non-loopback Ollama host
timeout_s = 120

[fix_metadata]
llm_title = false                   # verb B: grounded title proposals

[lint]
llm_pdf_match = false               # verb C: pdf_identity_mismatch finding
llm_pdf_match_min_confidence = 0.6

[summarize]                         # verb D
prompt_template = "default"         # or a path, e.g. "prompts/summary.md"
max_context_chars = 24000
tag = "paperful-summary"

[browser_agent]                     # verb A
max_steps = 20
max_wall_s = 300
# model = "qwen2.5:14b"             # override [llm].model for browsing only
```

Full key table: [Configuration § LLM](config.md#llm-optional-local-first).

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

```sh
uv run paperful recover --item ABCD1234 --dry-run   # shows the start URL only
uv run paperful recover --item ABCD1234             # runs the agent, attaches on success
uv run paperful recover --item K1 --item K2 --no-attach
```

- Start URL is `https://doi.org/<DOI>` when the item has a DOI, else its URL.
- Runs **only** the `browser_agent` source, on the session vault profile, one
  item at a time. It is not part of `run` and never in `DEFAULT_SOURCES`.
- Hard CAPTCHAs are not solved: the item ends as `captcha` and is retried on a
  later `recover`. Timeouts / no download → `not_found`.
- Success lands like any other source: PDF under `out/`, manifest line with
  `source = "browser_agent"`, attach through the normal path, report at
  `state/runs/<stamp>-recover.json` (`command = "recover"`).
- Prints a disclaimer: you are responsible for publisher terms; page content
  goes to your configured LLM.

Do not run `run` and `recover` concurrently against the same vault: both
would open the same Chromium profile.

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

### D. `summarize` — grounded summary note

```sh
uv run paperful summarize --item ABCD1234                 # → state/summaries/ABCD1234.html
uv run paperful summarize -C BBNJ --limit 5
uv run paperful summarize -C BBNJ --year-from 2023 -T journalArticle --limit 5
uv run paperful summarize --item ABCD1234 --apply         # create/update the tagged child note
uv run paperful summarize --item ABCD1234 --prompt prompts/one-liner.md --apply
```

- Full PDF text is extracted (`pdftotext`, then `pypdf`) and reduced to
  `max_context_chars` as head + detected headings + tail.
- The builtin prompt asks for Objective / Methods / Key findings /
  Limitations in simple HTML. Local models often answer in Markdown anyway;
  paperful converts headings, bullets, bold, and code fences so the Zotero
  note renders cleanly.
- Every summary ends with a provenance footer:
  `paperful · <model> · <UTC date> · prompt <sha8>` (prefixed `remote LLM`
  when the provider is not loopback).
- `--apply` finds an existing child note carrying `[summarize].tag` and
  **updates** it; otherwise it creates one. Re-running never duplicates notes.
- If `[lint].llm_pdf_match` is on and the item is flagged, `summarize` refuses
  it; pass `--force` to override.

Custom prompt file example (`prompts/one-liner.md`):

```text
Write one paragraph (max 120 words) stating the research question, the
approach, and the single most important finding. Plain HTML <p> only.
Use only the metadata and document text provided.
```

The file’s SHA-256 is stamped in the footer so you can tell which prompt
produced which note.

## 5. Docker

The optional image does **not** include `litellm` or `browser-use`; `recover`
is host-only (it needs the headed-login vault anyway). B/C/D work inside the
container against a host Ollama:

```toml
[llm]
enabled = true
base_url = "http://host.docker.internal:11434"
allow_remote = true      # required: host.docker.internal is not loopback
```

and start Ollama bound to all interfaces on the host
(`OLLAMA_HOST=0.0.0.0 ollama serve`). See [Docker](docker.md).

## 6. Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `llm.enabled is false in config.toml` | Set `[llm].enabled = true` |
| `Ollama unreachable` | `ollama serve` not running, wrong `base_url`, or firewall |
| `model 'x' not in Ollama tags` | `ollama pull x`; tags must match (e.g. `qwen2.5:7b`, not `qwen2.5`) |
| `Ollama URL host … is not local` | Set `allow_remote = true` knowingly (egress notice will print) |
| `LiteLLM not installed` | `uv sync --extra llm` |
| `model 'ollama/…' must use llm.provider = "ollama"` | Switch provider or model id |
| `recover requires Python 3.11+` | `uv python pin 3.12 && uv sync --extra browser-agent` |
| `browser-use is not installed` | `uv sync --extra browser-agent` |
| `session vault not ready` | `paperful session login scholar` (headed, on the host) |
| `recover` ends `not_found` quickly | Model too small for browsing; try a 14B+ tag via `[browser_agent].model` |
| Summary note shows raw `##` | Update paperful (0.5+ converts Markdown); re-run `summarize --apply` |
| `could not extract PDF text` | Scanned PDF without a text layer; OCR is out of scope |

## Related docs

- [config.md](config.md#llm-optional-local-first) — key reference
- [commands.md](commands.md) — `recover` / `summarize` flags and exit codes
- [architecture.md](architecture.md#llm-layer-optional-local-first) — layer, gates, note write path
- [sessions.md](sessions.md) — vault profile ownership during `recover`
- [ROADMAP.md](ROADMAP.md#optional-llm-assist-local-litellm) — what is later (Cloud/BU2, playbook mining)
