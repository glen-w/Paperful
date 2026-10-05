# Paperful terms

Product words for this repo. Cohort spine: pack `_synergies/VOCABULARY.md`.
Do not add `docs/GLOSSARY.md` beside this file. Do not use TranscriptX **admit**.

## Ladder (staging → gate → library of record)

```text
find / download  →  out/ PDF (staging on disk)  →  attach  →  Zotero (library)
gaps / attachments (honesty)  →  run (fill)  →  human reads out/  →  summarize / ask
reachout (contact, no fetch)  →  you email or click ResearchGate Request yourself
```

| Term | Meaning here |
| --- | --- |
| **library** | The reference **manager** catalogue (Zotero is well tested). Not a TranscriptX transcript library. |
| **attach** | Write a PDF into Zotero as a stored child. The write gate. |
| **admit** | **Do not use** in Paperful. That verb is TranscriptX (`originals/` → managed transcripts). |
| **mirror** / **`out/`** | Quiet on-disk copy: one folder per item (`record.json`, PDF, notes). Copy it yourself. |
| **`state/`** | Run reports, sessions, write keys. Lives next to `out/` under `PAPERFUL_DATA`. |
| **import** | RIS / BibTeX / EndNote XML into the manager. Not an “import inbox.” |
| **run** | Fill PDFs for items **already** in the library. |
| **reachout** | Contact-only list of missing PDFs (CSV / RG tabs). Never fetches. Never sends mail. |
| **dry-run** | Show what would happen; no durable write to the library of record. |
| **`--apply`** | Explicit second step that mutates the catalogue. |
| **doctor** | Readiness probe (green / amber / red + next steps). |
| **Ask** | Opt-in RAG over papers in `out/`. Distinct from per-paper `--question-id`. |
| **`--link`** | Attachment surgery (stored → linked). Advanced; only with `--apply`. Not the stranger door. |

## Mounts

Host `PAPERFUL_DATA` is mounted at container `/data`. `out/` and `state/` are
directories **inside** that tree (`/data/out`, `/data/state`). Compose does not
mount Zotero Storage as a writable volume.
