# Walkthroughs

Short, outcome-focused jobs in the **workbench** (`docker compose up`, then
http://127.0.0.1:8765). They complement the command reference; they do not
replace it.

The screenshots and short animations are a live `ocean/BBNJ` collection.
Follow the same clicks on any collection chip.

CLI recipes for the same verbs live in [Workflows](workflows.md)
(`paperful all`, named run configs). How a fill searches:
[How it works](how-it-works.md). Which pieces to turn on together:
[Example setups](example-setups.md). Every tool in one table:
[What it does](what-it-does.md).

## Common workflows

Start here. Never opened the workbench? Read
[First 10 minutes](first-10-minutes.md) first. Then follow **1 → 3** in order.

| # | Walkthrough | Outcome |
| --- | --- | --- |
| 1 | [First fill](first-fill.md) | On **Wanted**: preview missing PDFs, grab copies onto `out/`, attach the ones you trust |
| 2 | [Grow the library](grow-library.md) | Search a topic or follow people, review, add metadata parents |
| 3 | [Tidy a collection](tidy-library.md) | Lint, fix identifiers, review duplicates — before or after a fill |

Walkthroughs 1–3 do **not** need a local model. Ask and Briefs do
([Ask your library](rag.md), [LLM](llm.md)).

## More playbooks

| Playbook | Outcome |
| --- | --- |
| [Research pack](research-pack.md) | Cited-in-PDF works → parents → PDFs |
| [Author watch](authorwatch.md) | Named people → their new papers |
| [Snowball](snowball.md) | Keyword / DOI / ORCID crawl (CLI depth) |
| [Firefox add-on](firefox.md) | Optional. Save the open page, or selected tabs, into `out/`. The Zotero Connector stays for saving into Zotero |
| [Ask your library](rag.md) | Cited answers from PDFs already on disk. CLI `ask --claim-check` labels each sentence against the index (no LLM) |
| [Evidence table](evidence.md) | Sourced n / method / finding over held PDFs (CLI; quote or `check this`; no LLM) |
| [Peer review a draft](peer-review.md) | Pre-submission pack: checkers always; optional `--lane claims` locators against held cited PDFs; optional `context` / `context-web`. Not a grade |

## Prerequisites

- Docker Compose, then `docker compose up` ([Docker](docker.md)).
- Zotero **on the host** with the local API enabled ([Zotero](zotero.md)).
- A real `email` in `config.toml` (Unpaywall). `doctor` on **System** shows
  the next step for each amber/red row.
