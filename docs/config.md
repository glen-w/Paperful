# Configuration (`config.toml`)

Copy `config.minimal.toml` for a first run (email, paths, open-access sources)
or `config.example.toml` for the full file. Both are tracked; `config.toml` is not.

**Docker:** prefer relative `out_dir` / `state_dir` (`"out"` / `"state"`). Paths
with `~/…` expand to the container user's home (not the Compose `/data` mount),
so host `session login` and `docker compose run` will disagree about where
cookies live. `paperful doctor` ambers when that happens.

**Grey literature and no-DOI items** — Unpaywall and most DOI sources cannot
resolve PrepCom papers, many DOALOS/UN docs, or undocs without a DOI. `direct`
uses **declarative grey playbooks** (rewrite / scrape / synthesize). Grey-lit
packs: UNGA/undocs · BBNJ/DOALOS · ISA, plus FAO and ocean hosts
(RFMOs, IUCN/DOSI, IDDRI/Pew). Energy (IEA, IRENA) and other international
orgs (OECD, WHO, UNEP, UNDP) ship as optional example files under
`paperful/data/grey_playbooks_examples/`. Add your own hosts in `config.toml`.
Skip-host URLs (YouTube, Scholar, …) still
synthesize from Extra/title when a playbook matches. Then `htmlpdf` can print
DOI-less `document` / `report` pages. Otherwise the manifest records
`no_identifier`. See [Grey literature playbooks](#grey-literature-playbooks)
and [architecture](architecture.md).

| Key | Default | Meaning |
| --- | --- | --- |
| `email` | `""` | Contact address for Unpaywall, Crossref, NCBI, and polite OpenAlex use. Required when `unpaywall` is in `sources` |
| `manager` | `zotero` | Library adapter. **`zotero` is well tested — use that.** `mendeley` and `endnote` are in the tree and seeking testers. EndNote writes are an import bundle, not an edit of the `.enl` file |
| `[mendeley].client_id` / `client_secret` | `""` | Elsevier OAuth app from [dev.mendeley.com/myapps.html](https://dev.mendeley.com/myapps.html). Or `PAPERFUL_MENDELEY_CLIENT_*`. See [Mendeley](mendeley.md) |
| `[mendeley].redirect_uri` | `http://127.0.0.1:8765/callback` | Must match the app. Host-only (`session login mendeley`) |
| `[endnote].library` | (none) | Path to the `.enl` file. Matching `.Data` (with `sdb/sdb.eni`) must sit beside it. See [EndNote](endnote.md) |
| `out_dir` / `state_dir` | `out` / `state` | PDF tree; manifest, patches, PDF cache, run reports, and write key |
| `[mirror].pdfs` | `all` | PDFs the manager already holds: `all` (copy every one into its item folder; `paperful sync` does the first pass), `lazy` (copy one when a command first needs it; `additional` is the old name), `none` (keep them out of the mirror). `run` always writes PDFs it downloads |
| `[mirror].refresh` | `auto` | `auto`: each command refreshes the mirror from the manager before it reads. `manual`: only `paperful sync` does. `--offline` or `PAPERFUL_OFFLINE=1` skips the manager for one command |
| `[mirror].gone` | `mark` | An item trashed, merged, or deleted in the manager: `mark` keeps its folder in place and marks the record; `trash` also moves the folder under `out/_trash/`. Nothing is deleted either way |
| `[oa_honesty].stamp_fields` | `license`, `oa_status`, `version` | Which Unpaywall / OpenAlex fields are written to `record.json` (`fetch.oa`) and the manifest on successful fetch |
| `[oa_honesty].license_block` | `[]` | Substrings; when a stamped `license` matches, the run records `license_blocked` and does not save the PDF |
| `[remarks].surface` | `note` | Where the readable lines go: where a PDF came from, which duplicate to keep, and why a snowball hit belongs. `note` (child note), `tag` (parent tag), or `off`. The PDF attachment stamp stays the machine token |
| `sources` | `unpaywall` → `openalex` → `arxiv` → `biorxiv` → `europepmc` → `semanticscholar` → `core` → `openaire` → `direct` → `ezproxy` → `htmlpdf` | Default **head** of a run. `[fetch].order = "policy"` (default) still runs these first; `scholar` and `scihub` are **not** included unless you opt in. When `scholar` is in `sources`, policy places it in the **late tail** (one try before `browser_agent` when that lane is on). `order = "list"` honors this array. `core` is skipped until `core_api_key` is set. `openaire` looks up repository copies by DOI |
| `[fetch].order` | `policy` | `policy` late-tails Scholar / SerpApi / Sci-Hub (and academic `htmlpdf`). `list` is the configured `sources` order |
| `[scholar].when` | `auto` | `auto`: interleave with `browser_agent` when that lane is on, else one late Scholar phase. `phase`: Scholar burst then agent. `interleave`: always pair |
| `[serpapi].enabled` | `false` | Paid Google Scholar **link discovery** after local routes. Needs env `SERPAPI_API_KEY`. Never a silent default. See [SerpApi](serpapi.md) |
| `[serpapi].max_calls` | `20` | Paid Scholar searches this run. `0` = no cap. `--serpapi-max` overrides one run |
| `[handoff].scholar` | `true` | Put a Scholar results URL on miss rows and open it in the system browser when there is no direct PDF URL |
| `[request].channels` | `off` | Author-request policy: `off` \| `rg` \| `email` \| `both` \| `rg_then_email_after_days`. **`rg` is handoff-only:** opens an existing ResearchGate publication URL in your system browser so **you** click Request full-text (RG ToS). Paperful never clicks and does not search RG. `email` / delay are recorded for later mail-merge; Paperful does not send mail. Override one `gaps` / `run --handoff` / `reachout` with `--request-rg` / `--no-request-rg`. `--re-request` ignores the `state/author-requests.jsonl` ledger |
| `[request].email_after_days` | `14` | Used when `channels = rg_then_email_after_days` (policy only until a draft verb exists) |
| `[twenty]` / `[searxng]` | off | Optional CRM and metasearch for author pages. Not part of a normal fill. Knobs and what the products are: [Twenty and SearXNG](#twenty-and-searxng) |
| `verify_doi` | `true` | Check library DOIs against Crossref/OpenAlex before fetching; may swap DOI **in memory** for that run. `false` leaves an existing DOI as `doi_verified=unknown` and does not swap |
| `core_api_key` | `""` | CORE API bearer token; empty skips the `core` source |
| `ezproxy_base` | `""` (disabled) | Campus proxy prefix ending in `url=` — see [Campus EZProxy](ezproxy.md) |
| `ezproxy_relogin` | `true` | On a TTY, prompt to re-login before batch 1 (failed probe), at the next batch boundary mid-run, and after the fetch for session-expired items. `--no-ezproxy-relogin` skips |
| `ezproxy_cookies` | `state/ezproxy-cookies.txt` | Compat Netscape dump after `session login ezproxy` |
| `scholar_cookies` | `state/scholar-cookies.txt` | Compat Netscape dump after `session login scholar` |
| `grey_playbooks_builtin` | `true` | Load the packaged ocean/governance example pack |
| `grey_playbooks_dir` | (none) | Directory of extra pack `*.toml` files (merged after builtin, before inline). Relative paths resolve against the config file's folder. Learned recipes go in `learned.toml` inside this directory |
| `[playbooks].promote` | `gated` | `gated` only logs fetch wins. `auto` writes `learned.toml` after `auto_min_hits` matching wins. **Auto may promote flukes** (one-off article URLs, cookie-banner clicks). `run --promote` overrides one run |
| `[playbooks].auto_min_hits` | `2` | How many matching wins `auto` needs before writing a recipe. Manual `playbooks promote` can install a single cluster |
| `[[grey_playbooks]]` | (none) | User rewrite/scrape/synthesize rules; same `name` overrides the pack |
| `attach` | `true` | Attach into Zotero after download (`--no-attach` overrides) |
| `app_name` | `paperful` | Name shown in Zotero's authorisation dialog |

Leave `ezproxy_base` empty (or remove `ezproxy` from `sources`) if you do not
use a library proxy. Google Scholar is off until you add `scholar` to
`sources` (and usually run `session login scholar`). Policy mode then runs it
**late**, not in the middle of campus/grey. Paid [SerpApi](serpapi.md) Scholar
search is off until `[serpapi].enabled` and `SERPAPI_API_KEY`; cap with
`[serpapi].max_calls` / `--serpapi-max`. Sci-Hub is off until
you add `"scihub"` to `sources` or pass `--scihub` — see [Sci-Hub](scihub.md).
Items dated after 2021 are not sent to Sci-Hub; a `--year-from` past that
year drops it from the run list.

Tuning knobs (thresholds, concurrency, User-Agent, OpenAlex snapshot hosting)
live under [Advanced](#advanced).

## Run configs (profiles)

A **profile** stores one SCOPE plus the fetch/write flags you would otherwise
repeat on the command line. It is not a grey-lit playbook and not a
[pack](commands.md). Full recipes: [Workflows](workflows.md).

| Term | Meaning |
| --- | --- |
| Profile / run config | Named SCOPE + policy (`collections`, years, types, `try_all`, …) |
| `paperful all` | `gaps` → `run` → `lint` → `fix-metadata` → `summarize` |
| `--preset oa` | Open-access sources only (the default list without `ezproxy`). CLI flag or `preset` on a profile. `config.minimal.toml` is this list |
| `--preset eoi` | OA + EZProxy; no Scholar, no Sci-Hub. Same names as the default `sources` list today |
| Playbook | Grey-lit URL → PDF rule |
| Pack | Witness of one executed sequence under `state/packs/` |
| Snowball profile | `kind = "snowball"`. `run` and `all` refuse it. Use `paperful snowball run --profile` or `paperful snowball profile save` |

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
| `steps` | `--steps` (comma-separated). Optional extras: `snapshot`, `dedupe`, `synthesize`, `ocr` |
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
| `scrape` | Prefer matching hrefs on that host’s HTML landing | ISA `/documents/`, RFMO `/meetings/` |
| `synthesize` | Extra/title (or skip-host URL + Extra) → PDF URL | UN document symbol → undocs |

The packaged file
[`paperful/data/grey_playbooks_ocean.toml`](https://github.com/glen-w/Paperful/blob/main/paperful/data/grey_playbooks_ocean.toml)
is an **ocean/governance example pack** — grey-lit packs **UNGA/undocs ·
BBNJ/DOALOS · ISA**, plus FAO, RFMO, IUCN/DOSI, and IDDRI/Pew — on by default
via `grey_playbooks_builtin = true`. IEA/IRENA and OECD/WHO/UNEP/UNDP are
optional copies in
[`paperful/data/grey_playbooks_examples/`](https://github.com/glen-w/Paperful/tree/main/paperful/data/grey_playbooks_examples).
Copy those files into `grey_playbooks_dir`, or point that setting at the
examples folder. That folder does not contain the ocean builtin, so it will
not replace the shipped pack by name. Optionally set
`grey_playbooks_dir = "packs"` to load every `*.toml` in that directory (same
schema). Merge order: builtin → dir packs → inline `[[grey_playbooks]]`
(same `name` replaces earlier entries). Host ownership in the shipped files:
`un.org`, `highseasalliance.org`, and `iisd.org` belong to
`bbnj-doalos-prepcom`; `fao.org` belongs to `fao`; `iea.org` belongs to the
energy example. These rules turn a library item’s URL into a PDF. A matching
host does not mean Paperful indexes that organisation. Provenance stays
`grey:<playbook-name>`.
`paperful playbooks promote` adds `learned.toml` in that directory from local
fetch wins. Those recipes are not in the package. `[playbooks].promote = "auto"`
writes them during `run` and may promote a fluke; the default is `gated`.
PMC / arXiv / HAL stay as core OA rewrites, not playbooks. See
[architecture § Grey literature](architecture.md#grey-literature) for hosts
and symbol patterns. If you use the optional Docker image, put packs next to
config under `/data` (see [Docker](docker.md)).

```toml
grey_playbooks_builtin = true
grey_playbooks_dir = "packs"

# [playbooks]
# promote = "gated"       # gated | auto — auto may promote a fluke
# auto_min_hits = 2

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
lane and `recover`). Batch recover: `recover --from-last-run` reads
`state/last-run.json` (`--from-last-run-mode`, `--limit`). Setup walkthrough,
model advice, Docker networking, and troubleshooting: [LLM](llm.md).

| Table / key | Default | Role |
| --- | --- | --- |
| `[llm].enabled` | `false` | Master gate |
| `[llm].provider` | `ollama` | `ollama` or `litellm` |
| `[llm].model` | `qwen2.5:7b` | Model id |
| `[llm].base_url` | `http://127.0.0.1:11434` | Ollama API |
| `[llm].api_base` | `""` | OpenAI-compatible base when `provider = litellm` |
| `[fix_metadata].llm_title` | `false` | Grounded title proposals in `fix-metadata` |
| `[lint].llm_pdf_match` | `false` | `pdf_identity_mismatch` finding; `summarize` refuses flagged items unless `--force` |
| `[summarize].dest` | `both` | `disk` (`state/summaries/`), `zotero` (child note), or `both`. `--to` overrides |
| `[summarize].order` | `library` | Summarize queue order before `--limit`: `library` (manager order), `newest`, or `oldest`. `--order` overrides. Undated items stay last under `newest` / `oldest`. Type stays a filter (`-T`) |
| `[synthesize].dest` | `both` | `disk` (`state/reports/`), `zotero` (standalone note in the collection), or `both` |
| `[browser_agent].during_run` | `true` | When `[llm].enabled` and the extra is installed, `run` appends `browser_agent`. Policy order tries Scholar once immediately before it. Override per run with `--browser-agent` / `--no-browser-agent` |
| `[gaps].handoff` | `list` | Default for `gaps --handoff` when the flag is omitted: `list`, `tabs`, `walk`, or `watch`. `run` only handoffs when you pass `--handoff` |
| `[gaps].downloads_dir` | `~/Downloads` | Newest `*.pdf` pickup for `--handoff walk` (empty → home Downloads) |
| `[inbox].dir` | `""` | PDF drop folder for `--handoff watch` / `paperful inbox` (empty = off). Not snowball’s watch `inbox.jsonl`. `inbox watch` / `drain` match by PDF DOI across the whole library by default; pass `-C` to narrow |
| `[inbox].watch_after_handoff` | `true` | After `--handoff tabs` (or `watch`), keep polling `[inbox].dir` when `dir` is set (handoff session stays collection-scoped + FIFO) |
| `[inbox].poll_seconds` | `2.0` | Poll interval while watching |
| `[inbox].settle_seconds` | `1.5` | Require stable file size before ingest |
| `[inbox].idle_seconds` | `0` | Stop after this many idle seconds (`0` = until Ctrl+C); `--idle` on `inbox watch` overrides |
| `[inbox].match` | `doi_only` | `doi_only` \| `doi+title` \| `doi+title+ocr` \| `full` (title + OCR + LLM when thin) |
| `[inbox].quarantine_after_s` | `0` | Seconds to keep an unmatched PDF in the drop folder before `unmatched/` (`0` = immediately) |
| `[inbox].ocr_for_match` | `false` | Transient OCR for matching only; does not rewrite the drop file |
| `[inbox].llm_match` | `off` | `off` \| `when_thin` \| `always`. Needs `[llm].enabled`. Below confidence → no auto-attach |
| `[inbox].llm_match_min_confidence` | `0.75` | LLM `match: true` below this does not auto-attach |
| `[inbox].llm_auto_attach_min` | `0.92` | High bar for auto-attach; otherwise a gated proposal |
| `[inbox].create` | `attach_only` | `attach_only` \| `create_gated` (proposals) \| `create_auto` (unique DOI, or a unique ISBN / report number / title+year+host) |
| `[htmlpdf].academic` | `off` | `off` \| `gated` \| `auto`. DOI journal items. `gated` proposes; `auto` attaches a page snapshot after landing checks. `--htmlpdf` overrides one `run` |
| `[htmlpdf].upgrade` | `false` | When true, `run` retries items whose only PDF is an HTML snapshot. `--upgrade-snapshot` / `--no-upgrade-snapshot` override |
| `[htmlpdf].keep_snapshot` | `false` | Leave the HTML print in place when a native PDF attaches. `--keep-snapshot` on `run` |
| `[inbox].title_resolve` | `false` | Opt-in Crossref/OpenAlex title search when local title+year is thin (not silent create) |
| `[inbox].manager_metadata_s` | `0` | Wait after attach so a manager recognizer can run (`0` when the backend has none) |
| `[ingest].default_tags` | `()` | Tags on `ingest-dois --apply` and inbox-created parents |
| `[snowball].default_tags` | `()` | Extra tags on snowball `--gate auto` / `apply` creates, with `--tag` and `from-<seed-slug>` |
| `[snowball].dedupe_after` | `off` | After create: `off`, `classify` (`state/dedupe-packs/`), or `apply` (merge high-DOI extras) |
| `[snowball].author_site_preflight` | `false` | Co-author graph + proposed `state/author-packs/`. Promote before `author_site` fetch. Corpus frequency without a snowball run is `paperful authors -C … --apply` |
| `[authorwatch]` | — | Not parsed. Caps are `authorwatch run --max-authors` / `--per-author-limit`. `doctor` ambers lists with people and no ORCID/OpenAlex id. No social scrape |
| `[searxng].base_url` | `""` | SearXNG JSON endpoint for author-site remainder discovery, or `SEARXNG_BASE_URL`. Never a default `run` source. [Twenty and SearXNG](#twenty-and-searxng) |
| `[ingest].dedupe_scope` | `library` | `library` or `collection` when skipping `exists` |
| `[ocr].languages` | `eng` | Tesseract languages for `paperful ocr` (`eng+fra` or `eng fra`) |
| `[rag].enabled` | `false` | Master switch for `paperful rag` and `paperful ask`. Needs `paperful[rag]`. See [rag.md](rag.md) |
| `[rag].auto_ingest` | `false` | Index new PDFs after `run`, `attach`, `inbox`, `snapshot`, `ocr --apply` and `snowball` |
| `[rag].ocr` | `auto` | `auto` runs OCRmyPDF on scans during ingest and rewrites them under `out_dir`; `off` leaves them alone. PDFs with a text layer are never OCR'd |
| `[rag].parser` | `light` | `light` (`pdftotext` / `pypdf`) or `docling` (needs `paperful[rag-docling]`) |
| `[rag].embed_provider` | `ollama` | `ollama` or `litellm` |
| `[rag].embed_model` | `nomic-embed-text` | Embedding model. `bge-m3` for multilingual libraries. Each model keeps its own index under `state/rag/` |
| `[rag].embed_base_url` / `embed_api_base` | `""` | Ollama root / LiteLLM base URL for embeddings; empty uses `[llm].base_url` / `[llm].api_base` |
| `[rag].embed_batch_size` | `32` | Passages per embedding request |
| `[rag].chunk_chars` / `chunk_overlap` | `2048` / `256` | Passage size and overlap in characters. Changing them re-indexes on the next ingest |
| `[rag].top_k` | `10` | Passages sent to the chat model per question (`-k` overrides) |
| `[rag].max_context_chars` | `24000` | Cap on excerpt text in the prompt |
| `[rag].hybrid` | `true` | Blend vector and full-text search; falls back to vector only |
| `[rag].abstracts` | `true` | Index the abstract when an item has no readable PDF |
| `[rag].model` | `""` | Chat model for `ask`; empty uses `[llm].model` |
| `[rag].focus` | `default` | Prompt preset for `ask` / batch: `default`, `questions`, `gaps`, `methods`, `answered` |
| `[rag].prompt` | `""` | Custom system prompt file; when set, overrides `focus` |
| `[rag].dest` | `disk` | Batch ask note destination: `disk`, `zotero`, or `both` (Zotero needs `--apply` + one `-C`) |
| `[rag].extract_questions_llm` | `false` | Default for `rag questions --llm` grounded extract lane |

Timeouts, context budgets, prompt templates, tags, attachment hygiene, and
browser-agent step caps: [Advanced](#advanced).

API keys stay in the environment (never in `config.toml`).

## Advanced

Power-user knobs. Defaults are fine for a first library; change these when a
run misbehaves or you host infrastructure yourself.

### Fetch tuning

| Key | Default | Meaning |
| --- | --- | --- |
| `doi_suspect_score` | `0.70` | Title similarity below this marks a library DOI as suspect (eligible for in-memory swap). API failure is `unknown` and **keeps** the original DOI |
| `crossref_min_score` | `0.90` | Title-similarity threshold for accepting a title→DOI match (Crossref, then OpenAlex, then Semantic Scholar) |
| `concurrency_oa` | `4` | Parallel workers for open-access sources (Scholar, EZProxy, htmlpdf, SerpApi, and Sci-Hub are serial) |
| `min_pdf_bytes` | `10000` | Smaller downloads are rejected as error pages |
| `gate_short_pdfs` | `true` | One-page density gate: soft-reject sparse stubs; hold denser one-pagers for attach |
| `short_pdf_min_words` | `200` | Below this word count, a one-page PDF is treated as sparse (not a paper) |
| `source_routing` | `true` | Skip sources that look inapplicable from item metadata; use `--try-all` (or `false` here) when Zotero fields are untrustworthy |
| `circuit_breaker_threshold` | `3` | Captcha or block-page failures before a source pauses. A 429 does not count. After the pause, one item is tried again |
| `user_agent` | Chrome-like string | HTTP `User-Agent` for source and download requests |
| `scihub_mirrors` | built-in list | Hostnames tried in order when Sci-Hub is opted in |
| `delay_scihub_s` | `[3, 8]` | Random pause (seconds) before each Sci-Hub / EZProxy / htmlpdf page fetch |
| `mirror_failures_before_skip` | `3` | Network failures before a Sci-Hub mirror is skipped for the run |

### LLM and attachment fine print

| Table / key | Default | Role |
| --- | --- | --- |
| `[llm].allow_remote` | `false` | Allow non-loopback Ollama (e.g. `host.docker.internal` from the image) |
| `[llm].timeout_s` | `120` | Per-completion timeout |
| `[llm].max_num_ctx` | `32768` | Cap on the Ollama context window for `summarize` and `synthesize`. The model tag must support it |
| `[lint].llm_pdf_match_min_confidence` | `0.6` | A `match: true` below this confidence is still flagged |
| `[inbox].model` / `[inbox].provider` | `""` | Per-function LLM override for inbox match; empty uses `[llm]` |
| `[summarize].prompt_template` | `default` | Or path to a custom prompt file (relative to the config file); its SHA is stamped in the note footer |
| `[summarize].max_context_chars` | `24000` | Budget for PDF text sent to the model (head + headings + tail) |
| `[summarize].tag` | `paperful-summary` | Zotero child-note tag; re-runs update the note carrying it |
| `[synthesize].prompt_template` | `default` | Report prompt, or a path relative to the config file |
| `[synthesize].max_context_chars` | `24000` | Budget for summary text in one model call (room left for the prompt) |
| `[synthesize].tag` | `paperful-report` | Base tag on the collection note. A second tag `tag:<slug>` makes re-runs update |
| `[synthesize].timeout_s` | `max([llm].timeout_s, 300)` | Per-completion timeout for the report |
| `[browser_agent].max_steps` / `max_wall_s` | `20` / `300` | Step and wall-clock caps for `recover` (agent stops early once a valid PDF lands) |
| `[browser_agent].model` | (`[llm].model`) | Larger tool-capable model for browsing only; `doctor` warns under ~10B; see [browser-agent-models.md](browser-agent-models.md) |
| `[browser_agent].fallback_model` | `""` | One retry with this tag before final `not_found` (skipped after captcha / bot wall). LiteLLM ids (`provider/model`) need `llm.allow_remote` when `llm.provider` is Ollama |
| `[browser_agent].use_vision` | `false` | Send page screenshots to the model; requires a vision-capable tag (`qwen2.5vl`, etc.) |
| `[ocr].timeout_s` | `600` | Seconds allowed per PDF |
| `[attachments].fix_broken` | `false` | With `attachments --apply`, refill a ghost or broken link from `out/` when the MD5 matches |
| `[attachments].merge_files` | `false` | With `--apply`, trash extra PDF children on the same parent that share an MD5 |
| `[attachments].rename` | `false` | With `--apply`, rename files under `out/` to the mirror stem |
| `[attachments].link` | `false` | With `--apply`, stored-to-linked under `out/` (personal Zotero library only) |

### Twenty and SearXNG

Off unless you set them. [Twenty](https://twenty.com) is an open-source CRM
([docs](https://docs.twenty.com/)). [SearXNG](https://docs.searxng.org/) is a
metasearch engine, the maintained fork of SearX; public instances are listed
at [searx.space](https://searx.space/). How Paperful uses them, including
which public instances can answer, is
[snowball Advanced](snowball.md#twenty-and-searxng).

| Key | Default | Meaning |
| --- | --- | --- |
| `[twenty].enabled` | `false` | Talk to a Twenty workspace. Needs env `TWENTY_API_KEY` and `[twenty].base_url` (or `TWENTY_BASE_URL`). `twenty lookup` does not write the CRM (`--apply` caches contacts and a proposed pack). `twenty sync --apply` creates or enriches People. `reachout` can read the cache. No mail |
| `[twenty].lookup_on_preflight` | `false` | When Twenty is ready, add CRM websites to a snowball `--author-site-preflight` proposed pack. Does not call `sync` |
| `[twenty].fetch_listing_max` | `20` | Live People website lookups per run after the contact cache, for the late `author_site` lane |
| `[twenty].writeback_listings` | `false` | With `--twenty-writeback` on `run` or snowball preflight, append a SearXNG or author-site personal page onto a unique Person. Does not create People |
| `[twenty].retry_max` | `8` | Retries after HTTP 429 or 5xx (`Retry-After`, else backoff from `retry_base_seconds`) |
| `[twenty].retry_base_seconds` | `1` | Backoff base when the response has no `Retry-After` |
| `[twenty].sync_note_title` | `Paperful` | Title of the note stamped on create and enrich |
| `[twenty].provenance_keyword` | `paperful` | Keyword added beside the collection slug |
| `[searxng].base_url` | `""` | Instance root, or `SEARXNG_BASE_URL`. Paperful calls `GET /search?format=json`. A public host works only when that instance enables JSON; otherwise run your own ([install](https://docs.searxng.org/admin/installation.html)) |

### OpenAlex API limits and snapshot store

Snowball and large fills talk to the live [OpenAlex](https://openalex.org/) API
by default. A small crawl often needs no key; a free
[`OPENALEX_API_KEY`](https://openalex.org/settings/api) (environment only)
raises the daily allowance. Full limits, resume behaviour, and Semantic Scholar
keys: [snowball Advanced](snowball.md#advanced).

If you outgrow the API (heavy snowballs, shared VPN IP, institutional mirror),
you can download the [OpenAlex parquet
snapshot](https://help.openalex.org/access/snapshot/) yourself — locally or on
a shared host — and point Paperful at it. Paperful does **not** ship the dump;
most installs leave this unset.

When `[openalex_store]` is set, DOI and OpenAlex-id batch reads try the store
first; misses and every other OpenAlex call (cited-by, search, keywords, ORCID)
still use the live API. Rate-limit / budget handling stays API-only.

v1 backend: `ssh_duckdb` — DuckDB runs **on the host that holds the parquet**
(laptop path later; HTTP for campuses later). Paperful SSHs in, runs SQL, and
copies small JSON rows back. Env overrides: `OPENALEX_STORE_SSH_HOST`,
`OPENALEX_STORE_PARQUET_GLOB`.

```toml
# Optional. Most users leave this unset.
# [openalex_store]
# backend = "ssh_duckdb"   # later: local_duckdb | http
# ssh_host = "nuc"
# # ssh_user = "you"
# parquet_glob = "/mnt/files/openalex/data/parquet/**/*.parquet"
# # duckdb_bin = "duckdb"
# # timeout_s = 120
```