# Configuration (`config.toml`)

Copy `config.example.toml` to `config.toml` and edit locally; the example file
is tracked in git, personal config is not.

**Docker:** prefer relative `out_dir` / `state_dir` (`"out"` / `"state"`). Paths
with `~/…` expand to the container user's home (not the Compose `/data` mount),
so host `session login` and `docker compose run` will disagree about where
cookies live. `paperful doctor` ambers when that happens.

**Grey literature and no-DOI items** — Unpaywall and most DOI sources cannot
resolve PrepCom papers, many DOALOS/UN docs, or undocs without a DOI. `direct`
uses **declarative grey playbooks** (rewrite / scrape / synthesize). Grey-lit
packs: UNGA/undocs · BBNJ/DOALOS · ISA (plus FAO/OECD/IEA/WHO examples). Add
your own hosts in `config.toml`. Skip-host URLs (YouTube, Scholar, …) still
synthesize from Extra/title when a playbook matches. Then `htmlpdf` can print
DOI-less `document` / `report` pages. Otherwise the manifest records
`no_identifier`. See [Grey literature playbooks](#grey-literature-playbooks)
and [architecture](architecture.md).

| Key | Default | Meaning |
| --- | --- | --- |
| `email` | `""` | Sent as `mailto` to Unpaywall/OpenAlex/Crossref and as `email` to NCBI ID Converter (required by Unpaywall) |
| `manager` | `zotero` | Library adapter. **`zotero` is well tested — use that.** `mendeley` and `endnote` are in the tree and seeking testers. EndNote writes are an import bundle, not an edit of the `.enl` file |
| `[mendeley].client_id` / `client_secret` | `""` | Elsevier OAuth app from [dev.mendeley.com/myapps.html](https://dev.mendeley.com/myapps.html). Or `PAPERFUL_MENDELEY_CLIENT_*`. See [Mendeley](mendeley.md) |
| `[mendeley].redirect_uri` | `http://127.0.0.1:8765/callback` | Must match the app. Host-only (`session login mendeley`) |
| `[endnote].library` | (none) | Path to the `.enl` file. Matching `.Data` (with `sdb/sdb.eni`) must sit beside it. See [EndNote](endnote.md) |
| `out_dir` / `state_dir` | `out` / `state` | PDF tree; manifest, patches, PDF cache, run reports, and write key |
| `[mirror].pdfs` | `additional` | `snapshot` PDF policy: `additional` (fetched files only), `all` (also export Zotero PDFs), `none` (records and notes only). `run` always writes PDFs it downloads |
| `sources` | `unpaywall` → `openalex` → `arxiv` → `biorxiv` → `europepmc` → `semanticscholar` → `core` → `direct` → `ezproxy` → `htmlpdf` | Source order; `--sources` overrides per run. `scholar` and `scihub` are **not** included unless you opt in. `core` is skipped until `core_api_key` is set |
| `verify_doi` | `true` | Check library DOIs against Crossref/OpenAlex before fetching; may swap DOI **in memory** for that run. `false` leaves an existing DOI as `doi_verified=unknown` and does not swap |
| `doi_suspect_score` | `0.70` | Title similarity below this marks a library DOI as suspect (eligible for in-memory swap). API failure is `unknown` and **keeps** the original DOI |
| `core_api_key` | `""` | CORE API bearer token; empty skips the `core` source |
| `ezproxy_base` | `""` (disabled) | Campus proxy prefix ending in `url=` — see [Campus EZProxy](ezproxy.md) |
| `ezproxy_cookies` | `state/ezproxy-cookies.txt` | Compat Netscape dump after `session login ezproxy` |
| `scholar_cookies` | `state/scholar-cookies.txt` | Compat Netscape dump after `session login scholar` |
| `grey_playbooks_builtin` | `true` | Load the packaged ocean/governance example pack |
| `grey_playbooks_dir` | (none) | Directory of extra pack `*.toml` files (merged after builtin, before inline). Relative paths resolve against the config file's folder |
| `[[grey_playbooks]]` | (none) | User rewrite/scrape/synthesize rules; same `name` overrides the pack |
| `scihub_mirrors` | built-in list | Hostnames tried in order |
| `delay_scihub_s` | `[3, 8]` | Random pause (seconds) before each Sci-Hub / EZProxy / htmlpdf page fetch |
| `concurrency_oa` | `4` | Parallel workers for open-access sources (Scholar, EZProxy, htmlpdf, and Sci-Hub are serial) |
| `min_pdf_bytes` | `10000` | Smaller downloads are rejected as error pages |
| `crossref_min_score` | `0.90` | Title-similarity threshold for accepting a title→DOI match (Crossref, then OpenAlex, then Semantic Scholar) |
| `mirror_failures_before_skip` | `3` | Network failures before a Sci-Hub mirror is skipped for the run |
| `source_routing` | `true` | Skip sources that look inapplicable from item metadata; use `--try-all` to override per run |
| `circuit_breaker_threshold` | `3` | Block-like failures (CAPTCHA, rate limits) before a source is skipped for the rest of the run |
| `attach` | `true` | Attach into Zotero after download (`--no-attach` overrides) |
| `app_name` | `paperful` | Name shown in Zotero's authorisation dialog |
| `user_agent` | Chrome-like string | HTTP `User-Agent` for source and download requests |

Leave `ezproxy_base` empty (or remove `ezproxy` from `sources`) if you do not
use a library proxy. Google Scholar is off until you add `scholar` to
`sources` (and usually run `session login scholar`). Sci-Hub is off until
you add `"scihub"` to `sources` or pass `--scihub` — see [Sci-Hub](scihub.md).
Items dated after 2021 are not sent to Sci-Hub; a `--year-from` past that
year drops it from the run list.
Set `source_routing = false` (or pass `--try-all`) when Zotero fields are
untrustworthy and you want every configured source tried anyway.

## Run configs (profiles)

A **profile** stores one SCOPE plus the fetch/write flags you would otherwise
repeat on the command line. It is not a grey-lit playbook and not a
[pack](commands.md). Full recipes: [Workflows](workflows.md).

| Term | Meaning |
| --- | --- |
| Profile / run config | Named SCOPE + policy (`collections`, years, types, `try_all`, …) |
| `paperful all` | `gaps` → `run` → `lint` → `fix-metadata` → `summarize` |
| `--preset eoi` | Source list only (OA + EZProxy; no Scholar, no Sci-Hub) |
| Playbook | Grey-lit URL → PDF rule |
| Pack | Witness of one executed sequence under `state/packs/` |

**Where files live.** Beside `config.toml`:

- `[profiles.<name>]` tables in that file
- `profiles/<name>.toml` in the same directory (overlay: file wins per key)

Relative `profiles/` follows the config file, including Compose `/data`.
Profiles are not written under `state/` (that tree is backup-excluded).

**Precedence** for `paperful all` and `paperful profile show`:

1. Builtin `all` policy when the profile omits a key: steps `gaps`, `run`, `lint`, `fix-metadata`, `summarize`; `try_all`, `retry_failed`, `upgrade_linked`, and `apply` true
2. `[profiles.*]`
3. `profiles/<name>.toml`
4. `--profile` or `-f` / `--run-config`
5. Explicit CLI flags

A bare `paperful run --profile` does **not** inherit the builtin `all` flags.
Omitted `try_all` stays off unless the profile sets it.

| TOML key | CLI |
| --- | --- |
| `collections` | `--collection` / `-C` (repeatable; replaces the list) |
| `library` | `--library` / `--no-library` |
| `types` | `--type` / `-T` |
| `year_from` / `year_to` | `--year-from` / `--year-to` |
| `limit` | `--limit` / `-n` |
| `try_all` | `--try-all` / `--no-try-all` |
| `retry_failed` | `--retry-failed` / `--no-retry-failed` |
| `upgrade_linked` | `--upgrade-linked` / `--no-upgrade-linked` |
| `no_attach` | `--no-attach` / `--attach` |
| `scihub` | `--scihub` / `--no-scihub` |
| `preset` | `--preset` (`eoi`) |
| `sources` | `--sources` (comma-separated; TOML is an array of strings) |
| `apply` | `--apply` / `--no-apply` on `all`, `fix-metadata`, and `summarize` |
| `overwrite` | `--overwrite` / `--no-overwrite` on `fix-metadata` |
| `steps` | `--steps` (comma-separated). Optional extras: `snapshot`, `dedupe`, `synthesize` |
| `require_summarize` | `--require-summarize` — exit 1 if `summarize` cannot run because the LLM is off |
| `description` | `profile save --description` |

`profile save NAME` writes `profiles/NAME.toml` from the flags on that
invocation (plus `--profile` / `-f` if you are copying one). It refuses to
overwrite unless `--force`. It does not edit `config.toml`.

```toml
[profiles.bbnj-journal]
description = "BBNJ journal articles 2021–2026"
collections = ["BBNJ"]
types = ["journalArticle"]
year_from = 2021
year_to = 2026
try_all = true
retry_failed = true
upgrade_linked = true
apply = true
```

## Grey literature playbooks

Host-specific PDF rules are **data**, not forever-hardcoded Python. Kinds:

| Kind | When | Example |
| --- | --- | --- |
| `rewrite` | Zero-fetch URL → PDF (`url_re` + `pdf_template`, or `parser = "undocs"`) | FAO `/3/{code}/` |
| `scrape` | Prefer matching hrefs on that host’s HTML landing | OECD `/download/`, WHO `/iris/` |
| `synthesize` | Extra/title (or skip-host URL + Extra) → PDF URL | UN document symbol → undocs |

The packaged file
[`paperful/data/grey_playbooks_ocean.toml`](https://github.com/glen-w/Paperful/blob/main/paperful/data/grey_playbooks_ocean.toml)
is an **ocean/governance example pack** — grey-lit packs **UNGA/undocs ·
BBNJ/DOALOS · ISA**, plus FAO/OECD/IEA/WHO examples — on by default via
`grey_playbooks_builtin = true`. Optionally set `grey_playbooks_dir = "packs"`
to load every `*.toml` in that directory (same schema). Merge order: builtin →
dir packs → inline `[[grey_playbooks]]` (same `name` replaces earlier entries).
PMC / arXiv / HAL stay as core OA rewrites, not playbooks. See
[architecture § Grey literature](architecture.md#grey-literature) for hosts
and symbol patterns. If you use the optional Docker image, put packs next to
config under `/data` (see [Docker](docker.md)).

```toml
grey_playbooks_builtin = true
grey_playbooks_dir = "packs"

[[grey_playbooks]]
name = "my_org"
kind = "rewrite"
hosts = ["example.org"]
url_re = '(?i)example\\.org/docs/(?P<code>[a-z0-9]+)/?'
pdf_template = "https://example.org/docs/{code}/{code}.pdf"
```

## LLM (optional, local-first)

Off by default. Install extras: `uv sync --extra llm` (LiteLLM for paid APIs),
`uv sync --extra browser-agent` (Python 3.11+ only, for the `browser_agent` run
lane and `recover`). Setup
walkthrough, model advice, Docker networking, and troubleshooting: [LLM](llm.md).

| Table / key | Default | Role |
| --- | --- | --- |
| `[llm].enabled` | `false` | Master gate |
| `[llm].provider` | `ollama` | `ollama` or `litellm` |
| `[llm].model` | `qwen2.5:7b` | Model id |
| `[llm].base_url` | `http://127.0.0.1:11434` | Ollama API |
| `[llm].api_base` | `""` | OpenAI-compatible base when `provider = litellm` |
| `[llm].allow_remote` | `false` | Allow non-loopback Ollama (e.g. `host.docker.internal` from the image) |
| `[llm].timeout_s` | `120` | Per-completion timeout |
| `[llm].max_num_ctx` | `32768` | Cap on the Ollama context window for `summarize` and `synthesize`. The model tag must support it |
| `[fix_metadata].llm_title` | `false` | Grounded title proposals in `fix-metadata` |
| `[lint].llm_pdf_match` | `false` | `pdf_identity_mismatch` finding; `summarize` refuses flagged items unless `--force` |
| `[lint].llm_pdf_match_min_confidence` | `0.6` | A `match: true` below this confidence is still flagged |
| `[summarize].prompt_template` | `default` | Or path to a custom prompt file (relative to the config file); its SHA is stamped in the note footer |
| `[summarize].max_context_chars` | `24000` | Budget for PDF text sent to the model (head + headings + tail) |
| `[summarize].tag` | `paperful-summary` | Zotero child-note tag; re-runs update the note carrying it |
| `[summarize].dest` | `both` | `disk` (`state/summaries/`), `zotero` (child note), or `both`. `--to` overrides |
| `[synthesize].prompt_template` | `default` | Report prompt, or a path relative to the config file |
| `[synthesize].max_context_chars` | `24000` | Budget for summary text in one model call (room left for the prompt) |
| `[synthesize].tag` | `paperful-report` | Base tag on the collection note. A second tag `tag:<slug>` makes re-runs update |
| `[synthesize].dest` | `both` | `disk` (`state/reports/`), `zotero` (standalone note in the collection), or `both` |
| `[synthesize].timeout_s` | `max([llm].timeout_s, 300)` | Per-completion timeout for the report |
| `[browser_agent].max_steps` / `max_wall_s` | `20` / `300` | Step and wall-clock caps for `recover` (agent stops early once a valid PDF lands) |
| `[browser_agent].during_run` | `true` | When `[llm].enabled` and the extra is installed, `run` appends `browser_agent` after Scholar / EZProxy / htmlpdf |
| `[browser_agent].model` | (`[llm].model`) | Larger model for browsing only; `doctor` warns under ~10B |

API keys stay in the environment (never in `config.toml`).
