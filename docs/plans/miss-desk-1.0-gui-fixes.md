# Miss desk 1.0 GUI update plan

**Baseline SHA:** `6e416c4` (Wire Repair and Mirror GUI to library preview/apply cores #23)  
**Assessment date:** 2026-10-07  
**Scope:** Miss desk 1.0 only — excludes Discover share-crop, Card catalogue OG, full Workbench depth  

---

## Executive summary

The GUI exists and Wanted is the correct door for Miss desk 1.0. However, **critical honesty bugs block 1.0 shipment**: the default `attach_verified=True` makes "Grab" silently write to Zotero for first-hour users when they expect a fetch-only operation. The separate "Attach" button is **hidden** when this default is on, so strangers never see that Grab will perform a library write.

**Stop-ship P0 (write-surface honesty):** Four bugs must be fixed in the same pass before any chrome/polish work:
1. Flip `attach_verified` default to **off** (missing cookie → `"0"`, dataclass `False`)
2. Remove auto-attach logic from Grab (fetch-only in all cases)
3. Create separate, always-visible, labeled "Attach N PDFs to Zotero" button + enable hand-ticks on Held mismatch/unverified rows
4. Fix "Apply selected" to respect selected keys on fetch (or rename to "Apply all in scope")

**P1 (stranger first-hour):** Three high-priority UX issues: empty Wanted coaching, nav order (Wanted first, Discover to Advanced), Preview primary vs. equal-weight Grab.

**P2 (polish & docs):** Version alignment, `docs/gui.md` scope reconciliation, CLI docstring fixes.

**Verdict:** GUI exists; localhost bind passes; verification stamps exist — but write-surface honesty is **broken by default**, empty-state coaching is missing, and nav/verb naming conflicts with the room locks.

---

## Priority order

This plan orders fixes by:
1. **P0 (Stop-ship honesty — write-surface trust traps)** — Silent Grab→Zotero write is the #1 blocker. All four P0 items must be fixed in the same pass:
   - P0.1: Flip `attach_verified` default **off** (missing cookie → `"0"`, dataclass `False`)
   - P0.2: Remove auto-attach from Grab (fetch-only always)
   - P0.3: Separate labeled Attach button + enable hand-ticks on Held
   - P0.4: Fix "Apply selected" keys scope (or honest label)
2. **P1 (Stranger first-hour UX)** — Empty Wanted coaching / nav order (Wanted first, Discover to Advanced) / Preview primary vs. equal-weight Grab / Discover broken appearance
3. **P2 (Polish & docs)** — Version alignment / docs drift / CLI docstring / control styling / OG readiness

**Critical note:** P0 items are bundled as one write-surface honesty pass. Flipping the default off (P0.1) is essential because otherwise "Attach stays hidden and Grab still writes Zotero for first-hour users." No Wanted chrome or share-crop polish work should proceed until P0.1–P0.4 are complete.

---

## P0: Stop-ship honesty fixes (write-surface trust traps)

**Critical:** The default `attach_verified=True` makes Grab **silently write to Zotero** on first-hour use. This is the #1 blocker for Miss desk 1.0. All four P0 items are write-surface honesty bugs that must be fixed in the same pass before any chrome/polish work.

### P0.1 — Flip `attach_verified` default to OFF (stop-ship blocker #1)

**Problem:**  
Cookie `pf_attach_verified` defaults to `"1"` (on) in `prefs.py:30`, and the dataclass default is `attach_verified: bool = True` (line 21). For a **first-hour user with no cookie**, this evaluates to **True**, making "Grab all" silently attach every `doi_match` row to Zotero after fetch. The "Attach N PDFs…" button is **hidden** when `attach_verified` is on (`wanted.html:16`), so the stranger never sees that Grab will write to their library. This is a **trust trap**: they see one button that reads as "fetch to disk" but it performs a library write without explicit consent.

**Source:** Miss-desk claim↔code report, packaging slice report, room 💻 P0 lock; code at `paperful/ui/prefs.py:21,30`, `paperful/ui/jobs.py:152-181`, `paperful/ui/templates/wanted.html:16`.

**Proposed change:**  
1. **Change default cookie fallback** in `prefs.py:30` from `attach = (cookies.get(COOKIE_ATTACH_VERIFIED) or "1") == "1"` to `attach = (cookies.get(COOKIE_ATTACH_VERIFIED) or "0") == "1"`.
2. **Change dataclass default** in `prefs.py:21` from `attach_verified: bool = True` to `attach_verified: bool = False`.
3. Keep the Settings opt-in "Attach verified automatically" for power users who understand the behavior (unchecked by default).
4. Update tests to reflect new default (currently `test_ui_grab.py` assumes default is on).

**Success criteria:**  
- Fresh session (no cookie) → `attach_verified = False` → Grab fetches to `out/` only, **no Zotero attach**.
- "Attach N PDFs…" button is **visible** on fresh session (not hidden).
- Settings page shows "Attach verified automatically" toggle, default **unchecked**.
- Test `test_ui_grab.py` passes with new default off; add test case for explicit cookie on.

**Docs touch:**  
- `docs/gui.md` P0 note: "Grab fetches to out/ only by default. Opt-in 'Attach verified automatically' in Settings for power users."

---

### P0.2 — Remove auto-attach from Grab; ensure fetch-only by default

**Problem:**  
Even after P0.1, the Grab code path still has conditional auto-attach logic: `if attach_verified: _attach_doi_match(...)` (`jobs.py:152-154`). If a user or test sets the cookie/pref to True, Grab will still silently write to Zotero. The Settings toggle should **only** control whether the separate Attach button offers `doi_match` rows pre-ticked — it must **not** make Grab write to Zotero automatically.

**Source:** Miss-desk claim↔code report, room 💻 P0 lock; code at `paperful/ui/jobs.py:152-154`.

**Proposed change:**  
1. **Remove lines 152-154** from `grab_run` in `jobs.py`: delete the entire `if attach_verified: _attach_doi_match(...)` block.
2. Grab becomes **fetch-only** in all cases (no conditional attach).
3. The `attach_verified` pref now only affects UI presentation: when on, `doi_match` rows are pre-ticked in the Attach button flow (not auto-attached by Grab).

**Success criteria:**  
- Grab never calls `_attach_doi_match` or `Pipeline.attach_record`, regardless of `attach_verified` setting.
- Grab always passes `no_attach=True` to `run_fetch` and stops there.
- Test covers: Grab with `attach_verified=True` (legacy opt-in) still does **not** attach.

**Docs touch:**  
- No external doc change (internal code fix ensures fetch-only).

---

### P0.3 — Create separate, labeled Attach button + enable hand-ticks on Held

**Problem:**  
Current "Attach N PDFs to this Zotero library" button (`wanted.html:16`) is:
- **Hidden** when `attach_verified` is on (so first-hour users never see it).
- Shares the **same** `formaction="/wanted/grab"` when visible (not a distinct operation).
- When visible, still calls `grab_run(..., attach_verified=prefs.attach_verified)` which evaluates to False but does **not** attach — there is no real attach-only code path.

Additionally, on the Held tab, checkboxes for `doi_mismatch` and `unverified` rows are `disabled` (`wanted.html:24`), blocking the room lock requirement for "doi_match + hand-ticks" attach.

**Source:** Miss-desk claim↔code report, packaging slice report, room 💻 P0 lock; code at `paperful/ui/templates/wanted.html:16,24`, `paperful/ui/jobs.py`.

**Proposed change:**  
1. **Always show** "Attach N PDFs…" button (remove `{% if prefs.attach_verified %}hidden{% endif %}` from `wanted.html:16`).
2. **Change `formaction`** from `/wanted/grab` to `/wanted/attach`.
3. **Create new `POST /wanted/attach` route** in `app.py` that:
   - Takes a list of `keys` from checked boxes.
   - Only attaches ticked rows: `doi_match` rows (pre-ticked by `pages.py:44`) plus any user hand-ticked rows from Held.
   - Calls `Pipeline.attach_record` directly for each key (similar to `_attach_doi_match` at lines 158-181 in `jobs.py`, but key-scoped and not doi_match-filtered).
4. **Enable hand-ticks on Held:** Remove `{% if tab == 'held' and not row.ticked %}disabled{% endif %}` from checkbox in `wanted.html:24`.
5. **Update button label** dynamically based on ticked count: "Attach N PDFs to Zotero" where N = count of checked rows.
6. Optional: Rename "Grab" to "Apply" to align with Repair/Mirror preview → apply pattern (but keep endpoint as `/wanted/grab` for now, or rename to `/wanted/apply` in same pass).

**Success criteria:**  
- "Attach N PDFs to Zotero" button is always visible, clearly labeled as a library write.
- Attach button has distinct `formaction="/wanted/attach"` (not shared with Grab).
- Held tab: `doi_match` rows are pre-checked; `doi_mismatch` and `unverified` rows are **unchecked but enabled** for hand-ticks.
- User can manually tick a `doi_mismatch` row → Attach includes it.
- Tests cover: Apply with no attach, Attach after Apply, Attach with hand-ticked mismatch rows.

**Docs touch:**  
- `docs/gui.md` P0: "Preview → Apply (fetch to out/) → Attach (write verified PDFs to Zotero). Apply never touches Zotero; Attach is explicit and labeled."

---

### P0.4 — Fix "Apply selected" to respect selected keys on fetch

**Problem:**  
Preview creates a review token with `keys` (`jobs.py:80-91`), but production `grab_run` → `run_fetch` (else branch, lines 123-151) has **no `keys=` parameter** passed to the real CLI invocation. Test hook at line 120 passes `keys=list(keyset)`, but the real `run_fetch` at line 141 omits keys entirely — it fetches the entire collection/library scope. Attach step is key-filtered (lines 158-166), but **fetch is not**. Button label "Grab selected" / "Apply selected" **overclaims** by fetching everything while claiming to be scoped.

**Source:** Miss-desk claim↔code report, packaging slice report, room 💻 P0 lock; code at `paperful/ui/jobs.py:113-151`.

**Proposed change:**  
**Option A (preferred):** Thread `keys` into real `run_fetch` call. Check if CLI `run_fetch` in `run_cmd.py` supports a `keys=` parameter (likely needs to be added). If not, pre-filter items in `grab_run` before calling fetch:
1. Load scope items at line 106.
2. Filter `items = [it for it in items if it.key in keyset]` before passing to `run_fetch`.
3. Or: Pass `keys=list(keyset)` to `run_fetch` at line 141 and extend `run_fetch` signature to accept `keys` (same as test hook).

**Option B (honest label, if Option A is infeasible for 1.0):** Rename buttons from "Preview selected" / "Apply selected" to "Preview all" / "Apply all in scope". Remove per-row checkboxes from Missing/Held tabs (only keep them on Have tab for Attach). Make Preview/Apply whole-scope only; selection is Attach-only.

**Success criteria:**  
- **If Option A:** Preview with 3 selected rows → Apply → only those 3 PDFs are fetched (verified in `out/` manifest or logs). Test `test_ui_grab.py` covers selected-key fetch, not just attach filter.
- **If Option B:** Button labels are honest ("Apply all in scope"), checkboxes removed from Missing/Held, and docs clarify whole-scope behavior.

**Docs touch:**  
- If Option A: No change (selected-key fetch is implicit in "Apply selected").
- If Option B: `docs/gui.md` P0 note: "Wanted Preview/Apply is whole-scope; per-item selection is for Attach only."

---

## P1: Stranger first-hour fixes

These issues affect discoverability, navigation, and empty-state experience for new users. Not stop-ship honesty bugs, but block a friendly first hour.

### P1.1 — Empty Wanted coaching and Zotero-down UX

**Problem:**  
When Zotero is down or no collection is selected, Wanted shows blank rows and a small red health dot with no readable text. Stranger sees empty table, two action buttons (Preview/Grab), and no next-step guidance. First hour fails before any miss list appears.

**Source:** Usability report, P0 issue #1; UI at `paperful/ui/templates/wanted.html`.

**Proposed change:**  
1. Detect Zotero-down or no-collection state in Wanted route (`app.py`).
2. When empty:
   - Add amber banner above table: "Connect Zotero with local API enabled, or pick a collection to see missing PDFs."
   - Link to System page for doctor steps.
   - Replace buttons with disabled state or hide them (no Preview/Grab when there are no rows).
3. When populated but zero missing: show success message instead of empty table.
4. Expand health dot to short text: "Zotero offline" or "No collection selected" (link to System).

**Success criteria:**  
- Zotero down → amber banner with actionable next step, no broken controls.
- No collection → coaching to pick collection chip or check System.
- Populated library with zero missing → "All PDFs found" message, no empty table.
- Health status renders as text + icon (not just red dot).

**Docs touch:**  
- `docs/gui.md` P1: "First-time setup: start Zotero with local API, pick a collection, then Preview."

---

### P1.2 — Reorder nav: Wanted first, demote Discover

**Problem:**  
Discover is first in nav tabs (`base.html:22-27`) even though `/` redirects to `/wanted`. Door stills and muscle memory suggest Discover is primary. SEO/Design: never Discover as hero for Miss desk 1.0. Stranger confusion: "Why is the first tab broken (empty queue)?"

**Source:** Usability report, P0 issue #3; code at `paperful/ui/templates/base.html:22-27`.

**Proposed change:**  
1. Reorder nav: **Wanted · Library · Activity · System** on default bar.
2. Move Discover to Advanced (same reveal as Repair/Mirror/Index/Briefs).
3. Update `base.html` nav order to match.
4. Consider: for Miss desk 1.0, hide Discover entirely behind Advanced (only expose once card catalogue OG is ready).

**Success criteria:**  
- Default nav (Advanced off): Wanted is leftmost tab.
- Discover only visible when Advanced is on (or removed from default nav entirely).
- No stranger sees "broken" Discover queue as first impression.

**Docs touch:**  
- `docs/gui.md` P1: Update nav order table to reflect Wanted-first.
- If Discover is Advanced-only: "Discover (topic/person tracking) is an Advanced feature for Miss desk 1.0."

---

### P1.3 — Preview primary, Grab/Apply demoted until after review

**Problem:**  
Preview and Grab buttons have equal visual weight (both terracotta, side-by-side, same size). Room lock: dry-run default, explicit Apply only after reviewed preview. Current UX sells Grab as peer of Preview, failing the "not one-click write" bar (even after P0.1 fix).

**Source:** Usability report, P0 issue #2; UI at `paperful/ui/templates/wanted.html:14-16`.

**Proposed change:**  
1. Make Preview **primary** button (solid terracotta, left).
2. Demote Apply to **secondary** (outline or muted, right) until after Preview has run.
3. After Preview redirect (`?run=...`), show Apply/Attach buttons with review token context.
4. Option: Add workflow hint below buttons: "Preview first → review → then Apply."
5. Rename Grab → Apply throughout UI (aligned with P0.2).

**Success criteria:**  
- Preview button is visually primary (color, position, size).
- Apply/Attach buttons are secondary or hidden until Preview completes.
- No equal-weight verbs suggesting one-click Zotero write.

**Docs touch:**  
- `docs/gui.md` P1: "Wanted workflow: Preview all → review missing PDFs → Apply to fetch → Attach verified copies."

---

### P1.4 — Hide or fix Discover empty queue rows

**Problem:**  
Discover Queue shows ~40 empty rows (blank Title/DOI, each with None / Keep / Skip controls). Looks broken, poisons any demo or stranger visit. Unrelated to Miss desk 1.0 scope, but visible on default nav (pre-P1.2 fix).

**Source:** Usability report, P0 issue #4; Discover queue logic in `paperful/ui/pages.py`, `templates/discover.html`.

**Proposed change:**  
Option A (preferred for Miss desk 1.0): Move Discover to Advanced (per P1.2), so it's not visible to strangers.

Option B (if Discover stays on default nav):
1. Filter empty queue rows in `pages.py` (skip rows with no title/DOI).
2. Add empty-state message: "No pending candidates. Track a topic or follow a person to see new works here."
3. Hide Keep/Skip controls when queue is empty.

**Success criteria:**  
- Discover Queue never shows ghost rows with blank titles.
- Empty state has helpful coaching, not a broken-looking table.
- Or: Discover is Advanced-only for Miss desk 1.0 (deferred fix).

**Docs touch:**  
- If Option A: `docs/gui.md` note Discover is Advanced.
- If Option B: `docs/gui.md` P1: "Discover Queue is empty until you track a topic or follow a person."

---

## P2: Polish and documentation alignment

These are not blockers for a trust-safe Miss desk 1.0, but improve coherence, findability, and maintainability.

### P2.1 — Align version between `/health` and `pyproject.toml`

**Problem:**  
`GET /health` reports `0.8.0` while `pyproject.toml` says `0.9.0`. Packaging slice notes version drift. Affects trust if users compare public version to internal claims.

**Source:** Miss-desk claim↔code report, packaging slice report; code at `paperful/__version__.py` (inferred), `pyproject.toml`.

**Proposed change:**  
1. Audit true version: what was the last tagged release? If `0.8.0` is correct, update `pyproject.toml` to match. If `0.9.0` is correct, update `__version__.py`.
2. Prefer: next tag is `1.0.0` once Miss desk 1.0 ships (avoid fractional pre-release drift).
3. Add CI check: fail if `pyproject.toml` version != `__version__` constant.

**Success criteria:**  
- `/health` and `pyproject.toml` report the same version.
- CI prevents future drift.

**Docs touch:**  
- No doc change (internal consistency fix).

---

### P2.2 — Reconcile `docs/gui.md` 1.0 claim with Miss desk scope

**Problem:**  
`docs/gui.md` lines 1-7 call the full workbench (Discover, Repair, Mirror, Ask) a "1.0 target." Options locks (2026-10-06) and MARKETING/HONESTY say Miss desk = 1.0, Workbench after 1.0. Contradiction must be resolved before any invite or OG paste.

**Source:** Miss-desk claim↔code report; `docs/gui.md` intro vs. options locks report.

**Proposed change:**  
1. Update `docs/gui.md:1-7` to state: "1.0 adds **Miss desk** (Wanted server-rendered UI for gaps/run/attach). Full workbench (Discover share-crop, Ask, advanced Repair/Mirror) is post-1.0."
2. Keep detailed sections for Discover/Repair/Mirror/Ask but mark them "Advanced (post-1.0)" or "Roadmap."
3. Lead with Miss desk simple loop (lines 54-70) as the 1.0 user path.
4. Add cross-ref to ROADMAP.md product split.

**Success criteria:**  
- `docs/gui.md` intro clearly states Miss desk = 1.0, workbench depth = post-1.0.
- No contradiction with MARKETING.md or options locks.
- Strangers reading docs understand the 1.0 scope.

**Docs touch:**  
- `docs/gui.md` intro rewrite (lines 1-10).
- Optional: add "Miss desk 1.0" H2 section before "Simple loop" to clarify scope.

---

### P2.3 — Update CLI `serve` docstring to reflect GUI writes

**Problem:**  
`paperful/cli.py:1072` docstring says "Dry-run. … **No library writes.**" and `serve.py:4` header says "Writes stay on the CLI." Both are false once workbench is mounted: Grab/Discover/Repair/Mirror can write to Zotero over HTTP (via review tokens). Misleading for operators reading `paperful serve --help`.

**Source:** Packaging slice report; code at `paperful/cli.py:1072`, `paperful/serve.py:4`.

**Proposed change:**  
1. Update `cli.py` `serve` command docstring: "Start the local workbench on 127.0.0.1:8765. Wanted/Discover/Repair/Mirror may write to Zotero after explicit Preview → Apply. Capability JSON routes `/v1/*` remain dry-run."
2. Update `serve.py:4` header: "Writes are gated by review tokens; no auto-writes on serve start."
3. Keep note accurate for `/v1/refs-gap` and `/v1/ask` (dry-run / no Zotero touch).

**Success criteria:**  
- `paperful serve --help` reflects that GUI can write after explicit Apply.
- No claim of "no library writes" in serve docstring.

**Docs touch:**  
- No external doc change (internal docstring only).

---

### P2.4 — Style Discover form controls to warm-paper tokens

**Problem:**  
Discover uses native browser chrome (date pickers, raw blue "Fill PDFs" link). Breaks warm-paper coherence established by Wanted/Library. Noted in usability report P2 issue #8.

**Source:** Usability report, P2 issue #8.

**Proposed change:**  
Defer to post-1.0 or when Discover moves to card catalogue UI. For Miss desk 1.0 (with Discover in Advanced), this is low priority.

If fixed: style form controls in `discover.html` / `static/style.css` to match terracotta buttons, beige inputs, Fraunces/Source Sans fonts.

**Success criteria:**  
- Discover controls match Wanted/Library look (warm paper, no raw browser chrome).
- Or: deferred as "Advanced surfaces polish" post-1.0.

**Docs touch:**  
- None (visual polish only).

---

### P2.5 — Persist Advanced off by default for strangers

**Problem:**  
Advanced toggle state is cookie-based but not explicitly set to off for first visit. If a user enables Advanced and clears cookies, they see default (off) on return — this is correct. However, no explicit onboarding "Advanced is off" state means some confusion if docs mention Repair/Mirror without Advanced context.

**Source:** Usability report, P2 issue #9.

**Proposed change:**  
1. Ensure `prefs.py` default `advanced = False` (already correct at line 20).
2. Add inline note on Wanted or first page: "Enable Advanced to access Repair, Mirror, Index, Briefs" (dismissible tip for first visit).
3. Or: keep implicit (current behavior is correct; no change needed).

**Success criteria:**  
- Default nav for fresh session: Wanted · Library · Activity · System only (no Repair/Mirror/Index/Briefs).
- Advanced toggle is discoverable (e.g., gear icon or "Advanced" text link in nav).

**Docs touch:**  
- `docs/gui.md` P2: "Default nav shows Miss desk surfaces. Toggle Advanced to reveal Repair, Mirror, Ask."

---

## Packaging PASS items (no work needed)

The following items from the packaging slice report **passed** room locks and require no changes:

1. **Port `127.0.0.1` bind by default** — CLI default is `127.0.0.1:8765`; `compose.gui.yaml` publishes `127.0.0.1:8765:8765` (host-side localhost-only). ✅ Pass.
2. **Found rows show source + verification** — `file_verification` in `verify.py` returns `doi_match`, `doi_mismatch`, `unverified` (plus `snapshot`/`missing`). Wanted drawer displays Source + Verification. ✅ Pass.
3. **Ask off default nav** — Ask is under Advanced → Index, not on Wanted. `/v1/ask` JSON API is still registered (see optional P2.6 below), but HTML nav is correct. ✅ Pass.
4. **Summary counts, not % complete** — Wanted shows "Have N · Held N · Missing N" with no % complete metric. ✅ Pass.
5. **Verification stamps exist** — `doi_match` → terracotta "found" stamp, `doi_mismatch` → "check" stamp, `unverified` → plain state text. ✅ Pass (UI exists; needs real-Zotero validation once empty-state is fixed).

---

## Optional P2.6 — Ship-or-hide `/v1/ask` JSON route

**Problem:**  
`/v1/ask` is registered on `serve.py:54` with no flag gate, the same trap TranscriptX had. Room decision: Ask stays off the page (✅ done) but the JSON route is still open. Options locks defer Ask ship-or-hide decision.

**Source:** Options locks report; code at `paperful/serve.py:54`.

**Proposed change:**  
Option A: Gate `/v1/ask` behind `cfg.llm_enabled and cfg.rag_enabled` (same as HTML Ask on Index).

Option B: Document `/v1/ask` as "capability API, operator-only" in `docs/gui.md` (not advertised, but open for MCP/scripts).

Option C: Defer decision — current state (Ask off HTML nav) is acceptable for Miss desk 1.0; JSON route for power users is fine.

**Success criteria:**  
- If Option A: `/v1/ask` returns 403 or 501 when LLM/RAG are off.
- If Option B: `docs/gui.md` notes `/v1/ask` is operator/MCP surface, not GUI-linked.
- If Option C: no change (defer to post-1.0).

**Docs touch:**  
- If Option A or B: `docs/gui.md` "HTTP capability API" section updated.

---

## Out of scope for Miss desk 1.0

The following items are explicitly **excluded** from Miss desk 1.0 per the room locks and reports:

1. **Discover share-crop / Card catalogue OG** — Wanted is table-only for 1.0; card design is post-1.0 when OG/invite are ready.
2. **Full Workbench depth** — Repair/Mirror/Ask/Briefs workbench is post-1.0 (keep behind Advanced).
3. **Print/A4 client report stylesheet** — Design suggestion for Ko-fi service; defer until card UI exists.
4. **Live paperful.app title/desc/OG updates** — Blocked until GUI ships with Compose CI; no paste until cards + stamp proof exist.
5. **Discover queue Keep/Skip briefing/digest UX** — Workbench surface, not Miss desk 1.0.
6. **Per-item summarize in Wanted drawers** — Already behind Advanced + `llm_on`; acceptable but not core to Miss desk.

---

## Implementation order (suggested)

For agent or developer implementing these fixes:

**Phase 1 (Stop-ship honesty — one bundled pass, do not split):**

All four P0 items must be completed together in sequence before any chrome/polish work:

1. **P0.1** — Flip `attach_verified` default off in `prefs.py` (cookie fallback `"0"`, dataclass `False`)
2. **P0.2** — Remove `if attach_verified: _attach_doi_match(...)` from `grab_run` in `jobs.py` (fetch-only always)
3. **P0.3** — Create `POST /wanted/attach` route, always-visible labeled button, enable hand-ticks on Held (`wanted.html` remove `disabled` check)
4. **P0.4** — Thread `keys` into `run_fetch` call (Option A) or rename to "Apply all in scope" (Option B)

**Rationale:** Flipping the default off (P0.1) is essential because otherwise "Attach stays hidden and Grab still writes Zotero for first-hour users." The separate Attach button (P0.3) must be visible and labeled before any stranger uses Wanted. Selected-keys honesty (P0.4) is part of the same write-surface trust fix.

**Phase 2 (Stranger first-hour UX):**

5. P1.1 — Empty Wanted coaching (amber banner, health text, doctor link)
6. P1.2 — Nav reorder (Wanted first, Discover to Advanced)
7. P1.3 — Preview primary, Apply/Attach secondary (visual weight + workflow hint)

**Phase 3 (Polish & docs alignment):**

8. P2.1 — Version alignment (`/health` vs. `pyproject.toml`)
9. P2.2 — `docs/gui.md` scope reconciliation (Miss desk = 1.0, workbench depth = post-1.0)
10. P2.3 — CLI docstring fix (`serve` no longer claims "no library writes")
11. P2.5 — Advanced off by default (verify existing behavior)

**Optional / deferred:**
- P2.6 — Ship-or-hide `/v1/ask` (defer decision; current state acceptable for Miss desk 1.0)
- P1.4 — Discover empty queue (covered by P1.2 if Discover → Advanced; if not, fix queue filter)
- P2.4 — Discover control styling (defer to post-1.0 or card catalogue UI)

---

## Testing requirements

Each P0/P1 fix must include:

- **Unit test** for changed functions (e.g., `test_ui_grab.py` for P0.1/P0.2).
- **Integration test** for routes (e.g., POST `/wanted/attach` returns 200 with valid keys).
- **Manual walkthrough** with Zotero up, empty library, populated library (covers P1.1 coaching, P0.2 Apply/Attach split).
- **Regression check** on existing tests (especially `test_ui_rows.py`, `test_ui_grab.py`, `test_ui_jobs.py`).

---

## Success metrics for Miss desk 1.0 shipment

Miss desk 1.0 is ready to ship when:

**P0 (Stop-ship honesty — all four required):**
1. ✅ Fresh session (no cookie) → `attach_verified = False` → Grab/Apply fetches to `out/` only, **no silent Zotero write**.
2. ✅ Grab **never** calls `_attach_doi_match` or `Pipeline.attach_record`, regardless of `attach_verified` setting (fetch-only always).
3. ✅ Separate "Attach N PDFs to Zotero" button is **always visible**, clearly labeled, distinct `formaction="/wanted/attach"`.
4. ✅ Held tab: `doi_match` rows pre-checked; `doi_mismatch`/`unverified` rows **enabled** for hand-ticks.
5. ✅ "Apply selected" respects selected keys on fetch (Option A), or button label is honest "Apply all in scope" (Option B).

**P1 (Stranger first-hour — required for friendly onboarding):**
6. ✅ Empty Wanted shows coaching (amber banner, health text, doctor link) when Zotero down or no collection.
7. ✅ Nav order: Wanted first; Discover in Advanced (or styled/fixed if on default nav).
8. ✅ Preview is visually primary; Apply/Attach are secondary/demoted until after review.

**P2 (Polish — required for documentation coherence):**
9. ✅ Version aligned across `/health` and `pyproject.toml`.
10. ✅ `docs/gui.md` states Miss desk = 1.0, workbench depth = post-1.0.
11. ✅ CLI `serve` docstring reflects that GUI can write after explicit Apply (no "no library writes" claim).

**Testing:**
12. ✅ All P0/P1/P2 tests pass; manual walkthrough with real Zotero (down, empty, populated) succeeds.
13. ✅ Regression: existing tests (`test_ui_rows.py`, `test_ui_grab.py`, `test_ui_jobs.py`) pass with new defaults.

---

## Cross-references

- **Source reports:**
  - `Paperful-GUI-miss-desk-2026-10-07_ba36.md` (claim↔code assessment)
  - `Paperful-GUI-usability-2026-10-07_756c.md` (stranger/door walk)
  - `paperful-gui-packaging-slice-2026-10-07_655b.md` (packaging/bind/write surfaces)
  - `Paperful-GUI-options-2026-10-06_2ec0.md` (room locks)
- **Baseline SHA:** `6e416c4` (`main`)
- **Related docs:**
  - `docs/gui.md` (workbench overview — needs P2.2 scope update)
  - `docs/ROADMAP.md` (product split: 1.0 vs post-1.0)
  - `MARKETING.md` and `HONESTY.md` (room framing, not in tree on this SHA)

---

**Plan prepared:** 2026-10-07  
**For review by:** Glen / Design / UX / Researcher (rooms 💻💻💻 + 📣📣📣)  
**Next step:** Implement Phase 1 (P0 stop-ship fixes) → test → Phase 2 (P1 stranger UX) → tag Miss desk 1.0.
