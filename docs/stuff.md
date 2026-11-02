# Stuff (extra citations from the library)

`paperful stuff` suggests extra citations **you already hold** for each
claim in a draft. It splits the extract into sentences (or outline
sections), runs the same retriever as `paperful rag search`, and writes a
pack of hits. There is **no Ask narrative**, no invented BibTeX, and no
library write.

Needs `[rag].enabled` and a built index. Does **not** need `[llm]`. Fail
closed if the index is missing or empty.

This is not a rewrite and not claim verification. Similarity is not proof
the source supports the sentence. Extra cites belong in Zotero before
`\cite`.

## CLI

`--item KEY` and `--file PATH` are mutually exclusive. `--file` accepts the
same text formats as [critique](critique.md) (pdf, txt, md, html, rtf,
docx, odt, pptx; legacy `.doc` if a converter is on PATH).

```bash
uv run paperful stuff --file ./draft.docx -C "My Collection" --k 3
uv run paperful stuff --file ./outline.docx --lane outline -C "My Collection"
uv run paperful stuff --item KEY -C "My Collection"
uv run paperful stuff --file ./draft.md --dry-run
```

`--k` is extra sources per claim (default `[stuff].k` = 3, capped by
`[rag].top_k`). `-C` / `--library` / `--year-from` / `--year-to` / `--type`
scope the index the same way as `rag search`. When `--item` is set, that
item is never listed as a hit for itself.

`--lane` selects the **retrieval unit** (not an LLM extra). One lane per
run.

| Lane | Default | Unit | Skips |
| --- | --- | --- | --- |
| `manuscript` | yes | sentences after dropping the bibliography window | fragments under `min_sentence_words` (default 8) |
| `outline` | `--lane outline` or `[stuff].lane` | one row per section (`outline_slices`) | canonical References / Acknowledgements; empty queries |

Outline query is `{heading} {body}`, truncated. Thin named sections still
search (the heading is a useful query). Same heading ledger shape as
`critique --lane outline`.

`--dry-run` prints counts and does not write `state/stuff/`. `--format json`
prints `paperful.agent.json.v1`. Not in `paperful all`. `paperful jobs` →
completeness.

## Pack

Packs land in `state/stuff/<id>/<stamp>/` as `pack.json`
(`paperful.stuff.pack.v1`) and `pack.md`. `<id>` is the library item key or
`file-<filename-stem>`.

Each **row** is a quote plus locator plus `≤ k` hits (item key, title,
pages, score, passage snippet). **Skips** record `short`, `biblio`,
`over_cap`, or `empty`. Outline runs also write an `outline` ledger.
`[stuff].max_units` (default 200) caps how many claims are searched.

`pack.md` leads with an honesty banner: hits are in-library similarity, not
proof of support; this pack does not invent citation keys.

## Config

```toml
[stuff]
k = 3
min_sentence_words = 8
min_query_words = 4
max_units = 200
lane = "manuscript"   # manuscript | outline
```

See [config.md](config.md).

## What this is not

- Not `ask` (no grounded paragraph).
- Not [`refs gap`](commands.md) (cited-in-PDF works you do not own).
- Not `precedent` (no OpenAlex / public-metadata-only rows).
- Not auto-insert into the manuscript. `--apply` and stance labels stay later.

## Workbench

Advanced **Stuff** (next to Suggest edits; CLI is still `paperful stuff`):
pick a library item **or** upload a draft, choose lane (`manuscript` /
`outline`) and `k`, download `pack.md`. Needs `[rag]` and a built index.
Does not need `[llm]`. Never writes Zotero. Uploads stay under
`state/critiques/uploads/` like Critique.

Read-only MCP tool `stuff` (`item` or `file`, `lane`, `k`, `collection`)
returns the same envelope as `--format json`.
