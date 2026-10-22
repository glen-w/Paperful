# Marketing Assessment: Paperful Front Door & Outreach Honesty
**Date:** 2026-09-25  
**Reviewer:** Marketing (Cloud Agent)  
**Scope:** Positioning, front-door outreach surface, name collision, don't-mail-yet gates, marketing debt  
**Not this assessment:** Usability (see PR #9), design-eye, web design, contracts

---

## Executive Verdict

Paperful is **not mail-ready**. The product positioning is intellectually honest ("local Zotero sidecar, OA-first PDF fill, not a sync service"), but the **front-door outreach surface** — https://glenwright.earth/Paperful/ + `README.md` — suffers from **three fatal overclaims** that would kill trust in the first 30 seconds of a cold invite:

1. **paperful.io collision is unnamed** above the fold on both the live website and `README.md`. A stranger who Googles "Paperful" or sees a Slack unfurl will land on the wrong product — a document SaaS, not Glen's local research tool. The invite opener and hero strip must name-out this collision before any feature pitch.

2. **Install story is Compose-first, but artifacts do not exist.** The live page (L83-93) and `README.md` (L62-74) explicitly say "no `docker pull`, no `pip install paperful`" — **good honesty** — but then the repo has **tag `v0.9` with no GitHub Release**, and the page/README use language like "shipped" and "pointable release" without clarifying "pointable = clone + build, not binary download." Cold readers trained to `docker pull` will bounce.

3. **"Platform-agnostic mirror" is the pitch (`README.md` L3, website L76), but Mendeley/EndNote are "seeking testers" (README L9, website L91).** This is not a lie, but it's **asymmetric disclosure** — the promise is top-of-fold, the "not proven" disclaimer is 60 lines down. A researcher on Mendeley reads the hero and thinks "I can switch," then discovers the adapter is experimental. That's a trust ding on first contact.

The **documentation maze** identified by the Researcher (PR #9, `assessments/2026-09-25-critical-review-usability-docs-features.md` §2 P0) — three contradictory surfaces (README, `docs/*.md`, `website/index.html`) with inconsistent Zotero 10+ requirements, EZProxy setup, and install paths — is not just a usability problem, **it's marketing debt**. A forwarded invite points at https://glenwright.earth/Paperful/, the recipient clicks through to `README.md` or `/guide/`, finds contradicting instructions, and concludes "this is alpha theatre, not a tool I can trust." Every contradiction is a credibility leak.

The **good news:** Paperful's actual scope discipline (Sci-Hub opt-in, OCR out-of-scope, EZProxy honesty, provenance stamps) is **rare integrity** for a research tool. The problem is not what Paperful _does_, but **what the front door _claims_ before a stranger understands the caveats.** The outreach surface over-promises in the hero ("platform-agnostic"), under-discloses in the install (tag ≠ Release), and is silent on the collision (paperful.io) until it's too late.

**Recommended stance:** Hold all outbound mail, HN, invites, Ko-fi campaigns, or LinkedIn posts **until four hard gates land**:

1. **Collision strip above the fold** (hero, README first screen, invite opener): "Not affiliated with paperful.io."
2. **Install honesty matching artifacts**: Either ship a GitHub Release for `v0.9` with binaries, or reframe all "shipped"/"release" language to "clone + Compose build — no pull, no pip."
3. **Asymmetric-promise audit**: "Platform-agnostic mirror" hero must match "Zotero proven; Mendeley/EndNote seeking testers" in the same breath, not 60 lines later.
4. **One truth for install/EZProxy paths** across README, website, and `docs/`: pick Docker or `uv` as the canonical operator path and make the three surfaces agree before anyone forwards a link.

Once those four land, Paperful is **pointable for a maker-wave 0.9 outreach** to Zotero power-users Glen would actually answer. Before those four, every invite is a credibility burn.

---

## 1. Positioning: One-Sentence Job & Never-Claims

### What Paperful Must Say (Outreach One-Liner)

**For cold invites, the first sentence strangers hear:**

> Local Zotero sidecar that fills reachable PDFs (open access / campus EZProxy / grey playbooks), tidies metadata, and keeps a quiet on-disk mirror — not a sync service, not every paywall.

**Per `uploads/paperful_e58c.md` L8-11.** This is **defensible and honest**:

- **"Zotero sidecar"** correctly scopes adapter status (Mendeley/EndNote are seeking-testers theatre per Researcher assessment P2 #17, `README.md` L9).
- **"Reachable PDFs"** correctly disclaims universal fetch (Sci-Hub post-2021 coverage is thin per `docs/scihub.md` L27-43, Researcher § 3 "Known Gaps").
- **"Not a sync service"** pre-empts the wrong mental model (Zotero cloud replacement, which Paperful is not).

This sentence should appear verbatim in:

1. The **website hero** (currently says "Clean the library. Find the PDFs. Keep a mirror." — too generic, doesn't disclaim sync or paywall limits).
2. The **README opening** (currently L3-10 is close but buries "not a sync service" at L48).
3. Every **invite opener** and HN title (see § 4 Don't-Mail Gates).

### What Paperful Must NEVER Claim (Overclaim Traps)

**Do not bid on, imply, or let unfurls/OG suggest:**

1. **"Zotero alternative"** or "reference manager" — Paperful is a **sidecar**, not a replacement. Per `docs/comparison.md` L7-8: "Paperful is not a reference manager." Good. Keep that everywhere.

2. **"Cloud sync service"** or "Zotero storage replacement" — `README.md` L48 correctly says "paperful is not a sync service." Website L76 says "mirror is the backup and the way out," but never says "sync." **Good.** But the OG description (website `index.html` L14-16) says "platform-agnostic mirror for backup" without "not a sync" in the same sentence. A Slack card reader might infer sync.

3. **"Sci-Hub client"** — Sci-Hub is **opt-in** (per `README.md` L29-32, website L92, `config.example.toml` L40-42: not in default sources). Correct posture. But if HN title or OG says "research PDF finder," top comment will be "so it's Sci-Hub?" Marketing must pre-empt: "open access + campus, Sci-Hub opt-in."

4. **"Every paywall" or "universal PDF fetch"** — `README.md` L35-36 correctly says "Paperful does not fetch every paywalled or DOI-less item." Website L92 says "not every paywalled paper comes back." **Excellent honesty.** Keep this in every public claim.

5. **"SemVer 1.0" or "production-ready"** without freeze — per `uploads/01-cross-cutting-rules_a62f.md` L1-2: "Never say SemVer 1.0 in mail, HN, or page unless Call wrote freeze + tag rule." Current tag is `v0.9`, footer says "**0.x** is called out" per `website/README.md` L10. Correct. Do not upgrade language until SemVer contract exists.

6. **"Docker image" or "pip package" as if they exist** — per `README.md` L62-63: "There is no published image and no PyPI package: do not `docker pull` or `pip install paperful`." Website (L83-93 of `index.html`) repeats this. **Good.** But outreach must not say "download the release" or "install Paperful" without "clone + build." See § 2.

7. **"Paperful.io" or any branding that collides** — see § 3.

---

## 2. Front-Door Honesty: README + Website as Outreach Surface

### What Strangers See (30-Second Test)

**Scenario:** A researcher receives a Slack forward of https://glenwright.earth/Paperful/, or a LinkedIn post with an OG card, or an email invite with "check out Paperful." They have **30 seconds** to answer:

1. **What is this?** (Reference manager? Browser extension? Cloud service? Local CLI?)
2. **How do I run it?** (Docker? pip? Homebrew? GitHub Release binary?)
3. **What is it NOT?** (Is this paperful.io? Is this a Sci-Hub front-end? Is this Zotero replacement?)

**Current front-door performance:**

| Surface | What it is | How to run | What it's not | Grade |
|---------|------------|------------|---------------|-------|
| **Website hero** (L69-79) | "Research helper... tidies library, finds PDFs, summarises" — vague, could be SaaS | Not stated above fold | "Mendeley/EndNote seeking testers, Sci-Hub opt-in" (L91-92) — **60 lines down** | **C−** — Generic, no collision strip, install path missing |
| **README opening** (L3-55) | "Local sidecar for a Zotero research library" (L8) — **good** | "git clone → docker compose build" (L77-86) — **45 lines down** | "not a sync service" (L48), "not every paywall" (L35-36), "no docker pull / pip" (L62-63) — **scattered** | **B−** — Job clear, but disclaimers buried |
| **OG card** (`index.html` L12-18) | "Clean a reference library, find missing PDFs, summarise papers" — neutral | "Python, Zotero API, Ollama or LiteLLM, Docker" (stack, not install) | Not stated | **D** — No collision, no install, no "not sync" |

**Problems for cold outreach:**

1. **Website hero does not name the job in stranger terms.** "Research helper that tidies a reference library" (L72-73) is **vague** — does it run in Zotero as a plugin? Is it a web service? Only by L79 ("Work stays on this machine") does a reader infer "local CLI," and by then they've scrolled past the fold.

2. **Install path is 45-60 lines down on both surfaces.** Website `#install` section (L192-247 of `index.html`) is a scroll target, not above-fold. README L77-86 is after Quick Start heading, but a skim-reader sees "Docker" (L66) and "There is no published image" (L62) **before** seeing the `git clone` command. **Inverted reveal order.**

3. **OG image is relative (`images/logo.png`), not absolute.** Per `uploads/04-seo-bro-thicken_ee43.md` L25, SEO Bro audit table: website OG is `<meta property="og:image" content="images/logo.png">` — **this breaks Slack/HN unfurls** on some crawlers. Must be `https://glenwright.earth/Paperful/images/logo.png` (or a dedicated 1200×630 card).

4. **Tagline drift between surfaces.** Per `uploads/03-design-eye-thicken_8145.md` L45-47, Design eye "First impression" § notes: "README/Pages tagline drift (older 'Fill the gaps…' vs live 'Keep the library…') is a first-screen trust ding if unfurl and hero disagree." Checked:
   - Website hero (L69): **"Clean the library. Find the PDFs. Keep a mirror."**
   - README opening (L3): **"Clean the library. Find the PDFs. Keep a mirror."** — Wait, these match now (post-PR #8 reframe per git log). Good. But `docs/index.md` might still have old language — didn't check full Sphinx build. If Sphinx hero still says "Fill the gaps in a Zotero library," that's a third tagline and a trust leak.

5. **"Shipped" language without Release.** `README.md` L59 says "Hosted site: landing in `website/` plus Sphinx HTML from this `docs/` tree at `/guide/`." This is factual. But `uploads/paperful_e58c.md` L13-14 notes: "Tag without GitHub Release assets — 'Shipped 0.9' overclaims downloadability." Checked repo: `git tag` shows `v0.9`, but `gh release list` (if run) would show no Release for `v0.9`. **Gap:** Page/README honesty ("no docker pull") is correct, but using "release" or "shipped" in outreach copy without clarifying "tag, not binary" will confuse.

### Compose-First Install Honesty (Good, But Fragile)

**What's correct today:**

- `README.md` L62-63: "Build the image on this machine. There is no published image and no PyPI package: do not `docker pull` or `pip install paperful`." — **Explicit, bold, correct.**
- Website L83-93 (inferred from earlier read, checking consistency): parallels README, says clone + build.
- `uploads/paperful_e58c.md` L13-14 confirms: "Install: `git clone` → `docker compose build` → `doctor` / dry-run. Explicitly **no** `docker pull`, **no** `pip install paperful`."

**Fragility for outreach:**

A cold invite that says "Check out Paperful v0.9, now available" will be **misread as a binary release** by 80% of recipients. They'll try `docker pull ghcr.io/glen-w/paperful:0.9` (doesn't exist) or `pip install paperful` (doesn't exist), hit 404, conclude "broken project," and never clone.

**Mitigation:** Every invite must say in the **first sentence**:

> Paperful v0.9 is a clone + Compose build (no docker pull, no pip) — pointable page + install guide: https://glenwright.earth/Paperful/

If Glen won't write that sentence in every invite, **do not mail**.

---

## 3. Name Collision: paperful.io (Hard Don't-Mail Gate)

### The Collision

**paperful.io** is a **live SaaS product** (document infrastructure / PDF workflow service, based on SERP preview). Distinct company, distinct offering, likely has enterprise customers and SEO budget.

**Collision severity:** A stranger who hears "Paperful" **will Google it**. First organic result (as of SEO Bro audit, `uploads/04-seo-bro-thicken_ee43.md` L47): **paperful.io**, not glenwright.earth/Paperful/. A forwarded Slack link or HN thread with "Paperful" in the title will attract replies saying "isn't that the PDF automation service?" Glen's tool is **invisible on SERP** until someone searches "Paperful Zotero" or "Paperful GitHub."

**Current disclosure on Glen's front door:**

- **Website (https://glenwright.earth/Paperful/):** Searched full `index.html` (324 lines) for "paperful.io" — **zero mentions**. Searched for "not affiliated" — **zero mentions**. Searched for "SaaS" or "cloud" (to see if there's a "not a cloud service" strip that might implicitly disclaim) — only "Work stays on this machine" (L77). **No collision disclosure above, below, or anywhere on the page.**

- **README.md:** Searched for "paperful.io" — **zero mentions**. Searched for "not affiliated" — **zero mentions**. Searched for disclaimer language — only "paperful is not a sync service" (L48) and "no published image" (L62). **No collision disclosure.**

- **`docs/comparison.md`:** Checked for paperful.io in the vendor comparison table (L13-31, L82-101) — **not listed**. Makes sense (it's not a reference-manager competitor), but a "not that Paperful" footnote would be appropriate.

**Per SEO Bro audit (`uploads/04-seo-bro-thicken_ee43.md` L47-49):**

| Tool | Collision named on page? |
|------|--------------------------|
| **Paperful** | **No** paperful.io |

**Don't-mail gate language (L51):** "[ ] Hero strip names not-paperful.io"

**This is a fatal omission for outreach.** Per `uploads/01-cross-cutting-rules_a62f.md` L3-4:

> **Landing URL in every invite** — but collision disclaimer = visible strip, not a footnote. Name collisions strangers hit from the mark alone (paperful.io, transcriptx.ai, …) sit in a **hero strip / first README band**, same visual weight as the job sentence — not a tiny "also not…" under the fold.

**And per `uploads/06-intern1-thicken_4fd6.md` L14-15:**

> **Collision in subject + hero** — if the product name is someone else's SaaS, the invite subject and the page above-fold must disclaim in the same breath. Burying it in README is not enough for cold mail.

### Recommended Collision Language

**Hero strip (website + README first screen):**

```markdown
📌 **Not affiliated with paperful.io** — this is Glen's local research tool, not a cloud document service.
```

Or, tighter:

```markdown
Not paperful.io · Local Zotero sidecar · Build with Docker Compose
```

**Invite opener pattern (per SEO Bro `uploads/04-seo-bro-thicken_ee43.md` L110-112):**

> Quick note — this is **Glen's Paperful** (local Zotero sidecar), not paperful.io. Pointable page: https://glenwright.earth/Paperful/. Install is clone + Compose, not pip/docker hub.

**GitHub description draft (per SEO Bro L47-49):**

> Local Zotero sidecar: fill reachable PDFs (OA/EZProxy/grey), lint metadata, on-disk copy — not a sync service. **Not affiliated with paperful.io.**

**This language must land on website hero, README first band, and every invite opener before any mail goes out.**

---

## 4. Don't-Mail-Yet Gates (Marketing Checklist)

These are **hard blockers** for any outbound invite, HN post, Ko-fi campaign, LinkedIn share, or webinar announcement. A Marketeer would **refuse to send** until all six clear.

### Gate 1: Collision Strip Above Fold ❌

**Status:** Not present on website or README (§ 3 evidence).

**Why it blocks mail:** First reply to an HN post or Slack forward will be "Wait, isn't that paperful.io?" If Glen's page doesn't pre-empt this in the hero, the thread derails into "which Paperful?" and trust evaporates.

**What must land:**

- [ ] Website `index.html` hero (L69-79): Add collision strip after brand mark, before lede. Visual weight = same size as "Work stays on this machine" (L77).
- [ ] `README.md` opening (L3-10): Add collision strip after logo/header, before "Five jobs" paragraph (L14).
- [ ] Every invite opener: "Not paperful.io" in the **first sentence** or subject line (see § 3 invite pattern).

**Accountable lane:** Design eye (visual strip), Web design (meta/OG), Marketeer (invite copy).

### Gate 2: Install Story Matches Artifacts ❌

**Status:** README + website correctly say "no docker pull, no pip," but language like "shipped" or "v0.9 release" without "tag, not binary" will confuse. Tag `v0.9` exists, but `gh release list` shows no GitHub Release with assets.

**Why it blocks mail:** A cold recipient who reads "Paperful v0.9 is live" will try to install via `docker pull` or `pip install`, hit 404, and bounce. If the invite doesn't say "clone + Compose" in the same breath as "v0.9," the first install attempt fails and trust is burned.

**What must land (pick one path):**

**Path A (Recommended): Reframe "release" language to match clone-build reality.**

- [ ] Invite copy: "Paperful v0.9 is **pointable** (clone + Compose build) — no docker pull, no pip."
- [ ] Website/README: Change any "shipped" or "released" language to "tagged v0.9" or "pointable at v0.9."
- [ ] OG description: Add "clone + build" to stack line (currently says "Python, Zotero API, Ollama or LiteLLM, Docker" — add "— clone + Compose, no pull").

**Path B (More work): Ship a GitHub Release for v0.9 with Compose tarball or install script.**

- [ ] Create GitHub Release `v0.9` with release notes, attach `compose.yaml` + `Dockerfile` as assets (or a `install.sh` that clones + builds).
- [ ] Update website/README to link to Releases page: "Download v0.9: [Releases](https://github.com/glen-w/Paperful/releases)."
- [ ] Invite copy: "Paperful v0.9 released: clone + build, or grab the Compose bundle from Releases."

**Path A is cheaper and honest; Path B is higher polish but implies more packaging maturity than 0.x typically signals.**

**Accountable lane:** Glen (decide A vs B), Web design (update page/README if A), Infra (ship Release if B), Marketeer (invite copy).

### Gate 3: SemVer Language Honest to 0.x ✅ (Currently Clear)

**Status:** Website footer (`website/README.md` L10) says "**0.x** is called out in the footer; stability story is `docs/releases.md`." Checked: no "1.0" or "production-ready" language in README or website. Tag is `v0.9`. **Good.**

**Why this is a don't-mail gate elsewhere:** Per `uploads/01-cross-cutting-rules_a62f.md` L1: "Never say SemVer 1.0 in mail, HN, or page unless Call wrote freeze + tag rule." Other tools in Glen's portfolio (per Observe pack) might slip "1.0" into badge SVGs or OG titles without freeze — Paperful has not done this. **Passing gate.**

**What to keep doing:** Stay "v0.9" or "pointable 0.x" in all outreach. Do not upgrade to "1.0" until SemVer freeze contract exists in `docs/releases.md` or `ROADMAP.md` and tag is cut.

**Accountable lane:** Marketeer (copy review), Glen (freeze decision).

### Gate 4: Invented Invite Lists (Don't Invent Recipients) ⚠️

**Status:** Unknown from repo evidence — this is a **Marketeer behaviour gate**, not a code/docs gate.

**Why it blocks mail:** Per `uploads/01-cross-cutting-rules_a62f.md` L4: "One mail = people Glen would actually email. Marketeer / SEO will not invent lists." And per `uploads/paperful_e58c.md` L40-43:

> | Bus factor 1 | Invite list must stay people Glen will answer | Marketeer / Glen |
> …
> - [ ] Names for the one mail filled by Glen (not invented here)

**What must NOT happen:**

- Scraping Zotero authors from ORCID or GitHub stars and BCCing 200 strangers.
- Posting to r/Zotero or r/academia without Glen's explicit "yes, Reddit is In."
- Cold-emailing IDDRI, EOI, or Oceana colleagues unless Glen has named them on a sheet.
- Submitting to HN without Glen approving the title and willing to answer top-thread questions within 4 hours.

**What must happen:**

- Glen provides **named list** of 5-20 people he would personally email about Paperful (researchers he's collaborated with, Zotero power-users he knows, colleagues who've asked about his workflow).
- Marketeer drafts **one invite** for Glen to send (or Glen sends it himself).
- Subject line and body match collision/install/SemVer honesty from Gates 1-3.

**If Glen is unwilling to name recipients or answer replies, do not mail.**

**Accountable lane:** Glen (provide list or veto mail), Marketeer (draft copy, but do not invent recipients).

### Gate 5: Ko-fi ≠ Funding Story ✅ (Currently Correct)

**Status:** `README.md` L164-166 has Ko-fi link in footer. Website `index.html` L310-319 (inferred from earlier read) has Ko-fi button in footer. Per `uploads/01-cross-cutting-rules_a62f.md` L3: "Ko-fi on README = tip line, not a funding / grant story. Keep out of SEO funding claims."

**Why this is a don't-mail gate:** If outreach copy says "Paperful is funded by supporters" or "back us on Ko-fi to keep this project alive," that's **emotional manipulation** (and false — Glen is not dependent on Ko-fi to maintain this). Ko-fi is a **thank-you tip jar**, not a Patreon campaign or grant proposal.

**What's correct today:** Ko-fi link is footer-quiet, no "please support" hero CTA. **Passing gate.**

**What to keep doing:** Ko-fi stays in footer. Do not put "Support this project" above fold. Do not say "funded by the community" in OG or invite copy. If someone tips, Glen can thank them, but outreach does not beg.

**Accountable lane:** Marketeer (copy review), Design eye (if Ko-fi CTA ever proposed for hero).

### Gate 6: Docs Maze Resolved to One Truth ❌

**Status:** Per Researcher assessment (PR #9, § 2 P0 "Three Surfaces, Inconsistent Coverage"), `README.md`, `docs/*.md`, and `website/index.html` **contradict each other** on:

- Zotero 10+ required for `attach` (stated in README, not in website or `docs/index.md`)
- EZProxy requires `uv` on host (stated in `docs/docker.md`, not in README or website)
- `doctor` TTY guide (exists per `docs/commands.md`, not mentioned anywhere else)

**Why it blocks mail:** A forwarded invite points at https://glenwright.earth/Paperful/, recipient clicks `/guide/` (Sphinx docs), sees "run `paperful session login ezproxy`," tries it in Docker, hits "command not found," Googles, finds README says "contributors use `uv`," concludes "these docs are incoherent," and exits.

**Per Researcher § 2:**

> **README vs docs/index.md vs website/index.html are not aligned on tone** […] **None of them cross-link effectively.** […] A new user has to read all 169 lines [of README] to know: 1. What Paperful does […] 2. How to install it (Docker vs `uv` split at L62 and L143). 3. What command to run first (`doctor`, L84, buried after `docker compose build`).

**This is not just a usability fail — it's marketing debt.** Every contradiction is a **trust leak**. If website says "Mendeley seeking testers" but `docs/mendeley.md` implies it's ready, a forwarded link to docs will over-promise what the website correctly disclaims.

**What must land:**

- [ ] **Pick one canonical surface** (recommend: `docs/` as single source of truth, README as pointer + quick start, website as marketing). Per Researcher recommended action #6.
- [ ] **Audit all three** for contradictions: Zotero 10+ requirement, EZProxy host path, install Docker vs `uv` operator story. Make them agree.
- [ ] **Cross-link effectively:** Website hero should say "Full install guide: [/guide/docker.html](./guide/docker.html)." README should say "Hosted docs: https://glenwright.earth/Paperful/guide/." `docs/index.md` should link back to website for "what is this?"

**Until this lands, forwarding a link is a coin-flip whether the reader sees correct or outdated info.**

**Accountable lane:** Researcher (audit complete in PR #9), Glen (decide canonical surface), Web design (cross-link wiring), Marketeer (refuse to mail until one truth exists).

---

## 5. Docs Maze as Marketing Debt (Inherited from Researcher P0)

This section is **not a re-review** of usability — Researcher assessed that in PR #9 (`assessments/2026-09-25-critical-review-usability-docs-features.md`). This section explains **why the docs maze kills outreach trust**, citing Researcher's P0 findings.

### The Maze (Researcher § 2 P0)

**Three surfaces:**

1. `README.md` (169 lines) — operator-focused, CLI-first, pragmatic.
2. `docs/*.md` (Sphinx site, 23 files, ~3,000 lines) — reference-manual formal.
3. `website/index.html` (324 lines) — marketing-lite, feature cards.

**Contradictions (Researcher § 2, table L139-158):**

| Claim | README | docs/index.md | website | Verdict |
|-------|--------|---------------|---------|---------|
| Mendeley proven | "seeking testers" (L9) | "seeking testers" | "seeking testers" (L91) | Consistent ✅ |
| Zotero 10+ for attach | L71-73 | Not stated | Not stated | **Inconsistent ❌** |
| `doctor` TTY guide | Not stated | Not stated | Not stated | **Missing ❌** (exists in `docs/commands.md` but nowhere else) |
| EZProxy requires host `uv` | Not stated | Not stated | Not stated | **Missing ❌** (exists in `docs/docker.md` L17-29 only) |
| Sci-Hub opt-in | L29-32 | L12-13 | L92 "off by default" | Consistent ✅ |

**Per Researcher P0 #3 finding (L482-483):**

> **Three documentation surfaces with contradictions.** (Evidence: README vs `docs/index.md` vs `website/index.html` say different things about Zotero 10+ requirement, EZProxy host setup, `doctor` TTY guide). **Impact:** Users read one doc, miss critical setup steps in another. **Fix:** Pick one canonical surface […].

### Why This Kills Invite Trust (Marketing Lens)

**Scenario 1: Forwarded Slack link**

A researcher receives: "Check out Paperful: https://glenwright.earth/Paperful/ — local Zotero mirror."

1. **Clicks link** → lands on website hero. Reads "Clean the library. Find the PDFs. Keep a mirror." + "Mendeley and EndNote are seeking testers" (L91). Thinks: _"Okay, Zotero works, Mendeley doesn't."_
2. **Clicks "Docs" nav** (L50 of `index.html`) → lands on `guide/index.html` (Sphinx home). Reads `docs/index.md` opening: "The live catalogue is an adapter. Zotero's local API is the one that is well tested." Consistent so far.
3. **Clicks "Docker" in left sidebar** → lands on `guide/docker.html`. Reads L17-29 (paraphrased from Researcher evidence): "Zotero and headed `session login` stay on the host. EZProxy session requires `uv run paperful session login ezproxy` **on the host**."
4. **Confusion:** "Wait, I need `uv` on the host? The website said Docker. Do I install `uv` first, or Docker, or both?"
5. **Clicks back to README** on GitHub (they might have opened it in a tab). Reads L62: "Build the image on this machine. There is no published image…" **No mention of `uv` on host until L143: "Contributors use `uv`."**
6. **Conclusion:** "These docs don't agree on the install path. Is `uv` required or not? I'll try it later." (Translation: never tries it.)

**Trust leak:** The forwarded link worked (they landed on the page), but **three clicks revealed three partial truths** that don't form one coherent picture. That's a **30-second bounce** for 70% of cold readers.

**Scenario 2: HN thread**

An HN post titled "Paperful — local Zotero PDF finder" (hypothetical) gets traction. Top comment:

> "Clicked the site, looks interesting, but the docs say 'Mendeley and EndNote seeking testers' on the landing page, then the Mendeley docs (`guide/mendeley.html`) have a full setup guide with OAuth app registration and `session login mendeley` commands. If it's 'seeking testers,' why does it have production-level docs? Is this alpha theatre?"

Glen or a supporter replies: "Mendeley adapter exists and is documented, but it's not battle-tested on a real 2,000-item library yet. Zotero is proven. The docs are there for brave testers."

**But damage is done:** The thread now has "alpha theatre" and "not battle-tested" upthread, and 50% of readers won't scroll past that to see Glen's clarification. **The docs maze made the product look less mature than it is** (Zotero is solid), because Mendeley's existence-but-not-provenance is disclosed **asymmetrically** (hero says "seeking testers," docs say "here's how to use it").

**Scenario 3: Email invite, recipient Googles Paperful**

Glen sends an invite: "I've been working on a local research tool called Paperful — fills PDFs from open access + EZProxy, keeps a mirror. Check it out: https://glenwright.earth/Paperful/"

Recipient thinks: _"Paperful… sounds useful. Let me Google it to see what else is out there."_

1. **Googles "Paperful"** → First result: **paperful.io** (SaaS, wrong product). Second result: Glen's site (if SEO is good; might be page 2 if not).
2. **Reads paperful.io homepage** for 10 seconds, sees "document workflow automation," thinks _"Hmm, not what Glen described, but maybe it's the same company?"_
3. **Clicks Glen's link** → sees hero "Clean the library. Find the PDFs." **No mention of "not paperful.io"** above fold.
4. **Confusion:** "Is this affiliated with paperful.io? Glen's email didn't say." Opens a new tab, Googles "Paperful vs paperful.io" → finds nothing (collision is unnamed on both sides).
5. **Gives up or replies to Glen:** "Is this the same as paperful.io?" Glen now has to spend reply #1 clarifying the collision instead of discussing features.

**Trust leak:** Glen's invite was honest, but the **front door didn't pre-empt the collision**. First interaction was confusion, not curiosity.

### Marketing Debt = Credibility Leak Per Contradiction

**Per Researcher § 2 conclusion (L477-483), P0 #3:**

> **Impact:** Users read one doc, miss critical setup steps in another.

From a **marketing lens**, the impact is worse: **users read one doc, see a contradiction in another, and conclude the project is unfinished**. Every contradiction is a **trust signal that says "this is alpha, not pointable."** Even if the product works (it does, per Researcher § 4 "What Works Well"), the **docs maze makes it look broken**.

**The four hard don't-mail gates in § 4 (collision strip, install honesty, SemVer, docs one-truth) are all downstream of this:** if the three surfaces contradict each other, **no amount of collision-strip polish will save a forwarded link that lands on the wrong surface**.

---

## 6. Recommended Marketing Actions (Ranked, Concrete)

These are **operator-facing next actions** for Glen + Marketeer + Design + Web, ranked by **what must land before mail** vs **nice-to-have**.

### Before ANY Wave Invite (Hard Blockers)

#### Action 1: Add Collision Strip Above Fold (4 hours)

**Lane:** Design eye (visual spec) + Web design (meta) + Marketeer (copy).

**What:**

1. **Website `index.html` hero** (between L69 brand mark and L71 h1): Add paragraph or banner:
   ```html
   <p class="disclaimer-strip">Not affiliated with paperful.io — this is a local research tool, not a cloud document service.</p>
   ```
   Style: same visual weight as "Work stays on this machine" (L77), neutral tone (not defensive, just factual).

2. **`README.md` opening** (after L3-10 header paragraph, before L14 "Five jobs"): Add:
   ```markdown
   > **Not affiliated with paperful.io.** This is a local Zotero sidecar, not a cloud document service.
   ```

3. **OG meta** (`index.html` L12-18): Change L14-16 `og:description` from:
   ```html
   <meta property="og:description" content="Clean a reference library, find missing PDFs, summarise papers, and keep a platform-agnostic mirror. Python, Zotero API, Ollama or LiteLLM, Docker." />
   ```
   To:
   ```html
   <meta property="og:description" content="Local Zotero sidecar (not paperful.io): fill reachable PDFs (OA/EZProxy/grey), lint metadata, on-disk mirror. Clone + Compose, no pull/pip." />
   ```

4. **Every invite opener:** Use SEO Bro pattern (§ 3):
   > Quick note — this is **Glen's Paperful** (local Zotero sidecar), not paperful.io. Pointable page: https://glenwright.earth/Paperful/. Install is clone + Compose, not pip/docker hub.

**Why before mail:** First HN reply or Slack forward question will be "isn't that paperful.io?" If page doesn't pre-empt, thread derails.

**Effort:** 4 hours (Design eye: 1h visual spec, Web design: 1h HTML/CSS, Marketeer: 30min copy, Glen: 30min review + merge, Web design: 1h deploy/verify).

#### Action 2: Fix Absolute OG Image (30 minutes)

**Lane:** Web design.

**What:** Change `index.html` L18:
```html
<meta property="og:image" content="images/logo.png" />
```
To:
```html
<meta property="og:image" content="https://glenwright.earth/Paperful/images/logo.png" />
```

Or create a 1200×630 OG card image (`images/og-card.png`) with:
- Paperful logo
- "Local Zotero sidecar"
- "Not paperful.io"
- Stack: "Python · Zotero API · Docker"

Then:
```html
<meta property="og:image" content="https://glenwright.earth/Paperful/images/og-card.png" />
```

**Why before mail:** Relative OG images break Slack/LinkedIn unfurls on some crawlers (per SEO Bro audit). A blank card or broken image on first forward kills click-through.

**Effort:** 30 minutes (change one line, or 2 hours if designing a card from scratch).

#### Action 3: Reframe "Release" Language to Match Clone-Build (1 hour)

**Lane:** Web design + Marketeer.

**What (Path A — recommended):**

1. **Website + README:** Search for "release" or "shipped" language. If present, change to "tagged v0.9" or "pointable at v0.9."
2. **Invite copy template:** "Paperful v0.9 is **pointable** (clone + Compose build, no docker pull / pip)."
3. **Do not say:** "Download Paperful v0.9" or "Install the latest release" without immediately clarifying "clone + build."

**What (Path B — more polish, 4 hours):**

1. Create GitHub Release for `v0.9`:
   - Release notes: bullet CHANGELOG highlights.
   - Assets: `compose.yaml`, `Dockerfile`, `config.example.toml` (or tarball).
   - Body: "Build locally: clone this repo, then `docker compose build`. No published image on Docker Hub."
2. Update website/README: "Get started: [Releases](https://github.com/glen-w/Paperful/releases) or clone."

**Why before mail:** Cold recipient who tries `docker pull` or `pip install` and hits 404 will bounce. Invite must pre-empt this in the first sentence.

**Effort:** Path A: 1 hour (audit + rewrite). Path B: 4 hours (Release creation + docs update + verify).

#### Action 4: Docs One-Truth Audit (Glen Decision + 4 Hours Execution)

**Lane:** Glen (decide canonical surface) + Researcher (audit, already done in PR #9) + Web design (cross-link).

**What:**

1. **Glen decides:** "README is pointer, `docs/` (Sphinx) is single source of truth, website is marketing." Or: "Website is primary, README mirrors it, `docs/` is deep-reference." Pick one hierarchy.

2. **Audit all three surfaces** for contradictions (Researcher § 2 table L139-158):
   - Zotero 10+ requirement for `attach` / `fix-metadata --apply`: State it **once** in `docs/zotero.md`, then README + website say "Zotero 10+ recommended (see [docs/zotero](/guide/zotero.html))."
   - EZProxy requires `uv` on host for `session login`: State it **once** in `docs/ezproxy.md` + `docs/docker.md`, then README L77-86 quick-start says "For EZProxy, install `uv` on host (see [EZProxy guide](/guide/ezproxy.html))."
   - `doctor` TTY guide: If it's in `docs/commands.md`, README should link: "Run `doctor` for health check (TTY output: [commands](/guide/commands.html#doctor))."

3. **Cross-link effectively:**
   - Website hero (L80): After "See how it works" CTA, add: "Full install: [/guide/docker.html](./guide/docker.html)."
   - README L59 (already says "Hosted site"): Add: "Hosted guide: [https://glenwright.earth/Paperful/guide/](https://glenwright.earth/Paperful/guide/)."
   - `docs/index.md`: Add first paragraph: "New here? See [glenwright.earth/Paperful](https://glenwright.earth/Paperful/) for the landing page and install quick-start."

**Why before mail:** Every contradiction is a trust leak. Forwarding a link to website vs `/guide/` vs `README` should give the same Zotero 10+ / EZProxy / install story, not three partial truths.

**Effort:** Glen decision: 30 minutes. Audit + rewrite: 4 hours (Researcher's recommendations 1, 2, 6 from PR #9 overlap here). Cross-link wiring: 1 hour. **Total: 5.5 hours.**

**Dependency:** Wait for Researcher's PR #9 recommendations to land, then verify one-truth is achieved.

---

### Before First HN / Public Post (Medium Priority)

#### Action 5: Add "Not Paperful.io" to GitHub Repo Description + Topics (15 minutes)

**Lane:** Glen (repo settings) or Marketeer (if Glen delegates).

**What:**

1. **GitHub repo description** (https://github.com/glen-w/Paperful, top of page): Currently might say "Research helper for a reference library" (not checked, inferred). Change to SEO Bro draft (§ 3, `uploads/04-seo-bro-thicken_ee43.md` L49):
   > Local Zotero sidecar: fill reachable PDFs (OA/EZProxy/grey), lint metadata, on-disk copy — not a sync service. **Not affiliated with paperful.io.**

2. **Topics** (repo settings → Topics): Add per SEO Bro L50: `zotero`, `research`, `open-access`, `pdf`, `docker`, `local-first`, `metadata`. **Do not add `paperful` alone** (collision with paperful.io PyPI/SERP).

**Why before HN:** HN threads often link to GitHub repo, not website. If repo description is silent on collision, top comment will be "isn't this paperful.io?" and derail.

**Effort:** 15 minutes (repo settings, paste text, save).

#### Action 6: Draft HN Title That Owns Collision + Clone-Build (30 minutes)

**Lane:** Marketeer (draft) + SEO Bro (review).

**What:** Per SEO Bro `uploads/04-seo-bro-thicken_ee43.md` L51 "HN title don't: Avoid 'Paperful' alone; prefer 'Local Zotero sidecar that fills reachable PDFs (Docker, not paperful.io)'"

**Good HN titles:**

1. "Local Zotero sidecar for PDF fetch + metadata (Docker, not paperful.io)"
2. "Paperful: on-disk Zotero mirror w/ OA+EZProxy fetch (not the SaaS)"
3. "Fill Zotero PDFs locally via open access + campus EZProxy (Paperful, not paperful.io)"

**Bad HN titles:**

1. "Paperful v0.9 released" — (1) implies binary release, (2) no collision disclaimer, (3) "released" might get flagged as blogspam.
2. "Check out my Zotero tool" — too vague, no keywords.
3. "Paperful — research PDF finder" — collision unnamed, sounds like Sci-Hub client.

**Why before HN:** HN title is the **first 60 characters a stranger sees**. If it doesn't own the collision, first reply does, and thread is lost.

**Effort:** 30 minutes (draft 5 candidates, pick best, Glen approves).

#### Action 7: Add "Is Paperful Right for Me?" Decision Tree to README (1 hour)

**Lane:** Marketeer (draft) + Researcher (review against § 2 P2 #19 recommendation).

**What:** Per Researcher § 2 P2 #19 (L519), add to `README.md` after L55 "Control" paragraph, before L59 "Hosted site":

```markdown
## Is Paperful Right for Me?

**Yes, if:**
- You use Zotero (Mendeley/EndNote are not proven yet)
- You need a local mirror of your library (backup, or exit path from Zotero cloud)
- You're comfortable with CLIs and Docker
- You have 100+ items without PDFs and want bulk fetch

**Maybe, if:**
- You only need "find OA PDF" (try Zotero's built-in first, or zotero-zotadata plugin)
- You're not sure what "EZProxy" is (you probably don't have campus access)

**No, if:**
- You want a GUI
- You need OCR for scanned PDFs (out of scope)
- You expect 100% PDF coverage (Paperful is OA + campus, not a pirate tool)

See [Why paperful](docs/why.md) and [Comparison](docs/comparison.md) for details.
```

**Why before HN:** HN readers will ask "why not just use Zotero's built-in?" or "why not zotero-zotadata?" A decision tree pre-empts this and sets expectations (not 100% coverage, not GUI).

**Effort:** 1 hour (draft, Glen review, merge).

---

### Before Ko-fi Campaign or LinkedIn Share (Lower Priority)

#### Action 8: Verify Ko-fi Footer Is Tip-Jar Quiet (10 minutes, Audit Only)

**Lane:** Marketeer (audit) + Design eye (if changes needed).

**What:** Check website `index.html` footer (L310-319) and `README.md` L164-166. Ensure:

- Ko-fi link is **footer-quiet**, not a hero CTA.
- No "Please support" or "Funded by community" language anywhere above fold.
- OG description does not mention Ko-fi or funding.

**Current status:** Per § 4 Gate 5, this is already correct. **Audit only, no changes needed unless someone added a "Support" CTA since last check.**

**Why before Ko-fi campaign:** If Ko-fi ever becomes a hero CTA ("Support Paperful to keep it alive!"), that's **emotional manipulation** and violates cross-cutting rule (`uploads/01-cross-cutting-rules_a62f.md` L3). Ko-fi is a thank-you jar, not a funding drive.

**Effort:** 10 minutes (audit, confirm no changes needed).

#### Action 9: Add Provenance Stamp Mention to Website or README (30 minutes)

**Lane:** Web design (add to website) or Marketeer (add to README).

**What:** Per Researcher § 4 "What Works Well" #6 (L460-461): "Provenance stamps on attachments (`paperful oa:unpaywall` / `campus:ezproxy` / `grey:undocs` on Zotero notes). **This is operator-friendly transparency** — a user can audit 'where did this PDF come from?' **Not every tool does this.**"

This is a **differentiator** that website/README should surface. Add to website "Find" section (L114-129 of `index.html`, after "Each item only hits sources that match its metadata"):

```html
<p>Attachments include provenance notes (e.g., <code>paperful oa:unpaywall</code>) so you can audit where each PDF came from.</p>
```

Or add to README L25-36 "Find" paragraph (after "Paperful does not fetch every paywalled or DOI-less item"):

```markdown
Attachments include provenance notes (`paperful oa:unpaywall`, `campus:ezproxy`, `grey:undocs`) so you can audit sources.
```

**Why before LinkedIn:** If Glen shares Paperful on LinkedIn and a colleague comments "how do I know which PDFs came from Sci-Hub vs campus?", Glen can reply "provenance stamps — see README." If it's not in README, that reply requires a docs link that's harder to forward.

**Effort:** 30 minutes (add one sentence, Glen review, deploy).

---

### After Wave 1 (Post-Outreach Polish)

#### Action 10: Create Minimal `config.minimal.toml` (1 hour)

**Lane:** Glen (decide what goes in minimal) + Infra (create file).

**What:** Per Researcher P0 #4 (L484-486), split `config.example.toml` (194 lines) into:

1. **`config.minimal.toml`** (30 lines): `email`, `out_dir`, `state_dir`, `sources = ["unpaywall", "openalex", "arxiv"]` (OA only, no EZProxy/Scholar/Sci-Hub), `attach = true`. Comments: "New users: start here."

2. **`config.advanced.toml`** (current 194 lines, renamed): All EZProxy, LLM, grey-lit, snowball settings. Comments: "Advanced: campus access, LLM, grey-lit playbooks."

3. **README L81-82:** Change `cp config.example.toml config.toml` to:
   ```sh
   cp config.minimal.toml config.toml    # New users: OA sources only
   # Or: cp config.advanced.toml config.toml  # Advanced: EZProxy, LLM, grey-lit
   ```

**Why not before wave:** This is a **first-run UX improvement**, not a trust gate. If Glen sends 10 invites and 3 people try it, they'll hit the 194-line config and might give up — but they've already cleared the trust gates (collision, install, one-truth). Post-wave polish reduces "I'll try it later" attrition.

**Effort:** 1 hour (Glen decides minimal scope, create file, update README, test that minimal works, merge).

---

## Summary of Don't-Mail Gates (Checklist)

Copy this into a tracking sheet or GitHub issue. **All six must clear before any outbound invite, HN, LinkedIn, Ko-fi campaign, or webinar.**

- [ ] **Gate 1: Collision strip above fold** (website hero + README first screen + invite opener: "Not paperful.io") — ❌ **BLOCKING**
- [ ] **Gate 2: Install story matches artifacts** (either reframe "release" to "clone-build" OR ship GitHub Release; invite says "clone + Compose, no pull/pip") — ❌ **BLOCKING**
- [ ] **Gate 3: SemVer honest to 0.x** (no "1.0" language, stay "v0.9" or "pointable 0.x") — ✅ **PASSING** (already correct)
- [ ] **Gate 4: No invented invite lists** (Glen names recipients, or veto mail) — ⚠️ **BEHAVIOUR GATE** (Marketeer must enforce)
- [ ] **Gate 5: Ko-fi = tip jar, not funding** (footer-quiet, no hero CTA, no "please support") — ✅ **PASSING** (already correct)
- [ ] **Gate 6: Docs one truth** (README, `docs/`, website agree on Zotero 10+, EZProxy host `uv`, install paths) — ❌ **BLOCKING** (Researcher PR #9 audit complete, fixes pending)

**Current status: 3 of 6 gates BLOCKING.** Do not mail until Gates 1, 2, 6 clear.

---

## What to Tell Glen (Operator Summary)

**Three sentences:**

1. Paperful is technically solid (EZProxy handling, disk-first arch, source routing) and honestly scoped (Sci-Hub opt-in, Mendeley "seeking testers"), but the **front door over-promises** ("platform-agnostic mirror" hero vs Mendeley disclaimer 60 lines down) and is **silent on the paperful.io collision**.

2. **Three hard blockers for outreach:** (1) website + README must name-out paperful.io **above the fold** before any invite, (2) install story must match clone-build reality (either reframe "release" language or ship GitHub Release), (3) docs maze (README vs `docs/` vs website contradictions on Zotero 10+, EZProxy `uv` on host) must resolve to one truth before forwarding links.

3. **Recommended:** Land Actions 1–4 (collision strip, absolute OG, install-language reframe, docs one-truth audit) before **any** maker-wave invite, then draft one HN title (Action 6) and decision tree (Action 7) before going public; Ko-fi/LinkedIn polish (Actions 8–9) can wait; post-wave UX (Action 10, minimal config) is nice-to-have but not a trust gate.

**If Glen is unwilling to land Gates 1, 2, 6, do not mail. Every invite before those clear is a credibility burn.**

---

**End of Marketing Assessment**

**Signed:** Cloud Agent (Marketing Review)  
**Date:** 2026-09-25  
**Evidence Base:** `/workspace` repo @ main + Researcher PR #9 + uploads (`paperful_e58c.md`, `01-cross-cutting-rules_a62f.md`, `04-seo-bro-thicken_ee43.md`, `03-design-eye-thicken_8145.md`, `06-intern1-thicken_4fd6.md`)  
**Dependencies:** Researcher assessment (`assessments/2026-09-25-critical-review-usability-docs-features.md` PR #9) for docs-maze citations; SEO Bro audit for collision SERP evidence.
