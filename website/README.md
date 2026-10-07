# Paperful website

Modest public landing (plain HTML/CSS, minimal JS for mobile nav). Product
front door: hero (library, find, mirror) → how it works (fill pipeline) →
what it does (downloads, notes, summaries, folder copy) → on your machine →
install.

- Open `index.html` locally, or deploy via GitHub Pages (`.github/workflows/pages.yml`).
- Logos live in [images/](images/) (copied from `docs/`): `logo.png` (ink wordmark for light backgrounds) and `logo-dark.png` (cream wordmark for dark backgrounds). The README picks via `prefers-color-scheme`.
- Footer version should match [pyproject.toml](../pyproject.toml) `version` (currently **0.9.0**).
- **0.x** is called out in the footer; stability story is [docs/releases.md](../docs/releases.md).
- Install snippet matches README: `docker compose build`, then `doctor`, then a dry-run.
  The image is build-local only (no `docker pull`, no PyPI). `.env.example` sets
  `PAPERFUL_IMAGE_MODE=heavy`; CI builds **light**. `uv` is the contributor path.
  Guide: `./guide/docker.html` (light vs heavy packs).
- Docs CTAs point at the **Sphinx HTML guide** published beside this landing (`./guide/`), rebuilt from `docs/` on every qualifying `main` push. The walkthrough is `./guide/how-it-works.html`.
- The sticky header nav is shared with `/guide/` via `website/chrome/` (Sphinx injects the same chrome).
- Cleaning Service offer: `cleaning-service.html` (nav item on landing + guide). `paperful.cloud` should redirect there once DNS/SSL is sorted.
- Full local preview (landing + guide): `uv sync --extra docs && make pages-site` then open `_site/index.html`.
- Ko-fi support link in footer: https://ko-fi.com/C0C1XK8G
