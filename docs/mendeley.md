# Mendeley

Paperful talks to **Mendeley Reference Manager** over the cloud REST API
(`https://api.mendeley.com`). There is no local API. Official behaviour below
is from [dev.mendeley.com](https://dev.mendeley.com/) fetched **2026-09-21**.
Lines marked **paperful** are client rules, not Elsevier’s.

**This adapter is seeking testers.** Zotero remains the well-tested path.
Do not treat a first Mendeley run as proven.

## Setup

1. Register an OAuth app at
   [dev.mendeley.com/myapps.html](https://dev.mendeley.com/myapps.html).
   New apps were still documented as open in 2026. Use the **authorization
   code** flow with redirect `http://127.0.0.1:8765/callback` and scope
   `all`.
2. Put the client id and secret in `config.toml` (never commit them):

   ```toml
   manager = "mendeley"
   [mendeley]
   client_id = "…"
   client_secret = "…"
   # redirect_uri = "http://127.0.0.1:8765/callback"
   ```

   Environment overrides: `PAPERFUL_MENDELEY_CLIENT_ID` /
   `PAPERFUL_MENDELEY_CLIENT_SECRET`.
3. On the **host** (not inside Docker): `uv run paperful session login mendeley`.
   Tokens land in `state/mendeley-oauth.json` (mode `0600`).
4. `uv run paperful doctor` should show **Mendeley API** green.

The official Python SDK is unmaintained. Paperful uses httpx.

## What the API actually does

| Topic | Behaviour |
| --- | --- |
| Auth | OAuth2 authorization code. Access tokens last **one hour**. Refresh tokens **rotate**. |
| Versioning | Every resource needs a vendor `Accept` header (`application/vnd.mendeley-document.1+json`, folder, file, annotation, profile). |
| Pagination | `Link: <url>; rel="next"`. Follow the URL; do not replay the original query string. |
| Folders | Nested via `parent_id`. Membership is `folder_uuids` on the document when present, else `GET /folders/{id}/documents`. |
| Files | `POST /files` with raw PDF bytes, `Content-Disposition`, and `Link: <…/documents/{id}>; rel="document"`. **Not** multipart. `GET /files/{id}` **303**s to object storage. Paperful fetches the `Location` **without** the Bearer token (S3 rejects a forwarded `Authorization` header). |
| Trash | `POST /documents/{id}/trash`. Not a DELETE of the catalogue row. |
| Notes | Document `notes` (HTML, `view=all`) is read as a child note tagged `mendeley-notes`. Paperful **writes** child notes as annotations (`type=note`) and prefixes `<!-- paperful-note:{tag} -->` so re-runs update instead of duplicate. |
| Collection notes | Mendeley has no standalone notes. `synthesize` creates a generic document in the folder and puts the HTML on an annotation. |

Duplicate file uploads return **400**; paperful treats that as unchanged.

## Paperful rules

- Item keys are UUIDs. `out/` folder names keep the hyphens.
- Folders map to collection paths. There is no Zotero-style `linked_url` PDF.
- `dedupe --apply` is refused. Mendeley cannot move a PDF or note onto the keeper.
- `attachments` reports filename drift and duplicate cloud files (same `filehash`, which Mendeley documents as MD5). `--fix-broken`, `--merge-files`, and `--rename` with `--apply` upload from `out/` and delete the extra cloud file. They do not trash the document. `--link` is refused: Mendeley has no linked-file mode. A document with no file row is a missing PDF (`run` / `attach`), not a ghost attachment.
- Docker: headed OAuth must run on the host so the localhost redirect hits the
  CLI. Do not put client secrets in the image.
- Moving a library: `snapshot --pdfs all` here, switch `manager`, then
  `restore --apply` or `import` on the other side. The hub is `out/`.

## Commands

```sh
uv run paperful session login mendeley
uv run paperful doctor
uv run paperful collections
uv run paperful export library.ris --library
uv run paperful import other.bib --apply
```
