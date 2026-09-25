<h1 align="center">
  <img src="docs/logo.png" alt="Paperful" width="280">
</h1>

<p align="center">
  <strong>Keep the library. Keep the files. Keep control.</strong><br>
  A local sidecar for your research library: collections organised, missing
  PDFs filled, metadata linted, a quiet copy on disk. Zotero is the
  well-tested catalogue. Mendeley and EndNote adapters are in the tree and
  seeking testers. Work stays on this machine. Fills what open-access indexes,
  campus EZProxy, and grey playbooks can reach — not every paywalled or
  DOI-less item.
</p>

Open access first. Campus **EZProxy** when you have a subscription.
**Google Scholar** and **Sci-Hub** are opt-in and off by default (see
[Sci-Hub](docs/scihub.md)). Why this shape: [Why Paperful](docs/why.md).
Not sure if this is the right tool? [How Paperful compares](docs/comparison.md).

Hosted site: [glenwright.earth/Paperful](https://glenwright.earth/Paperful/)
(landing in [`website/`](website/) + Sphinx guide at `/guide/`). Preview:
`uv sync --extra docs && make pages-site`.

## Quick start

Build the image on this machine. There is no published image and no PyPI
package. Zotero and headed `session login` stay on the host. Work lands under
`out/` and `state/`.

**You need:** [Docker](https://docs.docker.com/get-docker/) with Compose v2,
and Zotero with the local API enabled (Zotero **10+** to attach PDFs). Setup
details: [Quick start](docs/start/quickstart.md), [Zotero](docs/zotero.md),
[Docker](docs/docker.md).

```sh
git clone https://github.com/glen-w/Paperful.git
cd Paperful
cp .env.example .env
cp config.example.toml config.toml   # set email for Unpaywall
docker compose build
docker compose run --rm paperful doctor
docker compose run --rm paperful collections
```

## Paths to results

After a green `doctor`, pick one:

1. **[Fill missing PDFs](docs/paths/fill-pdfs.md)** — `gaps` → `run` → `report` (campus EZProxy as a fork).
2. **[Quiet mirror](docs/paths/quiet-mirror.md)** — `snapshot` / `restore` for a browsable `out/` tree.
3. **[Snowball discovery](docs/paths/snowball.md)** — grow a collection from a keyword, DOI, ORCID, or seed set.

Guide index: [docs/](docs/index.md) (how-to, reference, architecture, contribute).

## Develop

Contributors use [uv](https://docs.astral.sh/uv/) (Python 3.10+). This is not
the operator install.

```sh
uv sync --group dev
cp config.example.toml config.toml
uv run paperful doctor
uv run pytest
```

See [CONTRIBUTING](CONTRIBUTING.md).

## License

[MIT](LICENSE)

---

<p align="center">
  <a href="https://ko-fi.com/C0C1XK8G" target="_blank" rel="noopener noreferrer"><img height="36" style="border:0;height:36px" src="https://storage.ko-fi.com/cdn/kofi6.png?v=6" alt="Buy Me a Coffee at ko-fi.com" /></a>
</p>
