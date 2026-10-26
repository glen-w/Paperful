# Hosted literature discovery, systematic-review, and evidence-synthesis platforms (ex-Edison/FutureHouse, ex-Zotero plugins)

Last reviewed: 2026-10-26. Public docs and library guides only. Labels: **verified** = vendor official page or peer-reviewed paper; **marketing** = vendor claims without independent check; **library-guide** = university/aggregator secondary source; **conflict** = sources disagree.

Scope exclusions applied: Edison/FutureHouse; Zotero plugins (PapersGPT, ZoteroGPT noted only as out-of-scope). ChatPDF successors covered only where a hosted product still exists independently.

Factory stages used below: **discover, screen, get PDF, extract, synthesize, cite, write, keep current**.

---

## Which stages of “paper factory” do they own?

### Takeaway
No hosted product owns the full factory. Closest synthesis-plus-review stacks are Elicit (discover→screen→extract→report) and Consensus (discover→synthesize→cite, with library uploads). Screening specialists (Covidence, Rayyan, DistillerSR, ASReview) own screen/extract/audit but not discovery or writing. Graph tools (ResearchRabbit, Litmaps, Connected Papers, Inciteful) own discover plus some keep-current. Reading tools (Scholarcy, Explainpaper, Humata, Gemini Notebook/NotebookLM) own extract/synthesize on user-supplied PDFs only. Infrastructure (OpenAlex, Semantic Scholar API, CORE) supplies corpus, not a factory.

### Cited Findings

#### Elicit (Ought) — job: AI literature review + systematic-review workflow
- Job: search, summarize, extract into tables, Research Agent/Reports, and a dedicated Systematic Review workflow (setup → gather → title/abstract screen → optional full-text screen → extract → research report). Dual independent screening is Enterprise-only. — [Elicit Systematic Reviews](https://support.elicit.com/en/articles/14759154-systematic-reviews-in-elicit) **verified**
- Corpus: “over 138 million academic papers from Semantic Scholar, PubMed, and OpenAlex,” weekly updates; ClinicalTrials.gov as a separate search corpus; overlap is deduplicated. Semantic Scholar cited as 200M+, OpenAlex 243M, PubMed 33M+. — [Elicit’s source for papers](https://support.elicit.com/en/articles/14758040-elicit-s-source-for-papers) **verified**
- PDF: paid plans include PDF parsing; “Premium PDF parsing” (all plans except Basic) uses a heavier model for formulae/figures/tables and unlocks figure extraction on Scale/Enterprise; usage rises while it is on. Users can upload PDFs or pick from Elicit Library. — [Systematic Reviews](https://support.elicit.com/en/articles/14759154-systematic-reviews-in-elicit); [Usage limits](https://support.elicit.com/en/articles/15646622-usage-limits-in-elicit) **verified**
- Synthesis: Research Agent, Research Reports, custom table columns, Routines (Pro+). Marketing: “save up to 80% of time” on SRs. — [Systematic Reviews](https://support.elicit.com/en/articles/14759154-systematic-reviews-in-elicit) **marketing** on 80%; workflow **verified**
- Citations/audit: “View sources for answers”; Pro “Explanations for AI-generated answers”; Enterprise claims “PRISMA-grade screening and extraction accuracy.” — [Pricing](https://elicit.com/pricing) **verified** as product copy; PRISMA-grade is **marketing**
- Export / API: API + MCP for search, reports, full SR (Pro/Scale/Enterprise). Report paper caps: default 80; Pro 135; Scale/Enterprise 200. Screen caps: Pro 5,000; Scale 20,000; Enterprise 40,000 papers per review. — [Elicit’s API](https://support.elicit.com/en/articles/14757400-elicit-s-api); [Systematic Reviews](https://support.elicit.com/en/articles/14759154-systematic-reviews-in-elicit) **verified**
- Library: “Import from Zotero” on Basic. No Mendeley named on pricing. — [Pricing](https://elicit.com/pricing) **verified**
- Pricing (Industry yearly, Oct 2026): Basic free (limited Agent/Reports; unlimited search/summaries/chat with full-text access); Pro $49/user/month billed $588/yr; Scale $229/user/month billed $2,748/yr; Enterprise custom. Extra usage on Pro/Scale billed in $100 increments. Unused usage does not roll over. — [Pricing](https://elicit.com/pricing); [Usage limits](https://support.elicit.com/en/articles/15646622-usage-limits-in-elicit) **verified**
- Independent accuracy (**not marketing**): four-review comparison found Elicit Pro Review-mode sensitivity **39.5%** (25.5–69.2%) vs original searches **94.5%**, but precision **41.8%** vs **7.55%**; some unique includes. Conclusion: not a replacement for traditional searching; useful adjunct. — [Lau & Golder 2025, Cochrane ESM, PMC12483133](https://pmc.ncbi.nlm.nih.gov/articles/PMC12483133/) **verified**
- Extraction vs humans on 20 RCTs: across seven variables, Elicit “more” 29.3%, “equal” 20.7%, “partially equal” 45.7%, “deviating” 4.3%; intervention effects 95% “partially equal.” Authors require human verification. — [Bianchi et al. 2025, PMC12462964](https://pmc.ncbi.nlm.nih.gov/articles/PMC12462964/) **verified**
- Bernard et al. 2025: Elicit search **not repeatable** (246 / 169 / 172 results across three trials); 3 papers in common with an umbrella review, 3 unique to Elicit, 17 unique to traditional search. — [BMC Med Res Methodol](https://link.springer.com/article/10.1186/s12874-025-02528-y) **verified**
- Factory stages: **Yes** discover, screen, extract, synthesize, cite (with sources), write (report templates). **Partial** get PDF (upload/OA/parsing, not campus proxy). **Partial** keep current (weekly corpus; not a monitoring product). Dual screen/PRISMA workflow **Partial** (Enterprise dual review).

#### Consensus — job: evidence-grounded academic search + synthesis
- Job: hybrid search then AI synthesis (Pro Analysis, Consensus Meter, Study Snapshots, Deep Review / Research Agent). “Won’t write your Literature Review.” — [Welcome to Consensus](https://consensus.app/home/blog/welcome-to-consensus/) **verified**; writing disclaimer **verified**
- Corpus **conflict**: blog “over 200 million” from Semantic Scholar + OpenAlex + own crawl; help center “over 220 million… updated weekly” plus “publisher partnerships and full-text access agreements”; product docs “400M+ scholarly articles” / MCP “400 million… including 350 million peer-reviewed.” — [Blog](https://consensus.app/home/blog/welcome-to-consensus/); [Research Database](https://help.consensus.app/en/articles/10055108-consensus-research-database); [Paper search](https://docs.consensus.app/get-started/how-search-works); [MCP](https://docs.consensus.app/consensus-mcp) **conflict**
- PDF: OA PDFs pulled into app with passage click-through; user uploads and Zotero PDFs (files stored in Zotero, not externally linked); LibKey **link-resolves institutional subscriptions but Consensus does not ingest LibKey full text**. Analysis may use licensed full text while the reader still hits a paywall. Abstract fallback when no full text. — [Read the full paper](https://docs.consensus.app/get-started/full-text-access) **verified**
- Synthesis: Study Snapshot (PICO-like fields); Pro/Deep agent (Deep Review: up to 20 parallel searches, ~50–100 papers); Consensus Meter on first ~20 yes/no results. — [Paper search](https://docs.consensus.app/get-started/how-search-works); [Welcome](https://consensus.app/home/blog/welcome-to-consensus/) **verified**
- Citations/audit: every paper cited is retrieved first (no invented refs, per vendor); “checker models”; hover quotes; tick icon = full text used. Hallucination type 3 (misread real paper) still possible. — [Welcome](https://consensus.app/home/blog/welcome-to-consensus/) **verified** as design claim; residual misread **vendor-acknowledged**
- Export / MCP: API + MCP (`search`, thread tools); paid plans get `include_full_text_chunks`. Library on all plans. — [MCP](https://docs.consensus.app/consensus-mcp); [Full text](https://docs.consensus.app/get-started/full-text-access) **verified**
- Library: one-way Zotero import (personal + group, no size limit); re-import to refresh; only journal articles used in analysis. — [Library](https://docs.consensus.app/core-features/library) **verified**
- Pricing (help, 12 Sep 2026): Free $0 (unlimited paper search, 10 Pro msgs, 3 Deep reviews, 10 snapshots, 30 API/MCP calls); Pro $20/mo or $144/yr; Deep $65/mo or $540/yr; Teams custom (Pro + 50 Deep/user); Enterprise custom. — [Subscription Plans](https://help.consensus.app/en/articles/10087865-subscription-plans) **verified**
- Factory: **Yes** discover, synthesize, cite. **Partial** get PDF (OA + uploads + licensed analysis, no proxy fetch). **Partial** extract (snapshots/tables). **Partial** screen (ranking, not dual-review SR). **No** write manuscript. **Partial** keep current (weekly index).

#### Scite (Research Solutions) — job: citation-context / Smart Citations
- Job: discover and evaluate papers via citation statements classified as supporting / contrasting / mentioning; Assistant Q&A; collections; MCP. Now part of Research Solutions. — [Pricing](https://scite.ai/pricing) **verified**
- Corpus: pricing page “1.6B+ Citations, 300M+ Scholarly sources, 44+ publishers, 2M+ users.” QUT guide: “1.2B+ citations indexed.” — [Pricing](https://scite.ai/pricing) **marketing**; [QUT](https://libguides.library.qut.edu.au/library-guidance-for-ai/academic-ai-search-tools) **library-guide** **conflict** on citation count
- PDF: not a PDF-fetch product; publisher partnerships for citation context from full text. QUT: no direct library integration, limited OA discovery. — [QUT](https://libguides.library.qut.edu.au/library-guidance-for-ai/academic-ai-search-tools) **library-guide**
- Synthesis: Assistant answers from full texts (Tulane lists “Assistant by Scite”). Not an SR extractor. — [Tulane AI tools](https://libguides.tulane.edu/AI/tools) **library-guide**
- Citations/audit: Smart Citations are the product’s audit primitive (how later papers treat a claim). — [Pricing FAQ](https://scite.ai/pricing) **verified**
- Export: RIS/BibTeX (QUT). API on Pro/Team. — [QUT](https://libguides.library.qut.edu.au/library-guidance-for-ai/academic-ai-search-tools) **library-guide**; [Pricing](https://scite.ai/pricing) **verified** API
- Library: Collections 1,000 papers (Basic) / 10,000 (Pro). Browser extension for journals. Zotero/Mendeley not documented on pricing page. — [Pricing](https://scite.ai/pricing) **verified**
- Pricing: Basic $12 (250 MCP credits/mo); Pro adds API, 2,500 MCP credits, patents/trials/grants, $60 API credit promo; Enterprise custom (SSO/IP, FAERS/MAUDE/510(k)). 7-day trial auto-converts. Student/academic discount via institutional referral. — [Pricing](https://scite.ai/pricing) **verified**
- Factory: **Yes** discover, cite (context). **Partial** synthesize (Assistant). **No** screen/extract/write/keep-current product. **No** get PDF.

#### Semantic Scholar (Ai2) — job: free academic graph + TLDRs
- Job: discovery, TLDRs, influential citations, author pages; not a synthesis factory. — [Georgetown](https://guides.library.georgetown.edu/ai/tools) **library-guide**; [Glasgow](https://www.gla.ac.uk/myglasgow/library/ai/) **library-guide**
- Corpus (API marketing page): **214 million papers**, **2.49 billion** citations (third figure “79 million” shown as authors/entities). — [S2 API](https://www.semanticscholar.org/product/api) **verified**
- PDF: OA/publisher partnerships; not campus-proxy fetch. Feeds many other tools. — [Glasgow](https://www.gla.ac.uk/myglasgow/library/ai/) **library-guide**
- Synthesis: SciTLDR summaries only. — [Georgetown](https://guides.library.georgetown.edu/ai/tools) **library-guide**
- Pricing: free. API: unauthenticated shared 1000 rps; API key intro **1 RPS**; keys prioritized for academic/nonprofit/gov. — [S2 API](https://www.semanticscholar.org/product/api) **verified**
- Factory: **Yes** discover. **Partial** cite (graph). **Partial** extract (TLDR). **No** screen/synthesize-across/write. **Partial** keep current (live index).

#### Undermind — job: iterative deep literature search / “co-researcher”
- Job: follow-up questions → searches/citation trails → reports/tables → full-text dive → alerts. Positions against Google Scholar and frontier web agents. — [undermind.ai](https://undermind.ai/) **verified**
- Corpus: QUT/Georgetown: via Semantic Scholar (~215M). Vendor homepage does not state a corpus size. — [QUT](https://libguides.library.qut.edu.au/library-guidance-for-ai/academic-ai-search-tools) **library-guide**
- PDF: Pro “Deepest analysis of full texts”; export CSV/BibTeX/RIS; QUT: no library integration, OA via linked sources. — [undermind.ai](https://undermind.ai/) **verified**; [QUT](https://libguides.library.qut.edu.au/library-guidance-for-ai/academic-ai-search-tools) **library-guide**
- Citations: inline citations to source papers. — [undermind.ai](https://undermind.ai/) **verified**
- Keep current: “notifies you with important updates.” — [undermind.ai](https://undermind.ai/) **verified**
- Pricing: Free (standard limits, agent connect); Pro **$16/mo billed annually**; Team **$15/person/mo annually**; Enterprise custom. “No training” on company data. — [undermind.ai](https://undermind.ai/) **verified**
- Benchmark (vendor, 23 queries, GPT-5.6 Sol judge on abstracts): Undermind deep search recall@20 **85%**, all-relevant **75%**, precision **58%** vs GPT-5.6 Sol 50/38/40 and Claude Opus 5 47/33/35 at 10 minutes. Production search stops ~2.9 min average. — [undermind.ai](https://undermind.ai/) **marketing** (self-benchmark)
- Factory: **Yes** discover, synthesize, cite, keep current. **Partial** extract (tables). **Partial** get PDF (full-text analysis, not fetch). **No** dual-review screen, **No** manuscript write.

#### SciSpace / Typeset — job: Q&A + PDF copilot + SLR/writer workspace
- Job (vendor compare page vs Connected Papers): cited answers, PDF chat, extraction tables, SLR workflow, AI Writer with reference management. — [SciSpace vs Connected Papers](https://scispace.com/compare/connected-papers) **marketing**
- Corpus: QUT 270M+; Glasgow: S2, OpenAlex, Google Scholar, “trusted repositories.” — [QUT](https://libguides.library.qut.edu.au/library-guidance-for-ai/academic-ai-search-tools); [Glasgow](https://www.gla.ac.uk/myglasgow/library/ai/) **library-guide**
- PDF: chat with PDFs; Chrome Copilot; “some OA versions”; no library integration (QUT). Export CSV/XLSX/BIBTEX. — [QUT](https://libguides.library.qut.edu.au/library-guidance-for-ai/academic-ai-search-tools); [SciSpace compare](https://scispace.com/compare/connected-papers) **marketing**+**library-guide**
- Pricing (vendor compare, 2026): Basic 100 credits; Premium **$20/mo**, 1,200 credits; Advanced **$90/mo**, 10,000; Max **$200/mo**, 40,000. Official `/pricing` returned **403** on 2026-10-26. — [Compare](https://scispace.com/compare/connected-papers) **marketing**; pricing page **gap**
- Independent: Đukić et al. 2024 tested Elicit and SciSpace on SLR search/screening; assistance useful, human expertise still required. — [RFOS/Springer](https://rfos.fon.bg.ac.rs/handle/123456789/2821) **verified** (abstract-level)
- Factory: **Yes** discover, extract, synthesize, write (AI Writer). **Partial** screen (SLR workflow claimed). **Partial** cite. **Partial** get PDF. **No** verified keep-current.

#### ResearchRabbit — job: citation-map discovery
- Job: visualize similar papers/authors; collections; collaboration. — [Georgetown](https://guides.library.georgetown.edu/ai/tools) **library-guide**
- Corpus: OpenAlex + Semantic Scholar (Georgetown); S2 + PubMed (Glasgow). — **library-guide** **conflict**
- PDF: QUT “no built-in OA discovery”; no extension. Export RIS/BibTeX. — [QUT](https://libguides.library.qut.edu.au/library-guidance-for-ai/academic-ai-search-tools) **library-guide**
- Library: Zotero import (Effortless Academic); Georgetown “currently free”; UNC 2026 guide: free forever + optional paid from **$12.50/month**; Effortless Academic: paid $12.50. — [UNC](https://guides.lib.unc.edu/genai_for_research_lifecycle/explore); [Effortless Academic](https://effortlessacademic.com/litmaps-vs-researchrabbit-vs-connected-papers-the-best-literature-review-tool-in-2025/) **conflict** free vs paid
- Factory: **Yes** discover. **Partial** keep current (author/paper monitoring commonly claimed; not re-verified on official FAQ this pass). **No** screen/extract/synthesize/write. **No** get PDF.

#### Litmaps — job: citation-timeline maps + alerts
- Job: seed-paper maps, advanced search, monitoring, sharing. — [Litmaps pricing](https://www.litmaps.com/pricing) **verified**
- Corpus: QUT 250M+ (OpenAlex, S2, Crossref); LibKey for PDF download. — [QUT](https://libguides.library.qut.edu.au/library-guidance-for-ai/academic-ai-search-tools) **library-guide**
- Library: Effortless Academic: Zotero; **2-way sync paid-only**. — [Effortless Academic](https://effortlessacademic.com/litmaps-vs-researchrabbit-vs-connected-papers-the-best-literature-review-tool-in-2025/) **not official**
- Pricing (official page, messy scrape): Free = limited maps/articles (one block: 2 maps / 100 articles / 20 inputs; another: 1 Litmap / 100 articles); Education Pro **~$10/** (asterisk; UNC “around $10 per month billed annually”); Team unlimited. Alerts: Free monthly summary vs Pro weekly/daily configurable. — [Litmaps pricing](https://www.litmaps.com/pricing) **verified** incomplete dollar amount; [UNC](https://guides.lib.unc.edu/genai_for_research_lifecycle/explore) **library-guide**
- Factory: **Yes** discover, keep current. **Partial** get PDF (LibKey links). **No** screen/extract/synthesize/write.

#### Connected Papers — job: similarity graph from a seed
- Job: similarity graph, Prior Works / Derivative Works, multi-origin graphs, saved papers, history. — [connectedpapers.com/pricing](https://www.connectedpapers.com/pricing) **verified**
- Corpus: Semantic Scholar (Georgetown/Glasgow). — **library-guide**
- Export: SciSpace compare claims Zotero + standard formats. — [SciSpace compare](https://scispace.com/compare/connected-papers) **marketing**
- Pricing: Free **5 graphs/month**, all features; Academic vs Business both unlimited graphs (Academic = academia/nonprofit/personal; Business = commercial). SciSpace compare lists Academic **$6/mo billed $72/yr**, Business **$20/mo**. Official page did not render numeric Academic/Business prices in the fetch. — [Official](https://www.connectedpapers.com/pricing) **verified** structure; dollar amounts **marketing**/secondary
- Factory: **Yes** discover. **No** screen/PDF/extract/synthesize/write/keep-current.

#### Inciteful — job: free citation-network analysis
- Job: build a paper network and rank relevant literature. — [Glasgow](https://www.gla.ac.uk/myglasgow/library/ai/); [Tulane](https://libguides.tulane.edu/AI/tools) **library-guide**
- Corpus: OpenAlex, Semantic Scholar, CrossRef, OpenCitations; LLM “N/A”; **Free**. — [Glasgow](https://www.gla.ac.uk/myglasgow/library/ai/) **library-guide**
- Factory: **Yes** discover. **No** other factory stages. Official pricing/docs not fetched this pass (**gap**).

#### Covidence — job: Cochrane-style evidence-synthesis workbench
- Job: import/dedup, title-abstract + full-text screening, data extraction forms, risk of bias; Cochrane-recommended for new Cochrane reviews; export to RevMan. — [CASRAI SLR tools](https://casrai.org/guides/systematic-literature-review-tools) **library-guide**
- Corpus: none of its own — user-imported records. — [CASRAI](https://casrai.org/guides/systematic-literature-review-tools) **library-guide**
- PDF: screening of imported PDFs; not discovery/fetch. Mobile title/abstract screening. — [Covidence pricing](https://www.covidence.org/pricing/) **verified**
- Library: RIS/CSV/PubMedXML; named: CRS, EndNote, **Zotero, Refworks, Mendeley**, RevMan. — [Covidence pricing](https://www.covidence.org/pricing/) **verified**
- Pricing: Single **$339 USD/year** (1 review, unlimited collaborators, 12 months); Package **$907/year** (up to 3 reviews); Institutions custom (unlimited reviews/users, Cochrane Interactive Learning licenses). No extra student discount; LMIC concessions. Not-for-profit, Future Evidence Foundation. — [Covidence pricing](https://www.covidence.org/pricing/) **verified**
- Factory: **Yes** screen, extract (forms), cite/audit (review log, PRISMA counts typically). **Partial** synthesize (RoB; stats in RevMan). **No** discover, get PDF from web, write paper, keep current.

#### Rayyan — job: collaborative AI-assisted screening
- Job: import, dedup, ML relevance ranking from reviewer decisions, blind dual screen, PRISMA counts; PICO extraction on higher tiers; not full extraction/RoB (CASRAI). — [CASRAI](https://casrai.org/guides/systematic-literature-review-tools) **library-guide**; [Rayyan pricing](https://www.rayyan.ai/pricing) **verified** (import types)
- Import: .ris .bib .enw .csv .txt .ciw .nbib .xml .pdf; “PDF First Import” on paid comparison table (details truncated in fetch). — [Rayyan pricing](https://www.rayyan.ai/pricing) **verified**
- Pricing **conflict**: official page Free $0 (3 active reviews); Essential **$8.33/mo billed quarterly**; Advanced **$13.33/mo billed quarterly**; Business/Enterprise. Research Tool Bench (checked 2026-08-16 vs vendor): Essential **US$4.99/mo billed annually**, Advanced **US$8.33/mo billed annually**. Littview 3 Sep 2026 repeats $4.99/$8.33 annual. Treat **billing cadence** as conflict; annual vs quarterly both claimed. — [Rayyan](https://www.rayyan.ai/pricing) **verified**; [Research Tool Bench](https://researchtoolbench.com/pricing-tracker/) **secondary**
- Factory: **Yes** screen. **Partial** extract (PICO on Advanced per third parties). **Partial** get PDF (attach/import). **No** discover/synthesize/write. Library via RIS/BibTeX from Zotero/Mendeley, not live sync.

#### DistillerSR (Evidence Partners) — job: regulated/high-volume review platform
- Job: configurable multi-level screening, extraction forms, ML prioritization, literature monitoring, pharmacovigilance, audit trails for regulatory dossiers. — [CASRAI](https://casrai.org/guides/systematic-literature-review-tools) **library-guide**
- Pricing: quote-based enterprise (CASRAI). Stanford Lane lists student/faculty monthly figures ($19.95 / $94 / $194 project) — **unverified against vendor** (product URL 404 this pass). — [Stanford Lane](https://laneguides.stanford.edu/c.php?g=1510721&p=11401116) **library-guide**; official product page **gap**
- Factory: **Yes** screen, extract, audit, **Partial** keep current (literature monitoring). **No** open discovery corpus, **No** write.

#### ASReview (Utrecht University) — job: open-source active-learning screening
- Job: local/open-source AI ranking that retrains after each decision; simulate/benchmark models; CrowdScreen; Screenathon example 12,473 records in two days. Claims “reduce your workload by 95%.” — [asreview.nl](https://asreview.nl/) **verified** product; 95% **marketing**
- Pricing: free open-source; 903K+ installations claimed. GDPR, no tracking cookies, data stays with user. — [asreview.nl](https://asreview.nl/) **verified**
- Factory: **Yes** screen. **No** discover/PDF/extract/synthesize/cite/write. Runs locally — relevant contrast to hosted factories.

#### Scholarcy — job: structured paper flashcards / literature matrix
- Job: summary cards (claims, methods, findings, refs); collections; literature matrix; export. Not a search engine — user uploads/links. — [Georgetown](https://guides.library.georgetown.edu/ai/tools) **library-guide**; [CASRAI chat-PDF](https://casrai.org/guides/chat-with-pdf-tools-for-researchers) **library-guide**
- Pricing: Free 10 summaries (web also says 1/day on Article Summarizer — **conflict** on free cap); paid “unlimited summarization,” enhanced summaries, export 100 flashcards, literature matrix. Dollar amount for paid plan **not rendered** on official pricing fetch; third party said $10/mo. — [scholarcy.com/pricing](https://www.scholarcy.com/pricing) **verified** incomplete; $10 **secondary**
- Factory: **Yes** extract. **Partial** synthesize (matrix). **No** discover/screen/get PDF from corpus/write/keep current.

#### Explainpaper — job: highlight-to-explain reading
- Job: highlight confusing text/formula/figure → explanation; follow-ups; Zotero import (third party). Free: unlimited highlight explanations; Pro: full-paper summaries + advanced models. Not multi-paper synthesis. — [Lynote 2026](https://lynote.ai/blog/free-scholarcy-alternatives) **secondary**; [Tulane](https://libguides.tulane.edu/AI/tools) **library-guide**
- Factory: **Partial** extract (explain passage). **No** discover/screen/synthesize-across/write.

#### Humata — job: multi-PDF Q&A with passage cites
- Job: query across many documents; cites source passages; encryption at rest claimed. — [CASRAI chat-PDF](https://casrai.org/guides/chat-with-pdf-tools-for-researchers) **library-guide**
- Pricing (CASRAI citing vendor page): Free 60 pages / 10 answers; Expert **$9.99/mo** 500 pages then $0.02/page, 3 users; Team **$49/user/mo** 5,000 pages then $0.01/page, 10 users; Enterprise custom. Training-on-uploads **not explicitly confirmed/denied**. — [CASRAI](https://casrai.org/guides/chat-with-pdf-tools-for-researchers) **secondary**
- Factory: **Yes** extract/synthesize on **user corpus**. **Partial** cite (passages). **No** scholarly discovery/screen/get paywalled PDF.

#### NotebookLM → **Gemini Notebook** (Google, rebrand July 2026)
- Job: source-grounded chat + Studio artifacts (reports, flashcards, quizzes, mind maps, audio/video overviews, data tables, infographics, slide decks). User-supplied sources only. Deleted notebooks not recoverable. Org data not used to train; consumer not trained unless feedback. — [notebooklm.google](https://notebooklm.google/) **verified**
- Limits (Lynote 2026, may predate rebrand): 100 notebooks, 50 sources, 50 chats/day on standard free. — [Lynote](https://lynote.ai/blog/free-scholarcy-alternatives) **secondary**
- Factory: **Yes** synthesize/extract/write-aids **on uploads**. **Partial** cite (inline to sources). **No** literature discovery, screen, paywall PDF, SR audit, Zotero.

#### Valency MCP Bond / Hub — still positioned as literature MCP
- Job: MCP server connecting Claude/ChatGPT/VS Code/etc. to “over 500 million research papers,” index updated daily; 36 endpoints in 8 categories (semantic search, citing papers, filters, etc.). Hub = web reader + submit/publish for **permissively licensed** works only. — [docs.valency.io](https://docs.valency.io/); [endpoints](https://docs.valency.io/reference/endpoints/); [Hub blog](https://blog.valency.io/posts/a-new-home-for-research/) **verified**
- PDF: Hub will not display paywalled papers; Bond can search works that Hub cannot show. — [Hub blog](https://blog.valency.io/posts/a-new-home-for-research/) **verified**
- Factory: **Yes** discover (via agent). **Partial** cite (citation endpoints). **No** screen/extract/SR/write. Hub **Partial** get PDF (OA/permissive only).

#### Infrastructure (not products)
- **OpenAlex** (OurResearch): CC0 MAG successor; Works/Authors/Sources/Institutions/Topics/Publishers/Funders; REST `api.openalex.org`. CASRAI: Feb **2026** hosted API moved to usage-based pricing; ID/DOI lookups remain free; bulk snapshots still free CC0. — [CASRAI OpenAlex API](https://casrai.org/guides/openalex-api) **secondary** (not openalex.org itself this pass)
- **Semantic Scholar Academic Graph API**: papers/authors/citations/venues/SPECTER2; Recommendations service. 214M papers. — [S2 API](https://www.semanticscholar.org/product/api) **verified**
- **CORE**: OA repository harvest (Open University + Jisc); metadata + full text where permitted; free API for TDM. — [core.ac.uk/documentation/api](https://core.ac.uk/documentation/api) **verified**

#### 2025–2026 entrants (skip-if-dead / classify)
- **SciArena**: evaluation arena for literature-grounded LLM answers (ScholarQA retrieval + pairwise researcher votes; 23 models; 13k+ votes). **Not** a lit-review product. — [SciArena paper](https://doi.org/10.52202/085713-3532) **verified**
- **OpenRead**: hosted reader/Q&A/graph; Basic **$20/month** with quotas (Paper Espresso 100, Q&A 300, etc.); credit-priced frontier models; university/enterprise SSO. Alive. — [openread.academy/pricing](https://www.openread.academy/pricing) **verified**
- **Afforai → Logically**: rebrand announced 3 Mar 2025; domain to logically.app; API sunset Apr 2025. Treat Afforai brand as **dead**; Logically is a student/research PDF AI, not an SR platform. — [Reddit cofounder post](https://www.reddit.com/r/LogicallyApp/comments/1jvcgdr/april_2025_new_simplified_plans_file_annotator/) **primary-ish**
- **PapersGPT / ZoteroGPT**: Zotero-native — **out of scope** per assignment. PapersGPT still selling hosted credits ($7/mo, lifetime $149) inside Zotero. — [papersgpt.com/en/pricing](https://www.papersgpt.com/en/pricing) **verified** existence only
- **ChatPDF**: still listed on Tulane libguide as 2 PDFs/day free upload chat; not independently re-verified. — [Tulane](https://libguides.tulane.edu/AI/tools) **library-guide**
- **Google Scholar Labs**: experimental free AI search over Google Scholar; limited users; LibKey. — [UNC](https://guides.lib.unc.edu/genai_for_research_lifecycle/explore) **library-guide**

### Inferences
- The commercial “AI review” layer (Elicit, Consensus, Undermind, SciSpace, Scite) is almost entirely a **Semantic Scholar / OpenAlex / PubMed remix** plus LLM. Differentiation is workflow (SR vs Q&A vs citation context vs deep iterative search), not a unique corpus.
- Independent Cochrane-adjacent work on Elicit is the strongest evidence that **discover+screen automation is not PRISMA-grade** despite Enterprise marketing language: low recall vs traditional search, non-repeatable result sets, extraction that is “partly equal.”
- A Zotero-first local “paper factory” would uniquely own **get PDF + keep library + restore ledger** stages that hosted tools either skip (LibKey-as-link-only) or treat as one-way import.
- Screening tools and synthesis tools remain **two markets**. Elicit is the main hosted attempt to merge them; Covidence/DistillerSR still own audit/compliance.

### Gaps
- SciSpace official pricing page 403; DistillerSR product URL 404; Scholarcy paid dollar amount not in HTML; Connected Papers Academic/Business prices not in fetch; Litmaps exact Education price asterisk.
- ResearchRabbit official current pricing (free vs $12.50) unresolved.
- No 2025–26 peer-reviewed accuracy study found for Consensus, Undermind, Scite Assistant, or SciSpace comparable to Lau & Golder on Elicit.
- Mendeley integrations almost never documented except Covidence import formats.
- Valency Bond pricing/auth commercial terms not fetched.
- OpenAlex Feb 2026 pricing not confirmed on openalex.org itself.

---

## What they never do (paywall fetch, campus proxy, grey literature, restore ledger)

### Takeaway
Hosted tools consistently **link or analyze** full text they already licensed or that is OA; they do not implement a researcher’s campus proxy/ILL as a fetch engine. Grey literature (reports, theses, regulatory docs) is absent except Scite Enterprise safety datasets and Elicit/Consensus clinical-trials add-ons. None offer a Zotero-style **restore ledger** (local immutable provenance of how a PDF/note entered the library). Dual-review audit trails exist in SR software, not in chat-with-PDF tools.

### Cited Findings
- Consensus: LibKey is **link resolving only**; “Consensus doesn’t use full text from LibKey.” Analysis full text can be licensed while the human still cannot download. — [Full-text access](https://docs.consensus.app/get-started/full-text-access) **verified**
- Valency Hub: “hosting only those works with permissive licenses”; paywalled Nobel papers cannot be viewed without institutional licenses. — [Hub blog](https://blog.valency.io/posts/a-new-home-for-research/) **verified**
- Glasgow Library: AI discovery tools “predominantly scrutinise open access journal articles”; ~half of articles OA and skewed Global North / research-intensive — use subject databases for subscription + grey. — [Glasgow AI](https://www.gla.ac.uk/myglasgow/library/ai/) **library-guide**
- Elicit gather: internal 138M + PubMed + ClinicalTrials.gov + uploads — not Web of Science/Embase/CINAHL/grey databases. Sensitivity 39.5% vs traditional multi-database search. — [Elicit sources](https://support.elicit.com/en/articles/14758040-elicit-s-source-for-papers); [Lau & Golder](https://pmc.ncbi.nlm.nih.gov/articles/PMC12483133/) **verified**
- QUT matrix: Undermind, Elicit, Scite, SciSpace, ResearchRabbit — “no direct library integration”; Litmaps and Consensus have LibKey; Google Scholar Labs has LibKey. — [QUT](https://libguides.library.qut.edu.au/library-guidance-for-ai/academic-ai-search-tools) **library-guide**
- Consensus Zotero: import **one-way, manual**; externally linked (not stored) PDFs skipped. — [Library](https://docs.consensus.app/core-features/library) **verified**
- Covidence/Rayyan/ASReview: no discovery corpus — they never search the live literature; they screen what you import. ASReview does not even host the review. — [CASRAI](https://casrai.org/guides/systematic-literature-review-tools); [asreview.nl](https://asreview.nl/) **verified**/guide
- Gemini Notebook: no literature index; “responses… always grounded in the information you provide”; deleted notes have **no recovery**. Opposite of a restore ledger. — [notebooklm.google](https://notebooklm.google/) **verified**
- Scholarcy/Explainpaper/Humata: no scholarly search; Humata training-on-data policy unspecified. — [Georgetown](https://guides.library.georgetown.edu/ai/tools); [CASRAI chat-PDF](https://casrai.org/guides/chat-with-pdf-tools-for-researchers)
- Scite Enterprise adds FAERS/MAUDE/510(k) — rare grey/regulatory exception, not theses/gov reports generally. — [scite.ai/pricing](https://scite.ai/pricing) **verified**
- OpenAlex/CORE/S2 APIs: metadata (CORE also OA full text where permitted); none fetch publisher paywalls. — [CORE API](https://core.ac.uk/documentation/api); [S2 API](https://www.semanticscholar.org/product/api) **verified**

### Inferences
- “Get PDF” in this market means: Unpaywall-class OA, publisher partnership for **model** access, or user upload. A local Zotero-first tool that uses campus proxy, publisher connectors, and records fetch provenance would occupy an empty cell in every matrix row.
- “Restore ledger” (replayable history of imports, screens, extractions, citation decisions) is closest in **DistillerSR/Covidence audit trails**, not in AI search products. Those trails are review-project scoped, not library-object scoped.
- Grey literature remains a systematic-review requirement that AI search products do not claim to meet; ClinicalTrials.gov is the only consistently named non-journal corpus (Elicit, Consensus/Scite datasets).

### Gaps
- No vendor was found advertising EZProxy/OpenAthens **content capture** (as opposed to link-out).
- Unpaywall/LibKey partnership details for Elicit, SciSpace, Undermind not on the pages fetched.
- DistillerSR literature-monitoring sources (Embase vs RSS vs safety DBs) not documented in this pass.

---

## Honest Yes / Partial / No hints for a capability matrix

### Takeaway
Use **Yes** only where the official product is built for that cell. Treat Elicit’s SR workflow as **Partial** for PRISMA-grade screen despite a dedicated UI, because 2025 evaluations show inadequate sensitivity and non-repeatable searches. Graph tools are Yes only on discover (± alerts). Reading tools are Yes only on extract/synthesize of **user PDFs**.

### Cited Findings

Matrix legend: Y = product owns it; P = present with major limits; N = not the job. Factory columns: D discover, S screen, PDF get PDF, E extract, Syn synthesize, C cite/audit, W write, K keep current. Also Zotero/Mendeley.

| Product | D | S | PDF | E | Syn | C | W | K | Zotero | Mendeley | Notes / sources |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Elicit | Y | P | P | P | Y | P | P | P | Y import | N | SR UI **verified**; recall/repeatability fail **PMC12483133**, **BMC**; Zotero on [pricing](https://elicit.com/pricing) |
| Consensus | Y | P | P | P | Y | Y | N | P | Y 1-way | N | [docs full text](https://docs.consensus.app/get-started/full-text-access), [library](https://docs.consensus.app/core-features/library) |
| Scite | Y | N | N | N | P | Y | N | N | N* | N | Smart Citations [pricing](https://scite.ai/pricing); *not on pricing page |
| Semantic Scholar | Y | N | P | P | N | P | N | Y | N | N | TLDRs; [API](https://www.semanticscholar.org/product/api) |
| Undermind | Y | N | P | P | Y | Y | N | Y | N | N | [undermind.ai](https://undermind.ai/); QUT no lib integration |
| SciSpace | Y | P | P | Y | Y | P | Y | N | P export | N | Vendor compare **marketing**; QUT 270M |
| ResearchRabbit | Y | N | N | N | N | P | N | P | P import | N | Pricing **conflict** |
| Litmaps | Y | N | P | N | N | P | N | Y | P 2-way paid? | N | [pricing](https://www.litmaps.com/pricing); Effortless Academic Zotero |
| Connected Papers | Y | N | N | N | N | P | N | N | P | N | [pricing](https://www.connectedpapers.com/pricing) |
| Inciteful | Y | N | N | N | N | P | N | N | N | N | Glasgow: free |
| Covidence | N | Y | P | Y | P | Y | N | N | Y RIS | Y RIS | [covidence.org/pricing](https://www.covidence.org/pricing/) |
| Rayyan | N | Y | P | P | N | P | N | N | P RIS | P RIS | [rayyan.ai/pricing](https://www.rayyan.ai/pricing) |
| DistillerSR | N | Y | P | Y | P | Y | N | P | P | P | CASRAI; official page **gap** |
| ASReview | N | Y | N | N | N | N | N | N | P import files | P | Local OSS [asreview.nl](https://asreview.nl/) |
| Scholarcy | N | N | N | Y | P | P | N | N | P export | P | Upload-only [Georgetown](https://guides.library.georgetown.edu/ai/tools) |
| Explainpaper | N | N | N | P | N | N | N | N | Y? | N | Zotero import **secondary** |
| Humata | N | N | N | Y | Y | P | N | N | N | N | User docs [CASRAI](https://casrai.org/guides/chat-with-pdf-tools-for-researchers) |
| Gemini Notebook | N | N | N | Y | Y | P | P | N | N | N | Rebrand Jul 2026 [notebooklm.google](https://notebooklm.google/) |
| Valency Bond | Y | N | P | N | N | P | N | Y daily index | N | N | [docs.valency.io](https://docs.valency.io/) |
| OpenAlex | Y | N | N | N | N | P | N | Y | N | N | Infra [CASRAI](https://casrai.org/guides/openalex-api) |
| S2 API | Y | N | P | N | N | P | N | Y | N | N | [S2 API](https://www.semanticscholar.org/product/api) |
| CORE | P OA | N | Y OA | N | N | N | N | Y | N | N | [CORE API](https://core.ac.uk/documentation/api) |
| OpenRead | Y | N | P | P | P | P | N | N | N | N | [pricing](https://www.openread.academy/pricing) |
| SciArena | N | N | N | N | P eval | P | N | N | N | N | Eval platform not factory |
| Logically (ex-Afforai) | N | N | N | P | P | P | N | N | N | N | Rebrand 2025 |
| Scholar Labs | Y | N | P | N | P | P | N | N | N | N | Experimental [UNC](https://guides.lib.unc.edu/genai_for_research_lifecycle/explore) |

Pricing cheat-sheet (self-serve, Oct 2026, **verified** unless noted):
- Elicit: $0 / $49 / $229 per user-mo annual industry — [elicit.com/pricing](https://elicit.com/pricing)
- Consensus: $0 / $20/mo or $144/yr / $65/mo or $540/yr — [help.consensus.app](https://help.consensus.app/en/articles/10087865-subscription-plans)
- Scite: $12 Basic; Pro unstated list $ on page (API + 10k collections) — [scite.ai/pricing](https://scite.ai/pricing)
- Undermind: $0 / $16/mo annual / $15 pp Team — [undermind.ai](https://undermind.ai/)
- Connected Papers: 5 graphs free; Academic/Business unlimited — [connectedpapers.com/pricing](https://www.connectedpapers.com/pricing)
- Litmaps: free limited; Education Pro ~$10 (UNC + site asterisk) — **partial**
- SciSpace: ~$20 / $90 / $200 — **marketing** compare page
- Covidence: $339 / $907 / org — [covidence.org/pricing](https://www.covidence.org/pricing/)
- Rayyan: $0; $8.33 or $13.33/mo quarterly official vs $4.99/$8.33 annual third-party — **conflict**
- ASReview: $0 OSS
- OpenRead Basic $20/mo — [openread.academy/pricing](https://www.openread.academy/pricing)
- Semantic Scholar / Inciteful / CORE search: $0
- Gemini Notebook: free + Google paid allowances **secondary**
- DistillerSR / Valency / Scholarcy paid $: **gap**

### Inferences
- For a comparison table vs a local Zotero-first v2 factory, the empty column that matters is **PDF + ledger + grey + proxy**, not “does it chat.” Hosted AI already saturates discover/synthesize/cite.
- Screen+audit is a separate buy (Covidence/Rayyan/DistillerSR/ASReview). Elicit overlapping that buy is the only strategic threat, and 2025 evaluations give a Zotero-first tool a **methods** argument (repeatable, high-recall, human dual review) rather than a features argument.
- MCP is becoming table stakes (Elicit, Consensus, Scite, Valency Bond, Undermind “connect your agents”) — a local tool without MCP will look incomplete to agent users even if PDF/ledger is superior.

### Gaps
- No single official matrix from vendors covering all eight factory stages; cells above mix verified pages with library guides — mark P cells as “re-verify in product” before publishing a customer-facing table.
- Pro Scite dollar price besides $12 Basic not fully parsed (page jumped to Pro features without a number).
- NotebookLM source/chat numeric limits after July 2026 rebrand not on the marketing homepage.
