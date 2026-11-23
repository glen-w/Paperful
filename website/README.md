# Paperful website

Modest public landing (plain HTML/CSS, minimal JS for mobile nav). Product
front door: hero → application screenshots → what it does (tool tables) → on your
machine → from a collection to PDFs you trust → install. Keep the marketing
voice here; operator depth lives in `./guide/` (catalog: `./guide/what-it-does.html`).

- Open `index.html` locally, or deploy via GitHub Pages (`.github/workflows/pages.yml`).
- Logos live in [images/](images/) (copied from `docs/`): `logo.png` (ink wordmark for light backgrounds) and `logo-dark.png` (cream wordmark for dark backgrounds). The README picks via `prefers-color-scheme`.
- Footer version should match [pyproject.toml](../pyproject.toml) `version` (currently **1.9.8**).
- Stability story is [docs/releases.md](../docs/releases.md).
- Install snippet matches the sibling-mount path in `docs/docker.md` and
  `.env.example` defaults (`../paperful-data` + `../paperful-out`):
  `docker compose build`, then `doctor`, then `docker compose up` (workbench at
  http://127.0.0.1:8765). README keeps the optional repo-local
  `PAPERFUL_DATA=.` variant. CLI one-shots stay `docker compose run --rm paperful …`.
  Build the image on your computer with `docker compose build`. `.env.example` sets
  `PAPERFUL_IMAGE_MODE=heavy`; CI builds **light**. `uv` is the contributor path.
  Guide: `./guide/docker.html` (light vs heavy packs).
- Docs CTAs point at the **Sphinx HTML guide** published beside this landing (`./guide/`), rebuilt from `docs/` on every qualifying `main` push. The tool catalog is `./guide/what-it-does.html` (same tables as the landing **What it does** section). Walkthroughs start at `./guide/walkthroughs.html`; the fill pipeline is `./guide/how-it-works.html`; Ask / CLI claim-check is `./guide/rag.html`; sourced evidence table is `./guide/evidence.html`; Advanced peer-review is `./guide/peer-review.html`.
- Workbench screenshots live in `images/workbench-*.png` (copied from `docs/_static/workflows/` by `scripts/docs/capture_workbench.py`). Workflow GIFs stay under `docs/_static/workflows/*.gif` (`scripts/docs/record_workflows.py`); the landing page does not embed them.
- The sticky header nav is shared with `/guide/` via `website/chrome/` (Sphinx injects the same chrome).
- Cleaning Service offer: `cleaning-service.html` (nav item on landing + guide). `paperful.cloud` should redirect there once DNS/SSL is sorted.
- Full local preview (landing + guide): `uv sync --extra docs && make pages-site` then open `_site/index.html`.
- Ko-fi support link in footer: https://ko-fi.com/C0C1XK8G
