# Vale style: Journal of Money Laundering Control (JMLC)

House-style rules for manuscripts targeting **Journal of Money Laundering Control** (Emerald Publishing, ISSN 1368-5201). They encode [Emerald’s general author guidelines](https://www.emerald.com/journals/author-guidance/1627/emerald-publishing-author-guidelines) plus the [JMLC journal page](https://www.emeraldgrouppublishing.com/journal/jmlc) (word counts, structured abstract, Harvard references).

## Quick start

```bash
cp styles/JMLC/vale.ini.example .vale.ini
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

Vale lints **extracted plain text**, not Word styles. Keep structured abstract subheadings on their own lines (`Purpose:`, `Purpose –`, etc.) so `Abstract.yml` can see them.

## Rule sets

| File | Focus |
|------|--------|
| `Abstract.yml` | Mandatory Emerald/JMLC structured abstract headings |
| `Terms.yml` | AML/CFT terminology and hyphenation |
| `EmeraldHarvard.yml` | In-text Harvard citations (`and`, `et al.`, page ranges) |
| `References.yml` | Reference list shape (`Vol.`, DOI, quoted titles) |
| `Spelling.yml` | British English preference (suggestion) |
| `Headings.yml` | Numbered sections; table/figure numbering conventions |
| `Manuscript.yml` | Keywords, anonymity, funding, notes |
| `Jargon.yml` | Practitioner-readable phrasing (Emerald guidance) |

## Source documents reviewed

### Official guidance (November 2026)

- [Emerald Publishing Author Guidelines](https://www.emerald.com/journals/author-guidance/1627/emerald-publishing-author-guidelines) — structured abstract, Harvard references, headings, tables/figures, ethics, file format.
- [JMLC author guidance](https://www.emeraldgrouppublishing.com/journal/jmlc) — **5,000–8,000** words for research papers (plus ~280 words per table/figure), up to **12** keywords, mandatory abstract sections **Purpose / Design/methodology/approach / Findings / Originality**, Harvard references, double-anonymous peer review.
- [Emerald Harvard reference guide](https://www.emeraldgrouppublishing.com/how-to/authoring-editing-reviewing/use-harvard-reference-system) — `(Author and Author, year)`, italic *et al.*, `pp.` ranges, `Ed.s`, DOIs.

Note: the Emerald Insight journal landing page sometimes lists **8,000–10,000** words for research papers; the dedicated JMLC author page states **5,000–8,000**. Treat the journal author page as the submission target and confirm in ScholarOne before submitting.

### Published articles (diverse methods; full text or AAM unless noted)

Downloaded for analysis into `research/jmlc-papers/` (local research copies; not required to use the style):

| Paper | DOI | Type | Source |
|-------|-----|------|--------|
| Malagueño et al., *Accounting and corruption: a cross-country analysis* | [10.1108/13685201011083885](https://doi.org/10.1108/13685201011083885) | Empirical econometric | [UEA repository PDF](https://ueaeprints.uea.ac.uk/id/eprint/54209/1/MoneyLaunderingFinal.pdf) |
| Burns et al., *Anti-money laundering in the United Kingdom* | [10.1108/JMLC-04-2021-0041](https://doi.org/10.1108/JMLC-04-2021-0041) | Qualitative interviews / policy | [UCL Discovery proof PDF](https://discovery.ucl.ac.uk/10133296/1/PDF_Proof.pdf) |
| Tiwari et al., *Global money laundering appeal index* | [10.1108/JMLC-10-2021-0108](https://doi.org/10.1108/JMLC-10-2021-0108) | PCA / index construction | [Bond University AAM PDF](https://pure.bond.edu.au/ws/files/122374839/AM_Global_money_laundering_appeal_index.pdf) |
| Gilmour, *Crime scripting… holistically* | [10.1108/JMLC-09-2020-0109](https://doi.org/10.1108/JMLC-09-2020-0109) | Conceptual / crime scripting | Crossref structured abstract only (VoR paywalled on Emerald Insight) |

**Patterns taken from those papers:** structured abstract with en dash or colon after subheadings; `(Author, year)` and `(Author et al., year)` citations; reference list entries with `Vol. X No. Y`, `pp.`; mix of `Originality/value` (older AAM) vs `Originality` (newer proofs); Roman numeral tables in some AAMs (`Table I`) and Arabic tables in others (`Table 1`); heavy use of **AML** acronym in policy-facing work; US spelling in older multi-country empirics vs UK spelling in UK-focused qualitative work — hence British rules are **suggestions**, not errors.

## Limits

- Vale cannot enforce word counts, reference sort order, or italic *et al.* in Word.
- Glossary-specific swaps belong in `paperful glossary export-vale`, not here.
- Uncomment `Packages` in `vale.ini.example` and run `vale sync` if you want Microsoft/write-good baselines in addition to `JMLC`.
