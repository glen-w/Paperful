<h1 align="center">
  <img src="docs/logo.png" alt="paperful" width="280">
</h1>

<p align="center">
  <strong>Fill the gaps in your Zotero library.</strong><br>
  Fetch the PDFs your items are missing. Keep them in a folder tree that
  mirrors your collections. Attach them back into Zotero.
</p>

Open access first (Unpaywall, OpenAlex, arXiv, bioRxiv/medRxiv, Europe PMC,
Semantic Scholar, CORE, optional Google Scholar, the item's own URL). Campus
**EZProxy** when you have a subscription. **Sci-Hub is opt-in and off by
default** — it occupies a legal grey zone in some jurisdictions; see
[Sci-Hub](docs/scihub.md).

By default each item only hits sources that match its metadata (DOI, arXiv
id, URL, …); `--try-all` disables that. Sci-Hub coverage after ~2021 is thin;
recent paywalled papers are best fetched via EZProxy when your library has a
subscription.

Work happens **on disk** (`out/`, `state/`). Zotero is a library adapter:
read the catalogue in, write PDFs and metadata patches back. Mendeley is
reserved in config for a later adapter. Not sure if this is the right
tool? [How paperful compares](docs/comparison.md).

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
- Optional: a university/library account and EZProxy URL for publisher PDFs.
- Optional: a browser session for Google Scholar
  (`paperful session login scholar`) if you keep `scholar` enabled.

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
```

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
- [Configuration](docs/config.md)
- [Source routing](docs/sources.md)
- [Architecture](docs/architecture.md)
- [Docker](docs/docker.md) — optional image, not a complete install

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
