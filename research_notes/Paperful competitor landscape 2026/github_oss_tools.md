# GitHub OSS tools vs Paperful (as of 2026-11-26)

Dense verification + discovery notes for `docs/comparison.md`. Stars / `pushed_at` from GitHub API unless noted. Complement vs competitor judged against Paperful’s niche: **local Zotero workbench + missing-PDF fetch + disk mirror/restore + held-PDF RAG/evidence**.

## Which listed repos are archived, renamed, unmaintained, or wrong about Zotero 7/10 support?

### Takeaway
None of the comparison-table repos are GitHub-archived. Several are **low-star or quiet** (StorScan, AlphaPulse, Open Citations, richardjlyon MCP, zotero-snowball). The only clear **URL mistake** is PaperOrchestra (`PaperOrchestra` 404 → `paper-orchestra`). Zotero version claims vary: current Zotadata is **8–10 only**; StorScan declares **Zotero 9**; most attachment plugins claim **7–10**.

### Cited Findings

#### Attachment / PDF / metadata plugins (listed)
- **ydeng11/zotero-zotadata** — active, **94★**, MIT, `pushed_at` 2026-11-20; latest release **v1.5.7** (2026-11-16). README: designed for **Zotero 8.x / 9.x / 10.x**; “requires Zotero 8.0 or later”; earlier extension for 7.x. Features: multi-API metadata, multi-source PDF retrieval (Unpaywall/CORE/arXiv + grey sources), attachment validation. — [GitHub](https://github.com/ydeng11/zotero-zotadata); [Releases](https://github.com/ydeng11/zotero-zotadata/releases); [zoteroplugins.org grade](https://zoteroplugins.org/p/zotero-zotadata)
- **brian-j-griffith/StorScan** — **0★**, no SPDX license on API, created 2026-07-26, last commit 2026-07-27 (“Add files via upload”), release **v.1.0.2**. README: **Requires Zotero 9**; linked-attachment audit/repair/rename + “Find Open Full Text”. Alive but nascent / nearly unadopted. — [GitHub](https://github.com/brian-j-griffith/StorScan)
- **MuiseDestiny/zotero-attanger** — **1411★**, AGPL-3.0, `pushed_at` 2026-11-23, release **v1.5.7**. README badge/text: **Zotero 7–10**. Attachment organize/rename/move/copy; not a bulk OA fetcher. Complement to Paperful `attachments`. — [GitHub](https://github.com/MuiseDestiny/zotero-attanger)
- **wileyyugioh/zotmoov** — **1614★**, GPL-3.0, `pushed_at` 2026-11-25, release **1.2.34**. `manifest.json`: `strict_min_version` **6.999**, `strict_max_version` **10.***; README marketed for Zotero 7. Move/copy to linked dir. Complement. — [GitHub](https://github.com/wileyyugioh/zotmoov); [manifest](https://github.com/wileyyugioh/zotmoov/blob/master/manifest.json)
- **RoadToDream/ZotMeta** — **222★**, MIT, `pushed_at` 2026-10-01, release **v2.1**. README: **Zotero 7.0 through 10.0.x**. DOI/ISBN/arXiv metadata bulk update + PDF ID extraction. Complement to Paperful `lint` / `fix-metadata`. — [GitHub](https://github.com/RoadToDream/ZotMeta)

#### Citation-count columns (listed)
- **justinribeiro/zotero-google-scholar-citation-count** — **435★**, MPL-2.0, `pushed_at` 2026-08-31. Active. Complement. — [GitHub](https://github.com/justinribeiro/zotero-google-scholar-citation-count)
- **josesiqueira/zotero-open-citations** — **2★**, MPL-2.0, `pushed_at` 2026-10-01. Alive but tiny adoption. OpenAlex/Semantic Scholar citation column. — [GitHub](https://github.com/josesiqueira/zotero-open-citations)
- **IrisM6/AlphaPulse** — **0★**, AGPL-3.0, `pushed_at` 2026-10-25. Description claims **Zotero 7–11** + alphaXiv likes + GS/OpenAlex/S2 cites. Active commits, zero stars. — [GitHub](https://github.com/IrisM6/AlphaPulse)

#### Agents / MCP (listed)
- **alex-roc/zotero-agent** — **12★**, AGPL-3.0, `pushed_at` 2026-10-26, release **v0.8.8**. “CLI + MCP + bridge plugin”; local, no API key. Closest **CLI sibling** to Paperful for library surgery (not disk mirror). — [GitHub](https://github.com/alex-roc/zotero-agent)
- **cookjohn/zotero-mcp** — **1300★**, MIT, `pushed_at` 2026-11-12, release **v1.7.0**. Zotero **plugin** with integrated MCP server. Active. — [GitHub](https://github.com/cookjohn/zotero-mcp)
- **richardjlyon/zotero-mcp** — **1★**, no license on API, `pushed_at` 2026-07-28. Rust local-first MCP; last activity ~4 months before this note. Not archived, but **marginal**. — [GitHub](https://github.com/richardjlyon/zotero-mcp)
- **Xevos117/mcp-zotero** — **43★**, license NOASSERTION, `pushed_at` 2026-11-24. npm `@xevos117/mcp-zotero`; Unpaywall PDF + Word citation inject. Active. — [GitHub](https://github.com/Xevos117/mcp-zotero)
- **Gap vs docs:** comparison lists those three MCP forks but **omits the dominant** [54yyyu/zotero-mcp](https://github.com/54yyyu/zotero-mcp) (**6077★**, MIT, pushed 2026-11-24) — see NEW section. PlugWiki ranks 54yyyu first among community Zotero MCP servers. — [PlugWiki](https://plugwiki.com/mcp/for/zotero)

#### Hosted / agent / RAG / integrity (listed)
- **summarizepaper/summarizepaper** — **319★**, MIT, `pushed_at` 2026-11-21; product at summarizepaper.com. Hosted OA/preprint companion. Complement, not Zotero mirror. — [GitHub](https://github.com/summarizepaper/summarizepaper)
- **alphaXiv/OpenResearch** — **8552★**, MIT, `pushed_at` 2026-11-26, release **v0.2.30**. Coding-agent → research-agent harness; **not** a Zotero tree tool. — [GitHub](https://github.com/alphaXiv/OpenResearch)
- **google-research/paper-orchestra** — **6500★**, Apache-2.0, `pushed_at` 2026-11-15. **No GitHub Releases**. Multi-agent LaTeX writer. Comparison link `google-research/PaperOrchestra` returns **404**; correct slug is lowercase `paper-orchestra`. — [GitHub](https://github.com/google-research/paper-orchestra); API 404 for `PaperOrchestra`
- **SakanaAI/AI-Scientist** — **15052★**, license NOASSERTION, `pushed_at` 2025-12-19 (stale relative to peers). Companion **SakanaAI/AI-Scientist-v2** **7560★**, same last-push window. Workshop-grade autonomy, not library helper. — [AI-Scientist](https://github.com/SakanaAI/AI-Scientist); [v2](https://github.com/SakanaAI/AI-Scientist-v2)
- **Future-House/paper-qa** — **9674★**, Apache-2.0, `pushed_at` 2026-11-16; PyPI `paper-qa` **v2026.8.12** (CalVer since Dec 2025). Local/agentic lit RAG over **user-supplied** PDFs; no Zotero mirror. — [GitHub](https://github.com/Future-House/paper-qa); [PyPI](https://pypi.org/project/paper-qa/)
- **exergyleizhou-ux/PaperGuard** — **3★**, MIT, `pushed_at` 2026-08-17. Statistical anomaly screener. Complement to Paperful `--forensics`. Low adoption. — [GitHub](https://github.com/exergyleizhou-ux/PaperGuard)

#### Bib / harvesters / snowball / SR (listed)
- **leo1oel/bibcite** — **3★**, MIT, `pushed_at` 2026-10-11. BibTeX resolve CLI. — [GitHub](https://github.com/leo1oel/bibcite)
- **FlamingTempura/bibtex-tidy** — **1129★**, MIT, `pushed_at` 2026-11-23. Active `.bib` cleaner. — [GitHub](https://github.com/FlamingTempura/bibtex-tidy)
- **pcubillos/bibmanager** — **64★**, MIT, `pushed_at` 2026-04-22; docs “Date: Apr 22, 2026”. Astronomy-oriented BibTeX + ADS PDF CLI (`bibm`). — [GitHub](https://github.com/pcubillos/bibmanager); [docs](https://bibmanager.readthedocs.io/)
- **jannisborn/paperscraper** — **548★**, MIT, `pushed_at` 2026-10-14. DOI/list metadata + PDF lanes **without Zotero**. — [GitHub](https://github.com/jannisborn/paperscraper)
- **jonatasgrosman/findpapers** — **428★**, MIT, `pushed_at` 2026-08-18. Multi-database search/download CLI; no Zotero mirror. — [GitHub](https://github.com/jonatasgrosman/findpapers)
- **neuromechanist/opencite** — **7★**, MIT, `pushed_at` 2026-10-23. “Academic literature search, citation management, and PDF retrieval CLI.” — [GitHub](https://github.com/neuromechanist/opencite)
- **socratic-irony/zotero-snowball** — **2★**, MIT, `pushed_at` 2026-11-25. In-Zotero one-hop OpenAlex snowball; README still says replace slug before publishing. Active but tiny. — [GitHub](https://github.com/socratic-irony/zotero-snowball)
- **phdemotions/zotero-citegeist** — **28★**, GPL-3.0, `pushed_at` 2026-09-29. Cite counts + network browser + one-click add; **Zotero 7+** (tested through 9). — [GitHub](https://github.com/phdemotions/zotero-citegeist)
- **asreview/asreview** — **1078★**, Apache-2.0, `pushed_at` 2026-11-23. Active learning for SR screening. Complement. Related **retorquere/zotero-asreview** last push **2022-03-29** (dormant bridge). — [ASReview](https://github.com/asreview/asreview); [zotero-asreview](https://github.com/retorquere/zotero-asreview)
- **amirkiarafiei/open-scholar-peer** — **151★**, MIT, `pushed_at` 2026-11-21. Open ScholarPeer protocol skills for AI peer-review. Complement / adjacent to Paperful peer-review lane (docs already distinguish). — [GitHub](https://github.com/amirkiarafiei/open-scholar-peer)

### Inferences
- **No archived listed repos** as of 2026-11-26; “unmaintained” is better framed as **starvation / quiet** (StorScan, AlphaPulse @ 0★; richardjlyon MCP; Open Citations @ 2★; Sakana AI-Scientist last push Dec 2025 while the space moved on).
- Comparison docs slightly **over-weight** richardjlyon/Xevos relative to **54yyyu** (stars ~1 / 43 vs 6077).
- **Zotero 7 support is not universal** among “PDF plugins”: Zotadata current line is 8+; StorScan is 9-only; claiming blanket “Zotero 7/10” for the whole table would be wrong.
- PaperOrchestra comparison URL should be fixed to `paper-orchestra` (rename/slug case issue, not a dead project).

### Gaps
- Exact live Zotero 10.x runtime test results for each plugin were not re-run; version claims are from README/manifest/releases only.
- StorScan SPDX license unclear (API `license: null`).
- Whether AlphaPulse’s “Zotero 11” claim matches any public Zotero release train was not independently verified beyond the repo description string.

---

## What NEW GitHub projects (2024–2026) cover PDF fetch, local lit RAG, literature MCP, helpers, agents, integrity, snowball, or OA companions?

### Takeaway
A dense 2025–2026 cluster appeared: **in-Zotero batch PDF fetchers** (ZotFetch, OpenAlex PDF, Better Find Full Text, PDFerret, Sci-PDF), **local Zotero RAG/MCP** (54yyyu, Seer-AI, ZotSeek, PapersGPT, ChiKen, native MCP), and **OpenAlex official CLI/MCP** for corpus-side OA PDFs. None advertise Paperful’s quiet **disk mirror + restore ledger**.

### Cited Findings

#### New / newly salient Zotero PDF fetch plugins
- **fdossi/zotfetch** — **6★**, MIT, `pushed_at` 2026-11-10. Batch PDF pipeline (OA → Unpaywall → S2 → OpenAlex → Europe PMC → CORE → DOI landing → **institutional proxy** / CAPES); HTML-to-PDF extractors; declares **Zotero 8.0.4–10.0.x**. Closest **in-app** peer to Paperful’s campus-proxy + multi-source fetch. — [GitHub](https://github.com/fdossi/zotfetch)
- **Littview/zotero-openalex-pdf** — **6★**, MIT, `pushed_at` 2026-11-11. Right-click attach **legal OA** via OpenAlex; **Zotero 7–10**; no API key. — [GitHub](https://github.com/Littview/zotero-openalex-pdf)
- **ppavlidis/better-find-full-text** — **6★**, license null on API, `pushed_at` 2026-09-11. Extends built-in Find Available PDF; paywall → browser + **Connector auto-merge**. Zotero 7/8/9/10 in README title. — [GitHub](https://github.com/ppavlidis/better-find-full-text)
- **urschrei/pdferret** — **56★**, NOASSERTION, `pushed_at` 2026-10-24. Registers custom PDF resolvers; default Sci-Hub / Anna’s Archive style providers; **Zotero 8+**. — [GitHub](https://github.com/urschrei/pdferret)
- **syt2/zotero-scipdf** — **1043★**, AGPL-3.0, `pushed_at` 2026-09-09; fork **LuckerYan/zotero-scipdf** **9★**. Multi-source incl. Sci-Hub-style mirrors; Zotero 7/8/9. High stars, grey-zone positioning. — [syt2](https://github.com/syt2/zotero-scipdf); [LuckerYan](https://github.com/LuckerYan/zotero-scipdf)

#### Local lit RAG / Zotero AI / MCP (new or under-listed)
- **54yyyu/zotero-mcp** — **6077★**, MIT, `pushed_at` 2026-11-24. Semantic search, PDF read/annotate, write paths, CLI + skill + in-Zotero agent plugin. De-facto default community Zotero MCP. — [GitHub](https://github.com/54yyyu/zotero-mcp)
- **dralkh/seerai** — **97★**, MIT, created 2025-12, `pushed_at` 2026-10-06. Zotero **9/10** AI plugin: chat, RAG, OCR, federated scholarly search (11 providers), PRISMA-style SR, standalone MCP. Overlaps Ask/RAG + discovery more than mirror. — [GitHub](https://github.com/dralkh/seerai)
- **introfini/ZotSeek** — **245★**, license null, `pushed_at` 2026-11-15. 100% local semantic search; built-in **read-only MCP**; Zotero 8/9/10. Author also mentions **citefact** manuscript audit (repo slug not confirmed via API). — [GitHub](https://github.com/introfini/ZotSeek)
- **papersgpt/papersgpt-for-zotero** — **2716★**, AGPL-3.0, `pushed_at` 2026-11-25. Chat with PDFs, whole-library search, Literature Radar, MCP server. Major in-Zotero AI product. — [GitHub](https://github.com/papersgpt/papersgpt-for-zotero)
- **yuanjua/chiken** — **90★**, MIT, last commit **2025-09-05**. Local RAG + MCP + deep research; **quiet ~14 months**. — [GitHub](https://github.com/yuanjua/chiken)
- **kujenga/zotero-mcp** — **162★**, MIT, `pushed_at` 2026-08-07. Lightweight read-oriented Python MCP. — [GitHub](https://github.com/kujenga/zotero-mcp)
- **dvdsosa/zotero-native-mcp** — **15★**, MIT, `pushed_at` 2026-11-08. MCP for **Zotero 10+ native local API**; no plugin/API key. — [GitHub](https://github.com/dvdsosa/zotero-native-mcp)
- **MuiseDestiny/zotero-gpt** — **7542★**, AGPL-3.0, `pushed_at` 2026-11-17. Long-standing “GPT meet Zotero” plugin (adjacent AI chat; not PDF completeness). — [GitHub](https://github.com/MuiseDestiny/zotero-gpt)

#### OpenAlex / OA companions / literature MCP (non-Zotero tree)
- **ourresearch/openalex-official** — **40★**, `pushed_at` 2026-09-19; `pip install openalex-official`. Official CLI: parallel metadata + **PDF/TEI** download with checkpoint/resume. Corpus OA companion, not Zotero write-back. — [GitHub](https://github.com/ourresearch/openalex-official); [CLI docs](https://help.openalex.org/access/cli/)
- **ourresearch/openalex-mcp-server** — **6★**, MIT, `pushed_at` 2026-11-26; hosted endpoint `https://mcp.openalex.org/mcp`. Official scholarly search MCP (OAuth). — [GitHub](https://github.com/ourresearch/openalex-mcp-server)
- **Kaago/openpapers-mcp** — **4★**, MIT, `pushed_at` 2026-10-18. Local stdio MCP: OpenAlex + CrossRef + Unpaywall **legal OA PDF** download. — [GitHub](https://github.com/Kaago/openpapers-mcp)
- Unpaywall is documented as **legacy-compatible OpenAlex surface** (same OA data since late 2025). — [OpenAlex Unpaywall help](https://help.openalex.org/access/unpaywall/)

#### Literature-review MCP / agent scaffolds (mostly SKIP-tier)
- **ydzat/literature-review-mcp** — **25★**, updated 2026-09. Chinese-doc lit-review MCP. — [GitHub](https://github.com/ydzat/literature-review-mcp)
- **helplessness/benchthread** — **4★**, self-hosted research workspace + MCP. — [GitHub](https://github.com/helplessness/benchthread)

### Inferences
- 2026’s competitive pressure on Paperful’s **fetch** row is from **ZotFetch / OpenAlex-PDF / Better-Find / Sci-PDF / PDFerret**, not from AI-scientist repos.
- 2026’s pressure on Paperful’s **ask/RAG/MCP** row is from **54yyyu, PapersGPT, Seer-AI, ZotSeek**, not from PaperQA2 alone.
- OpenAlex’s official CLI/MCP create a strong **complement** lane for “download OA PDFs by filter” without competing on Zotero restore.

### Gaps
- Full feature parity matrices (proxy cookies, Sci-Hub opt-in ethics, resume manifests) were not exhaustively re-tested against Paperful CLI.
- `introfini/citefact` returned GitHub 404 under that slug; existence elsewhere unverified.
- npm/PyPI install counts were not pulled; GitHub stars used as activity proxy.

---

## Which new tools are close enough to Paperful’s niche that they belong in docs/comparison.md?

### Takeaway
**ADD** the high-signal Zotero PDF fetchers (esp. ZotFetch), the dominant **54yyyu** MCP, and 1–2 local RAG plugins (ZotSeek / Seer-AI / PapersGPT). **WATCH** grey-zone Sci-PDF/PDFerret and OpenAlex official CLI. **SKIP** tiny lit-review MCP demos and dormant ChiKen unless stars revive. Nothing found matches Paperful’s **collection-folder mirror + restore ledger** as a first-class peer.

### Cited Findings

| Verdict | Project | Stars | Last push | License | Fit vs Paperful | Rationale |
|---------|---------|------:|-----------|---------|-----------------|-----------|
| **ADD** | [fdossi/zotfetch](https://github.com/fdossi/zotfetch) | 6 | 2026-11-10 | MIT | **Near-competitor (fetch)** | In-Zotero batch PDF + institutional proxy; closest plugin peer to Paperful `run` / EZProxy lane. Low stars but capability overlap is high. |
| **ADD** | [54yyyu/zotero-mcp](https://github.com/54yyyu/zotero-mcp) | 6077 | 2026-11-24 | MIT | **Complement (agent)** | Should replace/lead the MCP row currently citing lesser forks. |
| **ADD** | [Littview/zotero-openalex-pdf](https://github.com/Littview/zotero-openalex-pdf) | 6 | 2026-11-11 | MIT | **Complement (OA attach)** | Simple legal OA attach; good “Find Available PDF+” comparison cell. |
| **ADD** | [ppavlidis/better-find-full-text](https://github.com/ppavlidis/better-find-full-text) | 6 | 2026-09-11 | ? | **Complement (fetch UX)** | Connector merge workflow unique; belongs under attachment/PDF hygiene. |
| **ADD** | [introfini/ZotSeek](https://github.com/introfini/ZotSeek) | 245 | 2026-11-15 | ? | **Complement (local RAG)** | Local semantic search + read-only MCP over *held* library — same Ask niche, different product shape. |
| **ADD** | [dralkh/seerai](https://github.com/dralkh/seerai) | 97 | 2026-10-06 | MIT | **Partial competitor (in-app workbench)** | Chat/RAG/OCR/federated search/SR inside Zotero; overlaps Ask + discover, not mirror. |
| **ADD** | [papersgpt/papersgpt-for-zotero](https://github.com/papersgpt/papersgpt-for-zotero) | 2716 | 2026-11-25 | AGPL-3.0 | **Complement / partial competitor (AI)** | Large installed-base Zotero AI; cite in chat/RAG row. |
| **ADD** | [dvdsosa/zotero-native-mcp](https://github.com/dvdsosa/zotero-native-mcp) | 15 | 2026-11-08 | MIT | **Complement (Zotero 10 MCP)** | Native local API path matters as Zotero 10+ write-back matures. |
| **WATCH** | [ourresearch/openalex-official](https://github.com/ourresearch/openalex-official) | 40 | 2026-09-19 | (see repo) | **Complement (corpus OA CLI)** | Bulk OA PDF/TEI without Zotero; optional footnote next to paperscraper/findpapers. |
| **WATCH** | [ourresearch/openalex-mcp-server](https://github.com/ourresearch/openalex-mcp-server) | 6 | 2026-11-26 | MIT | **Complement (public corpus MCP)** | Adjacent to Valency/hosted search row, not held-PDF Ask. |
| **WATCH** | [Kaago/openpapers-mcp](https://github.com/Kaago/openpapers-mcp) | 4 | 2026-10-18 | MIT | **Complement (OA PDF MCP)** | Legal OA download MCP; early. |
| **WATCH** | [syt2/zotero-scipdf](https://github.com/syt2/zotero-scipdf) | 1043 | 2026-09-09 | AGPL-3.0 | **Partial competitor (grey fetch)** | High adoption grey-zone fetcher; only mention carefully (opt-in ethics), akin to Zotadata Sci-Hub lane. |
| **WATCH** | [urschrei/pdferret](https://github.com/urschrei/pdferret) | 56 | 2026-10-24 | NOASSERTION | **Partial competitor (resolver)** | Resolver registration; Sci-Hub-default positioning. |
| **WATCH** | [kujenga/zotero-mcp](https://github.com/kujenga/zotero-mcp) | 162 | 2026-08-07 | MIT | **Complement (light MCP)** | Optional footnote under MCP forks. |
| **SKIP** | [yuanjua/chiken](https://github.com/yuanjua/chiken) | 90 | 2025-09-05 | MIT | Stale local RAG | No commits ~14 months; revisit if revived. |
| **SKIP** | [ydzat/literature-review-mcp](https://github.com/ydzat/literature-review-mcp) | 25 | 2026-09 | — | Demo MCP | Not Zotero/mirror-adjacent enough. |
| **SKIP** | [helplessness/benchthread](https://github.com/helplessness/benchthread) | 4 | 2026-11 | — | Workspace scaffold | Too early / off-niche. |
| **SKIP** | [retorquere/zotero-asreview](https://github.com/retorquere/zotero-asreview) | 4 | 2022-03 | — | Dormant bridge | ASReview itself stays; Zotero bridge is dead. |
| **FIX (listed)** | PaperOrchestra URL → [google-research/paper-orchestra](https://github.com/google-research/paper-orchestra) | 6500 | 2026-11-15 | Apache-2.0 | Already listed | Case-sensitive slug. |
| **KEEP / note** | StorScan, AlphaPulse, Open Citations, richardjlyon | 0–2★ | 2026 | various | Already listed | Flag as **low adoption** in reference notes; don’t drop solely for stars if capability still unique. |
| **KEEP** | alex-roc/zotero-agent | 12 | 2026-10-26 | AGPL-3.0 | Closest CLI complement | Remains the right “scriptable surgery” neighbor. |

### Inferences
- **Direct competitors** (same jobs: missing-PDF completeness + local control): primarily **ZotFetch**, **zotero-zotadata**, secondarily Sci-PDF/PDFerret; **zotero-agent** for CLI surgery. None yet claim portable `out/` mirror + restore.
- **Complements** that should appear in the short table: **54yyyu MCP**, **ZotSeek/Seer-AI/PapersGPT** (Ask), **OpenAlex-PDF / Better-Find** (fetch hygiene), **OpenAlex official CLI** (non-Zotero OA batch).
- Attachment plugins (Attanger/ZotMoov/StorScan) remain complements; StorScan’s “Find Open Full Text” does not make it a Paperful fetch substitute given 0★ and Zotero-9-only scope.

### Gaps
- No public GitHub project found that documents a Paperful-like **collection-shaped disk mirror with restore ledger**; absence is inferred from search/README sampling, not a formal census of all Zotero plugins.
- Commercial hosted tools (Elicit, etc.) intentionally out of this GitHub-OSS brief except where already in comparison.

---

## Star counts, last activity, license, and one-line fit (master roster)

### Takeaway
Use this roster as the comparison-doc update checklist. **Active majority**; watch low-star listed tools and grey-zone fetchers; prioritize ADDs for ZotFetch + 54yyyu + local RAG plugins.

### Cited Findings

#### Already in comparison — status snapshot (2026-11-26)
| Tool | ★ | Last push | License | Zotero (claimed) | One-line fit |
|------|--:|-----------|---------|-----------------|--------------|
| [zotero-zotadata](https://github.com/ydeng11/zotero-zotadata) | 94 | 2026-11-20 | MIT | **8–10** (7 via older) | In-app OA/grey PDF + metadata; closest plugin fetch competitor |
| [StorScan](https://github.com/brian-j-griffith/StorScan) | 0 | 2026-07-27 | ? | **9** | Linked-attachment toolkit; nascent |
| [Attanger](https://github.com/MuiseDestiny/zotero-attanger) | 1411 | 2026-11-23 | AGPL-3.0 | 7–10 | Attachment organize/rename/move |
| [ZotMoov](https://github.com/wileyyugioh/zotmoov) | 1614 | 2026-11-25 | GPL-3.0 | 7–10 (`6.999`–`10.*`) | Auto move/copy → linked files |
| [ZotMeta](https://github.com/RoadToDream/ZotMeta) | 222 | 2026-10-01 | MIT | 7–10.0.x | Bulk DOI/ISBN/arXiv metadata |
| [GS Citation Count](https://github.com/justinribeiro/zotero-google-scholar-citation-count) | 435 | 2026-08-31 | MPL-2.0 | (plugin) | GS citation column |
| [Open Citations](https://github.com/josesiqueira/zotero-open-citations) | 2 | 2026-10-01 | MPL-2.0 | (plugin) | OpenAlex/S2 citation column |
| [AlphaPulse](https://github.com/IrisM6/AlphaPulse) | 0 | 2026-10-25 | AGPL-3.0 | 7–11 claimed | alphaXiv likes + cites |
| [zotero-agent](https://github.com/alex-roc/zotero-agent) | 12 | 2026-10-26 | AGPL-3.0 | bridge plugin | Local CLI/MCP library surgery |
| [cookjohn/zotero-mcp](https://github.com/cookjohn/zotero-mcp) | 1300 | 2026-11-12 | MIT | plugin MCP | In-Zotero MCP server |
| [richardjlyon/zotero-mcp](https://github.com/richardjlyon/zotero-mcp) | 1 | 2026-07-28 | ? | local MCP | Quiet Rust MCP |
| [Xevos117/mcp-zotero](https://github.com/Xevos117/mcp-zotero) | 43 | 2026-11-24 | NOASSERTION | API MCP | Library + OA PDF + Word cites |
| [SummarizePaper](https://github.com/summarizepaper/summarizepaper) | 319 | 2026-11-21 | MIT | n/a | Hosted OA summary companion |
| [OpenResearch](https://github.com/alphaXiv/OpenResearch) | 8552 | 2026-11-26 | MIT | n/a | Coding-agent research harness |
| [paper-orchestra](https://github.com/google-research/paper-orchestra) | 6500 | 2026-11-15 | Apache-2.0 | n/a | Multi-agent LaTeX writer (**fix URL**) |
| [AI-Scientist](https://github.com/SakanaAI/AI-Scientist) | 15052 | 2025-12-19 | NOASSERTION | n/a | Autonomous workshop scientist |
| [paper-qa](https://github.com/Future-House/paper-qa) | 9674 | 2026-11-16 | Apache-2.0 | n/a | Local lit RAG over supplied PDFs |
| [PaperGuard](https://github.com/exergyleizhou-ux/PaperGuard) | 3 | 2026-08-17 | MIT | n/a | Stats/forensics screener CLI |
| [bibcite](https://github.com/leo1oel/bibcite) | 3 | 2026-10-11 | MIT | n/a | BibTeX resolve CLI |
| [bibtex-tidy](https://github.com/FlamingTempura/bibtex-tidy) | 1129 | 2026-11-23 | MIT | n/a | `.bib` tidy/dedupe |
| [bibmanager](https://github.com/pcubillos/bibmanager) | 64 | 2026-04-22 | MIT | n/a | Astronomy BibTeX + ADS PDF CLI |
| [paperscraper](https://github.com/jannisborn/paperscraper) | 548 | 2026-10-14 | MIT | n/a | Non-Zotero PDF/metadata scrape |
| [findpapers](https://github.com/jonatasgrosman/findpapers) | 428 | 2026-08-18 | MIT | n/a | Multi-DB search/download |
| [opencite](https://github.com/neuromechanist/opencite) | 7 | 2026-10-23 | MIT | n/a | Search + cite + PDF CLI |
| [zotero-snowball](https://github.com/socratic-irony/zotero-snowball) | 2 | 2026-11-25 | MIT | plugin | In-app OpenAlex one-hop |
| [Citegeist](https://github.com/phdemotions/zotero-citegeist) | 28 | 2026-09-29 | GPL-3.0 | 7+ (≤9 tested) | Metrics + citation network UI |
| [ASReview](https://github.com/asreview/asreview) | 1078 | 2026-11-23 | Apache-2.0 | n/a | Active-learning SR screening |
| [open-scholar-peer](https://github.com/amirkiarafiei/open-scholar-peer) | 151 | 2026-11-21 | MIT | n/a | ScholarPeer protocol skills |

Sources: GitHub REST `GET /repos/{owner}/{repo}` on 2026-11-26; READMEs linked above.

#### NEW candidates — ADD / WATCH / SKIP (one-liners)
See verdict table in previous section; highest-priority **ADD**s for `docs/comparison.md`: **ZotFetch**, **54yyyu/zotero-mcp**, **ZotSeek**, **Seer-AI**, **PapersGPT**, **zotero-openalex-pdf**, **better-find-full-text**, **zotero-native-mcp**; **FIX** PaperOrchestra slug.

### Inferences
- Paperful’s differentiation that still holds after this survey: **disk-first collection mirror, restore ledger, campus-proxy CLI, grey playbooks, evidence tables, peer-review packs** — still weakly covered by the OSS field.
- Fetch niche is **crowding inside Zotero**; Ask/RAG niche is **crowding via MCP plugins**; mirror niche remains **sparse**.

### Gaps
- Star counts move daily; treat as ±same-day snapshots.
- Licenses marked `?` / `NOASSERTION` need SPDX confirmation before legal copy in docs.
- PyPI download stats for `paper-qa`, `openalex-official`, `bibmanager` not collected.
