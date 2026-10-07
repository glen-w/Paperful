# Commands

Snippets below use `uv run` so they stay short. The operator install is
clone plus `docker compose build`, then
`docker compose run --rm paperful …` ([Docker](docker.md)). CI builds the
**light** image and expects `doctor` to exit 2 without Zotero. **heavy**
adds `[llm]` `[rag]` `[browser-agent]` (see
[image mode](docker.md#image-mode-light-vs-heavy)). There is no published
image and no PyPI package. Headed `session login` is host-only
(`uv run paperful session login …`). No campus access: `--preset oa`.
Campus EZProxy: `--preset eoi`. `paperful jobs` lists verbs by job.
The public grow verb is `snowball` (there is no `harvest` command). People you
follow (no hop) are `authorwatch`.

```sh
# environment check (TTY guide for amber/red)
uv run paperful doctor
uv run paperful doctor --probe   # live Scholar / EZProxy session_ok
uv run paperful collections

# fetch to disk only
uv run paperful run --collection interesting --no-attach

# several collections, or the whole library (resumable; Ctrl-C any time, rerun to continue)
uv run paperful run -C BBNJ -C AO
uv run paperful run --library

# attach previously downloaded PDFs
uv run paperful attach
uv run paperful attach --allow-short-pdf          # attach denser one-pagers held by the density gate
uv run paperful attach --allow-pdf-doi-mismatch   # attach files left by --strict-pdf-doi
uv run paperful attach --item ITEMKEY --file ~/Downloads/paper.pdf

# what happened
uv run paperful report
uv run paperful report --last-run      # latest run summary only
uv run paperful report --json          # agent-friendly (manifest + last run)
uv run paperful report --not-found
uv run paperful report --status error

# policy-sensitive runs (OA + campus EZProxy; no Scholar / Sci-Hub)
uv run paperful run -C BBNJ --preset eoi --dry-run

# items with only a linked PDF URL in Zotero are skipped by default
uv run paperful run --library --upgrade-linked
uv run paperful run -C BBNJ --upgrade-snapshot
uv run paperful run -C BBNJ --htmlpdf gated
uv run paperful urls check -C BBNJ

# retry items marked not_found / no_identifier (e.g. after EZProxy login)
uv run paperful run --library --retry-failed
uv run paperful run --collection BBNJ --retry-failed
uv run paperful run --collection BBNJ --try-all   # ignore source_routing when metadata is unreliable

uv run paperful ocr -C BBNJ                 # list image PDFs; does not write
uv run paperful ocr -C BBNJ --apply        # text layer on the out/ PDF
uv run paperful ocr --item ITEMKEY --apply --attach   # also upload beside the scan

# optional library index — off until [rag].enabled; setup in docs/rag.md
# reads the mirror only; never calls the reference manager
uv run paperful rag ingest -C ocean/BBNJ --dry-run   # what would be indexed
uv run paperful rag ingest --library                 # index PDFs + abstracts; OCR for scans only
uv run paperful rag status                           # index vs mirror
uv run paperful rag search "impact assessment thresholds" -C ocean/BBNJ   # passages, no chat model
uv run paperful ask "What does the Agreement require for EIAs?" -C ocean/BBNJ
uv run paperful ask --from-file questions.txt -C ocean/BBNJ
uv run paperful rag questions -C ocean/BBNJ
uv run paperful rag answered --from-extract -C ocean/BBNJ
uv run paperful ask                                  # prompt for several questions

# optional LLM verbs — off until [llm].enabled; setup in docs/llm.md
# recover also auto-fires at the end of `run` when Scholar / EZProxy / htmlpdf fail
uv run paperful recover --item ITEMKEY --dry-run     # browser agent: show start URL only
uv run paperful recover --item ITEMKEY               # needs Python 3.11+ and paperful[browser-agent]
uv run paperful recover --from-last-run --dry-run    # batch keys from state/last-run.json
uv run paperful summarize --item ITEMKEY             # disk HTML + tagged child note (default both)
uv run paperful summarize -C BBNJ --to disk          # HTML only; Zotero tree stays clean
uv run paperful summarize --item ITEMKEY --prompt prompts/mine.md --force
uv run paperful synthesize -C BBNJ --dry-run         # chunk plan from existing summary notes
uv run paperful synthesize -C BBNJ                   # report on disk and a note in the collection

# the on-disk mirror. Every command refreshes it first; sync does only that.
uv run paperful sync --dry-run                  # what changed in the library since last time
uv run paperful sync                            # refresh, and copy library PDFs in (pdfs = all)
uv run paperful sync --full                     # read the whole library again
uv run paperful cache clean                     # list absorbed/stale pdf-cache files
uv run paperful cache clean --apply             # delete them
uv run paperful --offline gaps -C BBNJ          # work from the mirror; do not contact Zotero
uv run paperful snapshot -C BBNJ --dry-run      # re-read one collection in full
uv run paperful snapshot -C BBNJ --pdfs all
uv run paperful restore -C BBNJ                 # dry-run unless --apply
uv run paperful restore -C BBNJ --year-from 2021 --year-to 2026 -T journalArticle
uv run paperful restore -C BBNJ --apply         # create missing items; never overwrite fields

# restrict / reorder sources for one run, or cap the number of items processed
uv run paperful run -C hoops --sources unpaywall,openalex,ezproxy
uv run paperful run --library --limit 50

# year range (inclusive; undated items excluded) — e.g. full run on BBNJ 2023–2026
uv run paperful run -C BBNJ --year-from 2023 --year-to 2026
uv run paperful run -C BBNJ --year-from 2023 --year-to 2026 --dry-run
uv run paperful gaps -C BBNJ --year-from 2023 --year-to 2026
uv run paperful gaps -C BBNJ --list-missing --to missing.tsv
uv run paperful gaps -C BBNJ --list-missing --handoff tabs
uv run paperful gaps -C BBNJ --list-missing --handoff watch
uv run paperful gaps -C BBNJ --list-missing --handoff walk
uv run paperful reachout -C BBNJ --to reachout.csv          # contact only; never fetches
uv run paperful reachout -C BBNJ --non-oa-only --lookup --to reachout.csv
uv run paperful reachout -C BBNJ --request-rg --handoff tabs
uv run paperful inbox watch                   # poll [inbox].dir (whole library)
uv run paperful inbox drain                   # one-shot ingest
uv run paperful inbox watch -C BBNJ           # optional: narrow DOI index
uv run paperful refs gap -C BBNJ              # cited in PDFs, missing from library
uv run paperful refs gap -C BBNJ --format json
uv run paperful ingest-dois --from-file dois.txt -C BBNJ            # dry-run
uv run paperful ingest-dois --from-file dois.txt -C BBNJ --format json
uv run paperful collections add --keys-file keys.txt -C BBNJ        # dry-run
uv run paperful collections add --keys-file keys.txt -C BBNJ --apply
uv run paperful run -C BBNJ --dry-run --format json
uv run paperful inbox drain --format json
uv run paperful ask "What is BBNJ?" --format json
uv run paperful snowball search "BBNJ" --gate dry-run --format json
uv run paperful authorwatch save ocean-people
uv run paperful authorwatch add ocean-people --orcid 0000-0002-1825-0097
uv run paperful authorwatch suggest ocean-people -C ocean/BBNJ --method mix --limit 15
uv run paperful authorwatch accept ocean-people --id sug_abcd --seed-from 2025-01-01
uv run paperful authorwatch run ocean-people --backfill-from 2025-01-01
uv run paperful authorwatch apply ocean-people -C Watch/Ocean          # dry-run
uv run paperful authorwatch delete ocean-people --yes
uv run paperful mcp                           # optional stdio: refs_gap + ask; prefer --format json
uv run paperful serve                         # localhost HTTP (needs uv sync --extra serve)
uv run paperful ingest-dois --from-pack state/refs-gaps/<stamp> -C BBNJ
uv run paperful ingest-dois --from-file dois.txt -C BBNJ --apply --tag bbnj
uv run paperful acronyms -C BBNJ              # harvest ALL CAPS tokens (dry-run)
uv run paperful acronyms -C BBNJ --apply      # write state/acronyms/<scope>.json
uv run paperful authors -C BBNJ               # author/org frequency (dry-run)
uv run paperful authors -C BBNJ --apply       # report + proposed field author pack
uv run paperful inbox proposals list
uv run paperful inbox proposals apply <id>
uv run paperful notes delete -C BBNJ --type summary --except-model qwen2.5:7b
uv run paperful notes delete -C BBNJ --all --apply --yes

# restrict to Zotero item types (repeatable / comma-separated; friendly names ok)
uv run paperful run -C BBNJ -T journalArticle --year-from 2023 --year-to 2026
uv run paperful run -C BBNJ -T "Journal Article" -T report
uv run paperful lint -C BBNJ --type journalArticle,preprint

# the same slice as one command, or saved beside config.toml
#   gaps → run --try-all --retry-failed --upgrade-linked → lint → fix-metadata --apply → summarize --apply
uv run paperful all -C BBNJ -T journalArticle --year-from 2021 --year-to 2026
uv run paperful all -C BBNJ -T journalArticle --year-from 2021 --year-to 2026 --dry-run
uv run paperful profile save bbnj-journal -C BBNJ -T journalArticle --year-from 2021 --year-to 2026 --try-all --apply
uv run paperful all --profile bbnj-journal
uv run paperful profile list
uv run paperful profile show bbnj-journal
# dedupe + browser handoff + summarize template: docs/workflows.md § 4
# Sci-Hub is off by default; opt-in only, at your own risk — see scihub.md

# session (optional)
uv run paperful session login ezproxy   # system Chrome/Edge when present; campus SSO
uv run paperful session login scholar    # same; --engine playwright to force Playwright
uv run paperful session login mendeley  # Elsevier OAuth (host-only localhost redirect)
uv run paperful session status
uv run paperful ezproxy --no-open       # probe the EZProxy session
uv run paperful scholar --no-open       # probe Scholar
uv run paperful mirrors

# interchange (RIS / BibTeX / EndNote XML)
uv run paperful export library.ris --library
uv run paperful import other.bib                 # dry-run
uv run paperful import other.bib --apply

# identifiers vs PDFs (read-only); metadata writes are a separate step
uv run paperful lint --library --json             # progress bar on stderr; stdout is JSON
uv run paperful lint -C BBNJ --strict             # exit 1 if any finding
uv run paperful fix-metadata --library            # dry-run → state/metadata-patches.jsonl
uv run paperful fix-metadata --library --apply    # write DOI/title/date/venue into Zotero 10+
uv run paperful fix-metadata --library --apply --overwrite   # replaces title/date/venue you may have edited; dry-run first

# duplicates, then remaining PDF gaps (review the pack before --apply)
uv run paperful dedupe -C BBNJ --dry-run
uv run paperful dedupe -C BBNJ --apply          # high_doi only; add --apply-medium for title+year
uv run paperful gaps -C BBNJ

# one witness for a sequence (child reports still land in state/runs/)
uv run paperful pack open --label bbnj-journal-2021-2026
uv run paperful gaps -C BBNJ
uv run paperful pack close
uv run paperful pack show
```

| Command | Purpose |
| --- | --- |
| `doctor` | Environment check (Zotero / Mendeley / EndNote, paths, email, sessions, pdftotext, ocrmypdf, Playwright, grey-lit packs, LLM, browser-agent extra). Green / amber / red. TTY guide for remediations (`--guide` / `--no-guide`). `--probe` hits Scholar / EZProxy `session_ok` (vault browser when available) and ambers when cookie files exist but CAS/captcha. `--json` prints `{name, status, code, detail}` and still exits 2 when a check is red (`zotero_down`, `zotero_api_off`, `zotero_bad_host`, `zotero_no_write`, `unpaywall_email`). Empty email is red only when `unpaywall` is in `sources`. LLM disabled stays green. Missing `ocrmypdf` is amber. |
| `run` | Fill PDFs for items already in the library. Default attaches on Zotero 10+ (`--dry-run` does not). `--preset oa` drops EZProxy; `--preset eoi` is OA + EZProxy (`--upgrade-linked`, `--try-all`, `--retry-failed`, `--sources`, `--scihub`, `--browser-agent` / `--no-browser-agent`, `--strict-pdf-doi`, `--year-from` / `--year-to`, `--type` / `-T`, `--limit`, `--serpapi-max`, `--promote gated\|auto`). When `[llm].enabled` and the browser-agent extra is installed, appends `browser_agent` (default `[browser_agent].during_run`; `--no-browser-agent` skips it for one run). Default `[fetch].order = "policy"` runs Scholar (if opted in) **late**: one query immediately before each `browser_agent` call, or one late Scholar phase when the agent is off. `[fetch].order = "list"` keeps `sources` order. Opt-in [SerpApi](serpapi.md) (`[serpapi].enabled`) is a paid Scholar search after those local lanes; `--serpapi-max` caps searches this run (`0` = unlimited). Soft-blocked OA PDF URLs (empty httpx body) retry via the vault browser (SSO hop, citation PDF link, download control) and can hand off with `--handoff list|tabs|walk|watch` (`watch` = tabs then poll `[inbox].dir`). `[handoff].scholar` (default on) opens a Scholar results tab when there is no direct PDF URL. When `ezproxy` is in sources, `run` probes the vault before batch 1. On expiry mid-run, a TTY offers re-login once at the next batch boundary; after the fetch it still pauses (`ezproxy_relogin`, default on; `--no-ezproxy-relogin` skips) to retry only session-expired items. The login browser is closed before the report and before `--handoff` opens tabs. `--promote` overrides `[playbooks].promote` for that process. Never rewrites bibliographic fields. A PDF DOI that differs from the library item still attaches, with `warn:pdf_doi_mismatch` on the Zotero note. `--strict-pdf-doi` saves the file and does not attach; `paperful attach --allow-pdf-doi-mismatch` attaches those rows later. One-page PDFs: sparse stubs soft-reject (keep searching); denser one-pagers hold for `attach --allow-short-pdf` (`gate_short_pdfs` / `short_pdf_min_words`). |
| `recover` | Opt-in **browser-agent** PDF recovery (`--item KEY` repeatable, `--from-last-run`, `--from-last-run-mode browser_agent_miss\|missing\|browser_agent_not_found`, `--limit`, `--dry-run`, `--no-attach`). Also auto-appended on `run` when `[llm].enabled` and other vault browser lanes (Scholar, EZProxy, htmlpdf) fail — or when an OA lane soft-blocked a found PDF URL. Policy mode tries Scholar once immediately before that agent call. Needs Python 3.11+, `paperful[browser-agent]`, and a session vault. Manual report: `state/runs/<stamp>-recover.json`. See [LLM](llm.md#a-recover-browser-agent-pdf-recovery). |
| `lint` | Read-only identifier / PDF-DOI / title-hygiene findings (`--json`, `--strict`, `--year-from` / `--year-to`, `--type` / `-T`, `--limit`). Codes: `missing_doi`, `suspect_doi`, `swappable_doi`, `pmid_no_doi`, `pdf_doi_mismatch`, `title_html`, `title_all_caps`, `title_filename`, `title_unusable`, `no_identifier`, plus `pdf_identity_mismatch` when `[lint].llm_pdf_match` is on. Writes `state/runs/<stamp>-lint.json` (also for `--json`, before a `--strict` exit 1). |
| `acronyms` | Collection-scoped harvest of all-caps tokens from mixed-case titles, abstracts, and venues (`--min-count`, `--apply`). Frequency and shape only; no model. Dry-run prints the list. `--apply` writes `state/acronyms/<scope>.json` (`paperful.acronyms.v1`) and keeps a hand-edited `extra` list. `fix-metadata` and parent create keep those tokens uppercase when recasing ALL CAPS titles. |
| `authors` | Collection-scoped creator frequency (`--min-count`, `--max-authors`, `--apply`, `--format json`). People by name fingerprint; corporate `name`-only creators as orgs. Dry-run prints tables. `--apply` writes `state/reports/<scope>-authors.json` (`paperful.authors_report.v1`) and merges top people into `state/author-packs/<slug>.proposed.toml` (preserve existing listing URLs). Then `snowball packs promote`. Orgs stay report-only. Optional CRM: [Twenty and SearXNG](snowball.md#twenty-and-searxng). |
| `fix-metadata` | Propose patches on disk; `--apply` writes them to the library (`--overwrite` replaces title, date, or venue even when you edited them — dry-run first; `--year-from` / `--year-to`, `--type` / `-T`, `--limit`). Whitelist: `doi`, `title`, `date`, `publicationTitle`. HTML title cleanup, ALL CAPS → Title Case (also applied when creating parents and when adopting a DOI work title; harvested acronyms in `state/acronyms/` stay uppercase), a blank or citation-shaped title replaced from the DOI work, and verified PDF-DOI adoption included; filename titles stay lint-only unless `[fix_metadata].llm_title` proposes a grounded title (`source = "llm_title"`). Dry-run and `--apply` both write `state/runs/<stamp>-fix-metadata.json` (`patches_applied` only after `--apply`). |
| `ocr` | Text layer for scanned PDFs (`ocrmypdf`). Dry-run unless `--apply`. Rewrites the PDF under `out/` (exports a manager-only file there first). `--attach` uploads that file as a new attachment and does not trash the scan. Languages: `[ocr].languages` (default `eng`). Not in the default `all` chain; add it with `--steps`. |
| `rag ingest` | Build the library index from the mirror (`out/`): PDF text, or the abstract when there is no readable PDF. Scans get OCR first (`[rag].ocr = "auto"` rewrites them under `out/`, without `--apply`); PDFs with a text layer do not. `--item` / `-C` (a folder path under `out/`) / `--library`, `--year-from` / `--year-to`, `--type`, `--limit`, `--dry-run`, `--no-ocr`, `--retry-failed`, `--force`. Incremental and resumable. Never calls the reference manager. Needs `[rag].enabled` and `paperful[rag]`. See [rag.md](rag.md). |
| `rag status` | What the index holds and how far it is behind the mirror (items indexed, scans waiting for OCR, failures, PDFs held only by the reference manager). `--json`. Works with `[rag].enabled = false`. |
| `rag search` | Indexed passages closest to a query, with paper and pages. No chat model. `-k`, `--item` / `-C`, `--year-from` / `--year-to`, `--type`, `--json`. |
| `rag questions` | Extract research questions from indexed papers (rules; optional `--llm` / `[rag].extract_questions_llm`). `--item` / `-C` / `--library`, year/type/`--limit`, `--dry-run`. Writes `state/rag/questions/<key>.json`. Also on Advanced Index. See [rag.md](rag.md). |
| `rag answered` | Ask whether the corpus already answers operator or extracted questions (`--from-file` / `--from-extract`, `--after-item`, scope, `--force`). Writes `state/rq-answered/<stamp>/` (`pack.md`). Also on Advanced Index. See [rag.md](rag.md). |
| `ask` | Answer a question from the index, streamed, with cited sources and pages (`-k`, `--item` / `-C`, `--year-from` / `--year-to`, `--type`, `--focus`, `--prompt FILE`, `--from-file` batch → `state/ask-batch/`, `--force`, `--apply`/`--to`, `--no-stream`, `--show-context`, `--thread`, `--format json`). JSON implies `--no-stream` and needs a question (no TTY loop). Prompted `ask` (no question) keeps a thread under `state/rag/threads/`; follow-ups rewrite a standalone retrieval query. One-shot CLI still answers independently unless `--thread`. Writes `state/runs/<stamp>-ask.json`. Needs `[rag].enabled`, `[llm].enabled` and a built index. Advanced Index covers the same verbs except TTY / `--show-context` / run profiles — [gui.md](gui.md), [rag.md](rag.md#workbench-advanced-index). |
| `summarize` | Grounded LLM summary from the PDF already on disk (`--item` / `-C` / `--library`, `--year-from` / `--year-to`, `--type` / `-T`, `--order newest\|oldest\|library`, `--limit`, `--prompt FILE`, `--force`, `--to disk, zotero, or both`). Default writes `state/summaries/<key>.html` and one child note tagged `[summarize].tag`. Without `--force`, existing summaries for the chosen dest are skipped when the footer matches the current model (resume-safe; a model change rewrites). `--order` (default `[summarize].order`, or `library`) sorts before `--limit` so a slow model can finish recent or old work first; undated items stay last under `newest` / `oldest`. `--to disk` skips Zotero. `--apply` requires the note and conflicts with `--to disk`. Writes `state/runs/<stamp>-summarize.json`. See [LLM](llm.md#d-summarize-grounded-summary-note). |
| `synthesize` | Literature review from existing summary notes (`--item` / `-C` / `--library`, same year/type/`--limit` flags, `--prompt`, `--to`, `--dry-run`, `--force`, `--report-collection`). Writes `state/reports/<slug>.html` and, unless `--to disk`, a standalone note in each `-C` collection. See [LLM](llm.md#e-synthesize-summary-of-summaries). |
| `dedupe` | Duplicate pack on disk (`high_doi`, then `title+year`). Classify-only until `--apply`, which writes a spare-copy line, then merges DOI extras onto the keeper and trashes the emptied parent. If that line cannot be written, the merge does not run. Title+year needs `--apply-medium`. Held when same-DOI titles diverge. Same year/type scope flags as `run`. See [dedupe](dedupe.md). |
| `attachments` | Compare PDF attachments to `out/`. Report only unless you pass `--fix-broken`, `--merge-files`, `--rename`, or `--link` together with `--apply`. Repairs use a matching file already under `out/`. `--link` is Zotero personal libraries only. Mendeley can upload and delete cloud files; it cannot link. EndNote is report-only (missing paths, duplicate PDFs, filename drift) and does not edit the library. Same MD5 on two parents is reported and left to `dedupe`. Not in `paperful all`. |
| `versions` | Preprint and published paper as one work. Dry-run writes `state/version-packs/` (`paperful.version_pack.v1`). `--apply` puts the published citation and PDF on the older parent, keeps the preprint id and PDF, and trashes a sibling only after that PDF is attached. Title-only pairs are listed and not applied. |
| `gaps` | Counts: no stored PDF, linked PDF URL only, missing DOI. `--list-missing` prints key/title/DOI/URL/hint (`openable_url` / `doi_only` / `hard_miss` / `author_request`); `--to` writes `.tsv` or `.md`. `--handoff list|tabs|walk|watch` opens your browser, walks Downloads into `attach --item --file`, or (watch) polls `[inbox].dir`. `--request-rg` opens existing ResearchGate publication URLs so you click Request full-text (never automated). Year/type scope flags apply. Writes `state/runs/<stamp>-gaps.json`. |
| `reachout` | Contact mode for items with no stored PDF. **Never fetches.** Console table plus `--to` `.csv`/`.tsv`/`.md` (title, author, email, source, DOI, RG URL). Email from item `extra`/`mailto`/abstract first; Twenty `state/author-contacts/` when `[twenty].enabled`; `--lookup` searches People for remaining names. `--non-oa-only` keeps `paywalled` / `no_oa` / `license_blocked`. `--handoff tabs\|walk` opens **existing** ResearchGate publication URLs only (you click Request). Does not send mail. |
| `twenty lookup` | Opt-in [Twenty](snowball.md#twenty-and-searxng) People match for `-C` authors. Dry-run unless `--apply` (proposed author-pack websites + `state/author-contacts/` only). Needs `[twenty].enabled`, `base_url`, env `TWENTY_API_KEY`. Does not write the CRM. |
| `twenty sync` | Create or enrich People from `-C` authors. Dry-run unless `--apply`. Unique miss → create (first + last, collection keyword, Paperful note). Unique match → fill blank homepage/email and append extras; never replaces a primary. Ambiguous names and corporate creators are skipped. `--limit`, `--yes` when many creates. `--format json`. [Twenty and SearXNG](snowball.md#twenty-and-searxng). |
| `authorwatch` | People you follow → their papers (`save` / `add` / `remove` / `resolve` / `suggest` / `accept` / `delete` / `import` / `run` / `apply` / `show` / `briefing`). `suggest -C` ranks corpus/OpenAlex candidates; `accept --id` (+ optional `--seed-from`) adds to the list. ORCID or unique OpenAlex id required to poll. First `run` is a cursor baseline (proposes 0, no library open) unless `--backfill-from`. `apply -C` creates metadata parents (dry-run unless `--apply`; `--apply` needs write API). Does not need `[snowball] enabled`. Social follows: saved HTML/CSV via `import --file` (no live scrape). Distinct from `snowball watch` and `inbox watch`. [Author watch](authorwatch.md). |
| `inbox` | PDF drop-folder sidecar (`watch` / `drain` / `proposals`). Needs `[inbox].dir`. Default match is DOI-only against missing-PDF items (whole library unless `-C`). Optional `[inbox].match` ladder: hold before quarantine, OCR-for-match, title+year, `llm_when_thin`. `[inbox].create` is `attach_only` (default), `create_gated` (proposals), or high-bar `create_auto` (unique DOI only). Created parents are tagged `inbox-created`, `inbox:<dirname>`, `[ingest].default_tags`, and `--tag`. `--format json` on `drain` and `proposals list|apply|reject` is `paperful.agent.json.v1`. Handoff `watch` still uses FIFO. Writes `state/runs/<stamp>-inbox.json`. Not snowball’s `inbox.jsonl`. |
| `notes delete` | Trash **Paperful-owned** notes only (`paperful.note.v1` or known tags). Dry-run unless `--apply`. `--type summary\|review\|attach\|duplicate\|linked\|snowball\|briefing` is the **note** kind (not Zotero `-T` / `--item-type` on parents). `--model` / `--except-model`, `--all` (every owned note in `-C` / `--library` / `--item`). `--apply --all` confirms on a TTY unless `--yes`. Never parents. `--format json`. |
| `refs gap` | Works **cited inside** collection PDFs that are **not** in the library fingerprint. Always dry-run. Writes `state/refs-gaps/<stamp>/` (`paperful.refs_gap.pack.v1` plus `dois.txt`). `--format json` prints `paperful.agent.json.v1`. Then `ingest-dois --from-file` / `--from-pack`. Distinct from `gaps` (items already in scope missing a PDF). |
| `ingest-dois` | DOI list → metadata parents in `-C`. Dry-run unless `--apply`. Reports created / exists / unresolved / **held**. `--format json`. `--tag` plus `[ingest].default_tags` and `from-<file-stem>`. Does not fetch PDFs (`run` after). |
| `collections` | `list` (or bare `collections`) — collection tree with “No PDF” counts. `add --keys-file` — file **existing** item keys into `-C` (membership only; dry-run unless `--apply`; added / already-in / not-found). `--format json`. Complements `ingest-dois` (create parents). Zotero / Mendeley; EndNote refuses `--apply`. Not an MCP tool. |
| `mcp` | Optional stdio MCP over the same JSON channel. Tools: `refs_gap` (never writes parents) and `ask` (index read-only). Prefer `paperful … --format json` from a shell. `collections add` is CLI-only and is not exposed. |
| `serve` | Localhost HTTP (`127.0.0.1:8765`). Needs `paperful[serve]` (`uv sync --extra serve`). JSON capability API (health, doctor, collections, last-run, dry-run `refs-gap` / `ask`) plus Jinja workbench (Discover, Wanted, …; Advanced Index Ask/batch/`rag questions`/`rag answered` / Briefs / Repair / Mirror / Settings). Library writes only from Preview then Apply / Grab (review tokens). TTY, Sci-Hub, and `collections add` stay CLI. Every Compose image includes `serve` so the `gui` profile can run; **heavy** also has RAG/Ask extras for Index. See [gui.md](gui.md). |
| `all` | `gaps` → `run --try-all --retry-failed --upgrade-linked` → `lint` → `fix-metadata --apply` → `summarize --apply`. Stops on the first failure. `--dry-run` skips `summarize` and does not apply metadata. `--browser-agent` / `--no-browser-agent` pass through to the `run` step. `--profile` / `-f` load a saved run config. Opens a pack when none is open. `--format json` prints one envelope for the whole sequence (nested substeps stay quiet on stdout). See [Workflows](workflows.md). |
| `profile` | `list` / `show` / `save` — named run configs beside `config.toml` (`profiles/<name>.toml` or `[profiles.*]`). `show` prints the merge `all` would use. `save` does not edit `config.toml`. |
| `snowball` | Grow a library from one or more keywords, one or more DOIs, one or more ORCIDs, or a collection (`search`, `hybrid`, `doi`, `orcid`, `collection`, `apply`, `run --profile`, `resume`, `profile save`, `watch save` / `run` / `show` / `briefing` / `digest`, `briefing --run-id`, `digest --run-id`). `search` / `hybrid` take several keyword terms (AND by default; `--or`
matches any; a trailing `*` expands client-side); `doi` and `orcid` take
several positionals or `--seeds-file`; `profile save` repeats `--query` / `--doi` / `--orcid` (and `--or` for keywords). `hybrid` is keyword hits then one hop. `--direction` is `refs`, `cites`, `both`, `keywords`, `similar`, or a combination such as `refs+similar`. `similar` is one ranked hop (shared references, then Semantic Scholar recommendations). `--direction keywords` expands OpenAlex keywords (`--keyword-limit` 1–5, `--keyword-hop-limit` a positive integer; `all` is refused). `--cites-query` limits references and cited-by to an OpenAlex search (title, abstract, or full text). Seeds with no keywords are reported and skipped on that side. `--tag` (repeatable) plus `[snowball].default_tags` and `from-<seed-slug>` are applied on `--gate auto` / `apply` creates. Dry-run unless a writing gate is set. `approve-each` is for short lists. `fetch_pdfs` is `off`, `fast`, or `full` on the new keys only. A saved queue with no deferred OpenAlex work resumes into create and PDF fetch. `--format json` on crawl (`search` / `hybrid` / `doi` / `orcid` / `collection`), `run`, `resume`, and `apply` prints one `paperful.agent.json.v1` object (paths + summary; progress on stderr). Mixed `apply` writes exit **3**. `watch` re-runs a profile, remembers seen works, and proposes new arrivals on disk (never creates items; Paperful does not schedule it). `briefing` writes thin markdown from a queue or watch inbox (no silent creates; `--apply` plus `-C` files a collection note tagged `paperful:frontier-briefing`). `digest` writes `digest.md`: overlap-ranked new rows, a suggested `-C`, and queue / apply / resume paths. `watch run --digest` writes the watch digest after a successful run. Paperful does not schedule that. `run` and `all` refuse `kind = snowball` profiles. [How a hop is cut](snowball.md#how-a-hop-is-cut). |
| `pack` | `open` / `close` / `show` — group the run reports from one operator sequence into `state/packs/<id>.json` (`paperful.pack.v1`). `show` does not open the library. `PAPERFUL_PACK=off` keeps a command out of the open pack. |
| `report` | Manifest summary + latest run report (`--last-run`, `--json`, `--not-found`, `--status`) |
| `attach` | Attach already-downloaded PDFs into the configured manager, or ingest a hand download with `--item KEY --file PATH`. `--allow-pdf-doi-mismatch` and `--allow-short-pdf` unlock holds from `--strict-pdf-doi` and the one-page density gate |
| `sync` | Bring `out/` up to date with the library: rewrite the folders of items that changed since the last refresh, mark items that left, copy in PDFs the library holds (`--pdfs all\|lazy\|none`, default from `[mirror].pdfs`). `--full` reads the whole library. `--dry-run` reads and counts, writes nothing. Refuses to mark most of the mirror as gone (a different library) unless `--accept-gone`. Every other command runs the same refresh before it reads, without the whole-library PDF pass. |
| `snapshot` | Re-read a collection (or `--library`) in full and rewrite its item folders (`record.json`, optional PDF, notes) plus index, collection tree, and ledger pointers. `--pdfs all\|lazy\|none`. `--dry-run` counts without writing. Year/type scope flags apply. Needs the manager running. |
| `restore` | Recreate missing library items from those folders. Dry-run unless `--apply`. `--apply` creates missing items, attaches a local PDF when the live item has none, and adds missing notes. Does not overwrite bibliographic fields. Year/type scope flags apply. |
| `import` | Load RIS, BibTeX, or EndNote XML into the configured manager. Dry-run unless `--apply`. |
| `export` | Write the scoped library to RIS, BibTeX, or EndNote XML (`--pdfs` copies files for XML). |
| `session` | Local browser vault: `login scholar\|ezproxy\|mendeley` (`--engine` is for the browser slots), `status`, `export` |
| `playbooks` | `propose` / `promote` — draft and install learned PDF recipes from `state/fetch-wins.jsonl` (vault clicks/rewrites and browser-agent `click:` / `rewrite` wins, including optional `steps` on agent rows) into `grey_playbooks_dir/learned.toml`. Default `[playbooks].promote` is `gated`. `auto` may promote flukes. `probe --corpus FILE` fetches each target and passes only when the first candidate is a PDF of at least `--min-bytes` (default 10KB). Exit 1 on any miss. `--save` writes a replayable JSON snapshot. The shipped public corpus is `tests/fixtures/grey/corpus.toml` |
| `ezproxy` | Wrapper: headed login (or Netscape fallback) / `--no-open` probe |
| `scholar` | Wrapper: headed login (or Netscape fallback) / `--no-open` probe |
| `mirrors` | Ping configured Sci-Hub mirrors |
| `version` | Print the package version |

Collections can be given as a path (`BBNJ/not undermine`), a unique name, or
a key. Subcollections are always included. Items in several selected
collections are written once and hard-linked into the other folders.

## Scope filters

After collection / `--library` selection, these optional filters shrink the
item list further (applied before `--limit`). They appear in the Scope line
(e.g. `BBNJ, years 2023–2026, types journalArticle`).

Most verbs need `-C` or `--library` (or a profile that sets one). `inbox
watch` / `drain` are the exception: with no scope they default to the whole
library so a shared drop folder is not tied to one collection.

`--profile NAME` loads that slice from a run config so you do not repeat
`-C` / years / `-T` on every verb. `-f` / `--run-config FILE` overlays it.
Flags you pass still win. See [Workflows](workflows.md) and
[Configuration](config.md#run-configs-profiles).

| Flag | Effect |
| --- | --- |
| `--year-from YEAR` | Keep items dated this year or later (inclusive). |
| `--year-to YEAR` | Keep items dated this year or earlier (inclusive). |
| `--type` / `-T TYPE` | Keep only these Zotero item types (repeatable or comma-separated). |

**Year.** Open ends are fine (`--year-from 2023` alone). Items with no
parsed publication year are excluded whenever either bound is set.
`--year-from` must be ≤ `--year-to`.

**Type.** Accepts Zotero camelCase ids (`journalArticle`), spaced labels
(`Journal Article`), and hyphen/underscore forms (`journal-article`). Case
insensitive. Unknown tokens exit 1. Common scholarly types:

`journalArticle`, `preprint`, `conferencePaper`, `report`, `book`,
`bookSection`, `thesis`, `manuscript`, `document`, `webpage`,
`newspaperArticle`, `magazineArticle`, `blogPost`, `dataset`, `standard`,
`patent`, `presentation`, …

Attachments, notes, and annotations are never in scope (Zotero skips them
already). Full list: Zotero’s item-types reference; Paperful rejects anything
not in that set.

```sh
uv run paperful run -C BBNJ --year-from 2023 --year-to 2026 -T journalArticle
uv run paperful gaps -C BBNJ -T "Journal Article" -T report
uv run paperful lint -C BBNJ --type journalArticle,preprint --strict
```

Same flags on `run`, `lint`, `fix-metadata`, `dedupe`, `gaps`, `ocr`, `summarize`,
`synthesize`, `snapshot`, and `restore`.

## Doctor

`paperful doctor` prints one line per check. Default session rows are
file-presence only. Pass `--probe` to hit Scholar / EZProxy `session_ok`
(vault Chromium when available); cookie files that still bounce to CAS or a
captcha become **amber**.

| Colour | Meaning |
| --- | --- |
| **green** | Ready |
| **amber** | Degraded but you can continue (empty `email`, missing or expired EZProxy/Scholar session, no `pdftotext`, no `ocrmypdf`, Playwright/Chromium not ready, Zotero without write API, LLM enabled but daemon/model/extra not ready, small model for the browser agent) |
| **red** | Fatal if the check is `Zotero :23119`, `Mendeley API`, `EndNote library`, `out_dir`, or `state_dir` |

Unpaywall needs a real `email`. Missing or expired sessions: `paperful session login ezproxy` or `scholar` (system Chrome/Edge when present). Missing `pdftotext`: Poppler; `pypdf` is the fallback. Missing `ocrmypdf`: `brew install ocrmypdf tesseract-lang` or `apt install ocrmypdf tesseract-ocr-eng` (the Compose image ships English). Playwright is core; Chromium installs on first `session login`. An amber Write API means Zotero 7–9: fetch still works, but `attach`, `fix-metadata --apply`, and `dedupe --apply` do not.

On a host TTY, amber/red checks open an interactive **Guide**: each step prints
what to do, waits for Enter, then re-runs that check. Inside Docker, doctor
prints the same fix steps once (no Enter wait — Compose owns Ctrl-C / stdin on
`compose up`). Opt in to the interactive walk with
`docker compose run --rm paperful doctor --guide`. Session logins still need a
headed browser on the host. Force or skip with `--guide` / `--no-guide`.
Bare `docker compose run --rm paperful` is `doctor`.

## Dry-run

`paperful run … --dry-run` talks to Zotero only (no PDF fetches). The table’s
**Would-hit** column is the source lane for that item, in policy order (Scholar
late unless `[fetch].order = "list"`). `--try-all`
(or `source_routing = false`) lists every configured source.

`paperful dedupe` is classify-only unless you pass `--apply`: it writes
`state/dedupe-packs/` and does not merge or write the spare-copy line. Do not
pass `--dry-run` and `--apply` together.

## Exits

`--format json` prints one `paperful.agent.json.v1` object on **stdout**. Progress
bars and logs go to **stderr**. Early environment failures may print a human
ladder on stdout and skip the envelope — treat unparseable stdout plus the
process exit code as the result.

| Code | When |
| --- | --- |
| 0 | Success (including empty dry-run). `not_found` / paywalled misses on `run` are not failures. `ingest-dois` **held** and **unresolved**, and `collections add` **not-found** / **already-in**, are findings, not exit 3. |
| 1 | User error (unknown collection, bad preset, unknown `--phase`, `--dry-run` together with `--apply`, `--year-from` > `--year-to`, unknown `--type`, `--strict` lint findings, unknown `--item` key, LLM not enabled/misconfigured for `recover` / `summarize` / `synthesize`, `recover` on Python < 3.11, note write refused, `--to disk` together with `--apply` or `--report-collection`, `synthesize` still over budget after 3 reduce passes, `pack open` while one is open, `pack close` when none is open, unknown `--pdfs`). Also: a batch where every attempted write failed. |
| 2 | Environment: library unreachable on `sync`, `snapshot`, `restore`, `attachments`, `attach`, or any `--apply` (including `authorwatch apply --apply`); or unreachable on any library command when there is no mirror under `out/` yet. With a mirror, read commands (`collections`, `gaps`, `lint`, `export`, dry-runs, `summarize --to disk`, `run` without attach) carry on from it and say how old it is. `authorwatch save` / `add` / `run` without `--backfill-from` do not open the library; `authorwatch suggest` and `run` with `--backfill-from` / `--seed-from` do (OpenAlex budget spent is also exit 2). Prints **Next steps** (Zotero local API, or Mendeley login, or EndNote `.enl`; then `paperful doctor`) |
| 3 | Partial **write** batch: some rows succeeded and some failed. `run` counts **attached vs attach_failed** (not `not_found`). Also `inbox drain` (attached vs errors), `fix-metadata --apply`, `dedupe --apply`, `snowball apply`, `authorwatch apply --apply`, `summarize`, `ocr --apply`, `notes delete --apply`, `ingest-dois --apply` (created vs create errors), `collections add --apply` (added vs errors), and other batch verbs that emit `paperful.agent.json.v1`. The envelope has `"partial": true`. Dry-run mixed findings stay **0**. |

TTY-only (a GUI or agent must not claim these): `session login`, `doctor --guide`, mid-run EZProxy re-login, and `notes delete --apply --all` confirm unless `--yes`.

## Run summary

After a real `run`, a **Run summary** table lists PDFs downloaded, attached,
why a PDF was not saved (captcha, cloudflare, not found, and the other blocks),
publisher prices the browser agent saw on those misses,
deferred/skipped, sources checked, and typed errors. `paperful report` reprints
it. JSON: `paperful report --json` — field list in [architecture](architecture.md#run-report-v1).

## Output

- `out/<collection>/<Author - Year - Title -- KEY>/record.json` — restore
  record (`paperful.item.v1`). Identity, full creators, abstract, tags, Extra,
  type-specific fields, collection membership, attachment rows, fetch
  provenance, and note filenames. **Required keys frozen; extras may be added.** `run` writes this when
  it saves a PDF. A refresh writes one for every item, including items with
  no PDF, and rewrites it after each change in the library.
- `out/<collection>/<Author - Year - Title -- KEY>/<file>.pdf` — the PDF, when
  there is one. `run` always writes downloads here. With `[mirror].pdfs = "all"`
  (the default) `sync` also copies in a PDF already stored in Zotero. `lazy`
  copies one the first time a command needs it. `none` keeps them out and does
  not delete PDFs already on disk.
- `out/<collection>/…/notes/` — child-note HTML. A `state/summaries/<key>.html`
  file is copied as `paperful-summary.html`.
- `out/_index.jsonl` — one line per item key (`dirs`, `has_pdf`, `md5`, child keys).
- `out/_sync.json` — library version the mirror was last refreshed to.
- `out/_collections.json` — collection tree.
- `out/_history.json` — pointers at the append-only ledgers under `state/`
  (manifest, patches, dedupe, runs). Sessions, cookies, and the local API key
  are not copied.
- `state/manifest.jsonl` — one line per item attempt; the latest line per item
  key wins. Statuses: `ok` (on disk), `attached` (on disk + in Zotero),
  `not_found`, `no_identifier`, `captcha`, `error`, `attach_failed`,
  `retryable`. `ok` /
  `attached` are never retried; `not_found` / `no_identifier` only with
  `--retry-failed`; the rest are retried on every run. Extra fields:
  `library_doi` (DOI as stored in the manager), `doi` (DOI used for this
  attempt), `doi_verified` (`ok` / `suspect` / `swapped` / `unknown` /
  `missing`), `pdf_doi` (extracted from the file on disk after a successful
  download), `reason` (for example `strict_pdf_doi` or `short_pdf` when attach
  is held — batch `attach` skips those unless `--allow-pdf-doi-mismatch` or
  `--allow-short-pdf`).
- `state/metadata-patches.jsonl` — append-only audit log of proposed bibliographic
  patches from `fix-metadata` (dry-run and `--apply` both append here first).
  One patch per item key per invocation; inspect the file for review — it is not
  a selective re-apply queue.
- `state/dedupe-packs/` — `dedupe` review packs (`.json` and `.md`). Not applied
  until `--apply`.
- `state/dedupe-applied.jsonl` — one line per parent merged by
  `dedupe --apply` (children and better fields land on the keeper first).
- `state/cites/` — cached OpenAlex reference lists for the snowball
  "Cited by N papers in this collection." line. Keyed by the set of DOIs
  already in the target collection.
- `state/version-packs/` — `versions` review packs (`.json` and `.md`, `paperful.version_pack.v1`).
- `state/versions-applied.jsonl` — one line per work updated by
  `versions --apply`.
- `state/refs-gaps/<stamp>/` — `refs gap` pack (`pack.json`, `pack.md`, `dois.txt`). Always dry-run.
- `state/ingest/<stamp>/` — `ingest-dois` summary JSON. Created only classifies unless `--apply`.
- `state/collections-add/<stamp>/` — `collections add` summary JSON (`paperful.collections_add.v1`). Dry-run unless `--apply`.
- `state/authorwatch/<name>/` — people lists (`paperful.authorwatch.v1`), `people.jsonl`, `suggestions.jsonl`, inbox, seen, applied. Cursor baseline does not open the library; `suggest` does. See [authorwatch.md](authorwatch.md).
- `state/inbox/proposals/` — gated inbox create/attach proposals (`paperful.inbox.proposal.v1`).
- `state/pdf-cache/` — PDFs exported from the manager so lint can read text
  when `[mirror].pdfs = "none"`. `paperful sync` moves matching files into
  item folders; `paperful cache clean` removes absorbed or stale leftovers
  (dry-run unless `--apply`).
  on disk (`pdftotext`, then `pypdf`).
- `state/last-run.json` — latest auditable `run` or `recover` report (summary + per-item
  outcomes). Other commands do not replace it. Historical copies land in
  `state/runs/<timestamp>-<command>.json` (`run`, `recover`, `gaps`, `reachout`, `lint`,
  `fix-metadata` for dry-run and `--apply`, `summarize`, `synthesize`).
- `state/packs/<id>.json` — parent witness for one `pack open` … `pack close`
  sequence (`paperful.pack.v1`). Steps point at filenames under `state/runs/`.
  `state/packs/current` is the open id; `PAPERFUL_PACK=off` skips appending.
- `state/summaries/` — HTML summaries from `summarize` when dest includes disk.
- `state/reports/` — `synthesize` HTML report plus a JSON sidecar of source hashes; `authors --apply` writes `<scope>-authors.json` (`paperful.authors_report.v1`).
- `state/author-packs/` — field author packs (`*.proposed.toml` until `snowball packs promote`). Seeded by `authors --apply`, snowball `--author-site-preflight`, or `twenty lookup --apply`.
- `state/author-contacts/` — Twenty People cache from `twenty lookup --apply`, `twenty sync --apply`, or `reachout --lookup` (websites / emails; no mail).
- `state/author-requests.jsonl` — ResearchGate handoff ledger (`handoff_opened`). `--re-request` ignores it.
- `state/sessions/` — Chromium profile (`chromium/`) plus `meta.json` (no
  passwords). Gitignored; `chmod 700`. Netscape dumps also land here and as
  `ezproxy-cookies.txt` / `scholar-cookies.txt` for httpx.
- `state/fetch-wins.jsonl` — one line per vault or browser-agent PDF (host
  and path only; optional `steps` trace on agent successes). Gitignored with
  the rest of `state/`.
- `state/playbooks-proposed.toml` — draft from `paperful playbooks propose`.
  Installed only by `playbooks promote` into `grey_playbooks_dir/learned.toml`.
- `state/zotero-local-api-key.json` — the Zotero write key if you chose
  "Always Allow".
- `state/mendeley-oauth.json` — Mendeley access/refresh tokens after
  `session login mendeley` (mode `0600`).
- `state/endnote-import/<stamp>/` — staged XML+PDF bundle for EndNote
  File → Import. Paperful never edits the `.enl` database.
