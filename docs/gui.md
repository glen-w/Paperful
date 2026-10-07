# Paperful workbench

**Status: 1.0 target.** Paperful stays a **local CLI** with a quiet disk mirror.
**1.0** adds a **server-rendered workbench** on `paperful serve` that grows the
library and fills PDFs without a second fetch stack. Zotero remains the
catalogue and reader. **Interactive Ask** is on **Index** (opt-in `[rag]` +
`[llm]`), not the home page. A **Firefox extension** and
hosted SaaS are **post-1.0** — see [ROADMAP — Product split](ROADMAP.md#product-split-10-vs-post-10).

---

## Product framing

Two jobs sit on the default nav:

| Nav | CLI verbs | Job |
| --- | --- | --- |
| **Wanted** | `gaps`, `run`, `attach` | See missing PDFs, preview fetch, grab to `out/`, attach chosen copies |
| **Discover** | `snowball`, `authorwatch`, watches | Find new works (topic or person), review, add metadata parents |

**Library**, **Activity**, and **System** support the loop. **Repair**, **Mirror**,
**Index**, **Briefs**, and **Settings** appear only when **Advanced** is on
(reveal only; does not enable Scholar, Sci-Hub, or LLM).

```text
  Browser  ──HTTP──►  paperful serve  ──►  paperful.* (same as CLI)
                              │
                              ├── LibraryBackend (Zotero / …)
                              └── Ledger: out/ + state/
  CLI / MCP  ─────────────────┘
```

Control rules match the CLI: dry-run before bulk fetch, **Preview → Grab** with a
**review token** (refuse if the library changed), opt-in Scholar / Sci-Hub / LLM /
browser-agent. No built-in scheduler — **Check again** on Discover, not cron.

---

## Shell chrome

| Control | Role |
| --- | --- |
| **Collection** chip | Scoped collection (remembered in a cookie) |
| **Preset** chip | Open access (`oa`) or Campus (`eoi`) — the simple source choice |
| **Health** dot | Worst `doctor` status |
| **Advanced** toggle | Cookie only; reveals extra nav and form fields |

Layout: table-first rows, native `<dialog>` drawer (no embedded PDF viewer).
Long jobs return a **command id**; Activity polls `GET /v1/runs/{id}` (SSE later).
Bind `127.0.0.1`. Compose `gui` profile publishes `127.0.0.1:8765:8765` only.

---

## Simple loop

1. **Discover** — **Topic:** keyword search (`snowball search` dry-run queue),
   per-row Keep/Skip, then **Preview apply** → **Add selected**
   (`snowball apply`, metadata only). **Fill PDFs** opens Wanted.
   **Briefing** / **Digest** write `briefing.md` / `digest.md` on the queue
   (shown on the page; digests are not auto-created). Advanced can tick
   **File collection note** (`--apply` + collection chip) to file a Zotero
   collection note tagged `paperful:frontier-briefing`. **Keep an eye on this**
   saves a topic watch only when a snowball **profile** is chosen. **People:**
   create a list, Follow (ORCID + optional backfill), add/remove, resolve, run,
   import CSV/JSON/ORCID, people briefing; inbox uses the same Preview → apply
   pattern (`authorwatch apply`). **Check again** re-runs a saved topic watch or
   person list. Advanced topic watches also offer **Watch briefing** /
   **Watch digest** (same optional collection note).
2. **Wanted** — Miss rows use `MISS_SURFACE_PLAIN` only. **Held** tab: on-disk
   PDFs with `doi_match` / `doi_mismatch` / `unverified` / `snapshot` (not
   “% complete”). **Preview** → **Grab** (fetch to `out/` only; selected vs all)
   → **Attach** (explicit Zotero write for `doi_match` plus hand-ticks). Grab
   never writes the library.
3. **Library** — Collection list with have / held / missing counts; pick scope.
4. **Activity** — Command history + trust line from `last-run.json`.
5. **System** — `doctor` rows with one next step each.

---

## Advanced surfaces

Same shell; extra verbs call the same domain entrypoints as the CLI. Discover
adds snowball kinds (hybrid/doi/orcid/collection), crawl knobs (including
**Twenty writeback** → `cfg.twenty_writeback_listings`), profile save/run,
resume, briefing, frontier digest, **refs gap**, **ingest-dois**
(Preview → Apply token), **authors**, and **packs promote**.
Wanted adds attach (mismatch/short), `recover`, handoff, inbox drain, `reachout`,
plus Grab filters (`year` / type / retry / try-all / browser-agent / upgrade).
**Repair** Preview runs dry-run then Apply writes: `lint` (read-only report),
`fix-metadata`, `dedupe`, `versions`, `attachments`, `ocr`.
**Mirror** Preview/Apply: `sync`, `snapshot`, `restore`, `cache clean`.
**Index**: `rag ingest` / `search` when `[rag]` is on; cited Ask and batch Ask
(`state/ask-batch/`) when `[rag]` and `[llm]` are on and the index has rows.
Collection chip is the scope. **Synthesize** on Index when `[llm]` is on.
**Briefs**: collection **summarize** / **synthesize** when `[llm]` is on.
Per-item **summarize** in Wanted/Library drawers (Advanced). **Settings** writes
`config.toml`; it does not enable `[rag]` or `[llm]`.

**Stays CLI** (no GUI control): `session login`, `doctor --guide`, mid-run
EZProxy re-login, snowball `approve-each`, `collections add`, Sci-Hub source
toggles. `paperful all` / named run configs stay [workflows](workflows.md).

---

## HTTP capability API (P0 + GUI)

JSON capability routes live on `paperful serve` (`serve.py`). HTML + form POSTs
are mounted by `paperful.ui` (`mount_ui`).

| Method | Path | Behaviour |
| --- | --- | --- |
| GET | `/health` | `{ok, version}` |
| GET | `/v1/doctor` | Same as `doctor --json` |
| GET | `/v1/collections` | Collection tree |
| GET | `/v1/runs/last` | `state/last-run.json` |
| GET | `/v1/runs/{id}` | GUI command record under `state/gui/commands/` |
| POST | `/v1/refs-gap` | Dry-run `refs gap` envelope |
| POST | `/v1/ask` | Same as MCP `ask` (not linked from simple HTML) |
| POST | `/v1/gui/noop` | Smoke / readiness for the GUI process |
| POST | `/wanted/preview` | Review token for Grab (Advanced: year/type/retry/… flags) |
| POST | `/wanted/grab` | Consume token; fetch to `out/` only (`item_keys` from preview) |
| POST | `/wanted/attach/preview` | Review token for held PDF attach |
| POST | `/wanted/attach` | Consume token; attach pending `out/` PDFs |
| POST | `/wanted/recover/preview` | Review token for browser-agent recover |
| POST | `/wanted/recover` | Consume token; `recover` |
| POST | `/wanted/handoff` | `list` / `tabs` / `walk` / `watch` (never fetches) |
| POST | `/wanted/inbox/drain` | One-shot inbox drain |
| POST | `/wanted/reachout` | Export contact rows; optional RG tabs |
| POST | `/wanted/summarize` | Enqueue single-item `summarize`; redirect `?run=` |
| GET | `/item/{key}/summary` | Per-item HTML under `state/summaries/` |
| POST | `/discover/topic` | Enqueue snowball kind (Advanced) or keyword search |
| POST | `/discover/profile-save` | Save snowball profile from the topic form |
| POST | `/discover/refs-gap` | Dry-run refs gap pack for the collection chip |
| POST | `/discover/ingest-preview` | Classify DOIs / refs-gap pack; review token |
| POST | `/discover/ingest-apply` | Consume token; create parents |
| POST | `/discover/authors` | Authors frequency (optional `--apply` pack seed) |
| POST | `/discover/packs-promote` | Promote a proposed field author pack |
| POST | `/discover/follow` | Follow ORCID into a list (`authorwatch` run) |
| POST | `/discover/keep` | Mark queue DOI keep/skip |
| POST | `/discover/check-again` | Re-run topic watch or person list |
| POST | `/discover/resume` | Enqueue `snowball resume` |
| POST | `/discover/profile-run` | Enqueue snowball from a named profile |
| POST | `/discover/briefing` | Write queue `briefing.md`; optional collection note |
| POST | `/discover/digest` | Write queue `digest.md`; optional collection note |
| POST | `/discover/watch-briefing` | Watch inbox briefing; optional collection note |
| POST | `/discover/watch-digest` | Watch digest; optional collection note |
| POST | `/discover/watch` | `save_watch` (profile required) |
| POST | `/discover/apply-preview` | Review token for snowball/authorwatch apply |
| POST | `/discover/apply` | Consume token; `snowball apply` / `authorwatch apply` |
| POST | `/discover/aw/save` | Create authorwatch list |
| POST | `/discover/aw/add` | Add ORCID (optional display name / affiliation) |
| POST | `/discover/aw/remove` | Remove person from list |
| POST | `/discover/aw/resolve` | Enqueue `authorwatch resolve` |
| POST | `/discover/aw/run` | Enqueue `authorwatch run` (optional backfill / caps) |
| POST | `/discover/aw/import` | CSV/JSON/ORCID upload → list (`resolve` off); files under `state/gui/uploads/` |
| POST | `/discover/aw/briefing` | Write list `briefing.md` |
| POST | `/prefs/advanced` | Toggle Advanced cookie |
| POST | `/prefs/collection` | Remember collection chip cookie |
| POST | `/settings` | Write allowed `config.toml` fields |
| POST | `/repair/preview` | Dry-run repair verb + review token |
| POST | `/repair/apply` | Consume token; apply repair verb |
| POST | `/mirror/preview` | Dry-run mirror verb + review token |
| POST | `/mirror/apply` | Consume token; apply mirror verb |
| POST | `/index/ask` | Enqueue cited Ask turn; redirect to `/index?thread=&run=` |
| POST | `/index/ingest` | Enqueue `rag ingest` (Preview dry-run or Build); redirect `?run=` |
| POST | `/index/search` | Redirect to `/index?q=` (sync search on GET) |
| POST | `/index/ask-batch` | Enqueue `ask --from-file` batch; redirect `?run=` |
| GET | `/index/batch/{stamp}` | `answers.md` under `state/ask-batch/<stamp>/` |
| POST | `/index/synthesize` | Enqueue `synthesize` (dry-run or write); redirect `?run=` |
| GET | `/index/report/{slug}` | HTML under `state/reports/` |
| POST | `/briefs/summarize` | Enqueue `summarize`; redirect `/briefs?run=` |
| POST | `/briefs/synthesize` | Enqueue `synthesize` (dry-run or write); redirect `?run=` |
| GET | `/briefs/summary/{key}` | HTML under `state/summaries/` |
| GET | `/briefs/report/{slug}` | HTML under `state/reports/` |

HTML routes: `/discover`, `/wanted`, `/library`, `/activity`, `/system`, plus
advanced `/repair`, `/mirror`, `/index`, `/briefs`, `/settings`. `GET /` → `/wanted`.
`/repair/preview` and `/mirror/preview` enqueue work and redirect with `?run=`; Apply
posts `review_token` from that command record (stale previews return HTTP 409).
`POST /index/ask` enqueues a cited Ask turn (not linked from the simple shell).

Writes over HTTP use review tokens under `state/gui/reviews/`; stale library
fingerprints return **409**. Discover **Add selected** / inbox apply, ingest-dois
Apply, and Wanted **Grab** / attach / recover require **Preview** first (tokens
may bake Grab flags). **Grab** fetches to `out/` only; **Attach** is a separate
labelled library write. Repair / Mirror **Apply** require **Preview** first.
**Keep an eye on this** needs an existing snowball profile (`save_watch`); it
does not write an empty `watch.json`. Long jobs land under `state/gui/commands/`;
Activity polls `GET /v1/runs/{id}`.

---

## Non-goals

- Second Zotero (reader, annotations, collection drag-and-drop)
- Systematic-review screening as the primary UX
- Chat-over-library as the default landing
- Sci-Hub on simple pages or in Preview
- Replacing Zotero sync or WebDAV

---

## Related docs

- [ROADMAP — GUI](ROADMAP.md#gui)
- [architecture.md](architecture.md)
- [why.md](why.md)
- [commands.md](commands.md)
- [docker.md](docker.md) — Compose `gui` profile; **heavy** image for Index Ask / RAG extras
