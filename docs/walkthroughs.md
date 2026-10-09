# Walkthroughs

Short, outcome-focused jobs in the **workbench** (`docker compose up`, then
http://127.0.0.1:8765). They complement the command reference; they do not
replace it.

The screenshots are a live `ocean/BBNJ` collection. Follow the same clicks
on any collection chip.

CLI recipes for the same verbs live in [Workflows](workflows.md)
(`paperful all`, named run configs). How a fill searches:
[How it works](how-it-works.md).

## Common workflows

Start here. First-time users should follow **1 → 3** in order.

| # | Walkthrough | Outcome |
| --- | --- | --- |
| 1 | [First fill](first-fill.md) | On **Wanted**: preview missing PDFs, grab copies onto `out/`, attach the ones you trust |
| 2 | [Grow the library](grow-library.md) | Search a topic or follow people, review, add metadata parents |
| 3 | [Tidy a collection](tidy-library.md) | Lint, fix identifiers, review duplicates — before or after a fill |

Walkthroughs 1–3 do **not** need a local model. Index Ask and Briefs do
([Ask your library](rag.md), [LLM](llm.md)).

## More playbooks

| Playbook | Outcome |
| --- | --- |
| [Research pack](research-pack.md) | Cited-in-PDF works → parents → PDFs |
| [Author watch](authorwatch.md) | Named people → their new papers |
| [Snowball](snowball.md) | Keyword / DOI / ORCID crawl (CLI depth) |
| [Ask your library](rag.md) | Cited answers from PDFs already on disk |

## Prerequisites

- Docker Compose, then `docker compose up` ([Docker](docker.md)).
- Zotero **on the host** with the local API enabled ([Zotero](zotero.md)).
- A real `email` in `config.toml` (Unpaywall). `doctor` on **System** shows
  the next step for each amber/red row.
