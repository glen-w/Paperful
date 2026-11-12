# Roadmap

Guidance for contributors, not a commitment calendar. Paperful’s jobs are
**library**, **find**, **completeness**, **mirror**, and **control**: one
disk mirror (`out/`, `state/`), adapters for citation managers, and fetch /
lint / attach / summarise as the core loop. **Zotero is the well-tested
adapter.** Mendeley and EndNote are in the tree and seeking testers. See
[architecture.md](architecture.md) and [why.md](why.md).

Optional thin bridges (`paperful session login`) capture a local browser profile;
they do not rewrite the fetcher. A **Zotero plugin** is not the 1.0 bet.
The **Firefox extension** is an optional mirror bridge ([firefox.md](firefox.md)).
**Local OpenAlex snapshot** (beyond today’s opt-in v1) stays later — see
[Product split](#product-split-10-vs-post-10) and the
[post-1.1 buffet](#after-110-buffet-by-area). Alert loop / what-cites:
[`keepup`](keepup.md).

**1.0** is the trust checklist below (all rows shipped), a locked item record
(`paperful.item.v1` plus `snapshot` / `restore`), proven on **Zotero**, and the
**workbench** ([GUI](#gui)): Discover + Wanted + Ask on the default nav, Preview/Grab
with review tokens, full CLI surface behind **Advanced**. **Interactive Ask**
is `/ask` when `[rag]` + `[llm]` are on, not the home page
([Zotero-RAG integration](#zotero-rag-integration-later-question-centric-layer)).
**Mendeley and EndNote do not gate 1.0** — they stay in the tree with honest
docs (“seeking testers”; Zotero well-tested). Do not market them as supported
until real-library reports say so.
Still not a full-text reading index, not a WebDAV client, and not “AI fetch
everything.” `paperful ocr` is the optional text layer for scans. **1.0.0 and
1.1.0 are tagged** (1.1.0 on PyPI). **1.1.1** is stop-ship hygiene (shipped in
tree). **1.2.0** adds snowball stopping rules, off by default. **1.7.0**
(2026-11-02) is the hardening and platform cut. The **live map** is
[After 1.7](#after-17-live-map). The [1.1 area index](#after-110-buffet-by-area)
still lists jobs by area; many of those rows have shipped. Do not re-pick
them as the next thing to build.

(product-split-10-vs-post-10)=
## Product split: 1.0 vs post-1.0

Contributor decisions (not a calendar). **1.0** is CLI honesty plus the
operator workbench; **post-1.0** items stay on the map for power users and
integrations.

| **1.0** | **Post-1.0** |
| --- | --- |
| Trust checklist, locked `paperful.run_report.v1` / `paperful.item.v1`, snapshot contract | **Local OpenAlex parquet store** — phase 2C (full search / keyword / ORCID / `http`). Live API is enough for most installs; `ssh_duckdb` / `local_duckdb` + cites index remain opt-in |
| **GUI workbench** — Discover + Wanted simple loop (topic + people); command ids; review tokens; Advanced Repair / Mirror / Index / Briefs and the non-TTY CLI verbs | **Firefox extension** — optional native messaging into the mirror ([firefox.md](firefox.md)) |
| **Ask in GUI** — `/ask` on the default nav, scoped chat with citations when `[rag]` + `[llm]` on | Discover keepup UX polish; `refs` on collection digest; retractions / living-review ([Keeping up](#after-110-keeping-up)) |
| Zotero-proven fetch/mirror path; honest adapter docs (Mendeley / EndNote seeking testers) | SaaS tenancy polish; promoting other managers to “supported” after field reports; remote-manager parity beyond what 1.0 open/Docker needs |

**1.1.x vs later (still not a calendar).** 1.1.0 is the PyPI cut. **1.1.1**
closes Wanted scoping, ticks, Attach-at-zero, version drift, and first-hour
copy. **Wanted excellence** has shipped. Digest, precedent, PRISMA counts,
and grey URL watches have shipped too. The live order is
[After 1.7](#after-17-live-map); the area index below is the encyclopaedia.

(after-110-v2-factory-framing)=
**1.x vs v2 (factory, still not a calendar).** Public 1.x copy stays
**“find missing PDFs in Zotero.”** Internally, v2 is **named packs on that
ledger**, not a hosted Kosmos clone and not launch-page “academic paper
factory.” Sequence: Wanted honest → grow/keep current → Ask **your** PDFs →
then (gated) precedent pack, conflicting-evidence briefs, `stuff` into
Zotero, PRISMA **counts**. Those packs have since shipped. At most **one**
bigger bet a year. Grey-host watching shipped (`search` / `search watch`);
the bet now on the table is [systematic review](#after-17-sr). Never
auto-manuscript. Comparison routing:
[comparison.md](comparison.md); stage matrix:
[paper factory stages](comparison-reference.md#paper-factory-stages);
packs: [v2 factory](#after-110-paper-factory).

(after-17-live-map)=
## After 1.7 (live map)

Contributor map, not a commitment calendar. This is the section to read
before opening a new lane. The [1.1 area index](#after-110-buffet-by-area)
under it is still the encyclopaedia of jobs; it is not the order.

**Working stance:**

1. The ledger is honest enough to stop treating Wanted as the only lane.
   Residual Wanted polish stays polish.
2. The next product question is the one the 1.1 index already asked: what
   would make a researcher open Paperful again next week, once the gaps
   list is no longer a surprise?
3. Answer that with **joins of verbs that already exist**, plus **one**
   bigger bet carried forward from the annual cap
   ([systematic review](#after-17-sr)). Grey-literature watching already
   shipped (`paperful search`, `search watch`). It is not still the
   undecided bet.
4. At most one new workbench surface. Activity or Discover can host it.
   A new nav item waits until that surface has been used on a real
   collection for a month.
5. Each stage below can stop. Stopping is a successful outcome when the
   acceptance line fails.

(after-17-settled)=
### What 1.7 already settled

Sources: [1.7 decision log](plans/1.7-wave.md), [legal-privacy](legal-privacy.md),
changelog **1.7.0**. The 1.8.0 workbench hardening wave sits on top of
that tag (content-security policy, orphaned jobs, cached counts, Wanted and
Discover layout). It is in tree; it is not a reason to reopen 1.7’s
product decisions.

| Decision | Outcome |
| --- | --- |
| Install story | CLI: `pipx` / `uv tool`. Workbench: Docker Compose. `[serve]` without Docker stays documented, not the path CI proves end to end |
| Playwright | Optional extra `paperful[browser]`. Compose still installs it. `doctor` names the extra when a lane needs it |
| Workbench exposure | Loopback by default. Opt-in bearer token (`PAPERFUL_UI_TOKEN` / `serve --ui-token`) for a deliberate `--allow-remote-bind`. One shared secret, no accounts |
| OS keyring | **No** for 1.7. Headless and Docker installs have no keyring daemon. Secrets stay in the environment; `config check` points at them |
| Signed desktop bundle | **Rejected**, not deferred. Reach does not pay for notarisation while pipx and Compose cover the tested routes |
| Update notice | Opt-in check against PyPI. No general telemetry |
| Adapter “supported” | Conformance suite on a fake, **and** a filled [field assessment](templates/adapter-field-assessment.md) under `assessments/`, **and** mirror-first reads with the manager closed. Until then, Mendeley and EndNote stay “seeking testers” |
| Legal and fetch stance | Written on [legal-privacy](legal-privacy.md). Not legal advice. Publisher terms and campus licences stay the operator’s call |
| Python | 1.7 put 3.14 on the matrix. The live gate is smoke on 3.12 until the [rebuild](#after-17-ci-rebuild) puts the other versions back. `requires-python >=3.10` stays so existing installs are not stranded. Dropping 3.10 is a separate announced change |
| Coverage | Gate is **82**. A gate of 85 was measured and missed (82.3% at wave end) because new code grew the denominator. Do not claim 85 |
| Systematic review | A scaffold exists: `paperful sr init`, `sr screen`, `sr status` write a protocol and an append-only ledger under `state/sr/<slug>/`. That is not the bigger bet. The bet starts at [SR-1](#after-17-sr) |

(after-17-eaten)=
### What the 1.1 sequence already ate

The [old order](#after-110-sequence) and several [open questions](#after-110-open-questions)
are answered in tree. Recorded here so the next plan does not rebuild them.

| 1.1 “then decide” item | Where it landed |
| --- | --- |
| Wanted stamps, miss reasons, hand-ticks, Waiting→add | Shipped. 1.1.1 closed Grab scoping, ticks, Attach-at-zero |
| Weekly digest / alert loop | [`keepup`](keepup.md). Operator cron. No email, no built-in scheduler |
| Snowball stopping rule, drift cache, PRISMA **counts** | Shipped, counts only, no recall percentage |
| Precedent pack, named MCP read jobs | Waves 1–4 shipped (`precedent` included) |
| Conflicting-evidence and review-shaped briefs | `ask --focus conflict`; `synthesize --layout conflict` / `review` |
| `stuff` pack | CLI and Advanced workbench. `--apply` still later |
| Grey URL finding | `paperful search` + `search watch` |
| Author lists, co-author preflight, Twenty lookup | Shipped, opt-in |
| Note provenance and scoped delete | `paperful.note.v1`, `paperful notes delete` |
| OpenAlex topic housekeeping | Run stamp, watch rebaseline, snapshot warning, frozen fixture. **Topic-native product** is still open — [below](#after-17-topics) |
| Install route argument | Settled above. PyPI “which route?” is not an open product question |

Still genuinely open, and specified below: a weekly **holdings diff**,
citation debt that ages, a read-only memory of decisions already on disk,
Ask used as a **claim check**, the SR scaffold grown into a review you can
finish, topic gap map, playbook health, and the platform residuals 1.7
wrote down and did not do.

(after-17-habit)=
### Habit: one report of what changed

**Status:** roadmap. No command yet. Do not add a scheduler, an email, or
a nav item in the first slice.

The researcher already has watches (`keepup`), a miss list (`gaps`), a
retraction pass (`screen`), a version merge (`versions`), a URL check
(`urls check`), and a witness on run reports. None of those answers
“what is different since I last looked?” They answer “what is true now?”
The habit is the diff.

**Command sketch:** `paperful since` (name may change before it lands).
Always dry-run. Compares the live mirror and a fresh *plan* (no PDF
bytes) to the last [run witness](#run-witness-shipped-trust-thicken) for
a `-C`, or to `--since DATE` when there is no witness. Writes
`state/since/<stamp>/` (`since.md` + `paperful.since.v1`). Empty output
is a successful run: print “nothing changed” and do not file a Zotero
note.

Two sections, one pack:

1. **Holdings that changed meaning**
   - New retraction or expression of concern on an item you hold
     (`screen`, report-only).
   - Preprint with a version-of-record candidate (`versions`, no merge).
   - Metadata URL or linked PDF that newly classifies `hard_dead` or
     `paywall_html` (`urls check` against the previous `urls` report
     when one exists; otherwise this section says “no prior URL report”
     and skips, rather than paging the whole web on first run).
   - Snapshot-tier PDF (`snapshot:htmlpdf`) whose dry-run now names a
     native lane. Suggest `run --upgrade-snapshot` for those keys only.
   - Parents created by `keepup apply` that are still missing a PDF.
2. **Misses that healed**
   - Last `run` report said `not_found`, `no_oa`, `paywalled`, or
     `fetch_failed`; a new `--dry-run` (no download) now names an OA or
     campus candidate. Rank by the same cite-count × severity score
     handoff already uses.
   - Do not download in `since`. The operator opens Wanted or `run` for
     the keys the pack lists.

**Honesty bar.** Every row names the verb that produced it and the
witness id or date it was compared to. A row with no prior observation
is omitted, not invented. `since` never calls `--apply` on screen, never
attaches, never creates parents.

**Acceptance.**

- Zero manager writes. Zotero may be closed (mirror-first).
- Golden fixture: a tiny mirror plus two saved reports → a frozen
  `paperful.since.v1` with one healed miss and one retraction, and a
  second fixture that expects the empty pack.
- First run on a collection with no witness exits 0, says what it could
  not compare, and still reports sections that need no history (new
  retraction lookup is allowed; “healed” is not).
- Dogfood: four weekly runs on one real collection (BBNJ or whatever
  `-C` the operator actually refills). If three of the four packs are
  noise (rows the operator immediately dismisses), narrow the diff
  before any workbench page.

**Workbench.** A **Since** block on Activity (the page that already lists
jobs), rendered from the latest pack. Buttons deep-link to Wanted with
those keys, to `screen`, and to `versions`. They do not fetch.

**Stop.** If four dogfood packs are never opened, leave the command in
the CLI and do not build the block.

(after-17-citation-debt)=
### Citation debt that ages

**Status:** roadmap. Extend shipped `paperful refs gap`. Do not add a
second gap verb.

`refs gap` is a snapshot of “cited in these PDFs, not in the library.”
The snapshot forgets itself. The thickening is a fingerprint memory:

- On each run, key rows by the same identity `refs gap` already uses
  (DOI, else title+year, else grey fingerprint).
- Store the key, first-seen stamp, last-seen stamp, and
  `cited_by_count_in_scope` under `state/refs-gaps/memory.jsonl`
  (append; the latest row wins).
- The pack gains a `delta` per row: `new`, `still_missing`,
  `cite_count_up`, `now_owned`, `gone_from_drafts`.
- Rank still-missing by cite count × weeks since first-seen. A row that
  appears in a `--file` draft passed this run sorts above a row that
  appears only inside already-held PDFs.
- `suggested_action` stays `ingest-dois` dry-run or skip. `since` may
  *list* the top still-missing rows; it does not ingest them.

**Acceptance.** Re-running `refs gap` on an unchanged fixture yields
`still_missing` with the same cite count and a stable first-seen.
Adding the DOI to the fixture library yields `now_owned` and drops the
row from the default table (it remains in the jsonl). No parent create.

**Stop.** If operators do not hand the pack to `ingest-dois` on a real
collection within a month of dogfood, do not put debt on the workbench.
The jsonl is still worth keeping: it makes the next pack honest.

(after-17-decisions)=
### Decisions this collection already made

**Status:** roadmap. Read-only. No new ledger.

`state/` already remembers Keep/Skip, `keepup dismiss`, rejected inbox
proposals, promoted author packs, acronym files, and (when used) `sr`
screen rows. Operators re-litigate those because nothing reads them
together.

**Command sketch:** `paperful decisions -C …`. Prints one table. Omits a
source that has no stable key rather than scraping note prose.

| Source on disk | Row shows |
| --- | --- |
| Snowball queue Keep/Skip | identity, decision, run id |
| `keepup dismiss` | identity, source (`watch` / `authorwatch` / `cites` / `search`) |
| Inbox proposals rejected | file name or DOI, reason if recorded |
| Author pack promoted for this profile | author id, host |
| `state/acronyms/` for this `-C` | token |
| `state/sr/<slug>/` when the protocol names this collection | identity, decision, reviewer |

**Acceptance.** A fixture with one skipped snowball row and one dismissed
keepup id prints both and nothing else. No network. No manager.

**Workbench.** A collapsible block on Discover for the current chip, not
a page. **Stop** if the only rows people want are already visible on the
snowball queue itself — then delete the join and keep the queue.

(after-17-claim-check)=
### Ask, only as a claim check

**Status:** roadmap. Depends on shipped Ask, not on a new model.

Ask today can cite a passage. It can also write a smooth paragraph that
hides which sentence was unsupported. The trust test is a pack that
refuses the smooth paragraph.

**Command sketch:** `paperful ask --claim-check --file DRAFT` (or a flag
on the existing `--from-file` path — pick one when implementing; do not
ship both). Scope is `-C` / the same index as Ask. For each sentence
over the `stuff` length floor:

- **supported** — one or more passages, item key, page, quote.
- **mixed** — passages that touch the topic and do not state the claim.
  The pack says so in a fixed phrase, not a generated hedge.
- **unsupported** — no passage above the retrieve threshold.

Fail closed when the index is empty (same as Ask). No sentence is
rewritten. No citation is inserted. Output:
`state/ask-claims/<stamp>/` (`paperful.claim_check.v1` + `pack.md`).
`--apply` may file a child note only in a later stage, with
`paperful.note.v1` type `claim-check`, and only if the operator passes
`--apply`. Default is the pack on disk.

**What this unlocks, in order, each allowed to stop:**

1. **Claim check** (this stage). Dogfood on one real draft extract
   (a JMLC or house-style manuscript slice under `styles/` is the
   fixture shape; a private draft is the dogfood). Acceptance: every
   supported row has a quote that occurs in the indexed chunk; a
   sentence with no hit is `unsupported`, never a guessed citation.
2. **Living brief diff**, only if (1) is actually opened. Themes,
   contested points, gaps — the [briefs buffet](#after-110-briefs-ask)
   — filed as a collection note. A second run prints added and removed
   clusters (item keys), not a rewritten essay. Disagreement between
   papers is a pair of quotes, not a verdict.
3. **Evidence table.** Columns: study design (OpenAlex `study_designs`
   or work `type` when we have them, else the literal `unspecified`),
   n, method, finding. A cell is filled only from `extract-sections`
   or a quoted passage. Anything the model adds without a quote is the
   literal `check this` and does not count as a finding. Export CSV.
4. **Figure and table pullouts.** Caption + page + file stem from the
   local PDF. No generated artwork, no graphical abstract.
5. **Question generation from summaries.** Stays deferred until (1)
   ships. It is still the item marked deferred under
   [Zotero-RAG](#zotero-rag-integration-later-question-centric-layer).

**`stuff` labels, separate and smaller.** Optional pack column
`supports` / `contrasts` / `mentions` only when a quoted span from the
hit overlaps the claim the operator can see. Similarity alone stays
unlabelled. `--apply` into Zotero and auto-insert into the manuscript
stay parked. See [`stuff`](#stuff-later-extra-citations-from-the-library).

**Nav question.** Whether Ask stays on the default nav stays open until
claim-check exists. After it exists, the test is behavioural: if
operators run claim-check from the CLI and never open `/ask`, move Ask
under Advanced and leave a link on Index. Do not move it on a hunch
before that.

(after-17-sr)=
### Systematic review (the one bigger bet)

**Status:** scaffold shipped; the bet is roadmap. Grey-literature
watching is no longer the competing annual bet — it shipped. Do not
start a second bigger bet beside this one.

What exists (`paperful/sr_cmd.py`): `sr init` writes
`state/sr/<slug>/` with title, question, and `exclude_reasons: []`.
`sr screen` appends a decision (`include` / `exclude` / `maybe`), a
reason string, and a reviewer string. `sr status` counts. There is no
queue, no reason checklist, no second-reviewer report, no PRISMA flow,
no workbench.

Interoperate with Covidence, Rayyan, and ASReview. Do not replace them.
Do not claim a recall percentage. Sits beside Wanted: screening does
not attach PDFs and does not create parents.

**SR-1 — Reasons are data.** The protocol’s `exclude_reasons` list is
what `sr screen` will accept for `exclude`. `init` can take repeated
`--reason`. A reason not on the list is exit 1. `maybe` needs no
reason. `status` prints a histogram. Acceptance: fixture protocol
rejects an off-list reason and counts two excludes of the same reason
as two.

**SR-2 — Queue from a ledger you already have.** Import identities
(not PDFs) from a snowball queue (Keep rows only), a `refs gap` pack,
or an RIS/`included.csv` file into `state/sr/<slug>/queue.jsonl` with
status `unscreened`. A column `in_library` uses the existing
fingerprint and does not write to the manager. `screen` refuses an
identity that is not on the queue unless `--allow-extra` (so a typo
does not become a silent include). Acceptance: importing the same RIS
twice does not duplicate a DOI.

**SR-3 — Two reviewers, one disk.** Reviewer stays a string, not an
account. `status` adds agreement / conflict / single-screened, matched
on identity. Conflict is a row the operator reads. Export CSV
(identity, decisions, reasons) for a tool that does dual-blind
accounts. Workbench, only after SR-2 has been used on a real queue: one
page reached from Discover Advanced, keyboard include / exclude / maybe,
reason chips from the protocol. Not on the default nav.

**SR-4 — PRISMA flow from those integers.** Snowball already emits
`summary.prisma` counts. SR adds its own counts: imported,
screened, excluded-by-reason, included, still unscreened. Render a
table, plus an optional SVG built only by placing those integers in
fixed boxes. No illustrated diagram, no model in the loop. A short
methods paragraph template with the integers filled in, for the
operator to paste. Still no recall percentage.

**SR-5 — Ranking experiment, built to be killed.** Opt-in sort of
unscreened rows by embedding similarity to the centroid of includes
minus the centroid of excludes. Requires a built `[rag]` index and at
least a documented minimum of decisions (start at 20 includes). Write
the comparison in `assessments/`: this ranking versus sort-by-cited.
If it does not win on one real review, delete the sort and keep
SR-1–4. Do not ship a default “AI screener.” This is the only
ASReview-shaped slice; the embeddings buffet does not get a second one
until this verdict exists. See
[embeddings order](#after-17-embeddings-order).

**Dogfood gate.** SR-1 and SR-2 may land without a finished review.
SR-3 and after wait until the maintainer (or one tester) has a protocol
they are actually screening. A policy or methods desk with a real
question qualifies. A synthetic queue of fifty famous DOIs does not.

**Non-goals.** Accounts and blinding, a PDF reader inside the
workbench, robot exclusion, auto-exclude from a score, replacing
Rayyan’s collaboration, pulling SR into `paperful all`.

(after-17-topics)=
### OpenAlex topics as a product

**Status:** housekeeping shipped
([OpenAlex topics](#after-110-openalex-topics)). The three opportunities
named there are still roadmap. Pin **topic IDs**. Store the display
label beside the id and treat the label as cosmetic: OpenAlex relabels.

**Topic follow.** A watch kind next to keyword watches: topic id, plus
optional type, language, and OA filter. Cursor and inbox behave like
`authorwatch` (new works since cursor; `exists` stays out). Start the
watch from a snapshot dated on or after 14 Oct 2026, or from the live
API. Do not trust a topic assignment cached from a pre-October snapshot.
`snowball watch rebaseline` remains the flood valve when labels move.

**Library gap map.** For `-C`, resolve topic ids for DOIs you hold
(OpenAlex, budget-capped, cached under `state/`). Compare to a second
set the operator names: a saved snowball seed’s topic mix, or the
topics on works that cite the collection (`cites`, already a keepup
source). Report **thin** (you hold at most N, default 2) and **absent**
(in the comparison set, zero in the collection). Report only. Group
label `no topic` is a real bucket; do not guess a topic from the title.

This map is the collection picture that does not need embeddings. A
cluster view of the embedding space has to beat this report on the same
collection before anyone builds it.

**Grouping.** `since` and Wanted may group rows by topic label when the
id is already cached. Missing id → `no topic`. No extra API call on
the Wanted page render; a stale cache is labelled with the cache date
`doctor` already knows how to warn about.

**Acceptance.** Tests use `tests/fixtures/openalex_topics/`. CI does not
call the live topic endpoint. A gap-map fixture with three held DOIs
and one citing work in an unheld topic yields that topic under absent.

(after-17-embeddings-order)=
### Embeddings: one spike, then a baseline to beat

The [EmbeddingGemma 2](#embeddinggemma-2-local-embeddings) text spike
stays the only model experiment. Defaults stay `nomic-embed-text` /
`bge-m3`. sqlite-vec is not a silent swap: measure LanceDB size and
startup on a real library first, and open that bet only if the
measurement is the problem.

Consumers, in order, each with a baseline written down before the code:

| Consumer | Baseline it has to beat | Kill condition |
| --- | --- | --- |
| **Papers like this** (nearest chunks in *this* library for one item) | Shared references already computable from citation overlap | Operators prefer the overlap list on a 20-item dogfood |
| **Semantic snowball seed** (nearest-neighbour phrase → one OpenAlex query on an existing profile) | The keyword the operator would have typed | The hop’s Keep rate is not higher on one profile |
| **SR-5** | Sort by cited-count | Loses on the one real review |

Collection cluster UI waits on the gap map above, not the other way
around. Nightly “embed the library and query OpenAlex while you sleep”
stays out: it is an unattended discovery loop, and `keepup` plus topic
follow cover the scheduled-by-the-operator case without a second agent.

(after-17-ledger-finish)=
### Finish the ledger (small, after the habit)

These are parked holes with a shape. None of them outranks `since` or
SR-1. Pick one when a desk hits it.

**Playbook health.** `paperful playbooks health` (report). For each row
in `learned.toml`: win count, last win, consecutive misses, last HTTP
status when we have it. `doctor` ambers when the miss streak is at
least `[playbooks].stale_after` (default 5) or `last_win` is older than
`[playbooks].stale_days` (default 180). `playbooks retire` marks the
row disabled and keeps it in the file. No automatic retire. If there
is no learned file, exit 0 with “no learned playbooks.” Dogfood is
whatever `state/` already accumulated on ocean grey hosts.

**Wrong-paper queue.** `lint` already raises `pdf_identity_mismatch`.
The missing piece is a disposition: keep, or move the bytes to
`state/quarantine/<stamp>/` and drop the attach pointer, with a witness.
`--apply` required. Never unlink the only copy. False positive is a
recorded disposition so the same pair does not return next lint. Group
libraries: report only.

**Orphan files.** List mirror files (and, when the operator passes a
path, Zotero `storage/` files) that no item record references. Default
report. `--apply` **moves** them to `state/trash/<stamp>/`. A second
command, `paperful trash empty --older-than 30d --apply`, unlinks.
Group libraries refused. This is not a startup daemon.

**License gate.** Stamps already exist (`license`, `oa_status`,
`version`). The gate is an opt-in allowlist in config. When it is on,
`run` emits `license_blocked` and does not write bytes that fall
outside it. Default off, so today’s libraries do not change behaviour.
When it ships, add the allowlist shape to
[legal-privacy](legal-privacy.md). It is not a compliance product and
not a redistributor.

**Annotation mirror.** Zotero stays the reader. Phase 1: on `snapshot`
(or `paperful annotations mirror`), write
`out/<item>/annotations.json` (`paperful.annotations.v1`: text, page,
color, comment) from the backend’s annotation read. Read-only. Phase 2:
`[rag].prefer_highlights` (default off) lets ingest mark those passages
so Ask can say the citation was one you highlighted. Phase 3: export
only the highlighted passages as a pack. Writing highlights back,
tablet sync, and Mendeley/EndNote annotation parity stay out until a
tester asks. Group libraries stay out of phase 1.

**Author folders and tablet send/get** stay parked. Collections already
express “whose papers”; a sync product is a different job
([two folders](#after-17-two-folders)).

(after-17-siblings)=
### Siblings of a paper you hold

**Status:** roadmap. The parked line “SI / dataset / code siblings” gets
this shape and no wider one.

`paperful siblings -C` (dry-run) looks at links already on the mirrored
PDF or its landing metadata. It may record a sibling only when the host
is on an allowlist: Zenodo, OSF, Dryad, Figshare, a GitHub release, or
a Dataverse host the operator added. License is copied when that host’s
API returns one. `--apply` downloads into `out/<item>/siblings/` under
a byte cap and does **not** attach into Zotero unless `--attach` is
also passed (second flag, on purpose). Stamp `sibling:zenodo` (or the
host’s short name). Refuse generic cloud drives, personal blogs, and
any pirate host. Cap requests per run.

**Acceptance.** A fixture PDF whose only outbound link is a Zenodo
record yields one row; a fixture whose only link is a file host not on
the list yields zero rows and exit 0. **Stop** if a real `-C` dogfood
finds nothing worth keeping — the verb can exist as report-only forever.

(after-17-two-folders)=
### Two folders, no accounts

Collaboration stays “shared disk,” as in
[Maybe later §8](#maybe-later). Thicken the mechanism; do not add a
server.

- **`paperful mirror diff DIR`** compares this `out/` to another tree
  (a Syncthing copy, a backup, a colleague’s snapshot you were handed).
  Rows: item key, PDF added or hash changed, `record.json` hash
  changed, notes added. No merge button in the first slice. The
  operator uses `restore` on the keys they choose, dry-run first.
- **Attach clash.** `attach` and the apply path of `run` take an
  exclusive file `state/locks/<item-key>` (host, pid, timestamp). A
  lock older than `[attach].lock_hours` (default 12) is stale and may
  be replaced; the replacement is printed. This matters only after two
  processes share one `state/` via Syncthing or similar. Until someone
  reports a double attach, a test with two lock files is enough — do
  not build a fetch node.

(after-17-desks)=
### Field desks (proof, not products)

A desk is a collection the maintainer already uses, plus the playbooks
and one watch that belong to it. A desk graduates a feature when a
short note in `docs/` (or a local `assessments/` file) says the
acceptance line held on that collection. No suite page, no extra
install.

| Desk | Already in tree | Next proof |
| --- | --- | --- |
| Ocean / BBNJ | [bbnj-author-lanes](bbnj-author-lanes.md), grey packs, `author_site`, `authorwatch` | `since` and the topic gap map on `ocean/BBNJ` |
| Policy grey | `search` / `search watch`, RFMO and UN-doc playbooks | Playbook health on learned rows, or `siblings` if the holdings actually link out |
| Journal desk | Shipped example packs `styles/JMLC`, `styles/JCP`, `styles/MarinePolicy`; `critique` | Claim-check on one manuscript extract. Not a new style product |

Do not open a fourth desk to justify a feature.

(after-17-platform-residuals)=
### Platform residuals (named so they are not forgotten)

From the 1.7 log. These are not the habit lane. Pull one in when the
next tag needs it.

| Residual | Done looks like |
| --- | --- |
| Coverage 85 | A measured run at or above 85 **without** lowering the bar by deleting tests. Until then the gate stays 82 |
| Non-ledger `write_text` | Sweep report/export writers onto the atomic helper only where a torn file would lie to the operator. Not all ~150 sites |
| Kill-9 resume | One test that kills a `run` and a `sync` mid-write and asserts the next start matches the fsio contract. Not a chaos suite |
| Perf budgets | CI-tracked ceilings for `sync`, `gaps`, and `lint` on the synthetic bench, beside the mirror-scan numbers that exist today |
| Publish attestations | Turn `attestations` back on when the Rekor workaround is obsolete. SBOM from CI stays either way |
| Python 3.10 | Announce in a release note, then bump `requires-python`. Not inside an unrelated feature PR |
| Keyring, signed bundle | Stay closed unless a desktop-only tester asks in writing. Asking does not by itself reopen the decision |

(after-17-ci-rebuild)=
### CI gate, cut back to smoke

The 15-cell suite (Ubuntu, macOS, and Windows, each on Python 3.10–3.14)
plus lint, audit, socket, fresh-install, browser, and docker sat in the
queue, and the Windows cells failed on path spelling and encoding. The
live GitHub gate is one job: Ubuntu, Python 3.12, `uv run pytest -m smoke`
(CLI version, shell pages, workbench command paths), with a ten-minute cap.

`uv run pytest` is still the local suite. The coverage `fail_under` of 82
stays local. The coverage-badge workflow does nothing until a suite job
uploads `coverage-json` again.

Bring jobs back one at a time, and only after the previous step has been
green on `main` without sitting in a queue. Do not restore the 15-cell
matrix in one change.

| Step | Job | What it proves |
| --- | --- | --- |
| 0 (now) | smoke | The package imports, `paperful` reports its version, and the workbench routes boot |
| 1 | lint | `ruff`, format, and `mypy` on Ubuntu 3.12 |
| 2 | suite, Ubuntu 3.12 | Full offline pytest, and the coverage artifact the badge reads |
| 3 | socket | That same suite with sockets disabled |
| 4 | fresh-install | An isolated `.[serve]` install: `doctor` exits 2 without Zotero, then `/health` answers |
| 5 | docker | The light image, `doctor` exits 2, no live Zotero |
| 6 | browser | The Chromium workbench checks |
| 7 | audit | `pip-audit` and the SBOM artifact |
| 8 | Ubuntu 3.10, 3.11, 3.13, 3.14 | One extra Python per change |
| 9 | macOS 3.12 | One non-Linux OS |
| 10 | Windows 3.12, then the other Pythons | Last. Path spelling, case-only renames, and `tomllib` on 3.10 already failed this lane |

(after-17-workbench)=
### Workbench and docs residuals

The 1.8.0 hardening wave covers security headers, orphaned jobs,
cached counts, layout, Wanted and Discover structure, Preview-gated
Apply, and an opt-in browser test lane. Leave that wave’s bugs in its
own fixes.

Still open, and small:

- **First 10 minutes.** One page, GUI labels only: Wanted, Held, Grab,
  Attach, the `out/` folder. Steps: open the workbench, see an empty or
  real Wanted, run Preview, understand that Attach is a separate button,
  find `out/` on disk. No Scholar, no Sci-Hub, no model. Link it from
  [walkthroughs](walkthroughs.md) and the README.
- **One full-fetch narrative.** A single extra walkthrough for EZProxy
  re-login, handoff, and inbox — the path [Documentation](#documentation-thicken)
  already says is missing. Screenshot callouts on the dry-run table and
  on a provenance line in Zotero, recaptured with
  `scripts/docs/capture_workbench.py`.
- **`stuff --apply`** stays off the workbench until the pack column
  labels above exist and a tester asks for the note.

(after-17-order)=
### One possible order

Not a calendar. Each line can be the last line.

1. **`paperful since`** — holdings that changed meaning, and misses that
   healed. CLI pack, fixture, four-week dogfood. Workbench block only
   if the packs get opened.
2. **`refs gap` memory** — new / still missing / now owned.
3. **`paperful decisions -C`** — read-only join. Drop it if Discover
   already shows the only rows that matter.
4. **Claim check** — then, only if used, brief diff and the evidence
   table.
5. **SR-1 and SR-2** — reasons and a queue. Stop until a real review
   exists; then SR-3 and the counts diagram.
6. **Topic follow and gap map** — ids now; do not wait for 13 Jan 2027
   to store ids. Rebaseline when the live labels move.
7. **Playbook health** — cheap, and it tells the policy desk whether
   learned rows are rotting.
8. **One ledger-finish item** from the desk that has the pain
   (quarantine, orphans, annotations, siblings, or the EmbeddingGemma
   spike). Not all of them.

(after-17-questions)=
### Open questions (live)

- After four weekly `since` packs, is the diff a habit or noise?
- Once claim-check exists, does anyone still want `/ask` on the default
  nav?
- Is there a real systematic review this year, or do SR-1 and SR-2 sit
  until there is one?
- When is the Python 3.10 drop announced?

Older questions, with the answers we have, stay under
[Open questions](#after-110-open-questions) so the history is readable.

(after-110-buffet-by-area)=
## After 1.1.0 (area index)

Encyclopaedia of jobs, not the live order. For what to build next, read
[After 1.7](#after-17-live-map) first. Merged 16 Oct 2026 from the
post-v1 options compile (checked against `main` at `ae21bfb`). Many
rows below have since shipped; the status lines say so. **Include the
remainder on the map; pick from the live order.**

**Working stance (October 2026, historical):**

1. **Ship 1.1.1** (scoping, ticks, Attach guard, version single-source, copy).
   Done.
2. **Keep Wanted excellent** as the one main lane (foundation shipped).
   That lane is no longer the thing blocking the next bet. The weekly-habit
   question is now [the holdings diff](#after-17-habit).

Paperful knows what you *own*, which feed readers and discovery tools do not.
The open question behind the longer bets: what would make a researcher open
Paperful every week, not just once to fill gaps?

(after-110-facts)=
### Facts settled against 1.1.0

- 1.1.0 is tagged and on PyPI; trusted publishing (`publish.yml`) exists.
- Version: single source via `importlib.metadata` / `pyproject.toml` (1.9.2).
- Attach is **manual by default** (`[ui].attach_mode`); Grab does not write to
  Zotero unless Settings is automatic.
- **1.1.1 closed P0s:** Grab-selected `item_keys`, Held hand-ticks, Attach at
  zero disabled, attach count honesty, first-hour copy.
- **Ask** is on the default nav (third after Wanted and Discover); it does
  not need Advanced. Whether it *stays* there is an [open
  question](#after-110-open-questions).
- Install docs are pinned to `v1.9.2` (README, `docs/docker.md`,
  `website/index.html`). Recheck every paperful.app claim before launch.

(after-110-1-1-1)=
### 1.1.1 (stop-ship) — shipped

Landed in tree (tag when ready). Implementation notes:
[docs/plans/1.1.1-stop-ship.md](plans/1.1.1-stop-ship.md). User-facing copy:
[gui.md](gui.md), [first-fill.md](first-fill.md).

- Grab-selected `item_keys`, preview token keys, tests.
- Held hand-ticks; main Attach skips mismatch/short (Advanced overrides).
- Attach disabled at zero; attach count matches pending writes.
- `__version__` from package metadata; bind `127.0.0.1` tested.
- First-hour copy and Settings **After Grab** hidden until first Attach.
- Install pins: `v1.1.1` (README, docker, website). Recheck paperful.app
  before launch gates.

(after-110-wanted)=
### Wanted (main lane)

**Foundation shipped** (stamps, miss reasons, hand-ticks, report cards,
Waiting→add). It is what the site, share card, and paid cleaning report
(`doi_match` only) already promise. Residual polish stays here; bigger
workbench bets wait until this lane stays boring.

- Stamps you can trust: a **found** stamp only on `doi_match` cards, a
  **check** stamp on mismatches, no “% complete”. The paid report reuses the
  same cards, so “N found” equals the number of **Found** stamps.
- Hand-ticks (Missing and Held). Attach enables only for attachable ticks
  (main Attach still skips mismatch/short unless Advanced).
- A one-line reason for each miss (including **not_fetched** when never run).
- Snowball / digest **kept** items feed Wanted via **Waiting from Discover**
  (Preview add → Apply → Missing); not a second fill desk.

Workbench layers after this lane stays boring, not instead of it:

| Option | For | Against | When |
| --- | --- | --- | --- |
| **A. Wanted excellent** | Already the public promise | Less flashy | **Shipped** (bolster as needed) |
| B. Repair / Mirror GUI (workbench vision) | Library hygiene is a real pain | More places that write to the library, so more trust copy | After A is boring |
| C. Ask / Index depth | Differentiating if it works | Weakest trust story; usage unknown | Keep optional, last |

(after-110-discovery)=
### Discovery and sources

Paperful’s angle vs ResearchRabbit / Connected Papers / Litmaps: those tools
do not touch your library, and Zotero plugins do not discover. The join is
the product. Keyword search is crowded — keep it a thin layer, not a
headline.

- **Snowball done well.** Start from a paper’s references and citations via
  OpenAlex, drop anything already in the library, rank, say why each was
  suggested, then feed results into Wanted. See [Snowball](#snowball) and
  [Snowballing and review methods](#after-110-snowball-review).
- **ORCID / author harvest** is cheap but niche; keep, do not headline.
- **OSF Preprints** as a thin DOI source: *test* by counting recent misses
  with an OSF location before building.
- **Patents / trial registries** (Edison Literature indexes trials and
  patents): *test* the same way — how many Wanted misses or precedent
  questions would have been a ClinicalTrials.gov or patent-family hit —
  before any ingest lane. Detail:
  [Hosted AI scientists](#after-110-edison-scientific).
- **Author homepages:** promote ORCID / OpenAlex researcher URLs to a lookup
  at miss time (*keep*). Add template parsers (al-folio, Hugo Academic) only
  if winning author sites cluster on them (*test*). Co-author site preflight
  is already shipped — [Snowball phase 7](#snowball).
- Leave Twenty CRM as it is (shipped; not a growth bet).

(after-110-keeping-up)=
### Keeping up (digest, watches, alert loop)

**Shipped (CLI):** [`keepup`](keepup.md) — alert loop
(`watch` / `authorwatch` / `cites` → digest → apply → `ingested.md`) with
configurable `interval_days` (default 7). Also `snowball watch apply` and
`authorwatch digest`. Still **no** built-in scheduler and **no** email;
operators cron `keepup run`.

Pieces underneath: `watch.py`, `digest.py`, `briefing.py`;
[Frontier digest](#frontier-digest-later-watch--external-ingest) and
[author watch](#author-watch-lists-later-people-you-follow--their-papers).

- **Alert loop** — shipped as `paperful keepup` (+ standalone watch/authorwatch apply).
- **Weekly digest per Zotero collection.** Shipped as keepup `--source cites`
  (why line `cites N of your papers`); combine with `--watch` / `--authorwatch`
  on one job. Dismiss/mute via `keepup dismiss`. Discover one-click UX and
  “cited by your collection” (`refs`) remain buffet polish.
- **Infra variant:** a scheduled nightly or weekly job uses the library’s
  own embeddings to query OpenAlex and preprint servers, optional local-model
  summaries, lands as a Zotero note or email.
- Add-ons: retractions and corrections on items you already hold, worded as
  “flags to review”, never “detects” (`paperful screen` is the existing
  lookup); preprint-to-published linking (`paperful versions` is the
  existing merge); a monthly “living review” re-run of a saved snowball that
  flags when a new cluster appears. The weekly join of those signals is
  [`paperful since`](#after-17-habit), not a second poller.

(after-110-research-integrity-paperguard)=
### Research integrity forensics ([PaperGuard](https://github.com/exergyleizhou-ux/PaperGuard))

**Last reviewed:** 2026-10-26 against PaperGuard **2.17.0** (public README,
[ROADMAP](https://github.com/exergyleizhou-ux/PaperGuard/blob/main/ROADMAP.md),
PyPI `paperguard`). PaperGuard is a **sibling OSS tool**, not a dependency.
Paperful’s lane stays **library + mirror + fetch + light manuscript packs**;
PaperGuard stays **tabular / statistical / image / metadata anomaly screening**
on files you point at.

**Epistemic overlap (keep aligned).** Both projects flag **anomalies to
investigate**, never misconduct verdicts. PaperGuard reports severity tiers,
BH–FDR across findings, and mandatory `innocent_explanations` per hit; it
refuses “fraud” vocabulary in reports. Paperful uses the same copy pattern on
[`screen`](screen.md) and [`critique`](critique.md) (`pps_*`, overlap,
`cited_retracted`). Do not merge the tools into one “integrity score.”

**What PaperGuard ships that Paperful does not (and should not re-vendor).**

| Area | PaperGuard (indicative) | Paperful today |
| --- | --- | --- |
| **Spreadsheet / table fabrication** | Terminal-digit tests (Mosimann; Geng 0/5 preference), Benford, constant-diff/ratio columns, decimal consistency, implausible sentinels | No — manuscripts are prose/PDF, not lab notebooks |
| **Stats recomputation** | Full **statcheck** (t/F/χ²/r/z/Q; one- and two-tailed); **GRIM / GRIMMER / SPRITE**; **TIVA**; **P-curve**; decision-reversal flags | [`critique`](critique.md): stdlib **subset** (`statcheck_p_mismatch`, `grim_impossible_mean`, `p_without_n`) — no scipy/R, not a statcheck port |
| **RCT / trials** | Carlisle baseline imbalance; ClinicalTrials.gov outcome consistency (T2); trial-ID extraction (NCT, ISRCTN, …) | Critique **checklist mentions** only (`checklist_prisma` / `consort`) |
| **Image forensics** | Cross-image pHash (F1), intra-image ORB+RANSAC (F2), splice/copy-move (F3/F6), persistent cross-paper pHash store (F4), EXIF timelines (G1) | No — optional figure **pullouts** in briefs are captions + pages, not forensics |
| **Text / mill signals** | Corpus similarity (T1), 150+ tortured phrases (T4), stylometry (T5), AI-text stack (T6–T9, opt-in `--ml-check`), paper-mill **citation-graph** fingerprints (M1) | [`screen`](screen.md): PPS CSV fingerprints + retraction/PubPeer; critique repeats tortured phrases on the **draft extract** |
| **Cross-corpus checks** | Retraction Watch + CrossRef, PubPeer, ORI CSV, OpenAlex DOI metadata | Same **retraction / EoC** cache for `screen` and **cited** works in critique |
| **Operator surface** | `paperguard scan`, batch, HTML/JSON, plugin detectors, optional multi-tenant Web UI, LLM `explain` | `screen` / `critique` on collection or `--file`; mirror paths under `out/` |

**What Paperful already covers without PaperGuard.** Collection-wide **PPS +
retraction** on holdings (`screen`); **pre-submission reading packs**
(`critique`: structure, refs, floats, ethics mentions, library overlap, optional
Vale and composable review lanes — reviewers, MARG-S, ScholarPeer-inspired
`context` / `context-web`; not vendored). That is “does this draft hang together and cite retracted
works?” — not “are these CSV means GRIM-impossible?”

**Buffet — integrate, don’t duplicate (ship in order; each stage can stop):**

1. **Docs + comparison routing (now).** Short-answer row in
   [comparison.md](comparison.md); vendor notes in
   [comparison reference](comparison-reference.md#paperguard). Critique
   `statcheck_p_mismatch` footer should point heavy stats/table jobs at
   PaperGuard, not promise parity.
2. **Mirror hand-off (test).** For a mirrored item, document a stable recipe:
   export supplementary CSV/XLSX from `out/…/attachments/` (or operator path)
   → `paperguard scan -f …` → keep JSON beside the item folder. No PyPI
   dependency until a tester asks for one-command glue.
3. **`paperful critique --forensics` (shipped).** Optional subprocess wrapper:
   run PaperGuard on `--file` or on the item PDF plus sibling csv/xlsx/xls;
   ingest findings as a **separate pack section** (`suggested` lane, external
   tool attribution). Fail closed if `paperguard` is not on `PATH`. Never fold
   PaperGuard severities into a single Paperful grade.
4. **Collection batch (roadmap, after `screen` proves boring).**
   `paperful screen --supplements` or a sibling verb: for items with tagged
   supplementary data, batch-invoke PaperGuard in report-only mode; write
   `state/runs/<stamp>-forensics.json` (schema TBD). Still no auto-tag of
   misconduct — optional `--apply` might only add a child note “forensics pack
   available” with a path, same honesty as `screen --apply`.
5. **Workbench (roadmap).** Advanced Critique panel: “Open forensics report”
   when a sidecar JSON exists; link out to PaperGuard HTML export. Not on the
   default nav.
6. **MCP (roadmap).** Read-only `forensics_status` for agents: “last
   PaperGuard scan stamp + path” on an item key — no remote scan from MCP.

**Explicit non-goals (Paperful side).** Porting 41 detectors; hosting PaperGuard’s
Web UI; training T9-style classifiers inside Paperful; image-duplication store
as a default background job on every library; replacing institutional integrity
offices or journal editors. PaperGuard’s roadmap items (full Cabanac PDCN graph,
ML western-blot classifier, Redis-backed Web UI cache) stay **their** bets.

**Borrow only where cheap and honest.**

- **Convergence framing** — when multiple independent checker families fire,
  critique pack prose can say “multiple clusters — investigate” (PaperGuard’s
  combiner pattern), without importing their severity math.
- **Recall discipline** — PaperGuard documents cohort mismatch (e.g. OA PDF
  text vs inline NHST; vector figures vs raster supplements). Mirror the same
  honesty in critique overlap and screen copy (“supplementary CSV only”, “PDF
  text layer required”).
- **Keeping-up hook** — when `keepup` or `screen` surfaces a new retraction,
  optional footnote: “re-run file forensics if you relied on supplementary
  tables from this item” (operator checklist, not automated).
- **Binoculars Falcon load (critique `--ai-model`, housekeeping).** Upstream
  `binoculars` still loads `tiiuae/falcon-7b` / `falcon-7b-instruct` with
  `trust_remote_code=True`, which prints Hugging Face’s legacy-Falcon warning
  (“fully ported into transformers … load without trust_remote_code”). Fix when
  convenient: pin a transformers release with native Falcon and load without
  remote code (prefer an upstream Binoculars PR; thin Paperful wrapper only if
  upstream stalls). Keep scoring Hugging Face-offline; never treat the score as
  authorship proof. See [critique.md](critique.md) (optional AI-text extra).

Factory-stage context: PaperGuard strengthens **screen / audit** on **files**;
Paperful 1.x **screen** is **metadata + PPS on PDFs you hold**. See
[paper factory stages](comparison-reference.md#paper-factory-stages).

(after-110-openalex-topics)=
### OpenAlex topics (January 2027)

**No breakage on 13 Jan 2027.** Paperful never requests topics: the `SELECT`
in `paperful/snowball/openalex.py` lists no `topics` field. Grep finds no
`primary_topic`, `concepts`, topic-ID filters, or `/text/topics` in
`paperful/`, `tests/`, or `docs/`. The cutoff only retires the old classifier
on OpenAlex’s `/text/topics?version=1` endpoint. Works already switched to
the new topic assignments in early October 2026. Users need no notice.

Cheap housekeeping (can sit alongside 1.1.x). **Shipped (unreleased):** run
stamp (`openalex_run_date`, `openalex_topic_epoch`), `snowball watch
rebaseline`, the stale 12% figure dropped, `doctor` snapshot warning via
`[openalex_store].snapshot_date`, and a frozen before/after scoring fixture
(`tests/fixtures/openalex_topics/`). Original list:

- Stamp each snowball run with the OpenAlex date — pre-October runs cannot
  be reproduced (keywords are now linked to topics; OpenAlex reports
  keyword accuracy rising from 44% to 91%, so hops will return different,
  probably better, neighbours).
- Reset each keyword watch’s baseline once, so reassigned works do not
  arrive as a flood of “new” papers.
- Re-measure or drop the stale “about 12% of works have no topic and
  therefore no keywords” figure (`config.example.toml`, `docs/snowball.md`).
- Local snapshot users: OpenAlex says the change does not touch
  `updated_date`, so incremental syncs miss it. Users of `local_openalex.py`
  must reload fully from the 14 Oct 2026 snapshot. Document this; have
  `doctor` warn about older snapshots. Park **2C** (full search / `http`)
  until someone asks — [OpenAlex snapshot store](#snowball).
- Add a before/after snapshot test for keyword-based scoring.

Opportunity (pin to **topic IDs**, never to cached assignments). Specified
as watches and a gap map in [After 1.7](#after-17-topics):

- **Topic follow:** topic-native watches, filtered by type, language, and
  OA status.
- **Library gap map:** which topics your library covers thinly.
- **Grouping** Wanted and digests by subfield.

(after-110-briefs-ask)=
### Summaries, briefs, and Ask

Depends on solving Ask’s trust problem ([Wanted table](#after-110-wanted)).
Ask stays optional; whether it stays third on the default nav is open.

- **Per-collection grounded brief:** themes, what is contested, and gaps.
  Every sentence cites a paper you hold, with a click through to the
  passage. Filed in Zotero as a starred note (`* Briefing — …`). Updates
  incrementally and shows a diff of what changed (new clusters, papers that
  shifted the picture). Flags disagreements between papers.
- **Summaries with receipts:** each summary quotes the passages it relied
  on and is stored as a Zotero child note marked as machine-written. Local
  by default (Ollama); optional bring-your-own-key cloud. Turns Ask into
  the place you check claims, rather than a chat toy.
- Stretch: evidence-table export (study type, n, method, finding), each
  cell tied to a passage and marked “check this” when unsure; local claim
  tracking that sorts citing papers into supporting, contrasting, or just
  mentioning. Study-type seed for that table: Discover citation-map
  literature categories from OpenAlex `study_designs` and work `type` (see
  [Citation map](snowball.md#citation-map)).
- **Borrow from hosted literature agents** (Edison Scientific’s Literature /
  PaperQA line — [Hosted AI scientists](#after-110-edison-scientific)), still
  over **your** PDFs, never a 175M-paper cloud index:
  - A **conflicting-evidence** `synthesize` layout (already adjacent to
    `gaps` and “what is contested”) that names the camps, the methods that
    disagree, and the passages — not a single smoothed narrative. Ask
    `--focus conflict` is **shipped**; synthesize `--layout conflict` /
    `review` is **shipped** (Ask RAG vs summary-note briefs stay separate).
  - A **review-shaped** synthesize layout (question → methods in the set →
    findings → limits), closer to Edison’s “report with abstract and
    conclusions” than a chat dump. Same note provenance as today.
  - **Figure / table pullouts** from local PDFs into the brief (caption +
    page + file stem). Diagram *generation* stays out; we already hold the
    PDFs.
  - Rank or label retrieved passages with **study design / work type**
    (OpenAlex fields we already expose on the citation map) and, when the
    item has it, venue — never a proprietary “journal quality” score.
- Existing RAG / Ask / Briefs surface: [Zotero-RAG
  integration](#zotero-rag-integration-later-question-centric-layer),
  [GUI](#gui). Question generation from summaries is still deferred there.

(after-110-embeddings)=
### Local embeddings

Already in place: RAG supports Ollama embeddings (`nomic-embed-text`
default, `bge-m3` for multilingual), one index per model — [rag.md](rag.md).
Local-first and private by default; cloud models stay opt-in.

- **Benchmark first.** Add EmbeddingGemma as a tested preset. Compare it
  against nomic and bge-m3 on a real Zotero library, scoring recall@10 on
  held-out “which paper said X” questions. Publishing the numbers doubles
  as marketing. Key the index by model and dimension. Detail and spike
  order: [EmbeddingGemma 2](#embeddinggemma-2-local-embeddings).
- **Infra stack:** EmbeddingGemma (~300M, laptop CPU) stored with
  sqlite-vec as a single local file next to the Zotero data. No cloud, no
  API key. (Today’s RAG index is LanceDB; sqlite-vec is an alternative
  storage bet, not a silent swap.)
- Uses beyond chat, in an order with a baseline to beat:
  [embeddings](#after-17-embeddings-order). “Papers like this” from your own
  library; duplicate and near-duplicate detection for library hygiene; a
  collection map (only after the topic gap map loses on the same
  collection); screening that learns from accept/reject decisions
  (the killable SR-5 experiment, not a second product); semantic snowball,
  where a nearest-neighbour phrase seeds one OpenAlex query.

(after-110-snowball-review)=
### Snowballing and review methods

[SnowBallSLR](https://github.com/s-matysik/SnowBallSLR) is a reference
design, not a dependency: MIT, one author, young (v1.0.2, not on PyPI).
Deterministic, saturation-aware backward and forward snowballing; five
stopping rules with methods-section rationales; capture–recapture recall
estimates; content-addressed response cache plus `verify --refresh` to
classify drift; PRISMA counts/diagrams, `included.csv`, RIS. It does not
screen (labels come from outside) and does not retrieve full text.

Paperful grows libraries and keeps them current, with a path to write into
Zotero. SnowBallSLR is a rigorous search stage. They overlap on citation
chasing and complement each other everywhere else.

**Borrow (do not vendor):**

- A **stopping rule** (`marginal_yield` over Keep/Skip) instead of fixed
  hop caps. **Shipped, off by default** (`[snowball].stop_rule`, per-run
  flags / profile / Discover). One hop, then Keep/Skip, then
  `snowball continue`. `asymptotic_coverage`, `budget`, and `any` are
  included. Hop caps stay as ceilings. No recall percentage.
- A **response-hash cache with drift classification** for watches — **shipped**
  (`responses.json`, `watch_drift` on `snowball watch run`; `--refresh`
  rewrites the cache and skips the last-run date cursor). Tells a genuinely
  new paper apart from a reassigned or merged ID (matters for
  [OpenAlex topics](#after-110-openalex-topics)). Paperful still does not
  schedule watches.
- **PRISMA-style counts** (identified, screened, kept, added) in the run
  report — **shipped** as additive `summary.prisma` on snowball queues,
  apply, and watch run reports. Not a frozen `RUN_REPORT_SUMMARY_KEYS`
  member. Counts only; no recall percentage.

**Interoperate:** export a Discover queue as SnowBallSLR seeds or labels;
import `included.csv` / RIS into Wanted. Reviewers do the rigorous chase
there; Paperful does PDFs and Zotero. Writing to the author is cheap.

**Recall estimate:** treat as an internal experiment only. SnowBallSLR’s
own validation reports estimator undercoverage of 0–17% and calls the
estimate advisory. Do not headline “we estimate you’ve found ~85%” or put
any percentage in copy until it has been validated on real reviews.

Systematic-review screening is the bigger bet, specified outside this lane
([After 1.7](#after-17-sr)). A review UI bolted onto the snowball queue
stays parked; if a screen page is built, it hangs off Discover Advanced.
The Discover citation map is the
queue canvas (year × citations), not a corpus browser: Wave 1 hardened
edges / Keep / offline D3; Wave 2 added triage, year scrubber, path,
library halo, and watch delta. Literature categories (OpenAlex
`study_designs`) and in-map library actions (add / Find PDF / trash /
tags) sit on that canvas — [Citation map](snowball.md#citation-map).

(after-110-bigger-bets)=
### Bigger bets (pick at most one a year)

**Status:** grey-literature watching shipped. Systematic review is the
remaining annual bet, and it now has stages, stop lines, and a scaffold —
[After 1.7](#after-17-sr). Do not run a second bet beside it. The bullets
below stay as the original brief.

- **Systematic-review mode.** Guided snowball rounds, include/exclude
  screening with reasons, PRISMA **counts** (then official PRISMA flow from
  those counts — not an AI-illustrated diagram), a reproducible run file.
  Interop with Covidence/Rayyan/ASReview rather than replacing them. Sits
  *alongside* Wanted, not in place of it. Audience: librarians and
  Cochrane-style teams (grant money, real pain). Do not claim Elicit-like
  SR recall; independent 2025 work put that UI far below traditional search.
  Scaffold in tree: `paperful sr init|screen|status`.
- **Policy and grey-literature watchers.** BBNJ and RFMO work (for example
  SPRFMO SC14 reports) lives outside DOIs. **`paperful search` + Discover Web
  shipped** (SearXNG query → ranked PDF/landing hits → metadata parents).
  **`search watch` shipped** (save / run / apply, URL seen set, `--interval-days`
  like keepup; Discover Web can save and run). Paperful still does not
  schedule — cron `search watch run`. Grey playbooks fetch; search finds URLs.
- **Paperful as the local literature back end for AI assistants**, building
  on `paperful/mcp_server.py`: “your assistant reads your library, not the
  open web.” MCP read tools are shipped
  ([Literature-discovery complement](#literature-discovery-complement-waves)).
  Named **job-shaped** read tools (`ask` vs novelty/`precedent` vs `refs_gap`)
  are the Edison-client lesson — same envelope, still no `--apply` on MCP.
  Do **not** take the other Edison bet: a hosted Kosmos-class loop that
  reads 1,500 papers and runs analysis code for hours
  ([Hosted AI scientists](#after-110-edison-scientific)).
- **Shared lab library.** Needs authentication, so later. Aligns with
  [Collaboration without SaaS](#maybe-later) (Syncthing/git, not tenancy).

(after-110-edison-scientific)=
### Hosted AI scientists (Edison Scientific)

[Edison Scientific](https://docs.edisonscientific.com/) is the commercial
spinout of FutureHouse. Public docs (reviewed 2026-10-26) describe a
**hosted** R&D platform at platform.edisonscientific.com: specialised agents
over a large public corpus plus, for some jobs, uploaded datasets. Academic
free tier; paid rate limits. Feature lists below are positioning from those
docs, not a paid pilot.

| Agent (docs name) | What they claim | Paperful analogue today |
| --- | --- | --- |
| **Literature** (PaperQA3; `JobNames.LITERATURE` / `LITERATURE_HIGH`) | Cited answers and deep reviews over **175M+** papers, trials, and patents; citation graph, journal quality, clinical-trial structure; conflicting-evidence synthesis; diagrams / figure pullouts; follow-up via `continued_job_id` | `ask` / `synthesize` / `rag` over **your** mirror; OpenAlex hops on snowball; Ask `--thread`. No patents index, no trial registry, no 175M full-text |
| **Precedent** (formerly Has Anyone) | “Has this been tried?” novelty / gap search across fields | `paperful precedent` (held vs `public-metadata-only`; never “nobody has done this”). `refs gap` / coverage / similar hops remain adjacent |
| **Kosmos** | Autonomous scientist: objective + datasets → parallel literature + analysis agents sharing a structured **world model**; ~1,500 papers and ~42k lines of code per run; up to ~12h; every claim traces to code or a passage; publication-ready figures. **Not on the public API** | None. Run witness + typed notes + RAG citations are the audit trail we have. No code-execution scientist |
| **Analysis** | Flow cytometry, RNA-seq, stats, publication figures from **experimental** files | Out of jobs. Mirror holds PDFs, not assay pipelines |
| **Molecules** (Phoenix / ChemCrow line) | SMILES/CAS/IUPAC → ADMET, retrosynthesis, ChEMBL, safety | Out of jobs |
| **Client / storage** | `edison-client`: create/cancel tasks, chat sessions, dataset store (search/fetch/delete), enterprise **profiles** (image tier, tools, sub-agents, skills) | `paperful mcp` + `--format json` + profiles.toml. No hosted workspace, no code kernel |

Same stance as [SnowBallSLR](#after-110-snowball-review) and [Valency](#literature-discovery-complement-waves): **borrow shapes, do not vendor, do not become the hosted product.**

**Borrow (local, dry-run default, fail closed):**

1. **Precedent pack** — given a hypothesis or methods phrase, retrieve (a)
   passages you already hold (`rag search` / `ask --focus gaps`) and (b)
   OpenAlex keyword / similar works **not** in the library. Stamp each hit
   `held` vs `public-metadata-only`. Title the verb so operators cannot
   confuse it with “the literature has never done this.” Wave 4 under
   [Literature-discovery complement](#literature-discovery-complement-waves)
   (**shipped** as `paperful precedent`).
2. **Named read jobs on MCP** — Edison’s `JobNames` enum is the lesson:
   one client, distinct jobs. Map onto existing tools (`ask`, `refs_gap`,
   `snowball_search`) plus the precedent pack. Still read-only; writes stay
   CLI `--apply`.
3. **Conflicting-evidence + review-shaped briefs** — [Summaries, briefs, and
   Ask](#after-110-briefs-ask). Edison’s Literature agent is the existence
   proof that “synthesis of contradictory findings” is a productised job,
   not a chat temperature.
4. **Audit trail** — every machine sentence already needs a passage (Ask /
   summarize). Edison’s Kosmos bar (“trace to code or literature”) is the
   copy test for receipts: if we cannot click through, we do not write the
   sentence. No world-model store; `paperful.note.v1`, run witness, and the
   RAG thread log are enough.
5. **Study-design / type as retrieval context** — OpenAlex `study_designs`
   and work `type` already on the citation map. Pass them into `ask` /
   synthesize ranking. Do **not** invent a journal-impact score.
6. **Patents and trial registries as discovery sources** — *test* before
   build, same as OSF: count how often a miss or a precedent query would
   have been a USPTO / ClinicalTrials.gov / patent-family hit. Thin DOI or
   registry-id ingest at most. Not a second PaperQA corpus.

**Interoperate:** Edison (or Valency Bond) when the question is “what does
the public literature / trial / patent record say?” or “run Kosmos on this
dataset.” Paperful when the question is fill, fix, mirror, and reason over
**this** collection. Typical stack: their Literature or Precedent →
snowball / `ingest-dois` → `run` / Wanted → local `ask`. Do not upload
`out/` to their store by default.

**Non-goals (park, do not spike):**

- Hosting or wrapping Kosmos, Analysis, or Molecules.
- A shared world model, code-execution kernel, or “6 months of a PhD”
  overnight run.
- Uploading the quiet mirror into a vendor workspace as the Ask path.
- Clinical-trial–native PaperQA, glyph/Markush transcription, or enterprise
  agent-profile deploys.
- Claiming completeness of “the literature” from OpenAlex metadata.

(after-110-paper-factory)=
### v2 paper factory (packs after the ledger is honest)

Contributor framing, **not** user-facing launch copy. The 2026 market uses
“paper factory” for four different artifacts (Deep Research memo, wiki
survey, workshop-grade ML paper, hypothesis memo). A strict factory —
manuscript + real citations + novelty check + (for reviews) PRISMA +
code/data — **does not exist as a reliable public product**. Sakana’s own
workshop experiment was withdrawn by prior agreement; their internal
conference-bar review said none of three papers would pass, and they
documented a false citation. Kosmos’s paper is weaker on **interpretation**
than on quoted statements; Edison’s ACU grant still requires human
validation before publication. Elsevier’s June 2026 author factsheet allows
literature overview and language help and forbids writing substantive parts
without the author’s intellectual contribution, fabricating references, and
generating primary images.

Paperful’s scarce asset is the opposite of those hosted loops: a fail-closed
path from a Zotero item to a file on disk with a restore ledger. **Factory
here means a sequence of dry-run verbs** (`research-pack.md` already:
`refs gap` → ingest → `run` → `dedupe` → optional `summarize`/`ask`).
`paperful all` is fill + tidy + summarize, **not** a scientist.

Landscape (route, do not flatten): Edison / Google Co-Scientist / Sakana =
discovery loops; Elicit / Consensus / Undermind / SciSpace / Scite / Valency
= public-corpus search; Covidence / Rayyan / ASReview = screening; Jenni /
Paperpal / Overleaf = draft; PaperQA2 / GPT Researcher / STORM = local or
web reports. Detail: [comparison reference](comparison-reference.md#paper-factory-stages).

**1.x stays Wanted.** v2 packs stay off until `[llm]` / `[rag]` / gates, and
until Wanted is honest. Do not grow 1.x into a second product.

**Borrow (local, dry-run default, fail closed):**

| Borrow | Stage | Honesty bar | Home |
| --- | --- | --- | --- |
| PaperQA2 loop: held PDFs → chunk → retrieve → **cited answer with page pointers**; no answer if the PDF is missing. **Shipped** as Ask `simple` plus `--ask-mode advanced` (score then answer on the local index; no vendored `paper-qa`) | Extract / synthesize | `[rag]` off by default; never call the manager from Ask | [Zotero-RAG](#zotero-rag-integration-later-question-centric-layer) |
| Refuse the sentence if you cannot click the passage (`has_successful_answer`) | Synthesize / critique | Copy test, not a world-model store | Edison borrow #4 above |
| Split **novelty pack** from **synthesis** before any outline | Novelty vs synthesize | Stamp `held` vs `public-metadata-only`; never “nobody has done this” | Wave 4 (shipped: `paperful precedent`) |
| Continuation / cheap vs high-effort as a **user-visible** Ask control | Synthesize | Local model; do not claim LABBench wins | [Ask](#after-110-briefs-ask) |
| Conflicting-evidence `synthesize` (question → methods → findings → limits) over **your** PDFs. **Shipped** as `--layout conflict` / `review` | Synthesize | Held full text only | [Briefs](#after-110-briefs-ask) |
| Figure/table **pullouts** (caption + page + stem), not generated artwork | Extract | Publisher bans on genAI primary images | [Briefs](#after-110-briefs-ask) |
| `stuff`: sentence or outline section → `rag search`; extra cites enter **Zotero before** `\cite`; no invented BibTeX. **CLI shipped**; `--apply` later | Write | Fail closed if index empty | [`stuff`](#stuff-later-extra-citations-from-the-library) |
| PRISMA **counts** in the run report; watch **drift** hash. **Shipped** (`summary.prisma`, `responses.json`). Export Discover / import `included.csv` later | Screen / keep current | Counts only; no fake recall % | [Snowballing](#after-110-snowball-review) |
| Official PRISMA flow from **exact counts**, not AI-illustrated diagrams | Screen / export | Methods figure | [SR mode](#after-110-bigger-bets) |
| Point at Better BibTeX + Quarto (do not vendor CSL) | Write / export | Parked until testers ask | [Parked](#after-110-parked) |
| ASReview-class ranking only as optional local embeddings | Screen | Not dual review | [Embeddings](#after-110-embeddings) |
| Post-hoc Crossref / retraction check after a draft | Critique | Existence ≠ claim support | [critique.md](critique.md) |
| Apply a critique pack as locatable edits / tracked changes (worklog, align-then-generate, selected-span prompts; no vendor) | Write | Pack required; never overwrite the source; no invented numbers/cites | [rewrite.md](rewrite.md) (shipped) |
| Deep forensics on supplementary tables / stats / figures (external tool) | Screen / audit | No merged score; subprocess or hand-off | [PaperGuard](#research-integrity-forensics-paperguard) |
| Named MCP read jobs (`ask` vs precedent vs `refs_gap`); writes stay `--apply` | Agent | Table stakes without a hosted corpus | [Literature-discovery](#literature-discovery-complement-waves) |

**Stay out (v2 included):** hosted multi-user as the product; Kosmos world
model / unattended 12-hour code / “overnight PhD”; 150M multimodal corpus;
Analysis / Molecules / ChemCrow; publisher-gray scraping or Sci-Hub/LibGen
as **default** or in marketing; uploading `out/` to a vendor as Ask;
auto manuscript in public copy; “has never been done”; replacing Zotero as
reader; CAPTCHA bypass; “AI fetch everything”; draft-then-stuff extra cites
from the **open web** without a Zotero queue; genAI blots / graphical
abstracts; a bird-named agent zoo as UX.

**Safe internal subtitle:** after the Wanted list is honest, grow the
collection, keep it current, and ask **your** PDFs. Complementary sentence
already in comparison: Edison/Valency/Elicit when the question is the
**public** literature; Paperful when the question is fill, fix, mirror, and
reason over **this** collection.

(after-110-distribution)=
### Distribution and install

**Settled in 1.7** ([decision log](plans/1.7-wave.md)). The list underneath
is the old brief; do not reopen it.

- CLI route: `pipx install paperful` / `uv tool install paperful`.
- Workbench route: Docker Compose. A Docker image is not “only if testers
  ask” — it is the operator path CI exercises.
- Playwright is the `paperful[browser]` extra. `doctor` names it.
- Opt-in PyPI update check shipped. No general telemetry.
- Signed desktop bundle: **rejected** for a single maintainer.
- Fresh-install and the Python matrix shipped in 1.7, then came off the
  live gate. The current job is smoke only; the rebuild order is
  [CI gate, cut back to smoke](#after-17-ci-rebuild). 3.10 stays in
  `requires-python` until an announced drop
  ([residuals](#after-17-platform-residuals)).

(after-110-findability)=
### Findability and launch

**Who it is for:** researchers and PhD students with big Zotero libraries;
librarians and research-support staff (also the paid cleaning report);
policy / NGO researchers (warmest first trial).

**Pitch:** the clean-up step that comes after discovery tools, not a rival
to them. It runs locally and is open source, so library data stays on the
user’s machine. Never promise “every paywalled PDF”. Never call Camofox
“stealth”. Own one search phrase: **“find missing PDFs in Zotero”**. Keep
Ask, Discover, snowball, and “paper factory” / “AI scientist” out of the
title, meta, share card, and GitHub About. Do not promise journal
manuscripts. Point Edison/Elicit/Jenni from [comparison.md](comparison.md)
instead.

**Adoption copy:** document auto-attach as off by default, Zotero 10+ only,
and switched on in Settings. Make the PyPI README lead with Wanted. Hold
Repair and further Ask work until Wanted proves out.

Launch gates, in order:

1. The paperful.io collision strip, then a link-preview paste test.
2. Re-crop the share image as `og-v2.png` so the Wanted heading and count
   show. **Shipped** (`website/images/og-v2.png`, homepage `og:image`).
3. A `robots.txt` with the sitemap line.
4. A ~60-character title.
5. A homepage link and topics on GitHub About.

Then: a plain-text “What it won’t do” section and FAQ. Never mention
Sci-Hub in copy, keywords, or alt text. Describe Camofox only as an
optional scripted browser. Then: one honest listing each on the Zotero
forums and a tools directory. Cross-link from glenwright.earth and
glenwright.net.

Outreach order: launch gates → tag 1.1.1 → quiet outreach to the Zotero
forums and research-software circles → Show HN → LinkedIn in the
operator’s own voice, link in the comments.

**Cohort:** keep the tools separate, with no suite page. TranscriptX and
Transcribe can go out as a joint post. Rollup cannot say “1.0” until it is
tagged.

(after-110-trust-gaps)=
### Trust, legal, privacy, sustainability

Gaps that had no owner in the 1.0 push. Settled rows stay here so the
decision is findable.

1. **Legal and fetch stance.** **Written:** [legal-privacy](legal-privacy.md).
   Publisher terms and campus licences stay the operator’s call. Complements
   [Compliance & provenance](#maybe-later) and
   [CAPTCHA / soft bot walls](#optional-llm-assist-local-litellm).
2. **Evidence after the first hour.** Local witness on run reports is
   shipped. An opt-in “send a report” button is still out, and it is not on
   the [live order](#after-17-order): a one-maintainer tool does not grow a
   telemetry inbox to decide the next feature. Dogfood notes in `docs/` or
   local `assessments/` are the evidence.
3. **Credentials and privacy.** **Written** on the same legal page. OS
   keyring was tried as a 1.7 idea and **rejected** (no daemon on the Docker
   path). Secrets stay in the environment; `config check` flags secrets
   sitting in `config.toml`.
4. **Sustainability.** Still open, and small. One maintainer. Done looks
   like a short note in CONTRIBUTING: the licence, what a useful change is
   (one verb, dry-run default, a fixture), and that a quiet repository is an
   acceptable steady state. The paid cleaning report is a separate offer. It
   does not imply an SLA or a second product.
5. **Docs as product.** The first-10-minutes page is specified under
   [workbench residuals](#after-17-workbench). Layer list:
   [Documentation (thicken)](#documentation-thicken).

(after-110-parked)=
### Parked or hold

Do not start these until testers ask, or until the main lane is boring.

- **Firefox extension** — unsigned temporary add-on, mirror writes only.
  [firefox.md](firefox.md). Not a 1.0 gate.
- **Local OpenAlex 2C** — full search / keyword / ORCID / `http`; institutions only; live API is enough for most.
- **SaaS / tenancy.**
- **Kosmos-class autonomous scientist** (multi-hour world-model runs over
  public literature plus uploaded datasets; experimental pipelines;
  molecular design) — [Hosted AI scientists](#after-110-edison-scientific).
- **Auto manuscript / related-work generator** (Jenni/STORM/Sakana job).
  `stuff` may queue extra cites into Zotero; it does not write the paper.
  [`rewrite`](rewrite.md) is apply-from-critique (hygiene default, pack
  required), not this parked generator.
- **Catalogue unification** (managers as equals).
- **LibGen** (same opt-in bar as Sci-Hub if ever).
- **CSL / Quarto export** — point people at Better BibTeX.
- **Licence gate** on attach (stamps exist; the gate’s shape is
  [Finish the ledger](#after-17-ledger-finish)). Default stays off.
- **Mendeley / EndNote “supported”** — promote only after a single call
  for testers gets replies. [Seeking testers](#mendeley-and-endnote-seeking-testers).

Repo hygiene (not a product feature): splitting this file into decisions
plus `docs/backlog/` stays available if the map gets unwieldy; it is not a
prerequisite for picking from the buffet.

(after-110-sequence)=
### One possible order (historical, through 1.1)

Superseded by [After 1.7 — one possible order](#after-17-order). Kept so
the 1.1 plan stays legible.

1. **1.1.1** — P0 scoping and ticks, Attach-at-zero, review-token test,
   version single-source, first-hour copy.
2. **Launch gates** — paperful.io strip, share image (`og-v2.png` **shipped**),
   robots, title; GitHub About remains an operator step.
3. **Wanted excellence** — **shipped** (stamps, reasons, hand-ticks,
   Waiting→add); keep honesty polish here.
4. **Cheap OpenAlex housekeeping** alongside 1.1.x (date stamp, stale
   figure, keyword snapshot test, watch baseline reset, snapshot-reload
   note).
5. **Then decide:** hand-built weekly digest → alert loop, OSF and
   author-site parsers, Docker, EmbeddingGemma benchmark then dedupe /
   “papers like this”, borrow SnowBallSLR stopping rule / drift cache /
   PRISMA counts, Repair/Mirror, grounded brief once Ask’s trust story is
   solid, then **one** bigger bet (systematic-review mode or
   grey-literature watchers).

(after-110-open-questions)=
### Open questions (1.1 record)

Live questions: [After 1.7](#after-17-questions). Answers to the 1.1 list:

- **Weekly digest or grounded brief?** Digest shipped as `keepup`. The
  grounded brief waits on [claim check](#after-17-claim-check). **SR or
  grey watching?** Grey watching shipped. SR is the remaining bigger bet.
- **Ask on the default nav?** Still open. The test is written: decide
  after claim-check, from whether `/ask` is used, not from taste alone.
- **Main install route?** Settled in 1.7. CLI via `pipx` / `uv tool`.
  Workbench via Docker Compose.
- **Wanted as the only lane?** It stays the public pitch (“find missing
  PDFs in Zotero”). It is not the only engineering lane. Next is the
  holdings diff.
- **`--strict-pdf-doi` as the default?** No. The flag exists and defaults
  off; a mismatched DOI still attaches unless the operator sets it.
  Flipping the default is a trust change and waits on a real-library
  complaint, not on a roadmap slot.
- **Legal stance and contributions?** Fetch and privacy stance is
  [legal-privacy](legal-privacy.md). Contribution shape is the
  sustainability note under [Trust](#after-110-trust-gaps).

(trust-10)=
## 0.1 → 1.0 (trust + mirror contract)

`0.1` was a first usable helper. **1.0** is this checklist — every row shipped.
Do **not** grow it into a second product (no auto Sci-Hub, no “AI fetch
everything”). Tag when ready.

| Step | UX outcome | Status |
| --- | --- | --- |
| End-of-run **one-line** banner: `downloaded N · attached M · deferred K · not_found J` plus write-API yes/no | Trust after a run | Shipped (table still follows the line) |
| Attachment **provenance stamp** (`oa:unpaywall` / `campus:ezproxy` / `grey:undocs` on notes or title prefix) | Trust inside Zotero | Shipped on the Zotero attachment note. A readable parent line follows `[remarks].surface` |
| `--dry-run` **Would-hit** column (sources in order) | Trust before network | Shipped |
| Exit **2** + next-steps when Zotero is down (`collections` / `run` / `attach`) | Fresh clone never dead-ends | Shipped |
| Slim README + [CHANGELOG](../CHANGELOG.md) known limits | Trust before install | Shipped |
| Lock `paperful.run_report.v1` | Trust for agents | **Shipped** — required keys frozen (`RUN_REPORT_*_KEYS` incl. miss rollups); golden fixtures; extra keys may be added |
| Lock `paperful.item.v1` and `snapshot` / `restore` (additive keys only after 1.0) | Trust for the disk ledger | **Shipped** — required keys frozen; restore is create-missing (not lossless round-trip) |
| Strip legacy flat-PDF migrate + mixed-layout doctor amber | Day-0 mirror never steers people into a whole-library layout cleanup | **Shipped (0.1 → 1.0)** |
| **Mendeley and EndNote adapters** (not a 1.0 blocker) | The ledger survives a manager change | In the tree. **Seeking testers.** Zotero stays the well-tested path. See below |
| **Workbench GUI** | Discover, Wanted, Preview/Grab; Advanced Repair / Mirror / Discover grow / Wanted recover | **Shipped** — [GUI](#gui); `paperful serve` + `paperful/ui/`; `docker compose up` publishes `127.0.0.1:8765`. TTY and Sci-Hub stay CLI |
| **Interactive Ask (GUI)** | `/ask` on the default nav when `[rag]` + `[llm]` enabled | **Shipped** — Ask + batch (scope, custom prompts, force); Index for ingest/search/`rag questions`/`rag answered`; Briefs for summarize/synthesize |

Nice-to-have (not 1.0 blockers): colour glossary next to `doctor` (documented);
collection picker hint on fuzzy `--collection` miss.

### Mendeley and EndNote (seeking testers)

The code is in the tree. It has not been proven on real libraries the way
Zotero has. **1.0 does not wait on tester sign-off** — ship with clear limits
in README, [why.md](why.md), [mendeley.md](mendeley.md), and [endnote.md](endnote.md).
Do not call either adapter **supported** until field reports justify it.
Use the committed template
[`docs/templates/adapter-field-assessment.md`](templates/adapter-field-assessment.md)
for real-library runs; keep filled reports under gitignored `assessments/`.

1. **Mendeley** — `MendeleyBackend` talks to `api.mendeley.com` (no official
   SDK). OAuth via `paperful session login mendeley`. `supports_write` is true
   in code. File download must **not** forward the Bearer token on the 303 to
   object storage. Document `notes` (`view=all`) is read; Paperful writes
   still use annotations. Needs a real library: list, fetch a missing PDF,
   attach, notes, and a failed auth that prints the next-steps ladder.
2. **EndNote** — `EndNoteBackend` reads `<Library>.Data/sdb/sdb.eni` (a copy
   if EndNote holds the lock, including `-journal`). Writes never touch that
   database: they stage `state/endnote-import/<stamp>/` for File → Import.
   Trash is refused. SQLite `reference_type` is **not** the XML number
   (journal is 0 in the DB, 17 in XML). Groups come from `groups.spec` +
   `members`, not a join table. Testers should confirm a round trip: read a
   small library, `snapshot`, import the bundle, and check that types and
   groups (stored only as a Label in XML) match what they expect.
3. **Still later:** multi-manager-as-equals (conflict journal, virtual
   collections). A tester report is not that.

## Core (keep sharpening)

- Resumable missing-PDF fetch, source routing, circuit breaker, EZProxy session
  hygiene, attach reliability, `doctor` / `report`. **Google Scholar posture**
  (below): stop treating vault Scholar replay as core; human browser at handoff
  instead. **Shipped (find
  recovery):** soft-blocked OA URLs (empty httpx body) retry in the vault
  browser (SSO / PDF link / download control), then optional opt-in `camofox`
  (external camofox-browser REST; scripted grab; [camofox.md](camofox.md)) and
  optional `browser_agent`; items stay `retryable` / `soft block` rather than
  hard `not_found`. **Later (fetch, not a bypass product):** if vault retry
  of those 403 / empty httpx bodies is the bottleneck, an opt-in TLS
  impersonator on scripted HTTP only — [CAPTCHA open question 4](#optional-llm-assist-local-litellm).
  Dead vault landings (`login` / `captcha` / `no download
  control`) silence that final host for the rest of the run; transport timeouts
  use a short connect budget and do not permanently block a publisher on a
  single blip. Manual handoff: `run` / `gaps --handoff list|tabs|walk|watch` and
  `paperful inbox watch` / `drain` against `[inbox].dir` (default: PDF
  **DOI-only** attach to missing-PDF parents, whole-library scope;
  `[inbox].match` / `[inbox].create` opt in to the [match ladder](#inbox-match-ladder)
  and gated create). Distinct from snowball watch `inbox.jsonl`. **Later
  (handoff):** rank `--handoff list` by in-corpus cite count (from [refs
  gap](#bibliography-gap-scan-later-not-gaps)) × miss severity so limited
  browser time hits high-value PDFs first. CLI `--browser-agent` /
  `--no-browser-agent` and `--camofox` / `--no-camofox` override
  `[browser_agent].during_run` / `[camofox].during_run` for one `run` / `all`.
  **Later (author-site + RG):** personal-site PDF discovery via opt-in web
  search ([Acquire §2](#maybe-later-not-core)); ResearchGate request-from-author
  is **handoff-only** (existing RG URL → system browser; you click Request
  full-text; ToS) behind `[request].channels` ([same section](#maybe-later-not-core)).
- **Academic HTML→PDF snapshot (shipped, opt-in).** Web/news (and DOI-less
  `document` / `report`) still print when the page is the article. Journal and
  other DOI items stay off unless `[htmlpdf].academic` is `gated` or `auto`
  (`--htmlpdf` for one run). The print runs after scripted lanes and
  `browser_agent`. Landing pages are refused: paywall, login, cookie wall,
  access-options, short pages, and any page that still offers a native PDF.
  `gated` writes `state/htmlpdf/proposals/` (`paperful htmlpdf proposals
  list|apply|reject`). `auto` attaches only after those checks. The stamp is
  `snapshot:htmlpdf` (weaker than a publisher PDF). `gaps` counts
  `snapshot_only`. `run --upgrade-snapshot` retries native lanes and replaces
  the print unless `--keep-snapshot`. A snapshot is miss-surface `snapshot`,
  not `import_ok`.
- **Google Scholar — late tail + handoff (shipped).** `scholar` stays **opt-in**
  (not in `DEFAULT_SOURCES`; first-run CAPTCHA ambers if it were). **Policy**
  (`[fetch].order = "policy"`, default) pulls it out of the reliable loop:
  OA, campus, grey, then a **late** Scholar try. When `browser_agent` is on
  this run, `[scholar].when = "auto"` **interleaves**: one Scholar query, then
  the agent only if that miss remains — the agent wall clock is the backoff
  (no extra `delay_scihub_s` after an agent call). Agent off: one late Scholar
  phase with the existing latch. `[scholar].when = "phase"` keeps a Scholar
  burst then the agent; `"interleave"` always pairs. `[fetch].order = "list"`
  honors the `sources` array (field-specific escape). **Handoff:**
  `[handoff].scholar` (default on) adds a Scholar results URL to miss rows and
  opens it in the **system** browser when there is no direct PDF URL.
  **SerpApi** (`[serpapi].enabled` + env `SERPAPI_API_KEY`) is a paid link-discovery
  lane after local tail steps, never a silent cloud default; stamp `web:serpapi`.
  `[serpapi].max_calls` (default 20, `0` unlimited) and `--serpapi-max` cap
  paid searches this run. `doctor` ambers when enabled without a key (no paid probe).
  OpenAlex / Semantic Scholar / Crossref remain the programmatic defaults; Scholar stays
  out of snowball backends. CAPTCHA solve services stay out of scope.
  **Latch (unchanged):** the first Scholar 429, 503, or CAPTCHA / `/sorry/`
  page skips Scholar for the rest of the run; queued items get
  `scholar:skipped(blocked)` and still reach `browser_agent`. SerpApi quota
  uses its own latch and does not trip Scholar.
- **Inbox create-on-unmatched (config, shipped).** Optional `[inbox]` mode so
  `watch` / `drain` still ingests when no missing-PDF parent matches: create a
  parent in a configured collection (or a routed target from `[inbox].route`),
  attach the PDF, and fill bibliographic fields from Paperful’s identifier
  pipelines (DOI from PDF → Crossref / OpenAlex / Semantic Scholar; title /
  first-page fallbacks when DOI is missing). **Reference-manager metadata
  window:** configurable settle or poll after attach so Zotero and other backends
  that retrieve metadata from PDFs can run before Paperful writes or merges fields
  (skip or shorten the wait when the backend has no such behavior).   Config modes: `attach_only` (today) | `create_gated` | `create_auto` (high bar).
  Gated vs auto should match smart inbox; fail closed to `unmatched/` or
  `review/` when resolution is thin. **Gated UX:** write
  `state/inbox/proposals/<id>.json` (`paperful.inbox.proposal.v1`);
  `paperful inbox proposals list|apply|reject` — never silent parent create.
  Tag parents `inbox-created` and `inbox:<dirname>` for later `dedupe` / `refs gap`. Optional
  multi-root `[inbox].dir` list is still later. End-of-drain
  one-liner + JSON (attached / created_gated / unmatched), same honesty as
  `run`. Today’s default stays DOI attach only — no silent create-parent.
(inbox-match-ladder)=
- **Inbox match ladder (before `unmatched/`, config, shipped).** Optional stages
  run **in order** after a stable PDF lands in `[inbox].dir`, each toggled in
  config, before `move_unmatched`. Goal: attach (or propose attach) using the
  same missing-PDF index as today without requiring the operator to rescue files
  from `unmatched/` when metadata lives in the PDF but not in the first two
  pages of extractable text.
  1. **DOI (shipped)** — `doi_from_pdf` (pdftotext / pypdf, ~two pages) →
     normalized DOI → unique missing-PDF parent in scope. Fast path; keep default.
  2. **Hold / defer quarantine** — `[inbox].quarantine_after_s` (or
     `hold_before_unmatched`): poll the same path until timeout so another
     process can act (e.g. operator drag into Zotero, or a manager watched folder
     on a *different* path — Paperful does not drive Zotero’s GUI recognizer;
     document sidecar patterns). Re-run the ladder on the file before quarantine.
  3. **Richer text extraction** — when the text layer is empty or sparse, optional
     transient OCR for matching only (`[inbox].ocr_for_match`: cache under
     `state/pdf-cache/` or temp; do not rewrite the drop file unless the operator
     later runs `paperful ocr --apply` on the attached item). Reuse `ocrmypdf` /
     `[ocr].languages` where `doctor` is green.
  4. **Deterministic title / fingerprint attach** — derive candidate title (PDF
     `/Title`, first-page heuristics, filename stem when not junk), year when
     visible, optional registrant host from embedded links; normalize like dedupe
     title hygiene. Match missing-PDF rows in scope by
     `norm(title)+year` (same ambiguity rules as dedupe `medium_title_year`:
     hold groups with divergent titles; never attach on a tie). Shares the
     **non-DOI grey fingerprint** work (`norm(title)|year|registrant_host`; ISBN /
     report # when present — near-term table row 7). Crossref / OpenAlex title
     search only as an opt-in, rate-limited **resolve** step when local library
     match is thin (same honesty as `fix-metadata`, not silent parent create).
  5. **LLM match (`when_thin`)** — only when stages 1–4 fail or scores sit below
     a bar: grounded prompt with PDF excerpt + short list of candidate missing-PDF
     items (metadata block pattern from `lint` / `[lint].llm_pdf_match` and
     `fix-metadata` `llm_title`). Config: `[inbox].llm_match` `off` | `when_thin` |
     `always`, `[inbox].llm_match_min_confidence`, per-function
     `[inbox].model` / `[inbox].provider`. **Gated attach** by default (proposal
     row in `paperful.inbox.proposal.v1`); auto attach only above a high bar and
     single clear candidate. Fail closed to `unmatched/` or `review/`.
  **Config sketch:** `[inbox].match` preset `doi_only` (today) | `doi+title` |
  `doi+title+ocr` | `full` (title + OCR + `llm_when_thin`), or explicit stage
  list. Run report / `state/runs/*-inbox.json` should record `how`:
  `doi` | `fifo` | `title_fingerprint` | `title_resolve` | `ocr` | `llm` |
  `manager_metadata` | `none`. **Not in scope:** guessing parents outside the
  missing-PDF index without create-on-unmatched; bulk OCR of the whole library
  inside `watch`.
- **Smart inbox (config, shipped).** Create-on-unmatched and the match ladder
  attach or propose a parent; this lane chooses a **collection** when `-C` is
  omitted. Deterministic signals first — recent snowball runs and watches
  (`state/snowball/…`, `target_collection` on `summary.json`, last `-C` /
  profile), DOI already in the library, filename / PDF metadata / first-page
  text against **existing** collection titles — then an optional LLM ranker.
  **LLM use:** `[inbox].llm_route` `off` | `when_thin` | `always`. Model follows
  the house pattern: global `[llm]` plus `[inbox].model` / `[inbox].provider`.
  Apply modes: `[inbox].route` `off` (default) | `gated` | `auto`. Fail closed
  to `review/` / a proposal — never silent misfile, never invent a collection.
  DOI attach stays the fast path when a missing-PDF parent already matches.
- **OA honesty / miss taxonomy (shipped).** Project internal miss status to a frozen
  surface enum for dry-run, `gaps`, and the run report:
  `no_doi | paywalled | no_oa | fetch_failed | license_blocked | import_ok`
  (one code → one plain string; keep rich detail on `attempts[]`). Stamp
  Unpaywall / OpenAlex `license` / `oa_status` / `version` onto candidates and
  `record.json` so bronze vs licensed OA is auditable and a future license gate
  can emit `license_blocked` without writing bytes. **Configurable:** the
  operator chooses which of those fields get stamped (and later which feed a
  gate); defaults should be honest but not surprise a local library with
  redistribution policy. Prefer licensed `url_for_pdf` / green repository copies
  over bronze-only publisher landings when both exist. Follow-ons: DOI→candidate
  URL cache (TTL) to cut repeat API traffic; Crossref `link[]` PDF harvest as
  campus-entitled API-first (never claimed as free OA without entitlement).
  Not a hosted service SKU; not Sci-Hub completeness metrics. **Ship with** the
  next research-ops verbs ([Near-term research-ops](#near-term-research-ops)), not
  after: surface the same codes on `run --dry-run`, `gaps`, and `--handoff list`
  (plain-string column + optional `oa_status` / `license` when stamped); map rich
  `attempts[]` outcomes via `miss_detail` until Core fully switches. Without
  stamps when Unpaywall/OpenAlex supplied them → do not claim `import_ok`.
- **Linked-URL health (shipped).** `paperful urls check -C …` —
  short-budget HEAD/GET on metadata URLs and linked-PDF URLs; findings `ok | redirect | soft_404 |
  hard_dead | paywall_html`. `--apply` rewrites a URL only when a grey playbook
  already knows the PDF target. Report-only by default.
- **Quiet mirror** — [quiet-mirror.md](quiet-mirror.md). **Shipped:** `snapshot`
  writes a per-item folder (`record.json`, optional PDF, notes) plus
  `out/_index.jsonl`, `out/_collections.json`, and `out/_history.json`.
  `[mirror].pdfs` is `additional` (default), `all`, or `none`. `restore --apply`
  creates missing items and does not overwrite fields already in Zotero. Dual
  `imported_file` store; house sync (Syncthing) stays outside Paperful. Not a
  second reading UI. Not a linked-file cutover. Not a WebDAV client.
- **`paperful screen` (shipped, opt-in).** Retraction / expression-of-concern
  lookup (Crossref + OpenAlex), optional PubPeer (`[screen].pubpeer` +
  `PUBPEER_DEVKEY`), and local PDF screening against PPS fingerprint CSV dumps.
  Report by default; `--apply` writes a `paperful pps:` tag and `paperful-pps`
  note. Not in `paperful all`. See [screen.md](screen.md).
- Deterministic `lint` / `fix-metadata` (Crossref / OpenAlex / Semantic Scholar /
  PubMed, PDF-text DOI via pdftotext then pypdf) with explicit `--apply`.
  **Shipped:** verified PDF-DOI → patch; date precision guard; HTML title cleanup;
  ALL CAPS → Title Case; title hygiene findings (`title_html` / `title_all_caps` /
  `title_filename`). Filename titles stay findings-only.   De-allcaps today only keeps
  two-letter tokens (UN, EU); longer corpus acronyms (BBNJ, FAO, OECD, …) stay
  uppercase when they appear in `state/acronyms/` (`paperful acronyms -C … --apply`,
  frequency + shape; optional `extra` list). Deterministic first; optional LLM NER
  only as a later assist behind the existing `[llm]` gate.
- Collection-scoped duplicate packs: `paperful dedupe` (DOI, then title+year).
  Trash is explicit `--apply`; title+year needs `--apply-medium`. See
  [dedupe](dedupe.md).
- **Note hygiene — selective deletion + typed provenance (later).** Paperful
  writes many child and collection notes (`summarize`, `synthesize`, `[remarks]`
  found / duplicate / linked, dedupe spare-parent lines, attachment readable
  lines, future RAG / briefing exports). Re-runs often update in place via
  tags, but operators still need **bulk delete** with honest filters — e.g. only
  summaries from a particular model, all summaries **except** one model,
  dedupe-remark notes only, notes before a date stamp, or everything under `-C`
  matching selected `paperful-*` kinds. **Direction:** a scoped verb
  (`paperful notes …`, name TBD) with `--dry-run` default and `--apply` to
  trash matched notes only (never parent items). Filters should include
  `note_type` / kind, LLM **model** (from structured metadata, not regex on
  footer text), tag, date, collection scope, and paired exclusions
  (`--except-model`, `--except-type`, …). **Infrastructure:** do not infer
  intent by searching note bodies — each Paperful-owned note should carry a
  stable **`paperful.note.v1`** block (type, model, verb, run id, prompt sha
  when relevant) in machine-readable form (HTML comment or agreed prefix),
  mirrored on `snapshot` under `notes/`; Zotero tags stay the update lookup
  key but are not enough when tags were renamed or two verbs overlap.
  **First line (Zotero UX):** the item pane shows the note’s **first line**
  before open — every writer should lead with a fixed, scannable prefix per
  type (e.g. `Summary (qwen2.5:7b): …`, `Duplicate: …`, `Attach: oa:unpaywall
  …`) so provenance and intent are obvious at a glance; retrofit existing verbs
  when deletion ships. Complements `dedupe` (merge parents, not note purge)
  and quiet-mirror `notes/` (audit on disk before `--apply`). Mendeley / EndNote
  parity after the Zotero path is boring.
- **CORE as an OA PDF source (shipped).** In `DEFAULT_SOURCES`; skipped until
  `core_api_key` is set. Stamp `oa:core`. `doctor` reports whether the key is set
  (green either way — optional lane).
- Library adapter seam (`LibraryBackend`). **Zotero is well tested.** Mendeley
  and EndNote are seeking testers (above).

### Mirror-first reads

**Status:** shipped. The rule is in
[architecture](architecture.md#mirror-first) and the
[developer guide](developer.md). Measurements before the change:
`assessments/2026-10-01-mirror-first-zotero-api.md` (local, not published).

Commands refresh `out/` from what changed in the library, read the mirror,
and write through it. Read verbs run with Zotero closed. A first refresh of
a 22,700-item library takes about a minute; a refresh with nothing changed
is six requests.

Closed in this pass:

- **`attachments`** reads children from the mirror and proves a stored file
  by MD5 against the item folder. The manager is asked only about bytes the
  folder lacks (and for `--apply`). With it closed, report-only runs finish
  and say how many attachments went unchecked (`READ_VERBS` covers it).

- **Mendeley and EndNote** implement `changes(since)` (Mendeley via
  `modified_since` / `deleted_since`; EndNote via `sdb.eni` mtime). Their
  reads take the mirror-first path when the feed is present. Still seeking
  testers.
- **Non-PDF attachments** copy into the item folder when `[mirror].pdfs =
  "all"`. Standalone notes and attachments land under `out/_notes/` and
  `out/_attachments/`.
- **Freshness on screen** includes last-refresh written/gone counts from
  `_sync.json`.
- **`paperful cache clean`** removes absorbed or stale files under
  `state/pdf-cache/` (dry-run unless `--apply`).

Not in scope: reading `zotero.sqlite` or `storage/` directly, and any sync
daemon.

(near-term-research-ops)=
### Near-term research-ops

**Status:** rows 1–24 shipped (literature-discovery complement waves 1–4 in rows 22–24 plus Wave 4 pack). Same bars:
dry-run default, explicit `--apply`, fail closed, no silent library writes. See
[Documentation (thicken) — research pack](#documentation-thicken)
for the end-to-end operator story.

| Priority | Item | Status |
| --- | --- | --- |
| 1 | [`paperful refs gap`](#bibliography-gap-scan-later-not-gaps) — cited-in-PDF, not-in-library pack | Shipped |
| 2 | [Inbox match ladder](#inbox-match-ladder) (defer quarantine, title/OCR, optional `llm_when_thin`) + [create-on-unmatched](#core-keep-sharpening) (gated proposals) + smart inbox routing | Shipped (`create_auto`: unique DOI, or unique ISBN / report / title+year+host; `[inbox].route` picks `-C` when omitted) |
| 3 | `paperful ingest-dois` — DOI list → `-C`, `--dry-run` / `--apply`, `--tag` | Shipped |
| 4 | Provenance tags on create (`--tag`, `[snowball]` / `[ingest]` default_tags, `from-<seed-slug>`) | Shipped |
| 4b | OA honesty miss enum + license/OA stamps on `run --dry-run`, `gaps`, handoff list, run report | Shipped |
| 5 | Grey playbook example packs (think-tanks, RFMOs, institute report hosts) via `[[grey_playbooks]]` | Shipped — ocean builtin (`rfmo-docs`, `iucn-dosi`, `thinktank-ocean`) plus `paperful/data/grey_playbooks_examples/` (IEA/IRENA, OECD/WHO/UNEP/UNDP) |
| 6 | Linked-URL health (Core above) | Shipped (`paperful urls check`; `--apply` only via a known playbook rewrite) |
| 7 | Non-DOI grey fingerprint (`norm(title)|year|registrant_host`; ISBN/report # when present) in snowball / dedupe / inbox ladder + inbox-create | Shipped (ISBN/report like DOI; title\|year\|host is review-tier; host mismatch is not `exists`) |
| 8 | `paperful collections add --keys-file` — membership batch, dry-run / apply | Shipped |
| 9 | Acronym allowlist harvest (Core `fix-metadata`) | Shipped (`paperful acronyms`; Title Case consumes `state/acronyms/`) |
| 10 | [Frontier digest](#frontier-digest-later-watch--external-ingest); thin [snowball briefing](#frontier-digest-later-watch--external-ingest) export before full digest | Shipped (`snowball digest`, `watch digest`, `watch run --digest`); alert loop + what-cites as [`keepup`](keepup.md) — [Keeping up](#after-110-keeping-up) |
| 11 | Scholar late tail + latch + opt-in SerpApi | Shipped (`[fetch].order` policy; interleave with `browser_agent`; `[handoff].scholar`; `[serpapi].enabled` / `max_calls`) |
| 12 | Authors/orgs frequency report from `-C` (`state/reports/…`; seed **field author packs**) | Shipped (`paperful authors`; `--apply` writes report + proposed pack) |
| 13 | Handoff list ranking (Core handoff) | Shipped (cite count × miss severity) |
| 14 | Opt-in academic HTML→PDF snapshot (Core `htmlpdf`) | Shipped (`[htmlpdf].academic` off\|gated\|auto; snapshot tier; `--upgrade-snapshot`) |
| 15 | Agent JSON + documented exit codes on batch verbs; MCP after those are stable | **Shipped** — `paperful.agent.json.v1` + exits 0/1/2/3 on batch verbs; optional `paperful mcp` (expanded in row 22) |
| 16 | Author-site PDF (registry + packs + co-author crawl; **snowball co-author preflight** / `grey:author_site`) | Shipped (opt-in; promote packs; SearXNG local-only) |
| 17 | ResearchGate request-from-author (**handoff-only**; config off by default; you click) | Shipped (`[request].channels`; `state/author-requests.jsonl`; `paperful reachout --handoff tabs`) |
| 18 | Twenty CRM — lookup cache plus `twenty sync` (create/enrich, Paperful note, late `author_site` before Scholar, opt-in listing write-back) | Shipped (`paperful twenty lookup` / `twenty sync`; `[twenty].enabled`; `--twenty-writeback`) |
| 19 | Typed note provenance (`paperful.note.v1`) + scannable **first-line** prefixes on all Paperful note writers | Shipped (summarize / synthesize / remarks / snowball / briefing) |
| 20 | `paperful notes delete` (or equivalent) — scoped filters: type, model, `--except-model`, tags; dry-run / `--apply` | Shipped (`--type`, `--model` / `--except-model`, `--all` + confirm / `--yes`) |
| 21 | [Author watch lists](#author-watch-lists-later-people-you-follow--their-papers) — ORCID / OpenAlex resolve + `run` / `apply`; file import of follows; corpus suggestions | **Shipped** — `paperful authorwatch` (+ suggest/accept/delete); saved social HTML/CSV import; Discover list management |
| 22 | [Literature-discovery complement](#literature-discovery-complement-waves) — **Wave 1:** read-only MCP (`gaps`, snowball dry-run / keyword preview, collection `export`) + BibTeX/RIS for snowball / `authorwatch` proposal packs | **Shipped** — `paperful mcp` tools + `export-proposals`; CLI snowball `--format json` loads `summary.json` on dry-run |
| 23 | Same — **Wave 2:** OpenAlex publication trend report for a query or saved snowball seed (`snowball trends`) | **Shipped** |
| 24 | Same — **Wave 3:** thicker `authorwatch` briefing (co-authors + recent works via OpenAlex) | **Shipped** |
| 25 | ORCID ego co-authorship SNA (`paperful network`, Discover People map, BBNJ phase slices) | **Shipped** — [network](network.md); extra `paperful[network]` |
| 26 | `paperful search` + Discover Web (SearXNG grey query; metadata parents; PDFs via Wanted) | **Shipped** — [search](search.md); `search watch` URL poll shipped (you cron it) |

(literature-discovery-complement-waves)=
### Literature-discovery complement (waves)

**Context:** Hosted literature products (e.g. [Valency MCP Bond](comparison-reference.md#valency-mcp-bond-and-hub),
[Edison Scientific](comparison-reference.md#edison-scientific)) cover
corpus-scale search, citation graph, keyword trends, and (Edison) cited
reviews, novelty (“has anyone”), trials/patents, and optional data-analysis
agents. Paperful does not replicate those indexes or kernels; these waves
tighten the **local** loop and agent surface so Bond- / Edison-class tools
pair cleanly with snowball, mirror, and `ask`.

Same bars as [near-term research-ops](#near-term-research-ops): dry-run default,
explicit `--apply` for anything that touches the manager, fail closed, one JSON
envelope for CLI and MCP.

| Wave | Scope | Acceptance |
| --- | --- | --- |
| **1** | **Agent MCP + proposal export** — Extend optional `paperful mcp` with read-only tools that call the same builders as CLI `--format json`: `gaps`; snowball crawl dry-run / keyword preview (no gate that writes parents); collection `export` (BibTeX/RIS). Emit BibTeX or RIS from on-disk snowball / `authorwatch` proposal packs (DOIs already resolved in the pack). | **Shipped** — `export-proposals` + MCP tools; docs in [commands](commands.md#agent-channel-format-json-and-mcp), [snowball](snowball.md#bibtex--ris-from-the-queue), [authorwatch](authorwatch.md#ledger). |
| **2** | **Publication trends** — Count works by publication year for an OpenAlex query or a saved snowball profile seed; reuse `OpenAlexClient` and budget posture as snowball. | **Shipped** — `snowball trends`, MCP `snowball_trends`; dry-run table + `--format json`; no library writes. |
| **3** | **Author briefing thicken** — `authorwatch show` / list briefing adds co-author network and recent works from OpenAlex (same resolution paths as `resolve` / `suggest`). | **Shipped** — `authorwatch briefing` + compact `show`; `--format json`; no new polling scheduler. |
| **4** | **Precedent / novelty pack** — Edison Precedent shape, local honesty: phrase in → `rag search` over held PDFs **plus** OpenAlex keyword/similar works not in the library; stamp `held` vs `public-metadata-only`; dry-run pack + read-only MCP tool; never a “nobody has done this” claim. | **Shipped** — `paperful precedent`, MCP `precedent`; [commands](commands.md). |

**Non-goals for these waves:** hosting a global full-text index; Valency Hub–style
publishing; replacing Bond or Edison Literature for “ask the whole literature”
chat; wrapping Edison Kosmos / Analysis / Molecules.

**Spike acceptance (one week, eng):** `refs gap` dry-run pack with zero manager
writes; `ingest-dois` idempotent apply + `held` on ambiguous resolve; `collections
add --keys-file` dry-run with per-key `not-found`; miss enum + license stamps on
OA success path; gated inbox proposal → apply/reject without silent create;
inbox drain dry-run on a fixture pack where DOI-less PDFs attach via title
fingerprint (deterministic) and one `when_thin` LLM case logs confidence without
auto-attach when below bar.
Golden CI fixtures for `paperful.run_report.v1`, `paperful.refs_gap.pack.v1`, and
`paperful.inbox.proposal.v1` — **shipped** (`tests/fixtures/` + `tests/test_schema_freeze.py`).

## Optional LLM assist (local / LiteLLM)

**Status:** MVP shipped behind `[llm].enabled = false` — Ollama loopback default,
LiteLLM via `paperful[llm]`. Verbs: `recover` (browser agent on `run` after
other vault lanes fail, plus `paperful recover --item`; `paperful[browser-agent]`,
Py 3.11+), `fix-metadata` title proposals (`[fix_metadata].llm_title`), `lint`
`pdf_identity_mismatch` (`[lint].llm_pdf_match`), `summarize` → tagged child note,
`synthesize` → literature review from those notes (`state/reports/` and, by
default, a collection note). Image PDFs need `paperful ocr --apply` first.
See [architecture § LLM layer](architecture.md#llm-layer-optional-local-first).
URL recipes from vault/agent wins are already `playbooks propose` / `promote`
← `state/fetch-wins.jsonl` (below), including agent step traces when the
agent lands a PDF. **Shipped:** `[browser_agent].fallback_model` (one retry),
`use_vision`, `recover --from-last-run`. Still later: Browser Use Cloud / BU2;
venue/date cleanup; **vault /
agent Chromium extensions** when the profile can load them safely (small
operator allowlist — e.g. cookie-consent dismiss, PDF/link helpers — so models
spend fewer steps on CMP noise and missed download controls; spike Playwright +
unpacked vs store extensions and whether extension UI confuses DOM/vision
agents); model and doc posture below; CAPTCHA posture in the next subsection.

(browser-use-integration-models-docs-config)=
### browser-use integration (models, docs, config)

**Status:** Shipped as optional **`paperful[browser-agent]`** (browser-use **0.13.x**,
Python **≥3.11**). Wired in `paperful/browser_agent.py`: **`ChatOllama`** or
**`ChatLiteLLM`**, session-vault **Chrome**, **`use_vision=False`**, PDF success
only when bytes pass **`min_pdf_bytes`** and size stabilizes (never trust agent
`done` alone). **`run`** auto-appends the lane when `[llm].enabled`,
`[browser_agent].during_run`, and the extra are on (policy order: one Scholar
try immediately before the agent when Scholar is opted in);
**`paperful recover --item`** runs the same runner in isolation. **heavy**
Compose images ship browser-use; **light** (CI default) does not. Headed
vault login still stays on the host (shared `state/`).

#### Documentation map (keep in sync)

| Doc | Role |
| --- | --- |
| [ai.md](ai.md) | Feasibility: try-it vs ~1.5k library, overnight local reality, LiteLLM/OpenRouter setup, cost order of magnitude |
| [llm.md](llm.md) | Install extras, `[llm]` / `[browser_agent]` keys, `recover` behaviour, troubleshooting table |
| [browser-agent-models.md](browser-agent-models.md) | **Local Ollama tag guidance** for PDF UI loops (VRAM bands, avoid list, acceptance test) |
| [config.md](config.md#llm-optional-local-first) | Key table: `model`, `fallback_model`, `use_vision`, `during_run`, caps |
| [architecture.md](architecture.md) | Serial source ordering, Playwright handoff before agent, CAPTCHA → skip lane for run |
| [sessions.md](sessions.md) | Vault profile shared with recover; no concurrent vault users |
| [commands.md](commands.md) | `recover --from-last-run`, `--browser-agent` / `--no-browser-agent` on `run` / `all` |
| [docker.md](docker.md#image-mode-light-vs-heavy) | light vs heavy packs (`browser-use` in heavy) |
| `assessments/2026-09-29-ollama-browser-use-pdf-download-models.md` | Full research note (Infra rank + honesty/engineering cuts); **user-facing summary lives in `browser-agent-models.md`** |

When changing agent defaults, task text, or doctor floors, update **`llm.md`**
and **`browser-agent-models.md`** together so operators see one story.

#### Config contract (today)

```toml
[llm]
enabled = true
provider = "ollama"              # ollama | litellm
model = "qwen2.5:7b"             # summarize / synthesize / lint / fix-metadata
base_url = "http://127.0.0.1:11434"
allow_remote = false
timeout_s = 120

[browser_agent]
# model = "qwen3:14b"            # override for browsing only; omit → [llm].model
# fallback_model = "qwen3:30b"   # one retry before final not_found (not on captcha)
# use_vision = false             # true only with VL tags (qwen2.5vl, etc.)
during_run = true                # false → recover --item only unless --browser-agent
max_steps = 20                   # stop early when PDF lands
max_wall_s = 300
```

| Knob | Policy |
| --- | --- |
| **`[browser_agent].model`** | Always treat as **separate** from `[llm].model`. Browsing wants **tool-capable 14B+**; other verbs stay on 7B–12B. |
| **`doctor`** | Name-pattern amber under **~10B**; message points at **14b+ class** tag. |
| **`use_vision`** | Default **false**; set true only with a VL-capable `[browser_agent].model`. |
| **Vault** | Same **`user_data_dir`** as `session login`; extensions (uBlock, cookie banner) reduce step waste. |
| **Honesty** | Task + `_RECOVER_SYSTEM_EXT` forbid search engines, purchase, pirate hosts; hard CAPTCHA → **`captcha`** and lane silence for the run. |

Example operator split (dogfood): **`qwen3.8:latest`** for notes, **`qwen3-coder:30b`**
for recover on ~20 GB — coder MoE is **not** in the community top rank for UI;
validate on real publisher pages and prefer **`qwen3:30b`** / **`qwen2.5:14b+`**
if recover loops or mis-clicks.

#### Model selection (evidence, not a Paperful benchmark)

browser-use publishes **no official local-model quality table**; hosted
**ChatBrowserUse** / cloud VL scores do not transfer to Ollama quants. Consolidated
guidance (see [browser-agent-models.md](browser-agent-models.md)):

- **Floor:** community and GitHub threads cluster around **≥14B** for multi-step
  click loops; sub-7B tags parse-fail or time out.
- **24 GB+ band:** **`qwen2.5vl:32b`**, **`qwen3:32b`/`30b`**, **`qwen2.5:32b`**
  — best anecdotal reliability for publisher PDF flows.
- **12–16 GB:** **`qwen3:14b`** / **`qwen2.5:14b`** with raised Ollama context.
- **Avoid:** models without Ollama **tools** template (400), legacy **`qwen:`**,
  fragile **Gemma3** / **R1** loops, embedding models.
- **Qwen schema drift:** nested action objects; mitigations upstream = prompt
  examples — Paperful should extend system message if parse errors spike.

**Scoreboard for docs and dogfood:** schema-valid actions + **file on disk** +
no invented URL — not parameter count or model marketing copy.

#### Gaps vs upstream browser-use (roadmap)

| Item | Notes |
| --- | --- |
| **`[browser_agent].fallback_model`** | **Shipped:** one retry before final `not_found` (not on captcha). |
| **`use_vision` + VL tag** | **Shipped:** opt-in `[browser_agent].use_vision`; preflight/doctor check tag shape. |
| **`num_ctx` / temperature** | Pass through to `ChatOllama` or document Modelfile recipe; agent DOM dumps need **16k–32k+**. |
| **Schema hardening** | Nested JSON examples in `extend_system_message`; log parse failures to run report. |
| **Batch recover** | **Shipped:** `recover --from-last-run` + `--from-last-run-mode`. |
| **Playbooks from wins** | **Shipped:** agent successes write promotable `click:` / `rewrite` wins + optional `steps` in `fetch-wins.jsonl`. |
| **Browser Use Cloud / BU2** | Stealth / CAPTCHA — explicit non-default; no bypass product. |
| **Opt-in camofox lane** | **Shipped:** external camofox-browser REST before `browser_agent`; scripted PDF grab; not a CF-bypass product; no vault SSO. See [camofox.md](camofox.md). |
| **Controlled bakeoff** | No Paperful CI fixture for “Springer cookie → PDF” per model; optional **`assessments/`** protocol later. |

#### When *not* to run the agent (product rule)

Deterministic lanes first: Unpaywall, OA APIs, httpx download, vault Playwright
(SSO / `citation_pdf_url` / download control). **`browser_agent`** only after
those miss on a URL the vault **already** may load. Handoff (`--handoff`,
`inbox watch`) remains the honest path for Scholar, CAPTCHA, and entitlement
the vault cannot hold.

### CAPTCHA / soft bot walls (open; do not ship a bypass product)

Hard CAPTCHAs end as `captcha` today; vault landings that look like
`login` / `captcha` / `no download control` already silence that host for the
rest of the run. Soft bot walls may improve with Browser Use Cloud stealth
(not wired). **No** Cloudflare-bypass product feature; Sci-Hub ALTCHA stays
on the opt-in Sci-Hub lane only.

Open questions before wiring anything else:

1. **Third-party solve APIs** (2Captcha, CapSolver, …) — paid, keys leave the
   machine, publisher ToS / campus AUP risk. Only consider behind explicit
   opt-in + disclaimer, never as a default, never for pirate hosts. Prefer
   human-in-the-loop over a solve service.
2. **Human-once, quiet-for-run?** If vault / browser-use keeps the **same
   persistent Chromium profile** (cookie jar, User-Agent, outbound IP), a
   human challenge solve that issues site clearance (e.g. Cloudflare
   `cf_clearance`) can quiet *subsequent* challenges on that zone for the
   cookie lifetime (often tens of minutes), as long as later traffic stays in
   that profile. Opening a tab in a *different* browser (system Firefox vs
   vault Chromium) does **not** transfer clearance. Spike worth trying: on
   `captcha`, pause like EZProxy re-login — open headed vault on that URL,
   wait for the operator to pass the challenge, resume the same host for the
   rest of the run — instead of (or before) permanent host silence. Measure
   how often clearance actually sticks across publishers.
3. **User-Agent switcher (between items or mid-run)?** httpx uses one
   `[fetch].user_agent`; vault / `browser_agent` reuse the profile string.
   **Explore:** rotate or override UA per host, per serial source phase, or
   after a soft block — vs keeping UA stable for the life of the cookie jar
   (mixed fingerprint often triggers harder walls). Same question for switching
   only on scripted httpx while leaving vault UA alone. Measure against host
   silence, 403/soft-block rates, and campus/Google posture; opt-in config only,
   not a default anti-bot product.
4. **Small HTTP impersonator (later, not a scrape framework).** Some
   publisher `downloadpdf` links 403 on stock httpx TLS while the same URL
   works in the vault browser. **Later, if that retry is the bottleneck:**
   an opt-in extra that impersonates a browser TLS fingerprint on *scripted
   HTTP only* (typical engine: `curl_cffi` or httpx impersonate), still
   behind `is_fetchable_url`, pacing, circuit breaker, and email identity.
   Never a default. Never Cloudflare / Turnstile / CAPTCHA solving. Do
   **not** take on a crawl kit (Scrapling, Scrapy, Camoufox-in-process) for
   this — Camofox and `browser_agent` already cover recover. Measure 403 /
   empty-body rates against vault retry before wiring. Sibling of question 3.

**MVP:** when a title looks wonky (ALL CAPS, truncated, HTML junk, filename-as-title,
mojibake), propose a cleaned title using **abstract and/or first-page PDF text**
as grounding. Output lands in the existing patch pipeline
(`state/metadata-patches.jsonl`); human review + `fix-metadata --apply` remain
mandatory. Never mutate the library from a model call alone.

Sketch:

```text
lint / heuristics flag bad title
  → extract abstract (item) + first-page text (pdfid / out/ cache)
  → opt-in LLM propose {title} JSON
  → validate (non-empty, length bounds, not equal to garbage patterns)
  → Patch(source="llm_title", …) beside deterministic patches
```

### Patterns to copy (do not invent a third stack)

Prefer **rollup’s** CLI-shaped LiteLLM/Ollama split; borrow **transcriptx**
enablement / grounding / review rules for “suggestions only.”

Sibling checkouts (not in this repo): `Documents/rollup`, `Documents/transcriptx`.

| Pattern | Draw on | Paperful takeaway |
|---------|---------|-------------------|
| Optional extra, no silent cloud default | rollup `pyproject.toml` (`[llm]` extra), `LlmExtraMissingError` | `paperful[llm]`; LLM off unless config/flag |
| Provider protocol + Ollama vs LiteLLM clients | `rollup/src/rollup/llm_client.py` | Thin `LLMClient` + `CompletionRequest`; local Ollama default path |
| Reject `ollama/…` via LiteLLM; no Ollama-only knobs on LiteLLM | `rollup/src/rollup/provider_options.py` | Same guards if both providers ship |
| Plan-time validation before network | `rollup/src/rollup/llm_validate.py` | Fail in `doctor` / before batch, not mid-run |
| Doctor import/config checks (no paid probe) | `rollup/src/rollup/doctor.py` (`_check_litellm_config`) | Amber/red when `llm_provider=litellm` without extra or model |
| Keys from env only; `api_base` validated | rollup `validate_llm_api_base`, `docs/CONFIG.md` | Document remote = title/abstract/PDF excerpt leave the machine |
| Pluggable client + Null stub | `transcriptx/src/transcriptx/core/llm/llm_client.py` | Fix code never imports provider SDKs directly |
| Suggestions grounded + human apply | `transcriptx/docs/runtime/corrections-llm.md` | Ground in abstract/first page; reject ungrounded titles; continue on failure |
| Opt-in module flag separate from global LLM | transcriptx `analysis.corrections.llm.enabled` | e.g. `llm.enabled` + `fix_metadata.llm_title = true` |
| Multi-provider stance (sidecar vs in-process) | `transcriptx/docs/ROADMAP.md` theme N | Start in-process LiteLLM like rollup; revisit sidecar only if weight hurts |

Config sketch (names TBD):

```toml
[llm]
enabled = false
provider = "ollama"          # ollama | litellm
model = "qwen2.5:7b"
base_url = "http://127.0.0.1:11434"
# api_base = ""              # LiteLLM / OpenAI-compatible
# allow_remote = false

[fix_metadata]
llm_title = false            # MVP gate; requires [llm].enabled
```

**Non-goals for the MVP:** blank-slate auto-tagging of the whole library,
rewriting abstracts, silent cloud defaults, applying patches without `--apply`.
Staged tagging (below) is **later**, not part of the title / PDF-identity MVP.
Chat-over-library in the **GUI** is a **1.0 goal** (see
[Zotero-RAG integration](#zotero-rag-integration-later-question-centric-layer));
terminal `ask` / `--thread` remain the CLI path.

**Later LLM verbs:** venue/date cleanup from the first page. Title proposals,
the PDF identity check, and grounded briefs (`summarize` / `synthesize`) are
shipped. Still proposals on disk; never a silent library write. **Note cleanup**
(selective delete by model / type, dedupe remarks, etc.) and shared
`paperful.note.v1` + first-line prefixes — [Core note hygiene](#core-keep-sharpening).

### Zotero-RAG integration (later; question-centric layer)

**Status:** CLI question-centric layer shipped — see [rag.md](rag.md). The index
is built in Paperful from the on-disk mirror (no separate zotero-rag install, no
reference manager calls): `paperful rag ingest | search | status | questions |
answered` and `paperful ask` (one cited answer, TTY/`--thread` follow-ups, or
`--from-file` batch). Ask has two modes (`simple` default, `advanced` scores
passages then answers); `--ask-mode` / the Ask form / MCP `ask_mode` override
one run. Opt-in under `[rag]`; `auto_ingest` is off by default.

**Interactive Ask in the GUI is shipped** — see [GUI](#gui) and [Product
split](#product-split-10-vs-post-10). Terminal multi-turn and the Index page
share `ask --thread`: follow-ups are rewritten for retrieval and stored under
`state/rag/threads/` with visible scope (collection chip, optional years) and
citations. Index exposes batch scope (`--item`, years, types), custom prompts
(inline, upload, path, saved under `state/prompts/`), and `rag questions` /
`rag answered` when Advanced is on.

Reuse the house LLM pattern: global `[llm]` + per-verb overrides (same spirit
as `[summarize].model`, `[browser_agent].model`, `[rag].model`).

**Direction:**

1. **Batch Q&A with citations** — **Shipped:** `ask --from-file` →
   `state/ask-batch/` (`paperful.ask_batch.v1`); resume via question hash +
   focus + index tip; optional Zotero collection note with `--apply` + `-C`.
2. **Question generation from summaries** — optional LLM pass over existing
   `summarize` outputs (and/or `synthesize` sections) to propose **unanswered**
   or **open** research questions for the corpus; land in a reviewable queue
   before batch RAG (same patch / dry-run honesty as other LLM verbs). Still
   roadmap (deferred; batch/`rag answered` already accept operator files).
3. **Prompt variants and `--focus`** — **Shipped:** `--focus`
   default|questions|gaps|methods|answered|conflict; `[rag].focus`;
   `--prompt FILE`; profile `focus` field. `conflict` is an Ask prompt, not
   a third Ask mode.
4. **Extract questions posed by papers** — **Shipped:** `rag questions`
   (deterministic rules + optional `--llm` / `[rag].extract_questions_llm`) →
   `state/rag/questions/<key>.json` with provenance `rule`|`llm`.
5. **Corpus-wide RAG on those questions** — **Shipped:** `rag answered`
   `--from-file` / `--from-extract`, `--after-item`, year filters →
   `state/rq-answered/` (`paperful.rq_answered.v1`).
6. **Config** — **Shipped:** `[rag]` ask_mode/focus/prompt/dest/extract_questions_llm
   plus advanced knobs (defaults keep one summary pass);
   profile `focus` + existing SCOPE. `doctor` ambers when the index is missing,
   the embedding model is unavailable, or the index is behind the mirror.
7. **Per-claim extra citations (`stuff`)** — **Shipped (CLI pack):** batch
   `rag search` over manuscript sentences or outline sections; no Ask
   narrative. Workbench **shipped**; `--apply` still later. Detail:
   [`stuff`](#stuff-later-extra-citations-from-the-library).

**Non-goals for this lane:** replacing Zotero’s reader; cloud-default RAG;
answers without citations; auto-mutating parent metadata from Q&A output;
scheduling nightly “ask everything” jobs without an explicit operator command;
Edison Literature / PaperQA over a vendor corpus (Ask stays the local index;
their client is complementary — [Hosted AI scientists](#after-110-edison-scientific)).

**Consumer fit:** extends **Reading & knowledge** (below) and complements
`summarize` / `synthesize` — summaries stay the human-readable layer; RAG stays
the evidence-linked Q&A layer. `stuff` is the writing-side reuse of `rag search`
(sources only), not another chat verb.

(stuff-later-extra-citations-from-the-library)=
### `stuff` (CLI pack shipped; workbench later)

**Status:** CLI pack and Advanced workbench shipped (`paperful stuff`,
[stuff.md](stuff.md), [gui.md](gui.md)). `--apply` stays later. Needs `[rag].enabled` and a built
index. Does **not** need `[llm]` or Ask: no reviewer note, no grounded
paragraph, no claim rewrite.

**Job:** for each phrase/claim in a manuscript (or a paper you already
hold), suggest **X** additional citations from the local index. Implementation
is the boring loop: split the document into sentences (reuse
`critique_metrics.split_sentences`) or outline sections (`--lane outline`),
run each unit through the same retriever as `paperful rag search`
(`-k` = X), and return the sources (item key, title, pages, score, passage
snippet). Narrative summary stays off — this is not `ask`.

Same input shape as [`critique`](critique.md): `--item ITEMKEY` (mirror PDF)
or `--file` (draft path). Search scope is `-C` / year / type, same as
`rag search`. Exclude the source item from hits. Skip bibliography /
reference-list blocks and tiny fragments so the pack is not a self-cite
of the reference section.

**Direction (ship in order; each stage can stop):**

1. **CLI pack** — **Shipped.** `paperful stuff --item KEY -C … --k 3` (or
   `--file` draft, optional `--lane outline`). Writes
   `state/stuff/<id>/<stamp>/` (`pack.json` + `pack.md`, schema
   `paperful.stuff.pack.v1`). One row per sentence or outline section:
   quote, locator, up to `k` hits. Fail closed when the index is missing
   or empty. Zero manager writes. `--format json` → `paperful.agent.json.v1`.
   Read-only MCP tool `stuff`.
2. **Workbench** — **Shipped.** Advanced sibling of Critique: pick item or
   upload, background job, download pack.md. Not on the default nav.
3. **Later (parked until the pack is boring)** — optional `--apply` child
   note on the item; stance labels (supports / contrasts / mentions);
   auto-insert into the manuscript. Those are writing-product bets, not
   the first slice.

**Config:**

```toml
[stuff]
k = 3                    # extra sources per claim (CLI `--k` wins)
min_sentence_words = 8   # skip captions / headings / fragments
min_query_words = 4      # outline lane
max_units = 200
lane = "manuscript"      # manuscript | outline
```

Reuse `[rag].top_k` only as a ceiling; `stuff`’s `k` is the per-claim
request, typically smaller than Ask’s passage budget.

**Acceptance:**

- Each row is a sentence from the input plus `≤ k` index hits; no LLM
  prose in the pack.
- Hits are in-library (mirror index) only — not OpenAlex / web invent.
- Source item (when `--item`) is never listed as a hit for itself.
- `refs gap` stays the cited-but-not-owned scan; `stuff` does not create
  parents or propose ingest.

**Non-goals:** generating citation keys or CSL; rewriting the draft;
claim verification (“this sentence is true”); stuffing from outside the
corpus; nightly batch over the whole library; treating heuristic
similarity as proof the source supports the claim.

Complements `critique` (checkers on the same document), `rag search`
(one query), and `ask` (one narrative answer). Distinct from
[`refs gap`](#bibliography-gap-scan-later-not-gaps) (works named in the
PDF that you do not own). Buffet context:
[Summaries, briefs, and Ask](#after-110-briefs-ask).

(embeddinggemma-2-local-embeddings)=
### EmbeddingGemma 2 (later; stronger offline embeddings)

**Status:** roadmap only — evaluate as an optional `[rag].embed_model`, not a
default swap and not a new product. Today’s path stays
`nomic-embed-text` (small, English-leaning) or `bge-m3` (multilingual) via
Ollama / LiteLLM; each model already keeps its own index under `state/rag/`.
Announced 2026-10 ([Google Open Source roundup](https://opensource.googleblog.com/2026/10/this-week-in-open-source-for-october-15.html);
[developer guide](https://developers.googleblog.com/embeddinggemma-2-the-developer-guide/);
weights on [Hugging Face](https://huggingface.co/google/embeddinggemma-2)).

**Why it matters for Paperful:** Ask / `rag search` already run fully from the
on-disk mirror with local embeddings. EmbeddingGemma 2 is **Apache 2.0**,
sub-1B, and tuned for on-device RAG — so it strengthens the “passages never
leave the machine” story without inventing a second index stack. Quantized
footprint Google cites: ~**191 MB** active RAM for **text-only**, ~**567 MB**
for the full multimodal load (Pixel-class numbers; laptop CPU/GPU will differ).
Ollama already ships tags (`embeddinggemma-2`, plus size slices such as
`270m` text-only / `440m` text+vision / `740m` full), so the first spike can
stay on the existing `embed_provider = "ollama"` path.

| Property | EmbeddingGemma 2 | Paperful fit |
| --- | --- | --- |
| License | Apache 2.0 | Matches local-first / redistributable tooling posture |
| Text backbone | 270M (modular; vision +170M, audio +300M → 740M full) | Default Paperful path is **text from PDFs/abstracts** — load text-only |
| Output | 768-d native; MRL truncates to 512 / 256 / 128 | Large libraries: shorter vectors cut LanceDB storage (re-normalize after truncate) |
| Context | 8,192 tokens | Longer chunks than many small embed models; still respect `[rag]` chunk settings |
| Languages | 100+ (MTEB multilingual ~par with EmbeddingGemma 1) | Candidate alternative to documenting `bge-m3` as the only multilingual pick |
| Task prompts | Asymmetric `SearchQuery` / `Document` / `QuestionAnswering` (and titled `title: … \| text: …`) | Quality depends on prefixes — Ollama/LiteLLM passthrough may need an explicit Paperful wrapper |
| Multimodal | Shared space for text, images, video, audio | **Later:** figure / page-image retrieval; not required for the text spike |
| Precision note | Prefer **bfloat16** or float32; float16 can NaN or silently degrade | Document in `rag.md` / doctor; prefer bf16 Ollama tags when available |

**Direction (ship in order; each stage can stop):**

1. **Spike (config-only, no new provider)** — On a dogfood collection (e.g.
   `ocean/BBNJ` or a fixture pack), set
   `embed_model = "embeddinggemma-2:270m-…"` (pin a text-only / bf16 tag once
   the Ollama library naming is stable), run `rag ingest`, then compare
   `rag search` / `ask` recall against `nomic-embed-text` and `bge-m3` on the
   same questions. Record wall-clock, peak RSS, and citation hit rate in
   `assessments/` (local; not a published benchmark). Confirm `doctor` green
   and that switching models leaves the old index folder intact (existing
   contract).
2. **Task-prompt honesty** — EmbeddingGemma 2 expects different prefixes for
   queries vs documents. Spike whether Ollama’s embed API applies them, or
   whether Paperful must format passages (`title: {item title} | text: {chunk}`)
   and queries (`prompt_name` / instruction string) in `rag.ingest` /
   `rag.retrieve`. Fail closed: never claim “drop-in” if bare strings regress
   vs nomic. Document the required `[rag]` knobs (or a model-family hint) in
   [rag.md](rag.md).
3. **Docs + recommended tags** — If the spike is clearly better for multilingual
   or long-passage corpora, add a short “optional stronger local embedder”
   subsection beside the existing `nomic` / `bge-m3` guidance: pull command,
   RAM band, “rebuild index” reminder, float16 warning. **Do not** change the
   default until dogfood + CI fakes stay green; defaults stay small and boring.
4. **MRL / storage (optional)** — For libraries with tens of thousands of
   chunks, expose an opt-in truncate dim (256 default candidate for text) on
   ingest + query, with `normalize_embeddings` behaviour documented. Index
   folder name must include dim so 768-d and 256-d indexes do not collide.
5. **Vision path (parked until text is boring)** — With the 440M text+vision
   slice, embed page renders or extracted figures for “find the chart that
   shows …” queries. Only after OCR / `light`|`docling` text RAG is solid;
   keep citations grounded to item key + page. Audio/video are out of scope
   for a PDF library workbench.

**Config sketch (names TBD; additive only):**

```toml
[rag]
enabled = true
embed_provider = "ollama"
# Optional stronger local model (after spike); default remains nomic-embed-text
# embed_model = "embeddinggemma-2:270m-bf16-text"
# embed_dim = 768          # or 256 / 128 when MRL ships; part of index id
# embed_task = "qa"        # maps to QuestionAnswering vs SearchQuery prefixes
```

**Acceptance (spike):**

- Text-only tag embeds offline with `[llm].allow_remote = false`.
- `rag ingest` + `rag search` + `ask` work with zero manager calls (same as today).
- Side-by-side note vs `nomic-embed-text` on ≥10 fixed questions; no silent
  quality cliff from missing task prefixes.
- Peak embedding RSS in the same ballpark as Google’s text-only claim on a
  laptop-class machine (order-of-magnitude, not a hard CI gate).

**Non-goals:** replacing LanceDB; making EmbeddingGemma 2 the CI default;
shipping torch / sentence-transformers as a required extra when Ollama
suffices; cloud embedding endpoints; multimodal as a 1.0 or near-term
research-ops blocker; fine-tuning the model in-tree.

Post-1.1 buffet (after the text spike): “papers like this”, semantic
dedupe, a collection map, ASReview-style screening, semantic snowball, and
an optional sqlite-vec store — [Local embeddings](#after-110-embeddings).

(bibliography-gap-scan-later-not-gaps)=
### Bibliography gap scan (shipped; not `gaps`)

**Status:** shipped — `paperful refs gap` writes `state/refs-gaps/`
(`paperful.refs_gap.pack.v1`) and a command report under `state/runs/`. Always
dry-run. Sibling for briefing/note lists: [`coverage`](#briefing--collection-coverage-shipped-sibling-of-refs-gap).

| Today | Bibliography gap scan |
| --- | --- |
| **`paperful gaps`** (shipped) | **`paperful refs gap`** (shipped) |
| Items **already in scope** missing a stored PDF, linked-only URL, or DOI | Works **cited inside** your collection’s PDFs (or seed items) that are **not** in the library fingerprint |
| Drives `run` / handoff | Drives review pack → optional `ingest-dois` / snowball seed / gated create |

**Already in the tree:** snowball bibliography parsing
(`paperful/snowball/bibliography.py` — landing HTML, open-PDF reference
sections, `parse_bibliography_entries`); OpenAlex reference lists cached under
`state/cites/` for in-collection overlap remarks; Europe PMC / remote ref
recovery on hops. `refs gap` walks collection PDFs (mirror-first) and emits
**missing-from-library** rows as one operator-facing command.

**Direction:** `paperful refs gap` — inputs `-C`, seed item keys, and/or seed PDF
paths; always dry-run (never auto-create). Match: same fingerprint family as
`dedupe` / snowball (`DOI` → title+year; extend with [non-DOI grey
identity](#near-term-research-ops) when present). Output: stdout table +
`state/refs-gaps/<stamp>/` pack (`paperful.refs_gap.pack.v1`), reusing
`snowball.candidate` columns where they fit. Pack rows include at least
`cited_by_count_in_scope`, `oa_hint`, `already_exists`, `suggested_action`
(`ingest-dois` | `snowball doi` | skip). Gate: hand off to
`ingest-dois --dry-run` then `--apply`; optional rank for handoff. OCR /
text-layer required for scan-only PDFs (`ocr` first); clear finding, not crash.
Not a silent snowball auto-run. Treat as a **near-term research-ops epic** ([stack
above](#near-term-research-ops)).

(briefing--collection-coverage-shipped-sibling-of-refs-gap)=
### Briefing ↔ collection coverage (shipped; sibling of `refs gap`)

**Status:** shipped — `paperful coverage --from-note <key|path> -C …` or
`--from-file`. Always dry-run. Pack under `state/coverage/<stamp>/`
(`paperful.coverage.pack.v1`) with `in_collection` / `missing` / `ambiguous`;
`dois.txt` → `ingest-dois --from-file` / `--from-pack`. Same fingerprint family
as `refs gap`. Optional `provenance_hint` when tags are available.

### Frontier digest (later; watch + external ingest)

**Status:** digest shipped. Alert loop shipped as [`keepup`](keepup.md)
(poll → ingest → briefing; Paperful-local only — no email / rollup). Snowball
**watch** stays dry-run and does not download PDFs. There is still **no**
built-in scheduler. Post-1.1 buffet: Discover keepup UX, `refs` direction on
collection digest, retractions / living-review add-ons —
[Keeping up](#after-110-keeping-up).

**Digest (Paperful):** `paperful snowball digest --run-id`,
`snowball watch digest`, or `snowball watch run --digest` writes
`digest.md` (run dir, or `state/snowball/watches/<name>/`). The report is
new vs `exists` vs version vs deferred, overlap hints on the top new rows
(`score`, `why`, hop, `overlap`), a suggested `-C` from the profile or
`[snowball].target_collection`, and paths for the queue, `apply`, and
`resume`. `--apply -C` files a collection note tagged
`paperful:frontier-briefing`. After `watch run` the queue file holds only
new proposals; `already seen` is the overlap with the prior frontier.
launchd / systemd / cron examples are in [snowball.md](snowball.md#watch).

**Thin briefing (still shipped):** `paperful snowball briefing --run-id …` /
`snowball watch briefing <name>` → markdown export of the dry-run or watch queue
(no silent creates; optional collection note `paperful:frontier-briefing` with
`--apply -C`). Surface
grey-vs-peer / OA stamp hints in briefing tables where provenance
exists (`grey:…`, `oa:…`).

**Alert loop (shipped; Paperful-only):** `paperful keepup run` (operator cron;
no built-in scheduler) polls configured sources → `digest.md` →
`keepup apply --apply` (or `run --apply`) into the job `-C` → `ingested.md` →
`paperful run` for PDFs. Standalone: `snowball watch apply` /
`authorwatch apply` read **inbox jsonl**, not `digest.md`. Distinct from
digest `--apply`, which only files a `paperful:frontier-briefing` note.
No email, IMAP, or sibling rollup coupling.

(author-watch-lists-later-people-you-follow--their-papers)=
### Author watch lists (in tree; people you follow → their papers)

**Status:** shipped — `paperful authorwatch`. Distinct from collection-scoped [`snowball watch`](snowball.md#watch)
(keyword / DOI / ORCID **seed** profiles and hop expansion). Here the seed is a
**named author list** the operator curates: people they already care about,
turned into a **local** watch for **new research outputs**, not career posts.
Live social scraping is out of scope; saved HTML/CSV exports import with `--file`.

**Direction:**

- **Lists on disk** — `paperful authorwatch save|add|remove|show|delete` maintains people under `state/authorwatch/<name>/` (display name, ORCID
  when known, optional affiliation host). `resolve` fills missing ORCID / OpenAlex ids; **held** on ambiguity.
- **Suggestions** — `paperful authorwatch suggest -C … --method corpus|most_cited|coauthor|mix` ranks people from the collection (and OpenAlex where needed). `authorwatch accept --id …` (optional `--seed-from`) moves checked rows onto the list; ledger `suggestions.jsonl`.
- **Watch run** — `paperful authorwatch run` sets a cursor baseline (no full-oeuvre fetch) then polls OpenAlex for works indexed after that cursor. `--backfill-from` proposes by **publication** date. `exists` stays out of the inbox. `authorwatch apply -C` creates parents (independent of `[snowball] enabled`). PDFs via `paperful run`. Paperful does not schedule.
- **Import** — CSV/JSON/ORCID files; `import --source rg|linkedin|academia --file saved.html` parses operator-saved exports. Without `--file`, prints the export recipe.

**Pitch:** Get what really matters from the people you already follow —
**their research**. Social follow graphs surface jobs, posts, and noise;
authorwatch turns that graph into a frontier of **new papers** from those
names, in one place — **your machine** (`state/`, optional `-C`, same
mirror and honesty contract as snowball).

**Non-goals:** replacing RSS or social timelines; auto-friending or messaging on
RG; cloud “who to follow” recommendations; live authenticated scraping of social
follow pages; treating social HTML as a `run` PDF source.

### Structured section extract (MVP; shipped)

**Status:** shipped — `paperful extract-sections` (rules + optional GROBID
sidecar + optional LLM fill). Narrower than full `summarize`; structured
fields for downstream RAG, synthesis, and gap scan context.

**MVP fields (per item, on disk):** `abstract`, `conclusion`, `methodology`,
`research_questions` (plus optional raw section map). **Stage 1 — deterministic:**
split PDF text (and manager abstract when present) on a maintained **heading
synonym list** — e.g. Abstract, Introduction, Background, Methods / Materials
and methods, Results, Discussion, Conclusion(s), Summary, Research questions,
Limitations, References / Bibliography (locale and publisher variants in
`state/section-headings.toml` or shipped defaults). Boundaries from line-start
heuristics + known IMRaD patterns; fail partial sections to findings, not
garbage writes. Optional **GROBID** sidecar (`[grobid].enabled`, TEI cache
under `state/grobid/`) is the high-quality Stage 1 engine; heading rules remain
the fallback. **Stage 2 — LLM inference** only when `[llm].enabled` and a
dedicated gate (e.g. `[extract_sections].llm`): fill missing MVP fields from
the bounded excerpt; reject outputs that do not quote-ground in the supplied
spans. Writes `state/sections/<key>.json`; **no** silent Zotero parent mutation
(mirroring fields into `record.json` on snapshot remains a later option). Overlaps
Zotero-RAG RQ extraction (deterministic + LLM) — share heading list and
provenance enums where possible. `[rag].parser = "grobid"` reuses the TEI cache.

### Annotation mirror (later)

**Status:** roadmap — Zotero stays reader of record; the quiet mirror gains
**your** highlights and notes for RAG / evidence packs. Phases, the
`paperful.annotations.v1` file, and the off-by-default
`[rag].prefer_highlights` switch are specified in
[Finish the ledger](#after-17-ledger-finish). This lane does not outrank
the holdings diff.

Read item annotations (and tagged notes where distinguishable) through
`LibraryBackend` on `snapshot` or a dedicated `paperful annotations mirror`
verb; store beside `record.json` under `out/` (hashes + page anchors). Read-only
sync into Paperful — never replace Zotero’s annotation UI. Consumers: cited
answers prefer operator highlights; future evidence-pack export. Group libraries
and adapter parity (Mendeley/EndNote) are explicit non-goals until tested.

(run-witness-shipped-trust-thicken)=
### Run witness (shipped; trust thicken)

**Status:** shipped — optional `witness` (`paperful.witness.v1`) on every
`paperful.run_report.v1` written via `write_run_report` / `write_command_report`.
Includes config SHA-256, Paperful version, profile name when bound, scope,
fetch sources/preset, `[llm]` / RAG index tip, mirror `_sync.json` refresh.
Not part of `RUN_REPORT_KEYS` (additive). Open packs record `witness_id`
(first 12 of `config_sha256`) on each step. `refs gap`, `coverage`, and
`snowball apply` write command reports so they join the pack trail.

### Auto-tagging library items (later; not 1.0)

**Status:** roadmap only — do not implement until the fetch / lint / attach loop
and 1.0 trust checklist are solid. Suggestions-only + human `--apply`, same
patch posture as `fix-metadata`.

Goal: durable domain / topic tags on items (Zotero tags and/or fields that
survive into `record.json`), so catalogues stay filterable and downstream
surfaces can use them. One consumer already named: a **domain-engagement
timeline** on the public site (`glen-w.github.io`) — distinct from that site’s
career timeline (type/role over years). Site plan:
`/Users/89298/Documents/website/glen-w.github.io/docs/dev/career-timeline-plan.md`
(section *Later: domain engagement timeline*).

Staged approach (ship in order; each stage can stop without the next):

1. **Built-in keywords** — harvest BibTeX `keywords`, existing Zotero tags, and
   any collection/label hints already on the item. Normalise casing/slugs into
   a reviewable patch set; no model calls. Write only on explicit `--apply`.
2. **Extraction from abstract / title** — rules, frequency heuristics, and/or
   light NLP keyword harvest grounded in local title + abstract (and optional
   first-page text). Prefer deterministic allowlists under `state/` (same spirit
   as the collection-scoped acronym harvest under Core `lint` / `fix-metadata`).
   Still findings → patches → human apply.
3. **LLM pass** — optional enrichment / normalisation behind `[llm].enabled`
   (and a dedicated gate, e.g. `fix_metadata.llm_tags`). Ground proposals in
   title/abstract/PDF excerpt; reject ungrounded tags; never silent library
   writes. Reuse the existing LiteLLM/Ollama client patterns above.

**Non-goals for this lane:** chat-over-library tagging UI; replacing Zotero’s
tag UI; publishing tags straight to the website without a review path; treating
LLM tags as source of truth without stage 1–2 anchors.

## Snowball

**Status:** keyword, multi-DOI / multi-ORCID, and collection seeds, hybrid keyword-then-hop,
`direction` sides `refs` / `cites` / `both` / `keywords` / `similar` (and
combos), gates including `approve-each`, overlap ranking, and optional `[llm]`
query suggestions are in the tree. Discover **Map** draws the queue
(`paperful.citation_graph.v1`) and can expand one hop. Contract:
[snowball.md](snowball.md). Still outside: `expand = cited_authors`.

Snowball grows a library outward from a keyword, one or more DOIs, one or more
ORCIDs, or DOIs already in a collection. It writes a candidate queue on disk, then
creates items only under an explicit gate. `run` still fills PDFs. With
`fetch_pdfs`, snowball calls that same `run` in-process on the keys it just
created, so one command can go from a keyword to a collection with PDFs. The
stranger default is a dry-run: candidates only, no library writes, no
downloads.

The mechanic to port is the personal-site citation crawl
(`glen-w.github.io` `processing/library/citations.py`): a fixed one-hop
OpenAlex expansion (`referenced_works` out, `filter=cites:` in), polite
client, caps. Paperful needs a work list for the library. The site’s people
graph, hard-coded ego slug, and Scholar scrape stay on the site.

Phases, in order. Each can stop without the next.

1. **Dry-run. Shipped.** `snowball doi` / `search` write
   `paperful.snowball.candidate.v1` under `state/snowball/<run-id>/`.
2. **Writing gates and the one-shot library. Shipped:** `--gate auto` and
   `fetch_pdfs`, plus `approve-batch` / `snowball apply`, ORCID works (plus
   OpenAlex author fill), and collection DOI seeds.
3. **Optional expansion. Shipped:** `direction` including cited-by, OpenAlex
   keyword hops, and `similar` (one ranked hop: shared references, then
   Semantic Scholar recommendations; combinable e.g. `refs+similar`), plus
   depth above 1 under the same caps. A finished queue with no `deferred.json`
   resumes into create / PDF fetch without searching OpenAlex again.
4. **Config. Shipped:** `dedupe_scope`, type and venue filters, OpenAlex
   `listed_in` source-list allow filter (`--listed-in` / `[snowball].listed_in`;
   membership, not a quality score), profile save,
   and CLI `--dedupe-scope` on crawl / `run` / `resume` / `apply` / `watch run`
   (`apply` still defaults to the full library).
5. **Last pass. Shipped:** `hybrid`, `approve-each`, overlap ranking,
   Crossref / Semantic Scholar fill, and `[llm]` suggestions on the queue.
6. **Watch. Shipped:** `snowball watch save` / `run` / `show` re-runs a saved
   profile, baselines the frontier on the first run, and proposes only unseen
   arrivals into `state/snowball/watches/<name>/inbox.jsonl` plus a normal
   run queue. Always dry-run / no PDFs. `watch digest` / `watch run --digest`
   writes the frontier rollup. Paperful does not schedule it; your
   own launchd or cron may call `watch run --digest`. See [snowball.md](snowball.md#watch).
7. **Co-author site preflight (opt-in). Shipped:** Before or alongside hop
   expansion, derive a co-author graph from the seed + candidate author lists,
   discover personal / institutional / static-site home pages for
   high-centrality names (ORCID researcher URLs, then an optional CRM listing,
   then SearXNG), and write them into
   [field author packs](#maybe-later-not-core) for the profile scope so the
   following `run` / `fetch_pdfs` pass can try the `author_site` grey lane.
   Proposed packs only until `snowball packs promote`. Opt-in profile knob;
   not a substitute for OpenAlex caps or gates.

### Dedupe during snowball — ongoing prevention, not merge-after

Snowball never runs `paperful dedupe` inside the crawl. **Ongoing** here means
duplicate work is collapsed and library hits are applied **while the queue is
built and before any parent is created**, not a one-shot merge at the end.
Stragglers still use the same hygiene loop as any other ingest:
`dedupe --dry-run` → read `state/dedupe-packs/` → `dedupe --apply` on the
target collection. Optional `--dedupe-after` / `[snowball].dedupe_after`
(`off` | `classify` | `apply`) can run that pack after create. There is
still no snowball step inside `paperful all` today.

Treat snowball dedupe and `paperful dedupe` as complementary:

| Layer | When | What it does | What it does *not* do |
| --- | --- | --- | --- |
| **In-run identity** | Every hop and on OpenAlex resume merge | One `candidates.jsonl` row per work (`doi:` or `openalex:` identity). Duplicate paths merge `seed_keys`, ref/keyword overlap, and scores. | Read Zotero; trash or merge parents |
| **Library fingerprint** | Once per crawl finish (and again on `apply` / saved-queue resume) | Normalized DOI, then title+year (same family as [dedupe](dedupe.md)); optional preprint ↔ published via `link_versions` → row `version` (tag only, no `versions` merge). `create_new` skips `exists` / `version`. | Re-scan the library on every reference hop; title+year `held_divergent_title` logic |
| **Hygiene `dedupe`** | Operator schedule (between batches or after a messy week) | Classify DOI groups and title+year packs; `--apply` merges extras onto a keeper. | Run automatically at snowball exit |

#### Timeline through one run

```text
seeds → hops (OpenAlex / filters)
  → crawl _dedupe (work identity, all hops so far)
  → fill / overlap / truncate
  → read library per dedupe_scope → _mark_exists on every row
  → write queue (dry-run / approve-batch) OR create_new (writing gates)
```

- **Dry-run and `approve-batch`** still perform the library fingerprint before
  `candidates.jsonl` is written, so the table’s “in library” column is the same
  signal `auto` would use later. Editing `keep=true` on an `exists` row does not
  create a parent; `create_new` skips it.
- **`snowball apply`** reloads the queue, re-runs `_mark_exists` against the
  **full library** (not the profile’s `dedupe_scope`), then creates only rows
  still `status = new`. A second apply skips DOIs already written from that
  queue. If you imported parents elsewhere between dry-run and apply, they show
  up as `exists` on apply — that is the main “ongoing” safety net for delayed
  gates.
- **`snowball resume`** after an OpenAlex budget pause merges new neighbours with
  `_dedupe` into the on-disk queue and re-runs the library fingerprint before
  optional `auto` create. **`resume` on a finished queue** (no
  `deferred.json`) re-marks `exists` (full library unless `--dedupe-scope`)
  before create/PDF continue.
- **`snowball watch`** is a second ongoing filter: baseline stores every work
  identity from the first profile run in `state/snowball/watches/<name>/seen.json`.
  Later runs still use the profile’s `dedupe_scope` during the crawl, but only
  rows that are `status = new`, not already in `seen`, and (on non-baseline runs)
  unseen since baseline land in `inbox.jsonl`. Library `exists` rows never become
  watch proposals even if the watch ledger has not seen that DOI yet.

#### `dedupe_scope` (config and profiles)

| Value | Fingerprint against | Typical use |
| --- | --- | --- |
| `library` (default) | All parents the backend can list | New topic collection; avoid duplicating anything you already own |
| `collection` | Parents under target `-C` only | Deliberately re-fetch metadata for works already filed elsewhere; **same DOI outside `-C` can still be created** |
| `none` | Skipped (yellow log) | Scout-only queues; `auto` / `approve-each` still refuse create if the library cannot be opened |

Persist with `snowball profile save --dedupe-scope …` or `[snowball].dedupe_scope` /
`profiles/*.toml`. CLI `--dedupe-scope` overrides per invocation on crawl
commands, `run`, `resume`, and `watch run`. `apply` stays full-library unless
that flag is passed on apply.

Indexed lookup (when the backend exposes `items_in_scope`) also maps arXiv IDs and
`preprint DOI:` lines in Extra into the DOI index, aligned with dedupe’s DOI
normalisation. The Zotero fast path uses `find_top_item_key` (DOI-first; title
fallback without the full title+year index).

#### Operator loop (large corpus + watch)

Recommended rhythm when snowball is actively growing a collection — same spirit
as the **Large corpus from scratch** worked example under [Documentation
(thicken)](#documentation-thicken):

1. **Pre-flight** — `dedupe -C <target> --dry-run` on the slice (or `--library`
   if the topic bleeds across collections). Fix obvious DOI collisions before
   the crawl so `exists` counts are trustworthy.
2. **Scout** — profile with `gate = dry-run`, `dedupe_scope = library`, realistic
   `max_candidates` / hop caps. Read `state/snowball/<run-id>/candidates.jsonl`
   (`exists_match` → `item_key`, `doi`, or `title_year`).
3. **Write** — `approve-batch` + `snowball apply`, or `gate = auto` on a named
   profile after one dry-run. Expect `skipped_exists` in the run report.
4. **Post-batch hygiene** — after `fetch_pdfs` / `run` stragglers, `dedupe` again
   on `-C` (title+year stragglers often appear here, not in snowball).
5. **Frontier** — `snowball watch save` / `watch run` on the same profile;
   review `inbox.jsonl`, then apply or manual import; watch does not download
   PDFs.

`paperful all` does not insert dedupe or snowball; chain explicitly (see
[workflows.md](workflows.md) fill recipes).

#### Why duplicate parents can still appear

- **`collection` scope** — fingerprint misses the same DOI in another collection.
- **`none` or unread library** — queue rows stay `new` until a later apply with
  a readable backend.
- **Stale queue** — manual edits, or apply long after dry-run without re-apply’s
  fresh `_mark_exists`. Resume-after-budget merge re-fingerprints before
  `auto` create; delayed apply still defaults to the full library.
- **Title+year blind spots** — missing year, `(untitled)`, HTML/title drift:
  snowball may create a second parent; `dedupe` may **hold** divergent titles on
  the same DOI instead of merging.
- **Parallel snowball or manual ingest** — two creates for one DOI before either
  run’s fingerprint; second wins only if apply re-check runs.
- **`version` vs merge** — preprint and version-of-record stay two parents unless
  you run `paperful versions` / `dedupe --apply`; snowball only marks `version`.
- **Same bytes, two parents** — [`attachments`](commands.md) / `dedupe`, not
  snowball.

#### Parked (snowball lane — thicker “ongoing”)

- **Align `snowball apply` with saved `dedupe_scope`** — apply still defaults
  to full-library fingerprint; `--dedupe-scope` on apply is the override.
- **In-run create index** — while `create_new` runs, feed new keys/DOIs back into
  the fingerprint so a single `auto` batch cannot create the same DOI twice if
  the queue had duplicates reintroduced by hand.
- **Manifestation-aware identity** — work ↔ preprint ↔ VoR graph (**Identity /
  resolver graph**, Maybe later §3); snowball keeps skip-only semantics.

Still outside this lane: every paper by every cited author; a snowball step
inside `paperful all`; a built-in scheduler; a review UI; systematic-review screening;
Sci-Hub or Google Scholar as snowball sources. The Discover map
(`paperful.citation_graph.v1`) is a view of one queue, with one-hop expand.
Post-1.1 buffet for stopping rules, drift cache, PRISMA counts, SnowBallSLR
interop, and a possible systematic-review mode —
[Snowballing and review methods](#after-110-snowball-review),
[Bigger bets](#after-110-bigger-bets).

**OpenAlex snapshot store (opt-in).** Most installs use the live API only.
Institutions (or a personal homeserver) may host an [OpenAlex parquet
snapshot](https://help.openalex.org/access/snapshot/) and point
`[openalex_store]` at it. Architecture: a `WorksStore` transport behind
`OpenAlexClient` — not an entry in `snowball_backends`.

- **v1 (shipped):** `ssh_duckdb` and `local_duckdb` — DuckDB over a parquet
  snapshot (remote SSH or this machine). Covers `work_by_doi` /
  `works_by_dois` / `works_by_ids` with API fallback for misses; when the API
  daily budget is spent, DOI/id reads keep using the store. Docs:
  [config Advanced](config.md#openalex-api-limits-and-snapshot-store),
  [snowball Advanced](snowball.md#advanced).
- **2B (shipped):** inverted cites index (`paperful openalex-store build-cites`
  + `cites_index_glob`) for store-backed `works_citing`; title-only
  cites-query / `search=` on citing and id batches. Abstract/fulltext search
  remains live-API / 2C.
- **Post-1.0 (2C):** keyword / ORCID / full `search` parity; `http` backend for
  campus hosting without SSH. **Park** until an institution asks —
  [Parked](#after-110-parked).

OpenAlex **topic** classifier change (13 Jan 2027): nothing in Paperful
breaks; housekeeping and topic-native watches are
[OpenAlex topics](#after-110-openalex-topics).

## Maybe later, not core

Workbench layers beyond the mirror contract. Worth keeping on the map; not
prerequisites for the fetch / lint / attach loop.

1. **Catalogue unification** — conflict journal; query-scoped virtual collections
   as run scopes. Mendeley and EndNote adapters exist and are seeking testers
   (above). Treating every manager as an equal is still later.
2. **Acquire beyond journal PDFs** — **shipped:** local session vault
   (`paperful session login`); soft-blocked OA → vault retry (Core above);
   manual handoff / PDF inbox (`--handoff`, `inbox watch` / `drain`);
   **pluggable grey-lit PDF playbooks** in
   `direct`/`landing` with builtin packs (UNGA/undocs · BBNJ/DOALOS · ISA;
   plus FAO, RFMO, IUCN/DOSI, IDDRI/Pew). IEA/IRENA and OECD/WHO/UNEP/UNDP
   are optional files in `paperful/data/grey_playbooks_examples/` — extend
   via `grey_playbooks_dir` or `[[grey_playbooks]]`. **Shipped:**
   **inbox match ladder**, **inbox create-on-unmatched**, and **smart inbox**
   routing (config; snowball/recent-run context + ladder signals; LLM
   `off` | `when_thin` | `always`; gated or auto). Still parked:
   SI/dataset/code siblings;
   **opt-in LibGen** for `book` / `bookSection` gap-fill (title or ISBN routing;
   unofficial scrapers only — spike
   [libgen-api](https://pypi.org/project/libgen-api/) /
   [libgenesis-api](https://pypi.org/project/libgenesis-api/) first; same
   opt-in + disclaimer bar as Sci-Hub; no third-party HTTP gateways;
   **park** until testers ask — [Parked](#after-110-parked));
   **opt-in SearXNG** for author / personal-site / institutional-repo PDFs that
   Unpaywall / OpenAIRE / CORE never indexed. **Shipped** as author-site
   remainder search against `[searxng].base_url` (your instance, or a public
   one that serves JSON — [Twenty and SearXNG](snowball.md#twenty-and-searxng)).
   Not a default `run` source. Reuse the fetch +
   engine-rotation + disk-cache pattern from folk directory
   `ingest/scrape_searxng.py`; do not port the county×event grid. Query by
   title/author/`filetype:pdf` (or DOI), hand URLs to the existing download +
   PDF-identity checks.
   Same bar as legacy opt-in `scholar` on `run`: never in `DEFAULT_SOURCES`,
   circuit-breaker / sleep so fill runs do not burn the instance, CAPTCHA/empty
   engines are misses not hard fails. Wins when the PDF lives only on a personal
   page; complements handoff tabs rather than vault Scholar replay.
   **Field example (mesopelagic run, 2026-09):** Mendenhall 2024 missed every
   scripted lane; a web search surfaced a **direct PDF** on the author’s personal
   site at **result ~3** — not in Unpaywall-style indexes. The download URL’s host
   or path often carries the author surname (cheap **deterministic** match against
   `creator` / `lastName` before any LLM). Spike: rank SearXNG (or SerpApi web)
   hits with that host/token rule + `filetype:pdf` / `.pdf` suffix, then existing
   PDF-identity checks; log provenance as `grey:author_site` (or similar), not OA.
   **Author-site registry (grey; learned over time).** Successful personal-site
   fetches should accumulate a **local** map of “how to get this author’s PDFs” —
   not a hosted service. Keys: OpenAlex / ORCID author id when the item has one;
   else normalized name fingerprint (`last|first_initial` + optional affiliation
   host). Values: `base_host`, optional listing URL or path pattern, last-good
   direct-PDF URL or slug rule, `verified_at`, attach stamp `grey:author_site`.
   Feed from `state/fetch-wins.jsonl`, inbox/handoff saves, and operator
   `playbooks propose` / `promote` (same gated `learned.toml` posture as host
   grey packs — author-scoped rows, default propose-not-auto). On later misses,
   consult the registry **before** burning a web-search quota; treat hits as grey
   `direct`/`landing` playbooks, not OA. `doctor` ambers on stale entries; no
   silent promotion of third-party mirrors into the registry.
   **Field author packs (priority when names match).** Group registry entries into
   **packs** tied to keywords, topics, or `-C` / snowball profile scope (e.g.
   `ocean/mesopelagic` → authors seen often in that collection or seeded from a
   research pack). When a miss’s `creator` list intersects a pack active for the
   current run scope, **boost** that author’s site playbook and web-search rank
   (try known `base_host` before generic SearXNG). Packs are operator-owned files
   under `state/author-packs/` (or profile refs), mergeable from corpus stats
   ([authors/orgs frequency report](#near-term-research-ops) row 12 —
   `paperful authors -C … --apply`) plus manual curation — not an auto cloud
   graph. Same honesty: grey only, no OA mislabel.
   **Co-author expansion on personal sites.** Learn **frequent co-author** edges
   from in-library items (creator lists) and from bibliography / OpenAlex ref
   overlap; link co-authors to the same pack when they repeatedly co-publish in
   scope. When author **A** has a verified publications page, a miss on a paper
   where **B** (or C…) is on the item but only **A** is in the registry can still
   try **A’s site** — scan listing HTML/PDF links for title/DOI match to the
   target work (deterministic string match first). One site fetch may attach PDFs
   for several names on the author line; stamp which name triggered the lane.
   Co-author hints are suggestions until a win promotes them into the registry;
   disambiguate common surnames with ORCID / affiliation host when available.
   **Snowball preflight (co-author graph → author sites). Shipped**
   (opt-in; [snowball.md](snowball.md) / snowball phase 7): when `snowball`
   runs (dry-run or before `fetch_pdfs`), build a **co-author graph** from
   seeds, queue rows, and OpenAlex author ids; rank nodes by frequency in the
   frontier. For top authors, run bounded discovery (ORCID researcher URLs,
   optional CRM listing, then SearXNG remainder) to find faculty, GitHub Pages,
   Weebly, and similar **simple** hosts — then write a **proposed** field pack
   for that profile’s `-C`. Promote with `snowball packs promote` before
   `grey:author_site` fetch. Caps on authors/queries; no auto-promote. Complements
   post-hoc co-author site crawl on misses (still later, above).
   **ResearchGate “request from author” (config-gated, handoff-only).** When the
   item already has a `researchgate.net/publication` URL and `[request].channels`
   includes `rg`, `--handoff tabs` / `walk` on `gaps` / `run` / `paperful reachout`
   opens that page in the **system**
   browser. **You** click Request full-text. Paperful never automates the click
   (RG ToS / rate limits) and never searches ResearchGate for a URL. Fulfillment
   is async (email from authors). Ledger: `state/author-requests.jsonl`.
   `reachout` is the contact-only verb (no grab modalities; CSV of emails).
   **Twenty CRM (opt-in, shipped).** Lookup, sync, late `author_site`, and
   listing write-back are [Twenty and SearXNG](snowball.md#twenty-and-searxng).
   Paperful does not send mail. **RG vs email:**
   both channels can annoy the same author if mis-timed; treat as a **policy**
   knob, not one hardcoded path — e.g. `request_channels = rg | email | both |
   rg_then_email_after_days` with per-item “already requested” ledger
   (`handoff_opened` records channel + date). Email may cut through
   inbox noise when RG requests are ignored; RG may be faster when the author is
   active there — operator chooses. CRM writes stay on `twenty sync --apply`
   and `--twenty-writeback`; lookup stays read-only.
   **Marketing copy (later — ship only when the lanes above exist).** Draft
   positioning for site / README / comparison once learned grey playbooks,
   author-site registry, field packs, and co-author site crawl are real (local
   disk, not cloud training):

   > Paperful improves over time: it learns where the grey literature lives in
   > your field, remembers easy-to-access sources from your previous runs, and
   > keeps a list of authors with personal sites — and their co-author network —
   > so it can fetch co-authored papers from pages you already trust.

   Honesty bar: “learns” = your machine’s `state/` + promoted playbooks, not a
   shared model; grey and campus paths stay stamped; no implication of paywall
   bypass or universal completeness.
3. **Identity / resolver graph** — work ↔ version ↔ preprint; scored patches with
   undo; citation ingest; manifestation-aware dedupe. Collection DOI / title+year
   trash is already `paperful dedupe`. Snowball only **skips** rows that match
   those fingerprints before create ([Snowball — dedupe during snowball](#dedupe-during-snowball--ongoing-prevention-not-merge-after));
   it does not trash or merge existing parents. Preprint ↔ version of record is
   `paperful versions`: the older parent keeps the published citation and PDF,
   and the preprint stays as a version (snowball may tag a candidate `version`
   without running that merge).    **Shipped (research-ops):** `paperful ingest-dois --from-file dois.txt -C BBNJ
   --dry-run` then `--apply` (resolve Crossref/OpenAlex; skip `exists` under
   dedupe scope; report created / exists / unresolved / **held** on ambiguous
   title mismatch; repeatable `--tag` / `[ingest].default_tags`; hand off
   to `run` for PDFs). **Shipped:** `paperful collections add --keys-file keys.txt
   -C …` — membership-only batch (dry-run / apply; added / already-in /
   not-found). Complements `ingest-dois` (create parents) vs add (file existing
   keys). No scheduled bot inside Paperful. **Grey identity:** fingerprint
   `norm(title)|year|registrant_host` (plus ISBN/report number when present) for
   snowball / dedupe / inbox-create when DOI is absent.
   Growing a library from a keyword, one or more DOI bibliographies, or one or
   more ORCIDs is the
   [Snowball](snowball.md) section above, not a line item inside this graph.
4. **File & attachment OS** — **shipped (Zotero):** `paperful attachments`
   reports ghosts, broken links, same-file duplicates, and filename drift.
   `--fix-broken`, `--merge-files`, `--rename`, and `--link` write only with
   `--apply`, and only from files already under `out/`. `--link` is the
   stored-to-linked cutover and is refused for group libraries. The quiet
   mirror stays a dual `imported_file` store unless you pass `--link`. Still
   parked: full wrong-paper triage, orphan GC of unreferenced
   `storage/` files, author folders, and tablet send/get. **Shipped (slice):**
   one-page density gate — sparse stubs soft-reject and keep searching; denser
   one-pagers hold for `attach --allow-short-pdf`. PDF annotations and
   a full CSL dump are still later. A text layer for scans is `paperful ocr`.

## Maybe later

Larger product bets. Park until the ledger and core loop justify them.

5. **Reading & knowledge** — local full-text index; annotation sync;
   evidence packs; briefs grounded only in local PDFs. **Planned (see Optional
   LLM + subsections above):** [Zotero-RAG
   integration](#zotero-rag-integration-later-question-centric-layer);
   [EmbeddingGemma 2](#embeddinggemma-2-local-embeddings) (optional stronger
   offline embedder; text spike before any vision path);
   [bibliography gap scan](#bibliography-gap-scan-later-not-gaps) (cited-but-not-owned,
   distinct from shipped `gaps`); [structured section
   extract](#structured-section-extract-mvp-shipped) (shipped —
   `extract-sections`); [annotation
   mirror](#annotation-mirror-later); [frontier
   digest](#frontier-digest-later-watch--external-ingest) (watch rollup shipped;
   alert loop + what-cites as [`keepup`](keepup.md)); [author watch
   lists](#author-watch-lists-later-people-you-follow--their-papers) (shipped;
   saved social HTML/CSV import; live scrape still out). **[Run
   witness](#run-witness-shipped-trust-thicken)** (shipped) ties batches to
   config/model/index for reproducibility.    Post-1.1 buffet for grounded
   living briefs, summaries with receipts, Ask-as-claim-check, and
   Edison-shaped conflicting-evidence / review layouts over **held** PDFs —
   [Summaries, briefs, and Ask](#after-110-briefs-ask),
   [Hosted AI scientists](#after-110-edison-scientific).
6. **Writing & export** — CSL / BibLaTeX / Quarto sync; living review / gap lists;
   git-friendly CSL-JSON dumps; [briefing ↔ collection coverage](#briefing--collection-coverage-shipped-sibling-of-refs-gap)
   (shipped thin slice of parked “gap lists,” collection-scoped only).
   **Park CSL/Quarto as a Paperful feature** — point people at Better BibTeX
   until testers ask — [Parked](#after-110-parked).
7. **Agent surface** — MCP + CLI sharing one capability API; dry-run defaults;
   typed source/policy permissions; playbooks. **Shipped (CLI convenience,
   not a GUI):** named run configs and `paperful all` repeat a collection /
   year / type sequence (`profiles/*.toml`). Those are not grey-lit playbooks.
   **Shipped (opt-in):**
   [browser-use](https://github.com/browser-use/browser-use) as a *recovery*
   lane: last serial source on `run` after EZProxy / htmlpdf fail (today still
   after opt-in `scholar` until that source leaves core)
   (`[llm].enabled` + extra), and `paperful recover --item` for named keys.
   Never in `DEFAULT_SOURCES`, not “AI fetch everything.” Soft bot walls may improve with
   their Cloud stealth (not wired); hard CAPTCHAs stay human (see CAPTCHA
   open questions under Optional LLM). Vault fetch follows
   meta PDF links and SSO hops without an LLM. Successful vault and agent fetches
   log to `state/fetch-wins.jsonl`. `paperful playbooks propose` / `promote`
   install user-owned recipes in `grey_playbooks_dir/learned.toml` (default
   `gated`; `auto` is opt-in and can promote flukes). Learned packs are not
   shipped in the wheel. Still later: second-model fallback on agent failure
   (LLM section); playbook health / expiry; win analytics rolled into the run
   report (which hosts / win kinds paid off); **allowlisted extensions** on the
   vault profile for agent ergonomics (see Optional LLM — extensions bullet);
   **user-agent switcher** spike (CAPTCHA open question #3 under Optional LLM)
   for between-item or mid-run rotation vs stable profile UA; **later** a
   small opt-in HTTP TLS impersonator on scripted fetch only (question #4;
   not Scrapling, not a CAPTCHA product). **Shipped:** `--format json`
   (`paperful.agent.json.v1`) on batch verbs (`run`, `refs gap`, `coverage`,
   `ingest-dois`, `inbox drain`, `ask`, snowball crawl/apply, …); documented exit-code
   table (`0` ok, `1` user, `2` manager down, `3` partial write batch). **MCP** is a thin
   optional stdio wrap of `refs_gap` + `ask` over the same envelope — not a second API
   and not a prerequisite for research-ops. (`coverage` is CLI `--format json` only.) **Literature-discovery complement shipped**
   (waves 1–4): read-only MCP for `gaps`, snowball preview, `snowball_trends`,
   `export`, `proposal_export`, `precedent`, plus `export-proposals`, `snowball trends`,
   thickened `authorwatch briefing`, and `paperful precedent` — [Literature-discovery complement](#literature-discovery-complement-waves).
   **Wave 4 (shipped):** `paperful precedent` / MCP `precedent` — held vs
   `public-metadata-only`; never a novelty claim.
   Writes stay CLI `--apply`. `collections add` is CLI-only (not an MCP tool).
   **Shipped:** Twenty sync, lookup, and `--twenty-writeback` —
   [Twenty and SearXNG](snowball.md#twenty-and-searxng).
   Request-channel policy stays config (`[request].channels`), not agent-default.
   Contact surface without fetch is `paperful reachout` (CSV + optional RG tabs).
8. **Collaboration without SaaS** — shared `state/` over syncthing/git; attach
   locks; optional headless fetch node. Aligns with the house
   [quiet mirror](quiet-mirror.md) stance: Syncthing (or similar) is transport;
   Paperful stays a local workbench, not a sync product. The first mechanisms
   (`mirror diff`, a file lock around attach) are
   [two folders](#after-17-two-folders). A headless fetch node waits until
   two processes have actually clashed.
9. **Compliance & provenance** — 1.0 attach stamp is listed above. On disk,
   `record.json` plus `out/_history.json` are the chain-of-custody note for
   the library and the append-only ledgers. OA `license` / `oa_status` /
   `version` stamps (Core above) feed this lane; which fields are written stays
   config-driven. **[Run witness](#run-witness-shipped-trust-thicken)** extends
   run reports and packs with config/model scope. Still later: optional
   redistribution / license gate using those stamps, more jurisdictional
   presets, and PDF annotation export (annotation **mirror** is read-sync into
   `out/`, not export-only).

## Explicitly out of near-term scope

- Hosted multi-user service
- Replacing Zotero as a reading UI
- Shipping Sci-Hub or proxy abuse as defaults (opt-in + presets stay as today)
- Jeffersonian transcription / qualitative coding apps
- Autonomous AI-scientist loops (Kosmos-class world models, multi-hour code
  execution, publication-from-dataset), experimental-data pipelines
  (RNA-seq / flow cytometry kernels), and molecular design (ADMET /
  retrosynthesis). Point people at [Edison Scientific](https://docs.edisonscientific.com/)
  or similar; keep Paperful on library / find / completeness / mirror / control
  — [Hosted AI scientists](#after-110-edison-scientific)
- Journal-ready manuscript generation, Deep Research memos as a product, or
  “overnight PhD” copy — [v2 factory](#after-110-paper-factory)

## Optional thin bridge — Firefox extension (post-1.0)

**Status:** implemented, unsigned, temporary add-on. Not a 1.0 gate and not a
replacement for the Zotero Connector. Operator notes: [firefox.md](firefox.md).

The add-on saves the current page or selected tabs into the quiet mirror.
Identity is the mirror plus a live Zotero read, so a stale snapshot does not
create a second item. `[extension].snapshot = auto` (default) refreshes `out/`
once first. Writes stay on disk: no `create_items`, no attach. Transport is
native messaging to `paperful capture --stdio`. PDF bytes go to a drop
directory; the host receives a path (and will copy a just-downloaded file from
Downloads into that drop dir). Pirate hosts are refused. Snowball and
gaps `--handoff tabs` / `walk` write `state/handoff/session.json`, which the
tab checklist pre-checks (URL or DOI). Review selected plans each tab before
apply. Context menu, Alt+Shift+P, collection picker, capture notes, and
open-folder / Wanted links shipped in add-on 0.2. Starting a snowball from the
toolbar is not this cut. AMO signing is not this cut.

## Documentation (thicken)

**Status:** walkthroughs and workbench screenshots shipped
([Walkthroughs](walkthroughs.md), `docs/_static/workflows/`). Reference docs
remain; keep them aligned with the GUI.

Ship in layers:

0. **First 10 minutes** — one page that uses the **same labels as the GUI**
   (Wanted, Held, Grab, Attach, the `out/` folder on this computer). Walkthroughs
   exist; this is the stranger door that matches first-hour copy in
   [1.1.1](#after-110-1-1-1) and [Docs as product](#after-110-trust-gaps).
1. **Research pack playbook** — [research-pack.md](research-pack.md) (narrative spine for `-C` topic builds):
   seed greys + seed papers → `refs gap` → `ingest-dois --dry-run` → `--apply`
   with provenance tags → `run` / handoff / inbox for PDFs → `dedupe` hygiene →
   optional `snowball watch` + [frontier digest](#frontier-digest-later-watch--external-ingest)
   → `summarize` / RAG only after the ledger is honest.
2. **Example commands and templates** — copy-paste invocations plus
   `profiles/*.toml` and config snippets for recurring flows: `-C` / collection
   scoping, `--dry-run` → `--apply`, `paperful all`, snowball profiles and
   gates, `[inbox].dir` handoff, `session login` (Zotero / Mendeley / campus
   vault), and `[llm]` gates spelled as one-liners with expected exit codes.
3. **Worked examples** — **Shipped (workbench):** [Walkthroughs](walkthroughs.md)
   ([first fill](first-fill.md), [grow](grow-library.md),
   [tidy](tidy-library.md)); [research-pack](research-pack.md). CLI depth for
   hop gates and `paperful all` stays [workflows](workflows.md) /
   [snowball](snowball.md). Remaining: a side-by-side **full** fetch (EZProxy
   relogin, browser-agent, handoff walk / inbox) as its own page.
4. **Screenshots and video guides** — **Shipped (stills):** workbench Wanted,
   Discover, Repair, Index, Index Ask, System, Mirror (`docs/_static/workflows/`;
   homepage copies under `website/images/`). Recapture:
   `scripts/docs/capture_workbench.py`. Remaining: dry-run table callouts,
   Zotero provenance, short screen recordings.
5. **Developer guide** — [developer.md](developer.md). **Shipped:** the
   mirror-first rule, what a command's backend serves from disk, rules for
   new code, the module map, the refresh, disk schemas, and how to add a
   verb, a source, or an adapter method. Keep it current when a rule or a
   module boundary changes.

Keep new pages linked from README and [commands.md](commands.md); avoid a
second doc tree that drifts from the CLI.

## Related docs

- [architecture.md](architecture.md) — disk-first adapters, the mirror-first rule, and data flow
- [why.md](why.md) — library, find, completeness, mirror, control; what is true today
- [quiet-mirror.md](quiet-mirror.md) — `out/` as the copy you keep
- [releases.md](releases.md) — 1.0 contract; known limits
- [comparison.md](comparison.md) — what Paperful does and does not replace today
  (Zotero plugins, Valency, Edison, Elicit/Consensus, SR tools, writers)
- [comparison-reference.md](comparison-reference.md#paper-factory-stages) —
  factory-stage matrix (Oct 2026)
- Repo `reports/AI academic paper factories.md` — contributor research behind
  the matrix (not user-facing)
- [snowball.md](snowball.md) — library-building from a keyword, multi-DOI / multi-ORCID, or collection
- [bbnj-author-lanes.md](bbnj-author-lanes.md) — dogfood `author_site` + `authorwatch` on `ocean/BBNJ` / `ocean/BBNJ-test`
- Site career / domain timeline plan (consumer of durable tags):
  `/Users/89298/Documents/website/glen-w.github.io/docs/dev/career-timeline-plan.md`
- [firefox.md](firefox.md) — optional Firefox add-on; mirror writes, Zotero read
- [After 1.7 (live map)](#after-17-live-map) — what to build next
- [After 1.1.0 (area index)](#after-110-buffet-by-area) — jobs by area;
  many rows shipped

## GUI

**1.0 deliverable** — workbench (open / Docker first): [gui.md](gui.md).
**Shipped:** `paperful.item.v1` lock, `paperful serve` HTTP + server-rendered UI
under `paperful/ui/` — default nav **Wanted** (also `GET /`), **Discover**, **Ask**,
Preview → Grab (fetch to `out/`; Attach is manual by default, or automatic via `[ui].attach_mode`), with
review tokens and command ids under `state/gui/commands/`; Activity run-status
SSE on `GET /v1/runs/{id}/events`. Empty Wanted shows a
coach line when there is no collection or the library is down. Discover covers topic
queues (keep/skip, briefing, digest, profile run, resume, watches), people
lists (create/add/resolve/run/import/suggest/accept, inbox apply), and Advanced grow tools
(refs gap, ingest-dois, authors, packs promote). Queue/watch briefing and
digest can file a collection note (`paperful:frontier-briefing`). **Advanced**
(cookie) reveals Repair, Mirror, Index, Briefs, Settings and extra form fields
without enabling opt-in sources. Repair/Mirror Preview is dry-run; Apply uses
the same entrypoints as the CLI. TTY (`session login`, `doctor --guide`,
mid-run EZProxy), `collections add`, `approve-each`, and Sci-Hub stay CLI.
Screenshots: [Walkthroughs](walkthroughs.md).

The CLI stays the source of truth; the GUI marshals the same verbs with dry-run
default and explicit Apply. Not a second fetch stack or Zotero’s reader.
The optional [Firefox add-on](firefox.md) saves pages into the mirror and
does not attach.

Post-1.1: **Wanted excellence foundation is shipped** (stamps, hand-ticks, miss
reasons, Waiting→add). The next workbench surface is a Since block on
Activity, and only after the CLI pack is used —
[habit](#after-17-habit). Whether Ask stays on the default nav is
[open](#after-17-questions), and the test is claim-check usage.

**Ask (default nav, opt-in):** **Shipped** — `/ask` runs scoped chat with citations
when `[llm]` and `[rag]` are on and the index has rows. Mode (`simple` /
`advanced`) starts at `[rag].ask_mode` and is this run only. Collection chip is
the scope; threads live under `state/rag/threads/` (same as `ask --thread`).
Batch Ask (item/year/type/top-k/force, custom prompts, same Mode select) is on
that page when Advanced is on. **Index** (Advanced) runs `rag ingest`,
`rag search`, `rag questions`, and `rag answered`. **Briefs** (Advanced) runs
`summarize` and `synthesize`. CLI `ask` remains for scripts, TTY multi-turn,
`--ask-mode`, and run profiles.
See [Zotero-RAG integration](#zotero-rag-integration-later-question-centric-layer).
**Stuff** (Advanced, shipped): per-sentence `rag search`, no Ask chat
([`stuff`](#stuff-later-extra-citations-from-the-library)). `--apply` stays later.
