# Evidence table

`paperful evidence` writes a **sourced comparison table** over PDFs you already
hold. It is not chat, not a literature review, and not `synthesize`.

Every cell is a **quote that occurs in the PDF**, or the literal `check this`.
There is no model. `--apply` is refused; the pack stays on disk.

```sh
uv run paperful evidence -C BBNJ
uv run paperful evidence --item KEY
uv run paperful evidence -C BBNJ --year-from 2020 -T journalArticle --limit 20
uv run paperful evidence -C BBNJ --format json   # paperful.agent.json.v1
```

Writes `state/evidence/<stamp>/` (`pack.json`, `pack.md`, `table.csv`). Schema
`paperful.evidence.v1` (frozen keys: `schema`, `evidence_id`, `created_at`,
`scope`, `rows`, `counts`, `skips`). Same `--item` / `-C` / `--library` /
year / type / `--limit` scope as `summarize`. `--apply` exits 1. No GUI
control — see [Workbench](gui.md).

## Columns

| Column | Fill rule |
|--------|-----------|
| design | `study_design` already in Extra, else the Zotero item type, else `unspecified`. No live OpenAlex call |
| n | A sample-size span (`n = 42`, `sample of`, *N* participants) that occurs in methods/results text |
| method | Quote from `extract-sections` methodology, or a live heading split |
| finding | Quote from a Results heading, else Conclusion |
| loc | Page of the quote used |

Reuse `state/sections/<key>.json` when present. A missing PDF or empty text is a skip, not a guessed row.

## Honesty

- Anything without a quote is `check this` and does not count as a finding.
- This is not a verdict and it does not invent statistics.
- For per-sentence support of a **draft** you already wrote, use [`ask --claim-check`](rag.md#claim-check).
- For a summary of one paper with page quotes, use {ref}`summarize --receipts <d-summarize-grounded-summary-note>`.
- Hosted OA/preprint tables are [SummarizePaper](comparison.md); this verb only quotes files under `out/`.
