# What it does

Every fetch lands in a folder on this computer first: open-access copies when
they exist, campus login when you have it, then you attach the files you
trust. Zotero stays the catalogue. Optional notes and answers use a model
only when you turn one on, and they point back at the PDFs you already hold.

Wanted, Discover, Library, Activity, and System are on the default nav;
⚙️ marks Advanced; 🤖 marks optional AI (off until you enable it — local
[Ollama](https://ollama.com) when the machine can run it, or hosted APIs via
[LiteLLM](llm.md#litellm-paid--openai-compatible-apis)).

New here: [first 10 minutes](first-10-minutes.md). Click-through jobs:
[Walkthroughs](walkthroughs.md). How a fill searches:
[How it works](how-it-works.md).

## Fill missing PDFs

| Tool | What it does | Guide |
| --- | --- | --- |
| [Wanted](first-fill.md) | See which items still need a PDF, Preview what a search would find, Grab copies into `out/`, Attach the ones you trust (Zotero 10 or newer; on 7–9 the files stay in the folder) | [guide](first-fill.md) |
| [Library](gui.md) | Collection tree with item and missing-PDF counts; the target icon sets the scope for the rest of the workbench | [guide](gui.md) |
| [Sources](how-it-works.md) | Free copies first (Unpaywall, OpenAlex, and the rest of the open-access lane), campus EZProxy when you choose Campus, playbooks for odd landings | [guide](sources.md) |
| [Firefox add-on](firefox.md) | Save the page you are reading, or several tabs, into the folder copy. The Zotero Connector stays the way to save into Zotero. This one does not attach | [guide](firefox.md) |
| [Recover](browser-agent-models.md) ⚙️🤖 | Optional browser agent for landings the scripted sources missed (`paperful[browser-agent]`, Python 3.11+) | [guide](browser-agent-models.md) |

## Grow the library

| Tool | What it does | Guide |
| --- | --- | --- |
| [Discover](grow-library.md) | Topic search, citation map, Keep/Skip queue, then metadata parents — PDFs still go through Wanted | [guide](snowball.md) |
| [People](authorwatch.md) | Follow ORCID / OpenAlex authors; run the list; accept new works into the collection | [guide](authorwatch.md) |
| [Web](search.md) | Grey-literature hits via SearXNG; Preview apply creates parents | [guide](search.md) |
| [Research pack](research-pack.md) | Works cited in a PDF you already hold → parents in the collection → fill PDFs | [guide](research-pack.md) |
| [Keepup](keepup.md) | Poll topic watches, people lists, and what-cites on a cadence you cron; no email | [guide](keepup.md) |

## Tidy the library

| Tool | What it does | Guide |
| --- | --- | --- |
| [Repair](tidy-library.md) ⚙️ | Check identifiers, fix metadata, review duplicates, repair attachments, OCR scans, flag retractions / PubPeer / tortured phrases | [guide](tidy-library.md) |
| [Mirror](quiet-mirror.md) ⚙️ | Folder copy of the collection (`out/` + `state/`); snapshot, restore, sync. You copy the folder when you want a backup or a handoff | [guide](quiet-mirror.md) |
| [Import / export](commands.md) | RIS, BibTeX, and EndNote XML | [guide](commands.md) |

## Read papers you already have

| Tool | What it does | Guide |
| --- | --- | --- |
| [Ask](rag.md) 🤖 | Questions over PDFs already on disk, answered with a link to the passage; simple or advanced | [guide](rag.md) |
| [Briefs](ai.md) ⚙️🤖 | Per-item summary and a collection review from the mirror. CLI `summarize --receipts` drops sentences that cannot quote the PDF | [guide](llm.md) |
| [Index](rag.md) ⚙️ | Ingest the mirror, search passages, extract questions, see what is already answered, pull IMRaD-style sections | [guide](rag.md) |
| [Claim check](rag.md#claim-check) | Per-sentence support vs the index (CLI `ask --claim-check`; no chat model) | [guide](rag.md#claim-check) |
| [Evidence](evidence.md) | Sourced n / method / finding table over PDFs you hold; each cell is a quote or `check this`. No chat model. CLI only | [guide](evidence.md) |

## Check a draft

| Tool | What it does | Guide |
| --- | --- | --- |
| [Peer review](peer-review.md) ⚙️ | A draft you already wrote: structure and citations always; optional claim locators against held PDFs; optional comparison with this library. Not a grade | [guide](peer-review.md) |
| [Suggest edits](rewrite.md) ⚙️ | Apply a peer-review pack as locatable edits / tracked changes; never overwrites the source | [guide](rewrite.md) |
| [Stuff](stuff.md) ⚙️ | Extra library cites per sentence or outline section (needs the index; no chat model) | [guide](stuff.md) |
