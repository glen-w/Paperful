<h1 align="center">
  <img src="docs/logo.png" alt="paperful" width="280">
</h1>

<p align="center">
  <strong>Keep the library. Keep the files. Keep control.</strong><br>
  A local sidecar for your research library: collections organised, missing
  PDFs filled, metadata linted, a quiet copy on disk. Zotero is the
  well-tested catalogue. Mendeley and EndNote adapters are in the tree and
  seeking testers. Work stays on this machine.
</p>

Open access first (Unpaywall, OpenAlex, arXiv, bioRxiv/medRxiv, Europe PMC,
Semantic Scholar, CORE, optional Google Scholar, the item's own URL). Campus
**EZProxy** when you have a subscription. **Sci-Hub is opt-in and off by
default** — it occupies a legal grey zone in some jurisdictions; see
[Sci-Hub](docs/scihub.md).

By default each item only hits sources that match its metadata (DOI, arXiv
id, URL, …); `--try-all` disables that. Sci-Hub coverage after ~2021 is thin —
paperful skips Sci-Hub for items dated after 2021 (and drops it from the run
when `--year-from` is past that year). Recent paywalled papers are best fetched
via EZProxy when your library has a subscription.

Work happens **on disk** (`out/`, `state/`). Zotero is the well-tested
catalogue: read items in, write PDFs and metadata patches back. `snapshot`
writes a restore folder for every scoped item; `restore --apply` recreates
only what is missing. Mendeley (REST) and EndNote (read the local library;
writes are an import bundle, not an edit of the `.enl` file) are seeking
testers — do not treat them as proven. Why this shape:
[Why paperful](docs/why.md). Not sure if this is the right tool?
[How paperful compares](docs/comparison.md).

Hosted site (GitHub Pages): landing in [`website/`](website/) plus Sphinx HTML
from this `docs/` tree at `/guide/`. Preview locally with
`uv sync --extra docs && make pages-site`, then open `_site/index.html`.
Live: [glenwright.earth/Paperful](https://glenwright.earth/Paperful/).

## Quick start

paperful is a host-local CLI. Zotero (and headed browser login) stay on this
machine; work lands on disk (`out/`, `state/`).

**You need**

- Python 3.10+ and [uv](https://docs.astral.sh/uv/).
- Zotero running, with the local API enabled:
  Settings → Advanced → *Allow other applications on this computer to communicate with Zotero*.
- Zotero 10+ to attach PDFs into the library. On Zotero 7–9 the tool still
  downloads to disk; attach later with `paperful attach` once upgraded.
  Host header, write keys, and ghost attachments: [Zotero](docs/zotero.md).
- Optional (seeking testers): Mendeley via REST — register an app, then
  `paperful session login mendeley`. [Mendeley](docs/mendeley.md).
- Optional (seeking testers): EndNote desktop — set `[endnote].library` to
  the `.enl`. Writes are an import bundle, not an edit of the database.
  [EndNote](docs/endnote.md).
- Optional: a university/library account and EZProxy URL for publisher PDFs.
- Optional: a browser session for Google Scholar
  (`paperful session login scholar`) if you keep `scholar` enabled.
- Optional: [Ollama](https://ollama.com) with a pulled model if you turn on
  the LLM verbs (`[llm].enabled`); `recover` additionally needs Python 3.11+
  and `uv sync --extra browser-agent`. See [LLM](docs/llm.md).

```sh
git clone https://github.com/glen-w/Paperful.git
cd Paperful
uv sync
cp config.example.toml config.toml   # set email, optional ezproxy_base
mkdir -p packs out state
uv run paperful doctor
uv run paperful collections
```

Then pick a collection and go:

```sh
uv run paperful run --collection interesting --dry-run
uv run paperful run --collection interesting

# optional: narrow by year and/or Zotero item type
uv run paperful run -C BBNJ --year-from 2023 --year-to 2026 -T journalArticle

# same slice as one command (gaps → run → lint → fix-metadata → summarize)
uv run paperful all -C BBNJ --year-from 2021 --year-to 2026 -T journalArticle
uv run paperful all --profile bbnj-journal
```

Flags `--year-from` / `--year-to` and `--type` / `-T` also work on `lint`,
`fix-metadata`, `dedupe`, `gaps`, `summarize`, `synthesize`, `snapshot`, and
`restore`. Save them with `paperful profile save`. See
[Commands](docs/commands.md) and [Workflows](docs/workflows.md).

Optional: [Poppler](https://poppler.freedesktop.org/) `pdftotext` on `PATH`
for PDF-text DOI extraction (`pypdf` is the fallback; `doctor` ambers if
Poppler is missing). Playwright ships with a normal `uv sync`; Chromium is
installed automatically on the first `paperful session login …`.

If you use campus EZProxy, finish [Campus EZProxy](docs/ezproxy.md) before a
big run. If you keep `scholar` in `sources`, log in once with
`paperful session login scholar` — see [Browser sessions](docs/sessions.md).

### Docker (optional)

The image packs Python, Poppler, and Chromium so you can skip installing those
on the host. It does **not** replace Zotero or headed `session login` — those
stay on the host, sharing `out/` and `state/` via `PAPERFUL_DATA`.

```sh
cp .env.example .env   # PAPERFUL_DATA=. to keep repo-local data
docker compose build
docker compose run --rm paperful doctor   # default if you omit the command
docker compose run --rm paperful collections
docker compose run --rm paperful run --collection interesting --dry-run
```

Layout, Zotero networking, and the host/container split: [Docker](docs/docker.md).

Reference (same corpus as the hosted guide):

- [Commands and output](docs/commands.md)
- [Duplicate packs](docs/dedupe.md)
- [Configuration](docs/config.md)
- [Source routing](docs/sources.md)
- [Architecture](docs/architecture.md)
- [Quiet mirror](docs/quiet-mirror.md) — `out/` as a browsable collection tree
- [Docker](docs/docker.md) — optional image, not a complete install

Optional local LLM (Ollama by default; off until `[llm].enabled`): grounded
title proposals in `fix-metadata`, a `pdf_identity_mismatch` lint check,
`summarize` (HTML under `state/summaries/` and a tagged Zotero child note;
`--to disk` skips the note), `synthesize` (a literature review of those
notes), and `recover`: last `run` lane after Scholar / EZProxy / htmlpdf
fail, or `paperful recover --item` for named keys. Setup, model guidance,
privacy notes, and troubleshooting:
[LLM](docs/llm.md); key table:
[Configuration](docs/config.md#llm-optional-local-first).

```sh
ollama pull qwen2.5:7b                       # then set [llm] enabled = true in config.toml
uv run paperful doctor                       # LLM row must be green
uv run paperful summarize --item ITEMKEY     # disk HTML + tagged child note
uv run paperful synthesize -C COLLECTION     # report from those notes
```

## Develop

```sh
uv sync --group dev
uv run pytest
```

See [CONTRIBUTING](CONTRIBUTING.md).

## License

[MIT](LICENSE)

---

<p align="center">
  <a href="https://ko-fi.com/C0C1XK8G" target="_blank" rel="noopener noreferrer"><img height="36" style="border:0;height:36px" src="https://storage.ko-fi.com/cdn/kofi6.png?v=6" alt="Buy Me a Coffee at ko-fi.com" /></a>
</p>
