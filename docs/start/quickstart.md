# Quick start

Get a green `doctor` on this machine, then pick a [path to results](../index.md).

**Operators use Docker Compose.** There is no published image and no PyPI
package: do not `docker pull` or `pip install paperful`. Contributors use
`uv` — see [Contributing](../../CONTRIBUTING.md).

## You need

- [Docker](https://docs.docker.com/get-docker/) with Compose v2
- [Zotero](https://www.zotero.org/) running, with the local API enabled:
  Settings → Advanced → *Allow other applications on this computer to
  communicate with Zotero*
- Zotero **10+** to attach PDFs into the library (on 7–9, downloads still
  land under `out/`; attach later with `paperful attach`)

Host header, write keys, and ghost attachments: [Zotero](../howto/zotero.md).
Layout and host/container split: [Docker](../howto/docker.md).

## Install

```sh
git clone https://github.com/glen-w/Paperful.git
cd Paperful
cp .env.example .env          # PAPERFUL_DATA=. keeps data in this checkout
cp config.example.toml config.toml
# set email = "you@example.com" in config.toml (Unpaywall)
docker compose build
docker compose run --rm paperful doctor
docker compose run --rm paperful collections
```

`doctor` should be green (or amber only for optional sessions you have not
logged in yet). Work lands on disk under `out/` and `state/`.

## Pick a path

| Path | Goal |
| --- | --- |
| [Fill missing PDFs](../paths/fill-pdfs.md) | Download and attach PDFs for a Zotero collection |
| [Quiet mirror](../paths/quiet-mirror.md) | Snapshot a browsable folder tree; restore missing items later |
| [Snowball discovery](../paths/snowball.md) | Grow a collection from a keyword, DOI, ORCID, or seed set |

## Not in this first hour

Defer until after a path succeeds: `paperful all`, profiles, local LLM,
Sci-Hub, Google Scholar, Mendeley, and EndNote. Those are documented under
[How-to](../index.md).

**0.x** flags may still move — see [Releases](releases.md).
