# Critique (local manuscript pack)

`paperful critique` writes an evidence-backed Markdown pack for a manuscript
you already have: a mirrored library `--item`, or a `--file` / workbench
upload. Deterministic checkers always run. Optional LLM comments are a
separate **suggested** lane. There is **no score, grade, or accept/reject**.

This is a **pre-submission / reading-aid pack**, not a referee and not Google
Deep Review. It does not upload the manuscript, does not search the web, and
does not call a similarity API. Overlap is against **your library text already
on disk**.

## What it checks

Deterministic checkers always run (no model). **Checked** findings carry a
quote and a page / paragraph / slide loc when one exists. Heuristic AI-prose
tells always run too, as **suggested** `info` — they are not an LLM and not
proof of authorship. Optional `--llm` comments and `--ai-model` are separate
suggested extras.

| Area | Lane | Codes (examples) |
| --- | --- | --- |
| File health | checked | `needs_ocr`, `empty_extract`, `short_pdf`, `skipped_not_pdf` |
| Structure | checked | `missing_section` (methods, results, limitations, related work) |
| Identity / integrity | checked | lint codes; PPS / retraction flags as `pps_*` (same honesty as [screen](screen.md)) |
| Bibliography | checked | `cite_not_in_bibliography`, `bibliography_not_cited`, `cited_not_in_library` |
| Cited-work status (online) | checked | `unresolved_doi`; `cited_retracted` (major); `cited_withdrawn` / `cited_expression_of_concern` (warn); `citation_age`; `self_citation`. Same Crossref/OpenAlex cache as [screen](screen.md) |
| Floats | checked | `caption_not_referenced`, `mention_without_caption` (both directions) |
| Acronyms | checked | `acronym_undefined` (first use before an expansion) |
| Abstract numbers | checked | `abstract_number_missing` (`info`; rounding can false-positive) |
| Reproducibility / ethics | checked | `missing_mention` (limitations, data, funding, ethics, COI, code/data URL) |
| Checklists | checked | `checklist_prisma` / `checklist_consort` — mention only, when the text looks like a review or trial |
| Stats | checked | `statcheck_p_mismatch`, `grim_impossible_mean`, `p_without_n` (stdlib; no scipy/R) |
| Prose | checked | `long_sentence` (≥40 words), `hedge_words`, `passive_voice` (`info` only) |
| Metrics | checked | `readability_summary` (Flesch / Fog / ARI), `lexical_diversity_summary` (TTR / MTLD / hapax). Academic FRE is often 0–30; that is expected, not a defect |
| Heuristic AI-prose tells | suggested | `ai_tell`, `ai_tell_summary`, `ai_tells_abstain` (abstain below 150 words). Formal academic English often looks “smooth” on the same signals |
| Library text overlap | checked | `text_overlap` (distinctive n-grams vs `state/rag/text/`); `overlap_skipped_no_text` |

Offline (`PAPERFUL_OFFLINE=1` or no HTTP client): skip Crossref/OpenAlex rows
and emit `doi_status_skipped_offline` / `identity_skipped_offline`. Overlap
still runs when extracted library text is on disk.

Overlap is **flags to review**, not a plagiarism verdict. Boilerplate that
appears in many library texts is dropped. Do not narrate misconduct.

## CLI

`--item KEY` and `--file PATH` are mutually exclusive.

```bash
uv run paperful critique --item KEY -C "My Collection"
uv run paperful critique --file ./draft.docx -C "My Collection"
uv run paperful critique --file ./draft.pdf --llm
uv run paperful critique --file ./draft.pdf --llm --reviewer reviewer-2
uv run paperful critique --file ./draft.pdf --no-llm   # override [critique].llm
uv run paperful critique --file ./draft.pdf --ai-model
uv run paperful critique --item KEY --llm --force      # LLM despite identity lint
uv run paperful critique --item KEY --apply            # child note; needs --item
uv run paperful critique --item KEY --show-dismissed
uv run paperful critique dismiss FINDING_ID
uv run paperful critique dismiss FINDING_ID --critique-id KEY
```

`--dry-run` prints findings and does not write `state/critiques/`. `--apply`
posts a tagged child note only for a library `--item`. Uploads stay disk-only.
`--llm` / `--no-llm` override `[critique].llm`. `--ai-model` turns the
Binoculars extra on for this run (there is no `--no-ai-model`; set
`[critique].ai_model = false` in config). `-C` is the overlap / “cited but
not in library” corpus. `paperful jobs` lists `critique` under completeness.
Not in `paperful all`.

Packs land in `state/critiques/<id>/<stamp>/` as `pack.json`
(`paperful.critique.pack.v1`) and `pack.md`. `<id>` is the library item key
or `file-<filename-stem>` for `--file` / uploads, so re-running the same draft
keeps dismissals. Dismissals are `state/critiques/<id>/dismissed.jsonl`.
Dismissed rows stay in JSON and are omitted from `pack.md` unless
`--show-dismissed`.

`--format json` prints a `paperful.agent.json.v1` envelope. Run report:
`state/runs/<stamp>-critique.json`.

`pack.json` always has `findings`, `overlap`, `metrics`, and `llm`. `metrics`
holds readability, lexical diversity, and the AI-tell summary (also rendered
as a Metrics section in `pack.md`). `llm` is `null` until `--llm` runs; then
it records `model`, `prompt_sha`, `provider`, optional `narrative`, and a
`reviewers` list (per-id model, skip reason, Markdown note).

## Input formats

| Kind | How | Loc |
| --- | --- | --- |
| `.pdf` | existing PDF text layer | page |
| `.txt` `.md` | UTF-8 | paragraph |
| `.html` `.htm` | BeautifulSoup | paragraph |
| `.docx` `.odt` | zip + XML | paragraph |
| `.rtf` | control-word strip | paragraph |
| `.pptx` | slide XML | slide |
| `.doc` (OLE) | optional `antiword` / `catdoc` / `soffice`; else exit 1 | paragraph |

Unknown binaries are refused. Nothing is sent to Google Docs or Word. If
extract yields too little text, `needs_ocr` / `empty_extract` and checkers that
need body text stop.

Workbench uploads are copied under `state/critiques/uploads/<stamp>-<safe>/`
(same basename hardening as other GUI uploads; 40 MB cap). They never write
`out/` or Zotero unless you later attach the file yourself.

## Optional LLM (`--llm` / `[critique].llm`)

Follows [llm.md](llm.md): local Ollama by default, egress notice, grounded in
the extracted text already on disk plus the checked finding list. No web
search. Comments are `lane=suggested` only. Ungrounded spans are dropped.
`pdf_identity_mismatch` refuses the lane unless `--force`. Never emits scores.

Default is **one** reviewer (`[llm].model` + builtin JSON prompt). Add more
with `[[critique.reviewers]]` — each row has `id`, optional `model` (empty
inherits `[llm].model`), and `prompt` (`default` or a path relative to the
config file). `--reviewer ID` (repeatable) runs a subset. A Markdown prompt
file yields a **Reviewer note** at the head of `pack.md`; the builtin prompt
still returns JSON comments as suggested findings. One LLM call per reviewer.
`prompts/critique-reviewer-2.md` is the shipped Markdown example.

No-LLM users still get the pack (checkers, metrics, heuristic tells).

## Optional AI-text extra (`--ai-model` / `[critique].ai_model`)

Requests a Binoculars-style score
([Hans et al., ICML 2024](https://github.com/ahans30/Binoculars)). Paperful
does not install torch or Binoculars. If the extra is missing, the pack
records `ai_model_unavailable` (suggested / `info`) and still keeps the
heuristic tells. Never treated as proof of authorship.

## Workbench

Advanced **Critique** (not on the default Wanted/Discover/Ask nav): pick an
item from the collection chip **or** drop a file. Same checkers as the CLI.
When `[llm]` is on, checkboxes add suggested comments and (library item only)
force the lane past identity lint. **Write child note** is `--apply` (item
only). **Show dismissed** is `--show-dismissed`. **AI model** is `--ai-model`.
Uploads have no apply / force / dismissed controls.

## Config

See `[critique]` in [config.md](config.md) and `config.example.toml`.
