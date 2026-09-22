# Optional LLM: setup and verbs

Everything here is **off by default**. Paperful’s PDF loop (`run` / `attach` /
`lint` / `fix-metadata` / `dedupe`) never needs a model. Turn the LLM on only
for the five verbs below, and only after `paperful doctor` shows the `LLM` row
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
```

No Python extra is needed for Ollama: paperful talks HTTP to the daemon.

| Verb | Works well with | Notes |
| --- | --- | --- |
| `fix-metadata` titles, `lint` identity, `summarize`, `synthesize` | 7B–12B instruct models (`qwen2.5:7b`, `gemma3:12b`, `llama3.1:8b`) | JSON-capable instruct tags; thinking models are fine but slower. `summarize` and `synthesize` set Ollama `num_ctx` from the prompt, capped by `[llm].max_num_ctx` |
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

### Browser agent (`recover` / last `run` lane)

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
# max_num_ctx = 32768              # cap for the Ollama context window on summarize / synthesize

[fix_metadata]
llm_title = false                   # verb B: grounded title proposals

[lint]
llm_pdf_match = false               # verb C: pdf_identity_mismatch finding
llm_pdf_match_min_confidence = 0.6

[summarize]                         # verb D
prompt_template = "default"         # or a path, e.g. "prompts/summary.md"
max_context_chars = 24000
tag = "paperful-summary"
# dest = "both"                    # disk | zotero | both

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

On `run`, when `[llm].enabled` and `paperful[browser-agent]` are available,
paperful appends `browser_agent` after Scholar / EZProxy / htmlpdf. The agent
fires only if one of those vault lanes was tried and failed (not merely
skipped as inapplicable). Playwright releases the session profile first.
`[browser_agent].during_run = false` turns that auto-lane off. Sci-Hub, when
opted in, stays after recover.

`paperful recover --item` still targets named keys without waiting for other
lanes:

```sh
uv run paperful recover --item ABCD1234 --dry-run   # shows the start URL only
uv run paperful recover --item ABCD1234             # runs the agent, attaches on success
uv run paperful recover --item K1 --item K2 --no-attach
```

- Start URL is `https://doi.org/<DOI>` when the item has a DOI, else its URL.
- One item at a time, on the session vault profile. Never in `DEFAULT_SOURCES`.
- Hard CAPTCHAs are not solved: the item ends as `captcha` and is retried on a
  later `run` / `recover`. Timeouts / no download → `not_found`.
- Access blocks (403 / "Request blocked" / paywall with no free PDF) are
  instructed as immediate stop — the agent must not open search engines or
  support/help pages. If it navigates to Google/Bing/etc. or a support/contact
  path anyway, paperful force-stops that attempt.
- As soon as a valid PDF lands in the recover download folder (size stable
  across two polls), paperful calls `agent.stop()` so the step budget does not
  keep running after the click already succeeded.
- Success lands like any other source: PDF under `out/`, manifest line with
  `source = "browser_agent"`, attach through the normal path. A dedicated
  `recover` writes `state/runs/<stamp>-recover.json`; auto-recover on `run`
  is counted in that run’s report (`command = "run"`).
- Prints a disclaimer: you are responsible for publisher terms; page content
  goes to your configured LLM.

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

### D. `summarize` — grounded summary note

```sh
uv run paperful summarize --item ABCD1234                 # disk HTML + tagged child note
uv run paperful summarize -C BBNJ --to disk               # HTML only; Zotero tree stays clean
uv run paperful summarize -C BBNJ --year-from 2023 -T journalArticle --limit 5
uv run paperful summarize --item ABCD1234 --prompt prompts/one-liner.md
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
- `--to disk|zotero|both` (default `both`, or `[summarize].dest`) chooses the
  write. `disk` is `state/summaries/<key>.html`. `zotero` is one child note
  tagged `[summarize].tag`, updated on re-run rather than duplicated.
  `--to disk` leaves the Zotero tree clean. `--apply` still means “this run
  must write the note” and exits 1 together with `--to disk`.
- Ollama receives `num_ctx` sized from the prompt (about 3 characters per
  token, plus reply headroom, rounded up, capped by `[llm].max_num_ctx`).
  The model tag has to actually support that window. If Ollama logs a
  truncation warning, lower `max_context_chars` or raise `max_num_ctx`.
- If `[lint].llm_pdf_match` is on and the item is flagged, `summarize` refuses
  it; pass `--force` to override.

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
  If that still overflows, paperful reduces again, at most three times, then
  exits 1 and asks you to narrow the scope or raise the budget.
- The builtin prompt asks for Corpus / Themes / Points of agreement /
  Disagreements and tensions / Gaps and open questions / Suggested reading
  order, citing only `[Surname Year]`. `--prompt FILE` overrides it; its SHA
  is stamped in the footer.
- After the model text, paperful appends a **Sources** list (key, DOI, and
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

## 5. Docker

The build-local image does **not** include `litellm` or `browser-use`; the
`browser_agent` lane (`run` auto-recover and `paperful recover`) is host-only
(it needs the headed-login vault anyway). B/C/D work inside the
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
| `recover` never starts during `run` | Extra missing, `[llm].enabled` false, or `[browser_agent].during_run = false` |
| Summary note shows raw `##` | Update paperful (0.5+ converts Markdown); re-run `summarize` |
| `could not extract PDF text` | Scanned PDF without a text layer; OCR is out of scope |
| Report seems to ignore half the notes | Ollama truncated the prompt. Lower `[synthesize].max_context_chars` or raise `[llm].max_num_ctx`, and confirm the model supports that window |
| **Not included** list is long | Those items have no summary yet. Run `summarize` for them, then `synthesize` again |

## Related docs

- [config.md](config.md#llm-optional-local-first) — key reference
- [commands.md](commands.md) — `recover` / `summarize` / `synthesize` flags and exit codes
- [architecture.md](architecture.md#llm-layer-optional-local-first) — layer, gates, note write path
- [sessions.md](sessions.md) — vault profile ownership during `recover`
- [ROADMAP.md](ROADMAP.md#optional-llm-assist-local-litellm) — what is later (Cloud/BU2, playbook mining)
