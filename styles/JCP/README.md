# JCP Vale style

House-style rules for [Journal of Cleaner Production](https://www.sciencedirect.com/journal/journal-of-cleaner-production)
(Elsevier, ISSN 0959-6526), taken from the
[Guide for Authors](https://www.sciencedirect.com/journal/journal-of-cleaner-production/publish/guide-for-authors)
and the
[desk-reject policy](https://www.sciencedirect.com/journal/journal-of-cleaner-production/about/news/policy-statement-for-rejecting-articles-before-peer-review)
(read 2026-10-28). This is **not** an official Elsevier package.

Do **not** enable this pack together with `MarinePolicy`. Marine Policy uses
numbered citations; JCP uses author–year.

Paperful runs Vale on **extracted manuscript text** (`manuscript.txt`), not the
original `.docx` markup, so rules that need headings or character counts on
highlights are approximate.

## What these rules catch

| Rule | Guide point |
| --- | --- |
| `CitationStyle` | Author–year in the text, not numbered `[1]` |
| `DialectMix` | American **or** British English, not both |
| `InclusiveLanguage` | Inclusive language; avoid he/she |
| `Required*` | Abstract, keywords, highlights, funding, competing interests, data availability, CRediT |
| `GraphicalAbstract` | Graphical abstract is encouraged |
| `WordCount` | Original articles are 6000–8000 words (extracted text includes refs, so the alert is a high-water mark) |
| `VagueCrossRef` | Numbered section cross-references, not “the text” |
| `NumberedSections` | Divide the manuscript into numbered sections (1, 1.1, 1.2) |
| `ScopeFit` | Cleaner production / sustainability / environmental framing (desk-reject: scope) |
| `TheoreticalContribution` | Theoretical contribution (GFA: theoretical and practical cleaner production) |
| `PracticalImplications` | Practical / policy / production implications |
| `InternationalContext` | Regional work needs a wider international context (desk-reject) |
| `Terms` | Established CP / sustainability abbreviations (LCA, CE, SDGs, …) |
| `Placeholders` | Drafting residue (`[xx]`, TODO, lorem) |
| `Clarity` / `Padding` | A few padded phrases |
| `ContributionSentence` | Named contribution (`This paper proposes…`) |

## What they do not catch

Word limits by article type below the extract high-water mark, the **50-reference
cap**, 85-character highlights, 1–7 keywords as a count, figure resolution,
graphical-abstract pixel size, generative-AI declarations, or reference-list
completeness (DOI, LTWA journal abbreviations). Footnote markers such as
`(2021)[1]` are ignored by `CitationStyle`. Paperful’s own checkers still cover
captions, acronyms, overlap, and bibliography.

## Enable

```bash
cp styles/JCP/vale.ini.example .vale.ini
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
