# Rewrite (apply a critique pack)

`paperful rewrite` takes an existing [`critique`](critique.md) pack and
proposes locatable edits. The Advanced workbench labels this **Suggest
edits** so it is not read as “the AI rewrites my paper.” It is
**apply-from-critique**, not a paper generator. It does not re-run critique,
does not overwrite the source file, and does not write to the reference
manager.

Default area is **style** (hygiene: Vale, glossary/acronyms, prose). Other
areas (`cites`, `structure`, `comments`) are opt-in. Outputs are an edit plan
always, plus optional sidecar text and office files: Word tracked-changes,
OpenDocument (`.odt`), and/or PDF. `--output tracked` follows the source
suffix (Word spine for markdown / PDF / HTML / RTF). `--output odt` and
`--output pdf` can be requested for any source.

Paperful does not vendor [Paper Orchestra](https://github.com/google-research/paper-orchestra),
[ARIES](https://github.com/allenai/aries), or [XtraGPT](https://huggingface.co/collections/Xtra-Computing/xtragpt).
Docs credit the patterns: a worklog, align-then-generate, selected-span prompts.

## CLI

`--pack`, `--item`, and `--file` locate the critique pack. `--file` with
`--pack` is allowed: the pack supplies findings; `--file` is the manuscript
to edit.

```bash
uv run paperful rewrite --pack state/critiques/file-draft/20261027T...
uv run paperful rewrite --file ./draft.docx
uv run paperful rewrite --item KEY
uv run paperful rewrite --file ./draft.docx --area cites --area structure --comments substantive
uv run paperful rewrite --pack PATH --output edits --dry-run
```

- Exit 1 if no pack exists. Never calls `build_critique`.
- `--area` (repeatable): `style`, `cites`, `structure`, `comments`, or `all`.
- `--output` (repeatable): `edits`, `sidecar`, `tracked`, `odt`, `pdf`.
- `--comments`: `off` (default), `substantive`, `all` — reviewer/MARG notes as
  Word comments.
- `--dry-run` prints the plan and writes nothing.
- `--format json` → agent envelope. Phase lines on stderr.
- Not in `paperful all`. `paperful jobs` → completeness.

Packs land in `state/rewrites/<critique-id>/<stamp>/` as `plan.json`
(`paperful.rewrite.plan.v1`), `pack.md`, and `pack.json`
(`paperful.rewrite.pack.v1`). `--output tracked` writes `tracked.docx` /
`tracked.pptx` / `tracked.odt` matching the source (markdown and other
text sources get a Word spine). `--output odt` always writes `tracked.odt`
(native copy when the source is ODT; otherwise a paragraph spine).
`--output pdf` writes `tracked.pdf` (Playwright Chromium print of the
applied text). Library PDFs are read-only; output is always new files.

## Areas

| Id | Default | What it does |
| --- | --- | --- |
| `style` | on | Vale, glossary/acronyms, `long_sentence` / `hedge_words` / `passive_voice`. Glossary `suggested` and obvious Vale swaps are deterministic |
| `cites` | off | Bibliography locators. Cite keys only from the extract/pack. Retracted / withdrawn / EoC cites are comments, never deletes |
| `structure` | off | Missing section headings, float caption/mention, missing ethics/data mentions. No invented results |
| `comments` | off | Suggested findings and reviewer notes as comments on a unique span or heading |

Always skip: dismissed rows, direct quotations, overlap, AI-tells / Binoculars,
PaperGuard, file-health, metrics summaries, identity lint, non-actionable praise.

LLM is required only when a selected area still has findings without a
deterministic replacement. Style-only glossary/Vale substitutions run with
`[llm]` off.

## Config

```toml
[rewrite]
areas = ["style"]                 # style | cites | structure | comments | all
outputs = ["edits", "tracked"]    # edits | sidecar | tracked | odt | pdf
comments = "off"                  # off | substantive | all
max_edits = 80
timeout_s = 0                     # 0 → max([llm].timeout_s, 600)
openxml_audit = false             # optional extra: uv sync --extra openxml (docx/pptx/odt)
openxml_audit_policy = "warn"     # warn | fail

[[rewrite.specialists]]
id = "style"
model = ""                        # empty → [llm].model; may be an XtraGPT Ollama tag
prompt = "default"                # or prompts/rewrite-style.md
```

`[[rewrite.specialists]]` is separate from `[rewrite].areas` (enabled ids)
because TOML cannot use the same key for a string list and an array of tables.

Optional area model: an Ollama tag from `Xtra-Computing/XtraGPT-GGUF`. Default
remains `[llm].model`. ICLR/ReviseQA criteria are ML-shaped; ocean/policy
drafts should not assume them. See [llm.md](llm.md).

## Honesty

- No new numbers, experiments, or cite keys unless they already appear in the
  extract, the finding, or the pack.
- Unflagged text is unchanged.
- Body edits must not mention Paperful, the critique pack, or “the reviewer”.
- Weak alignment → skip or a Word comment, not a guessed rewrite.
- Tracked-changes v1 uses stdlib OOXML for `.docx`. Unique paragraph match
  only; miss → skip. Complex Word (fields, existing revisions, text boxes) is
  not round-tripped. `.pptx` / `.odt` get a copy with unique-span
  replacements (not Word revision markup; comments stay in the edit plan).
  `--output odt` on a non-ODT source builds a paragraph OpenDocument spine
  the same way. `--output pdf` prints the applied text (comments stay in
  the edit plan). Optional `[rewrite].openxml_audit` runs
  [openxml-audit](https://pypi.org/project/openxml-audit/) (Microsoft Open XML
  SDK port plus ODF adapter; `paperful[openxml]`) on office files and
  reports errors **not already on the source**. Word-authored drafts can fail
  the SDK on `stylesWithEffects`; those are ignored. `fail` exits 1 when
  rewrite introduced a new issue. Stdlib structure checks (comment ranges,
  Ignorable prefixes, slide/content XML, PDF header) always run on those
  outputs. Paperful does not write `.xlsx`; forensics only reads tables.

## Workbench

Advanced **Suggest edits** (next to Critique; CLI is still `paperful rewrite`):
pick a recent critique pack, optional replacement draft, area/output/comments
controls, download the result. With no pack on disk, the page is empty except
**Run Critique first**.

## See also

[critique](critique.md) · [config](config.md) · [llm](llm.md)
