# Academic writing, manuscript, citation, and “paper factory” authoring tools (as of 2026-10-26)

Research date: 2026-10-26. Scope: the “write” half of an academic-paper factory — turning a literature set into related work, drafts, LaTeX, figures, and submission-ready manuscripts. All facts below are tied to public URLs; vendor marketing is labeled as such.

## Do these tools ground in a personal library or the open web?

### Takeaway
The commercial “write with citations” products are hybrids: they ingest a user’s PDFs/library *and* search large public/index corpora (often 200M–300M articles). Pure local grounding (only YOUR PDFs) is the exception, not the default. Language tools (Writefull, Trinka, Grammarly Academic) mostly edit *your text* and then *stuff extra cites* from the open web or Dimensions, rather than drafting from a closed personal corpus.

### Cited Findings
- Jenni’s homepage states users can “import from Zotero or Mendeley, or let Jenni search 200M+ papers”; autocomplete “suggests sentences grounded in real papers” and claims can be traced to a PDF page/paragraph. — [Jenni](https://jenni.ai/)
- Jenni Library docs: uploaded PDFs support citation, chat, and synthesis; DOI/PMID imports try to fetch full PDFs; “Sources without an attached PDF can still be cited, but they are not available for AI Chat or autocomplete until a PDF is attached.” Citation search has Library vs Discover/web tabs. — [Jenni Library](https://docs.jenni.ai/docs/research/library/); [Jenni citation management](https://docs.jenni.ai/docs/research/citation-management/)
- Paperpal homepage: “Upload your references and PDFs, ask questions, and get cited findings from 300M+ verified research articles” and “Draft with suggestions grounded in your sources.” — [Paperpal](https://paperpal.com/)
- SciSpace AI Writer: “adds citations from 280M+ papers”; Cite button tabs include Suggestions, Created by Me, My Library, and high-impact papers. — [SciSpace AI Writer](https://scispace.com/ai-writer); [SciSpace Cite button](https://scispace.com/help/en/articles/10905014-how-to-use-the-cite-button-in-ai-writer)
- SciSpace vs Paperpal comparison (SciSpace’s own page, 2026): Paperpal ~250M+ articles, SciSpace ~280M+; SciSpace emphasizes multi-database search (Google Scholar, PubMed, arXiv, OpenAlex, Semantic Scholar). Treat counts as vendor claims. — [SciSpace vs Paperpal](https://scispace.com/compare/paperpal)
- Overleaf AI citation reviewer: “Scan for unsupported statements” then “relevant papers sourced from Dimensions”; adding a paper inserts citation + bibliography automatically. Typed citation-review chats “will use an LLM” and “are not verified against an authoritative source.” — [Overleaf AI assistant](https://docs.overleaf.com/integrations-and-add-ons/ai-features/ai-assistant)
- Overleaf AI features send project content to OpenAI; citation suggestions use “citation data via Dimensions.” — [Overleaf AI features](https://docs.overleaf.com/integrations-and-add-ons/ai-features)
- Grammarly Citation Finder “identif[ies] publicly available sources that support, conflict with, or contradict” claims; it “won’t change your wording”; free users insert up to five citations/day. Auto-citations work from a whitelist of publisher sites (Nature, ScienceDirect, arXiv, PMC, etc.). — [Citation Finder](https://www.grammarly.com/ai-agents/citation-finder); [Grammarly citations support](https://support.grammarly.com/hc/en-us/articles/9182359307917-How-to-generate-citations-and-a-bibliography)
- EndNote Cite While You Write searches *the user’s EndNote library* (author/year/keyword) and formats from an output style; it does not generate new literature from the open web as part of CWYW. — [EndNote CWYW Word](https://docs.endnote.com/docs/endnote/2025/macos/v1/content/09word/basic_instructions_word.htm)
- Paperpile is a personal library + Google Docs/LaTeX cite-while-you-write layer: “Search your references online while you are writing”; 7000+ styles; export RIS/BibTeX; EndNote-compatible Word export. — [Paperpile Workspace listing](https://workspace.google.com/marketplace/app/paperpile/894076725911)
- Better BibTeX + Quarto/Pandoc is strictly personal-library: Zotero collection auto-exports `.bib`; Quarto YAML `bibliography:` + optional `csl:`; cite with `[@key]`. — [BBT auto-export](https://retorque.re/zotero-better-bibtex/exporting/auto/index.html); [Quarto citations](https://quarto.org/docs/authoring/citations.html)
- AutoSurvey grounds retrieval in “a corpus of 530,000 computer science papers from arXiv,” not a user library; outline uses abstracts; subsection drafting uses up to the first 1,500 tokens of each paper body. — [AutoSurvey arXiv HTML](https://arxiv.org/html/2406.10252v2)
- STORM grounds on “trusted Internet sources” to write Wikipedia-like articles, not a personal PDF library. — [STORM project](https://storm-project.stanford.edu/research/storm/); [NAACL 2024](https://doi.org/10.18653/v1/2024.naacl-long.347)
- Citegeist (arXiv 2503.23229) RAG over ~2.6M arXiv papers to generate related-work sections; full-text corpus >1 TB so it filters on abstracts then retrieves full documents. — [Citegeist](https://doi.org/10.48550/arxiv.2503.23229)

### Inferences
- “Grounded in your sources” in marketing almost always means *union of your PDFs + a global index*. A local factory that must not leak unpublished work or invent extra cites needs an explicit *library-only* mode; few products default to that (Jenni’s “Auto-cite from Library” / “Library search” is the closest documented control).
- Cite-while-you-write managers (EndNote, Paperpile, BBT/Quarto) ground *citations* in the personal library but do **not** generate related-work prose. AI writers do the reverse: they generate prose then attach index-backed cites.
- Survey/related-work generators (STORM, AutoSurvey, Citegeist) are open-web/arXiv RAG systems. They are the opposite of “related work from YOUR PDFs.”

### Gaps
- Independent measurement of how often Jenni/Paperpal/SciSpace suggestions actually come from uploaded PDFs vs the global index was not found.
- Paperpal Citation Library help (dated 9 Apr 2024) said import of personal references was *planned*; whether 2026 product pages’ “upload your references” fully replaced that gap was not independently verified beyond homepage copy. — [Paperpal Citation library FAQ](https://support.paperpal.com/support/solutions/articles/3000125798-how-does-the-citation-library-feature-under-research-work-)
- No public API docs were found that expose “cite only from this Zotero collection” as a machine-checkable constraint for a local factory.

## Citation hallucination risk and advertised mitigations

### Takeaway
Unconstrained LLMs still fabricate references at high rates in 2025 studies. Vendor mitigations cluster into (1) attach cites only to indexed records, (2) post-hoc Crossref/DOI/retraction checkers, (3) “scan for missing citations then suggest real papers,” and (4) human “always verify.” None of the products claim they prove the cited paper *supports the attached claim* at the span level. Academic systems (AutoSurvey, STORM, CTS-based generation) still report non-trivial unsupported claims.

### Cited Findings
- Librarianship study: ChatGPT-3.5 produced 42.9% false/non-existent citations; ChatGPT-4o 51.8%; accuracy 3.92% vs 6.35% — “no significant difference” between versions. — [Hallucitation, Taylor & Francis 2025](https://www.tandfonline.com/doi/full/10.1080/19322909.2025.2482093?src=exp-la)
- Archaeology/reference-veracity study (Publications 2025): ChatGPT-3.5 had a large share of fictitious refs; ScholarGPT (academic-tuned) still “offered a high rate of fictitious references”; genuine OpenAI/DeepSeek refs that checked out were also cited on Wikipedia, suggesting third-hand sourcing; cloze tests failed to show models had read the cited full texts. — [MDPI Publications](https://www.mdpi.com/2304-6775/13/1/12)
- Jenni advertised mitigation: “Jenni attaches citations to identifiable sources and shows the source details so you can verify them… Always review a source before relying on it.” PDF upload used for autocomplete/chat. Page/paragraph traceability claimed on homepage. — [Jenni citation docs](https://docs.jenni.ai/docs/research/citation-management/); [Jenni](https://jenni.ai/)
- Paperpal Reference Checker (help, modified 26 Jun — year not stated in snippet, product live on 2026 homepage): flags broken URLs, URL–metadata mismatches, unverifiable refs, predatory/fake journals, unrelated refs; verifies against “250M+ verified research articles”; 9 in-depth checks; DOCX/PDF ≤25 MB. Paperpal blog also claims a study of 100 hallucinated citations in NeurIPS 2025 accepted papers (two-thirds total fabrications) — **this is vendor-cited, not independently located in this pass**. — [Hallucinated refs FAQ](https://support.paperpal.com/support/solutions/articles/3000137234-does-paperpal-s-reference-checker-detect-ai-hallucinated-references-); [How Reference Checker works](https://support.paperpal.com/support/solutions/articles/3000137228-how-does-paperpal-s-reference-checker-work-); [Paperpal blog](https://paperpal.com/blog/news-updates/reference-checker-verify-citations-before-you-submit)
- Trinka Citation Checker: Crossref validation; flags retracted, hallucinated/unverified, predatory, duplicates, old refs, journal overuse; “does not automatically correct”; paywalled articles can be quality-checked; Cloud-only as of product page. — [Trinka citation checker](https://www.trinka.ai/features/citation-checker); independent 2026-06-22 comparison: ReciteWorks checks in-text/list consistency only; Trinka checks Crossref quality, not in-text coupling. — [Literate Computing](https://www.literatecomputing.com/blog/2026-06-22-citation-checkers-compared/)
- Writefull Cite (institutions only): flags sentences that present non-general knowledge without a citation; does **not** insert suggested papers on that product page. — [Writefull Cite](https://www.writefull.com/writefull-cite)
- Overleaf: Dimensions-backed scan vs unverified LLM chat (see previous section). Check-citations from AI action menu. — [Overleaf AI features](https://docs.overleaf.com/integrations-and-add-ons/ai-features)
- Grammarly Citation Finder: “recommends trusted sources” but Grammarly support does not claim NLI-style claim–span entailment; a 2026 review (ManuSights, commercial) argues suggestions still need scientific scrutiny. — [Citation Finder](https://www.grammarly.com/ai-agents/citation-finder); [ManuSights review](https://manusights.com/blog/is-grammarly-good-for-academic-writing)
- Elsevier author policy (official): authors must “carefully review… (including checking the sources, as AI-generated references can be incorrect or fabricated).” June 2026 factsheet: “Find and read each source yourself… Never cite a reference you have not read.” — [Elsevier genAI journal policies](https://www.elsevier.com/about/policies-and-standards/generative-ai-policies-for-journals); [Elsevier factsheet PDF](https://researcheracademy.elsevier.com/uploads/2026-06/genai_factsheet_authors_v1_updated-1.pdf)
- AutoSurvey (NeurIPS 2024): at 64k tokens, citation recall 82.25% and precision 77.41% vs human 86.33% / 77.78%, using an NLI model over extracted claims vs cited papers; ablation: removing retrieval “significantly degrades citation quality.” Corpus = arXiv CS; first 1,500 tokens of body only. — [AutoSurvey](https://arxiv.org/html/2406.10252v2); [NeurIPS PDF](https://proceedings.neurips.cc/paper_files/paper/2024/file/d07a9fc7da2e2ec0574c38d5f504d105-Paper-Conference.pdf)
- STORM editors flagged “source bias transfer and over-association of unrelated facts.” — [NAACL 2024 abstract](https://doi.org/10.18653/v1/2024.naacl-long.347)
- Li et al.: abstract-conditioned citation generation “learn[s] to hallucinate”; cited text spans (CTS) from full text are more faithful. — [Cited Text Spans](https://arxiv.org/html/2309.06365v1)
- Li & Ouyang survey (2024): most RWG systems assume gold citation lists; RAG-for-related-work is still an open problem; humans want missing-citation alerts, not only drafting. — [RWG survey](https://arxiv.org/html/2404.11588v1)

### Inferences
- Advertised mitigations mostly prevent *bibliographic ghosts* (non-existent venues/DOIs), not *semantic ghosts* (real paper, wrong claim). Claim–citation coupling remains a factory requirement, not a shipped product guarantee.
- Post-hoc checkers (Paperpal, Trinka, ReciteWorks, Overleaf Dimensions scan) are complementary: existence/retraction vs in-text/list consistency vs “this sentence needs a cite.”
- AutoSurvey’s ~77% citation precision at 64k tokens is close to their human baseline on the same NLI metric — meaning even “good” automatic surveys leave ~1 in 4 citations weakly supporting the claim under their evaluator. That is not submission-safe.

### Gaps
- No independent audit of Jenni “page and paragraph” linking accuracy was found.
- Paperpal’s NeurIPS 2025 hallucinated-citation study was not retrieved as a primary paper in this pass.
- Writefull’s GPT Detector / Paperpal AI Detection / Trinka AI detection: advertised, but no independent accuracy numbers for *academic* text were collected here.
- Hedwigai MCP claims Crossref+doi.org lookup plus “every sentence that cites one is read against it”; this is a vendor page, not a peer-reviewed eval. — [hedwigai Overleaf MCP](https://www.hedwigai.com/overleaf-mcp)

## Integration with Zotero

### Takeaway
Zotero is the interoperability hub for the *library* half (import into Jenni/SciSpace; Better BibTeX living `.bib` for Quarto/LaTeX). It is **not** a bidirectional sync into most AI writers. EndNote/Paperpile compete as CWYW hosts rather than Zotero plugins. Overleaf/Writefull have no first-party Zotero cite plugin in the pages reviewed.

### Cited Findings
- Jenni: Import from Zotero via Settings > Connections or Library upload; personal + readable group libraries; **one-way**; re-import to pick up new sources; PDFs included per marketing page; contributor roles preserved from Zotero/BibTeX/RIS. Styles search the **Zotero CSL Style Repository** (10,000+). — [Jenni citations](https://docs.jenni.ai/docs/research/citation-management/); [Jenni Zotero/Mendeley](https://jenni.ai/zotero-mendeley)
- SciSpace: “Import from Zotero” on My Library; papers without DOI skipped; unmatched DOIs skipped; only uploaded PDFs reliably imported. Separate Typeset-era path: EndNote XML upload or paste BibTeX; table lists Zotero as “Upload Endnote XML.” — [SciSpace Zotero](https://scispace.com/help/en/articles/10719251-how-to-connect-scispace-with-zotero); [SciSpace reference managers](https://scispace.com/t/features/reference-citation/)
- Better BibTeX: collection/library export with “Keep updated”; on-change / on-idle / paused; recommend per-paper collections for performance. — [BBT auto-export](https://retorque.re/zotero-better-bibtex/exporting/auto/index.html)
- Quarto: `.bib` / BibLaTeX / CSL-JSON; `cite-method: biblatex` or `natbib` for PDF; default citeproc + CSL (Chicago author-date if no CSL). Utrecht open-textbook recipe: Zotero collection → BBT Keep updated → `references.bib` beside Quarto project. — [Quarto citations](https://quarto.org/docs/authoring/citations.html); [UU textbooks](https://utrechtuniversity.github.io/open-textbooks/citation.html)
- EndNote CWYW: Word desktop (Word 2010–2021 / M365 local), Word Online (EndNote 21/2025 web account), Google Docs, OpenOffice/LibreOffice (Windows). Instant Formatting updates bibliography as you insert. This is EndNote-library, not Zotero. — [EndNote overview](https://docs.endnote.com/docs/endnote/2025/v1/windows/en/content/01intro/overview.htm); [Word Online CWYW](https://support.clarivate.com/Endnote/s/article/EndNote-Word-Online-CWYW?language=en_US)
- EndNote users (Sep 2025 community thread) report BibTeX export to Quarto is “clunky” (escaping); contrast with Zotero. — [EndNote community](https://community.endnote.com/t/integration-with-rmarkdown-and-quarto/713433)
- Paperpile: Google Docs add-on; BibTeX/RIS export; SciSpace lists Paperpile as “Convert RIS to Endnote XML and Upload.” No first-party Zotero sync found on Paperpile homepage. — [Paperpile](https://paperpile.com); [Workspace listing](https://workspace.google.com/marketplace/app/paperpile/894076725911)
- Paperpal 2024 FAQ: Citation Library could save refs from AI responses; personal import “planned.” 2026 homepage says upload references/PDFs. No Zotero OAuth page was found in this pass. — [Paperpal FAQ](https://support.paperpal.com/support/solutions/articles/3000125798-how-does-the-citation-library-feature-under-research-work-); [Paperpal](https://paperpal.com/)
- Grammarly: APA/MLA/Chicago generators and Citation Finder; no Zotero integration on support pages reviewed.

### Inferences
- For a local factory, the durable Zotero path is **BBT auto-export → BibLaTeX/CSL**, not cloud AI OAuth. Cloud imports are snapshots.
- Jenni uniquely treats Zotero CSL as the style engine for 10k+ journal styles — useful if the factory must match arbitrary venues without maintaining a CSL tree itself.
- SciSpace’s DOI-required Zotero import will drop grey literature, theses, and unmatched records — a systematic hole for related-work from *your* library.

### Gaps
- Live confirmation of Paperpal 2026 Zotero support was not found (homepage is generic “upload”).
- Writefull/Overleaf/Trinka Zotero plugins: not found on product pages reviewed.
- Bidirectional sync (cite in Overleaf → write back to Zotero) remains a local/BBT problem, not a SaaS feature.

## What remains human (argument, novelty, ethics)?

### Takeaway
Publishers in 2025–2026 allow AI for language, organization, literature overview, and some explanatory figures, but they assign **authorship, novelty argument, claim verification, image integrity, and confidentiality** exclusively to humans. AI cannot be an author. Generative artwork and primary-data images are largely banned. “Stuff extra cites” after drafting is treated as a known integrity failure mode, not a feature.

### Cited Findings
- Elsevier (official journal policy): AI may synthesize literature, spot gaps, generate ideas, organize content, improve language; **must never substitute for human critical thinking**; authors accountable for accuracy, authenticity of analysis/ideas, disclosure, and IP/privacy of tools. AI not an author. Basic grammar/spelling/punctuation: no declaration; “substantive changes to sentence structure or organization” **must** be disclosed. Suggested declaration names tool + reason + human review. — [Elsevier genAI policies](https://www.elsevier.com/about/policies-and-standards/generative-ai-policies-for-journals)
- Elsevier June 2026 author factsheet: CAN use AI to summarize literature, structure, language, explanatory images, data viz from own data; must NOT “Write substantive parts of the paper without your own intellectual contribution,” fabricate refs, alter primary images, or use general-purpose AI for graphical abstracts (use BioRender-class tools). Checklist: “AI only as support, it did not write substantive content for me.” — [Factsheet PDF](https://researcheracademy.elsevier.com/uploads/2026-06/genai_factsheet_authors_v1_updated-1.pdf)
- Elsevier figures: explanatory images allowed with caption+declaration; data viz only if derived from own data via reproducible methods (Methods + caption); primary research images (microscopy, blots) forbidden to create/alter with AI; graphical abstracts: no general-purpose genAI. Reviewers/editors must not upload manuscripts to non-private AI. — same Elsevier policy URL
- Springer Nature: LLMs do not meet authorship criteria; LLM use documented in Methods (or alternative); **“AI assisted copy editing” need not be declared** (readability/grammar/tone, not “generative editorial work and autonomous content creation”); human accountability for final text. Generative AI images/videos generally not permitted while legal issues unresolved. — [npj Power Electronics AI policy](https://www.nature.com/npjpowerelect/for-authors-and-referees/about/editorial-policies/ai) (search hit; fetch 404’d in this pass — also compiled in [STM policy supplement](https://media.springernature.com/original/springer-static/esm/art%3A10.1186%2Fs41073-025-00158-y/MediaObjects/41073_2025_158_MOESM1_ESM.pdf))
- Nature Methods (published 11 Feb 2026): Nature Portfolio allows genAI to “help write sections… or edit… for readability” with Methods declaration; AI cannot be an author; **no AI-generated artwork** including covers; reviewers must not upload manuscripts to genAI. — [Nature Methods](https://www.nature.com/articles/s41592-026-03020-1)
- Nature Ecology & Evolution (2025): declare genAI in cover letter (manuscript declaration optional); **“we do not permit the use of AI for content generation”** beyond copyediting in that journal’s spotlight — **stricter than the general SN copyedit exception**; no AI figures/covers. — [Nat Ecol Evol](https://www.nature.com/articles/s41559-025-02907-0)
- Integrity incidents: Springer Nature retracted *Mastering Machine Learning* after 25/46 references unverifiable (Aug 2025). — [Retraction Watch](https://retractionwatch.com/2025/08/04/springer-nature-retracts-book-fake-citations-help-us-find-more/)
- HKU probe: *China Population and Development Studies* paper with ≥20/61 non-existent refs (published 17 Oct 2025; SCMP 10 Nov 2025); journal said core conclusions still valid. — [SCMP](https://www.scmp.com/news/hong-kong/education/article/3332120/non-existent-ai-generated-references-paper-spark-university-hong-kong-probe)
- Paper rejected for AI + fake refs (including a fake paper attributed to the reviewer) later published almost unchanged in *World of Media*; taken offline pending inquiry (Retraction Watch 12 Jun 2025). — [Retraction Watch](https://retractionwatch.com/2025/06/12/paper-rejected-for-ai-fake-references-published-elsewhere-with-hardly-anything-changed/)
- RWG survey: related-work is specifically the **novelty argument** (“compose a coherent story that connects… prior works to the current work”), not concatenated summaries. — [Li & Ouyang](https://arxiv.org/html/2404.11588v1)
- STORM: Wikipedia-like breadth/organization gains vs RAG baseline (+25% organized, +10% broad coverage) but experts still see bias transfer and over-association. — [STORM](https://storm-project.stanford.edu/research/storm/)

### Inferences
- A factory that auto-drafts Related Work + Methods + extra cites is **content generation**, which Elsevier’s 2026 factsheet and some Nature journals treat as non-compliant unless the human rewrites for original intellectual contribution and declares the tool.
- Language-only path (Writefull/Trinka/Paperpal grammar, SN “copy editing”) is the policy-safe automation layer; claim synthesis is not.
- Ethics leftover that cannot be automated: deciding what is novel, reading sources, dual-reviewer screening for systematic reviews, not uploading confidential reviews, not generating fake blots/microscopy, disclosing AI, and refusing to cite unread papers.

### Gaps
- Journal-level heterogeneity is large (Nat Ecol Evol vs generic SN vs Elsevier). A factory would need a policy table per target venue; this pass sampled Elsevier, SN/Nature Portfolio, not IEEE/ACM/ICMJE in full.
- No 2026 ICMJE update was fetched in this pass.

## Drafting and language products (Jenni, Paperpal, Writefull, SciSpace/Typeset, Overleaf AI, Trinka, Grammarly)

### Takeaway
These tools occupy a spectrum from **source-grounded drafting** (Jenni, SciSpace Writer, Paperpal) through **LaTeX-aware language+codegen** (Writefull-in-Overleaf / Overleaf AI) to **integrity/language checkers** (Trinka, Paperpal checkers, Grammarly Academic). None is a full submission pipeline by itself; several now sell “search → draft → check” workspaces.

### Cited Findings
- **Jenni**: editor + autocomplete + chat + editing + library + reviews (proofreading, claim confidence, source quality, tone, peer-review checks) + collab; Workflows “turn a topic and selected sources into a new document”; export DOCX/LaTeX/HTML; 6 million academics claimed; Oct 2026 changelog: code execution in chat (21 Oct 2026), figure/table cross-refs (7 Oct 2026), viewer/commenter roles (23 Sep 2026), charts from AI Chat (9 Sep 2026). — [Jenni intro](https://docs.jenni.ai/docs/getting-started/introduction/); [Jenni](https://jenni.ai/)
- **Paperpal** (Cactus; “24+ years of scholarly publishing”; “1,500+ leading journals”; “1M+ papers checked”): Word, Google Docs, Overleaf, web; plagiarism, AI detection, reference check, grammar; journal submission-readiness. Paperpal help: SciSpace is “primarily a literature search tool”; Paperpal is “first and foremost an advanced academic writing tool.” Files “never used to train AI”; ISO/IEC 42001:2023 claimed. — [Paperpal](https://paperpal.com/); [Paperpal vs SciSpace FAQ](https://support.paperpal.com/support/solutions/articles/3000130091-how-is-paperpal-s-chat-pdf-different-from-other-tools-like-scispace-what-ai-models-do-you-use-)
- **Writefull**: models “trained on millions of journal articles”; Word + Overleaf; Academizer, title/abstract generators, paraphraser, Sentence Palette by IMRaD section, GPT Detector (vendor claim). Overleaf: language on LaTeX source, TeXGPT, table/equation generators from prompt or image, rewrite widgets. Data: “never store your text” / not used for training; some features use third-party APIs with consent. Institutional licenses after Sep 2024 include TeXGPT + generators. Writefull toolbar in Overleaf **removed**; tools moved into Overleaf AI menus. — [Writefull](https://www.writefull.com/); [Writefull for Overleaf](https://www.writefull.com/writefull-for-overleaf); [Writefull institutions](https://www.writefull.com/writefull-at-your-institution); [Overleaf AI features](https://docs.overleaf.com/integrations-and-add-ons/ai-features)
- **Overleaf AI Assist**: AI assistant (Student/Standard/Pro, not Free/Commons); Error Assist; Writefull language suggestions; rewrite; generate title/abstract; TeXGPT; citation check. Project content sent to OpenAI; “data is never used to train AI models.” Org admins can disable AI. — [AI assistant](https://docs.overleaf.com/integrations-and-add-ons/ai-features/ai-assistant); [AI features](https://docs.overleaf.com/integrations-and-add-ons/ai-features)
- **SciSpace (formerly Typeset) AI Writer**: autocomplete, edits, citations from 280M+; bibliography auto; 1,000+ styles (SciSpace compare page) vs 10,000+ for Paperpal; Typeset-era manuscript formatter still documents 50,000+ journal formats and cite-from-uploaded XML. — [AI Writer](https://scispace.com/ai-writer); [Cite button](https://scispace.com/help/en/articles/10905014-how-to-use-the-cite-button-in-ai-writer); [Typeset citation](https://scispace.com/t/features/reference-citation/)
- **Trinka**: academic grammar + AI write/rewrite/translate + citation checker/formatter + plagiarism (190M+ paid, 200M+ OA, 99B webpages claimed) + AI content detection + 25+ submission checkpoints + journal finder + Enago human editing certificate. Privacy-first / zero training claims on citation-checker page. — [Trinka features](https://www.trinka.ai/features)
- **Grammarly Academic**: domain=Academic + APA/MLA/Chicago format checks; Citation Finder agent; research-paper marketing page. Not a scholarly index; not LaTeX-native. — [Grammarly research paper](https://www.grammarly.com/research-paper); [citations support](https://support.grammarly.com/hc/en-us/articles/9182359307917-How-to-generate-citations-and-a-bibliography)

### Inferences
- Closest commercial “paper factory write module”: Jenni (library-grounded draft + LaTeX export + claim reviews) or Paperpal (publisher-flavored edit + Overleaf + hallucination checker). SciSpace is stronger on discovery→draft. Writefull/Overleaf is stronger on LaTeX mechanics than on literature synthesis.
- Grammarly is a student/general academic layer; using it as the citation brain of a research factory would mix web sources into a scholarly bibliography.

### Gaps
- Pricing, rate limits, and PDF paywall compliance for Jenni PDF auto-fetch were not collected.
- Typeset.io brand vs SciSpace product split in 2026: compare pages treat SciSpace as the writer; old Typeset journal-format engine may still exist but was not fully mapped.

## Citation managers and living reviews (Paperpile, EndNote CWYW, Better BibTeX + Quarto/Pandoc)

### Takeaway
These are the **non-hallucinating** citation path: keys come from a human-curated library. They do not draft related work. BBT+Quarto is the living-review architecture (collection grows → `.bib` updates → citeproc/BibLaTeX rebuilds). EndNote/Paperpile win on Word/Google Docs collaboration.

### Cited Findings
- EndNote 2025 CWYW inserts from *your* library, Instant Formatting on by default, style switcher, exclude author/year, bibliography-only cites; Word Online add-in pools collaborators’ refs (EndNote 21/2025 web). Research Assistant is a new AI feature mentioned in EndNote 2025 overview (not evaluated here). — [CWYW instructions](https://docs.endnote.com/docs/endnote/2025/macos/v1/content/09word/basic_instructions_word.htm); [overview](https://docs.endnote.com/docs/endnote/2025/v1/windows/en/content/01intro/overview.htm)
- Paperpile: Google Docs CWYW, 7000+ styles, PubMed/DOI lookup, collaborative Docs, LaTeX export, RIS/BibTeX. Privacy: citation metadata only. — [Workspace listing](https://workspace.google.com/marketplace/app/paperpile/894076725911)
- Pandoc/Quarto citeproc: `[@key]`, locators, CSL from Zotero style repo; PDF can use BibLaTeX. — [Quarto](https://quarto.org/docs/authoring/citations.html)
- BBT: stable keys, Better BibLaTeX export, auto-export, journal abbreviations, pull export via embedded webserver. — [BBT](http://retorque.re/zotero-better-bibtex/index.html)

### Inferences
- Living reviews want: Zotero collection per review + BBT Keep updated + Quarto/Pandoc + CSL, not an AI writer’s one-way import.
- “Draft then stuff extra cites” fights this architecture: extra cites must enter Zotero (with PDFs) *before* they are citeable, or the living `.bib` and the prose diverge.

### Gaps
- EndNote Research Assistant capabilities vs hallucination were not documented in the CWYW pages fetched.
- Paperpile native Overleaf plugin: not confirmed (LaTeX export only).

## LaTeX agents and Cursor/Copilot as paper writers

### Takeaway
There is **no** first-party Cursor or GitHub Copilot “academic paper workflow product.” What exists: Overleaf’s own AI (Writefull-derived), research/browser extensions (OverleafCopilot), community Overleaf MCP servers, and IDE templates that point Copilot at a `.tex` repo. Treat these as general coding agents on LaTeX, not grounded scholarly writers, unless a server adds Crossref checks (vendor-claimed).

### Cited Findings
- OverleafCopilot (arXiv 2403.09733, KDD 2024 technical report): Chrome extension bridging Overleaf and LLM APIs; PromptGenius; “agent command system”; Chrome Web Store ID in paper. Privacy/communication called out as design challenges. — [arXiv](https://arxiv.org/abs/2403.09733)
- `mcp-server-overleaf`: MCP for Cursor/Claude/Codex; local clone edits until explicit publish; conflict stop on overlapping collaborator edits; optional session cookie for tracked-change suggestions. — [GitHub](https://github.com/yangzichao/mcp-server-overleaf)
- `@aloth/olcli-mcp`: list/pull/push/compile/comments/tracked changes; Cursor `mcp.json` + `OVERLEAF_SESSION`. — [olcli MCP.md](https://github.com/aloth/olcli/blob/main/docs/MCP.md)
- Hedwigai: claims Overleaf has no official MCP; community servers don’t verify refs; theirs lookup Crossref/doi.org and “read” citing sentences; Tectonic compile; no biber/LuaLaTeX. Vendor page. — [hedwigai](https://www.hedwigai.com/overleaf-mcp)
- LaTeX-dev-copilot GitHub: VS Code/Cursor + Copilot + containerized TeX + live preview; marketing vs Overleaf, not a scholarly RAG pipeline. — [GitHub](https://github.com/0-mostafa-rezaee-0/LaTeX-dev-copilot)
- Overleaf native TeXGPT/Error Assist/table-equation generators: documented product, not Cursor. — [Writefull for Overleaf](https://www.writefull.com/writefull-for-overleaf)

### Inferences
- Using Cursor on a git-backed paper is a **coding** workflow: it sees `.bib` and `.tex` if they’re in the repo, but will invent cites unless constrained to existing keys (hedwigai-style checks are the exception, un-audited).
- Policy risk: sending unpublished manuscripts to OpenAI via Overleaf AI or to Copilot/Cursor cloud is exactly the confidentiality issue Elsevier/Nature flag for *reviewers*; authors must read tool ToS (Elsevier policy).

### Gaps
- No Cursor Inc. documentation of an academic-paper product was found.
- GitHub Copilot “paper” templates beyond community READMEs were not found as official products.

## STORM, related-work generators, automatic survey generators

### Takeaway
Research systems can draft long, cited surveys/wiki articles from open corpora, with hierarchical outline→section pipelines. They optimize coverage/speed, not venue-ready novelty arguments, and they retrieve from arXiv/web—not the user’s PDF set. Related-work generation (RWG) literature says the hard part is *positioning the current paper*, which AutoSurvey does not even take as input.

### Cited Findings
- **STORM** (Shao et al., NAACL 2024): Synthesis of Topic Outlines through Retrieval and Multi-perspective Question Asking; pre-writing: perspectives, simulated expert interviews grounded on internet sources, outline, then article; FreshWiki eval; +25% organized, +10% coverage vs outline-driven RAG; expert issues: source bias, over-association. — [project](https://storm-project.stanford.edu/research/storm/); [ACL Anthology](https://doi.org/10.18653/v1/2024.naacl-long.347)
- **AutoSurvey** (Wang et al., NeurIPS 2024): retrieval+outline (abstracts, 1200 papers, 8 sections), parallel subsection drafting (60 papers/section, first 1500 tokens), refine (including “check the correctness of the cited references”), multi-LLM-as-judge, N=2 iterations; writer Claude-3-Haiku; ~$1.2 and ~3 minutes per example survey in intro figure caption; 64k-token speed 73.59 surveys/hour vs human 0.07; citation recall/precision 82.25/77.41 vs human 86.33/77.78; content quality near human on LLM judges; Spearman mix-of-judges vs humans 0.5429 (moderate). GitHub resources claimed. — [arXiv HTML](https://arxiv.org/html/2406.10252v2); [NeurIPS](https://papers.nips.cc/paper_files/paper/2024/hash/d07a9fc7da2e2ec0574c38d5f504d105-Abstract-Conference.html)
- **UR³WG** (Findings EMNLP 2023): unified retrieve+generate related work from LLM-expanded queries; most prior RWG used gold refs. — [ACL](https://aclanthology.org/2023.findings-emnlp.385.pdf)
- **Citegeist** (arXiv 2503.23229): related-work RAG on arXiv; breadth/depth/diversity hyperparameters; website + harness. Distinct from citegeist.io systematic-review SaaS. — [arXiv](https://doi.org/10.48550/arxiv.2503.23229)
- **RWG survey** (Li & Ouyang, arXiv 2404.11588): RWS must argue novelty relative to *this* paper; RAG-RWG is future work; missing-citation questions on review forms. — [survey](https://arxiv.org/html/2404.11588v1)
- **Cited Text Spans** (Li et al.): full-text span grounding beats abstracts for citation sentences. — [CTS](https://arxiv.org/html/2309.06365v1)

### Inferences
- AutoSurvey is a **survey mill**, not a paper mill: no methods/results of a new experiment, no claim of originality, CS-arXiv-only, truncated bodies. Dangerous if dropped into a contribution paper’s Related Work without human positioning.
- STORM is a **topic explainer**, not a manuscript. Useful as an outline prior, not as submission text.
- A local factory analogue would run AutoSurvey-like outline/draft **against the user’s PDF store** with CTS-level NLI, then require a human novelty paragraph.

### Gaps
- Post-2024 follow-ons (SurveyX, etc.) were not systematically searched.
- AutoSurvey citation metric uses NLI on whatever text was retrieved (often truncated); may overstate faithfulness to full papers.

## Figures, tables, and PRISMA diagram tools

### Takeaway
LaTeX table/equation codegen is mature inside Overleaf/Writefull. “Figures from papers” is mostly **flowchart/architecture illustration from prompts**, which collides with Nature/Elsevier bans on generative artwork and primary-image AI. PRISMA should be **count-driven templates** (official PRISMA Word + Shiny), not AI-illustrated diagrams, if the figure is for a methods section.

### Cited Findings
- Official PRISMA 2020: four Word templates (new vs update × databases-only vs databases+other sources); “Flow diagrams can also be generated using a Shiny App” at eshackathon.org; CC BY 4.0. — [PRISMA statement](https://www.prisma-statement.org/prisma-2020-flow-diagram); [PRISMA2020 Shiny](https://eshackathon.org/projects/prisma2020/)
- ConceptViz: precise count mode (recommended for submission) vs “AI illustration mode” for talks. — [ConceptViz](https://conceptviz.app/tools/prisma-flow-diagram-generator)
- CoChat / CiteGeist.io: auto-fill identification counts from searches; human screening; export SVG/PNG/PDF; 27-item checklist; CiteGeist.io maps exclusion tags → flow boxes + CSV extraction table; imports `.bib`/`.nbib`/PDF. These are product pages. — [CoChat PRISMA](https://cochat.ai/prisma-charts/); [CiteGeist litreview](https://citegeist.io/litreview/)
- SciFig.ai: prompt/sketch/PDF/CSV → illustration, DataChart, FlowChart; PRISMA/CONSORT from pasted counts; export SVG/PNG/JPG/PPTX. — [SciFig](https://scifig.ai/)
- Writefull/Overleaf: table and equation generators from prompt or image → LaTeX. Jenni (Sep–Oct 2026): AI Chat charts + auto figure/table cross-refs. — [Writefull for Overleaf](https://www.writefull.com/writefull-for-overleaf); [Jenni](https://jenni.ai/)
- EndNote: library groups/labels for PRISMA *counts*, not drawing the figure (JCU guide). — [JCU EndNote PRISMA](https://libguides.jcu.edu.au/endnote/prisma)
- Elsevier 2026: explanatory flowcharts allowed with disclosure; graphical abstracts must use dedicated scientific illustration tools, not general genAI; primary images forbidden. Nature Portfolio: no AI artwork. — [Elsevier policy](https://www.elsevier.com/about/policies-and-standards/generative-ai-policies-for-journals); [Nature Methods](https://www.nature.com/articles/s41592-026-03020-1)

### Inferences
- Factory figure stack should split: (a) **reproducible data plots** from code/data (policy-safe), (b) **PRISMA from exact counts** via official/Shiny/precise-mode tools, (c) **schematics** only with caption disclosure and venue check, (d) never AI microscopy/blots.
- “Figure generation from papers” as *extraction of published figures* is a copyright problem not solved by SciFig-style redraw.

### Gaps
- No strong open-source “methods comparison table from YOUR PDFs” product was found equivalent to CoChat’s extraction tables; that remains a factory-build item.
- BioRender vs AI policy interaction not fully documented here.

## What a local factory would need (CSL/BibLaTeX, claim–citation coupling, related work from YOUR PDFs, draft+extra cites, methods tables)

### Takeaway
SaaS tools cover language, some library-grounded drafting, and post-hoc ref hygiene. A local write-factory still has to own: closed-corpus RAG over user PDFs, span-level claim–citation NLI, CSL/BibLaTeX as source of truth, a queue for “model wanted an extra cite” that must enter Zotero before insertion, methods/extraction tables, and policy/disclosure packaging.

### Cited Findings
- Style engines already exist: Jenni/Paperpal wrap Zotero CSL (10k+ styles); Quarto/Pandoc consume CSL files from [Zotero styles](https://www.zotero.org/styles) or local `.csl`; BibLaTeX via `cite-method: biblatex`. — [Jenni citations](https://docs.jenni.ai/docs/research/citation-management/); [Quarto](https://quarto.org/docs/authoring/citations.html)
- Claim–citation coupling: AutoSurvey uses NLI over claims vs refs; CTS paper shows abstracts are insufficient; ReciteWorks only matches keys; Trinka only Crossref-exists; Overleaf Dimensions suggests papers for unsupported sentences (draft-then-stuff-cites). — [AutoSurvey](https://arxiv.org/html/2406.10252v2); [CTS](https://arxiv.org/html/2309.06365v1); [Literate Computing](https://www.literatecomputing.com/blog/2026-06-22-citation-checkers-compared/); [Overleaf AI assistant](https://docs.overleaf.com/integrations-and-add-ons/ai-features/ai-assistant)
- Related work from YOUR PDFs: Jenni Library + Auto-cite from Library / Configure context (sources ∪ one collection); SciSpace My Library (DOI-filtered Zotero). Neither documents CTS-level entailment. Research RWG systems use open corpora. — [Jenni citations](https://docs.jenni.ai/docs/research/citation-management/); [SciSpace Zotero](https://scispace.com/help/en/articles/10719251-how-to-connect-scispace-with-zotero)
- Draft + extra cites: Writefull Cite and Overleaf “unsupported statements” + Grammarly Citation Finder are exactly this pattern; Elsevier tells authors to read every source before citing. — [Writefull Cite](https://www.writefull.com/writefull-cite); [Citation Finder](https://www.grammarly.com/ai-agents/citation-finder); [Elsevier factsheet](https://researcheracademy.elsevier.com/uploads/2026-06/genai_factsheet_authors_v1_updated-1.pdf)
- Methods tables: CiteGeist.io / CoChat advertise custom extraction columns (method, sample size, findings) with CSV export — closest productized analogue, grounded in their search DBs not necessarily your PDFs. — [CiteGeist](https://citegeist.io/litreview/); [CoChat](https://cochat.ai/scientific-research/)
- Integrity constraints: fake-citation retractions 2025; AI-detection features sold by Paperpal/Writefull/Trinka as pre-submission self-checks (accuracy unknown). — [Retraction Watch book](https://retractionwatch.com/2025/08/04/springer-nature-retracts-book-fake-citations-help-us-find-more/); [Paperpal](https://paperpal.com/)
- Confidentiality: Overleaf sends project text to OpenAI; Elsevier requires checking ToS and preferring institutional/private tools. — [Overleaf AI](https://docs.overleaf.com/integrations-and-add-ons/ai-features); [Elsevier policy](https://www.elsevier.com/about/policies-and-standards/generative-ai-policies-for-journals)

### Inferences
- Recommended local write stack (from public pieces, not an existing product):
  1. Zotero collections + PDFs + BBT auto-export (BibLaTeX) + CSL.
  2. Retrieval **only** from attached full texts (Jenni’s missing-PDF rule is the right invariant).
  3. Related-work draft with CTS/span citations; NLI gate before a `\cite` is emitted.
  4. Extra-cite proposals go to a review queue → human reads → Zotero insert → then cite (never LLM-invented BibTeX).
  5. Methods comparison table as structured extraction over the same PDFs.
  6. PRISMA from screening counts (official template).
  7. Language pass with Writefull-class models (copyedit, often undeclared under SN).
  8. Post-hoc Crossref/retraction/DOI resolve (Trinka/Paperpal-class).
  9. Venue policy pack: disclosure paragraph, figure-caption AI notes, no genAI primary images.
- “Paper factory” as fully automatic manuscript generation is misaligned with 2026 Elsevier factsheet (“must NOT write substantive parts without your own intellectual contribution”) and with Nature’s novelty/accountability rules.

### Gaps
- No open benchmark in this pass that scores commercial writers on (a) library-only mode, (b) claim–span support, (c) extra-cite invention rate.
- Quarto/Typst default citation processing differences noted in Quarto docs were not explored for factory implications.
- Cost, data-retention, and copyright of PDF full-text indexes (Jenni fetch, SciSpace 280M) are legally material and not specified in the pages fetched.
