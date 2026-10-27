# Critique (local manuscript pack)

`paperful critique` writes an evidence-backed Markdown pack for a manuscript
you already have: a mirrored library `--item`, or a `--file` / workbench
upload. Deterministic checkers always run. Optional review lanes are a
separate **suggested** extra and can run together. There is **no score, grade,
or accept/reject**.

This is a **pre-submission / reading-aid pack**, not a referee and not Google
Deep Review. It does not upload the manuscript and does not call a similarity
API. Overlap is against **your library text already on disk**. Suggested
review lanes default to that extract (and optional local RAG). The
`context-web` lane is the only critique path that may query OpenAlex /
SearXNG, and only when you opt in.

## What it checks

Deterministic checkers always run (no model). **Checked** findings carry a
quote and a page / paragraph / slide loc when one exists. Heuristic AI-prose
tells always run too, as **suggested** `info` — they are not an LLM and not
proof of authorship. Optional review lanes (`--lane reviewers` / `marg` /
`adversary` / `context` / `context-web`; `--llm` and `--advanced` are aliases) and
`--ai-model` are separate suggested extras. Optional `--vale` house-style
alerts are **checked**. Optional `--forensics` runs sibling CLI `paperguard`
and records **suggested** findings. Paperful does not vendor MARG, ScholarPeer,
or PaperGuard detectors; docs credit the patterns.

| Area | Lane | Codes (examples) |
| --- | --- | --- |
| File health | checked | `needs_ocr`, `empty_extract`, `short_pdf`, `skipped_not_pdf` |
| Structure | checked | `missing_section` (methods, results, limitations, related work) |
| Identity / integrity | checked | lint codes; PPS / retraction flags as `pps_*` (same honesty as [screen](screen.md)) |
| Bibliography | checked | `cite_not_in_bibliography`, `bibliography_not_cited`, `cited_not_in_library` |
| Cited-work status (online) | checked | `unresolved_doi`; `cited_retracted` (major); `cited_withdrawn` / `cited_expression_of_concern` (warn); `citation_age`; `self_citation`. Same Crossref/OpenAlex cache as [screen](screen.md) |
| Floats | checked | `caption_not_referenced`, `mention_without_caption` (both directions) |
| Acronyms | checked | `acronym_undefined` (first use before an expansion); house glossary `acronym_expansion_mismatch` / `acronym_phrase_mismatch` when `state/glossary/` has entries |
| Abstract numbers | checked | `abstract_number_missing` (`info`; rounding can false-positive) |
| Reproducibility / ethics | checked | `missing_mention` (limitations, data, funding, ethics, COI, code/data URL) |
| Checklists | checked | `checklist_prisma` / `checklist_consort` — mention only, when the text looks like a review or trial |
| Stats | checked | `statcheck_p_mismatch`, `grim_impossible_mean`, `p_without_n` (stdlib; no scipy/R). Full statcheck, GRIMMER/SPRITE, TIVA, and table digit tests: optional `--forensics` subprocess to [PaperGuard](https://github.com/exergyleizhou-ux/PaperGuard) |
| Prose | checked | `long_sentence` (≥40 words), `hedge_words`, `passive_voice` (`info` only). Skips direct quotations (quoted spans and `>` block lines) |
| Metrics | checked | `readability_summary` (Flesch / Fog / ARI), `lexical_diversity_summary` (TTR / MTLD / hapax). Academic FRE is often 0–30; that is expected, not a defect |
| Heuristic AI-prose tells | suggested | `ai_tell`, `ai_tell_summary`, `ai_tells_abstain` (abstain below 150 words). Formal academic English often looks “smooth” on the same signals |
| Library text overlap | checked | `text_overlap` (distinctive n-grams vs `state/rag/text/`); `overlap_skipped_no_text` |
| House style (optional Vale) | checked | `vale_*` from your `.vale.ini` rules; alerts inside direct quotations are dropped; `vale_unavailable` / `vale_no_config` / `vale_failed` / `vale_truncated` when the extra is on |
| Forensics (optional PaperGuard) | suggested | `paperguard_*` from `paperguard scan` (`--forensics`); skip codes `paperguard_unavailable` / `paperguard_no_input` / `paperguard_failed` / `paperguard_truncated`; not a misconduct verdict |

Offline (`PAPERFUL_OFFLINE=1` or no HTTP client): skip Crossref/OpenAlex rows and
emit `doi_status_skipped_offline` / `identity_skipped_offline`. PPS fingerprints
still run when `state/pps/fingerprints/` or `[screen].fingerprint_dir` has CSV/JSON
(see [screen](screen.md)); warm the cache once with `paperful screen --refresh`.
When online, tortured-phrase and other PPS fingerprints run on the **critique
extract** for both `--item` and `--file` (same `[screen].detectors` and
`tortured_min` as screen).

Overlap is **flags to review**, not a plagiarism verdict. Boilerplate that
appears in many library texts is dropped. Do not narrate misconduct.

## CLI

`--item KEY` and `--file PATH` are mutually exclusive. `--file` also accepts
`csv` / `xlsx` / `xls` so PaperGuard can scan a table without a manuscript
wrapper (`xlsx`/`xls` have no text extract; checkers see an empty document).

```bash
uv run paperful critique --item KEY -C "My Collection"
uv run paperful critique --file ./draft.docx -C "My Collection"
uv run paperful critique --file ./draft.pdf --lane reviewers
uv run paperful critique --file ./draft.pdf --llm
uv run paperful critique --file ./draft.pdf --llm --reviewer reviewer-2
uv run paperful critique --file ./draft.pdf --lane marg
uv run paperful critique --file ./draft.pdf --lane adversary
uv run paperful critique --file ./draft.pdf --lane reviewers --lane marg --grobid
uv run paperful critique --file ./draft.pdf --lane context
uv run paperful critique --file ./draft.pdf --lane context-web
uv run paperful critique --file ./draft.pdf --no-llm --no-advanced
uv run paperful critique --file ./draft.pdf --no-llm   # drop reviewers (alias)
uv run paperful critique --file ./draft.pdf --ai-model
uv run paperful critique --file ./draft.pdf --vale
uv run paperful critique --file ./draft.pdf --forensics
uv run paperful critique --item KEY --llm --force      # LLM despite identity lint
uv run paperful critique --item KEY --apply            # child note; needs --item
uv run paperful critique --item KEY --show-dismissed
uv run paperful critique dismiss FINDING_ID
uv run paperful critique dismiss FINDING_ID --critique-id KEY
```

`--dry-run` prints findings and does not write `state/critiques/`. `--apply`
posts a tagged child note only for a library `--item`. Uploads stay disk-only.
`--lane NAME` (repeatable: `reviewers`, `marg`, `adversary`, `context`, `context-web`)
selects suggested review lanes for this run. `[critique].lanes` is the config
list; when it is empty, `[critique].llm` / `[critique].advanced` still map to
`reviewers` / `marg`. `--llm` / `--no-llm` and `--advanced` / `--no-advanced`
are aliases that add or remove those two ids. `--grobid` / `--no-grobid`
override `[grobid].enabled` and only affect MARG-S PDF chunking (`--grobid`
still attempts the sidecar even when `[grobid].enabled` is false, same as
`extract-sections`). `--ai-model` turns the
Binoculars extra on for this run (there is no `--no-ai-model`; set
`[critique].ai_model = false` in config). `--vale` turns the Vale house-style
pass on for this run (there is no `--no-vale`; set `[critique].vale = false`).
`--forensics` turns the PaperGuard subprocess on for this run (there is no
`--no-forensics`; set `[critique].forensics = false`).
`-C` is the overlap / “cited but not in library” corpus. `paperful jobs` lists
`critique` under completeness.
Not in `paperful all`.

Packs land in `state/critiques/<id>/<stamp>/` as `pack.json`
(`paperful.critique.pack.v1`) and `pack.md`. `<id>` is the library item key
or `file-<filename-stem>` for `--file` / uploads, so re-running the same draft
keeps dismissals. Dismissals are `state/critiques/<id>/dismissed.jsonl`.
Dismissed rows stay in JSON and are omitted from `pack.md` unless
`--show-dismissed`.

Human CLI prints elapsed phase lines (extract, checkers, cited-work DOI
counts, overlap, each reviewer, extras) so a long run is not silent until
the pack. `--format json` keeps stdout as the envelope only; a spinner still
goes to stderr on a TTY. Run report: `state/runs/<stamp>-critique.json`.

`pack.json` always has `findings`, `overlap`, `metrics`, and `llm`. `metrics`
holds readability, lexical diversity, and the AI-tell summary (also rendered
as a Metrics section in `pack.md`). `pack.md` leads with an **Incomplete lanes**
banner when a requested review lane skipped, then reviewer notes, counts,
metrics, **Critical path** (checked findings that are not hygiene, majors
first), **Suggested**, and **Hygiene** (Vale, acronyms, prose metrics, AI-tell
codes). JSON `findings` is unsplit. `llm` is `null` until a review lane runs;
then it records `lanes` (ordered ids), a deprecated `mode` string
(`default` / `marg` / `both` / `adversary` / `context` / `context-web`) derived from that
set, `model`, `prompt_sha`, `provider`, optional `narrative`, a `reviewers`
list (per-id model, skip reason, Markdown note, including `marg-experiments`
/ `marg-clarity` / `marg-impact`, `adversary`, and `context` / `context-web` when those
lanes ran), optional `marg` stats (`parser` is `grobid` or `extract`;
`rounds`, `calls`, `skipped`; optional `grobid_skipped`), optional `adversary`
stats (`calls`, `skipped`), and optional
`context` stats (`search_enabled`, `backends`, `rag_skipped`,
`search_skipped`). `ai_model` and `vale` appear only when those extras ran
(skip reason or alert counts).

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

## Review lanes (`--lane` / `[critique].lanes`)

Suggested extras. Checkers always run. Lanes are **additive** and may be
combined. Identity mismatch refuses **all** review lanes unless `--force`.
Each lane needs `[llm].enabled`; otherwise the pack records
`skipped: llm_disabled` and still writes. Paperful does not vendor
[allenai/marg-reviewer](https://github.com/allenai/marg-reviewer) or ScholarPeer
/ [open-scholar-peer](https://github.com/amirkiarafiei/open-scholar-peer).

| Id | Alias | What it does |
| --- | --- | --- |
| `reviewers` | `--llm` | Independent `[[critique.reviewers]]` JSON/Markdown calls |
| `marg` | `--advanced` | MARG-S-style multi-agent (experiments / clarity / impact) |
| `adversary` | — | Validity red-team (alternative explanations, validity, degrees of freedom, falsifiers, missing negatives) |
| `context` | — | ScholarPeer-inspired: summary, library historian, baseline scout, Q&A |
| `context-web` | — | Same pipeline; literature/baseline may query OpenAlex / optional SearXNG |

```toml
[critique]
lanes = ["reviewers", "marg"]
```

When `lanes` is non-empty, `[critique].llm` and `[critique].advanced` are
ignored. When it is empty, those bools still map to `reviewers` / `marg`.
`--no-llm --no-advanced` with no `--lane` is checkers only.
`--reviewer ID` still subsets only `[[critique.reviewers]]`. Orthogonal extras
(`--vale`, `--ai-model`, `--grobid`, `--forensics`) are not lanes.

## Optional reviewers (`--lane reviewers` / `--llm`)

Follows [llm.md](llm.md): local Ollama by default, egress notice, grounded in
the extracted text already on disk plus the checked finding list. No web
search. Comments are `lane=suggested` only. Ungrounded spans are dropped.
Direct quotations are not rewritten; comments on quoted spans are dropped.
Never emits scores.

Default is **one** reviewer (`[llm].model` + builtin JSON prompt). Add more
with `[[critique.reviewers]]` — each row has `id`, optional `model` (empty
inherits `[llm].model`), and `prompt` (`default` or a path relative to the
config file). `--reviewer ID` (repeatable) runs a subset. A Markdown prompt
file yields a **Reviewer note** at the head of `pack.md`; the builtin prompt
still returns JSON comments as suggested findings. One LLM call per reviewer.
`prompts/critique-reviewer-2.md` is the shipped Markdown example.
`prompts/critique-reviewer-5.md` is the OpenReviewer-style general review
(local `llama-openreviewer-8b`) with scores and Accept/Reject stripped — a
pre-submission stress-test, not a grade. The theatrical `critique-reviewer-4.md`
persona was removed; if you copied it into paperful-data, drop that
`[[critique.reviewers]]` row (use `--lane adversary` instead).

No-LLM users still get the pack (checkers, metrics, heuristic tells).

## Optional adversary (`--lane adversary`)

Additive suggested lane. One JSON turn over the extract and checked findings:
alternative explanations, selection / construct / external validity, researcher
degrees of freedom, what would falsify the core claim, and missing negative or
comparison cases. Same grounding and no-score rules as reviewers. Cap:
`adversary_max_comments` (default 12). Timeout is `[llm].timeout_s`.

## Optional MARG-S (`--lane marg` / `--advanced`)

Additive suggested lane inspired by MARG-S
([D’Arcy et al., arXiv:2401.04259](https://arxiv.org/abs/2401.04259);
[allenai/marg-reviewer](https://github.com/allenai/marg-reviewer), Apache-2.0).
Paperful does not vendor that repo. Python orchestrates JSON turns with a
leader, chunk workers, and one expert per aspect group (experiments, clarity,
impact), then a refine pass. Same grounding and no-score rules as reviewers.

MARG PDF chunks prefer the optional GROBID TEI cache (`process_pdf` /
`tei_to_markdown_pages`, same as [extract-sections](grobid.md)). Scans,
non-PDFs, and sidecar errors fall back to `ExtractedDoc` and record
`marg.parser = "extract"` plus `grobid_skipped`. Checkers never require GROBID.
Remote GROBID prints the same yellow egress notice as extract-sections
(PDF bytes leave this machine). Caps: `advanced_max_rounds`,
`advanced_max_workers`, `advanced_max_comments`, `advanced_refine`,
`advanced_timeout_s` (`0` → `max([llm].timeout_s, 600)`). A duplicated
leader broadcast is a hard stop (`skipped: loop`). A wall-clock overrun
records `skipped: timeout` rather than hanging a workbench job.

## Optional context (`--lane context` / `--lane context-web`)

Additive suggested lane inspired by ScholarPeer
([Goyal et al., arXiv:2601.22638](https://arxiv.org/abs/2601.22638)).
Paperful does not vendor that framework or community skill packs. The
pipeline is summary → historian → baseline scout → multi-aspect Q&A →
synthesis. Same grounding and no-score rules as reviewers. This is not
ScholarPeer parity and does not emit venue scores.

`context` retrieves only from the local RAG index (collection / library
scope when `-C` / `--library` loaded items). Missing index records
`rag_skipped` and continues on the extract.

`context-web` uses the same pipeline and may query OpenAlex, then optional
SearXNG when `[searxng].base_url` is set. A yellow egress notice prints.
`PAPERFUL_OFFLINE=1` skips those calls and records `search_skipped: offline`.
Venue filters are not hard-coded to ML conferences. Caps:
`context_timeout_s`, `context_max_comments`, `context_max_hits`.

## Optional AI-text extra (`--ai-model` / `[critique].ai_model`)

Requests a Binoculars-style score
([Hans et al., ICML 2024](https://github.com/ahans30/Binoculars)). Paperful
does not install torch or Binoculars. If the extra is missing, the pack
records `ai_model_unavailable` (suggested / `info`) and still keeps the
heuristic tells. Never treated as proof of authorship.

## House glossary (`state/glossary/`)

Canonical acronym expansions live in `state/glossary/<slug>.json`
(`paperful.glossary.v1`), not in the Title Case allowlist from
`paperful acronyms`. Critique reads every JSON file in that directory when
`[critique].glossary` is true (the default). Empty or missing files add no
findings.

```json
{
  "schema": "paperful.glossary.v1",
  "scope": "ocean/BBNJ",
  "entries": [
    {
      "token": "BBNJ",
      "expansion": "Areas Beyond National Jurisdiction",
      "aliases": [
        "Maritime Area beyond national jurisdictions",
        "marine areas beyond national jurisdiction"
      ]
    }
  ]
}
```

`acronym_expansion_mismatch` (`warn`) fires when a parenthetical expansion for
a listed token is close to the canonical form or an alias but not the
canonical text. `acronym_phrase_mismatch` (`info`) slides a window over the
body (stdlib `difflib`, default `[critique].glossary_similarity_min = 0.88`)
and flags near-misses of the long form even without the acronym. Exact
canonical wording is silent. Direct quotations are skipped. Findings suggest
the canonical string; they do not rewrite the manuscript.

`paperful glossary validate` checks the files. `paperful glossary export-vale`
prints (or `--out` writes) a Vale Substitution fragment from **exact**
aliases. Vale cannot fuzzy-match; keep the glossary for similarity, and merge
the export into your `.vale.ini` styles if you also run `--vale`.

Set `[critique].glossary = false` to skip the checker. `[critique].glossary_dir`
is a directory under `state_dir` (default `glossary`).

## Optional Vale (`--vale` / `[critique].vale`)

House-style lint via [Vale](https://vale.sh) on the **already extracted**
manuscript text (not the original `.docx` / PDF markup). Paperful does not
install Vale, does not put it in the Compose image, and does not run
`vale sync`. You install the binary, keep your own `.vale.ini` and styles, and
opt in. `paperful doctor` reports whether `vale` is on PATH (amber if missing;
not fatal).

Set `[critique].vale_config` to that ini (path relative to the paperful
config). If unset, Paperful looks for `.vale.ini` next to the paperful config
file only — not `$HOME` and not Vale’s global config (`--no-global`).
`[critique].vale_min_alert_level` (`suggestion` / `warning` / `error`) and
`vale_timeout_s` (default 60) apply to that subprocess. Missing binary, missing
config, or a Vale crash records `vale_unavailable` / `vale_no_config` /
`vale_failed` (`checked` / `info`) and the rest of the pack still runs. Alerts
map to `vale_<check>` findings (`lane=checked`, `source=vale`). Vale `suggestion`
is paperful `info`; Vale `warning` and `error` are `warn`, never `major`. More
than 100 alerts yields `vale_truncated`. Built-in prose checkers
(`long_sentence`, `hedge_words`, `passive_voice`) still run; overlap with Vale
rules is expected.

## Optional forensics (`--forensics` / `[critique].forensics`)

Subprocess wrapper around sibling [PaperGuard](https://github.com/exergyleizhou-ux/PaperGuard)
(`paperguard scan`). Paperful does not install PaperGuard and does not vendor
its detectors. You put `paperguard` on `PATH` and opt in. `paperful doctor`
reports whether it is on PATH (amber if missing; not fatal). Missing binary,
no scannable file, or a crash records `paperguard_unavailable` /
`paperguard_no_input` / `paperguard_failed` (`suggested` / `info`) and the
rest of the pack still runs.

`--file PATH` scans that file. `--item KEY` scans the resolved PDF plus
`*.csv` / `*.xlsx` / `*.xls` in the same directory. When the item has a DOI
and the run is online, Paperful passes `--doi` for PaperGuard metadata
cross-checks. Default detectors only — no `--ml-check`, `--llm-review`, or
paper-mill graph flags. Hits map to `paperguard_<detector_id>` findings
(`lane=suggested`, `source=paperguard`). PaperGuard NOTE is paperful `info`;
CONCERN is `warn`; SUSPICIOUS and CRITICAL are `major`. PASS rows are dropped.
More than 100 hits yields `paperguard_truncated`. PaperGuard’s `integrity_score`
is **not** copied into the pack. `pack.md` has a **Forensics (PaperGuard)**
section (anomalies to investigate, not a verdict); the same rows also appear
under Suggested. A copy of the raw report is `paperguard.json` next to
`pack.json`. Timeout: `[critique].forensics_timeout_s` (default 300).
The wrapper passes `--lang en` (and `PAPERGUARD_LANG=en`); some detector
summaries may still arrive in PaperGuard’s bundled language.

## Workbench

Advanced **Critique** (not on the default Wanted/Discover/Ask nav): pick an
item from the collection chip **or** drop a file. Same checkers as the CLI.
When `[llm]` is on, review-lane checkboxes (**Reviewers**, **MARG-S
multi-agent**, **Adversary (validity red-team)**, **Context (library)**,
**Context (web)**) can be combined
(pre-checked from `[critique].lanes`, or the llm/advanced shims when `lanes`
is empty). **GROBID sidecar** is for MARG-S chunks only (pre-checked from
`[grobid].enabled`).
Library item form also has force-LLM past identity lint. **Write child note** is `--apply` (item
only). **Show dismissed** is `--show-dismissed`. **AI model** is `--ai-model`.
**Vale** is `--vale`. The Vale checkbox is not pre-checked; `[critique].vale =
true` still runs the pass even if the box is empty. **Forensics (PaperGuard)**
is `--forensics` (same on-switch pattern). Uploads have no apply /
force / dismissed controls.

## Config

See `[critique]` in [config.md](config.md) and `config.example.toml`.
