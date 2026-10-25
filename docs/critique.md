# Critique (local manuscript pack)

`paperful critique` writes an evidence-backed Markdown pack for a manuscript
you already have: a mirrored library `--item`, or a `--file` / workbench
upload. Deterministic checkers always run. Optional LLM comments are a
separate **suggested** lane. There is **no score, grade, or accept/reject**.

This is a **pre-submission / reading-aid pack**, not a referee and not Google
Deep Review. It does not upload the manuscript, does not search the web, and
does not call a similarity API. Overlap is against **your library text already
on disk**.

## What it checks (no LLM)

Checked findings carry a quote and a page / paragraph / slide loc when one
exists:

| Area | Codes (examples) |
| --- | --- |
| File health | `needs_ocr`, `empty_extract`, `short_pdf`, `skipped_not_pdf` |
| Structure | `missing_section` (methods, results, limitations, related work) |
| Identity / integrity | lint codes; PPS / retraction flags as `pps_*` (same honesty as [screen](screen.md)) |
| Bibliography | `cite_not_in_bibliography`, `bibliography_not_cited`, `cited_not_in_library` |
| Cited-work status (online) | `unresolved_doi`, `cited_retracted`, `citation_age`, `self_citation` |
| Floats | `caption_not_referenced`, `mention_without_caption` (both directions) |
| Acronyms | `acronym_undefined` (first use before an expansion) |
| Abstract numbers | `abstract_number_missing` (`info`; rounding can false-positive) |
| Reproducibility / ethics | `missing_mention` (limitations, data, funding, ethics, COI, code/data URL) |
| Checklists | `checklist_prisma` / `checklist_consort` — mention only, when the text looks like a review or trial |
| Stats | `statcheck_p_mismatch`, `grim_impossible_mean`, `p_without_n` (stdlib; no scipy/R) |
| Prose | `long_sentence`, `hedge_words`, `passive_voice`, `readability` (`info` only) |
| Library text overlap | `text_overlap` (distinctive n-grams vs `state/rag/text/`); `overlap_skipped_no_text` |

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
uv run paperful critique --item KEY --apply          # child note; needs --item
uv run paperful critique dismiss FINDING_ID
uv run paperful critique dismiss FINDING_ID --critique-id KEY
```

`--dry-run` prints findings and does not write `state/critiques/`. `--apply`
posts a tagged child note only for a library `--item`. Uploads stay disk-only.

Packs land in `state/critiques/<id>/<stamp>/` as `pack.json`
(`paperful.critique.pack.v1`) and `pack.md`. `<id>` is the library item key
or `file-<filename-stem>` for `--file` / uploads, so re-running the same draft
keeps dismissals. Dismissals are `state/critiques/<id>/dismissed.jsonl`.
Dismissed rows stay in JSON and are omitted from `pack.md` unless
`--show-dismissed`.

`--format json` prints a `paperful.agent.json.v1` envelope. Run report:
`state/runs/<stamp>-critique.json`.

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
(same basename hardening as other GUI uploads). They never write `out/` or
Zotero unless you later attach the file yourself.

## Optional LLM (`--llm` / `[critique].llm`)

Follows [llm.md](llm.md): local Ollama by default, egress notice, grounded in
the extracted text already on disk plus the checked finding list. No web
search. Comments are `lane=suggested` only. Ungrounded spans are dropped.
`pdf_identity_mismatch` refuses the lane unless `--force`. Never emits scores.

No-LLM users still get the pack.

## Workbench

Advanced **Critique** (not on the default Wanted/Discover/Ask nav): pick an
item from the collection chip **or** drop a file. Same checkers as the CLI.

## Config

See `[critique]` in [config.md](config.md) and `config.example.toml`.
