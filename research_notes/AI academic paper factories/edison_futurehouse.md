# Edison Scientific and FutureHouse (as of 2026-10-26)

Research snapshot for a local open-source “paper factory” (library → PDFs → grounded synthesis → manuscript support). Distinguish **product docs** vs **paper/blog claims**. Platform UI at [platform.edisonscientific.com](https://platform.edisonscientific.com) is reachable but returned only a login-gated stub (“Edison Platform”); details below are from docs, blogs, arXiv, and GitHub.

Relationship: Edison Scientific is the 2025 for-profit spinout that now runs the commercial platform; FutureHouse remains a nonprofit lab (biology-first, wet lab in San Francisco) with access to Edison’s tools. Founders Sam Rodriques and Andrew White run both with stated conflict-of-interest controls. — [FutureHouse About](https://www.futurehouse.org/about); [Introducing Edison Scientific](https://edisonscientific.com/news/announcing-edison-scientific)

---

## Full agent lineup (Kosmos, Literature/PaperQA, Precedent/HasAnyone, Analysis, Molecules)

### Takeaway
The hosted Edison Platform is five specialized agents plus Kosmos as a long-running orchestrator of Analysis + Literature. Concrete capabilities are documented; bird-name aliases (Crow/Falcon/Owl/Finch/Phoenix) are the older FutureHouse job names still in the API enum.

### Cited Findings
- Platform overview: literature synthesis, data analysis, molecular design, novelty assessment; goal is compressing weeks/months of scientist work. — [docs overview](https://docs.edisonscientific.com/)
- **Kosmos**: given a research objective and one or more datasets, autonomously reads literature, writes/executes analysis code, generates hypotheses, produces a comprehensive cited report. Docs repeat ~1,500 papers and ~42,000 lines of code per run; multiple agents in parallel sharing structured “world models”; every conclusion claimed fully auditable to code or literature; publication-ready figures. Example discoveries named: SOD2 and myocardial fibrosis; SNP mechanism for reduced T2D risk. Best for high-dimensional data (scRNA-seq, proteomics, environmental parameters). **Not** positioned as a chatbot. — [Agents](https://docs.edisonscientific.com/agents.md); [overview](https://docs.edisonscientific.com/); [Kosmos announcement](https://edisonscientific.com/news/announcing-kosmos)
- **Literature**: search/synthesis over **175M+ papers, trials, and patents**; native understanding of citation graphs, journal quality, clinical trial data; reports with abstracts/conclusions; diagram creation and figure pullouts. Built with **PaperQA3**. — [Agents](https://docs.edisonscientific.com/agents.md); [Tasks](https://docs.edisonscientific.com/edison-client/tasks.md)
- PaperQA3 blog (2026-02-18) says Edison Literature and Kosmos can read figures/tables from **over 150M** research papers and patents and will consider hundreds of figures/tables before responding. That **150M** figure conflicts with docs’ **175M+**. — [PaperQA3 announcement](https://edisonscientific.com/news/edison-literature-agent)
- **Analysis** (alias Finch): biological experimental data (flow cytometry, RNA-seq, stats, visualization, multi-modal integration); protein tools and additional figure generation. User uploads data to Edison storage. — [Agents](https://docs.edisonscientific.com/agents.md); [File management](https://docs.edisonscientific.com/edison-client/file-management.md)
- **Precedent** (formerly **HasAnyone**, alias Owl): novelty / “has anyone done this” search across fields. Example in docs: SSR1 knock-in / lentiviral transduction novelty check. — [Agents](https://docs.edisonscientific.com/agents.md)
- **Molecules** (Phoenix; “new iteration of ChemCrow”): chemistry agent. Inputs: SMILES, CAS, IUPAC. Documented tools/outputs: ADMET, retrosynthesis, safety/toxicity (GHS, LD50, chemical-weapons screening mentioned in best-practices examples), ChEMBL search, logP/logS/QED/PSA, SAscore, Lipinski, reaction SMILES, enthalpy, lead optimization. — [Agents](https://docs.edisonscientific.com/agents.md); [Molecules best practices](https://docs.edisonscientific.com/guides/best-practices-for-interacting-with-edison-molecules.md); [Tasks](https://docs.edisonscientific.com/edison-client/tasks.md)
- API `JobNames` aliases: LITERATURE = `literature-20260216` / CROW / FALCON; LITERATURE_HIGH = `literature-high-20260216`; ANALYSIS = FINCH; PRECEDENT = OWL; MOLECULES = PHOENIX. — [API readme](https://docs.edisonscientific.com/edison-client/readme.md); [edison-client-docs GitHub](https://github.com/Future-House/edison-client-docs)
- **Robin** is the prior FutureHouse multi-agent “AI Scientist” (therapeutics-oriented; ripasudil / dry AMD story). Kosmos is explicitly a major upgrade on Robin, not a sixth current product agent. — [FutureHouse About](https://www.futurehouse.org/about); [Kosmos announcement](https://edisonscientific.com/news/announcing-kosmos); [arXiv 2511.02824](https://arxiv.org/abs/2511.02824)
- **ether0**: FutureHouse open-source chemistry reasoning model (not an Edison Platform agent). — [FutureHouse About](https://www.futurehouse.org/about)

### Inferences
- Product surface is **life-science / chemistry-first** even though Kosmos paper claims domain-generality (materials, neuroscience, statistical genetics appear in case studies).
- Literature vs Precedent is a useful split: synthesis vs novelty/gap finding. A paper factory should not collapse those into one “write a review” call.

### Gaps
- No public per-agent system-prompt, tool inventory, or timeout defaults except enterprise Profile schema.
- No independent product spec for how Precedent differs algorithmically from Literature (same PaperQA stack vs different retrieval?).
- platform.edisonscientific.com UI feature list not inspectable without login.

---

## PaperQA2/3, Aviary, LDP open-source stack vs hosted platform

### Takeaway
Open source is the **local RAG/agent gym stack** (PaperQA2, Aviary, LDP). Hosted Edison Literature/Kosmos literature is **PaperQA3** with a 150M+ figure-aware corpus, thinking-LLM autonomy, and LABBench2/HLE numbers. PaperQA3 algorithm improvements are described as updating “the underlying algorithm of our literature agent (which is open source)”; the public GitHub repo is still branded **PaperQA2**.

### Cited Findings
- **PaperQA2** (PyPI `paper-qa`): high-accuracy RAG on PDFs, Office, code; in-text citations; metadata-aware embeddings; LLM re-ranking and contextual summarization (RCS); agentic RAG; journal/citation metadata from multiple providers; local full-text search index; LiteLLM. Default OpenAI embeddings + Numpy vector DB. 2024 paper claimed superhuman precision / human-level accuracy on LitQA2. — [GitHub Future-House/paper-qa](https://github.com/future-house/paper-qa); [PaperQA2 docs](https://docs.edisonscientific.com/paperqa); mirrored on Edison docs
- PaperQA2 GitHub notes newer PDF readers (Docling and others) can parse images/tables and report page numbers; local LLM via Ollama/`paper-qa[local]`. Users must **provide PDFs**; agent `SearchPapers` queries a **local index**. Unpaywall mentioned for OA links. — [paper-qa README](https://github.com/future-house/paper-qa)
- **PaperQA3** (blog 2026-02-18): powers Edison Literature and Kosmos literature search. Multimodal figures/tables; agent inspects documents, reviews chunks, decides when to answer; less rigid harness; generated tables; citations with figures/page numbers; thinking-LLM token budget. Job names `literature-20260216` and `literature-20260216-high`. Claims +15–45% accuracy vs PQA2 on LABBench2 subsets; High Effort ~+7 points, “surpassing OpenAI GPT-5.2 Pro” on their reported setting. Parser: NVIDIA **Nemotron Parse**, ~10s/page latency, hundreds of thousands of pages/day on H200s. Design: agent **chooses when** to pull figures rather than multimodal embeddings over millions of docs. — [PaperQA3 announcement](https://edisonscientific.com/news/edison-literature-agent); NVIDIA case study linked from that post: [developer.nvidia.com/case-studies/scientific-literature-ai-nvidia-nemotron](https://developer.nvidia.com/case-studies/scientific-literature-ai-nvidia-nemotron)
- **Aviary**: gymnasium for language-agent RL environments (math, HotpotQA, cloning/DNA, literature Q&A via PaperQA, protein stability). Sister to LDP. Paper: arXiv 2412.21154 (HTML dated Aug 24, 2026 on arxiv.html). Claim: non-frontier LLMs trained online can match/exceed frontier agents and human PhDs on those tasks at much lower cost. — [FutureHouse Aviary post](https://www.futurehouse.org/research/aviary); [GitHub Future-House/aviary](https://github.com/Future-House/aviary); [arXiv 2412.21154](https://arxiv.org/html/2412.21154v1)
- **LDP** (Language Decision Processes): modular agents/environments/optimizers; language-grounded POMDPs; used with Aviary. Chat session messages convert `to_aviary_message()`. — [GitHub Future-House/ldp](https://github.com/future-house/ldp/); [Chat Sessions](https://docs.edisonscientific.com/edison-client/methods/chat-sessions.md)
- Edison docs host PaperQA, Aviary, and LDP sections (including PaperQA2 for Clinical Trials, LFRQA measurement, parser packages `paper-qa-pypdf`, `paper-qa-nemotron`, `paper-qa-pymupdf`). — [llms.txt](https://docs.edisonscientific.com/llms.txt)
- Dec 2025 $70M post: “major release of PaperQA today, our flagship open source literature agent.” — [We Raised $70M](https://edisonscientific.com/news/we-raised-70m-to-accelerate-science)
- FutureHouse About still lists PaperQA2 and Aviary as open-source; Kosmos commercialization is Edison. — [FutureHouse About](https://www.futurehouse.org/about)

### Inferences
- A local paper factory can **clone PaperQA2-style local PDF RAG + citations**, not the hosted 150M multimodal index or PaperQA3 production harness without reimplementation.
- `paper-qa-nemotron` appearing in Edison docs suggests they are publishing parser packages; whether full PaperQA3 agent loop is on GitHub as of 2026-10 is **not confirmed** from the PaperQA2-branded repo README.

### Gaps
- No arXiv PaperQA3 paper found in this pass (only the Feb 2026 blog + PaperQA2 2024 paper).
- License/version of `edison-client` and whether PaperQA3 weights/prompts are OSS: not verified beyond GitHub branding.
- Exact mapping of Crow vs Falcon (both alias LITERATURE) not explained in current JobNames table.

---

## API: JobNames, chat continuation, file storage, enterprise profiles; what is NOT on API (Kosmos)

### Takeaway
Public `edison-client` jobs are Literature, Literature High, Analysis, Precedent, Molecules. Docs **explicitly say Kosmos is not available via API**. A separate **Chat Sessions API is “only available for Kosmos users”** and is documented as subject to change—treat as a **docs contradiction**, not as Kosmos-on-API.

### Cited Findings
- Install: `uv pip install edison-client`. Auth: API key from [platform profile](https://platform.edisonscientific.com/profile). — [API readme](https://docs.edisonscientific.com/edison-client/readme.md)
- **“Please note that Kosmos is not available via API.”** — [Tasks](https://docs.edisonscientific.com/edison-client/tasks.md)
- `TaskRequest` fields: optional `id` UUID, `name` (job), `query`, `runtime_config`. Runtime can pass LDP `AgentConfig`, `timeout`, `max_steps`. — [API readme](https://docs.edisonscientific.com/edison-client/readme.md)
- Methods: `run_tasks_until_done` / async twin, `create_task`, `get_task`, `cancel_task`, `get_tasks`, `delete_trajectory`; storage: `store_file_content`, `fetch_data_from_storage`, `get_data_storage_entry`, `delete_data_storage_entry`, `search_data_storage`. — [llms.txt](https://docs.edisonscientific.com/llms.txt)
- **Task continuation**: `runtime_config: {"continued_job_id": task_id}` for follow-ups (example is Literature). — [Tasks](https://docs.edisonscientific.com/edison-client/tasks.md)
- Literature/Precedent responses: `PQATaskResponse` with `answer`, `formatted_answer`, `has_successful_answer`. Verbose: `agent_state`, `environment_frame` (contexts, paper metadata, answers), `metadata`. — [API readme](https://docs.edisonscientific.com/edison-client/readme.md)
- **File storage**: Analysis requires upload via `astore_file_content` (file or directory `as_collection=True`). Artifacts downloaded from `environment_frame["state"]["info"]["output_data"]`; >~10MB downloads to local FS. — [File management](https://docs.edisonscientific.com/edison-client/file-management.md)
- **Chat Sessions**: long-lived conversation keeping sandbox, workspace files, message history. Endpoints `/v0.1/chat` and `/v0.1/conversations`. Methods: `send_chat_message`, `get_conversation`, `get_conversations`, `queue_chat_message`, `recover_chat_session`, `store_conversation_message`; also `interrupt_chat_session`, `reset_chat_sandbox`. **NOTE: “The chat sessions API are only available for Kosmos users.”** Dispatch is async; no `wait_for_reply` in SDK—poll conversation. `ttl_seconds` 60–86400; per-turn `timeout` 30–172800. `data_storage_ids` mount files. `job_name` can be built-in JobNames or custom deployments. Example `job_name` in chat docs is `job-futurehouse-data-analysis-crow-high` (Analysis-like, not Kosmos). Messages convert to Aviary types. — [Chat Sessions](https://docs.edisonscientific.com/edison-client/methods/chat-sessions.md)
- **Enterprise Profile / custom jobs** (admin/write): `Profile` defines `base_image_tier`, packages, CPU/memory, timeouts, subagent jobs, model override, tools (must include `run_cell` and `reset_kernel`), prompt files, auto_skills, etc. Deploy via `create_job(JobDeploymentConfig)`. Layers: Profile (deploy), per-call RuntimeConfig, Directives. — [Agent Configurations](https://docs.edisonscientific.com/edison-client/agent-configurations)
- **Custom integrations** (enterprise only, sales@edisonscientific.com): same mechanism as built-in **Notion, Slack, Teams, Google Drive, GitHub**. Credentials in secret manager; sandbox egress proxy injects auth; agent never sees the key. Org vs user credential scope. Pair with markdown “skills” and `Profile.auto_skills`. — [Custom Integrations](https://docs.edisonscientific.com/edison-client/custom-integrations)

### Inferences
- Kosmos product access is **UI / credit-gated runs**, not `JobNames.KOSMOS`. Chat API is likely a **newer sandbox chat** gated to Kosmos-plan accounts, usable against Analysis/custom jobs—not a documented Kosmos `create_task` job.
- `has_successful_answer` is a rare honest-failure signal a paper factory should copy.

### Gaps
- OpenAPI spec / rate limits / payload size not fetched.
- Whether Kosmos world-model conversation promised in the $70M post (“converse directly with its world model”) shipped by 2026-10: not in public JobNames.
- Analysis tutorial’s exact `runtime_config` keys for attaching `data_storage.id` not fully captured here (tutorial exists: [edison_analysis_tutorial](https://docs.edisonscientific.com/edison-client/docs/edison_analysis_tutorial)).

---

## Auditability, world models, citation traces, figures, datasets, runtime

### Takeaway
The Kosmos **paper** (arXiv 2511.02824, Nov 2025) is the source of the quantitative loop; product docs repeat the averages. Auditability is **claim-to-code-or-passage linking**, not a public immutable lab notebook. Interpretation accuracy is the weak point (57% in the paper).

### Cited Findings
- **Paper (label: paper, not product SLA)**: given objective + dataset, Kosmos runs **up to 12 hours**; cycles of parallel analysis + literature + hypothesis; structured world model shared between Edison Analysis and Literature agents. Per cycle: up to **ten** literature/analysis tasks, then world-model update, then next-cycle task proposal. Average run: **42,000 lines of code** across **166** analysis rollouts; **1,500 full-length papers** across **36** literature rollouts; **~200 agent rollouts**; **9.8×** code vs Robin. Synthesizes **three or four scientific reports**. Claims cited to code or primary literature. Expert eval: **79.4%** of 102 statements accurate (85.5% analysis, 82.1% literature, **57% interpretation**). Collaborators (n=7): 20-cycle run ≈ **6.14 months** (σ=2.49) of their research time; valuable findings scale with cycles (tested to 20). Seven case-study discoveries (3 reproduce unpublished/preprint findings Kosmos did not access at runtime; 4 claimed novel). — [arXiv 2511.02824](https://arxiv.org/abs/2511.02824); [HTML](https://arxiv.org/html/2511.02824)
- **Paper limitations (technical)**: datasets **≲ ~5GB**; does **not** excel on raw images or raw sequencing; cannot autonomously pull public external datasets for orthogonal validation; stochastic (reruns diverge); sensitive to objective phrasing; **no scientist interaction in intermediate cycles**. Invents unorthodox metrics; conflates statistical vs scientific significance. — [arXiv HTML limitations](https://arxiv.org/html/2511.02824)
- **Product docs** echo 1500 papers / 42k LOC / world models / auditable traces / figures; dataset cap **uncompressed < 5GB**, “100s of files”; do not recommend mapping raw seq or annotating raw imaging; start small because **runtime scales with dataset size**. — [Agents](https://docs.edisonscientific.com/agents.md); [Kosmos best practices](https://docs.edisonscientific.com/guides/best-practices-for-optimizing-kosmos-workflows.md)
- **Product blog caveats**: not a chatbot; rabbit holes; run multiple times; $200/run at launch; Founding Subscriptions lock $1/credit. Independent time estimate: 15 min/paper + 2 h/analysis trajectory ≈ **4.1 months** at 40 h/week. Longer runs more likely to chase spurious correlations. — [Kosmos announcement](https://edisonscientific.com/news/announcing-kosmos)
- **Literature figures**: PaperQA3 reads figures/tables; citations show underlying figures/page numbers; example AlphaFold2 IPA ablation from Figure 4a with zoom. Trajectory URL: [platform.edisonscientific.com/trajectories/ad05e3c5-6578-4a62-8488-8e5c28f91bfb](https://platform.edisonscientific.com/trajectories/ad05e3c5-6578-4a62-8488-8e5c28f91bfb). Provenance extras: predatory journal flags, patent country, retractions. — [PaperQA3 announcement](https://edisonscientific.com/news/edison-literature-agent)
- **$70M post (Dec 2025) roadmap (not confirmed shipped)**: Kosmos auto-access data, steer exploration, converse with world model. — [We Raised $70M](https://edisonscientific.com/news/we-raised-70m-to-accelerate-science)
- Analysis artifacts: notebook + generated files via storage. — [File management](https://docs.edisonscientific.com/edison-client/file-management.md)

### Inferences
- “Fully auditable” means **trace links exist in the product**, not that 79.4% accuracy is a product guarantee. Interpretation/synthesis is the failure mode most dangerous for a manuscript factory.
- World model is the architectural idea worth borrowing: **structured shared state**, not a bigger context window.

### Gaps
- World-model schema (graph? JSON claims? embeddings?) is not in the public docs fetched.
- No public spec of figure file formats or how publication-ready figures are stored.
- Whether 12-hour / 20-cycle settings are user-tunable in the UI: not documented in the best-practices page.

---

## Pricing, academic free tier, target users (life sciences vs general academia)

### Takeaway
Credit system: Kosmos is expensive (200 credits/run); other agents cheap (1–2). Academic free credits are a **policy, not a SLA**, and numbers **moved between Nov 2025 and Feb 2026**. Commercial GTM is pharma/biotech; scientific coverage is biology-first with Kosmos case studies outside biology.

### Cited Findings
- Docs: “generous free tier for academics”; paid plans for higher rate limits; contact@edisonscientific.com. — [overview](https://docs.edisonscientific.com/)
- **Kosmos launch (2025-11-05)**: $200/run = 200 credits at $1/credit; academic free-tier usage; Founding Subscriptions lock $1/credit; price “ultimately will probably be higher”; framed as a reagent kit not a chatbot. — [Kosmos announcement](https://edisonscientific.com/news/announcing-kosmos)
- **$70M seed (2025-12-18)**: academics and students **650 credits/mo indefinitely** (“can’t promise forever”). Kosmos 200 credits; Analysis/Literature etc. **1 or 2 credits**. Paid users: regular agents **free via UI**; **API still paid**. Unpaid: **10 credits/month** for those agents. **$200/mo for 650 credits/mo** “staying for now, might be phased out at next major product update.” Hiring/GTM language is pharmaceutical companies. — [We Raised $70M](https://edisonscientific.com/news/we-raised-70m-to-accelerate-science)
- LinkedIn (Samuel G. Rodriques, 2025-11-11): doubling edu credits to **1300**/month (six Kosmos runs + agent runs), expire after a month; Kosmos satisfaction-guarantee credit refund. **Conflicts with later 650/mo statement.** — [LinkedIn post](https://www.linkedin.com/posts/samuel-g-rodriques-080a9b22_by-popular-demand-were-doubling-the-number-activity-7394098276733476864-Cm4J)
- PaperQA3 blog (2026-02-18): normal Literature **free with subscription**; academics **~20 free calls/day**. High Effort is the paid/SOTA mode. — [PaperQA3 announcement](https://edisonscientific.com/news/edison-literature-agent)
- **ACU Grant** (deadline 2026-01-08): up to 5 awards, **20,000 credits** (~100 Kosmos runs), 4-month validity, scientist support; PIs/staff/postdocs/PhDs at universities and nonprofits; “accepting all scientific fields” but **most support for life sciences**; must publish preprint and/or Edison blog with data QC + human validation of Kosmos findings. — [ACU Grant](https://edisonscientific.com/news/edison-platform-acu-grant)
- FutureHouse: nonprofit, biology/health, AI-for-Science Independent Postdoctoral Fellowship, 3,000 sq ft wet lab; funders Schmidt, OpenPhilanthropy, NSF, AI Safety Institute. Edison commercializes tools. — [FutureHouse About](https://www.futurehouse.org/about)
- Edison inbound interest claimed from “VP- or C-level executives at 6 of the top 10 pharma companies.” — [Introducing Edison Scientific](https://edisonscientific.com/news/announcing-edison-scientific)

### Inferences
- For a **general-academia paper factory**, Edison is a **life-science/pharma product with a literature agent that happens to index broadly**—not a writing tool for all fields equally.
- Credit math at 650/mo and 200/Kosmos ≈ **3 Kosmos runs/month** for academics (plus cheap Literature/Analysis).

### Gaps
- No public pricing page with current (2026-10) SKUs fetched; blog posts may be stale vs in-app billing.
- Literature High credit cost vs standard 1–2 credits: not specified.
- Enterprise contract pricing: sales-only.

---

## YOUR papers vs public corpus; Zotero / library integration

### Takeaway
Hosted Literature answers over Edison’s **licensed/aggregated public corpus** (papers, trials, patents). **Your PDFs** are first-class in **open-source PaperQA2** (folder index + Zotero). Hosted **Analysis/Kosmos** take **your datasets** via storage, not a documented Zotero sync. Enterprise can connect Drive/GitHub/Notion.

### Cited Findings
- Hosted Literature: 175M+ (docs) / 150M+ with figures (blog) papers, trials, patents; PDF-centric ingest (not webpages). Metadata for journal quality, retractions, patent geography. — [Agents](https://docs.edisonscientific.com/agents.md); [PaperQA3 announcement](https://edisonscientific.com/news/edison-literature-agent)
- Open-source PaperQA2: “usable full-text search engine for a **local repository** of PDF/text files”; `SearchPapers` uses local index; “you will need to provide PDFs yourself.” — [paper-qa README](https://github.com/future-house/paper-qa); [PaperQA2 docs](https://docs.edisonscientific.com/paperqa)
- **Zotero**: `pip install paper-qa[zotero]`; `paperqa.contrib.ZoteroDB` via pyzotero; personal or group library; requires PDFs attached in Zotero; env `ZOTERO_USER_ID`, `ZOTERO_API_KEY` (read). Maintainers note: **“It’s been a while since we’ve tested this.”** Also OpenReview helper extra; **paper-scraper warned as possible publisher ToS/legal gray area**. — [Where to get papers](https://docs.edisonscientific.com/paperqa/docs/tutorials/where_do_i_get_papers.md)
- Kosmos/Analysis: user-provided datasets (processed, labeled columns, <5GB). Kosmos paper: cannot autonomously fetch public reference datasets. — [Kosmos best practices](https://docs.edisonscientific.com/guides/best-practices-for-optimizing-kosmos-workflows.md); [arXiv 2511.02824](https://arxiv.org/html/2511.02824)
- Built-in enterprise connectors: Notion, Slack, Teams, **Google Drive**, **GitHub**. No Zotero named on the hosted custom-integrations page. — [Custom Integrations](https://docs.edisonscientific.com/edison-client/custom-integrations)

### Inferences
- Hosted Literature is **not** “chat with my Zotero library” unless an undocumented UI upload exists (not in fetched docs).
- A local paper factory should treat **user library PDFs as the source of truth** (PaperQA2 path) and treat any public-web scrape as legally unsafe (their own warning).

### Gaps
- No fetched doc describing uploading private PDFs into hosted Literature/Kosmos literature search.
- No EndNote/Mendeley/BibTeX hosted integration found.

---

## Competitors they name or sit next to

### Takeaway
They name other **AI scientists / deep research systems**, not Elicit/Consensus/SciSpace. Third parties place Edison next to those literature tools plus OpenAI Deep Research.

### Cited Findings
- **Kosmos paper related work**: FutureHouse **Robin**; **Sakana AI Scientist** (ML-only manuscript loop); **Google AI co-scientist** (hypotheses, no experiments/analysis); **The Virtual Lab** (nanobodies; lacks exploratory data analysis). — [arXiv 2511.02824 intro](https://arxiv.org/html/2511.02824)
- **Kosmos blog**: Deep Research-like (not chatbot); METR task-length estimates; GPT-4o/GPT-5 as contrasts; PaperQA2 vs Wikipedia-article labor. — [Kosmos announcement](https://edisonscientific.com/news/announcing-kosmos)
- **PaperQA3 blog**: benchmarks vs **GPT-5.2**, **GPT-5.2 Pro**, **Opus 4.6**, “current-day frontier deep research agents”; notes most DR agents use **web search** (leakage risk) vs their PDF corpus. LABBench2 (Edison) subsets FigQA2, PatentQA, LitQA3, TrialQA; HLE Bio/Chem. — [PaperQA3 announcement](https://edisonscientific.com/news/edison-literature-agent)
- Molecules docs: **ChemCrow** predecessor. — [Tasks](https://docs.edisonscientific.com/edison-client/tasks.md)
- Third-party aggregator [monarch-initiative/deep-research-client](https://github.com/monarch-initiative/deep-research-client/): lists Edison (formerly FutureHouse Falcon) beside OpenAI Deep Research, Asta, Perplexity, Consensus, OpenScientist, Claude Code, Biomni, ToolUniverse.
- Third-party comparison [Cortexa benchmarks](https://cortexa.sh/benchmarks): “Edison / Kosmos” as autonomous discovery vs Claude Science, Elicit, Asta, SciSpace, Consensus, Scite, OpenAI/Google science stacks, Perplexity. (Vendor comparison page; not Edison-authored.)

### Inferences
- Competitive set they care about: **autonomous scientists and frontier DR**, not “AI writing for papers.” Cloning Elicit-style systematic review UI is not their product thesis.
- Falcon remaining as a JobNames alias is why wrappers still say “formerly FutureHouse Falcon.”

### Gaps
- Edison does not publish a competitor matrix.
- No head-to-head vs Elicit/Consensus on systematic review workflows in their docs.

---

## What a local open-source paper factory should borrow vs refuse to clone

### Takeaway
Borrow **grounded local-PDF synthesis, citation traces, novelty-vs-synthesis split, honest failure flags, and structured long-run state**. Refuse **hosted 150M corpus, Kosmos-as-PhD, chem-weapon/ADMET product surface, publisher-gray scraping, and treating 57%-accurate interpretation as manuscript text**.

### Cited Findings
- PaperQA2 is explicitly designed for **local PDF repositories**, in-text citations, agentic query refinement, and user-supplied files—including Zotero. — [paper-qa](https://github.com/future-house/paper-qa); [Where to get papers](https://docs.edisonscientific.com/paperqa/docs/tutorials/where_do_i_get_papers.md)
- Hosted Literature differentiators that require their corpus/ops: 150M+ multimodal PDFs, Nemotron Parse at H200 scale, retraction/predatory metadata, LABBench2/HLE-tuned High Effort. — [PaperQA3 announcement](https://edisonscientific.com/news/edison-literature-agent)
- Kosmos paper: 57% accuracy on interpretation statements; rabbit holes; no mid-run steering (as of Nov 2025 paper); 5GB/raw-data limits. Blog: run multiple times; not a chatbot. — [arXiv 2511.02824](https://arxiv.org/html/2511.02824); [Kosmos announcement](https://edisonscientific.com/news/announcing-kosmos)
- Their own paper-scraper note: possible violation of publisher rights. — [Where to get papers](https://docs.edisonscientific.com/paperqa/docs/tutorials/where_do_i_get_papers.md)
- Molecules best practices include **chemical weapons screening** as an example safety check—hosted chem tooling, not a writing-stack requirement. — [Molecules best practices](https://docs.edisonscientific.com/guides/best-practices-for-interacting-with-edison-molecules.md)
- ACU grant requires **human validation** of Kosmos findings before publication. — [ACU Grant](https://edisonscientific.com/news/edison-platform-acu-grant)

### Inferences
**Borrow (docs-backed, local-feasible):**
- Library → PDFs → chunk/index → agentic retrieve/summarize → **cited answer with page/figure pointers**.
- `has_successful_answer` / refuse to write when evidence is thin.
- Split **Precedent-style novelty check** from **Literature-style synthesis** before any manuscript outline.
- Structured **world model / running claim graph** if you ever do multi-hour loops—do not dump 1500 papers into one context.
- Journal-quality / retraction metadata when available (OpenAlex, Crossref, etc.), not only full text.
- Continuation IDs for multi-turn reviews (`continued_job_id` pattern).
- High-effort vs cheap modes (thinking-token budget) as a user-visible control.
- Processed, well-described inputs; do not pretend to map raw NGS or parse all figures at NVIDIA production scale.

**Refuse to clone (wrong objective, uncloneable, or scientifically unsafe):**
- Marketing of “6 months of a PhD in one day” as a product requirement or eval target (survey of n=7 beta users).
- Autonomous **discovery reports as papers** without human claim-by-claim audit (their grant even requires this).
- Replicating 175M/150M full-text+figure corpus (licensing + compute).
- Publisher-gray **paper scraping**.
- ChemCrow/Phoenix **synthesis planning / weapons screening / ADMET** as part of a manuscript factory.
- Enterprise secret-proxy / Kubernetes sandbox / custom job images unless you are building a hosted lab agent.
- Kosmos-scale unattended 12-hour data analysis on private biomedical data without sandbox and QC (their own raw-data warning).
- Collapsing Literature High benchmarks vs GPT-5.2 Pro into a claim that a local factory “beats frontier DR.”
- Bird-named agent zoo as UX; keep a small explicit pipeline (ingest → retrieve → synthesize → novelty → outline) instead.

### Gaps
- No public evaluation of Edison Literature on **user-private libraries only** (the paper-factory setting).
- No fetched TOS on training on user papers/datasets.
