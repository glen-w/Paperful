# Quiet mirror (`out/`)

**Direction (2026-09-20):** treat paperful’s collection-mirrored tree under
`out/` as an intentional **quiet browsable PDF mirror** — useful to humans and
agents — while Zotero stays the bibliographic catalogue and attach target.

This is a product *stance*, not a new daemon. paperful remains a **local CLI**.
House sync of `out/` (and careful use of `state/`) lives outside this repo
(e.g. Syncthing on a homeserver). See the Toast Heaven ops plan
`docs/operations/syncthing-personal-and-research.md` in the `server` repo when
that tree is nearby.

## Roles

| Layer | Role |
| --- | --- |
| **Zotero** | Catalogue, collections, citations, annotations; `storage/` holds `imported_file` attachments after attach; phone/WebDAV sync is Zotero’s job |
| **`out/<collection>/…pdf`** | Quiet mirror + gap-fill workspace; collection-shaped folders; resumable via `state/manifest.jsonl` |
| **`state/`** | Ledger, patches, sessions, local API key — operator machine; sync only with care (keys, cookies) |

**Dual store for now.** Attach stays **`imported_file`**: bytes land under `out/`,
then upload into Zotero `storage/`. Duplicate bytes are acceptable. Do **not**
treat linked-file cutover (warehouse-as-only-bytes) as a 0.x goal.

```text
Zotero library  →  paperful run  →  out/<collection>/…pdf  →  attach (imported_file)
                      ↑
              OA / EZProxy / … / opt-in Sci-Hub
```

## What “quiet” means

- No second reading UI and no replacement for Zotero desktop.
- No long-running sync service inside paperful.
- Folder tree is for browse, scripts, and RAG-adjacent tooling that want paths —
  not for inventing a parallel library database.

## Non-goals (near term)

- Not a second Zotero
- Not linked-file migration in 0.x
- Not a hosted multi-user warehouse
- Not auto Sci-Hub or silent cloud defaults

## Related

- [architecture.md](architecture.md) — disk-first adapters and data flow
- [zotero.md](zotero.md) — attachment modes (`imported_file` vs linked)
- [ROADMAP.md](ROADMAP.md) — file OS / collaboration as maybe-later; this page is
  the near-term direction for the disk mirror
- [commands.md](commands.md) — `out/` path layout
