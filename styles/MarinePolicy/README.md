# MarinePolicy Vale style

House-style rules for [Marine Policy](https://www.sciencedirect.com/journal/marine-policy)
(Elsevier, ISSN 0308-597X), taken from the
[Guide for Authors](https://www.sciencedirect.com/journal/marine-policy/publish/guide-for-authors)
(read 2026-10-26). This is **not** an official Elsevier package.

Paperful runs Vale on **extracted manuscript text** (`manuscript.txt`), not the
original `.docx` markup, so rules that need headings or character counts on
highlights are approximate.

## What these rules catch

| Rule | Guide point |
| --- | --- |
| `CitationStyle` | Numbered citations in square brackets, not author–date |
| `DialectMix` | American **or** British English, not both |
| `InclusiveLanguage` | Inclusive language; avoid he/she |
| `Required*` | Abstract, keywords, highlights, funding, competing interests, data availability, CRediT |
| `PolicyImpact` | Full-length articles discuss policy impact |
| `WordCount` | Full-length articles are normally 4000–6000 words excluding abstract, references, acknowledgements |
| `VagueCrossRef` | Numbered section cross-references, not “the text” |
| `Terms` | Established ocean-policy abbreviations (UNCLOS, BBNJ, EEZ, …) |
| `Clarity` / `Padding` | A few padded phrases |

## What they do not catch

Word limits by article type, 85-character highlights, 1–7 keywords, figure
resolution, double-anonymized title-page split, cover letter, or reference-list
completeness (DOI, LTWA journal abbreviations). Paperful’s own checkers still
cover captions, acronyms, overlap, and bibliography.

Do **not** enable this pack together with `JCP` (author–year vs numbered
cites).

## Enable

```bash
cp styles/MarinePolicy/vale.ini.example .vale.ini
vale --config=.vale.ini path/to/manuscript.txt
```

With Paperful critique:

```toml
[critique]
vale = true
vale_config = ".vale.ini"
```

```bash
uv run paperful critique --file manuscript.docx --vale
```

A personal tint can sit in another gitignored directory under `styles/` and
use its own sibling `.vale-*.ini`. Do not mix that pack into this example
ini.
