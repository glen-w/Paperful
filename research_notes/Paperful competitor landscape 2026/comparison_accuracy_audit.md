# Comparison docs accuracy audit (2026-11-26)

Audit of `docs/comparison.md` and `docs/comparison-reference.md` against public sources as of **2026-11-26**. Positioning only; no paid pilots. Recommendations are keep / update / add / remove — **docs were not edited in this pass**.

## Short-answer and vendor one-line positioning

### Takeaway
Most Short answer rows still match public positioning. Highest-risk stale one-liners are SciSpace’s `typeset.io` primary URL, Consensus’s “will not write your literature review” parenthetical (conflicts with Deep Review), and the Zotero-version table that still groups StorScan/Attanger/ZotMeta/zotodata as “7–9”.

### Cited Findings
- **Valency MCP Bond** still exists as a remote MCP server over a large public corpus; marketing/docs claim search over **500 million** papers with a daily-updated index — [Welcome to MCP Bond](https://docs.valency.io/); [valency.io](https://www.valency.io/). A Nov 2026 ChemRxiv post distinguishes ~**45 million** OA/preprint works indexed vs a **500M+** citation graph — [ChemRxiv is now in Valency](https://blog.valency.io/posts/chemrxiv-is-now-in-valency/). Bond exposes a large tool surface (docs list **36** endpoints: semantic search, citation graph, authors, trends, export) — [MCP Endpoints](https://docs.valency.io/reference/endpoints/).
- **Edison Scientific** Literature still markets **175M+** papers/trials/patents; PaperQA3 Feb 2026 post says **150M+** with figures — [Overview](https://docs.edisonscientific.com/); [PaperQA3 announcement](https://edisonscientific.com/news/edison-literature-agent). Precedent (formerly Has Anyone) and Kosmos (~1,500 papers / ~42k LOC per run; UI/platform-oriented) match the docs — [Agents](https://docs.edisonscientific.com/agents).
- **Elicit** still states ~**138 million** papers (Semantic Scholar + OpenAlex + PubMed; weekly updates) — [Elicit's source for papers](https://support.elicit.com/en/articles/14758040-elicit-s-source-for-papers) (updated Sep 2026); [Paper Search](https://elicit.com/solutions/search).
- **OpenResearch** (`alphaXiv/OpenResearch`, `orx`) is live MIT OSS: local-first coding-agent harness, desktop app + CLI, lit sources alphaXiv / OpenAlex / bioRxiv / PubMed — [GitHub](https://github.com/alphaXiv/OpenResearch); [Literature docs](https://openresearch.sh/docs/literature); [openresearch.sh](https://openresearch.sh/).
- **PaperOrchestra** (`google-research/paper-orchestra`) is live; arXiv **2604.05018** resolves; project page and “not an officially supported Google product” disclaimer match — [GitHub](https://github.com/google-research/paper-orchestra/); [arXiv:2604.05018](https://arxiv.org/abs/2604.05018); [project page](https://yiwen-song.github.io/paper_orchestra/). PaperWritingBench is **not** in the code repo but **is** now on Hugging Face — [yiwen-song/PaperWritingBench](https://huggingface.co/datasets/yiwen-song/PaperWritingBench).
- **PaperGuard** GitHub + PyPI + HF demo URLs resolve; PyPI **v2.17.0** claims **41** built-in detectors, MIT, CLI + optional Web UI, anomaly-not-verdict stance — [PyPI paperguard](https://pypi.org/project/paperguard/); [GitHub](https://github.com/exergyleizhou-ux/PaperGuard); [HF demo](https://huggingface.co/spaces/exergyleizhou/paperguard-demo) (Space present; was sleeping when fetched).
- **SummarizePaper** positioning (hosted OA/preprint summaries, chat with cited passages, collections, email digests, OpenAI, Zotero web-API sync as Premium) matches public site/FAQ — [summarizepaper.com](https://www.summarizepaper.com); [FAQ](https://www.summarizepaper.com/en/faq/); [Zotero sync guide](https://www.summarizepaper.com/en/guides/zotero-sync-research-papers/). FAQ: full text only when license allows (CC BY family / CC0); **“You cannot upload your own PDF to have it summarized.”**
- **SciSpace** still uses `typeset.io` as a redirect; current brand URL is **scispace.com** — [CASRAI SciSpace guide](https://casrai.org/guides/scispace); [Typeset → SciSpace](https://scispace.com/guides/typeset-evolving-into-scispace).
- **zotero-zotadata**, **zotero-agent**, **StorScan**, **Attanger**, **ZotMeta**, **glen-w/Paperful** repos all resolve with positioning consistent with Short answer rows — [ydeng11/zotero-zotadata](https://github.com/ydeng11/zotero-zotadata); [alex-roc/zotero-agent](https://github.com/alex-roc/zotero-agent); [StorScan](https://github.com/brian-j-griffith/StorScan); [Attanger](https://github.com/MuiseDestiny/zotero-attanger); [ZotMeta](https://github.com/RoadToDream/ZotMeta); [glen-w/Paperful](https://github.com/glen-w/Paperful).
- **Gemini Notebook** is the Jul 2026 rename of NotebookLM; `notebooklm.google` link still works via redirect — [Google blog](https://blog.google/innovation-and-ai/products/gemini-notebook/notebooklm-gemini-notebook/). Docs already say “Gemini Notebook” with NotebookLM URL — OK.
- **Consensus** still documents LibKey as **link-resolve only** (does not ingest LibKey full text) — [Read the full paper](https://docs.consensus.app/get-started/full-text-access). Deep Review help says it **conducts full literature reviews** and often produces structured lit-review sections — [How to Use Deep review](https://help.consensus.app/en/articles/11740827-how-to-use-deep-review). An older Consensus blog still says the platform “won’t write your Literature Review or Dissertation for you” — [Consensus lit-review guide](https://consensus.app/home/blog/how-to-write-a-literature-review-dissertation/).

### Inferences
- Short answer rows for Paperful, Edison, Elicit, Valency Bond, OpenResearch, PaperOrchestra, PaperGuard, SummarizePaper, zotero-agent, zotero-mcp, SR tools, and writers are **keep** with light URL/corpus polish.
- Consensus stage-matrix parenthetical “will not write your literature review” is **overstated / stale** relative to Deep Review product copy; under the docs’ own “Write MS = submission-shaped draft” legend, a fair cell is **Partial** (Deep Review **report**, not a journal MS) — same band as Elicit — not a flat **No** tied to that parenthetical.
- Valency one-liner “semantic search / citation graph / authors / trends via MCP” is **still correct**; avoid baking a single corpus integer into customer tables without noting OA-index (~45M) vs citation-graph/marketing (500M) conflict.

### Gaps
- Hands-on verification of zotero-mcp fork feature parity (OCR, Unpaywall attach) was not done; “typical” column remains positioning-only.
- Jenni / Paperpal “200–300M index” figures were not re-fetched from vendor pricing pages in this pass — treat as **unverified vendor claims** already framed as such.
- Consensus publisher full-text *for analysis* (beyond OA/uploads) is newly emphasized in Consensus docs; how that should appear in a **Get PDF** column (library ownership) vs Synthesize remains a copy judgment, not fully resolved here.

## Capability Yes/Partial/No cells that look stale

### Takeaway
Two matrix bugs need fixes first: (1) Paperful attachment-repair is **Partial** in `comparison.md` but **No** in `comparison-reference.md`; (2) the Zotero version table is wrong for Attanger, ZotMeta, StorScan, and zotodata. Edison/Elicit corpus notes and PaperGuard packaging are largely fine; SummarizePaper “uploaded” wording and Consensus Write MS are the next tier.

### Cited Findings
- **Internal contradiction — Attachment repair:** `comparison.md` capability snapshot marks Paperful broken-link / file layout repair **Partial** (`attachments` report + `--apply` surgery). `comparison-reference.md` Zotero-centric table marks Paperful “Attachment / disk repair” **No**. Same product, opposite cells.
- **Zotero version table** (`comparison-reference.md`) groups “StorScan, Attanger, ZotMeta 2.0, zotodata” as **7–9**. Public READMEs/atlas as of Nov 2026:
  - Attanger: **Zotero 7–10** — [MuiseDestiny/zotero-attanger](https://github.com/MuiseDestiny/zotero-attanger)
  - ZotMeta **2.1**: **Zotero 7.0–10.0.x** — [RoadToDream/ZotMeta](https://github.com/RoadToDream/ZotMeta); [Zotero Plugins Atlas](https://zoteroplugins.org/p/zotmeta)
  - StorScan 1.0.2: **Zotero 9 only** (not 10; not 7–8) — [StorScan README](https://github.com/brian-j-griffith/StorScan); [Atlas](https://zoteroplugins.org/p/storscan)
  - zotero-zotadata: **Zotero 8–10** (7.x needs older plugin) — [ydeng11/zotero-zotadata](https://github.com/ydeng11/zotero-zotadata)
- **Edison 175M vs 150M:** Docs already warn not to reconcile; still accurate vs [docs overview](https://docs.edisonscientific.com/) and [PaperQA3 post](https://edisonscientific.com/news/edison-literature-agent).
- **Elicit ~138M:** Still matches Sep 2026 help center — [Elicit's source for papers](https://support.elicit.com/en/articles/14758040-elicit-s-source-for-papers).
- **Valency MCP Bond existence/features:** Confirmed (Bond + Hub split, MCP-first, authors/trends/graph/export). “Large tool surface” is understated relative to published **36** endpoints but not wrong — [MCP Endpoints](https://docs.valency.io/reference/endpoints/).
- **SummarizePaper capabilities:** Stage/capability rows mostly OK. Capability table wording “OA / preprint / **uploaded**” conflicts with FAQ “cannot upload your own PDF” — [FAQ](https://www.summarizepaper.com/en/faq/). Scoop / citation / email-alert claims still appear on marketing/tools pages.
- **OpenResearch status:** Active; lit sources including OpenAlex confirmed in official docs (README homepage blurb omits OpenAlex; comparison-reference is **more complete** than the GitHub README blurb) — [Literature search](https://openresearch.sh/docs/literature).
- **PaperOrchestra status:** Active; win-margin 50–68% lit-review claim matches project page. Update “PaperWritingBench … not in the code repo” to note **HF release** — [PaperWritingBench](https://huggingface.co/datasets/yiwen-song/PaperWritingBench).
- **PaperGuard packaging:** PyPI `paperguard`, `paperguard[webui]`, ~41 detectors, anomaly + innocent explanations — aligns with comparison-reference PaperGuard section — [PyPI](https://pypi.org/project/paperguard/).
- **Paperful Write MS Partial (`stuff`):** `stuff` is shipped (CLI + workbench + docs) — repo `docs/stuff.md`, `paperful/stuff_cmd.py`. Oct 2026 factory report’s “stuff unshipped / Write MS No” is **stale relative to current comparison docs**; comparison docs are the correct side.
- **Consensus Write MS = No:** Deep Review product copy describes structured literature-review outputs — [Deep review help](https://help.consensus.app/en/articles/11740827-how-to-use-deep-review). Under matrix legend (Write MS = submission-shaped draft), **Partial** is a better fit than **No** + outdated parenthetical.
- Stage-matrix dating note still says “public-docs positioning (**2026-10-26**)” — should bump after this audit.

### Inferences
- **CRITICAL:** Align Paperful attachment cell to **Partial** in both files (or rename the reference row so “No” is clearly “no in-app StorScan-class author-folder toolkit,” not “no attachment CLI”).
- **CRITICAL:** Rewrite Zotero version table into per-tool rows; stop the “7–9” bundle.
- **IMPORTANT:** Fix SummarizePaper “uploaded”; Consensus Write MS cell/parenthetical; SciSpace primary URL; PaperOrchestra HF note; bump matrix “as of” date; optionally add Valency “36 tools / 500M marketing vs ~45M OA index” caveat in the Bond note (not the customer Yes/No grid).
- **NICE:** Mention Valency endpoint count; note Consensus analyzes some publisher full text for answers while LibKey remains link-only for institutional copies.

### Gaps
- StorScan Atlas vs README: both say Zotero 9 / not 10; whether a newer XPI appears after 2026-11-26 was not monitored beyond Atlas last-checked 11 Nov 2026.
- Independent 2025 Elicit SR recall (~40%) citation in the stage preamble was not re-audited against newer Elicit “PRISMA 2020 / 95% recall” marketing — docs correctly keep Screen as Partial; do not promote vendor 95% as Yes without a new independent study.

## Dead links, renamed products, wrong GitHub orgs

### Takeaway
No dead primary GitHub orgs found for named tools. Prefer `scispace.com` over `typeset.io`. PaperOrchestra / OpenResearch / PaperGuard / Valency / Edison / Elicit links are live. PaperWritingBench “not released” is understated.

### Cited Findings
- SciSpace: `https://www.typeset.io/` still redirects; brand site is `https://scispace.com/` — [CASRAI](https://casrai.org/guides/scispace).
- PaperOrchestra GitHub org `google-research/paper-orchestra` correct; arXiv `2604.05018` live — [arXiv](https://arxiv.org/abs/2604.05018).
- OpenResearch org `alphaXiv/OpenResearch`, docs `openresearch.sh` live — [GitHub](https://github.com/alphaXiv/OpenResearch).
- PaperGuard org `exergyleizhou-ux/PaperGuard` unusual but real; PyPI + HF demo URLs work — [GitHub](https://github.com/exergyleizhou-ux/PaperGuard).
- Valency `valency.io` + `docs.valency.io` live — [docs](https://docs.valency.io/).
- Edison `docs.edisonscientific.com` live — [Overview](https://docs.edisonscientific.com/).
- zotero-agent `alex-roc/zotero-agent` live (v0.8.8, Oct 2026) — [GitHub](https://github.com/alex-roc/zotero-agent).
- Paperful reference link `glen-w/Paperful` live — [GitHub](https://github.com/glen-w/Paperful).
- DistillerSR named without URL in Short answer / SR section (Covidence/Rayyan/ASReview are linked).
- Gemini Notebook / NotebookLM naming: docs already use Gemini Notebook — keep; URL to notebooklm.google is acceptable.

### Inferences
- **IMPORTANT:** Change SciSpace Short answer / Hosted literature links from typeset.io → scispace.com (keep “formerly Typeset” only if useful).
- **IMPORTANT:** Update PaperOrchestra note: PaperWritingBench available on HF though still absent from the code repo.
- **NICE:** Add DistillerSR homepage link for parity; optionally note HF Space for PaperGuard may sleep when idle.

### Gaps
- Did not HTTP-check every secondary deep-link (Overleaf AI docs, Covidence pricing, Rayyan, Scite, Undermind, Scholarcy, Explainpaper, Humata, bibmanager, bibcite, paperscraper). No contrary signals from searches.
- Did not verify whether `richardjlyon/zotero-mcp`, `cookjohn/zotero-mcp`, `Xevos117/mcp-zotero` remain the best three forks to name.

## Missing obvious peers in the same row categories

### Takeaway
Row coverage is strong for Zotero helpers, hosted lit search, AI scientists, SR screening, and writers. Optional adds are citation-map UIs already alluded to in snowball copy, and lit-MCP peers if Valency is the only named global MCP.

### Cited Findings
- Short answer already clusters Elicit / Consensus / Undermind / SciSpace / Scite for hosted lit search; Edison + Co-Scientist + Sakana for AI scientist; Covidence / Rayyan / DistillerSR / ASReview for SR; Jenni / Paperpal / SciSpace Writer / Overleaf Writefull for drafting.
- Snowball row already mentions Research Rabbit as a citation-map that “links out” vs Paperful downloads — [comparison.md](../../docs/comparison.md) Short answer grow-library row.
- Background factory report also lists Connected Papers / Litmaps-class discovery and Semantic Scholar API as adjacent discover surfaces — `reports/AI academic paper factories.md`.
- Valency is the only named **hosted literature MCP**; Elicit publicly markets API + MCP — [Elicit API and MCP](https://elicit.com/blog/the-elicit-api-and-mcp-powering-autonomous-research-engines) (Jul 2026).

### Inferences
- **NICE / optional ADD:** In Hosted literature search reference blurb, one line that Elicit (and peers) also expose MCP/API — Bond remains MCP-first.
- **NICE / optional ADD:** Citation-map peers (Connected Papers, Litmaps, ResearchRabbit) as a Short answer sibling only if snowball’s one-hop browsers row feels thin — not required for accuracy.
- **Do not ADD** as peers that would blur Paperful’s jobs: Jeffersonian/qual coding, Valency Hub publishing, ChemCrow/Molecules (already correctly out of scope).

### Gaps
- No exhaustive market scan of every 2026 lit-MCP competitor beyond Valency/Elicit mentions; “missing peers” list is not claimed complete.

## Sci-Hub mentions vs opt-in brief-mention policy

### Takeaway
Comparison docs stay inside the allowed brief/capability/architecture pattern: Sci-Hub appears as opt-in capability Yes and in the ASCII source stack, not as a promoted recipe or hero path. No expansion recommended.

### Cited Findings
- Workspace rule: outside `docs/scihub.md`, only brief notes that Sci-Hub is **off by default**, opt-in at user risk; no example commands or screenshots — `.cursor/rules/scihub-docs.mdc`.
- `comparison.md` / `comparison-reference.md`: Sci-Hub only in capability grids (“explicit opt-in”), architecture diagram (“(opt-in Sci-Hub)”), and “Where Paperful sits” job list — no `--scihub` recipes, no mirror URLs, no Short answer “If you need Sci-Hub” row.
- Related-docs pointer to architecture.md for Sci-Hub is consistent with “technical architecture notes” allowance.

### Inferences
- **KEEP** current Sci-Hub mentions; **do not expand** recipes or add a Short answer Sci-Hub row.
- Optional polish only: in capability legend footnotes, one clause “off by default; see scihub.md” if editors want stricter policy alignment — not required for a violation finding (no violation found).

### Gaps
- Did not audit screenshots under `docs/screenshots/` for Sci-Hub UI (out of comparison.md scope).

## Prioritized fix list (recommend only)

### Takeaway
Fix the contradictory Paperful attachment cell and the Zotero version table first; then refresh Consensus Write MS, SummarizePaper upload wording, SciSpace URL, PaperOrchestra HF note, and matrix “as of” date. Polish peers and Valency corpus caveats last.

### Cited Findings
Evidence for each fix is cited in the sections above.

### Inferences

#### CRITICAL (wrong)
1. **UPDATE** `comparison-reference.md` Paperful “Attachment / disk repair” from **No** → **Partial** to match `comparison.md` (or redefine the row label so the two tables are not contradicting each other).
2. **UPDATE** Zotero version table — replace the bundled “StorScan, Attanger, ZotMeta 2.0, zotodata | 7–9” row with per-tool notes:
   - Attanger: 7–10
   - ZotMeta 2.1: 7–10
   - StorScan: 9 (not 10 per upstream/Atlas)
   - zotero-zotadata: 8–10 (not 7)
3. **UPDATE** Consensus workflow-stage **Write MS** cell: change **No** (“will not write your literature review”) → **Partial** (Deep Review structured **report**; not a journal manuscript / dissertation). Keep honesty that Consensus markets “won’t write your dissertation,” but do not deny Deep Review outputs.

#### IMPORTANT (stale / missing)
4. **UPDATE** SummarizePaper capability note: drop “uploaded” (FAQ forbids PDF upload); say OA / preprint / DOI / journal pages, license-gated full text.
5. **UPDATE** SciSpace links: primary URL `https://scispace.com/` (typeset.io optional as formerly/redirect).
6. **UPDATE** PaperOrchestra: keep “not in code repo,” **add** Hugging Face `yiwen-song/PaperWritingBench`.
7. **UPDATE** Stage-matrix preamble date **2026-10-26** → **2026-11-26** (or “verified 2026-11-26”).
8. **UPDATE** Valency Bond vendor note: optional caveat that marketing “500M papers” coexists with ~45M OA/preprint index + 500M citation-graph language (do not put a single reconciled integer in the Yes/No grid).
9. **KEEP** Edison 175M/150M dual note; Elicit ~138M; OpenResearch status/positioning; PaperGuard packaging (~41 detectors, PyPI, anomaly stance); Paperful `stuff` as Write MS Partial.

#### NICE (polish)
10. **ADD** DistillerSR URL beside Covidence/Rayyan.
11. **ADD** one clause that Elicit exposes API/MCP (Bond remains the MCP-first global-corpus row).
12. **OPTIONAL ADD** Connected Papers / Litmaps next to Research Rabbit in the grow-library / citation-map aside.
13. **OPTIONAL** Valency “~36 MCP tools” instead of only “large tool surface.”
14. **OPTIONAL** Consensus Get PDF / Synthesize footnote: analysis may use publisher full text; LibKey remains link-only; still no campus-proxy fetch into Zotero.
15. **KEEP** Sci-Hub brief/capability mentions; no recipe expansion.
16. **REMOVE** nothing required for accuracy; ZotFile legacy row remains useful.

### Gaps
- Paid-feature depth (Edison credits, SummarizePaper Premium limits, Consensus Deep quotas) intentionally unverified.
- No doc edits were applied; this file is recommendations only.
