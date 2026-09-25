# Documentation guide

The Markdown under `docs/` is the only docs corpus. Sphinx builds it into
`/guide/` on the hosted site (`make pages-site`). Marketing HTML lives in
`website/` and is assembled beside that guide.

## Sections (Diataxis)

| Folder | Role | Edit when… |
| --- | --- | --- |
| `docs/start/` | Prerequisites and product framing | Install story, why, 0.x promises |
| `docs/paths/` | Tutorials that end in a concrete result | A first-success journey changes |
| `docs/howto/` | Task-oriented operator recipes | A procedure changes |
| `docs/reference/` | CLI, config, source tables | Flags or keys change |
| `docs/explain/` | Architecture and comparison | Internals or positioning change |
| `docs/contribute/` | Roadmap and this guide | Contributor process changes |

Root [CONTRIBUTING.md](../../CONTRIBUTING.md) is the contributor setup page;
link to it from the guide, do not duplicate the full setup here.

## Stubs and redirects

Flat files at `docs/<name>.md` (for example `docs/zotero.md`) are **stubs**
marked `orphan: true`. They exist so CLI messages, CHANGELOG links, and old
bookmarks keep working, and they are not listed in the sidebar. Put new prose
only in the canonical folder path. When you move a page, update the stub to
point at the new file.

Hosted HTML for old names (`/guide/zotero.html`) is built from those stubs.

## Snippet convention

- Operator / path / howto pages: `docker compose run --rm paperful …`
- Contribute / tests / architecture internals: `uv run …`

## Build

```sh
uv sync --extra docs
make docs          # docs/_build/html
make pages-site    # website/ + guide → _site/
```

## Checklist for doc PRs

- Prefer fixing the canonical page; leave stubs thin.
- Keep path pages short; link howto/reference for depth.
- User-facing behaviour changes: note in [CHANGELOG.md](../../CHANGELOG.md)
  and [Releases](../start/releases.md) when 0.x vs 1.0 promises move.
