# Social discovery of Paperful-adjacent tools (2025–2026)

Research date: 2026-11-26. Scope: Reddit, Hacker News, product sites, GitHub activity. **X/Twitter search was unavailable** in this environment (X plugin `user-not-enrolled` / pay-per-use; Cursor `XSearch` not available for this account)—treat X signal as a documented gap below.

Already covered in Paperful comparison (do not treat as gaps): Elicit, Consensus, Undermind, SciSpace, Scite, Edison Scientific, Valency, OpenResearch, PaperOrchestra, PaperQA2, zotero-zotadata, StorScan/Attanger/ZotMoov, zotero-agent, named zotero-mcp forks (richardjlyon / cookjohn / Xevos117), Research Rabbit / Litmaps / Connected Papers (snowball docs), NotebookLM (as Gemini Notebook), Covidence/Rayyan/ASReview, Jenni/Paperpal, Sakana AI Scientist, SummarizePaper, PaperGuard, bib tools, paperscraper.

**Verdict shorthand for report writer:** ADD = likely missing from comparison and worth a row or reference note; WATCH = real but niche/early/overlapping; SKIP = noise, abandoned, or already covered.

---

## What tools do academics recommend now for Zotero PDF management, lit-review automation, local RAG, research agents, citation managers, and AI peer review?

### Takeaway
Community recommendations cluster into (1) hosted lit discovery already in Paperful’s table, (2) a **rising Zotero×AI layer** (DeepTutor, SeerAI, 54yyyu/zotero-mcp, Zoteus) largely **absent from Paperful docs**, (3) **OA missing-PDF plugins** adjacent to Paperful’s fetch job (Littview OpenAlex PDF), and (4) **lit-review workspaces** (moara.io, LuminaReviewer, Literfy) that sit between Zotero and Elicit-class tools.

### Cited Findings

**Zotero PDF / library hygiene**
- r/zotero users still ask for Sci-Hub-style auto-fetch; the long-lived `zotero-scihub` plugin is reported broken on Zotero 7 and unmaintained since ~2022 — [r/zotero Sci-Hub plugin thread (2024-04-13)](https://www.reddit.com/r/zotero/comments/1c2y9jr/is_there_a_plugin_that_can_pull_papers_directly/); [Zotero 7 scihub breakage (2024-08-23)](https://www.reddit.com/r/zotero/comments/1ezjz8s/right_click_on_item_to_fetch_pdf_via_sci_hub_on/).
- **Littview OpenAlex PDF Finder** (GitHub `Littview/zotero-openalex-pdf`, created 2026-10-03, ~6★ as of 2026-11-26) was launched on r/zotero as a free OA-only complement when built-in Find Available PDF misses DOI-less Scopus exports — [r/zotero post (2026-10-03)](https://www.reddit.com/r/zotero/comments/1wx0dtk/i_made_a_free_plugin_that_finds_openaccess_pdfs/); [product write-up](https://www.littview.com/blog/zotero-openalex-pdf-finder); [repo](https://github.com/Littview/zotero-openalex-pdf). **Buzz matches a real shipped .xpi** (releases active through mid-Nov 2026).
- **Paperpile** remains the most-cited paid Zotero alternative in r/PhD for PDF→metadata, campus proxy PDF grab, Google Drive storage, Overleaf — [r/PhD switching thread (2025-09-23)](https://www.reddit.com/r/PhD/comments/1nom7js/is_switching_to_zotero_worth_it/); [r/PhD write-up tools (2026-01-23)](https://www.reddit.com/r/PhD/comments/1ql64tl/software_for_phd_write_up_and_any_other_tips/). Zotero itself still wins “default free” votes; no viral “Zotero killer” product dominates 2025–2026 PhD threads.

**Literature review automation (hosted)**
- Grad-student roundups in 2026 still name **Elicit** (discovery), **Consensus** (focused evidence Q), **SciSpace** (per-paper reading), **NotebookLM** (upload-your-sources synthesis), plus Zotero+Claude paste workflows — [r/AIToolsAndTips (2026-05-21)](https://www.reddit.com/r/AIToolsAndTips/comments/1tje38x/best_ai_tools_for_literature_reviews_in_2026_i/); [r/PhD lit-review AI (2026-06 / comments into 2026-10)](https://www.reddit.com/r/PhD/comments/1ufe00o/best_literature_review_ai_tool/).
- Paid-stack advice: do **not** pay for Elicit + SciSpace + Consensus together; prefer one research tool + a general LLM; Consensus often preferred for focused questions when already on Perplexity Pro — [r/PhdProductivity (2026-07 / Aug comments)](https://www.reddit.com/r/PhdProductivity/comments/1ulxxi0/what_paid_research_aillm_are_you_using/).
- **Undermind** is actively recommended by a professor-suggested workflow and by an academic librarian for citation-mapping / early field maps; weaknesses: Semantic Scholar corpus bias, slow runs — [r/PhdProductivity (2026-03-18)](https://www.reddit.com/r/PhdProductivity/comments/1rx5gqr/a_discussion_and_suggestion_on_ai_use_again_i_know/); librarian product review [JCHLA 2025-08-01](https://journals.library.ualberta.ca/jchla/index.php/jchla/en/article/view/29854); still live Nov 2026 — [Verdict status](https://verdict.tools/status/undermind); HN praise snippet [2025-07-03](https://news.ycombinator.com/item?id=44458353).
- **Literfy** (`literfy.ai`) appears in the May 2026 lit-review roundup as a select-papers-then-write tool with figure generation — [r/AIToolsAndTips (2026-05-21)](https://www.reddit.com/r/AIToolsAndTips/comments/1tje38x/best_ai_tools_for_literature_reviews_in_2026_i/); [site](https://literfy.ai/). Thread reads partly promotional; product is real.
- **moara.io** is an AI lit-review workspace (library + agent + editor) with Zotero import, LibKey full-text, screening views; librarian review published 2026-07-30 — [Katina Magazine](https://katinamagazine.org/content/article/resource-advisor/2026/can-an-ai-integrated-platform-improve-lit-review); [moara.io](https://www.moara.io/); soft-launched into r/PhD comments as “Zotero meets ChatGPT” — [r/PhD ref managers (2025-10-09 comment)](https://www.reddit.com/r/PhD/comments/1o28j2w/best_reference_management_software/).
- **LuminaReviewer** marketed as end-to-end SR (search, snowball, AI-ranked screening, dual review, OA PDF attach, PRISMA) — [luminareviewer.com](https://luminareviewer.com/); named in r/research as a pipeline consolidator vs Rayyan+Covidence+Elicit — [r/research (2026-03-07)](https://www.reddit.com/r/research/comments/1r9e13r/ai_tools_for_systematic_review_and_metaanalysis/).

**Local RAG over papers / Zotero chat**
- Practical local stack still recommended: export Zotero PDFs → **Open WebUI** or **AnythingLLM** + Ollama embeddings — [Stephen Turner blog (2025-04-05)](https://blog.stephenturner.us/p/local-rag-app-open-webui-zotero-library).
- **PaperQA2** remains the named OSS “local PaperQA” with ZoteroDB helper; Future House/Edison continue shipping (PaperQA3 multimodal for hosted Literature, 2026-02-18) — [repo](https://github.com/Future-House/paper-qa) (~9.6k★); [PaperQA3 announcement](https://edisonscientific.com/news/edison-literature-agent); earlier HN [2025-03-05](https://news.ycombinator.com/item?id=43268330).
- **DeepTutor** (KnoWhiz): Zotero fork embedding library-wide chat / Graph RAG / arXiv; Show HN 2025-10-22 (5 pts, AGPL discussion); Reddit update 2026-07-03 claims 4,000+ users and library-wide auto-context — [HN](https://news.ycombinator.com/item?id=45663884); [r/zotero](https://www.reddit.com/r/zotero/comments/1um4d7k/deeptutor_update_ask_questions_across_your_zotero/); [Product Hunt](https://www.producthunt.com/products/deeptutor); [DeepTutorZotero repo](https://github.com/KnoWhiz/DeepTutorZotero) (low star count; product is primarily commercial+fork, not star-driven).
- **SeerAI** (`dralkh/seerai`, ~97★, created 2025-12-10): Zotero plugin for local Ollama/LM Studio RAG, federated search, OCR — recommended in r/LocalLLaMA as SciSpace alternative — [comment on older thread](https://www.reddit.com/r/LocalLLaMA/comments/1dlw92m/local_alternative_to_scholargpt_scispace/); [repo](https://github.com/dralkh/seerai).
- DIY: `Cyb3rDudu/axiom` (Zotero-backed personal RAG, ~3★) shared in r/LocalLLaMA Sept 2026 — [thread](https://www.reddit.com/r/LocalLLaMA/comments/1w79gag/how_do_you_guys_handle_your_personal_rag_setup/); [repo](https://github.com/Cyb3rDudu/axiom). Sentiment in that thread: hybrid FTS+vector preferred; pure vector RAG often unreliable.

**Research agents / MCP**
- **54yyyu/zotero-mcp** is the viral MCP: Show HN 2025-04-28; **~6,077★** by 2026-11-26; r/zotero roundup of MCP options July 2025 lists it first — [HN](https://news.ycombinator.com/item?id=43824520); [r/zotero MCP thread (2025-07-03)](https://www.reddit.com/r/zotero/comments/1lqjpl6/anyone_using_zotero_with_mcp_model_context/); [repo](https://github.com/54yyyu/zotero-mcp); author write-up [stevenyuyy.com](https://stevenyuyy.com/zotero-mcp/). **Not named in Paperful comparison** (docs cite other forks only).
- **Zoteus** (`oscardvs/zoteus`, ~68★, MIT; site zoteus.com): MCP with passage locators, OA attach via OpenAlex, scholar graph, optional hosted — [r/zotero (2026-09-08)](https://www.reddit.com/r/zotero/comments/1wag8ux/zoteus_an_opensource_mcp_server_for_zotero_with/); [repo](https://github.com/oscardvs/zoteus).
- **paperboy** MCP: search → Zotero queue → e-reader; Show HN 2026-07-13 (2 pts) — [HN](https://news.ycombinator.com/item?id=48895810); [repo](https://github.com/michaelellis003/paperboy).
- Edison Scientific spinout + **Kosmos** AI scientist (2025-11-05) and PaperQA3 (2026-02) are the loudest “AI scientist” launches adjacent to PaperQA — already comparison-covered; social/academic press confirms they are not abandoned — [Edison announcement](https://www.futurehouse.org/news/announcing-edison-scientific); [Kosmos](https://edisonscientific.com/news/announcing-kosmos).

**AI peer review**
- Little community signal for dedicated “AI peer review” products beyond SciSpace “Deep Review” marketing copy and general LLM critique workflows; Paperful’s peer-review lane competitors are not a hot Reddit/HN topic in 2025–2026 samples. SciSpace vs Elicit SEO-style comparison emphasizes SciSpace critique mode — [r/bestaitools2025](https://www.reddit.com/r/bestaitools2025/comments/1pdfkgl/scispace_vs_elicit_in_2025/) (treat as low-trust promotional).

### Inferences
- The largest **doc gap vs social reality** is the **Zotero×agent layer**: 54yyyu/zotero-mcp’s star count and Reddit mindshare dwarf the forks Paperful currently cites.
- Missing-PDF social pain is still real; new OA plugins (Littview) compete on the *same job* as Paperful `run` for OA-only cases, without campus-proxy/grey/mirror ledger.
- Hosted lit tools are **stable incumbents**, not abandoned; researchers complain about **overlap and hallucination**, not about a single winner displacing Elicit.

### Gaps
- No direct X/Twitter citations for 2025–2026 (API/tools unavailable).
- Systematic Discord/Slack academic communities not indexed; cannot quantify private lab Discord buzz.
- Independent verification of DeepTutor’s “4,000+ users” claim beyond vendor Reddit post.

---

## Viral launches and “Zotero killer” / “Elicit alternative” / “local PaperQA” / “research MCP” threads (2025–2026)

### Takeaway
No true “Zotero killer” went viral. The sticky launches are **MCP bridges into Zotero**, **DeepTutor’s in-Zotero chat**, and **Edison/Kosmos/PaperQA3** on the AI-scientist side. “Elicit alternative” discourse recycles Consensus / SciSpace / Undermind / NotebookLM rather than crowning a new 2026 disruptor.

### Cited Findings
- DeepTutor Show HN (2025-10-22): low points (5), AGPL compliance question, founder claims 200 beta researchers in 48h — [HN item 45663884](https://news.ycombinator.com/item?id=45663884). Follow-up Show HN paper→code→notebook (2026-01-27) even quieter (2 pts) — [HN 46775935](https://news.ycombinator.com/item?id=46775935).
- Early “AI assistant inside Zotero” tester call (HN, ~2025-07, 10 pts) — likely same product lineage — [HN 44467159](https://news.ycombinator.com/item?id=44467159).
- Zotero-MCP Show HN (2025-04-28, 10 pts) → became the high-star standard — [HN 43824520](https://news.ycombinator.com/item?id=43824520).
- paperboy Show HN (2026-07-13, 2 pts) — niche MCP — [HN 48895810](https://news.ycombinator.com/item?id=48895810).
- Gamma PDF “AI-native PDF reader, self-hosted” Show HN (2026-11-14, 11 pts) — adjacent reader, not Zotero workbench — [HN 50495073](https://news.ycombinator.com/item?id=50495073); [gammapdf.com](https://gammapdf.com/).
- PaperQA2 HN threads exist (2024–2025); 2025-03 RAG-Arena claim post — [HN 43268330](https://news.ycombinator.com/item?id=43268330). “Local PaperQA” in practice = PaperQA repo + Open WebUI/AnythingLLM recipes, not a new branded fork.
- OpenResearch (`orx`) had **no HN Algolia hits** in this search window; social discovery for it is thin relative to Paperful’s already covering it via product docs.
- Reddit “Elicit alternative” framing stays comparative among known vendors — [2026 lit-review tools](https://www.reddit.com/r/AIToolsAndTips/comments/1tje38x/best_ai_tools_for_literature_reviews_in_2026_i/); [paid research AI](https://www.reddit.com/r/PhdProductivity/comments/1ulxxi0/what_paid_research_aillm_are_you_using/).

### Inferences
- Viral energy in this niche shifted from **new citation managers** to **MCP + in-app AI** bolted onto Zotero.
- Paperful’s differentiators (campus proxy, grey playbooks, disk mirror/restore) barely appear in these social threads—communities talk about chat/RAG/discovery, not restore ledgers.

### Gaps
- Could not enumerate X launch threads for Kosmos / PaperQA3 / Valency Bond.
- Algolia HN search for `OpenResearch` returned 0 hits; may under-index GitHub-only launches.

---

## Sentiment: which listed tools are praised vs abandoned?

### Takeaway
Among tools Paperful already lists, **none of the major hosted names show abandonment signals** in 2025–2026 community sources. Praise is **conditional** (use for discovery, verify PDFs). The clearest abandonment signal is **legacy Sci-Hub Zotero plugins**, not Elicit-class products.

### Cited Findings

| Tool | Sentiment signal | Source |
|------|------------------|--------|
| **Elicit** | Still recommended for discovery / early exploration; not trusted alone for thesis synthesis | [r/AIToolsAndTips 2026-05](https://www.reddit.com/r/AIToolsAndTips/comments/1tje38x/best_ai_tools_for_literature_reviews_in_2026_i/); [r/PhD](https://www.reddit.com/r/PhD/comments/1ufe00o/best_literature_review_ai_tool/) |
| **Consensus** | Preferred single paid lit tool for focused Qs; “deep research” praised | [r/PhdProductivity 2026](https://www.reddit.com/r/PhdProductivity/comments/1ulxxi0/what_paid_research_aillm_are_you_using/) |
| **SciSpace** | Useful as PDF reading assistant; overlapping subscriptions discouraged | Same threads |
| **Undermind** | Praised for deep citation mapping; slow; corpus gaps in humanities; **not shutting down** as of 2026-11-26 | [r/PhdProductivity](https://www.reddit.com/r/PhdProductivity/comments/1rx5gqr/a_discussion_and_suggestion_on_ai_use_again_i_know/); [Verdict](https://verdict.tools/status/undermind); [JCHLA review](https://journals.library.ualberta.ca/jchla/index.php/jchla/en/article/view/29854) |
| **Scite** | Still named for citation context (support/refute) | [r/PhD comment](https://www.reddit.com/r/PhD/comments/1ufe00o/best_literature_review_ai_tool/) |
| **PaperQA / Edison** | Active OSS + commercial path; PaperQA3 launch Feb 2026; Kosmos Nov 2025 | [PaperQA3](https://edisonscientific.com/news/edison-literature-agent); [Edison spinout](https://www.futurehouse.org/news/announcing-edison-scientific) |
| **NotebookLM** | Frequently praised for grounded synthesis on *user-selected* PDFs | [r/AIToolsAndTips 2026-05](https://www.reddit.com/r/AIToolsAndTips/comments/1tje38x/best_ai_tools_for_literature_reviews_in_2026_i/) |
| **Research Rabbit** | Still named for graph discovery alongside Elicit/Consensus | [r/PhD](https://www.reddit.com/r/PhD/comments/1ufe00o/best_literature_review_ai_tool/) |
| **zotero-scihub** | **Abandoned / broken** on Zotero 7 | [r/zotero](https://www.reddit.com/r/zotero/comments/1ezjz8s/right_click_on_item_to_fetch_pdf_via_sci_hub_on/) |
| **Mendeley** | Mixed; some switch to Zotero, some stay for Word plugin | [r/PhD 2025-09](https://www.reddit.com/r/PhD/comments/1nom7js/is_switching_to_zotero_worth_it/) |
| **AnythingLLM** | Used but called “clunky” by some local RAG users vs custom stacks | [r/LocalLLaMA 2026-09](https://www.reddit.com/r/LocalLLaMA/comments/1w79gag/how_do_you_guys_handle_your_personal_rag_setup/) |

### Inferences
- Paperful should not drop Undermind/Elicit/etc. from comparison on “abandonment” grounds.
- Social frustration concentrates on **hallucinated synthesis** and **subscription overlap**, which reinforces Paperful’s “held PDFs / no invented cites” positioning—but that positioning is rarely articulated by users unless they already care about library mirrors.

### Gaps
- No quantitative abandonware scan of every comparison-table row (Valency, PaperOrchestra, OpenResearch social volume thin).
- Sentiment aggregators (e.g. RightAIChoice Undermind page) are secondary; prefer primary Reddit/HN/librarian reviews above.

---

## Tools frequently mentioned that Paperful docs omit — ADD / WATCH / SKIP

### Takeaway
Highest-priority omissions: **54yyyu/zotero-mcp**, **DeepTutor**, **SeerAI**, **Littview OpenAlex PDF**, **moara.io**, and **Zoteus**. Several others are real but niche.

### Cited Findings — candidate ledger

| Candidate | Verdict | Why | Buzz ↔ product? |
|-----------|---------|-----|-----------------|
| **54yyyu/zotero-mcp** | **ADD** | Dominant Zotero MCP (~6k★); Reddit/HN mindshare; docs only list other forks | Yes — active repo + Show HN + blog |
| **DeepTutor** (knowhiz) | **ADD** | In-Zotero chat/RAG fork; HN + r/zotero 2025–2026; closest “chat your library” competitor UX | Yes — site, PH, OSS forks; user-count claim unverified |
| **Littview zotero-openalex-pdf** | **ADD** | Direct OA missing-PDF competitor/complement to Paperful `run` for DOI-less imports | Yes — Oct 2026 launch, releases, blog |
| **SeerAI** | **ADD** | Local Zotero AI plugin (Ollama RAG); LocalLLaMA recommendation | Yes — public repo ~97★ |
| **Zoteus** | **ADD** (MCP ecosystem note) | Newer MCP with passage locators + OA attach + OpenAlex scholar tools | Yes — MIT repo + zoteus.com + r/zotero |
| **moara.io** | **ADD** / **WATCH** | AI lit-review workspace with Zotero import + LibKey; librarian-reviewed 2026 | Yes — Katina review + product site |
| **LuminaReviewer** | **WATCH** | SR pipeline consolidator with OA PDF + PRISMA; overlaps Covidence/Rayyan row | Yes — site; Reddit mention sparse |
| **Literfy** | **WATCH** | Select-papers lit-review writer; appears in 2026 roundup | Yes — literfy.ai; social may be self-promo |
| **paperboy MCP** | **WATCH** | Zotero + e-reader delivery via Claude | Yes — small Show HN + repo |
| **Open WebUI / AnythingLLM + Zotero** | **WATCH** (pattern, not vendor row) | Default DIY local RAG recipe in blogs/LocalLLaMA | Yes — documented workflows |
| **Paperpile** | **WATCH** | Persistent paid citation-manager alternative; campus PDF proxy praised | Yes — long-standing product |
| **Gamma PDF** | **WATCH** | Self-hosted AI PDF reader (Nov 2026 HN) | Yes — early Show HN |
| **axiom (Cyb3rDudu)** | **SKIP** / personal WATCH | DIY Zotero RAG; tiny star count | Real but individual |
| **zotero-scihub** | **SKIP** | Abandoned; legal/policy noise | Dead for Z7 |
| **HKUDS/DeepTutor** | **SKIP** | Unrelated “tutoring” GitHub name collision on HN | Different product |
| **Already covered tools** (Elicit, Consensus, Undermind, SciSpace, Scite, Edison, PaperQA2, OpenResearch, Valency, etc.) | **SKIP** | In comparison already | N/A |

### Inferences
- Update the comparison’s **zotero-mcp ecosystem** line to lead with `54yyyu/zotero-mcp` and mention Zoteus/paperboy as specialized MCP.
- Add a short row for **DeepTutor / SeerAI** under “chat with PDFs you already have / AI inside Zotero.”
- Add **Littview OpenAlex PDF** next to zotero-zotadata / Find Available PDF as an OA-only in-app fetcher (Paperful still owns campus + grey + mirror).
- Consider **moara.io** near hosted lit-review / SR-adjacent workspace tools.

### Gaps
- X launch virality for these ADD candidates not measured.
- Did not deep-audit feature parity (campus proxy, grey lit, restore ledger) beyond public marketing—report writer should not claim Paperful uniqueness without product-doc cross-check already available in-repo.

---

## Source & method notes

- Primary: Reddit threads (r/zotero, r/PhD, r/PhdProductivity, r/LocalLLaMA, r/research, r/AIToolsAndTips), HN Algolia + item pages, GitHub API star/date snapshots (2026-11-26), vendor sites, one librarian review (Katina; JCHLA).
- Failed: X plugin search (`client-forbidden` / `user-not-enrolled`); Cursor `XSearch` unavailable.
- Epistemic caution: some Reddit “best tools 2026” posts and SciSpace-vs-Elicit pages are SEO/affiliate-flavored; weighted lower than librarian reviews, Show HN + repo activity, and multi-comment academic threads.
