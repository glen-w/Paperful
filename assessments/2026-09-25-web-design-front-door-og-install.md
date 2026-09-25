# Web Design Assessment: Paperful Front Door
**Date:** 2026-09-25  
**Lane:** Web design — pointable front door (live page + README as web artifacts)  
**Scope:** Share/unfurl quality, OG tags, install honesty, paperful.io collision, README scan path  
**Adjacent lanes:** Design eye (stills/brand) owned by others; Marketeer (copy) owned by others; UX (operator first-hour) covered in [critical-review-usability-docs-features.md](./2026-09-25-critical-review-usability-docs-features.md)

---

## Executive Verdict

**FAIL** for share-ready front door. The live page https://glenwright.earth/Paperful/ has **two ship-blocking issues** that will break social unfurls and mislead users looking for paperful.io. Relative `og:image` means Slack/Discord/LinkedIn/HN cards will show broken images. Zero mention of the paperful.io name collision means users searching for "paperful" will land on the wrong product with no warning.

Install story is honest (page explicitly says "no docker pull" and "no pip install"). Docker Compose is the documented path, matches repo reality (`compose.yaml` exists, no PyPI package). Pass on install claims.

README as a web artifact is clean (logo, Ko-fi badge, code fences), but the logo path `docs/logo.png` does not match the deployed site structure (`website/images/logo.png` is the live path). Scan path is acceptable: title → lede → five jobs → quick start.

**Don't-ship gates for this lane:**
1. Fix `og:image` to absolute URL (P0)
2. Add paperful.io collision warning above fold on page and README (P0)
3. Fix missing OG/Twitter metadata (P1)

---

## What Was Checked

### Live Page
- **URL:** https://glenwright.earth/Paperful/
- **Fetched:** 2026-09-25 09:33 UTC
- **HTTP headers:** `content-type: text/html; charset=utf-8`, `cache-control: max-age=600`, served via GitHub Pages
- **File:** `website/index.html` (324 lines)

### Repository Files
- `README.md` (169 lines) — scan path, logo reference, install claims
- `website/index.html` — `<head>` metadata, OG tags, favicon, page structure
- `compose.yaml` — confirms Docker Compose is real install path
- `docs/docker.md` — confirms "build-local only, no docker pull" (L3-5)
- Live logo image: https://glenwright.earth/Paperful/images/logo.png (accessible, 495KB PNG)

### Search Evidence
- `grep -i "paperful.io"` in `website/index.html` and `README.md`: **zero matches**
- `grep -i "canonical"` in `website/index.html`: **zero matches**
- `grep -i "og:url\|twitter:card"` in `website/index.html`: **zero matches**

---

## Findings

### P0: Blocks Don't-Share, Don't-Mail

#### 1. Relative `og:image` breaks unfurls (P0)

**Evidence:** `website/index.html` L18:
```html
<meta property="og:image" content="images/logo.png" />
```

**Impact:** Slack, Discord, Twitter/X, LinkedIn, HN, iMessage, WhatsApp, and any other unfurl crawler will fail to fetch the image because `images/logo.png` is interpreted as `https://glenwright.earth/images/logo.png` (missing `/Paperful/` path segment) or fails entirely due to relative URL handling. Result: **broken unfurl cards** on every share.

**Live verification:** `https://glenwright.earth/Paperful/images/logo.png` returns HTTP 200, but unfurl bots will not resolve the relative path correctly from the page base.

**Fix:** Change to absolute URL:
```html
<meta property="og:image" content="https://glenwright.earth/Paperful/images/logo.png" />
```

**Why this is P0:** A share-ready front door means "can paste URL into Slack and get a working card." This fails that test. No point sending this link to collaborators or HN until fixed.

---

#### 2. Zero paperful.io collision warning (P0)

**Evidence:** 
- `grep -i "paperful.io"` in `website/index.html`: **no matches**
- `grep -i "paperful.io"` in `README.md`: **no matches**
- String "paperful.io" does not appear in live page HTML (fetched 2026-09-25)

**Context:** User query states "paperful.io name-collision strip: is it above the fold on the live page and README, or missing?" Answer: **missing entirely**.

**Impact:** Users searching for "paperful" or "paperful.io" (a different product/service) will land on this GitHub repo or the live page with **zero indication** they may be looking for the wrong thing. If paperful.io is an active product, this creates confusion for both user bases.

**Fix:** Add above-fold callout on live page (in hero or immediately below) and in README (after title, before lede):

**Suggested callout (terse):**
> **Note:** This is `github.com/glen-w/Paperful`. If you're looking for the paperful.io service, that is a different product.

**Why this is P0:** If Glen asked for it as a "strip" to check, it means he knows there's a collision risk. Shipping a front door without clarifying this is user-hostile to both products' audiences.

---

### P1: Major Web Design Flaws

#### 3. No `og:url` canonical reference (P1)

**Evidence:** No `<meta property="og:url" ...>` tag in `website/index.html` `<head>` (L1-32).

**Impact:** Social crawlers may not correctly attribute the canonical URL when the page is shared. GitHub Pages serves both `https://glenwright.earth/Paperful/` and potentially `https://glenwright.earth/Paperful/index.html` — without `og:url`, unfurl cards may show inconsistent URLs across platforms.

**Fix:** Add after L18:
```html
<meta property="og:url" content="https://glenwright.earth/Paperful/" />
```

---

#### 4. No `<link rel="canonical">` tag (P1)

**Evidence:** `grep -i "canonical"` in `website/index.html`: **no matches**.

**Impact:** SEO crawlers (Google, Bing) cannot definitively resolve duplicate content if the page is accessible via multiple URLs (trailing slash variations, query params from tracking links). GitHub Pages typically handles this, but explicit `canonical` is best practice.

**Fix:** Add in `<head>` after L11:
```html
<link rel="canonical" href="https://glenwright.earth/Paperful/" />
```

---

#### 5. Missing Twitter card metadata (P1)

**Evidence:** No `<meta name="twitter:card" ...>` tags in `website/index.html`.

**Impact:** Twitter/X unfurls fall back to OG tags, but explicit Twitter card metadata (`twitter:card`, `twitter:image`, `twitter:title`, `twitter:description`) gives better control over card presentation. Without it, Twitter may render a less rich card (e.g., summary instead of summary_large_image).

**Fix:** Add after L18:
```html
<meta name="twitter:card" content="summary_large_image" />
<meta name="twitter:image" content="https://glenwright.earth/Paperful/images/logo.png" />
<meta name="twitter:title" content="paperful — clean the library, find the PDFs, keep a mirror" />
<meta name="twitter:description" content="Clean a reference library, find missing PDFs, summarise papers, and keep a platform-agnostic mirror. Python, Zotero API, Ollama or LiteLLM, Docker." />
```

---

#### 6. README logo path mismatch (P1)

**Evidence:** `README.md` L2:
```html
<img src="docs/logo.png" alt="paperful" width="280">
```

**Live site structure:** Logo is at `website/images/logo.png` (verified accessible at https://glenwright.earth/Paperful/images/logo.png).

**Impact:** On GitHub, `docs/logo.png` may or may not exist (Glob search found no `logo.png` in `/workspace/docs/`). If it doesn't, README shows a broken image. If it does, there are now two copies of the logo (duplication risk). More importantly, **the README path does not match the deployed site path**, creating a mental model mismatch for contributors.

**Fix (choose one):**
1. Move logo to `docs/logo.png` and reference it from `website/index.html` as `../docs/logo.png` (keeps README honest to repo structure).
2. Update README to `<img src="website/images/logo.png" ...>` (matches deployed site structure).
3. Symlink `docs/logo.png` → `website/images/logo.png` (ugly but works).

**Recommendation:** Option 2 — align README with deployed structure. Contributors read the README on GitHub, not the live site; the path should be truthful to the repo layout.

---

#### 7. Favicon only declared as `<link rel="icon">`, no multi-size variants (P1)

**Evidence:** `website/index.html` L11:
```html
<link rel="icon" href="images/logo.png" type="image/png" />
```

**What exists on disk:** `website/images/favicon-32.png` (2.4KB), `website/images/favicon.ico` (94KB).

**Impact:** Modern browsers expect multiple favicon sizes for different contexts (browser tab, bookmark, home screen). Using `logo.png` (495KB) as the favicon is wasteful and not optimized for tab display. The existing `favicon-32.png` and `favicon.ico` are **not referenced** in the HTML.

**Fix:** Replace L11 with:
```html
<link rel="icon" href="images/favicon.ico" sizes="any" />
<link rel="icon" href="images/favicon-32.png" type="image/png" sizes="32x32" />
```

---

### P2: Polish (Not Ship Blockers)

#### 8. No structured data (schema.org) (P2)

**Evidence:** No `<script type="application/ld+json">` block in `website/index.html`.

**Impact:** Search engines cannot extract structured metadata (SoftwareApplication, author, version, license). This is a minor SEO loss but not critical for a GitHub Pages project site.

**Fix (optional):** Add JSON-LD block in `<head>`:
```html
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  "name": "paperful",
  "description": "A research helper that tidies a reference library, finds missing PDFs, and summarises papers.",
  "url": "https://glenwright.earth/Paperful/",
  "applicationCategory": "DeveloperApplication",
  "operatingSystem": "Linux, macOS, Windows",
  "softwareVersion": "0.9.0",
  "license": "https://opensource.org/licenses/MIT"
}
</script>
```

---

#### 9. Logo `alt=""` on page (intentional but not ideal) (P2)

**Evidence:** `website/index.html` L62-67:
```html
<img
  class="hero-logo"
  src="images/logo.png"
  alt=""
  width="140"
  height="140"
/>
```

**Impact:** `alt=""` tells screen readers to skip the image (per HTML5 spec, this is correct for decorative images). However, the logo here is **not purely decorative** — it's the brand mark. Better practice: `alt="paperful logo"`.

**Why this is P2, not P1:** The brand name "paperful" is immediately below the logo in text (L68), so screen reader users are not missing critical information. Still, explicit alt text is better.

**Fix:** Change L65 to `alt="paperful logo"`.

---

## Install Honesty Verification

**Claim 1 (README L63):** "There is no published image and no PyPI package: do not `docker pull` or `pip install paperful`."

**Reality check:**
- `compose.yaml` exists in repo (confirmed)
- `docs/docker.md` L3-5: "The image is **build-local only** (`paperful:local`). There is no `docker pull` and no PyPI package."
- No `pyproject.toml` with `[project]` table for PyPI publishing (checked repo structure)
- README quick start (L77-89) shows `docker compose build` followed by `docker compose run`, **not** `docker pull`

**Verdict:** ✅ **Honest**. No misleading "just pip install" claims. Docker Compose path is real and matches repo.

---

**Claim 2 (website L279-281):** "There is no `docker pull` and no `pip install paperful`. Docker is the operator path."

**Reality check:** Same as above — matches repo structure and `docs/docker.md`.

**Verdict:** ✅ **Honest**.

---

**Claim 3 (Compose mentions on page):** Page mentions "Docker" 3 times (hero tech stack, "Docker is the operator path" in install section). Does not over-promise one-click install.

**Verdict:** ✅ **Honest**. Sets expectation of "git clone → build → run", not "brew install".

---

## README as Web Artifact (Scan Path)

**First screen (L1-14):**
1. **Logo** (centered, 280px) — immediate brand recognition ✅
2. **Tagline** (centered, bold): "Clean the library. Find the PDFs. Keep a mirror." — clear value prop ✅
3. **Lede paragraph** — 4 sentences, covers jobs (library/find/completeness/mirror/control), adapters (Zotero proven, Mendeley/EndNote seeking testers), playbooks, AI browser opt-in, platform-agnostic mirror, local work. Dense but scans well ✅

**Second screen (L14-40):**
- Five jobs explainer (library, find, completeness, mirror, control) — matches page structure ✅
- Hosted site link (L56-58) — points to live page ✅

**Third screen (L60-89):**
- Quick start with Docker Compose commands — matches install honesty claims ✅

**Badges:** None. No CI badge, no license badge, no version badge. **This is fine** — badges are cargo-cult for many projects. The Ko-fi link (L164-166) serves as a "support the project" badge.

**Verdict:** ✅ **Acceptable scan path**. Logo → tagline → lede → jobs → install. No badge clutter. Clear hierarchy.

**One issue:** Logo path mismatch (`docs/logo.png` vs. `website/images/logo.png`) — see Finding #6 (P1).

---

## Checklist to Clear This Lane

### P0 (Ship blockers — must fix before "don't-mail, don't-share" lifts)
- [ ] **Fix `og:image` to absolute URL** (`https://glenwright.earth/Paperful/images/logo.png`)
- [ ] **Add paperful.io collision warning** above fold on `website/index.html` (hero or immediately below) and in `README.md` (after title, before lede)

### P1 (Major fixes — should fix before public launch)
- [ ] Add `<meta property="og:url" content="https://glenwright.earth/Paperful/" />`
- [ ] Add `<link rel="canonical" href="https://glenwright.earth/Paperful/" />`
- [ ] Add Twitter card metadata (`twitter:card`, `twitter:image`, `twitter:title`, `twitter:description`)
- [ ] Fix README logo path to match deployed site structure (`website/images/logo.png`)
- [ ] Replace favicon declaration to use `favicon.ico` and `favicon-32.png` instead of `logo.png`

### P2 (Polish — nice to have)
- [ ] Add schema.org structured data (JSON-LD block)
- [ ] Change logo `alt=""` to `alt="paperful logo"` on live page

**Estimated effort:** 20 minutes for P0 fixes, 30 minutes for P1 fixes, 15 minutes for P2 polish. Total: ~65 minutes.

---

## Adjacent Concerns (Owned by Other Lanes)

**Not assessed here:**
- **Design eye:** Logo quality, color palette, typography, visual hierarchy, responsive design, dark mode — owned by Design eye lane
- **Marketeer:** Copy tone, call-to-action wording, "See how it works" vs. "Get started", Ko-fi placement — owned by Marketeer lane
- **UX (operator first-hour):** CLI first-run friction, `doctor` output, config overload — covered in [critical-review-usability-docs-features.md](./2026-09-25-critical-review-usability-docs-features.md) by Researcher
- **Engineer:** `compose.yaml` structure, Dockerfile quality, build reproducibility — owned by Engineer lane

**Related finding from Researcher's assessment:** Researcher flagged "no zero-to-first-PDF tutorial" (P0) and "Docker vs `uv` install path incoherence" (P0). Those are **UX first-hour issues**, not front-door web design. This assessment confirms the **front-door honesty** (no false pip/pull claims) but does not evaluate whether the Compose path is easy to follow — that's UX lane.

---

## Summary

**Pass:** Install honesty, README scan path, page structure  
**Fail:** OG unfurl quality (relative image), missing paperful.io collision warning  
**Needs work:** Missing canonical/Twitter metadata, favicon optimization, logo path mismatch

**Don't-ship this lane until:** P0 fixes (absolute og:image + paperful.io warning) are deployed.

**Cross-reference:** See [critical-review-usability-docs-features.md](./2026-09-25-critical-review-usability-docs-features.md) for operator first-hour UX assessment (5 P0s: no tutorial, Docker/uv incoherence, three-docs contradictions, 194-line config, EZProxy assumptions).
