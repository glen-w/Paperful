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
subscription. Grey-lit packs (UNGA/undocs · BBNJ/DOALOS · ISA) cover DOI-less
institutional PDFs via `direct`/`landing` — see [architecture](docs/architecture.md#grey-literature).

Work happens **on disk** (`out/`, `state/`). Zotero is a library adapter.
**0.x** flags and report JSON may still move; **1.0** locks
`paperful.run_report.v1` and attach behaviour ([releases](docs/releases.md),
[changelog](CHANGELOG.md)).

Not sure if this is the right tool? [How paperful compares](docs/comparison.md)
(that page owns the routing table — this README does not).

Site: [glenwright.earth/Paperful](https://glenwright.earth/Paperful/)
(`website/` + Sphinx `/guide/`; `uv sync --extra docs && make pages-site`).

## Quick start

**You need**

- Zotero running, with the local API enabled:
  Settings → Advanced → *Allow other applications on this computer to communicate with Zotero*.
- Zotero 10+ to attach PDFs into the library. On Zotero 7–9 the tool still
  downloads to disk; attach later with `paperful attach` once upgraded.
- [`uv`](https://docs.astral.sh/uv/) (Python 3.10+).
- Optional: a university/library account and EZProxy URL for publisher PDFs
  (ScienceDirect, Springer, Wiley, Taylor & Francis, …).
- Optional: a browser session for Google Scholar (`paperful scholar`) if you
  keep `scholar` enabled.
- Optional: [Poppler](https://poppler.freedesktop.org/) `pdftotext` on `PATH`
  for PDF-text DOI extraction (`pypdf` is the fallback; `doctor` ambers if
  Poppler is missing).

```sh
git clone https://github.com/glen-w/Paperful.git
cd Paperful
uv sync
cp config.example.toml config.toml   # then set email, out_dir, optional ezproxy_base
uv run paperful doctor               # Zotero, paths, cookies — green / amber / red
uv run paperful collections          # sanity check: tree with "No PDF" counts
```

Then pick a collection and go:

```sh
uv run paperful run --collection interesting --dry-run   # see what would be fetched
uv run paperful run --collection interesting                   # fetch + attach
```

If you use campus EZProxy, finish [Campus EZProxy](docs/ezproxy.md) before a
big run. If you keep `scholar` in `sources`, log in once with
`paperful session login scholar` — see [Browser sessions](docs/sessions.md).

Reference:

- [Commands](docs/commands.md) · [config](docs/config.md) · [sources](docs/sources.md)
- [EZProxy](docs/ezproxy.md) · [sessions](docs/sessions.md) · [architecture](docs/architecture.md)

## Tests

```sh
uv run pytest
```

## License

[MIT](LICENSE)

---

<p align="center">
  <a href="https://ko-fi.com/C0C1XK8G" target="_blank" rel="noopener noreferrer"><img height="36" style="border:0;height:36px" src="https://storage.ko-fi.com/cdn/kofi6.png?v=6" alt="Buy Me a Coffee at ko-fi.com" /></a>
</p>
