# paperful website

Modest public landing (plain HTML/CSS, minimal JS for mobile nav). Product
front door: hero → what the app does → outcomes → local-first → install.

- Open `index.html` locally, or deploy via GitHub Pages (`.github/workflows/pages.yml`).
- Logo lives in [images/](images/) (copied from `docs/logo.png`).
- Footer version should match [pyproject.toml](../pyproject.toml) `version` (currently **0.9.0**).
- **0.x** is called out in the footer; stability story is [docs/start/releases.md](../docs/start/releases.md).
- Install snippet matches README: `docker compose build`, then `doctor`, then a dry-run.
  The image is build-local only (no `docker pull`, no PyPI). `uv` is the contributor path.
  Guide front door: `./guide/start/quickstart.html`.
- Docs CTAs point at the **Sphinx HTML guide** published beside this landing (`./guide/`), rebuilt from `docs/` on every qualifying `main` push. Paths: fill PDFs, quiet mirror, snowball.
- The sticky header nav is shared with `/guide/` via `website/chrome/` (Sphinx injects the same chrome).
- Full local preview (landing + guide): `uv sync --extra docs && make pages-site` then open `_site/index.html`.
- Ko-fi support link in footer: https://ko-fi.com/C0C1XK8G
