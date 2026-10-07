# Miss desk 1.0 GUI update plan

**Baseline SHA:** `6e416c4` (`main`)  
**Assessment date:** 2026-10-07  
**Revised:** 2026-10-07 (sanity check vs current tree; lean rewrite)  
**Scope:** Miss desk 1.0 only — Wanted write-surface honesty + thin first-hour UX. No Discover share-crop, Card catalogue OG, or full Workbench.

Sources folded in: claim↔code, usability/door walk, packaging slice, options locks (2026-10-06).

---

## Verdict

Wanted is the right door. Localhost bind, verify stamps, Ask-off-nav, and Have/Held/Missing counts already pass.

**Stop-ship:** default-on `attach_verified` makes Grab silently write Zotero for first-hour users while hiding the Attach control. The visible “Attach” button is not a real attach path. “Grab selected” overclaims because production fetch ignores token keys.

Ship write-surface honesty before chrome.

---

## Sanity check (what to keep / drop)

| Claim | Current tree | Decision |
| --- | --- | --- |
| Default `attach_verified=True` + Attach hidden | [`prefs.py`](../../paperful/ui/prefs.py) dataclass `True`, cookie fallback `"1"`; [`wanted.html`](../../paperful/ui/templates/wanted.html) hides Attach when on | **P0** |
| Fake Attach (same `/wanted/grab`) | No attach-only route in [`app.py`](../../paperful/ui/app.py) | **P0** |
| Held mismatch/unverified checkboxes disabled | `wanted.html` | **P0** |
| “Grab selected” overclaims | Token stores keys; production `grab_run` else-branch calls [`run_fetch`](../../paperful/run_cmd.py) with **no** key filter; test hook passes `keys=` | **P0** |
| “Just pass `keys=` to `run_fetch`” | **Wrong** — `run_fetch` has no such arg | Add optional `item_keys` filter after catalog load |
| Keep Settings “Attach verified automatically” wired to Grab | Still a silent Grab→Zotero trust trap if left on | Grab never attaches; remove Settings checkbox for 1.0 |
| Discover → Advanced + empty Discover queue as P1 | `/` already → `/wanted`; Discover is 📣 product | **Defer** |
| Preview visual weight as P1 | Review token already gates Grab | **Defer** |
| Rename Grab → Apply as honesty gate | Nice copy; not required if Grab is fetch-only and Attach is real | **Defer** |
| Version `0.8.0` vs `pyproject` `0.9.0`, serve “no writes” docstring, `docs/gui.md` full-workbench 1.0 claim | Real docs debt | Note only; optional ride-along |
| Ship-or-hide `/v1/ask` | Off HTML nav already | **Out of Miss desk 1.0** |

---

## P0 — write-surface honesty (one bundled pass)

Do these together before Wanted chrome or share-crop polish.

### P0.1 — Default `attach_verified` off

**Problem:** Missing cookie → `"1"` and dataclass default `True` ([`prefs.py`](../../paperful/ui/prefs.py)). Fresh session Grab auto-attaches `doi_match` rows and hides Attach.

**Change:** Dataclass `False`; missing cookie → `"0"`.

**Success:** Fresh session → Grab does not attach; Attach control is not hidden by default.

**Docs:** One line in [`docs/gui.md`](../gui.md): Grab is fetch-only by default.

### P0.2 — Grab fetch-only always

**Problem:** [`jobs.py`](../../paperful/ui/jobs.py) `grab_run` still does `if attach_verified: _attach_doi_match(...)`. A Settings toggle that re-enables silent Grab→Zotero is still a trust trap.

**Change:** Remove auto-attach from `grab_run`. Grab always ends after `run_fetch(..., no_attach=True)`.

**Success:** Grab never calls attach, even if a leftover cookie is `"1"`.

**Docs:** Settings no longer documents “Attach verified automatically” as Grab behavior.

### P0.3 — Real Attach + hand-ticks

**Problem:** Attach button shares `formaction="/wanted/grab"`, is hidden when auto-attach is on, and does not attach when visible. Held non-`doi_match` checkboxes are `disabled`, so “doi_match + hand-ticks” is impossible.

**Change:**
- Always-visible labelled “Attach N PDFs to this Zotero library”
- New `POST /wanted/attach` (not shared with Grab)
- Attach only `doi_match` plus user hand-ticks
- Enable Held checkboxes for mismatch/unverified (unticked by default; `doi_match` stays pre-ticked)
- Remove Settings “Attach verified automatically” checkbox (prefer remove over a confusing relabel)

**Success:** Attach is a distinct Zotero write; Held hand-ticks work; Grab never writes the library.

**Docs:** [`docs/gui.md`](../gui.md) Wanted loop: Preview → Grab (fetch to `out/`) → Attach (explicit library write).

### P0.4 — Selected-keys honesty on fetch

**Problem:** Preview token stores selected keys; production `grab_run` else-branch ignores them. Attach is key-filtered; fetch is whole collection/library. “Grab selected” overclaims. `run_fetch` has no `keys`/`item_keys` today; CLI `run` has no `--item`.

**Change:** Add optional `item_keys` filter in [`run_fetch`](../../paperful/run_cmd.py) after catalog load (before the PDF todo). Pass token keys from the production `grab_run` else-branch. Cover the real path in [`tests/test_ui_grab.py`](../../tests/test_ui_grab.py), not only the test hook.

**Success:** Preview of three keys → Grab fetches only those three (or the missing subset among them), not the whole scope.

**Docs:** None beyond existing “Preview / Grab (selected vs all)” once behavior is true.

Do **not** block P0 on renaming Grab → Apply.

---

## P1 — stranger first hour (after P0)

### P1.1 — Empty Wanted coaching

**Problem:** Zotero down / no collection → blank table, red health dot only, Preview/Grab still offered. First hour fails before any miss list ([usability report](https://github.com/glen-w/Paperful)).

**Change:** When Zotero down or no collection, show an amber next-step line (reuse [`doctor_steps.py`](../../paperful/ui/doctor_steps.py) copy) and readable health text linking to System. Soften or disable Grab until there is a scope with rows.

**Success:** Stranger sees what to do next, not a silent empty desk.

**Docs:** Short first-time note in [`docs/gui.md`](../gui.md) (start Zotero local API, pick collection, Preview).

### P1.2 — Wanted first in nav

**Problem:** Discover is leftmost even though `/` redirects to Wanted ([`base.html`](../../paperful/ui/templates/base.html)).

**Change:** Put Wanted first on the default nav. Keep Discover on the default bar for now.

**Success:** Tab order matches the door (Wanted).

**Docs:** Update nav order table in [`docs/gui.md`](../gui.md) if it still lists Discover first.

---

## Packaging PASS (no work)

- CLI / Compose GUI publish `127.0.0.1:8765` ([`compose.gui.yaml`](../../compose.gui.yaml))
- Found rows: source + `doi_match` / `doi_mismatch` / `unverified` ([`verify.py`](../../paperful/ui/verify.py))
- Ask off default nav (Advanced → Index); `/v1/ask` JSON left as-is for Miss desk 1.0
- Summary counts, not `% complete`

---

## Defer (not Miss desk 1.0 gates)

| Item | Why deferred |
| --- | --- |
| Discover → Advanced, empty Discover queue, Discover form chrome | Product/📣; landing is already Wanted |
| Card catalogue / OG / paperful.app paste | Post-honesty; no Wanted crop as apex OG until cards |
| Preview vs Grab visual weight | Review token already gates Grab |
| Grab → Apply rename | Copy polish once Attach is real |
| Full Workbench depth / Ask ship-or-hide | Post-1.0 / options leftover |
| Version align (`0.8.0` vs `0.9.0`), serve “no library writes” docstring, `docs/gui.md` “full workbench = 1.0” framing | Docs debt; optional ride-along only |

---

## Implementation order

**Phase 1 (bundled P0):**
1. Default `attach_verified` off  
2. Remove Grab auto-attach  
3. `POST /wanted/attach` + always-visible button + Held hand-ticks; remove Settings auto-attach checkbox  
4. `run_fetch(..., item_keys=...)` + wire production Grab; fix tests  

**Phase 2 (P1):**
5. Empty Wanted coaching  
6. Wanted-first nav  

**Then (optional):** docs debt ride-along — version sync, serve docstring, Miss-desk framing in `docs/gui.md`.

---

## Success bar for Miss desk 1.0 (honesty + thin first hour)

1. Fresh session: Grab fetches to `out/` only; no silent Zotero write.  
2. Grab never attaches, regardless of leftover cookies.  
3. Attach is a distinct, always-visible library write for `doi_match` + hand-ticks.  
4. Held mismatch/unverified rows are tickable.  
5. Grab selected respects token keys on the real fetch path.  
6. Empty Wanted coaches Zotero-down / no-collection.  
7. Wanted is first in default nav.  

Tests: extend [`test_ui_grab.py`](../../tests/test_ui_grab.py) for fetch-only Grab, real Attach route, selected-key fetch; keep [`test_ui_rows.py`](../../tests/test_ui_rows.py) green.

---

## Out of scope

Discover share-crop / Card catalogue OG, Repair/Mirror/Ask workbench marketing, print A4 client report, live SEO paste until honesty + populated Wanted proof exist.
