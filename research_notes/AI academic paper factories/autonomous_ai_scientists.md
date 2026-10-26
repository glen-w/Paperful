# Autonomous AI-scientist and auto-paper-generation systems (as of 2026-10-26)

Scope: platforms that run literature + hypothesis + experiment/code + write loops, or generate papers/reviews end-to-end. **Excluded by assignment:** Edison / FutureHouse products (owned by another researcher). PaperQA-class local RAG is noted only as a *stack pattern*, not as a FutureHouse product review.

Prototype vs product is stated on each system. “Hosted” means a public or waitlisted web product a non-author can use without cloning a lab repo. Dates: research as of **2026-10-26**.

---

## What Sakana AI Scientist / AI Scientist v2 actually does

### Takeaway
Sakana’s **AI Scientist v1** (arXiv 2408.06292, 2024) and **AI Scientist-v2** (arXiv 2504.08066, 2025) are the clearest open **idea → code experiment → figures → LaTeX manuscript → LLM review** loops in ML; v2 produced a fully AI-written workshop paper that scored above a cooperating ICLR 2025 workshop’s average acceptance threshold, then was **withdrawn by protocol**. They are **open-source research prototypes**, not hosted products; domain is **code-expressible ML**; humans supply topic/template and pick which PDFs to submit.

### Cited Findings
- v1 is described as “the first comprehensive system for fully automatic scientific discovery,” with three maintained templates (**NanoGPT**, **2D Diffusion**, **Grokking**); community templates exist (SEIR, MobileNetV3, quantum chemistry MACE, etc.) but are unmaintained by Sakana. — [SakanaAI/AI-Scientist README](https://github.com/SakanaAI/AI-Scientist)
- v1 literature/citations use **Semantic Scholar** (`S2_API_KEY`) or experimental **OpenAlex**; authors say you can skip literature search and citation phases if APIs fail. PDFs are loaded as **raw text** for the LLM reviewer (`load_paper`). — [SakanaAI/AI-Scientist README](https://github.com/SakanaAI/AI-Scientist)
- Typical cost cited by authors: **&lt; $15 per paper** with Claude Sonnet 3.5; success rate depends on template and model; highest experiment success with Claude 3.5; reviews “best done with GPT-4o.” — [SakanaAI/AI-Scientist README](https://github.com/SakanaAI/AI-Scientist)
- v2 “autonomously generates hypotheses, runs experiments, analyzes data, and writes scientific manuscripts”; **removes human-authored code templates**; uses **progressive agentic tree search** (built on [AIDE](https://github.com/WecoAI/aideml)) plus an experiment-manager agent; VLM feedback loop for figures. Authors warn **v2 is not necessarily better than v1** when a strong template exists; v2 has **lower success rates**. — [SakanaAI/AI-Scientist-v2 README](https://github.com/SakanaAI/AI-Scientist-v2); [arXiv:2504.08066](https://arxiv.org/abs/2504.08066)
- v2 ideation: user writes a Markdown topic (`Title`, `Keywords`, `TL;DR`, `Abstract`); `perform_ideation_temp_free.py` brainstorms ideas and checks novelty via Semantic Scholar; then `launch_scientist_bfts.py` runs BFTS experiments and writeup. Writeup ~**20–30 minutes**; full example run “several hours.” Experiment phase ~**$15–$20** (Claude 3.5 Sonnet) + ~**$5** writing. — [SakanaAI/AI-Scientist-v2 README](https://github.com/SakanaAI/AI-Scientist-v2)
- **ICLR 2025 workshop experiment (ICBINB):** 3 fully AI-generated papers submitted with ICLR leadership + workshop cooperation and **UBC IRB**. Reviewers told 3/43 papers *might* be AI-generated, not which. Humans only chose the topic and picked 3 papers. One paper (“Compositional Regularization…”) scored **6/7/6 (mean 6.33)**, above the workshop’s average acceptance threshold; **all three were withdrawn/desk-rejected after review by prior agreement** and not posted on OpenReview. Sakana’s own internal ICLR-*conference*-bar review: **none of the three would pass**. — [Sakana blog, 12 Mar 2025](https://sakana.ai/ai-scientist-first-publication/)
- Documented citation failure: attributing “an LSTM-based neural network” to **Goodfellow (2016)** instead of **Hochreiter & Schmidhuber (1997)**. — [Sakana blog](https://sakana.ai/ai-scientist-first-publication/)
- Nature publication (26 Mar 2026) of a paper covering architecture + new scaling results: [s41586-026-10265-5](https://www.nature.com/articles/s41586-026-10265-5); blog states open-access Nature paper + GitHub v1/v2. — [Sakana Nature announcement](https://sakana.ai/ai-scientist-nature/)
- **Open vs hosted:** GitHub under **The AI Scientist Source Code License** (Responsible AI License derivative). **Mandatory disclosure** of AI use in any resulting manuscript. **Not a hosted SaaS.** Code **executes LLM-written code**; authors require sandbox/Docker. — [v1 README license](https://github.com/SakanaAI/AI-Scientist); [v2 README](https://github.com/SakanaAI/AI-Scientist-v2)
- **HITL:** v2 pipeline is designed as autonomous after topic file + idea JSON; humans still pick topics, optionally `--load_code`, choose models, and (in the workshop study) selected which papers to submit. Reviewer is an LLM, not a journal. — [v2 README](https://github.com/SakanaAI/AI-Scientist-v2); [Sakana blog](https://sakana.ai/ai-scientist-first-publication/)
- **Factory stages:** **discover** (ideation + Semantic Scholar novelty), **read** (S2/OpenAlex metadata, not full-text PDF corpora), **analyze** (run code, plots, tree viz `unified_tree_viz.html`), **write** (LaTeX PDF), **review** (LLM + optional VLM figures), **submit** (manual; workshop experiment was a one-off with organizers). No PRISMA.

### Inferences
- Closest public artifact to a “paper factory” for **computational ML**, but output quality is explicitly **workshop-grade**, not main-conference/journal-grade, by the authors’ own reviews.
- Auditability is **local logs + generated code + PDFs + tree HTML**, not a third-party provenance ledger; citation integrity is **not guaranteed**.

### Gaps
- Did not independently read the full Nature 2026 PDF (paywall/full-text not fetched here); new scaling numbers beyond the blog claim are not extracted.
- No public hosted Sakana “submit to arXiv for me” product found.

---

## Agent Laboratory, AgentRxiv, ResearchAgent, SciAgents, and PaperQA-class local stacks

### Takeaway
These are **research-assistant / idea / hypothesis** systems, not interchangeable. **Agent Laboratory** is the usable end-to-end ML **idea-in → arXiv lit review → code + LaTeX report** GitHub tool with optional **copilot** HITL. **AgentRxiv** is a **shared preprint store among agents**, not a publisher. **ResearchAgent** and **SciAgents** stop at **ideas/hypotheses** (plus SciAgents materials case studies). **PaperQA-class** stacks are **cited Q&A over PDFs you already have**, not scientists; FutureHouse products are out of scope.

### Cited Findings

#### Agent Laboratory (prototype you can run; MIT license)
- Input: **human-produced research idea**. Output: **code repository + research report**. Three phases: **Literature Review, Experimentation, Report Writing**. Tools: **arXiv, Hugging Face, Python, LaTeX**. Agents include PhD / Postdoc / ML Engineer / Professor; **mle-solver** and **paper-solver**. — [agentlaboratory.github.io](https://agentlaboratory.github.io/); [arXiv:2501.04227](https://arxiv.org/abs/2501.04227)
- Paper claims: o1-preview produced best outcomes; generated ML code “able to achieve SOTA vs existing methods” (authors’ evaluation); **human feedback at each stage significantly improves quality**; **84% cost decrease** vs previous autonomous research methods. Revised 17 Jun 2025. — [arXiv:2501.04227](https://arxiv.org/abs/2501.04227)
- **Copilot mode:** YAML `copilot-mode: "true"` for checkpoint feedback; default progress in `state_saves`. Models: OpenAI o1/o1-preview/o1-mini/gpt-4o/o3-mini and DeepSeek-v3. Optional `pdflatex`; `--compile-latex false` if no sudo. — [SamuelSchmidgall/AgentLaboratory README](https://github.com/SamuelSchmidgall/AgentLaboratory)
- **Open vs hosted:** **Open GitHub**, MIT. No first-party commercial host found. Domain: **ML/code experiments** as demonstrated. Literature via **arXiv API** (not systematic PDF screening).
- **Factory stages:** discover (limited; idea is human), **read** (arXiv summaries), **analyze** (code experiments), **write** (LaTeX), **review** (iterative edits “peer review-like” in AgentRxiv description), **submit** (no).

#### AgentRxiv (research framework, not a public preprint server for humans)
- Shared store so agent labs **upload/retrieve** reports; similarity search; modeled after arXiv/bioRxiv. Agents with access to prior research: **11.4% relative** MATH-500 improvement vs isolated; multiple labs sharing: **13.7%** relative vs baseline; best strategy generalized **+3.3% average** on other-domain benchmarks. — [arXiv:2503.18102](https://arxiv.org/abs/2503.18102); [agentrxiv.github.io](https://agentrxiv.github.io/)
- Built **on Agent Laboratory**; autonomous mode vs copilot checkpoints. — [agentrxiv.github.io](https://agentrxiv.github.io/)
- **Not** a replacement for arXiv.org; it is an **agent-to-agent** knowledge-sharing experiment.

#### ResearchAgent (ideation prototype)
- Starts from a **core paper**, expands via **citation graph**, plus an **entity-centric knowledge store** mined from titles/abstracts (papers after 1 May 2023 in their construction). Outputs **problem + method + experiment design**, refined by LLM **ReviewingAgents** with criteria induced from ~10 human-scored idea pairs. Does **not** run experiments or write full papers. — [arXiv HTML 2404.07738v2](https://arxiv.org/html/2404.07738v2)
- Authors claim code at [github.com/JinheonBaek/ResearchAgent](https://github.com/JinheonBaek/ResearchAgent). This notes file did **not** verify that repo’s 2026 maintenance status.
- **Factory stages:** **discover / read (abstracts+graph) / (light) review of ideas**. No analyze/write/submit.

#### SciAgents (materials hypothesis; open notebooks)
- Multi-agent **ontological knowledge-graph** reasoning + LLMs + retrieval; applied to **bio-inspired materials**. Agents: Ontologist, Scientists, Critic. Generates/refines hypotheses, retrieves research, critiques. Published **Advanced Materials** 2025 (DOI 10.1002/adma.202413523); preprint [arXiv:2409.05556](https://arxiv.org/abs/2409.05556).
- Code: [lamm-mit/SciAgentsDiscovery](https://github.com/lamm-mit/SciAgentsDiscovery) (AG2/AutoGen automated + non-automated notebooks) and [lamm-mit/GraphReasoning](https://github.com/lamm-mit/GraphReasoning). PMC abstract states a case of a **new biocomposite** with enhanced mechanical properties / energy-efficient production — that is a **lab materials claim**, not a paper mill. — [PMC12138853](https://pmc.ncbi.nlm.nih.gov/articles/PMC12138853/)
- **Open notebooks, not a hosted product.** Stages: **discover / read (KG+retrieval) / hypothesize**. No end-to-end manuscript factory.

#### PaperQA-class local stacks (pattern only; FutureHouse products excluded)
- Independent catalogues treat **paper-qa** as **cited Q&A over full-text PDFs you already own** (Tantivy index), **not** discovery or screening; “will not find them or screen them for you.” — [PICKS.md lit-review catalogue](https://github.com/brycewang-stanford/lit-review-agent-tools/blob/main/PICKS.md)
- Same catalogue: **STORM writes a survey, not a systematic review — no screening, no PRISMA trail.** — [PICKS.md](https://github.com/brycewang-stanford/lit-review-agent-tools/blob/main/PICKS.md)
- **Inference for this assignment:** labs can *wrap* local PDF RAG as the “read” stage of a scientist loop; that does **not** make PaperQA an autonomous scientist.

### Inferences
- If the user wants a **runnable paper-ish factory today**, Agent Laboratory and Sakana/HKU AI-Researcher are the relevant GitHub class; SciAgents/ResearchAgent are **upstream ideation**.
- AgentRxiv shows a market gap: **no production “agent arXiv”** with human-grade moderation.

### Gaps
- Did not audit Agent Laboratory’s “SOTA code” claim against independent replication.
- ResearchAgent GitHub activity as of 2026-10-26 not verified by fetch.
- PaperQA / Edison / FutureHouse intentionally not reviewed.

---

## Google Co-Scientist / AI co-scientist (public status)

### Takeaway
Google’s **Co-Scientist** is a **Gemini multi-agent hypothesis engine** (generate–critique–tournament–evolve), validated in **biomedicine** (AML drug-repurposing in vitro, etc.). It is **not open source**. As of **19 May 2026** Google began rolling a **Labs experimental tool “Hypothesis Generation”** with registration at **labs.google/science** — a **waitlisted hosted product**, not a paper writer.

### Cited Findings
- Feb 19, 2025 Google Research blog: “AI co-scientist” on **Gemini 2.0**; agents **Generation, Reflection, Ranking, Evolution, Proximity, Meta-review**; input = scientist’s natural-language goal; output = **novel hypotheses, research overview, experimental protocols** — explicitly **beyond** literature review / “deep research.” — [research.google blog](https://research.google/blog/accelerating-scientific-breakthroughs-with-an-ai-co-scientist/)
- Nature paper **“Accelerating scientific discovery with Co-Scientist”** (published **19 May 2026**): tournament evolution + test-time compute; biomedical focus: **drug repurposing, novel-target discovery, AMR mechanisms**; AML combination therapies **validated in vitro**. — [Nature s41586-026-10644-y](https://www.nature.com/articles/s41586-026-10644-y)
- **Code availability (Nature):** full source **not public** (internal infra, compute, **safety of unmonitored autonomous agents**). Experimental access program; later “thousands of scientists” via APIs. Pseudocode + system prompts in supplements. Gemini itself is public via APIs. — [Nature code availability](https://www.nature.com/articles/s41586-026-10644-y)
- DeepMind blog same day: making Co-Scientist available via **Hypothesis Generation**; register [labs.google/science](https://labs.google/science). — [deepmind.google blog](https://deepmind.google/blog/co-scientist-a-multi-agent-ai-partner-to-accelerate-research/)
- I/O 2026 “Gemini for Science”: three Labs experiments — **Hypothesis Generation (Co-Scientist)** with “idea tournament” and **clickable citations**; **Computational Discovery** (AlphaEvolve + ERA) for mass code variants; **Literature Insights** (NotebookLM) tables/reports/slides. Gradual access. — [blog.google Gemini for Science](https://blog.google/innovation-and-ai/technology/research/gemini-for-science-io-2026/)
- **Factory stages:** **discover + hypothesize + (protocols)**; Computational Discovery adds **analyze/code**; Literature Insights adds **read/write reports**. **No journal manuscript + submit loop** in public docs.
- **HITL:** framed as collaborator; scientist supplies objectives and must experimentally verify. **Domain:** general-purpose architecture, **validation in biomed**.
- **Auditability:** citations claimed on Labs Hypothesis tool; full agent traces not released as open software.

### Inferences
- Public “Google AI scientist” in 2026 is **hypothesis + literature UX**, not Sakana-style auto-paper.
- Separate from **Gemini Deep Research** (web report factory; see next section).

### Gaps
- Access conversion rate / whether Hypothesis Generation is generally available vs waitlist as of 2026-10-26 not confirmed by logging into Labs.
- In vitro AML details not extracted beyond Nature abstract.

---

## OpenAI, Gemini, and Perplexity Deep Research / Academic as research-report factories

### Takeaway
These are **hosted report synthesizers** (plan → browse → cited longform). They are **products people can use**. They do **not** run original scientific experiments or produce submission-ready journal articles. Vendors themselves warn of **hallucination and citation errors**. Perplexity **Academic focus** is a **scholarly-source filter**, not a separate “auto-paper” product.

### Cited Findings

#### OpenAI Deep Research (hosted product)
- Launched **2 Feb 2025** in ChatGPT; agentic multi-step web research; “tens of minutes”; “hundreds of online sources”; report “at the level of a research analyst”; reads **text, images, and PDFs** on the internet. Powered initially by an **o3 browsing/data-analysis** variant. — [openai.com/index/introducing-deep-research](https://openai.com/index/introducing-deep-research/)
- **Humanity’s Last Exam:** model powering deep research **26.6%** at launch (OpenAI’s number). — [same](https://openai.com/index/introducing-deep-research/)
- **Limitations (vendor):** “can sometimes **hallucinate facts** or make incorrect inferences”; weak at distinguishing authoritative vs rumor; poor **confidence calibration**; “minor formatting errors in reports and citations.” — [same](https://openai.com/index/introducing-deep-research/)
- Help Center (updated 2026): Chat / Work / Codex; user describes outcome; **reviews/edits plan**; can filter websites and connected apps; interrupt; structured report with **citations or source links to verify**. Usage by plan (Free limited, Plus expanded, Pro maximum). Enterprise RBAC. — [help.openai.com Deep research](https://help.openai.com/en/articles/10500283-deep-research)
- **10 Feb 2026 update:** connect **MCP/apps**, restrict web to trusted sites, real-time progress, interrupt. **17 Jul 2025:** visual browser via ChatGPT **agent mode** (deeper); original deep research remains in tools menu. **24 Apr 2025:** Plus/Team/Enterprise/Edu **25**/month full queries, Pro **250**, Free **5**, then lightweight o4-mini version. — [introducing-deep-research](https://openai.com/index/introducing-deep-research/)
- **Factory stages:** discover/read/write **reports**. HITL: plan approval + interrupt. **Not** experiment/code/submit. OpenAI help: citations are for verification, not a guarantee (also emphasized in secondary academic-comparison posts).

#### Google Gemini Deep Research (hosted product)
- Agentic Gemini feature: plan, browse **up to hundreds of websites**, optional **Gmail, Drive, Chat**, upload files, multi-page reports in minutes, Audio Overview, Canvas. Available desktop/mobile, **150 countries, 45+ languages**, Workspace. — [gemini.google/overview/deep-research](https://gemini.google/overview/deep-research/)
- Help: default source **Google Search**; can add Gmail/Drive; upload files and **NotebookLM notebooks**; edit plan then Start research; typically **5–10 minutes**. Ultra plan: charts/diagrams/simulators. — [support.google.com](https://support.google.com/gemini/answer/15719111)
- **Factory stages:** discover/read/write. Personal files = extra corpus (audit mix of web vs private). No experiment loop.

#### Perplexity Deep Research + Academic (hosted products)
- **Deep Research:** plan, “thousands of retrieval steps,” “fully cited” report; in **Computer**, can become deck/dashboard; files + live web; premium data (Statista, PitchBook, CB Insights claimed). Routes subtasks across **20+ models** (product FAQ). — [perplexity.ai/hub/products/deep-research](https://www.perplexity.ai/hub/products/deep-research)
- **Academic focus / Pro Search:** focus selector **Academic** searches scholarly databases; source cards show authors, journal, year. USC hub (8 Oct 2026): good for lit scans; **cited sources not always high-quality**; can **misread/overstate** sources; unsourced sentences are model inference. — [USC AI Knowledge Hub](https://sites.usc.edu/ai-knowledge-hub/ai-tools/perplexity/); [Pro Search help](https://www.perplexity.ai/help-center/en/articles/10352903-what-is-pro-search)
- Agent API: `search_domain_filter` to arxiv.org, nature.com, PubMed, `.edu`. — [Perplexity academic-search cookbook](https://docs.perplexity.ai/docs/cookbook/articles/academic-search/README)
- **DRACO** (Perplexity, arXiv **2602.11685**, 12 Feb 2026): 100 tasks, 10 domains, 40 countries, from de-identified Deep Research usage. Grades accuracy, completeness, presentation/objectivity, citation quality. Authors report **Perplexity Deep Research strongest overall** vs OpenAI Deep Research, Gemini Deep Research, Claude Opus — **vendor-authored benchmark**; treat as non-independent. Dataset: https://hf.co/datasets/perplexity-ai/draco — [arXiv:2602.11685](https://arxiv.org/pdf/2602.11685)

### Inferences
- Market “deep research” = **analyst memo factory**, not **academic paper factory**.
- Best audit story: **clickable URLs** (Perplexity UX strongest); still requires human verification.
- None implement PRISMA, novelty vs prior art, or journal submission.

### Gaps
- Independent (non-vendor) head-to-head on **citation hallucination rates** for 2026 models was not found in primary vendor docs (only OpenAI’s qualitative “lower than ChatGPT” claim).
- Exact 2026-10-26 query quotas may have changed after help-center updates.

---

## AutoResearch, GPT-Researcher, STORM, and WikiLike synthesis

### Takeaway
**STORM** is the academic **Wikipedia-like synthesis** system (open package + Stanford live preview). **GPT Researcher** is the most productized **open deep-research agent** (pip, Docker, gptr.dev, MCP). Multiple **2026 papers named AutoResearch** exist; they are **reliability/grounding prototypes**, not a single dominant product. None of these run a full scientific experiment loop comparable to Sakana.

### Cited Findings

#### STORM / Co-STORM (Stanford OVAL)
- **STORM** (NAACL 2024): Synthesis of Topic Outlines through Retrieval and Multi-perspective Question Asking; Wikipedia-like articles from Internet research; FreshWiki eval; vs outline-RAG baseline: **+25% organized**, **+10% broad** (absolute). Editors found it useful in **pre-writing**; **cannot produce publication-ready articles**. Challenges: **source bias transfer**, **over-association of unrelated facts**. — [storm-project.stanford.edu](https://storm-project.stanford.edu/research/storm/)
- GitHub: `pip install knowledge-storm`; search RMs (You, Bing) + **VectorRM for user documents** (Jul 2024). **Co-STORM** (EMNLP 2024): human + LLM experts + moderator + mind map; **&gt;70,000** people tried live preview. Demo: [storm.genie.stanford.edu](https://storm.genie.stanford.edu/). Research preview ToS: may err; inputs may be used for research (CC-BY-like). — [github.com/stanford-oval/storm](https://github.com/stanford-oval/storm/)
- **Open + hosted research preview.** Stages: **discover/read/write**. HITL in Co-STORM. **No experiments, no PRISMA, no journal format.**

#### GPT Researcher (open product-grade tool)
- “First open deep research agent” for **web and local** research; planner + crawler agents + publisher; **&gt;20 sources**; reports **&gt;2,000 words**; export **PDF/Word**; local **PDF, txt, CSV, Excel, MD, PPT, Word** via `DOC_PATH`. Apache-2. Needs LLM + search (Tavily) keys. Official site [gptr.dev](https://gptr.dev), docs [docs.gptr.dev](https://docs.gptr.dev). Deep Research mode: tree breadth/depth, ~**5 min**, ~**$0.4** with o3-mini high. Multi-agent (LangGraph/AG2) path inspired by STORM: **5–6 page** PDF/Docx/MD. — [assafelovic/gpt-researcher README](https://github.com/assafelovic/gpt-researcher)
- **Disclaimer (authors):** experimental; **“NOT a recommendation to use in academic or research papers.”** Aim to reduce (not eliminate) bias via multi-site scraping. — [same README](https://github.com/assafelovic/gpt-researcher)
- Community issue **#1572**: if `self.context` is empty, `write_report` can still emit **fabricated sources**. — [issue discussion as summarized in a third-party architecture note](https://doramagic.ai/en/projects/gpt-researcher/manual/) — prefer verifying on GitHub issue 1572.
- **Hosted-ish:** self-host UI; Claude Skill; MCP server moved to [gptr-mcp](https://github.com/assafelovic/gptr-mcp). Not a journal factory.

#### AutoResearch (name collision — three different things)
1. **AutoResearch: An Execution-Grounded Multi-Agent Framework…** ([arXiv HTML 2607.02520](https://arxiv.org/html/2607.02520v1)): sandbox Python/PyTorch, iterative repair, **four-step citation verification** (arXiv ID, DOI/CrossRef, Semantic Scholar, LLM relevance). External annotators: invalid-citation rate **3.5%** vs **31%** Tool-Agent baseline (n=500 each). Authors **deny** being a fully autonomous scientist or manuscript-writing benchmark.
2. **AutoResearch: Insight In, Hallucination Out** ([arXiv 2608.17906](https://arxiv.org/html/2608.17906v2)): discovery+execution grounding; “system-level hallucination” = unsupported claims from bad code/measurement.
3. **EvoMap/AutoResearch** GitHub: optional GPT Researcher adapter writing **Git-ignored drafts** for human review before knowledge-base ingest — not auto-publish. — [github.com/EvoMap/AutoResearch](https://github.com/EvoMap/AutoResearch)

Treat “AutoResearch” in 2026 as a **label**, not one platform.

### Inferences
- WikiLike / survey generation is **mature and usable**; **systematic review / PRISMA factories are not** (explicitly disclaimed for STORM).
- GPT Researcher is the practical **open counterpart** to ChatGPT/Gemini/Perplexity Deep Research.

### Gaps
- GitHub issue #1572 not fetched live in this pass (only secondary summary).
- Hugging Face Spaces for STORM vs genie.stanford.edu: live preview is Stanford Genie, not necessarily a Space.

---

## 2025–2026 multi-agent scientific discovery papers that shipped something people can use

### Takeaway
Several **code-first AI scientists** shipped **GitHub (+ sometimes a web GUI)**. **ChemCrow-class chemistry agents** remain mostly **papers + public repos**, not consumer products. The only **big-lab hosted** scientist-adjacent products found are **Google Labs Hypothesis Generation** and generic **Deep Research** UIs.

### Cited Findings

#### HKUDS AI-Researcher — prototype + hosted chat
- NeurIPS 2025 **Spotlight**. End-to-end: literature, idea, algorithm implementation/validation, analysis, **publication-ready manuscript**. Inputs: detailed idea **or** “here are reference papers, invent and implement.” Resource collector: **arXiv, IEEE, ACM, Google Scholar, GitHub, Hugging Face**. Docker image `tjbtech1/airesearcher`. **Scientist-Bench** vs human papers. — [arXiv:2505.18705](https://arxiv.org/abs/2505.18705); [HKUDS/AI-Researcher](https://github.com/HKUDS/AI-Researcher/)
- GitHub header: “production-ready version: **https://novix.science/chat**”; Web GUI in May 2025 release notes. — [README](https://github.com/HKUDS/AI-Researcher/)
- **Domain:** AI/ML research automation. **Open (MIT claimed in third-party nav) + hosted Novix.** Stages: full loop except journal submit. HITL: two input levels; otherwise “full autonomy” marketing.

#### Ai2 CodeScientist — open, semi-automated
- Human supplies **papers + codeblocks**; genetic search over papers×code; generate–execute–reflect; report + multi-seed meta-analysis. ~50 papers in; researcher picked 50 ideas; **19** flagged discoveries; **6** passed human soundness+incremental novelty (agents/virtual environments). **&gt;50% experiments fail** in debugging. HITL on idea selection strongly recommended. Open source; ACL Findings 2025. — [allenai.org/blog/codescientist](https://allenai.org/blog/codescientist); [ACL Anthology](https://aclanthology.org/2025.findings-acl.692/)
- Authors position it vs **AI Scientist, Agent Laboratory, data-to-paper**.

#### ChemCrow and “successors”
- ChemCrow (Bran et al., **Nature Machine Intelligence 2024**): GPT-4 + **18 chemistry tools**; planned syntheses (insect repellent, organocatalysts); guided a **novel chromophore** (predicted 369 nm, measured **336 nm**) with human-in-loop synthesis. — [doi:10.1038/s42256-024-00832-8](https://doi.org/10.1038/s42256-024-00832-8)
- 2026 chemistry/SDL review: ChemCrow strong on Comprehension/Design, **linear, weak Analysis/Optimization loop**; lists **Coscientist, LLM-RDF, AI-Chemist** as milestones — **not** as paper factories. — [PMC13213502](https://pmc.ncbi.nlm.nih.gov/articles/PMC13213502/)
- **No ChemCrow commercial paper-generation product found** in this pass.

#### Other 2025–2026 names (catalogued; not all fetched)
- Awesome-Auto-Research (updated **2026-05-26**) lists end-to-end: **autoresearch, AutoResearchClaw, InternAgent, Agent Lab, AI-Scientist v1/v2**; lit/survey: **SurveyX, DeerFlow, OpenResearcher**; domain: **Biomni**, ChemCrow. Capability matrix: AI-Scientist has peer-review column; GPT Researcher/STORM do not execute code. — [EdwardLeeLPZ/Awesome-Auto-Research](https://github.com/EdwardLeeLPZ/Awesome-Auto-Research)
- These catalogue rows are **secondary**; treat as pointers, not evaluations.

#### Reviews (context, 2025–2026)
- **Nature Reviews Methods Primers** “Agentic AI systems for scientific discovery” (published **22 Oct 2026**): agents as workflows over literature, simulation, automated labs; hallucination, tool misuse, safety; HITL vs autonomous. — [s43586-026-00534-y](https://www.nature.com/articles/s43586-026-00534-y)
- Preprint “Collective Intelligence…” (2025) maps MAS onto research stages; **not peer-reviewed**. — [10.20944/preprints202508.1640.v3](https://doi.org/10.20944/preprints202508.1640.v3)

### Inferences
- **Shipped usable “scientist” software** clusters in **CS/ML code experiments** (Sakana, Agent Lab, AI-Researcher, CodeScientist).
- **Shipped usable “scientist” products** for **life-science hypothesis** cluster at **Google Labs**.
- Chemistry auto-lab agents have **not** become academic paper mills.

### Gaps
- novix.science/chat not live-tested (uptime, pricing, auth).
- AutoResearchClaw / InternAgent / SurveyX / Biomni not fetched as primary in this pass.
- data-to-paper not re-fetched (cited by Ai2 as predecessor).

---

## What “fully-fledged academic paper factory” means in this market

### Takeaway
Vendors blur **report**, **survey**, **workshop ML paper**, and **hypothesis memo**. A strict factory would ship: **manuscript + figures + related work with real citations + novelty check + (for reviews) PRISMA + code/data artifacts + a submission path**. **No public system as of 2026-10-26 reliably does all of that.** Closest: Sakana/AI-Researcher on **ML workshop papers**; STORM/GPT-R/Deep Research on **survey-like reports**; Google Co-Scientist on **hypotheses**.

### Cited Findings
- Sakana v2: full manuscript **from title to references including figures**, but **workshop-level**, citation errors, withdrawn from publication by ethics protocol; license **requires disclosing AI generation**. — [Sakana blog](https://sakana.ai/ai-scientist-first-publication/); [v2 README](https://github.com/SakanaAI/AI-Scientist-v2)
- STORM authors: **not publication-ready**; Wikipedia editors use it for **pre-writing**; **no PRISMA**. — [Stanford STORM page](https://storm-project.stanford.edu/research/storm/); [PICKS.md](https://github.com/brycewang-stanford/lit-review-agent-tools/blob/main/PICKS.md)
- GPT Researcher authors: **do not recommend** use in academic papers. — [GPT Researcher README](https://github.com/assafelovic/gpt-researcher)
- Google Co-Scientist Nature: **hypotheses for experimental verification**, source **not released**, safety rationale against unmonitored agents. — [Nature code availability](https://www.nature.com/articles/s41586-026-10644-y)
- OpenAI Deep Research: **analyst reports**, known **hallucinations/citation formatting** issues. — [OpenAI introducing post](https://openai.com/index/introducing-deep-research/)
- CodeScientist: even “discoveries” need **human paper+code review**; majority of runs **fail to execute**. — [Ai2 blog](https://allenai.org/blog/codescientist)
- AutoResearch (2607.02520): citation verification drops invalid citations **31% → 3.5%** in their study — implying **unverified factories routinely hallucinate bibliography**. — [arXiv 2607.02520](https://arxiv.org/html/2607.02520v1)

### Inferences
- Market language:
  - **Report factory:** Deep Research, GPT Researcher, DeerFlow-class.
  - **Wiki/survey factory:** STORM, SurveyX.
  - **ML paper factory (prototype):** Sakana v1/v2, Agent Laboratory, AI-Researcher, CodeScientist.
  - **Hypothesis factory:** Google Co-Scientist, SciAgents, ResearchAgent.
- **PRISMA / living systematic review** is a **missing product category** in the sources above.
- **Submit** is almost always **human** (arXiv/journal/workshop); AgentRxiv submit is **agent-only sandbox**.
- **Novelty** in Sakana is **Semantic Scholar search**, not a legal/priority search.
- **Figures:** Sakana/Agent Lab generate from experiment plots; GPT Researcher can scrape or **generate decorative Gemini images** (not experimental figures).
- **Code+data:** only the ML-scientist class emits repos; Deep Research generally does not.

### Gaps
- No 2026 market report with pricing TAM for “AI paper factories” was used.
- Journal policies on fully AI-authored papers beyond Sakana’s ICLR experiment were not systematically surveyed.

---

## Legal / ethics issues that are documented (not speculation)

### Takeaway
Documented issues are **fake or wrong citations**, **passing peer review without disclosure**, **undermining review**, **unsafe code execution**, and **vendor refusal to open autonomous scientists** on safety grounds.

### Cited Findings
- Sakana: wrong LSTM citation; community has **not decided** whether to publish fully AI-generated manuscripts in the same venues; papers **withdrawn** after review; reviewers were **partially informed**; goal is not to optimize solely for passing review. Concurrent Tiny Papers track: **humans** still wrote related work, polished language, edited citations/LaTeX; those papers were **not** fully AI-generated. — [Sakana first publication blog](https://sakana.ai/ai-scientist-first-publication/)
- Sakana license: **mandatory prominent disclosure** of AI use. — [AI-Scientist README](https://github.com/SakanaAI/AI-Scientist)
- OpenAI: hallucination + citation formatting errors in Deep Research. — [introducing-deep-research](https://openai.com/index/introducing-deep-research/)
- GPT Researcher: empty-context **fabricated sources** (issue #1572); authors disclaim academic use. — [README](https://github.com/assafelovic/gpt-researcher); [secondary issue summary](https://doramagic.ai/en/projects/gpt-researcher/manual/)
- AutoResearch study: ~**31%** invalid citations without verification vs **3.5%** with a four-step bibliographic checker (their annotators). — [2607.02520](https://arxiv.org/html/2607.02520v1)
- Google: will not release Co-Scientist source due in part to **“safety implications of unmonitored autonomous agentic use.”** — [Nature](https://www.nature.com/articles/s41586-026-10644-y)
- Sakana/Agent Lab: **LLM-written code execution** risk (dangerous packages, web, processes) — sandbox required. — [v2 README](https://github.com/SakanaAI/AI-Scientist-v2)
- STORM preview ToS: generated reports **can make mistakes**; user content may be collected for research. — [storm.genie.stanford.edu](https://storm.genie.stanford.edu/)
- USC on Perplexity Academic: citations can be **wrong quality or overstated**. — [USC hub](https://sites.usc.edu/ai-knowledge-hub/ai-tools/perplexity/)

### Inferences
- The binding academic risk is **bibliographic hallucination + undisclosed AI authorship**, not “the AI submitted to Nature by itself.”
- Peer-review experiments require **venue cooperation**; silent submission of AI papers would be an ethics violation relative to Sakana’s own protocol.

### Gaps
- No court cases or publisher-wide 2026 ban language were retrieved here.
- ICLR Tiny Papers concurrent work was described only via Sakana’s footnote, not that group’s own paper.

---

## Compact comparison (for the report writer)

| System | Type | Open / hosted | Domain | HITL | PDF/lib | Stages (D/R/A/W/Rev/S) |
|---|---|---|---|---|---|---|
| Sakana AI Scientist v1 | Prototype | Open GitHub, custom license / not SaaS | ML templates | Topic+template | S2/OpenAlex; PDF as text for review | D R A W Rev; S manual |
| Sakana v2 | Prototype | Same | Open-ended ML | Topic file; pick papers | S2 during ideation/cites | D R A W Rev; S experiment only |
| Agent Laboratory | Prototype | Open MIT | ML code | Copilot optional | arXiv API | R A W; D human idea |
| AgentRxiv | Prototype | Paper+site | Agent preprints | Copilot optional | Shared agent PDFs | W + retrieve; not human arXiv |
| ResearchAgent | Prototype | Claimed GitHub | Multi-discipline ideas | LLM reviewers | Abstracts+citation graph | D R (ideas only) |
| SciAgents | Prototype | GitHub notebooks | Bio-inspired materials | Critic agent | KG + retrieval | D R hypothesize |
| Google Co-Scientist | Product (waitlist) | Closed; Labs tool | Biomed validated, general claimed | Scientist goals | Citations claimed | D hypothesize; protocols |
| Gemini Science Labs | Product (waitlist) | Hosted | Science workflow | Yes | NotebookLM + files | Split: hypo / code / lit |
| OpenAI Deep Research | Product | Hosted ChatGPT | General + PDFs on web | Plan+interrupt | Web PDFs, uploads | D R W report |
| Gemini Deep Research | Product | Hosted Gemini | General + Workspace | Edit plan | Search, Drive, uploads | D R W report |
| Perplexity DR / Academic | Product | Hosted | General / scholarly filter | Follow-ups | Web / academic DBs | D R W report |
| GPT Researcher | Productized OSS | pip/Docker/gptr.dev | Web+local docs | Optional UI | Local PDF folder | D R W report |
| STORM / Co-STORM | Prototype + preview | pip + genie.stanford.edu | Wiki-like any topic | Co-STORM yes | Web + VectorRM docs | D R W survey |
| AI-Researcher (HKU) | Prototype + Novix | GitHub + novix.science/chat | AI papers | Two input levels | Academic DBs | D R A W |
| CodeScientist | Prototype | Open (Ai2) | Agents/code science | Strong HITL advised | Human-provided papers | D R A W (reports) |
| AutoResearch (2607) | Prototype | Paper | Reliability layer | Verifier agents | arXiv/DOI/S2 checks | A W + cite audit |
| ChemCrow | Prototype | Public code historically | Chemistry tools | Yes (synthesis) | Chem tools, not papers | Design/execute chem; not write |

Legend: D=discover, R=read, A=analyze/experiment, W=write, Rev=review, S=submit.

**Edison/FutureHouse excluded** per assignment.
