# Configuration (`config.toml`)

Copy `config.example.toml` to `config.toml` and edit locally; the example file
is tracked in git, personal config is not.

Looked up as `--config PATH`, then `./config.toml`, then the project folder's
`config.toml`, then `~/.config/paperful/config.toml`. Relative paths resolve
against the config file's folder.

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
| `manager` | `zotero` | Library adapter. `mendeley` is reserved (not implemented yet) |
| `out_dir` / `state_dir` | `out` / `state` | PDF tree; manifest, patches, PDF cache, run reports, and write key |
| `sources` | `unpaywall` → `openalex` → `arxiv` → `biorxiv` → `europepmc` → `semanticscholar` → `core` → `scholar` → `direct` → `ezproxy` → `htmlpdf` | Source order; `--sources` overrides per run. `scihub` is **not** included unless you opt in. `core` is skipped until `core_api_key` is set |
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
use a library proxy. Remove `scholar` from `sources` if Google Scholar
CAPTCHAs add noise even after `session login scholar`. Sci-Hub is off until
you add `"scihub"` to `sources` or pass `--scihub` — see [Sci-Hub](scihub.md).
Set `source_routing = false` (or pass `--try-all`) when Zotero fields are
untrustworthy and you want every configured source tried anyway.

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
and symbol patterns. Under Docker, put packs next to config under `/data`
(see [Docker](docker.md)).

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
