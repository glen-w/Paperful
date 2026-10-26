# Paperful vs v2 academic-paper factory (internal inventory)

Internal-only notes from `/Users/89298/Documents/paperful` docs and CLI. No web. Status language: **shipped** = documented as in tree / CLI; **roadmap** = named in ROADMAP with not-yet-shipped direction; **out of scope** = explicit non-goal. Do not treat ROADMAP buffet items as capabilities.

Legend for stages: **S** shipped · **P** partial (adjacent verb, opt-in, or lighter than a factory stage) · **R** roadmap / buffet · **X** explicit non-goal.

## What factory stages exist today (discover, acquire PDF, metadata, screen, extract, synthesize, critique, write, keep current, export)?

### Takeaway
Paperful is a **disk-first library helper** whose 1.x product is Wanted (missing PDFs) plus Discover (grow the catalogue) plus optional Ask over **held** PDFs — not an end-to-end paper factory. Most factory stages have a **shipped slice** with dry-run / `--apply` / fail-closed bars; **write** (citation stuffing, manuscript generation, CSL/Quarto) and **systematic screening** are the largest holes.

### Cited Findings

**Product jobs (not factory stages).** Five jobs: Library, Find, Completeness, Mirror, Control. Ladder: `gaps` / `attachments` honesty → `run` fills `out/` → read the mirror → then summarize or Ask. **attach** writes the PDF into Zotero. — [docs/why.md — Five jobs](file:///Users/89298/Documents/paperful/docs/why.md)

**1.0 vs post-1.0.** 1.0 is trust checklist, locked `paperful.item.v1` / `paperful.run_report.v1`, Zotero-proven fetch/mirror, workbench Wanted + Discover + Ask. Still not a full-text reading index, not a WebDAV client, not “AI fetch everything.” Wanted is the recommended main lane after 1.1.1. — [docs/ROADMAP.md — Product split: 1.0 vs post-1.0](file:///Users/89298/Documents/paperful/docs/ROADMAP.md); [docs/ROADMAP.md — Wanted (main lane)](file:///Users/89298/Documents/paperful/docs/ROADMAP.md)

**Workbench nav maps to CLI, not a second stack.** Default nav: Wanted = `gaps` / `run` / `attach`; Discover = `snowball` / `authorwatch` / watches; Ask = `ask`. Advanced: Repair, Mirror, Index, Briefs, Critique. Grab fetches to `out/`; Attach writes the library. No built-in scheduler. TTY, Sci-Hub, `collections add` stay CLI. Not Zotero’s reader (no embedded PDF viewer). — [docs/gui.md — Product framing](file:///Users/89298/Documents/paperful/docs/gui.md); [docs/ROADMAP.md — GUI](file:///Users/89298/Documents/paperful/docs/ROADMAP.md)

| Factory stage | Status | What exists in repo (verbs / surfaces) | What is not this stage |
| --- | --- | --- | --- |
| **Discover** | **S** (local collection growth) **P** vs public corpus | `snowball` (keyword / DOI / ORCID / collection / hybrid; refs/cites/similar; dry-run default; gates; Discover map); `authorwatch`; `ingest-dois`; `snowball trends`; MCP `snowball_search` / `snowball_trends` | Not Valency-scale semantic search over 100M+ papers; Explore is one seed + hops, not the whole public graph — [docs/snowball.md — Out of this lane](file:///Users/89298/Documents/paperful/docs/snowball.md) |
| **Acquire PDF** | **S** | `run` (OA, CORE, arXiv, EZProxy, grey playbooks, opt-in Scholar / Sci-Hub / browser-agent / Camofox / SerpApi); Wanted Preview → Grab; `inbox`; `gaps --handoff`; `recover`; `htmlpdf`; `reachout` never fetches | Publisher TDM APIs: **No** vs paperscraper — [docs/comparison-reference.md — DOI-centric downloaders](file:///Users/89298/Documents/paperful/docs/comparison-reference.md) |
| **Metadata** | **S** (Zotero) | `lint`, `fix-metadata --apply` (whitelist doi/title/date/venue), `acronyms`, `versions`, `snapshot` `record.json`, `dedupe` (Zotero-only apply) | Mendeley/EndNote **seeking testers**; EndNote does not edit `.enl` — [docs/why.md — What is true today](file:///Users/89298/Documents/paperful/docs/why.md) |
| **Screen** | **P** | `screen`: retractions/EoC/withdrawal (Crossref+OpenAlex), optional PubPeer, PPS fingerprints on PDF text; report default; `--apply` tag + note; **not** in `paperful all` — [docs/screen.md](file:///Users/89298/Documents/paperful/docs/screen.md). Discover Keep/Skip is hop triage, not SR screening | ASReview-style learned screening is buffet — [docs/ROADMAP.md — Local embeddings](file:///Users/89298/Documents/paperful/docs/ROADMAP.md). Systematic-review screening **parked** — [docs/ROADMAP.md — Parked (snowball lane)](file:///Users/89298/Documents/paperful/docs/ROADMAP.md) |
| **Extract** | **S** (structured + index) | `ocr`; `extract-sections` → `state/sections/<key>.json` (`paperful.sections.v1`; rules always; `--llm` fill); `rag ingest` / `rag search` / `rag questions` (mirror-only; never calls the manager) — [docs/rag.md — Structured sections](file:///Users/89298/Documents/paperful/docs/rag.md); [docs/commands.md — Command table](file:///Users/89298/Documents/paperful/docs/commands.md) | Annotation mirror **R** — [docs/ROADMAP.md — Annotation mirror](file:///Users/89298/Documents/paperful/docs/ROADMAP.md). Two-up split stays zotero-agent |
| **Synthesize** | **P** | Opt-in `[llm]`: `summarize` (grounded HTML + child note), `synthesize` (review from **existing summary notes**), `ask` (cited Q&A from LanceDB index), `--focus` default\|questions\|gaps\|methods\|answered, `rag answered` | Conflicting-evidence / review-shaped briefs / figure pullouts / evidence tables / living starred briefing: **R** buffet — [docs/ROADMAP.md — Summaries, briefs, and Ask](file:///Users/89298/Documents/paperful/docs/ROADMAP.md) |
| **Critique** | **S** (pre-submission pack) | `critique`: `--item` or `--file`; deterministic checkers always; no score/grade/accept-reject; overlap vs **library text on disk**; optional `--llm` suggested lane; not Deep Review; not in `paperful all` — [docs/critique.md](file:///Users/89298/Documents/paperful/docs/critique.md) | Not a referee; no web search; no similarity API |
| **Write** | **R** / **P** (export only) | `stuff` is **roadmap only** (no CLI verb in `commands.md`) — [docs/ROADMAP.md — stuff](file:///Users/89298/Documents/paperful/docs/ROADMAP.md). `export` RIS/BibTeX/EndNote XML; `export-proposals` | No manuscript generation; no auto-insert citations; CSL/Quarto **parked** (point to Better BibTeX) |
| **Keep current** | **S** (you cron) | `keepup` (watch + authorwatch + `--source cites`); `snowball watch`; `authorwatch run`. No email, no built-in scheduler — [docs/keepup.md](file:///Users/89298/Documents/paperful/docs/keepup.md) | Nightly embedding queries of OpenAlex, living-review re-run, Discover keepup UX: buffet — [docs/ROADMAP.md — Keeping up](file:///Users/89298/Documents/paperful/docs/ROADMAP.md) |
| **Export / handoff** | **S** (mirror + bib) | `snapshot` / `restore --apply` (missing items only, never overwrite fields); copy `out/` yourself; Firefox add-on writes `out/` only; MCP `export` / `proposal_export` | Quiet mirror is not a citation manager — [docs/why.md — Mirror](file:///Users/89298/Documents/paperful/docs/why.md) |

**Research-pack spine (operator factory, not one verb).** Sequence: `refs gap` → `ingest-dois --dry-run` → `--apply` → `run` / handoff / inbox → `dedupe` → optional watch/digest → `summarize` / `ask` after ledger is honest. Not `paperful all`. PDFs never come from ingest. — [docs/research-pack.md — Sequence](file:///Users/89298/Documents/paperful/docs/research-pack.md)

**`paperful all` is fill+tidy+summarize, not a factory.** Chain: `gaps` → `run --try-all --retry-failed --upgrade-linked` → `lint` → `fix-metadata --apply` → `summarize --apply`. No snowball, no critique, no rag ingest, no keepup. — [docs/commands.md — `all`](file:///Users/89298/Documents/paperful/docs/commands.md)

**Ask / RAG honesty.** `[rag].enabled` off by default. Reads `out_dir` only. Coverage depends on `[mirror].pdfs`; manager-only PDFs need `snapshot --pdfs all` first. `ask` needs a built index + `[llm]`. Local 7B can over-claim; check cited pages. — [docs/rag.md](file:///Users/89298/Documents/paperful/docs/rag.md)

**Snowball vs fill.** Snowball creates **metadata parents** under an explicit gate; `run` still fills PDFs (unless `fetch_pdfs` calls `run` in-process on new keys). Stranger default: dry-run, no library writes, no downloads. — [docs/ROADMAP.md — Snowball](file:///Users/89298/Documents/paperful/docs/ROADMAP.md)

**Stopping rules shipped, off by default.** `[snowball].stop_rule`; `snowball continue` after Keep/Skip. No recall percentage in copy. PRISMA counts **not** shipped (borrow list). — [docs/ROADMAP.md — Snowballing and review methods](file:///Users/89298/Documents/paperful/docs/ROADMAP.md); [docs/commands.md — `snowball`](file:///Users/89298/Documents/paperful/docs/commands.md)

**MCP is read-only.** Tools: `gaps`, `snowball_search`, `snowball_trends`, `export`, `proposal_export`, `refs_gap`, `ask`. No `--apply`. Chat that mutates Zotero stays zotero-mcp. — [docs/commands.md — `mcp`](file:///Users/89298/Documents/paperful/docs/commands.md); [docs/comparison.md — Where Paperful sits](file:///Users/89298/Documents/paperful/docs/comparison.md)

**Near-term research-ops rows 1–24 shipped** (including literature-discovery waves 1–3). Wave 4 precedent pack is **roadmap**. — [docs/ROADMAP.md — Near-term research-ops](file:///Users/89298/Documents/paperful/docs/ROADMAP.md); [docs/ROADMAP.md — Literature-discovery complement (waves)](file:///Users/89298/Documents/paperful/docs/ROADMAP.md)

### Inferences
- A “factory” already exists as a **playbook of verbs** (`research-pack.md`) with human gates, not as a single autonomous pipeline.
- Strongest shipped stages vs competitors: **acquire missing PDFs**, **disk mirror/restore**, **campus EZProxy + grey playbooks**, **local RAG over your PDFs**.
- Weakest vs a full factory: **write** (`stuff` unshipped), **SR screening / PRISMA**, **living synthesis with receipts**, **corpus-scale discovery** (intentionally complementary).

### Gaps
- No in-repo definition of “academic-paper factory” stages; mapping above is the assignment’s list laid onto docs, not a product term Paperful uses.
- `paperful jobs` grouping was not executed in this pass; inventory uses `commands.md` table + why.md jobs.
- Implementation vs docs drift was not verified in Python (assignment: docs + CLI verbs).

## What is explicitly out of scope in v1 and why?

### Takeaway
v1 (1.0/1.1 trust + Wanted promise) is **local, Zotero-proven, disk-first fill**. Out of near-term scope is hosted multi-user, replacing Zotero’s reader, Sci-Hub as default, qualitative coding, and Kosmos-class autonomous science — because those break Control (opt-in sources, dry-run, fail-closed) or the “find missing PDFs” pitch.

### Cited Findings

**ROADMAP — Explicitly out of near-term scope** (heading): hosted multi-user service; replacing Zotero as a reading UI; shipping Sci-Hub or proxy abuse as defaults (opt-in + presets stay); Jeffersonian transcription / qualitative coding apps; autonomous AI-scientist loops (Kosmos-class world models, multi-hour code execution, publication-from-dataset), experimental-data pipelines (RNA-seq / flow cytometry), molecular design. Point people at Edison Scientific; keep Paperful on library / find / completeness / mirror / control. — [docs/ROADMAP.md — Explicitly out of near-term scope](file:///Users/89298/Documents/paperful/docs/ROADMAP.md)

**comparison.md — What Paperful does not do today:** Mendeley/EndNote seeking testers; author-folder / tablet send/get; Mendeley/EndNote item merge; two-up scan split or chat agent over the library; hosted multi-user; autonomous AI-scientist / experimental kernels / molecular design; Jeffersonian transcription. — [docs/comparison.md — What Paperful does not do today](file:///Users/89298/Documents/paperful/docs/comparison.md)

**why.md — What is true today:** “Linked-file cutover, hosted multi-user service, a second reading app — Cutover is `attachments --link --apply` (off by default; personal library only). Hosted service and a second reading app are not the product.” — [docs/why.md — What is true today](file:///Users/89298/Documents/paperful/docs/why.md)

**Findability / launch (why v1 copy stays narrow):** Own one search phrase: **“find missing PDFs in Zotero”**. Keep Ask, Discover, and snowball out of the title, meta, share card, and GitHub About. Never promise “every paywalled PDF”. Never mention Sci-Hub in copy, keywords, or alt text. Never call Camofox “stealth”. — [docs/ROADMAP.md — Findability and launch](file:///Users/89298/Documents/paperful/docs/ROADMAP.md)

**Core trust rule:** Do **not** grow it into a second product (no auto Sci-Hub, no “AI fetch everything”). — [docs/ROADMAP.md — 0.1 → 1.0](file:///Users/89298/Documents/paperful/docs/ROADMAP.md) (section “0.1 → 1.0 (trust + mirror contract)”)

**Zotero-RAG non-goals:** replacing Zotero’s reader; cloud-default RAG; answers without citations; auto-mutating parent metadata from Q&A; scheduling nightly “ask everything”; Edison Literature over a vendor corpus as the Ask path. — [docs/ROADMAP.md — Zotero-RAG integration](file:///Users/89298/Documents/paperful/docs/ROADMAP.md)

**Critique non-goals:** not a referee, not Google Deep Review; does not upload the manuscript, search the web, or call a similarity API. — [docs/critique.md](file:///Users/89298/Documents/paperful/docs/critique.md)

**Authorwatch non-goals:** live social scrape; auto-friending; cloud “who to follow”; social HTML as a `run` PDF source. — [docs/ROADMAP.md — Author watch lists](file:///Users/89298/Documents/paperful/docs/ROADMAP.md)

**Snowball out of this lane:** hosted discovery service; built-in scheduler; dedicated screening TUI; Sci-Hub/Scholar as discovery sources; every publication of every cited author. — [docs/snowball.md — Out of this lane](file:///Users/89298/Documents/paperful/docs/snowball.md)

**Product split post-1.0 (not v1):** local OpenAlex 2C full search; Firefox extension (implemented but not a 1.0 gate); SaaS tenancy polish. — [docs/ROADMAP.md — Product split](file:///Users/89298/Documents/paperful/docs/ROADMAP.md)

**GUI bind:** non-loopback requires `--allow-remote-bind` and still has **no HTTP auth**. — [docs/gui.md — Shell chrome](file:///Users/89298/Documents/paperful/docs/gui.md)

### Inferences
- “Out of v1” is a **trust + pitch** decision: Wanted must stay the public promise even when Discover/Ask already ship.
- Sci-Hub exists as **opt-in capability** (comparison tables say Yes) but is **out of default and out of marketing** — do not collapse those two facts.

### Gaps
- Exact legal/ToS written position is listed as an unowned trust gap (needed before paid/public), not a finished policy doc — [docs/ROADMAP.md — Trust, legal, privacy, sustainability](file:///Users/89298/Documents/paperful/docs/ROADMAP.md).

## Existing Edison notes already in ROADMAP/comparison — do not duplicate; list gaps vs a full factory

### Takeaway
Edison (Literature / Precedent / Kosmos / Analysis / Molecules) is **already tabulated** in comparison + ROADMAP borrow/non-goals. Thickening should add **factory-stage holes that Edison notes do not cover** (SR screening, `stuff`, PRISMA, grey watchers, Wanted excellence), not a second Edison analogue table.

### Cited Findings

**Already written — do not copy wholesale into new tables:**

- Routing row: hosted AI scientist → Edison; Paperful owns PDFs, disk mirror, Ask over *your* collection. — [docs/comparison.md — Short answer](file:///Users/89298/Documents/paperful/docs/comparison.md); [docs/comparison.md — Choosing in one glance](file:///Users/89298/Documents/paperful/docs/comparison.md)
- Capability matrix vs Valency / Edison / zotero-mcp (public corpus search, novelty claims, experimental analysis, local vs hosted). — [docs/comparison-reference.md — Hosted literature MCP](file:///Users/89298/Documents/paperful/docs/comparison-reference.md)
- Vendor note + typical stack: Edison Literature/Precedent → snowball / `ingest-dois` → `run` / Wanted → local `ask`. Do not treat their workspace as the quiet mirror. — [docs/comparison-reference.md — Edison Scientific](file:///Users/89298/Documents/paperful/docs/comparison-reference.md)
- Agent analogue table + **Borrow (local, dry-run default, fail closed)** 1–6 + **Non-goals (park, do not spike)**. — [docs/ROADMAP.md — Hosted AI scientists (Edison Scientific)](file:///Users/89298/Documents/paperful/docs/ROADMAP.md)
- Wave 4 = precedent pack (roadmap). Waves 1–3 shipped. — [docs/ROADMAP.md — Literature-discovery complement](file:///Users/89298/Documents/paperful/docs/ROADMAP.md)
- Parked: Kosmos-class autonomous scientist. — [docs/ROADMAP.md — Parked or hold](file:///Users/89298/Documents/paperful/docs/ROADMAP.md)

**Edison analogue vs Paperful today (from that table, for factory mapping only):**

| Edison agent | Paperful analogue today | Factory implication |
| --- | --- | --- |
| Literature (PaperQA3, 175M+ papers/trials/patents) | `ask` / `synthesize` / `rag` over **your** mirror | Synthesize stage is **held-PDF only**; no patents/trials index |
| Precedent (“has this been tried?”) | `refs gap`, coverage, similar hops, `ask --focus gaps` — **none claim absence** | Novelty pack is Wave 4, still must not claim “nobody has done this” |
| Kosmos (~1500 papers, ~42k LOC, world model) | **None.** Run witness + notes + RAG citations | No write/analyze/code stage |
| Analysis / Molecules | Out of jobs | Stay X at v2 |

— [docs/ROADMAP.md — Hosted AI scientists](file:///Users/89298/Documents/paperful/docs/ROADMAP.md)

**Gaps vs a full factory that Edison notes do not already list** (use these to thicken ROADMAP/comparison):

1. **Systematic include/exclude with reasons + PRISMA diagram** — bigger bet; SnowBallSLR interop parked; Discover Keep/Skip is not this. — [docs/ROADMAP.md — Bigger bets](file:///Users/89298/Documents/paperful/docs/ROADMAP.md); [docs/ROADMAP.md — Snowballing and review methods](file:///Users/89298/Documents/paperful/docs/ROADMAP.md)
2. **`stuff` (per-claim extra citations from local index)** — named, unshipped; writing stage. — [docs/ROADMAP.md — stuff](file:///Users/89298/Documents/paperful/docs/ROADMAP.md)
3. **Question generation from summaries** — RAG direction item 2 still roadmap. — [docs/ROADMAP.md — Zotero-RAG integration](file:///Users/89298/Documents/paperful/docs/ROADMAP.md)
4. **Annotation mirror** into `out/` for RAG. — [docs/ROADMAP.md — Annotation mirror](file:///Users/89298/Documents/paperful/docs/ROADMAP.md)
5. **Evidence-table export / claim tracking (supports/contrasts/mentions)** — stretch under Summaries, briefs, and Ask; also parked on `stuff` later slice. — [docs/ROADMAP.md — Summaries, briefs, and Ask](file:///Users/89298/Documents/paperful/docs/ROADMAP.md)
6. **Scheduled grey-literature host watching** (meeting docs / RFMO) — bigger bet; playbooks shipped, **scheduled watching** is not. — [docs/ROADMAP.md — Bigger bets](file:///Users/89298/Documents/paperful/docs/ROADMAP.md)
7. **OpenAlex topic follow / library gap map / grouping Wanted by subfield** — opportunity after Jan 2027 classifier; Paperful currently does not request topics. — [docs/ROADMAP.md — OpenAlex topics](file:///Users/89298/Documents/paperful/docs/ROADMAP.md)
8. **Wanted excellence** (stamps, miss reasons, snowball feeding Wanted) is **foundation shipped**; residual honesty polish, not Edison-shaped. — [docs/ROADMAP.md — Wanted](file:///Users/89298/Documents/paperful/docs/ROADMAP.md)
9. **Response-hash cache with drift classification** for watches (SnowBallSLR borrow, unshipped). — [docs/ROADMAP.md — Snowballing and review methods](file:///Users/89298/Documents/paperful/docs/ROADMAP.md)
10. **Shared lab library / collaboration without SaaS** (Syncthing/git, attach locks) — later; needs auth if tenancy. — [docs/ROADMAP.md — Maybe later §8](file:///Users/89298/Documents/paperful/docs/ROADMAP.md); [docs/ROADMAP.md — Bigger bets](file:///Users/89298/Documents/paperful/docs/ROADMAP.md)

### Inferences
- Factory v2 that stays honest is **local literature operations** (fill → screen → extract → grounded briefs → optional `stuff`), not Edison-in-Docker.
- Comparison thickening: add a **factory-stage** column (discover…export) with S/P/R/X; keep Edison as one complementary hosted row already written.

### Gaps
- This research did not re-audit Edison public docs; Edison claims are as already recorded in comparison-reference (last reviewed 2026-10-26, positioning not paid pilot).

## Concrete borrow list from typical competitors that would fit disk-first / local / dry-run / fail-closed bars

### Takeaway
Docs already mark **borrow shapes, do not vendor**. Fit bar: local or operator-cron, dry-run default, `--apply` for writes, fail closed, no “nobody has done this,” no hosted corpus as Ask. Below is a **deduped borrow list** (Edison/SnowBallSLR/Valency/plugins) tagged to factory stages; skip items already shipped.

### Cited Findings

**House bar (apply to every borrow):** dry-run default, explicit `--apply`, fail closed, no silent library writes. Same as research-ops and literature-discovery waves. — [docs/ROADMAP.md — Near-term research-ops](file:///Users/89298/Documents/paperful/docs/ROADMAP.md)

**Already borrowed/shipped (do not re-list as new work):** stopping rule (`marginal_yield` etc., off by default); MCP read tools waves 1–3; `refs gap` / coverage; `extract-sections`; `keepup`; Ask `--focus` / batch / `rag answered`; run witness.

| Borrow (source named in docs) | Factory stage | Fit / honesty | Status in docs |
| --- | --- | --- | --- |
| Precedent pack: `rag search` + OpenAlex not-in-library; stamp `held` vs `public-metadata-only`; never claim absence | Discover / synthesize | Local + OpenAlex metadata; dry-run pack + read-only MCP | **R** Wave 4 — [ROADMAP Hosted AI scientists](file:///Users/89298/Documents/paperful/docs/ROADMAP.md); [Literature-discovery Wave 4](file:///Users/89298/Documents/paperful/docs/ROADMAP.md) |
| Named MCP `JobNames`-style tools (`ask` vs precedent vs `refs_gap`) | Agent / keep current | Read-only; writes stay CLI `--apply` | **R** (partial: tools exist, job-shaped names not fully) — [Bigger bets](file:///Users/89298/Documents/paperful/docs/ROADMAP.md) |
| Conflicting-evidence `synthesize` / `--focus`; review-shaped layout (question → methods → findings → limits) | Synthesize | Over **your** PDFs only | **R** — [Summaries, briefs, and Ask](file:///Users/89298/Documents/paperful/docs/ROADMAP.md) |
| Figure/table pullouts from local PDFs (caption + page + stem); no diagram generation | Extract / synthesize | Files already on disk | **R** — same section |
| Study-design / work type in Ask ranking (OpenAlex fields already on citation map); **no** journal-quality score | Synthesize | Fail closed if field missing | **R** — Edison borrow #5 |
| Patents / trial registries as **thin DOI/registry ingest** after counting Wanted misses | Discover / acquire | Test before build; not a second PaperQA corpus | **R** test-first — [Discovery and sources](file:///Users/89298/Documents/paperful/docs/ROADMAP.md) |
| Audit-trail copy test: if we cannot click through, we do not write the sentence | Synthesize / critique | Kosmos bar as **copy test**, not world-model store | Stance — Edison borrow #4 |
| SnowBallSLR: response-hash cache + drift classification for watches | Keep current | Distinguishes new paper vs reassigned OpenAlex ID | **R** — [Snowballing and review methods](file:///Users/89298/Documents/paperful/docs/ROADMAP.md) |
| SnowBallSLR: PRISMA-style counts in run report (identified/screened/kept/added) | Screen / export | Counts only; no fake recall % | **R** |
| SnowBallSLR interop: export Discover queue as seeds/labels; import `included.csv` / RIS into Wanted | Discover ↔ screen | Reviewers chase there; Paperful does PDFs | **R** interoperate, do not vendor |
| Capture–recapture recall estimate | Screen | **Internal experiment only**; do not headline % | Park until validated — same section |
| EmbeddingGemma 2 as optional `[rag].embed_model` (Ollama text-only spike) | Extract / Ask | Local; do not change default until spike | **R** — [EmbeddingGemma 2](file:///Users/89298/Documents/paperful/docs/ROADMAP.md) |
| sqlite-vec as alternative store; “papers like this”; semantic dedupe; collection cluster map; ASReview-style screening; semantic snowball | Extract / screen / discover | Local embeddings; secondary screens | **R** buffet — [Local embeddings](file:///Users/89298/Documents/paperful/docs/ROADMAP.md) |
| `stuff`: sentence → `rag search` hits; no LLM prose | Write | Fail closed if index empty; no parent create | **R** — [stuff](file:///Users/89298/Documents/paperful/docs/ROADMAP.md) |
| Per-collection grounded brief with diffs + Zotero starred note | Synthesize / keep current | Citations to held passages only | **R** — [Summaries, briefs, and Ask](file:///Users/89298/Documents/paperful/docs/ROADMAP.md) |
| OSF Preprints as thin DOI source | Acquire | Count OSF-location misses first | **R** test-first — [Discovery and sources](file:///Users/89298/Documents/paperful/docs/ROADMAP.md) |
| Topic-native watches / library gap map (OpenAlex topic IDs, never cached assignments) | Discover / keep current | After housekeeping; pin IDs | **R** — [OpenAlex topics](file:///Users/89298/Documents/paperful/docs/ROADMAP.md) |
| Policy/grey host **watchers** (scheduled meeting docs) | Keep current / acquire | Playbooks exist; this is cron-shaped watching of those hosts | **R** bigger bet |
| Systematic-review mode (guided rounds, include/exclude reasons, PRISMA export, reproducible run file) | Screen + export | **Alongside** Wanted, not instead | **R** pick-at-most-one-year |
| Valency Bond as **complement** (discovery → snowball → Paperful PDFs) | Discover (external) | Do not host papers / Hub | Stance already in comparison-reference |
| zotero-agent `pdf-prep` two-up split | Extract | Leave to that CLI; Paperful `ocr` is text layer only | Complementary — [comparison.md](file:///Users/89298/Documents/paperful/docs/comparison.md) |
| Better BibTeX for CSL/Quarto | Write / export | Park as Paperful feature until testers ask | Parked — [ROADMAP Parked](file:///Users/89298/Documents/paperful/docs/ROADMAP.md) |
| Syncthing/git shared `state/` | Collaboration | Transport only; not a sync product | **R** Maybe later §8 |

**Does not fit the bar (docs say so):** wrapping Kosmos/Analysis/Molecules; uploading `out/` to vendor workspace as Ask; clinical-trial–native PaperQA; journal impact scores; Sci-Hub/LibGen as defaults; live social scrape; CAPTCHA bypass product; claiming completeness of “the literature” from OpenAlex metadata. — [docs/ROADMAP.md — Hosted AI scientists Non-goals](file:///Users/89298/Documents/paperful/docs/ROADMAP.md); [docs/ROADMAP.md — CAPTCHA / soft bot walls](file:///Users/89298/Documents/paperful/docs/ROADMAP.md)

### Inferences
- Highest-leverage borrows that still look like Paperful: **Wave 4 precedent pack**, **conflicting-evidence synthesize**, **`stuff` CLI pack**, **PRISMA counts**, **watch drift cache** — all packs on disk, no new hosted index.
- Anything that needs a **global full-text corpus** should stay “interoperate with Bond/Edison,” not a Paperful stage.

### Gaps
- Competitor feature lists in comparison.md are “public docs and positioning — not paid pilots” (last reviewed 2026-10-26). This note does not independently verify those products.
- No additional competitors were mined from code beyond those named in comparison.md / comparison-reference.md / ROADMAP (assignment: internal only).

## What must stay out even at v2 (hosted multi-user, Kosmos code kernel, Sci-Hub default, replacing Zotero reader)

### Takeaway
v2 can thicken factory stages **on disk** without becoming Edison or a citation-manager clone. Four hard stays: **no hosted multi-user**, **no Kosmos code kernel / world model**, **Sci-Hub never default (and never in marketing)**, **Zotero remains reader/catalogue**. Plus: no “nobody has done this,” no Jeffersonian/qualitative product, no Analysis/Molecules.

### Cited Findings

| Must stay out | Why (from docs) | Source |
| --- | --- | --- |
| Hosted multi-user / SaaS tenancy as the product | Explicitly out of near-term scope; parked “SaaS / tenancy”; GUI is 127.0.0.1, no HTTP auth on remote bind | [ROADMAP Explicitly out](file:///Users/89298/Documents/paperful/docs/ROADMAP.md); [ROADMAP Parked](file:///Users/89298/Documents/paperful/docs/ROADMAP.md); [gui.md](file:///Users/89298/Documents/paperful/docs/gui.md) |
| Kosmos-class loop (world model, multi-hour code execution, ~1500 papers + analysis kernel) | Bigger bets: do **not** take that Edison bet; parked; Analysis/Molecules out of jobs | [ROADMAP Bigger bets](file:///Users/89298/Documents/paperful/docs/ROADMAP.md); [ROADMAP Hosted AI scientists Non-goals](file:///Users/89298/Documents/paperful/docs/ROADMAP.md) |
| Sci-Hub (or LibGen) as **default** source | Opt-in + presets stay; never in copy/keywords/alt; LibGen same opt-in bar **if ever**, park until testers ask | [ROADMAP Explicitly out](file:///Users/89298/Documents/paperful/docs/ROADMAP.md); [ROADMAP Findability](file:///Users/89298/Documents/paperful/docs/ROADMAP.md); [ROADMAP Parked](file:///Users/89298/Documents/paperful/docs/ROADMAP.md) |
| Replacing Zotero as reading UI / second reading app | “not the product”; GUI has no embedded PDF viewer; annotation mirror is read-sync into `out/`, never replace Zotero annotation UI; Firefox add-on is not a Connector replacement | [why.md What is true today](file:///Users/89298/Documents/paperful/docs/why.md); [gui.md](file:///Users/89298/Documents/paperful/docs/gui.md); [ROADMAP Annotation mirror](file:///Users/89298/Documents/paperful/docs/ROADMAP.md); [ROADMAP Firefox](file:///Users/89298/Documents/paperful/docs/ROADMAP.md) |
| Uploading quiet mirror into vendor workspace as Ask | Edison non-goal | [ROADMAP Hosted AI scientists](file:///Users/89298/Documents/paperful/docs/ROADMAP.md) |
| Claiming literature completeness / “has never been done” | Precedent analogue must not; OpenAlex is metadata | Same; [comparison-reference Edison](file:///Users/89298/Documents/paperful/docs/comparison-reference.md) |
| Jeffersonian transcription / qualitative coding | Explicit out | [ROADMAP Explicitly out](file:///Users/89298/Documents/paperful/docs/ROADMAP.md); [comparison.md](file:///Users/89298/Documents/paperful/docs/comparison.md) |
| Auto Sci-Hub / “AI fetch everything” / CAPTCHA bypass product | 1.0 trust; CAPTCHA open: do not ship a bypass | [ROADMAP 0.1→1.0](file:///Users/89298/Documents/paperful/docs/ROADMAP.md); [ROADMAP CAPTCHA](file:///Users/89298/Documents/paperful/docs/ROADMAP.md) |
| Valency Hub–style publishing | Out of library/mirror jobs | [comparison-reference Valency](file:///Users/89298/Documents/paperful/docs/comparison-reference.md); [Literature-discovery non-goals](file:///Users/89298/Documents/paperful/docs/ROADMAP.md) |
| Critique as referee with scores | No score/grade/accept-reject | [critique.md](file:///Users/89298/Documents/paperful/docs/critique.md) |
| Built-in email scheduler as a hosted alert product | keepup: you cron; no email | [keepup.md](file:///Users/89298/Documents/paperful/docs/keepup.md) |
| Catalogue unification (all managers equal) without tester evidence | Parked; Mendeley/EndNote seeking testers; not 1.0 blockers | [ROADMAP Parked](file:///Users/89298/Documents/paperful/docs/ROADMAP.md); [why.md](file:///Users/89298/Documents/paperful/docs/why.md) |

**Shared lab library** is a **maybe** at v2 only as Syncthing/git, not tenancy — still “needs authentication, so later.” Do not market as hosted multi-user. — [docs/ROADMAP.md — Bigger bets](file:///Users/89298/Documents/paperful/docs/ROADMAP.md)

### Inferences
- v2 language can say “local paper factory **for a library you already keep**” if every stage still ends in `out/` + optional `--apply`.
- Opt-in Sci-Hub remaining in the **capability** table is compatible with “must stay out as default.”

### Gaps
- Assignment listed four hard outs; docs add several siblings (Jeffersonian, Hub, completeness claims). Writer should keep the four as slogans and the siblings as footnotes, not drop them.

## Suggested v2 framing language that does not break v1 trust (Wanted/PDF fill still the 1.x promise)

### Takeaway
Keep **1.x = find missing PDFs in Zotero (Wanted) + honest disk mirror**. Frame v2 as **optional stages after the ledger is honest** — the research-pack spine — not a rename of the product to “AI scientist” or “factory that writes papers.”

### Cited Findings

**v1 pitch already locked:** “the clean-up step that comes after discovery tools, not a rival to them.” “Never promise every paywalled PDF.” Own **“find missing PDFs in Zotero”**. Keep Ask/Discover/snowball out of title/meta/share/GitHub About. PyPI README leads with Wanted. Hold Repair and further Ask until Wanted proves out. — [docs/ROADMAP.md — Findability and launch](file:///Users/89298/Documents/paperful/docs/ROADMAP.md)

**Working stance:** Keep Wanted excellent as the one main lane (foundation shipped); bigger bets wait until that lane stays boring. Open question: what would make a researcher open Paperful every week, not just once to fill gaps? — [docs/ROADMAP.md — After 1.1.0](file:///Users/89298/Documents/paperful/docs/ROADMAP.md)

**Jobs copy:** “Paperful is a research helper for a reference library you already keep. It cleans the records, finds missing PDFs, and summarises papers, then keeps a platform-agnostic mirror… The work stays on this machine.” — [docs/why.md](file:///Users/89298/Documents/paperful/docs/why.md)

**Complement not clone:** Bond/Edison when the question is the public literature; Paperful when the question is fill, fix, mirror, and reason over **this** collection. — [docs/comparison-reference.md — Edison / Valency](file:///Users/89298/Documents/paperful/docs/comparison-reference.md)

**Research pack already uses factory-like sequencing without claiming autonomy.** — [docs/research-pack.md](file:///Users/89298/Documents/paperful/docs/research-pack.md)

**Honesty bar for “learns” copy (grey lanes, later):** “learns” = this machine’s `state/` + promoted playbooks, not a shared model; no paywall bypass; no universal completeness. — [docs/ROADMAP.md — Maybe later, not core §2](file:///Users/89298/Documents/paperful/docs/ROADMAP.md)

### Inferences — suggested phrases (for ROADMAP/comparison thickening, not committed marketing)

Safe **1.x** (unchanged): “Find missing PDFs in Zotero. Preview, grab to disk, attach when you say so.”

Safe **v2 subtitle / buffet framing** (does not replace 1.x):

- “After the Wanted list is honest: grow the collection, keep it current, and ask **your** PDFs.”
- “A local literature workbench: same CLI honesty (dry-run, `--apply`, fail closed) across discover → fill → extract → brief → optional critique.”
- “Not a hosted AI scientist. Complementary to Edison/Valency: they search the public record; Paperful fills and reasons over the library on this machine.”
- “Factory means a **playbook of gated verbs**, not an overnight PhD.”

Avoid in v1 or v2 public copy:

- “AI fetch everything,” “stealth,” Sci-Hub, “has nobody done this,” “replaces Zotero,” “Kosmos/autonomous scientist,” “we found ~85% of the literature,” scores/grades on critique, “hosted multi-user.”

Versioning suggestion consistent with docs: **1.x = Wanted + mirror contract**; **buffet / v2 = named packs** (precedent, stuff, conflicting-evidence synthesize, SR mode or grey watchers — pick at most one big bet a year) that stay off until `[llm]`/`[rag]`/gates.

### Gaps
- Docs never use the product name “v2 academic-paper factory”; any public use of “factory” would be new language and should stay internal until Wanted tester evidence exists ([ROADMAP After 1.1.0 working stance](file:///Users/89298/Documents/paperful/docs/ROADMAP.md)).
- Whether Ask stays third on default nav is an open question — do not freeze v2 UI copy on Ask-as-home. — [docs/ROADMAP.md — Open questions](file:///Users/89298/Documents/paperful/docs/ROADMAP.md)
